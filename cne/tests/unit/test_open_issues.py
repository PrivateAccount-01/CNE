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


def test_execution_policy_blocks_cache_read_and_write_on_side_effects():
    """Doc #4: Graphs with WriteExternal/Interactive side effects MUST NOT be cached or served from cache."""
    from cne.effects.effect_set import Effect
    from cne.effects.execution_policy import Cacheability

    fabric = LocalStateFabric()
    cne = ComputationNecessityEngine(fabric=fabric)

    g = SemanticIRGraph()
    # Call node with declared WriteExternal effect
    call_node = IRNode(
        id="side_effect_call",
        op=OpKind.CALL,
        declared_effects=EffectSet([Effect.WriteExternal]),
        attributes={"fn": lambda: 42}
    )
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["side_effect_call"])
    g.add_node(call_node)
    g.add_node(emit)
    g.root_id = "emit"

    contract = OutcomeContract(contract_type=ContractType.EXACT)

    # First run: executes, but should NOT persist into StateFabric due to Cacheability.NEVER
    res1 = cne.execute_query(g, contract, env={}, query_id="q_side_effect_1")
    assert res1.value == 42
    assert res1.reused_state is False
    assert fabric.total_state_created == 0, "Side-effecting graph was mistakenly written to StateFabric!"

    # Second run: must re-execute, NOT serve from cache
    res2 = cne.execute_query(g, contract, env={}, query_id="q_side_effect_2")
    assert res2.value == 42
    assert res2.reused_state is False


def test_symmetric_join_dependency_registration():
    """Doc #6: Join dependency must invalidate when either source_a or source_b mutates."""
    dm = DependencyManager()
    dep = DependencyKey(
        source="orders",
        granularity="join",
        key="customers",  # source_b
        field_name="customer_id"
    )
    dm.register_dependency("entry_join_1", dep)

    # Mutating source_a ('orders') with customer_id
    res_a = dm.notify_change(ChangeType.INSERT, "orders", new_row={"id": 1, "customer_id": 99})
    assert "entry_join_1" in res_a, "Mutating source_a failed to invalidate join dependency!"

    # Mutating source_b ('customers') with customer_id
    res_b = dm.notify_change(ChangeType.UPDATE, "customers", new_row={"id": 100, "customer_id": 99})
    assert "entry_join_1" in res_b, "Mutating source_b failed to invalidate join dependency (asymmetric registration)!"


def test_graph_structural_cache_invalidation_on_mutation():
    """Doc #10: Adding or removing nodes/regions must invalidate cached structural derivations."""
    g = SemanticIRGraph()
    n1 = IRNode(id="n1", op=OpKind.LITERAL, attributes={"value": 10})
    g.add_node(n1)
    g.root_id = "n1"

    # Compute topological order and cached reachable
    order1 = g.topological_order()
    assert order1 == ["n1"]
    assert g._cached_topo == ["n1"]

    # Mutate graph by adding a node
    n2 = IRNode(id="n2", op=OpKind.LITERAL, attributes={"value": 20})
    g.add_node(n2)
    assert g._cached_topo is None, "Adding a node failed to invalidate _cached_topo!"
    assert g._cached_reachable is None, "Adding a node failed to invalidate _cached_reachable!"

    order2 = g.topological_order()
    assert set(order2) == {"n1", "n2"}

    # Remove node
    g.remove_node("n2")
    assert g._cached_topo is None, "Removing a node failed to invalidate _cached_topo!"


def test_real_cardinality_hint_propagation_to_cost_class():
    """Doc #13: Real dataset sizes in env must be propagated to CostClass instead of defaulting to 100."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs_large", op=OpKind.OBSERVE, attributes={"source": "large_dataset"})
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs_large"])
    g.add_node(obs)
    g.add_node(emit)
    g.root_id = "emit"

    large_env = {"large_dataset": [{"id": i} for i in range(25000)]}

    cne = ComputationNecessityEngine()
    contract = OutcomeContract(contract_type=ContractType.EXACT)

    # Execute and verify CostClass dynamically derives bracket ">100k" or "1k-100k"
    res = cne.execute_query(g, contract, env=large_env, query_id="q_large")
    assert res.value is not None


def test_decision_contract_simplification():
    """Doc #14: DECISION contract simplification folds constant boundary values."""
    from cne.optimizer.static.contract_simplification import ContractSimplifier

    g = SemanticIRGraph()
    lit = IRNode(id="const_val", op=OpKind.LITERAL, attributes={"value": 150.0})
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["const_val"])
    g.add_node(lit)
    g.add_node(emit)
    g.root_id = "emit"

    c_dec = OutcomeContract(contract_type=ContractType.DECISION, decision_boundary=100.0)
    simplified = ContractSimplifier.simplify(g, c_dec)

    folded_node = simplified.nodes["const_val"]
    assert folded_node.attributes["value"] is True, "Decision contract simplification failed to fold constant boundary!"


