"""Resumable bounded parallel download of pinned data; verify ranges and full SHA-256."""
import concurrent.futures,hashlib,json,time,urllib.request
from pathlib import Path
from field_analyst.sources import BASE
SIZE=2184723441
SHA='fba30c6a7965e49be94b47a62f8aff6cfb1c35c27f475f22092b56db41745e84'
CHUNK=8*1024*1024

def main():
    root=Path('field_analyst/data');target=root/'data.zip';parts=root/'archive-parts';parts.mkdir(exist_ok=True)
    begun=time.perf_counter();count=(SIZE+CHUNK-1)//CHUNK
    def part(index):
        start=index*CHUNK;end=min(SIZE,start+CHUNK)-1;path=parts/f'{index:04d}.part'
        if path.exists() and path.stat().st_size==end-start+1:return path
        for attempt in range(5):
            try:
                # Distinct query avoids proxy/CDN reusing an unrelated cached range response.
                req=urllib.request.Request(BASE+f'data.zip?part={index}',headers={'Range':f'bytes={start}-{end}'})
                with urllib.request.urlopen(req,timeout=60) as src:
                    if src.status!=206 or src.headers.get('Content-Range')!=f'bytes {start}-{end}/{SIZE}':raise ValueError('Server range mismatch')
                    with path.open('wb') as out:
                        while data:=src.read(256*1024):out.write(data)
                if path.stat().st_size!=end-start+1:raise ValueError('Part size mismatch')
                return path
            except Exception as e:
                print(f'part={index} attempt={attempt+1} error={type(e).__name__}: {e}',flush=True)
                if attempt==4:raise
    if not target.exists():
        # Reuse only completely downloaded chunks from the previous sequential attempt.
        sequential=root/'data.zip.part'
        if sequential.exists():
            with sequential.open('rb') as f:
                for i in range(sequential.stat().st_size//CHUNK):
                    p=parts/f'{i:04d}.part';data=f.read(CHUNK)
                    if not p.exists():p.write_bytes(data)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(part,i) for i in range(count)]
            for done,future in enumerate(concurrent.futures.as_completed(futures),1):
                future.result()
                if done%8==0:print(f'parts_complete={done}/{count} elapsed_s={time.perf_counter()-begun:.1f}',flush=True)
        temp=root/'data.zip.assembling'
        with temp.open('wb') as out:
            for i in range(count):
                with (parts/f'{i:04d}.part').open('rb') as src:
                    while data:=src.read(1024*1024):out.write(data)
        with temp.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
        if sha!=SHA:raise ValueError('Checksum mismatch; keep parts for inspection, do not use archive')
        temp.replace(target)
    with target.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    report={'path':str(target.resolve()),'bytes':target.stat().st_size,'sha256':sha,'expected_sha256':SHA,'verified':sha==SHA,'elapsed_s':time.perf_counter()-begun,'source_url':BASE+'data.zip'}
    Path('field_analyst/reports/archive-download.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)
    if sha!=SHA:raise ValueError('Archive checksum mismatch')
if __name__=='__main__':main()
