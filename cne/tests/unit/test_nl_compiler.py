"""
Unit tests for CNE Natural Language Task Compiler (NLCompiler).
Validates:
1. 4-way classification outcomes (COMPILED, UNSUPPORTED_INTENT, AMBIGUOUS_INTENT, LOW_CONFIDENCE_MAPPING).
2. Proper instantiation of all 10 topologies including structural outlier and P0.8 templates.
3. Attachment of canonical descriptors, shape key, and execution policy.
4. P0.8 slot extraction bug fixes (duration/percentage misinterpretation).
5. P0.8 specificity disambiguation (derived intents override parent intents).
"""
import pytest
from cne.compiler.nl_compiler import ClassificationOutcome, NLCompiler
from cne.semantic_ir.nodes import OpKind


def test_nl_compiler_compiles_10_topologies():
    queries = {
        "expense": "Calculate total food spending over $150",
        "troubleshooting": "Diagnose telemetry alerts on node_4 with error threshold exceeding 10",
        "scheduling": "Schedule a meeting with alice for 45 minutes",
        "habit_fitness": "Log my running workout activity and verify goal of 45 minutes",
        "factual_decision": "Decide on deployment strategy and evaluate options with confidence >= 0.85",
        "recommendation": "Recommend catalog items and suggest top products with rating above 4.5 for user_9",
        "cross_source_join_aggregate": "Reconcile orders and inventory matching stock quantity exceeding 20",
        "comparative_trend": "Compare my food spending this month versus last month",
        "predictive_alert": "Alert me when I am running low on groceries budget",
        "categorical_tagging": "Categorize my transactions as essential or discretionary",
    }

    for expected_intent, text in queries.items():
        res = NLCompiler.compile(text)
        assert res.outcome == ClassificationOutcome.COMPILED, f"Failed for {expected_intent}: {res.reason}"
        assert res.intent == expected_intent, f"Expected intent {expected_intent}, got {res.intent}"
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


def test_nl_compiler_comparative_trend_properties():
    """P0.8: Verify comparative_trend fixture has dual-pipeline topology."""
    text = "Compare my food spending this month versus last month"
    res = NLCompiler.compile(text)
    assert res.outcome == ClassificationOutcome.COMPILED
    assert res.intent == "comparative_trend"
    g = res.graph
    ops = [n.op for n in g.nodes.values()]
    assert ops.count(OpKind.OBSERVE) == 2, "Comparative trend needs dual observation"
    assert ops.count(OpKind.JOIN) == 1, "Comparative trend needs join to combine periods"
    assert ops.count(OpKind.REDUCE) >= 2, "Comparative trend needs at least 2 reduces (one per period)"


def test_nl_compiler_predictive_alert_properties():
    """P0.8: Verify predictive_alert fixture has projection + branch topology."""
    text = "Alert me when I am running low on groceries budget"
    res = NLCompiler.compile(text)
    assert res.outcome == ClassificationOutcome.COMPILED
    assert res.intent == "predictive_alert"
    g = res.graph
    ops = [n.op for n in g.nodes.values()]
    assert OpKind.BRANCH in ops, "Predictive alert needs a branch for threshold check"
    assert ops.count(OpKind.MAP) >= 2, "Predictive alert needs map for projection"


def test_nl_compiler_categorical_tagging_properties():
    """P0.8: Verify categorical_tagging fixture has classify + group topology."""
    text = "Categorize my transactions as essential or discretionary"
    res = NLCompiler.compile(text)
    assert res.outcome == ClassificationOutcome.COMPILED
    assert res.intent == "categorical_tagging"
    g = res.graph
    ops = [n.op for n in g.nodes.values()]
    assert OpKind.MAP in ops, "Categorical tagging needs map for classification"
    assert OpKind.REDUCE in ops, "Categorical tagging needs reduce for group accumulation"


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


# === P0.8 Slot Extraction Bug Fixes ===

def test_slot_extraction_duration_not_misinterpreted_as_threshold():
    """P0.8 fix: '90 days' should NOT be extracted as threshold=$90."""
    res = NLCompiler.compile("Show my food spending in the last 90 days")
    assert res.outcome == ClassificationOutcome.COMPILED
    assert res.extracted_slots.get("threshold") != 90.0, \
        f"Duration '90 days' was incorrectly extracted as threshold={res.extracted_slots.get('threshold')}"


def test_slot_extraction_percentage_not_misinterpreted_as_threshold():
    """P0.8 fix: '15%' or '15 percent' should NOT be extracted as threshold=$15."""
    # This query should route to predictive_alert or still avoid threshold=15
    for query in [
        "Show expenses above 15 percent of budget",
        "Alert me when spending exceeds 15% of income"
    ]:
        res = NLCompiler.compile(query)
        if res.intent == "expense":
            assert res.extracted_slots.get("threshold") != 15.0, \
                f"Percentage '15%' was incorrectly extracted as threshold in query: {query}"


def test_specificity_disambiguation_comparative_over_expense():
    """P0.8: Comparative queries should not be ambiguous with expense."""
    res = NLCompiler.compile("Compare my food spending this month versus last month")
    assert res.outcome == ClassificationOutcome.COMPILED
    assert res.intent == "comparative_trend"


def test_specificity_disambiguation_tagging_over_expense():
    """P0.8: Tagging queries should not be ambiguous with expense."""
    res = NLCompiler.compile("Tag my expenses by type and group them")
    assert res.outcome == ClassificationOutcome.COMPILED
    assert res.intent == "categorical_tagging"


def test_10_topologies_produce_distinct_shape_keys():
    """P0.8: All 10 topologies must produce distinct shape keys."""
    queries = {
        "expense": "Calculate total food spending over $150",
        "troubleshooting": "Diagnose telemetry alerts on node_4 with error threshold exceeding 10",
        "scheduling": "Schedule a meeting with alice for 45 minutes",
        "habit_fitness": "Log my running workout activity and verify goal of 45 minutes",
        "factual_decision": "Decide on deployment strategy and evaluate options with confidence >= 0.85",
        "recommendation": "Recommend catalog items with rating above 4.5 for user_9",
        "cross_source_join_aggregate": "Reconcile orders and inventory matching stock quantity exceeding 20",
        "comparative_trend": "Compare my food spending this month versus last month",
        "predictive_alert": "Alert me when I am running low on groceries budget",
        "categorical_tagging": "Categorize my transactions as essential or discretionary",
    }

    shape_keys = {}
    for expected_intent, text in queries.items():
        res = NLCompiler.compile(text)
        assert res.outcome == ClassificationOutcome.COMPILED
        shape_keys[expected_intent] = res.graph._cached_shape_key.key_hash

    unique_hashes = set(shape_keys.values())
    assert len(unique_hashes) == 10, f"Expected 10 distinct shape keys, got {len(unique_hashes)}: {shape_keys}"

