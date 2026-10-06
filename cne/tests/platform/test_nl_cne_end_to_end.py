import json
from pathlib import Path
from dataclasses import replace
import pytest
from cne.platform.registry import CapabilityRegistry
from cne.platform.security import TrustMode
from cne.platform.manifest import CapabilityManifest, Modality, Permission
from cne.platform.bridge import PlatformControllerBridge
from cne.platform.execution import (
    PlatformExecutor,
    ExperienceRepository,
    ScopedPrivateStore,
    MutationAuthority,
)
from cne.platform.memory import SessionStore, SQLiteSessionRepository
from cne.platform.external_data import ExternalDataRecord
from cne.optimizer.runtime.dependencies import ChangeType


@pytest.fixture
def platform(tmp_path):
    registry = CapabilityRegistry(trust_mode=TrustMode.DEVELOPMENT_TRUST_MODE)
    path = Path(__file__).parents[2] / "packs/finance/manifest.json"
    m = CapabilityManifest(**json.loads(path.read_text()))
    registry.register_pack(m)
    for user in ("alice", "bob"):
        for permission in m.permissions:
            registry.permission_authority.grant(
                m.id, permission, user, "test-user-consent"
            )
    sessions = SessionStore(SQLiteSessionRepository(tmp_path / "sessions.db"))
    executor = PlatformExecutor(
        PlatformControllerBridge(registry, sessions),
        experiences=ExperienceRepository(tmp_path / "experiences.db"),
    )
    return executor


def query(threshold=50):
    return f"Calculate total spending on food over {threshold} dollars"


def test_true_natural_language_end_to_end(platform, tmp_path):
    env = {"transactions": [tx("food", 25), tx("food", 80), tx("travel", 300)]}
    result = platform.execute("alice", "a", query(), env)
    assert result.value == 80 and result.contract_satisfied and not result.reused_state
    repeat = platform.execute("alice", "a", query(), env)
    assert repeat.value == 80 and repeat.reused_state
    assert not platform.last_audit.has_errors
    assert platform.telemetry._records[-1].cache_hits_by_layer["L3"] == 1
    assert platform.telemetry._records[-1].cache_hits_by_layer["L2"] == 1
    request_id = platform.telemetry._records[-1].request_id
    experience = platform.experiences.get("alice", request_id)
    assert experience.verification_result["satisfied"] and not experience.query_text
    with pytest.raises(PermissionError):
        platform.experiences.get("bob", request_id)
    reopened = SessionStore(SQLiteSessionRepository(tmp_path / "sessions.db"))
    assert reopened.get_session("alice", "a").active_entities["threshold"] == 50
    with pytest.raises(PermissionError):
        reopened.get_session("bob", "a")


def test_adversarial_cache_matrix(platform):
    env = {"transactions": [tx("food", 80), tx("food", 120)]}
    one = platform.execute("alice", "a", query(), env)
    changed_slot = platform.execute("alice", "a", query(100), env)
    assert changed_slot.value == 120 and not changed_slot.reused_state
    assert platform.telemetry._records[-1].cache_hits_by_layer["L2"] == 1
    other_user = platform.execute("bob", "b", query(), env)
    assert not other_user.reused_state and other_user.memo_key != one.memo_key
    assert platform.telemetry._records[-1].cache_hits_by_layer["L2"] == 0
    env["transactions"][0]["amount"] = 90
    platform.engine_for("alice").fabric.notify_data_mutation(
        ChangeType.UPDATE, "transactions"
    )
    changed = platform.execute("alice", "a", query(), env)
    assert changed.value == 210 and not changed.reused_state
    registry = platform.bridge.registry
    other = CapabilityManifest("agri.crop", "1.0.0", "test", [Modality.TEXT], [])
    registry.register_pack(other)
    assert platform.execute("alice", "a", query(), env).reused_state
    registry.register_pack(replace(other, version="1.0.1"))
    assert platform.execute("alice", "a", query(), env).reused_state
    used = registry.get_pack("finance.personal_budget").manifest
    registry.register_pack(replace(used, version="1.0.1"))
    for p in used.permissions:
        registry.permission_authority.grant(used.id, p, "alice", "test")
    assert not platform.execute("alice", "a", query(), env).reused_state
    with pytest.raises(ValueError, match="STALE"):
        platform.execute(
            "alice",
            "a",
            query(),
            env,
            [ExternalDataRecord("weather", "Mumbai", {}, 0, 1)],
        )


def test_permissions_rechecked_before_cache(platform):
    env = {"transactions": []}
    platform.execute("alice", "a", query(), env)
    platform.bridge.registry.permission_authority.revoke("finance.personal_budget")
    declined = platform.execute("alice", "a", query(), env)
    assert declined.graph is None


