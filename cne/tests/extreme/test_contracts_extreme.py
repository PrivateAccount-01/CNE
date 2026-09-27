"""
Module 3: Contract System Extreme Tests.
20 black-box tests pushing every contract type to breaking points —
IEEE 754 traps, NaN, infinity, empty sets, None values, boundary conditions.
"""
import math
import pytest
from cne.contracts.outcome_contract import ContractType, OutcomeContract


# ---------- Exact contract ----------

def test_exact_contract_none_vs_none():
    """None ≡ None under exact contract."""
    c = OutcomeContract(contract_type=ContractType.EXACT)
    assert c.is_equivalent(None, None)


def test_exact_contract_float_precision():
    """0.1 + 0.2 vs 0.3 — IEEE 754 trap. Under EXACT, these must NOT be equal."""
    c = OutcomeContract(contract_type=ContractType.EXACT)
    # 0.1 + 0.2 == 0.30000000000000004 in IEEE 754
    result = c.is_equivalent(0.1 + 0.2, 0.3)
    assert result is False  # Exact contract must fail on float imprecision


# ---------- Set-valued contract ----------

def test_set_valued_empty_sets():
    """Empty set ≡ Empty set."""
    c = OutcomeContract(contract_type=ContractType.SET_VALUED)
    assert c.is_equivalent([], [])


def test_set_valued_nested_dicts():
    """Sets of deeply nested dicts — order-independent."""
    c = OutcomeContract(contract_type=ContractType.SET_VALUED)
    cand = [{"a": {"b": 1}}, {"c": {"d": [2, 3]}}]
    ref = [{"c": {"d": [2, 3]}}, {"a": {"b": 1}}]
    assert c.is_equivalent(cand, ref)


def test_set_valued_none_input():
    """None vs None under set-valued — both None should be equivalent."""
    c = OutcomeContract(contract_type=ContractType.SET_VALUED)
    assert c.is_equivalent(None, None)


# ---------- Approximate numeric ----------

def test_approximate_zero_tolerance():
    """Zero tolerance should behave like exact match."""
    c = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 0.0, "abs_tol": 0.0}
    )
    assert c.is_equivalent(100.0, 100.0)
    assert not c.is_equivalent(100.0, 100.0001)


def test_approximate_huge_tolerance():
    """rel_tol=1.0 (100% tolerance) — very wide tolerance."""
    c = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 1.0, "abs_tol": 0.0}
    )
    # 100% relative tolerance: 100 vs 200 should be equivalent
    assert c.is_equivalent(100.0, 200.0)


def test_approximate_negative_numbers():
    """Negative values with tolerance."""
    c = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 1e-3, "abs_tol": 1e-4}
    )
    assert c.is_equivalent(-100.0, -100.05)
    assert not c.is_equivalent(-100.0, -105.0)


def test_approximate_infinity():
    """inf vs inf under approximate — should be equivalent."""
    c = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 1e-4, "abs_tol": 1e-6}
    )
    assert c.is_equivalent(float("inf"), float("inf"))


def test_approximate_nan():
    """NaN vs NaN — should NOT be equivalent (NaN != NaN by IEEE 754)."""
    c = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 1e-4, "abs_tol": 1e-6}
    )
    result = c.is_equivalent(float("nan"), float("nan"))
    assert result is False  # NaN is never equal to NaN


def test_approximate_dict_mismatch_keys():
    """Dicts with different key sets — should NOT be equivalent."""
    c = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 1e-3, "abs_tol": 1e-4}
    )
    assert not c.is_equivalent({"a": 1.0, "b": 2.0}, {"a": 1.0, "c": 2.0})


# ---------- Decision contract ----------

def test_decision_boundary_exact():
    """Value exactly at decision boundary — should be treated as >= boundary."""
    c = OutcomeContract(contract_type=ContractType.DECISION,
                        decision_boundary=0.5)
    # Both at exactly 0.5 → both >= 0.5 → same decision
    assert c.is_equivalent(0.5, 0.5)
    # One at 0.5 (>=), one at 0.99 (>=) → same decision
    assert c.is_equivalent(0.5, 0.99)
    # One at 0.5 (>=), one at 0.499 (<) → different decision
    assert not c.is_equivalent(0.5, 0.499)


def test_decision_no_boundary():
    """Decision contract without boundary — should fallback to equality."""
    c = OutcomeContract(contract_type=ContractType.DECISION)
    assert c.is_equivalent("approve", "approve")
    assert not c.is_equivalent("approve", "reject")


# ---------- Structured explanation ----------

def test_structured_missing_required_fact():
    """Candidate missing a required fact — should NOT be equivalent."""
    c = OutcomeContract(
        contract_type=ContractType.STRUCTURED_EXPLANATION,
        required_facts={"cause", "action", "severity"}
    )
    cand = {"cause": "disk_full", "action": "clear_cache"}  # missing severity
    ref = {"cause": "disk_full", "action": "clear_cache", "severity": "high"}
    assert not c.is_equivalent(cand, ref)


def test_structured_extra_fields_ok():
    """Extra fields in candidate should be tolerated."""
    c = OutcomeContract(
        contract_type=ContractType.STRUCTURED_EXPLANATION,
        required_facts={"cause"}
    )
    cand = {"cause": "leak", "extra_detail": "lots of info", "debug": True}
    ref = {"cause": "leak"}
    assert c.is_equivalent(cand, ref)


# ---------- No-solution ----------

def test_no_solution_none_both():
    """Both None → both considered insufficient → equivalent."""
    c = OutcomeContract(contract_type=ContractType.NO_SOLUTION)
    assert c.is_equivalent(None, None)


def test_no_solution_false_positive():
    """One insufficient, other has real result → NOT equivalent."""
    c = OutcomeContract(contract_type=ContractType.NO_SOLUTION)
    assert not c.is_equivalent(
        {"status": "insufficient_evidence"},
        {"status": "ok", "result": 42}
    )


# ---------- Custom equivalence ----------

def test_custom_equivalence_fn():
    """Custom acceptable_equivalence overrides all contract logic."""
    c = OutcomeContract(
        contract_type=ContractType.EXACT,
        acceptable_equivalence=lambda a, b: abs(a - b) < 10
    )
    assert c.is_equivalent(100, 105)
    assert not c.is_equivalent(100, 115)


# ---------- Constraints ----------

def test_constraints_all_pass():
    """satisfies_constraints with all passing constraints."""
    c = OutcomeContract(
        contract_type=ContractType.EXACT,
        constraints=[lambda x: x > 0, lambda x: x < 100]
    )
    assert c.satisfies_constraints(50)


def test_constraints_one_fails():
    """satisfies_constraints with one failing constraint."""
    c = OutcomeContract(
        contract_type=ContractType.EXACT,
        constraints=[lambda x: x > 0, lambda x: x < 100]
    )
    assert not c.satisfies_constraints(150)
