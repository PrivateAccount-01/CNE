"""
Module 2: Effect System Extreme Tests.
15 black-box tests verifying effects are sets (NEVER hierarchy),
execution policy derivation, and propagation safety invariants.
"""
import pytest
from cne.effects.effect_set import Effect, EffectSet
from cne.effects.execution_policy import Cacheability, ExecutionPolicy, Retryability
from cne.effects.propagation import EffectPropagator
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion


def test_all_4_effects_union():
    """Union of all 4 atomic effects retains all 4."""
    eff = EffectSet([Effect.ReadExternal, Effect.WriteExternal,
                     Effect.Nondeterministic, Effect.Interactive])
    assert len(eff) == 4
    assert Effect.ReadExternal in eff
    assert Effect.WriteExternal in eff
    assert Effect.Nondeterministic in eff
    assert Effect.Interactive in eff
    assert not eff.is_pure


def test_effect_set_immutability():
    """EffectSet uses frozenset — cannot be mutated after creation."""
    eff = EffectSet([Effect.ReadExternal])
    # The internal _effects is a frozenset
    assert isinstance(eff.effects, frozenset)
    # Cannot add to frozenset
    with pytest.raises(AttributeError):
        eff.effects.add(Effect.WriteExternal)


def test_effect_set_equality_and_hash():
    """Two identical EffectSets are equal and produce the same hash."""
    eff1 = EffectSet([Effect.ReadExternal, Effect.WriteExternal])
    eff2 = EffectSet([Effect.WriteExternal, Effect.ReadExternal])
    assert eff1 == eff2
    assert hash(eff1) == hash(eff2)
    # Can be used as dict key
    d = {eff1: "value"}
    assert d[eff2] == "value"


def test_pure_union_with_pure_stays_pure():
    """Pure ∪ Pure = Pure."""
    p1 = EffectSet.pure()
    p2 = EffectSet.pure()
    result = p1.union(p2)
    assert result.is_pure
    assert len(result) == 0


def test_execution_policy_interactive():
    """Interactive → NEVER cacheable, NEVER retryable."""
    eff = EffectSet([Effect.Interactive])
    pol = ExecutionPolicy.from_effect_set(eff)
    assert pol.cacheability == Cacheability.NEVER
    assert pol.retryability == Retryability.NEVER


def test_execution_policy_nondeterministic():
    """Nondeterministic → NEVER cacheable, POLICY_DEPENDENT retryable."""
    eff = EffectSet([Effect.Nondeterministic])
    pol = ExecutionPolicy.from_effect_set(eff)
    assert pol.cacheability == Cacheability.NEVER
    assert pol.retryability == Retryability.POLICY_DEPENDENT


def test_execution_policy_all_effects():
    """All 4 effects → most restrictive policy (NEVER/NEVER)."""
    eff = EffectSet([Effect.ReadExternal, Effect.WriteExternal,
                     Effect.Nondeterministic, Effect.Interactive])
    pol = ExecutionPolicy.from_effect_set(eff)
    assert pol.cacheability == Cacheability.NEVER
    assert pol.retryability == Retryability.NEVER


