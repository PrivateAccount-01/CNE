"""Real-data pipeline: waits for verified archive, audit-gates training, never fabricates evidence."""
import argparse,json,subprocess,sys,time
from pathlib import Path
from field_analyst.cohort import prepare

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--epochs',type=int,default=3);args=parser.parse_args()
    print('Waiting for pinned archive download and checksum verification',flush=True)
    while not Path('field_analyst/reports/archive-download.json').exists():time.sleep(10)
    download=json.loads(Path('field_analyst/reports/archive-download.json').read_text())
    if not download['verified']:raise ValueError('Archive checksum not verified')
    prepare();base='field_analyst/data/cohort-v1';run='field_analyst/runs/real-cpu'
    command=[sys.executable,'-u','-m','field_analyst.train','train','--root','field_analyst/data','--manifest',base+'/manifest.csv','--metadata',base+'/metadata.json','--resolutions',base+'/resolutions.json','--out',run,'--epochs',str(args.epochs),'--batch-size','16','--device','cpu','--freeze-features','--threads','4']
    print('REAL_TRAINING_COMMAND',json.dumps(command),flush=True);subprocess.run(command,check=True)
    subprocess.run([sys.executable,'-u','-m','field_analyst.train','export','--checkpoint',run+'/best.pt','--out','field_analyst/runs/torchscript'],check=True)
    print('REAL_TRAINING_AND_TORCHSCRIPT_EXPORT_COMPLETE',flush=True)
if __name__=='__main__':main()
