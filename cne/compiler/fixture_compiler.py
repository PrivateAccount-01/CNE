"""
CNE Fixture Compiler.
Compiles structured task specifications / queries into typed Semantic IR graphs and Outcome Contracts.
Hardware-agnostic and deterministic.
"""
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
from cne.compiler.deterministic_fixtures import (
    build_expense_fixture,
    build_troubleshooting_fixture,
    build_scheduling_fixture
)
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import DependencyKey, SemanticType


class FixtureCompiler:
    """
    Compiles query descriptors into SemanticIRGraph instances.
    """
    @classmethod
    def compile_query(cls, query_spec: Dict[str, Any]) -> Tuple[SemanticIRGraph, OutcomeContract]:
        domain = query_spec.get("domain", "expense")

        if domain == "expense":
            category = query_spec.get("category", "Food")
            exclude_transfers = query_spec.get("exclude_transfers", True)
            threshold = float(query_spec.get("threshold", 100.0))
            g, contract = build_expense_fixture(
                category=category,
                exclude_transfers=exclude_transfers,
                threshold=threshold
            )

        elif domain == "troubleshooting":
            system_id = query_spec.get("system_id", "node_1")
            error_threshold = int(query_spec.get("error_threshold", 5))
            g, contract = build_troubleshooting_fixture(
                system_id=system_id,
                error_threshold=error_threshold
            )

        elif domain == "scheduling":
            user_id = query_spec.get("user_id", "alice")
            duration = int(query_spec.get("duration", 30))
            g, contract = build_scheduling_fixture(
                user_id=user_id,
                required_slot_duration=duration
            )

        elif domain == "simple_lookup":
            # Distinct topology: single Observe -> Emit
            g = SemanticIRGraph()
            obs = IRNode(
                id="obs_simple",
                op=OpKind.OBSERVE,
                attributes={"source": "system_info", "key": query_spec.get("key", "status")}
            )
            g.add_node(obs)
            emit = IRNode(id="emit_simple", op=OpKind.EMIT, inputs=["obs_simple"])
            g.add_node(emit)
            g.root_id = "emit_simple"
            contract = OutcomeContract(contract_type=ContractType.EXACT)

        elif domain == "multi_join_analytics":
            # Distinct topology: 2 Observers -> 2 Filters -> Join -> Map -> Reduce -> Emit
            g = SemanticIRGraph()
            obs1 = IRNode(id="obs_a", op=OpKind.OBSERVE, attributes={"source": "table_a"})
            obs2 = IRNode(id="obs_b", op=OpKind.OBSERVE, attributes={"source": "table_b"})
            g.add_node(obs1)
            g.add_node(obs2)
            f1 = IRNode(id="filt_a", op=OpKind.FILTER, inputs=["obs_a"], attributes={"predicate": lambda x: True})
            f2 = IRNode(id="filt_b", op=OpKind.FILTER, inputs=["obs_b"], attributes={"predicate": lambda x: True})
            g.add_node(f1)
            g.add_node(f2)
            jn = IRNode(id="join_ab", op=OpKind.JOIN, inputs=["filt_a", "filt_b"], attributes={"left_key": "id", "right_key": "a_id"})
            g.add_node(jn)
            mp = IRNode(id="map_ab", op=OpKind.MAP, inputs=["join_ab"], attributes={"fn": lambda x: x.get("val", 0)})
            g.add_node(mp)
            red = IRNode(id="red_ab", op=OpKind.REDUCE, inputs=["map_ab"], attributes={"op": lambda a, b: a + b, "init": 0})
            g.add_node(red)
            em = IRNode(id="emit_ab", op=OpKind.EMIT, inputs=["red_ab"])
            g.add_node(em)
            g.root_id = "emit_ab"
            contract = OutcomeContract(contract_type=ContractType.EXACT)
        else:
            raise ValueError(f"Unknown domain {domain}")

        # Attach static canonical shape hash from compiler phase (system.md §3.1, §10)
        from cne.signature.canonicalization import Canonicalizer
        import hashlib, json
        descriptors, _ = Canonicalizer.canonicalize_graph(g)
        g._cached_descriptors = descriptors
        g._cached_shape_hash = hashlib.sha256(json.dumps(descriptors, sort_keys=True).encode("utf-8")).hexdigest()

        # Attach compile-time execution policy (Doc #4)
        from cne.effects.effect_set import EffectSet
        from cne.effects.execution_policy import ExecutionPolicy
        from cne.effects.propagation import EffectPropagator
        static_effects = EffectPropagator.compute_static_effects(g)
        root_eff = static_effects.get(g.root_id) if g.root_id else EffectSet.pure()
        policy = ExecutionPolicy.from_effect_set(root_eff)
        g.metadata["execution_policy"] = policy
        g._cached_execution_policy = policy

        return g, contract
