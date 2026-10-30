"""Inspect PlantDoc structure without using field images for model selection."""
import collections, json, subprocess, urllib.request
from pathlib import Path
from field_analyst.dataset import digest, immutable
REV='5467f6012d78d1c446145d5f582da6096f852ae8'
# Exact directory mapping, preregistered before any inference/metrics. Healthy is deliberately unmapped.
MAPPING={'Tomato Early blight leaf':'Tomato___Early_blight','Tomato leaf bacterial spot':'Tomato___Bacterial_spot','Tomato leaf late blight':'Tomato___Late_blight'}
def inspect(out):
    url=f'https://api.github.com/repos/pratikkayal/PlantDoc-Dataset/git/trees/{REV}?recursive=1'
    raw=urllib.request.urlopen(url,timeout=60).read();tree=json.loads(raw)
    if tree.get('truncated'):raise ValueError('Truncated source tree')
    counts=collections.Counter();paths=[]
    for item in tree['tree']:
        p=item['path'];parts=p.split('/')
        if item['type']=='blob' and p.lower().endswith(('.jpg','.jpeg','.png','.bmp')) and len(parts)>=3 and parts[0] in ('train','test'):
            counts[parts[0],parts[1]]+=1;paths.append({'path':p,'git_blob':item['sha'],'bytes':item.get('size'),'mapped_label':MAPPING.get(parts[1])})
    unknown_dirs=set(MAPPING)-{l for s,l in counts}
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    records={}
    for f in ('README.md','LICENSE.txt'):
        data=urllib.request.urlopen(f'https://raw.githubusercontent.com/pratikkayal/PlantDoc-Dataset/{REV}/{f}',timeout=60).read()
        immutable(root/f,data);records[f]=digest(data)
    report={'revision':REV,'role':'External field-like evaluation only; original train and test preserved as provenance; neither used for training/tuning',
            'mapping':MAPPING,'healthy_mapping':None,'mapping_status':'EXACT_DIRECTORY_NAMES_REVIEWED; image-level class suitability and rights NOT_REVIEWED',
            'missing_mapped_directories':sorted(unknown_dirs),'grouping_status':'UNVERIFIED: relationship between crops of same original image/leaf unknown',
            'rights_status':'README CC BY 4.0; internet-sourced images, source-item rights NOT_VERIFIED; no redistribution',
            'counts':[{'original_split':s,'source_label':l,'images':n,'mapped_label':MAPPING.get(l)} for (s,l),n in sorted(counts.items())],
            'image_items':paths,'source_hashes':records,'tree_sha256':digest(raw),
            'evaluation_status':'BLOCKED: image rights/grouping review, exact/near duplicate overlap audit and locked model required',
            'unknown_plan':'Separately curate non-tomato, unsupported tomato diseases, multi-leaf and blurred real captures; retain source/original-image groups; unknown_test only, no threshold tuning'}
    immutable(root/'inspection.json',(json.dumps(report,indent=2)+'\n').encode());return report
if __name__=='__main__':
    r=inspect('field_analyst/reports/plantdoc');print(json.dumps({k:v for k,v in r.items() if k!='image_items'},indent=2))
