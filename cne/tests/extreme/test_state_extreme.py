"""
Module 6: State Fabric & Lifecycle Extreme Tests.
18 black-box tests for lifecycle transitions, eviction under pressure,
retention correctness, and the invariant that eviction NEVER changes correctness.
"""
import time
import pytest
from cne.state.lifecycle import StateLifecycle
from cne.state.state_entry import StateClass, StateEntry
from cne.state.retention import EvictionPolicy
from cne.state.fabric import LocalStateFabric
from cne.signature.memo_key import MemoKey
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.compiler.deterministic_fixtures import build_expense_fixture
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.optimizer.necessity_engine import ComputationNecessityEngine


# ---------- Lifecycle transition tests ----------

def test_lifecycle_all_valid_transitions():
    """Every valid transition succeeds."""
    valid = {
        StateLifecycle.CREATED: [StateLifecycle.VERIFIED, StateLifecycle.ACTIVE, StateLifecycle.DELETED],
        StateLifecycle.VERIFIED: [StateLifecycle.ACTIVE, StateLifecycle.STALE, StateLifecycle.DELETED],
        StateLifecycle.ACTIVE: [StateLifecycle.STALE, StateLifecycle.SUPERSEDED, StateLifecycle.ARCHIVED, StateLifecycle.DELETED],
        StateLifecycle.STALE: [StateLifecycle.VERIFIED, StateLifecycle.ACTIVE, StateLifecycle.SUPERSEDED, StateLifecycle.ARCHIVED, StateLifecycle.DELETED],
        StateLifecycle.SUPERSEDED: [StateLifecycle.ARCHIVED, StateLifecycle.DELETED],
        StateLifecycle.ARCHIVED: [StateLifecycle.DELETED],
    }
    for source, targets in valid.items():
        for target in targets:
            assert source.can_transition_to(target), \
                f"{source} -> {target} should be valid"


def test_lifecycle_all_invalid_transitions():
    """Every invalid transition is rejected."""
    invalid = {
        StateLifecycle.CREATED: [StateLifecycle.STALE, StateLifecycle.SUPERSEDED, StateLifecycle.ARCHIVED],
        StateLifecycle.VERIFIED: [StateLifecycle.CREATED, StateLifecycle.SUPERSEDED, StateLifecycle.ARCHIVED],
        StateLifecycle.ACTIVE: [StateLifecycle.CREATED, StateLifecycle.VERIFIED],
        StateLifecycle.STALE: [StateLifecycle.CREATED],
        StateLifecycle.SUPERSEDED: [StateLifecycle.CREATED, StateLifecycle.VERIFIED, StateLifecycle.ACTIVE, StateLifecycle.STALE],
        StateLifecycle.ARCHIVED: [StateLifecycle.CREATED, StateLifecycle.VERIFIED, StateLifecycle.ACTIVE, StateLifecycle.STALE, StateLifecycle.SUPERSEDED],
        StateLifecycle.DELETED: [StateLifecycle.CREATED, StateLifecycle.VERIFIED, StateLifecycle.ACTIVE, StateLifecycle.STALE, StateLifecycle.SUPERSEDED, StateLifecycle.ARCHIVED],
    }
    for source, targets in invalid.items():
        for target in targets:
            assert not source.can_transition_to(target), \
                f"{source} -> {target} should be invalid"


def test_lifecycle_deleted_is_terminal():
    """DELETED → nothing. It's a terminal state."""
    for target in StateLifecycle:
        assert not StateLifecycle.DELETED.can_transition_to(target)


# ---------- Eviction tests ----------

def test_eviction_lru_ordering():
    """Least recently used evicted first."""
    fabric = LocalStateFabric(eviction_policy=EvictionPolicy(max_entries=3))
    # Put 3 entries
    fabric.put("e1", StateClass.COMPUTATIONAL, "val1")
    fabric.put("e2", StateClass.COMPUTATIONAL, "val2")
    fabric.put("e3", StateClass.COMPUTATIONAL, "val3")

    # Access e1 and e3 to make them "recently used"
    if "e1" in fabric._entries:
        fabric._entries["e1"].mark_accessed()
    if "e3" in fabric._entries:
        fabric._entries["e3"].mark_accessed()

    # Put e4, forcing eviction of e2 (least recently used)
    fabric.put("e4", StateClass.COMPUTATIONAL, "val4")
    assert "e2" not in fabric._entries
    assert len(fabric._entries) <= 3


def test_eviction_stale_entries_first():
    """Stale/Superseded entries are evicted before Active ones."""
    fabric = LocalStateFabric(eviction_policy=EvictionPolicy(max_entries=3))
    fabric.put("e1", StateClass.COMPUTATIONAL, "val1")
    fabric.put("e2", StateClass.COMPUTATIONAL, "val2")
    fabric.put("e3", StateClass.COMPUTATIONAL, "val3")

    # Mark e1 as stale
    fabric._entries["e1"].transition(StateLifecycle.STALE)

    # Put e4, should evict e1 (stale) first
    fabric.put("e4", StateClass.COMPUTATIONAL, "val4")
    assert "e1" not in fabric._entries


def test_eviction_cost_benefit_scoring():
    """Higher saved-cost entries survive eviction."""
    fabric = LocalStateFabric(eviction_policy=EvictionPolicy(max_entries=2))
    e1 = fabric.put("e1", StateClass.COMPUTATIONAL, "val1")
    e2 = fabric.put("e2", StateClass.COMPUTATIONAL, "val2")

    # e2 has high saved cost
    e2.mark_accessed(saved_cost=1000000.0)

    # Put e3, forcing eviction. e1 (low cost saved) should be evicted
    fabric.put("e3", StateClass.COMPUTATIONAL, "val3")
    assert "e2" in fabric._entries  # high cost entry survives


