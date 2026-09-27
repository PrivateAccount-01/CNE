"""
CNE Static Reachability Analysis.
Identifies nodes in the graph that can reach the Emit node or required effectful operations.
Unreachable nodes are eliminated.
"""
from __future__ import annotations
import copy
from typing import Dict, Set
from cne.effects.effect_set import Effect
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph


class ReachabilityAnalyzer:
    @classmethod
    def eliminate_unreachable(cls, graph: SemanticIRGraph) -> SemanticIRGraph:
        # Fast check: reachability from root
        reachable: Set[str] = set()

        def mark_backward(nid: str):
            if nid in reachable:
                return
            reachable.add(nid)
            node = graph.nodes.get(nid)
            if node:
                for inp in node.inputs:
                    mark_backward(inp)

        if graph.root_id and graph.root_id in graph.nodes:
            mark_backward(graph.root_id)

        for nid, node in graph.nodes.items():
            eff = node.get_immediate_effects()
            if Effect.WriteExternal in eff or Effect.Interactive in eff:
                mark_backward(nid)

        if len(reachable) == len(graph.nodes):
            return graph

        g = graph.clone()
        for nid in list(g.nodes.keys()):
            if nid not in reachable:
                del g.nodes[nid]
        return g
