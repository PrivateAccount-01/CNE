"""Registry-driven controller protocol and adapter to the authoritative CNE core.

The built-in controller accepts only full declared grammar matches. General natural
language requires an injected real controller; unmatched mappings never fabricate DSL.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import re
import shlex
import time
from cne.compiler.nl_compiler import ClassificationOutcome, CompilationResult
from cne.contracts.outcome_contract import ContractType
from cne.platform.dsl import SemanticDSLParser
from cne.platform.memory import SessionStore, SemanticPlanCache, SemanticPlanTemplate
import hashlib
from cne.platform.registry import CapabilityRegistry, CapabilityResolver
from cne.platform.slots import TypedSlotBinder, SlotBindingError
from cne.platform.versions import ExecutionSemanticVersionVector
from cne.semantic_ir.nodes import OpKind
from cne.platform.operations import authorize_operation
from cne.platform.errors import SemanticPlanError


@dataclass
class ControllerDecision:
    outcome: ClassificationOutcome
    selected_capability_ids: list = field(default_factory=list)
    semantic_dsl: str | None = None
    extracted_slots: dict = field(default_factory=dict)
    confidence: float | None = None
    decline_reason: str | None = None
    controller_version: str = "declared-grammar-2"
    evidence: dict = field(default_factory=dict)
    routing_confidence: float | None = None
    semantic_confidence: float | None = None
    slot_confidence: float | None = None
    validation_result: str = "NOT_VALIDATED"
    intent: str | None = None


class PlatformSemanticController:
    controller_version = "declared-grammar-2"

    def __init__(self, registry, plan_cache=None):
        self.registry = registry
        self.resolver = CapabilityResolver(registry)
        self.binder = TypedSlotBinder()
        self.plan_cache = plan_cache or SemanticPlanCache()

    def decide(self, query_text, scope="local_device", context=None):
        controller_start = time.perf_counter()
        routing_start = time.perf_counter()
        resolution = self.resolver.resolve(query_text, scope)
        routing_ms = (time.perf_counter() - routing_start) * 1000
        selected = [p.id for p in resolution.selected_capabilities]
        evidence = {
            "routing": resolution.scores,
            "rejections": resolution.rejection_reasons,
            "confidence_status": "NOT_MEASURED",
        }
        if not selected:
            return ControllerDecision(
                ClassificationOutcome.UNSUPPORTED_INTENT,
                decline_reason="No installed permitted capability matches",
                evidence=evidence,
            )
        matches = []
        from cne.platform.utterances import match_mapping

        for pack in resolution.selected_capabilities:
            for mapping in pack.manifest.schemas.get("intents", []):
                match = match_mapping(mapping, query_text)
                if match:
                    matches.append((pack, mapping, match))
        context = context or {}
        constraint_applier = context.get("constraint_applier")
        if constraint_applier is not None and len(matches) > 1:
            matches = constraint_applier.select_mapping(
                matches, context.get("corrections", []), scope
            )
        if not matches:
            return ControllerDecision(
                ClassificationOutcome.LOW_CONFIDENCE_MAPPING,
                selected,
                decline_reason="NOT_IMPLEMENTED: no declared semantic mapping for request",
                evidence=evidence,
            )
        # A composition is declared by one schema and explicitly names every participant.
        if len(matches) != 1:
            return ControllerDecision(
                ClassificationOutcome.AMBIGUOUS_INTENT,
                selected,
                decline_reason="Multiple semantic mappings match",
                evidence=evidence,
            )
        pack, mapping, match = matches[0]
        participants = sorted(set([pack.id] + mapping.get("capabilities", [])))
        for cid in participants:
            dependency = self.registry.get_pack(cid)
            if dependency is None or not dependency.is_enabled():
                return ControllerDecision(
                    ClassificationOutcome.UNSUPPORTED_INTENT,
                    decline_reason=f"Missing participant {cid}",
                    evidence=evidence,
                )
            if cid == pack.id:
                authorize_operation(self.registry, dependency, scope, mapping["intent"])
        try:
            slot_start = time.perf_counter()
            bound = self.binder.bind(
                mapping.get("slots", {}),
                match.groupdict(),
                {k: match.span(k) for k in match.groupdict()},
            )
            if constraint_applier is not None:
                values, applied = constraint_applier.apply_slots(
                    {k: v.value for k, v in bound.items()},
                    context.get("corrections", []),
                    scope,
                    pack.id,
                    mapping["intent"],
                )
                if applied:
                    bound = self.binder.bind(mapping.get("slots", {}), values)
                    evidence["applied_correction_ids"] = applied
            slot_ms = (time.perf_counter() - slot_start) * 1000
            template_key = hashlib.sha256(
                json.dumps(mapping, sort_keys=True).encode()
            ).hexdigest()
            capability_vector = hashlib.sha256(
                json.dumps(
                    [
                        (
                            cid,
                            self.registry.get_pack(
                                cid
                            ).manifest.compute_manifest_hash(),
                        )
                        for cid in participants
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            values = {name: slot.value for name, slot in bound.items()}
            dsl = self.plan_cache.bind(
                scope,
                template_key,
                values,
                capability_vector,
                self.controller_version,
                "dsl-2",
            )
            evidence["plan_cache_hit"] = dsl is not None
            if dsl is None:
                self.plan_cache.put_template(
                    scope,
                    SemanticPlanTemplate(
                        template_key,
                        mapping["dsl"],
                        capability_vector,
                        self.controller_version,
                        "dsl-2",
                        tuple(sorted(values)),
                        tuple(mapping.get("tool_ids", ())),
                    ),
                )
                dsl = self.plan_cache.bind(
                    scope,
                    template_key,
                    values,
                    capability_vector,
                    self.controller_version,
                    "dsl-2",
                )
            if "${" in dsl:
                raise SlotBindingError("Unbound DSL slot")
            compile_start = time.perf_counter()
            if constraint_applier is not None:
                constraint_applier.validate_plan(
                    dsl, context.get("corrections", []), scope, participants
                )
            compiled = SemanticDSLParser.compile_dsl(dsl, intent=mapping["intent"])
            compile_ms = (time.perf_counter() - compile_start) * 1000
            if not compiled.is_valid:
                raise SlotBindingError(compiled.error_message)
        except (SlotBindingError, SemanticPlanError) as exc:
            return ControllerDecision(
                ClassificationOutcome.LOW_CONFIDENCE_MAPPING,
                participants,
                decline_reason=str(exc),
                evidence=evidence,
            )
        evidence["slot_provenance"] = {k: vars(v) for k, v in bound.items()}
        evidence["tool_ids"] = sorted(
            {
                n.attributes["target"]
                for n in compiled.graph.get_all_nodes().values()
                if n.op == OpKind.CALL
            }
        )
        evidence["mapping"] = mapping["intent"]
        evidence["parameterized_dsl"] = mapping["dsl"]
        evidence["privacy_reviewed_template"] = True
        evidence["timings"] = {
            "routing_ms": routing_ms,
            "slot_binding_ms": slot_ms,
            "dsl_compile_ms": compile_ms,
            "controller_ms": (time.perf_counter() - controller_start) * 1000,
        }
        return ControllerDecision(
            ClassificationOutcome.COMPILED,
            participants,
            dsl,
            {k: v.value for k, v in bound.items()},
            evidence=evidence,
            validation_result="VALID",
            intent=mapping["intent"],
        )


class RuntimeSemanticController(PlatformSemanticController):
    """Optional real-runtime controller. Quality remains unverified until benchmarked.

    Installed schemas constrain model choices. Model confidence never authorizes
    permissions or substitutes for compiler validation.
    """

    controller_version = "runtime-controller-2"

    def __init__(
        self,
        registry,
        runtime,
        descriptor,
        residency_manager=None,
        candidate_limit=5,
        index=None,
        prompt_builder=None,
    ):
        super().__init__(registry)
        from cne.platform.capability_index import CapabilityCandidateRetriever
        from cne.platform.prompting import ControllerPromptBuilder

        self.runtime = runtime
        self.descriptor = descriptor
        if not 1 <= candidate_limit <= 8:
            raise ValueError("Candidate K must be 1..8")
        self.retriever = index or CapabilityCandidateRetriever(
            registry, candidate_limit
        )
        self.prompt_builder = prompt_builder or ControllerPromptBuilder()
        if residency_manager is not None and residency_manager.runtime is not runtime:
            raise ValueError("Residency manager must own the controller runtime")
        self.residency_manager = residency_manager

    def _authorize(self, pack, scope, intent, tools, sources):
        from cne.platform.operations import authorize_operation

        return authorize_operation(self.registry, pack, scope, intent, tools, sources)

    def decide(self, query_text, scope="local_device", context=None):
        from cne.platform.models import ModelRequest

        candidates = self.retriever.retrieve(query_text, user_id=scope)
        permitted = []
        for pack in candidates:
            try:
                self.registry._validate_dependencies(pack.manifest)
                self.registry.package_verifier.verify(pack.manifest, pack.install_path)
            except Exception:
                continue
            permitted.append(pack)
        if not permitted:
            return ControllerDecision(
                ClassificationOutcome.UNSUPPORTED_INTENT,
                decline_reason="No relevant active capabilities",
                evidence={"candidate_k": self.retriever.k, "shortlisted_ids": []},
            )
        load_latency = None
        result = None
        owner = "controller:" + scope
        if self.residency_manager is not None:
            load_start = time.perf_counter()
            self.residency_manager.ensure_resident(self.descriptor, owner=owner)
            load_latency = (time.perf_counter() - load_start) * 1000
        elif not self.runtime.is_loaded(self.descriptor.model_id):
            load_start = time.perf_counter()
            self.runtime.load_model(self.descriptor, self.descriptor.preferred_backend)
            load_latency = (time.perf_counter() - load_start) * 1000
        views = [self.prompt_builder.views.build(p.manifest) for p in permitted]
        corrections = [
            m.correction.constraint
            for m in (context or {}).get("corrections", [])
            if m.correction.audit_status.value in ("VERIFIED", "USER_SCOPED")
        ]
        prompt, schema, prompt_identity = self.prompt_builder.build(
            query_text, views, corrections
        )
        evidence_prompt = prompt
        model_identity = {
            "model_id": self.descriptor.model_id,
            "version": self.descriptor.version,
            "asset_sha256": self.descriptor.asset_sha256,
            "source_repository": self.descriptor.source_repository,
            "source_revision": self.descriptor.source_revision,
            "license": self.descriptor.license,
            "quantization": self.descriptor.quantization,
            "prompt_format": self.descriptor.prompt_format,
            "chat_template_mode": self.descriptor.chat_template_mode,
            "bos_policy": self.descriptor.bos_policy,
            "eos_policy": self.descriptor.eos_policy,
            "n_threads": self.descriptor.n_threads,
            "context_window": self.descriptor.context_window,
        }
        prompt_identity = hashlib.sha256(
            json.dumps([prompt_identity, model_identity], sort_keys=True).encode()
        ).hexdigest()
        try:
            try:
                result = self.runtime.infer(
                    ModelRequest(
                        "controller",
                        self.descriptor.model_id,
                        prompt,
                        {"max_tokens": 512, "temp": 0.0},
                        user_scope=scope,
                        response_schema=schema,
                    )
                )
            except (TimeoutError, MemoryError, PermissionError):
                raise
            except Exception as exc:
                from cne.platform.errors import ModelOutputError

                raise ModelOutputError("Local model inference failed") from exc
        finally:
            if self.residency_manager is not None:
                self.residency_manager.release(self.descriptor.model_id, owner=owner)
        if result is None:
            raise RuntimeError("Model inference returned no result")
        evidence = {
            "model_dependencies": [
                (
                    self.descriptor.model_id,
                    self.descriptor.version,
                    self.descriptor.asset_sha256,
                )
            ],
            "model_identity": model_identity,
            "prompt_format_identity": prompt_identity,
            "candidate_k": self.retriever.k,
            "shortlisted_ids": [p.id for p in permitted],
            "prompt_sha256": hashlib.sha256(evidence_prompt.encode()).hexdigest(),
            "adapter_dependencies": result.metadata.get("adapter_dependencies", []),
            "runtime": {
                "latency_ms": result.latency_ms,
                "load_latency_ms": load_latency,
                "tokens_generated": result.tokens_generated,
                **result.metadata,
            },
            "confidence_status": "NOT_MEASURED",
        }
        try:
            raw = json.loads(result.outputs)
            outcome = ClassificationOutcome(raw["outcome"])
            if outcome != ClassificationOutcome.COMPILED:
                return ControllerDecision(
                    outcome,
                    decline_reason=raw.get("decline_reason"),
                    controller_version="runtime-controller-2",
                    evidence=evidence,
                )
            selected = raw["selected_capability_ids"]
            allowed = {p.id: p for p in permitted}
            if (
                not selected
                or not isinstance(selected, list)
                or set(selected) - allowed.keys()
            ):
                raise ValueError("Undeclared capability selection")
            schemas = {}
            declared_sources = set()
            intent = raw.get("intent")
            for cid in selected:
                pack = allowed[cid]
                intent_specs = [
                    m.get("slots", {})
                    for m in pack.manifest.schemas.get("intents", [])
                    if m["intent"] == intent
                ]
                package_slots = pack.manifest.schemas.get("slots", {})
                for key, spec in package_slots.items():
                    if key in schemas and schemas[key] != spec:
                        raise ValueError("Ambiguous composed slot schema")
                    schemas[key] = spec
                for intent_schema in intent_specs:
                    for key, spec in intent_schema.items():
                        if key in schemas and schemas[key] != spec:
                            raise ValueError("Ambiguous composed slot schema")
                        schemas[key] = spec
                declared_sources.update(
                    allowed[cid].manifest.schemas.get("sources", [])
                )
            bound = self.binder.bind(schemas, raw.get("extracted_slots", {}))
            declared_intents = {
                mapping["intent"]
                for cid in selected
                for mapping in allowed[cid].manifest.schemas.get("intents", [])
            }
            legacy_boundary = not declared_intents and len(allowed) == 1
            if intent not in declared_intents and not legacy_boundary:
                raise ValueError("Undeclared intent")
            dsl = raw["semantic_dsl"]
            evidence["parameterized_dsl"] = dsl
            for name, slot in bound.items():
                dsl = dsl.replace(
                    "${" + name + "}", shlex.quote(json.dumps(slot.value))
                )
            if "${" in dsl:
                raise ValueError("Unbound slot")
            compiled = SemanticDSLParser.compile_dsl(dsl, intent=intent)
            if not compiled.is_valid:
                raise ValueError(compiled.error_message)
            observed_sources = set(compiled.graph.get_observed_sources())
            if observed_sources - declared_sources:
                raise ValueError("Undeclared data source")
            tools = [
                n.attributes["target"]
                for n in compiled.graph.get_all_nodes().values()
                if n.op == OpKind.CALL
            ]
            for cid in selected:
                pack = allowed[cid]
                pack_tools = {t.tool_id for t in pack.manifest.deterministic_tools}
                declared_pack_sources = set(pack.manifest.schemas.get("sources", []))
                self._authorize(
                    pack,
                    scope,
                    intent,
                    set(tools) & pack_tools,
                    observed_sources & declared_pack_sources,
                )
            ExecutionSemanticVersionVector.for_execution(self.registry, selected, tools)
            evidence["tool_ids"] = sorted(set(tools))
            evidence["source_ids"] = sorted(observed_sources)
            return ControllerDecision(
                outcome,
                sorted(set(selected)),
                dsl,
                {k: v.value for k, v in bound.items()},
                controller_version="runtime-controller-2",
                evidence=evidence,
                validation_result="VALID",
                intent=intent,
            )
        except PermissionError:
            return ControllerDecision(
                ClassificationOutcome.LOW_CONFIDENCE_MAPPING,
                decline_reason="Required operation permission is not granted",
                controller_version="runtime-controller-2",
                evidence=evidence,
            )
        except (ValueError, TypeError, KeyError) as exc:
            return ControllerDecision(
                ClassificationOutcome.LOW_CONFIDENCE_MAPPING,
                decline_reason=str(exc),
                controller_version="runtime-controller-2",
                evidence=evidence,
            )


class PlatformControllerBridge:
    def __init__(
        self, registry=None, session_store=None, device_profile=None, controller=None
    ):
        self.registry = registry or CapabilityRegistry()
        self.session_store = session_store or SessionStore()
        self.device_profile = device_profile
        self.controller = controller or PlatformSemanticController(self.registry)
        self.last_decision = None

    def compile(self, query_text, session_id="default_session", context=None):
        context = context or {}
        user_id = context.get("user_id")
        if not user_id:
            raise PermissionError("ACCESS_DENIED: user_id required")
        self.session_store.get_session(user_id, session_id)
        decision = self.controller.decide(query_text, scope=user_id, context=context)
        self.last_decision = decision
        if decision.outcome != ClassificationOutcome.COMPILED:
            return CompilationResult(
                query_text=query_text,
                outcome=decision.outcome,
                confidence=None,
                reason=decision.decline_reason,
            )
        # Recheck after inference: grants may have expired or been revoked.
        for cid in decision.selected_capability_ids:
            pack = self.registry.get_pack(cid)
            if pack is None or not pack.is_enabled():
                raise PermissionError("ACCESS_DENIED: inactive capability")
            self.registry.package_verifier.verify(pack.manifest, pack.install_path)
            self.registry._validate_dependencies(pack.manifest)
            used_tools = (
                {
                    n.attributes["target"]
                    for n in SemanticDSLParser.compile_dsl(
                        decision.semantic_dsl, intent=decision.intent
                    )
                    .graph.get_all_nodes()
                    .values()
                    if n.op == OpKind.CALL
                }
                if decision.semantic_dsl
                else set()
            )
            used_sources = (
                set(
                    SemanticDSLParser.compile_dsl(
                        decision.semantic_dsl, intent=decision.intent
                    ).graph.get_observed_sources()
                )
                if decision.semantic_dsl
                else set()
            )
            if isinstance(self.controller, RuntimeSemanticController):
                self.controller._authorize(
                    pack, user_id, decision.intent, used_tools, used_sources
                )
            else:
                authorize_operation(
                    self.registry,
                    pack,
                    user_id,
                    decision.intent,
                    used_tools,
                    used_sources,
                )
        compile_start = time.perf_counter()
        result = self.compile_to_cne(decision.semantic_dsl, intent=decision.intent)
        if "timings" in decision.evidence:
            decision.evidence["timings"]["dsl_compile_ms"] += (
                time.perf_counter() - compile_start
            ) * 1000
        if result.outcome != ClassificationOutcome.COMPILED:
            return result
        result.query_text = query_text
        result.extracted_slots = decision.extracted_slots
        result.confidence = decision.confidence  # No calibration evidence exists.
        used_tools = sorted(
            {
                n.attributes["target"]
                for n in result.graph.get_all_nodes().values()
                if n.op == OpKind.CALL
            }
        )
        vector = ExecutionSemanticVersionVector.for_execution(
            self.registry,
            decision.selected_capability_ids,
            tool_ids=used_tools,
            models=decision.evidence.get("model_dependencies", ()),
            adapters=decision.evidence.get("adapter_dependencies", ()),
            knowledge=decision.evidence.get("knowledge_dependencies", ()),
        )
        result.graph.metadata.update(
            {
                "execution_vector": vector,
                "user_id": user_id,
                "selected_capabilities": decision.selected_capability_ids,
            }
        )
        if not context.get("defer_session", False):
            for cid in decision.selected_capability_ids:
                self.session_store.record_turn(
                    session_id,
                    query_text,
                    cid,
                    decision.intent,
                    decision.extracted_slots,
                    user_id=user_id,
                )
        return result

    def compile_to_cne(
        self, dsl_text, contract_type=ContractType.EXACT, intent="custom_pipeline"
    ):
        result = SemanticDSLParser.compile_dsl(dsl_text, contract_type, intent)
        return CompilationResult(
            query_text=dsl_text,
            outcome=ClassificationOutcome.COMPILED
            if result.is_valid
            else ClassificationOutcome.LOW_CONFIDENCE_MAPPING,
            confidence=None,
            intent=intent,
            graph=result.graph,
            contract=result.contract,
            extracted_slots=result.extracted_slots,
            reason=result.error_message,
        )
