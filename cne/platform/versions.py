"""Only dependencies explicitly used by an execution belong in its cache identity."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, replace
import hashlib
import json
from cne.signature.memo_key import SystemVersions


@dataclass(frozen=True)
class ExecutionSemanticVersionVector:
    capabilities: tuple = ()
    models: tuple = ()
    adapters: tuple = ()
    tools: tuple = ()
    knowledge: tuple = ()
    semantic_compiler_version: str = "dsl-2"
    policy_version: str = "permissions-2"

    def model_identity_map(self):
        """Return stable structured model identities while accepting legacy pairs."""
        result = {}
        for identity in self.models:
            if len(identity) == 2:
                model_id, version = identity
                asset_sha256 = None
            elif len(identity) == 3:
                model_id, version, asset_sha256 = identity
            else:
                raise ValueError("Model dependency identity must have 2 or 3 fields")
            if model_id in result:
                raise ValueError(f"Duplicate model dependency: {model_id}")
            result[model_id] = {"version": version, "asset_sha256": asset_sha256}
        return result

    def model_ids(self):
        return list(self.model_identity_map())

    def digest(self):
        data = asdict(self)
        for key in ("capabilities", "models", "adapters", "tools", "knowledge"):
            data[key] = sorted(data[key])
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def system_versions(self):
        return SystemVersions(
            capability_vector_hash=self.digest(),
            semantic_compiler_version=self.semantic_compiler_version,
            policy_version=self.policy_version,
        )

    @classmethod
    def for_execution(
        cls, registry, capability_ids, tool_ids=(), models=(), adapters=(), knowledge=()
    ):
        caps, tools = [], []
        remaining = set(tool_ids)
        for cid in sorted(set(capability_ids)):
            pack = registry.get_pack(cid)
            if pack is None or not pack.is_enabled():
                raise ValueError(f"Inactive execution dependency: {cid}")
            # Hash the execution manifest projection: unused tool declarations are
            # package provenance, not execution dependencies. The complete manifest
            # remains integrity-verified at installation.
            projected = replace(
                pack.manifest,
                deterministic_tools=[
                    t
                    for t in pack.manifest.deterministic_tools
                    if t.tool_id in tool_ids
                ],
            )
            caps.append((cid, pack.version, projected.compute_manifest_hash()))
            for tool in pack.manifest.deterministic_tools:
                if tool.tool_id in remaining:
                    tools.append((tool.tool_id, tool.schema_version))
                    remaining.remove(tool.tool_id)
        if remaining:
            raise ValueError(f"Undeclared tools: {sorted(remaining)}")
        return cls(
            tuple(caps), tuple(models), tuple(adapters), tuple(tools), tuple(knowledge)
        )
