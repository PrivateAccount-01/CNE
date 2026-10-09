# CNE Evaluation Gates & Acceptance Criteria

## Current implementation evidence (2026-10-06)

Implementation status: benchmark accounting IMPLEMENTED; real controller/model tournament NOT_TESTED.

Every quality metric contains numerator, denominator, status and value. Zero samples are NOT_APPLICABLE. Missing semantic/task oracles are NOT_MEASURED, never inferred from parse success. Routing, intent, OOS, ambiguity and whole-slot exact match compare separate gold labels. Contract and post-execution correctness require independent executable oracles.

Callback latency is measured with perf_counter and includes sampling overhead. RSS/PSS are explicitly sampled process peaks at 5 ms, not model allocation or guaranteed instantaneous peaks. PSS is NOT_MEASURED where unavailable. TTFT and token counts come only from actual ModelResult runtime observations; model file size comes from filesystem stat. Passing quality without required runtime evidence cannot win model selection.

Current controller targets: schema >=99%, semantic >=95%, slots >=90%, OOS >=95%, in-scope >=60%, primitive adherence 100%; routing, ambiguity, contract and task success are separately reported. No 100?150M / 250?350M / 500?700M model runs were performed without real assets. No final controller is selected. The untouched 600-query held-out corpus remains quarantined and no replacement success is claimed. Original baseline figures below are historical evidence, not results from this platform hardening.

---

## 1. Overview

This document defines the formal evaluation scorecards and acceptance gates governing new controllers, capability packs, caching layers, and continual learning adaptations.

---

## 2. Controller Acceptance Gate (Replacing P1 Baseline)

To replace the P1 `LearnedSemanticController`, the new platform controller must demonstrably meet all quality gates when evaluated against the untouched, quarantined 600-query blind corpus (`test_heldout_blind.jsonl`).

| Metric | P0.8 Baseline | P1 Result (Control) | Platform Gate Requirement | Status |
|:---|:---:|:---:|:---:|:---:|
| **Schema Validity** | N/A | 98.5% | $\ge 99.0\%$ | Mandatory |
| **Semantic Correctness** | 100.0% | 99.8% | $\ge 95.0\%$ | Mandatory |
| **Slot Exact-Match Accuracy** | 81.2% | 4.8% | $\ge 90.0\%$ | Mandatory |
| **Out-of-Scope (OOS) Rejection** | 100.0% | 77.0% | $\ge 95.0\%$ | Mandatory |
| **In-Scope Coverage** | 34.0% | 41.0% | $\ge 60.0\%$ | Mandatory |
| **Primitive Adherence** | 100.0% | 100.0% | $100.0\%$ (0 violations) | Mandatory |
| **Blind Coverage** | 14.2% | 37.5% | $\ge 35.0\%$ | Mandatory |

*Latency is measured and reported separately. Optimization of latency must not come at the expense of schema validity or safety.*

---

## 3. Cache & Computational State Gate

In adversarial testing:
- **Incorrect Exact Cache Reuse:** **0** (Zero tolerance).
- **Known Stale-State Acceptance:** **0** (Zero tolerance).
- **Missed Dependency Invalidation:** **0** in the certified test corpus.
- **Cross-Capability Leakage:** **0** (Capability A cannot read Capability B private memory without mutual declaration).
- **Cross-User Leakage:** **0** (User A cannot access User B state).

---

## 4. Continual Learning Regression Gate

Before any candidate adapter or updated policy can be rolled out:
- **Historical Error Recovery:** $\ge 80\%$ recovery on verified historical error set.
- **Repeated Error Recurrence:** $< 10\%$ recurrence of previously audited errors.
- **Unrelated Task Regression:** $< 2.0$ percentage points on standard benchmark splits.
- **New Permission Violations:** **0** (Zero tolerance).
- **New Unsafe State Reuse Violations:** **0** (Zero tolerance).

---

## 5. Resource & Mobile Deployment Envelope

On the reference ARM 6 GB Android class device:
- **Peak Process PSS:** $\le 1.5$ GB.
- **Steady Active Runtime Memory:** $\le 1.0$ GB.
- **Base Model Storage:** $\le 500$ MB.
- **Core Framework Storage:** $\le 150$ MB (excluding models).
- **CPU-Only Operational Guarantee:** 100% of baseline functionality operates on CPU alone.

## Running a real development tournament

The `ProductionControllerTournament` harness is currently a Python API, not a command-line tool. Call its `run(runtime_factory, descriptor, cases)` method with development-only labeled cases and locally provisioned licensed model assets. Missing backends/assets must be recorded as NOT_TESTED. Independent semantic/contract/task oracles remain necessary; the harness does not select a final controller. Keep the blind corpus out of development cases.
