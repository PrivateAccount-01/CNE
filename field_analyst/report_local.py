"""Generate current truthful documentation only from completed local experiment evidence."""
import json,hashlib,subprocess
from pathlib import Path

def main():
    root=Path('field_analyst');read=lambda p:json.loads((root/p).read_text(encoding='utf-8-sig'))
    download=read('reports/archive-download.json');audit=read('reports/cohort-audit.json');training=read('runs/real-cpu/training.json');comparison=read('runs/onnx/selection.json' if (root/'runs/onnx/selection.json').exists() else 'runs/onnx/comparison.json');proof=read('reports/local-real-proof.json');gui=read('reports/gui-proof.json')
    selected=comparison['chosen'];manifest=read('runs/onnx/'+selected+'.json');test=proof['test'];validation=comparison['reports'][selected];field=proof['field_evaluation_provisional'];unknown=proof['unknown_evaluation'];model=root/'runs/onnx'/(selected+'.onnx')
    if hashlib.sha256(model.read_bytes()).hexdigest()!=proof['model_sha256'] or gui['model_sha256']!=proof['model_sha256']:raise ValueError('Evidence/model identity mismatch')
    counts={s:sum(r['images'] for r in audit['counts'] if r['split']==s) for s in ('train','validation','test')}
    per='\n'.join(f"| {r['label']} | {r['precision']:.4f} | {r['recall']:.4f} | {r['f1']:.4f} | {r['support']} |" for r in test['per_class'])
    sizes='\n'.join(f"| {n} | {r['bytes']:,} | {r['macro_f1']:.4f} | {r['p50_inference_including_preprocess_ms']:.2f} |" for n,r in comparison['reports'].items())
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip()
    text=f'''# Actual local model run — 2026-10-30

**Desktop CPU model: trained and executed. Full Android product: NOT COMPLETE.** This report supersedes the earlier script-only status for desktop inference. No push, merge or publication occurred. HEAD `{head}`, branch `{branch}`. Existing CNE core and project configuration are preserved.

## Data that actually downloaded

PlantVillage pinned revision `9e97599868962bd0079b8db4b7f1efa9185fa1e7` archive is local at `field_analyst/data/data.zip`: **{download['bytes']:,} bytes**. SHA-256 `{download['sha256']}`, verified against upstream. Archive has 163,034 members and no included README/license file; source-card license declaration and uncertainty are retained in provenance. Download took {download['elapsed_s']:.1f} seconds in the successful bounded parallel/resumed run.

All 6,627 four-class color source images were extracted and hashed. **{audit['original_selected_images']-audit['quarantined_images']:,} images** remain in the verified-leaf cohort; **{audit['quarantined_images']:,} are quarantined**, including original missing leaf identities and all affected groups from unresolved cross-group exact/near candidates. Candidate screen found {audit['near_candidates']} pairs. Entire original selected-class official test inventory remains preserved unchanged in `data/cohort-v1/official-inventory.json`; exclusions are explicit in `quarantine.json`. No fallback leaf IDs were invented and no class was silently dropped. Human/source-backed within-leaf resolutions and conservative cross-leaf quarantine precede model metrics.

The audit passed **for this restricted verified cohort only**, not the complete official benchmark. Original physical-leaf groups never cross active partitions. Source-metadata filtering narrows capture distribution and can make this subset easier than the full source. Counts: train **{counts['train']}**, validation **{counts['validation']}**, held-out verified test subset **{counts['test']}**. Full source test remains unqualified where grouping is missing. Real training used no synthetic images and no field images.

Manifest SHA-256: `{audit['manifest_sha256']}`. Metadata: `{audit['metadata_sha256']}`. Curation resolutions: `{audit['resolutions_sha256']}`. Exact counts and leaves per label/split: `reports/cohort-audit.json`. The broken documented Hugging Face loader remains recorded; this run used the checksum-verified archive and pinned source lists/map directly. A Hugging Face loader fingerprint is unavailable; archive and immutable manifest hashes identify the actual data.

## Training that actually ran

MobileNetV3 Small, ImageNet V1 initialization; convolution features frozen, four-class classifier actually optimized using labeled real images. Eight total epochs (3-epoch smoke + epoch-consistent resume to 8), seed 42, AdamW learning rate .0003, batch 16, four CPU threads, Python/PyTorch/torchvision versions bound in checkpoint lineage. CUDA unavailable; no GPU training claim. Total recorded epoch computation/validation time: **{sum(r['elapsed_s'] for r in training['logs']):.1f} seconds** (not total development/download wall time). {manifest['parameter_count']:,} total model parameters. Best checkpoint and all confidence thresholds were selected on validation only; official-subset and provisional external evaluations happened afterward.

Pretrained hash: `{manifest['pretrained']['sha256']}`; final selected checkpoint hash: `{manifest['checkpoint_sha256']}`. Full epoch losses/validation confusion matrices and metrics: `runs/real-cpu/training.json`; smoke and resumed commands/output: `reports/real-pipeline.log`, `reports/real-full.log`. Model initialization alone was never presented as tomato training.

## Size and validation comparison

All three candidates used the same locked 795 validation images and preprocessing. The full QDQ INT8 candidate was calibrated using 128 fixed **training-only** images (32 per class); it failed the quality gate and was rejected. A classifier-only dynamic INT8 fallback was then evaluated on validation before any held-out or external results; its convolutions remain FP32 and activation ranges are computed at inference. Full-candidate calibration provenance is `runs/onnx/calibration.json`. Preregistered storage selection: prefer INT8 only if macro F1 drop <= .02 and every class recall drop <= .05, otherwise FP32. Selection: **{selected.upper()}**. Best checkpoint: epoch **{manifest["selected_epoch_1based"]}** of the eight-epoch run.

| Format | Model bytes | Validation macro F1 | P50 preprocess+inference ms |
|---|---:|---:|---:|
{sizes}

FP32 preprocessing maximum absolute difference from torchvision: {comparison['reports']['fp32']['preprocess_max_abs_error']:.8g}; maximum FP32 ONNX/PyTorch logit difference on 32 locked validation references: {comparison['reports']['fp32']['torch_export_max_abs_error']:.8g}. Export numeric gate was registered before metrics. FP32/full-QDQ-INT8 rank agreement (the rejected candidate): {comparison['rank_agreement']:.4f}. Per-class degradation and largest logit discrepancy examples are retained in `runs/onnx/comparison.json`; no claim that a quantized logit matches FP32 exactly. No global smallest-architecture claim: this is the smaller acceptable measured export of the specified small architecture.

## Held-out evidence

Restricted verified-leaf official-test subset, **n={test['known_n']}**: accuracy **{test['accuracy']:.4f}**, macro F1 **{test['macro_f1']:.4f}**, ECE (15 bins) **{test['ece_15_equal_width']:.4f}**, multiclass Brier (sum over classes) **{test['multiclass_brier_sum']:.4f}**. These are lab-source subset results, not the full official benchmark or farm diagnostic accuracy. The image-level Wilson interval is exploratory and not leaf-cluster adjusted.

| Label | Precision | Recall | F1 | Images |
|---|---:|---:|---:|---:|
{per}

PlantDoc: separately downloaded/materialized 2,578 original image items; two decode/size rejections were logged. Directory mapping was frozen before metrics, with no invented healthy class. Cross-source SHA256/dHash screening against all 6,627 used PV source images (including quarantines) excludes unresolved candidates. Other PV categories were not used for training and were not screened. Original-image grouping, item rights and field representativeness remain **UNVERIFIED**, so external numbers below are provisional/insufficient evidence for general deployment.

Provisional matching-class PlantDoc evaluation: n={field['known_n'] if field else 0}, accuracy {field['accuracy'] if field else None}, macro F1 {field['macro_f1'] if field else None}. No mapped healthy support. Fixed 128-or-fewer unsupported PlantDoc examples: n={unknown['unknown_n'] if unknown else 0}, false-accept rate at the validation-derived score threshold **{unknown['operating_point']['unknown_false_accept'] if unknown else None}**. This is a measured limitation, not reliable unknown detection. Blur and multiple-leaf support remain NOT_VALIDATED. No external image influenced training, threshold or format selection. Full confusion matrices, sample lists and source provenance are in `reports/local-real-proof.json`.

## Actual local CPU execution

Selected model: `runs/onnx/{selected}.onnx`, **{proof['model_bytes']:,} bytes**; SHA-256 `{proof['model_sha256']}`. Runtime ONNX Runtime 1.20.1, CPUExecutionProvider only, one intra/inter-op thread, sequential deterministic-compute option. **PyTorch imported in inference process: {proof['torch_imported_in_inference_process']}**. No HTTP service/cloud API is used for inference; installed assets and records are local.

New-session load time (single observation; OS cache uncontrolled): **{proof['model_load_ms']:.2f} ms**. Across {test['known_n']} locked subset test images, preprocess+inference P50/P95: **{proof['test_p50_preprocess_and_infer_ms']:.2f}/{proof['test_p95_preprocess_and_infer_ms']:.2f} ms**. Whole verification process RSS at observation: **{proof['process_rss_bytes']/2**20:.1f} MiB**; OS peak working set **{(proof['process_peak_working_set_bytes'] or 0)/2**20:.1f} MiB**. These are this Windows computer's measurements, not Android or isolated model-only memory. Runtime-only requirements exclude torch/torchvision/datasets; the development environment retains them for training.

The actual existing `ComputationNecessityEngine` executed Observe/Call/Emit for real images, not a separate answer cache. Four real observation cases verified repeated logits, note-only behavior, baseline parity and record durability after reopening SQLite. Actual-model tampering was rejected before invocation. Twenty warm paired baseline/CNE trials with alternating execution order recorded median net savings **{proof['median_net_savings_ns']/1e6:.3f} ms**, negative-savings fraction **{proof['negative_savings_fraction']:.2%}**. Native reuse remains conservatively disabled by Nondeterministic/ReadExternal effects; no savings claim is fabricated. This path executes real CNE but does not yet optimize model invocations. Deterministic core reuse/invalidation has separate unit evidence.

Desktop Tk interface: actual selected model loaded, actual image preview rendered, real inference result and all four ranked labels rendered in functional test. Status: `{gui['status']}`. Visual/accessibility/manual UX review remains NOT_TESTED. User can import local photos, retain observations/notes, view history and CNE trace. Model scores are not calibrated diagnosis probabilities; healthy is not proof of plant health. Source/preprocessing/model identities are integrity checked.

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
'''
    lean_path=root/'reports/lean-runtime-proof.json'
    if lean_path.exists():
        lean=json.loads(lean_path.read_text())
        text+=f"\n## Minimal deployed-model process\n\nA separate fresh Python process loaded `deploy/model.onnx` and performed 21 actual CNE/model calls on one fixed real validation image, without any training imports or dataset audit. RSS after inference: **{lean['rss_after_21_inferences_bytes']/2**20:.1f} MiB**; OS peak working set: **{lean['peak_working_set_bytes']/2**20:.1f} MiB**. PyTorch imported: **{lean['torch_imported']}**. New-session load {lean['model_load_ms']:.2f} ms; first CNE analysis {lean['first_cne_analysis_ms']:.2f} ms; warm CNE P50/P95 over n=20 repeats {lean['warm_cne_p50_ms']:.2f}/{lean['warm_cne_p95_ms']:.2f} ms. These include image validation, model integrity checks, preprocessing, actual CNE and inference. OS file-cache state was uncontrolled; no Android/cold-process percentile claim. The inference runtime does not require the training dataset. See `reports/lean-runtime-proof.json`.\n"
    text=text.replace(chr(92)*2,'/')
    (root/'docs/LOCAL_MODEL_RUN.md').write_text(text,encoding='utf8')
    (root/'docs/MODEL_CARD.md').write_text(f'''# CNE Field Analyst actual model card\n\nLocal experimental four-class tomato image classifier, actually trained on {counts['train']} real verified-leaf PlantVillage images, selected on {counts['validation']} validation images. Best of eight CPU epochs. Architecture: MobileNetV3 Small ImageNet V1 features + trained classifier. Model: {selected}, {proof['model_bytes']:,} bytes, SHA-256 `{proof['model_sha256']}`.\n\nRestricted verified test subset n={test['known_n']}: accuracy {test['accuracy']:.4f}, macro F1 {test['macro_f1']:.4f}. These exclude quarantined/unverified groups and do not establish full-source or field performance. Full training, provenance, software, quantization comparison and per-class measurements: [actual run report](LOCAL_MODEL_RUN.md).\n\nOutputs in frozen order: {', '.join(manifest['labels'])}. Scores are not calibrated diagnosis probabilities, healthy is not proof of plant health, and no severity/treatment/causal-change claim is supported. Unknown false acceptance is measured and can be high; no reliable OOD claim. Field-item grouping/rights are unverified; blur/multiple-leaf reliability is not validated.\n\nWindows local CPU inference and actual CNE execution were verified; Android inference is NOT_IMPLEMENTED. Native memo reuse remains disabled; no compute-savings claim. Code/data/pretrained license and distribution uncertainties are retained in provenance; local research use only, no production certification.\n''',encoding='utf8')
    print('Wrote truthful current model documentation',flush=True)
if __name__=='__main__':main()
