import csv, io, json, urllib.parse, urllib.request
from pathlib import Path
from field_analyst import LABELS
from field_analyst.dataset import digest, immutable
root=Path('field_analyst/reports/grouping-review');root.mkdir(parents=True,exist_ok=True)
api=json.load(urllib.request.urlopen('https://api.github.com/repos/spMohanty/PlantVillage-Dataset/commits/master',timeout=60));revision=api['sha']
records={}
for f in ['leaf_grouping/aggregate_map.py','leaf_grouping/create_map.py']+['leaf_grouping/filtered_leafmaps/'+l+'.csv' for l in LABELS]:
    data=urllib.request.urlopen('https://raw.githubusercontent.com/spMohanty/PlantVillage-Dataset/'+revision+'/'+urllib.parse.quote(f),timeout=60).read()
    name=Path(f).name+('.txt' if f.endswith('.py') else '');immutable(root/name,data);records[f]=digest(data)
report={'revision':revision,'files_sha256':records,'evidence':'aggregate_map.py constructs class:::Leaf # identities from File Name and Leaf # columns in filtered CSVs; repeated original leaf numbers are real upstream group metadata.',
        'semantics':'Original leaf number, namespaced by source and class; no inferred filename-as-leaf grouping.',
        'result':'PARTIAL: validates semantics of mapped leaf IDs, does not fill absent entries. 1582 selected-color images unmatched in pinned HF lookup. Original CSV examples confirm at least one filename changed from a conflicted-copy name. Unmapped healthy GH_HL Leaf entries cannot be assigned by assumption.',
        'reviewer':'Codex source inspection','training_status':'BLOCKED; official selected-class test membership must not be silently modified'}
immutable(root/'review.json',(json.dumps(report,indent=2)+'\n').encode());print(json.dumps(report,indent=2))
