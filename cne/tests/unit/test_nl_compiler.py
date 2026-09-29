"""
Unit tests for CNE Natural Language Task Compiler (NLCompiler).
Validates:
1. 4-way classification outcomes (COMPILED, UNSUPPORTED_INTENT, AMBIGUOUS_INTENT, LOW_CONFIDENCE_MAPPING).
2. Proper instantiation of all 7 topologies including structural outlier.
3. Attachment of canonical descriptors, shape key, and execution policy.
"""
import pytest
from cne.compiler.nl_compiler import ClassificationOutcome, NLCompiler
from cne.semantic_ir.nodes import OpKind


def test_nl_compiler_compiles_7_topologies():
    queries = {
        "expense": "Calculate total food spending over $150",
        "troubleshooting": "Diagnose telemetry alerts on node_4 with error threshold exceeding 10",
        "scheduling": "Schedule a meeting with alice for 45 minutes",
        "habit_fitness": "Log my running workout activity and verify goal of 45 minutes",
        "factual_decision": "Decide on deployment strategy and evaluate options with confidence >= 0.85",
        "recommendation": "Recommend catalog items and suggest top products with rating above 4.5 for user_9",
        "cross_source_join_aggregate": "Reconcile orders and inventory matching stock quantity exceeding 20"
    }

    for expected_intent, text in queries.items():
        res = NLCompiler.compile(text)
        assert res.outcome == ClassificationOutcome.COMPILED, f"Failed for {expected_intent}: {res.reason}"
        assert res.intent == expected_intent
        assert res.graph is not None
        assert res.contract is not None
        assert res.confidence >= NLCompiler.CONFIDENCE_FLOOR
        # Verify compiled metadata
        assert hasattr(res.graph, "_cached_descriptors")
        assert hasattr(res.graph, "_cached_shape_hash")
        assert hasattr(res.graph, "_cached_shape_key")
        assert hasattr(res.graph, "_cached_execution_policy")


def test_nl_compiler_structural_outlier_properties():
    text = "Reconcile orders and inventory cross-reference items where order quantity exceeding 15"
    res = NLCompiler.compile(text)
    assert res.outcome == ClassificationOutcome.COMPILED
    assert res.intent == "cross_source_join_aggregate"
    g = res.graph

    # Verify structural outlier has exactly 2 Observe nodes and 1 Join node
    ops = [n.op for n in g.nodes.values()]
    assert ops.count(OpKind.OBSERVE) == 2
    assert ops.count(OpKind.JOIN) == 1
    assert ops.count(OpKind.FILTER) >= 1
    assert ops.count(OpKind.MAP) >= 1
    assert ops.count(OpKind.REDUCE) >= 1
    assert ops.count(OpKind.EMIT) == 1


def test_nl_compiler_unsupported_domains():
    unsupported_samples = [
        "What is the weather forecast for tomorrow in Paris?",
        "Translate this paragraph into French and German",
        "Buy 100 shares of Apple stock on Nasdaq",
        "Write a poem about the autumn leaves",
        "Generate a photo of a futuristic electric car",
        "Can you write a python script to parse CSV files?",
        "Book a flight from New York to London Heathrow",
        "Give me a recipe for baking chocolate chip cookies"
    ]

    for q in unsupported_samples:
        res = NLCompiler.compile(q)
        assert res.outcome == ClassificationOutcome.UNSUPPORTED_INTENT, f"Expected UNSUPPORTED for '{q}', got {res.outcome}"
        assert res.confidence >= 0.5


def test_nl_compiler_ambiguous_intents():
    # Queries that deliberately blend two distinct domains with comparable weight
    ambiguous_query = "Schedule a meeting with alice to reconcile orders and inventory spending"
    res = NLCompiler.compile(ambiguous_query)
    assert res.outcome == ClassificationOutcome.AMBIGUOUS_INTENT
    assert len(res.competing_intents) >= 2


def test_nl_compiler_low_confidence_mapping():
    # Very vague query with weak keyword match
    vague_query = "check status of some stuff exceeding 5"
    res = NLCompiler.compile(vague_query)
    assert res.outcome in (ClassificationOutcome.LOW_CONFIDENCE_MAPPING, ClassificationOutcome.UNSUPPORTED_INTENT)


def test_nl_compiler_empty_input():
    res = NLCompiler.compile("   ")
    assert res.outcome == ClassificationOutcome.UNSUPPORTED_INTENT
