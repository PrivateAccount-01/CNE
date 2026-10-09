"""Scoped platform memory. SQLite repositories persist bounded structured records."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Protocol


class AuditStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    USER_SCOPED = "USER_SCOPED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ExperienceState(str, Enum):
    RAW = "RAW"
    AUDITED = "AUDITED"
    VERIFIED = "VERIFIED"
    TRAINING_ELIGIBLE = "TRAINING_ELIGIBLE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RedactionPolicy:
    def __init__(self, patterns=None):
        self.patterns = {
            "EMAIL": r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
            "PHONE": r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)",
            "IDENTIFIER": r"(?i)\b(?:account|user_id|payment|iban|upi)\s*[:=#]?\s*[\w@.-]+",
            **(patterns or {}),
        }

    def redact(self, text):
        for token, pattern in self.patterns.items():
            text = re.sub(pattern, "[" + token + "]", text)
        return text


def request_fingerprint(query, capability_scope=(), schema_version="request-2"):
    normalized = " ".join(query.casefold().split())
    return hashlib.sha256(
        json.dumps(
            [schema_version, sorted(capability_scope), normalized],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@dataclass
class CorrectionRecord:
    record_id: str
    request_fingerprint: str
    query_redacted: str
    capability_id: str
    model_version: str
    controller_version: str
    error_type: str
    incorrect_decision: str
    verified_correction: str
    user_feedback: str | None = None
    verifier_evidence: str | None = None
    confidence: float | None = None
    audit_status: AuditStatus = AuditStatus.UNVERIFIED
    created_at: float = field(default_factory=time.time)
    scope: str = "local_device"
    user_id: str = "default_user"
    semantic_shape: str = ""
    intent: str = ""
    capability_version: str = ""
    tool_versions: dict = field(default_factory=dict)
    constraint: dict = field(default_factory=dict)
    correction_kind: str = "factual"
    experience_id: str = ""
    training_example: dict | None = None


@dataclass
class ExperienceRecord:
    experience_id: str
    session_id: str
    query_text: str
    capability_ids: list
    model_id: str
    semantic_dsl: str
    outcome: str
    contract_satisfied: bool
    latency_ms: float
    user_correction_provided: bool = False
    timestamp: float = field(default_factory=time.time)
    user_id: str = "default_user"
    state: ExperienceState = ExperienceState.RAW
    controller_version: str = ""
    capability_versions: dict = field(default_factory=dict)
    model_versions: dict = field(default_factory=dict)
    tool_versions: dict = field(default_factory=dict)
    input_fingerprint: str = ""
    semantic_shape: str = ""
    slot_values: dict = field(default_factory=dict)
    contract: dict = field(default_factory=dict)
    verification_result: dict = field(default_factory=dict)
    error_classification: str | None = None
    backend: str = ""
    resource_metrics: dict = field(default_factory=dict)
    fallback: str | None = None
    intent: str = ""
    training_example: dict | None = None
    admission: dict = field(default_factory=dict)


@dataclass
class SessionState:
    session_id: str
    user_id: str = "default_user"
    active_capabilities: set = field(default_factory=set)
    active_entities: dict = field(default_factory=dict)
    active_goals: list = field(default_factory=list)
    compact_summary: str = ""
    semantic_history: list = field(default_factory=list)
    relevant_correction_ids: list = field(default_factory=list)
    token_budget_consumed: int = 0
    model_versions: dict = field(default_factory=dict)
    capability_versions: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)


class SessionRepository(Protocol):
    def get_session(self, user_id, session_id):
        ...

    def save(self, session):
        ...


class InMemorySessionRepository:
    def __init__(self):
        self._sessions = {}

    def get_session(self, user_id, session_id):
        session = self._sessions.get(session_id)
        if session is not None and session.user_id != user_id:
            raise PermissionError("ACCESS_DENIED")
        return session

    def save(self, session):
        self.get_session(session.user_id, session.session_id)
        self._sessions[session.session_id] = session


class SQLiteSessionRepository:
    def __init__(self, path, codec=None):
        self.db = sqlite3.connect(path)
        self.codec = codec
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self.db.commit()

    def get_session(self, user_id, session_id):
        row = self.db.execute(
            "SELECT owner,payload FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        if row[0] != user_id:
            raise PermissionError("ACCESS_DENIED")
        data = (
            self.codec.open(row[1], user_id, "sessions")
            if self.codec
            else json.loads(row[1])
        )
        data["active_capabilities"] = set(data["active_capabilities"])
        return SessionState(**data)

    def save(self, session):
        data = asdict(session)
        data["active_capabilities"] = sorted(session.active_capabilities)
        with self.db:
            self.db.execute(
                "INSERT INTO sessions VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload WHERE sessions.owner=excluded.owner",
                (
                    session.session_id,
                    session.user_id,
                    self.codec.seal(data, session.user_id, "sessions")
                    if self.codec
                    else json.dumps(data),
                ),
            )
            self.get_session(session.user_id, session.session_id)

    def close(self):
        self.db.close()


class SessionStore:
    def __init__(self, repository=None):
        self.repository = repository or InMemorySessionRepository()

    def get_session(self, user_id, session_id):
        if not user_id:
            raise PermissionError("ACCESS_DENIED: user scope required")
        session = self.repository.get_session(user_id, session_id)
        if session is None:
            session = SessionState(session_id, user_id)
            self.repository.save(session)
        return session

    def get_or_create(self, session_id, user_id="default_user"):
        """Compatibility for local single-user callers; ownership is still checked."""
        return self.get_session(user_id, session_id)

    def record_turn(
        self,
        session_id,
        user_query,
        active_capability,
        intent,
        extracted_slots,
        tokens_used=0,
        user_id="default_user",
    ):
        session = self.get_session(user_id, session_id)
        session.active_capabilities.add(active_capability)
        session.active_entities.update(extracted_slots)
        session.token_budget_consumed += tokens_used
        session.last_updated = time.time()
        session.semantic_history.append(
            {
                "fingerprint": request_fingerprint(user_query, [active_capability]),
                "capability": active_capability,
                "intent": intent,
                "timestamp": session.last_updated,
            }
        )
        session.semantic_history = session.semantic_history[-10:]
        self.repository.save(session)

    def close_session(self, session_id, user_id="default_user"):
        session = self.get_session(user_id, session_id)
        session.compact_summary = (
            f"Session {session_id} ended with {len(session.semantic_history)} turns."
        )
        self.repository.save(session)


@dataclass
class SemanticPlanTemplate:
    shape_hash: str
    parameterized_dsl: str
    capability_vector: str
    controller_version: str
    schema_version: str
    required_slots: tuple
    tool_dependencies: tuple = ()
    created_at: float = field(default_factory=time.time)
    last_used: float | None = None
    use_count: int = 0


class SemanticPlanCache:
    def __init__(self, database_path=":memory:", codec=None):
        self._plan_templates = {}
        self.db = sqlite3.connect(database_path)
        self.codec = codec
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS semantic_plans (owner TEXT, shape TEXT, payload TEXT, PRIMARY KEY(owner,shape))"
        )
        self.db.commit()

    def put_template(self, user_id, template):
        if not user_id:
            raise PermissionError("User scope required")
        self._plan_templates[user_id, template.shape_hash] = template
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO semantic_plans VALUES (?,?,?)",
                (
                    user_id,
                    template.shape_hash,
                    self.codec.seal(asdict(template), user_id, "semantic_plans")
                    if self.codec
                    else json.dumps(asdict(template)),
                ),
            )

    def bind(
        self,
        user_id,
        shape_hash,
        slots,
        capability_vector,
        controller_version,
        schema_version,
    ):
        import shlex

        row = self.db.execute(
            "SELECT payload FROM semantic_plans WHERE owner=? AND shape=?",
            (user_id, shape_hash),
        ).fetchone()
        payload = (
            (
                self.codec.open(row[0], user_id, "semantic_plans")
                if self.codec
                else json.loads(row[0])
            )
            if row
            else None
        )
        template = SemanticPlanTemplate(**payload) if payload else None
        if template is None:
            return None
        if (
            template.capability_vector,
            template.controller_version,
            template.schema_version,
        ) != (capability_vector, controller_version, schema_version):
            return None
        if set(template.required_slots) != set(slots):
            raise ValueError("Every slot must be rebound")
        result = template.parameterized_dsl
        for name, value in slots.items():
            result = result.replace("${" + name + "}", shlex.quote(json.dumps(value)))
        if "${" in result:
            raise ValueError("Unbound slot")
        template.last_used = time.time()
        template.use_count += 1
        self.put_template(user_id, template)
        return result


@dataclass
class CorrectionMatch:
    correction: CorrectionRecord
    relevance_score: float
    scope: str
    evidence: dict
    reason_matched: str


class CorrectionRetriever(Protocol):
    def retrieve(self, query_text, capability_id, user_id, **filters):
        ...


class CorrectionStore:
    def __init__(self, path=":memory:", relevance_threshold=0.6, codec=None):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS corrections (id TEXT PRIMARY KEY, owner TEXT, payload TEXT)"
        )
        self.db.commit()
        self.relevance_threshold = relevance_threshold
        self.codec = codec

    def add_correction(self, record, commit=True):
        record.query_redacted = RedactionPolicy().redact(record.query_redacted)
        for name in (
            "incorrect_decision",
            "verified_correction",
            "user_feedback",
            "verifier_evidence",
        ):
            value = getattr(record, name)
            if value is not None:
                setattr(record, name, RedactionPolicy().redact(value))
        if record.audit_status == AuditStatus.VERIFIED and not record.verifier_evidence:
            raise ValueError("Verified corrections require independent evidence")
        import contextlib

        with self.db if commit else contextlib.nullcontext():
            old = self.db.execute(
                "SELECT owner FROM corrections WHERE id=?", (record.record_id,)
            ).fetchone()
            if old and old[0] != record.user_id:
                raise PermissionError("ACCESS_DENIED")
            self.db.execute(
                "INSERT OR REPLACE INTO corrections VALUES (?,?,?)",
                (
                    record.record_id,
                    record.user_id,
                    self._seal(asdict(record), record.user_id),
                ),
            )

    def _seal(self, payload, owner):
        return (
            self.codec.seal(payload, owner, "corrections")
            if self.codec
            else json.dumps(payload)
        )

    def _open(self, payload, owner):
        return (
            self.codec.open(payload, owner, "corrections")
            if self.codec
            else json.loads(payload)
        )

    def get_correction(self, user_id, record_id):
        row = self.db.execute(
            "SELECT owner,payload FROM corrections WHERE id=?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        if row[0] != user_id:
            raise PermissionError("ACCESS_DENIED")
        return CorrectionRecord(**self._open(row[1], row[0]))

    def get_corrections_for_capability(self, capability_id, user_id="default_user"):
        rows = list(self.db.execute("SELECT owner,payload FROM corrections"))
        records = [
            CorrectionRecord(**self._open(payload, owner))
            for owner, payload in rows
            if owner == user_id or self._is_verified_global(payload, owner)
        ]
        return [
            r
            for r in records
            if r.capability_id == capability_id
            and r.audit_status in (AuditStatus.VERIFIED, AuditStatus.USER_SCOPED)
        ]

    def _is_verified_global(self, payload, owner):
        data = self._open(payload, owner)
        return (
            data.get("scope") == "global"
            and data.get("audit_status") == AuditStatus.VERIFIED.value
        )

    def retrieve(self, query_text, capability_id, user_id, **filters):
        stage = filters.pop("stage", "post")
        words = set(re.findall(r"\w+", RedactionPolicy().redact(query_text).casefold()))
        matches = []
        for r in self.get_corrections_for_capability(capability_id, user_id):
            # Pre-plan only applies broad constraints. Narrow records wait for post-plan metadata.
            narrow = ("semantic_shape", "intent", "tool_versions", "model_version")
            if stage == "pre" and any(getattr(r, k) for k in narrow):
                continue
            if any(
                getattr(r, k) and k not in filters
                for k in (
                    "semantic_shape",
                    "intent",
                    "capability_version",
                    "tool_versions",
                    "controller_version",
                    "model_version",
                )
            ):
                continue
            if any(getattr(r, k) and getattr(r, k) != v for k, v in filters.items()):
                continue
            other = set(re.findall(r"\w+", r.query_redacted.casefold()))
            exact = r.request_fingerprint == request_fingerprint(
                query_text, [capability_id]
            )
            score = (
                1.0
                if exact
                else len(words & other) / len(words | other)
                if words | other
                else 0
            )
            if score >= self.relevance_threshold:
                matches.append(
                    CorrectionMatch(
                        r,
                        score,
                        r.scope,
                        filters,
                        "compatible metadata and request similarity",
                    )
                )
        return sorted(
            matches, key=lambda m: (-m.relevance_score, m.correction.record_id)
        )

    def find_matching_correction(
        self, query_text, capability_id, user_id="default_user", **filters
    ):
        matches = self.retrieve(query_text, capability_id, user_id, **filters)
        return matches[0].correction if matches else None
