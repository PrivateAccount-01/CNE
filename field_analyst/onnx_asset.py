"""Lightweight CPU-only ONNX asset; no PyTorch dependency in inference process."""
import io,json,platform
from pathlib import Path
import numpy as np
import PIL
from field_analyst import LABELS
from field_analyst.dataset import canonical,digest
from field_analyst.preprocess import tensor,PREPROCESS_VERSION,PREPROCESS
class OnnxAsset:
    reusable=False  # Real native reuse is unqualified; retain conservative core effect policy.
    def __init__(self,model_path,manifest_path):
        import onnxruntime as ort
        self.path=Path(model_path);self.manifest_path=Path(manifest_path);self.manifest_bytes=self.manifest_path.read_bytes();self.manifest=json.loads(self.manifest_bytes)
        m=self.manifest
        if m['labels']!=list(LABELS) or m['preprocess']!=PREPROCESS or m['format']!='onnx':raise ValueError('Model label/preprocessing/format mismatch')
        if m['runtime']['onnxruntime']!=ort.__version__:raise ValueError('ONNX runtime version mismatch')
        self.verify();options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL;options.use_deterministic_compute=True
        self.session=ort.InferenceSession(self.path.read_bytes(),sess_options=options,providers=['CPUExecutionProvider'])
        if self.session.get_providers()!=['CPUExecutionProvider']:raise ValueError('CPU provider required')
        self.input=self.session.get_inputs()[0]
        if self.input.shape!=[1,3,224,224]:raise ValueError('Invalid input shape')
        self.threshold_path=self.manifest_path.with_name(self.manifest_path.stem+'-threshold.json')
        self.threshold_bytes=self.threshold_path.read_bytes() if self.threshold_path.exists() else None
        self.threshold=None
        if self.threshold_bytes is not None:
            rule=json.loads(self.threshold_bytes)
            if rule.get('model_sha256')!=m['sha256'] or not isinstance(rule.get('threshold'),(int,float)) or not 0<=rule['threshold']<=1:
                raise ValueError('Threshold/model identity mismatch')
            self.threshold=rule['threshold']
        self.identity=canonical({'model':m['sha256'],'manifest':digest(self.manifest_bytes),'runtime':ort.__version__,'numpy':np.__version__,'pillow':PIL.__version__,'provider':'CPUExecutionProvider','intra_threads':1,'inter_threads':1,'deterministic_compute':True,'platform':platform.platform(),'machine':platform.machine(),'preprocess_code':digest(Path(__file__).with_name('preprocess.py').read_bytes()),'image_decode_code':digest(Path(__file__).with_name('dataset.py').read_bytes()),'adapter_code':digest(Path(__file__).read_bytes()),'labels':m['labels'],'preprocess':m['preprocess']})
    def verify(self):
        if digest(self.path.read_bytes())!=self.manifest['sha256'] or self.manifest_path.read_bytes()!=self.manifest_bytes:raise ValueError('Model/manifest integrity failure; reload required')
        if getattr(self,'threshold_bytes',None) is not None and self.threshold_path.read_bytes()!=self.threshold_bytes:
            raise ValueError('Threshold mutated; reload required')
    def __call__(self,data):
        self.verify();result=self.session.run(None,{self.input.name:tensor(data)})[0]
        if result.shape!=(1,len(LABELS)) or not np.isfinite(result).all():raise ValueError('Invalid output logits')
        return result[0].tolist()

def load_asset(model,manifest):
    spec=json.loads(Path(manifest).read_text())
    if spec['format']=='onnx':return OnnxAsset(model,manifest)
    from field_analyst.engine import TorchAsset
    return TorchAsset(model,manifest)
