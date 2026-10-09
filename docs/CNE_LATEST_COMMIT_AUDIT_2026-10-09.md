# CNE latest-commit audit, implementation status, and remediation plan

**Audit date:** 2026-10-09  
**Repository:** PrivateAccount-01/CNE  
**Reviewed main commit:** `f14493eab9023e71264b370c5385322fa4d7a154`  
**Parent:** `94e4adad16b37abcf6311be12cd042dd9614778b`  
**Latest commit title:** “feat: Introduce new platform components for prompting, runtime configuration, state management, and storage”  
**Review type:** repository source inspection + published GitHub Actions run/log inspection; **not** an independently executed local test run.  
**Code changed by the reviewed commit:** 39 paths (including CI, runtime, storage, routing, correction review, tests, and docs).  
**Review boundary:** findings describe this exact source snapshot. Subsequent commits require revalidation.

> **Executive verdict:** CNE has advanced from a primarily research-oriented computation kernel to a substantial **local-first platform prototype**. The newest commit closes several genuine gaps: bounded capability routing, declarative prompt views, typed correction promotion, durable SQLite-backed repositories, optional AES-GCM payload encryption, persistent computational-state reuse, restricted utterance patterns, and a CI workflow. **It is not production-ready, the replacement controller is not quality-qualified, and the current commit is not CI-green.** Several source-level defects must be addressed before an authoritative model tournament, third-party capability release, or Android claim.

## 1. The current position, in one page

### 1.1 What is implemented, what is proved, and what remains

| Subsystem | Code status at reviewed SHA | Evidence level | What it actually means |
|---|---|---|---|
| Semantic IR, frozen primitives, graph execution | Implemented research prototype | Historical unit/gate tests; not green at this SHA | Real DAG and evaluator machinery exists; do not rewrite it |
| Outcome Contracts, signatures, memo keys, optimizer, verifier | Implemented research prototype | Historical tests/reports | The distinctive computation-necessity core exists; general correctness guarantees remain workload-conditional |
| Dependency invalidation and incremental reuse | Implemented for tested paths | Prior tests plus new restart tests | Cache reuse is real; concurrency, crash consistency, and encrypted invalidation are not fully safe |
| Deterministic capability registry, scoped grants, signed package verification | Implemented application-level mechanisms | Source + earlier integration evidence | Not yet a complete third-party security boundary or mobile sandbox |
| Capability inverted index / bounded top-K routing | Implemented | New 120-pack **boundedness** test | Bounded prompt size demonstrated in a fixture; routing recall at 100–1,000 packs not demonstrated |
| Declared-grammar controller and typed slots | Implemented for narrow patterns | Deterministic finance/correction fixtures | Not an open-domain NL controller |
| Local GGUF CPU model adapter, quantization-compatible runtime, adapter attachment | Implemented optional runtime paths | Prior desktop SmolLM2-135M smoke artifacts | Actual inference exists; current model-to-CNE end-to-end execution is not fully verified |
| Grammar-constrained runtime semantic controller | Implemented integration path | Schema/fake-runtime tests; optional GGUF job not run | Model semantic quality and robust production chat formatting remain unproved |
| Persistent sessions, correction ledger, replay, plan cache, external data, computational state | Implemented SQLite repositories | New restart and encryption unit tests | Durability exists; migrations, deletion, encryption enforcement, quotas, and concurrent mutation are incomplete |
| Correction review and deterministic fast learning | Implemented for declared grammar | One verified finance alias example, restart/paraphrase checks | Narrow genuine improvement; **not** general autonomous learning |
| Supervised LoRA and gated adaptation | Mechanism implemented | Earlier one-example training/activation smoke | Proves mechanics, not improved generalization, privacy, or safe continual learning |
| Production-equivalent multi-model tournament | Harness exists | **Not run with candidate models** | No controller winner; no new blind score |
| 600-query replacement blind benchmark | Frozen historical dataset | Historical P1 numbers only | **Not rerun for new architecture** |
| Agriculture computer vision | Explicit stub | No real CV inference | Must not be advertised as implemented |
| Android 6 GB CPU-only deployment | Not implemented | No real-device evidence | All memory, thermal, battery, and mobile latency targets are hypotheses |
| Third-party capability ecosystem | Partially designed and desktop-sandboxed | Limited Linux/WSL tests | No Android untrusted-pack isolation proof |
| Reinforcement learning / autonomous policy adaptation | Excluded/not implemented | None | Do not claim this capability |

**Overall stage:** strong **desktop platform prototype / integration-hardening stage**. The platform is **not** at productionization, Android certification, general controller acceptance, or publishable end-to-end savings validation.

### 1.2 What the latest commit achieved

- Added `PlatformRuntimeConfig` and `PlatformRuntimeFactory` to compose persistent services under a configured root instead of relying on incidental in-memory defaults.
- Added `StateFabricRepository` / `PersistentStateFabric` for conservative, exact-JSON computational state reuse across restarts.
- Added `SQLiteReplayRepository` and optional AES-GCM `EncryptedPayloadCodec`.
- Added `CapabilityIndex`, `ControllerCapabilityViewBuilder`, and `ControllerPromptBuilder` to reduce prompt exposure and bound candidate selection.
- Replaced arbitrary default regex matching with restricted legacy regex and typed utterance templates.
- Added operation-level permission declarations and checks.
- Added audited correction transitions, user-scoped preference promotion, verified correction constraints, and progression tests.
- Added optional killable-process GGUF inference, thread policy, structured decoding smoke, and an actual GitHub Actions workflow.
- Added more honest single-run evidence tooling and documentation of measurement limits.

These are meaningful implementation advances. They do **not** erase the defects below.

### 1.3 The actual CI result at this SHA

**GitHub Actions run:** https://github.com/PrivateAccount-01/CNE/actions/runs/37963846298  
**Job:** `full-suite`, **FAILED**. `optional-gguf-smoke`, **SKIPPED**.

