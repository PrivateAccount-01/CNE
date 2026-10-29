"""Pre-metric cross-source candidate screening against all used PV partitions including quarantine."""
import json
from pathlib import Path
from field_analyst.cohort import NearIndex
from field_analyst.dataset import image_rgb,dhash,safe_path,digest,canonical,immutable

def main():
    root=Path('field_analyst/data');inventory=json.loads((root/'cohort-v1/official-inventory.json').read_text());index=NearIndex();hashes={}
    for r in inventory:
        data=safe_path(root,r['path']).read_bytes()
        if digest(data)!=r['sha256']:raise ValueError('PV source changed')
        try:fp=dhash(image_rgb(data))
        except Exception:continue
        index.add(fp,r);hashes.setdefault(r['sha256'],[]).append(r)
    pdroot=root/'plantdoc-safe';items=json.loads((pdroot/'image-provenance.json').read_text());eligible=[];quarantined=[];candidates=[]
    for item in items:
        if item['decode_status']!='PASS':quarantined.append(dict(item,reason='decode rejection'));continue
        data=safe_path(pdroot,item['path']).read_bytes()
        if digest(data)!=item['sha256']:raise ValueError('PlantDoc source changed')
        matches=index.query(dhash(image_rgb(data)));exact=hashes.get(item['sha256'],[])
        if matches or exact:
            quarantined.append(dict(item,reason='Unresolved cross-source exact/near candidate'))
            candidates.append({'plantdoc_path':item['original_path'],'pv_paths':sorted({r['path'] for r in matches+exact}),'resolution':'quarantined without metric inspection'})
        else:eligible.append(item)
    report={'status':'CANDIDATE_SCREEN_COMPLETE_NOT_GROUP_OR_RIGHTS_CERTIFIED','scope':'all6627 selected-four-class PV images, all official train/test including quarantined; other PV classes were not used for training and not screened',
            'method':'exact SHA256 plus dHash Hamming<=4; unresolved candidates excluded; not proof of no near overlap',
            'eligible_images':len(eligible),'quarantined_images':len(quarantined),'candidates':candidates,'eligible':eligible,'quarantined':quarantined,
            'field_role':'evaluation only; mapping pre-registered; original-image/leaf groups and source-item rights remain UNVERIFIED; provisional evidence only'}
    immutable(root/'plantdoc-screen.json',(canonical(report)+'\n').encode());Path('field_analyst/reports/crosssource-screen.json').write_text(json.dumps({k:v for k,v in report.items() if k not in ('eligible','quarantined')},indent=2));print('eligible',len(eligible),'quarantined',len(quarantined),flush=True)
if __name__=='__main__':main()
