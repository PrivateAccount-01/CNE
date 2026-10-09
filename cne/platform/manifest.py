"""
CNE Capability Manifest Specification & Types.
Formal schema defining installable capability packs, permissions, dependencies, and budgets.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class Modality(str, Enum):
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    AUDIO = "AUDIO"
    TIME_SERIES = "TIME_SERIES"
    STRUCTURED = "STRUCTURED"


class NetworkMode(str, Enum):
    OFFLINE = "OFFLINE"
    LOCAL_COMPUTE_NETWORK_DATA = "LOCAL_COMPUTE_NETWORK_DATA"
    HYBRID_OPTIONAL = "HYBRID_OPTIONAL"


class Permission(str, Enum):
    FILESYSTEM_READ = "filesystem:read"
    FILESYSTEM_WRITE = "filesystem:write"
    NETWORK_HTTP = "network:http"
    CAMERA = "camera"
    MICROPHONE = "microphone"
    CALENDAR_READ = "calendar:read"
    CALENDAR_WRITE = "calendar:write"
    CONTACTS_READ = "contacts:read"
    FINANCIAL_DATA_READ = "financial_data:read"
    FINANCIAL_DATA_WRITE = "financial_data:write"
    LOCATION = "location"
    SENSORS = "sensors"


@dataclass(frozen=True)
class CapabilityVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, ver_str: str) -> CapabilityVersion:
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", ver_str.strip())
        if not match:
            raise ValueError(f"Invalid semantic version: {ver_str}")
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ModelDependency:
    role: str
    model_kind: str
    model_id: str
    version: str
    shared: bool = True
    optional: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    schema_version: str
    entrypoint: str
    description: str = ""
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    returns_schema: Dict[str, Any] = field(default_factory=dict)
    mutation_sources: List[str] = field(default_factory=list)
    required_permissions: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CapabilityManifest:
    """
    Formal specification manifest for an installable capability pack.
    """

    id: str
    version: str
    description: str
    modalities: List[Modality]
    provided_capabilities: List[str]
    required_capabilities: List[str] = field(default_factory=list)
    model_dependencies: List[ModelDependency] = field(default_factory=list)
    deterministic_tools: List[ToolDefinition] = field(default_factory=list)
    schemas: Dict[str, Any] = field(default_factory=dict)
    permissions: List[Permission] = field(default_factory=list)
    network_mode: NetworkMode = NetworkMode.OFFLINE
    storage_budget_mb: float = 50.0
    expected_peak_ram_mb: float = 150.0
    backend_compatibility: List[str] = field(default_factory=lambda: ["CPU"])
    package_hash: Optional[str] = None
    signature: Optional[str] = None
    asset_hashes: Dict[str, str] = field(default_factory=dict)
    model_asset_hashes: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate canonical ID
        if not re.match(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$", self.id):
            raise ValueError(
                f"Capability ID '{self.id}' violates canonical format '<domain>.<subdomain>'"
            )
        # Validate version
        CapabilityVersion.parse(self.version)

        # Coerce modalities, network_mode, permissions if raw strings provided
        coerced_mods = [
            Modality(m) if isinstance(m, str) else m for m in self.modalities
        ]
        object.__setattr__(self, "modalities", coerced_mods)

        if isinstance(self.network_mode, str):
            object.__setattr__(self, "network_mode", NetworkMode(self.network_mode))

        coerced_perms = [
            Permission(p) if isinstance(p, str) else p for p in self.permissions
        ]
        object.__setattr__(self, "permissions", coerced_perms)
        object.__setattr__(
            self,
            "model_dependencies",
            [
                ModelDependency(**m) if isinstance(m, dict) else m
                for m in self.model_dependencies
            ],
        )
        object.__setattr__(
            self,
            "deterministic_tools",
            [
                ToolDefinition(**t) if isinstance(t, dict) else t
                for t in self.deterministic_tools
            ],
        )

    def compute_manifest_hash(self) -> str:
        """Deterministic SHA-256 fingerprint of the manifest specification."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def canonical_bytes(self) -> bytes:
        data = asdict(self)
        data.pop("package_hash", None)
        data.pop("signature", None)
        # Convert enums to values
        data["modalities"] = [
            m.value if isinstance(m, Modality) else m for m in self.modalities
        ]
        data["network_mode"] = (
            self.network_mode.value
            if isinstance(self.network_mode, NetworkMode)
            else self.network_mode
        )
        data["permissions"] = [
            p.value if isinstance(p, Permission) else p for p in self.permissions
        ]
        return json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
