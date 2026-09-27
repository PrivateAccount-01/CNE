"""
CNE Master Benchmark Suite.
Runs all gates G0 through G7, generates the master summary table,
and persists the complete empirical benchmark report to cne/artifacts/reports/master_benchmark_report.json.
"""
from __future__ import annotations
import json
import os
import sys
import time
from typing import Any, Dict
from cne.bench.ablations import AblationRunner
from cne.bench.g0 import GateG0Runner
from cne.bench.g1 import GateG1Runner
from cne.bench.g2_oracle import GateG2Runner
from cne.bench.g3_measurement import GateG3Runner
from cne.bench.g4_state import GateG4Runner
from cne.bench.g5_calibration import GateG5Runner
from cne.bench.g6_thresholds import GateG6Runner
from cne.bench.g7_envelope import GateG7Runner
from cne.bench.p3_report import P3ReportRunner


def run_master_benchmark() -> Dict[str, Any]:
    print("=" * 70)
    print("      CNE MASTER IMPLEMENTATION SPECIFICATION BENCHMARK SUITE")
    print("=" * 70)

    report_dir = os.path.join(os.path.dirname(__file__), "..", "artifacts", "reports")
    os.makedirs(report_dir, exist_ok=True)

    master_results: Dict[str, Any] = {
        "benchmark_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gates": {},
        "summary": {}
    }

    gates = [
        ("G0", "Fixture Representability", GateG0Runner.run_g0),
        ("G1", "Semantic Signatures", GateG1Runner.run_g1),
        ("G2", "Information-Honest Oracle", GateG2Runner.run_g2),
        ("G3", "Measurement & Cost Accounting", GateG3Runner.run_g3),
        ("G4", "State Correctness & Selectivity", GateG4Runner.run_g4),
        ("G5", "Calibration & Verification Model", lambda: GateG5Runner.run_g5(sample_count=500)),
        ("G6", "Threshold-Freezing Protocol", GateG6Runner.run_g6),
        ("G7", "CPU-First Mobile Envelope", GateG7Runner.run_g7),
    ]

    all_passed = True
    gate_table_rows = []

    for gid, name, runner_fn in gates:
        print(f"\n[RUNNING] {gid}: {name}...")
        t0 = time.perf_counter()
        try:
            res = runner_fn()
            duration_s = time.perf_counter() - t0
            passed = res.get("passed", False)
            all_passed = all_passed and passed
            status_str = "PASS" if passed else "FAIL"
            print(f"[{status_str}] {gid}: {name} ({duration_s:.2f}s)")
            master_results["gates"][gid] = {
                "name": name,
                "passed": passed,
                "duration_seconds": round(duration_s, 2),
                "details": res
            }
            gate_table_rows.append((gid, name, status_str, f"{duration_s:.2f}s"))
        except Exception as e:
            duration_s = time.perf_counter() - t0
            all_passed = False
            print(f"[ERROR] {gid}: {name} failed with error: {e}")
            master_results["gates"][gid] = {
                "name": name,
                "passed": False,
                "duration_seconds": round(duration_s, 2),
                "error": str(e)
            }
            gate_table_rows.append((gid, name, "ERROR", f"{duration_s:.2f}s"))

    # Run Phase P3 Consolidated Report
    print(f"\n[RUNNING] Phase P3 Consolidated Co-Measurement Report...")
    t_p3_start = time.perf_counter()
    p3_res = P3ReportRunner.generate_report(trials=5)
    master_results["phase_p3"] = p3_res
    print(f"[DONE] Phase P3 completed ({time.perf_counter() - t_p3_start:.2f}s)")

    # Run Ablations Ladder (§39 & §40)
    print(f"\n[RUNNING] Ablations Ladder (B(-1) through B7)...")
    t_abl_start = time.perf_counter()
    abl_res = AblationRunner.run_ablations(trials=3)
    master_results["ablations"] = abl_res
    print(f"[DONE] Ablations completed ({time.perf_counter() - t_abl_start:.2f}s)")

    master_results["summary"] = {
        "all_gates_passed": all_passed,
        "total_gates": len(gates),
        "passed_gates": sum(1 for g in master_results["gates"].values() if g.get("passed", False))
    }

    # Save to disk
    report_file = os.path.join(report_dir, "master_benchmark_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(master_results, f, indent=2)

    # Print summary table
    print("\n" + "=" * 70)
    print("                     BENCHMARK SUMMARY TABLE")
    print("=" * 70)
    print(f"{'Gate':<6} | {'Description':<35} | {'Status':<6} | {'Time':<8}")
    print("-" * 70)
    for gid, name, status, t_str in gate_table_rows:
        print(f"{gid:<6} | {name:<35} | {status:<6} | {t_str:<8}")
    print("=" * 70)
    print(f"Overall Result: {'ALL GATES PASSED (100%)' if all_passed else 'SOME GATES FAILED'}")
    print(f"Master report saved to: {report_file}")
    print("=" * 70)

    return master_results


if __name__ == "__main__":
    run_master_benchmark()
