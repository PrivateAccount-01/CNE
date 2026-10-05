"""
Unit tests for CNE Local AI Platform core interfaces.
Tests:
1. DeviceProfile & ResourceBudget
2. CapabilityManifest validation & hashing
3. CapabilityRegistry lifecycle & permissions
4. ModelResidencyManager & eviction
5. SessionStore & compact history
6. CorrectionStore (L4) fast learning retrieval
7. SemanticDSLParser & deterministic graph compilation
8. PlatformControllerBridge compatibility
"""
from __future__ import annotations

import pytest

from cne.compiler.nl_compiler import ClassificationOutcome
from cne.platform.bridge import PlatformControllerBridge
from cne.platform.device import DeviceProfile, ResourceBudget, RuntimeBackend
from cne.platform.dsl import SemanticDSLParser
from cne.platform.manifest import (
    CapabilityManifest,
    CapabilityVersion,
    Modality,
    NetworkMode,
    Permission,
)
from cne.platform.memory import (
    AuditStatus,
    CorrectionRecord,
    CorrectionStore,
    SessionStore,
)
from cne.platform.models import ModelDescriptor, ModelKind, ModelResidencyManager
from cne.platform.registry import CapabilityRegistry, CapabilityState
from cne.semantic_ir.nodes import OpKind


class TestDeviceProfile:
    def test_cpu_is_always_available(self):
        profile = DeviceProfile()
        assert profile.is_backend_available(RuntimeBackend.CPU)
        cpu_caps = profile.backends[RuntimeBackend.CPU]
        assert cpu_caps.compute_units >= 1

    def test_resource_snapshot_and_budget(self):
        profile = DeviceProfile()
        snap = profile.capture_snapshot()
        assert snap.available_ram_mb > 0
        assert snap.process_rss_mb >= 0
        assert profile.budget.is_within_budget(snap)


class TestCapabilityManifest:
    def test_canonical_id_validation(self):
        manifest = CapabilityManifest(
            id="finance.personal_budget",
            version="1.0.0",
            description="Budget tracking",
            modalities=[Modality.TEXT],
            provided_capabilities=["expense_aggregation"],
            permissions=[Permission.FINANCIAL_DATA_READ]
        )
        assert manifest.id == "finance.personal_budget"
        h = manifest.compute_manifest_hash()
        assert len(h) == 64

    def test_invalid_canonical_id_rejected(self):
        with pytest.raises(ValueError, match="violates canonical format"):
            CapabilityManifest(
                id="InvalidIDFormat",
                version="1.0.0",
                description="Invalid",
                modalities=[Modality.TEXT],
                provided_capabilities=[]
            )


class TestCapabilityRegistry:
    def test_lifecycle_and_permissions(self):
        registry = CapabilityRegistry()
        manifest = CapabilityManifest(
            id="agriculture.crop_disease",
            version="1.0.0",
            description="Vision disease detection",
            modalities=[Modality.IMAGE],
            provided_capabilities=["crop_detection"],
            permissions=[Permission.CAMERA]
        )
        pack = registry.register_pack(manifest)
        assert pack.state == CapabilityState.ENABLED
        assert registry.has_permission("agriculture.crop_disease", Permission.CAMERA)
        assert not registry.has_permission("agriculture.crop_disease", Permission.NETWORK_HTTP)

        # Vector hash is computed
        v_hash = registry.compute_active_capability_vector_hash()
        assert v_hash != "none"

        # Disable
        assert registry.disable_pack("agriculture.crop_disease")
        assert not pack.is_enabled()

        # Uninstall
        assert registry.uninstall_pack("agriculture.crop_disease")
        assert registry.get_pack("agriculture.crop_disease") is None


class TestModelResidencyManager:
    def test_residency_and_eviction(self):
        mgr = ModelResidencyManager(max_resident_memory_mb=600.0)
        m1 = ModelDescriptor("m1", ModelKind.TEXT_GENERATION, "1.0", 500, estimated_ram_mb=400.0)
        m2 = ModelDescriptor("m2", ModelKind.COMPUTER_VISION, "1.0", 200, estimated_ram_mb=300.0)

        mgr.record_load(m1, RuntimeBackend.CPU)
        assert mgr.current_resident_memory_mb == 400.0

        # Adding m2 would exceed 600MB -> m1 should be evicted
        candidates = mgr.select_eviction_candidates(m2.estimated_ram_mb)
        assert "m1" in candidates


class TestSessionAndCorrectionMemory:
    def test_session_store_compact_history(self):
        store = SessionStore()
        sess = store.get_or_create("s1")
        for i in range(15):
            store.record_turn("s1", f"Query {i}", "finance.budget", "expense", {"threshold": i})
        # History is kept compact (<= 10 turns)
        assert len(sess.semantic_history) <= 10
        store.close_session("s1")
        assert "Session s1 ended" in sess.compact_summary

    def test_correction_store_retrieval(self):
        c_store = CorrectionStore()
        rec = CorrectionRecord(
            record_id="c1",
            request_fingerprint="fp1",
            query_redacted="calculate groceries over 50 dollars",
            capability_id="finance.personal_budget",
            model_version="1.0",
            controller_version="1.0",
            error_type="SLOT_ERROR",
            incorrect_decision="threshold=500",
            verified_correction="threshold=50.0"
        )
        c_store.add_correction(rec)
        matched = c_store.find_matching_correction(
            "calculate groceries over 50 dollars please",
            "finance.personal_budget"
        )
        assert matched is not None
        assert matched.verified_correction == "threshold=50.0"


class TestSemanticDSLParser:
    def test_compile_valid_dsl(self):
        dsl = """
        OBS source=transactions category=groceries
        FIL threshold=50.0 op=gt
        MAP field=amount
        RED op=sum
        EMI label=total_expense
        """
        res = SemanticDSLParser.compile_dsl(dsl)
        assert res.is_valid
        assert res.graph is not None
        assert len(res.graph.nodes) == 5
        # Verify 11 frozen primitive adherence
        assert res.graph.nodes["n0_obs"].op == OpKind.OBSERVE
        assert res.graph.nodes["n1_fil"].op == OpKind.FILTER
        assert res.graph.nodes["n2_map"].op == OpKind.MAP
        assert res.graph.nodes["n3_red"].op == OpKind.REDUCE
        assert res.graph.nodes["n4_emi"].op == OpKind.EMIT
        assert res.extracted_slots["category"] == "groceries"
        assert res.extracted_slots["threshold"] == 50.0

    def test_rejects_missing_emit(self):
        dsl = "OBS source=data\nFIL op=filter"
        res = SemanticDSLParser.compile_dsl(dsl)
        assert not res.is_valid
        assert "Last node must be 'EMI'" in (res.error_message or "")

    def test_rejects_unknown_opcode(self):
        with pytest.raises(ValueError, match="Unknown primitive opcode 'INVALID'"):
            SemanticDSLParser.parse_line("INVALID arg=1")


class TestPlatformControllerBridge:
    def test_bridge_compilation(self):
        bridge = PlatformControllerBridge()
        res = bridge.compile("Calculate total spending on food over 100 dollars")
        assert res.outcome == ClassificationOutcome.COMPILED
        assert res.graph is not None
        assert res.intent == "expense"

    def test_bridge_unsupported_rejection(self):
        bridge = PlatformControllerBridge()
        res = bridge.compile("Turn on the living room lights")
        assert res.outcome == ClassificationOutcome.UNSUPPORTED_INTENT
        assert res.graph is None
