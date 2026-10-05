"""
CNE Capability Registry & Lifecycle Manager.
Tracks, resolves, and manages installable capability packs with atomic state transitions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from cne.platform.manifest import CapabilityManifest, CapabilityVersion, Permission

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

    def __init__(self):
        self._packs: Dict[str, CapabilityPack] = {}
        self._version_history: Dict[str, List[CapabilityManifest]] = {}

    def register_pack(
        self,
        manifest: CapabilityManifest,
        install_path: str = "",
        auto_enable: bool = True
    ) -> CapabilityPack:
        """Register and optionally enable a capability pack."""
        # Check if updating an existing pack
        if manifest.id in self._packs:
            existing = self._packs[manifest.id]
            self._version_history.setdefault(manifest.id, []).append(existing.manifest)

        pack = CapabilityPack(
            manifest=manifest,
            state=CapabilityState.ENABLED if auto_enable else CapabilityState.INSTALLED,
            install_path=install_path,
            granted_permissions=set(manifest.permissions)
        )
        self._packs[manifest.id] = pack
        return pack

    def get_pack(self, capability_id: str) -> Optional[CapabilityPack]:
        return self._packs.get(capability_id)

    def list_packs(self, enabled_only: bool = False) -> List[CapabilityPack]:
        if enabled_only:
            return [p for p in self._packs.values() if p.is_enabled()]
        return list(self._packs.values())

    def enable_pack(self, capability_id: str) -> bool:
        pack = self._packs.get(capability_id)
        if pack and pack.state in (CapabilityState.INSTALLED, CapabilityState.DISABLED):
            pack.state = CapabilityState.ENABLED
            return True
        return False

    def disable_pack(self, capability_id: str) -> bool:
        pack = self._packs.get(capability_id)
        if pack and pack.state == CapabilityState.ENABLED:
            pack.state = CapabilityState.DISABLED
            return True
        return False

    def uninstall_pack(self, capability_id: str) -> bool:
        pack = self._packs.get(capability_id)
        if not pack:
            return False
        pack.state = CapabilityState.UNINSTALLED
        del self._packs[capability_id]
        return True

    def rollback_pack(self, capability_id: str) -> Optional[CapabilityPack]:
        """Rollback to the most recent prior version if available."""
        history = self._version_history.get(capability_id, [])
        if not history:
            return None
        prior_manifest = history.pop()
        pack = CapabilityPack(
            manifest=prior_manifest,
            state=CapabilityState.ENABLED,
            granted_permissions=set(prior_manifest.permissions)
        )
        self._packs[capability_id] = pack
        return pack

    def compute_active_capability_vector_hash(self) -> str:
        """Computes a stable deterministic hash of active (id, version) pairs."""
        import hashlib
        active = [
            (p.id, p.version) for p in self._packs.values()
            if p.is_enabled()
        ]
        sorted_pairs = sorted(active, key=lambda x: x[0])
        raw = ";".join(f"{cid}@{ver}" for cid, ver in sorted_pairs)
        if not raw:
            return "none"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def has_permission(self, capability_id: str, permission: Permission) -> bool:
        """Deterministic platform check: verify if capability was granted permission."""
        pack = self._packs.get(capability_id)
        if not pack or not pack.is_enabled():
            return False
        return permission in pack.granted_permissions


class CapabilityResolver:
    """
    Routes incoming user requests to relevant active capability packs.
    """

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def resolve(self, query_text: str) -> List[CapabilityPack]:
        """
        Identify candidate capability packs for a query based on provided capabilities,
        keywords, and domain ontologies.
        """
        candidates: List[CapabilityPack] = []
        q_lower = query_text.lower()

        for pack in self.registry.list_packs(enabled_only=True):
            # Domain prefix match
            domain = pack.id.split(".")[0]
            if domain in q_lower:
                candidates.append(pack)
                continue
            # Provided capability match
            for cap in pack.manifest.provided_capabilities:
                if cap.replace("_", " ") in q_lower:
                    candidates.append(pack)
                    break

        return candidates