The runner successfully checked out the reviewed SHA, installed `.[platform,dev]`, and passed the checksum step. Pytest then reported **341 collected items / 1 collection error**, stopped before test execution, and exited with code 2. The exception was:

    ModuleNotFoundError: No module named 'openai'
    cne/compiler/constrained_decoder.py:22

This is **not** evidence that 341 tests failed. It is also **not** a passing suite. Previous reports of 350 unique tests across multiple runs are historical artifacts from an earlier dirty/local snapshot and cannot substitute for a single clean run at this SHA.

**Immediate status rule:** until CI completes one clean full-suite run, the reviewed commit's overall correctness status is **BLOCKED / UNVERIFIED**.

## 2. Evidence notation and priority

- **CONFIRMED-CI:** directly observed in the linked Actions log.
- **CONFIRMED-SOURCE:** deterministic control-flow/contract mismatch visible in the exact source; still requires a regression test before closure.
- **HIGH-RISK:** strong architectural failure mode, not yet reproduced.
- **HYPOTHESIS:** performance/quality/security concern requiring empirical validation.

Priority definitions:
- **P0:** blocks trust in current commit or creates a credible correctness/security failure on an intended path.
- **P1:** blocks controller productionization, durable multi-user operation, or credible benchmarking.
- **P2:** ecosystem/mobile hardening before broader release.
- **P3:** can wait until core quality and safety gates are green.

## 3. P0: repair before treating this commit as a baseline

### F-001. Clean CI cannot collect tests

**Priority:** P0. **Evidence:** CONFIRMED-CI.  
**Location:** `.github/workflows/ci.yml:18,25-26`; `cne/compiler/constrained_decoder.py:22`; `pyproject.toml`.  
**Failure:** `pip install -e '.[platform,dev]'` does not install `openai`, while a legacy controller module imports it at module import time. The full suite aborts during collection.

**Fix specification:**
1. Put the legacy OpenAI-compatible client dependency in an explicit, version-bounded optional extra, for example `legacy-controller`, and install that extra in the full-suite job **or** make the import lazy so offline unit tests can collect without it.
2. Preserve legacy controller tests; do not silently skip, delete, or xfail them to paint CI green.
3. Test both dependency-present and dependency-absent import behavior. The latter should fail only when a feature actually requiring the client is invoked.
4. Upload JUnit plus a source-bound evidence manifest from the same run. Add a test summary and exit-code check.
5. Use a fresh checkout and the same dependency lock/constraints as the intended runtime.

**Required tests:** `python -m pytest cne/tests --junitxml=artifacts/junit.xml` from clean CI; isolated legacy-controller import tests.  
**Acceptance:** no collection errors, one full-suite run passes, and the evidence manifest points to this exact tested SHA. No merged partial-run totals.

### F-002. Encrypted computational-state invalidation dereferences the ciphertext envelope as plaintext

**Priority:** P0. **Evidence:** CONFIRMED-SOURCE.  
**Location:** `cne/platform/state_repository.py:43-74,76-85,194-196`; `cne/platform/storage.py:94-124`.  
**Failure:** `StateFabricRepository.save` encrypts the state payload when a codec is present. `invalidate` then executes `json.loads(payload)["source_fingerprints"]` without decrypting. The decoded object is the AES-GCM envelope with fields such as `v`, `key_id`, `nonce`, `data`, **not** `source_fingerprints`. Source mutation on encrypted persistent state therefore raises an error rather than safely invalidating it.

**Fix specification:**
1. Do **not** scan and decrypt every state row on each mutation. Create a relational dependency index, e.g. `computational_state_sources(owner, source, memo)`, with an index on `(owner, source)`.
2. On save, atomically replace the state row and its source-index rows in the same SQLite transaction.
3. On mutation, delete affected memo rows via the index and delete associated index rows in one transaction. Keep owner scoping in every predicate.
4. On startup, verify the state/index schema version and migrate or rebuild the index from authenticated payloads. Fail closed on corruption; never reuse unvalidated rows.
5. If encryption or the index is unavailable, disable durable reuse and recompute. Never continue with stale state.
6. Add explicit tests for encrypted state: first execution, restart hit, source mutation, restart miss, second user isolation, wrong key, corrupt ciphertext, and interrupted index update.

**Acceptance:** zero stale hits and zero invalidation exceptions across encrypted and plaintext paths; source invalidation is indexed rather than O(all owner rows).

### F-003. Runtime-controller execution consumes a three-field model tuple as a two-field pair

**Priority:** P0. **Evidence:** CONFIRMED-SOURCE.  
**Location:** `cne/platform/bridge.py:343-349,558-565`; `cne/platform/versions.py:10-16,35-64`; `cne/platform/execution.py:302,462-478,504,518,539`.  
**Failure:** runtime-controller evidence defines model dependencies as `(model_id, version, asset_sha256)`. `ExecutionSemanticVersionVector.models` preserves those triples. The executor calls `dict(vector.models)` and destructures `for model_id, _ in vector.models`. Python rejects three-element entries in these two-element consumers. This failure occurs **after CNE execution** when experience/telemetry records are built, potentially after tool side effects.

**Fix specification:**
1. Freeze one canonical typed model identity, e.g. `ModelDependencyIdentity(model_id, version, asset_sha256)`, and use it throughout controller, vector, experience, telemetry, audit, and cache.
2. Convert triples explicitly to a structured record/list; never call `dict` on triples. Include the asset digest in cache identity and evidence.
3. Define serialization and migration for old two-field model entries; reject malformed arities.
4. Ensure all persistence and telemetry preparation that can fail occurs before irreversible side effects, or use a durable execution journal.
5. Add a real `RuntimeSemanticController -> bridge -> PlatformExecutor.execute -> ExperienceRepository -> telemetry` test with a controlled local model boundary returning valid structured output. Include a one-tool call and verify no duplicate side effect on retry.

**Acceptance:** full runtime-controller path succeeds with model hash-bearing vectors; version changes invalidate dependent reuse; no tuple-unpack or dictionary-conversion errors.

### F-004. Production composition bypasses the model-residency budget

