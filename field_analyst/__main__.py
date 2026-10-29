"""Executable desktop CLI; never fabricates absent model results."""
import argparse,json
from pathlib import Path
from field_analyst.dataset import audit
from field_analyst.records import Records
from field_analyst.engine import FieldEngine,TorchAsset

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('audit')
    for x in ('root','manifest','metadata','out'): q.add_argument('--'+x,required=True)
    q.add_argument('--resolutions')
    q=sub.add_parser('plant'); q.add_argument('--db',required=True); q.add_argument('--name',required=True)
    q=sub.add_parser('import'); q.add_argument('--db',required=True); q.add_argument('--plant',required=True); q.add_argument('--image',required=True); q.add_argument('--note',default='')
    q=sub.add_parser('note'); q.add_argument('--db',required=True); q.add_argument('--observation',required=True); q.add_argument('--text',required=True)
    q=sub.add_parser('history'); q.add_argument('--db',required=True); q.add_argument('--plant',required=True)
    q=sub.add_parser('analyze'); q.add_argument('--db',required=True); q.add_argument('--observation',required=True); q.add_argument('--model',required=True); q.add_argument('--model-manifest',required=True)
    a=p.parse_args()
    if a.command=='audit':
        result=audit(a.root,a.manifest,a.metadata,a.resolutions); Path(a.out).write_text(json.dumps(result,indent=2),encoding='utf8'); print(result['status']); raise SystemExit(0 if result['status']=='PASS' else 2)
    store=Records(a.db)
    try:
        if a.command=='plant': result=store.create_plant(a.name)
        elif a.command=='import': result=store.add(a.plant,Path(a.image).read_bytes(),a.note)
        elif a.command=='note': result=store.update_note(a.observation,a.text)
        elif a.command=='history': result=store.history(a.plant)
        else:
            from field_analyst.onnx_asset import load_asset
            result=store.analyze(a.observation,FieldEngine(load_asset(a.model,a.model_manifest)))
        print(json.dumps(result,indent=2))
    finally: store.close()
if __name__=='__main__': main()
