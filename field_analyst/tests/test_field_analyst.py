"""Offline audit/training fixtures only. No synthetic quality evidence."""
import csv, io, json, random
from pathlib import Path
import pytest
from PIL import Image
from field_analyst import LABELS
from field_analyst.dataset import *
from field_analyst.engine import FieldEngine
from field_analyst.records import Records
from field_analyst.metrics import metrics, select_threshold

def photo(seed=0):
    rng=random.Random(seed); image=Image.frombytes('RGB',(32,32),rng.randbytes(32*32*3))
    buf=io.BytesIO(); image.save(buf,format='PNG'); return buf.getvalue()

def fixture(tmp_path):
    rows=[]
    for split in ('train','validation','test'):
        for label in LABELS:
            for i in range(2):
                index=len(rows); data=photo(index); name=f'{index}.png'; (tmp_path/name).write_bytes(data)
                rows.append(dict(path=name,label=label,group_id=f'plantvillage:{index}',split=split,source='plantvillage',source_revision='fixture',sha256=digest(data)))
    meta={'grouping_status':'verified','grouping_evidence':'SYNTHETIC CODE FIXTURE ONLY',
          'sources':{'plantvillage':dict(revision='fixture',license='fixture',attribution='fixture',rights_status='fixture')},
          'official_test_paths':sorted(r['path'] for r in rows if r['split']=='test')}
    write_manifest(tmp_path/'manifest.csv',rows); (tmp_path/'metadata.json').write_text(json.dumps(meta))
    return rows,meta

def run_audit(tmp_path): return audit(tmp_path,tmp_path/'manifest.csv',tmp_path/'metadata.json')
def rewrite(tmp_path,rows):
    (tmp_path/'manifest.csv').unlink(); write_manifest(tmp_path/'manifest.csv',rows)

def test_valid_manifest_and_immutability(tmp_path):
    rows,meta=fixture(tmp_path); before=(tmp_path/'manifest.csv').read_bytes(); write_manifest(tmp_path/'manifest.csv',list(reversed(rows)))
    assert before==(tmp_path/'manifest.csv').read_bytes(); assert run_audit(tmp_path)['status']=='PASS'
    with pytest.raises(ValueError,match='Immutable'): write_manifest(tmp_path/'manifest.csv',rows[:-1])

@pytest.mark.parametrize('attack',['group','exact','corrupt','hash','fallback','revision','path','testlist','missingclass','duplicatepath','label'])
def test_audit_rejects(tmp_path,attack):
    rows,meta=fixture(tmp_path)
    if attack=='group': rows[8]['group_id']=rows[0]['group_id']
    elif attack=='exact': rows[8]['path']='copied.png'; (tmp_path/'copied.png').write_bytes((tmp_path/'0.png').read_bytes()); rows[8]['sha256']=rows[0]['sha256']
    elif attack=='corrupt': (tmp_path/'0.png').write_bytes(b'bad'); rows[0]['sha256']=digest(b'bad')
    elif attack=='hash': (tmp_path/'0.png').write_bytes(photo(100))
    elif attack=='fallback': rows[0]['group_id']='plantvillage:fallback_x'
    elif attack=='revision': rows[0]['source_revision']='different'
    elif attack=='path': rows[0]['path']='../outside.png'
    elif attack=='testlist': meta['official_test_paths']=[]
    elif attack=='missingclass': rows=[r for r in rows if not (r['split']=='validation' and r['label']==LABELS[0])]
    elif attack=='duplicatepath': rows.append(dict(rows[0]))
    elif attack=='label': rows[0]['label']='Potato___healthy'
    rewrite(tmp_path,rows); (tmp_path/'metadata.json').write_text(json.dumps(meta)); assert run_audit(tmp_path)['status']=='FAIL'

def test_near_duplicate_requires_explicit_review(tmp_path):
    rows,_=fixture(tmp_path); image=image_rgb((tmp_path/'0.png').read_bytes()); b=io.BytesIO(); image.save(b,format='PNG',compress_level=0)
    data=b.getvalue(); (tmp_path/'8.png').write_bytes(data); rows[8]['sha256']=digest(data); rewrite(tmp_path,rows)
    report=run_audit(tmp_path); assert report['status']=='FAIL'; assert report['near_duplicate_candidates']
    decisions={c['id']:dict(decision='distinct',reviewer='unit-test-only',reason='fixture tests decision plumbing') for c in report['near_duplicate_candidates']}
    path=tmp_path/'decisions.json'; path.write_text(json.dumps(decisions))
    assert audit(tmp_path,tmp_path/'manifest.csv',tmp_path/'metadata.json',path)['status']=='PASS'

