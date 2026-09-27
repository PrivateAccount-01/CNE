"""
CNE Static Constant Folding and Partial Evaluation.
Evaluates pure nodes whose inputs are known constants at compile-time.
Replaces folded nodes with Literal nodes.
"""
from __future__ import annotations
import copy
from typing import Dict, Optional
from cne.effects.effect_set import EffectSet
from cne.effects.propagation import EffectPropagator
from cne.semantic_ir.evaluator import ExecutionContext, SemanticEvaluator
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph


class ConstantFolder:
    def __init__(self, evaluator: Optional[SemanticEvaluator] = None):
        self.evaluator = evaluator or SemanticEvaluator()

    def fold(self, graph: SemanticIRGraph) -> SemanticIRGraph:
        # Fast path: if no literals exist, no folding is possible
        if not any(n.op == OpKind.LITERAL for n in graph.nodes.values()):
            return graph

        g = graph.clone()
        static_effects = EffectPropagator.compute_static_effects(g)

        changed = True
        while changed:
            changed = False
            for nid in g.topological_order():
                node = g.nodes.get(nid)
                if not node or node.op in (OpKind.LITERAL, OpKind.EMIT, OpKind.BRANCH, OpKind.ITERATE, OpKind.OBSERVE):
                    continue

                # Check if node is pure according to static effect analysis
                eff = static_effects.get(nid, EffectSet.pure())
                if not eff.is_pure:
                    continue

                # Check if all inputs are Literals
                all_literal = True
                lit_values = []
                for inp_id in node.inputs:
                    inp_node = g.nodes.get(inp_id)
                    if not inp_node or inp_node.op != OpKind.LITERAL:
                        all_literal = False
                        break
                    lit_values.append(inp_node.attributes.get("value"))

                if all_literal and node.inputs:
                    sub_ctx = ExecutionContext()
                    for idx, inp_id in enumerate(node.inputs):
                        sub_ctx.values[inp_id] = lit_values[idx]

                    try:
                        computed_val = self.evaluator._evaluate_node(node, g, sub_ctx)
                        # Replace with Literal
                        g.nodes[nid] = IRNode(
                            id=nid,
                            op=OpKind.LITERAL,
                            attributes={"value": computed_val},
                            output_type=node.output_type
                        )
                        changed = True
                        break  # Re-evaluate topological order
                    except Exception:
                        pass

        return g
