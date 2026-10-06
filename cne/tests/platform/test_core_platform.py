"""Behavioral regression tests for platform hardening."""
import json
from dataclasses import replace
import pytest
from cne.platform.manifest import (
    CapabilityManifest,
    Modality,
    Permission,
    ToolDefinition,
    ModelDependency,
)
from cne.platform.registry import CapabilityRegistry, CapabilityResolver
from cne.platform.security import TrustMode, CapabilityPackageVerifier
from cne.platform.dsl import SemanticDSLParser
from cne.platform.memory import *
from cne.platform.bridge import PlatformControllerBridge
from cne.platform.device import DeviceProfile
from cne.platform.versions import ExecutionSemanticVersionVector
from cne.semantic_ir.evaluator import SemanticEvaluator


@pytest.fixture
def registry():
    return CapabilityRegistry(trust_mode=TrustMode.DEVELOPMENT_TRUST_MODE)


def manifest(cid="finance.budget", **kwargs):
    return CapabilityManifest(
        cid, "1.0.0", "test", [Modality.TEXT], ["budget"], **kwargs
    )


def test_permission_declared_is_not_granted(registry):
    registry.register_pack(manifest(permissions=[Permission.NETWORK_HTTP]))
    assert not registry.has_permission("finance.budget", Permission.NETWORK_HTTP)
    registry.permission_authority.grant(
        "finance.budget", Permission.NETWORK_HTTP, "alice", "unit-test"
    )
    assert registry.has_permission("finance.budget", Permission.NETWORK_HTTP, "alice")
    assert not registry.has_permission("finance.budget", Permission.NETWORK_HTTP, "bob")
    assert not registry.has_permission("finance.budget", Permission.CAMERA, "alice")
    registry.disable_pack("finance.budget")
    assert not registry.has_permission(
        "finance.budget", Permission.NETWORK_HTTP, "alice"
    )


def test_expired_grant_rejected(registry):
    registry.register_pack(manifest(permissions=[Permission.CAMERA]))
    registry.permission_authority.grant(
        "finance.budget", Permission.CAMERA, "alice", "test", expires_at=0
    )
    assert not registry.has_permission("finance.budget", Permission.CAMERA, "alice")


def test_production_rejects_unsigned():
    with pytest.raises(ValueError, match="MANIFEST_HASH_MISSING"):
        CapabilityRegistry().register_pack(manifest())


def test_corrupt_manifest_and_assets(tmp_path, registry):
    import hashlib

    asset = tmp_path / "model.bin"
    asset.write_bytes(b"weights")
    m = manifest(asset_hashes={"model.bin": hashlib.sha256(b"weights").hexdigest()})
    m = replace(m, package_hash=m.compute_manifest_hash())
    registry.register_pack(m, str(tmp_path))
    with pytest.raises(ValueError, match="MANIFEST_HASH_MISMATCH"):
        registry.register_pack(replace(m, description="modified"), str(tmp_path))
    asset.write_bytes(b"bad")
    with pytest.raises(ValueError, match="ASSET_HASH_MISMATCH"):
        registry.register_pack(m, str(tmp_path))


def test_production_signature_fail_closed():
    m = manifest()
    m = replace(m, package_hash=m.compute_manifest_hash(), signature="invalid")
    with pytest.raises(ValueError, match="INVALID_SIGNATURE"):
        CapabilityRegistry().register_pack(m)


def test_asset_escape_rejected(tmp_path, registry):
    with pytest.raises(ValueError, match="ASSET_MISSING"):
        registry.register_pack(
            manifest(asset_hashes={"../escape": "0" * 64}), str(tmp_path)
        )


@pytest.mark.parametrize(
    "kwargs,code",
    [
        (
            {"required_capabilities": ["missing.pack@1.0.0"]},
            "MISSING_CAPABILITY_DEPENDENCY",
        ),
        ({"required_capabilities": ["finance.budget"]}, "DEPENDENCY_CYCLE"),
        ({"backend_compatibility": ["NPU"]}, "BACKEND_UNAVAILABLE"),
        (
            {
                "model_dependencies": [
                    ModelDependency("controller", "TEXT", "missing", "1.0")
                ]
            },
            "MODEL_ASSET_MISSING",
        ),
    ],
)
def test_dependency_failures(registry, kwargs, code):
    with pytest.raises(ValueError, match=code):
        registry.register_pack(manifest(**kwargs))
    assert registry.get_pack("finance.budget") is None


def test_dependency_version(registry):
    registry.register_pack(manifest())
    with pytest.raises(ValueError, match="INCOMPATIBLE_CAPABILITY_VERSION"):
        registry.register_pack(
            manifest("travel.plan", required_capabilities=["finance.budget@2.0.0"])
        )


