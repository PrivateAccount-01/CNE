"""Embedded actual CNE; Java supplies CPU tensor execution, never caching decisions."""
import base64,json,platform,sys
from pathlib import Path
import numpy as np
import PIL
from field_analyst import LABELS
from field_analyst.dataset import canonical,digest
from field_analyst.preprocess import tensor,PREPROCESS
from field_analyst.engine import FieldEngine

_engine=None


class AndroidAsset:
    reusable=False

    def __init__(self,native,manifest,threshold,bundle):
        self.native=native
        self.manifest=json.loads(manifest)
        self.bundle=json.loads(bundle)
        required={'cne/optimizer/necessity_engine.py','cne/signature/memo_key.py','cne/contracts/outcome_contract.py',
                  'field_analyst/engine.py','field_analyst/preprocess.py','field_analyst/dataset.py','field_analyst/uncertainty.py'}
        if not required.issubset(self.bundle.get('python_sha256',{})):
            raise ValueError('Incomplete actual-core source manifest')
        m=self.manifest
        if m['labels']!=list(LABELS) or m['preprocess']!=PREPROCESS or m['format']!='onnx':
            raise ValueError('Unsupported labels/preprocessing/format')
        if m['runtime']['onnxruntime']!='1.20.1':raise ValueError('Runtime identity mismatch')
        rule=json.loads(threshold);self.threshold=rule['threshold']
        if rule['model_sha256']!=m['sha256'] or isinstance(self.threshold,bool) or not isinstance(self.threshold,(int,float)) or not np.isfinite(self.threshold) or not 0<=self.threshold<=1:
            raise ValueError('Invalid threshold binding')
        self.identity=canonical({'bundle':digest(bundle.encode()),'model':m['sha256'],'manifest':digest(manifest.encode()),'threshold':digest(threshold.encode()),
                                 'runtime':'onnxruntime-android:1.20.0','numpy':np.__version__,'pillow':PIL.__version__,'python':sys.version,'platform':platform.platform(),
                                 'provider':'CPUExecutionProvider','threads':1,'reuse':False})
        self.verify()

    def verify(self):
        self.native.verify()
        import cne,field_analyst
        roots={'cne':Path(cne.__file__).parent,'field_analyst':Path(field_analyst.__file__).parent}
        for rel,expected in self.bundle['python_sha256'].items():
            package,*parts=rel.split('/')
            if digest(roots[package].joinpath(*parts).read_bytes())!=expected:
                raise ValueError('Embedded source integrity failure: '+rel)

    def __call__(self,data):
        from java import jarray,jfloat
        self.verify()
        values=self.native.runTensor(jarray(jfloat)(tensor(data).reshape(-1)))
        return [float(x) for x in values]


def initialize(native,manifest,threshold,bundle):
    global _engine
    _engine=FieldEngine(AndroidAsset(native,manifest,threshold,bundle))
    return _engine.asset.identity


def analyze(encoded,note='',baseline=False):
    if _engine is None:raise RuntimeError('Model is not initialized')
    data=base64.b64decode(encoded,validate=True)
    if len(data)>32*1024*1024:raise ValueError('Image exceeds 32 MiB')
    return json.dumps(_engine.analyze(data,note,baseline=baseline),allow_nan=False)


def reference_tensor(encoded):
    """Instrumentation parity hook; reference corpus/tolerances must be preregistered."""
    data=base64.b64decode(encoded,validate=True)
    return base64.b64encode(tensor(data).astype('<f4').tobytes()).decode('ascii')
