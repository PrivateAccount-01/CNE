"""
CNE Static Optimizer.
Executes the frozen 5-step static optimization pipeline:
1. Reachability
2. Constant folding
3. Static effect analysis (E_static)
4. Static dependency slicing
5. Exact contract simplification

CRITICAL SAFETY INVARIANT: Never leaks runtime path knowledge backward into static analysis!
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
from typing import Dict, Tuple
from cne.contracts.outcome_contract import OutcomeContract
from cne.effects.effect_set import EffectSet
from cne.effects.propagation import EffectPropagator
from cne.optimizer.static.contract_simplification import ContractSimplifier
from cne.optimizer.static.folding import ConstantFolder
from cne.optimizer.static.reachability import ReachabilityAnalyzer
from cne.optimizer.static.slicing import DependencySlicer
from cne.semantic_ir.nodes import SemanticIRGraph


@dataclass
class StaticOptimizationResult:
    optimized_graph: SemanticIRGraph
    static_effects: Dict[str, EffectSet]
    nodes_eliminated: int
    nodes_folded: int
    evidence_tier: str = "Certified"
    contract_repr: str = ""


class StaticOptimizer:
    def __init__(self):
        self.folder = ConstantFolder()

    def optimize(self, graph: SemanticIRGraph, contract: OutcomeContract) -> StaticOptimizationResult:
        initial_node_count = len(graph.nodes)

        # Step 1: Reachability
        g1 = ReachabilityAnalyzer.eliminate_unreachable(graph)

        # Step 2: Constant folding
        g2 = self.folder.fold(g1)
        folded_count = sum(1 for n in g2.nodes.values() if n.op.value == "Literal" and graph.nodes.get(n.id) and graph.nodes[n.id].op.value != "Literal")

        # Step 3: Static effect analysis (uses E_static, union of all reachable regions)
        static_effects = EffectPropagator.compute_static_effects(g2)

        # Step 4: Static dependency slicing
        g3 = DependencySlicer.slice(g2)

        # Step 5: Exact contract simplification
        g_final = ContractSimplifier.simplify(g3, contract)

        eliminated_count = max(0, initial_node_count - len(g_final.nodes))
        evidence_tier = g_final.metadata.get("evidence_tier", "Certified")
        g_final._cached_reachable = set(g_final.nodes.keys())
        g_final._cached_executable_order = g_final.topological_order()

        return StaticOptimizationResult(
            optimized_graph=g_final,
            static_effects=static_effects,
            nodes_eliminated=eliminated_count,
            nodes_folded=folded_count,
            evidence_tier=evidence_tier,
            contract_repr=getattr(contract, "contract_repr", "")
        )
