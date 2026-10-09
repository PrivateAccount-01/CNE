"""Explicit production composition: every durable service shares an app-private root."""
from dataclasses import dataclass
from pathlib import Path
from cne.platform.security import (
    TrustMode,
    PermissionAuthority,
    IdentityAuthority,
    Ed25519TrustStore,
    CapabilityPackageVerifier,
)
from cne.platform.registry import CapabilityRegistry
from cne.platform.memory import (
    SessionStore,
    SQLiteSessionRepository,
    CorrectionStore,
    SemanticPlanCache,
)
from cne.platform.execution import PlatformExecutor, ExperienceRepository
from cne.platform.bridge import (
    PlatformControllerBridge,
    PlatformSemanticController,
    RuntimeSemanticController,
)
from cne.platform.learning import LearningReplayStore, GatedAdaptationPipeline
from cne.platform.storage import SQLiteReplayRepository
from cne.platform.state_repository import StateFabricRepository
from cne.platform.correction_review import CorrectionReviewService
from cne.platform.external_data import ExternalDataCache
from cne.platform.telemetry import LocalTelemetryCollector


@dataclass(frozen=True)
class PlatformRuntimeConfig:
    storage_root: str | None = None
    mode: str = "production"
    in_memory: bool = False
    candidate_limit: int = 5
    controller_residency_budget_mb: float = 1024.0
    key_provider: object | None = None
    key_id: str | None = None

    def __post_init__(self):
        if self.mode not in ("production", "development", "test"):
            raise ValueError("Unknown runtime mode")
        if self.in_memory and self.mode != "test":
            raise ValueError("Volatile storage requires explicit test mode")
        if not self.in_memory and not self.storage_root:
            raise ValueError("A private storage root is required")
        if not 1 <= self.candidate_limit <= 8:
            raise ValueError("Candidate K must be 1..8")
        if self.controller_residency_budget_mb <= 0:
            raise ValueError("Controller residency budget must be positive")
        if bool(self.key_provider) != bool(self.key_id):
            raise ValueError("key_provider and key_id must be configured together")
        if self.mode == "production" and self.key_provider is None:
            raise ValueError("Production storage requires a host key provider")


class PlatformStorageLayout:
    def __init__(self, config):
        self.config = config
        self.root = Path(config.storage_root).resolve() if config.storage_root else None
        if self.root:
            self.root.mkdir(parents=True, exist_ok=True)
            for name in ("cne_state", "adapters", "capability_packages", "telemetry"):
                (self.root / name).mkdir(exist_ok=True)

    def database(self, name):
        return (
            ":memory:" if self.config.in_memory else str(self.root / (name + ".sqlite"))
        )


@dataclass
class PlatformRuntime:
    config: PlatformRuntimeConfig
    layout: PlatformStorageLayout
    executor: PlatformExecutor
    registry: CapabilityRegistry
    identity: IdentityAuthority
    trust: Ed25519TrustStore
    review: CorrectionReviewService
    replay: LearningReplayStore
    adaptations: GatedAdaptationPipeline
    external_data: ExternalDataCache
    encryption: object | None = None
    residency_manager: object | None = None

    def close(self):
        if self.residency_manager is not None:
            self.residency_manager.unload_all()
        # Close each SQLite connection once; users may safely reopen the composition.
        candidates = [
            self.registry,
            self.registry.permission_authority,
            self.identity,
            self.trust,
            self.review.store,
            self.executor.experiences,
            self.replay.repository,
            self.adaptations,
            self.external_data,
            self.executor.bridge.session_store.repository,
            self.executor.bridge.controller.plan_cache,
            self.executor.state_repository,
            self.executor.telemetry,
        ]
        seen = set()
        for obj in candidates:
            db = getattr(obj, "db", None)
            if db is not None and id(db) not in seen:
                db.close()
                seen.add(id(db))


class PlatformRuntimeFactory:
    @staticmethod
    def create(config, model_runtime=None, descriptor=None, verifiers=None):
        if (model_runtime is None) != (descriptor is None):
            raise ValueError("Model runtime and descriptor must be configured together")
        if descriptor is not None and descriptor.estimated_ram_mb <= 0:
            raise ValueError("Controller model requires a positive memory estimate")
        layout = PlatformStorageLayout(config)
        from cne.platform.storage import EncryptedPayloadCodec

        encryption = (
            EncryptedPayloadCodec(config.key_provider, config.key_id)
            if config.key_provider
            else None
        )
        authority = PermissionAuthority(layout.database("permissions"))
        trust = Ed25519TrustStore(layout.database("publisher_keys"))
        mode = (
            TrustMode.PRODUCTION
            if config.mode == "production"
            else TrustMode.DEVELOPMENT_TRUST_MODE
        )
        registry = CapabilityRegistry(
            permission_authority=authority,
            package_verifier=CapabilityPackageVerifier(mode, trust.verify),
            database_path=layout.database("registry"),
        )
        plans = SemanticPlanCache(layout.database("semantic_plans"), codec=encryption)
        residency_manager = None
        if model_runtime is not None:
            from cne.platform.models import ModelResidencyManager

            residency_manager = ModelResidencyManager(
                config.controller_residency_budget_mb, model_runtime
            )
        controller = (
            RuntimeSemanticController(
                registry,
                model_runtime,
                descriptor,
                residency_manager=residency_manager,
                candidate_limit=config.candidate_limit,
            )
            if model_runtime
            else PlatformSemanticController(registry, plans)
        )
        controller.plan_cache = plans
        bridge = PlatformControllerBridge(
            registry,
            SessionStore(
                SQLiteSessionRepository(layout.database("sessions"), codec=encryption)
            ),
            controller=controller,
        )
        corrections = CorrectionStore(layout.database("corrections"), codec=encryption)
        experiences = ExperienceRepository(
            layout.database("experiences"), codec=encryption
        )
        executor = PlatformExecutor(
            bridge,
            corrections,
            experiences,
            LocalTelemetryCollector(
                database_path=layout.database("telemetry"), codec=encryption
            ),
            StateFabricRepository(layout.database("cne_state/state"), codec=encryption),
        )
        replay = LearningReplayStore(
            repository=SQLiteReplayRepository(
                layout.database("replay"), codec=encryption
            )
        )
        return PlatformRuntime(
            config,
            layout,
            executor,
            registry,
            IdentityAuthority(layout.database("identity")),
            trust,
            CorrectionReviewService(corrections, experiences, verifiers),
            replay,
            GatedAdaptationPipeline(
                replay_store=replay,
                database_path=layout.database("adapters"),
                codec=encryption,
            ),
            ExternalDataCache(layout.database("external_data"), codec=encryption),
            encryption,
            residency_manager,
        )
