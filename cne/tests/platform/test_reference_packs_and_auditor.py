import json
import pytest
from cne.packs.agriculture_cv.classifier import CropDiseaseClassifier, lookup_treatment
from cne.packs.finance.tools import calculate_total, filter_transactions
from cne.packs.travel.planner import build_day_schedule
from cne.platform.auditor import ErrorAuditor, AuditSignal, ErrorType
from cne.platform.memory import CorrectionStore


def transaction(amount=50):
    return {
        "amount": amount,
        "currency": "USD",
        "date": "2026-10-06",
        "category": "Food",
        "account": "checking",
    }


def test_finance_real_arithmetic():
    tx = [transaction(25.5), transaction(80)]
    assert (
        calculate_total(filter_transactions(tx, category="Food", min_amount=50)) == 80
    )


@pytest.mark.parametrize(
    "op,count", [("GT", 0), ("GTE", 1), ("LT", 0), ("LTE", 1), ("EQ", 1), ("NE", 0)]
)
def test_finance_boundaries(op, count):
    assert (
        len(filter_transactions([transaction()], amount_operator=op, amount_value=50))
        == count
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "50"),
        ("amount", True),
        ("amount", float("nan")),
        ("currency", "dollars"),
        ("date", "tomorrow"),
        ("account", ""),
        ("category", None),
    ],
)
def test_finance_rejects_bad_schema(field, value):
    tx = transaction()
    tx[field] = value
    with pytest.raises((ValueError, TypeError)):
        calculate_total([tx])


def test_finance_mixed_currency_rejected():
    a, b = transaction(), transaction()
    b["currency"] = "INR"
    with pytest.raises(ValueError, match="Mixed"):
        calculate_total([a, b])


def test_agriculture_explicit_stub():
    assert CropDiseaseClassifier.IMPLEMENTATION_STATUS == "STUB"
    with pytest.raises(NotImplementedError, match="NOT_IMPLEMENTED"):
        CropDiseaseClassifier().classify_image(b"leaf")
    assert lookup_treatment("early_blight")["validation"] == "UNVERIFIED"


@pytest.mark.parametrize("network", [False, True])
def test_travel_never_invents_data(network):
    item = build_day_schedule("Rome", ["Pantheon"], network_available=network).items[0]
    assert not item.is_live_status and item.freshness_status == "NO_DATA"
    assert item.source_id is None and "no opening-hours" in item.freshness_notice


def test_feedback_never_verified():
    store = CorrectionStore()
    auditor = ErrorAuditor(store)
    signal = auditor.audit_turn(
        "s",
        "my email is test@example.org",
        "finance.budget",
        True,
        user_feedback="category should be food",
        user_id="alice",
    )
    assert signal.error_type == ErrorType.SLOT_ERROR
    assert store.get_corrections_for_capability("finance.budget", "alice") == []
    payload = store.db.execute("SELECT payload FROM corrections").fetchone()[0]
    assert "test@example.org" not in payload and "UNVERIFIED" in payload


def test_audit_report():
    report = ErrorAuditor().generate_session_report(
        "s", [AuditSignal("contract_failure", "bounds", ErrorType.CONTRACT_FAILURE)], 3
    )
    assert report.has_errors and report.total_turns == 3
