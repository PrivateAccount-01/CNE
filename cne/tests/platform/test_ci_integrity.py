"""Synthetic integrity fixtures; production blind content is hashed, never inspected here."""
import hashlib,subprocess
from pathlib import Path
import pytest
from cne.platform.frozen_integrity import verify_frozen,FROZEN

def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE)

@pytest.fixture
def frozen(tmp_path):
    git(tmp_path,'init');(tmp_path/'.gitattributes').write_bytes(b'/frozen.jsonl text eol=lf\n');data=b'{"fixture":1}\n{"fixture":2}\n'
    (tmp_path/'frozen.jsonl').write_bytes(data);git(tmp_path,'add','.');git(tmp_path,'-c','user.name=Test fixture','-c','user.email=fixture@example.invalid','commit','--no-gpg-sign','-qm','fixture')
    reference={'frozen.jsonl':{'blob':git(tmp_path,'rev-parse','HEAD:frozen.jsonl').decode().strip(),'sha256':hashlib.sha256(data).hexdigest()}}
    return tmp_path,data,reference

def test_lf_and_autocrlf_checkout_obey_exact_policy(frozen):
    root,data,expected=frozen
    assert verify_frozen(root,attestations=expected)['status']=='PASS'
    git(root,'-c','core.autocrlf=true','checkout-index','--force','--','frozen.jsonl')
    assert (root/'frozen.jsonl').read_bytes()==data
    assert verify_frozen(root,attestations=expected)['status']=='PASS'
    (root/'frozen.jsonl').write_bytes(data.replace(b'\n',b'\r\n'))
    assert verify_frozen(root,attestations=expected)['status']=='FAIL'

@pytest.mark.parametrize('mutation',[lambda b:b.replace(b'1',b'9'),lambda b:b[:-1],lambda b:b+b'{"fixture":3}\n',lambda b:b''.join(reversed(b.splitlines(keepends=True)))])
def test_meaningful_byte_truncation_append_reordering_cannot_pass(frozen,mutation):
    root,data,expected=frozen;(root/'frozen.jsonl').write_bytes(mutation(data));assert verify_frozen(root,attestations=expected)['status']=='FAIL'

def test_changed_git_object_wrong_reference_and_missing_attributes_fail(frozen):
    root,data,expected=frozen
    assert verify_frozen(root,'definitely-not-a-ref',expected)['status']=='FAIL'
    (root/'.gitattributes').write_text('');assert verify_frozen(root,attestations=expected)['status']=='FAIL'
    (root/'.gitattributes').write_bytes(b'/frozen.jsonl text eol=lf\n');(root/'frozen.jsonl').write_bytes(data+b'corrupt')
    git(root,'add','.');git(root,'-c','user.name=Test fixture','-c','user.email=fixture@example.invalid','commit','--no-gpg-sign','-qm','changed synthetic asset')
    assert verify_frozen(root,attestations=expected)['status']=='FAIL'

def test_production_git_objects_and_historical_crlf_attestation():
    root=Path(__file__).resolve().parents[3]
    for rel,record in FROZEN.items():
        obj=git(root,'cat-file','blob',record['blob'])
        assert hashlib.sha256(obj).hexdigest()==record['sha256']
        assert hashlib.sha256(obj.replace(b'\n',b'\r\n')).hexdigest()==record['historical_crlf_sha256']

def test_default_version_allocation_optimization_preserves_exact_memo_identity():
    from dataclasses import FrozenInstanceError
    from cne.signature.memo_key import MemoKey,SystemVersions,DEFAULT_SYSTEM_VERSIONS
    from cne.semantic_ir.nodes import IRNode,OpKind,SemanticIRGraph
    graph=SemanticIRGraph();graph.add_node(IRNode('input',OpKind.OBSERVE,attributes={'source':'immutable_input'}));graph.root_id='input'
    implicit=MemoKey.from_graph(graph,env={'immutable_input':'first'})
    explicit=MemoKey.from_graph(graph,env={'immutable_input':'first'},versions=SystemVersions())
    assert implicit.serialized_identity==explicit.serialized_identity and implicit==explicit
    assert implicit.versions is DEFAULT_SYSTEM_VERSIONS
    assert MemoKey.from_graph(graph,env={'immutable_input':'other'})!=implicit
    assert MemoKey.from_graph(graph,env={'immutable_input':'first'},versions=SystemVersions(model_version='changed'))!=implicit
    with pytest.raises(FrozenInstanceError):DEFAULT_SYSTEM_VERSIONS.model_version='forbidden'

