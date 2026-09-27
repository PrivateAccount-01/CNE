"""
CNE Instrumentation Boundary.
Separate high-resolution timers for:
1. Control (compilation, signature, dependencies, memo lookup, cost gate, analysis, planning, choose)
2. Execution (actual execution of surviving operations)
3. Verification (contract audit, result checks)
4. Persistence (state fabric storage and indexing)

CRITICAL INVARIANT (Section 26):
C_CNE = C_CNE_control + C_CNE_execution (within measurement tolerance).
Control overhead MUST NOT leak into execution time.
"""
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CostBreakdown:
    control_ns: float = 0.0
    execution_ns: float = 0.0
    verification_ns: float = 0.0
    persistence_ns: float = 0.0

    @property
    def total_cne_ns(self) -> float:
        return self.control_ns + self.execution_ns

    def verify_boundary(self, total_measured_ns: float, rel_tol: float = 0.05, abs_tol: float = 2000.0) -> bool:
        """
        Verify that C_CNE = C_control + C_execution within measurement tolerance.
        """
        expected = self.control_ns + self.execution_ns
        return math.isclose(expected, total_measured_ns, rel_tol=rel_tol, abs_tol=abs_tol)


class PrecisionTimer:
    def __init__(self):
        self._start_ns: int = 0
        self._elapsed_ns: float = 0.0

    def start(self) -> None:
        self._start_ns = time.perf_counter_ns()

    def stop(self) -> float:
        now = time.perf_counter_ns()
        self._elapsed_ns += max(0, now - self._start_ns)
        return self._elapsed_ns

    @property
    def elapsed_ns(self) -> float:
        return self._elapsed_ns
