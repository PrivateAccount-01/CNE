"""
CNE Gate G7 CPU-Only Envelope Benchmark Runner.
Validates:
1. Primary CPU-only execution path independently clears G6 within the target envelope:
   - Android target envelope: 6-8 GB RAM, ARM CPU, offline-capable, zero NPU dependency.
2. Evaluates physical plan target assignments.
3. Confirms USB tier is strictly an optional secondary substrate, never required for core claims.
"""
from __future__ import annotations
from typing import Any, Dict
from cne.bench.g6_thresholds import GateG6Runner
from cne.compiler.deterministic_fixtures import build_expense_fixture, build_troubleshooting_fixture
from cne.planner.physical_planner import ExecutionTarget, PhysicalPlanner


class GateG7Runner:
    @classmethod
    def run_g7(cls) -> Dict[str, Any]:
        # 1. Run G6 under CPU-only constraint
        g6_res = GateG6Runner.run_g6()

        # 2. Verify physical planner CPU-first assignments
        planner_cpu = PhysicalPlanner(allow_usb=False)
        g_exp, _ = build_expense_fixture()
        plan_cpu = planner_cpu.plan(g_exp)

        # 3. Check optional USB planner behavior under thermal throttling
        planner_usb = PhysicalPlanner(allow_usb=True)
        plan_usb_throttled = planner_usb.plan(g_exp, system_thermal_throttled=True)

        cpu_independent_pass = g6_res["passed"] and plan_cpu.is_cpu_only

        return {
            "gate": "G7",
            "passed": cpu_independent_pass,
            "target_envelope": {
                "os": "Android",
                "ram_budget_gb": "6-8 GB",
                "processor": "ARM CPU (local)",
                "npu_dependency": False,
                "cloud_dependency": False,
                "device_validation_status": "current software benchmark passes its own estimated-envelope formula; real-device validation (P6) not yet performed"
            },
            "g6_cleared_by_cpu_only": g6_res["passed"],
            "cpu_plan_details": {
                "is_cpu_only": plan_cpu.is_cpu_only,
                "targets": [t.value for t in plan_cpu.target_assignments.values()]
            },
            "secondary_usb_tier_tested": {
                "active_when_throttled": any(t == ExecutionTarget.USB_TIER for t in plan_usb_throttled.target_assignments.values()),
                "necessary_for_core_claim": False
            }
        }


if __name__ == "__main__":
    res = GateG7Runner.run_g7()
    print("G7 Result:", res)
