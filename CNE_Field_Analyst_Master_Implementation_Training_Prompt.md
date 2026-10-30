# CNE Field Analyst — Master Implementation and Training Prompt

**For:** coding agent operating in the user's existing local CNE Git repository  
**Purpose:** build a real, testable tomato-leaf analysis product for Android, backed by a trained computer-vision model and the actual Computation Necessity Engine (CNE).  
**Baseline:** inspect the current local repository; do not assume that a previous commit, feature or artifact is still current. Work in a new local feature branch if the worktree permits. Do not push, merge or publish without the user's instruction.

## Instructions to the coding agent

Work autonomously through the phases in this document. Produce working source, run relevant tests and actual experiments, and make failures visible. Do not stop after producing plans, mock interfaces, a fabricated model or a UI that bypasses CNE. If an external dependency, Android toolchain, dataset access or device is unavailable, complete independent work and report the exact blocker with the commands needed to resume. Never claim a capability, measurement, training run, model quality, Android build or hardware validation unless actually executed and recorded.

First run `git status --short --branch`, `git rev-parse HEAD`, inspect `AGENTS.md` and applicable instructions, then inspect `cne/packs/agriculture_cv/`, CNE semantic IR, contracts, effects, signatures, state fabric, invalidation, runtime cost gate, physical planner, execution and verification, platform model adapters, tests, Android baseline and latest audit. Summarize real/partial/stub status. Respect local uncommitted work. The previous assistant created a **local-only** initial increment (`dataset_audit.py`, `train.py`, tests and `docs/FIELD_ANALYST_BUILD.md`) and provided a ZIP; it is NOT known to be in the remote repository. If those files exist, inspect and improve rather than assume correctness. If absent, implement this specification directly. Never blindly replace the user's `pyproject.toml` with the ZIP copy.

## 1. Product and truthful scope

Build **CNE Field Analyst**, a local-first, experimental tomato-leaf investigation app. A user can create plant records, photograph or import photos, run image analysis, see ranked model outputs with explicit uncertainty, retain observations, compare previous observations, and view a diagnostic trace explaining executed/reused work. Support offline CPU inference and local storage; 8 GB RAM phone is the user's device, with 6–8 GB ARM CPU as design target, no required NPU/GPU/USB/cloud. Determine Android version and CPU ABI from the device or ask if deployment requires it. No claim of compatibility based solely on RAM/storage.

The model classifies images against supported labels; it does NOT establish a plant diagnosis, measure disease severity, or provide pesticide/treatment instructions. A generic `healthy` output is not proof of plant health. Avoid claims of causal changes over time; a photo-to-photo comparison is affected by lighting, view, leaf and capture conditions. Show this in the product. No internet is required once the APK and model are installed. Data and models may be downloaded on the development computer.

Start with four PlantVillage categories as candidates: `Tomato___healthy`, `Tomato___Early_blight`, `Tomato___Late_blight`, `Tomato___Bacterial_spot`. Inspect actual source schemas and counts first. Preserve the exact source-to-canonical mapping, report chosen classes and rejected classes, and adjust scope only if evidence makes a class unusable. Unsupported crops/conditions, multiple leaves, blur and unseen diseases must be included as negative/unknown evaluation examples. This is a proposed 4-class start, not a claim the model can safely recognize all other cases.

## 2. Sources, provenance and download

A. **PlantVillage**, primary training and in-domain evaluation: https://huggingface.co/datasets/mohanty/PlantVillage and https://github.com/spMohanty/PlantVillage-Dataset . The upstream dataset card currently lists CC BY-SA 3.0; retain attribution, exact license, revision and provenance and check the actual downloaded snapshot for any restrictions. Record the actual snapshot revision and dataset fingerprint. Its documentation describes an official group-preserving 80/20 train/test split and `leaf_id`; inspect the actual features and version on disk. Prefer the documented color images. Preserve official test untouched; split **only the official train set** into train and validation by leaf ID, stratifying at group level where feasible, seed 42. Validate groups never cross splits. Preserve exact official source test list; do not train, tune thresholds, select hyperparameters, or inspect samples adaptively based on test outcomes. If IDs are missing, fallback/generated identifiers are unreliable, or upstream loading fails, fail closed on the grouped-data claim and document; use the original repository's leaf grouping metadata only after validating its actual semantics. Do not fabricate `group_id` from filenames without proof.

