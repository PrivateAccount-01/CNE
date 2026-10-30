"""Build a real inference APK. A successful build is not device/parity evidence."""
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys,tempfile,urllib.request,zipfile
from pathlib import Path
from field_analyst.android_inference.prepare import prepare
from cne.platform.evidence import source_identity

GRADLE_VERSION='8.9'
GRADLE_SHA256='d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab'


def sha(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def gradle(cache):
    url=f'https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip'
    archive=cache/f'gradle-{GRADLE_VERSION}-bin.zip';cache.mkdir(parents=True,exist_ok=True)
    if not archive.exists():
        temporary=archive.with_suffix('.part')
        with urllib.request.urlopen(url,timeout=60) as source,temporary.open('wb') as output:
            shutil.copyfileobj(source,output,1024*1024)
        if sha(temporary)!=GRADLE_SHA256:raise ValueError('Gradle download checksum mismatch')
        temporary.replace(archive)
    if sha(archive)!=GRADLE_SHA256:raise ValueError('Cached Gradle checksum mismatch')
    directory=cache/f'gradle-{GRADLE_VERSION}'
    if not directory.exists():
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not (cache/name).resolve().is_relative_to(cache.resolve()):raise ValueError('Unsafe Gradle archive path')
            bundle.extractall(cache)
    (cache/'download.json').write_text(json.dumps({'url':url,'version':GRADLE_VERSION,'sha256':GRADLE_SHA256},indent=2))
    command=directory/'bin'/('gradle.bat' if os.name=='nt' else 'gradle')
    if os.name!='nt':command.chmod(0o755)
    return command


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--abi',choices=['arm64-v8a','x86_64'],default='arm64-v8a')
    parser.add_argument('--sdk',default=os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT'))
    parser.add_argument('--build-python',required=True,help='Host Python 3.11 executable')
    parser.add_argument('--gradle',type=Path,help='Optional already verified Gradle 8.9 executable')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--with-parity-tests',action='store_true',help='Requires prepared registered test references')
    args=parser.parse_args();root=Path(__file__).resolve().parent;repo=root.parents[1]
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output=(args.output or repo/'artifacts/android-inference'/f'{stamp}-{args.abi}').resolve();output.mkdir(parents=True,exist_ok=False)
    before=source_identity(repo);report={'status':'INCOMPLETE','source_before':before,'abi':args.abi,'device_status':'NOT_TESTED','parity_status':'NOT_TESTED','steps':[]}
    try:
        sdk=Path(args.sdk) if args.sdk else Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk'
        if not (sdk/'platforms/android-35/android.jar').is_file():raise ValueError('Android SDK platform 35 required')
        version=subprocess.check_output([args.build_python,'-c','import sys;print(sys.version_info[:2])'],text=True).strip()
        if version!='(3, 11)':raise ValueError('Host build Python must be 3.11')
        prepare(repo)
        if args.with_parity_tests and not (root/'generated/test-assets/references.json').exists():raise ValueError('Run prepare_references using the registered protocol first')
        stage=Path(tempfile.mkdtemp(prefix='cne-android-'))
        report['stage']=str(stage)
        shutil.copytree(root,stage,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.gradle','build','__pycache__','local.properties'))
        (stage/'local.properties').write_text('sdk.dir='+sdk.resolve().as_posix()+'\n')
        command=args.gradle or gradle(repo/'artifacts/forensic/android-toolchain')
        tasks=['assembleDebug']+(['assembleDebugAndroidTest'] if args.with_parity_tests else [])
        cmd=[str(command),'-p',str(stage),f'-PbuildPython={args.build_python}',f'-PtargetAbi={args.abi}','--no-daemon','--console=plain','--write-verification-metadata','sha256',*tasks]
        with (output/'build.log').open('wb') as log:result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
        report['steps'].append({'command':cmd,'exit_code':result.returncode})
        if result.returncode:raise RuntimeError('Gradle build failed; see build.log')
        apks=[]
        for apk in sorted((stage/'app/build/outputs/apk').rglob('*.apk')):
            target=output/apk.name;shutil.copyfile(apk,target)
            apks.append({'path':str(target),'sha256':sha(target),'bytes':target.stat().st_size})
        if not apks:raise ValueError('Build returned success without APKs')
        for rel in ['generated/assets/bundle.json','gradle/verification-metadata.xml']:
            if (stage/rel).is_file():shutil.copyfile(stage/rel,output/Path(rel).name)
        report.update(status='BUILT_DEVICE_AND_PARITY_UNVERIFIED',apks=apks)
    except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        report['source_after']=source_identity(repo)
        if report['source_after']!=before:report.update(status='INCOMPLETE',source_changed=True)
        (output/'build-report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'status':report['status'],'report':str(output/'build-report.json')}))
    return 0 if report['status']=='BUILT_DEVICE_AND_PARITY_UNVERIFIED' else 1


if __name__=='__main__':raise SystemExit(main())
