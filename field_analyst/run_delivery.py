"""Continue real artifact verification only after completed audited training and runtime install."""
import json,subprocess,time
from pathlib import Path

def main():
    runtime=Path('field_analyst/.venv/Scripts/python.exe').resolve()
    while True:
        raw=Path('field_analyst/reports/real-full.log').read_bytes()
        log=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig',errors='replace')
        if 'FULL_REAL_TRAINING_COMPLETE' in log:break
        if 'Traceback (most recent call last)' in log:raise RuntimeError('Real training pipeline failed; inspect report')
        time.sleep(10)
    while True:
        probe=subprocess.run([str(runtime),'-c','import onnx,onnxruntime;print(onnx.__version__,onnxruntime.__version__)'],capture_output=True,text=True)
        if probe.returncode==0:print('Verified runtime packages:',probe.stdout,flush=True);break
        time.sleep(10)
    def run(args):print('RUN',json.dumps(args),flush=True);subprocess.run([str(runtime),'-u','-m',*args],check=True,stderr=subprocess.STDOUT)
    base='field_analyst/data/cohort-v1'
    if not Path('field_analyst/runs/onnx/comparison.json').exists():
        run(['field_analyst.export_onnx','--checkpoint','field_analyst/runs/real-cpu/best.pt','--root','field_analyst/data','--manifest',base+'/manifest.csv','--metadata',base+'/metadata.json','--resolutions',base+'/resolutions.json','--out','field_analyst/runs/onnx'])
    if not Path('field_analyst/runs/onnx/selection.json').exists():run(['field_analyst.quantize_head'])
    if not Path('field_analyst/data/plantdoc-screen.json').exists():run(['field_analyst.crosssource'])
    if not Path('field_analyst/reports/local-real-proof.json').exists():run(['field_analyst.local_validation'])
    run(['field_analyst.gui_validation']);run(['field_analyst.report_local'])
    print('REAL_DESKTOP_MODEL_AND_INTEGRATION_CHECKS_COMPLETE',flush=True)
if __name__=='__main__':main()
