"""Platform orchestration; CNE execution and verification remain authoritative."""
from __future__ import annotations
from dataclasses import replace, asdict
import hashlib
import importlib
import json
import sqlite3
import time
import uuid
from cne.compiler.nl_compiler import ClassificationOutcome
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.platform.auditor import ErrorAuditor
from cne.platform.errors import FreshnessError
from cne.platform.operations import authorize_operation
from cne.platform.memory import CorrectionStore, ExperienceRecord, request_fingerprint
from cne.platform.telemetry import RequestTelemetry, LocalTelemetryCollector
from cne.semantic_ir.nodes import OpKind
from cne.signature.shape_key import SemanticShapeKey


class ScopedPrivateStore:
    """Caller identity must come from a trusted dispatcher, never pack arguments."""

    def __init__(self):
        self._values = {}

    def put(self, caller_user, caller_pack, key, value):
        self._values[caller_user, caller_pack, key] = value

    def get(self, caller_user, caller_pack, owner_user, owner_pack, key):
        if (caller_user, caller_pack) != (owner_user, owner_pack):
            raise PermissionError("ACCESS_DENIED")
        return self._values.get((owner_user, owner_pack, key))


class ExperienceRepository:
    def __init__(self, path=":memory:", codec=None):
        self.db = sqlite3.connect(path)
        self.codec = codec
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS experiences (id TEXT PRIMARY KEY,owner TEXT,payload TEXT)"
        )
        self.db.commit()

    def save(self, record):
        with self.db:
            self.db.execute(
                "INSERT INTO experiences VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,payload=excluded.payload WHERE experiences.owner=excluded.owner",
                (
                    record.experience_id,
                    record.user_id,
                    self._seal(asdict(record), record.user_id),
                ),
            )

    def _seal(self, payload, owner):
        return (
            self.codec.seal(payload, owner, "experiences")
            if self.codec
            else json.dumps(payload)
        )

    def get(self, user_id, experience_id):
        row = self.db.execute(
            "SELECT owner,payload FROM experiences WHERE id=?", (experience_id,)
        ).fetchone()
        if not row:
            return None
        if row[0] != user_id:
            raise PermissionError("ACCESS_DENIED")
        payload = (
            self.codec.open(row[1], row[0], "experiences")
            if self.codec
            else json.loads(row[1])
        )
        return ExperienceRecord(**payload)

    def list_user(self, user_id):
        rows = self.db.execute(
            "SELECT owner,payload FROM experiences WHERE owner=?", (user_id,)
        ).fetchall()
        result = []
        for owner, payload in rows:
            data = (
                self.codec.open(payload, owner, "experiences")
                if self.codec
                else json.loads(payload)
            )
            result.append(ExperienceRecord(**data))
        return result


class MutationAuthority:
    def __init__(self, engine):
        self.engine = engine

    def mutate(self, source, change_type, mutation):
        # Even a partially failing tool may have changed data: always invalidate.
        try:
            return mutation()
        finally:
            self.engine.fabric.notify_data_mutation(change_type, source)


