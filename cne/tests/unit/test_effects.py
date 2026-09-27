"""
Unit tests for CNE Effect System:
- EffectSet operations (sets, never severity hierarchy)
- Most restrictive execution policy
- Static vs runtime effect semantics on lazy Branch
"""
import pytest
from cne.effects.effect_set import Effect, EffectSet
from cne.effects.execution_policy import Cacheability, ExecutionPolicy, Retryability
from cne.effects.propagation import EffectPropagator
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion


def test_effect_set_is_not_hierarchy():
    # Retains both ReadExternal and WriteExternal
    eff = EffectSet([Effect.ReadExternal, Effect.WriteExternal])
    assert Effect.ReadExternal in eff
    assert Effect.WriteExternal in eff
    assert not eff.is_pure


def test_most_restrictive_execution_policy():
    # {ReadExternal, WriteExternal} -> Never cacheable, Idempotent-only retry
    eff = EffectSet([Effect.ReadExternal, Effect.WriteExternal])
    pol = ExecutionPolicy.from_effect_set(eff)
    assert pol.cacheability == Cacheability.NEVER
    assert pol.retryability == Retryability.IDEMPOTENT_ONLY

    # Pure -> Always cacheable, Always retryable
    pol_pure = ExecutionPolicy.from_effect_set(EffectSet.pure())
    assert pol_pure.cacheability == Cacheability.ALWAYS
    assert pol_pure.retryability == Retryability.ALWAYS


def test_static_vs_runtime_effects_on_branch():
    g = SemanticIRGraph()
    cond = IRNode(id="cond", op=OpKind.LITERAL, attributes={"value": True})
    g.add_node(cond)

    then_reg = SemanticRegion(id="then_reg")
    node_then = IRNode(id="then_node", op=OpKind.OBSERVE, attributes={"source": "table_a"})
    then_reg.add_node(node_then)
    then_reg.root_id = "then_node"
    g.add_region(then_reg)

    else_reg = SemanticRegion(id="else_reg")
    node_else = IRNode(id="else_node", op=OpKind.CALL, declared_effects=EffectSet([Effect.WriteExternal]))
    else_reg.add_node(node_else)
    else_reg.root_id = "else_node"
    g.add_region(else_reg)

    branch = IRNode(
        id="br",
        op=OpKind.BRANCH,
        inputs=["cond"],
        attributes={"then_region": "then_reg", "else_region": "else_reg"}
    )
    g.add_node(branch)
    g.root_id = "br"

    # Static effect analysis: conservative union of ALL reachable regions
    static_effects = EffectPropagator.compute_static_effects(g)
    br_static = static_effects["br"]
    assert Effect.ReadExternal in br_static
    assert Effect.WriteExternal in br_static
