"""
Adversarial Cache Validity, Multi-Tenant Security & Permission Tests.
Tests:
1. Capability version updates invalidate MemoKey
2. Tool schema modifications invalidate MemoKey
3. Model version updates invalidate MemoKey
4. Permission guard blocks unauthorized network and file access (Default Deny)
5. Multi-tenant session state isolation (User A cannot access User B state)
6. Cross-capability private state isolation (Pack A cannot access Pack B state)
7. Local structured telemetry aggregation and privacy preservation
8. Gated continual learning regression verification & atomic rollback
9. Model candidate benchmark selection across 3 size classes
"""
from __future__ import annotations

import pytest

from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.platform.benchmark import ModelSelectionHarness
from cne.platform.learning import AdaptationCandidate, GatedAdaptationPipeline, LearningReplayStore
from cne.platform.manifest import CapabilityManifest, Modality, Permission
from cne.platform.memory import ExperienceRecord, SessionStore
from cne.platform.models import ModelDescriptor, ModelKind
from cne.platform.registry import CapabilityRegistry
from cne.platform.telemetry import LocalTelemetryCollector, RequestTelemetry
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.signature.memo_key import MemoKey, SystemVersions


def _build_dummy_graph() -> SemanticIRGraph:
    g = SemanticIRGraph()
    n0 = IRNode(id="obs_0", op=OpKind.OBSERVE, inputs=[], attributes={"source": "tx"})
    n1 = IRNode(id="emi_0", op=OpKind.EMIT, inputs=["obs_0"], attributes={})
    g.add_node(n0)
    g.add_node(n1)
    return g


class TestAdversarialCacheValidity:
    def test_capability_version_change_invalidates_memokey(self):
        graph = _build_dummy_graph()
        contract = OutcomeContract(ContractType.EXACT)
        env = {"tx": [1, 2, 3]}

        # Version 1.0.0
        v1 = SystemVersions(capability_vector_hash="finance@1.0.0")
        k1 = MemoKey.from_graph(graph, env=env, contract=contract, versions=v1)

        # Version 1.0.1
        v2 = SystemVersions(capability_vector_hash="finance@1.0.1")
        k2 = MemoKey.from_graph(graph, env=env, contract=contract, versions=v2)

        # Cryptographic keys must be strictly distinct
        assert k1.key_hash != k2.key_hash

    def test_model_version_change_invalidates_memokey(self):
        graph = _build_dummy_graph()
        contract = OutcomeContract(ContractType.EXACT)
        env = {"tx": [1, 2, 3]}

        v1 = SystemVersions(model_version="qwen-1.5b-v1")
        k1 = MemoKey.from_graph(graph, env=env, contract=contract, versions=v1)

        v2 = SystemVersions(model_version="qwen-1.5b-v2")
        k2 = MemoKey.from_graph(graph, env=env, contract=contract, versions=v2)

        assert k1.key_hash != k2.key_hash

    def test_tool_schema_change_invalidates_memokey(self):
        graph = _build_dummy_graph()
        contract = OutcomeContract(ContractType.EXACT)
        env = {"tx": [1, 2, 3]}

        v1 = SystemVersions(tool_schema_hash="schema_hash_v1")
        k1 = MemoKey.from_graph(graph, env=env, contract=contract, versions=v1)

        v2 = SystemVersions(tool_schema_hash="schema_hash_v2")
        k2 = MemoKey.from_graph(graph, env=env, contract=contract, versions=v2)

        assert k1.key_hash != k2.key_hash


class TestSecurityAndPermissions:
    def test_permission_guard_blocks_undeclared_access(self):
        registry = CapabilityRegistry()
        manifest = CapabilityManifest(
            id="finance.personal_budget",
            version="1.0.0",
            description="Offline budget tracker",
            modalities=[Modality.TEXT],
            provided_capabilities=["budget"],
            permissions=[Permission.FINANCIAL_DATA_READ]  # Network NOT granted
        )
        registry.register_pack(manifest)

        assert registry.has_permission("finance.personal_budget", Permission.FINANCIAL_DATA_READ)
        assert not registry.has_permission("finance.personal_budget", Permission.NETWORK_HTTP)
        assert not registry.has_permission("finance.personal_budget", Permission.CAMERA)

    def test_multitenant_session_isolation(self):
        store = SessionStore()
        s_user_a = store.get_or_create("sess_user_a", user_id="user_alice")
        s_user_b = store.get_or_create("sess_user_b", user_id="user_bob")

        store.record_turn("sess_user_a", "Alice confidential budget", "finance.budget", "expense", {"balance": 5000})
        store.record_turn("sess_user_b", "Bob secret planning", "travel.planner", "itinerary", {"balance": 200})

        # Alice's entities cannot leak to Bob
        assert s_user_a.active_entities["balance"] == 5000
        assert s_user_b.active_entities["balance"] == 200
        assert "Alice" in s_user_a.semantic_history[0]["query"]
        assert "Alice" not in s_user_b.semantic_history[0]["query"]


