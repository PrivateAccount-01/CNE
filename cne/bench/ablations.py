"""
CNE Ablation Ladder and Leave-One-Out (LOO) Attribution.
Strictly implements the frozen specification in system.md §39 & §40:

1. Baseline Ladder (§39):
   B(-1) Oracle upper bound
   B0   Direct baseline
   B1   Semantic representation
   B2   Persistent state
   B3   Dependency invalidation
   B4   Static elimination
   B5   Runtime necessity (Cost Gate)
   B6   Bounds (Lookahead & budget constraints)
   B7   Learned controller (Offline policy specialization)

2. Leave-One-Out (LOO) Attribution (§40):
   Full system minus B1
   Full system minus B2
   Full system minus B3
   Full system minus B4
   Full system minus B5
   Full system minus B6

3. Interaction Analysis (§40):
   Validates non-linear component interaction: Effect(A+B) != Effect(A) + Effect(B).
"""
from __future__ import annotations
import copy
import statistics
import time
from typing import Any, Dict, List, Optional
from cne.bench.corpus.corpus_generator import CorpusGenerator
from cne.compiler.fixture_compiler import FixtureCompiler
from cne.contracts.outcome_contract import OutcomeContract
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.optimizer.oracle import G2Oracle
from cne.optimizer.runtime.cost_gate import CostGate
from cne.optimizer.runtime.dependencies import ChangeType
from cne.optimizer.static.static_optimizer import StaticOptimizer
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.semantic_ir.nodes import OpKind
from cne.signature.memo_key import MemoKey
from cne.state.fabric import LocalStateFabric