**Priority:** P0 for resource guarantees; P1 for desktop correctness. **Evidence:** CONFIRMED-SOURCE.  
**Location:** `cne/platform/runtime_config.py:108-143`; `cne/platform/bridge.py:280-290`; `cne/platform/models.py:126-285`.  
**Failure:** `PlatformRuntimeFactory.create` constructs `RuntimeSemanticController` without a `residency_manager`. The controller consequently loads the model directly through `runtime.load_model` and does not apply `ModelResidencyManager.ensure_resident` budget/eviction accounting. A platform-level 1.5 GB memory envelope is not enforced by this factory path.

**Fix specification:**
1. Add explicit resource budget configuration to `PlatformRuntimeConfig`, including controller/model residency, context, concurrent inference count, and per-capability budgets.
2. Construct and inject one shared `ModelResidencyManager` in the factory. The factory should reject a model descriptor without a runtime, or a runtime without a valid descriptor.
3. Use admission control **before** model load; account for resident models, KV context, activation transient double-residency, Python overhead, and worker copies.
4. Make `PlatformRuntime.close` release active model ownership and unload owned runtime assets. Handle crash recovery without trusting stale in-memory accounting.
5. Measure RSS and PSS on the target device. An RSS delta from a memory-mapped GGUF is not a reliable peak-memory guarantee.

**Acceptance:** no direct model-load bypass in production composition; memory-pressure tests produce bounded eviction or explicit decline; real Android peak PSS remains **NOT_MEASURED** until tested.

### F-005. Compiler creates an EXACT contract regardless of the domain's declared outcome requirements

**Priority:** P0 for research correctness. **Evidence:** CONFIRMED-SOURCE.  
**Location:** `cne/platform/dsl.py:100-109,273-279`; `cne/platform/bridge.py:585-599`; `cne/packs/travel/manifest.json`.  
**Failure:** `SemanticDSLParser.compile_dsl` constructs `OutcomeContract(contract_type=contract_type)`, with `EXACT` as default. The bridge uses that default; the runtime model response schema contains no outcome-contract selection or validated contract parameters. Capability manifests may declare `STRUCTURED_EXPLANATION`, `SET_VALUED`, or `APPROXIMATE_NUMERIC`, but that declaration is not used to construct the actual contract.

**Why this matters:** CNE's research claim depends on preserving the **correct requested outcome**, not merely generating a structurally valid DAG and checking its output against an underspecified contract.

**Fix specification:**
1. Introduce a versioned, typed `OutcomeContractSpec` selected by the declared intent, not freely authored by the model.
2. Define output schema, exactness/tolerance, required facts, provenance, freshness, side-effect rules, and allowed equivalence per intent.
3. Have the deterministic compiler validate the selected contract against the plan's output type and capability contract allowlist.
4. For unknown or ambiguous contract semantics, decline or execute the full conservative path; never silently fall back to EXACT.
5. Add differential semantic oracles for finance, travel, cross-source join, and nondeterministic/external tools. Prove that contract changes alter cache identity.

**Acceptance:** no compiled plan without an explicit validated contract specification; tests reject mismatched contract types and demonstrate correct invalidation under contract drift.

### F-006. The runtime model sees corrections but does not deterministically apply verified constraints

**Priority:** P0 for advertised fast learning. **Evidence:** CONFIRMED-SOURCE.  
**Location:** `cne/platform/bridge.py:292-299,405-455`; `cne/platform/correction_review.py:237-294`; `cne/platform/execution.py:270-319`.  
**Failure:** the declared-grammar controller calls `CorrectionConstraintApplier.apply_slots` and `validate_plan`. The runtime controller only serializes approved constraints into the prompt. It does **not** run the same deterministic post-model slot normalization, unique-routing selection, or invalid-plan digest rejection before accepting the model plan. Prompting a model to respect a verified correction is not an enforcement mechanism.

**Fix specification:**
1. Move correction application into a shared deterministic **post-inference, pre-DSL-compilation** stage used by both controllers.
2. Apply typed constraints to bound slots, then rebind/revalidate with the selected intent's schema.
3. Reject exact known-invalid plan digests, resolve only uniquely verifiable routing corrections, and reauthorize tools/sources after any change.
4. Bind correction scope to owner, capability, intent, schema/version, source context when relevant, and a finite validity window. Reject contradictory corrections.
5. Record the exact applied correction IDs and distinguish “retrieved” from “applied” in telemetry. Do not claim a recurrence reduction when only the prompt changed.

**Acceptance:** verified corrections change or block runtime-controller outputs even when the model ignores the correction text; unverified and unrelated corrections have zero effect.

## 4. P1: controller, state, privacy, and methodology issues

### F-007. Response schema is not compositional across domain packs

**Evidence:** CONFIRMED-SOURCE. **Location:** `cne/platform/prompting.py:12-27,40-50`; `cne/platform/controller_view.py:115-157`.  
**Failure:** the response schema merges **top-level** pack slots into one flat object and throws when two shortlisted packs use the same slot name with different schemas. It does not build response properties from intent-only slots. This can reject a legitimate request merely because an irrelevant shortlisted pack has a conflicting `date` or `amount` definition, or make an intent-only slot impossible to emit.

**Fix:** use capability+intent-qualified slot namespaces and a discriminated schema keyed by the selected capability/intent. Validate selection first, then validate only that intent's slots. For multi-pack composition, explicit aliasing and type unification must resolve collisions.  
**Tests:** unrelated conflicting packs do not block one-domain queries; two-domain plan with same-named but distinct slots compiles; intent-only required slots appear in output grammar.  
**Gate:** zero false schema collisions on an adversarial pack-composition corpus.

### F-008. Permission fallback becomes coarse when an intent is not declared by a participating pack

**Evidence:** CONFIRMED-SOURCE. **Location:** `cne/platform/operations.py:5-27`; `cne/platform/bridge.py:433-443,498-539`.  
**Failure:** `intent_permissions` falls back to **all manifest permissions** if the requested intent is absent. In cross-pack plans, secondary packs can therefore require unrelated grants even when only one source/tool is used. This can cause false denial and obscures least-privilege proofs.

