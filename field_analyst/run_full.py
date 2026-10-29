"""Complete eight predeclared epochs after the real three-epoch smoke; test remains unopened."""
import json,subprocess,sys,time
from pathlib import Path
while True:
    raw=Path('field_analyst/reports/real-pipeline.log').read_bytes()
    log=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig',errors='replace')
    if 'REAL_TRAINING_AND_TORCHSCRIPT_EXPORT_COMPLETE' in log:break
    if 'Traceback (most recent call last)' in log:raise RuntimeError('Smoke pipeline failed')
    time.sleep(5)
base='field_analyst/data/cohort-v1';run='field_analyst/runs/real-cpu'
command=[sys.executable,'-u','-m','field_analyst.train','train','--root','field_analyst/data','--manifest',base+'/manifest.csv','--metadata',base+'/metadata.json','--resolutions',base+'/resolutions.json','--out',run,'--epochs','8','--batch-size','16','--device','cpu','--freeze-features','--threads','4','--resume',run+'/last.pt']
print('FULL_COMMAND',json.dumps(command),flush=True);subprocess.run(command,check=True)
print('FULL_REAL_TRAINING_COMPLETE',flush=True)
