"""
CNE Outcome Contract.
Defines what constitutes an admissible/equivalent result under contract equivalence (A ≡_C B).
Supports: Exact, Set-valued, Approximate numeric, Decision, Structured explanation, and No-solution.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set, Union
import math


class ContractType(Enum):
    EXACT = auto()
    SET_VALUED = auto()
    APPROXIMATE_NUMERIC = auto()
    DECISION = auto()
    STRUCTURED_EXPLANATION = auto()
    NO_SOLUTION = auto()


@dataclass
class OutcomeContract:
    contract_type: ContractType
    output_schema: Optional[Dict[str, Any]] = None
    required_facts: Set[str] = field(default_factory=set)
    constraints: List[Callable[[Any], bool]] = field(default_factory=list)
    tolerances: Dict[str, float] = field(default_factory=dict)  # e.g. {"rel_tol": 1e-4, "abs_tol": 1e-6}
    decision_boundary: Optional[float] = None
    acceptable_equivalence: Optional[Callable[[Any, Any], bool]] = None
    provenance_requirements: Optional[Dict[str, Any]] = None

    def is_equivalent(self, candidate: Any, reference: Any) -> bool:
        """
        Evaluate contract equivalence: candidate ≡_C reference.
        """
        # Custom user equivalence function if provided
        if self.acceptable_equivalence:
            return self.acceptable_equivalence(candidate, reference)

        if self.contract_type == ContractType.EXACT:
            return candidate == reference

        elif self.contract_type == ContractType.SET_VALUED:
            if candidate is None or reference is None:
                return candidate == reference
            # Compare collections as sets (or sets of frozen dict items)
            def canonicalize_item(x):
                if isinstance(x, dict):
                    return tuple(sorted((k, canonicalize_item(v)) for k, v in x.items()))
                elif isinstance(x, (list, tuple)):
                    return tuple(canonicalize_item(i) for i in x)
                return x

            cand_set = {canonicalize_item(x) for x in candidate}
            ref_set = {canonicalize_item(x) for x in reference}
            return cand_set == ref_set

        elif self.contract_type == ContractType.APPROXIMATE_NUMERIC:
            rel_tol = self.tolerances.get("rel_tol", 1e-4)
            abs_tol = self.tolerances.get("abs_tol", 1e-6)
            if isinstance(candidate, (int, float)) and isinstance(reference, (int, float)):
                return math.isclose(float(candidate), float(reference), rel_tol=rel_tol, abs_tol=abs_tol)
            elif isinstance(candidate, dict) and isinstance(reference, dict):
                if set(candidate.keys()) != set(reference.keys()):
                    return False
                for k in candidate:
                    cv = candidate[k]
                    rv = reference[k]
                    if isinstance(cv, (int, float)) and isinstance(rv, (int, float)):
                        if not math.isclose(float(cv), float(rv), rel_tol=rel_tol, abs_tol=abs_tol):
                            return False
                    elif cv != rv:
                        return False
                return True
            return candidate == reference

        elif self.contract_type == ContractType.DECISION:
            # Check decision agreement
            if self.decision_boundary is not None:
                cand_decision = candidate >= self.decision_boundary if isinstance(candidate, (int, float)) else candidate
                ref_decision = reference >= self.decision_boundary if isinstance(reference, (int, float)) else reference
                return cand_decision == ref_decision
            return candidate == reference

        elif self.contract_type == ContractType.STRUCTURED_EXPLANATION:
            if not isinstance(candidate, dict) or not isinstance(reference, dict):
                return candidate == reference
            # Required facts must remain present
            for fact in self.required_facts:
                if fact not in candidate:
                    return False
                if candidate[fact] != reference.get(fact):
                    return False
            return True

        elif self.contract_type == ContractType.NO_SOLUTION:
            # Both must agree on explicit insufficiency
            cand_is_insufficient = (candidate is None) or (isinstance(candidate, dict) and candidate.get("status") == "insufficient_evidence")
            ref_is_insufficient = (reference is None) or (isinstance(reference, dict) and reference.get("status") == "insufficient_evidence")
            return cand_is_insufficient == ref_is_insufficient

        return candidate == reference

    def satisfies_constraints(self, candidate: Any) -> bool:
        for c in self.constraints:
            if not c(candidate):
                return False
        return True
