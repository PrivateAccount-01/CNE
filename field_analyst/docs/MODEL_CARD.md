# CNE Field Analyst actual model card

Local experimental four-class tomato image classifier, actually trained on 3183 real verified-leaf PlantVillage images, selected on 795 validation images. Best of eight CPU epochs. Architecture: MobileNetV3 Small ImageNet V1 features + trained classifier. Model: head_int8, 4,333,541 bytes, SHA-256 `1798ca38ffcf388baee5e2c4c5eeab162ad475fdf7aeffdc63b7f5a4928e2582`.

Restricted verified test subset n=1047: accuracy 0.9685, macro F1 0.9598. These exclude quarantined/unverified groups and do not establish full-source or field performance. Full training, provenance, software, quantization comparison and per-class measurements: [actual run report](LOCAL_MODEL_RUN.md).

Outputs in frozen order: Tomato___healthy, Tomato___Early_blight, Tomato___Late_blight, Tomato___Bacterial_spot. Scores are not calibrated diagnosis probabilities, healthy is not proof of plant health, and no severity/treatment/causal-change claim is supported. Unknown false acceptance is measured and can be high; no reliable OOD claim. Field-item grouping/rights are unverified; blur/multiple-leaf reliability is not validated.

Windows local CPU inference and actual CNE execution were verified; Android inference is NOT_IMPLEMENTED. Native memo reuse remains disabled; no compute-savings claim. Code/data/pretrained license and distribution uncertainties are retained in provenance; local research use only, no production certification.
