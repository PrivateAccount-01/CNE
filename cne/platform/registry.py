"""
CNE Capability Registry & Lifecycle Manager.
Tracks, resolves, and manages installable capability packs with atomic state transitions.
"""
from __future__ import annotations

import logging
import json
import sqlite3
from dataclasses import asdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from cne.platform.manifest import CapabilityManifest, CapabilityVersion, Permission
from cne.platform.security import (
    CapabilityPackageVerifier,
    CapabilityValidationError,
    PermissionAuthority,
    PermissionDecisionKind,
    TrustMode,
)

logger = logging.getLogger(__name__)


class CapabilityState(str, Enum):
    INSTALLED = "INSTALLED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    CORRUPTED = "CORRUPTED"
    UNINSTALLED = "UNINSTALLED"


@dataclass
class CapabilityPack:
    """An active or registered capability pack."""

    manifest: CapabilityManifest
    state: CapabilityState = CapabilityState.INSTALLED
    install_path: str = ""
    active_adapter_path: Optional[str] = None
    granted_permissions: Set[Permission] = field(default_factory=set)

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    def is_enabled(self) -> bool:
        return self.state == CapabilityState.ENABLED


class CapabilityRegistry:
    """
    Central registry of installed capability packs.
    Enforces atomic lifecycle transitions, dependency resolution, and permission verification.
    """

    def __init__(
        self,
        trust_mode=TrustMode.PRODUCTION,
        permission_authority=None,
        package_verifier=None,
        model_assets=None,
        available_backends=("CPU",),
        database_path=":memory:",
        trusted_in_process_ids=("finance.personal_budget", "travel.itinerary_planner"),
    ):
        self._packs: Dict[str, CapabilityPack] = {}
        self._version_history: Dict[str, List[CapabilityManifest]] = {}
        self.permission_authority = permission_authority or PermissionAuthority()
        self.package_verifier = package_verifier or CapabilityPackageVerifier(
            trust_mode
        )
        self.model_assets = model_assets or {}
        self.available_backends = set(available_backends)
        self.trusted_in_process_ids = frozenset(trusted_in_process_ids)
        self._path_history = {}
        self.generation = 0
        self.db = sqlite3.connect(database_path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS registry_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)"
        )
        self.db.commit()
        row = self.db.execute(
            "SELECT payload FROM registry_state WHERE id=1"
        ).fetchone()
        if row:
            data = json.loads(row[0])
            for cid, item in data["packs"].items():
                pack = CapabilityPack(
                    CapabilityManifest(**item["manifest"]),
                    CapabilityState(item["state"]),
                    item["path"],
                )
                try:
                    self.package_verifier.verify(pack.manifest, pack.install_path)
                except CapabilityValidationError:
                    pack.state = CapabilityState.CORRUPTED
                self._packs[cid] = pack
            self._version_history = {
                cid: [CapabilityManifest(**m) for m in hist]
                for cid, hist in data["history"].items()
            }
            self._path_history = data.get("paths", {})

    def _persist(self):
        self.generation += 1
        data = {
            "packs": {
                cid: {
                    "manifest": asdict(p.manifest),
                    "state": p.state.value,
                    "path": p.install_path,
                }
                for cid, p in self._packs.items()
            },
            "history": {
                cid: [asdict(m) for m in hist]
                for cid, hist in self._version_history.items()
            },
            "paths": self._path_history,
        }
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO registry_state VALUES (1,?)",
                (json.dumps(data, sort_keys=True),),
            )

    def register_pack(
        self,
        manifest: CapabilityManifest,
        install_path: str = "",
        auto_enable: bool = True,
    ) -> CapabilityPack:
        """Register and optionally enable a capability pack."""
        from cne.platform.utterances import validate_mappings
        from cne.platform.controller_view import ControllerCapabilityViewBuilder

        validate_mappings(manifest)
        ControllerCapabilityViewBuilder().build(manifest)
        requested = set(manifest.permissions)
        operations = [
            m.get("required_permissions", [])
            for m in manifest.schemas.get("intents", [])
        ]
        operations += [t.required_permissions for t in manifest.deterministic_tools]
        operations += list(manifest.schemas.get("source_permissions", {}).values())
        if any(not {Permission(p) for p in perms} <= requested for perms in operations):
            raise CapabilityValidationError(
                "UNDECLARED_OPERATION_PERMISSION", manifest.id
            )
        self.package_verifier.verify(manifest, install_path)
        if auto_enable:
            self._validate_dependencies(manifest)
        # Check if updating an existing pack
        if manifest.id in self._packs:
            existing = self._packs[manifest.id]
            self._version_history.setdefault(manifest.id, []).append(existing.manifest)
            self._path_history.setdefault(manifest.id, []).append(existing.install_path)

        pack = CapabilityPack(
            manifest=manifest,
            state=CapabilityState.ENABLED if auto_enable else CapabilityState.INSTALLED,
            install_path=install_path,
            granted_permissions=set(),
        )
        self._packs[manifest.id] = pack
        self.permission_authority.revoke(manifest.id)
        self._persist()
        return pack

    def _validate_dependencies(self, manifest, visiting=None):
        from pathlib import Path

        visiting = set() if visiting is None else set(visiting)
        if manifest.id in visiting:
            raise CapabilityValidationError("DEPENDENCY_CYCLE", manifest.id)
        visiting.add(manifest.id)
        if not self.available_backends.intersection(manifest.backend_compatibility):
            raise CapabilityValidationError("BACKEND_UNAVAILABLE", manifest.id)
        for spec in manifest.required_capabilities:
            cid, _, required = spec.partition("@")
            if cid in visiting:
                raise CapabilityValidationError("DEPENDENCY_CYCLE", cid)
            dependency = self._packs.get(cid)
            if dependency is None:
                raise CapabilityValidationError("MISSING_CAPABILITY_DEPENDENCY", cid)
            if required and dependency.version != required:
                raise CapabilityValidationError("INCOMPATIBLE_CAPABILITY_VERSION", spec)
            self._validate_dependencies(dependency.manifest, visiting)
            if not dependency.is_enabled():
                raise CapabilityValidationError("MISSING_CAPABILITY_DEPENDENCY", cid)
        for dep in manifest.model_dependencies:
            asset = self.model_assets.get(dep.model_id)
            if dep.optional and asset is None:
                continue
            if asset is None or not Path(asset["path"]).is_file():
                raise CapabilityValidationError("MODEL_ASSET_MISSING", dep.model_id)
            if asset["version"] != dep.version:
                raise CapabilityValidationError("MODEL_VERSION_MISMATCH", dep.model_id)
            if "sha256" in asset:
                import hashlib

                if (
                    hashlib.sha256(Path(asset["path"]).read_bytes()).hexdigest()
                    != asset["sha256"]
                ):
                    raise CapabilityValidationError("MODEL_HASH_MISMATCH", dep.model_id)
            elif self.package_verifier.trust_mode == TrustMode.PRODUCTION:
                raise CapabilityValidationError("MODEL_HASH_MISSING", dep.model_id)
            if asset.get("backend", "CPU") not in self.available_backends:
                raise CapabilityValidationError("BACKEND_UNAVAILABLE", dep.model_id)

    def get_pack(self, capability_id: str) -> Optional[CapabilityPack]:
        return self._packs.get(capability_id)

    def list_packs(self, enabled_only: bool = False) -> List[CapabilityPack]:
        if enabled_only:
            return [p for p in self._packs.values() if p.is_enabled()]
        return list(self._packs.values())

    def enable_pack(self, capability_id: str) -> bool:
        pack = self._packs.get(capability_id)
        if pack and pack.state in (CapabilityState.INSTALLED, CapabilityState.DISABLED):
            self.package_verifier.verify(pack.manifest, pack.install_path)
            self._validate_dependencies(pack.manifest)
            pack.state = CapabilityState.ENABLED
            self._persist()
            return True
        return False

    def disable_pack(self, capability_id: str) -> bool:
        pack = self._packs.get(capability_id)
        if pack and pack.state == CapabilityState.ENABLED:
            pack.state = CapabilityState.DISABLED
            self._persist()
            return True
        return False

    def uninstall_pack(self, capability_id: str) -> bool:
        pack = self._packs.get(capability_id)
        if not pack:
            return False
        pack.state = CapabilityState.UNINSTALLED
        del self._packs[capability_id]
        self.permission_authority.revoke(capability_id)
        self._persist()
        return True

    def rollback_pack(self, capability_id: str) -> Optional[CapabilityPack]:
        """Rollback to the most recent prior version if available."""
        history = self._version_history.get(capability_id, [])
        if not history:
            return None
        prior_manifest = history[-1]
        prior_path = self._path_history.get(
            capability_id, [self._packs[capability_id].install_path]
        )[-1]
        self.package_verifier.verify(prior_manifest, prior_path)
        self._validate_dependencies(prior_manifest)
        history.pop()
        if self._path_history.get(capability_id):
            self._path_history[capability_id].pop()
        pack = CapabilityPack(
            manifest=prior_manifest,
            state=CapabilityState.ENABLED,
            granted_permissions=set(),
            install_path=prior_path,
        )
        self._packs[capability_id] = pack
        self.permission_authority.revoke(capability_id)
        self._persist()
        return pack

    def compute_active_capability_vector_hash(self) -> str:
        """Computes a stable deterministic hash of active (id, version) pairs."""
        import hashlib

        active = [(p.id, p.version) for p in self._packs.values() if p.is_enabled()]
        sorted_pairs = sorted(active, key=lambda x: x[0])
        raw = ";".join(f"{cid}@{ver}" for cid, ver in sorted_pairs)
        if not raw:
            return "none"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def has_permission(
        self, capability_id: str, permission: Permission, scope: str = "local_device"
    ) -> bool:
        """Deterministic platform check: verify if capability was granted permission."""
        pack = self._packs.get(capability_id)
        if not pack or not pack.is_enabled():
            return False
        return (
            self.permission_authority.decide(pack, permission, scope).decision
            == PermissionDecisionKind.GRANTED
        )

    def require_permission(self, capability_id, permission, scope):
        if not self.has_permission(capability_id, permission, scope):
            raise PermissionError(
                f"ACCESS_DENIED: {capability_id} {permission} {scope}"
            )


