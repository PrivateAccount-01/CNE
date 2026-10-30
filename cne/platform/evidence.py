"""Single-run evidence; missing/malformed/partial inputs fail closed, never synthesize passes."""
from __future__ import annotations
import argparse,hashlib,json,os,platform,subprocess,time,uuid
from pathlib import Path
import xml.etree.ElementTree as ET

def _git(root,*args):
    try:return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL).decode().strip()
    except (OSError,subprocess.CalledProcessError):return None

def source_identity(root):
    root=Path(root).resolve();status=_git(root,'status','--porcelain')
    if status is None:return {'commit':None,'commit_tree':None,'dirty':None,'identity_error':'Not a readable Git checkout'}
    digest=hashlib.sha256()
    try:
        for tracked in (True,False):
            args=['git','-C',str(root),'ls-files','-z']
            if not tracked:args+=['--others','--exclude-standard']
            paths=subprocess.check_output(args,stderr=subprocess.DEVNULL).split(b'\0')
            for encoded in sorted(x for x in paths if x):
                path=root/os.fsdecode(encoded);digest.update((b'tracked:' if tracked else b'untracked:')+encoded+b'\0')
                if path.is_symlink():digest.update(b'link:'+os.fsencode(os.readlink(path)))
                elif path.is_file():digest.update(path.read_bytes())
                else:digest.update(b'MISSING')
    except (OSError,subprocess.CalledProcessError) as exc:
        return {'commit':_git(root,'rev-parse','HEAD'),'dirty':bool(status),'identity_error':str(exc)}
    return {'commit':_git(root,'rev-parse','HEAD'),'commit_tree':_git(root,'rev-parse','HEAD^{tree}'),'dirty':bool(status),
            'status_sha256':hashlib.sha256(status.encode()).hexdigest(),'working_tree_content_sha256':digest.hexdigest()}

def _junit_summary(path):
    if not path:return None,None
    root=ET.parse(path).getroot()
    if root.tag not in ('testsuite','testsuites'):raise ValueError('Unrecognized JUnit root')
    suites=[s for s in root.iter('testsuite') if not s.findall('testsuite')]
    if not suites:raise ValueError('JUnit contains no test suites')
    counts=dict(tests=0,failures=0,errors=0,skipped=0);ids=[]
    for suite in suites:
        cases=suite.findall('testcase');actual={k:sum(bool(c.find(k[:-1] if k in ('failures','errors') else k) is not None) for c in cases) for k in ('failures','errors','skipped')}
        actual['tests']=len(cases)
        for key in counts:
            declared=int(suite.get(key,'0'))
            if declared<0 or declared!=actual[key]:raise ValueError('JUnit declared counts disagree with actual cases: '+key)
            counts[key]+=declared
        for case in cases:
            if not case.get('name') or not case.get('classname'):raise ValueError('JUnit case identity missing')
            properties={p.get('name'):p.get('value') for p in case.findall('./properties/property')}
            ids.append(properties.get('cne_nodeid') or case.get('classname')+'::'+case.get('name'))
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate JUnit test identity')
    return counts,sorted(ids)

