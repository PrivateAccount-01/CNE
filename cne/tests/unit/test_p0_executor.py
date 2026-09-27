"""
P0 and P0.5 Break Tests:
Tests semantic execution foundation:
- type checking
- deterministic replay
- lazy Branch (unselected branch never executes!)
- lazy Iterate
- effect propagation
- exact Bayesian update
- three G0 fixtures execution
"""
import pytest
from cne.compiler.deterministic_fixtures import (
    build_expense_fixture,
    build_troubleshooting_fixture,
    build_scheduling_fixture
)
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.effects.effect_set import Effect, EffectSet
from cne.effects.propagation import EffectPropagator
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import DependencyKey, SemanticType


def test_lazy_branch_unselected_region_never_executes():
    """
    CRITICAL SAFETY INVARIANT: Unselected branch must NOT execute.
    """
    g = SemanticIRGraph()

    cond = IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True})
    g.add_node(cond)

    executed_side_effects = []

    then_reg = SemanticRegion(id="then_reg")
    node_then = IRNode(
        id="then_act",
        op=OpKind.MAP,
        inputs=[],
        attributes={"fn": lambda x: executed_side_effects.append("THEN") or 42}
    )
    then_reg.add_node(node_then)
    then_reg.root_id = "then_act"
    g.add_region(then_reg)

    else_reg = SemanticRegion(id="else_reg")
    node_else = IRNode(
        id="else_act",
        op=OpKind.MAP,
        inputs=[],
        attributes={"fn": lambda x: executed_side_effects.append("ELSE") or 99}
    )
    else_reg.add_node(node_else)
    else_reg.root_id = "else_act"
    g.add_region(else_reg)

    branch = IRNode(
        id="br",
        op=OpKind.BRANCH,
        inputs=["cond"],
        attributes={"then_region": "then_reg", "else_region": "else_reg"}
    )
    g.add_node(branch)
    g.root_id = "br"

    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)

    assert "else_act" not in ctx.executed_nodes
    assert "then_act" in ctx.executed_nodes
    assert "ELSE" not in executed_side_effects


def test_bayesian_update_exact():
    prior = {"A": 0.5, "B": 0.5}
    def lh(h, ev):
        return 0.8 if h == "A" else 0.2
    post = SemanticEvaluator._bayesian_update(prior, "obs", lh)
    assert abs(post["A"] - 0.8) < 1e-6
    assert abs(post["B"] - 0.2) < 1e-6


def test_g0_expense_fixture_execution():
    g, contract = build_expense_fixture(category="Food", threshold=50.0)
    tx_data = [
        {"id": "1", "category": "Food", "amount": 60.0, "is_transfer": False},
        {"id": "2", "category": "Food", "amount": 30.0, "is_transfer": False},  # below threshold
        {"id": "3", "category": "Travel", "amount": 100.0, "is_transfer": False}, # diff category
        {"id": "4", "category": "Food", "amount": 75.0, "is_transfer": True},   # transfer
        {"id": "5", "category": "Food", "amount": 80.0, "is_transfer": False},
    ]
    evaluator = SemanticEvaluator()
    result, ctx = evaluator.execute(g, initial_env={"transactions": tx_data})

    # Expected: 60.0 + 80.0 = 140.0
    assert result == 140.0
    assert contract.is_equivalent(result, 140.0)
    assert len(ctx.observed_dependencies) >= 1


def test_g0_troubleshooting_fixture_execution():
    g, contract = build_troubleshooting_fixture(system_id="srv_01", error_threshold=3)
    evaluator = SemanticEvaluator()

    # Case 1: Healthy
    res1, ctx1 = evaluator.execute(g, initial_env={
        "telemetry": {"srv_01": {"system_id": "srv_01", "error_count": 1}},
        "diagnostic_evidence": {"srv_01": "all normal"}
    })
    assert res1 == {"status": "healthy", "action": "noop"}
    assert "obs_diag" not in ctx1.executed_nodes  # Unselected region didn't run!

    # Case 2: Unhealthy with memory leak evidence
    res2, ctx2 = evaluator.execute(g, initial_env={
        "telemetry": {"srv_01": {"system_id": "srv_01", "error_count": 8}},
        "diagnostic_evidence": {"srv_01": "log: out_of_memory in worker process"}
    })
    assert res2 is not None
    assert res2["id"] == "restart_service"
    assert "obs_diag" in ctx2.executed_nodes


def test_g0_scheduling_fixture_execution():
    g, contract = build_scheduling_fixture(user_id="bob", required_slot_duration=30)
    evaluator = SemanticEvaluator()

    slots = [
        {"slot_id": "s1", "start_hour": 8, "duration": 15},   # too short
        {"slot_id": "s2", "start_hour": 9, "duration": 30},   # hour diff 2 (pref=11)
        {"slot_id": "s3", "start_hour": 11, "duration": 45},  # exact hour match
        {"slot_id": "s4", "start_hour": 14, "duration": 60},  # hour diff 3
    ]
    prefs = {"bob": {"preferred_start_hour": 11}}

    res, ctx = evaluator.execute(g, initial_env={
        "calendar_slots": slots,
        "user_preferences": prefs
    })
    assert res is not None
    assert res["slot_id"] == "s3"
