"""
CNE Phase P3 Necessity Optimizer Consolidated Report Runner.
Unified Co-Measurement Protocol (system.md §51 & §62):
1. Co-measures Baseline, G2 Oracle (with state fabric access per §20/§21), and CNE
   over the exact same execution instance to guarantee commensurability.
2. Evaluates OptimizationCapture = ΔC_CNE / ΔC_oracle against the oracle bound.
3. Multi-trial repeated measurement protocol with reported variance/statistics (system.md §28, §58, §60).
4. Explicitly reports all secondary distribution metrics:
   - negative_savings_fraction
   - p95_overhead_ratio
   - median_savings_ns
   - State Reuse Ratio
   - Amortized Computation Savings
"""
from __future__ import annotations
import json
import statistics
import time
from typing import Any, Dict, List, Optional
from cne.bench.corpus.corpus_generator import CorpusGenerator
from cne.compiler.fixture_compiler import FixtureCompiler
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.optimizer.oracle import G2Oracle
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.signature.memo_key import MemoKey
from cne.state.fabric import LocalStateFabric


class P3ReportRunner:
    @classmethod
    def _run_single_co_measurement(
        cls,
        eval_workload: List[Dict[str, Any]],
        env: Dict[str, Any]
    ) -> Dict[str, Any]:
        fabric = LocalStateFabric()
        evaluator = SemanticEvaluator()
        oracle = G2Oracle(evaluator=evaluator)
        cne = ComputationNecessityEngine(fabric=fabric, evaluator=evaluator)

        tot_base_ns = 0.0
        tot_oracle_ns = 0.0
        tot_cne_ns = 0.0
        tot_control_ns = 0.0
        tot_exec_ns = 0.0

        per_query_cne_savings: List[float] = []
        per_query_overheads: List[float] = []
        boundary_checks_passed = 0

        for idx, q in enumerate(eval_workload):
            graph, contract = FixtureCompiler.compile_query(q)

            # 1. Measure baseline cost C_baseline(q)
            t0 = time.perf_counter_ns()
            base_val, _ = evaluator.execute(graph, initial_env=env)
            c_base = max(1.0, float(time.perf_counter_ns() - t0))

            # 2. Evaluate G2 Oracle over A(G, S, C) on the EXACT same state & inputs
            # Per system.md §20/§21.1: Persistent state S is allowed information.
            ores = oracle.find_recoverable_bound(
                query_id=q["id"],
                graph=graph,
                contract=contract,
                env=env,
                fabric=fabric
            )
            c_oracle = ores.optimal_cost

            # 3. Execute CNE pipeline on the exact same instance
            cne_res = cne.execute_query(
                graph=graph,
                contract=contract,
                env=env,
                query_id=f"p3_{idx}_{q['id']}",
                baseline_cost_hint_ns=c_base
            )

            ctrl_cost = cne_res.costs.control_ns
            exec_cost = cne_res.costs.execution_ns
            c_cne = ctrl_cost + exec_cost

            if cne_res.costs.verify_boundary(c_cne, rel_tol=0.01, abs_tol=100.0):
                boundary_checks_passed += 1

            tot_base_ns += c_base
            tot_oracle_ns += c_oracle
            tot_cne_ns += c_cne
            tot_control_ns += ctrl_cost
            tot_exec_ns += exec_cost

            delta_c = c_base - c_cne
            per_query_cne_savings.append(delta_c)
            per_query_overheads.append(ctrl_cost / c_base)

        delta_c_cne_ns = tot_base_ns - tot_cne_ns
        delta_c_oracle_ns = tot_base_ns - tot_oracle_ns

        # Optimization Capture: ΔC_CNE / ΔC_oracle (strictly <= 1.0)
        opt_capture = (delta_c_cne_ns / delta_c_oracle_ns) if delta_c_oracle_ns > 0 else 0.0
        r_star = delta_c_oracle_ns / tot_base_ns if tot_base_ns > 0 else 0.0
        a_corpus = tot_control_ns / tot_base_ns if tot_base_ns > 0 else 0.0

        sorted_oh = sorted(per_query_overheads)
        p95_oh = sorted_oh[int(0.95 * len(sorted_oh))] if sorted_oh else 0.0
        neg_frac = sum(1 for s in per_query_cne_savings if s < 0) / len(per_query_cne_savings)
        med_sav = statistics.median(per_query_cne_savings) if per_query_cne_savings else 0.0

        return {
            "baseline_cost_ms": round(tot_base_ns / 1e6, 3),
            "oracle_cost_ms": round(tot_oracle_ns / 1e6, 3),
            "cne_cost_ms": round(tot_cne_ns / 1e6, 3),
            "control_cost_ms": round(tot_control_ns / 1e6, 3),
            "execution_cost_ms": round(tot_exec_ns / 1e6, 3),
            "delta_c_total_ms": round(delta_c_cne_ns / 1e6, 3),
            "delta_c_oracle_ms": round(delta_c_oracle_ns / 1e6, 3),
            "r_star_recoverable_bound": round(r_star, 4),
            "optimizer_overhead_a_corpus": round(a_corpus, 4),
            "optimization_capture_ratio": round(opt_capture, 4),
            "median_savings_ns": round(med_sav, 2),
            "p95_overhead_ratio": round(p95_oh, 4),
            "negative_savings_fraction": round(neg_frac, 4),
            "state_reuse_ratio": round(fabric.state_reuse_ratio, 4),
            "amortized_computation_savings_ns": round(fabric.compute_amortized_savings(len(eval_workload)), 2),
            "boundary_verified": (boundary_checks_passed == len(eval_workload))
        }

    @classmethod
    def generate_report(cls, trials: int = 5) -> Dict[str, Any]:
        from cne.bench.co_measurement import CoMeasurementRunner
        co_res = CoMeasurementRunner.run_co_measurement(trials=trials)
        report = {
            "phase": "P3",
            "passed": co_res["p3_passed"],
            "trials_conducted": co_res["trials_conducted"],
            "baseline_cost_ms": co_res["total_baseline_cost_ms"],
            "oracle_cost_ms": co_res["total_oracle_cost_ms"],
            "cne_cost_ms": co_res["total_cne_cost_ms"],
            "control_cost_ms": co_res["total_control_cost_ms"],
            "execution_cost_ms": co_res["total_exec_cost_ms"],
            "r_star_recoverable_bound": co_res["g2_oracle"]["corpus_r_star"],
            "r_star_recoverable_bound_std": co_res["g2_oracle"]["corpus_r_star_std"],
            "oracle_bound_label": co_res["g2_oracle"]["oracle_label"],
            "optimizer_overhead_a_corpus": co_res["primary_condition"]["a_corpus"],
            "optimizer_overhead_a_corpus_std": co_res["primary_condition"]["a_corpus_std"],
            "delta_c_total_ms": co_res["net_savings_delta_c_ms"],
            "delta_c_total_std_ms": co_res["net_savings_std_ms"],
            "optimization_capture_ratio": co_res["optimization_capture"]["capture_ratio"],
            "optimization_capture_ratio_std": co_res["optimization_capture"]["capture_ratio_std"],
            "optimization_capture_label": co_res["optimization_capture"]["label"],
            "median_savings_ns": co_res["secondary_reporting"]["median_savings_ns"],
            "p95_overhead_ratio": co_res["secondary_reporting"]["p95_overhead_ratio"],
            "negative_savings_fraction": co_res["secondary_reporting"]["negative_savings_fraction"],
            "state_reuse_ratio": co_res["secondary_reporting"]["state_reuse_ratio"],
            "reuse_events_per_created_state": co_res["secondary_reporting"].get("reuse_events_per_created_state", co_res["secondary_reporting"]["state_reuse_ratio"]),
            "amortized_computation_savings_ns": co_res["secondary_reporting"]["amortized_computation_savings_ns"],
            "boundary_verified": co_res["instrumentation_boundary_verified"],
            "co_measurement": co_res
        }
        return report


if __name__ == "__main__":
    rep = P3ReportRunner.generate_report(trials=5)
    print("\n================== P3 REPORT ==================")
    print(json.dumps(rep, indent=2))
