"""Execute preregistered validation-only desktop parity reference; no quality selection."""
import csv,json,platform,sys
from pathlib import Path
from field_analyst.dataset import digest
from field_analyst.onnx_asset import OnnxAsset
from field_analyst.preprocess import tensor
from cne.platform.evidence import source_identity


def main():
    repo=Path(__file__).resolve().parents[2];root=Path(__file__).resolve().parent
    output=root/'generated/test-assets';output.mkdir(parents=True,exist_ok=True)
    rows=list(csv.DictReader((repo/'field_analyst/data/cohort-v1/manifest.csv').open()))
    selected=sorted((r for r in rows if r['split']=='validation'),key=lambda r:r['sha256'])[:3]
    if len(selected)!=3:raise ValueError('Three reference images required')
    asset=OnnxAsset(repo/'field_analyst/deploy/model.onnx',repo/'field_analyst/deploy/model.json')
    refs=[]
    for i,row in enumerate(selected):
        data=(repo/'field_analyst/data'/row['path']).read_bytes()
        if digest(data)!=row['sha256']:raise ValueError('Reference image hash mismatch')
        logits=asset(data);image=f'reference-{i}.image';nchw=f'reference-{i}.f32'
        (output/image).write_bytes(data);(output/nchw).write_bytes(tensor(data).astype('<f4').tobytes())
        from field_analyst import LABELS
        refs.append({'image':image,'tensor':nchw,'image_sha256':digest(data),'tensor_sha256':digest((output/nchw).read_bytes()),
                     'model_sha256':asset._expected_model_sha256,'logits':logits,'ranked_labels':[LABELS[j] for j in sorted(range(4),key=lambda j:-logits[j])]})
    (output/'references.json').write_text(json.dumps(refs,indent=2))
    (output/'reference-environment.json').write_text(json.dumps({'source':source_identity(repo),'python':sys.version,'platform':platform.platform(),
        'asset_identity':asset.identity,'protocol_sha256':digest((root/'PARITY_PROTOCOL.md').read_bytes()),'scope':'Observed validation integration only; NOT new field evidence'},indent=2))
    print('Prepared three registered desktop references; Android comparison NOT_TESTED')


if __name__=='__main__':main()
