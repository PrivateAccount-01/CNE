"""
Desktop DSL-to-CNE Integration Test:
Platform Controller Bridge -> Semantic DSL -> CNE Execution Engine -> LocalStateFabric -> MemoKey Reuse.
Validates offline, zero-cloud, deterministic computation necessity caching on the reference substrate.
"""
from __future__ import annotations
import pytest
from typing import Dict, Any

from cne.platform.bridge import PlatformControllerBridge
from cne.platform.registry import CapabilityRegistry
from cne.platform.device import DeviceProfile
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.state.fabric import LocalStateFabric
from cne.signature.memo_key import SystemVersions
from cne.contracts.outcome_contract import ContractType, OutcomeContract


class TestPlatformCNEEndToEnd:
    @pytest.fixture
    def setup_platform_cne(self):
        profile = DeviceProfile()
        registry = CapabilityRegistry()
        bridge = PlatformControllerBridge(registry=registry, device_profile=profile)
        fabric = LocalStateFabric()
        engine = ComputationNecessityEngine(fabric=fabric)
        return {
            "bridge": bridge,
            "engine": engine,
            "fabric": fabric,
            "registry": registry,
        }

    def test_end_to_end_compilation_execution_and_caching(self, setup_platform_cne):
        bridge = setup_platform_cne["bridge"]
        engine = setup_platform_cne["engine"]
        fabric = setup_platform_cne["fabric"]

        # 1. Natural Language or DSL compilation through Platform Bridge
        dsl_script = (
            "t0 = OBS source=transactions key=amounts\n"
            "t1 = RED in=t0 reducer=sum initial=0\n"
            "t2 = EMI in=t1"
        )
        comp_res = bridge.compile_to_cne(dsl_script, contract_type=ContractType.EXACT)
        from cne.compiler.nl_compiler import ClassificationOutcome

        assert comp_res.outcome == ClassificationOutcome.COMPILED
        assert comp_res.graph is not None

        env = {"transactions": {"amounts": [100, 250, 75, 500]}}
        contract = comp_res.contract or OutcomeContract(ContractType.EXACT)
        versions_v1 = SystemVersions(capability_vector_hash="finance@1.0.0")

        # 2. First Execution: Cold run, must evaluate and persist in StateFabric
        run1 = engine.execute_query(
            comp_res.graph,
            contract=contract,
            env=env,
            query_id="q1",
            versions=versions_v1,
        )
        assert run1.contract_satisfied
        assert run1.value == 925
        assert not run1.reused_state
        assert run1.costs.execution_ns > 0

        # 3. Second Execution: Exact same inputs & capability vector -> 100% Memo hit!
        run2 = engine.execute_query(
            comp_res.graph,
            contract=contract,
            env=env,
            query_id="q2",
            versions=versions_v1,
        )
        assert run2.contract_satisfied
        assert run2.value == 925
        assert run2.reused_state
        assert run2.costs.execution_ns == 0.0
        assert run1.memo_key.key_hash == run2.memo_key.key_hash

        # 4. State Mutation: Input data changes in environment -> Cache miss & Recompute
        env_mutated = {"transactions": {"amounts": [100, 250, 75, 500, 1000]}}
        run3 = engine.execute_query(
            comp_res.graph,
            contract=contract,
            env=env_mutated,
            query_id="q3",
            versions=versions_v1,
        )
        assert run3.contract_satisfied
        assert run3.value == 1925
        assert not run3.reused_state
        assert run3.memo_key.key_hash != run1.memo_key.key_hash

        # 5. Capability Vector Upgrade: Even if data is reverted, new capability version forces cache miss
        versions_v2 = SystemVersions(capability_vector_hash="finance@1.0.1")
        run4 = engine.execute_query(
            comp_res.graph,
            contract=contract,
            env=env,
            query_id="q4",
            versions=versions_v2,
        )
        assert run4.contract_satisfied
        assert run4.value == 925
        assert not run4.reused_state  # Recomputed because capability vector changed!
        assert run4.memo_key.key_hash != run1.memo_key.key_hash
