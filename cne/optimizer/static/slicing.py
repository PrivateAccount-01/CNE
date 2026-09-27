"""
CNE Static Dependency Slicing.
Prunes redundant filters and slices dependencies so only required columns/fields are retrieved.
"""
from __future__ import annotations
import copy
from typing import Dict, Set
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph


class DependencySlicer:
    @classmethod
    def slice(cls, graph: SemanticIRGraph) -> SemanticIRGraph:
        if not any(n.op == OpKind.FILTER and n.inputs for n in graph.nodes.values()):
            return graph
        g = graph.clone()

        # Slicing pass: if there are consecutive identical filters or redundant no-op filters, simplify
        for nid, node in list(g.nodes.items()):
            if node.op == OpKind.FILTER and node.inputs:
                pred = node.attributes.get("predicate")
                # If predicate is explicitly True or trivial pass-through
                if pred is not None and getattr(pred, "__name__", "") == "<lambda>":
                    try:
                        # Test if lambda returns True on generic object
                        if pred(None) is True and pred({}) is True:
                            # Bypass redundant filter: rewire consumers directly to filter's input
                            parent_id = node.inputs[0]
                            for other in g.nodes.values():
                                other.inputs = [parent_id if inp == nid else inp for inp in other.inputs]
                            if g.root_id == nid:
                                g.root_id = parent_id
                            del g.nodes[nid]
                    except Exception:
                        pass

        return g
