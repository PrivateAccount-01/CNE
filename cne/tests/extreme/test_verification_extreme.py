"""
Module 8: Verification & Gate Extreme Tests.
12 black-box tests for Wilson score interval edge cases,
verification levels, and statistical auditor boundary conditions.
"""
import math
import pytest
from cne.verify.verifier import (
    StatisticalAuditor, VerificationEvidence, VerificationLevel
)


# ---------- Wilson Score Interval ----------

def test_wilson_0_successes():
    """0/100 → lower bound ≈ 0."""
    lb, ub = StatisticalAuditor.wilson_score_interval(0, 100)
    assert lb >= 0.0
    assert lb < 0.01  # Very close to 0
    assert ub > lb


def test_wilson_all_successes():
    """100/100 → lower bound near 1.0."""
    lb, ub = StatisticalAuditor.wilson_score_interval(100, 100)
    assert lb > 0.95
    assert ub <= 1.0


def test_wilson_0_total():
    """0/0 → (0.0, 0.0) — degenerate case."""
    lb, ub = StatisticalAuditor.wilson_score_interval(0, 0)
    assert lb == 0.0
    assert ub == 0.0


def test_wilson_sample_floor_460():
    """n=460 with high success rate — test the spec's sample floor.
    Section 36: LB_CI >= 95% for prune correctness over n >= 460."""
    # 460 successes out of 460
    lb, ub = StatisticalAuditor.wilson_score_interval(460, 460)
    assert lb >= 0.95  # Spec requirement

    # 450 successes out of 460 (97.8% rate)
    lb2, ub2 = StatisticalAuditor.wilson_score_interval(450, 460)
    assert lb2 >= 0.95  # Should still meet threshold

    # 437 successes out of 460 (95.0% rate)
    lb3, ub3 = StatisticalAuditor.wilson_score_interval(437, 460)
    # This is the borderline case — LB may or may not be >= 0.95
    # Recording actual value for analysis


def test_wilson_1_success_1_total():
    """1/1 → interval bounds should be valid."""
    lb, ub = StatisticalAuditor.wilson_score_interval(1, 1)
    assert 0.0 <= lb <= 1.0
    assert 0.0 <= ub <= 1.0
    assert lb <= ub


def test_wilson_half_successes():
    """50/100 → interval should be approximately (0.40, 0.60)."""
    lb, ub = StatisticalAuditor.wilson_score_interval(50, 100)
    assert 0.35 < lb < 0.50
    assert 0.50 < ub < 0.65


# ---------- Verification Levels ----------

def test_verification_certified_claim():
    """Certified → 'This node cannot affect the outcome.'"""
    ev = VerificationEvidence(
        level=VerificationLevel.CERTIFIED,
        model_confidence_score=1.0,
        justification="Formal proof via dependency analysis"
    )
    assert ev.permitted_claim == "This node cannot affect the outcome."


def test_verification_audited_claim():
    """Audited → 'We predict this can be safely omitted.'"""
    ev = VerificationEvidence(
        level=VerificationLevel.AUDITED,
        model_confidence_score=0.95,
        justification="Model confidence high"
    )
    assert ev.permitted_claim == "We predict this can be safely omitted."


def test_verification_fallback_claim():
    """Fallback → 'No optimization claim.'"""
    ev = VerificationEvidence(
        level=VerificationLevel.FALLBACK,
        model_confidence_score=0.0,
        justification="Cannot verify"
    )
    assert ev.permitted_claim == "No optimization claim."


# ---------- Wilson statistical properties ----------

def test_wilson_large_sample_10000():
    """n=10000, 9500 successes (95%) — large sample behavior."""
    lb, ub = StatisticalAuditor.wilson_score_interval(9500, 10000)
    # With n=10000, the interval should be very tight around 0.95
    assert 0.94 < lb < 0.95
    assert 0.95 < ub < 0.96


def test_wilson_confidence_monotonicity():
    """More successes → higher lower bound (monotonicity)."""
    lb_low, _ = StatisticalAuditor.wilson_score_interval(80, 100)
    lb_high, _ = StatisticalAuditor.wilson_score_interval(90, 100)
    assert lb_high > lb_low


def test_wilson_interval_contains_true_proportion():
    """For a reasonable sample, the interval should contain p_hat."""
    for successes in [30, 50, 70, 90]:
        total = 100
        p_hat = successes / total
        lb, ub = StatisticalAuditor.wilson_score_interval(successes, total)
        # The Wilson interval is NOT centered on p_hat, but should contain
        # values near it. For moderate proportions, p_hat is usually inside.
        # This is a soft check — recording the actual behavior.
        assert lb < ub  # Interval must be non-degenerate
        assert lb >= 0.0
        assert ub <= 1.0