**Fix:** represent an intent's ownership and each graph node's owning pack explicitly. Require only the primary intent's declared grants plus the exact selected tool/source grants of secondary packs. Reject undeclared cross-pack resource ownership.  
**Tests:** secondary pack with extra unused `calendar:write` does not require that grant for a read-only composition; undeclared source/tool still denied.  
**Gate:** least-privilege permission trace matches executed resources exactly.

### F-009. The CI “reviewed corpus checksum” checks a test file, not the frozen blind corpus

**Evidence:** CONFIRMED-SOURCE. **Location:** `.github/workflows/ci.yml:19-22`.  
**Failure:** the checksum covers `cne/tests/unit/test_realistic_corpus.py`. It does **not** pin `cne/artifacts/p1_dataset/test_heldout_blind.jsonl` or its independent gold metadata. A test source checksum is not blind-corpus integrity.

**Fix:** freeze the blind dataset's raw-byte SHA-256 and gold manifest in a protected provenance file, verify both in CI, prohibit training jobs from reading that path, and keep evaluation credentials/data separated from development. Do not update the frozen hash casually.  
**Gate:** deliberate one-byte blind-corpus modification fails integrity CI; training-data scanner detects any blind IDs or near-duplicates.

### F-010. Privacy defaults and user deletion are incomplete

**Evidence:** CONFIRMED-SOURCE + HIGH-RISK. **Locations:** `cne/platform/runtime_config.py:114-118`; `cne/platform/memory.py:218-243,362-404`; `cne/platform/storage.py:83-124`.  
**Failure:** production can run with **no encryption key provider**, leaving SQLite payloads plaintext. Sessions persist raw `active_entities` slot values; correction constraints and training examples are not comprehensively scrubbed by the regex redactor. Multiple stores have individual delete methods or none, but there is no one authoritative, tested delete-user workflow across sessions, experiences, corrections, state, replay, plans, telemetry, external data, and adapters.

**Fix:** production policy must explicitly choose “encrypted private store” or a documented host-managed equivalent; fail startup if policy unmet. Implement a single owner-scoped deletion coordinator, including key destruction/rotation, backup and export policies, index cleanup, training replay tombstones, and audit receipts. Store minimum necessary session entities with retention/TTL. Do not treat a boolean `privacy_approved` as a privacy classifier.  
**Tests:** multi-user deletion, restart, backup restoration, encrypted mutation, wrong key, key rotation, redaction bypasses (names, account strings, free-text constraints), and data recovery attempts.  
**Gate:** no readable deleted-user content in active stores or new training sets; all persistent stores covered by the deletion inventory.

### F-011. State persistence is not bounded, versioned, or concurrency-safe enough

**Evidence:** CONFIRMED-SOURCE + HIGH-RISK. **Location:** `cne/platform/state_repository.py:12-41,100-151`; `cne/platform/runtime_config.py:54-66`.  
**Failure:** `safe_json` recursively accepts arbitrary-size lists/dicts and has no byte, depth, row-count, or owner quota. The state schema uses a payload version but no migration implementation. Multiple SQLite connections and in-memory engine maps have no cross-process transaction/locking protocol. Crash or concurrent mutation during execution can race with memo reuse.

**Fix:** enforce maximum serialized bytes, nesting depth, element count, per-owner rows, TTL, and eviction. Use SQLite WAL, busy timeout, explicit migration transactions, integrity checks, and a single-writer policy or optimistic generation/epoch checks. Snapshot source-version vectors at plan start and revalidate before publishing a reusable result; abort/recompute on concurrent mutation.  
**Tests:** fuzz deep JSON, disk-full, SIGKILL between state/index writes, two writers, concurrent source mutation, schema v1->v2 migration, database corruption, and rollback.  
**Gate:** zero wrong reuse under concurrency; bounded disk and memory; fail-closed recovery.

### F-012. Corrections and training replay can be promoted with insufficient semantic evidence

**Evidence:** CONFIRMED-SOURCE + HIGH-RISK. **Location:** `cne/platform/correction_review.py:103-194`; `cne/platform/learning.py:216-273`.  
**Failure:** a verifier is an arbitrary configured callback. The code checks distinct **names** for global promotion, not independent trust domains. A training example's “correct” DSL is checked for **syntax**, not equivalence to the user's intended result, schema version, or executable gold. The privacy flag is asserted in a dictionary. Replay admission checks presence of evidence, not a cryptographically bound trusted verifier attestation.

**Fix:** define a verifier registry with provenance, independence groups, signed/hashed evidence, immutable correction history, schema hash, exact request/plan identity, and independent executable expected outcomes. Use per-domain semantic oracles and privacy review. Quarantine suspect replay, detect poisoning/duplicates, and require explicit owner consent for training.  
**Tests:** malicious verifier, duplicate-authority aliases, mismatched incorrect-plan hash, valid-but-wrong DSL, private data hidden in constraint fields, revoked verifier, and conflicting corrections.  
**Gate:** no global promotion from two aliases of one authority; no training example without semantic and privacy attestations.

### F-013. Model-tournament path has missing production proof and documentation drift

**Evidence:** CONFIRMED-SOURCE. **Location:** `cne/platform/tournament.py:1-78`; `docs/EVALUATION_GATES.md`; `cne/platform/benchmark.py:91-282`.  
**Failure:** `ProductionControllerTournament` is a class-based harness, but documentation tells users to run `python -m cne.platform.tournament --config ...`. That module has no CLI entry point or argument parser. The callback-based `ModelSelectionHarness` is not itself production-equivalent. The tournament currently checks a narrow outcome/intent/value tuple and does not prove slot exact match, cross-domain semantic equivalence, calibrated rejection, energy, or safety.

**Fix:** either implement the documented CLI or remove the command. Require the exact `PlatformRuntimeFactory + RuntimeSemanticController + bridge + executor` pipeline for each candidate, varying only model/runtime settings. Pin dataset, prompt, grammar, tokenizer/chat template, GGUF digest, runtime version, thread policy, and hardware. Use independent semantic/contract/execution oracles and separate in-scope/OOS/ambiguous strata.  
**Gate:** a clean development tournament produces reproducible per-case and aggregate metrics with no blind-set exposure. No winner selected from parse success alone.

