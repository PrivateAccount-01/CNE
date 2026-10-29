# Actual local model run — 2026-10-30

**Desktop CPU model: trained and executed. Full Android product: NOT COMPLETE.** This report supersedes the earlier script-only status for desktop inference. No push, merge or publication occurred. HEAD `440f5e9c16e2d08b815e81604e46f7821dc1dba2`, branch `feature/cne-field-analyst`. Existing CNE core and project configuration are preserved.

## Data that actually downloaded

PlantVillage pinned revision `9e97599868962bd0079b8db4b7f1efa9185fa1e7` archive is local at `field_analyst/data/data.zip`: **2,184,723,441 bytes**. SHA-256 `fba30c6a7965e49be94b47a62f8aff6cfb1c35c27f475f22092b56db41745e84`, verified against upstream. Archive has 163,034 members and no included README/license file; source-card license declaration and uncertainty are retained in provenance. Download took 739.2 seconds in the successful bounded parallel/resumed run.

All 6,627 four-class color source images were extracted and hashed. **5,025 images** remain in the verified-leaf cohort; **1,602 are quarantined**, including original missing leaf identities and all affected groups from unresolved cross-group exact/near candidates. Candidate screen found 31 pairs. Entire original selected-class official test inventory remains preserved unchanged in `data/cohort-v1/official-inventory.json`; exclusions are explicit in `quarantine.json`. No fallback leaf IDs were invented and no class was silently dropped. Human/source-backed within-leaf resolutions and conservative cross-leaf quarantine precede model metrics.

The audit passed **for this restricted verified cohort only**, not the complete official benchmark. Original physical-leaf groups never cross active partitions. Source-metadata filtering narrows capture distribution and can make this subset easier than the full source. Counts: train **3183**, validation **795**, held-out verified test subset **1047**. Full source test remains unqualified where grouping is missing. Real training used no synthetic images and no field images.

Manifest SHA-256: `93c7775c3d1df5b26049a558c8e8012a354b246d4453e7d8a47c79a0dae10541`. Metadata: `c176481044f63434c2bfbe52899eeb16f455d03c74fb25f11d226a71f2e888ad`. Curation resolutions: `fc7eb912fb8c36ffbdd49407f8df965048f22e5db25114e637e86f41b03c82d5`. Exact counts and leaves per label/split: `reports/cohort-audit.json`. The broken documented Hugging Face loader remains recorded; this run used the checksum-verified archive and pinned source lists/map directly. A Hugging Face loader fingerprint is unavailable; archive and immutable manifest hashes identify the actual data.

## Training that actually ran

MobileNetV3 Small, ImageNet V1 initialization; convolution features frozen, four-class classifier actually optimized using labeled real images. Eight total epochs (3-epoch smoke + epoch-consistent resume to 8), seed 42, AdamW learning rate .0003, batch 16, four CPU threads, Python/PyTorch/torchvision versions bound in checkpoint lineage. CUDA unavailable; no GPU training claim. Total recorded epoch computation/validation time: **280.9 seconds** (not total development/download wall time). 1,521,956 total model parameters. Best checkpoint and all confidence thresholds were selected on validation only; official-subset and provisional external evaluations happened afterward.

Pretrained hash: `047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`; final selected checkpoint hash: `a5bd693c5b106e8312256a8b10dd006c6e1472dbe4ecddbdd5d401f402a2d6f3`. Full epoch losses/validation confusion matrices and metrics: `runs/real-cpu/training.json`; smoke and resumed commands/output: `reports/real-pipeline.log`, `reports/real-full.log`. Model initialization alone was never presented as tomato training.

## Size and validation comparison

All three candidates used the same locked 795 validation images and preprocessing. The full QDQ INT8 candidate was calibrated using 128 fixed **training-only** images (32 per class); it failed the quality gate and was rejected. A classifier-only dynamic INT8 fallback was then evaluated on validation before any held-out or external results; its convolutions remain FP32 and activation ranges are computed at inference. Full-candidate calibration provenance is `runs/onnx/calibration.json`. Preregistered storage selection: prefer INT8 only if macro F1 drop <= .02 and every class recall drop <= .05, otherwise FP32. Selection: **HEAD_INT8**. Best checkpoint: epoch **7** of the eight-epoch run.

