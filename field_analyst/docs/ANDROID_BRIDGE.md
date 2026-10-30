# Proposed Android bridge to authoritative CNE

Status: **DESIGN ONLY / BLOCKED / NOT_TESTED**. The records APK deliberately contains neither CNE nor inference and exposes no enabled analysis action.

A concrete integration path is embedded CPython, which is the Android execution mode documented by [Python](https://docs.python.org/3/using/android.html). Package a pinned Android `libpython` build and standard library privately in the APK, load it through JNI, and package the unmodified repository CNE modules. Run its actual `ComputationNecessityEngine.execute_query` on a serialized worker thread; Java receives results and execution traces. Do not implement a second cache or rewrite graph decisions in Java.

The proposed model runtime is the CPU-only Android ONNX Runtime artifact, invoked from the existing generic Call primitive through a small synchronous JNI callable. The official [ONNX Runtime Android build documentation](https://onnxruntime.ai/docs/build/android.html) is the source to verify supported versions/ABIs when this bridge is built. This requires a real trained checkpoint, verified ONNX conversion, pinned runtime libraries, preprocessing implementation and provenance/license manifests. The current desktop TorchScript export is not evidence of ONNX conversion or mobile compatibility. No embedded interpreter/runtime binaries or JNI bridge have been integrated in this increment.

Bridge boundary:

1. Android copies the selected immutable photo bytes into a bounded request, verifies asset hashes and includes preprocessing, label order, runtime/version/ABI/thread configuration and output-contract identities.
2. Embedded Python builds Observe(image hex), Observe(asset identity), Call(cpu inference), Emit using existing primitives. The call declares ReadExternal plus Nondeterministic until that exact runtime/configuration has deterministic conformance evidence. No policy override, third-party pack code or network service is allowed.
3. The Call receives verified bytes and identity, executes preprocessing plus ONNX CPU inference in the same process, and returns four finite logits in frozen label order. SQLite writes and notes occur outside the inference graph. Asset changes are verified before every query, including a possible reuse hit.
4. CPython returns logits, invocation count, memo key, effects, dependency identities, costs and contract result. UI shows model scores and validated abstention metadata only when bound to that model hash. Contract satisfaction establishes no biological diagnosis.

Proposed conformance gates, preregistered before any mobile metrics:

- Desktop/Android execute identical canonical requests for cold, repeated, image-byte mutation, model mutation, preprocessing/label/runtime change and note-only cases. Compare graph/signature/dependency/effect traces, invocation counts, planner target and verifier outcomes. Copy the core test cases into instrumented bridge tests; do not use blind controller corpora.
- Same pinned real corpus: compare decoded/oriented RGB, normalized NCHW tensors and logits. Proposed initial numeric tolerance is absolute/relative 1e-5; justify any change before seeing final test results. Require label-order/rank agreement and report all discrepancy inputs plus per-class quality changes. Validate quantization separately; no winner yet.
- Tampered model/manifest/preprocessing/runtime fails before CNE memo lookup. Unknown/blur/multiple-leaf inputs come from distinct reviewed sources; score-based acceptance remains unqualified until measured.
- Process termination restores records; recomputation is allowed. If durable CNE state is added, use the actual core state repository and test integrity, versions, dependency invalidation and crash recovery; do not persist an independent answer cache.
- APK inspection must show interpreter, actual CNE source, inference runtime and model; verify all hashes, licenses and zero INTERNET permission. Confirm CPU provider on the actual ABI/device. Benchmark baseline and CNE on the same runtime with cold-load and warm trials, including low-benefit/negative savings. Resource/thermal/battery claims require physical measurements.

Blockers are substantive implementation work: trustworthy complete dataset groups and audited training; ONNX export/parity; embedded Python and JNI packaging; Android preprocessing conformance; device installation and measurements. A successful records APK build closes none of these inference gates.