### F-014. The model chat-template and timeout paths need real compatibility and deadline tests

**Evidence:** HIGH-RISK. **Location:** `cne/platform/models.py:322-364,491-583`; `cne/platform/gguf_smoke.py:63-82`.  
**Failure mode:** `model.chat_handler` invocation and expected `formatted.prompt`/`formatted.added_special` may vary by installed llama-cpp-python version and model metadata. The fallback `System:/User:/Assistant:` format is not necessarily correct for an instruct-tuned model. In-process timeout is checked only between generated tokens; native prefill or a stuck call may exceed the deadline. The killable isolated worker is available but not the default controller execution path.

**Fix:** pin runtime version, introspect supported chat formatting with known fixtures, fail closed if a required template is missing, and test BOS/EOS policy. Use a supervised killable worker for hard deadlines where platform support exists; define Android-equivalent worker isolation. Record first-token and prefill separately.  
**Tests:** representative 135M/300M/600M licensed GGUF assets, structured JSON grammar, context overflow, malformed output, long prefill, worker crash, timeout, and cancellation.  
**Gate:** correct formatting and bounded termination on the exact production runtime, not just mocked interfaces.

### F-015. Routing is bounded but has no demonstrated recall at scale

**Evidence:** CONFIRMED-SOURCE + HYPOTHESIS. **Location:** `cne/platform/capability_index.py:18-75`; `cne/platform/registry.py:329-394`; `cne/tests/platform/test_review_hardening.py:57-66`.  
**Failure mode:** token overlap can return zero candidates for synonyms, multilingual requests, or paraphrases. Popular/common terms can displace the correct pack from top K. The 120-pack test proves only that five results are returned, not that the relevant pack is among them. Permission filtering happens after retrieval and may waste all K positions on unavailable packs.

**Fix:** two-stage deterministic indexed retrieval with canonical synonyms/aliases, typed modality filtering, permission/dependency eligibility, and bounded refill. Add multi-label recall and a conservative ambiguity/clarification path. Do not let untrusted manifest prose drive routing authority.  
**Tests:** 1/10/100/500/1,000 packs, collisions, OOS, synonyms, Unicode, adversarial keyword stuffing, missing grants, and 2–4-domain composition.  
**Gate (recommended, not measured):** top-K relevant-pack recall >=99% on an independently labeled supported-intent development set, with no silent execution of unauthorized packs.

### F-016. Package integrity, downgrade, and in-process trust need a stronger ecosystem boundary

**Evidence:** HIGH-RISK. **Location:** `cne/platform/registry.py:70-83,134-175,245-278`; `cne/platform/security.py:250-290`; `cne/platform/sandbox.py:18-167`.  
**Failure mode:** runtime registration can replace an installed ID, and no explicit monotonic version/downgrade policy is visible. The in-process allowlist is keyed by capability ID, not immutable publisher/asset identity. Rehashing entire declared assets on every controller request can create major I/O overhead; conversely, mutable installed paths risk TOCTOU if hashes are cached carelessly. Bubblewrap/WSL is not an Android sandbox.

**Fix:** immutable publisher-scoped pack identity, signed update chain, monotonic version policy with explicit rollback authorization, content-addressed read-only package storage, pinned opened file handles/asset digests, and trust decisions bound to exact signed assets. Run third-party code out of process with OS-enforced Android isolation before mobile release.  
**Tests:** forged trusted ID, signed downgrade, package swap after verification, symlink race, revoked key, zip bomb, malicious validator, and asset hash mismatch.  
**Gate:** no third-party code executes in trusted process; downgrade and mutable-asset attacks fail closed.

### F-017. Stale external data can be returned in a failed-fetch result

**Evidence:** CONFIRMED-SOURCE. **Location:** `cne/platform/external_data.py:121-176`.  
**Failure:** on HTTP failure, `HTTPJSONConnector.fetch` returns `LIVE_FETCH_FAILED` with `cached`, which may already be stale. The platform executor separately checks freshness for its explicit external records, but other consumers could accidentally treat `result.record` as fresh.

**Fix:** make the default failure result contain no usable record if TTL expired; expose stale fallback only through an explicit contract-allowed mode with a freshness flag and age. Bind source version, provenance, expiry and online/offline status to the execution dependency vector. Handle clock rollback and external schema changes.  
**Tests:** TTL expiry + network failure, clock rollback, ETag drift, offline transition, schema mismatch, and cache hit before/after restart.  
**Gate:** zero unmarked stale records accepted as fresh.

### F-018. Side effects are not transactional with post-execution persistence

**Evidence:** HIGH-RISK with source-level trigger F-003. **Location:** `cne/platform/execution.py:388-452,458-551`.  
**Failure mode:** a `CALL` node may perform an external write, and a later experience/telemetry/contract/version serialization error may raise. Retrying the request can repeat the side effect. Invalidation in `finally` is good but does not provide exactly-once semantics.

**Fix:** classify graph effects before execution. For mutating tools, require idempotency keys, prepare/commit or saga compensation, a durable effect journal, and a verifier-aware recovery state. Never memoize side-effectful calls as pure computation. Persist request/effect identity before invoking the tool.  
**Tests:** crash immediately before/after external write, exception after write, retry, concurrent duplicate request, and rollback.  
**Gate:** at-most-once external mutation for idempotent APIs; explicit reconciliation for non-idempotent APIs.

### F-019. Schema/runtime and Python-version documentation drift

**Evidence:** CONFIRMED-SOURCE. **Location:** `pyproject.toml`; `cne/platform/runtime_config.py:32-40`; `docs/PLATFORM_HARDENING_AUDIT.md:58`.  
**Failure:** package metadata declares `requires-python >=3.9`, but modules without postponed annotation evaluation use PEP 604 unions (e.g. `str | None`), which require Python 3.10+. The hardening audit still describes historical combined passes rather than the latest clean CI status.