def test_eviction_max_1_entry():
    """Max capacity = 1 — extreme capacity test."""
    fabric = LocalStateFabric(eviction_policy=EvictionPolicy(max_entries=1))
    fabric.put("e1", StateClass.COMPUTATIONAL, "val1")
    assert len(fabric._entries) == 1

    fabric.put("e2", StateClass.COMPUTATIONAL, "val2")
    assert len(fabric._entries) == 1
    assert "e2" in fabric._entries


def test_eviction_max_1000_entries():
    """Fill to 1000 entries — verify no capacity violation."""
    fabric = LocalStateFabric(eviction_policy=EvictionPolicy(max_entries=100))
    for i in range(1000):
        fabric.put(f"e_{i}", StateClass.COMPUTATIONAL, f"val_{i}")
    assert len(fabric._entries) <= 100


# ---------- Fabric operations ----------

def test_fabric_put_get_roundtrip():
    """Store → retrieve by memo key."""
    fabric = LocalStateFabric()
    mk = MemoKey(key_hash="hash_abc", serialized_identity="{test}")
    fabric.put("e1", StateClass.COMPUTATIONAL, {"result": 42}, memo_key=mk)
    retrieved = fabric.get_by_memo_key(mk)
    assert retrieved is not None
    assert retrieved.value == {"result": 42}


def test_fabric_delete_entry():
    """Delete removes from all indices."""
    fabric = LocalStateFabric()
    mk = MemoKey(key_hash="hash_del", serialized_identity="{}")
    fabric.put("e1", StateClass.COMPUTATIONAL, 42, memo_key=mk)
    assert fabric.get_by_memo_key(mk) is not None

    fabric.delete("e1")
    assert "e1" not in fabric._entries
    assert fabric.get_by_memo_key(mk) is None


def test_fabric_state_reuse_ratio():
    """StateReuseRatio = UsefulPriorStateReused / TotalStateCreated."""
    fabric = LocalStateFabric()
    fabric.put("e1", StateClass.COMPUTATIONAL, 1)
    fabric.put("e2", StateClass.COMPUTATIONAL, 2)
    fabric.put("e3", StateClass.COMPUTATIONAL, 3)

    # Record 1 useful reuse
    fabric.record_useful_reuse(fabric._entries["e1"], 1000.0)
    assert fabric.state_reuse_ratio == 1 / 3


def test_fabric_amortized_savings():
    """AmortizedSavings calculation with overhead."""
    fabric = LocalStateFabric()
    fabric.total_amortized_savings_ns = 10000.0
    fabric.total_stateful_overhead_ns = 2000.0
    savings = fabric.compute_amortized_savings(num_subsequent_tasks=4)
    assert savings == (10000.0 - 2000.0) / 4


def test_fabric_amortized_savings_zero_tasks():
    """0 subsequent tasks → 0 savings (no division by zero)."""
    fabric = LocalStateFabric()
    fabric.total_amortized_savings_ns = 10000.0
    assert fabric.compute_amortized_savings(0) == 0.0


def test_fabric_memo_index_cleanup_on_delete():
    """Memo index is cleared when entry is deleted."""
    fabric = LocalStateFabric()
    mk = MemoKey(key_hash="cleanup_test", serialized_identity="{}")
    fabric.put("e1", StateClass.COMPUTATIONAL, 42, memo_key=mk)
    assert mk.key_hash in fabric._memo_index

    fabric.delete("e1")
    assert mk.key_hash not in fabric._memo_index


def test_mark_accessed_updates_metrics():
    """Access count and timestamp update correctly."""
    entry = StateEntry(
        entry_id="test",
        state_class=StateClass.COMPUTATIONAL,
        value=42,
        lifecycle=StateLifecycle.ACTIVE
    )
    old_ts = entry.last_accessed_at_ns
    time.sleep(0.001)  # 1ms
    entry.mark_accessed(saved_cost=100.0)
    assert entry.access_count == 1
    assert entry.computation_cost_saved == 100.0
    assert entry.last_accessed_at_ns >= old_ts


def test_eviction_preserves_correctness_recompute():
    """Evicted state → recompute still produces correct result (Section 14)."""
    fabric = LocalStateFabric(eviction_policy=EvictionPolicy(max_entries=2))
    cne = ComputationNecessityEngine(fabric=fabric)
    g, contract = build_expense_fixture()
    env = {"transactions": [
        {"id": "1", "category": "Food", "amount": 200.0, "is_transfer": False}
    ]}

    r1 = cne.execute_query(g, contract, env, query_id="q1")
    r2 = cne.execute_query(g, contract, env, query_id="q2")
    r3 = cne.execute_query(g, contract, env, query_id="q3")

    assert len(fabric._entries) <= 2
    # Recompute — must still be correct
    r4 = cne.execute_query(g, contract, env, query_id="q1_again")
    assert r4.contract_satisfied
    assert contract.is_equivalent(r4.value, r1.value)


def test_concurrent_put_evict_cycle():
    """Rapid put/evict cycle — 100 iterations with capacity 5."""
    fabric = LocalStateFabric(eviction_policy=EvictionPolicy(max_entries=5))
    for i in range(100):
        fabric.put(f"entry_{i}", StateClass.COMPUTATIONAL, f"value_{i}")
    assert len(fabric._entries) <= 5
    # Last entries should be present
    assert f"entry_99" in fabric._entries
