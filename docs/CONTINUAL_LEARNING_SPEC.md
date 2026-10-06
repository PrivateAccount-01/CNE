# CNE Continual Learning Specification

## Current implementation evidence (2026-10-06)

Implementation status: replay/evaluation governance, supervised LoRA training and live GGUF adapter deployment IMPLEMENTED. RL is intentionally excluded.

User feedback creates UNVERIFIED candidates, never globally verified truth. The auditor is separate from the authoritative CNE verifier. Host-approved verification and privacy review are required before replay admission. Admission strips raw queries/private slots, deduplicates by owner/fingerprint/DSL/outcome, applies timestamp retention and capacity limits, and samples historical records across outcome buckets. The replay store itself is in-memory.

CandidateEvaluator executes candidate and baseline callables against five required, independently labeled datasets. It calculates counts, failure IDs, Wilson intervals, dataset hashes and gates; callers cannot supply metric values. Evaluation measures the supplied callable, not model quality unless that callable actually invokes the model. Recurrence is measured on a second execution of historical requests; repeated-session lifecycle evaluation is not implied.

GatedAdaptationPipeline(database_path=...) transactionally persists active/previous/candidate metadata and the evaluated artifact hash. It rejects fabricated or mismatched evaluation artifacts. Restart and rollback are tested. AdapterDeploymentManager verifies and stages actual weights, loads a replacement runtime before committing activation, recovers after restart, and restores previous weights on rollback. evaluate_active runs independent regression cases and rolls back failures. Hosts schedule this evaluation; scalar telemetry alone cannot approve a candidate. SupervisedLoRATrainer trains frozen-base Llama-family down_proj LoRA parameters on admitted semantic DSL, exports GGUF and records dataset/artifact hashes and losses. Other model architectures and adapter target modules are rejected. Training smoke evidence is not learning-quality or deployment-gate evidence.

---

## 1. Two-Speed Continual Learning

The CNE platform strictly separates rapid error correction from long-term parameter adaptation.

```text
+-------------------------------------------------------------------------+
| FAST LEARNING (Immediate, Memory-Based)                                 |
| Trigger: Verified user correction, OutcomeContract failure              |
| Mechanism: L4 Correction Store constraint retrieval                     |
| Weight Mutation: ZERO. Immediate effect on subsequent turns             |
+-------------------------------------------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
| SLOW CONTINUAL LEARNING (Gated, Replay-Sampled)                          |
| Trigger: Accumulated verified experiences in L5 Replay Store            |
| Mechanism: Parameter-efficient adapter fine-tuning (LoRA / Prefix)      |
| Gate: Shadow testing on historical regression suite                     |
| Activation: Atomic versioned rollout with instantaneous rollback       |
+-------------------------------------------------------------------------+
```

---

## 2. Fast Learning Architecture (L4)

1. **Triggering:** When an execution trajectory is flagged with an `AuditSignal` (e.g. `SLOT_ERROR`, `INTENT_ERROR`, `CONTRACT_FAILURE`), an `ExperienceRecord` is evaluated.
2. **Verification Gate:** Feedback creates `audit_status = UNVERIFIED`. A trusted independent verification process may subsequently approve it; preferences may instead become USER_SCOPED.
3. **Retrieval & Planning Constraints:** Subsequent queries in the same capability domain perform semantic retrieval over active L4 corrections. Matching corrections are injected as negative constraints or few-shot counterexamples into the prompt/planner context.
4. **Safety Invariant:** Correction records can **never** override deterministic safety rules, permission boundaries, or contract validations.

---

## 3. Slow Continual Learning Architecture (L5)

1. **Candidate Generation:** Periodically batches curated examples from L5 Learning Replay Store.
2. **Parameter-Efficient Adapters:** Targets small rank-4 or rank-8 LoRA adapters or prompt-tuning vectors. Base model weights remain frozen and immutable.
3. **Regression Gate Thresholds:**
   - $\ge 80\%$ recovery on verified historical error corpus.
   - Repeated verified-error recurrence $< 10\%$.
   - Unrelated-task regression $< 2.0$ percentage points on standard benchmark splits.
   - Zero new permission violations.
   - Zero new unsafe state-reuse violations.
4. **Versioned Rollout & Rollback:**
   - Every candidate adapter is assigned a semantic version (e.g. `adapter.v1.0.1`).
   - Prior adapter versions are archived in local storage.
   - If post-deployment telemetry flags a regression, the platform triggers an atomic rollback to the prior verified adapter version.