@pytest.mark.parametrize("repository_kind", ["memory", "sqlite"])
def test_session_ownership_persistence(tmp_path, repository_kind):
    repo = (
        InMemorySessionRepository()
        if repository_kind == "memory"
        else SQLiteSessionRepository(tmp_path / "sessions.db")
    )
    store = SessionStore(repo)
    store.record_turn(
        "s",
        "email alice@example.org",
        "finance.budget",
        "expense",
        {"threshold": 10},
        user_id="alice",
    )
    with pytest.raises(PermissionError, match="ACCESS_DENIED"):
        store.get_session("bob", "s")
    if repository_kind == "sqlite":
        repo.close()
        store = SessionStore(SQLiteSessionRepository(tmp_path / "sessions.db"))
    assert store.get_session("alice", "s").active_entities == {"threshold": 10}
    assert "alice@example" not in json.dumps(
        store.get_session("alice", "s").semantic_history
    )


def correction(**kwargs):
    return CorrectionRecord(
        "c1",
        "fp",
        "email a@example.org calculate budget",
        "finance.budget",
        "1",
        "1",
        "SLOT_ERROR",
        "bad",
        "good",
        **kwargs,
    )


def test_unverified_and_cross_user_corrections(tmp_path):
    store = CorrectionStore(tmp_path / "corrections.db")
    record = correction(user_id="alice")
    store.add_correction(record)
    assert not store.get_corrections_for_capability("finance.budget", "alice")
    with pytest.raises(PermissionError):
        store.get_correction("bob", "c1")
    assert "a@example.org" not in store.get_correction("alice", "c1").query_redacted
    record.audit_status = AuditStatus.USER_SCOPED
    store.add_correction(record)
    assert store.retrieve(
        record.query_redacted, "finance.budget", "alice", controller_version="1"
    )
    assert not store.retrieve(record.query_redacted, "finance.budget", "bob")
    assert not store.retrieve(
        record.query_redacted, "finance.budget", "alice", controller_version="2"
    )
    reopened = CorrectionStore(tmp_path / "corrections.db")
    assert reopened.get_correction("alice", "c1").audit_status == "USER_SCOPED"


def test_verified_requires_evidence():
    with pytest.raises(ValueError):
        CorrectionStore().add_correction(correction(audit_status=AuditStatus.VERIFIED))


def test_fingerprint_normalization():
    assert request_fingerprint("  Budget  FOOD ", ["a"]) == request_fingerprint(
        "budget food", ["a"]
    )
    assert request_fingerprint("budget food", ["a"]) != request_fingerprint(
        "budget food", ["b"]
    )


def test_plan_rebind_and_scope():
    cache = SemanticPlanCache()
    template = SemanticPlanTemplate(
        "s", "n = LIT value=${x}\ne = EMI in=n", "v", "c", "2", ("x",)
    )
    cache.put_template("alice", template)
    one = cache.bind("alice", "s", {"x": 1}, "v", "c", "2")
    two = cache.bind("alice", "s", {"x": 2}, "v", "c", "2")
    assert one != two and "value=2" in two
    with pytest.raises(ValueError):
        cache.bind("alice", "s", {}, "v", "c", "2")
    assert cache.bind("bob", "s", {"x": 1}, "v", "c", "2") is None


def evaluate(dsl, env=None):
    res = SemanticDSLParser.compile_dsl(dsl)
    assert res.is_valid, res.error_message
    return SemanticEvaluator().execute(res.graph, env or {})[0]


def test_explicit_references_and_filter_zero():
    assert (
        evaluate(
            "a = OBS source=data\nb = FIL in=a op=gte val=0\nc = RED in=b reducer=sum\nd = EMI in=c",
            {"data": [-3, 0, 2]},
        )
        == 2
    )


def test_join_multi_source():
    assert evaluate(
        "a = OBS source=orders\nb = OBS source=inventory\nc = JOI left=a right=b on=sku\nd = EMI in=c",
        {"orders": [{"sku": 1}], "inventory": [{"sku": 1}, {"sku": 2}]},
    ) == [({"sku": 1}, {"sku": 1})]


@pytest.mark.parametrize(
    "dsl",
    [
        "a = OBS source=x\ne = EMI in=missing",
        "a = LIT value=1\na = LIT value=2\ne = EMI in=a",
        "a = MAP in=b field=x\nb = MAP in=a field=x\ne = EMI in=a",
        "a = LIT value=1\ne = EMI in=a,b",
        "a = OBS source=x mystery=1\ne = EMI in=a",
        "a = OBS source=x",
        "a = LIT value=1\nb = RED in=a reducer=sum\ne = EMI in=b",
        "a = LIT value=1\nb = LIT value=2\ne = EMI in=a",
        "a = LIT value=1\ne = EMI in=a\nf = EMI in=a",
        "OBS source=data\nEMI in=data",
    ],
)
def test_invalid_dags(dsl):
    assert not SemanticDSLParser.compile_dsl(dsl).is_valid