def test_group_split_keeps_test_and_groups():
    rows=[dict(group_id=f'p:{label}:{i}',label=label,split='train') for label in LABELS for i in range(10) for _ in range(2)]
    rows.append(dict(group_id='test',label=LABELS[0],split='test'))
    a=group_split(rows); assert a==group_split(rows); assert a[-1]==rows[-1]
    for g in {r['group_id'] for r in a}: assert len({r['split'] for r in a if r['group_id']==g})==1

def test_missing_group_class():
    with pytest.raises(ValueError,match='Insufficient'): group_split([])

class TrustedFixture:
    """Deterministic built-in unit fixture; not a real model/performance claim."""
    reusable=True
    identity='fixture-v1'
    def verify(self): pass
    def __call__(self,data): return [float(len(data)),0.,1.,2.]

def test_actual_cne_reuse_note_and_identity_invalidation():
    asset=TrustedFixture(); e=FieldEngine(asset); data=photo()
    first=e.analyze(data); again=e.analyze(data,note='new note')
    assert first['trace']['inference_calls']==1; assert again['trace']['reused_state']; assert e.invocations==1
    assert again['logits']==e.analyze(data,baseline=True)['logits']
    changed=e.analyze(photo(1)); assert not changed['trace']['reused_state']
    asset.identity='fixture-v2'; assert not e.analyze(data)['trace']['reused_state']
    assert e.analyze(data)['trace']['reused_state']
    asset.identity='fixture-v2-new-preprocessing'; assert not e.analyze(data)['trace']['reused_state']
    asset.identity='fixture-v2-new-label-map'; assert not e.analyze(data)['trace']['reused_state']

def test_native_effect_refuses_reuse():
    asset=TrustedFixture(); asset.reusable=False; e=FieldEngine(asset)
    assert not e.analyze(photo())['trace']['reused_state']; assert not e.analyze(photo())['trace']['reused_state']; assert e.invocations==2

def test_reject_bad_input_and_output():
    e=FieldEngine(TrustedFixture())
    with pytest.raises(Exception): e.analyze(b'not image')
    class Bad(TrustedFixture):
        def __call__(self,data): return [float('nan')]*4
    with pytest.raises(ValueError,match='Invalid model'): FieldEngine(Bad()).analyze(photo())

def test_restart_and_notes(tmp_path):
    path=tmp_path/'records.db'; s=Records(path); pid=s.create_plant('Tomato'); oid=s.add(pid,photo(),'first'); e=FieldEngine(TrustedFixture())
    s.analyze(oid,e); s.update_note(oid,'second'); s.analyze(oid,e); assert e.invocations==1; s.close()
    s=Records(path); h=s.history(pid); assert h[0]['note']=='second'; assert h[0]['result']['trace']['reused_state']; s.close()
    # CNE state is explicitly process-local; records survive, memo state is not persisted.
    assert FieldEngine(TrustedFixture()).analyze(photo())['trace']['inference_calls']==1

def test_calibration_missing_and_unknown():
    r=metrics([[10,0,0,0],[0,10,0,0]],[0,-1],.9)
    assert r['known_n']==1 and r['unknown_n']==1 and r['accuracy']==1
    assert r['operating_point']['unknown_false_accept']==1.; assert len(r['missing_classes'])==3
    assert r['multiclass_brier_sum']<.001
    assert 0<=select_threshold([[10,0,0,0]],[0])<=1
    with pytest.raises(ValueError): metrics([],[])
    with pytest.raises(ValueError): metrics([[0,0,0,0]],[5])

def test_training_fails_closed_before_download(tmp_path):
    from argparse import Namespace
    from field_analyst.train import train
    fixture(tmp_path); meta=json.loads((tmp_path/'metadata.json').read_text()); meta['grouping_status']='unverified'; (tmp_path/'metadata.json').write_text(json.dumps(meta))
    a=Namespace(epochs=1,batch_size=1,root=tmp_path,manifest=tmp_path/'manifest.csv',metadata=tmp_path/'metadata.json',resolutions=None)
    with pytest.raises(ValueError,match='audit failed'): train(a)