**Fix:** set supported Python minimum to the actual supported version (recommended >=3.10, possibly >=3.11 if chosen) or backport annotation syntax and test 3.9. Add a tested Python matrix. Update the status report to reference the current SHA and single-run CI artifact.  
**Gate:** clean install/import/test on every declared supported Python version; no misleading pass badge.

### F-020. Evidence tooling does not by itself prove full-suite completeness

**Evidence:** CONFIRMED-SOURCE. **Location:** `cne/platform/evidence.py:47-88`.  
**Failure:** `build_evidence_report` sets `single_full_suite_pass` from a caller-supplied `full_suite` flag and JUnit's lack of failures. It does not verify expected test inventory, exit code, exact command execution, or CI provenance. `ci_commit_evidence` is hard-coded false.

**Fix:** generate evidence inside the CI job after the actual command; record exit status, job/run IDs, commit/tree, dependency lock, test inventory, JUnit digest, corpus digest, and artifact URL. Compare expected test inventory to collected IDs, not merely the count. Verify source identity and clean checkout.  
**Gate:** a tiny passing subset cannot be labeled a full-suite pass; dirty runs are explicitly non-authoritative.

### F-021. Learning deployment is not yet a robust multi-restart promotion protocol

**Evidence:** HIGH-RISK. **Location:** `cne/platform/learning.py:307-395`; `cne/platform/models.py:446-489`.  
**Failure mode:** `GatedAdaptationPipeline.deploy_candidate` requires an evaluation result in the evaluator's **in-memory** `_artifacts` map even though evaluation payloads are written to SQLite only during deployment. Artifact existence and digest validation are not performed in that method. Runtime adapter activation has stronger mechanics, but the full end-to-end evaluation-to-deployment trust chain remains fragmented.

**Fix:** persist signed/hashed evaluation provenance before deployment; bind candidate to exact base-model digest, adapter digest, dataset hashes, and runtime version. On restart, revalidate evidence and artifacts before staged activation. Run shadow/holdout regression, then atomic pointer switch, post-activation canary, and automatic rollback on independently measured failure.  
**Gate:** safe restart between evaluation and activation, rejection of swapped/missing adapter, and zero unauthorized promotion.

## 5. Further stress and failure exploration

These are **tests to run**, not observed benchmark outcomes.

| Stress dimension | Likely failure | Required invariant and experiment |
|---|---|---|
| 1 -> 1,000 installed packs | top-K false negatives, manifest scanning, prompt collisions | Query latency and top-K recall measured by pack count; bounded candidate view; permission-safe refill |
| 2–4 active packs | slot collisions, wrong tool ownership, contract mismatch | Qualified namespaces, typed composition, source/tool ownership graph; differential execution oracle |
| 100M/150M/300M/600M controllers | underpowered slots/OOS, JSON truncation, latency | Same production pipeline; held-out development splits; model hash and prompt identity fixed |
| 6 GB ARM CPU-only | mmap accounting error, KV growth, thermal collapse | Android PSS, RSS, energy, P50/P95, cold/warm latency, 30-minute soak; CPU-only correctness |
| Process death during state write | partial row/index, lost mutation notification | SQLite transaction + generation epoch + crash-injection checkpoints |
| Two concurrent requests | stale read, duplicate effect, SQLite lock | Source snapshot isolation, idempotency keys, bounded retries and no wrong cache hit |
| Encrypted state mutation | ciphertext treated as plaintext | F-002 regression must be mandatory in CI |
| Upgrade/rollback | stale cache or adapter/base mismatch | Version-vector migration, signed rollback authorization, zero cross-version reuse |
| Corrupt DB / wrong key | exception cascade or silent reset | Fail closed, quarantine, recover/recompute; never reinterpret ciphertext |
| Expired external data | stale answer after offline transition | Contract freshness gate; no unmarked stale fallback |
| Malicious manifest/template | prompt injection, routing hijack | Whitelist validated fields, immutable trusted instructions, fuzzed schemas, no pack prose authority |
| Malicious skill/correction | persistent prompt injection or bad normalization | Typed constrained correction, independent verification, scope and expiry, deterministic application |
| Long sessions / multi-user | private entities retained, context overflow | Per-user quotas, TTL, deletion, context budgets, isolation probes |
| Disk full | partial durable update and wrong success report | Preflight quota, atomic write, rollback, explicit STORAGE_EXHAUSTED |
| Model hangs in native prefill | cooperative timeout ineffective | Killable worker deadline, worker lifecycle test |
| Mutating tool fails after partial write | duplicate external side effects | Durable effect journal, idempotency, reconciliation |
| False verifier | wrong “verified” memory or poisoned replay | Independent oracle, provenance and authority separation |
| Clock/timezone changes | TTL/permission expiry drift | Trusted epoch and monotonic session checks; rollback detection |
| 24-hour soak | connection leak, DB bloat, memory creep | Stable PSS/disk/latency trends; no unbounded history |
| Capability removal | dangling state and tool dependencies | Revocation epoch, dependency index, fail-closed cache invalidation |

### 5.1 Computation-necessity falsification tests

The central claim is **not** that the controller is small. It is that CNE reduces necessary computation while preserving an Outcome Contract. Try to disprove it:

1. **Cold single-shot scalar tasks:** compare direct deterministic execution against CNE with routing, compilation, signature construction, lookup, optimization, verification, and persistence all included. If overhead dominates, the cost gate must bypass optimization.
2. **Low-reuse and high-churn data:** mutate one source every query. Compare CNE against recompute-all; record false reuse, invalidation overhead, and total energy.
3. **High-reuse sessions:** identical plans with varying slot values and source versions. Measure valid reuse, not just cache hit counts.
4. **Non-deterministic or effectful tools:** repeated calls, clock-dependent results, API freshness, writes, and randomized models. These should not receive unsafe exact memo hits.
5. **Contract drift:** switch from EXACT to approximate/decision/structured outputs. Prove distinct cache identities and correct equivalence checks.
6. **Cross-domain joins:** add/remove a pack, change schema/tool version, revoke permission, and change one input. Measure selective invalidation and contract preservation.
7. **End-to-end cost:** include controller inference and model load. CNE's downstream microsecond savings may be negligible next to seconds of language-model inference; report both separately.
8. **Ablation ladder:** direct execution; +DSL/IR; +state; +invalidation; +static optimizer; +cost gate; +verification; +corrections; +model controller. Report median/P95 latency, CPU time, energy, memory, correctness, and net savings with confidence intervals.

