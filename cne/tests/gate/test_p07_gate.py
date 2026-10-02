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
    assert report["hygiene_fix"]["dynamic_runtime_proof_passed"] is True
    assert report["hygiene_fix"]["inverted_adversarial_contamination_verified"] is True
    assert report["hygiene_fix"]["decoupled_protocol"] is True
    assert len(report["hygiene_fix"]["steady_state_trials"]) >= 3
    assert len(report["hygiene_fix"]["session_evolution"]) >= 3
    assert report["semantic_gold_validation"]["topology_routing_accuracy"] >= 0.90
    assert 0.0 < report["coverage_metrics"]["coverage_ratio"] <= 1.0
    assert report["shape_diversity"]["d_passed"] is True
    assert report["shape_diversity"]["d_ratio"] <= 0.40
    assert report["shape_diversity"]["distinct_shapes"] >= 10

    # Multi-domain topology-blind evaluation assertions (Negative Points 1-4)
    assert "open_world_blind_evaluation" in report
    blind_eval = report["open_world_blind_evaluation"]
    assert blind_eval["total_blind_queries"] == 600
    assert len(blind_eval["domains_evaluated"]) == 12
    assert 0.0 <= blind_eval["blind_rejection_rate"] <= 1.0
    assert blind_eval["blind_rejection_rate"] >= 0.70  # Broad multi-domain workload rejection is ~86%
    assert blind_eval["novel_shapes_count"] > 0
    assert blind_eval["novel_shape_rate"] > 0.0
    assert blind_eval["novel_shape_query_mass"] > 0.0
    assert blind_eval["semantically_valid_novel_mass"] > 0.0
    assert blind_eval["misinterpreted_novel_mass"] >= 0.0
    assert len(blind_eval["blind_shapes"]) > 0

    # Multi-session reuse disambiguation
    for s in report["hygiene_fix"]["session_evolution"]:
        assert "reuse_events_per_created_state" in s
        assert s["reuse_events_per_created_state"] == s["state_reuse_ratio"]

    assert report["surface_to_semantic_stability"]["cross_batch_canonicalization"]["stable"] is True
    assert report["surface_to_semantic_stability"]["adversarial_families"]["all_adversarial_passed"] is True
    assert report["extended_gates"]["g0_extended_passed"] is True
    assert report["extended_gates"]["structural_outlier_g0_passed"] is True
    assert report["extended_gates"]["g1b_extended_passed"] is True
    assert report["realistic_co_measurement"]["g2_passed"] is True
    assert report["realistic_co_measurement"]["g3_passed"] is True
    assert report["realistic_co_measurement"]["p3_passed"] is True

    # Verify updated Decision Gate claim text reflects P0.8 coverage expansion
    assert "Surface-to-semantic stability and reuse are confirmed" in report["narrowed_claim"]
    assert "binding constraint on further generalization" in report["narrowed_claim"]
    assert "10 currently-supported topologies" in report["narrowed_claim"]

    # Verify artifacts exist on disk
    json_path = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "reports", "p07_validation_report.json")
    assert os.path.exists(json_path)

    md_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "P07_VALIDATION_REPORT.md")
    assert os.path.exists(md_path)