def test_composed_query_two_sources(platform):
    registry = platform.bridge.registry
    inventory = CapabilityManifest(
        "inventory.stock",
        "1.0.0",
        "inventory",
        [Modality.STRUCTURED],
        ["inventory"],
        schemas={"ontology": ["inventory"]},
        permissions=[Permission.FILESYSTEM_READ],
    )
    orders = CapabilityManifest(
        "orders.sales",
        "1.0.0",
        "orders",
        [Modality.STRUCTURED],
        ["orders"],
        schemas={
            "ontology": ["orders"],
            "intents": [
                {
                    "intent": "reconcile",
                    "pattern": "Match orders with inventory",
                    "slots": {},
                    "capabilities": ["inventory.stock"],
                    "dsl": "orders = OBS source=orders\nstock = OBS source=inventory\njoined = JOI left=orders right=stock on=sku\nresult = EMI in=joined",
                }
            ],
        },
        permissions=[Permission.FILESYSTEM_READ],
    )
    for manifest in (orders, inventory):
        registry.register_pack(manifest)
        registry.permission_authority.grant(
            manifest.id, Permission.FILESYSTEM_READ, "alice", "test"
        )
    result = platform.execute(
        "alice",
        "a",
        "Match orders with inventory",
        {"orders": [{"sku": "a"}], "inventory": [{"sku": "a"}, {"sku": "b"}]},
    )
    assert result.value == [({"sku": "a"}, {"sku": "a"})] and result.contract_satisfied
    assert platform.bridge.last_decision.selected_capability_ids == [
        "inventory.stock",
        "orders.sales",
    ]
    assert platform.telemetry._records[-1].active_capabilities == [
        "inventory.stock",
        "orders.sales",
    ]
    assert (
        "finance.personal_budget"
        not in platform.telemetry._records[-1].active_capabilities
    )
    registry.permission_authority.revoke("inventory.stock")
    with pytest.raises(PermissionError):
        platform.execute("alice", "a", "Match orders with inventory", {})


def test_private_store_actual_attack():
    store = ScopedPrivateStore()
    store.put("alice", "pack.a", "secret", 100)
    with pytest.raises(PermissionError):
        store.get("alice", "pack.b", "alice", "pack.a", "secret")
    with pytest.raises(PermissionError):
        store.get("bob", "pack.a", "alice", "pack.a", "secret")
    assert store.get("alice", "pack.a", "alice", "pack.a", "secret") == 100


def tx(category, amount):
    return {
        "category": category,
        "amount": amount,
        "currency": "USD",
        "date": "2026-10-06",
        "account": "checking",
    }


def test_failure_trajectory_persists_without_private_values(platform, tmp_path):
    registry = platform.bridge.registry
    registry.permission_authority.revoke("finance.personal_budget")
    try:
        platform.execute(
            "alice", "failure-session", query(), {"transactions": [tx("food", 80)]}
        )
    except PermissionError:
        pass
    telemetry = platform.telemetry._records[-1]
    saved = ExperienceRepository(tmp_path / "experiences.db").get(
        "alice", telemetry.request_id
    )
    assert not saved.contract_satisfied and saved.error_classification
    assert saved.query_text == "" and saved.slot_values == {}
    assert platform.last_audit.has_errors
    with pytest.raises(PermissionError):
        platform.experiences.get("bob", telemetry.request_id)


def test_external_source_requires_provenance_and_invalidates_changed_data(platform):
    import time

    registry = platform.bridge.registry
    m = registry.get_pack("finance.personal_budget").manifest
    registry.register_pack(
        replace(m, schemas={**m.schemas, "external_sources": ["transactions"]})
    )
    for permission in m.permissions:
        registry.permission_authority.grant(m.id, permission, "alice", "consent")
    with pytest.raises(ValueError, match="NO_DATA"):
        platform.execute(
            "alice", "external", query(), {"transactions": [tx("food", 999)]}
        )
    first = ExternalDataRecord(
        "transactions", "account", [tx("food", 80)], time.time(), 60, version="v1"
    )
    result = platform.execute("alice", "external", query(), {}, [first])
    assert result.value == 80
    assert platform.execute("alice", "external", query(), {}, [first]).reused_state
    second = replace(first, value=[tx("food", 120)], version="v2")
    changed = platform.execute("alice", "external", query(), {}, [second])
    assert changed.value == 120 and not changed.reused_state
    with pytest.raises(ValueError, match="STALE"):
        platform.execute("alice", "external", query(), {}, [replace(second, ttl=0)])