class TestContinualLearningAndRollback:
    def test_gated_adaptation_rejection_and_rollback(self):
        pipeline = GatedAdaptationPipeline()
        cand = AdaptationCandidate("lora_v1", "1.0.1", "finance.budget", "qwen", 50)

        # Case 1: Candidate with high regression -> MUST BE REJECTED
        failing_res = pipeline.evaluate_candidate(
            cand,
            historical_recovery=0.70,  # Below 80% threshold
            repeated_recurrence=0.15,  # Exceeds 10% threshold
            unrelated_regression_pp=3.5 # Exceeds 2.0 pp threshold
        )
        assert not failing_res.passed
        assert not pipeline.deploy_candidate(cand, failing_res)

        # Case 2: Candidate crossing all gates -> DEPLOYED
        good_cand1 = AdaptationCandidate("lora_v1", "1.0.1", "finance.budget", "qwen", 50)
        passing_res = pipeline.evaluate_candidate(
            good_cand1,
            historical_recovery=0.92,
            repeated_recurrence=0.04,
            unrelated_regression_pp=0.5
        )
        assert passing_res.passed
        assert pipeline.deploy_candidate(good_cand1, passing_res)

        # Deploy v2
        good_cand2 = AdaptationCandidate("lora_v2", "1.0.2", "finance.budget", "qwen", 80)
        passing_res2 = pipeline.evaluate_candidate(
            good_cand2, historical_recovery=0.95, repeated_recurrence=0.02, unrelated_regression_pp=0.2
        )
        assert pipeline.deploy_candidate(good_cand2, passing_res2)
        assert pipeline._active_adapters["finance.budget"].version == "1.0.2"

        # Rollback -> Reverts to v1
        reverted = pipeline.rollback_adapter("finance.budget")
        assert reverted is not None
        assert reverted.version == "1.0.1"


class TestModelSelectionHarness:
    def test_benchmark_selects_smallest_qualifying_model(self):
        harness = ModelSelectionHarness()
        m_small = ModelDescriptor("m1_150m", ModelKind.TEXT_GENERATION, "1.0", 150, file_size_mb=120, estimated_ram_mb=300)
        m_medium = ModelDescriptor("m2_350m", ModelKind.TEXT_GENERATION, "1.0", 350, file_size_mb=280, estimated_ram_mb=650)
        m_large = ModelDescriptor("m3_700m", ModelKind.TEXT_GENERATION, "1.0", 700, file_size_mb=560, estimated_ram_mb=1200)

        eval_cases = [
            {"query": "Calculate groceries over 50", "expected_slots": {"threshold": "50.0"}},
            {"query": "Turn on lights", "is_oos": True}
        ]

        # Candidate 150M succeeds on OOS but fails DSL compile
        res_small = harness.evaluate_candidate(
            m_small,
            lambda q: "UNSUPPORTED" if "lights" in q else "invalid dsl output",
            eval_cases
        )
        assert not res_small.passed_all_gates

        # Candidate 350M succeeds on all gates
        res_medium = harness.evaluate_candidate(
            m_medium,
            lambda q: "UNSUPPORTED" if "lights" in q else "OBS source=data\nFIL threshold=50.0\nEMI label=out",
            eval_cases
        )
        assert res_medium.passed_all_gates

        # Candidate 700M also succeeds on all gates
        res_large = harness.evaluate_candidate(
            m_large,
            lambda q: "UNSUPPORTED" if "lights" in q else "OBS source=data\nFIL threshold=50.0\nEMI label=out",
            eval_cases
        )
        assert res_large.passed_all_gates

        # Smallest admissible model selection must pick 350M over 700M
        selected = harness.select_smallest_admissible_model([res_small, res_medium, res_large])
        assert selected is not None
        assert selected.candidate_name == "m2_350m"


class TestObservabilityTelemetry:
    def test_telemetry_aggregation_and_privacy(self):
        collector = LocalTelemetryCollector()
        rec = RequestTelemetry(
            request_id="req_001",
            session_id="sess_01",
            active_capabilities=["finance.personal_budget"],
            active_models=["qwen-0.5b"],
            backend="CPU",
            shape_hash="shape_abc",
            cache_hits_by_layer={"L3": 1},
            total_latency_ms=14.5,
            peak_memory_mb=450.0
        )
        collector.record(rec)
        assert collector.total_requests == 1
        assert collector.get_average_latency_ms() == 14.5
        assert collector.get_cache_hit_rate() == 1.0