**Research decision rule:** if necessity analysis costs more than it saves for a workload class, the correct CNE behavior is to **bypass it**. Never make optimization mandatory for every query to protect the narrative.

## 6. Mandatory new test matrix

| Suite | New cases | Required pass condition |
|---|---|---|
| CI/dependency | clean install, legacy optional import, Python versions | Full collection + complete green suite |
| Model-vector serialization | hashed 3-field models, 2-field migration, runtime controller execute | No serialization failures or stale version reuse |
| Encrypted state | restart, mutate, invalidate, wrong key, corruption | Zero stale hits, zero encrypted invalidation crash |
| Persistent store | schema migration, disk full, kill mid-write, WAL recovery | Atomic or safely rejected state; no wrong reuse |
| Concurrent state | two users, same user concurrent reads/writes, source update | No cross-user leak, no stale hit, bounded lock waits |
| Controller schema | intent-only slots, conflicting names, multiple packs | Correct typed schema and deterministic decline |
| Correction loop | model ignores correction, conflicting correction, malicious verifier | Verified constraints enforced; unrelated unaffected |
| Permission security | absent grants, revoke mid-request, secondary-pack minimal grants | Zero unauthorized tool/source execution |
| Package supply chain | downgrade, forged trusted ID, asset swap, revoked key | Fail closed |
| Privacy | redaction bypass, all-store deletion, key rotation, backup restore | No unauthorized retention/recovery |
| External freshness | expired cached data + fetch failure, clock rollback | Zero false fresh claims |
| Tool effects | write + crash + retry, duplicate concurrent request | No unintended duplicate side effect |
| GGUF runtime | real grammar, model chat template, native deadline | Correct structured output, bounded execution |
| Model tournament | independently labeled development corpus, 3 size classes | Same production path, complete provenance |
| Scaling | 1/10/100/500/1,000 packs, multi-domain | Recall/latency curves reported, no fabricated thresholds |
| Android | reference 6 GB ARM, offline, process death, thermal soak | Device evidence for every claimed envelope |
| CNE research | negative-savings, churn, nondeterminism, contract drift | Correctness preserved; net savings honestly reported |

### 6.1 Suggested commands and artifact rules

- Clean test: `python -m pip install -e '.[platform,dev,legacy-controller]'` **after** defining the extra; then `python -m pytest cne/tests --junitxml=artifacts/junit.xml`.
- Separate focused tests for encrypted-state invalidation, model-version serialization, correction enforcement, and contract selection must be added before running the full suite.
- The GGUF job must use a licensed, locally provisioned model with pinned digest. It must upload its report as an artifact, including run SHA, asset digest, runtime version, and measured host.
- Do not use or tune against the frozen 600-query blind set while repairing these issues. Use newly curated train/dev/test splits and independent semantic gold.
- No test should fake a model response and then report that as a **real model-quality** measurement.
- Record **NOT_MEASURED** rather than zeros or passes for unavailable mobile, thermal, energy, or model-quality metrics.

## 7. Implementation sequence and hard gates

### Phase A: make the repository trustworthy again (P0, first)

1. Fix F-001 and obtain a clean full-suite CI run.
2. Add and fix F-002 encrypted-state mutation tests.
3. Fix F-003 hashed model-vector consumers and run actual runtime-controller-to-executor integration tests.
4. Fix F-004 factory residency injection and enforce explicit resource admission.
5. Fix F-005 explicit intent-owned Outcome Contracts.
6. Fix F-006 deterministic runtime correction enforcement.
7. Fix F-009 blind corpus checksum and F-019 Python-version support.

**Exit gate A:** one clean CI pass at the repair commit; no P0 defects; a source-bound JUnit/evidence artifact; zero wrong reuse in new regression cases. Do **not** run the frozen blind evaluation before this.

### Phase B: controller productionization

1. Fix F-007 typed cross-pack schemas and F-008 least-privilege operation ownership.
2. Establish a stable prompt/grammar/chat-template ABI, hard deadlines, and deterministic post-model validation.
3. Build a development-only semantic corpus with exact slots, intents, capability sets, OOS/ambiguity labels, contracts, and executable outcomes.
4. Stress retrieval at 1/10/100/500/1,000 packs, including synonyms and multi-pack requests.
5. Implement the documented tournament CLI or correct the documentation.
6. Run production-equivalent candidate comparisons, with model/adapter asset hashes and resource measurements.

**Exit gate B (recommended quality targets, not measured results):** schema >=99%; semantic correctness >=95% under an independent oracle; exact slots >=90%; OOS rejection >=95%; in-scope coverage >=60%; primitive adherence 100%; zero permission and stale-cache violations. Report all denominators and confidence intervals. If no model meets the gates, keep the deterministic controller and continue iteration.

### Phase C: privacy, persistence, and continual-learning readiness

1. Fix F-010/011/012/017/018/021.
2. Add encrypted and unencrypted migration, corruption, concurrency, deletion, and crash-consistency tests.
3. Bind training examples to executable semantic evidence, privacy consent, immutable version identities, and independent verifier authorities.
4. Run replay/adaptation regression gates on a held-out development suite, then canary/rollback. One-example LoRA smoke is not sufficient.

**Exit gate C:** reproducible historical-error recovery without unrelated regressions; zero new permission violations; zero unsafe state reuse; audited deletion and rollback. No autonomous weight promotion before this.

### Phase D: third-party ecosystem

1. Immutable signed pack identity and anti-downgrade policy.
2. Sandboxed execution with per-tool/source permissions and content-addressed packages.
3. Dependency revocation epochs, schema migrations, quotas, and malicious-pack fuzzing.
4. Cross-domain ownership and side-effect contracts.

