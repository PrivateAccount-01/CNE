"""
Unit tests for the 10 P0 correctness defects:
1. MemoKey collision on different data (detects middle element change)
2. Keyed Observe value sensitivity (records observed value, not key name)
3. Positional argument order preservation in canonicalization
4. Callable identity distinguishing different lambdas
5. Contract identity folding constraints, acceptable_equivalence, and provenance
6. SemanticEvaluator dead-code reachability elimination
7. Memo-hit verification evaluating satisfies_constraints
8. JoinKeySubscription precision with active_keys
9. IncrementalExecutor authoritatively deriving stale sources from DependencyManager
10. Region-aware incremental execution preserving valid region nodes
"""
import pytest
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.effects.effect_set import EffectSet
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.optimizer.runtime.dependencies import ChangeType, DependencyManager
from cne.optimizer.runtime.incremental_executor import IncrementalExecutor
from cne.semantic_ir.evaluator import ExecutionContext, SemanticEvaluator
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import DependencyKey
from cne.signature.canonicalization import Canonicalizer, callable_identity
from cne.signature.memo_key import MemoKey
from cne.state.fabric import LocalStateFabric
from cne.state.state_entry import StateClass


def test_memo_key_detects_middle_element_change():
    """Issue #1: Two datasets differing in a middle element must produce distinct MemoKeys."""
    g = SemanticIRGraph()
    g.add_node(IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "transactions"}))
    g.root_id = "obs"

    env1 = {"transactions": [{"id": 1, "amount": 100}, {"id": 2, "amount": 200}, {"id": 3, "amount": 300}]}
    env2 = {"transactions": [{"id": 1, "amount": 100}, {"id": 2, "amount": 999999}, {"id": 3, "amount": 300}]}

    mk1 = MemoKey.from_graph(g, env=env1)
    mk2 = MemoKey.from_graph(g, env=env2)

    assert mk1 != mk2, "MemoKey collided on different datasets differing in middle element!"


def test_memo_key_keyed_observe_value_sensitivity():
    """Issue #1: Keyed observe must hash the observed value, not merely the key name."""
    g = SemanticIRGraph()
    g.add_node(IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "telemetry", "key": "node_1"}))
    g.root_id = "obs"

    env1 = {"telemetry": {"node_1": {"error_count": 0, "status": "ok"}}}
    env2 = {"telemetry": {"node_1": {"error_count": 5, "status": "degraded"}}}

    mk1 = MemoKey.from_graph(g, env=env1)
    mk2 = MemoKey.from_graph(g, env=env2)

    assert mk1 != mk2, "MemoKey failed to detect changed value in keyed observe!"


def test_positional_order_preservation():
    """Issue #4: Canonicalization must preserve positional argument order for non-commutative operations."""
    g1 = SemanticIRGraph()
    g1.add_node(IRNode(id="n1", op=OpKind.LITERAL, attributes={"value": 10}))
    g1.add_node(IRNode(id="n2", op=OpKind.LITERAL, attributes={"value": 2}))
    g1.add_node(IRNode(id="call", op=OpKind.CALL, inputs=["n1", "n2"], attributes={"fn": lambda a, b: a - b}))
    g1.root_id = "call"

    g2 = SemanticIRGraph()
    g2.add_node(IRNode(id="n1", op=OpKind.LITERAL, attributes={"value": 10}))
    g2.add_node(IRNode(id="n2", op=OpKind.LITERAL, attributes={"value": 2}))
    g2.add_node(IRNode(id="call", op=OpKind.CALL, inputs=["n2", "n1"], attributes={"fn": lambda a, b: a - b}))
    g2.root_id = "call"

    mk1 = MemoKey.from_graph(g1)
    mk2 = MemoKey.from_graph(g2)

    assert mk1 != mk2, "Canonicalization destroyed positional argument order!"


