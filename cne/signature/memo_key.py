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
    def from_graph(
        cls,
        graph: SemanticIRGraph,
        input_data: Optional[Dict[str, Any]] = None,
        versions: Optional[SystemVersions] = None,
        dependency_snapshot: Optional[Dict[str, str]] = None
    ) -> MemoKey:
        sys_ver = versions or SystemVersions()
        cached_str = getattr(graph, "_cached_descriptors_str", None)
        if cached_str is None:
            descriptors, _ = Canonicalizer.canonicalize_graph(graph)
            cached_str = json.dumps(descriptors, sort_keys=True)
            graph._cached_descriptors_str = cached_str

        memo_dict = {
            "v": f"{sys_ver.model_version}_{sys_ver.tokenizer_version}_{sys_ver.runtime_version}_{sys_ver.semantic_compiler_version}",
            "d": cached_str,
            "i": {k: str(v) for k, v in sorted((input_data or {}).items())},
            "s": {k: str(v) for k, v in sorted((dependency_snapshot or {}).items())}
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
