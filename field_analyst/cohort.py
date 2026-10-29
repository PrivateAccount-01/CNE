"""Build an explicitly restricted verified-leaf cohort; preserve full official inventory.
Unmapped images and every ambiguous near-match component are quarantined, never relabeled.
The full official test benchmark remains uncertified; subset evaluation is identified as such.
"""
import collections,hashlib,json,random,re,zipfile
from pathlib import Path
from field_analyst import LABELS
from field_analyst.dataset import canonical,digest,immutable,write_manifest,group_split,image_rgb,dhash,audit
from field_analyst.sources import inspect,PV_REVISION,METADATA_SHA256

class NearIndex:
    def __init__(self):self.root=None
    def query(self,value,radius=4):
        hits=[];stack=[self.root] if self.root else []
        while stack:
            key,items,children=stack.pop();distance=(key^value).bit_count()
            if distance<=radius:hits.extend(items)
            stack.extend(node for d,node in children.items() if distance-radius<=d<=distance+radius)
        return hits
    def add(self,value,item):
        if self.root is None:self.root=[value,[item],{}];return
        node=self.root
        while True:
            d=(node[0]^value).bit_count()
            if d==0:node[1].append(item);return
            if d not in node[2]:node[2][d]=[value,[item],{}];return
            node=node[2][d]

def prepare(root='field_analyst/data',out='field_analyst/data/cohort-v1'):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    mapped,source=inspect(root);lookup={r['path']:r for r in mapped}
    archive=root/'data.zip'
    with archive.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    if sha!='fba30c6a7965e49be94b47a62f8aff6cfb1c35c27f475f22092b56db41745e84':raise ValueError('Archive hash mismatch')
    inventory=[];fingerprints={};quarantine={}
    with zipfile.ZipFile(archive) as z:
        for split in ('train','test'):
            for rel in (root/'source'/f'splits_color_{split}.txt').read_text().splitlines():
                label=rel.split('/')[2]
                if label not in LABELS:continue
                entry=z.getinfo(rel)
                if entry.file_size>32*1024*1024 or entry.file_size/max(1,entry.compress_size)>1000:raise ValueError('Unsafe archive member')
                data=z.read(entry);immutable(root/rel,data)
                row=dict(lookup.get(rel,dict(path=rel,label=label,group_id='',split=split,source='plantvillage',source_revision=PV_REVISION)),sha256=digest(data))
                inventory.append(row)
                if not row['group_id']:quarantine[rel]='No unambiguous source leaf ID; never included in certified cohort'
                try:fingerprints[rel]=dhash(image_rgb(data))
                except Exception as exc:quarantine[rel]='Image decode/size rejection: '+str(exc)
    immutable(out/'official-inventory.json',(canonical(inventory)+'\n').encode())
    # All original official files retained; only a non-adaptive, premetric subset may train/evaluate.
    tree=NearIndex();collisions=[];excluded_groups=set()
    for row in inventory:
        path=row['path']
        if path not in fingerprints:continue
        for other in tree.query(fingerprints[path]):
            same_group=bool(row['group_id']) and row['group_id']==other['group_id'] and row['label']==other['label']
            if same_group:continue
            # Exact and perceptual candidates across different/unverified leaves are quarantined conservatively.
            pair=sorted([row['sha256'],other['sha256']]);key=digest(canonical(pair).encode())
            collisions.append({'id':key,'a':other['path'],'b':path,'hashes':pair,'resolution':'quarantine all affected verified leaf groups and both unknown items','method':'exact or 64-bit dHash radius 4'})
            for r in (row,other):
                quarantine[r['path']]='Unresolved cross-group exact/near match; conservative quarantine'
                if r['group_id']:excluded_groups.add(r['group_id'])
        tree.add(fingerprints[path],row)
    for row in inventory:
        if row['group_id'] in excluded_groups:quarantine[row['path']]='Entire source leaf group excluded due to near/exact-match collision'
    selected=[r for r in inventory if r['path'] not in quarantine]
    selected=group_split(selected)
    write_manifest(out/'manifest.csv',selected)
    quarantined=[dict(r,reason=quarantine[r['path']]) for r in inventory if r['path'] in quarantine]
    immutable(out/'quarantine.json',(canonical(quarantined)+'\n').encode())
    immutable(out/'near-candidates.json',(canonical(collisions)+'\n').encode())
    # Within-source-leaf candidate pairs are resolved by the original physical-leaf metadata, not guessed distinctness.
    resolutions={};tree=NearIndex()
    for row in selected:
        for other in tree.query(fingerprints[row['path']]):
            if row['sha256']==other['sha256']:continue
            pair=sorted([row['sha256'],other['sha256']]);key=digest(canonical(pair).encode())
            if row['group_id']!=other['group_id']:raise ValueError('Unresolved cross-group pair survived quarantine')
            resolutions[key]={'decision':'same_verified_group','group_id':row['group_id'],'reviewer':'source metadata verification',
                              'reason':'Both exact file names map to the same original source class:::Leaf #. Same group cannot cross partitions.'}
        tree.add(fingerprints[row['path']],row)
    immutable(out/'resolutions.json',(canonical(resolutions)+'\n').encode())
    rel_inventory=(out/'official-inventory.json').relative_to(root).as_posix();rel_quarantine=(out/'quarantine.json').relative_to(root).as_posix()
    meta={'seed':42,'grouping_status':'verified','grouping_evidence':{'revision':PV_REVISION,'semantics':'Unambiguous original class:::Leaf # entries only; no fallback IDs','review':'reports/grouping-review/review.json'},
          'claim_scope':'RESTRICTED_VERIFIED_COHORT_ONLY; NOT full official PlantVillage test; unmatched source images remain quarantined; no field/OOD generalization claim',
          'official_test_paths':sorted(r['path'] for r in inventory if r['split']=='test'),
          'cohort':{'inventory':rel_inventory,'inventory_sha256':digest((out/'official-inventory.json').read_bytes()),'quarantine':rel_quarantine,'quarantine_sha256':digest((out/'quarantine.json').read_bytes()),
                    'official_test_list_sha256':METADATA_SHA256['splits/color_test.txt'],'policy':'premetric exact/near candidates quarantined by full leaf group; verified same-leaf pairs retained within one split'},
          'sources':{'plantvillage':{'revision':PV_REVISION,'license':'CC BY-SA 3.0 per dataset card; upstream license assumption noted','attribution':'Mohanty, Hughes and Salathe (2016), PlantVillage','rights_status':'Local research use; source declaration retained; distribution rights unverified'}},
          'label_order':list(LABELS),'archive_sha256':sha}
    immutable(out/'metadata.json',(canonical(meta)+'\n').encode())
    report=audit(root,out/'manifest.csv',out/'metadata.json',out/'resolutions.json')
    report.update(original_selected_images=len(inventory),quarantined_images=len(quarantined),near_candidates=len(collisions),claim_scope=meta['claim_scope'])
    (out/'audit.json').write_text(json.dumps(report,indent=2));Path('field_analyst/reports/cohort-audit.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('near_duplicate_candidates','errors')},indent=2),flush=True)
    if report['status']!='PASS':raise ValueError('Cohort audit failed: '+canonical(report['errors'][:10]))
if __name__=='__main__':prepare()