Dataset card's documented loader:
```python
from datasets import load_dataset
pv = load_dataset('mohanty/PlantVillage', 'color')
print(pv)
print(pv['train'].features)
```
A dataset loader or configuration can change or be incompatible with the installed `datasets` version: check and report actual output/errors. Use a pinned snapshot and compatible loader or documented original source; no unverified assumption that this snippet works in every version. Verify whether rows are image bytes, paths, labels or text before adapting. Store data outside Git; never commit photos or whole datasets.

B. **PlantDoc cropped classification**, external field-like evaluation only initially: https://github.com/pratikkayal/PlantDoc-Dataset . Official README lists CC BY 4.0 and says images were collected from the internet; verify source-item rights, attribution and suitability for intended distribution. Clone into a data directory. Inspect actual directories, label definitions, counts, sources, original split and the image/leaf relationship; document known versus unknown grouping. Create a manually reviewed mapping for *genuinely matching* tomato classes; no invented healthy category or unmatched disease mapping. Deduplicate exact and near duplicates against all PlantVillage partitions; review possible overlaps, quarantining unresolved matches. Pre-register its role, mapping and filtering before looking at metrics. Use no field test images for training, augmentation, threshold selection or model selection. If the field benchmark is insufficient or unverified, label it accordingly, do not claim representativeness. For support/out-of-distribution testing, non-tomato/other conditions can be selected separately and labeled as unknown, preserving origin and grouping. Log counts by source and label.

C. **Pretrained model**, `torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1`: https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.mobilenet_v3_small.html . This is ImageNet initialization, not a tomato-trained model. Record source URL, revision/version, license, SHA-256 and preprocessing. Train/fine-tune on actual labeled tomato images. This work may download pretrained weights but must not require paid services. Optional larger/smaller candidates are allowed, but compare on quality, CPU timing, peak memory, storage and conversion success; do not claim a winner before evidence.

## 3. Implement auditable dataset preparation

Provide idempotent scripts/commands to download or point at sources, inspect schema and create local immutable manifests. CSV or equivalent contains `path,label,group_id,split,source,source_revision,sha256` with a separate metadata and rights file. Paths must stay within the dataset root, prevent symlink escape, detect corrupt images and decompression issues, validate RGB/EXIF handling, compute file hash and dimensions, detect duplicate paths, conflicting exact duplicates, cross-split exact duplicates and group overlap; group IDs include source namespace. Exact-match checks are insufficient: produce a near-duplicate candidate report, manually/explicitly resolve collisions and preserve proof of curation. In upstream fallback group cases, fail closed or clearly exclude those examples from group-certified claims. Do not silently discard or relabel samples.

Produce class-by-split image and unique-leaf counts, manifest and split hashes, seed, rejection reasons, source/rights records and a human-readable dataset card. Fail training on audit failures. Never use synthetic images to claim real quality. A synthetic fixture is permitted only for testing code and must be clearly labeled.

The previous `dataset_audit.py` prototype only detects exact-byte duplicates, and its group IDs are supplied by the user; it does not establish their correctness, detect near duplicates or determine rights. Review and strengthen it, do not treat PASS as proof of those things. Ensure train and validation have adequate representation for every trained class; explicitly report absent/low-support test classes.

## 4. Train and evaluate a real model

Create reproducible, resumable training and evaluation commands, with a CPU baseline and optional supported local GPU training. Device autodetection should be explicit; record actual device, Python/PyTorch/torchvision versions, dependency lock, config, seed, determinism limitations, pretrained weight and final model hashes. Never claim training on GPU if CPU was used. Allow memory-safe batch size, checkpoints and recovery on interruption; ensure CPU mode works and clear errors for incompatible GPU. Measure actual timings; do not estimate or fabricate. Do not assume the user's computer has a GPU.

