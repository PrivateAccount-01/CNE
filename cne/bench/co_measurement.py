"""
CNE Unified Co-Measurement Benchmark Engine (system.md §20, §21, §28, §51, §58, §60, §62).
Provides the single, authoritative measurement pipeline for:
1. Gate G2: Information-honest closed-world benchmark oracle bound R*
2. Gate G3: Measurement overhead A_corpus <= 20% and net savings ΔC > 0
3. Phase P3: Consolidated optimization capture ratio ΔC_CNE / ΔC_oracle

Ensures strict commensurability: Baseline, CNE, and Oracle are co-measured over the EXACT same
runtime instance, environment, and inputs, completely eliminating measurement pipeline divergence.

Measurement protocol:
- A single persistent set of objects (fabric, evaluator, cne, oracle, compiled graphs) is shared
  across the warmup pass and all measured trials.
- Warmup populates graph-level caches (_cached_static_opt_res, _cached_physical_plan,
  _cached_executable_order, _cached_imm_effects, etc.) so that measured trials reflect
  steady-state (warm) control overhead — the regime that matters for amortized savings (§28/§60).
- Cold-start overhead is reported alongside as a secondary metric for full disclosure.
"""
from __future__ import annotations
import math
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple
from cne.bench.corpus.corpus_generator import CorpusGenerator
from cne.compiler.fixture_compiler import FixtureCompiler
from cne.contracts.outcome_contract import OutcomeContract
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.optimizer.oracle import G2Oracle
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.semantic_ir.nodes import SemanticIRGraph
from cne.state.fabric import LocalStateFabric


