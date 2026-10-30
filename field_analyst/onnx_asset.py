"""CPU-only ONNX asset. Runtime consumes the exact verified byte snapshot; no PyTorch."""
import json,platform
from pathlib import Path
import numpy as np
import PIL
from field_analyst import LABELS
from field_analyst.dataset import canonical,digest
from field_analyst.preprocess import tensor,PREPROCESS
class OnnxAsset:
    reusable=False
    def __init__(self,model_path,manifest_path):
        import onnxruntime as ort
        self.path=Path(model_path);self.manifest_path=Path(manifest_path)
        self.manifest_bytes=self.manifest_path.read_bytes();self.manifest=json.loads(self.manifest_bytes);m=self.manifest
        if m['labels']!=list(LABELS) or m['preprocess']!=PREPROCESS or m['format']!='onnx':raise ValueError('Model label/preprocessing/format mismatch')
        if m['runtime']['onnxruntime']!=ort.__version__:raise ValueError('ONNX runtime version mismatch')
        self._expected_model_sha256=m['sha256']
        verified_model_bytes=self.path.read_bytes()
        if digest(verified_model_bytes)!=self._expected_model_sha256:raise ValueError('Model integrity failure')
        self.threshold_path=self.manifest_path.with_name(self.manifest_path.stem+'-threshold.json')
        self.threshold_bytes=self.threshold_path.read_bytes() if self.threshold_path.exists() else None;self.threshold=None
        if self.threshold_bytes is not None:
            rule=json.loads(self.threshold_bytes);value=rule.get('threshold')
            if rule.get('model_sha256')!=self._expected_model_sha256 or isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value) or not 0<=value<=1:
                raise ValueError('Threshold/model identity mismatch')
            self.threshold=value
        options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1;options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL;options.use_deterministic_compute=True
        # Never re-read mutable model bytes between hash verification and loading.
        self.session=ort.InferenceSession(verified_model_bytes,sess_options=options,providers=['CPUExecutionProvider'])
        if self.session.get_providers()!=['CPUExecutionProvider']:raise ValueError('CPU provider required')
        self.input=self.session.get_inputs()[0]
        if self.input.shape!=[1,3,224,224]:raise ValueError('Invalid input shape')
        self.verify() # refuse changes during initialization, before exposing the session
        self.identity=canonical({'model':self._expected_model_sha256,'manifest':digest(self.manifest_bytes),'threshold':digest(self.threshold_bytes) if self.threshold_bytes is not None else 'absent',
            'runtime':ort.__version__,'numpy':np.__version__,'pillow':PIL.__version__,'provider':'CPUExecutionProvider','intra_threads':1,'inter_threads':1,'deterministic_compute':True,'platform':platform.platform(),'machine':platform.machine(),
            'preprocess_code':digest(Path(__file__).with_name('preprocess.py').read_bytes()),'image_decode_code':digest(Path(__file__).with_name('dataset.py').read_bytes()),'adapter_code':digest(Path(__file__).read_bytes()),'labels':m['labels'],'preprocess':m['preprocess']})
    def verify(self):
        try:
            if digest(self.path.read_bytes())!=self._expected_model_sha256 or self.manifest_path.read_bytes()!=self.manifest_bytes:raise ValueError('Model/manifest integrity failure; reload required')
            current=self.threshold_path.read_bytes() if self.threshold_path.exists() else None
            if current!=self.threshold_bytes:raise ValueError('Threshold appeared, changed or disappeared; reload required')
        except OSError as exc:raise ValueError('Asset integrity check failed: '+str(exc)) from exc
    def __call__(self,data):
        self.verify();result=self.session.run(None,{self.input.name:tensor(data)})[0]
        if result.shape!=(1,len(LABELS)) or not np.isfinite(result).all() or result.dtype.kind not in 'fiu':raise ValueError('Invalid output logits')
        return result[0].tolist()

def load_asset(model,manifest):
    spec=json.loads(Path(manifest).read_text())
    if spec['format']=='onnx':return OnnxAsset(model,manifest)
    from field_analyst.engine import TorchAsset
    return TorchAsset(model,manifest)
