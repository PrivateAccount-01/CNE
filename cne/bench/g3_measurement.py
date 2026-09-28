"""
CNE Gate G3 Cost Accounting and Instrumentation Benchmark Runner.
Validates:
1. Primary scalar cost metric C = wall-clock latency (high resolution ns).
2. Instrumentation boundary: C_CNE = C_CNE_control + C_CNE_execution (verified within tolerance).
3. Primary condition: Net savings ΔC_total > 0 and corpus overhead A_corpus <= 20%.
4. Secondary distribution: median savings, p95 overhead, negative-savings fraction,
   State Reuse Ratio, Amortized Computation Savings.
5. Multi-trial repeated measurement protocol with reported variance/statistics (system.md §28, §58, §60).
"""
from __future__ import annotations
import math
import statistics
import time
from typing import Any, Dict, List, Optional
from cne.bench.corpus.corpus_generator import CorpusGenerator
from cne.compiler.fixture_compiler import FixtureCompiler
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.state.fabric import LocalStateFabric


class GateG3Runner:
    @classmethod
    def _run_single_trial(
        cls,
        eval_workload: List[Dict[str, Any]],
        env: Dict[str, Any]
    ) -> Dict[str, Any]:
        fabric = LocalStateFabric()
        evaluator = SemanticEvaluator()
        cne = ComputationNecessityEngine(fabric=fabric, evaluator=evaluator)

        baseline_costs_ns: List[float] = []
        cne_costs_ns: List[float] = []
        cne_control_costs_ns: List[float] = []
        cne_exec_costs_ns: List[float] = []
        per_query_savings_ns: List[float] = []
        per_query_overhead_ratios: List[float] = []
        boundary_checks_passed = 0

        for idx, q in enumerate(eval_workload):
            graph, contract = FixtureCompiler.compile_query(q)

            # Measure baseline cost C_baseline(q)
            t0 = time.perf_counter_ns()
            base_val, _ = evaluator.execute(graph, initial_env=env)
            base_cost = max(1.0, float(time.perf_counter_ns() - t0))
            baseline_costs_ns.append(base_cost)

            # Measure CNE
            cne_res = cne.execute_query(
                graph=graph,
                contract=contract,
                env=env,
                query_id=f"q_{idx}_{q['id']}",
                baseline_cost_hint_ns=base_cost
            )

            ctrl_cost = cne_res.costs.control_ns
            exec_cost = cne_res.costs.execution_ns
            total_cne = ctrl_cost + exec_cost

            cne_costs_ns.append(total_cne)
            cne_control_costs_ns.append(ctrl_cost)
            cne_exec_costs_ns.append(exec_cost)

            # Invariant check: C_CNE = C_control + C_execution
            if cne_res.costs.verify_boundary(total_cne, rel_tol=0.01, abs_tol=100.0):
                boundary_checks_passed += 1

            # Savings and overhead
            delta_c = base_cost - total_cne
            per_query_savings_ns.append(delta_c)
            overhead_ratio = ctrl_cost / base_cost
            per_query_overhead_ratios.append(overhead_ratio)

        total_baseline = sum(baseline_costs_ns)
        total_cne = sum(cne_costs_ns)
        total_control = sum(cne_control_costs_ns)
        total_delta_c = total_baseline - total_cne
        a_corpus = total_control / total_baseline if total_baseline > 0 else 0.0

        median_savings = statistics.median(per_query_savings_ns) if per_query_savings_ns else 0.0
        sorted_overheads = sorted(per_query_overhead_ratios)
        p95_idx = int(0.95 * len(sorted_overheads))
        p95_overhead = sorted_overheads[p95_idx] if sorted_overheads else 0.0
        negative_savings_fraction = sum(1 for s in per_query_savings_ns if s < 0) / len(per_query_savings_ns)

        isolated_overhead_samples = [oh for s, oh in zip(per_query_savings_ns, per_query_overhead_ratios) if s <= 0]
        avg_isolated_overhead = statistics.mean(isolated_overhead_samples) if isolated_overhead_samples else 0.0

        primary_pass = (total_delta_c > 0) and (a_corpus <= 0.20)
        boundary_pass = (boundary_checks_passed == len(eval_workload))

        return {
            "passed": primary_pass and boundary_pass,
            "boundary_verified": boundary_pass,
            "total_baseline_ms": round(total_baseline / 1e6, 3),
            "total_cne_ms": round(total_cne / 1e6, 3),
            "total_control_ms": round(total_control / 1e6, 3),
            "net_savings_ms": round(total_delta_c / 1e6, 3),
            "a_corpus": round(a_corpus, 4),
            "median_savings_ns": round(median_savings, 2),
            "p95_overhead_ratio": round(p95_overhead, 4),
            "negative_savings_fraction": round(negative_savings_fraction, 4),
            "state_reuse_ratio": round(fabric.state_reuse_ratio, 4),
            "amortized_savings_ns": round(fabric.compute_amortized_savings(len(eval_workload)), 2),
            "isolated_overhead_ratio": round(avg_isolated_overhead, 4)
        }

    @classmethod
    def run_g3(cls, trials: int = 5) -> Dict[str, Any]:
        from cne.bench.co_measurement import CoMeasurementRunner
        co_res = CoMeasurementRunner.run_co_measurement(trials=trials)
        res = dict(co_res)
        res["gate"] = "G3"
        res["passed"] = co_res["g3_passed"]
        res["a_corpus"] = co_res["primary_condition"]["a_corpus"]
        return res


if __name__ == "__main__":
    res = GateG3Runner.run_g3(trials=5)
    print("G3 Multi-Trial Result:")
    print(f"Passed: {res['passed']}")
    print(f"A_corpus: {res['primary_condition']['a_corpus']*100:.2f}% ± {res['primary_condition']['a_corpus_std']*100:.2f}%")
    print(f"Net Savings: {res['net_savings_delta_c_ms']:.2f} ms ± {res['net_savings_std_ms']:.2f} ms")
    print(f"P95 Overhead: {res['secondary_reporting']['p95_overhead_ratio']:.2f}x")
    print(f"Negative Savings Fraction: {res['secondary_reporting']['negative_savings_fraction']*100:.2f}%")
