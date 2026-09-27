"""
CNE Graph Canonicalization.
Sorts and canonicalizes nodes, edges, and types to produce invariant topological representations.
"""
from __future__ import annotations
import hashlib
import json
from typing import Any, Dict, List, Tuple
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion


class Canonicalizer:
    @staticmethod
    def canonical_node_descriptor(node: IRNode, id_map: Dict[str, str]) -> Dict[str, Any]:
        """
        Builds a hardware-agnostic canonical descriptor for a node.
        Replaces local node IDs with topological canonical IDs.
        """
        mapped_inputs = [id_map.get(inp, inp) for inp in sorted(node.inputs)]

        # Extract structural attributes, filtering out wording-specific labels
        structural_attrs = {}
        for k in sorted(node.attributes.keys()):
            if k in ("name", "description", "raw_query", "label", "wording"):
                continue  # Invariant to wording
            v = node.attributes[k]
            if callable(v):
                # Use qualitative name of function if available
                structural_attrs[k] = getattr(v, "__name__", "fn")
            elif isinstance(v, (int, float, bool, str)):
                structural_attrs[k] = v
            elif isinstance(v, (list, tuple)):
                structural_attrs[k] = list(v)
            elif isinstance(v, dict):
                structural_attrs[k] = {str(dk): str(dv) for dk, dv in sorted(v.items())}

        return {
            "op": node.op.value,
            "inputs": mapped_inputs,
            "output_type": node.output_type.name,
            "attributes": structural_attrs
        }

    @classmethod
    def canonicalize_graph(cls, graph: SemanticIRGraph) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        Computes canonical topological ordering and id mapping.
        """
        top_order = graph.topological_order()
        id_map = {orig_id: f"v_{i}" for i, orig_id in enumerate(top_order)}

        descriptors = []
        for orig_id in top_order:
            node = graph.nodes[orig_id]
            desc = cls.canonical_node_descriptor(node, id_map)
            desc["canonical_id"] = id_map[orig_id]
            descriptors.append(desc)

        return descriptors, id_map
