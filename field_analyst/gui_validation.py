"""Functional Tk smoke check with the actual selected model; no visual/device claim."""
import json,tkinter as tk
from pathlib import Path
from field_analyst.app import App
from field_analyst import LABELS
from field_analyst.dataset import read_manifest,safe_path

def main():
    folder=Path('field_analyst/runs/onnx');selection=folder/('selection.json' if (folder/'selection.json').exists() else 'comparison.json');choice=json.loads(selection.read_text())['chosen']
    root=tk.Tk();root.withdraw();app=App(root,folder/(choice+'.onnx'),folder/(choice+'.json'),'field_analyst/data/gui-proof.db')
    pid=app.store.create_plant('Real model UI verification');app.refresh_plants()
    row=next(r for r in read_manifest('field_analyst/data/cohort-v1/manifest.csv') if r['split']=='validation')
    oid=app.store.add(pid,safe_path('field_analyst/data',row['path']).read_bytes(),'Actual validation photo')
    app.observation=oid;app.show(oid);root.update_idletasks();result=app.store.analyze(oid,app.engine);app.render(result);root.update_idletasks()
    content=app.result.get('1.0','end')
    assert all(label in content for label in LABELS);assert result['trace']['inference_calls']==1;assert app.photo is not None
    report={'status':'FUNCTIONAL_TK_TEST_PASSED_WITH_REAL_MODEL','model_sha256':app.engine.asset.manifest['sha256'],'real_image_sha256':row['sha256'],'ranked_labels_rendered':len(result['ranked']),'actual_inference_calls':result['trace']['inference_calls'],'visual_review':'NOT_TESTED','physical_device':'NOT_TESTED'}
    Path('field_analyst/reports/gui-proof.json').write_text(json.dumps(report,indent=2));app.close();print(json.dumps(report,indent=2))
if __name__=='__main__':main()