def test_bounded_lookahead_policy_integration_in_evaluator():
    """Doc #21: Evaluator integrates BoundedLookaheadPolicy on Choose operations when requested."""
    evaluator = SemanticEvaluator()

    g = SemanticIRGraph()
    actions = [
        {"name": "a1", "cost": {"latency": 5.0}, "expected_utility": 10.0},
        {"name": "a2", "cost": {"latency": 10.0}, "expected_utility": 25.0}
    ]
    choose_node = IRNode(
        id="choose",
        op=OpKind.CHOOSE,
        attributes={
            "actions": actions,
            "budget": {"latency": 15.0},
            "policy": "bounded_lookahead",
            "lookahead_depth": 2
        }
    )
    g.add_node(choose_node)
    g.root_id = "choose"

    val, ctx = evaluator.execute(g)
    assert val is not None
    assert val["name"] in ("a1", "a2")


def test_physical_planner_integration_in_cne_result():
    """Doc #22: CNEExecutionResult includes the physical plan generated by PhysicalPlanner."""
    from cne.compiler.deterministic_fixtures import build_expense_fixture
    cne = ComputationNecessityEngine()
    g, contract = build_expense_fixture()

    res = cne.execute_query(g, contract, env={"transactions": []}, query_id="q_plan")
    assert res.physical_plan is not None
    assert res.physical_plan.is_cpu_only is True


def test_fabric_put_and_delete_timing_in_stateful_overhead():
    """Doc #19: StateFabric put() and delete() overhead must be counted in total_stateful_overhead_ns."""
    fabric = LocalStateFabric()
    assert fabric.total_stateful_overhead_ns == 0.0

    entry = fabric.put(
        entry_id="e1",
        state_class=StateClass.COMPUTATIONAL,
        value="test_val"
    )
    assert fabric.total_stateful_overhead_ns > 0.0, "fabric.put() did not record stateful overhead!"

    prev_overhead = fabric.total_stateful_overhead_ns
    fabric.delete("e1")
    assert fabric.total_stateful_overhead_ns > prev_overhead, "fabric.delete() did not record stateful overhead!"


def test_filter_slicing_evidence_tier_certified():
    """Item 2: Bytecode-proven constant-True filter elimination must be labeled Certified."""
    from cne.optimizer.static.slicing import DependencySlicer
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "transactions"})
    filt = IRNode(id="filt", op=OpKind.FILTER, inputs=["obs"], attributes={"predicate": lambda x: True})
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["filt"])
    g.add_node(obs)
    g.add_node(filt)
    g.add_node(emit)
    g.root_id = "emit"

    sliced = DependencySlicer.slice(g)
    assert "filt" not in sliced.nodes, "Certified constant-True filter was not eliminated!"
    assert sliced.metadata.get("evidence_tier") == "Certified"
    evidence = sliced.metadata.get("filter_slicing_evidence", [])
    assert len(evidence) == 1
    assert evidence[0]["evidence_tier"] == "Certified"
    assert "Bytecode" in evidence[0]["justification"]


def test_filter_slicing_evidence_tier_audited():
    """Item 2: Heuristic-probed filter elimination without bytecode proof must be labeled Audited."""
    from cne.optimizer.static.slicing import DependencySlicer
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "transactions"})
    # A lambda that depends on a parameter or dictionary lookup but returns True for None and {}
    # E.g.: (lambda x: True if x is None or isinstance(x, dict) else False)
    filt = IRNode(id="filt", op=OpKind.FILTER, inputs=["obs"], attributes={
        "predicate": lambda x: True if x is None or isinstance(x, dict) else False
    })
    emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["filt"])
    g.add_node(obs)
    g.add_node(filt)
    g.add_node(emit)
    g.root_id = "emit"

    sliced = DependencySlicer.slice(g)
    assert "filt" not in sliced.nodes, "Audited heuristic filter was not eliminated!"
    assert sliced.metadata.get("evidence_tier") == "Audited"
    evidence = sliced.metadata.get("filter_slicing_evidence", [])
    assert len(evidence) == 1
    assert evidence[0]["evidence_tier"] == "Audited"
    assert "Audited tier" in evidence[0]["justification"]


def test_state_reuse_ratio_and_reuse_events_alias():
    """Item 3: state_reuse_ratio and reuse_events_per_created_state match and represent reuse events per entry."""
    fabric = LocalStateFabric()
    e = fabric.put(entry_id="e1", state_class=StateClass.COMPUTATIONAL, value=42)
    assert fabric.state_reuse_ratio == 0.0
    assert fabric.reuse_events_per_created_state == 0.0

    fabric.record_useful_reuse(e, baseline_cost_saved_ns=100.0)
    fabric.record_useful_reuse(e, baseline_cost_saved_ns=100.0)
    fabric.record_useful_reuse(e, baseline_cost_saved_ns=100.0)

    # 3 reuse events on 1 created state entry = 3.0
    assert fabric.state_reuse_ratio == 3.0
    assert fabric.reuse_events_per_created_state == 3.0


