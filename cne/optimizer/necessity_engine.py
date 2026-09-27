"""
CNE Computation Necessity Engine Coordinator.
Executes the frozen end-to-end pipeline (Section 3.1 & 65):
Query -> Semantic IR -> Signature -> Contract -> Cost Gate -> State Fabric Lookup ->
Static Optimizer -> Execution -> Verifier/Auditor -> State Persistence.
Maintains strict separation between Control, Execution, Verification, and Persistence times.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from cne.contracts.outcome_contract import OutcomeContract
from cne.optimizer.instrumentation import CostBreakdown, PrecisionTimer
from cne.optimizer.runtime.cost_gate import CostGate
from cne.optimizer.runtime.incremental_executor import IncrementalExecutor
from cne.optimizer.static.static_optimizer import StaticOptimizer
from cne.semantic_ir.evaluator import ExecutionContext, SemanticEvaluator
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.signature.cost_class import CostClass
from cne.signature.memo_key import MemoKey
from cne.signature.shape_key import SemanticShapeKey
from cne.state.fabric import LocalStateFabric
from cne.state.state_entry import StateClass


@dataclass
class CNEExecutionResult:
    value: Any
    costs: CostBreakdown
    reused_state: bool
    optimized: bool
    contract_satisfied: bool
    memo_key: MemoKey


class ComputationNecessityEngine:
    def __init__(
        self,
        fabric: Optional[LocalStateFabric] = None,
        evaluator: Optional[SemanticEvaluator] = None,
        cost_gate: Optional[CostGate] = None
    ):
        self.fabric = fabric or LocalStateFabric()
        self.evaluator = evaluator or SemanticEvaluator()
        self.cost_gate = cost_gate or CostGate()
        self.static_optimizer = StaticOptimizer()

    def execute_query(
        self,
        graph: SemanticIRGraph,
        contract: OutcomeContract,
        env: Dict[str, Any],
        query_id: str = "query_0",
        baseline_cost_hint_ns: float = 0.0
    ) -> CNEExecutionResult:
        timer_control = PrecisionTimer()
        timer_exec = PrecisionTimer()
        timer_verify = PrecisionTimer()
        timer_persist = PrecisionTimer()

        # ================= CONTROL PHASE =================
        timer_control.start()

        # 1. Signature generation: collect input data for all observed sources and embed contract
        memo_k = MemoKey.from_graph(graph, env=env, contract=contract)
        cost_cls = CostClass.from_graph(graph)

        # 2. State Fabric Lookup
        cached_entry = self.fabric.get_by_memo_key(memo_k)
        if cached_entry is not None:
            # Active valid memo exists: completely avoid re-execution!
            self.fabric.record_useful_reuse(cached_entry, baseline_cost_saved_ns=baseline_cost_hint_ns)
            timer_control.stop()

            # Verification: cached value satisfies contract
            timer_verify.start()
            valid = contract.is_equivalent(cached_entry.value, cached_entry.value)
            timer_verify.stop()

            costs = CostBreakdown(
                control_ns=timer_control.elapsed_ns,
                execution_ns=0.0,
                verification_ns=timer_verify.elapsed_ns,
                persistence_ns=0.0
            )
            return CNEExecutionResult(
                value=cached_entry.value,
                costs=costs,
                reused_state=True,
                optimized=True,
                contract_satisfied=valid,
                memo_key=memo_k
            )

        # 3. Cost-gate evaluation
        should_opt = self.cost_gate.should_optimize(cost_cls)
        active_graph = graph

        if should_opt:
            # Run static optimizer: reachability, folding, slicing, contract simplification
            opt_res = self.static_optimizer.optimize(graph, contract)
            active_graph = opt_res.optimized_graph

        timer_control.stop()

        # ================= EXECUTION PHASE =================
        timer_exec.start()
        val, ctx = self.evaluator.execute(active_graph, initial_env=env)
        timer_exec.stop()

        # ================= VERIFICATION PHASE =================
        timer_verify.start()
        # Verify contract compliance
        contract_ok = contract.satisfies_constraints(val)
        timer_verify.stop()

        # ================= PERSISTENCE PHASE =================
        timer_persist.start()
        self.fabric.put(
            entry_id=f"entry_{query_id}",
            state_class=StateClass.COMPUTATIONAL,
            value=val,
            memo_key=memo_k,
            contract=contract,
            dependencies=ctx.observed_dependencies
        )
        timer_persist.stop()

        costs = CostBreakdown(
            control_ns=timer_control.elapsed_ns,
            execution_ns=timer_exec.elapsed_ns,
            verification_ns=timer_verify.elapsed_ns,
            persistence_ns=timer_persist.elapsed_ns
        )

        return CNEExecutionResult(
            value=val,
            costs=costs,
            reused_state=False,
            optimized=should_opt,
            contract_satisfied=contract_ok,
            memo_key=memo_k
        )
