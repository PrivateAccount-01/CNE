"""Current model scores do not establish supported input or reliable unknown detection."""
import math
STATUS='UNKNOWN_RELIABILITY_UNVERIFIED'
def assess_scores(scores,threshold=None):
    if len(scores)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in scores):
        raise ValueError('Four finite numeric scores in [0,1] required')
    if not math.isclose(sum(scores),1.,abs_tol=1e-6):raise ValueError('Scores must sum to one')
    if threshold is not None and (isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<=threshold<=1):
        raise ValueError('Invalid score threshold')
    # Existing calibration used known examples only and demonstrably accepted all
    # tested unknowns. Do not turn its score cutoff into apparent safe acceptance.
    return {'support_status':STATUS,'accepted':None,'abstained':True,'threshold':threshold,
            'below_known_score_threshold':max(scores)<threshold if threshold is not None else None,
            'uncertainty_status':STATUS+': no supported classification decision; ranked scores are inspection-only. A known-only cutoff is not an unknown-input detector.'}
