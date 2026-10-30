"""Stage exact local model/core bytes; no training or replacement artifact download."""
import hashlib,json,shutil
from pathlib import Path

MODEL_SHA='1798ca38ffcf388baee5e2c4c5eeab162ad475fdf7aeffdc63b7f5a4928e2582'


def prepare(repo=None):
    root=Path(__file__).resolve().parent
    repo=Path(repo) if repo else root.parents[1]
    generated=root/'generated';assets=generated/'assets';python=generated/'python'
    assets.mkdir(parents=True,exist_ok=True);python.mkdir(parents=True,exist_ok=True)
    # Clean only this task-owned generated Python directory, never the source.
    if not python.resolve().is_relative_to(root.resolve()):raise ValueError('Unsafe generated directory')
    for package in ('cne','field_analyst'):
        target=python/package
        if target.exists():shutil.rmtree(target)
    hashes={}
    for package in ('cne','field_analyst'):
        for path in sorted((repo/package).rglob('*.py')):
            rel=path.relative_to(repo)
            if package=='field_analyst' and len(rel.parts)!=2:continue
            if package=='cne' and any(p in {'tests','artifacts','bench','__pycache__'} for p in rel.parts):continue
            target=python/rel;target.parent.mkdir(parents=True,exist_ok=True)
            data=path.read_bytes();target.write_bytes(data);hashes[rel.as_posix()]=hashlib.sha256(data).hexdigest()
    asset_hashes={}
    for name in ('model.onnx','model.json','model-threshold.json'):
        data=(repo/'field_analyst/deploy'/name).read_bytes();sha=hashlib.sha256(data).hexdigest()
        if name=='model.onnx' and sha!=MODEL_SHA:raise ValueError('Pinned trained model mismatch')
        (assets/name).write_bytes(data);asset_hashes[name]=sha
    manifest=json.loads((assets/'model.json').read_text())
    if manifest['sha256']!=MODEL_SHA:raise ValueError('Model manifest mismatch')
    bundle={'schema_version':1,'assets_sha256':asset_hashes,'python_sha256':hashes,
            'runtime':{'onnxruntime_android':'1.20.0','chaquopy':'16.1.0','python':'3.11','numpy':'1.26.2','Pillow':'11.0.0'},
            'scope':'Experimental inspection-only; native reuse disabled; Android parity NOT_TESTED until instrumentation runs'}
    (assets/'bundle.json').write_text(json.dumps(bundle,sort_keys=True,indent=2))
    shutil.copyfile(root/'NOTICE.txt',assets/'NOTICE.txt')
    notices=assets/'third-party';notices.mkdir(exist_ok=True)
    for path in sorted((root/'third-party').iterdir()):
        if path.is_file():shutil.copyfile(path,notices/path.name)
    if (repo/'LICENSE').exists():shutil.copyfile(repo/'LICENSE',assets/'CNE-LICENSE.txt')
    return bundle


if __name__=='__main__':
    bundle=prepare();print(json.dumps({'status':'STAGED_NOT_EXECUTED','model_sha256':MODEL_SHA,'python_files':len(bundle['python_sha256'])}))
