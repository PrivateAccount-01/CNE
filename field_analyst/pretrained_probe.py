import torch,torchvision,hashlib,json
from pathlib import Path
from torchvision.models import MobileNet_V3_Small_Weights,mobilenet_v3_small
w=MobileNet_V3_Small_Weights.IMAGENET1K_V1
m=mobilenet_v3_small(weights=w);p=Path(torch.hub.get_dir())/'checkpoints'/Path(w.url).name
r={'kind':'IMAGENET_INITIALIZATION_NOT_TOMATO_TRAINED','url':w.url,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'torch':torch.__version__,'torchvision':torchvision.__version__,'preprocess':str(w.transforms())}
Path('field_analyst/reports/pretrained.json').write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
