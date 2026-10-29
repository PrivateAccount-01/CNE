"""Recover Windows-incompatible PlantDoc paths from cloned Git objects.
Uses content-addressed destination filenames; preserves every original path and split.
Does not claim grouping, rights clearance, deduplication, or field quality.
"""
import argparse, json, subprocess
from pathlib import Path
from field_analyst.dataset import digest, immutable, image_rgb
from field_analyst.plantdoc import REV, MAPPING

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(a.out); root.mkdir(parents=True,exist_ok=True)
    head=subprocess.check_output(['git','-C',a.repo,'rev-parse','HEAD'],text=True).strip()
    if head!=REV:raise ValueError('PlantDoc revision mismatch')
    listing=subprocess.check_output(['git','-C',a.repo,'ls-tree','-rz','--full-tree','HEAD'])
    records=[]
    for entry in listing.split(b'\0'):
        if not entry:continue
        header,path=entry.split(b'\t',1); mode,kind,blob=header.decode().split();path=path.decode('utf8');parts=path.split('/')
        if kind!='blob' or len(parts)<3 or parts[0] not in ('train','test') or not path.lower().endswith(('.jpg','.jpeg','.png','.bmp')):continue
        if mode!='100644':raise ValueError('Unexpected source mode')
        data=subprocess.check_output(['git','-C',a.repo,'cat-file','blob',blob]);sha=digest(data)
        local='images/'+sha+Path(path).suffix.lower();immutable(root/local,data)
        record={'original_path':path,'original_split':parts[0],'source_label':parts[1],'canonical_label':MAPPING.get(parts[1]),'path':local,'sha256':sha,'git_blob':blob,'source_revision':head,'grouping_status':'UNVERIFIED','rights_status':'NOT_REVIEWED'}
        try:
            image=image_rgb(data);record['dimensions']=list(image.size);record['decode_status']='PASS'
        except Exception as exc:record['decode_status']='REJECTED';record['reason']=str(exc)
        records.append(record)
    immutable(root/'image-provenance.json',(json.dumps(records,indent=2)+'\n').encode())
    report={'revision':head,'images':len(records),'decode_rejections':[r for r in records if r['decode_status']!='PASS'],
            'matched_tomato_images':sum(r['canonical_label'] is not None for r in records),'status':'INSPECTED_NOT_EVALUATED','source_item_rights':'UNVERIFIED','grouping':'UNVERIFIED','cross_source_dedup':'BLOCKED until PlantVillage data available',
            'windows_recovery':'Git checkout failed on filenames containing ?; original Git blobs materialized under content hashes without modifying source or labels'}
    immutable(root/'inspection.json',(json.dumps(report,indent=2)+'\n').encode());print(json.dumps(report,indent=2))
if __name__=='__main__':main()
