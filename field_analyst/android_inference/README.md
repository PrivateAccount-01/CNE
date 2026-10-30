# Embedded CPU inference implementation

This is a separate package, `org.cne.fieldanalyst.inference`, from the historical records-only shell. Build/device/parity evidence is separate. Implementation alone is not a verified phone product.

Architecture: Chaquopy 16.1.0 embeds CPython 3.11, the actual repository CNE modules and `FieldEngine`. The generic CALL invokes a small Java ONNX Runtime **1.20.0** CPU adapter. Original desktop ONNX Runtime is **1.20.1**; Android Maven has no 1.20.1 artifact. Original trained model/manifest/threshold bytes are preserved. NumPy 1.26.2 and Pillow 11.0.0 are available Android wheels; their difference from desktop must pass the fixed [parity protocol](PARITY_PROTOCOL.md). Native reuse remains disabled, and every invocation verifies assets and embedded source hashes. This can be expensive; no savings claim is made.

The app offers camera/picker, plant observations, app-private images, notes/history, ranked outputs and real CNE traces. All results abstain from supported-input decisions. Image storage is limited to 256 MiB, individual inputs to 32 MiB/25 million pixels, and history renders the latest 20 records to bound preview memory. Images use private files rather than large SQLite BLOB cursor windows. A single process worker keeps inference off the Activity thread. Process death permits recomputation; saved records persist. Remaining lifecycle/permission/upgrade/accessibility behavior requires executed device tests.

From the repository, with the existing verified local deployment model and Android SDK platform 35:

```powershell
python -m field_analyst.android_inference.prepare_references
python -m field_analyst.android_inference.build --abi arm64-v8a --build-python <Python-3.11.exe>
python -m field_analyst.android_inference.build --abi x86_64 --build-python <Python-3.11.exe> --with-parity-tests
```

Reference preparation needs the lightweight desktop runtime environment plus existing validation images. Building needs host Python 3.11, JDK 17+ and the SDK. The helper downloads Gradle 8.9 only if absent and checks its recorded SHA-256 before execution, uses a short temporary staging path, records dependency verification metadata and source identities, copies APKs and writes a fail-closed report/log under ignored `artifacts/android-inference/`. Debug keys stay outside Git. No model substitute or fake weights are downloaded. Test references are in the **test APK**, not the user APK.

Install both debug APKs on an x86_64 emulator, then run:

```text
adb shell am instrument -w org.cne.fieldanalyst.inference.test/androidx.test.runner.AndroidJUnitRunner
```

This must actually execute successfully before claiming parity. Phone runs require the arm64-v8a build and a connected compatible device. Inspect APK manifest (zero INTERNET permission), ABI, signed certificate, actual CNE/model/runtime contents and hashes. Device PSS, thermal/energy and real ARM performance remain NOT_MEASURED until collected.

Primary compatibility/API sources: [Chaquopy versions](https://chaquo.com/chaquopy/doc/current/versions.html), [packaging and Python dependencies](https://chaquo.com/chaquopy/doc/current/android.html), [Java/Python conversion](https://chaquo.com/chaquopy/doc/current/python.html), [ONNX Runtime Java](https://onnxruntime.ai/docs/get-started/with-java.html), [Android Maven releases](https://repo.maven.apache.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/maven-metadata.xml). Preserve upstream license/notices in addition to this project's NOTICE.
