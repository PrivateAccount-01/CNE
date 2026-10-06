"""Executed evaluation, replay admission and runtime boundary regressions."""
from dataclasses import replace
import pytest
from cne.platform.learning import *
from cne.platform.memory import ExperienceRecord, ExperienceState
from cne.platform.benchmark import ModelSelectionHarness
from cne.platform.models import (
    ModelDescriptor,
    ModelKind,
    LlamaCppRuntimeAdapter,
    ModelResidencyManager,
)
from cne.platform.device import RuntimeBackend
from cne.platform.external_data import ExternalDataCache, ExternalDataRecord
from cne.platform.slots import TypedSlotBinder


def evaluator():
    return CandidateEvaluator(
        {
            name: [EvaluationCase(name + "1", 1, 2), EvaluationCase(name + "2", 2, 3)]
            for name in CandidateEvaluator.REQUIRED
        }
    )


def test_learning_computes_scores_and_transactional_rollback(tmp_path):
    ev = evaluator()
    path = tmp_path / "adapters.db"
    pipe = GatedAdaptationPipeline(evaluator=ev, database_path=path)
    candidate = AdaptationCandidate("a", "1", "finance.budget", "m", 2)
    bad = pipe.evaluate_candidate(candidate, lambda x: 0, lambda x: x + 1, "baseline1")
    assert bad.historical_error_recovery_rate == 0 and not bad.passed
    assert not pipe.deploy_candidate(candidate, bad)
    good = pipe.evaluate_candidate(
        candidate, lambda x: x + 1, lambda x: x + 1, "baseline1"
    )
    assert good.passed and good.sample_counts["HistoricalErrorSet"] == 2
    assert pipe.deploy_candidate(candidate, good)
    next_candidate = replace(candidate, version="2")
    assert not pipe.deploy_candidate(next_candidate, good)
    good2 = pipe.evaluate_candidate(
        next_candidate, lambda x: x + 1, lambda x: x + 1, "1"
    )
    assert pipe.deploy_candidate(next_candidate, good2)
    reopened = GatedAdaptationPipeline(database_path=path)
    assert reopened.get_active("finance.budget").version == "2"
    assert reopened.rollback_adapter("finance.budget").version == "1"


def test_caller_cannot_supply_metrics():
    pipe = GatedAdaptationPipeline(evaluator=evaluator())
    with pytest.raises(TypeError):
        pipe.evaluate_candidate(
            AdaptationCandidate("a", "1", "f.b", "m", 1), historical_recovery=0.99
        )


def test_empty_evaluation_never_passes():
    ev = CandidateEvaluator({name: [] for name in CandidateEvaluator.REQUIRED})
    res = ev.evaluate(
        AdaptationCandidate("a", "1", "f.b", "m", 0), lambda x: x, lambda x: x, "1"
    )
    assert not res.passed and res.historical_error_recovery_rate is None


def test_replay_admission_retention_and_scope():
    store = LearningReplayStore(max_capacity=2)
    raw = ExperienceRecord(
        "e",
        "s",
        "",
        "finance.budget".split(),
        "m",
        "dsl",
        "COMPILED",
        True,
        1,
        user_id="alice",
        input_fingerprint="fp",
    )
    with pytest.raises(ValueError):
        store.add_experience(raw)
    store.admit(raw, "auditor checked", "verifier checked", True)
    store.admit(replace(raw, experience_id="duplicate"), "auditor", "verifier", True)
    assert store.total_records == 1
    assert len(store.sample_batch("finance.budget", user_id="alice")) == 1
    assert not store.sample_batch("finance.budget", user_id="bob")
    with pytest.raises(ValueError):
        store.admit(replace(raw, query_text="private email"), "audit", "verify", True)
    with pytest.raises(ValueError, match="EXPIRED"):
        store.admit(replace(raw, timestamp=0), "audit", "verify", True)
    store.delete_user("alice")
    assert store.total_records == 0


