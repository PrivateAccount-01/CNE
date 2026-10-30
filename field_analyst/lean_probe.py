"""Minimal installed-model process profile; no dataset audit/training/framework imports."""
import json,sys,time
from pathlib import Path
import numpy as np,psutil
from field_analyst.onnx_asset import OnnxAsset
from field_analyst.engine import FieldEngine

def main():
    evidence=json.loads(Path('field_analyst/reports/local-real-proof.json').read_text());case=evidence['real_observation_cases'][0];data=(Path('field_analyst/data')/case['path']).read_bytes();p=psutil.Process();before=p.memory_info().rss
    tick=time.perf_counter_ns();asset=OnnxAsset('field_analyst/deploy/model.onnx','field_analyst/deploy/model.json');load=time.perf_counter_ns()-tick;e=FieldEngine(asset)
    tick=time.perf_counter_ns();first=e.analyze(data);first_ns=time.perf_counter_ns()-tick;times=[]
    for _ in range(20):
        tick=time.perf_counter_ns();result=e.analyze(data);times.append(time.perf_counter_ns()-tick)
        if result['logits']!=first['logits']:raise ValueError('Local repeat differs')
    info=p.memory_info();report={'status':'DEPLOYED_MODEL_REAL_INFERENCE_VERIFIED','model_sha256':asset.manifest['sha256'],'cpu_providers':asset.session.get_providers(),'torch_imported':'torch' in sys.modules,'rss_before_model_bytes':before,'rss_after_21_inferences_bytes':info.rss,'peak_working_set_bytes':getattr(info,'peak_wset',None),'model_load_ms':load/1e6,'first_cne_analysis_ms':first_ns/1e6,'warm_cne_p50_ms':float(np.percentile(times,50)/1e6),'warm_cne_p95_ms':float(np.percentile(times,95)/1e6),'warm_n':20,'image_sha256':case['sha256'],'condition':'one fixed real validation image, fresh session, OS cache uncontrolled, CPU only','actual_model_calls':e.invocations,'dataset_required_by_model_runtime':False,'ranked':first['ranked']}
    Path('field_analyst/reports/lean-runtime-proof.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
