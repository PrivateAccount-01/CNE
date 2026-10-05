# CNE Resource & Runtime Specification

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
