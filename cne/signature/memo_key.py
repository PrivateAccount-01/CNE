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
from typing import Any, Dict, List, Optional
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.signature.canonicalization import Canonicalizer


@dataclass(frozen=True)
class SystemVersions:
    model_version: str = "v1.5"
    tokenizer_version: str = "v1.0"
    runtime_version: str = "1.0.0"
    semantic_compiler_version: str = "1.0.0"
    policy_version: str = "1.0.0"
    knowledge_version: str = "1.0.0"
    schema_version: str = "1.0.0"


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
        for node in graph.nodes.values():
            if getattr(node, "op", None) == OpKind.OBSERVE:
                src = node.attributes.get("source")
                k = node.attributes.get("key")
                if k is not None:
                    input_data[f"{src}.{k}"] = str(k)
                elif src in env:
                    val = env[src]
                    if isinstance(val, list):
                        input_data[f"src:{src}:len"] = len(val)
                        if val:
                            h = val[0]
                            t = val[-1]
                            input_data[f"src:{src}:h"] = h.get("id", str(h)) if isinstance(h, dict) else str(h)
                            input_data[f"src:{src}:t"] = t.get("id", str(t)) if isinstance(t, dict) else str(t)
                    elif isinstance(val, dict):
                        input_data[f"src:{src}:klen"] = len(val)
                    else:
                        input_data[f"src:{src}"] = str(val)
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
        if descriptors is None:
            descriptors, _ = Canonicalizer.canonicalize_graph(graph)
            graph._cached_descriptors = descriptors

        contract_repr = None
        if contract is not None:
            contract_repr = {
                "t": getattr(getattr(contract, "contract_type", None), "name", str(contract)),
                "tol": sorted(getattr(contract, "tolerances", {}).items()),
                "b": getattr(contract, "decision_boundary", None),
                "f": sorted(list(getattr(contract, "required_facts", set()))),
                "s": getattr(contract, "output_schema", None)
            }

        if isinstance(input_data, dict):
            input_repr = {k: str(v) for k, v in sorted(input_data.items())}
        elif isinstance(input_data, list):
            input_repr = {f"idx_{i}": str(v) for i, v in enumerate(input_data[:10])}
            input_repr["_len"] = str(len(input_data))
        elif input_data is not None:
            input_repr = {"_val": str(input_data)}
        else:
            input_repr = {}

        memo_dict = {
            "v": f"{sys_ver.model_version}_{sys_ver.tokenizer_version}_{sys_ver.runtime_version}_{sys_ver.semantic_compiler_version}_{sys_ver.policy_version}_{sys_ver.knowledge_version}_{sys_ver.schema_version}",
            "d": descriptors,
            "i": input_repr,
            "s": {k: str(v) for k, v in sorted((dependency_snapshot or {}).items())},
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