class PlatformExecutor:
    def __init__(
        self,
        bridge,
        corrections=None,
        experiences=None,
        telemetry=None,
        state_repository=None,
    ):
        self.state_repository = state_repository
        self.bridge = bridge
        self.corrections = corrections or CorrectionStore()
        self.experiences = experiences or ExperienceRepository()
        self.telemetry = telemetry or LocalTelemetryCollector()
        self.auditor = ErrorAuditor(self.corrections)
        self._engines = {}
        self._external_versions = {}
        self.last_audit = None

    def engine_for(self, user_id):
        if not user_id:
            raise PermissionError("ACCESS_DENIED")
        if user_id not in self._engines:
            from cne.platform.state_repository import PersistentStateFabric

            fabric = (
                PersistentStateFabric(self.state_repository, user_id)
                if self.state_repository
                else None
            )
            self._engines[user_id] = ComputationNecessityEngine(fabric=fabric)
        return self._engines[user_id]

    def execute_authenticated(
        self, identity_authority, token, session_id, query, env, external_records=()
    ):
        return self.execute(
            identity_authority.authenticate(token),
            session_id,
            query,
            env,
            external_records,
        )

    def execute(self, user_id, session_id, query, env, external_records=()):
        if not user_id:
            raise PermissionError("ACCESS_DENIED")
        start = time.perf_counter()
        try:
            return self._execute(user_id, session_id, query, env, external_records)
        except Exception as exc:
            from cne.platform.auditor import ErrorType

            from cne.platform.errors import classify_exception

            category = ErrorType(classify_exception(exc))
            # Exception messages can contain private inputs. Persist only the type.
            self._record_failure(
                user_id,
                session_id,
                query,
                start,
                "EXECUTION_FAILURE",
                category,
                type(exc).__name__,
            )
            raise

    def _record_decline(self, user_id, session_id, query, start, outcome):
        labels = {
            ClassificationOutcome.UNSUPPORTED_INTENT: "DECLINED_UNSUPPORTED",
            ClassificationOutcome.AMBIGUOUS_INTENT: "NEEDS_CLARIFICATION",
            ClassificationOutcome.LOW_CONFIDENCE_MAPPING: "DECLINED_LOW_CONFIDENCE",
        }
        label = labels[outcome]
        request_id = uuid.uuid4().hex
        duration = (time.perf_counter() - start) * 1000
        self.experiences.save(
            ExperienceRecord(
                request_id,
                session_id,
                "",
                [],
                "",
                "",
                label,
                False,
                duration,
                user_id=user_id,
                input_fingerprint=request_fingerprint(query),
                verification_result={"status": "NOT_EXECUTED"},
            )
        )
        self.last_experience_id = request_id
        self.last_audit = self.auditor.generate_session_report(session_id, [], 1)
        self.telemetry.record(
            RequestTelemetry(
                request_id,
                session_id,
                [],
                [],
                "NOT_EXECUTED",
                None,
                total_latency_ms=duration,
                contract_status=label,
            )
        )

    def _record_failure(
        self, user_id, session_id, query, start, outcome, category, exception_type=None
    ):
        from cne.platform.auditor import AuditSignal

        request_id = uuid.uuid4().hex
        duration = (time.perf_counter() - start) * 1000
        execution_status = "NOT_MEASURED" if exception_type else "NOT_EXECUTED"
        self.experiences.save(
            ExperienceRecord(
                request_id,
                session_id,
                "",
                [],
                "",
                "",
                outcome,
                False,
                duration,
                user_id=user_id,
                input_fingerprint=request_fingerprint(query),
                error_classification=category.value,
                verification_result={
                    "status": execution_status,
                    "exception_type": exception_type,
                },
            )
        )
        self.last_experience_id = request_id
        signal = AuditSignal(
            "request_failure",
            outcome,
            category,
            evidence={"exception_type": exception_type},
        )
        self.last_audit = self.auditor.generate_session_report(session_id, [signal], 1)
        self.telemetry.record(
            RequestTelemetry(
                request_id,
                session_id,
                [],
                [],
                execution_status,
                None,
                total_latency_ms=duration,
                contract_status=execution_status,
                error_category=category.value,
            )
        )

    def _execute(self, user_id, session_id, query, env, external_records=()):
        start = time.perf_counter()
        # TTL is rechecked before CNE cache lookup on every request.
        for record in external_records:
            if not record.is_fresh():
                raise FreshnessError("STALE")
        context = {"user_id": user_id, "defer_session": True}
        from cne.platform.correction_review import CorrectionConstraintApplier

        context["constraint_applier"] = CorrectionConstraintApplier()
        resolution = self.bridge.controller.resolver.resolve(query, user_id)
        context["corrections"] = [
            m
            for pack in resolution.selected_capabilities
            for m in self.corrections.retrieve(
                query,
                pack.id,
                user_id,
                controller_version=self.bridge.controller.controller_version,
                capability_version=pack.version,
                stage="pre",
            )
        ]
        compiled = self.bridge.compile(query, session_id, context)
        if compiled.outcome == ClassificationOutcome.COMPILED:
            decision = self.bridge.last_decision
            vector = compiled.graph.metadata["execution_vector"]
            from cne.signature.shape_key import SemanticShapeKey

            post = []
            for cid in decision.selected_capability_ids:
                post.extend(
                    self.corrections.retrieve(
                        query,
                        cid,
                        user_id,
                        stage="post",
                        capability_version=self.bridge.registry.get_pack(cid).version,
                        controller_version=decision.controller_version,
                        model_version=json.dumps(dict(vector.models), sort_keys=True),
                        intent=decision.intent,
                        semantic_shape=SemanticShapeKey.from_graph(
                            compiled.graph
                        ).key_hash,
                        tool_versions=dict(vector.tools),
                    )
                )
            initial_ids = {m.correction.record_id for m in context["corrections"]}
            new = [m for m in post if m.correction.record_id not in initial_ids]
            if new:
                context["corrections"] += new
                compiled = self.bridge.compile(query, session_id, context)
                self.bridge.last_decision.evidence["replan_count"] = 1
            self.bridge.last_decision.evidence.setdefault("applied_correction_ids", [])
            self.bridge.last_decision.evidence["retrieved_correction_ids"] = [
                m.correction.record_id for m in context["corrections"]
            ]
        timings = self.bridge.last_decision.evidence.get("timings", {})
        runtime_metrics = self.bridge.last_decision.evidence.get("runtime", {})
        if compiled.outcome != ClassificationOutcome.COMPILED:
            self._record_decline(user_id, session_id, query, start, compiled.outcome)
            return compiled
        decision = self.bridge.last_decision
        for cid in decision.selected_capability_ids:
            self.bridge.session_store.record_turn(
                session_id,
                query,
                cid,
                decision.intent,
                decision.extracted_slots,
                user_id=user_id,
            )
        graph = compiled.graph
        vector = graph.metadata["execution_vector"]
        engine = self.engine_for(user_id)
        env = dict(env)
        records_by_source = {}
        for record in external_records:
            if record.source in records_by_source:
                raise ValueError("Ambiguous external source records")
            records_by_source[record.source] = record
        for cid in graph.metadata["selected_capabilities"]:
            pack = self.bridge.registry.get_pack(cid)
            for source in pack.manifest.schemas.get("external_sources", []):
                if source not in graph.get_observed_sources():
                    continue
                if source not in records_by_source:
                    raise ValueError("NO_DATA: external source record required")
                record = records_by_source[source]
                fingerprint = hashlib.sha256(
                    json.dumps(
                        [record.version, record.value], sort_keys=True, allow_nan=False
                    ).encode()
                ).hexdigest()
                key = (user_id, source)
                if self._external_versions.get(key) != fingerprint:
                    from cne.optimizer.runtime.dependencies import ChangeType

                    engine.fabric.notify_data_mutation(ChangeType.UPDATE, source)
                    self._external_versions[key] = fingerprint
                env[source] = record.value
            for source, entrypoint in pack.manifest.schemas.get(
                "source_validators", {}
            ).items():
                if source in graph.get_observed_sources():
                    module, name = entrypoint.split(":")
                    if cid not in self.bridge.registry.trusted_in_process_ids:
                        if not pack.install_path:
                            raise PermissionError(
                                "ACCESS_DENIED: missing installed validator"
                            )
                        from cne.platform.sandbox import (
                            BubblewrapWorker,
                            WSLBubblewrapWorker,
                        )
                        import sys

                        worker = (
                            WSLBubblewrapWorker()
                            if sys.platform == "win32"
                            else BubblewrapWorker()
                        )
                        worker.run(pack.install_path, entrypoint, [env.get(source)])
                    else:
                        getattr(importlib.import_module(module), name)(env.get(source))
        # All callable nodes must resolve to declared tools. No silent missing Call.
        tool_defs = {
            t.tool_id: (pack, t)
            for cid in graph.metadata["selected_capabilities"]
            for pack in [self.bridge.registry.get_pack(cid)]
            for t in pack.manifest.deterministic_tools
        }
        for node in graph.get_all_nodes().values():
            if node.op != OpKind.CALL:
                continue
            target = node.attributes["target"]
            if target not in tool_defs:
                raise PermissionError("NOT_DECLARED: tool")
            pack, definition = tool_defs[target]
            if pack.id in self.bridge.registry.trusted_in_process_ids:
                module, name = definition.entrypoint.split(":")
                function = getattr(importlib.import_module(module), name)
            else:
                if not pack.install_path:
                    raise PermissionError(
                        "ACCESS_DENIED: untrusted tool has no installed package"
                    )
                from cne.platform.sandbox import BubblewrapWorker, WSLBubblewrapWorker
                import sys

                worker = (
                    WSLBubblewrapWorker()
                    if sys.platform == "win32"
                    else BubblewrapWorker()
                )

                def function(*args, _pack=pack, _definition=definition):
                    return worker.run(
                        _pack.install_path, _definition.entrypoint, list(args)
                    )

            def guarded(*args, _pack=pack, _fn=function, _definition=definition):
                authorize_operation(
                    self.bridge.registry,
                    _pack,
                    user_id,
                    decision.intent,
                    [_definition.tool_id],
                )
                try:
                    return _fn(*args)
                finally:
                    from cne.optimizer.runtime.dependencies import ChangeType

                    for source in _definition.mutation_sources:
                        engine.fabric.notify_data_mutation(ChangeType.UPDATE, source)

            engine.evaluator.tools[target] = guarded
        # Private state never shares an engine; scope also participates in the version identity.
        versions = replace(
            vector.system_versions(),
            policy_version=vector.policy_version
            + ":"
            + hashlib.sha256(user_id.encode()).hexdigest(),
        )
        if self.state_repository:
            engine.fabric.prepare(graph, env)
        result = engine.execute_query(
            graph, compiled.contract, env, versions=versions, query_id=uuid.uuid4().hex
        )
        request_id = uuid.uuid4().hex
        evidence = {
            "satisfied": result.contract_satisfied,
            "tier": result.evidence_tier,
        }
        record = ExperienceRecord(
            request_id,
            session_id,
            "",
            graph.metadata["selected_capabilities"],
            ",".join(model_id for model_id, _ in vector.models),
            self.bridge.last_decision.evidence.get("parameterized_dsl", "")
            if self.bridge.last_decision.evidence.get("privacy_reviewed_template")
            else "",
            compiled.outcome.value,
            result.contract_satisfied,
            (time.perf_counter() - start) * 1000,
            user_id=user_id,
            intent=decision.intent or "",
            controller_version=self.bridge.last_decision.controller_version,
            capability_versions={
                cid: self.bridge.registry.get_pack(cid).version
                for cid in graph.metadata["selected_capabilities"]
            },
            model_versions=dict(vector.models),
            tool_versions=dict(vector.tools),
            resource_metrics=runtime_metrics,
            input_fingerprint=request_fingerprint(
                query, graph.metadata["selected_capabilities"]
            ),
            semantic_shape=SemanticShapeKey.from_graph(graph).key_hash
            if hasattr(SemanticShapeKey, "from_graph")
            else "",
            contract={"type": compiled.contract.contract_type.value},
            verification_result=evidence,
            backend="CNE deterministic CPU",
        )
        persist_start = time.perf_counter()
        self.experiences.save(record)
        self.last_experience_id = record.experience_id
        persistence_ms = (time.perf_counter() - persist_start) * 1000
        signal = self.auditor.audit_turn(
            session_id,
            query,
            graph.metadata["selected_capabilities"][0],
            result.contract_satisfied,
            user_id=user_id,
            controller_version=record.controller_version,
            capability_version=record.capability_versions[
                graph.metadata["selected_capabilities"][0]
            ],
            model_version=json.dumps(record.model_versions, sort_keys=True),
            semantic_shape=record.semantic_shape,
            intent=record.intent,
            tool_versions=record.tool_versions,
            fingerprint=record.input_fingerprint,
        )
        self.last_audit = self.auditor.generate_session_report(
            session_id, [signal] if signal else [], 1
        )
        self.telemetry.record(
            RequestTelemetry(
                request_id,
                session_id,
                graph.metadata["selected_capabilities"],
                [model_id for model_id, _ in vector.models],
                "CNE deterministic CPU",
                record.semantic_shape,
                cache_hits_by_layer={
                    f"L{i}": int(
                        (i == 3 and result.reused_state)
                        or (
                            i == 2
                            and self.bridge.last_decision.evidence.get(
                                "plan_cache_hit", False
                            )
                        )
                    )
                    for i in range(6)
                },
                controller_latency_ms=timings.get("controller_ms"),
                inference_latency_ms=runtime_metrics.get("latency_ms"),
                model_load_latency_ms=runtime_metrics.get("load_latency_ms"),
                inference_ttft_ms=runtime_metrics.get("ttft_ms"),
                tokens_generated=runtime_metrics.get("tokens_generated"),
                tokens_per_second=runtime_metrics.get("tokens_per_second"),
                model_versions=dict(vector.models),
                routing_latency_ms=timings.get("routing_ms"),
                slot_binding_latency_ms=timings.get("slot_binding_ms"),
                dsl_compile_latency_ms=timings.get("dsl_compile_ms"),
                control_latency_ms=result.costs.control_ns / 1e6,
                execution_latency_ms=result.costs.execution_ns / 1e6,
                verification_latency_ms=result.costs.verification_ns / 1e6,
                persistence_latency_ms=persistence_ms,
                total_latency_ms=(time.perf_counter() - start) * 1000,
                capability_vector=vector.digest(),
                contract_status="SATISFIED" if result.contract_satisfied else "FAILED",
            )
        )
        return result
