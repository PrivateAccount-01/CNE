"""
CNE Local State Fabric.
Manages the four state classes (Working, Semantic, Computational, Archive),
lifecycle transitions, retention/eviction, provenance, and dependency-driven invalidation.
Calculates State Reuse Ratio and Amortized Computation Savings.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from cne.contracts.outcome_contract import OutcomeContract
from cne.optimizer.runtime.dependencies import ChangeType, DependencyManager
from cne.semantic_ir.types import DependencyKey
from cne.signature.memo_key import MemoKey
from cne.state.lifecycle import StateLifecycle
from cne.state.retention import EvictionPolicy
from cne.state.state_entry import StateClass, StateEntry


class LocalStateFabric:
    def __init__(self, eviction_policy: Optional[EvictionPolicy] = None):
        self._entries: Dict[str, StateEntry] = {}
        self._memo_index: Dict[str, str] = {}  # memo_key_hash -> entry_id
        self.dep_manager = DependencyManager()
        self.eviction_policy = eviction_policy or EvictionPolicy()

        # Metrics tracking
        self.total_state_created = 0
        self.useful_prior_state_reused = 0
        self.total_amortized_savings_ns = 0.0
        self.total_stateful_overhead_ns = 0.0

    def put(
        self,
        entry_id: str,
        state_class: StateClass,
        value: Any,
        memo_key: Optional[MemoKey] = None,
        contract: Optional[OutcomeContract] = None,
        dependencies: Optional[List[DependencyKey]] = None,
        predicate_fns: Optional[Dict[str, Callable[[Dict[str, Any]], bool]]] = None,
        provenance: Optional[Dict[str, Any]] = None
    ) -> StateEntry:
        # Check eviction if needed
        if len(self._entries) >= self.eviction_policy.max_entries:
            candidates = self.eviction_policy.select_eviction_candidates(
                self._entries, self.eviction_policy.max_entries - 1
            )
            for cid in candidates:
                self.delete(cid)

        # Record current dependency snapshot
        dep_snap = {}
        if dependencies:
            for dep in dependencies:
                dep_snap[dep.source] = self.dep_manager.get_source_version(dep.source)

        entry = StateEntry(
            entry_id=entry_id,
            state_class=state_class,
            value=value,
            lifecycle=StateLifecycle.ACTIVE,
            memo_key=memo_key,
            contract=contract,
            dependency_keys=dependencies or [],
            dependency_snapshot=dep_snap,
            provenance=provenance or {}
        )
        self._entries[entry_id] = entry
        self.total_state_created += 1

        if memo_key:
            self._memo_index[memo_key.key_hash] = entry_id

        # Register dependencies with DependencyManager
        if dependencies:
            for dep in dependencies:
                pred_fn = (predicate_fns or {}).get(dep.source)
                self.dep_manager.register_dependency(entry_id, dep, predicate_fn=pred_fn)

        return entry

    def is_entry_valid(self, entry: StateEntry) -> bool:
        """
        Sound validity check: active lifecycle and unviolated dependency snapshot.
        """
        if entry.lifecycle != StateLifecycle.ACTIVE:
            return False
        for dep in entry.dependency_keys:
            if dep.granularity in ("source", "table"):
                expected_ver = entry.dependency_snapshot.get(dep.source)
                if expected_ver is not None and self.dep_manager.get_source_version(dep.source) != expected_ver:
                    entry.transition(StateLifecycle.STALE)
                    return False
        return True

    def get_by_memo_key(self, memo_key: MemoKey) -> Optional[StateEntry]:
        """
        Retrieves active, non-stale computational state by memo key.
        Integrates dependency validity verification.
        """
        t0 = time.perf_counter_ns()
        entry_id = self._memo_index.get(memo_key.key_hash)
        if not entry_id:
            self.total_stateful_overhead_ns += (time.perf_counter_ns() - t0)
            return None

        entry = self._entries.get(entry_id)
        if not entry or not self.is_entry_valid(entry):
            self.total_stateful_overhead_ns += (time.perf_counter_ns() - t0)
            return None

        self.total_stateful_overhead_ns += (time.perf_counter_ns() - t0)
        return entry

    def record_useful_reuse(self, entry: StateEntry, baseline_cost_saved_ns: float) -> None:
        """
        Marks state as USEFULLY reused (actually avoided computation).
        """
        entry.mark_accessed(saved_cost=baseline_cost_saved_ns)
        self.useful_prior_state_reused += 1
        self.total_amortized_savings_ns += baseline_cost_saved_ns

    def notify_data_mutation(
        self,
        change_type: ChangeType,
        source: str,
        changed_row: Optional[Dict[str, Any]] = None,
        row_key: Optional[str] = None,
        old_row: Optional[Dict[str, Any]] = None,
        new_row: Optional[Dict[str, Any]] = None
    ) -> Set[str]:
        """
        Invalidates state entries whose fine or coarse dependencies match the mutation.
        Transitions affected entries to StateLifecycle.STALE.
        Supports sound P(old) OR P(new) update semantics.
        """
        t0 = time.perf_counter_ns()
        invalidated_ids = self.dep_manager.notify_change(
            change_type=change_type,
            source=source,
            changed_row=changed_row,
            row_key=row_key,
            old_row=old_row,
            new_row=new_row
        )

        for eid in invalidated_ids:
            if eid in self._entries:
                entry = self._entries[eid]
                entry.transition(StateLifecycle.STALE)

        self.total_stateful_overhead_ns += (time.perf_counter_ns() - t0)
        return invalidated_ids

    def delete(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            entry = self._entries[entry_id]
            entry.transition(StateLifecycle.DELETED)
            if entry.memo_key:
                self._memo_index.pop(entry.memo_key.key_hash, None)
            self.dep_manager.unregister_entry(entry_id)
            del self._entries[entry_id]
            return True
        return False

    @property
    def state_reuse_ratio(self) -> float:
        """
        StateReuseRatio = UsefulPriorStateReused / TotalStateCreated (Section 15)
        """
        if self.total_state_created == 0:
            return 0.0
        return self.useful_prior_state_reused / self.total_state_created

    def compute_amortized_savings(self, num_subsequent_tasks: int) -> float:
        """
        AmortizedSavings = (C_from_scratch - C_stateful) / N_subsequent_tasks (Section 16)
        """
        if num_subsequent_tasks <= 0:
            return 0.0
        net_savings = self.total_amortized_savings_ns - self.total_stateful_overhead_ns
        return net_savings / num_subsequent_tasks
