# CNE Core Integration Specification

## Current implementation evidence (2026-10-06)

Implementation status: IMPLEMENTED for declared deterministic grammar paths; PARTIAL for general model orchestration.

PlatformExecutor performs scoped session access, installed-capability resolution and permission checks, correction retrieval, controller decision, typed slot binding, explicit DSL compilation, CNE execution/verification, SQLite experience persistence, telemetry and audit. Tests assert actual finance results and a two-capability orders/inventory join. These are desktop integration tests, not Android P13 validation.

ExecutionSemanticVersionVector contains selected capabilities and projected manifest hashes, used tools, explicit model/adapter/knowledge versions, compiler and policy versions. The execution projection excludes unused tool declarations; the full package manifest is separately integrity-verified. Updating unrelated packs or unused tool schemas preserves identity. Version lists must name actual participants; RuntimeSemanticController propagates the executed model ID/version; real GGUF runtime inference is smoke-tested; controller semantic quality remains unevaluated. The global enabled-pack hash is a legacy diagnostic, not used by PlatformExecutor.

Invariant: every data mutation goes through MutationAuthority or declared tool mutation_sources and calls LocalStateFabric.notify_data_mutation(), including partially failing mutations. Freshness records must be checked before each CNE cache lookup. ExternalDataCache provides scoped TTL checking; no network connector currently populates it.

One narrow core correctness fix clears per-iteration region values, including nested regions, so Iterate recomputes against the current item. Core contracts, optimizer, planner, cost gate, signatures and verification authority remain unchanged. The controller mode environment switch described below is a design target, not an implemented selector.

---

## 1. Integration Boundary & Principles

CNE (`ComputationNecessityEngine`) remains the authoritative execution and necessity engine of the platform. The platform layers (Device Abstraction, Capability Packs, DSL Controller, Memory Layers) sit **upstream** and **downstream** of CNE without bypassing or mutating CNE's internal verification pipeline.

```text
User Request
     |
     v
[Platform Controller Layer]
  - Device profile & resource check
  - Capability resolution
  - Session context & correction retrieval
  - Semantic DSL generation
  - Deterministic DSL compilation -> SemanticIRGraph + OutcomeContract
     |
     +-----> PlatformControllerBridge
                 |
                 v
           CompilationResult
                 |
                 v
[CNE Execution Engine (Preserved)]
  1. Effect Policy & Cacheability check
  2. Extended MemoKey generation (scoped by capability vector)
  3. Local State Fabric lookup (L3)
  4. If Hit: Verify against OutcomeContract -> Return reused state
  5. If Miss: Cost Gate -> Static Optimizer -> Physical Planner ->
              Execution -> Verifier/Auditor -> State Persistence
                 |
                 v
           CNEExecutionResult
                 |
                 v
[Platform Feedback & Audit Layer]
  - Error Auditor updates L4 Correction Store if failure occurred
  - Session Store (L1) updated with turn outcome
  - Local Telemetry logged
```

---

## 2. Extended SystemVersions & MemoKey

To ensure that capability pack updates, model swaps, or tool schema modifications never result in silent, invalid state reuse, `SystemVersions` is extended backwards-compatibly:

```python
@dataclass(frozen=True)
class SystemVersions:
    # Existing CNE core fields (defaults preserved for 100% backward compatibility)
    model_version: str = "v1.5"
    tokenizer_version: str = "v1.0"
    runtime_version: str = "1.0.0"
    semantic_compiler_version: str = "1.0.0"
    policy_version: str = "1.0.0"
    knowledge_version: str = "1.0.0"
    schema_version: str = "1.0.0"

    # New Platform extension fields
    capability_vector_hash: str = "core_default"
    adapter_version: str = "none"
    tool_schema_hash: str = "none"
```

### Stable Capability Vector Hash
When multiple capability packs participate in a query, their IDs and versions are sorted lexicographically and hashed:
```python
def compute_capability_vector_hash(active_packs: List[Tuple[str, str]]) -> str:
    sorted_pairs = sorted(active_packs, key=lambda p: p[0])
    raw = ";".join(f"{cid}@{v}" for cid, v in sorted_pairs)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
```
This guarantees that updating a capability pack from `1.0.0` to `1.0.1` cleanly generates a different `MemoKey`, preventing stale computation reuse.

---

## 3. Platform Controller Bridge

The `PlatformControllerBridge` implements the compile interface expected by existing CNE benchmark and integration consumers:
```python
class PlatformControllerBridge:
    def __init__(self, platform_controller: PlatformSemanticController):
        self.platform_controller = platform_controller

    def compile(self, query_text: str, context: Optional[Dict] = None) -> CompilationResult:
        # Executes: query -> capability routing -> DSL emission -> DSL compilation -> CompilationResult
        ...
```
A system configuration flag (`CNE_CONTROLLER_MODE`) allows selecting:
- `"legacy_controller"`: Uses `LearnedSemanticController` (P1 baseline)
- `"platform_controller"`: Uses `PlatformSemanticController` (new modular architecture)

Existing tests and benchmark scripts can run against either controller seamlessly.

External-data capabilities can declare `schemas.external_sources`. PlatformExecutor then requires fresh ExternalDataRecords for those observed sources, binds their values, and invalidates CNE state when their version/value fingerprints change. HTTPJSONConnector provides permission-checked real fetches and durable user-scoped cached records. A production travel/weather provider must still supply its host allowlist and endpoint; lack of a provider remains NO_DATA.
