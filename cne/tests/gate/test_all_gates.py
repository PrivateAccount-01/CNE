"""
Automated Pytest Gate Suite.
Verifies all frozen benchmark gates:
- Gate G0: Fixture representability
- Gate G1: Semantic signatures (G1a, G1b, G1c)
- Gate G2: Information-honest oracle bound R*
- Gate G3: Measurement and Cost accounting (ΔC > 0, A <= 20%)
- Gate G4: 100/100 state correctness & selectivity
- Gate G5: Calibration & Wilson score confidence interval
- Gate G6: Frozen baseline-only thresholds
- Gate G7: CPU-only deployment envelope
"""
import pytest
from cne.bench.g0 import GateG0Runner
from cne.bench.g1 import GateG1Runner
from cne.bench.g2_oracle import GateG2Runner
from cne.bench.g3_measurement import GateG3Runner
from cne.bench.g4_state import GateG4Runner
from cne.bench.g5_calibration import GateG5Runner
from cne.bench.g6_thresholds import GateG6Runner
from cne.bench.g7_envelope import GateG7Runner


def test_gate_g0():
    res = GateG0Runner.run_g0()
    assert res["passed"]
    assert res["new_primitives_count"] <= 2


def test_gate_g1():
    res = GateG1Runner.run_g1()
    assert res["passed"]
    assert res["g1a"]["passed"]
    assert res["g1b"]["passed"]
    assert res["g1c"]["passed"]


def test_gate_g2_oracle():
    res = GateG2Runner.run_g2()
    assert res["passed"]
    assert res["train_eval_disjoint"]
    assert res["corpus_r_star"] >= 0.10


def test_gate_g3_measurement():
    res = GateG3Runner.run_g3()
    assert res["passed"]
    assert res["primary_condition"]["positive_total_savings"]
    assert res["primary_condition"]["a_corpus_passed"]
    assert res["instrumentation_boundary_verified"]


def test_gate_g4_state():
    res = GateG4Runner.run_g4()
    assert res["passed"]
    assert res["passed_test_cases"] == 100
    assert res["no_solution_tests"]["passed"]


def test_gate_g5_calibration():
    res = GateG5Runner.run_g5(sample_count=480)
    assert res["passed"]
    assert res["sample_floor_met"]
    assert res["wilson_ci_95_lower_bound"] >= 0.95


def test_gate_g6_thresholds():
    res = GateG6Runner.run_g6()
    assert res["passed"]


def test_gate_g7_envelope():
    res = GateG7Runner.run_g7()
    assert res["passed"]
    assert res["cpu_plan_details"]["is_cpu_only"]
