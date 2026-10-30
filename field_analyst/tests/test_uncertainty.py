"""Decision policy tests, not evidence of classifier quality."""
import pytest
from field_analyst.uncertainty import assess_scores, STATUS
from field_analyst.engine import valid_logits
from field_analyst.metrics import metrics


@pytest.mark.parametrize('scores', [[1.,0.,0.,0.], [.25]*4])
@pytest.mark.parametrize('threshold', [None,0.,.5,1.])
def test_even_extreme_scores_cannot_establish_supported_input(scores,threshold):
    result=assess_scores(scores,threshold)
    assert result['accepted'] is None and result['abstained'] is True
    assert result['support_status']==STATUS
    assert result['below_known_score_threshold']==(max(scores)<threshold if threshold is not None else None)


@pytest.mark.parametrize('scores', [[True,0,0,0],[float('nan'),0,0,0],[float('inf'),0,0,0],[.2]*4,[1,0,0],[-1,1,1,0]])
def test_invalid_scores_fail_closed(scores):
    with pytest.raises(ValueError):assess_scores(scores)


@pytest.mark.parametrize('threshold', [True,float('nan'),float('inf'),-1,2,'0.5'])
def test_invalid_threshold_fails_closed(threshold):
    with pytest.raises(ValueError):assess_scores([.25]*4,threshold)


@pytest.mark.parametrize('targets', [[True],[0.9],['0']])
def test_metrics_do_not_silently_coerce_target_labels(targets):
    with pytest.raises(ValueError,match='integer class'):metrics([[1,0,0,0]],targets)


def test_boolean_is_not_a_model_logit():
    assert not valid_logits([True,0.,0.,0.])


@pytest.mark.parametrize('logits', [[[True,False,False,False]],[['1','0','0','0']]])
def test_metrics_refuse_coerced_logits(logits):
    with pytest.raises(ValueError,match='numeric'):metrics(logits,[0])


def test_large_unsigned_target_cannot_wrap_into_unknown():
    import numpy as np
    with pytest.raises(ValueError,match='Invalid target'):metrics([[1,0,0,0]],np.asarray([2**64-1],dtype=np.uint64))


def test_numpy_promotion_cannot_hide_a_boolean_scalar():
    with pytest.raises(ValueError,match='integer class'):metrics([[1,0,0,0],[0,1,0,0]],[True,0])
    with pytest.raises(ValueError,match='numeric'):metrics([[True,0.,0.,0.]],[0])


def test_streaming_archive_hash_matches_bytes(tmp_path):
    import hashlib
    from field_analyst.dataset import file_sha256
    path=tmp_path/'archive';data=b'bounded hashing\0'*(100000)
    path.write_bytes(data)
    assert file_sha256(path)==hashlib.sha256(data).hexdigest()
    path.write_bytes(b'')
    assert file_sha256(path)==hashlib.sha256(b'').hexdigest()
