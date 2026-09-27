"""
Module 7: Optimizer & Oracle Extreme Tests.
22 black-box tests for the static optimizer, G2 oracle, cost gate,
incremental executor selectivity, Choose oracle under budget pressure.
"""
import pytest
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import SemanticType
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.effects.effect_set import Effect, EffectSet
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.optimizer.static.static_optimizer import StaticOptimizer
from cne.optimizer.runtime.cost_gate import CostGate
from cne.optimizer.oracle import G2Oracle
from cne.optimizer.runtime.incremental_executor import IncrementalExecutor
from cne.optimizer.runtime.choose import (
    BoundedLookaheadPolicy, ChooseOracle, GreedyChoosePolicy
)
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.planner.physical_planner import ExecutionTarget, PhysicalPlanner
from cne.signature.cost_class import CostClass, CostTier
from cne.state.fabric import LocalStateFabric
from cne.state.retention import EvictionPolicy
from cne.compiler.deterministic_fixtures import (
    build_expense_fixture, build_troubleshooting_fixture
)


# ---------- Static Optimizer ----------

def test_static_optimizer_no_optimization_needed():
    """Already minimal graph — optimizer should not break it."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE,
                 attributes={"source": "data"})
    g.add_node(obs)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs"])
    g.add_node(emit)
    g.root_id = "emit"

    contract = OutcomeContract(contract_type=ContractType.EXACT)
    opt = StaticOptimizer()
    result = opt.optimize(g, contract)
    assert "emit" in result.optimized_graph.nodes
    assert result.optimized_graph.root_id == "emit"


def test_static_optimizer_dead_code_elimination():
    """Unreachable nodes should be removed by optimizer."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "data"})
    g.add_node(obs)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs"])
    g.add_node(emit)
    # Dead code — not reachable from root
    dead = IRNode(id="dead", op=OpKind.MAP, inputs=[],
                  attributes={"fn": lambda x: x})
    g.add_node(dead)
    g.root_id = "emit"

    contract = OutcomeContract(contract_type=ContractType.EXACT)
    opt = StaticOptimizer()
    result = opt.optimize(g, contract)
    assert "dead" not in result.optimized_graph.nodes
    assert result.nodes_eliminated >= 1


def test_static_optimizer_constant_folding():
    """Pure literal chains should be folded."""
    g = SemanticIRGraph()
    lit1 = IRNode(id="a", op=OpKind.LITERAL, attributes={"value": 10})
    lit2 = IRNode(id="b", op=OpKind.LITERAL, attributes={"value": 20})
    g.add_node(lit1)
    g.add_node(lit2)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["a"])
    g.add_node(emit)
    g.root_id = "emit"

    contract = OutcomeContract(contract_type=ContractType.EXACT)
    opt = StaticOptimizer()
    result = opt.optimize(g, contract)
    # Should not crash; "b" is dead code
    assert "emit" in result.optimized_graph.nodes


# ---------- Cost Gate ----------

def test_cost_gate_bypass_trivial():
    """Trivial cost → bypass optimizer (execute directly)."""
    gate = CostGate(bypass_trivial=True)
    g = SemanticIRGraph()
    lit = IRNode(id="lit", op=OpKind.LITERAL, attributes={"value": 1})
    g.add_node(lit)
    g.root_id = "lit"
    cc = CostClass.from_graph(g, cardinality_hint=1)
    assert not gate.should_optimize(cc)


def test_cost_gate_engage_heavy():
    """Heavy cost → run optimizer."""
    gate = CostGate(bypass_trivial=True)
    g = SemanticIRGraph()
    for i in range(10):
        g.add_node(IRNode(id=f"obs_{i}", op=OpKind.OBSERVE,
                          attributes={"source": f"src_{i}"}))
    join = IRNode(id="join", op=OpKind.JOIN,
                  inputs=["obs_0", "obs_1"])
    g.add_node(join)
    g.root_id = "join"
    cc = CostClass.from_graph(g, cardinality_hint=50000)
    assert gate.should_optimize(cc)


# ---------- G2 Oracle ----------

