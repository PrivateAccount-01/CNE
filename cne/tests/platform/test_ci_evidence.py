"""Adversarial evidence and real lifecycle tests; synthetic fixtures do not imply product quality."""
import copy,json,subprocess
from pathlib import Path
import pytest
from cne.platform.evidence import build_evidence_report,source_identity
from cne.platform.ci_runner import run_gate

@pytest.fixture
def evidence(tmp_path,monkeypatch):
    # Fixture repositories are not the GitHub checkout being tested. Tests which
    # exercise GitHub binding explicitly set the fixture SHA after construction.
    monkeypatch.delenv('GITHUB_SHA',raising=False)
    monkeypatch.delenv('GITHUB_RUN_ID',raising=False)
    def git(*args):return subprocess.check_output(['git','-C',str(tmp_path),*args],stderr=subprocess.PIPE)
    git('init');(tmp_path/'.gitignore').write_text('/artifacts/\n');(tmp_path/'sample.txt').write_text('synthetic source fixture')
    git('add','.');git('-c','user.name=Test fixture','-c','user.email=fixture@example.invalid','commit','--no-gpg-sign','-qm','fixture')
    out=tmp_path/'artifacts';out.mkdir();node='tests/test_fixture.py::test_ok';source=source_identity(tmp_path)
    expected=out/'expected.json';actual=out/'actual.json';junit=out/'junit.xml'
    expected.write_text(json.dumps([node]));junit.write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_fixture" name="test_ok"><properties><property name="cne_nodeid" value="'+node+'"/></properties></testcase></testsuite></testsuites>')
    execution={'schema':'cne-pytest-execution-2','source_start':source,'source_end':source,'collected':[node],'exit_code':0,'records':[{'nodeid':node,'phases':{phase:{'outcome':'passed','wasxfail':False} for phase in ('setup','call','teardown')}}]};actual.write_text(json.dumps(execution))
    return tmp_path,out,expected,actual,junit,execution

def report(fixture,**kw):
    root,out,expected,actual,junit,_=fixture
    return build_evidence_report(root,'synthetic pytest',junit_path=junit,full_suite=True,exit_code=kw.pop('exit_code',0),expected_inventory_path=expected,actual_inventory_path=actual,**kw)

def test_complete_source_bound_execution_passes(evidence,monkeypatch):
    monkeypatch.delenv('GITHUB_SHA',raising=False);r=report(evidence);assert r['single_full_suite_pass'];assert r['test_counts_single_run']['tests']==1;assert not r['ci_commit_evidence']

@pytest.mark.parametrize('target',['expected','actual','junit'])
def test_missing_evidence_is_incomplete_not_a_traceback(evidence,target):
    paths=dict(expected=evidence[2],actual=evidence[3],junit=evidence[4]);paths[target].unlink();r=report(evidence)
    assert not r['single_full_suite_pass'];assert r['issues']

@pytest.mark.parametrize('payload',['','<testsuites>','<anything/>','<testsuite tests="0"><testcase name="forged" classname="m"/></testsuite>'])
def test_malformed_partial_or_false_zero_junit_fails(evidence,payload):
    evidence[4].write_text(payload);assert not report(evidence)['single_full_suite_pass']

@pytest.mark.parametrize('attack',['empty-records','wrong-node','duplicate','partial-phase','xfail','skip-required','source','collected','exit','junit-identity'])
def test_execution_inventory_phase_skip_and_source_mismatch(evidence,attack):
    execution=copy.deepcopy(evidence[5]);phases=execution['records'][0]['phases']
    if attack=='empty-records':execution['records']=[]
    elif attack=='wrong-node':execution['records'][0]['nodeid']='different'
    elif attack=='duplicate':execution['records']*=2
    elif attack=='partial-phase':phases.pop('call')
    elif attack=='xfail':phases['call']['wasxfail']=True
    elif attack=='skip-required':
        phases['call']['outcome']='skipped';phases['call']['reason']='not installed'
        text=evidence[4].read_text().replace('skipped="0"','skipped="1"').replace('</properties>','</properties><skipped message="not installed"/>');evidence[4].write_text(text)
    elif attack=='source':execution['source_end']['commit']='another-commit'
    elif attack=='collected':execution['collected']=[]
    elif attack=='exit':execution['exit_code']=2
    elif attack=='junit-identity':evidence[4].write_text(evidence[4].read_text().replace('value="tests/test_fixture.py::test_ok"','value="forged"'))
    evidence[3].write_text(json.dumps(execution));assert not report(evidence)['single_full_suite_pass']

def test_nonzero_exit_and_mismatched_github_commit_not_green(evidence,monkeypatch):
    assert not report(evidence,exit_code=2)['single_full_suite_pass']
    monkeypatch.setenv('GITHUB_SHA','wrong');r=report(evidence,ci_run_id='123');assert not r['ci_commit_evidence'];assert not r['single_full_suite_pass']

def test_early_integrity_failure_retains_first_failure_and_missing_junit(evidence):
    root,out,*_=evidence;code=run_gate(root,out/'gate',['tests/absent.py'],integrity=True)
    result=json.loads((out/'gate/evidence.json').read_text());assert code!=0;assert result['first_failure_exit_code']!=0
    assert result['stages'][-1]['name']=='frozen-integrity'
    assert result['setup_status']=='FAILED_OR_INCOMPLETE';assert result['test_counts_single_run'] is None
    assert (out/'gate/summary.md').is_file();assert not (out/'gate/junit.xml').exists()

def test_explicit_optional_skip_stays_visible(evidence):
    execution=copy.deepcopy(evidence[5]);node=execution['records'][0]['nodeid'];execution['records'][0]['phases']['call']={'outcome':'skipped','reason':'OPTIONAL: licensed fixture absent','wasxfail':False}
    evidence[3].write_text(json.dumps(execution));evidence[4].write_text(evidence[4].read_text().replace('skipped="0"','skipped="1"').replace('</properties>','</properties><skipped message="OPTIONAL: licensed fixture absent"/>'))
    result=report(evidence,allowed_skips={node:'OPTIONAL: licensed fixture absent'});assert result['single_full_suite_pass'];assert result['status']=='PASSED_WITH_ALLOWED_SKIPS';assert result['test_counts_single_run']['skipped']==1

@pytest.mark.parametrize('malformed',[{'nodeid':7,'phases':{}},'invalid',{'nodeid':'n','phases':[]},{'nodeid':'n','phases':{'call':None}}])
def test_malformed_executed_record_fails_closed(evidence,malformed):
    execution=copy.deepcopy(evidence[5]);execution['records']=[malformed];evidence[3].write_text(json.dumps(execution));assert not report(evidence)['single_full_suite_pass']

def test_same_count_forged_expected_inventory_is_rejected(evidence):
    evidence[2].write_text(json.dumps(['tests/forged.py::test_other']));assert not report(evidence)['single_full_suite_pass']
