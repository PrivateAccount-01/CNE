"""
Module 4: Dependency & Invalidation Extreme Tests.
20 black-box tests for Section 13 — one of CNE's most important implementation areas.
Tests predicate subscriptions, range subscriptions, join-key invalidation,
and the critical requirement that newly inserted rows matching a predicate MUST invalidate.
"""
import pytest
from cne.optimizer.runtime.dependencies import (
    ChangeType, DependencyManager, PredicateSubscription
)
from cne.semantic_ir.types import DependencyKey
from cne.state.fabric import LocalStateFabric
from cne.state.lifecycle import StateLifecycle
from cne.state.state_entry import StateClass
from cne.signature.memo_key import MemoKey


# ---------- Predicate subscription tests (Section 13.2) ----------

def test_predicate_insert_matching_row():
    """CRITICAL: Insert matching row → MUST invalidate (Section 13.2)."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="transactions", granularity="predicate",
                            predicate_desc="category == Food")
    dm.register_dependency("entry_1", dep_key,
                           predicate_fn=lambda row: row.get("category") == "Food")
    result = dm.notify_change(ChangeType.INSERT, "transactions",
                              {"id": "tx_new", "category": "Food", "amount": 50})
    assert "entry_1" in result


def test_predicate_insert_nonmatching_row():
    """Insert non-matching row → MUST NOT invalidate."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="transactions", granularity="predicate",
                            predicate_desc="category == Food")
    dm.register_dependency("entry_1", dep_key,
                           predicate_fn=lambda row: row.get("category") == "Food")
    result = dm.notify_change(ChangeType.INSERT, "transactions",
                              {"id": "tx_new", "category": "Travel", "amount": 200})
    assert "entry_1" not in result


def test_predicate_delete_matching_row():
    """Delete matching row → MUST invalidate."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="transactions", granularity="predicate",
                            predicate_desc="category == Food")
    dm.register_dependency("entry_1", dep_key,
                           predicate_fn=lambda row: row.get("category") == "Food")
    result = dm.notify_change(ChangeType.DELETE, "transactions",
                              {"id": "tx_old", "category": "Food", "amount": 100})
    assert "entry_1" in result


def test_predicate_update_matching_to_nonmatching():
    """Update row to no longer match → MUST invalidate via P(old) matching."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="transactions", granularity="predicate",
                            predicate_desc="category == Food")
    dm.register_dependency("entry_1", dep_key,
                           predicate_fn=lambda row: row.get("category") == "Food")
    old_row = {"id": "tx_1", "category": "Food", "amount": 100}
    new_row = {"id": "tx_1", "category": "Travel", "amount": 100}
    result = dm.notify_change(ChangeType.UPDATE, "transactions",
                              old_row=old_row, new_row=new_row)
    assert "entry_1" in result

    # When neither old nor new row matches predicate, entry is preserved
    unmatched_old = {"id": "tx_2", "category": "Travel", "amount": 50}
    unmatched_new = {"id": "tx_2", "category": "Entertainment", "amount": 50}
    result2 = dm.notify_change(ChangeType.UPDATE, "transactions",
                               old_row=unmatched_old, new_row=unmatched_new)
    assert "entry_1" not in result2


def test_key_level_insert_same_key():
    """Key-level subscription for exact key — same key → invalidate."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="users", granularity="key", key="alice")
    dm.register_dependency("entry_1", dep_key)
    result = dm.notify_change(ChangeType.UPDATE, "users",
                              {"id": "alice", "name": "Alice Updated"},
                              row_key="alice")
    assert "entry_1" in result


def test_key_level_insert_different_key():
    """Key-level: different key → NO invalidation."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="users", granularity="key", key="alice")
    dm.register_dependency("entry_1", dep_key)
    result = dm.notify_change(ChangeType.UPDATE, "users",
                              {"id": "bob", "name": "Bob"},
                              row_key="bob")
    assert "entry_1" not in result


