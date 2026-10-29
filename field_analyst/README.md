# CNE Field Analyst — actual local CPU model

**A real model has now been trained and run locally.** PlantVillage was downloaded, checksum-verified, and used for real eight-epoch CPU training. The desktop interface executes the actual CNE core and the selected local ONNX model; this is no longer a scripts-only increment.

**It is experimental and not reliable for field diagnosis. Android inference remains incomplete.**

## Run now

From the CNE repository root in PowerShell:

```powershell
.\field_analyst\.venv\Scripts\python.exe -m field_analyst.app
```

Create a plant, import a local leaf photo, click **Analyze locally**, and inspect ranked scores, history and the CNE trace. `run-local.ps1` is an optional launcher. No API key, server, paid service, GPU or inference-time download is required. The installed development environment remains local; PyTorch is not imported by the selected ONNX inference path.

The selected deployment files are:

- `deploy/model.onnx` — **4,333,541 bytes**; classifier layers dynamically INT8, convolutions FP32.
- `deploy/model.json` — model hash, labels, preprocessing, runtime and actual training lineage.
- `deploy/model-threshold.json` — validation-derived threshold, bound to the model hash. It is **not reliable unknown detection**.
- `deploy/deployment.json` — deployment scope and integrity record.

Model SHA-256: `1798ca38ffcf388baee5e2c4c5eeab162ad475fdf7aeffdc63b7f5a4928e2582`.

## What actually ran

- Downloaded the complete pinned PlantVillage archive: **2,184,723,441 bytes**, local `data/data.zip`; SHA-256 verified. Extracted all 6,627 images for the four requested tomato categories.
- Preserved the full official test inventory. Explicitly quarantined 1,602 images with unverified grouping or unresolved duplicate candidates. The audited verified cohort contains **3,183 train / 795 validation / 1,047 test** images. These are restricted-subset results, not a complete official benchmark certification.
- Trained MobileNetV3 Small's classifier on real labeled images for eight CPU epochs, with frozen ImageNet-initialized convolution features. Selected epoch 7 using validation only.
- Compared FP32, full static INT8, and classifier-only dynamic INT8. Full static INT8 failed quality validation and was rejected. The selected 4.33 MB format retained validation macro F1 **0.9639**, versus **0.9656** FP32.
- Executed real held-out inference, actual CNE/baseline parity and model-call traces, note changes, model-tampering refusal, SQLite restart checks, and a functional Tk interface test with real images/model outputs.

| Evaluation | Images | Accuracy | Important scope |
|---|---:|---:|---|
| Verified PlantVillage held-out subset | 1,047 | 96.85% | Lab-source subset; excludes unverified groups |
| Provisional PlantDoc field-like set | 309 | 47.57% | Grouping/item rights and representativeness unverified; no healthy mapping |
| Unsupported PlantDoc inputs | 128 | All 128 falsely accepted by score threshold | Unknown rejection is ineffective |

This evidence does **not** support reliable field diagnosis, severity, treatment, proof of plant health, or broad unknown/blur/multiple-leaf recognition. The interface shows the limitations. Scores are not calibrated diagnosis probabilities. Photo comparisons depend on capture conditions.

On this Windows computer, over 1,047 test images, preprocessing + inference P50/P95 was **9.72 / 12.77 ms**. These are desktop CPU results, not phone measurements. Separate minimal deployed-model process measurements are in `reports/lean-runtime-proof.json`. The actual CNE path currently recomputes native inference conservatively; reuse is disabled until qualified. Measured overhead/negative savings are reported, not concealed.

Read the [actual training/evaluation report](docs/LOCAL_MODEL_RUN.md) for exact commands, hashes, per-class metrics, calibration, quantization failure, memory, timings, sample sizes and remaining gaps. [Model card](docs/MODEL_CARD.md). The [earlier report](docs/IMPLEMENTATION_REPORT.md) is historical and describes the initial incomplete phase.

## Reproduce or resume

The existing `.venv` includes the installed ONNX exporter/runtime and uses the existing CPU torch environment for training. Runtime-only requirements are listed in `requirements-runtime.txt`; inference needs no torch, torchvision, datasets, training images or experiment logs. A fresh runtime environment has not been separately installed/tested; the present Windows environment and real inference are verified.

Implemented commands, from repository root:

```powershell
python -m field_analyst.download
python -m field_analyst.cohort
.\field_analyst\.venv\Scripts\python.exe -m pytest field_analyst/tests -q
.\field_analyst\.venv\Scripts\python.exe -m field_analyst.local_validation --out field_analyst/reports/local-real-proof-rerun.json
.\field_analyst\.venv\Scripts\python.exe -m field_analyst.gui_validation
.\field_analyst\.venv\Scripts\python.exe -m field_analyst.lean_probe
```

For a new training run, use a **new output folder**:

```powershell
python -m field_analyst.train train --root field_analyst/data --manifest field_analyst/data/cohort-v1/manifest.csv --metadata field_analyst/data/cohort-v1/metadata.json --resolutions field_analyst/data/cohort-v1/resolutions.json --out field_analyst/runs/new-real-run --epochs 8 --batch-size 16 --device cpu --freeze-features --threads 4
```

Resume completed epochs with the same arguments/configuration and `--resume field_analyst/runs/new-real-run/last.pt`. An interrupted epoch is replayed. Loading checkpoints uses trusted local PyTorch pickle; do not load untrusted downloaded checkpoints.

The strict full-source `sources prepare` still refuses missing leaf IDs. The new `cohort` command does not invent them: it certifies only mapped original leaf groups, retains all source files/inventory, and records exclusions. Do not describe its audit as certifying the whole dataset. Immutable outputs refuse differing content. Quantization and thresholds used validation/train only; the field/held-out sets were evaluated after format selection and must not be reused to tune this artifact.

PlantDoc's original Windows checkout failed on `?` filenames. `materialize_plantdoc` recovered the Git blobs under content-hash filenames while retaining original paths/labels/splits. The recovery, per-image decode and cross-source screening evidence is retained. Source licenses/attribution are recorded; source-item redistribution rights remain unverified. No data/model was published.

## Android status

The previous `android/build/cne-field-analyst-records-debug.apk` is **records-only**. It contains no inference model/runtime or actual Android CNE bridge. Desktop success does not make that APK an inference app. Embedded CNE, Android CPU inference/parity and actual device tests remain **BLOCKED / NOT_IMPLEMENTED / NOT_TESTED**. No phone RAM, thermal, battery, latency or compatibility claim is made. See [bridge design](docs/ANDROID_BRIDGE.md).

Data, weights, environments, deployment copies and build outputs remain ignored locally in Git. Branch: `feature/cne-field-analyst`; no existing core/configuration changes, commit, push, merge or publication.