def test_returned_logits_cannot_mutate_core_state():
    engine=FieldEngine(TrustedFixture()); first=engine.analyze(photo()); first['logits'][0]=-999
    assert engine.analyze(photo())['logits'][0]!=-999

def test_torch_asset_integrity_and_preprocessing(tmp_path):
    import torch, torchvision
    from field_analyst.train import PREPROCESS, transform
    from field_analyst.engine import TorchAsset
    # Executable torch fixture, explicitly UNTRAINED; never shipped or evaluated as plant quality.
    module=torch.nn.Sequential(torch.nn.AdaptiveAvgPool2d((1,1)),torch.nn.Flatten(),torch.nn.Linear(3,4)).eval()
    path=tmp_path/'model.pt'; torch.jit.save(torch.jit.script(module),str(path))
    manifest={'format':'torchscript-desktop','sha256':digest(path.read_bytes()),'labels':list(LABELS),'preprocess':PREPROCESS,
              'runtime':{'torch':torch.__version__,'torchvision':torchvision.__version__,'device':'cpu'}}
    meta=tmp_path/'model.json'; meta.write_text(json.dumps(manifest)); asset=TorchAsset(path,meta)
    data=photo(); actual=asset(data)
    with torch.inference_mode(): reference=module(transform()(image_rgb(data)).unsqueeze(0))[0].tolist()
    assert actual==reference
    engine=FieldEngine(asset); assert engine.analyze(data)['logits']==actual
    assert not engine.analyze(data)['trace']['reused_state']; assert engine.invocations==2
    meta.write_text(json.dumps(dict(manifest,labels=list(reversed(LABELS)))))
    with pytest.raises(ValueError,match='mutated'): engine.analyze(data)
    with pytest.raises(ValueError,match='labels'): TorchAsset(path,meta)
    meta.write_text(json.dumps(manifest)); path.write_bytes(path.read_bytes()+b'tamper')
    with pytest.raises(ValueError,match='hash mismatch'): TorchAsset(path,meta)

def test_resume_consistency_with_synthetic_code_fixture(tmp_path,monkeypatch):
    import torch
    from argparse import Namespace
    import field_analyst.train as training
    # Synthetic fixture is solely checkpoint/recovery evidence, never crop/model quality.
    fixture(tmp_path)
    def small_model(pretrained=False):
        return torch.nn.Sequential(torch.nn.AdaptiveAvgPool2d((1,1)),torch.nn.Flatten(),torch.nn.Dropout(.2),torch.nn.Linear(3,4))
    monkeypatch.setattr(training,'model',small_model)
    def args(out,epochs,resume=None):
        return Namespace(epochs=epochs,batch_size=1,root=tmp_path,manifest=tmp_path/'manifest.csv',metadata=tmp_path/'metadata.json',resolutions=None,device='cpu',out=tmp_path/out,lr=.001,resume=resume)
    training.train(args('full',2));training.train(args('resumed',1));training.train(args('resumed',2,tmp_path/'resumed'/'last.pt'))
    full=torch.load(tmp_path/'full'/'last.pt',weights_only=False);resumed=torch.load(tmp_path/'resumed'/'last.pt',weights_only=False)
    for name,value in full['state'].items(): assert torch.equal(value,resumed['state'][name])
    with pytest.raises(ValueError,match='lineage'):
        a=args('resumed',3,tmp_path/'resumed'/'last.pt');a.lr=.01;training.train(a)

def test_exif_orientation_and_unsupported_animation():
    image=Image.new('RGB',(12,20));exif=Image.Exif();exif[274]=6
    stream=io.BytesIO();image.save(stream,format='JPEG',exif=exif)
    assert image_rgb(stream.getvalue()).size==(20,12)
    stream=io.BytesIO();image.save(stream,format='GIF',save_all=True,append_images=[Image.new('RGB',(12,20),'white')])
    with pytest.raises(ValueError,match='animated'):image_rgb(stream.getvalue())

def test_partition_identity_permits_only_new_external_evaluation():
    from field_analyst.train import partition_hashes
    original=[dict(path='a',source='pv',split='train'),dict(path='b',source='pv',split='test')]
    extra=original+[dict(path='c',source='field',split='field_test')]
    assert partition_hashes(original)==partition_hashes(extra)
    changed=[dict(original[0],path='swapped'),original[1]]
    assert partition_hashes(original)!=partition_hashes(changed)

