"""
CNE Local Utility.
Temporary restricted form of OutcomeContract:
scalar terminal utility + decision boundary.
Used by Choose in early phases.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class LocalUtility:
    utility_fn: Callable[[Dict[str, Any], Dict[str, float]], float]
    decision_boundary: float = 0.0

    def evaluate(self, action: Dict[str, Any], belief: Dict[str, float]) -> float:
        return self.utility_fn(action, belief)

    def is_acceptable(self, utility_val: float) -> bool:
        return utility_val >= self.decision_boundary