Use correct pretrained transformations; implement train-only augmentations without crossing groups or producing images saved in evaluation. Respect label order across train/evaluation/export. Guard batch-normalization handling for batch-size-one. Log loss and per-class validation metrics, choose checkpoint and thresholds on validation only, and keep test and field-test evaluation in a separate command. Handle zero-sample classes and label mismatch explicitly. Save confusion matrices, per-class precision/recall/F1/support, macro F1 and accuracy, plus confidence calibration (e.g. ECE/Brier with defined computation) and unknown-detection/abstention coverage versus risk, with uncertainty intervals where justified. Keep all confidence and abstention thresholds validation-derived and versioned. A closed-set softmax score is not a calibrated probability or a reliable OOD detector by itself; measure false accepts and false rejects on distinct, clearly characterized unknowns. Do not label uncertainty reliable without real validation evidence.

Report PlantVillage held-out and PlantDoc field-like outputs separately; dataset shift, small per-class support and failure cases matter. Compare FP32 vs exported/quantized formats on same locked inputs, including preprocessing parity, per-class degradation and discrepancy examples. Training success alone does not mean Android model compatibility. Create an artifact manifest with real SHA-256, dataset identity and exact command/config. No metrics until a run exists.

## 5. Actual CNE integration

Existing CNE core remains authoritative. Preserve the semantic/physical split, frozen generic semantic primitives, outcome contracts, signatures, effects, state fabric, selective invalidation, planner, verifier/auditor and benchmark corpus. Do not introduce domain-specific semantic node kinds or mutate graph truth. Use trusted built-in capability integration; do not grant third-party packs execution privileges.

Construct an actual semantic graph using existing primitives and model/tool calls with correct declared effects; identify the exact image bytes, model hash, preprocessing version, label mapping, runtime identity and contract in dependency/memo identity. Ensure note-only changes cannot invalidate image inference unnecessarily, while replacing image/model/preprocessing/labels invalidates affected output. Conservative recomputation is acceptable when safety cannot be proved. Tests must show actual model invocation count or trace, reused-state observability, model/asset mutation invalidation, note-only behavior, lifecycle/restart durability if implemented, and baseline parity. Verify data dependencies and effects rather than directly asserting reuse correctness. Check any existing effect-aware cache rules; do not mark model inference pure if nondeterminism, native runtime, mutable files or configuration make reuse unsafe. Refuse reuse when keys or integrity checks cannot be trusted.

The current desktop model adapter is not proof of Android execution. Produce a concrete, testable Android bridge design to the actual CNE core (e.g. supported embedded runtime or semantics-preserving port with conformance evidence); do not replace the core with a hard-coded result, a separate cache described as CNE, or an HTTP/cloud service. If the real engine cannot yet run on Android, leave the APK integration explicitly blocked/unverified; do not claim otherwise.

Compare baseline full recomputation and CNE on the same inputs, model/runtime/device, output contract, warm/cold conditions and repeated trials. Measure end-to-end elapsed, inference calls, overhead and total net savings; verify equality/tolerance using a stated contract. Include cold runs, reuse hits, image/model mutation and low-benefit cases; report overhead and negative savings. `contract_satisfied` is not evidence a disease prediction is correct.

## 6. Android product, build and device tests

Create a real Android application using a CPU-compatible on-device inference runtime supported by the selected exported artifact. Preserve offline operation, local records, camera/import permissions with denial paths, lifecycle recovery and accessible responsive UI. Show product name, photo preview, supported labels, prediction/uncertainty with experimental warning, plant history and diagnostic trace. No server, fake inference, guessed diagnosis or paid APIs. Include model manifest, source/license notices and file integrity checks. Ensure preprocessing/model-label parity with desktop reference; validate logits or declared tolerance on a fixed corpus.

