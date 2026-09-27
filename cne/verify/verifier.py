"""
CNE Gate G5 Verification and Calibration Model.
Three verification levels:
- Certified: proof, dependency theorem, exact bound, contract invariant.
  Permitted claim: "This node cannot affect the outcome."
- Audited: model score, sampling, historical success.
  Permitted claim: "We predict this can be safely omitted."
- Fallback: full execution. No optimization claim.

Pre-declared statistical rule (Section 36):
Wilson score confidence interval at 95% confidence level.
Acceptance criterion: LB_CI >= 95% for prune correctness over sample floor n >= 460.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Tuple


class VerificationLevel(Enum):
    CERTIFIED = "Certified"
    AUDITED = "Audited"
    FALLBACK = "Fallback"


@dataclass(frozen=True)
class VerificationEvidence:
    level: VerificationLevel
    model_confidence_score: float  # e.g. 0.95
    justification: str

    @property
    def permitted_claim(self) -> str:
        if self.level == VerificationLevel.CERTIFIED:
            return "This node cannot affect the outcome."
        elif self.level == VerificationLevel.AUDITED:
            return "We predict this can be safely omitted."
        return "No optimization claim."


class StatisticalAuditor:
    @staticmethod
    def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
        """
        Computes the Wilson score interval for a binomial proportion.
        For 95% confidence, z = 1.95996.
        """
        if total == 0:
            return (0.0, 0.0)

        # z-score for two-sided confidence
        z = 1.959963984540054  # 95% confidence
        p_hat = successes / total

        denominator = 1.0 + (z ** 2) / total
        centre_adjusted_probability = p_hat + (z ** 2) / (2 * total)
        adjusted_standard_deviation = math.sqrt((p_hat * (1 - p_hat) + (z ** 2) / (4 * total)) / total)

        lower_bound = (centre_adjusted_probability - z * adjusted_standard_deviation) / denominator
        upper_bound = (centre_adjusted_probability + z * adjusted_standard_deviation) / denominator

        return (max(0.0, lower_bound), min(1.0, upper_bound))