@dataclass
class CapabilityResolution:
    candidate_capabilities: list = field(default_factory=list)
    selected_capabilities: list = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    rejection_reasons: dict = field(default_factory=dict)
    required_permissions: dict = field(default_factory=dict)
    missing_dependencies: dict = field(default_factory=dict)


class CapabilityResolver:
    """
    Routes incoming user requests to relevant active capability packs.
    """

    def __init__(self, registry: CapabilityRegistry, model_scorer=None):
        self.registry = registry
        self.model_scorer = model_scorer

    def resolve(self, query_text: str, scope="local_device") -> CapabilityResolution:
        """
        Identify candidate capability packs for a query based on provided capabilities,
        keywords, and domain ontologies.
        """
        import re
        from cne.platform.capability_index import CapabilityCandidateRetriever
        from cne.platform.utterances import match_mapping
        from cne.platform.operations import intent_permissions

        if not hasattr(self, "retriever"):
            self.retriever = CapabilityCandidateRetriever(self.registry, k=8)
        result = CapabilityResolution()
        words = set(re.findall(r"\w+", query_text.casefold()))
        for pack in self.retriever.retrieve(query_text, scope):
            ontology = pack.manifest.schemas.get(
                "ontology", pack.manifest.provided_capabilities
            )
            terms = [
                set(re.findall(r"\w+", str(term).replace("_", " ").casefold()))
                for term in ontology
            ]
            matches = [t for t in terms if t and t <= words]
            mappings = [
                m
                for m in pack.manifest.schemas.get("intents", [])
                if match_mapping(m, query_text)
            ]
            result.candidate_capabilities.append(pack)
            result.scores[pack.id] = {
                "ontology_matches": len(matches),
                "ontology_terms": len(terms),
                "exact_schema_match": bool(mappings),
                "model_score": self.model_scorer(query_text, pack.manifest)
                if self.model_scorer
                else None,
            }
            try:
                self.registry._validate_dependencies(pack.manifest)
            except CapabilityValidationError as exc:
                result.missing_dependencies[pack.id] = str(exc)
                result.rejection_reasons[pack.id] = exc.code
                continue
            requirements = [
                intent_permissions(pack.manifest, m["intent"]) for m in mappings
            ]
            if not requirements:
                requirements = [
                    intent_permissions(pack.manifest, m["intent"])
                    for m in pack.manifest.schemas.get("intents", [])
                ] or [set(pack.manifest.permissions)]
            available = [
                r
                for r in requirements
                if all(self.registry.has_permission(pack.id, p, scope) for p in r)
            ]
            result.required_permissions[pack.id] = sorted(
                set().union(*requirements), key=str
            )
            if not available:
                result.rejection_reasons[
                    pack.id
                ] = "ACCESS_DENIED: operation grants required"
            else:
                result.selected_capabilities.append(pack)
        return result