Build a debug APK with a reproducible command and record SDK/Gradle/build versions, package ID, min SDK, target SDK, ABIs, SHA-256, APK size and signing type. Check install and launch on a real device if accessible; otherwise mark device test NOT_TESTED and provide precise instructions for the user. Debug signing is for local testing. Inspect APK to confirm real model/runtime inclusion and no unnecessary network permission. Report device model, OS/ABI, memory, CPU-only execution, peak Android PSS, cold/warm P50/P95, model load/inference times, 30-minute thermal behavior and battery measurement only if actually measured with methodology. Installation must be possible without network after artifact acquisition.

## 7. Automated tests and acceptance

Add meaningful tests for group and duplicate leakage, manifest stability, corrupted files, group fallback, label mapping, missing-class handling, training/eval split boundaries, resume consistency, unsupported input, confidence calibration and unknowns, artifact hash tampering, preprocessing parity and CNE reuse/invalidation, including adversarial mismatch. Mocks only for isolated unit tests; never as evidence of real model or mobile performance. Run relevant existing tests and report exact test counts, skips and failures. Run a real small training run on actual audited data, then the full run if resources allow; log real parameters and timing. Do not use production blind CNE controller corpora for this vision work or training.

Acceptance requires: real trained artifact + auditable training lineage; separate held-out and field-like evaluation or explicit insufficient evidence; real CNE execution path with tested invalidation and parity; actual Android CPU inference and APK, or a clearly documented blocker; and honest device data when physically tested. No arbitrary fabricated accuracy/speed targets. Where appropriate propose measurable gates before executing tests; report actual outcomes separately.

## 8. Deliverables and reporting

Provide repository changes, exact runnable Windows PowerShell and cross-platform commands, data paths, setup/recovery instructions, requirements lock, signed hashes, experiment configs, dataset manifests, metrics and model card. Large data/model/build files stay outside Git unless repository policy says otherwise. Include the actual debug APK path and SHA-256 only when built. Do not say model trained or APK working without proof.

At completion report: current HEAD and branch, files changed, what actually ran, exact commands, model/dataset/runtime hashes, dataset counts and splits, quantitative results with sample sizes, test results, actual device observations, known failures and next steps. Clearly distinguish COMPLETE, PARTIAL, NOT_TESTED, NOT_MEASURED and BLOCKED. Do not push or merge without explicit user instruction. Preserve the user's work and offer exact commands to resume interrupted steps.

## 9. Getting started on Windows

From PowerShell, navigate to the user's existing CNE checkout and inspect state first:

```powershell
cd C:\path\to\CNE
git status --short --branch
git rev-parse HEAD
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install datasets pillow pytest scikit-learn
python -c "import sys,torch,torchvision; print(sys.version); print('torch',torch.__version__,'torchvision',torchvision.__version__,'CUDA',torch.cuda.is_available())"
```

This is a CPU setup; it is not an instruction to replace an already-working environment. If Python 3.11 or PowerShell activation is unavailable, adapt to an installed supported Python and policy; do not change system security settings. For NVIDIA GPU training select a compatible installation from https://pytorch.org/get-started/locally/ after inspecting the actual GPU/driver; no GPU is required.

The documented PlantVillage download example (run from the activated environment):

```powershell
python -c "from datasets import load_dataset; d=load_dataset('mohanty/PlantVillage','color'); print(d); print(d['train'].features)"
```

This downloads data/cache and may require substantial disk space. If the current upstream dataset loader or `datasets` version is incompatible, capture the error and implement the source-verified alternative above. The command downloads/inspects; it does **not** create the training manifest or train a model.

Download the official PlantDoc repository separately:

```powershell
New-Item -ItemType Directory -Force -Path data | Out-Null
git clone https://github.com/pratikkayal/PlantDoc-Dataset.git data/plantdoc
```

Do not start training until the coding agent has implemented and run manifest preparation, leakage audit, and the correct command against real files. The agent must provide the exact commands based on its implemented CLI; do not invent future script names or paths. Data assets remain local and out of Git. If the ZIP from the previous session is used, copy only reviewed new files and merge changes to configuration rather than overwriting local work.