def test_branch_is_lazy():
    dsl = """REGION yes root=y
y = LIT value=42
END
REGION no root=z
bad = OBS source=bad
z = MAP in=bad field=missing
END
condition = LIT value=true
b = BRA in=condition then_region=yes else_region=no
e = EMI in=b"""
    # Mismatched branch types are rejected before execution.
    assert not SemanticDSLParser.compile_dsl(dsl).is_valid
    dsl = dsl.replace("y = LIT value=42", "y = OBS source=good")
    assert evaluate(dsl, {"good": [42], "bad": [{}]}) == [42]


def test_iterate_region():
    dsl = """REGION step root=item
item = OBS source=_loop_item type=numeric
END
items = OBS source=items
loop = ITE in=items step_region=step initial=0
result = EMI in=loop"""
    assert evaluate(dsl, {"items": [1, 2, 3]}) == 3


def test_choose():
    assert (
        evaluate(
            "a = OBS source=actions\nc = CHO in=a\ne = EMI in=c",
            {
                "actions": [
                    {"id": "a", "expected_utility": 1},
                    {"id": "b", "expected_utility": 2},
                ]
            },
        )
        is not None
    )


def test_device_measurements():
    snap = DeviceProfile().capture_snapshot()
    assert snap.process_rss_mb > 0 and snap.thermal_state == "UNKNOWN"
    assert DeviceProfile().budget.evaluate(
        snap, peak_memory_mb=10, steady_memory_mb=10, concurrent_inferences=2
    ).violations == ["concurrent_inferences"]


def test_no_fabricated_bridge(registry):
    bridge = PlatformControllerBridge(registry)
    result = bridge.compile("Calculate total spending", context={"user_id": "alice"})
    assert result.graph is None and result.outcome.value == "UNSUPPORTED_INTENT"
    with pytest.raises(PermissionError):
        bridge.compile("anything")


def test_resolver_composes_and_checks_grants(registry):
    registry.register_pack(manifest(schemas={"ontology": ["workout"]}))
    registry.register_pack(
        manifest(
            "calendar.events",
            schemas={"ontology": ["meeting"]},
            permissions=[Permission.CALENDAR_READ],
        )
    )
    result = CapabilityResolver(registry).resolve(
        "move workout around meeting", "alice"
    )
    assert (
        len(result.candidate_capabilities) == 2
        and len(result.selected_capabilities) == 1
    )
    registry.permission_authority.grant(
        "calendar.events", Permission.CALENDAR_READ, "alice", "test"
    )
    assert (
        len(
            CapabilityResolver(registry)
            .resolve("move workout around meeting", "alice")
            .selected_capabilities
        )
        == 2
    )


def test_selective_vectors(registry):
    tools = [
        ToolDefinition("finance.used", "1", "module:fn"),
        ToolDefinition("finance.unused", "1", "module:fn"),
    ]
    m = manifest(deterministic_tools=tools)
    other = manifest("agri.crop")
    registry.register_pack(m)
    registry.register_pack(other)

    def vector(**kw):
        return ExecutionSemanticVersionVector.for_execution(
            registry, ["finance.budget"], ["finance.used"], **kw
        ).digest()

    original = vector()
    registry.register_pack(replace(other, version="1.0.1"))
    assert vector() == original
    registry.register_pack(
        replace(
            m, deterministic_tools=[tools[0], replace(tools[1], schema_version="2")]
        )
    )
    assert vector() == original
    registry.register_pack(
        replace(
            m, deterministic_tools=[replace(tools[0], schema_version="2"), tools[1]]
        )
    )
    assert vector() != original
    registry.register_pack(m)
    assert vector(adapters=[("used", "1")]) != vector(adapters=[("used", "2")])
    assert vector(models=[("controller", "1")]) != vector(models=[("controller", "2")])
    registry.register_pack(replace(m, version="1.0.1"))
    assert vector() != original


def test_two_pack_dependency_cycle(registry):
    a = manifest(required_capabilities=["travel.plan"])
    b = manifest("travel.plan", required_capabilities=["finance.budget"])
    registry.register_pack(a, auto_enable=False)
    registry.register_pack(b, auto_enable=False)
    with pytest.raises(ValueError, match="DEPENDENCY_CYCLE"):
        registry.enable_pack(a.id)


