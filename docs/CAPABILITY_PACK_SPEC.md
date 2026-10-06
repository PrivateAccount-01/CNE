# CNE Capability Pack Specification

## Current implementation evidence (2026-10-06)

Implementation status: PARTIAL. The sections below describe the target packaging architecture.

`permissions` are requests. Installation and rollback grant nothing. A trusted `PermissionAuthority` must issue an explicit capability/permission/scope grant with source and optional expiry. Enabled state, declaration, grant and exact scope are all required.

Production registration rejects missing/mismatched manifest hashes, missing or corrupt declared assets, and absent/invalid signatures. Signature verification requires a trusted verifier configured by the host; Ed25519TrustStore supplies local signing, domain-bound key trust and revocation. Enterprise key distribution is not included. Canonical manifests use sorted compact UTF-8 JSON, exclude `package_hash`/`signature`, and include asset hashes. `package_hash` stores the bare SHA-256 canonical manifest digest. Unsigned first-party development packages require explicit `TrustMode.DEVELOPMENT_TRUST_MODE` by the host.

Dependencies use `capability.id@exact.version` (or an installed enabled capability ID). Semver ranges are NOT_IMPLEMENTED. Required model catalog entries need path/version/backend and a hash in production. Cycles fail before enabling. CapabilityPackageInstaller rejects traversal, symlinks, duplicate entries and undeclared assets, verifies staged packages, then publishes content-addressed files and durable registry pointers. Registry rollback restores the corresponding asset path. Untrusted tools use restricted workers.

Declared `schemas.intents` contain full-match patterns, typed slots, DSL templates, and optional composition capability IDs. Unmatched requests decline. Tool `mutation_sources` must list every modified CNE source; trusted tools must use the mutation authority. Malicious Python code is outside this in-process boundary.

---

## 1. Concept & Scope

A **Capability Pack** is a self-contained, modular bundle of assets that provides domain-specific AI and computational functionality to the CNE platform. A capability pack is **not** necessarily a neural model. A pack may contain:

- Heterogeneous model weights (or references to shared models)
- Parameter-efficient adapters (LoRA / prompt prefixes)
- Deterministic tools and calculation routines
- Input/output schemas and type ontologies
- Normalizers, parsers, and prompt templates
- Local retrieval indexes and structured knowledge bases
- Local data connectors (e.g. SQLite, file system, sensor feeds)
- Evaluation and regression test cases
- Schema migration and state invalidation rules

---

## 2. Canonical Capability Identity

Every capability pack must possess a unique, dot-separated canonical ID matching the pattern:
```
<domain>.<subdomain_or_feature>
```
Examples:
- `finance.personal_budget`
- `finance.portfolio_risk`
- `agriculture.crop_disease`
- `travel.itinerary_planner`
- `vision.document_ocr`
- `health.workout_analytics`

---

## 3. Capability Manifest Schema

Every pack must provide a `manifest.json` adhering strictly to this schema:

```json
{
  "id": "finance.personal_budget",
  "version": "1.0.0",
  "description": "Local personal budget tracking, expense aggregation, and category filtering.",
  "modalities": ["TEXT"],
  "provided_capabilities": [
    "expense_aggregation",
    "budget_comparison",
    "category_filtering"
  ],
  "required_capabilities": [],
  "model_dependencies": [
    {
      "role": "semantic_controller",
      "model_kind": "TEXT_GENERATION",
      "model_id": "qwen2.5-coder-0.5b-gguf",
      "version": "1.0.0",
      "shared": true,
      "optional": false
    }
  ],
  "deterministic_tools": [
    {
      "tool_id": "finance.calc_sum",
      "schema_version": "1.0.0",
      "entrypoint": "cne.packs.finance.tools:calculate_sum"
    }
  ],
  "schemas": {
    "slots": "schemas/slots.json",
    "contracts": ["EXACT", "APPROXIMATE_NUMERIC"]
  },
  "permissions": [
    "filesystem:read",
    "financial_data:read"
  ],
  "network_mode": "OFFLINE",
  "storage_budget_mb": 25.0,
  "expected_peak_ram_mb": 120.0,
  "backend_compatibility": ["CPU"],
  "evaluation_suite": "tests/eval_suite.json",
  "package_hash": "sha256:...",
  "signature": "..."
}
```

---

## 4. Modalities & Network Modes

### Modalities
- `TEXT`: Natural language understanding, DSL generation, deterministic calculation.
- `IMAGE`: Computer vision, leaf/crop disease detection, OCR.
- `AUDIO`: Automatic speech recognition (ASR), voice commands.
- `TIME_SERIES`: Telemetry, health tracking, financial trends.
- `STRUCTURED`: Tabular data, SQL records, JSON documents.

### Network Modes
- `OFFLINE`: 100% local compute over local data. Outbound network sockets are physically blocked.
- `LOCAL_COMPUTE_NETWORK_DATA`: Computation is 100% local, but fresh external data may be fetched over network if available. If network is absent, returns an explicit freshness limitation rather than failing or hallucinating.
- `HYBRID_OPTIONAL`: Optional cloud offloading strictly when permitted by user and hardware cannot satisfy request.

---

## 5. Security & Permission Architecture

1. **Default Deny:** Capabilities have zero access to device resources unless explicitly declared in `permissions`.
2. **Deterministic Platform Enforcement:** Permissions are enforced by the platform runtime before invoking capability code or tools. The language model has zero authority to grant, request, or bypass permissions.
3. **Declared Permission Categories:**
   - `network`: External socket / HTTP access.
   - `filesystem`: Scoped directory read/write.
   - `camera`: Image capture.
   - `microphone`: Audio input.
   - `calendar`: Calendar event read/write.
   - `contacts`: Address book read.
   - `financial_data`: Sensitive banking/transaction stores.
   - `location`: GPS / coarse location.
   - `sensors`: Accelerometer, heart rate, step counters.
4. **State Isolation:** A pack may never access another pack's private state without an explicit mutual dependency declaration.

---

## 6. Lifecycle Management

The `CapabilityRegistry` manages the lifecycle of capability packs:
- `INSTALL`: Validates package hash and signature, unpacks into isolated directory, registers schemas.
- `ENABLE` / `DISABLE`: Dynamically activates or deactivates routing without deleting assets.
- `UPDATE`: Installs new version, verifies compatibility, atomically switches active pointer, invalidates dependent `MemoKey` computational state.
- `ROLLBACK`: Atomically reverts to prior version if regression gates fail.
- `UNINSTALL`: Safely unregisters pack, purges assets, preserves core runtime and unrelated packs.
