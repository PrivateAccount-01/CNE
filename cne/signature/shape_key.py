"""
CNE Semantic Shape Key Projection.
Groups equivalent computational structures based on topology, control flow, and types.
Invariant to surface wording and literals.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List
from cne.semantic_ir.nodes import SemanticIRGraph
from cne.signature.canonicalization import Canonicalizer


@dataclass(frozen=True)
class SemanticShapeKey:
    """
    Hash and structural representation of the semantic shape.
    """
    key_hash: str
    structural_signature: str

    @classmethod
    def from_graph(cls, graph: SemanticIRGraph) -> SemanticShapeKey:
        cached = getattr(graph, "_cached_shape_key", None)
        if cached is not None:
            return cached

        descriptors, _ = Canonicalizer.canonicalize_graph(graph)

        # For shape key, we strip literal values so that wording and constant values don't split the shape
        shape_elements = []
        for d in descriptors:
            shape_elem = {
                "cid": d["canonical_id"],
                "op": d["op"],
                "inputs": d["inputs"],
                "type": d["output_type"]
            }
            # Include control structure attributes (regions, joins)
            attrs = d.get("attributes", {})
            for k in ("then_region", "else_region", "step_region", "granularity", "left_key", "right_key"):
                if k in attrs:
                    shape_elem[k] = attrs[k]
            shape_elements.append(shape_elem)

        # Also include region structures
        regions_desc = []
        for reg_id in sorted(graph.regions.keys()):
            reg = graph.regions[reg_id]
            reg_ops = [reg.nodes[n].op.value for n in sorted(reg.nodes.keys())]
            regions_desc.append({"rid": reg_id, "ops": reg_ops})

        full_repr = {
            "nodes": shape_elements,
            "regions": regions_desc
        }

        serialized = json.dumps(full_repr, sort_keys=True)
        key_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        res = cls(key_hash=key_hash, structural_signature=serialized)
        graph._cached_shape_key = res
        return res

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SemanticShapeKey):
            return self.key_hash == other.key_hash
        return False

    def __hash__(self) -> int:
        return hash(self.key_hash)

    def __repr__(self) -> str:
        return f"ShapeKey({self.key_hash})"