def test_propagation_linear_chain():
    """Effects propagate through a 10-node linear chain.
    First node is Observe (ReadExternal), all subsequent are pure Maps.
    All downstream nodes should inherit ReadExternal."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "s"})
    g.add_node(obs)
    prev = "obs"
    for i in range(9):
        nid = f"map_{i}"
        m = IRNode(id=nid, op=OpKind.MAP, inputs=[prev],
                   attributes={"fn": lambda x: x})
        g.add_node(m)
        prev = nid
    g.root_id = prev

    effects = EffectPropagator.compute_static_effects(g)
    for nid in g.nodes:
        assert Effect.ReadExternal in effects[nid]


def test_propagation_branch_unions_both_regions():
    """Static effect analysis: Branch statically unions ALL reachable regions."""
    g = SemanticIRGraph()
    cond = IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True})
    g.add_node(cond)

    # Then region: has ReadExternal
    then_reg = SemanticRegion(id="then_r")
    then_node = IRNode(id="tn", op=OpKind.OBSERVE,
                       attributes={"source": "table_a"})
    then_reg.add_node(then_node)
    then_reg.root_id = "tn"
    g.add_region(then_reg)

    # Else region: has WriteExternal
    else_reg = SemanticRegion(id="else_r")
    else_node = IRNode(id="en", op=OpKind.CALL,
                       declared_effects=EffectSet([Effect.WriteExternal]))
    else_reg.add_node(else_node)
    else_reg.root_id = "en"
    g.add_region(else_reg)

    br = IRNode(id="br", op=OpKind.BRANCH, inputs=["cond"],
                attributes={"then_region": "then_r", "else_region": "else_r"})
    g.add_node(br)
    g.root_id = "br"

    effects = EffectPropagator.compute_static_effects(g)
    assert Effect.ReadExternal in effects["br"]
    assert Effect.WriteExternal in effects["br"]


def test_propagation_iterate_unions_step_region():
    """Static effects: Iterate unions step_region effects."""
    g = SemanticIRGraph()
    items = IRNode(id="items", op=OpKind.LITERAL, attributes={"value": [1]})
    g.add_node(items)

    step_reg = SemanticRegion(id="step_r")
    step_obs = IRNode(id="s_obs", op=OpKind.OBSERVE,
                      attributes={"source": "external_api"})
    step_reg.add_node(step_obs)
    step_reg.root_id = "s_obs"
    g.add_region(step_reg)

    iterate = IRNode(id="iter", op=OpKind.ITERATE, inputs=["items"],
                     attributes={"step_region": "step_r", "init": 0})
    g.add_node(iterate)
    g.root_id = "iter"

    effects = EffectPropagator.compute_static_effects(g)
    assert Effect.ReadExternal in effects["iter"]


def test_runtime_effects_branch_only_taken():
    """Runtime effects only include the taken branch, not the other."""
    from cne.semantic_ir.evaluator import SemanticEvaluator
    g = SemanticIRGraph()
    cond = IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True})
    g.add_node(cond)

    then_reg = SemanticRegion(id="then_r")
    then_node = IRNode(id="tn", op=OpKind.OBSERVE,
                       attributes={"source": "table_a"})
    then_reg.add_node(then_node)
    then_reg.root_id = "tn"
    g.add_region(then_reg)

    else_reg = SemanticRegion(id="else_r")
    else_node = IRNode(id="en", op=OpKind.CALL,
                       declared_effects=EffectSet([Effect.WriteExternal]))
    else_reg.add_node(else_node)
    else_reg.root_id = "en"
    g.add_region(else_reg)

    br = IRNode(id="br", op=OpKind.BRANCH, inputs=["cond"],
                attributes={"then_region": "then_r", "else_region": "else_r"})
    g.add_node(br)
    g.root_id = "br"

    evaluator = SemanticEvaluator()
    _, ctx = evaluator.execute(g)
    # Runtime effects should include ReadExternal (from taken then_reg)
    # but NOT WriteExternal (from untaken else_reg)
    assert Effect.ReadExternal in ctx.runtime_effects
    assert Effect.WriteExternal not in ctx.runtime_effects


def test_propagation_empty_region():
    """Branch with an empty region — should not crash."""
    g = SemanticIRGraph()
    cond = IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True})
    g.add_node(cond)

    then_reg = SemanticRegion(id="then_r")
    g.add_region(then_reg)
    else_reg = SemanticRegion(id="else_r")
    g.add_region(else_reg)

    br = IRNode(id="br", op=OpKind.BRANCH, inputs=["cond"],
                attributes={"then_region": "then_r", "else_region": "else_r"})
    g.add_node(br)
    g.root_id = "br"

    effects = EffectPropagator.compute_static_effects(g)
    assert "br" in effects


def test_effect_set_duplicate_effects():
    """Creating EffectSet with duplicate effects — should deduplicate."""
    eff = EffectSet([Effect.ReadExternal, Effect.ReadExternal,
                     Effect.ReadExternal])
    assert len(eff) == 1
    assert Effect.ReadExternal in eff


def test_propagation_graph_no_regions():
    """Graph with no regions — propagation should still work."""
    g = SemanticIRGraph()
    obs = IRNode(id="obs", op=OpKind.OBSERVE, attributes={"source": "s"})
    g.add_node(obs)
    m = IRNode(id="m", op=OpKind.MAP, inputs=["obs"],
               attributes={"fn": lambda x: x})
    g.add_node(m)
    g.root_id = "m"
    effects = EffectPropagator.compute_static_effects(g)
    assert Effect.ReadExternal in effects["m"]
    assert effects["m"].is_pure is False
