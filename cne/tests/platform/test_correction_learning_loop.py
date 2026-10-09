import json
from pathlib import Path
import pytest
from cne.platform.runtime_config import PlatformRuntimeConfig, PlatformRuntimeFactory
from cne.platform.manifest import CapabilityManifest
from cne.platform.memory import AuditStatus


def create_runtime(tmp_path):
    config = PlatformRuntimeConfig(str(tmp_path), mode="development")
    runtime = PlatformRuntimeFactory.create(
        config,
        verifiers={
            "gold": lambda record: {
                "passed": record.constraint
                == {
                    "kind": "slot_normalization",
                    "slot": "category",
                    "from": "groceries",
                    "to": "food",
                },
                "evidence": "Reviewed public category alias and independent fixture",
                "training_example": {
                    "sanitized_request": "finance expense_total category groceries threshold 50",
                    "intent": "expense_total",
                    "slot_schema_hash": "finance.personal_budget-v1",
                    "incorrect_plan_sha256": __import__("hashlib")
                    .sha256(record.incorrect_decision.encode())
                    .hexdigest(),
                    "correct_plan": "tx = OBS source=transactions\nfood = FIL in=tx field=category op=eq val=food\nfiltered = FIL in=food field=amount op=gt val=50\namounts = MAP in=filtered field=amount\ntotal = RED in=amounts reducer=sum\nresult = EMI in=total",
                    "provenance": "independent-fixture-and-owner-review",
                    "privacy_approved": True,
                },
            }
        },
    )
    if not runtime.registry.get_pack("finance.personal_budget"):
        manifest = CapabilityManifest(
            **json.loads(
                (Path(__file__).parents[2] / "packs/finance/manifest.json").read_text()
            )
        )
        runtime.registry.register_pack(manifest)
        for user in ("alice", "bob", "benchmark"):
            for p in manifest.permissions:
                runtime.registry.permission_authority.grant(
                    manifest.id, p, user, "test consent"
                )
    return runtime


ENV = {
    "transactions": [
        {
            "category": "food",
            "amount": 80,
            "currency": "USD",
            "date": "2026-10-06",
            "account": "public-example",
        }
    ]
}
QUERY = "Calculate total spending on groceries over 50 dollars"
CONSTRAINT = {
    "kind": "slot_normalization",
    "slot": "category",
    "from": "groceries",
    "to": "food",
}


def test_verified_correction_changes_plan_and_survives_restart(tmp_path):
    rt = create_runtime(tmp_path)
    assert rt.executor.execute("alice", "s0", QUERY, ENV).value == 0
    rec = rt.review.submit_user_feedback(
        "alice",
        rt.executor.last_experience_id,
        QUERY,
        "Groceries means food",
        CONSTRAINT,
    )
    assert (
        rec.audit_status == AuditStatus.UNVERIFIED
        and rec.controller_version == rt.executor.bridge.controller.controller_version
    )
    assert (
        rec.capability_version == "1.0.0"
        and rec.intent == "expense_total"
        and rec.semantic_shape
    )
    assert rt.executor.execute("alice", "before", QUERY, ENV).value == 0
    with pytest.raises(ValueError):
        rt.review.promote_user_scoped("alice", rec.record_id)
    with pytest.raises(PermissionError):
        rt.review.verify("alice", rec.record_id, "user-assertion")
    rt.review.verify("alice", rec.record_id, "gold")
    assert rt.executor.execute("alice", "s1", QUERY, ENV).value == 80
    saved = rt.executor.experiences.get("alice", rt.executor.last_experience_id)
    assert saved.training_example is None
    reviewed_exp = rt.executor.experiences.get("alice", rec.experience_id)
    assert reviewed_exp.training_example["sanitized_request"].startswith(
        "finance expense_total"
    )
    assert rt.executor.bridge.last_decision.evidence["replan_count"] == 1
    rt.close()
    rt = create_runtime(tmp_path)
    assert (
        rt.executor.execute("alice", "s2", QUERY.replace("50", "60"), ENV).value == 80
    )
    assert rt.executor.execute("bob", "bob-session", QUERY, ENV).value == 0
    assert (
        rt.executor.execute(
            "alice", "unrelated", QUERY.replace("groceries", "travel"), ENV
        ).value
        == 0
    )
    assert not rt.executor.bridge.last_decision.evidence["applied_correction_ids"]
    rows = rt.review.store.db.execute(
        "SELECT before_state,after_state FROM correction_transitions WHERE correction=?",
        (rec.record_id,),
    ).fetchall()
    assert rows == [(None, "UNVERIFIED"), ("UNVERIFIED", "VERIFIED")]
    rt.review.reject("alice", rec.record_id, "Withdrawn evidence")
    assert rt.executor.execute("alice", "after-reject", QUERY, ENV).value == 0
    rt.close()


def test_preference_promotion_and_global_evidence(tmp_path):
    rt = create_runtime(tmp_path)
    rt.executor.execute("alice", "s0", QUERY, ENV)
    constraint = {**CONSTRAINT, "kind": "slot_preference"}
    rec = rt.review.submit_user_feedback(
        "alice",
        rt.executor.last_experience_id,
        QUERY,
        "My preference",
        constraint,
        kind="preference",
    )
    rt.review.promote_user_scoped("alice", rec.record_id)
    assert rt.executor.execute("alice", "s1", QUERY, ENV).value == 80
    with pytest.raises(ValueError):
        rt.review.verify("alice", rec.record_id, ["gold"], global_scope=True)
    with pytest.raises(PermissionError):
        rt.review.reject("bob", rec.record_id, "bad")
    rt.close()


def test_progression_benchmark(tmp_path):
    from cne.platform.progression import (
        RepeatedErrorProgressionBenchmark,
        ProgressionCase,
    )

    case = ProgressionCase(
        "alias", QUERY, QUERY.replace("50", "60"), ENV, 80, CONSTRAINT, "gold"
    )
    unrelated = ProgressionCase(
        "travel", QUERY.replace("groceries", "travel"), "unused", ENV, 0, {}, "gold"
    )
    result = RepeatedErrorProgressionBenchmark().run(
        lambda: create_runtime(tmp_path), [case], [unrelated]
    )
    assert result["baseline_failures"] == 1
    assert (
        result["exact_repeat_recurrence"]
        == result["restart_recurrence"]
        == result["paraphrase_recurrence"]
        == 0
    )
    assert (
        result["recovery_rate"] == 1
        and result["false_correction_application_rate"] == 0
    )
    assert result["retrieval_precision"] == result["retrieval_recall"] == 1
