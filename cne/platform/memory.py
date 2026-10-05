"""
CNE Multi-Layer Memory Subsystem.
Implements L1 (Session Store), L2 (Semantic Plan Cache), L4 (Correction/Experience Store),
and L5 (Learning Replay Store) while preserving L3 LocalStateFabric.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class AuditStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


@dataclass
class CorrectionRecord:
    """
    An audited correction record stored in L4.
    Used exclusively as planning constraints or counterexamples. Never returned directly.
    """
    record_id: str
    request_fingerprint: str
    query_redacted: str
    capability_id: str
    model_version: str
    controller_version: str
    error_type: str
    incorrect_decision: str
    verified_correction: str
    user_feedback: Optional[str] = None
    verifier_evidence: Optional[str] = None
    confidence: float = 1.0
    audit_status: AuditStatus = AuditStatus.VERIFIED
    created_at: float = field(default_factory=time.time)
    scope: str = "local_device"


@dataclass
class ExperienceRecord:
    """Raw execution trajectory recorded for auditing and gated replay."""
    experience_id: str
    session_id: str
    query_text: str
    capability_ids: List[str]
    model_id: str
    semantic_dsl: str
    outcome: str
    contract_satisfied: bool
    latency_ms: float
    user_correction_provided: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionState:
    """Structured, persistent state for an ongoing user session (L1)."""
    session_id: str
    user_id: str = "default_user"
    active_capabilities: Set[str] = field(default_factory=set)
    active_entities: Dict[str, Any] = field(default_factory=dict)
    active_goals: List[str] = field(default_factory=list)
    compact_summary: str = ""
    semantic_history: List[Dict[str, Any]] = field(default_factory=list)
    relevant_correction_ids: List[str] = field(default_factory=list)
    token_budget_consumed: int = 0
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)


class SessionStore:
    """
    Manages persistent session continuation (L1).
    Avoids replaying unbounded raw transcripts.
    """

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}

    def get_or_create(self, session_id: str, user_id: str = "default_user") -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id, user_id=user_id)
        return self._sessions[session_id]

    def record_turn(
        self,
        session_id: str,
        user_query: str,
        active_capability: str,
        intent: Optional[str],
        extracted_slots: Dict[str, Any],
        tokens_used: int = 0
    ) -> None:
        sess = self.get_or_create(session_id)
        sess.active_capabilities.add(active_capability)
        sess.active_entities.update(extracted_slots)
        sess.token_budget_consumed += tokens_used
        sess.last_updated = time.time()

        # Append compact history entry (not raw verbosity)
        sess.semantic_history.append({
            "query": user_query[:100],
            "capability": active_capability,
            "intent": intent,
            "timestamp": time.time()
        })
        # Keep sliding history window compact (max 10 turns)
        if len(sess.semantic_history) > 10:
            sess.semantic_history = sess.semantic_history[-10:]

    def close_session(self, session_id: str) -> None:
        if session_id in self._sessions:
            sess = self._sessions[session_id]
            # Formulate compact summary on session close
            sess.compact_summary = f"Session {session_id} ended with {len(sess.semantic_history)} turns. Active: {list(sess.active_capabilities)}"


class SemanticPlanCache:
    """
    L2 Semantic Plan Cache.
    Stores reusable computational DAG shapes parameterized by slot variables.
    """

    def __init__(self):
        self._plan_templates: Dict[str, str] = {}  # shape_hash -> parameterized DSL template

    def put_template(self, shape_hash: str, dsl_template: str) -> None:
        self._plan_templates[shape_hash] = dsl_template

    def get_template(self, shape_hash: str) -> Optional[str]:
        return self._plan_templates.get(shape_hash)


class CorrectionStore:
    """
    L4 Correction & Experience Store.
    Provides fast, immediate learning by retrieving verified constraints for related requests.
    """

    def __init__(self):
        self._corrections: Dict[str, CorrectionRecord] = {}

    def add_correction(self, record: CorrectionRecord) -> None:
        self._corrections[record.record_id] = record

    def get_corrections_for_capability(self, capability_id: str) -> List[CorrectionRecord]:
        return [
            c for c in self._corrections.values()
            if c.capability_id == capability_id and c.audit_status == AuditStatus.VERIFIED
        ]

    def find_matching_correction(self, query_text: str, capability_id: str) -> Optional[CorrectionRecord]:
        """Simple retrieval of relevant counterexamples/constraints."""
        q_tokens = set(query_text.lower().split())
        for c in self.get_corrections_for_capability(capability_id):
            c_tokens = set(c.query_redacted.lower().split())
            overlap = len(q_tokens.intersection(c_tokens))
            if overlap >= 3:
                return c
        return None
