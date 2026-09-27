"""
Unit tests for Choose Oracle, Greedy Policy, and Bounded Lookahead.
Validates >= 4/5 pass criterion against hand-computed/exact oracle.
"""
import pytest
from cne.optimizer.runtime.choose import (
    BoundedLookaheadPolicy,
    ChooseOracle,
    GreedyChoosePolicy
)


def test_choose_against_oracle_5_scenarios():
    scenarios = [
        # Scenario 1: Clear winner within budget
        {
            "belief": {"A": 0.8, "B": 0.2},
            "actions": [
                {"id": "a1", "cost": {"latency": 10.0}, "target": "A"},
                {"id": "a2", "cost": {"latency": 10.0}, "target": "B"},
            ],
            "budget": {"latency": 20.0},
            "utility_fn": lambda act, b: b.get(act["target"], 0.0) * 10.0,
            "expected_id": "a1"
        },
        # Scenario 2: High utility action exceeds budget, must pick affordable suboptimal
        {
            "belief": {"A": 0.9, "B": 0.1},
            "actions": [
                {"id": "a_expensive", "cost": {"latency": 50.0}, "target": "A"},
                {"id": "a_cheap", "cost": {"latency": 5.0}, "target": "B"},
            ],
            "budget": {"latency": 20.0},
            "utility_fn": lambda act, b: b.get(act["target"], 0.0) * 10.0,
            "expected_id": "a_cheap"
        },
        # Scenario 3: Multiple resource constraints (energy + memory)
        {
            "belief": {"A": 0.5, "B": 0.5},
            "actions": [
                {"id": "a1", "cost": {"energy": 15.0, "memory": 50.0}, "val": 8.0},
                {"id": "a2", "cost": {"energy": 25.0, "memory": 10.0}, "val": 12.0},  # energy over budget
                {"id": "a3", "cost": {"energy": 5.0, "memory": 20.0}, "val": 6.0},
            ],
            "budget": {"energy": 20.0, "memory": 60.0},
            "utility_fn": lambda act, b: act["val"],
            "expected_id": "a1"
        },
        # Scenario 4: Negative utility penalty dominates
        {
            "belief": {"A": 0.6, "B": 0.4},
            "actions": [
                {"id": "a_high_lat", "cost": {"latency": 30.0}, "prob": 0.6},
                {"id": "a_low_lat", "cost": {"latency": 2.0}, "prob": 0.4},
            ],
            "budget": {"latency": 50.0},
            "utility_fn": lambda act, b: act["prob"] * 10.0 - act["cost"]["latency"] * 0.5,
            # a_high_lat utility = 6.0 - 15.0 = -9.0
            # a_low_lat utility = 4.0 - 1.0 = +3.0
            "expected_id": "a_low_lat"
        },
        # Scenario 5: Multi-hypothesis tie-breaker
        {
            "belief": {"H1": 0.4, "H2": 0.4, "H3": 0.2},
            "actions": [
                {"id": "act_h1", "cost": {"latency": 5.0}, "target": "H1"},
                {"id": "act_h2", "cost": {"latency": 10.0}, "target": "H2"},
            ],
            "budget": {"latency": 20.0},
            "utility_fn": lambda act, b: b[act["target"]] * 20.0 - act["cost"]["latency"],
            # act_h1 = 8.0 - 5.0 = 3.0
            # act_h2 = 8.0 - 10.0 = -2.0
            "expected_id": "act_h1"
        }
    ]

    matches = 0
    for sc in scenarios:
        oracle_act = ChooseOracle.find_optimal_action(
            sc["belief"], sc["actions"], sc["budget"], sc["utility_fn"]
        )
        greedy_act = GreedyChoosePolicy.select_action(
            sc["belief"], sc["actions"], sc["budget"], sc["utility_fn"]
        )
        assert oracle_act is not None
        assert oracle_act["id"] == sc["expected_id"]
        if greedy_act and greedy_act["id"] == oracle_act["id"]:
            matches += 1

    assert matches >= 4  # >= 4/5 pass criterion
    assert matches == 5  # in fact 5/5 matched
