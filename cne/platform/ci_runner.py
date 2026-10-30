"""Stdlib CI lifecycle: preserve first failure and real evidence, including setup/collection failure."""
from __future__ import annotations
import argparse,json,os,platform,subprocess,sys,time
from pathlib import Path
from cne.platform.evidence import build_evidence_report,source_identity
from cne.platform.frozen_integrity import verify_frozen

OPTIONAL_CORE_SKIPS={
 'cne/tests/platform/test_adversarial_cache_and_security.py::test_real_gguf_integration_when_configured':'NOT_TESTED:',
 'cne/tests/platform/test_remaining_components.py::test_sandbox_fails_closed_on_unsupported_host':'Linux worker tested by native integration probe',
}
SMOKE="""import cne.compiler.constrained_decoder; import cne.platform.runtime_config
import jsonschema
schema={'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}
jsonschema.validate({'count':1},schema)
try: jsonschema.validate({'count':'invalid'},schema)
except jsonschema.ValidationError: pass
else: raise AssertionError('Invalid schema instance accepted')
"""

def run_gate(root,output,paths,install_profile=None,integrity=True,allowed_skips=None):
    root=Path(root).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    stages=[];start=source_identity(root);first_failure=0;pytest_exit=None;begun=time.perf_counter()
    def stage(name,args,env=None,cwd=None):
        nonlocal first_failure
        t=time.perf_counter();log=output/(name+'.log')
        try:
            with log.open('wb') as stream:r=subprocess.run(args,cwd=cwd or root,env=env,stdout=stream,stderr=subprocess.STDOUT)
            code=r.returncode
        except OSError as error:code=127;log.write_text(str(error),encoding='utf8')
        stages.append({'name':name,'command':args,'exit_code':code,'elapsed_s':time.perf_counter()-t,'log':log.name})
        if code and not first_failure:first_failure=code
        return code
    if install_profile is not None:stage('install',[sys.executable,'-m','pip','install','-e',str(root)+'['+install_profile+']'])
    if not first_failure:stage('pip-check',[sys.executable,'-m','pip','check'])
    if not first_failure:stage('imports-and-schema',[sys.executable,'-I','-c',SMOKE],cwd=output)
    if not first_failure and integrity:
        result=verify_frozen(root);(output/'integrity.json').write_text(json.dumps(result,indent=2),encoding='utf8');code=0 if result['status']=='PASS' else 1
        stages.append({'name':'frozen-integrity','exit_code':code,'report':'integrity.json'})
        if code:first_failure=code
    common=[sys.executable,'-m','pytest',*paths,'--rootdir',str(root),'-p','cne.platform.pytest_inventory']
    expected=output/'expected-inventory.json';execution=output/'execution.json';junit=output/'junit.xml'
    if not first_failure:
        env=os.environ.copy();env['CNE_TEST_INVENTORY_PATH']=str(expected);env.pop('CNE_TEST_EXECUTION_PATH',None)
        stage('collect',common+['--collect-only','-q'],env=env)
    if not first_failure:
        env=os.environ.copy();env['CNE_TEST_INVENTORY_PATH']=str(output/'actual-collected.json');env['CNE_TEST_EXECUTION_PATH']=str(execution)
        pytest_exit=stage('tests',common+['-q','-rs','--junitxml='+str(junit)],env=env)
    report=build_evidence_report(root,' '.join(common),junit_path=junit,corpus_path=root/'cne/artifacts/p1_dataset/test_heldout_blind.jsonl' if integrity else None,
        full_suite=True,exit_code=pytest_exit,expected_inventory_path=expected,actual_inventory_path=execution,ci_run_id=os.environ.get('GITHUB_RUN_ID'),
        ci_job=os.environ.get('CNE_CI_JOB'),allowed_skips=allowed_skips)
    end=source_identity(root)
    if start!=end:
        report['issues'].append('Source changed during CI lifecycle');report['single_full_suite_pass']=False;report['status']='INCOMPLETE_OR_FAILED'
    if first_failure or not report['single_full_suite_pass']:
        report['single_full_suite_pass']=False;report['status']='INCOMPLETE_OR_FAILED';report['ci_commit_evidence']=False
    report.update(stages=stages,first_failure_exit_code=first_failure,source_before_install=start,elapsed_s=time.perf_counter()-begun,
                  setup_status='FAILED_OR_INCOMPLETE' if pytest_exit is None else 'TESTS_EXECUTED',suite_paths=paths)
    (output/'evidence.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf8')
    summary=['# CNE verification: '+report['status'],'','Source: '+str(report['source']),'Tests: '+str(report['test_counts_single_run']),
             'First failure exit: '+str(first_failure),'Pytest exit: '+str(pytest_exit),'','## Stages']
    summary.extend('- '+s['name']+': exit '+str(s['exit_code']) for s in stages)
    summary+=['','## Issues']+['- '+issue for issue in report['issues']]
    (output/'summary.md').write_text('\n'.join(summary)+'\n',encoding='utf8');print(json.dumps({'status':report['status'],'tests':report['test_counts_single_run'],'first_failure':first_failure,'issues':report['issues']}),flush=True)
    return first_failure or (0 if report['single_full_suite_pass'] else 1)

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--output',required=True);p.add_argument('--suite',choices=['core','field','runtime','combined'],default='core');p.add_argument('--install-profile');a=p.parse_args(argv)
    paths={'core':['cne/tests'],'field':['field_analyst/tests'],'runtime':['field_analyst/tests/test_onnx_runtime.py'],'combined':['cne/tests','field_analyst/tests']}[a.suite]
    return run_gate(a.root,a.output,paths,a.install_profile,integrity=True,allowed_skips=OPTIONAL_CORE_SKIPS if a.suite in ('core','combined') else {})
if __name__=='__main__':raise SystemExit(main())
