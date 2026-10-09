"""Deterministic permission authority and fail-closed package verification.

This is an application boundary, not an OS sandbox for hostile Python code.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import hashlib
import time
import sqlite3
import json
import secrets
import base64

from cne.platform.manifest import Permission


class PermissionDecisionKind(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    ASK_USER = "ASK_USER"
    NOT_DECLARED = "NOT_DECLARED"


@dataclass(frozen=True)
class PermissionGrant:
    capability_id: str
    permission: Permission
    scope: str
    granted_at: float
    source: str
    expires_at: float | None = None


@dataclass(frozen=True)
class PermissionDecision:
    capability_id: str
    permission: Permission
    decision: PermissionDecisionKind
    scope: str
    granted_at: float | None = None
    expires_at: float | None = None
    source: str = "authority"


class PermissionAuthority:
    def __init__(self, database_path=":memory:"):
        self._grants = {}
        self.db = sqlite3.connect(database_path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS permission_grants (capability TEXT, permission TEXT, scope TEXT, issued REAL, source TEXT, expiry REAL, PRIMARY KEY(capability,permission,scope))"
        )
        self.db.commit()

    def grant(self, capability_id, permission, scope, source, expires_at=None):
        if not scope or not source:
            raise ValueError("Explicit scope and source required")
        grant = PermissionGrant(
            capability_id,
            Permission(permission),
            scope,
            time.time(),
            source,
            expires_at,
        )
        self._grants[capability_id, Permission(permission), scope] = grant
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO permission_grants VALUES (?,?,?,?,?,?)",
                (
                    capability_id,
                    Permission(permission).value,
                    scope,
                    grant.granted_at,
                    source,
                    expires_at,
                ),
            )
        return grant

    def revoke(self, capability_id):
        self._grants = {k: v for k, v in self._grants.items() if k[0] != capability_id}
        with self.db:
            self.db.execute(
                "DELETE FROM permission_grants WHERE capability=?", (capability_id,)
            )

    def decide(self, pack, permission, scope):
        permission = Permission(permission)
        kind = PermissionDecisionKind
        if permission not in pack.manifest.permissions:
            return PermissionDecision(pack.id, permission, kind.NOT_DECLARED, scope)
        if not pack.is_enabled():
            return PermissionDecision(pack.id, permission, kind.DENIED, scope)
        row = self.db.execute(
            "SELECT issued,source,expiry FROM permission_grants WHERE capability=? AND permission=? AND scope=?",
            (pack.id, permission.value, scope),
        ).fetchone()
        grant = (
            PermissionGrant(pack.id, permission, scope, row[0], row[1], row[2])
            if row
            else None
        )
        if grant is None:
            return PermissionDecision(pack.id, permission, kind.ASK_USER, scope)
        decision = (
            kind.GRANTED
            if grant.expires_at is None or grant.expires_at > time.time()
            else kind.DENIED
        )
        return PermissionDecision(
            pack.id,
            permission,
            decision,
            scope,
            grant.granted_at,
            grant.expires_at,
            grant.source,
        )


class TrustMode(str, Enum):
    DEVELOPMENT_TRUST_MODE = "DEVELOPMENT_TRUST_MODE"
    PRODUCTION = "PRODUCTION"


class IdentityAuthority:
    """Local bearer sessions issued only by a trusted, authenticated host login.

    A model or capability receives no reference to this provisioning authority.
    Only a SHA-256 token digest is persisted, never the bearer secret.
    """

    def __init__(self, database_path=":memory:"):
        self.db = sqlite3.connect(database_path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS identities (digest TEXT PRIMARY KEY, user TEXT NOT NULL, expiry REAL NOT NULL)"
        )
        self.db.commit()

    def issue(self, authenticated_user_id, lifetime_s=3600):
        if not authenticated_user_id or lifetime_s <= 0:
            raise ValueError("Authenticated user and positive lifetime required")
        token = secrets.token_urlsafe(32)
        with self.db:
            self.db.execute(
                "INSERT INTO identities VALUES (?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    authenticated_user_id,
                    time.time() + lifetime_s,
                ),
            )
        return token

    def authenticate(self, token):
        row = self.db.execute(
            "SELECT user,expiry FROM identities WHERE digest=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
        if row is None or row[1] <= time.time():
            raise PermissionError("ACCESS_DENIED: invalid or expired identity")
        return row[0]

    def revoke(self, token):
        with self.db:
            self.db.execute(
                "DELETE FROM identities WHERE digest=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )


class Ed25519TrustStore:
    """Persisted publisher keys; rotation/revocation is an administrator operation."""

    def __init__(self, database_path=":memory:"):
        self.db = sqlite3.connect(database_path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS publisher_keys (id TEXT PRIMARY KEY, public BLOB NOT NULL, domain TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)"
        )
        self.db.commit()

    def trust(self, key_id, public_key_bytes, domain):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(public_key_bytes)
        if not key_id or not domain or "." in domain:
            raise ValueError("Key ID and canonical domain required")
        with self.db:
            self.db.execute(
                "INSERT INTO publisher_keys VALUES (?,?,?,0)",
                (key_id, public_key_bytes, domain),
            )

    def revoke(self, key_id):
        with self.db:
            self.db.execute("UPDATE publisher_keys SET revoked=1 WHERE id=?", (key_id,))

    @staticmethod
    def sign(manifest, key_id, private_key):
        from dataclasses import replace

        signature = base64.b64encode(
            private_key.sign(manifest.canonical_bytes())
        ).decode("ascii")
        return replace(
            manifest,
            package_hash=manifest.compute_manifest_hash(),
            signature=json.dumps(
                {"algorithm": "Ed25519", "key_id": key_id, "value": signature},
                sort_keys=True,
            ),
        )

    def verify(self, canonical_bytes, envelope):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature

        try:
            data = json.loads(envelope)
            row = self.db.execute(
                "SELECT public,domain,revoked FROM publisher_keys WHERE id=?",
                (data["key_id"],),
            ).fetchone()
            if (
                data["algorithm"] != "Ed25519"
                or not row
                or row[2]
                or json.loads(canonical_bytes)["id"].split(".")[0] != row[1]
            ):
                return False
            Ed25519PublicKey.from_public_bytes(row[0]).verify(
                base64.b64decode(data["value"], validate=True), canonical_bytes
            )
            return True
        except (ValueError, KeyError, TypeError, InvalidSignature):
            return False


from cne.platform.errors import PackageVersionError


class CapabilityValidationError(PackageVersionError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"{code}: {detail}")


class CapabilityPackageVerifier:
    def __init__(self, trust_mode=TrustMode.PRODUCTION, signature_verifier=None):
        self.trust_mode = TrustMode(trust_mode)
        self.signature_verifier = signature_verifier

    def verify(self, manifest, install_path=""):
        digest = manifest.compute_manifest_hash()
        if manifest.package_hash is not None and manifest.package_hash != digest:
            raise CapabilityValidationError("MANIFEST_HASH_MISMATCH", manifest.id)
        if self.trust_mode == TrustMode.PRODUCTION and manifest.package_hash is None:
            raise CapabilityValidationError("MANIFEST_HASH_MISSING", manifest.id)
        root = Path(install_path).resolve()
        for relative, expected in {
            **manifest.asset_hashes,
            **manifest.model_asset_hashes,
        }.items():
            asset = (root / relative).resolve()
            if not asset.is_relative_to(root) or not asset.is_file():
                raise CapabilityValidationError(
                    "MODEL_ASSET_MISSING"
                    if relative in manifest.model_asset_hashes
                    else "ASSET_MISSING",
                    relative,
                )
            if hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
                raise CapabilityValidationError("ASSET_HASH_MISMATCH", relative)
        if manifest.signature is not None or self.trust_mode == TrustMode.PRODUCTION:
            if (
                not manifest.signature
                or self.signature_verifier is None
                or not self.signature_verifier(
                    manifest.canonical_bytes(), manifest.signature
                )
            ):
                raise CapabilityValidationError("INVALID_SIGNATURE", manifest.id)
        ids = [t.tool_id for t in manifest.deterministic_tools]
        if len(ids) != len(set(ids)) or any(
            not t.schema_version for t in manifest.deterministic_tools
        ):
            raise CapabilityValidationError("TOOL_SCHEMA_VERSION_INVALID", manifest.id)
        return digest


class PermissionBroker:
    """Trusted application resource gateway; it does not sandbox imported code."""

    def __init__(self, registry, filesystem_roots=None):
        self.registry = registry
        self.filesystem_roots = filesystem_roots or {}

    def read_file(self, capability_id, user_id, path):
        self.registry.require_permission(
            capability_id, Permission.FILESYSTEM_READ, user_id
        )
        requested = Path(path).resolve()
        roots = self.filesystem_roots.get((user_id, capability_id), ())
        if not any(requested.is_relative_to(Path(root).resolve()) for root in roots):
            raise PermissionError("ACCESS_DENIED: filesystem scope")
        return requested.read_bytes()

    def authorize_network(self, capability_id, user_id):
        from cne.platform.manifest import NetworkMode

        self.registry.require_permission(
            capability_id, Permission.NETWORK_HTTP, user_id
        )
        if (
            self.registry.get_pack(capability_id).manifest.network_mode
            == NetworkMode.OFFLINE
        ):
            raise PermissionError("ACCESS_DENIED: offline capability")
