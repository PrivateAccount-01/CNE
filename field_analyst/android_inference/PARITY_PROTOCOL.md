# Android parity protocol v1

Registered before executing this Android implementation. No Android parity result is claimed by this document.

Use three lexicographically first entries of the existing verified cohort's **validation** split, sorted by SHA-256. These are already observed validation images: integration checks only, never new blind quality evidence. Preserve their original bytes and label order. Select no reference image by its model score or Android result.

Reference: existing head-only INT8 ONNX artifact SHA-256 `1798ca38ffcf388baee5e2c4c5eeab162ad475fdf7aeffdc63b7f5a4928e2582`; desktop ONNX Runtime 1.20.1 CPU, sequential, one intra/inter thread, deterministic compute. Save source identity, original image hash, normalized little-endian float32 NCHW tensor, raw logits and versions before Android execution.

Android candidate: embedded Chaquopy 16.1.0 / CPython 3.11, NumPy 1.26.2, Pillow 11.0.0, ONNX Runtime Android 1.20.0, CPU only, sequential one thread. Different NumPy/Pillow versions are explicitly a parity risk, not presumed equivalent.

Gates, fixed before results: tensor shape `[1,3,224,224]`; tensor elementwise absolute error <= `1e-6` and relative error <= `1e-5` using the usual atol + rtol * abs(reference) rule; logits atol/rtol `1e-5`; exact ordered labels, rank order, input/model identity and contract satisfaction. Compare direct native recomputation versus actual CNE on each same-device input. Every native call must execute and reuse must remain false. Missing, nonfinite, wrong-size or mismatched reference data fails. Any discrepancy is retained and investigated; do not increase tolerances after observing results.

Warm/cold timing samples from these correctness checks are diagnostic only. A later benchmark must alternate path order, record raw trials, cold load separately, warmups, quantiles, full integrity/control costs and negative savings. Phone RAM/PSS, energy, thermals and responsiveness require a connected physical device; an emulator cannot establish those claims.

Pre-execution correction: the initial requested Android Maven coordinate 1.20.1 does not exist. Gradle v2 failed dependency resolution. Maven Central metadata lists 1.20.0 then 1.21.0. Android is pinned to 1.20.0; desktop remains 1.20.1 and its original model manifest is preserved. This additional runtime-version difference is part of the measured parity risk. No Android result was seen and no tolerance was changed. Primary metadata: https://repo.maven.apache.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/maven-metadata.xml .
