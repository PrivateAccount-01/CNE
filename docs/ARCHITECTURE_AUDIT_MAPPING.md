# CNE Architecture Audit & Component Evolution Mapping

## 1. Overview

This document establishes the authoritative component audit and evolution mapping for transitioning `PrivateAccount-01/CNE` from a standalone Computation Necessity Engine into a hardware-agnostic, accelerator-optional, local-first AI capability platform.

---

## 2. Component Inventory & Status Mapping

| Existing Component | File Location | Status | New / Extended Responsibility | Architectural Rationale |
|:---|:---|:---:|:---|:---|
| **Semantic IR Primitives** | `cne/semantic_ir/nodes.py` | **KEEP** | Preserved immutably: exactly 11 OpKind primitives (`Observe, Filter, Map, Reduce, Join, Branch, Iterate, Choose, Update, Call, Emit` + `Literal`). | Core mathematical foundation of CNE. Proven 100% adherence and zero primitive hallucination across all empirical evaluations. |
| **Outcome Contracts** | `cne/contracts/outcome_contract.py` | **KEEP** | Preserved unchanged: defines acceptable results, admissibility, and decision boundaries (`EXACT, SET_VALUED, APPROXIMATE_NUMERIC, DECISION, STRUCTURED_EXPLANATION, NO_SOLUTION`). | Unifies verification criteria across all local platform capabilities and deterministic tools. |
| **Local State Fabric** | `cne/state/fabric.py` | **KEEP** | Retains L3 Computational State role: Working, Semantic, Computational, Archive storage classes. | High-performance state retention with fine-grained mutation tracking and amortized computation savings. Must NOT be polluted with learning experiences. |
| **SystemVersions & MemoKey** | `cne/signature/memo_key.py` | **EXTEND** | Extended backwards-compatibly to incorporate sorted capability-version vectors, active adapter versions, runtime versions, and tool schema hashes. | Guarantees that capability updates or model swaps cleanly invalidate affected cached state without cross-tenant/cross-version pollution. |
| **Dependency Invalidation** | `cne/optimizer/runtime/dependencies.py` | **KEEP** | Preserved unchanged: fine-grained predicate-aware source invalidation. | Guarantees exact cache invalidation upon local data mutations. |
| **Cost Gate & Static Optimizer** | `cne/optimizer/` | **KEEP** | Compile-time dead-code elimination, filter slicing, and cost admission. | Preserves contract-admissible pruning before physical resource allocation. |
| **Physical Planner** | `cne/planner/physical_planner.py` | **EXTEND** | Schedules physical execution across CPU (mandatory reference) and optional discovered accelerator backends (GPU/NPU/DSP). | Enables heterogeneous hardware routing without modifying semantic graph representations. |
| **Verifier & Auditor** | `cne/verify/verifier.py` | **KEEP** | Validates execution output against contract constraints and certifies evidence tiers. | Deterministic correctness guard for all CNE outputs. |
| **NLCompiler (Rule-Based)** | `cne/compiler/nl_compiler.py` | **KEEP** | Preserved intact as deterministic fallback and ground-truth validation reference across 10 topologies. | Guarantees zero regression on existing 253 unit/integration tests. |
| **LearnedSemanticController (P1)** | `cne/compiler/constrained_decoder.py` | **KEEP** | Preserved as baseline/control model (`legacy_controller`) for empirical benchmark comparison. | Official baseline (37.5% blind coverage, 98.5% schema validity) must remain directly runnable for delta evaluations. |
| **ControllerBridge** | `cne/compiler/controller_bridge.py` | **EXTEND** | Preserved; accompanied by new `PlatformControllerBridge`. | Ensures dual-stack execution switch between legacy and platform controllers. |
| **Evaluation Harness & Blind Corpus** | `cne/bench/`, `cne/artifacts/p1_dataset/test_heldout_blind.jsonl` | **KEEP & FREEZE** | 600-query blind corpus remains strictly isolated and untouched. | Benchmark sanctity; models never train, tune, or contaminate this corpus. |

---

## 3. New Platform Subsystems

| Subsystem | Directory | Responsibilities | Target Deployment Requirement |
|:---|:---|:---|:---|
| **L1 Device Abstraction** | `cne/platform/device.py` | CPU cores, RAM status, thermal state, battery status, runtime backend capabilities, storage quotas. | CPU is mandatory reference; accelerators optional. Process PSS $\le 1.5$ GB. |
| **Capability Pack System** | `cne/platform/manifest.py`, `cne/platform/registry.py` | Pack packaging, signed manifests, permission checks, isolated lifecycle management. | Support hundreds of packs; load only currently needed models/tools. |
| **Model Runtime Abstraction** | `cne/platform/models.py` | Model-family agnostic runtime interface supporting SLMs, CV, speech, embeddings, time-series. | Lightweight, Android-portable, CPU-capable C++ / GGUF engine. |
| **Multi-Layer Memory** | `cne/platform/memory.py` | 6 distinct layers: L0 (Execution), L1 (Session), L2 (Semantic Plan), L3 (CNE Fabric), L4 (Correction), L5 (Replay). | Session continuation without transcript replay bloat. |
| **Compact Semantic DSL** | `cne/platform/dsl.py` | Terse formal grammar for controller generation (`OBS/FIL/MAP/RED/EMIT`), deterministic parser and IR compiler. | Replaces verbose JSON; eliminates slot name hallucinations. |
| **Platform Controller Bridge** | `cne/platform/bridge.py` | Bridges platform routing and DSL compilation into CNE `CompilationResult`. | Runtime toggle between `legacy_controller` and `platform_controller`. |
| **Error Auditor & Continual Learning** | `cne/platform/auditor.py`, `cne/platform/learning.py` | 19 typed error classes, session audit reports, fast memory-based adaptation, gated slow adaptation. | Prevent repeated audited errors without uncontrolled weight mutation. |

---

## 4. Test Invariant & Baseline Protection

- Existing test suite (253 tests across `cne/tests/`) must maintain 100% pass rate at every phase.
- `cne/artifacts/p1_dataset/test_heldout_blind.jsonl` is strictly quarantined.
- P1 baseline metrics are permanently locked for automated A/B regression gates:
  - Blind coverage: 37.5%
  - In-scope coverage: 41.0%
  - OOS rejection: 77.0%
  - Schema validity: 98.5%
  - Semantic validity: 99.8%
  - Slot accuracy: 4.8%
  - Shape diversity: 0.7216
  - Primitive adherence: 100.0%