| Format | Model bytes | Validation macro F1 | P50 preprocess+inference ms |
|---|---:|---:|---:|
| fp32 | 6,097,436 | 0.9656 | 12.49 |
| int8 | 1,847,079 | 0.1251 | 7.46 |
| head_int8 | 4,333,541 | 0.9639 | 12.63 |

FP32 preprocessing maximum absolute difference from torchvision: 0; maximum FP32 ONNX/PyTorch logit difference on 32 locked validation references: 2.3841858e-05. Export numeric gate was registered before metrics. FP32/full-QDQ-INT8 rank agreement (the rejected candidate): 0.2289. Per-class degradation and largest logit discrepancy examples are retained in `runs/onnx/comparison.json`; no claim that a quantized logit matches FP32 exactly. No global smallest-architecture claim: this is the smaller acceptable measured export of the specified small architecture.

## Held-out evidence

Restricted verified-leaf official-test subset, **n=1047**: accuracy **0.9685**, macro F1 **0.9598**, ECE (15 bins) **0.0144**, multiclass Brier (sum over classes) **0.0423**. These are lab-source subset results, not the full official benchmark or farm diagnostic accuracy. The image-level Wilson interval is exploratory and not leaf-cluster adjusted.

| Label | Precision | Recall | F1 | Images |
|---|---:|---:|---:|---:|
| Tomato___healthy | 0.9739 | 1.0000 | 0.9868 | 224 |
| Tomato___Early_blight | 0.9789 | 0.8651 | 0.9185 | 215 |
| Tomato___Late_blight | 0.8906 | 0.9942 | 0.9396 | 172 |
| Tomato___Bacterial_spot | 0.9954 | 0.9931 | 0.9943 | 436 |

PlantDoc: separately downloaded/materialized 2,578 original image items; two decode/size rejections were logged. Directory mapping was frozen before metrics, with no invented healthy class. Cross-source SHA256/dHash screening against all 6,627 used PV source images (including quarantines) excludes unresolved candidates. Other PV categories were not used for training and were not screened. Original-image grouping, item rights and field representativeness remain **UNVERIFIED**, so external numbers below are provisional/insufficient evidence for general deployment.

Provisional matching-class PlantDoc evaluation: n=309, accuracy 0.47572815533980584, macro F1 0.32230048211485923. No mapped healthy support. Fixed 128-or-fewer unsupported PlantDoc examples: n=128, false-accept rate at the validation-derived score threshold **1.0**. This is a measured limitation, not reliable unknown detection. Blur and multiple-leaf support remain NOT_VALIDATED. No external image influenced training, threshold or format selection. Full confusion matrices, sample lists and source provenance are in `reports/local-real-proof.json`.

## Actual local CPU execution

Selected model: `runs/onnx/head_int8.onnx`, **4,333,541 bytes**; SHA-256 `1798ca38ffcf388baee5e2c4c5eeab162ad475fdf7aeffdc63b7f5a4928e2582`. Runtime ONNX Runtime 1.20.1, CPUExecutionProvider only, one intra/inter-op thread, sequential deterministic-compute option. **PyTorch imported in inference process: False**. No HTTP service/cloud API is used for inference; installed assets and records are local.

New-session load time (single observation; OS cache uncontrolled): **264.77 ms**. Across 1047 locked subset test images, preprocess+inference P50/P95: **9.72/12.77 ms**. Whole verification process RSS at observation: **113.4 MiB**; OS peak working set **326.0 MiB**. These are this Windows computer's measurements, not Android or isolated model-only memory. Runtime-only requirements exclude torch/torchvision/datasets; the development environment retains them for training.

The actual existing `ComputationNecessityEngine` executed Observe/Call/Emit for real images, not a separate answer cache. Four real observation cases verified repeated logits, note-only behavior, baseline parity and record durability after reopening SQLite. Actual-model tampering was rejected before invocation. Twenty warm paired baseline/CNE trials with alternating execution order recorded median net savings **-0.488 ms**, negative-savings fraction **75.00%**. Native reuse remains conservatively disabled by Nondeterministic/ReadExternal effects; no savings claim is fabricated. This path executes real CNE but does not yet optimize model invocations. Deterministic core reuse/invalidation has separate unit evidence.

