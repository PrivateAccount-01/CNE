"""Desktop validation of bridge integrity logic; never Android execution evidence."""
import importlib.util,json
from pathlib import Path
import pytest
from field_analyst import LABELS
from field_analyst.preprocess import PREPROCESS
from field_analyst.dataset import digest


def bridge():
    path=Path(__file__).parents[1]/'android_inference/app/src/main/python/android_bridge.py'
    spec=importlib.util.spec_from_file_location('android_bridge_contract_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class VerificationOnlyNative:
    def __init__(self):self.checks=0
    def verify(self):self.checks+=1


def arguments():
    root=Path(__file__).parents[2]
    paths=['cne/optimizer/necessity_engine.py','cne/signature/memo_key.py','cne/contracts/outcome_contract.py',
           'field_analyst/engine.py','field_analyst/preprocess.py','field_analyst/dataset.py','field_analyst/uncertainty.py']
    manifest={'labels':list(LABELS),'preprocess':PREPROCESS,'format':'onnx','runtime':{'onnxruntime':'1.20.1'},'sha256':'synthetic-model-fixture'}
    threshold={'model_sha256':manifest['sha256'],'threshold':0.}
    bundle={'python_sha256':{p:digest((root/p).read_bytes()) for p in paths}}
    return manifest,threshold,bundle


def test_bridge_uses_authoritative_engine_and_disables_native_reuse():
    module=bridge();manifest,threshold,bundle=arguments();native=VerificationOnlyNative()
    module.initialize(native,*map(json.dumps,(manifest,threshold,bundle)))
    from field_analyst.engine import FieldEngine
    assert isinstance(module._engine,FieldEngine)
    assert module._engine.asset.reusable is False and native.checks==1
    with pytest.raises(ValueError):module.analyze('invalid base64')


@pytest.mark.parametrize('attack',['missingcore','sourcehash','thresholdbinding','thresholdbool','labelorder','preprocess','runtime'])
def test_bridge_refuses_invalid_asset_identity(attack):
    module=bridge();manifest,threshold,bundle=arguments()
    if attack=='missingcore':bundle['python_sha256']={}
    elif attack=='sourcehash':bundle['python_sha256']['cne/optimizer/necessity_engine.py']='incorrect'
    elif attack=='thresholdbinding':threshold['model_sha256']='wrong'
    elif attack=='thresholdbool':threshold['threshold']=True
    elif attack=='labelorder':manifest['labels'].reverse()
    elif attack=='preprocess':manifest['preprocess']=dict(PREPROCESS,crop=100)
    elif attack=='runtime':manifest['runtime']['onnxruntime']='wrong'
    with pytest.raises(ValueError):module.initialize(VerificationOnlyNative(),*map(json.dumps,(manifest,threshold,bundle)))
