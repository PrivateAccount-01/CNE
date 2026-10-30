"""Exact frozen-asset integrity: Git blobs and execution checkout, no normalization on verification."""
from __future__ import annotations
import argparse,hashlib,json,subprocess
from pathlib import Path

FROZEN={
 'cne/artifacts/p1_dataset/test_heldout_blind.jsonl':{'blob':'233dac27fa029a26782e0fe269c20eca4a2363f8','sha256':'90bad5884125af7971318a8243be35e172679e73a86cbe5f2fbd0abf148f31ce','historical_crlf_sha256':'ed56f7665b1a05159460362f806cd56f712afedc948a0613c4024a2df309f3bd'},
 'cne/artifacts/p1_dataset/dataset_summary.json':{'blob':'870c30d59693d77903f102ce33fd6bac7de98593','sha256':'23d4052be450ccfa3ebee5cb36d600b0e3627762e963de3c9d1a0a013971b778','historical_crlf_sha256':'4c27bf9107c05dd68bed5d0209c7c0163e57ff622fa52c30fb8000e239ba1bf9'},
}

def sha(data):return hashlib.sha256(data).hexdigest()
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE)

def verify_frozen(root,reference='HEAD',attestations=None,require_attributes=True):
    root=Path(root).resolve();expected=FROZEN if attestations is None else attestations;records=[];errors=[]
    for rel,attestation in expected.items():
        record={'path':rel,'reference':reference,'expected_sha256':attestation['sha256']}
        try:
            path=(root/rel).resolve(strict=True)
            if not path.is_relative_to(root):raise ValueError('Frozen path escapes checkout')
            blob=git(root,'rev-parse',reference+':'+rel).decode().strip();obj=git(root,'cat-file','blob',blob);work=path.read_bytes()
            record.update(blob=blob,git_sha256=sha(obj),checkout_sha256=sha(work))
            if blob!=attestation['blob'] or sha(obj)!=attestation['sha256']:raise ValueError('Git object does not match attested frozen bytes')
            if b'\r' in obj:raise ValueError('Attested object is not canonical LF')
            if work!=obj:raise ValueError('Execution checkout differs from canonical Git bytes (including line endings)')
            if require_attributes:
                attrs=git(root,'check-attr','-z','text','eol','--',rel).decode().split('\0')
                actual={attrs[i+1]:attrs[i+2] for i in range(0,len(attrs)-1,3)}
                record['attributes']=actual
                if actual!={'text':'set','eol':'lf'}:raise ValueError('Frozen checkout attributes must explicitly require text eol=lf')
            record['status']='PASS'
        except (OSError,ValueError,subprocess.CalledProcessError) as exc:
            record['status']='FAIL';record['error']=str(exc);errors.append({'path':rel,'error':str(exc)})
        records.append(record)
    return {'status':'PASS' if records and not errors else 'FAIL','policy':'exact attested Git blobs AND exact LF execution checkout; no normalization during verification','records':records,'errors':errors}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--reference',default='HEAD');p.add_argument('--output');a=p.parse_args(argv)
    report=verify_frozen(a.root,a.reference)
    if a.output:
        path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
