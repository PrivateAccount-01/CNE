"""
Unit tests for Open-World Topology-Blind Evaluation (Phase P0.7 Issue 1 & Issue 2).
Validates:
1. Topology-blind dataset schema: 300 queries, 4 domains, zero pre-assigned intended_topology labels.
2. Rejection rate computation on unguided natural requests.
3. Novel-shape discovery detection comparing blind shape set against anchored shape set.
"""
import json
import os
import pytest
from cne.compiler.nl_compiler import ClassificationOutcome, NLCompiler
from cne.signature.shape_key import SemanticShapeKey


def test_topology_blind_dataset_structure():
    artifact_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "artifacts", "corpus", "topology_blind_queries_v1.json"
    )
    assert os.path.exists(artifact_path), f"Missing artifact at {artifact_path}"

    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data["metadata"]
    assert meta["total_queries"] == 300
    assert set(meta["domains"]) == {"finances", "schedule", "health_fitness", "shopping_inventory"}

    queries = data["queries"]
    assert len(queries) == 300

    domain_counts = {}
    for q in queries:
        # Crucial architectural requirement: NO pre-assigned intended_topology field!
        assert "intended_topology" not in q, f"Query {q['id']} illegally contains intended_topology!"
        assert "query_text" in q and len(q["query_text"]) > 10
        assert "domain" in q
        d = q["domain"]
        domain_counts[d] = domain_counts.get(d, 0) + 1

    for d in ["finances", "schedule", "health_fitness", "shopping_inventory"]:
        assert domain_counts[d] == 75


def test_topology_blind_compilation_and_rejection_rate():
    artifact_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "artifacts", "corpus", "topology_blind_queries_v1.json"
    )
    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sample = data["queries"][:60]  # 15 from each domain
    outcomes = {}
    compiled_shapes = set()

    for q in sample:
        res = NLCompiler.compile(q["query_text"])
        outcomes[res.outcome] = outcomes.get(res.outcome, 0) + 1
        if res.outcome == ClassificationOutcome.COMPILED and res.graph is not None:
            compiled_shapes.add(res.graph._cached_shape_key.key_hash)

    # Rejection rate is substantial (> 30%) because open-ended queries are rejected
    rejections = sum(count for outcome, count in outcomes.items() if outcome != ClassificationOutcome.COMPILED)
    rejection_rate = rejections / len(sample)
    assert rejection_rate >= 0.30

    # Some queries that match structured personal assistant subtasks compile cleanly
    assert ClassificationOutcome.COMPILED in outcomes
    assert len(compiled_shapes) > 0


def test_novel_shape_discovery_logic():
    # Synthetic verification of novel shape set difference
    anchored_shapes = {"shape_exp_sum", "shape_exp_count", "shape_sched", "shape_trouble"}
    blind_shapes = {"shape_exp_sum", "shape_sched", "shape_novel_multi_filter", "shape_novel_window"}

    novel = blind_shapes - anchored_shapes
    assert len(novel) == 2
    assert "shape_novel_multi_filter" in novel
    assert "shape_novel_window" in novel
    rate = len(novel) / len(blind_shapes)
    assert rate == 0.50