Desktop Tk interface: actual selected model loaded, actual image preview rendered, real inference result and all four ranked labels rendered in functional test. Status: `FUNCTIONAL_TK_TEST_PASSED_WITH_REAL_MODEL`. Visual/accessibility/manual UX review remains NOT_TESTED. User can import local photos, retain observations/notes, view history and CNE trace. Model scores are not calibrated diagnosis probabilities; healthy is not proof of plant health. Source/preprocessing/model identities are integrity checked.

## Commands

From repository root, launch installed local interface:

```powershell
./field_analyst/.venv/Scripts/python.exe -m field_analyst.app
```

Re-run local evaluation/integration to a fresh evidence file (keeps model and threshold frozen):

```powershell
./field_analyst/.venv/Scripts/python.exe -m field_analyst.local_validation --out field_analyst/reports/local-real-proof-rerun.json
./field_analyst/.venv/Scripts/python.exe -m field_analyst.gui_validation
```

Implemented reproducible stages, also usable in POSIX shells with the corresponding environment Python:

```sh
python -m field_analyst.download
python -m field_analyst.cohort
python -m field_analyst.train train --root field_analyst/data --manifest field_analyst/data/cohort-v1/manifest.csv --metadata field_analyst/data/cohort-v1/metadata.json --resolutions field_analyst/data/cohort-v1/resolutions.json --out field_analyst/runs/new-real-run --epochs 8 --batch-size 16 --device cpu --freeze-features --threads 4
python -m field_analyst.export_onnx --checkpoint field_analyst/runs/new-real-run/best.pt --root field_analyst/data --manifest field_analyst/data/cohort-v1/manifest.csv --metadata field_analyst/data/cohort-v1/metadata.json --resolutions field_analyst/data/cohort-v1/resolutions.json --out field_analyst/runs/new-onnx-export
```

Export requires the local development environment with onnx/onnxruntime installed. Immutable manifest/export directories must be new, or have identical source content. Epoch checkpoints support `--resume <last.pt>` with unchanged configuration/lineage. Read logs as UTF-16 when Windows PowerShell redirects them; Python-produced JSON is UTF-8. A log encoding issue delayed stage continuation and was corrected, with no retraining/test leakage. The archive downloader retried actual network timeouts and verified final SHA-256.

## Remaining acceptance gaps

**Android inference/APK integration is still BLOCKED/NOT_IMPLEMENTED**, despite real desktop success. The prior signed records-only APK contains no inference runtime/model/CNE bridge; do not present it as a working inference APK. No device was connected; Android install/launch, ABI compatibility, PSS, thermal, battery and cold/warm timing are NOT_TESTED/NOT_MEASURED. The bridge design remains separate work. The desktop runtime does not establish mobile compatibility.

Full-source grouping certification, broad field/OOD reliability, blur/multiple-leaf validation, source-item redistribution rights, production model signing, and native CNE reuse qualification remain incomplete. Data, weights and development outputs are ignored locally in Git. SHA-256 records are integrity evidence, not model attestation signatures. Test results and source checks are in `reports/tests.txt` and `reports/cne-tests.txt`; the optional real GGUF test was skipped because no asset was configured.

## Minimal deployed-model process

A separate fresh Python process loaded `deploy/model.onnx` and performed 21 actual CNE/model calls on one fixed real validation image, without any training imports or dataset audit. RSS after inference: **74.7 MiB**; OS peak working set: **79.6 MiB**. PyTorch imported: **False**. New-session load 238.80 ms; first CNE analysis 36.63 ms; warm CNE P50/P95 over n=20 repeats 14.52/15.49 ms. These include image validation, model integrity checks, preprocessing, actual CNE and inference. OS file-cache state was uncontrolled; no Android/cold-process percentile claim. The inference runtime does not require the training dataset. See `reports/lean-runtime-proof.json`.
