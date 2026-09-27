"""
CNE Effect Propagation.
Static conservative effect propagation and runtime effect accounting.
Strict invariant: Static optimization NEVER uses runtime path knowledge.
"""
from __future__ import annotations
from typing import Dict, Optional
from cne.effects.effect_set import EffectSet
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion


class EffectPropagator:
    @staticmethod
    def compute_static_effects(graph: SemanticIRGraph) -> Dict[str, EffectSet]:
        """
        Computes conservative static effect sets for all nodes in the graph.
        For Branch, statically unions all reachable regions.
        """
        effects: Dict[str, EffectSet] = {}
        order = graph.topological_order()

        for nid in order:
            node = graph.nodes[nid]
            eff = node.get_immediate_effects()

            # Union input effects
            for inp_id in node.inputs:
                if inp_id in effects:
                    eff = eff.union(effects[inp_id])

            # For Branch: statically union then and else regions
            if node.op == OpKind.BRANCH:
                then_reg_id = node.attributes.get("then_region")
                else_reg_id = node.attributes.get("else_region")
                if then_reg_id and then_reg_id in graph.regions:
                    reg = graph.regions[then_reg_id]
                    reg_effects = EffectPropagator.compute_region_static_effects(reg, effects)
                    eff = eff.union(reg_effects)
                if else_reg_id and else_reg_id in graph.regions:
                    reg = graph.regions[else_reg_id]
                    reg_effects = EffectPropagator.compute_region_static_effects(reg, effects)
                    eff = eff.union(reg_effects)

            # For Iterate: statically union step region
            elif node.op == OpKind.ITERATE:
                step_reg_id = node.attributes.get("step_region")
                if step_reg_id and step_reg_id in graph.regions:
                    reg = graph.regions[step_reg_id]
                    reg_effects = EffectPropagator.compute_region_static_effects(reg, effects)
                    eff = eff.union(reg_effects)

            effects[nid] = eff

        return effects

    @staticmethod
    def compute_region_static_effects(region: SemanticRegion, outer_effects: Dict[str, EffectSet]) -> EffectSet:
        """
        Conservative static effects for an inner region.
        """
        reg_effects: Dict[str, EffectSet] = {}
        visited = set()
        order = []

        def dfs(nid: str):
            if nid in visited:
                return
            visited.add(nid)
            node = region.nodes.get(nid)
            if node:
                for inp in node.inputs:
                    if inp in region.nodes:
                        dfs(inp)
                order.append(nid)

        for nid in region.nodes:
            dfs(nid)

        total_eff = EffectSet.pure()
        for nid in order:
            node = region.nodes[nid]
            eff = node.get_immediate_effects()
            for inp in node.inputs:
                if inp in reg_effects:
                    eff = eff.union(reg_effects[inp])
                elif inp in outer_effects:
                    eff = eff.union(outer_effects[inp])
            reg_effects[nid] = eff
            total_eff = total_eff.union(eff)

        return total_eff
