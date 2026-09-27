"""
CNE Phase P3 Necessity Optimizer Comprehensive Report.
Computes and reports all required Section 51 & 62 metrics:
- baseline cost
- oracle cost
- CNE cost
- control cost
- execution cost
- recoverable mass R*
- optimizer overhead A
- ΔC_total
- median savings
- p95 overhead
- negative-savings fraction
- State Reuse Ratio
- Amortized Computation Savings
- Optimization Capture = CNE savings / Oracle maximum savings
"""
from __future__ import annotations
import json
from typing import Any, Dict
from cne.bench.g2_oracle import GateG2Runner
from cne.bench.g3_measurement import GateG3Runner


class P3ReportRunner:
    @classmethod
    def generate_report(cls) -> Dict[str, Any]:
        print("Running G2 Oracle Bound calculation...")
        g2_res = GateG2Runner.run_g2()

        print("Running G3 Measurement and Cost Accounting...")
        g3_res = GateG3Runner.run_g3()

        # Costs
        baseline_cost_ms = g3_res["total_baseline_cost_ms"]
        cne_cost_ms = g3_res["total_cne_cost_ms"]
        control_cost_ms = g3_res["total_control_cost_ms"]
        exec_cost_ms = round(cne_cost_ms - control_cost_ms, 3)

        # Oracle upper bound applied to this workload
        r_star = g2_res["corpus_r_star"]
        oracle_max_savings_ms = round(baseline_cost_ms * r_star, 3)
        oracle_cost_ms = round(baseline_cost_ms - oracle_max_savings_ms, 3)

        cne_savings_ms = g3_res["net_savings_delta_c_ms"]
        optimization_capture = (cne_savings_ms / oracle_max_savings_ms) if oracle_max_savings_ms > 0 else 0.0

        report = {
            "phase": "P3",
            "passed": g3_res["passed"] and g2_res["passed"],
            "baseline_cost_ms": baseline_cost_ms,
            "oracle_cost_ms": oracle_cost_ms,
            "cne_cost_ms": cne_cost_ms,
            "control_cost_ms": control_cost_ms,
            "execution_cost_ms": exec_cost_ms,
            "r_star_recoverable_bound": r_star,
            "optimizer_overhead_a_corpus": g3_res["primary_condition"]["a_corpus"],
            "delta_c_total_ms": cne_savings_ms,
            "optimization_capture_ratio": round(optimization_capture, 4),
            "median_savings_ns": g3_res["secondary_reporting"]["median_savings_ns"],
            "p95_overhead_ratio": g3_res["secondary_reporting"]["p95_overhead_ratio"],
            "negative_savings_fraction": g3_res["secondary_reporting"]["negative_savings_fraction"],
            "state_reuse_ratio": g3_res["secondary_reporting"]["state_reuse_ratio"],
            "amortized_computation_savings_ns": g3_res["secondary_reporting"]["amortized_computation_savings_ns"]
        }
        return report


if __name__ == "__main__":
    rep = P3ReportRunner.generate_report()
    print("\n================== P3 REPORT ==================")
    print(json.dumps(rep, indent=2))
