# CNE 19 Error Type Taxonomy

## 1. Classification Overview

The CNE Error Auditor classifies execution discrepancies, verifier mismatches, and user corrections into exactly 19 typed error categories.

---

## 2. Complete Error Taxonomy

| ErrorType | Description | Primary Audit Signal |
|:---|:---|:---|
| `ROUTING_ERROR` | Request routed to wrong capability pack | Capability resolver failure |
| `INTENT_ERROR` | Wrong computational topology selected | Intent mismatch with user request |
| `SLOT_ERROR` | Incorrect slot extracted or wrong value bound | Slot mismatch with gold schema |
| `SEMANTIC_PLAN_ERROR` | Emitted DSL violates DAG rules or frozen primitives | Parser or acyclicity failure |
| `TOOL_SELECTION_ERROR` | Wrong tool selected for task sub-operation | Tool dispatch discrepancy |
| `TOOL_ARGUMENT_ERROR` | Tool invoked with invalid types or missing parameters | Tool exception / validation failure |
| `MODEL_INFERENCE_ERROR` | Runtime crash, syntax timeout, or token truncation | Infer exception |
| `HALLUCINATION` | Emitted entity or fact unsupported by evidence | Verifier audit mismatch |
| `CONTRACT_FAILURE` | Execution result violates Outcome Contract bounds | Contract constraint violation |
| `VERIFICATION_ERROR` | Verifier unable to certify computation proof | Evidence tier degradation |
| `CACHE_ERROR` | Unsafe or incorrect memoized state returned | Stale state detection |
| `INVALIDATION_ERROR` | Source data mutated but cached state was not evicted | Dependency tracking failure |
| `FRESHNESS_ERROR` | Offline data returned without freshness disclaimer | Network mode policy breach |
| `RESOURCE_ERROR` | Query exceeded RAM, storage, or thermal budget | OOM or thermal throttling |
| `BACKEND_ERROR` | Hardware backend failed or unavailable | Device driver / runtime fault |
| `PERMISSION_ERROR` | Capability attempted unauthorized resource access | Deterministic security guard block |
| `COMPOSITION_ERROR` | Multi-pack join or pipelining failure | Inter-pack contract mismatch |
| `LEARNING_REGRESSION` | Candidate adapter degraded performance on benchmark | Shadow test regression gate failure |
| `VERSION_ERROR` | Incompatible capability, model, or schema version | Version vector mismatch |

---

## 3. Session Audit Report Schema

Every session audit produces a `SessionAuditReport`:
```json
{
  "session_id": "sess_1048",
  "total_turns": 4,
  "has_errors": true,
  "signals": [
    {
      "signal_type": "user_correction",
      "description": "User changed category from groceries to dining",
      "error_type": "SLOT_ERROR",
      "confidence": 1.0,
      "evidence": {"slot": "category", "old": "groceries", "new": "dining"},
      "timestamp": 1728189000.0
    }
  ],
  "generated_corrections": [
    "User changed category from groceries to dining"
  ],
  "created_at": 1728189010.0
}
```
