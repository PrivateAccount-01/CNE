"""Fetch official PyPI wheels with bounded range downloads and published SHA-256."""
import concurrent.futures,hashlib,json,urllib.request
from pathlib import Path
PACKAGES={'onnx':'1.17.0','onnxruntime':'1.20.1','coloredlogs':'15.0.1','humanfriendly':'10.0','pyreadline3':'3.5.6'}
def main():
    root=Path('field_analyst/data/wheels');root.mkdir(exist_ok=True);records=[]
    for package,version in PACKAGES.items():
        metadata=json.load(urllib.request.urlopen(f'https://pypi.org/pypi/{package}/{version}/json',timeout=30))
        files=[f for f in metadata['urls'] if f['filename'].endswith('.whl') and ('cp312-cp312-win_amd64' in f['filename'] or 'none-any' in f['filename'])]
        if len(files)!=1:raise ValueError('Ambiguous/missing platform wheel '+package)
        f=files[0];path=root/f['filename'];chunk=512*1024;size=f['size'];count=(size+chunk-1)//chunk
        def get(i):
            start=i*chunk;end=min(size,start+chunk)-1
            for attempt in range(5):
                try:
                    req=urllib.request.Request(f['url'],headers={'Range':f'bytes={start}-{end}'})
                    with urllib.request.urlopen(req,timeout=60) as r:
                        if r.status!=206 or r.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':raise ValueError('Range mismatch')
                        data=r.read()
                    if len(data)!=end-start+1:raise ValueError('Size mismatch')
                    return data
                except Exception:
                    if attempt==4:raise
        if not path.exists():
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                data=list(pool.map(get,range(count)))
            path.write_bytes(b''.join(data))
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if sha!=f['digests']['sha256']:raise ValueError('PyPI wheel checksum mismatch')
        records.append({'name':package,'version':version,'filename':path.name,'sha256':sha,'url':f['url'],'bytes':path.stat().st_size});print('VERIFIED',path.name,flush=True)
    Path('field_analyst/reports/wheels.json').write_text(json.dumps(records,indent=2))
if __name__=='__main__':main()
