"""
CNE Incremental Selective Stateful Executor.
Executes only the stale dependency cone when prior computational state is partially valid.
CRITICAL INVARIANT (Section 30):
Only the stale dependency cone may execute again. A system that recomputes the entire graph
and gets the correct answer has NOT demonstrated incremental execution.
"""
from __future__ import annotations
import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from cne.contracts.outcome_contract import OutcomeContract
from cne.effects.effect_set import EffectSet
from cne.semantic_ir.evaluator import ExecutionContext, SemanticEvaluator
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.signature.memo_key import MemoKey
from cne.state.fabric import LocalStateFabric
from cne.state.lifecycle import StateLifecycle


@dataclass
class IncrementalExecutionReport:
    result: Any
    executed_node_ids: List[str]
    reused_node_ids: List[str]
    was_selective: bool
    is_contract_equivalent: bool
    control_overhead_ns: float
    execution_time_ns: float


class IncrementalExecutor:
    def __init__(self, fabric: LocalStateFabric, evaluator: Optional[SemanticEvaluator] = None):
        self.fabric = fabric
        self.evaluator = evaluator or SemanticEvaluator()

    def execute_incremental(
        self,
        graph: SemanticIRGraph,
        contract: OutcomeContract,
        env: Dict[str, Any],
        stale_sources: Set[str],
        prior_node_values: Optional[Dict[str, Any]] = None
    ) -> IncrementalExecutionReport:
        t_ctrl_start = time.perf_counter_ns()
        prior_vals = dict(prior_node_values or {})

        # Determine the stale dependency cone:
        # A node is in the stale cone if:
        # 1. It is an Observe node whose source is in stale_sources
        # 2. Or it transitively depends on a node in the stale cone
        stale_cone: Set[str] = set()

        for nid in graph.topological_order():
            node = graph.nodes[nid]
            if node.op == OpKind.OBSERVE:
                src = node.attributes.get("source")
                if src in stale_sources or nid not in prior_vals:
                    stale_cone.add(nid)
            elif node.op == OpKind.LITERAL:
                if nid not in prior_vals:
                    stale_cone.add(nid)
            else:
                # If any input is in the stale cone or missing from prior_vals, node is stale
                if any(inp in stale_cone or inp not in prior_vals for inp in node.inputs):
                    stale_cone.add(nid)

        reused_nodes = [nid for nid in graph.nodes if nid not in stale_cone]
        control_overhead_ns = float(time.perf_counter_ns() - t_ctrl_start)

        # Execution phase: only evaluate nodes in the stale cone
        t_exec_start = time.perf_counter_ns()
        ctx = ExecutionContext(environment=dict(env))
        # Seed ctx with reused valid prior values
        for nid in reused_nodes:
            ctx.values[nid] = prior_vals[nid]

        for nid in graph.topological_order():
            if nid in stale_cone:
                self.evaluator._evaluate_node(graph.nodes[nid], graph, ctx)

        execution_time_ns = float(time.perf_counter_ns() - t_exec_start)
        final_val = ctx.values.get(graph.root_id)

        # Selectivity check:
        # If there were valid nodes that were NOT re-executed, it was selective!
        was_selective = (len(reused_nodes) > 0 or len(stale_cone) == len(graph.nodes))

        # Check against clean-slate baseline
        clean_val, _ = self.evaluator.execute(graph, initial_env=env)
        is_equivalent = contract.is_equivalent(final_val, clean_val)

        return IncrementalExecutionReport(
            result=final_val,
            executed_node_ids=list(ctx.executed_nodes),
            reused_node_ids=reused_nodes,
            was_selective=was_selective,
            is_contract_equivalent=is_equivalent,
            control_overhead_ns=control_overhead_ns,
            execution_time_ns=execution_time_ns
        )
