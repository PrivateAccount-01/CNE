"""Build and test base/runtime wheel installs outside repository in clean, non-inheriting venvs."""
import argparse,json,os,subprocess,sys,time,venv,zipfile
from pathlib import Path
from cne.platform.ci_runner import SMOKE
from cne.platform.evidence import source_identity

def run(root,output):
    root=Path(root).resolve();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False);rows=[];source_before=source_identity(root)
    def stage(name,args):
        start=time.perf_counter()
        with (out/(name+'.log')).open('wb') as stream:r=subprocess.run([str(x) for x in args],cwd=out,stdout=stream,stderr=subprocess.STDOUT)
        rows.append({'name':name,'command':[str(x) for x in args],'exit_code':r.returncode,'elapsed_s':time.perf_counter()-start})
        if r.returncode:raise RuntimeError(name+' failed; inspect '+str(out/(name+'.log')))
    failure=None
    try:
        stage('build-wheel',[sys.executable,'-m','pip','wheel','--no-deps',root,'--wheel-dir',out/'wheel'])
        wheel=next((out/'wheel').glob('cne-*.whl'))
        with zipfile.ZipFile(wheel) as z:
            names=z.namelist()
            if 'field_analyst/onnx_asset.py' not in names:raise ValueError('Product module absent from wheel')
            forbidden=('field_analyst/data/','field_analyst/runs/','field_analyst/deploy/','field_analyst/.venv/','field_analyst/reports/')
            if any(n.startswith(forbidden) for n in names):raise ValueError('Development/research artifacts leaked into runtime wheel')
            (out/'wheel-members.json').write_text(json.dumps(names,indent=2),encoding='utf8')
        for profile in ('base','runtime'):
            # Match python -m venv's platform policy. Copying a relocatable
            # standalone POSIX interpreter can lose its stdlib (/install).
            env=out/profile;venv.EnvBuilder(with_pip=True,system_site_packages=False,symlinks=os.name!='nt').create(env);python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            spec=str(wheel)+('[field-runtime]' if profile=='runtime' else '')
            stage(profile+'-install',[python,'-m','pip','install',spec]);stage(profile+'-pip-check',[python,'-m','pip','check'])
            stage(profile+'-schema',[python,'-I','-c',SMOKE])
            if profile=='runtime':
                code="import field_analyst,field_analyst.engine,field_analyst.onnx_asset,onnxruntime; import importlib.util; assert importlib.util.find_spec('torch') is None; print(onnxruntime.get_available_providers())"
                stage('runtime-imports-no-torch',[python,'-I','-c',code]);stage('runtime-installed-cli',[python,'-I','-m','field_analyst','--help'])
    except (OSError,ValueError,RuntimeError,StopIteration,subprocess.SubprocessError) as exc:failure=str(exc)
    source_after=source_identity(root)
    if source_before!=source_after:failure='Source changed while building/testing wheel'
    report={'status':'FAILED' if failure else 'PASSED','source':source_after,'source_before':source_before,'stages':rows,'failure':failure,'python':sys.version,'contract':'clean wheel installs; no system-site-packages; isolated imports from outside repository'}
    (out/'install-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps({'status':report['status'],'failure':failure}));return 1 if failure else 0

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--output',required=True);a=p.parse_args();return run(a.root,a.output)
if __name__=='__main__':raise SystemExit(main())