def test_benchmark_independent_labels_and_no_fabricated_metrics():
    descriptor = ModelDescriptor(
        "test-callback", ModelKind.TEXT_GENERATION, "1", 150, estimated_ram_mb=1
    )
    cases = [
        {
            "query": "one",
            "expected_capabilities": ["finance.budget"],
            "expected_intent": "expense",
            "expected_slots": {"amount": 1},
        },
        {"query": "outside", "is_oos": True},
        {"query": "ambiguous", "is_ambiguous": True},
    ]

    def wrong(q):
        return {
            "semantic_dsl": "a = LIT value=1\ne = EMI in=a",
            "selected_capability_ids": ["wrong.pack"],
            "intent": "wrong",
            "extracted_slots": {},
            "outcome": "COMPILED",
        }

    result = ModelSelectionHarness().evaluate_candidate(descriptor, wrong, cases)
    assert (
        result.routing_accuracy == 0
        and result.intent_accuracy == 0
        and result.ambiguity_accuracy == 0
    )
    assert result.dsl_validity_rate == 1 and result.slot_exact_match_rate == 0
    assert (
        result.ttft_ms is None
        and result.peak_ram_mb > 0
        and not result.passed_all_gates
    )
    assert result.metrics["routing_accuracy"].denominator == 1
    empty = ModelSelectionHarness().evaluate_candidate(descriptor, wrong, [])
    assert empty.metrics["routing_accuracy"].status == "NOT_APPLICABLE"
    assert empty.routing_accuracy is None
    assert ModelSelectionHarness().select_smallest_admissible_model([result]) is None


def test_real_backend_missing_asset_explicit():
    runtime = LlamaCppRuntimeAdapter()
    with pytest.raises(FileNotFoundError, match="MODEL_ASSET_MISSING"):
        runtime.load_model(ModelDescriptor("m", ModelKind.TEXT_GENERATION, "1", 100))


def test_real_gguf_integration_when_configured():
    import os

    path = os.environ.get("CNE_TEST_GGUF")
    if not path:
        pytest.skip("NOT_TESTED: set CNE_TEST_GGUF to a local licensed GGUF asset")
    pytest.importorskip("llama_cpp", reason="NOT_TESTED: llama-cpp-python unavailable")
    from cne.platform.models import ModelRequest

    runtime = LlamaCppRuntimeAdapter()
    descriptor = ModelDescriptor(
        "test",
        ModelKind.TEXT_GENERATION,
        "test",
        0,
        asset_path=path,
        context_window=256,
    )
    runtime.load_model(descriptor)
    try:
        result = runtime.infer(ModelRequest("r", "test", "Hello", {"max_tokens": 4}))
        assert result.tokens_generated >= 0 and result.latency_ms > 0
        assert result.metadata["backend_identity"] == "llama-cpp-python/CPU"
    finally:
        runtime.unload_model("test")
    assert not runtime.is_loaded("test")


def test_residency_does_not_evict_owned_or_pinned():
    mgr = ModelResidencyManager(100)
    for name in ("active", "pinned", "idle"):
        mgr.record_load(
            ModelDescriptor(
                name, ModelKind.TEXT_GENERATION, "1", 1, estimated_ram_mb=40
            ),
            RuntimeBackend.CPU,
            actual_memory_mb=40,
        )
    mgr._entries["active"].active_owners.add("request")
    mgr._entries["pinned"].pinned = True
    assert mgr.select_eviction_candidates(30) == ["idle"]
    assert mgr.get_residency_snapshot()["idle"]["measured_ram_mb"] == 40


def test_external_cache_ttl_and_user_scope():
    cache = ExternalDataCache()
    rec = ExternalDataRecord("weather", "Mumbai", {"temperature": 25}, 100, 10)
    cache.put("alice", rec)
    assert cache.get("alice", "weather", "Mumbai", now=109) == rec
    with pytest.raises(ValueError, match="STALE"):
        cache.get("alice", "weather", "Mumbai", now=110)
    assert cache.get("bob", "weather", "Mumbai", now=109) is None


@pytest.mark.parametrize(
    "kind,raw,expected",
    [
        ("number", "1.25", 1.25),
        ("percentage", "25%", 0.25),
        ("date", "2026-10-06", "2026-10-06"),
        ("currency", "USD 20", 20),
        ("unit", "5 km", 5),
    ],
)
def test_typed_slot_normalization(kind, raw, expected):
    spec = {"type": kind, "currency": "USD", "unit": "km", "required": True}
    result = TypedSlotBinder().bind({"x": spec}, {"x": raw})["x"]
    assert result.value == expected and result.confidence is None


@pytest.mark.parametrize("values", [{}, {"x": ["1", "2"]}, {"x": "NaN"}, {"x": -1}])
def test_slot_rejects_missing_ambiguous_invalid(values):
    with pytest.raises(ValueError):
        TypedSlotBinder().bind(
            {"x": {"type": "number", "required": True, "minimum": 0}}, values
        )
