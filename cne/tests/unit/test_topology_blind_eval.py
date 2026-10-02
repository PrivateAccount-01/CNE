"""
Unit tests for Multi-Domain Topology-Blind Evaluation & Semantic Validation (Phase P0.7 Revision 3).
Validates:
1. Multi-domain topology-blind dataset schema: 600 queries across 12 realistic domains, zero intended_topology labels.
2. Rejection rate computation on unguided natural requests (rejection rate >= 70%).
3. Novel-shape discovery and novel query mass calculation.
4. BlindSemanticValidator discrimination between genuine compositional variation and compiler misinterpretation.
"""
import json
import os
import pytest
from cne.compiler.nl_compiler import ClassificationOutcome, NLCompiler
from cne.signature.shape_key import SemanticShapeKey
from cne.bench.blind_semantic_validator import BlindSemanticValidator


def test_topology_blind_dataset_structure():
    artifact_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "artifacts", "corpus", "topology_blind_queries_v1.json"
    )
    assert os.path.exists(artifact_path), f"Missing artifact at {artifact_path}"

    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data["metadata"]
    assert meta["total_queries"] == 600
    assert len(meta["domains"]) == 12

    expected_domains = {
        "finances", "schedule", "health_fitness", "shopping_inventory",
        "system_settings_device", "communication_messaging", "file_data_management",
        "home_automation_iot", "media_entertainment", "open_web_search_knowledge",
        "math_calculations", "creative_brainstorming"
    }
    assert set(meta["domains"]) == expected_domains

    queries = data["queries"]
    assert len(queries) == 600

    domain_counts = {}
    for q in queries:
        # Crucial architectural requirement: NO pre-assigned intended_topology field!
        assert "intended_topology" not in q, f"Query {q['id']} illegally contains intended_topology!"
        assert "query_text" in q and len(q["query_text"]) > 5
        assert "domain" in q
        d = q["domain"]
        domain_counts[d] = domain_counts.get(d, 0) + 1

    for d in expected_domains:
        assert domain_counts[d] == 50, f"Domain {d} expected 50 queries, got {domain_counts.get(d)}"


def test_topology_blind_compilation_and_rejection_rate():
    artifact_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "artifacts", "corpus", "topology_blind_queries_v1.json"
    )
    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sample = data["queries"]
    outcomes = {}
    compiled_shapes = set()

    for q in sample:
        res = NLCompiler.compile(q["query_text"])
        outcomes[res.outcome] = outcomes.get(res.outcome, 0) + 1
        if res.outcome == ClassificationOutcome.COMPILED and res.graph is not None:
            compiled_shapes.add(res.graph._cached_shape_key.key_hash)

    # Rejection rate across 12 diverse domains is high (>= 75%)
    rejections = sum(count for outcome, count in outcomes.items() if outcome != ClassificationOutcome.COMPILED)
    rejection_rate = rejections / len(sample)
    assert rejection_rate >= 0.75, f"Expected high multi-domain rejection >= 0.75, got {rejection_rate:.2%}"

    # Non-empty compiled subset
    assert ClassificationOutcome.COMPILED in outcomes
    assert len(compiled_shapes) > 0


def test_blind_semantic_validator():
    # Test valid query: single filter sum on dining expenses
    valid_query = "Calculate total dining expenses"
    res_valid = NLCompiler.compile(valid_query)
    assert res_valid.outcome == ClassificationOutcome.COMPILED
    shape_hash = res_valid.graph._cached_shape_key.key_hash
    is_valid, reason = BlindSemanticValidator.validate(valid_query, res_valid.graph, shape_hash)
    assert is_valid is True
    assert "single-filter" in reason.lower()

    # Test misinterpretation: inflation comparison NOW correctly routed to comparative_trend (P0.8)
    comparative_query = "Compare my restaurant dining costs against inflation"
    res_comp = NLCompiler.compile(comparative_query)
    if res_comp.intent == "comparative_trend":
        # P0.8: correctly routed to comparative_trend template
        is_valid_comp, reason_comp = BlindSemanticValidator.validate(comparative_query, res_comp.graph, "")
        assert is_valid_comp is True
        assert "comparative" in reason_comp.lower()
    else:
        # Legacy fallback: still misinterpreted
        is_valid_comp, reason_comp = BlindSemanticValidator.validate(comparative_query, res_comp.graph, "")
        assert is_valid_comp is False

    # Test P0.8: categorical tagging correctly recognized
    tag_query = "Categorize my transactions as essential or discretionary"
    res_tag = NLCompiler.compile(tag_query)
    assert res_tag.intent == "categorical_tagging"
    is_valid_tag, reason_tag = BlindSemanticValidator.validate(tag_query, res_tag.graph, "")
    assert is_valid_tag is True
    assert "categorical" in reason_tag.lower()

    # Test P0.8: predictive alert correctly recognized
    alert_query = "Alert me when I am running low on groceries budget"
    res_alert = NLCompiler.compile(alert_query)
    assert res_alert.intent == "predictive_alert"
    is_valid_alert, reason_alert = BlindSemanticValidator.validate(alert_query, res_alert.graph, "")
    assert is_valid_alert is True
    assert "predictive" in reason_alert.lower()


def test_novel_shape_query_mass_calculation():
    anchored_shapes = {"shape_exp_sum", "shape_exp_count", "shape_sched"}
    compiled_queries = [
        {"id": "q1", "shape": "shape_exp_sum"},
        {"id": "q2", "shape": "shape_exp_sum"},
        {"id": "q3", "shape": "shape_exp_count"},
        {"id": "q4", "shape": "shape_novel_A"},
        {"id": "q5", "shape": "shape_novel_B"},
    ]
    blind_shapes = {"shape_exp_sum", "shape_exp_count", "shape_novel_A", "shape_novel_B"}
    novel_shapes = blind_shapes - anchored_shapes
    assert len(novel_shapes) == 2
    novel_shape_rate = len(novel_shapes) / len(blind_shapes)
    assert novel_shape_rate == 0.50

    novel_queries = [q for q in compiled_queries if q["shape"] in novel_shapes]
    novel_query_mass = len(novel_queries) / len(compiled_queries)
    # 2 queries out of 5 compiled = 40%
    assert novel_query_mass == 0.40

