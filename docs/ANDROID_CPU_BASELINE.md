# Android CPU Reference Baseline & Device Validation

## Current implementation evidence (2026-10-06)

Implementation status: NOT_IMPLEMENTED Android deployment; HARDWARE_NOT_MEASURED for all Android resource/performance claims. The profile and test battery below are targets only. Desktop Python tests do not demonstrate Android P13 readiness.

---

## 1. Reference Device Profile

- **Target OS:** Android 13+ (API level 33+)
- **CPU Architecture:** ARM64-v8a / ARM64-v9a (e.g. 4x Cortex-A78 + 4x Cortex-A55, or modern equivalent)
- **RAM:** 6 GB physical RAM
- **Storage:** UFS 2.2 / 3.1 flash storage
- **Mandatory Substrate:** CPU only. NPU (NNAPI / QNN) and GPU (Vulkan) are optional secondary comparisons.

---

## 2. Memory Profiling & PSS Measurement

On Android, Proportional Set Size (PSS) is the authoritative measure of memory consumption because it accurately apportions shared system libraries.

### Target Metrics
- **Peak Process PSS:** $\le 1536$ MB ($1.5$ GB).
- **Steady Active Runtime PSS:** $\le 1024$ MB ($1.0$ GB).
- **Core Engine Framework Overhead:** $\le 150$ MB.
- **Model File Storage:** $\le 500$ MB (using 4-bit / 3-bit GGUF quantization).

---

## 3. Required Test Battery on Reference Device

The Android baseline test suite exercises:
1. **Cold Start:** Engine initialization, manifest loading, L1/L3 store verification.
2. **Warm Start:** Subsequent query processing with cached model weights.
3. **Repeated Sessions:** 20 consecutive sessions testing for memory leaks or transcript inflation.
4. **Model Eviction Under Pressure:** Triggering a high-memory capability load and verifying automatic unloading of idle models.
5. **Capability Switching:** Transitioning from `finance.personal_budget` to `agriculture.crop_disease` without process restart.
6. **Background / Foreground Transitions:** Android OS lifecycle resilience under low-memory killer (LMK) signals.
7. **100% Offline Integrity:** Airplane mode verification ensuring zero socket connections for offline capabilities.
