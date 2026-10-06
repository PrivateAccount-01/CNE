# CNE Resource & Runtime Specification

## Current implementation evidence (2026-10-06)

Implementation status: PARTIAL. Android validation is HARDWARE_NOT_MEASURED.

LlamaCppRuntimeAdapter invokes optional llama-cpp-python directly on CPU GGUF assets. Missing package/assets fail explicitly. It yields actual token IDs, counts generated tokens and timestamps the first token; inference timeout is cooperative between generated tokens. API reference: https://llama-cpp-python.readthedocs.io/en/latest/api-reference/ . No model asset is bundled. Local SmolLM2-135M Q4_K_M CPU inference has been executed; source revision and SHA-256 are recorded in validation artifacts. This is a runtime smoke test, not controller selection.

RuntimeSemanticController optionally shares a residency manager and releases request ownership after inference. Residency manager invokes load/unload, prevents eviction of pinned/owned entries, and records RSS load deltas and latency. RSS deltas are process observations, not isolated model allocations, and memory mapping/allocators can delay release. Warm-load/reload distributions, preemptive OOM prevention and hard inference cancellation are PARTIAL. Eviction score is age * accounting_size / (max(reload_ms,1) * (access_count+1)); higher scores are evicted first.

DeviceProfile reports real RSS and optional real PSS; unavailable PSS stays null. Thermal state is UNKNOWN. CPU presence does not advertise int4/int8 acceleration. ResourceBudget.evaluate returns violations and observations for memory, requested storage and concurrency. Snapshot checks do not certify continuous peak/steady limits.

---

## 1. Primary Hardware Envelope

The reference deployment target is an Android-class commodity device:
- **Processor:** ARM64 CPU (mandatory baseline).
- **RAM:** 6 GB minimum system RAM.
- **Process Memory Limits:**
  - Peak process PSS target: $\le 1.5$ GB.
  - Preferred steady active runtime: $\le 1.0$ GB.
  - Base model storage target: $\le 500$ MB.
  - Core framework footprint: $\le 150$ MB (excluding models).
- **Accelerators:** GPU (Vulkan/OpenCL), NPU, and USB compute are optional accelerators. Absence of an accelerator must never compromise platform execution.

---

## 2. Model Residency Manager

The `ModelResidencyManager` dynamically balances active neural weights in RAM.

### State Tracking
For every loaded model, the manager maintains:
- `model_id`: Canonical asset identifier
- `version`: Asset version
- `backend`: Runtime backend (`CPU`, `GPU`, `NPU`)
- `memory_footprint_mb`: Resident memory in megabytes
- `load_latency_ms`: Measured cold load time
- `last_accessed`: Unix epoch of last inference
- `access_count`: Frequency of invocations
- `reload_penalty_ms`: Cost to re-read and map weights from flash storage
- `capability_dependencies`: Set of capability pack IDs relying on this model

### Eviction Policy
1. When a model load request causes projected resident memory to exceed the $1.0$ GB steady-state threshold, the residency manager invokes cost-aware LRU eviction:
   $$\text{EvictionScore}(m) = \frac{\text{time}() - \text{last\_accessed}(m)}{\text{reload\_penalty}(m) \times (\text{access\_count}(m) + 1)}$$
2. Models with the highest eviction score are unloaded first until resident memory falls below the safety budget.
3. The interface is pluggable to accommodate learned contextual bandit / RL scheduling policies in Phase P12.

## Reproducing local integration checks

Install the `platform`, `gguf` and (for training) `training` extras in an isolated environment. Supply a licensed GGUF file and its matching local Transformers base. Run:

```text
python -m cne.platform.validation --gguf MODEL.gguf --base-model BASE_DIRECTORY --output VALIDATION_DIRECTORY --sandbox
```

Omit `--base-model` to skip training. Linux requires `bubblewrap`; Windows requires WSL Ubuntu with Python 3 and bubblewrap. Unsupported sandbox hosts fail closed. The validation uses one public literal example, performs two adapter gradient updates, verifies frozen base weights, exports GGUF, attaches it and runs actual inference. It does not authorize production deployment or evaluate learning quality. On hosts with unrelated TensorFlow installations, `USE_TF=0` restricts Transformers to the tested PyTorch path.

The checked-in `real_runtime_validation.json`, `adapter_training_validation.json` and `sandbox_validation.json` artifacts record this checkout's observed results. Local dependencies and downloaded weights are excluded under `.dist/`.
