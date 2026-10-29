"""Pinned source inspection. Never execute downloaded dataset Python."""
import argparse, collections, json, re, urllib.request, zipfile
from pathlib import Path
from field_analyst import LABELS
from field_analyst.dataset import canonical, digest, immutable, write_manifest, group_split, safe_path
PV_REVISION='9e97599868962bd0079b8db4b7f1efa9185fa1e7'
BASE=f'https://huggingface.co/datasets/mohanty/PlantVillage/resolve/{PV_REVISION}/'
FILES=('README.md','plant_village.py','splits/color_train.txt','splits/color_test.txt','leaf_grouping/leaf-map.json')
METADATA_SHA256={
    'README.md':'9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb',
    'plant_village.py':'872c207c874ad96e3a2e470299abf67e82b15c66e23f9e4e5b1ed784c69567d8',
    'splits/color_train.txt':'c43e0205b321d1c929116f5df1842348ac1e5c4861306e081416785d3c439dbd',
    'splits/color_test.txt':'7a7257dcb5f9456feae6ae81248d29c28f45dc4cd41a00c13a5c5c198c5f2f8b',
    'leaf_grouping/leaf-map.json':'3b4b253683c6911744959a3870a92509b1faa1ee34e9f8585e21d0fe6337a25b',
}

def fetch(url,path,return_bytes=True):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        temporary=path.with_suffix(path.suffix+'.part')
        with urllib.request.urlopen(url,timeout=60) as src, temporary.open('wb') as out:
            while chunk:=src.read(1024*1024): out.write(chunk)
        temporary.replace(path)
    return path.read_bytes() if return_bytes else path

def inspect(root):
    root=Path(root); snapshots={}
    for f in FILES:
        snapshots[f]=fetch(BASE+f,root/'source'/f.replace('/','_'))
        if digest(snapshots[f])!=METADATA_SHA256[f]:
            raise ValueError(f'Pinned source metadata integrity mismatch: {f}')
    leaf_map=json.loads(snapshots['leaf_grouping/leaf-map.json']); rows=[]; failures=[]; counts=collections.Counter()
    for split in ('train','test'):
        for rel in snapshots[f'splits/color_{split}.txt'].decode().splitlines():
            parts=rel.split('/')
            if len(parts)!=4 or parts[1]!='color':
                failures.append({'path':rel,'reason':'Unexpected source path'}); continue
            label=parts[2]; counts[split,label]+=1
            if label not in LABELS: continue
            # Mirrors documented upstream lookup ONLY, never invent fallback IDs.
            name=parts[-1].replace('_final_masked','').split('___')[-1].split('copy')[0]
            name=re.sub(r'\.(jpg|png)$','',name,flags=re.I).strip().lower()
            choices=leaf_map.get(name,[])
            matches=[c for c in choices if c.startswith(label+':::')]
            if len(matches)!=1:
                failures.append({'path':rel,'reason':'Missing/ambiguous official leaf-map match','choices':choices}); continue
            rows.append({'path':rel,'label':label,'group_id':'plantvillage:'+matches[0], 'split':split,
                         'source':'plantvillage','source_revision':PV_REVISION})
    groups=collections.defaultdict(set)
    for r in rows: groups[r['group_id']].add(r['split'])
    overlap=[g for g,s in groups.items() if len(s)>1]
    report={'revision':PV_REVISION,'selected_labels':list(LABELS),'rejected_labels':sorted({l for s,l in counts if l not in LABELS}),
            'counts':[{'split':s,'label':l,'images':n} for (s,l),n in sorted(counts.items())],
            'matched_selected_images':len(rows),'group_count':len(groups),'group_overlap':overlap,'rejections':failures,
            'metadata_hashes':{f:digest(v) for f,v in snapshots.items()},
            'status':'BLOCKED' if failures or overlap else 'METADATA_MATCHED_GROUP_SEMANTICS_NEED_REVIEW',
            'grouping_note':'Upstream class:::leaf-number map is used without fallback. Physical-leaf semantics require review of original metadata.',
            'license':'CC BY-SA 3.0 per dataset card; loader itself says assuming generic open license, verify if possible.'}
    (root/'source-inspection.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return rows,report

def prepare(root,out,grouping_evidence):
    rows,report=inspect(root)
    if report['rejections'] or report['group_overlap']:
        raise ValueError('Source metadata has missing/ambiguous groups or official cross-split overlap; see source-inspection.json. No training manifest created.')
    if not grouping_evidence:
        raise ValueError('Original leaf grouping semantics must be reviewed; pass --grouping-evidence with a source-backed review file')
    review=json.loads(Path(grouping_evidence).read_text(encoding='utf-8-sig'))
    if review.get('revision')!=PV_REVISION or not all(review.get(k) for k in ('reviewer','evidence','semantics')):
        raise ValueError('Invalid grouping evidence')
    root=Path(root); archive=root/'data.zip'
    fetch(BASE+'data.zip',archive,return_bytes=False)
    # Hash in chunks; archive is >2GB.
    import hashlib
    h=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
    if h!='fba30c6a7965e49be94b47a62f8aff6cfb1c35c27f475f22092b56db41745e84':
        raise ValueError('Source archive SHA-256 mismatch')
    with zipfile.ZipFile(archive) as z:
        for r in rows:
            entry=z.getinfo(r['path'])
            if entry.file_size>32*1024*1024 or entry.file_size/max(1,entry.compress_size)>1000:
                raise ValueError('Unsafe zip member')
            data=z.read(entry); immutable(root/r['path'],data); r['sha256']=digest(data)
    official=sorted(r['path'] for r in rows if r['split']=='test')
    rows=group_split(rows); out=Path(out); write_manifest(out/'manifest.csv',rows)
    meta={'seed':42,'grouping_status':'verified','grouping_evidence':review,'official_test_paths':official,
          'sources':{'plantvillage':{'revision':PV_REVISION,'license':'CC BY-SA 3.0','attribution':'Mohanty, Hughes and Salathe (2016), PlantVillage',
                                    'rights_status':'Dataset card declaration; verify intended redistribution','url':BASE}},
          'source_inspection':report,'label_order':list(LABELS)}
    immutable(out/'metadata.json',(canonical(meta)+'\n').encode())

def main():
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['inspect','prepare']); p.add_argument('--root',required=True); p.add_argument('--out'); p.add_argument('--grouping-evidence')
    a=p.parse_args()
    if a.command=='inspect': print(json.dumps(inspect(a.root)[1],indent=2))
    else:
        if not a.out: p.error('--out required')
        prepare(a.root,a.out,a.grouping_evidence)
if __name__=='__main__': main()