class AblationRunner:
    @classmethod
    def run_ablations(cls, trials: int = 3) -> Dict[str, Any]:
        corpus = CorpusGenerator.generate_corpus()
        queries = corpus["queries"][:80]  # Balanced evaluation subset (40 expense, 40 troubleshooting)

        env = {
            "transactions": [
                {"id": f"tx_{k}", "category": "Food" if k % 3 == 0 else ("Travel" if k % 3 == 1 else "Utilities"), "amount": 20.0 + (k * 13) % 250, "is_transfer": (k % 11 == 0)}
                for k in range(3000)
            ],
            "telemetry": {f"node_{k}": {"system_id": f"node_{k}", "error_count": (k * 3) % 12} for k in range(1, 40)},
            "diagnostic_evidence": {f"node_{k}": "log: out_of_memory in process" if k % 4 == 0 else "system normal" for k in range(1, 40)}
        }

        # Workload with session reuse
        workload = queries + queries[:40]

        evaluator = SemanticEvaluator()
        oracle = G2Oracle(evaluator=evaluator)

        # ---------------- B(-1): Oracle Upper Bound ----------------
        # Theoretical optimal plan with zero control overhead: sum of optimal execution costs
        t_bm1_list = []
        for _ in range(trials):
            fabric_oracle = LocalStateFabric()
            total_optimal_ns = 0.0
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                mk = MemoKey.from_graph(g, input_data=env.get("inputs"))
                cached = fabric_oracle.get_by_memo_key(mk)
                if cached is not None and c.satisfies_constraints(cached.value):
                    c_cost = 0.0
                else:
                    ores = oracle.find_recoverable_bound(q["id"], g, c, env)
                    c_cost = ores.optimal_cost
                    fabric_oracle.put(f"o_{idx}", None, ores.optimal_cost, memo_key=mk, contract=c)
                total_optimal_ns += c_cost
            t_bm1_list.append(total_optimal_ns / 1e6)
        bm1_ms = statistics.mean(t_bm1_list)

        # ---------------- B0: Direct Baseline ----------------
        # Pure native query execution directly against raw environment data (no IR)
        t_b0_list = []
        for _ in range(trials):
            t0 = time.perf_counter_ns()
            for q in workload:
                domain = q.get("domain", "expense")
                if domain == "expense":
                    cat = q.get("category", "Food")
                    thresh = float(q.get("threshold", 100.0))
                    ex = q.get("exclude_transfers", True)
                    _ = sum(tx["amount"] for tx in env.get("transactions", []) if tx.get("category") == cat and tx.get("amount", 0) >= thresh and (not ex or not tx.get("is_transfer")))
                elif domain == "troubleshooting":
                    sid = q.get("system_id", "node_1")
                    tel = env.get("telemetry", {}).get(sid, {})
                    _ = {"action": "restart"} if tel.get("error_count", 0) > q.get("error_threshold", 5) else {"status": "healthy"}
                elif domain == "scheduling":
                    slots = env.get("calendar_slots", [])
                    dur = int(q.get("duration", 30))
                    _ = [s for s in slots if s.get("duration", 0) >= dur]
                else:
                    g, c = FixtureCompiler.compile_query(q)
                    evaluator.execute(g, initial_env=env)
            t_b0_list.append((time.perf_counter_ns() - t0) / 1e6)
        b0_ms = statistics.mean(t_b0_list)

        # ---------------- B1: Semantic Representation ----------------
        # Compiles to Semantic IR and executes via interpreter, zero caching or optimization
        t_b1_list = []
        for _ in range(trials):
            t0 = time.perf_counter_ns()
            for q in workload:
                g, c = FixtureCompiler.compile_query(q)
                evaluator.execute(g, initial_env=env)
            t_b1_list.append((time.perf_counter_ns() - t0) / 1e6)
        b1_ms = statistics.mean(t_b1_list)

        # ---------------- B2: Persistent State ----------------
        # B1 + Local State Fabric memoization, but coarse whole-store invalidation on mutation
        t_b2_list = []
        for _ in range(trials):
            fabric_b2 = LocalStateFabric()
            cne_b2 = ComputationNecessityEngine(fabric=fabric_b2, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=False))
            cne_b2.static_optimizer.optimize = lambda g, c: type('obj', (object,), {'optimized_graph': g, 'static_effects': {}, 'nodes_eliminated': 0, 'nodes_folded': 0})()
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                if idx > 0 and idx % 80 == 0:
                    fabric_b2._entries.clear()
                    fabric_b2._memo_index.clear()
                g, c = FixtureCompiler.compile_query(q)
                cne_b2.execute_query(g, c, env, f"b2_{idx}")
            t_b2_list.append((time.perf_counter_ns() - t0) / 1e6)
        b2_ms = statistics.mean(t_b2_list)

        # ---------------- B3: Dependency Invalidation ----------------
        # B2 + fine-grained predicate/range dependency management (selective invalidation)
        t_b3_list = []
        for _ in range(trials):
            fabric_b3 = LocalStateFabric()
            cne_b3 = ComputationNecessityEngine(fabric=fabric_b3, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=False))
            cne_b3.static_optimizer.optimize = lambda g, c: type('obj', (object,), {'optimized_graph': g, 'static_effects': {}, 'nodes_eliminated': 0, 'nodes_folded': 0})()
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                if idx > 0 and idx % 80 == 0:
                    fabric_b3.notify_data_mutation(ChangeType.INSERT, "transactions", new_row={"id": f"mut_{idx}", "category": "Travel", "amount": 99.0})
                g, c = FixtureCompiler.compile_query(q)
                cne_b3.execute_query(g, c, env, f"b3_{idx}")
            t_b3_list.append((time.perf_counter_ns() - t0) / 1e6)
        b3_ms = statistics.mean(t_b3_list)

        # ---------------- B4: Static Elimination ----------------
        # B3 + compile-time reachability, constant folding, and static slicing
        t_b4_list = []
        for _ in range(trials):
            fabric_b4 = LocalStateFabric()
            cne_b4 = ComputationNecessityEngine(fabric=fabric_b4, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=False))
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                cne_b4.execute_query(g, c, env, f"b4_{idx}")
            t_b4_list.append((time.perf_counter_ns() - t0) / 1e6)
        b4_ms = statistics.mean(t_b4_list)

        # ---------------- B5: Runtime Necessity ----------------
        # B4 + O(1) Cost Gate bypass for trivial/lightweight queries
        t_b5_list = []
        for _ in range(trials):
            fabric_b5 = LocalStateFabric()
            cne_b5 = ComputationNecessityEngine(fabric=fabric_b5, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=True))
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                cne_b5.execute_query(g, c, env, f"b5_{idx}")
            t_b5_list.append((time.perf_counter_ns() - t0) / 1e6)
        b5_ms = statistics.mean(t_b5_list)

        # ---------------- B6: Bounds & Lookahead (Doc #21) ----------------
        # B5 + BoundedLookaheadPolicy on Choose operations under budget
        t_b6_list = []
        for _ in range(trials):
            fabric_b6 = LocalStateFabric()
            cne_b6 = ComputationNecessityEngine(fabric=fabric_b6, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=True))
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                for n in g.nodes.values():
                    if n.op == OpKind.CHOOSE:
                        n.attributes["policy"] = "bounded_lookahead"
                        n.attributes["lookahead_depth"] = 2
                cne_b6.execute_query(g, c, env, f"b6_{idx}")
            t_b6_list.append((time.perf_counter_ns() - t0) / 1e6)
        b6_ms = statistics.mean(t_b6_list)

        # ---------------- B7: Learned Controller (Phase P5 Extension) ----------------
        # Scheduled for Phase P5; explicitly marked as future extension.
        b7_ms = None

        ladder = {
            "B(-1)_Oracle_Upper_Bound_ms": round(bm1_ms, 3),
            "B0_Direct_Baseline_ms": round(b0_ms, 3),
            "B1_Semantic_Representation_ms": round(b1_ms, 3),
            "B2_Persistent_State_ms": round(b2_ms, 3),
            "B3_Dependency_Invalidation_ms": round(b3_ms, 3),
            "B4_Static_Elimination_ms": round(b4_ms, 3),
            "B5_Runtime_Necessity_ms": round(b5_ms, 3),
            "B6_Bounds_Target_ms": round(b6_ms, 3),
            "B7_Learned_Controller_ms": "NOT YET IMPLEMENTED (Phase P5 Extension)"
        }

        # Full implemented system target is B6 (Bounds & Lookahead)
        full_ms = b6_ms

        # ---------------- Leave-One-Out (LOO) Ablations (§40) ----------------
        # All LOO variants use repeated-trial averaging to eliminate single-shot noise

        # Minus B1: Syntactic string-keyed cache without semantic canonicalization
        loo_b1_trials = []
        for _ in range(trials):
            raw_cache: Dict[str, Any] = {}
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                q_key = f"{q.get('domain')}_{q.get('id')}_{sorted(q.items())}"
                if q_key in raw_cache:
                    val = raw_cache[q_key]
                else:
                    g, c = FixtureCompiler.compile_query(q)
                    val, _ = evaluator.execute(g, initial_env=env)
                    raw_cache[q_key] = val
            loo_b1_trials.append((time.perf_counter_ns() - t0) / 1e6)
        loo_minus_b1_ms = statistics.mean(loo_b1_trials)

        # Minus B2: No persistent state fabric (0 caching across queries)
        loo_b2_trials = []
        for _ in range(trials):
            fabric_no_b2 = LocalStateFabric()
            cne_no_b2 = ComputationNecessityEngine(fabric=fabric_no_b2, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=True))
            cne_no_b2.fabric.get_by_memo_key = lambda mk: None  # force cache miss
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                cne_no_b2.execute_query(g, c, env, f"no_b2_{idx}")
            loo_b2_trials.append((time.perf_counter_ns() - t0) / 1e6)
        loo_minus_b2_ms = statistics.mean(loo_b2_trials)

        # Minus B3: Coarse invalidation only (all mutations flush fabric)
        loo_b3_trials = []
        for _ in range(trials):
            fabric_no_b3 = LocalStateFabric()
            cne_no_b3 = ComputationNecessityEngine(fabric=fabric_no_b3, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=True))
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                if idx > 0 and idx % 80 == 0:
                    fabric_no_b3._entries.clear()
                    fabric_no_b3._memo_index.clear()
                g, c = FixtureCompiler.compile_query(q)
                cne_no_b3.execute_query(g, c, env, f"no_b3_{idx}")
            loo_b3_trials.append((time.perf_counter_ns() - t0) / 1e6)
        loo_minus_b3_ms = statistics.mean(loo_b3_trials)

        # Minus B4: No static elimination (static optimizer disabled)
        loo_b4_trials = []
        for _ in range(trials):
            fabric_no_b4 = LocalStateFabric()
            cne_no_b4 = ComputationNecessityEngine(fabric=fabric_no_b4, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=True))
            cne_no_b4.static_optimizer.optimize = lambda g, c: type('obj', (object,), {'optimized_graph': g, 'static_effects': {}, 'nodes_eliminated': 0, 'nodes_folded': 0})()
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                cne_no_b4.execute_query(g, c, env, f"no_b4_{idx}")
            loo_b4_trials.append((time.perf_counter_ns() - t0) / 1e6)
        loo_minus_b4_ms = statistics.mean(loo_b4_trials)

        # Minus B5: No cost gate (run static optimizer unconditionally on every query)
        loo_b5_trials = []
        for _ in range(trials):
            fabric_no_b5 = LocalStateFabric()
            cne_no_b5 = ComputationNecessityEngine(fabric=fabric_no_b5, evaluator=evaluator, cost_gate=CostGate(bypass_trivial=False))
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                cne_no_b5.execute_query(g, c, env, f"no_b5_{idx}")
            loo_b5_trials.append((time.perf_counter_ns() - t0) / 1e6)
        loo_minus_b5_ms = statistics.mean(loo_b5_trials)

        # Minus B6: Greedy action choice without bounded lookahead (Doc #21)
        loo_minus_b6_ms = b5_ms

        loo_results = {
            "Full_System_Target_ms": round(full_ms, 3),
            "Minus_B1_Semantic_IR_ms": round(loo_minus_b1_ms, 3),
            "Minus_B2_Persistent_State_ms": round(loo_minus_b2_ms, 3),
            "Minus_B3_Dependency_Invalidation_ms": round(loo_minus_b3_ms, 3),
            "Minus_B4_Static_Elimination_ms": round(loo_minus_b4_ms, 3),
            "Minus_B5_Runtime_Necessity_ms": round(loo_minus_b5_ms, 3),
            "Minus_B6_Bounds_ms": round(loo_minus_b6_ms, 3),
            "Marginal_Contribution_B2_ms": round(loo_minus_b2_ms - full_ms, 3),
            "Marginal_Contribution_B4_ms": round(loo_minus_b4_ms - full_ms, 3),
            "Marginal_Contribution_B5_ms": round(loo_minus_b5_ms - full_ms, 3),
            "Marginal_Contribution_B6_ms": round(loo_minus_b6_ms - full_ms, 3)
        }

        # ---------------- Controlled 2x2 Factorial Interaction Analysis (§40) ----------------
        # Evaluates B2 (Persistent State) x B5 (Cost Gate) holding B1, B3, B4 fixed:
        # y00: Neither B2 nor B5 (No cache, No cost gate)
        # y10: B2 only (State fabric ON, Cost gate OFF)
        # y01: B5 only (Cost gate ON, State fabric OFF)
        # y11: Both B2 and B5 (State fabric ON, Cost gate ON = full_ms)
        t_y00 = []
        t_y10 = []
        t_y01 = []
        for _ in range(trials):
            # y00: No B2, No B5
            cne_00 = ComputationNecessityEngine(fabric=LocalStateFabric(), evaluator=evaluator, cost_gate=CostGate(bypass_trivial=False))
            cne_00.fabric.get_by_memo_key = lambda mk: None
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                cne_00.execute_query(g, c, env, f"y00_{idx}")
            t_y00.append((time.perf_counter_ns() - t0) / 1e6)

            # y10: B2 only (State fabric active, Cost gate bypass OFF)
            cne_10 = ComputationNecessityEngine(fabric=LocalStateFabric(), evaluator=evaluator, cost_gate=CostGate(bypass_trivial=False))
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                cne_10.execute_query(g, c, env, f"y10_{idx}")
            t_y10.append((time.perf_counter_ns() - t0) / 1e6)

            # y01: B5 only (Cost gate bypass ON, State fabric inactive)
            cne_01 = ComputationNecessityEngine(fabric=LocalStateFabric(), evaluator=evaluator, cost_gate=CostGate(bypass_trivial=True))
            cne_01.fabric.get_by_memo_key = lambda mk: None
            t0 = time.perf_counter_ns()
            for idx, q in enumerate(workload):
                g, c = FixtureCompiler.compile_query(q)
                cne_01.execute_query(g, c, env, f"y01_{idx}")
            t_y01.append((time.perf_counter_ns() - t0) / 1e6)

        y00_ms = statistics.mean(t_y00)
        y10_ms = statistics.mean(t_y10)
        y01_ms = statistics.mean(t_y01)
        y11_ms = full_ms

        factorial_interaction_ms = y11_ms - y10_ms - y01_ms + y00_ms
        interaction_detected = abs(factorial_interaction_ms) > 0.05

        if interaction_detected and factorial_interaction_ms < 0:
            analysis_text = (
                f"Super-additive interaction confirmed between persistent state (B2) and runtime necessity cost gate (B5) "
                f"in controlled 2x2 factorial evaluation (interaction effect: {factorial_interaction_ms:.2f} ms). "
                f"Combined system latency ({y11_ms:.2f} ms) achieves greater savings than the sum of independent contributions."
            )
        elif interaction_detected:
            analysis_text = (
                f"Non-additive interaction detected between B2 and B5 in controlled 2x2 factorial evaluation "
                f"(interaction effect: {factorial_interaction_ms:.2f} ms)."
            )
        else:
            analysis_text = (
                f"Additive interaction observed between B2 and B5 in controlled 2x2 factorial evaluation "
                f"(interaction effect: {factorial_interaction_ms:.2f} ms)."
            )

        return {
            "phase": "Ablations",
            "frozen_ladder": ladder,
            "leave_one_out": loo_results,
            "factorial_b2_x_b5": {
                "y00_no_b2_no_b5_ms": round(y00_ms, 3),
                "y10_b2_only_ms": round(y10_ms, 3),
                "y01_b5_only_ms": round(y01_ms, 3),
                "y11_both_b2_b5_ms": round(y11_ms, 3),
                "interaction_effect_ms": round(factorial_interaction_ms, 3),
                "interaction_detected": interaction_detected
            },
            "optimization_capture_vs_oracle": round((b1_ms - full_ms) / (b1_ms - bm1_ms), 4) if (b1_ms - bm1_ms) > 0 else 0.0,
            "interaction_detected": interaction_detected,
            "interaction_analysis": analysis_text
        }


if __name__ == "__main__":
    res = AblationRunner.run_ablations(trials=3)
    import json
    print(json.dumps(res, indent=2))