def build_evidence_report(root,command,junit_path=None,corpus_path=None,full_suite=False,exit_code=None,
                          expected_junit_path=None,expected_inventory_path=None,actual_inventory_path=None,
                          ci_run_id=None,ci_job=None,allowed_skips=None):
    root=Path(root).resolve();issues=[];source=source_identity(root);hashes={};counts=None;actual_ids=None;expected_ids=None;execution=None;inventory_matches=False
    def raw(path,label):
        if not path:issues.append(label+' not supplied');return None
        try:
            data=Path(path).read_bytes();hashes[label]=hashlib.sha256(data).hexdigest();return data
        except OSError as exc:issues.append(label+': '+str(exc));return None
    def decode(path,label):
        data=raw(path,label)
        if data is None:return None
        try:return json.loads(data)
        except (ValueError,UnicodeError) as exc:issues.append(label+' invalid JSON: '+str(exc));return None
    if raw(junit_path,'junit') is not None:
        try:counts,actual_ids=_junit_summary(junit_path)
        except (OSError,ValueError,ET.ParseError) as exc:issues.append('Malformed/partial JUnit: '+str(exc))
    if corpus_path:raw(corpus_path,'corpus')
    if expected_junit_path:
        try:_,expected_ids=_junit_summary(expected_junit_path)
        except (OSError,ValueError,ET.ParseError) as exc:issues.append('Expected JUnit invalid: '+str(exc))
    elif expected_inventory_path:expected_ids=decode(expected_inventory_path,'expected_inventory')
    if not isinstance(expected_ids,list) or any(not isinstance(x,str) for x in (expected_ids or [])) or len(expected_ids or [])!=len(set(expected_ids or [])):
        issues.append('Expected inventory must contain unique test IDs');expected_ids=None
    if actual_inventory_path:execution=decode(actual_inventory_path,'actual_inventory')
    if isinstance(execution,dict) and execution.get('schema')=='cne-pytest-execution-2':
        records=execution.get('records');collected=execution.get('collected')
        valid=isinstance(records,list) and isinstance(collected,list) and all(isinstance(n,str) for n in collected)
        valid=valid and all(isinstance(r,dict) and isinstance(r.get('nodeid'),str) and isinstance(r.get('phases'),dict)
                            and all(isinstance(p,dict) and p.get('outcome') in ('passed','failed','skipped') for p in r['phases'].values()) for r in (records or []))
        if not valid:issues.append('Malformed executed-test records');execution=None
    if isinstance(execution,dict) and execution.get('schema')=='cne-pytest-execution-2':
        collected=execution.get('collected');records=execution.get('records');records_ok=isinstance(records,list)
        recorded_ids=[r.get('nodeid') for r in records if isinstance(r,dict)] if records_ok else []
        inventory_matches=bool(expected_ids and isinstance(collected,list) and sorted(collected)==sorted(expected_ids)
                               and len(recorded_ids)==len(set(recorded_ids)) and sorted(recorded_ids)==sorted(expected_ids)
                               and actual_ids==sorted(expected_ids) and (counts or {}).get('tests')==len(expected_ids))
        if execution.get('source_start')!=execution.get('source_end') or execution.get('source_end')!=source:
            issues.append('Execution source changed or evidence belongs to a different source tree')
        if source.get('identity_error'):issues.append('Source identity unavailable')
        if execution.get('exit_code')!=exit_code:issues.append('Recorded pytest exit code mismatch')
        allowed_skips=allowed_skips or {};skipped=[];xfailed=[]
        for record in records if records_ok else []:
            phases=record.get('phases',{})
            if 'setup' not in phases:issues.append('Missing setup phase: '+str(record.get('nodeid')))
            if not phases or not any(k in phases for k in ('setup','call')):issues.append('Test was not executed: '+str(record.get('nodeid')))
            if any(p.get('outcome')=='failed' for p in phases.values()):issues.append('Executed phase failed: '+str(record.get('nodeid')))
            for phase in phases.values():
                if phase.get('wasxfail'):xfailed.append(record.get('nodeid'))
                if phase.get('outcome')=='skipped':
                    skipped.append(record.get('nodeid'));reason=str(phase.get('reason') or '');allowed=allowed_skips.get(record.get('nodeid'))
                    if not allowed or allowed not in reason:issues.append('Required test skipped: '+str(record.get('nodeid')))
            if phases.get('setup',{}).get('outcome')=='passed' and 'call' not in phases:issues.append('Missing test call phase: '+str(record.get('nodeid')))
            if phases.get('setup',{}).get('outcome')=='skipped' and 'call' in phases:issues.append('Impossible call after skipped setup: '+str(record.get('nodeid')))
            if 'teardown' not in phases:issues.append('Missing teardown phase: '+str(record.get('nodeid')))
        if xfailed:issues.append('xfail/xpass is not an accepted required gate result')
        if counts and counts['skipped']!=len(set(skipped)):issues.append('JUnit and execution skipped counts disagree')
    else:
        # Legacy expected-JUnit comparison remains readable but cannot attest actual execution.
        inventory_matches=bool(expected_ids is not None and actual_ids==sorted(expected_ids))
        issues.append('Source-bound executed-test record is missing or invalid')
    if not inventory_matches:issues.append('Collected/executed/JUnit test inventory mismatch')
    if not counts or not counts['tests']:issues.append('No actual tests executed')
    if counts and (counts['failures'] or counts['errors']):issues.append('JUnit reports failures/errors')
    if exit_code!=0:issues.append('Command did not succeed')
    github_sha=os.environ.get('GITHUB_SHA');ci_source_matches=bool(github_sha and source.get('commit')==github_sha and source.get('dirty') is False)
    if github_sha and not ci_source_matches:issues.append('GitHub commit/clean-source mismatch')
    passed=bool(full_suite and not issues)
    return {'schema':'cne-evidence-2','generated_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'run_id':uuid.uuid4().hex,'source':source,'command':command,
            'environment':{'python':platform.python_version(),'platform':platform.platform()},'junit_sha256':hashes.get('junit'),'corpus_sha256':hashes.get('corpus'),
            'test_counts_single_run':counts,'expected_test_counts':{'tests':len(expected_ids)} if expected_ids else None,'test_inventory_matches':inventory_matches,
            'test_inventory_sha256':{'expected':hashes.get('expected_inventory'),'actual':hashes.get('actual_inventory')},'pytest_exit_code':exit_code,
            'single_full_suite_pass':passed,'status':('PASSED_WITH_ALLOWED_SKIPS' if passed and counts['skipped'] else 'PASSED') if passed else 'INCOMPLETE_OR_FAILED',
            'issues':issues,'allowed_skip_policy':allowed_skips or {},'ci':{'run_id':ci_run_id,'job':ci_job,'commit':github_sha},'ci_source_matches':ci_source_matches,
            'ci_commit_evidence':bool(passed and ci_run_id and ci_source_matches)}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--command',required=True);p.add_argument('--junit',required=True);p.add_argument('--corpus');p.add_argument('--expected-junit');p.add_argument('--expected-inventory');p.add_argument('--actual-inventory');p.add_argument('--output',required=True);p.add_argument('--exit-code',required=True,type=int);p.add_argument('--full-suite',action='store_true');p.add_argument('--ci-job');a=p.parse_args(argv)
    report=build_evidence_report(a.root,a.command,a.junit,a.corpus,a.full_suite,a.exit_code,a.expected_junit,a.expected_inventory,a.actual_inventory,os.environ.get('GITHUB_RUN_ID'),a.ci_job)
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf8');print(json.dumps({'status':report['status'],'tests':report['test_counts_single_run'],'issues':report['issues']}));return 0 if report['single_full_suite_pass'] else 1
if __name__=='__main__':raise SystemExit(main())
