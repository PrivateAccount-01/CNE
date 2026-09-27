"""
CNE Cost Gate.
Fast pre-execution filter based on CostClass:
if class_prior_cost(query_class) < THRESHOLD:
    execute directly without running expensive optimizer
else:
    run analyzer
"""
from __future__ import annotations
from typing import Dict
from cne.signature.cost_class import CostClass, CostTier


class CostGate:
    def __init__(self, bypass_trivial: bool = True):
        self.bypass_trivial = bypass_trivial

    def should_optimize(self, cost_class: CostClass) -> bool:
        """
        Fast O(1) gate check. Trivial and lightweight operations execute directly
        to avoid wasting control overhead on sub-millisecond computations.
        """
        if self.bypass_trivial and cost_class.tier in (CostTier.TRIVIAL, CostTier.LIGHTWEIGHT):
            return False
        return True
