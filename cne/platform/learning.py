"""
CNE Gated Continual Learning & Replay Store (L5).
Implements offline adaptation pipelines, regression evaluation gates, and versioned rollback.

Invariants:
1. Base model weights remain frozen and immutable.
2. Adaptations operate on reversible, parameter-efficient adapters (LoRA / prefix).
3. Candidate activation gates:
   - >= 80% recovery on verified historical errors
   - < 10% repeated error recurrence
   - < 2.0 pp unrelated task regression
   - Zero new permission violations
   - Zero new unsafe state-reuse violations
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cne.platform.memory import ExperienceRecord

logger = logging.getLogger(__name__)


@dataclass
class AdaptationCandidate:
    adapter_id: str
    version: str
    capability_id: str
    target_model_id: str
    training_sample_count: int
    created_at: float = field(default_factory=time.time)


@dataclass
class RegressionEvaluationResult:
    candidate_id: str
    historical_error_recovery_rate: float
    repeated_error_recurrence_rate: float
    unrelated_task_regression_pp: float
    new_permission_violations: int = 0
    new_unsafe_state_reuses: int = 0
    passed: bool = False


class LearningReplayStore:
    """
    L5 Learning Replay Store.
    Curates verified, deduplicated execution trajectories for gated offline adaptation.
    """

    def __init__(self, max_capacity: int = 5000):
        self.max_capacity = max_capacity
        self._records: Dict[str, ExperienceRecord] = {}

    def add_experience(self, exp: ExperienceRecord) -> None:
        if len(self._records) >= self.max_capacity:
            # Evict oldest
            oldest_k = next(iter(self._records))
            del self._records[oldest_k]
        self._records[exp.experience_id] = exp

    def sample_batch(self, capability_id: str, limit: int = 100) -> List[ExperienceRecord]:
        return [
            e for e in self._records.values()
            if capability_id in e.capability_ids
        ][:limit]

    @property
    def total_records(self) -> int:
        return len(self._records)


class GatedAdaptationPipeline:
    """
    Manages candidate adapter generation, regression gate evaluation, and atomic rollback.
    """

    def __init__(self, replay_store: Optional[LearningReplayStore] = None):
        self.replay_store = replay_store or LearningReplayStore()
        self._active_adapters: Dict[str, AdaptationCandidate] = {}
        self._adapter_history: Dict[str, List[AdaptationCandidate]] = {}

    def evaluate_candidate(
        self,
        candidate: AdaptationCandidate,
        historical_recovery: float,
        repeated_recurrence: float,
        unrelated_regression_pp: float,
        permission_violations: int = 0,
        unsafe_reuses: int = 0
    ) -> RegressionEvaluationResult:
        """
        Evaluates a candidate adapter against the non-negotiable regression gates.
        """
        passes = (
            historical_recovery >= 0.80 and
            repeated_recurrence < 0.10 and
            unrelated_regression_pp < 2.0 and
            permission_violations == 0 and
            unsafe_reuses == 0
        )
        return RegressionEvaluationResult(
            candidate_id=candidate.adapter_id,
            historical_error_recovery_rate=historical_recovery,
            repeated_error_recurrence_rate=repeated_recurrence,
            unrelated_task_regression_pp=unrelated_regression_pp,
            new_permission_violations=permission_violations,
            new_unsafe_state_reuses=unsafe_reuses,
            passed=passes
        )

    def deploy_candidate(self, candidate: AdaptationCandidate, eval_result: RegressionEvaluationResult) -> bool:
        """Atomically deploy candidate if regression gate passed."""
        if not eval_result.passed:
            logger.warning(f"Candidate {candidate.adapter_id} failed regression gates. Deployment rejected.")
            return False

        # Archive currently active adapter
        if candidate.capability_id in self._active_adapters:
            prev = self._active_adapters[candidate.capability_id]
            self._adapter_history.setdefault(candidate.capability_id, []).append(prev)

        self._active_adapters[candidate.capability_id] = candidate
        logger.info(f"Deployed adapter {candidate.adapter_id} version {candidate.version}")
        return True

    def rollback_adapter(self, capability_id: str) -> Optional[AdaptationCandidate]:
        """Atomically rollback to prior adapter version."""
        history = self._adapter_history.get(capability_id, [])
        if not history:
            return None
        prior = history.pop()
        self._active_adapters[capability_id] = prior
        logger.info(f"Rolled back {capability_id} to adapter {prior.adapter_id} version {prior.version}")
        return prior
