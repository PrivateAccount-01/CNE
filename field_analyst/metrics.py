"""Classification metrics. Confidence scores are not diagnosis probabilities."""
import numpy as np
from field_analyst import LABELS

def metrics(logits, targets, threshold=None):
    # Inspect original scalar types before NumPy promotes mixed bool/int input.
    if any(isinstance(v,(bool,np.bool_)) for v in np.asarray(targets,dtype=object).flat):raise ValueError('Targets must be integer class IDs, not bools')
    raw_y=np.asarray(targets)
    if raw_y.ndim!=1 or raw_y.dtype.kind not in 'iu':raise ValueError('Targets must be integer class IDs, not coerced floats/strings/bools')
    if ((raw_y>=len(LABELS))|(raw_y < -1 if raw_y.dtype.kind=='i' else False)).any():raise ValueError('Invalid target')
    if any(isinstance(v,(bool,np.bool_)) for v in np.asarray(logits,dtype=object).flat):raise ValueError('Logits must be numeric, not bools')
    raw_x=np.asarray(logits)
    if raw_x.dtype.kind not in 'fiu':raise ValueError('Logits must be numeric, not coerced strings/bools')
    x=raw_x.astype(np.float64); y=raw_y.astype(np.int64)
    if x.ndim!=2 or x.shape!=(len(y),len(LABELS)) or not len(y) or not np.isfinite(x).all():
        raise ValueError('Empty, nonfinite or mismatched logits')
    if ((y < -1)|(y>=len(LABELS))).any(): raise ValueError('Invalid target')
    p=np.exp(x-x.max(1,keepdims=True)); p/=p.sum(1,keepdims=True)
    pred=p.argmax(1); confidence=p.max(1); known=y>=0; n=int(known.sum())
    cm=np.zeros((len(LABELS),len(LABELS)),dtype=int)
    for a,b in zip(y[known],pred[known]): cm[a,b]+=1
    per=[]
    for i,label in enumerate(LABELS):
        tp=int(cm[i,i]); support=int(cm[i].sum()); predictions=int(cm[:,i].sum())
        precision=tp/predictions if predictions else 0.; recall=tp/support if support else None
        f1=2*tp/(support+predictions) if support else None
        per.append(dict(label=label,precision=precision,recall=recall,f1=f1,support=support))
    correct=pred[known]==y[known]; ece=0.
    bins=np.minimum(14,(confidence[known]*15).astype(int))
    for bucket in range(15):
        mask=bins==bucket
        if mask.any(): ece+=float(mask.sum()/max(1,n)*abs(correct[mask].mean()-confidence[known][mask].mean()))
    brier=float(np.square(p[known]-np.eye(len(LABELS))[y[known]]).sum(1).mean()) if n else None
    curve=[]
    for t in np.linspace(0,1,21):
        accepted=confidence>=t; ka=accepted&known
        curve.append({'threshold':float(t),'known_coverage':float(ka.sum()/n) if n else None,
                      'known_risk':float((pred[ka]!=y[ka]).mean()) if ka.any() else None,
                      'unknown_false_accept':float(accepted[~known].mean()) if (~known).any() else None})
    accuracy=float(correct.mean()) if n else None
    # Wilson interval on known image accuracy; correlated leaves violate IID assumptions.
    interval=None
    if n:
        z=1.96; den=1+z*z/n; center=(accuracy+z*z/(2*n))/den
        half=z*((accuracy*(1-accuracy)/n+z*z/(4*n*n))**.5)/den
        interval=[center-half,center+half]
    result={'known_n':n,'unknown_n':int((~known).sum()),'accuracy':accuracy,'macro_f1':float(np.mean([v['f1'] or 0 for v in per])) if n else None,
            'confusion_matrix':cm.tolist(),'per_class':per,'ece_15_equal_width':ece if n else None,'multiclass_brier_sum':brier,
            'accuracy_wilson95_image_iid_only':interval,'interval_caveat':'Not leaf-cluster adjusted; exploratory only',
            'coverage_risk':curve,'missing_classes':[v['label'] for v in per if not v['support']]}
    if threshold is not None:
        if isinstance(threshold,(bool,np.bool_)) or not isinstance(threshold,(int,float,np.integer,np.floating)) or not np.isfinite(threshold) or not 0<=threshold<=1: raise ValueError('Invalid threshold')
        accepted=confidence>=threshold
        result['operating_point']={'threshold':threshold,'unknown_false_accept':float(accepted[~known].mean()) if (~known).any() else None,
                                   'known_false_reject':float((~accepted[known]).mean()) if n else None,
                                   'unknown_detection_status':'NO_UNKNOWN_EVIDENCE' if not (~known).any() else 'MEASURED_ON_LISTED_UNKNOWNS_ONLY'}
    return result

def select_threshold(logits, targets):
    """Validation only: maximize known coverage at empirical risk <=10%; no general guarantee."""
    report=metrics(logits,targets)
    if report['known_n']==0: raise ValueError('Known validation required')
    feasible=[r for r in report['coverage_risk'] if r['known_risk'] is not None and r['known_risk']<=.1]
    return min((r['threshold'] for r in feasible),default=1.)
