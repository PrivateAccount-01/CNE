"""Conservative durable CNE state adapter; the CNE evaluator remains authoritative."""
from dataclasses import asdict
import hashlib, json, sqlite3, time, math
from cne.state.fabric import LocalStateFabric
from cne.state.state_entry import StateClass
from cne.contracts.outcome_contract import OutcomeContract, ContractType
from cne.semantic_ir.types import DependencyKey
from cne.signature.memo_key import MemoKey, SystemVersions, clear_digest_cache
from cne.optimizer.runtime.dependencies import ChangeType


def safe_json(value, _depth=0, _budget=None):
    """Accept only finite JSON under conservative depth and node budgets."""
    if _budget is None:
        _budget = [10000]
    _budget[0] -= 1
    if _budget[0] < 0 or _depth > 32:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if type(value) is str:
        return len(value.encode("utf-8")) <= 1_000_000
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(safe_json(x, _depth + 1, _budget) for x in value)
    if type(value) is dict:
        return all(
            type(k) is str and len(k.encode("utf-8")) <= 1024
            and safe_json(v, _depth + 1, _budget)
            for k, v in value.items()
        )
    return False


def fingerprint(value):
    if not safe_json(value):
        raise ValueError("Opaque source remains ephemeral")
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class StateFabricRepository:
    MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
    MAX_OWNER_ROWS = 10000

    def __init__(self, path, codec=None):
        self.db = sqlite3.connect(path)
        self.codec = codec
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS computational_state (owner TEXT, memo TEXT, payload TEXT, created REAL, used REAL, PRIMARY KEY(owner,memo))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS computational_state_sources (owner TEXT NOT NULL, source TEXT NOT NULL, memo TEXT NOT NULL, PRIMARY KEY(owner,source,memo), FOREIGN KEY(owner,memo) REFERENCES computational_state(owner,memo) ON DELETE CASCADE)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_state_sources_owner_source ON computational_state_sources(owner,source)")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError("Unsupported computational state schema")
        if version == 0:
            # One-time fail-closed migration: rebuild dependencies from authenticated
            # payloads; rows we cannot authenticate/parse are discarded, never reused.
            with self.db:
                rows = self.db.execute(
                    "SELECT owner,memo,payload FROM computational_state"
                ).fetchall()
                for owner, memo, encoded in rows:
                    try:
                        payload = (
                            self.codec.open(encoded, owner, "cne_state")
                            if self.codec
                            else json.loads(encoded)
                        )
                        sources = payload["source_fingerprints"]
                        if not isinstance(sources, dict):
                            raise ValueError("Invalid source index payload")
                        self.db.executemany(
                            "INSERT OR IGNORE INTO computational_state_sources(owner,source,memo) VALUES (?,?,?)",
                            [(owner, source, memo) for source in sources],
                        )
                    except Exception:
                        self.db.execute(
                            "DELETE FROM computational_state WHERE owner=? AND memo=?",
                            (owner, memo),
                        )
                self.db.execute("PRAGMA user_version=1")
        self.db.commit()

    def save(self, owner, memo, payload):
        now = time.time()
        encoded = (
            self.codec.seal(payload, owner, "cne_state")
            if self.codec
            else json.dumps(payload, separators=(",", ":"), allow_nan=False)
        )
        if len(encoded.encode("utf-8")) > self.MAX_PAYLOAD_BYTES:
            raise ValueError("Persistent state payload exceeds size limit")
        sources = payload.get("source_fingerprints", {})
        if not isinstance(sources, dict) or len(sources) > 10000:
            raise ValueError("Invalid persistent state source index")
        with self.db:
            count = self.db.execute(
                "SELECT COUNT(*) FROM computational_state WHERE owner=? AND memo<>?",
                (owner, memo),
            ).fetchone()[0]
            if count >= self.MAX_OWNER_ROWS:
                evicted = self.db.execute(
                    "SELECT memo FROM computational_state WHERE owner=? AND memo<>? ORDER BY used ASC LIMIT ?",
                    (owner, memo, count - self.MAX_OWNER_ROWS + 1),
                ).fetchall()
                self.db.executemany(
                    "DELETE FROM computational_state WHERE owner=? AND memo=?",
                    [(owner, row[0]) for row in evicted],
                )
                self.db.executemany(
                    "DELETE FROM computational_state_sources WHERE owner=? AND memo=?",
                    [(owner, row[0]) for row in evicted],
                )
            self.db.execute(
                "INSERT INTO computational_state VALUES (?,?,?,?,?) ON CONFLICT(owner,memo) DO UPDATE SET payload=excluded.payload,used=excluded.used",
                (owner, memo, encoded, now, now),
            )
            self.db.execute(
                "DELETE FROM computational_state_sources WHERE owner=? AND memo=?",
                (owner, memo),
            )
            self.db.executemany(
                "INSERT INTO computational_state_sources(owner,source,memo) VALUES (?,?,?)",
                [(owner, source, memo) for source in sources],
            )

    def load(self, owner, memo):
        row = self.db.execute(
            "SELECT payload FROM computational_state WHERE owner=? AND memo=?",
            (owner, memo),
        ).fetchone()
        if row:
            try:
                payload = (
                    self.codec.open(row[0], owner, "cne_state")
                    if self.codec
                    else json.loads(row[0])
                )
                if not isinstance(payload, dict) or not isinstance(payload.get("source_fingerprints"), dict):
                    return None
            except Exception:
                # A missing/wrong key or damaged envelope must never become a cache hit.
                return None
            with self.db:
                self.db.execute(
                    "UPDATE computational_state SET used=? WHERE owner=? AND memo=?",
                    (time.time(), owner, memo),
                )
            return payload

    def invalidate(self, owner, source):
        # The relational index is intentionally independent of payload encoding.
        # Ciphertext never needs to be decrypted on a mutation path.
        with self.db:
            memos = [
                row[0]
                for row in self.db.execute(
                    "SELECT memo FROM computational_state_sources WHERE owner=? AND source=?",
                    (owner, source),
                )
            ]
            self.db.executemany(
                "DELETE FROM computational_state WHERE owner=? AND memo=?",
                [(owner, memo) for memo in memos],
            )
            self.db.execute(
                "DELETE FROM computational_state_sources WHERE owner=? AND source=?",
                (owner, source),
            )

    def delete_user(self, owner):
        with self.db:
            self.db.execute("DELETE FROM computational_state WHERE owner=?", (owner,))
            self.db.execute("DELETE FROM computational_state_sources WHERE owner=?", (owner,))


