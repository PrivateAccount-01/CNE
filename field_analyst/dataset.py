"""Safe immutable manifests. Audit success is not a rights/grouping certification."""
from __future__ import annotations
import csv, hashlib, io, json, random, warnings
from collections import Counter, defaultdict
from pathlib import Path
from PIL import Image, ImageOps
from field_analyst import LABELS

FIELDS = ('path','label','group_id','split','source','source_revision','sha256')
SPLITS = {'train','validation','test','field_test','unknown_validation','unknown_test'}

def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    """Bounded-memory file hashing, including supported Python 3.10 hosts."""
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            result.update(chunk)
    return result.hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)

def immutable(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f'Immutable output differs: {path}; choose a new output directory')
    else:
        with path.open('xb') as out:
            out.write(data)

def safe_path(root, relative):
    root = Path(root).resolve(); rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or ':' in str(rel):
        raise ValueError('Unsafe dataset path')
    p = (root / rel).resolve(strict=True)
    if not p.is_relative_to(root) or not p.is_file():
        raise ValueError('Dataset path escapes root or is not a file')
    return p

def image_rgb(data):
    if len(data) > 32 * 1024 * 1024:
        raise ValueError('Image exceeds 32 MiB')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 25_000_000 or getattr(im, 'n_frames', 1) != 1:
                raise ValueError('Oversized or animated image')
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            return ImageOps.exif_transpose(im).convert('RGB').copy()