**Exit gate D:** independent red-team suite with zero unauthorized execution or cross-user leakage; all unsupported hosts fail closed.

### Phase E: Android CPU-only reference deployment

1. Build an actual Android ARM64 host and safe worker model; do not assume Linux bubblewrap is available.
2. Measure process PSS/RSS, model load, KV growth, cold/warm P50/P95, CPU time, energy, thermal throttling, process death, and offline behavior.
3. Enforce the intended 6 GB device envelope with explicit graceful declines under pressure.

**Exit gate E:** target hardware meets **measured** peak PSS <=1.5 GB and steady memory <=1.0 GB (or revise the claim openly), CPU-only baseline correctness, stable soak behavior, and safe restart.

### Phase F: research and publication

1. Only after A–E are stable, run the **frozen 600-query blind set once** under a preregistered controller evaluation protocol; preserve the raw output and hashes.
2. Compare with historical P1 baseline: blind 37.5%, in-scope 41.0%, OOS 77.0%, slots 4.8%, shape diversity 0.7216, ~7.2s mean latency. These are **historical P1** measurements, not current-platform measurements.
3. Publish separate results for (a) semantic-controller quality, (b) CNE computation savings, (c) end-to-end latency/energy, and (d) device resource behavior.
4. Include negative savings, failure rates, CI source identity, ablations, confidence intervals, and reproducible scripts.

**Exit gate F:** independently repeatable improvements, zero known correctness regressions, and no claims based on smoke tests or combined partial runs.

## 8. Kill and pivot criteria

These are proposed research decisions, **not** observed failures.

- **Controller too weak:** if 100–150M models cannot achieve exact-slot/OOS gates despite constrained DSL and domain schemas, use them only for routing or discard that size class. Test 300–600M without pretending parameter count alone guarantees quality.
- **Capability routing collapses:** if top-K recall degrades badly at 500–1,000 packs, replace lexical-only routing with a hierarchical deterministic index plus small classifier; do not simply raise K until prompts become unbounded.
- **No net necessity benefit:** if repeated, representative workloads show CNE overhead exceeds saved execution cost after a reasonable amortization horizon, add stronger bypass heuristics or narrow CNE's claimed target workload.
- **Durable state too risky:** if crash/concurrency/encryption tests cannot achieve zero wrong reuse, disable L3 persistence and keep ephemeral conservative recomputation.
- **Unsafe continual learning:** if verified corrections/adapters produce material regressions or privacy leakage, freeze weights and retain only audited deterministic corrections.
- **Mobile envelope fails:** if a 6 GB CPU-only reference device cannot meet the measured memory/latency/thermal envelope, narrow supported tasks/models or revise the deployment claim. Do not relabel desktop RSS as Android PSS.
- **Third-party sandbox absent:** do not ship third-party executable packs on Android until OS-enforced isolation exists. Built-in trusted packs are a separate, narrower claim.
- **Contract semantics too broad:** if general semantic equivalence is undecidable or too expensive for a task, use strict domain contracts and conservative full execution rather than approximate “verified” reuse.

## 9. Clear final status statement for the project

**What we have achieved:** a functioning computation-necessity research core, real semantic DAG execution, signatures/contracts/state reuse, deterministic capability packs, an increasingly substantial local-first platform layer, desktop CPU GGUF inference smoke, signed package and scoped-permission mechanisms, persistent SQLite repositories, narrow verified correction learning, and initial CI automation.

**What we have not achieved:** a clean passing CI result for the latest commit; a quality-qualified compact semantic controller; reliable runtime-controller end-to-end execution with hashed model identities; complete encrypted state invalidation; contract-correct multi-domain composition; proven safe continual learning; scalable 1,000-pack routing recall; robust multi-user deletion; third-party Android sandboxing; measured 6 GB Android CPU-only performance; or a new 600-query blind benchmark result.

**Recommended next action:** repair the **six P0 findings first**, then establish a clean, single-run CI baseline. This is a better use of time than adding another model, capability pack, or agent-memory feature to a pipeline that can currently fail during test collection and after successful execution.

---

## 10. Source pointers and audit trail

- Reviewed commit: https://github.com/PrivateAccount-01/CNE/commit/f14493eab9023e71264b370c5385322fa4d7a154
- Failed CI run: https://github.com/PrivateAccount-01/CNE/actions/runs/37963846298
- `.github/workflows/ci.yml`
- `cne/platform/runtime_config.py`
- `cne/platform/state_repository.py`
- `cne/platform/storage.py`
- `cne/platform/bridge.py`
- `cne/platform/execution.py`
- `cne/platform/versions.py`
- `cne/platform/prompting.py`
- `cne/platform/controller_view.py`
- `cne/platform/correction_review.py`
- `cne/platform/memory.py`
- `cne/platform/models.py`
- `cne/platform/learning.py`
- `cne/platform/registry.py`
- `cne/platform/security.py`
- `cne/platform/sandbox.py`
- `cne/platform/external_data.py`
- `cne/platform/tournament.py`
- `cne/platform/benchmark.py`
- `cne/platform/dsl.py`
- `cne/platform/evidence.py`
- `cne/tests/platform/test_correction_learning_loop.py`
- `cne/tests/platform/test_review_hardening.py`
- `cne/tests/platform/test_persistent_cne_state.py`
- `cne/artifacts/platform_hardening_report.json` (historical, not current-SHA CI evidence)
- `cne/artifacts/real_runtime_validation.json` (desktop smoke)
- `cne/artifacts/adapter_training_validation.json` (one-example smoke)
- `docs/PLATFORM_MASTER_SPEC.md`
- `docs/EVALUATION_GATES.md`
- `docs/ANDROID_CPU_BASELINE.md`

**Audit limitations:** The review inspected repository source, commit metadata, test definitions, documentation, and GitHub Actions logs. No local checkout, mutation testing, licensed model inference, Android device run, or independent execution of new regression tests was available during this review. Source-derived failures are labeled accordingly. All recommended numeric gates beyond previously documented thresholds are **proposals**, not measured outcomes.
