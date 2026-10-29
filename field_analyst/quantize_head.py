"""Validation-only fallback quantization after full QDQ INT8 failed its registered gate.
Keeps failed artifacts and metrics; never uses held-out/field results for this choice.
"""
import json,time
from pathlib import Path
import numpy as np
from onnxruntime.quantization import quantize_dynamic,QuantType
from field_analyst import LABELS
from field_analyst.dataset import canonical,digest,immutable,read_manifest,safe_path
from field_analyst.metrics import metrics,select_threshold
from field_analyst.onnx_asset import OnnxAsset

def main():
    folder=Path('field_analyst/runs/onnx');path=folder/'head_int8.onnx'
    if Path('field_analyst/reports/local-real-proof.json').exists():raise ValueError('Held-out already evaluated; do not adapt format on that evidence')
    quantize_dynamic(str(folder/'fp32.onnx'),str(path),weight_type=QuantType.QInt8,per_channel=True,op_types_to_quantize=['MatMul','Gemm'])
    spec=json.loads((folder/'fp32.json').read_text());spec.update(quantization='INT8 dynamic classifier only; convolution remains FP32',sha256=digest(path.read_bytes()),calibration_sha256=None)
    immutable(folder/'head_int8.json',(canonical(spec)+'\n').encode());asset=OnnxAsset(path,folder/'head_int8.json')
    rows=[r for r in read_manifest('field_analyst/data/cohort-v1/manifest.csv') if r['split']=='validation'];logits=[];ys=[];latencies=[]
    for r in rows:
        data=safe_path('field_analyst/data',r['path']).read_bytes();tick=time.perf_counter_ns();logits.append(asset(data));latencies.append(time.perf_counter_ns()-tick);ys.append(LABELS.index(r['label']))
    threshold=select_threshold(logits,ys);report=metrics(logits,ys,threshold);report.update(bytes=path.stat().st_size,p50_inference_including_preprocess_ms=float(np.percentile(latencies,50)/1e6),p95_inference_including_preprocess_ms=float(np.percentile(latencies,95)/1e6),model_sha256=spec['sha256'])
    immutable(folder/'head_int8-validation.json',(json.dumps(report,indent=2)+'\n').encode());immutable(folder/'head_int8-threshold.json',(canonical(dict(threshold=threshold,model_sha256=spec['sha256'],selection='validation-only known risk <=10%, not OOD reliability',unknown_n=0))+'\n').encode())
    comparison=json.loads((folder/'comparison.json').read_text());fp=comparison['reports']['fp32'];drops=[(x['recall'] or 0)-(y['recall'] or 0) for x,y in zip(fp['per_class'],report['per_class'])]
    eligible=fp['macro_f1']-report['macro_f1']<=.02 and max(drops)<=.05 and report['bytes']<fp['bytes']
    comparison['reports']['head_int8']=report;comparison.update(chosen='head_int8' if eligible else comparison['chosen'],fallback_reason='Full static QDQ INT8 failed validation; dynamic classifier-only INT8 evaluated before opening held-out/field',head_int8_eligible=eligible,head_per_class_recall_drop=drops,full_int8_original_rank_agreement=comparison['rank_agreement'])
    immutable(folder/'selection.json',(json.dumps(comparison,indent=2)+'\n').encode());print('Head-only INT8 validation macro F1',report['macro_f1'],'bytes',report['bytes'],'chosen',comparison['chosen'],flush=True)
if __name__=='__main__':main()
