# CNE Local-First AI Capability Platform — Master Specification

## Current implementation evidence (2026-10-06)

Status: PARTIAL platform hardening; this document's architecture is a target, not completion evidence.

IMPLEMENTED: registry-scoped declared-grammar controller, explicit DAG/region DSL, scoped SQLite sessions/corrections/experiences, deterministic finance and composed-source CNE execution. The controller has no calibrated confidence and does not claim general language coverage. Correction retrieval supplies context but the declared grammar does not learn from it.

IMPLEMENTED: durable package lifecycle and grants, Ed25519 signatures, verified archive staging, HTTP JSON connectors, restricted workers, supervised Llama-family LoRA export and live adapter activation/recovery. Resource accounting cannot guarantee process peak memory. Capability resolver optional scoring interface is IMPLEMENTED; no scoring model has been installed or evaluated.

STUB: agriculture CV (the explicitly allowed stub option). EXCLUDED: RL and Android deployment/performance claims. HARDWARE_NOT_MEASURED: Android latency, PSS, thermal behavior and battery. Real llama-cpp-python CPU GGUF inference is validated locally; broad controller quality and the multi-model tournament remain unevaluated. Runtime controller protocol tests use an isolated test boundary and establish no model quality. No controller replacement or tournament victory is claimed.

See [hardening audit](PLATFORM_HARDENING_AUDIT.md) and `cne/artifacts/platform_hardening_report.json` for measured evidence.

---

## 1. Architectural Mission & Scope

The CNE Platform evolves the Computation Necessity Engine into a **hardware-agnostic, accelerator-optional, local-first AI capability platform**. The platform coordinates heterogeneous AI models, deterministic tools, local data connectors, and formal execution plans on commodity edge devices.

### Primary Deployment Target
- **Device Class:** Android-class commodity devices.
- **Hardware Architecture:** ARM CPU (mandatory baseline), 6 GB RAM reference envelope.
- **Accelerator Policy:** Accelerators (GPU, NPU, DSP, USB compute) are strictly optional enhancements. The absence of an accelerator must never invalidate the baseline platform claim.
- **Network Mode:** 100% offline-capable for local data tasks. No paid or external cloud API is required for baseline operation.
- **Process Memory Targets:**
  - Peak process PSS: $\le 1.5$ GB.
  - Steady active runtime memory: $\le 1.0$ GB.
  - Base model storage target: $\le 500$ MB.
  - Core framework footprint: $\le 150$ MB (excluding models).

---

## 2. Non-Negotiable Platform Invariants

1. **CNE Core Invariant:** CNE remains the computation-necessity core. High-level planning lowers into CNE's 11 frozen primitives (`Observe, Filter, Map, Reduce, Join, Branch, Iterate, Choose, Update, Call, Emit` + `Literal`).
2. **Model Family Neutrality:** The platform supports small language models (SLMs), computer-vision models, speech models, embedding models, time-series predictors, and deterministic tools. It is NOT an LLM wrapper.
3. **Deterministic Computation Primacy:** Arithmetic, aggregation, date math, unit conversions, and known rule checks are executed by deterministic code, never delegated to a language model.
4. **Deterministic Permissions:** Models and controllers are physically prohibited from granting permissions. Permissions are enforced by deterministic platform guards with deny-by-default semantics.
5. **Memory Separation:**
   - KV/prefix cache $\ne$ semantic memory.
   - Session transcript $\ne$ long-term memory.
   - Computational state (`LocalStateFabric`) $\ne$ learning experiences.
6. **Two-Speed Learning:** Fast learning operates purely in memory (constraints, counterexamples). Slow learning (weight/adapter adaptation) is gated, offline, and atomically reversible.
7. **Version Invalidation:** Every reusable state item is scoped by a version vector. Model, runtime, or capability updates must cleanly invalidate dependent cached state.
8. **Benchmark Sanctity:** The 600-query blind evaluation corpus (`test_heldout_blind.jsonl`) remains strictly quarantined. No training or tuning may touch it.

---

## 3. System Architecture & Subsystems

```text
+-------------------------------------------------------------------------+
|                              USER SESSION                               |
|                  Session Store (L1) & History Window                    |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                       PLATFORM CONTROLLER LAYER                         |
|  Device Abstraction (L1) | Resource Manager | Security Guard            |
|  Capability Registry & Manifest Resolver                                |
|  Correction / Experience Store (L4) -> Semantic Controller              |
|  Semantic Controller -> Compact CNE DSL -> Deterministic DSL Compiler   |
+------------------------------------+------------------------------------+
                                     |
                         SemanticIRGraph + Contract
                                     |
                                     v
+-------------------------------------------------------------------------+
|                  CNE COMPUTATION NECESSITY CORE                         |
|  Extended SystemVersions & MemoKey -> Local State Fabric (L3)           |
|  Cost Gate -> Static Optimizer -> Physical Planner                      |
|  Execution Engine -> Contract Verifier & Evidence Auditor               |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                     HETEROGENEOUS MODEL RUNTIMES                        |
|  ModelRuntimeAdapter: CPU (llama.cpp/GGUF, ONNX, LiteRT, Vision)        |
+-------------------------------------------------------------------------+
```

---

## 4. Subsystem Specifications

### 4.1 Device Abstraction & Resource Manager
- `DeviceProfile`: Captures CPU core count, available RAM, thermal state (nominal/throttling), battery status, and active backends.
- `ModelResidencyManager`: Dynamically manages active model weights. Enforces the 1.5 GB peak PSS and 1.0 GB steady runtime limits via cost-aware LRU eviction, tracking load latency, reload penalties, and capability requirements.

### 4.2 Capability Pack Subsystem
- Modularity: Supports hundreds of installable capability packs (`.cap` packages).
- Manifest: Hash-verified, signed `CapabilityManifest` specifying ID, semantic version, modalities, declared permissions, network mode, and dependencies.
- Lifecycle: Safe atomic operations: install, verify, enable, disable, update, rollback, uninstall.

### 4.3 Compact Semantic DSL & Compiler
- Replaces unconstrained, high-token JSON generation with a terse, grammar-constrained domain-specific language.
- Format:
  ```text
  tx = OBS source=transactions
  food = FIL in=tx field=category op=eq val=food
  amounts = MAP in=food field=amount
  total = RED in=amounts reducer=sum
  result = EMI in=total
  ```
- Deterministic compiler verifies graph acyclicity, enforces single `Emit` sink, binds typed slots from capability schemas, and normalizes numbers/dates/units deterministically.

### 4.4 Multi-Layer Memory Architecture
- **L0 (Model Execution Cache):** Ephemeral KV/prefix cache keyed by `(model_hash, tokenizer_hash, prefix_hash)`.
- **L1 (Session Store):** Structured session state, active entities, goals, compact summary.
- **L2 (Semantic Plan Cache):** Reusable DAG topologies with dynamic slot rebinding.
- **L3 (Computational State):** Existing `LocalStateFabric` with `MemoKey` and dependency invalidation.
- **L4 (Correction Store):** Verified failure and correction records used as planning constraints.
- **L5 (Learning Replay Store):** Curated, deduplicated examples for gated offline adaptation.

### 4.5 Error Auditor & Learning Gates
- 19 typed error classifications.
- Fast adaptation: injects verified corrections into planner context to immediately halt recurring mistakes.
- Slow adaptation: gated adapter rollout requiring $\ge 80\%$ recovery on historical error set, $<10\%$ error recurrence, $<2\%$ unrelated regression, zero new permission violations, and zero stale state reuse.