def test_pinned_source_cache_tampering_is_rejected(tmp_path,monkeypatch):
    import field_analyst.sources as source
    monkeypatch.setattr(source,'fetch',lambda *a,**k:b'tampered cached source metadata')
    with pytest.raises(ValueError,match='integrity mismatch'):source.inspect(tmp_path)

def cohort_fixture(tmp_path,monkeypatch):
    rows,meta=fixture(tmp_path)
    for row in rows:
        original=row['path'];row['path']='raw/color/'+row['label']+'/'+original
        target=tmp_path/row['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((tmp_path/original).read_bytes())
    rewrite(tmp_path,rows)
    inventory=[dict(r,split='train' if r['split']=='validation' else r['split']) for r in rows]
    immutable(tmp_path/'inventory.json',canonical(inventory).encode());immutable(tmp_path/'quarantine.json',b'[]')
    import field_analyst.sources as source
    proof=[{k:v for k,v in r.items() if k!='sha256'} for r in inventory]
    monkeypatch.setattr(source,'inspect',lambda root:(proof,{}))
    expected={}
    for split in ('train','test'):
        data=('\n'.join(r['path'] for r in inventory if r['split']==split)+'\n').encode();path=tmp_path/'source'/f'splits_color_{split}.txt';path.parent.mkdir(exist_ok=True);path.write_bytes(data);expected[f'splits/color_{split}.txt']=digest(data)
    monkeypatch.setattr(source,'METADATA_SHA256',expected)
    meta['official_test_paths']=sorted(r['path'] for r in inventory if r['split']=='test');meta['claim_scope']='RESTRICTED_VERIFIED_COHORT_ONLY fixture'
    meta['cohort']=dict(inventory='inventory.json',inventory_sha256=digest((tmp_path/'inventory.json').read_bytes()),quarantine='quarantine.json',quarantine_sha256=digest(b'[]'))
    (tmp_path/'metadata.json').write_text(json.dumps(meta));return rows,meta

def test_restricted_cohort_keeps_full_inventory(tmp_path,monkeypatch):
    rows,meta=cohort_fixture(tmp_path,monkeypatch);assert run_audit(tmp_path)['status']=='PASS'
    (tmp_path/'quarantine.json').write_text('[{}]');assert run_audit(tmp_path)['status']=='FAIL'

def test_cohort_cannot_invent_leaf_group_or_change_official_split(tmp_path,monkeypatch):
    rows,meta=cohort_fixture(tmp_path,monkeypatch)
    rows[0]['group_id']='plantvillage:invented';rewrite(tmp_path,rows)
    assert run_audit(tmp_path)['status']=='FAIL'

def test_same_verified_group_resolution_not_cross_group(tmp_path):
    rows,_=fixture(tmp_path);image=image_rgb((tmp_path/'0.png').read_bytes());b=io.BytesIO();image.save(b,format='PNG',compress_level=0)
    (tmp_path/'8.png').write_bytes(b.getvalue());rows[8]['sha256']=digest(b.getvalue());rewrite(tmp_path,rows)
    result=run_audit(tmp_path);resolutions={c['id']:dict(decision='same_verified_group',group_id=rows[0]['group_id'],reviewer='fixture',reason='adversarial false leaf claim') for c in result['near_duplicate_candidates']}
    p=tmp_path/'resolutions.json';p.write_text(json.dumps(resolutions));assert audit(tmp_path,tmp_path/'manifest.csv',tmp_path/'metadata.json',p)['status']=='FAIL'

def test_torch_free_preprocessing_parity_across_shapes():
    import numpy as np
    from field_analyst.preprocess import tensor
    from field_analyst.train import transform
    for shape in [(256,256),(333,201),(201,333),(450,601),(32,32)]:
        rng=random.Random(sum(shape));im=Image.frombytes('RGB',shape,rng.randbytes(shape[0]*shape[1]*3));b=io.BytesIO();im.save(b,format='PNG');data=b.getvalue()
        assert np.max(np.abs(tensor(data)-transform()(image_rgb(data)).unsqueeze(0).numpy()))<=1e-6
