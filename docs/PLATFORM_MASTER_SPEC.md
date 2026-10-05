# CNE Local-First AI Capability Platform — Master Specification

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
  OBS source=transactions category=food
  FIL threshold=100.0 op=gt
  MAP field=amount
  RED op=sum
  EMIT label=total_food_spending
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
