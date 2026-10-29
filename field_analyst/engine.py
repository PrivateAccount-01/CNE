"""Trusted local adapter to the authoritative CNE. Native torch reuse is conservative."""
from __future__ import annotations
import hashlib, io, json, math, threading, time, uuid
from pathlib import Path
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.effects.effect_set import Effect, EffectSet
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.signature.memo_key import SystemVersions
from field_analyst import LABELS, WARNING
from field_analyst.dataset import canonical, digest, image_rgb

class TorchAsset:
    """Loads verified bytes once. Rechecks mutable disk assets before every invocation."""
    reusable=False  # Native/runtime determinism has NOT been qualified for reuse.
    def __init__(self,model_path,manifest_path):
        import torch, torchvision
        from field_analyst.train import PREPROCESS, transform
        self.path=Path(model_path); self.manifest_path=Path(manifest_path)
        self.manifest_bytes=self.manifest_path.read_bytes(); self.manifest=json.loads(self.manifest_bytes)
        m=self.manifest
        if m['labels']!=list(LABELS) or m['preprocess']!=PREPROCESS or m['format']!='torchscript-desktop':
            raise ValueError('Unsupported model labels/preprocessing/format')
        if m['runtime']!={'torch':torch.__version__,'torchvision':torchvision.__version__,'device':'cpu'}:
            raise ValueError('Runtime identity mismatch')
        data=self.path.read_bytes()
        if digest(data)!=m['sha256']: raise ValueError('Model hash mismatch')
        self.identity=canonical({'model':m['sha256'],'manifest':digest(self.manifest_bytes),'runtime':m['runtime'],
                                 'preprocess':m['preprocess'],'labels':m['labels'],'adapter':digest(Path(__file__).read_bytes())})
        self.model=torch.jit.load(io.BytesIO(data),map_location='cpu').eval(); self.transform=transform()
    def verify(self):
        if digest(self.path.read_bytes())!=self.manifest['sha256'] or self.manifest_path.read_bytes()!=self.manifest_bytes:
            raise ValueError('Model or asset manifest mutated; reload required')
    def __call__(self,data):
        import torch
        self.verify(); x=self.transform(image_rgb(data)).unsqueeze(0)
        with torch.inference_mode(): return self.model(x)[0].tolist()

def valid_logits(value):
    return isinstance(value,list) and len(value)==len(LABELS) and all(isinstance(x,(float,int)) and math.isfinite(x) for x in value)

class FieldEngine:
    """Only trusted built-in assets; never loads pack code or overrides core cache policy."""
    def __init__(self,asset):
        self.asset=asset; self.cne=ComputationNecessityEngine(); self.invocations=0; self.lock=threading.Lock()
        self.contract=OutcomeContract(ContractType.EXACT,output_schema={'logits':'finite float[4]'},constraints=[valid_logits])
    def _invoke(self,image_hex,identity):
        if identity!=self.asset.identity: raise ValueError('Runtime identity changed')
        self.invocations+=1
        result=self.asset(bytes.fromhex(image_hex))
        if not valid_logits(result): raise ValueError('Invalid model output')
        return result
    def analyze(self,data,note='',baseline=False):
        with self.lock:
            self.asset.verify(); image_rgb(data) # reject unsupported inputs before memo lookup
            identity=self.asset.identity
            graph=SemanticIRGraph()
            graph.add_node(IRNode('image',OpKind.OBSERVE,attributes={'source':'image_bytes_hex'}))
            graph.add_node(IRNode('asset',OpKind.OBSERVE,attributes={'source':'asset_identity'}))
            # No mutable list/dict is observed: avoids core's id+length digest cache hazards.
            effects=[Effect.ReadExternal]
            if not self.asset.reusable: effects.append(Effect.Nondeterministic)
            graph.add_node(IRNode('inference',OpKind.CALL,inputs=['image','asset'],attributes={'target':'field_analyst.cpu_logits','fn':self._invoke},declared_effects=EffectSet(effects)))
            graph.add_node(IRNode('out',OpKind.EMIT,inputs=['inference'])); graph.root_id='out'
            env={'image_bytes_hex':data.hex(),'asset_identity':identity}
            before=self.invocations; tick=time.perf_counter_ns()
            if baseline:
                logits=self._invoke(env['image_bytes_hex'],identity); reused=False; contract_ok=self.contract.satisfies_constraints(logits); costs=None; memo=None
            else:
                result=self.cne.execute_query(graph,self.contract,env,query_id=uuid.uuid4().hex,
                    versions=SystemVersions(model_version=digest(identity.encode()),runtime_version='field-analyst-v1'))
                logits=result.value; reused=result.reused_state; contract_ok=result.contract_satisfied; costs=vars(result.costs); memo=result.memo_key.key_hash
            elapsed=time.perf_counter_ns()-tick
            if not contract_ok: raise ValueError('CNE output contract rejected')
            logits=list(logits)  # Do not expose mutable aliases to CNE's stored result.
            exps=[math.exp(x-max(logits)) for x in logits]; scores=[x/sum(exps) for x in exps]
            threshold=getattr(self.asset,'threshold',None)
            uncertainty=('Validation-derived score threshold only; does not establish crop support, diagnosis or reliable unknown detection.'
                         if threshold is not None else 'UNVALIDATED; abstention unavailable without checkpoint-bound validation threshold')
            return {'logits':logits,'ranked':[{'label':LABELS[i],'softmax_score':scores[i]} for i in sorted(range(len(LABELS)),key=lambda j:-scores[j])],
                    'note':note,'warning':WARNING,'uncertainty_status':uncertainty,'abstained':max(scores)<threshold if threshold is not None else None,'threshold':threshold,
                    'trace':{'engine':'authoritative cne.optimizer.necessity_engine','reused_state':reused,'inference_calls':self.invocations-before,
                             'elapsed_ns':elapsed,'costs':costs,'memo_key':memo,'asset_identity':identity,'image_sha256':digest(data),
                             'contract_satisfied':contract_ok,'contract_note':'Execution equivalence only, not prediction correctness',
                             'reuse_policy':'dependency gated' if self.asset.reusable else 'disabled: native runtime not determinism-qualified'}}