# ---------- Range subscription tests ----------

def test_range_insert_within_range():
    """Value within subscribed range → invalidate."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="prices", granularity="range",
                            field_name="amount", range_bounds=(50.0, 200.0))
    dm.register_dependency("entry_1", dep_key)
    result = dm.notify_change(ChangeType.INSERT, "prices",
                              {"id": "p1", "amount": 100.0})
    assert "entry_1" in result


def test_range_insert_outside_range():
    """Value outside range → NO invalidation."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="prices", granularity="range",
                            field_name="amount", range_bounds=(50.0, 200.0))
    dm.register_dependency("entry_1", dep_key)
    result = dm.notify_change(ChangeType.INSERT, "prices",
                              {"id": "p1", "amount": 300.0})
    assert "entry_1" not in result


def test_range_boundary_exact_min():
    """Value exactly at range minimum — should invalidate (inclusive)."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="prices", granularity="range",
                            field_name="amount", range_bounds=(50.0, 200.0))
    dm.register_dependency("entry_1", dep_key)
    result = dm.notify_change(ChangeType.INSERT, "prices",
                              {"id": "p1", "amount": 50.0})
    assert "entry_1" in result


def test_range_boundary_exact_max():
    """Value exactly at range maximum — should invalidate (inclusive)."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="prices", granularity="range",
                            field_name="amount", range_bounds=(50.0, 200.0))
    dm.register_dependency("entry_1", dep_key)
    result = dm.notify_change(ChangeType.INSERT, "prices",
                              {"id": "p1", "amount": 200.0})
    assert "entry_1" in result


# ---------- Join key tests ----------

def test_join_key_change():
    """Change to join key field → invalidate."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="orders", granularity="join",
                            key="products", field_name="product_id")
    dm.register_dependency("entry_1", dep_key)
    result = dm.notify_change(ChangeType.INSERT, "orders",
                              {"order_id": "o1", "product_id": "p42"})
    assert "entry_1" in result


# ---------- Source-level tests ----------

def test_source_level_any_change():
    """Source-level subscription → any change to that source invalidates."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="config", granularity="source")
    dm.register_dependency("entry_1", dep_key)
    result = dm.notify_change(ChangeType.UPDATE, "config",
                              {"key": "anything", "value": "something"})
    assert "entry_1" in result


# ---------- Multiple subscriptions ----------

def test_multiple_subscriptions_same_source():
    """Multiple entries subscribed to same source — all should be notified."""
    dm = DependencyManager()
    for i in range(5):
        dep_key = DependencyKey(source="shared_table", granularity="source")
        dm.register_dependency(f"entry_{i}", dep_key)
    result = dm.notify_change(ChangeType.INSERT, "shared_table",
                              {"id": "new_row"})
    for i in range(5):
        assert f"entry_{i}" in result


# ---------- Unregister cleanup ----------

def test_unregister_entry_cleanup():
    """After unregister, no more invalidations for that entry."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="data", granularity="source")
    dm.register_dependency("entry_1", dep_key)

    # Before unregister
    result1 = dm.notify_change(ChangeType.INSERT, "data", {"id": "row1"})
    assert "entry_1" in result1

    # Unregister
    dm.unregister_entry("entry_1")

    # After unregister
    result2 = dm.notify_change(ChangeType.INSERT, "data", {"id": "row2"})
    assert "entry_1" not in result2


# ---------- Predicate error handling ----------

def test_predicate_error_conservative_fallback():
    """Predicate throws → conservative invalidation (Section 13.2)."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="data", granularity="predicate",
                            predicate_desc="broken_predicate")

    def broken_pred(row):
        raise ValueError("Predicate evaluation error!")

    dm.register_dependency("entry_1", dep_key, predicate_fn=broken_pred)
    result = dm.notify_change(ChangeType.INSERT, "data",
                              {"id": "some_row"})
    # Conservative fallback: if predicate errors, entry MUST be invalidated
    assert "entry_1" in result


