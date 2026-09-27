"""
CNE Graph Canonicalization.
Sorts and canonicalizes nodes, edges, and types to produce invariant topological representations.
"""
from __future__ import annotations
import hashlib
import json
from typing import Any, Dict, List, Tuple
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion


_CALLABLE_CACHE: Dict[Tuple[Any, str], str] = {}


def callable_identity(fn: Any) -> str:
    """
    Computes a deterministic cryptographic fingerprint of a callable.
    Distinguishes structurally different lambdas and functions while producing
    identical identities for identical implementations.
    """
    if not callable(fn):
        return str(fn)
    code = getattr(fn, "__code__", None)
    qualname = getattr(fn, "__qualname__", getattr(fn, "__name__", "fn"))
    if code is not None:
        cache_key = (code, qualname)
        cached = _CALLABLE_CACHE.get(cache_key)
        if cached is not None:
            return cached

        module = getattr(fn, "__module__", "")
        # Include bytecode, constants, and referenced names
        sig = f"{module}.{qualname}:{code.co_code}:{code.co_consts}:{code.co_names}"
        digest = hashlib.sha256(sig.encode("utf-8")).hexdigest()[:12]
        res = f"{qualname}_{digest}"
        _CALLABLE_CACHE[cache_key] = res
        return res

    module = getattr(fn, "__module__", "")
    return f"{module}.{qualname}"


class Canonicalizer:
    @staticmethod
    def canonical_node_descriptor(node: IRNode, id_map: Dict[str, str]) -> Dict[str, Any]:
        """
        Builds a hardware-agnostic canonical descriptor for a node.
        Replaces local node IDs with topological canonical IDs.
        Preserves positional argument order unless explicitly marked commutative.
        """
        is_commutative = bool(node.attributes.get("commutative", False))
        if is_commutative:
            mapped_inputs = [id_map.get(inp, inp) for inp in sorted(node.inputs)]
        else:
            mapped_inputs = [id_map.get(inp, inp) for inp in node.inputs]

        # Extract structural attributes, filtering out wording-specific labels
        structural_attrs = {}
        for k in sorted(node.attributes.keys()):
            if k in ("name", "description", "raw_query", "label", "wording", "commutative"):
                continue  # Invariant to wording & metadata
            v = node.attributes[k]
            if callable(v):
                structural_attrs[k] = callable_identity(v)
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
