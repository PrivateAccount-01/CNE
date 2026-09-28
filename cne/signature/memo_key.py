"""
CNE Memo Key Projection.
Identifies reusable exact computation.
GENERAL INVARIANT: A memo key is valid ONLY when all output-determining
execution semantics are identical or contract-equivalent.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.signature.canonicalization import Canonicalizer, callable_identity


DEFAULT_VERSION_STRING = "v1.5_v1.0_1.0.0_1.0.0_1.0.0_1.0.0_1.0.0"


@dataclass(frozen=True)
class SystemVersions:
    model_version: str = "v1.5"
    tokenizer_version: str = "v1.0"
    runtime_version: str = "1.0.0"
    semantic_compiler_version: str = "1.0.0"
    policy_version: str = "1.0.0"
    knowledge_version: str = "1.0.0"
    schema_version: str = "1.0.0"

    @property
    def version_string(self) -> str:
        if (self.model_version == "v1.5" and
            self.tokenizer_version == "v1.0" and
            self.runtime_version == "1.0.0" and
            self.semantic_compiler_version == "1.0.0" and
            self.policy_version == "1.0.0" and
            self.knowledge_version == "1.0.0" and
            self.schema_version == "1.0.0"):
            return DEFAULT_VERSION_STRING
        return f"{self.model_version}_{self.tokenizer_version}_{self.runtime_version}_{self.semantic_compiler_version}_{self.policy_version}_{self.knowledge_version}_{self.schema_version}"


_DIGEST_CACHE: Dict[int, Tuple[int, str]] = {}


def clear_digest_cache() -> None:
    """Clears the input digest cache. Called on data mutations."""
    _DIGEST_CACHE.clear()


def compute_canonical_digest(val: Any) -> str:
    """
    Computes a canonical SHA-256 content digest of arbitrary input data.
    Uses an (id, len) cache for collections to ensure O(1) repeated access
    without re-serializing large datasets on recurring queries.
    """
    if val is None:
        return "none"
    if isinstance(val, (int, float, bool, str)):
        return str(val)

    val_id = id(val)
    val_len = len(val) if isinstance(val, (list, dict, tuple, set)) else 0
    if val_id in _DIGEST_CACHE:
        cached_len, cached_h = _DIGEST_CACHE[val_id]
        if cached_len == val_len:
            return cached_h

    serialized = json.dumps(val, sort_keys=True, default=str)
    h = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    _DIGEST_CACHE[val_id] = (val_len, h)
    return h


@dataclass(frozen=True)
class MemoKey:
    """
    Cryptographic identity of an exact computation, its parameters, inputs, and environment versions.
    """
    key_hash: str
    serialized_identity: str
    versions: SystemVersions = field(default_factory=SystemVersions)

    @classmethod
    def extract_input_data(cls, graph: SemanticIRGraph, env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not env:
            return {}
        input_data: Dict[str, Any] = {}
        if "inputs" in env and isinstance(env["inputs"], dict):
            input_data.update(env["inputs"])
        
        obs_nodes = getattr(graph, "_cached_observe_nodes", None)
        if obs_nodes is None:
            obs_nodes = [n for n in graph.nodes.values() if getattr(n, "op", None) == OpKind.OBSERVE]
            graph._cached_observe_nodes = obs_nodes

        for node in obs_nodes:
            src = node.attributes.get("source")
            k = node.attributes.get("key")
            src_obj = env.get(src) if env else None
            if k is not None:
                # Keyed observe: retrieve the actual observed value, not the key name!
                if isinstance(src_obj, dict):
                    observed_val = src_obj.get(k)
                elif isinstance(src_obj, (list, tuple)) and isinstance(k, int) and 0 <= k < len(src_obj):
                    observed_val = src_obj[k]
                else:
                    observed_val = None
                input_data[f"{src}.{k}"] = compute_canonical_digest(observed_val)
            elif src in env:
                input_data[f"src:{src}"] = compute_canonical_digest(src_obj)
        return input_data

    @classmethod
    def from_graph(
        cls,
        graph: SemanticIRGraph,
        input_data: Optional[Dict[str, Any]] = None,
        versions: Optional[SystemVersions] = None,
        dependency_snapshot: Optional[Dict[str, str]] = None,
        contract: Optional[Any] = None,
        env: Optional[Dict[str, Any]] = None
    ) -> MemoKey:
        sys_ver = versions or SystemVersions()
        if input_data is None and env is not None:
            input_data = cls.extract_input_data(graph, env)

        descriptors = getattr(graph, "_cached_descriptors", None)
        shape_hash = getattr(graph, "_cached_shape_hash", None)
        if descriptors is None or shape_hash is None:
            descriptors, _ = Canonicalizer.canonicalize_graph(graph)
            graph._cached_descriptors = descriptors
            shape_hash = hashlib.sha256(json.dumps(descriptors, sort_keys=True).encode("utf-8")).hexdigest()
            graph._cached_shape_hash = shape_hash

        contract_repr = getattr(contract, "contract_repr", None) if contract is not None else None
        if contract_repr is None and contract is not None:
            contract_repr = getattr(contract, "_cached_contract_repr", None)
            if contract_repr is None:
                constraints_repr = [
                    callable_identity(c) for c in getattr(contract, "constraints", [])
                ]
                equiv_fn = getattr(contract, "acceptable_equivalence", None)
                equiv_repr = callable_identity(equiv_fn) if equiv_fn else None
                prov_repr = sorted(getattr(contract, "provenance_requirements", {}).items()) if getattr(contract, "provenance_requirements", None) else None

                contract_repr = {
                    "t": getattr(getattr(contract, "contract_type", None), "name", str(contract)),
                    "tol": sorted(getattr(contract, "tolerances", {}).items()),
                    "b": getattr(contract, "decision_boundary", None),
                    "f": sorted(list(getattr(contract, "required_facts", set()))),
                    "s": getattr(contract, "output_schema", None),
                    "cst": constraints_repr,
                    "eq": equiv_repr,
                    "prov": prov_repr
                }
                try:
                    contract._cached_contract_repr = contract_repr
                except Exception:
                    pass

        if isinstance(input_data, dict):
            input_repr = {k: str(v) for k, v in sorted(input_data.items())}
        elif isinstance(input_data, list):
            input_repr = {f"idx_{i}": str(v) for i, v in enumerate(input_data[:10])}
            input_repr["_len"] = str(len(input_data))
        elif input_data is not None:
            input_repr = {"_val": str(input_data)}
        else:
            input_repr = {}

        v_str = sys_ver.version_string if hasattr(sys_ver, "version_string") else DEFAULT_VERSION_STRING
        memo_dict = {
            "v": v_str,
            "sh": shape_hash,
            "i": input_repr,
            "s": {k: str(v) for k, v in sorted(dependency_snapshot.items())} if dependency_snapshot else {},
            "c": contract_repr
        }

        serialized = json.dumps(memo_dict, sort_keys=True)
        key_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return cls(key_hash=key_hash, serialized_identity=serialized, versions=sys_ver)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MemoKey):
            return self.key_hash == other.key_hash
        return False

    def __hash__(self) -> int:
        return hash(self.key_hash)

    def __repr__(self) -> str:
        return f"MemoKey({self.key_hash[:16]})"
