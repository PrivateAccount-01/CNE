"""Real local CPU evaluation/integration proof; use after frozen validation model choice."""
import argparse,json,statistics,sys,time,tempfile,shutil
from pathlib import Path
import numpy as np
import psutil
from field_analyst import LABELS
from field_analyst.dataset import digest,read_manifest,safe_path,require_audit,immutable
from field_analyst.metrics import metrics
from field_analyst.onnx_asset import OnnxAsset
from field_analyst.engine import FieldEngine
from field_analyst.records import Records

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='field_analyst/reports/local-real-proof.json');a=p.parse_args()
    root='field_analyst/data';base=Path(root)/'cohort-v1';audit=require_audit(root,base/'manifest.csv',base/'metadata.json',base/'resolutions.json')
    folder=Path('field_analyst/runs/onnx');selection=folder/('selection.json' if (folder/'selection.json').exists() else 'comparison.json');choice=json.loads(selection.read_text())['chosen'];tick=time.perf_counter_ns();asset=OnnxAsset(folder/(choice+'.onnx'),folder/(choice+'.json'));load_ns=time.perf_counter_ns()-tick
    threshold=json.loads((folder/(choice+'-threshold.json')).read_text())
    if threshold['model_sha256']!=asset.manifest['sha256']:raise ValueError('Threshold identity mismatch')
    rows=read_manifest(base/'manifest.csv');test=[r for r in rows if r['split']=='test'];logits=[];ys=[];times=[]
    for r in test:
        data=safe_path(root,r['path']).read_bytes();tick=time.perf_counter_ns();logits.append(asset(data));times.append(time.perf_counter_ns()-tick);ys.append(LABELS.index(r['label']))
    report=metrics(logits,ys,threshold['threshold']);report['scope']=audit['claim_scope'];report['paths_sha256']=digest(json.dumps(test,sort_keys=True).encode());report['split']='restricted verified official-test subset, NOT complete official test'
    fixed=[next(r for r in rows if r['split']=='validation' and r['label']==label) for label in LABELS]
    benchmark=[];e=FieldEngine(asset);store=Records('field_analyst/data/integration-proof.db');pid=store.create_plant('Actual local model verification');observations=[]
    for r in fixed:
        data=safe_path(root,r['path']).read_bytes();oid=store.add(pid,data,'Initial real image');first=store.analyze(oid,e);store.update_note(oid,'Note changed; image bytes unchanged');second=store.analyze(oid,e)
        if first['logits']!=second['logits']:raise ValueError('Repeated CPU inference differs')
        for trial in range(5):
            if trial%2==0:b=e.analyze(data,baseline=True);c=e.analyze(data)
            else:c=e.analyze(data);b=e.analyze(data,baseline=True)
            if b['logits']!=c['logits']:raise ValueError('Baseline/CNE parity failure')
            benchmark.append({'path':r['path'],'trial':trial,'order':'baseline_then_cne' if trial%2==0 else 'cne_then_baseline','condition':'warm loaded session, OS cache uncontrolled','baseline_ns':b['trace']['elapsed_ns'],'cne_ns':c['trace']['elapsed_ns'],'net_savings_ns':b['trace']['elapsed_ns']-c['trace']['elapsed_ns'],'inference_calls':c['trace']['inference_calls'],'reused_state':c['trace']['reused_state']})
        observations.append({'path':r['path'],'sha256':r['sha256'],'result':first,'note_change_result':second})
    store.close();store=Records('field_analyst/data/integration-proof.db');durable=store.history(pid);store.close()
    if len(durable)!=4 or any(r['note']!='Note changed; image bytes unchanged' for r in durable):raise ValueError('Record restart verification failed')
    with tempfile.TemporaryDirectory(prefix='field-model-integrity-') as temporary:
        temp=Path(temporary);shutil.copyfile(asset.path,temp/'model.onnx');shutil.copyfile(asset.manifest_path,temp/'model.json')
        isolated=FieldEngine(OnnxAsset(temp/'model.onnx',temp/'model.json'));data=safe_path(root,fixed[0]['path']).read_bytes();isolated.analyze(data)
        with (temp/'model.onnx').open('ab') as f:f.write(b'intentional integrity test')
        try:isolated.analyze(data);raise AssertionError('Tampered real model was accepted')
        except ValueError as error:tamper_error=str(error)
        if isolated.invocations!=1:raise ValueError('Tamper was not refused before invocation')
    # Real unknown inputs from PlantDoc: non-tomato or unsupported tomato directories; no training/tuning.
    screen=json.loads(Path(root+'/plantdoc-screen.json').read_text());provenance=screen['eligible'];unknown=[]
    for item in provenance:
        if item['canonical_label'] is None and item['source_label']!='Tomato leaf' and item['decode_status']=='PASS':
            unknown.append(item)
    unknown=unknown[:128];unknown_logits=[asset(safe_path(root+'/plantdoc-safe',r['path']).read_bytes()) for r in unknown]
    unknown_report=metrics(unknown_logits,[-1]*len(unknown),threshold['threshold']) if unknown else None
    field=[r for r in provenance if r['canonical_label'] in LABELS]
    field_logits=[asset(safe_path(root+'/plantdoc-safe',r['path']).read_bytes()) for r in field]
    field_report=metrics(field_logits,[LABELS.index(r['canonical_label']) for r in field],threshold['threshold']) if field else None
    result={'status':'ACTUAL_LOCAL_INFERENCE_EXECUTED','model_format':choice,'model_sha256':asset.manifest['sha256'],'model_bytes':asset.path.stat().st_size,'model_load_ms':load_ns/1e6,
            'cpu_provider':asset.session.get_providers(),'threads':1,'torch_imported_in_inference_process':'torch' in sys.modules,
            'process_rss_bytes':psutil.Process().memory_info().rss,'process_peak_working_set_bytes':getattr(psutil.Process().memory_info(),'peak_wset',None),
            'test':report,'test_p50_preprocess_and_infer_ms':float(np.percentile(times,50)/1e6),'test_p95_preprocess_and_infer_ms':float(np.percentile(times,95)/1e6),
            'real_observation_cases':observations,'restart_records_verified':len(durable),'paired_trials':benchmark,'median_net_savings_ns':statistics.median(t['net_savings_ns'] for t in benchmark),
            'real_model_tampering_refused_before_inference':True,'tamper_error':tamper_error,
            'negative_savings_fraction':sum(t['net_savings_ns']<0 for t in benchmark)/len(benchmark),
            'unknown_evaluation':unknown_report,'unknown_source_items':unknown,'unknown_limitations':'PlantDoc grouping/item rights/cross-source overlap unverified; fixed first128 unsupported class records, no threshold tuning. Not field-representative. Multiple-leaf/blur specifically NOT_VALIDATED.',
            'field_evaluation_provisional':field_report,'field_source_items':field,'field_limitations':screen['field_role'],
            'android':'NOT_IMPLEMENTED inference bridge; desktop success only'}
    immutable(a.out,(json.dumps(result,indent=2)+'\n').encode());print(json.dumps({k:v for k,v in result.items() if k not in ('real_observation_cases','paired_trials','unknown_source_items','unknown_evaluation','field_source_items')},indent=2),flush=True)
if __name__=='__main__':main()
