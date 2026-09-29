"""
Unit tests for SemanticGoldEvaluator (Phase P0.7 Revision 3).
Validates:
1. Confusion matrix computation across all 4 classification outcomes.
2. Precision, Recall, and F1 per class.
3. Topology routing accuracy against ground-truth intended topology.
4. Slot extraction accuracy.
"""
import pytest
from cne.bench.corpus.realistic_corpus_generator import RealisticCorpusGenerator
from cne.bench.semantic_gold_evaluator import SemanticGoldEvaluator
from cne.compiler.nl_compiler import ClassificationOutcome, CompilationResult, NLCompiler


def test_semantic_gold_confusion_matrix_perfect():
    # Synthetic perfect case
    items = [
        ({"expected_classification": "COMPILED", "intended_topology": "expense", "slots": {"category": "Food"}},
         CompilationResult("q1", ClassificationOutcome.COMPILED, 0.9, intent="expense", extracted_slots={"category": "Food"})),
        ({"expected_classification": "UNSUPPORTED_INTENT", "intended_topology": "none", "slots": {}},
         CompilationResult("q2", ClassificationOutcome.UNSUPPORTED_INTENT, 0.9, intent=None, extracted_slots={})),
        ({"expected_classification": "AMBIGUOUS_INTENT", "intended_topology": "none", "slots": {}},
         CompilationResult("q3", ClassificationOutcome.AMBIGUOUS_INTENT, 0.7, intent=None, extracted_slots={})),
        ({"expected_classification": "LOW_CONFIDENCE_MAPPING", "intended_topology": "none", "slots": {}},
         CompilationResult("q4", ClassificationOutcome.LOW_CONFIDENCE_MAPPING, 0.4, intent=None, extracted_slots={})),
    ]

    report = SemanticGoldEvaluator.evaluate(items)
    assert report.total_evaluated == 4
    assert report.overall_accuracy == 1.0
    for outcome in SemanticGoldEvaluator.OUTCOMES:
        metrics = report.class_metrics[outcome]
        assert metrics.precision == 1.0
        assert metrics.recall == 1.0
        assert metrics.f1 == 1.0
    assert report.topology_routing_accuracy == 1.0
    assert report.slot_extraction_accuracy == 1.0


def test_semantic_gold_slot_mismatch_and_misclassification():
    items = [
        # Predicted COMPILED, but expected UNSUPPORTED (False Positive for COMPILED)
        ({"expected_classification": "UNSUPPORTED_INTENT", "intended_topology": "none", "slots": {}},
         CompilationResult("q1", ClassificationOutcome.COMPILED, 0.8, intent="expense", extracted_slots={})),
        # Predicted COMPILED with wrong topology (Routing error)
        ({"expected_classification": "COMPILED", "intended_topology": "expense", "slots": {"category": "Food"}},
         CompilationResult("q2", ClassificationOutcome.COMPILED, 0.85, intent="troubleshooting", extracted_slots={"system_id": "node_1"})),
        # Predicted COMPILED with correct topology, but mismatched slot value
        ({"expected_classification": "COMPILED", "intended_topology": "expense", "slots": {"category": "Food", "threshold": 100.0}},
         CompilationResult("q3", ClassificationOutcome.COMPILED, 0.9, intent="expense", extracted_slots={"category": "Travel", "threshold": 100.0})),
    ]

    report = SemanticGoldEvaluator.evaluate(items)
    assert report.total_evaluated == 3
    assert report.overall_accuracy < 1.0
    # COMPILED class has 2 TP (q2 and q3 expected COMPILED, both predicted COMPILED), 1 FP (q1)
    compiled_m = report.class_metrics["COMPILED"]
    assert compiled_m.tp == 2
    assert compiled_m.fp == 1
    # Routing accuracy: 1 out of 2 expected-compiled had correct topology (q3)
    assert report.topology_routing_accuracy == 0.5
    # Slot accuracy: 1 out of 2 evaluated slots correct for q3
    assert 0.0 < report.slot_extraction_accuracy < 1.0


def test_semantic_gold_full_corpus_sample():
    corpus = RealisticCorpusGenerator.generate_corpus()
    sample_queries = corpus["queries"][:100]

    eval_items = []
    for q in sample_queries:
        res = NLCompiler.compile(q["query_text"])
        eval_items.append((q, res))

    report = SemanticGoldEvaluator.evaluate(eval_items)
    assert report.total_evaluated == 100
    assert report.overall_accuracy > 0.80
    assert report.topology_routing_accuracy > 0.90
    assert report.slot_extraction_accuracy > 0.60

    report_dict = report.to_dict()
    assert "confusion_matrix" in report_dict
    assert "class_metrics" in report_dict
    assert "topology_routing_accuracy" in report_dict
