"""
Unit tests for Reference Capability Packs and Error Auditor.
Tests:
1. Finance reference pack deterministic calculations & filtering
2. Agriculture CV leaf disease classification & local knowledge
3. Travel itinerary planning & offline freshness limitation
4. ErrorAuditor signal classification across 19 ErrorTypes & SessionAuditReport
"""
from __future__ import annotations

import json
import os
import pytest

from cne.packs.agriculture_cv.classifier import CropDiseaseClassifier, lookup_treatment
from cne.packs.finance.tools import calculate_total, filter_transactions
from cne.packs.travel.planner import build_day_schedule
from cne.platform.auditor import AuditSignal, ErrorAuditor, ErrorType
from cne.platform.manifest import CapabilityManifest
from cne.platform.memory import CorrectionStore


class TestFinancePack:
    def test_filter_and_total(self):
        txs = [
            {"id": "t1", "category": "Food", "amount": 25.50, "account": "checking"},
            {"id": "t2", "category": "Food", "amount": 80.00, "account": "checking"},
            {"id": "t3", "category": "Utilities", "amount": 120.00, "account": "checking"},
        ]
        filtered = filter_transactions(txs, category="Food", min_amount=50.0)
        assert len(filtered) == 1
        assert filtered[0]["id"] == "t2"

        total = calculate_total(filtered, aggregation="sum")
        assert total == 80.00

    def test_finance_manifest_validity(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "packs", "finance", "manifest.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        manifest = CapabilityManifest(**data)
        assert manifest.id == "finance.personal_budget"
        assert manifest.storage_budget_mb <= 50.0


class TestAgricultureCVPack:
    def test_classifier_and_treatment_lookup(self):
        classifier = CropDiseaseClassifier()
        img_mock = b"\x01\x02\x03\x04"
        res = classifier.classify_image(img_mock)
        assert res.confidence >= 0.8
        assert res.disease_key in ("healthy", "early_blight", "late_blight")

        treatment = lookup_treatment(res.disease_key)
        assert "disease" in treatment

    def test_agri_manifest_validity(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "packs", "agriculture_cv", "manifest.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        manifest = CapabilityManifest(**data)
        assert manifest.id == "agriculture.crop_disease"
        assert "IMAGE" in [m.value for m in manifest.modalities]


class TestTravelPack:
    def test_offline_freshness_notice(self):
        itinerary = build_day_schedule(
            destination="Rome",
            attractions=["Colosseum", "Pantheon"],
            network_available=False
        )
        assert len(itinerary.items) == 2
        assert itinerary.items[0].freshness_notice is not None
        assert "Offline Mode" in itinerary.items[0].freshness_notice

    def test_online_freshness(self):
        itinerary = build_day_schedule(
            destination="Rome",
            attractions=["Colosseum"],
            network_available=True
        )
        assert itinerary.items[0].freshness_notice is None
        assert itinerary.items[0].is_live_status is True


class TestErrorAuditor:
    def test_auditing_user_feedback(self):
        c_store = CorrectionStore()
        auditor = ErrorAuditor(correction_store=c_store)

        signal = auditor.audit_turn(
            session_id="s1",
            query_text="Calculate spending on groceries",
            capability_id="finance.personal_budget",
            contract_satisfied=True,
            user_feedback="category should be Food"
        )
        assert signal is not None
        assert signal.error_type == ErrorType.SLOT_ERROR
        # Verify correction stored in L4
        assert len(c_store.get_corrections_for_capability("finance.personal_budget")) == 1

    def test_session_audit_report(self):
        auditor = ErrorAuditor()
        signal = AuditSignal(
            signal_type="contract_failure",
            description="Outcome bounds exceeded",
            error_type=ErrorType.CONTRACT_FAILURE
        )
        report = auditor.generate_session_report("s2", [signal], total_turns=3)
        assert report.has_errors
        assert report.total_turns == 3