def test_callable_identity_distinguishes_lambdas():
    """Issue #5: Different lambdas must produce distinct callable identities and memo keys."""
    f1 = lambda x: x + 1
    f2 = lambda x: x * 2

    id1 = callable_identity(f1)
    id2 = callable_identity(f2)
    assert id1 != id2, f"Callable identities collided: {id1} vs {id2}"

    g1 = SemanticIRGraph()
    g1.add_node(IRNode(id="m", op=OpKind.MAP, attributes={"fn": f1}))
    g1.root_id = "m"

    g2 = SemanticIRGraph()
    g2.add_node(IRNode(id="m", op=OpKind.MAP, attributes={"fn": f2}))
    g2.root_id = "m"

    assert MemoKey.from_graph(g1) != MemoKey.from_graph(g2)


def test_contract_identity_distinguishes_callables_and_tolerances():
    """Issue #3: Contract constraints and equivalence functions must participate in MemoKey identity."""
    g = SemanticIRGraph()
    g.add_node(IRNode(id="lit", op=OpKind.LITERAL, attributes={"value": 42}))
    g.root_id = "lit"

    c_base = OutcomeContract(contract_type=ContractType.EXACT)
    c_constraint1 = OutcomeContract(contract_type=ContractType.EXACT, constraints=[lambda x: x > 0])
    c_constraint2 = OutcomeContract(contract_type=ContractType.EXACT, constraints=[lambda x: x > 100])
    c_equiv1 = OutcomeContract(contract_type=ContractType.EXACT, acceptable_equivalence=lambda a, b: True)
    c_equiv2 = OutcomeContract(contract_type=ContractType.EXACT, acceptable_equivalence=lambda a, b: False)

    mk_base = MemoKey.from_graph(g, contract=c_base)
    mk_c1 = MemoKey.from_graph(g, contract=c_constraint1)
    mk_c2 = MemoKey.from_graph(g, contract=c_constraint2)
    mk_eq1 = MemoKey.from_graph(g, contract=c_equiv1)
    mk_eq2 = MemoKey.from_graph(g, contract=c_equiv2)

    assert mk_base != mk_c1
    assert mk_c1 != mk_c2
    assert mk_eq1 != mk_eq2


def test_evaluator_skips_unreachable_dead_code():
    """Issue #6: SemanticEvaluator must skip dead nodes not reachable from root and lacking side effects."""
    g = SemanticIRGraph()
    # Reachable path
    g.add_node(IRNode(id="live", op=OpKind.LITERAL, attributes={"value": 100}))
    g.add_node(IRNode(id="emit", op=OpKind.EMIT, inputs=["live"]))
    g.root_id = "emit"

    # Dead node (unreachable, pure)
    def fail_if_called():
        raise RuntimeError("Dead code was executed!")

    g.add_node(IRNode(id="dead", op=OpKind.CALL, attributes={"fn": fail_if_called}, declared_effects=EffectSet.pure()))

    evaluator = SemanticEvaluator()
    val, ctx = evaluator.execute(g)
    assert val == 100
    assert "dead" not in ctx.executed_nodes
    assert "live" in ctx.executed_nodes


def test_memo_hit_verification_checks_constraints():
    """Issue #2: Memo-hit verification must check satisfies_constraints, not tautological self-comparison."""
    fabric = LocalStateFabric()
    cne = ComputationNecessityEngine(fabric=fabric)

    g = SemanticIRGraph()
    g.add_node(IRNode(id="lit", op=OpKind.LITERAL, attributes={"value": -5}))
    g.root_id = "lit"

    # Contract requires positive value
    contract_positive = OutcomeContract(
        contract_type=ContractType.EXACT,
        constraints=[lambda x: x > 0]
    )

    # First execution: fails constraint check
    res1 = cne.execute_query(g, contract_positive, {})
    assert not res1.contract_satisfied

    # Put a positive value manually with valid memo
    contract_valid = OutcomeContract(contract_type=ContractType.EXACT, constraints=[lambda x: x == 42])
    g_pos = SemanticIRGraph()
    g_pos.add_node(IRNode(id="lit", op=OpKind.LITERAL, attributes={"value": 42}))
    g_pos.root_id = "lit"

    res_ok = cne.execute_query(g_pos, contract_valid, {})
    assert res_ok.contract_satisfied

    # Second execution: hits memo, satisfies_constraints passes
    res_cached = cne.execute_query(g_pos, contract_valid, {})
    assert res_cached.reused_state
    assert res_cached.contract_satisfied


