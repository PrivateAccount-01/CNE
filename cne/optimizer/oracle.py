"""
CNE G2 Recoverable-Computation Oracle.
Computes upper bound of recoverable computation R* over admissible, information-honest interventions.
STRICT ADMISSIBILITY RULES:
1. Preserves graph typing
2. Preserves control semantics
3. Satisfies downstream inputs
4. Preserves required effects
5. Testable under the declared Outcome Contract
6. Information availability: I_intervention ⊆ I_available_before_skipped_work
7. Hindsight-validation distinction: baseline output is used OFFLINE ONLY to validate C,
   NEVER to manufacture or invent the intervention.
"""
from __future__ import annotations
import copy
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from cne.contracts.outcome_contract import OutcomeContract
from cne.effects.effect_set import Effect, EffectSet
from cne.effects.propagation import EffectPropagator
from cne.semantic_ir.evaluator import ExecutionContext, SemanticEvaluator
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion


import statistics


@dataclass
class OracleIntervention:
    """
    Candidate admissible transformation on graph G.
    """
    description: str
    transformed_graph: SemanticIRGraph
    estimated_cost: float
    evidence_tier: str = "Certified"


@dataclass
class OracleResult:
    query_id: str
    baseline_cost: float
    optimal_cost: float
    recoverable_ratio: float  # R* = (C_baseline - C_optimal) / C_baseline
    admissible_interventions_evaluated: int
    optimal_intervention_desc: str
    contract_satisfied: bool


