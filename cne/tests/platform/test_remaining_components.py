"""Behavioral tests for the remaining platform services."""
import hashlib
import json
import sys
import threading
import zipfile
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from cne.platform.security import (
    PermissionAuthority,
    IdentityAuthority,
    Ed25519TrustStore,
    CapabilityPackageVerifier,
    PermissionBroker,
    TrustMode,
)
from cne.platform.registry import CapabilityRegistry
from cne.platform.manifest import CapabilityManifest, Modality, Permission, NetworkMode
from cne.platform.packages import CapabilityPackageInstaller
from cne.platform.external_data import ExternalDataCache, HTTPJSONConnector
from cne.platform.sandbox import BubblewrapWorker, SandboxUnavailable


def manifest(**kw):
    return CapabilityManifest(
        "finance.budget", "1.0.0", "test", [Modality.TEXT], ["budget"], **kw
    )


def test_durable_registry_permissions_and_revocation(tmp_path):
    auth = PermissionAuthority(tmp_path / "grants.db")
    reg = CapabilityRegistry(
        trust_mode=TrustMode.DEVELOPMENT_TRUST_MODE,
        database_path=tmp_path / "registry.db",
        permission_authority=auth,
    )
    reg.register_pack(manifest(permissions=[Permission.CAMERA]))
    auth.grant("finance.budget", Permission.CAMERA, "alice", "explicit consent")
    reopened = CapabilityRegistry(
        trust_mode=TrustMode.DEVELOPMENT_TRUST_MODE,
        database_path=tmp_path / "registry.db",
        permission_authority=PermissionAuthority(tmp_path / "grants.db"),
    )
    assert reopened.has_permission("finance.budget", Permission.CAMERA, "alice")
    auth.revoke("finance.budget")
    assert not reopened.has_permission("finance.budget", Permission.CAMERA, "alice")
    reopened.disable_pack("finance.budget")
    assert (
        not CapabilityRegistry(
            trust_mode=TrustMode.DEVELOPMENT_TRUST_MODE,
            database_path=tmp_path / "registry.db",
        )
        .get_pack("finance.budget")
        .is_enabled()
    )


def test_identity_bearer_expiry_and_revocation(tmp_path):
    authority = IdentityAuthority(tmp_path / "identity.db")
    token = authority.issue("alice")
    reopened = IdentityAuthority(tmp_path / "identity.db")
    assert reopened.authenticate(token) == "alice"
    assert token not in (tmp_path / "identity.db").read_bytes().decode("latin1")
    with pytest.raises(PermissionError):
        reopened.authenticate("alice")
    authority.revoke(token)
    with pytest.raises(PermissionError):
        reopened.authenticate(token)


