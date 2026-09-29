"""
Automated Gate Test for Phase P0.7: Realistic Language & Shape Validation.
Validates the complete 10-step sequence and decision gate outcome.
"""
import os
import pytest
from cne.bench.p07_report import P07ReportRunner


def test_p07_master_decision_gate():
    report = P07ReportRunner.run_p07_evaluation()

    assert report["decision"] == "GO", f"Expected GO decision, got {report['decision']}"
    assert report["decision_passed"] is True
    assert report["hygiene_fix"]["step_0_verified"] is True
    assert report["coverage_metrics"]["coverage_ratio"] >= 0.75
    assert report["shape_diversity"]["d_passed"] is True
    assert report["shape_diversity"]["d_ratio"] <= 0.40
    assert report["surface_to_semantic_stability"]["cross_batch_canonicalization"]["stable"] is True
    assert report["surface_to_semantic_stability"]["adversarial_families"]["all_adversarial_passed"] is True
    assert report["extended_gates"]["g0_extended_passed"] is True
    assert report["extended_gates"]["structural_outlier_g0_passed"] is True
    assert report["extended_gates"]["g1b_extended_passed"] is True
    assert report["realistic_co_measurement"]["g2_passed"] is True
    assert report["realistic_co_measurement"]["g3_passed"] is True
    assert report["realistic_co_measurement"]["p3_passed"] is True

    # Verify artifacts exist on disk
    json_path = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "reports", "p07_validation_report.json")
    assert os.path.exists(json_path)

    md_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "P07_VALIDATION_REPORT.md")
    assert os.path.exists(md_path)