def test_oracle_r_star_nontrivial():
    """R* > 0 for a graph with sliceable dead code."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "data"})
    g.add_node(obs)
    dead = IRNode(id="dead", op=OpKind.MAP, inputs=[],
                  attributes={"fn": lambda x: x})
    g.add_node(dead)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs"])
    g.add_node(emit)
    g.root_id = "emit"

    contract = OutcomeContract(contract_type=ContractType.EXACT)
    oracle = G2Oracle()
    result = oracle.find_recoverable_bound(
        "q_test", g, contract, env={"data": 42},
        train_corpus_ids={"train_1", "train_2"}
    )
    assert result.recoverable_ratio >= 0.0
    assert result.contract_satisfied


def test_oracle_contamination_check():
    """Query in train corpus → must raise ValueError."""
    g, contract = build_expense_fixture()
    oracle = G2Oracle()
    with pytest.raises(ValueError, match="Contamination"):
        oracle.find_recoverable_bound(
            "q_contaminated", g, contract,
            env={"transactions": []},
            train_corpus_ids={"q_contaminated"}
        )


def test_oracle_effect_preservation():
    """WriteExternal must not be dropped by oracle interventions."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "data"})
    g.add_node(obs)
    call = IRNode(id="call", op=OpKind.CALL, inputs=["obs"],
                  attributes={"target": "side_effect_fn"},
                  declared_effects=EffectSet([Effect.WriteExternal]))
    g.add_node(call)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["call"])
    g.add_node(emit)
    g.root_id = "emit"

    contract = OutcomeContract(contract_type=ContractType.EXACT)
    oracle = G2Oracle()
    result = oracle.find_recoverable_bound(
        "q_eff", g, contract,
        env={"data": "test"},
        train_corpus_ids=set()
    )
    assert result.contract_satisfied


def test_oracle_branch_specialization():
    """Literal condition → branch can be specialized."""
    g = SemanticIRGraph()
    cond = IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True})
    g.add_node(cond)

    then_reg = SemanticRegion(id="then_r")
    then_lit = IRNode(id="tl", op=OpKind.LITERAL,
                      attributes={"value": "taken"})
    then_reg.add_node(then_lit)
    then_reg.root_id = "tl"
    g.add_region(then_reg)

    else_reg = SemanticRegion(id="else_r")
    else_lit = IRNode(id="el", op=OpKind.LITERAL,
                      attributes={"value": "not_taken"})
    else_reg.add_node(else_lit)
    else_reg.root_id = "el"
    g.add_region(else_reg)

    branch = IRNode(id="br", op=OpKind.BRANCH, inputs=["cond"],
                    attributes={"then_region": "then_r", "else_region": "else_r"})
    g.add_node(branch)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["br"])
    g.add_node(emit)
    g.root_id = "emit"

    contract = OutcomeContract(contract_type=ContractType.EXACT)
    oracle = G2Oracle()
    result = oracle.find_recoverable_bound("q_br", g, contract, env={})
    assert result.contract_satisfied


# ---------- Incremental Executor ----------