def test_real_signatures_package_install_and_tampering(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private = Ed25519PrivateKey.generate()
    trust = Ed25519TrustStore(tmp_path / "keys.db")
    trust.trust(
        "publisher",
        private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
        "finance",
    )
    verifier = CapabilityPackageVerifier(signature_verifier=trust.verify)
    reg = CapabilityRegistry(
        package_verifier=verifier, database_path=tmp_path / "reg.db"
    )
    payload = b'print("hello")'
    m = trust.sign(
        manifest(asset_hashes={"tool.py": hashlib.sha256(payload).hexdigest()}),
        "publisher",
        private,
    )
    archive = tmp_path / "pack.cap"
    from dataclasses import asdict

    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("manifest.json", json.dumps(asdict(m)))
        z.writestr("tool.py", payload)
    installed = CapabilityPackageInstaller(reg, tmp_path / "packs").install(archive)
    assert (
        installed.is_enabled()
        and (
            tmp_path / "packs" / m.id / m.compute_manifest_hash() / "tool.py"
        ).read_bytes()
        == payload
    )
    with pytest.raises(ValueError):
        verifier.verify(replace(m, description="tampered"), installed.install_path)
    trust.revoke("publisher")
    with pytest.raises(ValueError, match="INVALID_SIGNATURE"):
        verifier.verify(m, installed.install_path)


def test_archive_escape_rejected(tmp_path):
    archive = tmp_path / "bad.cap"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape", "no")
    installer = CapabilityPackageInstaller(
        CapabilityRegistry(trust_mode=TrustMode.DEVELOPMENT_TRUST_MODE),
        tmp_path / "packs",
    )
    with pytest.raises(ValueError, match="Unsafe"):
        installer.install(archive)
    assert not (tmp_path / "escape").exists()


def test_real_http_fetch_cache_and_denial(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        requests = 0

        def do_GET(self):
            Handler.requests += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("ETag", "v1")
            self.end_headers()
            self.wfile.write(b'{"temperature":25}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    reg = CapabilityRegistry(trust_mode=TrustMode.DEVELOPMENT_TRUST_MODE)
    reg.register_pack(
        manifest(
            permissions=[Permission.NETWORK_HTTP],
            network_mode=NetworkMode.LOCAL_COMPUTE_NETWORK_DATA,
        )
    )
    cache = ExternalDataCache(tmp_path / "data.db")
    connector = HTTPJSONConnector(
        PermissionBroker(reg), cache, ["127.0.0.1"], allow_loopback_http=True
    )
    url = f"http://127.0.0.1:{server.server_port}/weather"
    try:
        with pytest.raises(PermissionError):
            connector.fetch("finance.budget", "alice", "weather", "city", url, 60)
        assert Handler.requests == 0
        reg.permission_authority.grant(
            "finance.budget", Permission.NETWORK_HTTP, "alice", "consent"
        )
        fetched = connector.fetch("finance.budget", "alice", "weather", "city", url, 60)
        assert (
            fetched.status == "LIVE_FETCHED"
            and fetched.record.value["temperature"] == 25
        )
        assert (
            connector.fetch(
                "finance.budget", "alice", "weather", "city", url, 60
            ).status
            == "LOCAL_CACHED"
        )
        assert Handler.requests == 1
        assert (
            ExternalDataCache(tmp_path / "data.db")
            .get("alice", "weather", "city")
            .version
            == "v1"
        )
        assert cache.get("bob", "weather", "city") is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_sandbox_fails_closed_on_unsupported_host(tmp_path):
    if sys.platform == "linux":
        pytest.skip("Linux worker tested by native integration probe")
    with pytest.raises(SandboxUnavailable):
        BubblewrapWorker().run(tmp_path, "worker.py", {})


def test_adapter_activation_failure_recovery_and_regression_rollback(tmp_path):
    from cne.platform.adapters import AdapterDeploymentManager
    from cne.platform.learning import (
        AdaptationCandidate,
        CandidateEvaluator,
        EvaluationCase,
        GatedAdaptationPipeline,
    )
    from cne.platform.models import ModelDescriptor, ModelKind

    datasets = {
        name: [EvaluationCase(name, 7, 7)] for name in CandidateEvaluator.REQUIRED
    }
    evaluator = CandidateEvaluator(datasets)
    pipeline = GatedAdaptationPipeline(
        evaluator=evaluator, database_path=tmp_path / "adapters.db"
    )

    class RuntimeBoundary:
        fail = False
        path = None

        def activate_adapter(self, descriptor, path, commit):
            if self.fail:
                raise RuntimeError("load failed")
            commit()
            self.path = path

    runtime = RuntimeBoundary()
    manager = AdapterDeploymentManager(pipeline, runtime, tmp_path / "assets")
    descriptor = ModelDescriptor("model", ModelKind.TEXT_GENERATION, "1", 1)
    candidates = []
    for version in ("1", "2"):
        path = tmp_path / (version + ".gguf")
        path.write_bytes(("boundary-test-" + version).encode())
        candidate = AdaptationCandidate(
            "adapter",
            version,
            "finance.budget",
            "model",
            1,
            artifact_path=str(path),
            artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        evaluation = pipeline.evaluate_candidate(
            candidate, lambda x: x, lambda x: x, "base"
        )
        if version == "2":
            runtime.fail = True
            with pytest.raises(RuntimeError):
                manager.deploy(candidate, evaluation, descriptor)
            assert pipeline.get_active("finance.budget") == candidates[0]
            runtime.fail = False
        assert manager.deploy(candidate, evaluation, descriptor)
        candidates.append(candidate)
    recovered = AdapterDeploymentManager(
        GatedAdaptationPipeline(database_path=tmp_path / "adapters.db"),
        runtime,
        tmp_path / "assets",
    )
    assert recovered.recover("finance.budget", descriptor)
    with pytest.raises(ValueError, match="MODEL_VERSION_MISMATCH"):
        recovered.recover("finance.budget", replace(descriptor, model_id="wrong"))
    failure = manager.evaluate_active(
        "finance.budget", descriptor, lambda x: None, lambda x: x, "base"
    )
    assert not failure.passed and pipeline.get_active("finance.budget") == candidates[0]
    (tmp_path / "assets" / (candidates[0].artifact_sha256 + ".gguf")).write_bytes(
        b"tampered"
    )
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        recovered.recover("finance.budget", descriptor)


def test_signed_publisher_revocation_blocks_existing_execution(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from cne.platform.bridge import PlatformControllerBridge

    key = Ed25519PrivateKey.generate()
    trust = Ed25519TrustStore(tmp_path / "keys.db")
    trust.trust(
        "publisher",
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
        "finance",
    )
    m = trust.sign(
        manifest(
            schemas={
                "intents": [
                    {
                        "pattern": "budget",
                        "intent": "literal",
                        "dsl": "v = LIT value=42\ne = EMI in=v",
                        "slots": {},
                    }
                ]
            }
        ),
        "publisher",
        key,
    )
    registry = CapabilityRegistry(
        package_verifier=CapabilityPackageVerifier(signature_verifier=trust.verify)
    )
    registry.register_pack(m)
    bridge = PlatformControllerBridge(registry)
    assert bridge.compile("budget", "s", {"user_id": "alice"}).graph is not None
    trust.revoke("publisher")
    with pytest.raises(ValueError, match="INVALID_SIGNATURE"):
        bridge.compile("budget", "s", {"user_id": "alice"})


def test_first_adapter_regression_restores_base(tmp_path):
    from cne.platform.adapters import AdapterDeploymentManager
    from cne.platform.learning import (
        AdaptationCandidate,
        CandidateEvaluator,
        EvaluationCase,
        GatedAdaptationPipeline,
    )
    from cne.platform.models import ModelDescriptor, ModelKind

    evaluator = CandidateEvaluator(
        {name: [EvaluationCase(name, 1, 1)] for name in CandidateEvaluator.REQUIRED}
    )
    pipeline = GatedAdaptationPipeline(evaluator=evaluator)
    asset = tmp_path / "adapter.gguf"
    asset.write_bytes(b"boundary-only")
    candidate = AdaptationCandidate(
        "adapter",
        "1",
        "finance.budget",
        "model",
        1,
        artifact_path=str(asset),
        artifact_sha256=hashlib.sha256(asset.read_bytes()).hexdigest(),
    )
    evaluation = pipeline.evaluate_candidate(
        candidate, lambda x: x, lambda x: x, "base"
    )

    class RuntimeBoundary:
        path = "initial"

        def activate_adapter(self, descriptor, path, commit):
            commit()
            self.path = path

    runtime = RuntimeBoundary()
    descriptor = ModelDescriptor("model", ModelKind.TEXT_GENERATION, "1", 1)
    manager = AdapterDeploymentManager(pipeline, runtime, tmp_path / "assets")
    assert manager.deploy(candidate, evaluation, descriptor)
    manager.evaluate_active(
        "finance.budget", descriptor, lambda x: None, lambda x: x, "base"
    )
    assert runtime.path is None and pipeline.get_active("finance.budget") is None