def test_wrong_model_hash(tmp_path):
    asset = tmp_path / "m.gguf"
    asset.write_bytes(b"weights")
    registry = CapabilityRegistry(
        trust_mode=TrustMode.DEVELOPMENT_TRUST_MODE,
        model_assets={"m": {"path": str(asset), "version": "1", "sha256": "0" * 64}},
    )
    with pytest.raises(ValueError, match="MODEL_HASH_MISMATCH"):
        registry.register_pack(
            manifest(
                model_dependencies=[ModelDependency("controller", "TEXT", "m", "1")]
            )
        )


def test_actual_file_and_network_denial(tmp_path, registry):
    from cne.platform.security import PermissionBroker

    root = tmp_path / "allowed"
    root.mkdir()
    (root / "ok").write_text("ok")
    outside = tmp_path / "secret"
    outside.write_text("private")
    m = manifest(permissions=[Permission.FILESYSTEM_READ, Permission.NETWORK_HTTP])
    registry.register_pack(m)
    broker = PermissionBroker(registry, {("alice", m.id): [root]})
    with pytest.raises(PermissionError):
        broker.read_file(m.id, "alice", root / "ok")
    with pytest.raises(PermissionError):
        broker.authorize_network(m.id, "alice")
    registry.permission_authority.grant(
        m.id, Permission.FILESYSTEM_READ, "alice", "test"
    )
    assert broker.read_file(m.id, "alice", root / "ok") == b"ok"
    with pytest.raises(PermissionError):
        broker.read_file(m.id, "alice", outside)
    registry.permission_authority.grant(m.id, Permission.NETWORK_HTTP, "alice", "test")
    with pytest.raises(PermissionError, match="offline"):
        broker.authorize_network(m.id, "alice")


def test_nested_branch_in_iterate():
    dsl = """REGION yes root=yes_value
yes_value = OBS source=_loop_item type=numeric
END
REGION no root=no_value
no_value = LIT value=0
END
REGION step root=branch
condition = LIT value=true
branch = BRA in=condition then_region=yes else_region=no
END
items = OBS source=items
loop = ITE in=items step_region=step initial=0
result = EMI in=loop"""
    assert evaluate(dsl, {"items": [1, 2, 9]}) == 9


def test_installed_weather_is_not_globally_rejected(registry):
    from cne.platform.manifest import NetworkMode

    m = manifest(
        "weather.current",
        schemas={
            "intents": [
                {
                    "intent": "current_weather",
                    "pattern": "current weather in (?P<city>[A-Za-z]+)",
                    "slots": {"city": {"type": "string", "required": True}},
                    "dsl": "weather = OBS source=weather key=${city} type=any\nresult = EMI in=weather",
                }
            ]
        },
        permissions=[Permission.NETWORK_HTTP],
        network_mode=NetworkMode.LOCAL_COMPUTE_NETWORK_DATA,
    )
    registry.register_pack(m)
    bridge = PlatformControllerBridge(registry)
    assert (
        bridge.compile("current weather in Mumbai", context={"user_id": "alice"}).graph
        is None
    )
    registry.permission_authority.grant(m.id, Permission.NETWORK_HTTP, "alice", "test")
    result = bridge.compile("current weather in Mumbai", context={"user_id": "alice"})
    assert result.graph is not None and result.extracted_slots == {"city": "Mumbai"}
    assert result.confidence is None
    assert bridge.compile("buy 100 shares", context={"user_id": "alice"}).graph is None


def test_runtime_controller_protocol_boundary(registry):
    # Isolated runtime boundary only; this test makes no model quality claim.
    from cne.platform.bridge import RuntimeSemanticController
    from cne.platform.models import ModelDescriptor, ModelKind, ModelResult

    class RuntimeBoundary:
        def is_loaded(self, model_id):
            return True

        def infer(self, request):
            return ModelResult(
                request.request_id,
                request.model_id,
                json.dumps(
                    {
                        "outcome": "COMPILED",
                        "selected_capability_ids": ["finance.budget"],
                        "intent": "total",
                        "extracted_slots": {},
                        "semantic_dsl": "a = OBS source=data\nb = RED in=a reducer=sum\ne = EMI in=b",
                    }
                ),
                0,
            )

    registry.register_pack(manifest(schemas={"sources": ["data"], "slots": {}}))
    descriptor = ModelDescriptor("test-boundary", ModelKind.TEXT_GENERATION, "2", 0)
    bridge = PlatformControllerBridge(
        registry,
        controller=RuntimeSemanticController(registry, RuntimeBoundary(), descriptor),
    )
    result = bridge.compile("sum data", context={"user_id": "alice"})
    assert result.graph.metadata["execution_vector"].models == (("test-boundary", "2"),)
    assert result.confidence is None
    registry.register_pack(manifest(schemas={"sources": [], "slots": {}}))
    assert bridge.compile("sum data", context={"user_id": "alice"}).graph is None
