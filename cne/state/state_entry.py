"""
CNE State Entry and State Classes.
Four state classes:
1. Working: session state, active buffers, KV-like state (short-lived)
2. Semantic: facts, entities, preferences (long-lived)
3. Computational: outputs, dependencies, proofs, bounds, cost history (long-lived, conditionally valid)
4. Archive: compressed provenance/audit history (cold/on-disk)
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set
from cne.contracts.outcome_contract import OutcomeContract
from cne.semantic_ir.types import DependencyKey
from cne.signature.memo_key import MemoKey
from cne.state.lifecycle import StateLifecycle


class StateClass(Enum):
    WORKING = "working"
    SEMANTIC = "semantic"
    COMPUTATIONAL = "computational"
    ARCHIVE = "archive"


@dataclass
class StateEntry:
    entry_id: str
    state_class: StateClass
    value: Any
    lifecycle: StateLifecycle = StateLifecycle.CREATED
    memo_key: Optional[MemoKey] = None
    contract: Optional[OutcomeContract] = None
    dependency_keys: List[DependencyKey] = field(default_factory=list)
    dependency_snapshot: Dict[str, int] = field(default_factory=dict)
    created_at_ns: int = field(default_factory=time.perf_counter_ns)
    last_accessed_at_ns: int = field(default_factory=time.perf_counter_ns)
    access_count: int = 0
    computation_cost_saved: float = 0.0
    provenance: Dict[str, Any] = field(default_factory=dict)

    def mark_accessed(self, saved_cost: float = 0.0) -> None:
        self.last_accessed_at_ns = time.perf_counter_ns()
        self.access_count += 1
        self.computation_cost_saved += saved_cost

    def transition(self, new_lifecycle: StateLifecycle) -> bool:
        if self.lifecycle.can_transition_to(new_lifecycle):
            self.lifecycle = new_lifecycle
            return True
        return False
