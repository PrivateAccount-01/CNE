import pytest
from cne.tests.platform.test_correction_learning_loop import create_runtime, ENV, QUERY
from cne.platform.runtime_config import PlatformRuntimeConfig


def test_production_requires_durable_root():
    with pytest.raises(ValueError):
        PlatformRuntimeConfig()
    with pytest.raises(ValueError):
        PlatformRuntimeConfig(in_memory=True)
    assert PlatformRuntimeConfig(mode="test", in_memory=True)


def test_execute_restart_revalidate_reuse_and_mutation(tmp_path):
    query = QUERY.replace("groceries", "food")
    rt = create_runtime(tmp_path)
    one = rt.executor.execute("alice", "s0", query, ENV)
    assert one.value == 80 and not one.reused_state
    rt.close()
    rt = create_runtime(tmp_path)
    two = rt.executor.execute("alice", "s1", query, ENV)
    assert two.value == 80 and two.reused_state
    assert rt.executor.telemetry._records[-1].cache_hits_by_layer["L2"] == 1
    changed = {"transactions": [{**ENV["transactions"][0], "amount": 120}]}
    three = rt.executor.execute("alice", "s2", query, changed)
    assert three.value == 120 and not three.reused_state
    assert not rt.executor.execute("bob", "b0", query, ENV).reused_state
    rt.close()



def test_production_runtime_requires_host_encryption_key_provider():
    from cne.platform.runtime_config import PlatformRuntimeConfig

    with pytest.raises(ValueError, match="host key provider"):
        PlatformRuntimeConfig(storage_root="private-data", mode="production")
