"""
CNE Gate G3 Cost Accounting and Instrumentation Benchmark Runner.
Validates:
1. Primary scalar cost metric C = wall-clock latency (high resolution ns).
2. Instrumentation boundary: C_CNE = C_CNE_control + C_CNE_execution (verified within tolerance).
3. Primary condition: Net savings ΔC_total > 0 and corpus overhead A_corpus <= 20%.
4. Secondary distribution: median savings, p95 overhead, negative-savings fraction,
   State Reuse Ratio, Amortized Computation Savings.
5. Isolation of optimizer overhead on full baseline-equivalent cases.
"""
from __future__ import annotations
import math
import statistics
import time
from typing import Any, Dict, List
from cne.bench.corpus.corpus_generator import CorpusGenerator
from cne.compiler.fixture_compiler import FixtureCompiler
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.state.fabric import LocalStateFabric


class GateG3Runner:
    @classmethod
    def run_g3(cls) -> Dict[str, Any]:
        corpus = CorpusGenerator.generate_corpus()
        queries = corpus["queries"]

        fabric = LocalStateFabric()
        evaluator = SemanticEvaluator()
        cne = ComputationNecessityEngine(fabric=fabric, evaluator=evaluator)

        # Realistic environment with realistic mobile dataset size (Section 2 & 58)
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

        baseline_costs_ns: List[float] = []
        cne_costs_ns: List[float] = []
        cne_control_costs_ns: List[float] = []
        cne_exec_costs_ns: List[float] = []
        per_query_savings_ns: List[float] = []
        per_query_overhead_ratios: List[float] = []
        boundary_checks_passed = 0

        # Run over queries with realistic session reuse (Section 50: P2 State Reuse)
        eval_workload = queries + queries[:100]

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

        # Aggregate calculations
        total_baseline = sum(baseline_costs_ns)
        total_cne = sum(cne_costs_ns)
        total_control = sum(cne_control_costs_ns)
        total_delta_c = total_baseline - total_cne

        # Corpus-level overhead A_corpus
        a_corpus = total_control / total_baseline if total_baseline > 0 else 0.0

        # Secondary metrics
        median_savings = statistics.median(per_query_savings_ns) if per_query_savings_ns else 0.0
        sorted_overheads = sorted(per_query_overhead_ratios)
        p95_idx = int(0.95 * len(sorted_overheads))
        p95_overhead = sorted_overheads[p95_idx] if sorted_overheads else 0.0
        negative_savings_fraction = sum(1 for s in per_query_savings_ns if s < 0) / len(per_query_savings_ns)

        # Section 29: Isolation of overhead on full baseline-equivalent cases
        isolated_overhead_samples = [oh for s, oh in zip(per_query_savings_ns, per_query_overhead_ratios) if s <= 0]
        avg_isolated_overhead = statistics.mean(isolated_overhead_samples) if isolated_overhead_samples else 0.0

        # Gate G3 pass condition:
        # ΔC_total > 0 and A_corpus <= 0.20
        primary_pass = (total_delta_c > 0) and (a_corpus <= 0.20)
        boundary_pass = (boundary_checks_passed == len(eval_workload))
        overall_pass = primary_pass and boundary_pass

        return {
            "gate": "G3",
            "passed": overall_pass,
            "total_queries_evaluated": len(eval_workload),
            "instrumentation_boundary_verified": boundary_pass,
            "total_baseline_cost_ms": round(total_baseline / 1e6, 3),
            "total_cne_cost_ms": round(total_cne / 1e6, 3),
            "total_control_cost_ms": round(total_control / 1e6, 3),
            "net_savings_delta_c_ms": round(total_delta_c / 1e6, 3),
            "primary_condition": {
                "positive_total_savings": total_delta_c > 0,
                "a_corpus": round(a_corpus, 4),
                "a_corpus_threshold": 0.20,
                "a_corpus_passed": a_corpus <= 0.20
            },
            "secondary_reporting": {
                "median_savings_ns": round(median_savings, 2),
                "p95_overhead_ratio": round(p95_overhead, 4),
                "negative_savings_fraction": round(negative_savings_fraction, 4),
                "state_reuse_ratio": round(fabric.state_reuse_ratio, 4),
                "amortized_computation_savings_ns": round(fabric.compute_amortized_savings(len(eval_workload)), 2),
                "isolated_optimizer_overhead_ratio": round(avg_isolated_overhead, 4)
            }
        }


if __name__ == "__main__":
    res = GateG3Runner.run_g3()
    print("G3 Result:", res)