def test_memo_encoder_preserves_canonical_bytes_under_concurrency():
    import concurrent.futures,json
    from cne.signature.memo_key import _MEMO_JSON_ENCODER
    values=[{'value':i,'unicode':'leaf \u091f','nested':{'b':[True,None,.25],'a':'x'}} for i in range(40)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:actual=list(pool.map(_MEMO_JSON_ENCODER.encode,values))
    assert actual==[json.dumps(v,sort_keys=True) for v in values]

def test_memo_serialization_cache_tracks_every_current_projection():
    import json
    from cne.signature.memo_key import MemoKey,SystemVersions
    from cne.semantic_ir.nodes import IRNode,OpKind,SemanticIRGraph
    from cne.contracts.outcome_contract import OutcomeContract,ContractType
    graph=SemanticIRGraph();graph.add_node(IRNode('input',OpKind.OBSERVE,attributes={'source':'bytes'}));graph.root_id='input'
    contract=OutcomeContract(ContractType.EXACT);versions=SystemVersions();env={'bytes':'same-length-A'}
    first=MemoKey.from_graph(graph,env=env,contract=contract,versions=versions,dependency_snapshot={'image':1})
    again=MemoKey.from_graph(graph,env=env,contract=contract,versions=versions,dependency_snapshot={'image':1})
    assert first==again and first.serialized_identity==again.serialized_identity
    assert again.serialized_identity==json.dumps(json.loads(again.serialized_identity),sort_keys=True)
    assert MemoKey.from_graph(graph,env={'bytes':'same-length-B'},contract=contract,versions=versions,dependency_snapshot={'image':1})!=first
    assert MemoKey.from_graph(graph,env=env,contract=contract,versions=versions,dependency_snapshot={'image':2})!=first
    assert MemoKey.from_graph(graph,env=env,contract=contract,versions=SystemVersions(runtime_version='different'),dependency_snapshot={'image':1})!=first
    contract.output_schema={'new':'schema'}
    assert MemoKey.from_graph(graph,env=env,contract=contract,versions=versions,dependency_snapshot={'image':1})!=first
    graph.add_node(IRNode('out',OpKind.EMIT,inputs=['input']));graph.root_id='out';graph.invalidate_structural_cache()
    changed=MemoKey.from_graph(graph,env=env,contract=contract,versions=versions,dependency_snapshot={'image':1})
    assert changed!=first


@pytest.mark.parametrize('field,value', [('tolerances',{'abs_tol':.9}),('decision_boundary',.7),('required_facts',{'new fact'}),('output_schema',{'changed':'schema'}),('constraints',[lambda x:False]),('provenance_requirements',{'source':'changed'})])
def test_mutable_contract_fields_change_memo_identity(field,value):
    from cne.signature.memo_key import MemoKey
    from cne.semantic_ir.nodes import IRNode,OpKind,SemanticIRGraph
    from cne.contracts.outcome_contract import OutcomeContract,ContractType
    graph=SemanticIRGraph();graph.add_node(IRNode('input',OpKind.OBSERVE,attributes={'source':'x'}));graph.root_id='input'
    contract=OutcomeContract(ContractType.EXACT)
    before=MemoKey.from_graph(graph,env={'x':'immutable'},contract=contract)
    setattr(contract,field,value)
    assert MemoKey.from_graph(graph,env={'x':'immutable'},contract=contract)!=before


def test_inplace_tolerance_mutation_changes_memo_identity():
    from cne.signature.memo_key import MemoKey
    from cne.semantic_ir.nodes import SemanticIRGraph
    from cne.contracts.outcome_contract import OutcomeContract,ContractType
    graph=SemanticIRGraph();contract=OutcomeContract(ContractType.APPROXIMATE_NUMERIC,tolerances={'abs_tol':.01})
    before=MemoKey.from_graph(graph,contract=contract)
    contract.tolerances['abs_tol']=.5
    assert MemoKey.from_graph(graph,contract=contract)!=before
