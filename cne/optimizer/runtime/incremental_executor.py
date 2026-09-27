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

    def derive_stale_sources_from_fabric(
        self,
        prior_entry_id: Optional[str] = None
    ) -> Set[str]:
        """
        Authoritatively queries the DependencyManager to determine which data sources
        have mutated since the prior execution snapshot.
        """
        stale_srcs: Set[str] = set()
        if not self.fabric or not hasattr(self.fabric, "dep_manager"):
            return stale_srcs

        if prior_entry_id and prior_entry_id in self.fabric._entries:
            entry = self.fabric._entries[prior_entry_id]
            for src, recorded_ver in entry.dependency_snapshot.items():
                curr_ver = self.fabric.dep_manager.get_source_version(src)
                if curr_ver > recorded_ver:
                    stale_srcs.add(src)
        else:
            # Check any source that has registered mutations
            for src, ver in self.fabric.dep_manager.source_versions.items():
                if ver > 0:
                    stale_srcs.add(src)
        return stale_srcs

    @staticmethod
    def get_all_nodes(graph: SemanticIRGraph) -> Dict[str, IRNode]:
        """Flattens top-level nodes and all nested region nodes."""
        all_nodes = dict(graph.nodes)
        regions_to_visit = list(graph.regions.values())
        for node in graph.nodes.values():
            for attr_name in ("then_region", "else_region", "step_region"):
                r = node.attributes.get(attr_name)
                if r:
                    if isinstance(r, str) and r in graph.regions:
                        regions_to_visit.append(graph.regions[r])
                    elif hasattr(r, "nodes"):
                        regions_to_visit.append(r)
        visited_regs = set()
        while regions_to_visit:
            reg = regions_to_visit.pop()
            reg_id = getattr(reg, "id", id(reg))
            if reg_id in visited_regs:
                continue
            visited_regs.add(reg_id)
            for nid, node in reg.nodes.items():
                all_nodes[nid] = node
        return all_nodes

    def derive_stale_cone(
        self,
        graph: SemanticIRGraph,
        prior_vals: Dict[str, Any],
        stale_sources: Optional[Set[str]] = None,
        mutated_dependencies: Optional[List[DependencyKey]] = None,
        prior_entry_id: Optional[str] = None
    ) -> Set[str]:
        """
        Derives the minimal transitive stale cone from dependency manager state,
        including region-internal subgraphs (Branch / Iterate).
        A node is in the stale cone if:
        1. It is an Observe node whose source or key is stale
        2. Or any input node is in the stale cone
        3. Or it is missing from prior_vals
        """
        if stale_sources is None:
            stale_srcs = self.derive_stale_sources_from_fabric(prior_entry_id)
        else:
            stale_srcs = set(stale_sources)

        stale_cone: Set[str] = set()

        for nid in graph.topological_order():
            node = graph.nodes[nid]
            if node.op == OpKind.OBSERVE:
                src = node.attributes.get("source")
                k = node.attributes.get("key")
                is_stale = (src in stale_srcs) or (nid not in prior_vals)
                if not is_stale and mutated_dependencies:
                    for dep in mutated_dependencies:
                        if dep.source == src:
                            if dep.granularity in ("source", "table"):
                                is_stale = True
                                break
                            elif dep.granularity == "key" and k is not None and str(dep.key) == str(k):
                                is_stale = True
                                break
                if is_stale:
                    stale_cone.add(nid)
            elif node.op == OpKind.LITERAL:
                if nid not in prior_vals:
                    stale_cone.add(nid)
            elif node.op == OpKind.BRANCH:
                cond_stale = any(inp in stale_cone or inp not in prior_vals for inp in node.inputs)
                then_reg = node.attributes.get("then_region")
                else_reg = node.attributes.get("else_region")
                
                # Check regions for stale dependency inputs
                any_reg_stale = False
                for reg in (then_reg, else_reg):
                    reg_obj = None
                    if isinstance(reg, str) and reg in graph.regions:
                        reg_obj = graph.regions[reg]
                    elif hasattr(reg, "nodes"):
                        reg_obj = reg

                    if reg_obj and hasattr(reg_obj, "nodes"):
                        changed = True
                        while changed:
                            changed = False
                            for r_nid, r_node in reg_obj.nodes.items():
                                if r_nid in stale_cone:
                                    continue
                                r_is_stale = (r_nid not in prior_vals)
                                if r_node.op == OpKind.OBSERVE:
                                    r_src = r_node.attributes.get("source")
                                    r_k = r_node.attributes.get("key")
                                    if (r_src in stale_srcs) or (r_nid not in prior_vals):
                                        r_is_stale = True
                                    if not r_is_stale and mutated_dependencies:
                                        for dep in mutated_dependencies:
                                            if dep.source == r_src:
                                                if dep.granularity in ("source", "table"):
                                                    r_is_stale = True
                                                    break
                                                elif dep.granularity == "key" and r_k is not None and str(dep.key) == str(r_k):
                                                    r_is_stale = True
                                                    break
                                elif any(inp in stale_cone or (inp in reg_obj.nodes and inp not in prior_vals) for inp in r_node.inputs):
                                    r_is_stale = True
                                if r_is_stale:
                                    stale_cone.add(r_nid)
                                    any_reg_stale = True
                                    changed = True

                if cond_stale or (nid not in prior_vals) or any_reg_stale:
                    stale_cone.add(nid)
            elif node.op == OpKind.ITERATE:
                items_stale = any(inp in stale_cone or inp not in prior_vals for inp in node.inputs)
                step_reg = node.attributes.get("step_region")
                reg_obj = None
                if isinstance(step_reg, str) and step_reg in graph.regions:
                    reg_obj = graph.regions[step_reg]
                elif hasattr(step_reg, "nodes"):
                    reg_obj = step_reg

                any_reg_stale = False
                if reg_obj and hasattr(reg_obj, "nodes"):
                    changed = True
                    while changed:
                        changed = False
                        for r_nid, r_node in reg_obj.nodes.items():
                            if r_nid in stale_cone:
                                continue
                            r_is_stale = (r_nid not in prior_vals)
                            if r_node.op == OpKind.OBSERVE:
                                r_src = r_node.attributes.get("source")
                                if (r_src in stale_srcs) or (r_nid not in prior_vals):
                                    r_is_stale = True
                            elif any(inp in stale_cone or (inp in reg_obj.nodes and inp not in prior_vals) for inp in r_node.inputs):
                                r_is_stale = True
                            if r_is_stale:
                                stale_cone.add(r_nid)
                                any_reg_stale = True
                                changed = True

                if items_stale or (nid not in prior_vals) or any_reg_stale:
                    stale_cone.add(nid)
            else:
                if any(inp in stale_cone or inp not in prior_vals for inp in node.inputs):
                    stale_cone.add(nid)

        return stale_cone

    def execute_incremental(
        self,
        graph: SemanticIRGraph,
        contract: OutcomeContract,
        env: Dict[str, Any],
        stale_sources: Optional[Set[str]] = None,
        prior_node_values: Optional[Dict[str, Any]] = None,
        mutated_dependencies: Optional[List[DependencyKey]] = None
    ) -> IncrementalExecutionReport:
        t_ctrl_start = time.perf_counter_ns()
        prior_vals = dict(prior_node_values or {})

        stale_cone = self.derive_stale_cone(
            graph=graph,
            prior_vals=prior_vals,
            stale_sources=stale_sources,
            mutated_dependencies=mutated_dependencies
        )

        all_nodes = self.get_all_nodes(graph)
        reused_nodes = [nid for nid in all_nodes if nid not in stale_cone]
        control_overhead_ns = float(time.perf_counter_ns() - t_ctrl_start)

        # Execution phase: only evaluate nodes in the stale cone
        t_exec_start = time.perf_counter_ns()
        ctx = ExecutionContext(environment=dict(env))
        # Seed ctx with reused valid prior values
        for nid in reused_nodes:
            if nid in prior_vals:
                ctx.values[nid] = prior_vals[nid]

        for nid in graph.topological_order():
            if nid in stale_cone:
                self.evaluator._evaluate_node(graph.nodes[nid], graph, ctx)

        execution_time_ns = float(time.perf_counter_ns() - t_exec_start)
        final_val = ctx.values.get(graph.root_id)

        # True selectivity check (Section 30):
        # Execution is selective iff some nodes were successfully reused AND not all nodes had to be recomputed.
        was_selective = (len(reused_nodes) > 0 and len(stale_cone) < len(all_nodes))

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