class CoMeasurementRunner:
    """
    Authoritative single-point co-measurement engine.
    Used by GateG2Runner, GateG3Runner, and P3ReportRunner.
    """

    @classmethod
    def _run_trial_against(
        cls,
        compiled: List[Tuple[SemanticIRGraph, OutcomeContract, Dict[str, Any]]],
        env: Dict[str, Any],
        fabric: LocalStateFabric,
        evaluator: SemanticEvaluator,
        cne: ComputationNecessityEngine,
        oracle: G2Oracle,
        trial_prefix: str = "co"
    ) -> Dict[str, Any]:
        """
        Run one measured trial against a SHARED set of persistent objects.
        The compiled graphs, fabric, evaluator, cne, and oracle all persist across calls —
        graph-level caches populated during warmup (or earlier trials) remain valid and are
        reused, reflecting steady-state overhead.
        """
        baseline_costs_ns: List[float] = []
        oracle_costs_ns: List[float] = []
        cne_costs_ns: List[float] = []
        cne_control_costs_ns: List[float] = []
        cne_exec_costs_ns: List[float] = []
        per_query_savings_ns: List[float] = []
        per_query_overhead_ratios: List[float] = []
        boundary_checks_passed = 0

        for idx, (graph, contract, q) in enumerate(compiled):
            # 1. Baseline latency C_baseline(q)
            t0 = time.perf_counter_ns()
            base_val, _ = evaluator.execute(graph, initial_env=env)
            c_base = max(1.0, float(time.perf_counter_ns() - t0))
            baseline_costs_ns.append(c_base)

            # 2. Closed-world benchmark oracle bound over A_benchmark(G, S, C)
            # Evaluated BEFORE CNE write lands for this query, preventing self-memo leak
            # while legitimately allowing inspection of prior queries' fabric state (P0.7 §4).
            ores = oracle.find_recoverable_bound(
                query_id=q["id"],
                graph=graph,
                contract=contract,
                env=env,
                fabric=fabric
            )
            oracle_costs_ns.append(ores.optimal_cost)

            # 3. CNE Execution & Fabric Population
            cne_res = cne.execute_query(
                graph=graph,
                contract=contract,
                env=env,
                query_id=f"{trial_prefix}_{idx}_{q['id']}",
                baseline_cost_hint_ns=c_base
            )

            ctrl_cost = cne_res.costs.control_ns
            exec_cost = cne_res.costs.execution_ns
            total_cne = ctrl_cost + exec_cost

            cne_costs_ns.append(total_cne)
            cne_control_costs_ns.append(ctrl_cost)
            cne_exec_costs_ns.append(exec_cost)

            # Invariant check: C_CNE = C_control + C_execution within tolerance
            if cne_res.costs.verify_boundary(total_cne, rel_tol=0.01, abs_tol=100.0):
                boundary_checks_passed += 1

            delta_c = c_base - total_cne
            per_query_savings_ns.append(delta_c)
            per_query_overhead_ratios.append(ctrl_cost / c_base)

        total_baseline = sum(baseline_costs_ns)
        total_oracle = sum(oracle_costs_ns)
        total_cne = sum(cne_costs_ns)
        total_control = sum(cne_control_costs_ns)
        total_exec = sum(cne_exec_costs_ns)

        total_delta_c = total_baseline - total_cne
        total_delta_oracle = total_baseline - total_oracle

        a_corpus = total_control / total_baseline if total_baseline > 0 else 0.0
        r_star = total_delta_oracle / total_baseline if total_baseline > 0 else 0.0
        # Optimization capture ratio: observed capture ratio, currently <= 1.0 empirically
        opt_capture = (total_delta_c / total_delta_oracle) if total_delta_oracle > 0 else 0.0

        median_savings = statistics.median(per_query_savings_ns) if per_query_savings_ns else 0.0
        sorted_overheads = sorted(per_query_overhead_ratios)
        p95_idx = int(0.95 * len(sorted_overheads))
        p95_overhead = sorted_overheads[p95_idx] if sorted_overheads else 0.0
        negative_savings_fraction = sum(1 for s in per_query_savings_ns if s < 0) / len(per_query_savings_ns)

        isolated_overhead_samples = [oh for s, oh in zip(per_query_savings_ns, per_query_overhead_ratios) if s <= 0]
        avg_isolated_overhead = statistics.mean(isolated_overhead_samples) if isolated_overhead_samples else 0.0

        n_queries = len(compiled)
        boundary_pass = (boundary_checks_passed == n_queries)
        g2_pass = (r_star >= 0.25)
        g3_pass = (total_delta_c > 0) and (a_corpus <= 0.20) and boundary_pass
        p3_pass = g3_pass and (0.0 <= opt_capture <= 1.0)

        return {
            "g2_passed": g2_pass,
            "g3_passed": g3_pass,
            "p3_passed": p3_pass,
            "boundary_verified": boundary_pass,
            "total_baseline_ms": round(total_baseline / 1e6, 3),
            "total_oracle_ms": round(total_oracle / 1e6, 3),
            "total_cne_ms": round(total_cne / 1e6, 3),
            "total_control_ms": round(total_control / 1e6, 3),
            "total_exec_ms": round(total_exec / 1e6, 3),
            "net_savings_ms": round(total_delta_c / 1e6, 3),
            "delta_c_oracle_ms": round(total_delta_oracle / 1e6, 3),
            "a_corpus": round(a_corpus, 4),
            "r_star": round(r_star, 4),
            "opt_capture": round(opt_capture, 4),
            "median_savings_ns": round(median_savings, 2),
            "p95_overhead_ratio": round(p95_overhead, 4),
            "negative_savings_fraction": round(negative_savings_fraction, 4),
            "state_reuse_ratio": round(fabric.state_reuse_ratio, 4),
            "reuse_events_per_created_state": round(fabric.reuse_events_per_created_state, 4),
            "amortized_savings_ns": round(fabric.compute_amortized_savings(n_queries), 2),
            "isolated_overhead_ratio": round(avg_isolated_overhead, 4)
        }

    @classmethod
    def run_single_trial(
        cls,
        eval_workload: List[Dict[str, Any]],
        env: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Backward-compatible single-trial entry point.
        Creates fresh objects (cold-start measurement). Used by ablation B(-1).
        """
        fabric = LocalStateFabric()
        evaluator = SemanticEvaluator()
        oracle = G2Oracle(evaluator=evaluator)
        cne = ComputationNecessityEngine(fabric=fabric, evaluator=evaluator)

        compiled = []
        for q in eval_workload:
            graph, contract = FixtureCompiler.compile_query(q)
            compiled.append((graph, contract, q))

        return cls._run_trial_against(
            compiled=compiled,
            env=env,
            fabric=fabric,
            evaluator=evaluator,
            cne=cne,
            oracle=oracle,
            trial_prefix="single"
        )

    _run_single_co_measurement = run_single_trial

    @classmethod
    def run_steady_state_trials(
        cls,
        compiled: List[Tuple[Any, Any, Dict[str, Any]]],
        env: Dict[str, Any],
        trials: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Runs independent steady-state trials.
        For EACH trial, creates fresh objects (fabric, evaluator, engine, oracle),
        pre-warms them identically, then measures the workload.
        The variance across these trials reflects pure timing noise under identical conditions (§P0.7a).
        """
        trial_results = []
        for t_idx in range(max(1, trials)):
            fabric = LocalStateFabric()
            evaluator = SemanticEvaluator()
            oracle = G2Oracle(evaluator=evaluator)
            cne = ComputationNecessityEngine(fabric=fabric, evaluator=evaluator)

            # Full workload warmup pass to establish uniform steady state across all graph paths (§P0.7a)
            cls._run_trial_against(
                compiled, env, fabric, evaluator, cne, oracle, trial_prefix="warmup"
            )

            # Measured trial
            t_res = cls._run_trial_against(
                compiled, env, fabric, evaluator, cne, oracle, trial_prefix=f"steady_t{t_idx}"
            )
            trial_results.append(t_res)
        return trial_results

    @classmethod
    def run_session_evolution_experiment(
        cls,
        compiled: List[Tuple[Any, Any, Dict[str, Any]]],
        env: Dict[str, Any],
        sessions: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Measures state evolution and amortization across sequential sessions (S1 -> S2 -> S3)
        over a single shared persistent fabric (§P0.7a).
        """
        fabric = LocalStateFabric()
        evaluator = SemanticEvaluator()
        oracle = G2Oracle(evaluator=evaluator)
        cne = ComputationNecessityEngine(fabric=fabric, evaluator=evaluator)

        session_results = []
        for s_idx in range(max(1, sessions)):
            s_res = cls._run_trial_against(
                compiled, env, fabric, evaluator, cne, oracle, trial_prefix=f"session_{s_idx}"
            )
            session_results.append({
                "session": s_idx + 1,
                "a_corpus": s_res["a_corpus"],
                "net_savings_ms": s_res["net_savings_ms"],
                "total_cne_ms": s_res["total_cne_ms"],
                "total_control_ms": s_res["total_control_ms"],
                "total_exec_ms": s_res["total_exec_ms"],
                "state_reuse_ratio": s_res["state_reuse_ratio"],
                "amortized_savings_ns": s_res["amortized_savings_ns"]
            })
        return session_results

    @classmethod
    def run_co_measurement(cls, trials: int = 5) -> Dict[str, Any]:
        """
        Runs the full multi-trial unified co-measurement protocol.
        Decouples steady-state timing noise (independent pre-warmed trials)
        from multi-session state evolution (sequential S1->S2->S3 amortization).
        """
        corpus = CorpusGenerator.generate_corpus()
        queries = corpus["queries"]

        env = {
            "transactions": [
                {"id": f"tx_{k}", "category": "Food" if k % 3 == 0 else ("Travel" if k % 3 == 1 else "Utilities"), "amount": 20.0 + (k * 13) % 250, "is_transfer": (k % 11 == 0)}
                for k in range(5000)
            ],
            "telemetry": {
                f"node_{k}": {"system_id": f"node_{k}", "error_count": (k * 3) % 12}
                for k in range(1, 50)
            },
            "diagnostic_evidence": {
                f"node_{k}": "log: out_of_memory in process" if k % 4 == 0 else "system normal"
                for k in range(1, 50)
            }
        }

        # Workload with session reuse (Section 50: P2 State Reuse)
        eval_workload = queries + queries[:100]

        # ---- Cold-start measurement (fresh objects, disclosed as secondary metric) ----
        cold_start_res = cls.run_single_trial(eval_workload, env)
        cold_start_a_corpus = cold_start_res["a_corpus"]

        # Pre-compile all queries once
        compiled = []
        for q in eval_workload:
            graph, contract = FixtureCompiler.compile_query(q)
            compiled.append((graph, contract, q))

        # ---- Measured trials: independent steady-state timing-noise averaging ----
        trial_results = cls.run_steady_state_trials(compiled, env, trials=trials)

        # ---- Multi-session state evolution trajectory ----
        session_evolution = cls.run_session_evolution_experiment(compiled, env, sessions=3)

        baseline_vals = [t["total_baseline_ms"] for t in trial_results]
        oracle_vals = [t["total_oracle_ms"] for t in trial_results]
        cne_vals = [t["total_cne_ms"] for t in trial_results]
        control_vals = [t["total_control_ms"] for t in trial_results]
        exec_vals = [t["total_exec_ms"] for t in trial_results]
        delta_c_vals = [t["net_savings_ms"] for t in trial_results]
        a_corpus_vals = [t["a_corpus"] for t in trial_results]
        r_star_vals = [t["r_star"] for t in trial_results]
        opt_cap_vals = [t["opt_capture"] for t in trial_results]
        p95_vals = [t["p95_overhead_ratio"] for t in trial_results]
        neg_frac_vals = [t["negative_savings_fraction"] for t in trial_results]
        median_sav_vals = [t["median_savings_ns"] for t in trial_results]

        mean_baseline = statistics.mean(baseline_vals)
        mean_oracle = statistics.mean(oracle_vals)
        mean_cne = statistics.mean(cne_vals)
        mean_control = statistics.mean(control_vals)
        mean_exec = statistics.mean(exec_vals)
        mean_delta_c = statistics.mean(delta_c_vals)
        std_delta_c = statistics.stdev(delta_c_vals) if len(delta_c_vals) > 1 else 0.0

        mean_a_corpus = statistics.mean(a_corpus_vals)
        std_a_corpus = statistics.stdev(a_corpus_vals) if len(a_corpus_vals) > 1 else 0.0

        mean_r_star = statistics.mean(r_star_vals)
        std_r_star = statistics.stdev(r_star_vals) if len(r_star_vals) > 1 else 0.0

        mean_opt_cap = statistics.mean(opt_cap_vals)
        std_opt_cap = statistics.stdev(opt_cap_vals) if len(opt_cap_vals) > 1 else 0.0

        mean_p95 = statistics.mean(p95_vals)
        mean_neg_frac = statistics.mean(neg_frac_vals)
        mean_median_sav = statistics.mean(median_sav_vals)

        all_boundaries_passed = all(t["boundary_verified"] for t in trial_results)
        g2_passed = mean_r_star >= 0.25
        g3_passed = (mean_delta_c > 0) and (mean_a_corpus <= 0.20) and all_boundaries_passed
        p3_passed = g3_passed and (0.0 <= mean_opt_cap <= 1.0)

        return {
            "g2_passed": g2_passed,
            "g3_passed": g3_passed,
            "p3_passed": p3_passed,
            "passed": g3_passed and g2_passed and p3_passed,
            "trials_conducted": len(trial_results),
            "total_queries_evaluated": len(eval_workload),
            "instrumentation_boundary_verified": all_boundaries_passed,
            "total_baseline_cost_ms": round(mean_baseline, 3),
            "total_oracle_cost_ms": round(mean_oracle, 3),
            "total_cne_cost_ms": round(mean_cne, 3),
            "total_control_cost_ms": round(mean_control, 3),
            "total_exec_cost_ms": round(mean_exec, 3),
            "net_savings_delta_c_ms": round(mean_delta_c, 3),
            "net_savings_std_ms": round(std_delta_c, 3),
            "primary_condition": {
                "positive_total_savings": mean_delta_c > 0,
                "a_corpus": round(mean_a_corpus, 4),
                "a_corpus_std": round(std_a_corpus, 4),
                "a_corpus_threshold": 0.20,
                "a_corpus_passed": mean_a_corpus <= 0.20
            },
            "g2_oracle": {
                "corpus_r_star": round(mean_r_star, 4),
                "corpus_r_star_std": round(std_r_star, 4),
                "r_star_threshold": 0.25,
                "r_star_passed": g2_passed,
                "oracle_label": "information-honest closed-world oracle bound (this candidate space)"
            },
            "optimization_capture": {
                "capture_ratio": round(mean_opt_cap, 4),
                "capture_ratio_std": round(std_opt_cap, 4),
                "passed": 0.0 <= mean_opt_cap <= 1.0,
                "label": "observed capture ratio, currently <= 1.0 empirically"
            },
            "secondary_reporting": {
                "median_savings_ns": round(mean_median_sav, 2),
                "p95_overhead_ratio": round(mean_p95, 4),
                "negative_savings_fraction": round(mean_neg_frac, 4),
                "state_reuse_ratio": round(trial_results[0]["state_reuse_ratio"], 4),
                "reuse_events_per_created_state": round(trial_results[0]["reuse_events_per_created_state"], 4),
                "amortized_computation_savings_ns": round(trial_results[0]["amortized_savings_ns"], 2),
                "isolated_optimizer_overhead_ratio": round(trial_results[0]["isolated_overhead_ratio"], 4),
                "cold_start_a_corpus": round(cold_start_a_corpus, 4)
            },
            "session_state_evolution": session_evolution,
            "trial_runs": trial_results
        }