# ---------- Scale stress ----------

def test_100_concurrent_subscriptions():
    """100 simultaneous subscriptions — verify all fire correctly."""
    dm = DependencyManager()
    for i in range(100):
        dep_key = DependencyKey(source="bulk_source", granularity="predicate",
                                predicate_desc=f"pred_{i}")
        dm.register_dependency(f"e_{i}", dep_key,
                               predicate_fn=lambda row, idx=i: idx % 2 == 0)

    result = dm.notify_change(ChangeType.INSERT, "bulk_source",
                              {"id": "trigger"})
    # Even-indexed entries should be invalidated
    even_count = sum(1 for i in range(100) if f"e_{i}" in result and i % 2 == 0)
    assert even_count == 50


# ---------- State Fabric integration ----------

def test_cascade_invalidation_through_fabric():
    """State fabric transitions entries to STALE on data mutation."""
    fabric = LocalStateFabric()
    dep_key = DependencyKey(source="accounts", granularity="predicate",
                            predicate_desc="active accounts")
    entry = fabric.put(
        entry_id="cached_result",
        state_class=StateClass.COMPUTATIONAL,
        value={"total": 500},
        dependencies=[dep_key],
        predicate_fns={"accounts": lambda row: row.get("status") == "active"}
    )
    assert entry.lifecycle == StateLifecycle.ACTIVE

    fabric.notify_data_mutation(ChangeType.INSERT, "accounts",
                                {"id": "new_acct", "status": "active"})
    assert entry.lifecycle == StateLifecycle.STALE


def test_stale_entry_not_returned_by_memo():
    """Stale entry should NOT be returned by get_by_memo_key."""
    fabric = LocalStateFabric()
    mk = MemoKey(key_hash="test_hash_123", serialized_identity="{}")
    entry = fabric.put(
        entry_id="e1",
        state_class=StateClass.COMPUTATIONAL,
        value=42,
        memo_key=mk
    )
    assert fabric.get_by_memo_key(mk) is not None

    # Manually transition to STALE
    entry.transition(StateLifecycle.STALE)
    assert fabric.get_by_memo_key(mk) is None


def test_predicate_never_existed_row():
    """Row that never existed triggers predicate correctly (Section 13.2).
    A newly inserted row must trigger predicate evaluation even though
    the row did not exist when the computation was registered."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="inventory", granularity="predicate",
                            predicate_desc="quantity > 100")
    dm.register_dependency("entry_1", dep_key,
                           predicate_fn=lambda row: row.get("quantity", 0) > 100)

    # Insert a brand new row that satisfies the predicate
    result = dm.notify_change(ChangeType.INSERT, "inventory",
                              {"id": "new_item", "quantity": 150})
    assert "entry_1" in result


def test_field_granularity_mismatch():
    """Field-level subscription vs key-level change — interaction test."""
    dm = DependencyManager()
    dep_key = DependencyKey(source="users", granularity="field",
                            key="alice", field_name="email")
    dm.register_dependency("entry_1", dep_key)

    # Mutating matching key 'alice' and matching field 'email' -> MUST invalidate
    result_matched = dm.notify_change(
        ChangeType.UPDATE, "users",
        new_row={"id": "alice", "email": "new@example.com"},
        row_key="alice"
    )
    assert "entry_1" in result_matched

    # Mutating matching key 'alice' but different field 'age' -> MUST NOT invalidate
    result_unmatched_field = dm.notify_change(
        ChangeType.UPDATE, "users",
        new_row={"id": "alice", "age": 30},
        row_key="alice"
    )
    assert "entry_1" not in result_unmatched_field

    # Mutating different key 'bob' with 'email' -> MUST NOT invalidate
    result_unmatched_key = dm.notify_change(
        ChangeType.UPDATE, "users",
        new_row={"id": "bob", "email": "bob@example.com"},
        row_key="bob"
    )
    assert "entry_1" not in result_unmatched_key
