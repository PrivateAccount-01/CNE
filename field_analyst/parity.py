"""Locked-input desktop FP32/export parity and paired CNE baseline timings."""
import argparse, json, statistics, time
from pathlib import Path
import numpy as np
import torch
from field_analyst.dataset import digest, immutable, read_manifest, safe_path
from field_analyst.engine import TorchAsset, FieldEngine
from field_analyst.train import Images, load_checkpoint

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--manifest',required=True);p.add_argument('--model',required=True);p.add_argument('--model-manifest',required=True);p.add_argument('--checkpoint',required=True);p.add_argument('--out',required=True);p.add_argument('--trials',type=int,default=5);a=p.parse_args()
    if a.trials<3: raise ValueError('At least 3 paired trials required')
    rows=[r for r in read_manifest(a.manifest) if r['split']=='validation']
    if not rows: raise ValueError('Locked validation corpus required; do not adapt based on held-out test')
    asset=TorchAsset(a.model,a.model_manifest);m,checkpoint=load_checkpoint(a.checkpoint)
    if asset.manifest['checkpoint_sha256']!=digest(Path(a.checkpoint).read_bytes()) or checkpoint['lineage']['manifest_sha256']!=digest(Path(a.manifest).read_bytes()):raise ValueError('Lineage mismatch')
    torch.set_num_threads(2); dataset=Images(a.root,rows);examples=[];paired=[]
    for i,row in enumerate(rows):
        data=safe_path(a.root,row['path']).read_bytes(); x,_=dataset[i]
        with torch.inference_mode(): reference=m(x.unsqueeze(0))[0].tolist()
        exported=asset(data);error=float(np.max(np.abs(np.array(reference)-exported)))
        examples.append({'path':row['path'],'sha256':digest(data),'label':row['label'],'reference':reference,'exported':exported,'max_abs_error':error,'within_atol_1e-5_rtol_1e-5':bool(np.allclose(reference,exported,atol=1e-5,rtol=1e-5))})
        engine=FieldEngine(asset)
        for trial in range(a.trials):
            # Alternate order; both paths use exact same asset/runtime/input/output contract.
            results={}
            for baseline in ([True,False] if trial%2==0 else [False,True]):
                tick=time.perf_counter_ns();r=engine.analyze(data,note=str(trial),baseline=baseline);elapsed=time.perf_counter_ns()-tick
                results['baseline' if baseline else 'cne']={'end_to_end_ns':elapsed,'result':r}
            b=results['baseline'];c=results['cne']
            paired.append({'path':row['path'],'trial':trial,'condition':'first_pair_model_already_loaded' if trial==0 else 'warm',
                           'baseline_ns':b['end_to_end_ns'],'cne_ns':c['end_to_end_ns'],'net_savings_ns':b['end_to_end_ns']-c['end_to_end_ns'],
                           'equivalent':b['result']['logits']==c['result']['logits'],'cne_inference_calls':c['result']['trace']['inference_calls'],'reused':c['result']['trace']['reused_state']})
    report={'format':'torchscript FP32 desktop, no quantized comparison','model_sha256':asset.manifest['sha256'],'manifest_sha256':digest(Path(a.manifest).read_bytes()),
            'examples':examples,'paired_trials':paired,'parity_pass':all(e['within_atol_1e-5_rtol_1e-5'] for e in examples),
            'median_net_savings_ns':statistics.median(r['net_savings_ns'] for r in paired),'negative_savings_fraction':sum(r['net_savings_ns']<0 for r in paired)/len(paired),
            'limitations':['Native reuse disabled','Cold process/model loading NOT_MEASURED','No Android measurements','Timing includes common validation/formatting; asset load excluded','Image/model mutation correctness covered by tests; real trained model mutation benchmark NOT_MEASURED']}
    immutable(a.out,(json.dumps(report,indent=2)+'\n').encode())
if __name__=='__main__': main()
