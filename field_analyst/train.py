"""CPU-safe reproducible training, held-out evaluation and export; all data audit gated."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, random, subprocess, time
from pathlib import Path
import numpy as np
import torch, torchvision
from torch import nn
from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
from torchvision import transforms as T
from field_analyst import LABELS
from field_analyst.dataset import canonical, digest, image_rgb, safe_path, read_manifest, require_audit, immutable
from field_analyst.metrics import metrics, select_threshold
WEIGHTS=MobileNet_V3_Small_Weights.IMAGENET1K_V1
PREPROCESS={'version':'pv-rgb-exif-bilinear256-center224-imagenet-v1','resize_short':256,'crop':224,
            'mean':[.485,.456,.406],'std':[.229,.224,.225],'interpolation':'bilinear','exif_transpose':True}

def transform(train=False):
    if not train: return WEIGHTS.transforms()
    return T.Compose([T.RandomResizedCrop(224,scale=(.75,1.)),T.RandomHorizontalFlip(),T.ColorJitter(.15,.15,.1),T.ToTensor(),T.Normalize(PREPROCESS['mean'],PREPROCESS['std'])])

class Images(torch.utils.data.Dataset):
    def __init__(self,root,rows,train=False): self.root=root; self.rows=rows; self.transform=transform(train)
    def __len__(self): return len(self.rows)
    def __getitem__(self,i):
        r=self.rows[i]; data=safe_path(self.root,r['path']).read_bytes()
        if digest(data)!=r['sha256']: raise ValueError('Dataset changed after audit')
        return self.transform(image_rgb(data)), LABELS.index(r['label']) if r['label'] in LABELS else -1

def seed_all(seed,threads=2):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True); torch.set_num_threads(threads)

def model(pretrained=False):
    m=mobilenet_v3_small(weights=WEIGHTS if pretrained else None)
    m.classifier[-1]=nn.Linear(m.classifier[-1].in_features,len(LABELS)); return m

def infer(m,loader,device):
    m.eval(); logits=[]; ys=[]
    with torch.inference_mode():
        for x,y in loader: logits.append(m(x.to(device)).cpu().numpy()); ys.extend(y.tolist())
    if not logits: raise ValueError('Empty evaluation partition')
    return np.concatenate(logits),np.asarray(ys)

def atomic_save(value,path):
    temporary=Path(str(path)+'.tmp'); torch.save(value,temporary); os.replace(temporary,path)

def lineage(a, audit):
    return {'manifest_sha256':audit['manifest_sha256'],'metadata_sha256':audit['metadata_sha256'],
            'resolutions_sha256':audit['resolutions_sha256'],'labels':list(LABELS),'preprocess':PREPROCESS,
            'partitions':partition_hashes(read_manifest(a.manifest)),
            'seed':42,'batch_size':a.batch_size,'learning_rate':a.lr,'device':a.device,
            'freeze_features':getattr(a,'freeze_features',False),'threads':getattr(a,'threads',2),
            'claim_scope':audit.get('claim_scope'),
            'torch':torch.__version__,'torchvision':torchvision.__version__,'python':platform.python_version(),
            'code_sha256':digest(Path(__file__).read_bytes()),'dataset_code_sha256':digest(Path(__file__).with_name('dataset.py').read_bytes()),
            'determinism_limitations':'Same software/device only; no cross-platform bitwise guarantee'}

def partition_hashes(rows):
    return {split:digest(canonical(sorted([r for r in rows if r['split']==split],key=lambda r:(r['source'],r['path']))).encode())
            for split in ('train','validation','unknown_validation','test')}

def train(a):
    if a.epochs<1 or a.batch_size<1: raise ValueError('Positive epochs/batch size required')
    audit=require_audit(a.root,a.manifest,a.metadata,a.resolutions); rows=read_manifest(a.manifest)
    if a.device=='cuda' and not torch.cuda.is_available(): raise ValueError('CUDA unavailable; select --device cpu')
    seed_all(42,getattr(a,'threads',2)); device=torch.device(a.device); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    identity=lineage(a,audit); resume=torch.load(a.resume,map_location='cpu',weights_only=False) if a.resume else None
    if resume and resume['lineage']!=identity: raise ValueError('Resume lineage/config/code mismatch')
    if not resume and any(out.glob('*.pt')): raise ValueError('Existing run; use --resume or new --out')
    m=model(pretrained=not bool(resume)).to(device)
    if getattr(a,'freeze_features',False):
        for parameter in m.features.parameters():parameter.requires_grad_(False)
    optimizer=torch.optim.AdamW([p for p in m.parameters() if p.requires_grad],lr=a.lr)
    pretrained_path=Path(torch.hub.get_dir())/'checkpoints'/Path(WEIGHTS.url).name
    pretrained_hash=digest(pretrained_path.read_bytes()) if pretrained_path.exists() else (resume or {}).get('pretrained_sha256')
    start_epoch=0; best=-1.; logs=[]
    if resume:
        m.load_state_dict(resume['state']); optimizer.load_state_dict(resume['optimizer']); start_epoch=resume['epoch']+1
        best=resume['best']; logs=resume['logs']; random.setstate(resume['random']); np.random.set_state(resume['numpy']); torch.set_rng_state(resume['torch_rng'])
        if a.device=='cuda': torch.cuda.set_rng_state_all(resume['cuda_rng'])
    train_rows=[r for r in rows if r['split']=='train']; val_rows=[r for r in rows if r['split'] in ('validation','unknown_validation')]
    train_loader=torch.utils.data.DataLoader(Images(a.root,train_rows,True),batch_size=a.batch_size,shuffle=True,num_workers=0)
    val_loader=torch.utils.data.DataLoader(Images(a.root,val_rows),batch_size=a.batch_size,num_workers=0)
    begun=time.perf_counter()
    for epoch in range(start_epoch,a.epochs):
        tick=time.perf_counter(); m.train()
        # Freeze BN running statistics for memory-safe batches, including singleton remainder.
        for module in m.modules():
            if isinstance(module,nn.modules.batchnorm._BatchNorm): module.eval()
        total=0.; count=0
        for step,(x,y) in enumerate(train_loader):
            optimizer.zero_grad(set_to_none=True); loss=nn.functional.cross_entropy(m(x.to(device)),y.to(device))
            loss.backward(); optimizer.step(); total+=loss.item()*len(y); count+=len(y)
            if step%50==0:print(f'epoch={epoch} step={step}/{len(train_loader)} loss={loss.item():.5f} elapsed_s={time.perf_counter()-tick:.1f}',flush=True)
        logits,ys=infer(m,val_loader,device); report=metrics(logits,ys); improved=report['macro_f1']>best
        best=max(best,report['macro_f1']); logs.append({'epoch':epoch,'train_loss':total/count,'validation':report,'elapsed_s':time.perf_counter()-tick})
        checkpoint={'state':m.state_dict(),'optimizer':optimizer.state_dict(),'epoch':epoch,'best':best,'logs':logs,'lineage':identity,
                    'pretrained_sha256':pretrained_hash,'pretrained_url':WEIGHTS.url,'random':random.getstate(),'numpy':np.random.get_state(),
                    'torch_rng':torch.get_rng_state(),'cuda_rng':torch.cuda.get_rng_state_all() if a.device=='cuda' else None}
        atomic_save(checkpoint,out/'last.pt')
        if improved:
            atomic_save(checkpoint,out/'best.pt')
            immutable_threshold={'threshold':select_threshold(logits,ys),'selection':'validation only, empirical known risk <= .10; no reliability guarantee',
                                 'validation_n':len(ys),'unknown_n':int((ys<0).sum()),'checkpoint_sha256':digest((out/'best.pt').read_bytes())}
            (out/'threshold.json').write_text(json.dumps(immutable_threshold,indent=2))
        (out/'training.json').write_text(json.dumps({'lineage':identity,'logs':logs,'session_elapsed_s':time.perf_counter()-begun,'pretrained_sha256':pretrained_hash,'command':__import__('sys').argv},indent=2))
        print(f'epoch={epoch} train_loss={total/count:.6f} validation_macro_f1={report["macro_f1"]:.6f}',flush=True)

def load_checkpoint(path):
    # Only load your trusted local checkpoints: PyTorch pickle is executable input.
    checkpoint=torch.load(path,map_location='cpu',weights_only=False)
    if checkpoint['lineage']['labels']!=list(LABELS) or checkpoint['lineage']['preprocess']!=PREPROCESS: raise ValueError('Checkpoint schema mismatch')
    m=model(); m.load_state_dict(checkpoint['state']); return m.eval(),checkpoint

def evaluate(a):
    audit=require_audit(a.root,a.manifest,a.metadata,a.resolutions); m,checkpoint=load_checkpoint(a.checkpoint)
    if checkpoint['lineage']['partitions']!=partition_hashes(read_manifest(a.manifest)):
        raise ValueError('Training/validation/official-test partitions changed since training')
    threshold=json.loads(Path(a.threshold).read_text()); checkpoint_hash=digest(Path(a.checkpoint).read_bytes())
    if threshold['checkpoint_sha256']!=checkpoint_hash: raise ValueError('Threshold/checkpoint mismatch')
    rows=[r for r in read_manifest(a.manifest) if r['split']==a.split]
    seed_all(42); tick=time.perf_counter(); logits,ys=infer(m,torch.utils.data.DataLoader(Images(a.root,rows),batch_size=a.batch_size),torch.device('cpu'))
    result=metrics(logits,ys,threshold['threshold']); result.update(split=a.split,elapsed_s=time.perf_counter()-tick,checkpoint_sha256=checkpoint_hash,manifest_sha256=audit['manifest_sha256'],paths=[r['path'] for r in rows])
    immutable(a.out,(json.dumps(result,indent=2)+'\n').encode())

def export(a):
    m,checkpoint=load_checkpoint(a.checkpoint); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()): raise ValueError('Export directory must be empty')
    scripted=torch.jit.script(m); torch.jit.save(scripted,str(out/'model.pt'))
    meta={'format':'torchscript-desktop','sha256':digest((out/'model.pt').read_bytes()),'labels':list(LABELS),'preprocess':PREPROCESS,
          'runtime':{'torch':torch.__version__,'torchvision':torchvision.__version__,'device':'cpu'},'lineage':checkpoint['lineage'],
          'checkpoint_sha256':digest(Path(a.checkpoint).read_bytes()),'android_status':'BLOCKED: no validated embedded CNE/runtime bridge',
          'pretrained':{'url':checkpoint['pretrained_url'],'sha256':checkpoint['pretrained_sha256'],'source':'torchvision IMAGENET1K_V1; verify ImageNet weight rights before distribution'},
          'parity_status':'NOT_TESTED on real locked image corpus; use parity command'}
    immutable(out/'model.json',(canonical(meta)+'\n').encode())

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    for name in ('train','evaluate'):
        q=sub.add_parser(name)
        for arg in ('root','manifest','metadata','out'): q.add_argument('--'+arg,required=True)
        q.add_argument('--resolutions'); q.add_argument('--batch-size',type=int,default=8)
        if name=='train':
            q.add_argument('--epochs',type=int,default=1); q.add_argument('--lr',type=float,default=.0003); q.add_argument('--device',choices=['cpu','cuda'],default='cpu'); q.add_argument('--resume')
            q.add_argument('--freeze-features',action='store_true');q.add_argument('--threads',type=int,default=2)
        else:
            q.add_argument('--checkpoint',required=True); q.add_argument('--threshold',required=True); q.add_argument('--split',choices=['test','field_test','unknown_test'],required=True)
    q=sub.add_parser('export'); q.add_argument('--checkpoint',required=True); q.add_argument('--out',required=True)
    a=p.parse_args(); {'train':train,'evaluate':evaluate,'export':export}[a.command](a)
if __name__=='__main__': main()
