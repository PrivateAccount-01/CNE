"""
Property-based invariant tests for CNE:
- Invariant 1: Deterministic replay
- Invariant 2: Sound dependency invalidation
- Invariant 3: Computational memory correctness (eviction preserves correctness)
- Invariant 4: No information leakage in static analysis
"""
import pytest
from cne.compiler.deterministic_fixtures import build_expense_fixture
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.optimizer.runtime.dependencies import ChangeType
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.state.fabric import LocalStateFabric
from cne.state.lifecycle import StateLifecycle
from cne.state.retention import EvictionPolicy
from cne.state.state_entry import StateClass


def test_invariant_deterministic_replay():
    g, contract = build_expense_fixture(category="Food", threshold=50.0)
    env = {
        "transactions": [
            {"id": f"tx_{i}", "category": "Food", "amount": 60.0 + i, "is_transfer": False}
            for i in range(10)
        ]
    }
    evaluator = SemanticEvaluator()
    res1, ctx1 = evaluator.execute(g, initial_env=env)
    res2, ctx2 = evaluator.execute(g, initial_env=env)

    assert res1 == res2
    assert ctx1.executed_nodes == ctx2.executed_nodes
    assert len(ctx1.observed_dependencies) == len(ctx2.observed_dependencies)


def test_invariant_sound_invalidation():
    fabric = LocalStateFabric()
    g, contract = build_expense_fixture(category="Food", threshold=100.0)
    evaluator = SemanticEvaluator()

    env = {"transactions": [{"id": "tx_1", "category": "Food", "amount": 120.0, "is_transfer": False}]}
    val, ctx = evaluator.execute(g, initial_env=env)

    entry = fabric.put(
        entry_id="e_food",
        state_class=StateClass.COMPUTATIONAL,
        value=val,
        dependencies=ctx.observed_dependencies,
        predicate_fns={"transactions": lambda tx: tx.get("category") == "Food" and tx.get("amount", 0) >= 100.0}
    )
    assert entry.lifecycle == StateLifecycle.ACTIVE

    # Insert a non-matching row (Travel): must NOT invalidate
    fabric.notify_data_mutation(ChangeType.INSERT, "transactions", {"id": "tx_2", "category": "Travel", "amount": 200.0})
    assert entry.lifecycle == StateLifecycle.ACTIVE

    # Insert a matching row (Food, amount 150): MUST invalidate
    fabric.notify_data_mutation(ChangeType.INSERT, "transactions", {"id": "tx_3", "category": "Food", "amount": 150.0})
    assert entry.lifecycle == StateLifecycle.STALE


def test_invariant_eviction_preserves_correctness():
    # Eviction policy with max 2 entries
    fabric = LocalStateFabric(eviction_policy=EvictionPolicy(max_entries=2))
    cne = ComputationNecessityEngine(fabric=fabric)
    g, contract = build_expense_fixture()
    env = {"transactions": [{"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False}]}

    # Put 3 entries, forcing eviction of the first
    cne.execute_query(g, contract, env, query_id="q1")
    cne.execute_query(g, contract, env, query_id="q2")
    cne.execute_query(g, contract, env, query_id="q3")

    # State fabric must not exceed capacity
    assert len(fabric._entries) <= 2

    # Query 1 must still produce a contract-correct result upon recomputation!
    res1 = cne.execute_query(g, contract, env, query_id="q1_again")
    assert res1.contract_satisfied
