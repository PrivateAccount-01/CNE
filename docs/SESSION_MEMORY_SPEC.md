# CNE Multi-Layer Memory & Session Caching Specification

## 1. Memory Architecture Overview

The CNE platform organizes state across six strictly segregated layers, preventing execution artifacts, session context, computational state, and learning experiences from contaminating one another.

```text
+-------------------------------------------------------------------------+
| L0: MODEL EXECUTION CACHE                                               |
| Ephemeral KV/prefix cache | Key: (model_hash, tokenizer_hash, prefix_h) |
+-------------------------------------------------------------------------+
| L1: SESSION STORE                                                       |
| Active capabilities, entities, goals, compact summary                   |
+-------------------------------------------------------------------------+
| L2: SEMANTIC PLAN CACHE                                                 |
| Reusable DAG shapes parameterized by slot variables                     |
+-------------------------------------------------------------------------+
| L3: CNE COMPUTATIONAL STATE (LocalStateFabric)                          |
| Exact output memoization, MemoKey, dependency invalidation              |
+-------------------------------------------------------------------------+
| L4: CORRECTION / EXPERIENCE STORE                                       |
| Verified error records, counterexamples, planning constraints           |
+-------------------------------------------------------------------------+
| L5: LEARNING REPLAY STORE                                               |
| Curated, privacy-scoped training examples for gated slow adaptation    |
+-------------------------------------------------------------------------+
```

---

## 2. Detailed Layer Specifications

### L0: Model Execution Cache
- **Scope:** Ephemeral GPU/CPU KV cache and pre-computed prefix representations.
- **Keying:** Keyed strictly by `(model_version, tokenizer_version, stable_prefix_hash, tool_schema_hash)`.
- **Constraint:** Performance optimization only. Must NEVER be treated as semantic or factual memory.

### L1: Session Store
- **Scope:** Structured session state across turns.
- **Contents:**
  - Active capability pack IDs
  - Active entities and slot values
  - Active user goals and pending actions
  - Compact semantic summary (replaces endless transcript replay)
  - Links to verified correction records relevant to current domain
  - Token and resource budget meters
- **Session Continuation:**
  - When closing: serialize structured state, compact history, flush expensive L0 execution cache.
  - When resuming: load structured state, identify active packs, prewarm stable prefix, supply compact context window without full transcript replay.

### L2: Semantic Plan Cache
- **Scope:** Reusable computational topologies and DSL templates.
- **Rule:** May reuse topological DAG structures across similar queries, but **must rebind dynamic slots**. Stale slot values are never reused based on superficial phrasing similarity.

### L3: CNE Computational State (`LocalStateFabric`)
- **Scope:** Exact deterministic execution results stored in CNE's existing `LocalStateFabric`.
- **Mechanism:** Addressed by cryptographic `MemoKey`, constrained by `OutcomeContract`, invalidated by source data mutations via `DependencyManager`.
- **Rule:** Never stores learning experiences or unverified hypotheses.

### L4: Correction / Experience Store
- **Scope:** Verified failure analyses, user corrections, and verifier mismatches.
- **Record Schema:**
  - `fingerprint`: Request hash
  - `query_redacted`: Sanitized query text
  - `capability_id`: Target pack
  - `error_type`: Classified error category (19 types)
  - `incorrect_decision`: What the model/planner chose wrongly
  - `verified_correction`: The verified correct plan or slot binding
  - `audit_status`: `UNVERIFIED`, `VERIFIED`, `REJECTED`, `SUPERSEDED`
  - `provenance`: Timestamps, user/verifier feedback, confidence
- **Rule:** Correction memory is **never returned directly as an answer**. It may only constrain or inform subsequent planning (fast learning).

### L5: Learning Replay Store
- **Scope:** Curated, privacy-filtered training datasets for offline adapter fine-tuning.
- **Governance:** Deduplicated, versioned, retention-limited, and subject to forget/regression verification.
