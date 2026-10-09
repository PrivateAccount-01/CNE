"""Versioned durable repositories for reviewed replay and private payload encryption."""
from dataclasses import asdict
import json, sqlite3, hashlib, time
from typing import Protocol
from cne.platform.memory import ExperienceRecord


class ReplayRepository(Protocol):
    def load(self):
        ...

    def replace(self, records):
        ...


class InMemoryReplayRepository:
    def __init__(self):
        self.records = []

    def load(self):
        return [ExperienceRecord(**json.loads(x)) for x in self.records]

    def replace(self, records):
        self.records = [json.dumps(asdict(r)) for r in records]


class SQLiteReplayRepository:
    def __init__(self, path, codec=None):
        self.db = sqlite3.connect(path)
        self.codec = codec
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError("Unsupported replay schema migration")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS replay (identity TEXT PRIMARY KEY, owner TEXT, timestamp REAL, state TEXT, payload TEXT)"
        )
        self.db.execute("PRAGMA user_version=1")
        self.db.commit()

    def load(self):
        records = []
        for owner, payload in self.db.execute("SELECT owner,payload FROM replay"):
            data = (
                self.codec.open(payload, owner, "replay")
                if self.codec
                else json.loads(payload)
            )
            records.append(ExperienceRecord(**data))
        return records

    def replace(self, records):
        with self.db:
            self.db.execute("DELETE FROM replay")
            for r in records:
                key = hashlib.sha256(
                    json.dumps(
                        [r.user_id, r.input_fingerprint, r.semantic_dsl, r.outcome]
                    ).encode()
                ).hexdigest()
                self.db.execute(
                    "INSERT INTO replay VALUES (?,?,?,?,?)",
                    (
                        key,
                        r.user_id,
                        r.timestamp,
                        r.state,
                        self.codec.seal(asdict(r), r.user_id, "replay")
                        if self.codec
                        else json.dumps(asdict(r)),
                    ),
                )

    def delete_user(self, user_id):
        with self.db:
            self.db.execute("DELETE FROM replay WHERE owner=?", (user_id,))


class KeyProvider(Protocol):
    def get_key(self, key_id):
        ...


class EncryptedPayloadCodec:
    """AES-GCM envelope for repository payloads. Keys are supplied by the host/OS.

    Owner and repository namespace are authenticated, preventing ciphertext swaps.
    No plaintext fallback or local key-file generation is provided.
    """

    def __init__(self, key_provider, key_id):
        self.provider = key_provider
        self.key_id = key_id

    def seal(self, payload, owner, namespace):
        import os, base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        aad = json.dumps([owner, namespace]).encode()
        encrypted = AESGCM(self.provider.get_key(self.key_id)).encrypt(
            nonce, json.dumps(payload).encode(), aad
        )
        return json.dumps(
            {
                "v": 1,
                "key_id": self.key_id,
                "nonce": base64.b64encode(nonce).decode(),
                "data": base64.b64encode(encrypted).decode(),
            }
        )

    def open(self, envelope, owner, namespace):
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        obj = json.loads(envelope)
        if obj["v"] != 1 or obj["key_id"] != self.key_id:
            raise ValueError("Unknown encryption envelope")
        plain = AESGCM(self.provider.get_key(self.key_id)).decrypt(
            base64.b64decode(obj["nonce"]),
            base64.b64decode(obj["data"]),
            json.dumps([owner, namespace]).encode(),
        )
        return json.loads(plain)