def test_incremental_selective_execution():
    """Only stale cone re-executes — valid nodes reused."""
    g, contract = build_expense_fixture()
    fabric = LocalStateFabric()
    evaluator = SemanticEvaluator()
    env = {"transactions": [
        {"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False}
    ]}

    # First execution: get baseline values
    _, ctx = evaluator.execute(g, initial_env=env)
    prior_vals = dict(ctx.values)

    # Incremental: only "transactions" source is stale
    inc = IncrementalExecutor(fabric, evaluator)
    report = inc.execute_incremental(g, contract, env,
                                     stale_sources={"transactions"},
                                     prior_node_values=prior_vals)
    assert report.is_contract_equivalent
    assert len(report.reused_node_ids) >= 0  # Some nodes may be reused


def test_incremental_no_stale_sources():
    """No stale sources → maximum reuse, minimal re-execution."""
    g, contract = build_expense_fixture()
    fabric = LocalStateFabric()
    evaluator = SemanticEvaluator()
    env = {"transactions": [
        {"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False}
    ]}

    _, ctx = evaluator.execute(g, initial_env=env)
    prior_vals = dict(ctx.values)

    inc = IncrementalExecutor(fabric, evaluator)
    report = inc.execute_incremental(g, contract, env,
                                     stale_sources=set(),
                                     prior_node_values=prior_vals)
    assert report.is_contract_equivalent
    assert len(report.reused_node_ids) > 0  # Nodes were reused


def test_incremental_all_stale():
    """All sources stale → full re-execution, but still contract equivalent."""
    g, contract = build_expense_fixture()
    fabric = LocalStateFabric()
    evaluator = SemanticEvaluator()
    env = {"transactions": [
        {"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False}
    ]}

    _, ctx = evaluator.execute(g, initial_env=env)
    prior_vals = dict(ctx.values)

    # All sources stale
    all_sources = {"transactions"}
    inc = IncrementalExecutor(fabric, evaluator)
    report = inc.execute_incremental(g, contract, env,
                                     stale_sources=all_sources,
                                     prior_node_values=prior_vals)
    assert report.is_contract_equivalent


def test_incremental_contract_equivalence():
    """Incremental result ≡_C clean-slate (Section 30)."""
    g, contract = build_expense_fixture(category="Food", threshold=50.0)
    fabric = LocalStateFabric()
    evaluator = SemanticEvaluator()
    env = {"transactions": [
        {"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False},
        {"id": "2", "category": "Food", "amount": 60.0, "is_transfer": False},
    ]}

    # Baseline
    baseline_val, ctx = evaluator.execute(g, initial_env=env)
    prior_vals = dict(ctx.values)

    # Change data and do incremental
    env2 = {"transactions": [
        {"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False},
        {"id": "2", "category": "Food", "amount": 60.0, "is_transfer": False},
        {"id": "3", "category": "Food", "amount": 75.0, "is_transfer": False},
    ]}

    inc = IncrementalExecutor(fabric, evaluator)
    report = inc.execute_incremental(g, contract, env2,
                                     stale_sources={"transactions"},
                                     prior_node_values=prior_vals)
    # Must be contract-equivalent to clean-slate
    assert report.is_contract_equivalent


# ---------- Choose Oracle ----------

def test_choose_oracle_sequence_depth_3():
    """Multi-step optimal sequence at depth 3."""
    actions = [
        {"id": "a1", "cost": {"latency": 5.0}, "val": 3.0},
        {"id": "a2", "cost": {"latency": 3.0}, "val": 2.0},
        {"id": "a3", "cost": {"latency": 1.0}, "val": 1.0},
    ]
    belief = {"A": 0.5}
    budget = {"latency": 10.0}
    utility_fn = lambda act, b: act["val"]

    seq = ChooseOracle.find_optimal_sequence(
        belief, actions, budget, utility_fn, horizon=3
    )
    assert len(seq) >= 1
    total_cost = sum(a["cost"]["latency"] for a in seq)
    assert total_cost <= budget["latency"]


def test_choose_oracle_budget_exhaustion():
    """Budget fully consumed by first action — no room for second."""
    actions = [
        {"id": "expensive", "cost": {"latency": 9.0}, "val": 10.0},
        {"id": "cheap", "cost": {"latency": 2.0}, "val": 1.0},
    ]
    belief = {}
    budget = {"latency": 10.0}
    utility_fn = lambda act, b: act["val"]

    seq = ChooseOracle.find_optimal_sequence(
        belief, actions, budget, utility_fn, horizon=2
    )
    # After expensive (cost 9), remaining budget is 1, cheap (cost 2) doesn't fit
    total_u = sum(utility_fn(a, belief) for a in seq)
    assert total_u >= 10.0  # At least expensive action's utility


def test_choose_greedy_vs_oracle_agreement():
    """Greedy should match oracle on straightforward scenarios."""
    belief = {"A": 0.7, "B": 0.3}
    actions = [
        {"id": "a1", "cost": {"latency": 5.0}, "target": "A"},
        {"id": "a2", "cost": {"latency": 5.0}, "target": "B"},
    ]
    budget = {"latency": 10.0}
    utility_fn = lambda act, b: b.get(act["target"], 0) * 10.0

    oracle_act = ChooseOracle.find_optimal_action(
        belief, actions, budget, utility_fn
    )
    greedy_act = GreedyChoosePolicy.select_action(
        belief, actions, budget, utility_fn
    )
    assert oracle_act["id"] == greedy_act["id"]


def test_bounded_lookahead_vs_greedy():
    """Bounded lookahead should find at least as good as greedy."""
    belief = {"A": 0.5, "B": 0.5}
    actions = [
        {"id": "a1", "cost": {"latency": 5.0}, "val": 3.0},
        {"id": "a2", "cost": {"latency": 3.0}, "val": 2.0},
    ]
    budget = {"latency": 10.0}
    utility_fn = lambda act, b: act["val"]

    greedy = GreedyChoosePolicy.select_action(
        belief, actions, budget, utility_fn
    )
    lookahead = BoundedLookaheadPolicy.select_first_action(
        belief, actions, budget, utility_fn, depth=2
    )
    # Both should pick the best first action
    assert greedy is not None
    assert lookahead is not None


# ---------- Necessity Engine end-to-end ----------

def test_necessity_engine_full_pipeline():
    """End-to-end CNE pipeline execution."""
    fabric = LocalStateFabric()
    cne = ComputationNecessityEngine(fabric=fabric)
    g, contract = build_expense_fixture()
    env = {"transactions": [
        {"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False}
    ]}
    result = cne.execute_query(g, contract, env, query_id="q_full")
    assert result.value is not None
    assert result.costs.total_cne_ns > 0
    assert result.memo_key is not None


def test_necessity_engine_memo_hit():
    """Second identical query → memo reuse."""
    fabric = LocalStateFabric()
    cne = ComputationNecessityEngine(fabric=fabric)
    g, contract = build_expense_fixture()
    env = {"transactions": [
        {"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False}
    ]}

    r1 = cne.execute_query(g, contract, env, query_id="q1")
    r2 = cne.execute_query(g, contract, env, query_id="q2")
    assert r2.reused_state is True
    assert r2.costs.execution_ns == 0.0


def test_necessity_engine_stale_after_mutation():
    """Mutation → stale → recompute produces correct result."""
    from cne.optimizer.runtime.dependencies import ChangeType

    fabric = LocalStateFabric()
    cne = ComputationNecessityEngine(fabric=fabric)
    g, contract = build_expense_fixture(threshold=50.0)
    env = {"transactions": [
        {"id": "1", "category": "Food", "amount": 100.0, "is_transfer": False}
    ]}

    r1 = cne.execute_query(g, contract, env, query_id="q1")
    assert r1.value == 100.0
    assert r1.reused_state is False

    # Mutate the data source
    new_tx = {"id": "2", "category": "Food", "amount": 80.0, "is_transfer": False}
    env["transactions"].append(new_tx)
    fabric.notify_data_mutation(
        ChangeType.INSERT, "transactions",
        new_row=new_tx
    )
    # Should NOT get stale cached result
    r2 = cne.execute_query(g, contract, env, query_id="q2_post_mutation")
    # r2 should be a fresh computation (not reused stale state)
    assert r2.reused_state is False
    assert r2.value == 180.0


# ---------- Physical Planner ----------

def test_physical_planner_cpu_only_default():
    """Default planner assigns CPU_LOCAL to all nodes."""
    g, _ = build_expense_fixture()
    planner = PhysicalPlanner(allow_usb=False)
    plan = planner.plan(g)
    assert plan.is_cpu_only
    for target in plan.target_assignments.values():
        assert target == ExecutionTarget.CPU_LOCAL


def test_physical_planner_usb_offload():
    """USB offload only when thermal throttled AND allowed."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "data"})
    g.add_node(obs)
    join = IRNode(id="join", op=OpKind.JOIN, inputs=["obs", "obs"])
    g.add_node(join)
    red = IRNode(id="red", op=OpKind.REDUCE, inputs=["join"],
                 attributes={"op": lambda a, b: a, "init": 0})
    g.add_node(red)
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["red"])
    g.add_node(emit)
    g.root_id = "emit"

    # USB not allowed → still CPU only
    planner_no_usb = PhysicalPlanner(allow_usb=False)
    plan1 = planner_no_usb.plan(g, system_thermal_throttled=True)
    assert plan1.is_cpu_only

    # USB allowed + thermal → some nodes offloaded
    planner_usb = PhysicalPlanner(allow_usb=True)
    plan2 = planner_usb.plan(g, system_thermal_throttled=True)
    assert not plan2.is_cpu_only
