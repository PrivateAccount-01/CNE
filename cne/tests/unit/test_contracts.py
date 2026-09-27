"""
Unit tests for all 6 OutcomeContract types:
- Exact
- Set-valued
- Approximate numeric
- Decision
- Structured explanation
- No-solution
"""
import pytest
from cne.contracts.outcome_contract import ContractType, OutcomeContract


def test_exact_contract():
    c = OutcomeContract(contract_type=ContractType.EXACT)
    assert c.is_equivalent(17 * 43, 731)
    assert not c.is_equivalent(17 * 43, 730)


def test_set_valued_contract():
    c = OutcomeContract(contract_type=ContractType.SET_VALUED)
    # Order-independent collection equivalence
    cand = [{"id": 1, "val": "A"}, {"id": 2, "val": "B"}]
    ref = [{"id": 2, "val": "B"}, {"id": 1, "val": "A"}]
    diff = [{"id": 1, "val": "A"}]
    assert c.is_equivalent(cand, ref)
    assert not c.is_equivalent(cand, diff)


def test_approximate_numeric_contract():
    c = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 1e-3, "abs_tol": 1e-4}
    )
    assert c.is_equivalent(100.0, 100.05)
    assert not c.is_equivalent(100.0, 105.0)


def test_decision_contract():
    c = OutcomeContract(contract_type=ContractType.DECISION, decision_boundary=0.5)
    assert c.is_equivalent(0.8, 0.9)  # Both >= 0.5 (same decision)
    assert c.is_equivalent(0.1, 0.2)  # Both < 0.5 (same decision)
    assert not c.is_equivalent(0.8, 0.2)  # Different decision


def test_structured_explanation_contract():
    c = OutcomeContract(
        contract_type=ContractType.STRUCTURED_EXPLANATION,
        required_facts={"cause", "action"}
    )
    cand = {"cause": "disk_full", "action": "clear_cache", "wording": "Disk reached 99%"}
    ref = {"cause": "disk_full", "action": "clear_cache", "wording": "System alert: storage full"}
    diff = {"cause": "network_down", "action": "clear_cache"}
    assert c.is_equivalent(cand, ref)
    assert not c.is_equivalent(cand, diff)


def test_no_solution_contract():
    c = OutcomeContract(contract_type=ContractType.NO_SOLUTION)
    assert c.is_equivalent({"status": "insufficient_evidence"}, {"status": "insufficient_evidence"})
    assert not c.is_equivalent({"status": "insufficient_evidence"}, {"status": "ok", "result": 10})
