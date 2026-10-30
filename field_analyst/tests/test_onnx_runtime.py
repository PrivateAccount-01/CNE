"""Tiny untrained ONNX fixtures test the runtime only; never quality evidence."""
import io,json
import numpy as np
import pytest
from PIL import Image
import onnx
import onnxruntime as ort
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


@pytest.mark.parametrize('change',['appear','disappear','modify'])
def test_threshold_lifecycle_invalidates_loaded_asset(tmp_path,change):
    model,manifest,spec=asset_files(tmp_path)
    threshold=tmp_path/'fixture-threshold.json'
    rule={'model_sha256':spec['sha256'],'threshold':.5}
    if change!='appear':threshold.write_text(json.dumps(rule))
    asset=OnnxAsset(model,manifest)
    if change=='disappear':threshold.unlink()
    else:threshold.write_text(json.dumps(dict(rule,threshold=.7)))
    with pytest.raises(ValueError,match='Threshold'):asset.verify()
    assert OnnxAsset(model,manifest).identity!=asset.identity


def test_runtime_loads_verified_bytes_and_refuses_initialization_race(tmp_path,monkeypatch):
    model,manifest,_=asset_files(tmp_path);expected=model.read_bytes()
    original=ort.InferenceSession
    def racing_session(data,**kwargs):
        assert isinstance(data,bytes) and data==expected
        model.write_bytes(expected+b'changed during load')
        return original(data,**kwargs)
    monkeypatch.setattr(ort,'InferenceSession',racing_session)
    with pytest.raises(ValueError,match='integrity'):OnnxAsset(model,manifest)


def test_concurrent_calls_never_reuse_native_results_or_expose_aliases(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    model,manifest,_=asset_files(tmp_path);engine=FieldEngine(OnnxAsset(model,manifest))
    stream=io.BytesIO();Image.new('RGB',(40,40),(20,90,160)).save(stream,format='PNG');data=stream.getvalue()
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(engine.analyze,[data]*8))
    assert engine.invocations==8
    assert all(r['trace']['inference_calls']==1 and not r['trace']['reused_state'] for r in results)
    original=list(results[1]['logits']);results[0]['logits'][0]=999
    assert results[1]['logits']==original and engine.analyze(data)['logits']==original
    assert all(r['accepted'] is None and r['abstained'] for r in results)