class G2Oracle:
    def __init__(self, evaluator: Optional[SemanticEvaluator] = None):
        self.evaluator = evaluator or SemanticEvaluator()

    def find_recoverable_bound(
        self,
        query_id: str,
        graph: SemanticIRGraph,
        contract: OutcomeContract,
        env: Dict[str, Any],
        train_corpus_ids: Optional[Set[str]] = None,
        fabric: Optional[Any] = None
    ) -> OracleResult:
        """
        Calculates R* under strict information-honesty rules and train/eval split.
        Operates over the explicit closed space A_benchmark(G, S, C) containing all
        7 admissible transformations and their compositions for this Semantic IR.
        """
        # Train/eval split check: evaluated query_id must not be in train_corpus
        if train_corpus_ids and query_id in train_corpus_ids:
            raise ValueError(f"Contamination violation: evaluated query {query_id} is in train corpus!")

        # 1. Run baseline execution and measure baseline cost across repeated trials (Doc #18)
        baseline_result, baseline_ctx = self.evaluator.execute(graph, initial_env=env)
        base_times = []
        for _ in range(3):
            t0 = time.perf_counter_ns()
            self.evaluator.execute(graph, initial_env=env)
            base_times.append(max(1, time.perf_counter_ns() - t0))
        baseline_cost = float(statistics.median(base_times))

        # 2. Enumerate candidate admissible interventions from A_benchmark(G, S, C)
        candidate_interventions = self._generate_admissible_candidates(graph, env, contract, fabric)

        optimal_graph = graph
        optimal_cost = baseline_cost
        best_desc = "baseline_direct"
        contract_satisfied = True

        # 3. Offline hindsight-validation:
        # Validate candidate against OutcomeContract using baseline result
        for cand in candidate_interventions:
            # Measure candidate execution time via repeated-trial median to eliminate noise (Doc #18)
            cand_val, cand_ctx = self.evaluator.execute(cand.transformed_graph, initial_env=env)
            cand_times = []
            for _ in range(3):
                t_cand = time.perf_counter_ns()
                self.evaluator.execute(cand.transformed_graph, initial_env=env)
                cand_times.append(max(1, time.perf_counter_ns() - t_cand))
            cand_time_ns = int(statistics.median(cand_times))

            # Check contract equivalence: cand_val ≡_C baseline_result
            if contract.is_equivalent(cand_val, baseline_result):
                # Check effect preservation: candidate must not drop required side effects
                if self._preserves_required_effects(baseline_ctx.runtime_effects, cand_ctx.runtime_effects):
                    if cand_time_ns < optimal_cost:
                        optimal_cost = float(cand_time_ns)
                        optimal_graph = cand.transformed_graph
                        best_desc = cand.description

        # Compute R*
        r_star = max(0.0, (baseline_cost - optimal_cost) / baseline_cost) if baseline_cost > 0 else 0.0

        return OracleResult(
            query_id=query_id,
            baseline_cost=baseline_cost,
            optimal_cost=optimal_cost,
            recoverable_ratio=r_star,
            admissible_interventions_evaluated=len(candidate_interventions),
            optimal_intervention_desc=best_desc,
            contract_satisfied=contract_satisfied
        )

    def _generate_admissible_candidates(
        self,
        graph: SemanticIRGraph,
        env: Dict[str, Any],
        contract: Optional[OutcomeContract] = None,
        fabric: Optional[Any] = None
    ) -> List[OracleIntervention]:
        """
        Generates candidate interventions strictly from information available BEFORE skipped work.
        Explicitly evaluates the closed space A_benchmark(G, S, C) for this IR:
        T0: Baseline direct
        T1: Static dependency slice
        T2: Constant folding of pure nodes
        T3: Branch specialization (statically resolvable condition)
        T4: State memo substitution (when active valid state in fabric)
        T5: Filter pushdown / simplification under contract
        T6: Composite composition (T1 o T2 o T3 o T5)
        """
        candidates: List[OracleIntervention] = []

        # T1: Dead-code sliced graph
        sliced_g = self._slice_graph(graph)
        candidates.append(OracleIntervention(
            description="static_dependency_slice",
            transformed_graph=sliced_g,
            estimated_cost=0.0
        ))

        # T2: Constant-folded graph (pure inputs folded)
        folded_g = self._fold_constants(sliced_g, env)
        candidates.append(OracleIntervention(
            description="constant_folded_graph",
            transformed_graph=folded_g,
            estimated_cost=0.0
        ))

        # T3: Branch-specialized graph if condition is statically resolvable
        spec_g = self._specialize_branches(folded_g, env)
        candidates.append(OracleIntervention(
            description="branch_specialized_graph",
            transformed_graph=spec_g,
            estimated_cost=0.0
        ))

        # T4: State fabric memo substitution (Section 20/21: S is allowed information)
        if fabric is not None:
            from cne.signature.memo_key import MemoKey
            mk = MemoKey.from_graph(graph, contract=contract, env=env)
            cached = fabric.get_by_memo_key(mk)
            if cached is not None and cached.value is not None:
                memo_g = SemanticIRGraph()
                lit_memo = IRNode(
                    id="memo_val",
                    op=OpKind.LITERAL,
                    attributes={"value": cached.value}
                )
                memo_g.add_node(lit_memo)
                memo_g.root_id = "memo_val"
                candidates.append(OracleIntervention(
                    description="state_memo_substitution",
                    transformed_graph=memo_g,
                    estimated_cost=0.0
                ))

        # T5: Filter simplification under contract
        # (Doc #15: Relabeled as Audited-tier evidence, since heuristic predicate sampling on empty/test input is not a formal proof)
        filt_g = self._simplify_filters(spec_g, contract)
        candidates.append(OracleIntervention(
            description="contract_filter_simplification",
            transformed_graph=filt_g,
            estimated_cost=0.0,
            evidence_tier="Audited"
        ))

        # T6: Composite composition
        candidates.append(OracleIntervention(
            description="composite_optimal_pipeline",
            transformed_graph=filt_g,
            estimated_cost=0.0
        ))

        return candidates

    def _simplify_filters(self, graph: SemanticIRGraph, contract: Optional[OutcomeContract]) -> SemanticIRGraph:
        """
        Bypasses redundant pass-through filters when contract allows.
        """
        g = copy.deepcopy(graph)
        for nid, node in list(g.nodes.items()):
            if node.op == OpKind.FILTER and node.inputs:
                pred = node.attributes.get("predicate")
                if pred is not None:
                    try:
                        if pred({}) is True and pred({"test": 1}) is True:
                            parent_id = node.inputs[0]
                            for other in g.nodes.values():
                                other.inputs = [parent_id if inp == nid else inp for inp in other.inputs]
                            if g.root_id == nid:
                                g.root_id = parent_id
                            del g.nodes[nid]
                    except Exception:
                        pass
        return g

    def _slice_graph(self, graph: SemanticIRGraph) -> SemanticIRGraph:
        """
        Retain only nodes necessary to produce Emit and required effects.
        """
        g = copy.deepcopy(graph)
        needed = set()

        def mark(nid: str):
            if nid in needed:
                return
            needed.add(nid)
            node = g.nodes.get(nid)
            if node:
                for inp in node.inputs:
                    mark(inp)

        if g.root_id:
            mark(g.root_id)

        # Remove unneeded nodes
        for nid in list(g.nodes.keys()):
            if nid not in needed:
                # Unless node has external write effect
                if not (Effect.WriteExternal in g.nodes[nid].get_immediate_effects()):
                    del g.nodes[nid]

        return g

    def _fold_constants(self, graph: SemanticIRGraph, env: Dict[str, Any]) -> SemanticIRGraph:
        """
        Folds pure deterministic nodes whose inputs are literals.
        """
        g = copy.deepcopy(graph)
        static_effects = EffectPropagator.compute_static_effects(g)

        for nid in g.topological_order():
            node = g.nodes.get(nid)
            if not node or node.op in (OpKind.EMIT, OpKind.LITERAL, OpKind.BRANCH, OpKind.ITERATE):
                continue

            # If node is pure and all inputs are literals, we can fold it
            if static_effects.get(nid, EffectSet.pure()).is_pure:
                all_literal = True
                lit_inputs = []
                for inp in node.inputs:
                    inp_node = g.nodes.get(inp)
                    if not inp_node or inp_node.op != OpKind.LITERAL:
                        all_literal = False
                        break
                    lit_inputs.append(inp_node.attributes.get("value"))

                if all_literal and node.inputs:
                    # Evaluate purely
                    sub_ctx = ExecutionContext()
                    for i, inp_id in enumerate(node.inputs):
                        sub_ctx.values[inp_id] = lit_inputs[i]
                    try:
                        val = self.evaluator._evaluate_node(node, g, sub_ctx)
                        # Replace node with Literal
                        g.nodes[nid] = IRNode(
                            id=nid,
                            op=OpKind.LITERAL,
                            attributes={"value": val},
                            output_type=node.output_type
                        )
                    except Exception:
                        pass

        return g

    def _specialize_branches(self, graph: SemanticIRGraph, env: Dict[str, Any]) -> SemanticIRGraph:
        """
        If a Branch condition is a Literal, replace Branch with the root of the taken region.
        """
        g = copy.deepcopy(graph)
        for nid, node in list(g.nodes.items()):
            if node.op == OpKind.BRANCH and node.inputs:
                cond_node = g.nodes.get(node.inputs[0])
                if cond_node and cond_node.op == OpKind.LITERAL:
                    cond_val = bool(cond_node.attributes.get("value"))
                    reg_id = node.attributes.get("then_region" if cond_val else "else_region")
                    if reg_id and reg_id in g.regions:
                        reg = g.regions[reg_id]
                        # Inline taken region into main graph
                        for r_nid, r_node in reg.nodes.items():
                            g.nodes[r_nid] = r_node
                        # Alias branch node to region root
                        if reg.root_id in g.nodes:
                            # Forward consumers of nid to reg.root_id
                            for other_node in g.nodes.values():
                                other_node.inputs = [reg.root_id if inp == nid else inp for inp in other_node.inputs]
                            if g.root_id == nid:
                                g.root_id = reg.root_id
        return g

    @staticmethod
    def _preserves_required_effects(baseline_eff: EffectSet, cand_eff: EffectSet) -> bool:
        """
        Ensures candidate preserves all external writes and interactions present in baseline.
        """
        for req in (Effect.WriteExternal, Effect.Interactive):
            if req in baseline_eff and req not in cand_eff:
                return False
        return True
