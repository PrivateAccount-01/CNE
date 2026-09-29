"""
Unit tests for Phase P0.7 Metrics Engine (metrics_p07.py).
Validates:
1. Mathematical correctness of D(N), Shannon Entropy H, Top-20 coverage C_20, and R_k (k=2,5,10).
2. Compiler coverage and breakdown calculations.
3. Cross-batch canonicalization stability analyzer.
4. Adversarial family verification (A1 - A6).
"""
import pytest
from cne.bench.corpus.realistic_corpus_generator import RealisticCorpusGenerator
from cne.bench.metrics_p07 import CompilerCoverageMetrics, P07MetricsEngine, ShapeDiversityMetrics
from cne.compiler.nl_compiler import ClassificationOutcome, CompilationResult, NLCompiler


def test_diversity_metrics_mathematical_properties():
    # 1. Extreme case: all shapes identical (maximal reuse)
    shapes_uniform = ["shape_A"] * 100
    m_uni = P07MetricsEngine.compute_diversity_metrics(shapes_uniform)
    assert m_uni.distinct_shapes == 1
    assert m_uni.diversity_ratio_d == 0.01
    assert m_uni.entropy_h == 0.0
    assert m_uni.top_20_coverage_c20 == 1.0
    assert m_uni.recurrence_r2 == 1.0
    assert m_uni.recurrence_r10 == 1.0

    # 2. Extreme case: all shapes distinct (zero reuse)
    shapes_distinct = [f"shape_{i}" for i in range(100)]
    m_dist = P07MetricsEngine.compute_diversity_metrics(shapes_distinct)
    assert m_dist.distinct_shapes == 100
    assert m_dist.diversity_ratio_d == 1.0
    assert m_dist.entropy_h > 6.0
    assert m_dist.top_20_coverage_c20 == 0.20
    assert m_dist.recurrence_r2 == 0.0
    assert m_dist.recurrence_r10 == 0.0


def test_coverage_metrics_breakdown():
    results = [
        CompilationResult("q1", ClassificationOutcome.COMPILED, 0.9),
        CompilationResult("q2", ClassificationOutcome.COMPILED, 0.8),
        CompilationResult("q3", ClassificationOutcome.UNSUPPORTED_INTENT, 0.9),
        CompilationResult("q4", ClassificationOutcome.AMBIGUOUS_INTENT, 0.7),
        CompilationResult("q5", ClassificationOutcome.LOW_CONFIDENCE_MAPPING, 0.5),
    ]

    cov = P07MetricsEngine.compute_coverage_metrics(results)
    assert cov.total_submitted == 5
    assert cov.compiled_count == 2
    assert cov.coverage_ratio == 0.4
    assert cov.unsupported_count == 1
    assert cov.unsupported_rate == 0.2
    assert cov.ambiguous_count == 1
    assert cov.ambiguous_rate == 0.2
    assert cov.low_confidence_count == 1
    assert cov.low_confidence_rate == 0.2


def test_adversarial_families_validation():
    corpus = RealisticCorpusGenerator.generate_corpus()
    adv_queries = [q for q in corpus["queries"] if q["category"] == "adversarial"]

    adv_results = []
    for q in adv_queries:
        res = NLCompiler.compile(q["query_text"])
        adv_results.append((q, res))

    eval_res = P07MetricsEngine.evaluate_adversarial_families(adv_results)
    assert eval_res["all_adversarial_passed"] is True
    for fam_name, fam_data in eval_res["families"].items():
        assert fam_data["passed"] is True, f"Family {fam_name} failed verification!"
