"""Export actual checkpoint to FP32 ONNX and train-calibrated INT8; validate before test."""
import argparse,json,time
from pathlib import Path
import numpy as np
import onnx,onnxruntime as ort,torch
from onnxruntime.quantization import CalibrationDataReader,quantize_static,QuantFormat,QuantType,CalibrationMethod
from field_analyst import LABELS
from field_analyst.dataset import canonical,digest,immutable,read_manifest,safe_path,require_audit
from field_analyst.train import PREPROCESS,load_checkpoint
from field_analyst.preprocess import tensor
from field_analyst.metrics import metrics,select_threshold
from field_analyst.onnx_asset import OnnxAsset

def main():
    p=argparse.ArgumentParser()
    for n in ('checkpoint','root','manifest','metadata','resolutions','out'):p.add_argument('--'+n,required=True)
    a=p.parse_args();audit=require_audit(a.root,a.manifest,a.metadata,a.resolutions);m,cp=load_checkpoint(a.checkpoint);torch.set_num_threads(2)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise ValueError('Export directory must be new/empty')
    rows=read_manifest(a.manifest);val=[r for r in rows if r['split']=='validation'];calibration=[r for r in rows if r['split']=='train']
    # Fixed stratified first 32 per label in sorted immutable training manifest, no test inputs.
    calibration=[r for label in LABELS for r in [x for x in calibration if x['label']==label][:32]]
    torch.onnx.export(m,torch.zeros(1,3,224,224),str(out/'fp32.onnx'),input_names=['image'],output_names=['logits'],opset_version=17,dynamo=False)
    onnx.checker.check_model(onnx.load(out/'fp32.onnx'))
    class Reader(CalibrationDataReader):
        def __init__(self):self.it=iter(calibration)
        def get_next(self):
            row=next(self.it,None)
            return {'image':tensor(safe_path(a.root,row['path']).read_bytes())} if row else None
    quantize_static(str(out/'fp32.onnx'),str(out/'int8.onnx'),Reader(),quant_format=QuantFormat.QDQ,activation_type=QuantType.QUInt8,weight_type=QuantType.QInt8,per_channel=True,calibrate_method=CalibrationMethod.MinMax,op_types_to_quantize=['Conv','MatMul','Gemm'])
    immutable(out/'calibration.json',(canonical(calibration)+'\n').encode())
    reports={};all_logits={}
    for name in ('fp32','int8'):
        path=out/(name+'.onnx');manifest={'format':'onnx','quantization':name,'sha256':digest(path.read_bytes()),'labels':list(LABELS),'preprocess':PREPROCESS,'runtime':{'onnxruntime':ort.__version__,'provider':'CPUExecutionProvider'},'lineage':cp['lineage'],'checkpoint_sha256':digest(Path(a.checkpoint).read_bytes()),'parameter_count':sum(p.numel() for p in m.parameters()),'pretrained':{'url':cp['pretrained_url'],'sha256':cp['pretrained_sha256'],'kind':'ImageNet V1 initialization, then actually trained classifier'},'calibration_sha256':digest((out/'calibration.json').read_bytes()) if name=='int8' else None,'android_status':'NOT_TESTED','claim_scope':audit['claim_scope']}
        manifest['selected_epoch_1based']=cp['epoch']+1
        immutable(out/(name+'.json'),(canonical(manifest)+'\n').encode());asset=OnnxAsset(path,out/(name+'.json'));logits=[];ys=[];latencies=[];max_preprocess_error=0.;max_export_error=0.
        from field_analyst.train import transform
        from field_analyst.dataset import image_rgb
        for i,r in enumerate(val):
            data=safe_path(a.root,r['path']).read_bytes();tick=time.perf_counter_ns();logits.append(asset(data));latencies.append(time.perf_counter_ns()-tick);ys.append(LABELS.index(r['label']))
            if i<32 and name=='fp32':
                ref=transform()(image_rgb(data)).unsqueeze(0)
                max_preprocess_error=max(max_preprocess_error,float(np.max(np.abs(ref.numpy()-tensor(data)))))
                with torch.inference_mode():reference=m(ref)[0].numpy()
                max_export_error=max(max_export_error,float(np.max(np.abs(reference-np.array(logits[-1])))))
        logits=np.asarray(logits);all_logits[name]=logits;threshold=select_threshold(logits,ys);rpt=metrics(logits,ys,threshold);rpt.update(bytes=path.stat().st_size,p50_inference_including_preprocess_ms=float(np.percentile(latencies,50)/1e6),p95_inference_including_preprocess_ms=float(np.percentile(latencies,95)/1e6),model_sha256=manifest['sha256'],preprocess_max_abs_error=max_preprocess_error if name=='fp32' else None,torch_export_max_abs_error=max_export_error if name=='fp32' else None)
        reports[name]=rpt;immutable(out/(name+'-validation.json'),(json.dumps(rpt,indent=2)+'\n').encode());immutable(out/(name+'-threshold.json'),(canonical({'threshold':threshold,'model_sha256':manifest['sha256'],'selection':'validation-only empirical risk <=10%, not reliable OOD','unknown_n':0})+'\n').encode())
        print(name,'validation macro F1',rpt['macro_f1'],'bytes',rpt['bytes'],flush=True)
    # Preregistered storage-focused gate: <=2 percentage-point macro F1 and <=5 pp per-class recall degradation.
    recall_drop=[(f['recall'] or 0)-(q['recall'] or 0) for f,q in zip(reports['fp32']['per_class'],reports['int8']['per_class'])]
    eligible=reports['fp32']['macro_f1']-reports['int8']['macro_f1']<=.02 and max(recall_drop)<=.05 and reports['int8']['bytes']<reports['fp32']['bytes']
    chosen='int8' if eligible else 'fp32';discrepancy=np.max(np.abs(all_logits['fp32']-all_logits['int8']),axis=1)
    comparison={'selection_split':'validation only','chosen':chosen,'gate':'INT8 smaller; macro F1 drop <=0.02 and every class recall drop <=0.05','int8_eligible':eligible,'per_class_recall_drop':recall_drop,'reports':reports,'rank_agreement':float((all_logits['fp32'].argmax(1)==all_logits['int8'].argmax(1)).mean()),'largest_discrepancies':[{'path':val[i]['path'],'max_abs_logit_difference':float(discrepancy[i])} for i in np.argsort(discrepancy)[-10:]],'unknown_detection':'NOT_VALIDATED','full_official_test':'NOT_EVALUATED; restricted verified cohort only'}
    if reports['fp32']['preprocess_max_abs_error']>1e-6 or reports['fp32']['torch_export_max_abs_error']>1e-4:raise ValueError('Desktop preprocessing/export parity failed')
    immutable(out/'comparison.json',(json.dumps(comparison,indent=2)+'\n').encode());print('selected',chosen,flush=True)
if __name__=='__main__':main()
