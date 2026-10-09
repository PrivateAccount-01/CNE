"""
CNE Error Auditor & Error Taxonomy.
Defines the 19 standard ErrorType categories and generates SessionAuditReports.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from cne.platform.memory import (
    AuditStatus,
    CorrectionRecord,
    CorrectionStore,
    ExperienceRecord,
)
from cne.platform.memory import RedactionPolicy, request_fingerprint
import uuid


class ErrorType(str, Enum):
    ROUTING_ERROR = "ROUTING_ERROR"
    INTENT_ERROR = "INTENT_ERROR"
    SLOT_ERROR = "SLOT_ERROR"
    SEMANTIC_PLAN_ERROR = "SEMANTIC_PLAN_ERROR"
    TOOL_SELECTION_ERROR = "TOOL_SELECTION_ERROR"
    TOOL_ARGUMENT_ERROR = "TOOL_ARGUMENT_ERROR"
    MODEL_INFERENCE_ERROR = "MODEL_INFERENCE_ERROR"
    HALLUCINATION = "HALLUCINATION"
    CONTRACT_FAILURE = "CONTRACT_FAILURE"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"
    CACHE_ERROR = "CACHE_ERROR"
    INVALIDATION_ERROR = "INVALIDATION_ERROR"
    FRESHNESS_ERROR = "FRESHNESS_ERROR"
    RESOURCE_ERROR = "RESOURCE_ERROR"
    BACKEND_ERROR = "BACKEND_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    COMPOSITION_ERROR = "COMPOSITION_ERROR"
    LEARNING_REGRESSION = "LEARNING_REGRESSION"
    VERSION_ERROR = "VERSION_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"


@dataclass
class AuditSignal:
    signal_type: str  # e.g., 'user_correction', 'contract_failure', 'tool_exception'
    description: str
    error_type: ErrorType
    confidence: Optional[float] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionAuditReport:
    session_id: str
    total_turns: int
    signals: List[AuditSignal] = field(default_factory=list)
    has_errors: bool = False
    generated_corrections: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class ErrorAuditor:
    """
    Subsystem analyzing execution trajectories, user feedback, and verifier signals
    to classify failures and generate unverified correction candidates (L4).
    """

    def __init__(self, correction_store: Optional[CorrectionStore] = None):
        self.correction_store = correction_store or CorrectionStore()

    def audit_turn(
        self,
        session_id: str,
        query_text: str,
        capability_id: str,
        contract_satisfied: bool,
        user_feedback: Optional[str] = None,
        tool_exception: Optional[Exception] = None,
        verifier_error: Optional[str] = None,
        user_id: str = "default_user",
        controller_version: str = "",
        capability_version: str = "",
        model_version: str = "",
        semantic_shape: str = "",
        intent: str = "",
        tool_versions: Optional[dict] = None,
        fingerprint: str = "",
    ) -> Optional[AuditSignal]:
        """Classify signals from a turn into an AuditSignal."""
        if tool_exception is not None:
            return AuditSignal(
                signal_type="tool_exception",
                description=str(tool_exception),
                error_type=ErrorType.TOOL_ARGUMENT_ERROR,
                evidence={"exception": str(tool_exception)},
            )

        if not contract_satisfied or verifier_error:
            return AuditSignal(
                signal_type="contract_failure",
                description=verifier_error or "Outcome Contract violated",
                error_type=ErrorType.CONTRACT_FAILURE,
                evidence={"verifier_error": verifier_error},
            )

        if user_feedback:
            # User correction provided -> candidate for fast learning
            signal = AuditSignal(
                signal_type="user_correction",
                description=user_feedback,
                error_type=ErrorType.SLOT_ERROR
                if "amount" in user_feedback or "category" in user_feedback
                else ErrorType.INTENT_ERROR,
                evidence={"feedback": user_feedback},
            )
            # Feedback is evidence of disagreement, not independent verification.
            rec = CorrectionRecord(
                record_id=f"corr_{uuid.uuid4().hex}",
                request_fingerprint=fingerprint
                or request_fingerprint(query_text, [capability_id]),
                query_redacted=RedactionPolicy().redact(query_text),
                capability_id=capability_id,
                model_version=model_version,
                controller_version=controller_version,
                capability_version=capability_version,
                semantic_shape=semantic_shape,
                intent=intent,
                tool_versions=tool_versions or {},
                error_type=signal.error_type.value,
                incorrect_decision="model_output",
                verified_correction=RedactionPolicy().redact(user_feedback),
                user_feedback=RedactionPolicy().redact(user_feedback),
                audit_status=AuditStatus.UNVERIFIED,
                user_id=user_id,
            )
            self.correction_store.add_correction(rec)
            return signal

        return None

    def generate_session_report(
        self, session_id: str, signals: List[AuditSignal], total_turns: int
    ) -> SessionAuditReport:
        has_errs = len(signals) > 0
        return SessionAuditReport(
            session_id=session_id,
            total_turns=total_turns,
            signals=signals,
            has_errors=has_errs,
            generated_corrections=[
                s.description for s in signals if s.signal_type == "user_correction"
            ],
        )