def dhash(image):
    gray = image.convert('L').resize((9, 8), Image.Resampling.LANCZOS)
    a = list(gray.getdata())
    return sum((a[y*9+x] > a[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))

def write_manifest(path, rows):
    stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
    writer.writeheader(); writer.writerows(sorted(rows, key=lambda r: (r['source'],r['path'])))
    immutable(path, stream.getvalue().encode())

def read_manifest(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != list(FIELDS):
            raise ValueError('Manifest schema mismatch')
        return list(reader)

def group_split(rows, fraction=.2, seed=42):
    """Only official train may be repartitioned. A group has exactly one class."""
    groups = defaultdict(list)
    for row in rows:
        if row['split'] == 'train':
            groups[row['group_id']].append(row)
    by_label = defaultdict(list)
    for group, members in sorted(groups.items()):
        labels = {m['label'] for m in members}
        if len(labels) != 1:
            raise ValueError('Conflicting group labels')
        by_label[members[0]['label']].append(group)
    selected = set(); rng = random.Random(seed)
    for label in LABELS:
        values = by_label[label]
        if len(values) < 2:
            raise ValueError(f'Insufficient train leaf groups: {label}')
        rng.shuffle(values); selected.update(values[:max(1, min(len(values)-1, round(len(values)*fraction)))])
    return [dict(r, split='validation') if r['split']=='train' and r['group_id'] in selected else dict(r) for r in rows]

def audit(root, manifest, metadata, resolutions=None):
    rows = read_manifest(manifest); meta = json.loads(Path(metadata).read_text(encoding='utf-8-sig'))
    errors = []; paths=set(); hashes=defaultdict(list); groups=defaultdict(set); fingerprints=[]
    counts=Counter(); leaves=defaultdict(set); dimensions=Counter()
    for row in rows:
        try:
            if not all(row.values()) or row['split'] not in SPLITS:
                raise ValueError('Missing identity or invalid split')
            if row['label'] not in LABELS and not (row['label']=='unknown' and row['split'].startswith('unknown_')):
                raise ValueError('Unsupported label/split combination')
            if not row['group_id'].startswith(row['source'] + ':') or any(s in row['group_id'].lower() for s in ('fallback','unknown','unverified')):
                raise ValueError('Unverified or non-namespaced leaf group')
            if row['path'] in paths:
                raise ValueError('Duplicate path')
            paths.add(row['path']); p=safe_path(root,row['path']); data=p.read_bytes()
            if digest(data)!=row['sha256']:
                raise ValueError('Image hash mismatch')
            im=image_rgb(data); dimensions[str(im.size)]+=1
            fingerprints.append((row, dhash(im)))
            hashes[row['sha256']].append(row); groups[row['group_id']].add(row['split'])
            counts[(row['split'],row['label'])]+=1; leaves[(row['split'],row['label'])].add(row['group_id'])
        except Exception as exc:
            errors.append({'path':row['path'],'reason':str(exc)})
    for h, members in hashes.items():
        if len({m['label'] for m in members}) > 1 or len({m['split'] for m in members}) > 1:
            errors.append({'hash':h,'reason':'Conflicting or cross-split exact duplicates'})
    for g, splits in groups.items():
        if len(splits)>1:
            errors.append({'group':g,'reason':'Group overlap'})
    # BK-tree Hamming radius search, rather than quadratic all-pairs image comparisons.
    tree=None; candidates=[]
    def visit(node, value, radius):
        if node is None: return []
        key, members, children=node; distance=(key^value).bit_count()
        hits=list(members) if distance<=radius else []
        for d, child in children.items():
            if distance-radius<=d<=distance+radius: hits.extend(visit(child,value,radius))
        return hits
    def insert(node, value, row):
        if node is None: return [value,[row],{}]
        distance=(node[0]^value).bit_count()
        if distance==0: node[1].append(row)
        else: node[2][distance]=insert(node[2].get(distance),value,row)
        return node
    for row, fp in fingerprints:
        for other in visit(tree,fp,4):
            # All possible collisions are reported, even within one partition.
            if row['sha256']==other['sha256']: continue
            pair=sorted([row['sha256'],other['sha256']]); key=digest(canonical(pair).encode())
            candidates.append({'id':key,'a':other['path'],'b':row['path'],'hashes':pair,
                               'same_group':row['group_id']==other['group_id'] and row['split']==other['split'],
                               'group_id':row['group_id'] if row['group_id']==other['group_id'] else None})
        tree=insert(tree,fp,row)
    decisions={} if resolutions is None else json.loads(Path(resolutions).read_text(encoding='utf-8-sig'))
    for c in candidates:
        decision=decisions.get(c['id'],{})
        accepted=decision.get('decision')=='distinct' or (decision.get('decision')=='same_verified_group' and c['same_group'] and decision.get('group_id')==c['group_id'])
        if not accepted or not decision.get('reviewer') or not decision.get('reason'):
            errors.append({'candidate':c['id'],'reason':'Unresolved near duplicate; quarantine/rebuild manifest or document distinct images'})
    if meta.get('grouping_status')!='verified' or not meta.get('grouping_evidence'):
        errors.append({'reason':'Source grouping semantics not verified'})
    for source in {r['source'] for r in rows}:
        record=meta.get('sources',{}).get(source,{})
        if not all(record.get(k) for k in ('revision','license','attribution','rights_status')):
            errors.append({'reason':f'Missing source/rights record: {source}'})
        if any(r['source_revision']!=record.get('revision') for r in rows if r['source']==source):
            errors.append({'reason':f'Source revision mismatch: {source}'})
    for split in ('train','validation'):
        for label in LABELS:
            if counts[split,label]<2 or len(leaves[split,label])<2:
                errors.append({'reason':f'Insufficient support: {split}/{label}; need 2 images and 2 groups'})
    official = meta.get('official_test_paths')
    actual = sorted(r['path'] for r in rows if r['source']=='plantvillage' and r['split']=='test')
    if 'cohort' in meta:
        try:
            cohort=meta['cohort']
            if not meta.get('claim_scope','').startswith('RESTRICTED_VERIFIED_COHORT_ONLY'):
                raise ValueError('Restricted cohort must explicitly limit its claims')
            blobs={}
            for key in ('inventory','quarantine'):
                data=safe_path(root,cohort[key]).read_bytes()
                if digest(data)!=cohort[key+'_sha256']:raise ValueError('Cohort record hash mismatch')
                blobs[key]=json.loads(data)
            inventory=blobs['inventory']; excluded=blobs['quarantine']
            from field_analyst.sources import inspect, METADATA_SHA256
            verified,_=inspect(root); verified={r['path']:r for r in verified}
            expected=[]
            for split in ('train','test'):
                raw=safe_path(root,'source/splits_color_'+split+'.txt').read_bytes()
                if digest(raw)!=METADATA_SHA256['splits/color_'+split+'.txt']:raise ValueError('Official source split tampering')
                expected.extend(p for p in raw.decode().splitlines() if p.split('/')[2] in LABELS)
            inv={r['path']:r for r in inventory}; exc={r['path']:r for r in excluded}
            if len(inv)!=len(inventory) or len(exc)!=len(excluded) or sorted(inv)!=sorted(expected):raise ValueError('Official inventory incomplete/duplicated')
            if set(inv)!=paths|set(exc) or paths&set(exc):raise ValueError('Active/quarantined inventory partition mismatch')
            for row in inventory:
                data=safe_path(root,row['path']).read_bytes()
                if digest(data)!=row['sha256']:raise ValueError('Original inventory image hash mismatch')
                if row['label']!=row['path'].split('/')[2]:raise ValueError('Original inventory label changed')
            for r in excluded:
                original={k:r[k] for k in FIELDS}
                if original!=inv[r['path']] or not r.get('reason'):raise ValueError('Unexplained quarantine or changed source record')
            for r in rows:
                original=inv[r['path']]; proof=verified.get(r['path'])
                if not proof or r['group_id']!=proof['group_id'] or r['label']!=proof['label']:raise ValueError('Active leaf not verified by original source map')
                if r['sha256']!=original['sha256'] or (proof['split']=='test' and r['split']!='test') or (proof['split']=='train' and r['split'] not in ('train','validation')):
                    raise ValueError('Cohort changed original split or content')
            actual=sorted(actual+[r['path'] for r in excluded if r['split']=='test'])
            if sorted(official or [])!=sorted(r['path'] for r in inventory if r['split']=='test'):raise ValueError('Full official test inventory changed')
        except Exception as exc:
            errors.append({'reason':'Invalid restricted cohort: '+str(exc)})
    if official is None or sorted(official)!=actual:
        errors.append({'reason':'Official selected-class test list changed/missing'})
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,'near_duplicate_candidates':candidates,
            'manifest_sha256':digest(Path(manifest).read_bytes()),'metadata_sha256':digest(Path(metadata).read_bytes()),
            'resolutions_sha256':digest(Path(resolutions).read_bytes()) if resolutions else None,
            'claim_scope':meta.get('claim_scope','Complete supplied manifest only; not an independent certification'),
            'counts':[{'split':s,'label':l,'images':n,'leaves':len(leaves[s,l])} for (s,l),n in sorted(counts.items())],
            'low_support_test_classes':[l for l in LABELS if counts['test',l]<30],
            'dimensions':dict(dimensions),'near_duplicate_method':'64-bit dHash Hamming <=4; candidate screening only; does not prove absence',
            'rights_note':'Audit validates records, not legal clearance or physical leaf identity.'}

def require_audit(root, manifest, metadata, resolutions=None):
    result=audit(root,manifest,metadata,resolutions)
    if result['status']!='PASS':
        raise ValueError('Dataset audit failed: '+canonical(result['errors'][:12]))
    return result
