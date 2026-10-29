"""Tiny untrained ONNX fixtures test the runtime only; never quality evidence."""
import io,json
import numpy as np
import pytest
from PIL import Image
onnx=pytest.importorskip('onnx');ort=pytest.importorskip('onnxruntime')
from onnx import helper,TensorProto,numpy_helper
from field_analyst import LABELS
from field_analyst.dataset import digest
from field_analyst.preprocess import PREPROCESS,tensor
from field_analyst.onnx_asset import OnnxAsset
from field_analyst.engine import FieldEngine

def asset_files(tmp_path):
    graph=helper.make_graph([helper.make_node('GlobalAveragePool',['image'],['mean']),helper.make_node('Flatten',['mean'],['flat']),helper.make_node('Gemm',['flat','weight','bias'],['logits'])],
        'UNTRAINED_CODE_FIXTURE',[helper.make_tensor_value_info('image',TensorProto.FLOAT,[1,3,224,224])],[helper.make_tensor_value_info('logits',TensorProto.FLOAT,[1,4])],
        [numpy_helper.from_array(np.arange(12,dtype=np.float32).reshape(3,4)/10,'weight'),numpy_helper.from_array(np.zeros(4,dtype=np.float32),'bias')])
    m=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)]);model=tmp_path/'fixture.onnx';onnx.save(m,model)
    manifest=tmp_path/'fixture.json';spec={'format':'onnx','labels':list(LABELS),'sha256':digest(model.read_bytes()),'preprocess':PREPROCESS,'runtime':{'onnxruntime':ort.__version__}}
    manifest.write_text(json.dumps(spec));return model,manifest,spec

def test_actual_cpu_onnx_and_cne_parity(tmp_path):
    model,manifest,_=asset_files(tmp_path);asset=OnnxAsset(model,manifest);stream=io.BytesIO();Image.new('RGB',(256,256),(120,150,170)).save(stream,format='PNG');data=stream.getvalue()
    expected=tensor(data).mean(axis=(2,3))@(np.arange(12,dtype=np.float32).reshape(3,4)/10)
    # FP32 pooling sums 50,176 values with backend-dependent reduction order.
    # This analytic fixture allows 1e-4 relative error; real-model export has its separate registered gate.
    np.testing.assert_allclose(asset(data),expected[0],atol=0,rtol=1e-4)
    engine=FieldEngine(asset);assert engine.analyze(data)['logits']==engine.analyze(data,baseline=True)['logits'];assert not engine.analyze(data)['trace']['reused_state']
    model.write_bytes(model.read_bytes()+b'tamper')
    with pytest.raises(ValueError,match='integrity'):engine.analyze(data)

def test_preprocessing_labels_and_threshold_binding(tmp_path):
    model,manifest,spec=asset_files(tmp_path);spec['preprocess']=dict(PREPROCESS,mean=[0,0,0]);manifest.write_text(json.dumps(spec))
    with pytest.raises(ValueError,match='preprocessing'):OnnxAsset(model,manifest)
    spec['preprocess']=PREPROCESS;manifest.write_text(json.dumps(spec));threshold=tmp_path/'fixture-threshold.json';threshold.write_text(json.dumps({'model_sha256':'wrong','threshold':.5}))
    with pytest.raises(ValueError,match='Threshold'):OnnxAsset(model,manifest)