def test_join_invalidation_precision():
    """Issue #8: Join invalidation with active_keys must not invalidate on unrelated join key values."""
    dm = DependencyManager()
    dep_key = DependencyKey(
        source="users",
        granularity="join",
        key="orders",
        field_name="user_id",
        attributes={"active_keys": {"u_1", "u_2"}}
    )
    dm.register_dependency("entry_join_1", dep_key)

    # Mutation with matching key: must invalidate
    inv1 = dm.notify_change(ChangeType.INSERT, "users", new_row={"user_id": "u_1", "name": "Alice"})
    assert "entry_join_1" in inv1

    # Mutation with non-matching key: must NOT invalidate
    inv2 = dm.notify_change(ChangeType.INSERT, "users", new_row={"user_id": "u_999", "name": "Zoe"})
    assert "entry_join_1" not in inv2


def test_incremental_executor_derives_stale_sources_automatically():
    """Issue #9: IncrementalExecutor must derive stale sources from DependencyManager when not caller-supplied."""
    fabric = LocalStateFabric()
    executor = IncrementalExecutor(fabric=fabric)

    g = SemanticIRGraph()
    g.add_node(IRNode(id="obs_a", op=OpKind.OBSERVE, attributes={"source": "source_a"}))
    g.add_node(IRNode(id="obs_b", op=OpKind.OBSERVE, attributes={"source": "source_b"}))
    g.add_node(IRNode(id="combine", op=OpKind.CALL, inputs=["obs_a", "obs_b"], attributes={"fn": lambda a, b: f"{a}_{b}"}))
    g.root_id = "combine"

    prior_vals = {"obs_a": "val_a", "obs_b": "val_b", "combine": "val_a_val_b"}

    # Mutate source_a through fabric
    fabric.notify_data_mutation(ChangeType.UPDATE, "source_a", new_row={"id": 1})

    # Execute incremental WITHOUT supplying stale_sources
    report = executor.execute_incremental(
        graph=g,
        contract=OutcomeContract(contract_type=ContractType.EXACT),
        env={"source_a": "new_a", "source_b": "val_b"},
        prior_node_values=prior_vals
    )

    assert "obs_a" in report.executed_node_ids
    assert "obs_b" in report.reused_node_ids
    assert report.was_selective


def test_lazy_branch_region_selective_recompute():
    """Issue #7: In a Branch with sub-regions, untouched region nodes must be reused."""
    fabric = LocalStateFabric()
    executor = IncrementalExecutor(fabric=fabric)

    g = SemanticIRGraph()
    g.add_node(IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True}))

    # Then region with 2 nodes: one depends on source_a, one depends on source_b
    then_reg = SemanticRegion(id="then_reg", root_id="r_comb")
    r_node_a = IRNode(id="r_obs_a", op=OpKind.OBSERVE, attributes={"source": "source_a"})
    r_node_b = IRNode(id="r_obs_b", op=OpKind.OBSERVE, attributes={"source": "source_b"})
    r_comb = IRNode(id="r_comb", op=OpKind.CALL, inputs=["r_obs_a", "r_obs_b"], attributes={"fn": lambda a, b: a + b})

    then_reg.nodes = {"r_obs_a": r_node_a, "r_obs_b": r_node_b, "r_comb": r_comb}

    branch = IRNode(
        id="branch",
        op=OpKind.BRANCH,
        inputs=["cond"],
        attributes={"then_region": then_reg}
    )
    g.add_node(IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True}))
    g.add_node(branch)
    g.root_id = "branch"

    prior_vals = {
        "cond": True,
        "branch": 30,
        "r_obs_a": 10,
        "r_obs_b": 20,
        "r_comb": 30
    }

    # Stale source_a only
    fabric.notify_data_mutation(ChangeType.UPDATE, "source_a", new_row={"id": 1})

    report = executor.execute_incremental(
        graph=g,
        contract=OutcomeContract(contract_type=ContractType.EXACT),
        env={"source_a": 15, "source_b": 20},
        prior_node_values=prior_vals
    )

    # r_obs_b was untouched: reused!
    assert "r_obs_b" in report.reused_node_ids
    assert report.result == 35
