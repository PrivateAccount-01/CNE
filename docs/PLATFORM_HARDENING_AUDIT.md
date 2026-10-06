# Platform hardening audit

Baseline: `b5fd5b3765131a6387662f8d8e3a6a240624afc4`. Classification describes inspected implementation, not architectural intent. The original platform tests often assert the same unsafe assumptions as the implementation.

| Subsystem | Classification | Current implementation / unsafe assumption | Missing behavior / required change | Baseline coverage |
|---|---|---|---|---|
| Registry permissions | PARTIAL | Requested permissions automatically granted, including rollback | Explicit scoped authority, expiry, default deny and enforcement | Tests expect automatic grants |
| Package integrity | UNIMPLEMENTED | Hash metadata only | Verify canonical manifest, assets and signatures before activation | Manifest construction only |
| Dependencies | UNIMPLEMENTED | Required capabilities ignored | Version checks, cycles, model assets and backends | None |
| Execution versions | PARTIAL | MemoKey accepts version fields; registry hashes every enabled pack | Select participating execution dependencies | Only manually changed hashes |
| DSL | PARTIAL | Assignment IDs discarded; implicit chain, heuristic types, unknown attributes ignored | Explicit DAG references, typed schemas and lazy regions | Linear pipeline only |
| Resolver | PARTIAL | Domain substring routing | Schema matching, multiple capabilities, permissions | Minimal |
| Controller bridge | SIMULATED | Default expense intent, generic graph and fabricated confidence | Registry-owned mappings or actual model; explicit decline | Asserts fabricated graph exists |
| Session memory | PARTIAL | In-memory dictionary with no owner check | Scoped persistent repositories | Distinct session IDs only |
| Plan cache | STUB | Shape to DSL dictionary | Metadata, scope and fresh slot binding | None |
| Correction audit | PARTIAL | Feedback marked verified; process hash and raw query | Unverified default, stable digest, redaction, scoped retrieval | Assumes feedback is truth |
| Replay / adaptation | SIMULATED | Arbitrary experience admitted; caller-supplied scores; dictionary activation | Admission governance, executed evaluation and transactional deployment | Caller supplies passing metrics |
| Model runtime | UNIMPLEMENTED | Abstract interface | Actual local backend, asset prerequisites and measurements | None |
| Residency | STUB | Records estimates and selects IDs without runtime calls | Actual load/unload, ownership and measured memory | Accounting only |
| Benchmark | SIMULATED | TTFT fraction, fixed ambiguity and descriptor RAM | Independent labels, counts, unavailable metrics explicit | Fabricated inference callbacks |
| Agriculture CV | SIMULATED | Byte modulo classification with artificial confidence | Remove classifier or integrate validated model | Synthetic bytes |
| Agriculture knowledge | PARTIAL | Unattributed treatment dictionary | Provenance and unverified designation | Lookup only |
| Finance | PARTIAL | Real arithmetic, permissive transaction coercion | Typed transactions and explicit comparison semantics | Small deterministic example |
| Travel | SIMULATED | Network flag means live; nonexistent cache verification | Actual freshness records and TTL | Asserts network flag implies live |
| Device / budget | PARTIAL | Actual RSS; mislabeled PSS, assumed quantization and thermal state | Unknown states and detailed budget decisions | Snapshot only |
| Telemetry | PARTIAL | Records supplied numbers; defaults imply measured success | Nullable measurements, provenance and complete timings | Aggregation only |
| CNE integration | PARTIAL | Real DSL-to-CNE execution and reuse | Natural-language scoped composed execution | Desktop test mislabeled P13 |
| OS sandbox / Android / RL | UNIMPLEMENTED | Specifications only | No deployment or performance claims; no RL in this phase | No hardware evidence |

The existing Semantic IR, contracts, optimizer, execution, verifier and invalidation remain authoritative. No blind-corpus data is to be edited or used for training. Every platform mutation must notify `LocalStateFabric.notify_data_mutation()` before reuse is possible.

Implementation evidence and remaining limitations are tracked in `cne/artifacts/platform_hardening_report.json`. Passing desktop tests do not establish model quality, Android readiness, or an OS sandbox.

## Post-hardening evidence and limits

The baseline classification above is retained as an audit trail. Current behavior:

| Area | Current status | Evidence / remaining limit |
|---|---|---|
| Permission authority and broker | IMPLEMENTED application boundary | Durable grants and bearer identities; real Windows-to-WSL restricted worker denies host files and network |
| Package/dependency validation | IMPLEMENTED local lifecycle | Canonical hashes, Ed25519 trust/revocation, verified archive staging, durable registry, exact dependency versions |
| Execution versions | IMPLEMENTED for wired deterministic/runtime-controller paths | Selected pack projection, used tools, model version; unused tools/packs preserve keys |
| DAG compiler | IMPLEMENTED supported schemas | Explicit edges, cycles, types, lazy Branch, Iterate, Choose, Join and nested-region tests |
| Controller | PARTIAL | Registry-owned full grammar matches or optional actual model runtime; model quality NOT_TESTED |
| Sessions/corrections/experiences | IMPLEMENTED SQLite repositories | Restart, owner mismatch and unverified-feedback tests; no universal PII detector |
| Plan cache | IMPLEMENTED declared mappings | Declared-grammar controller reuses templates with fresh typed slots; user-scoped native KV reset |
| Replay/evaluation | PARTIAL | Admission, retention, deduplication, scoped sampling and five-set evaluation; real supervised LoRA smoke passed |
| Adapter activation | IMPLEMENTED GGUF LoRA | Verified GGUF staging, real live attachment, durable pointer recovery and regression-triggered rollback |
| Benchmark | IMPLEMENTED accounting | Independent labels/counts, first-token runtime evidence, sampled process memory; real model tournament NOT_TESTED |
| Runtime/residency | IMPLEMENTED CPU GGUF | Actual SmolLM2 CPU inference, residency load/eviction/reload and scope-reset probes passed |
| Agriculture | STUB | Byte-modulo classifier removed; treatment knowledge unavailable rather than falsely verified |
| Finance/travel | PARTIAL | Strict deterministic finance; generic permission-checked HTTP JSON connector; travel needs a configured data provider |
| Device/telemetry | PARTIAL | Observed RSS/PSS or null, unknown thermal state, explicit measurements; continuous budget guarantees absent |
| CNE integration | IMPLEMENTED tested paths | Real NL finance result, composed join, selective cache and multi-user adversarial checks |

Implementation and smoke evidence now cover local signing/install lifecycle, sandbox transport, supervised adapter generation and live activation. Broad controller benchmarking and comprehensive runtime resource validation remain unevaluated. The allowed agriculture stub remains explicit. No RL or Android performance claim is introduced. The only core semantic change fixes stale loop-region values; all other core subsystems remain unchanged.

Final follow-up validation: 97 platform tests passed with real GGUF inference enabled. The initial full run had 345 passes and two frozen timing-gate failures (G6/G7); both passed on isolated rerun without threshold changes. Combining the latest results covers 350 unique tests, including the 253 preserved non-platform tests. This is a combined result, not a claim that the initial full run was entirely green. The original failure artifact and recheck are both retained.

Additional real probes passed for frozen-base supervised LoRA updates, GGUF adapter export/attachment, preservation of the previous live model after a failed activation commit, base-model restoration, residency eviction/reload and Windows-to-WSL sandbox isolation. The blind corpus remains byte-equivalent after newline normalization and was not used for training.