class PersistentStateFabric(LocalStateFabric):
    def __init__(self, repository, owner):
        super().__init__()
        self.repository = repository
        self.owner = owner
        self.current_sources = {}
        self.admissible = False

    def prepare(self, graph, env):
        clear_digest_cache()
        try:
            sources = {s: fingerprint(env.get(s)) for s in graph.get_observed_sources()}
        except ValueError:
            self.admissible = False
            return
        for source, digest in sources.items():
            if (
                source in self.current_sources
                and self.current_sources[source] != digest
            ):
                self.notify_data_mutation(ChangeType.UPDATE, source)
        self.current_sources = sources
        # Calls and opaque/custom contracts require a future durable proof codec.
        from cne.semantic_ir.nodes import OpKind

        self.admissible = not any(
            n.op == OpKind.CALL for n in graph.get_all_nodes().values()
        )

    def put(self, *args, **kwargs):
        entry = super().put(*args, **kwargs)
        c = entry.contract
        if (
            not self.admissible
            or entry.state_class != StateClass.COMPUTATIONAL
            or not entry.memo_key
            or not c
            or c.contract_type != ContractType.EXACT
            or c.constraints
            or c.acceptable_equivalence
            or not safe_json(entry.value)
        ):
            return entry
        if not c.satisfies_constraints(entry.value):
            return entry
        payload = {
            "schema": 1,
            "entry_id": entry.entry_id,
            "state_class": entry.state_class.value,
            "value": entry.value,
            "memo": asdict(entry.memo_key),
            "contract": c.contract_repr,
            "dependencies": [asdict(d) for d in entry.dependency_keys],
            "dependency_snapshot": entry.dependency_snapshot,
            "source_fingerprints": dict(self.current_sources),
            "provenance": {"codec": "exact-json-1"},
            "lifecycle": "active",
        }
        self.repository.save(self.owner, entry.memo_key.key_hash, payload)
        return entry

    def get_by_memo_key(self, key):
        entry = super().get_by_memo_key(key)
        if entry or not self.admissible:
            return entry
        payload = self.repository.load(self.owner, key.key_hash)
        if (
            not payload
            or payload.get("schema") != 1
            or payload.get("lifecycle") != "active"
            or payload["source_fingerprints"] != self.current_sources
        ):
            return None
        if (
            payload["memo"] != asdict(key)
            or payload["contract"]["t"] != "EXACT"
            or payload["contract"]["cst"]
            or payload["contract"]["eq"]
        ):
            return None
        if not safe_json(payload["value"]):
            return None
        c = payload["contract"]
        contract = OutcomeContract(
            ContractType.EXACT,
            output_schema=c["s"],
            required_facts=set(c["f"]),
            tolerances=dict(c["tol"]),
            decision_boundary=c["b"],
            provenance_requirements=dict(c["prov"]) if c["prov"] else None,
        )
        # Coarse restored subscriptions are conservative: no executable predicates are deserialized.
        return super().put(
            payload["entry_id"],
            StateClass.COMPUTATIONAL,
            payload["value"],
            memo_key=key,
            contract=contract,
            dependencies=[DependencyKey(s, "source") for s in self.current_sources],
            provenance=payload["provenance"],
        )

    def notify_data_mutation(self, change_type, source, *args, **kwargs):
        self.repository.invalidate(self.owner, source)
        return super().notify_data_mutation(change_type, source, *args, **kwargs)
