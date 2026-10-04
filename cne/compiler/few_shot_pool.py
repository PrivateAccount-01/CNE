"""
Phase P1 Few-Shot Demonstration Pool.
Curates high-quality canonical demonstrations covering all 10 topologies + rejection.
Provides topology-diverse selection for inference-time prompt construction.

Invariants:
1. All demonstrations use ONLY the 11 frozen primitives (+Literal).
2. Each gold AST passes validate_raw_graph() static validation.
3. Pool is immutable after construction — no runtime modification.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FewShotDemo:
    """A single canonical demonstration."""
    topology: str
    query_text: str
    gold_ast: Dict[str, Any]
    outcome: str = "COMPILED"

    def to_messages(self) -> List[Dict[str, str]]:
        """Convert to chat message pair (user query -> assistant AST)."""
        return [
            {"role": "user", "content": self.query_text},
            {"role": "assistant", "content": json.dumps(self.gold_ast, separators=(",", ":"))}
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Canonical Demonstration Pool (11 entries: 10 topologies + 1 rejection)
# ─────────────────────────────────────────────────────────────────────────────

_CANONICAL_DEMOS: List[FewShotDemo] = [
    # 1. Expense (Observe -> Filter -> Filter -> Map -> Reduce -> Emit)
    FewShotDemo(
        topology="expense",
        query_text="Calculate total spending on Groceries over 50 dollars",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "expense",
            "reason": None,
            "contract": {"contract_type": "EXACT", "decision_boundary": None},
            "slots": {"category": "Groceries", "threshold": 50.0, "aggregation": "sum"},
            "nodes": [
                {"id": "obs_tx", "op": "Observe", "inputs": [], "attributes": {"source": "transactions"}, "output_type": "collection"},
                {"id": "filt_cat", "op": "Filter", "inputs": ["obs_tx"], "attributes": {"category": "Groceries"}, "output_type": "collection"},
                {"id": "filt_amt", "op": "Filter", "inputs": ["filt_cat"], "attributes": {"threshold": 50.0, "comparator": "gt"}, "output_type": "collection"},
                {"id": "map_amt", "op": "Map", "inputs": ["filt_amt"], "attributes": {"field": "amount"}, "output_type": "collection"},
                {"id": "red_sum", "op": "Reduce", "inputs": ["map_amt"], "attributes": {"reducer": "sum"}, "output_type": "scalar"},
                {"id": "emit_out", "op": "Emit", "inputs": ["red_sum"], "attributes": {"label": "total_expense"}, "output_type": "scalar"}
            ],
            "root_id": "emit_out"
        }
    ),

    # 2. Troubleshooting (Observe -> Filter -> Map -> Reduce -> Branch -> Choose -> Emit)
    FewShotDemo(
        topology="troubleshooting",
        query_text="My laptop keeps overheating during video calls",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "troubleshooting",
            "reason": None,
            "contract": {"contract_type": "STRUCTURED_EXPLANATION", "decision_boundary": None},
            "slots": {"symptom": "overheating", "context": "video calls", "device": "laptop"},
            "nodes": [
                {"id": "obs_logs", "op": "Observe", "inputs": [], "attributes": {"source": "system_logs", "scope": "thermal"}, "output_type": "collection"},
                {"id": "filt_thermal", "op": "Filter", "inputs": ["obs_logs"], "attributes": {"metric": "temperature", "threshold_exceed": True}, "output_type": "collection"},
                {"id": "map_patterns", "op": "Map", "inputs": ["filt_thermal"], "attributes": {"extract": "correlation_pattern"}, "output_type": "collection"},
                {"id": "red_freq", "op": "Reduce", "inputs": ["map_patterns"], "attributes": {"reducer": "frequency_rank"}, "output_type": "record"},
                {"id": "branch_severity", "op": "Branch", "inputs": ["red_freq"], "attributes": {"condition": "max_temp > critical_threshold"}, "output_type": "bool"},
                {"id": "choose_action", "op": "Choose", "inputs": ["branch_severity"], "attributes": {"strategy": "diagnostic_priority"}, "output_type": "record"},
                {"id": "emit_diag", "op": "Emit", "inputs": ["choose_action"], "attributes": {"label": "diagnosis"}, "output_type": "record"}
            ],
            "root_id": "emit_diag"
        }
    ),

    # 3. Scheduling (Observe -> Filter -> Map -> Branch -> Emit)
    FewShotDemo(
        topology="scheduling",
        query_text="Schedule a dentist appointment next Tuesday at 2pm",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "scheduling",
            "reason": None,
            "contract": {"contract_type": "EXACT", "decision_boundary": None},
            "slots": {"event_type": "dentist appointment", "day": "next Tuesday", "time": "2pm"},
            "nodes": [
                {"id": "obs_calendar", "op": "Observe", "inputs": [], "attributes": {"source": "calendar", "date": "next Tuesday"}, "output_type": "collection"},
                {"id": "filt_slot", "op": "Filter", "inputs": ["obs_calendar"], "attributes": {"time_slot": "14:00", "available": True}, "output_type": "collection"},
                {"id": "map_event", "op": "Map", "inputs": ["filt_slot"], "attributes": {"create": "event", "title": "dentist appointment"}, "output_type": "record"},
                {"id": "branch_conflict", "op": "Branch", "inputs": ["map_event"], "attributes": {"condition": "no_overlap"}, "output_type": "bool"},
                {"id": "emit_sched", "op": "Emit", "inputs": ["branch_conflict"], "attributes": {"label": "schedule_result"}, "output_type": "record"}
            ],
            "root_id": "emit_sched"
        }
    ),

    # 4. Habit/Fitness (Observe -> Filter -> Reduce -> Branch -> Emit)
    FewShotDemo(
        topology="habit_fitness",
        query_text="How many steps have I walked this week?",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "habit_fitness",
            "reason": None,
            "contract": {"contract_type": "EXACT", "decision_boundary": None},
            "slots": {"aggregation": "sum", "activity_type": "walking", "period": "this week", "metric": "steps"},
            "nodes": [
                {"id": "obs_activities", "op": "Observe", "inputs": [], "attributes": {"source": "activities", "period": "this week"}, "output_type": "collection"},
                {"id": "filt_walk", "op": "Filter", "inputs": ["obs_activities"], "attributes": {"activity_type": "walking"}, "output_type": "collection"},
                {"id": "map_steps", "op": "Map", "inputs": ["filt_walk"], "attributes": {"field": "steps"}, "output_type": "collection"},
                {"id": "red_sum", "op": "Reduce", "inputs": ["map_steps"], "attributes": {"reducer": "sum"}, "output_type": "scalar"},
                {"id": "emit_steps", "op": "Emit", "inputs": ["red_sum"], "attributes": {"label": "total_steps"}, "output_type": "scalar"}
            ],
            "root_id": "emit_steps"
        }
    ),

    # 5. Factual Decision (Observe -> Map -> Reduce -> Join -> Branch -> Map -> Emit)
    FewShotDemo(
        topology="factual_decision",
        query_text="Should I refinance my mortgage given current rates?",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "factual_decision",
            "reason": None,
            "contract": {"contract_type": "DECISION", "decision_boundary": 0.5},
            "slots": {"topic": "mortgage refinancing", "factor": "interest_rates"},
            "nodes": [
                {"id": "obs_current", "op": "Observe", "inputs": [], "attributes": {"source": "mortgage_data"}, "output_type": "record"},
                {"id": "obs_rates", "op": "Observe", "inputs": [], "attributes": {"source": "market_rates"}, "output_type": "record"},
                {"id": "map_savings", "op": "Map", "inputs": ["obs_current"], "attributes": {"calc": "potential_savings"}, "output_type": "scalar"},
                {"id": "join_compare", "op": "Join", "inputs": ["map_savings", "obs_rates"], "attributes": {"how": "cross"}, "output_type": "record"},
                {"id": "red_net", "op": "Reduce", "inputs": ["join_compare"], "attributes": {"reducer": "net_benefit"}, "output_type": "scalar"},
                {"id": "branch_decide", "op": "Branch", "inputs": ["red_net"], "attributes": {"condition": "net_benefit > 0"}, "output_type": "bool"},
                {"id": "emit_decision", "op": "Emit", "inputs": ["branch_decide"], "attributes": {"label": "refinance_decision"}, "output_type": "bool"}
            ],
            "root_id": "emit_decision"
        }
    ),

    # 6. Recommendation (Observe -> Filter -> Map -> Reduce -> Emit)
    FewShotDemo(
        topology="recommendation",
        query_text="Suggest a budget-friendly restaurant near downtown",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "recommendation",
            "reason": None,
            "contract": {"contract_type": "SET_VALUED", "decision_boundary": None},
            "slots": {"criteria": "budget-friendly", "location": "downtown", "category": "restaurant"},
            "nodes": [
                {"id": "obs_venues", "op": "Observe", "inputs": [], "attributes": {"source": "venues", "category": "restaurant"}, "output_type": "collection"},
                {"id": "filt_loc", "op": "Filter", "inputs": ["obs_venues"], "attributes": {"location": "downtown"}, "output_type": "collection"},
                {"id": "filt_budget", "op": "Filter", "inputs": ["filt_loc"], "attributes": {"price_range": "budget"}, "output_type": "collection"},
                {"id": "map_score", "op": "Map", "inputs": ["filt_budget"], "attributes": {"calc": "relevance_score"}, "output_type": "collection"},
                {"id": "red_top", "op": "Reduce", "inputs": ["map_score"], "attributes": {"reducer": "top_k", "k": 3}, "output_type": "collection"},
                {"id": "emit_recs", "op": "Emit", "inputs": ["red_top"], "attributes": {"label": "recommendations"}, "output_type": "collection"}
            ],
            "root_id": "emit_recs"
        }
    ),

    # 7. Cross-Source Join (Observe x2 -> Map x2 -> Join -> Map -> Reduce -> Emit)
    FewShotDemo(
        topology="cross_source_join_aggregate",
        query_text="Compare my bank statement with credit card charges for discrepancies",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "cross_source_join_aggregate",
            "reason": None,
            "contract": {"contract_type": "SET_VALUED", "decision_boundary": None},
            "slots": {"source_a": "bank_statement", "source_b": "credit_card"},
            "nodes": [
                {"id": "obs_bank", "op": "Observe", "inputs": [], "attributes": {"source": "bank_statement"}, "output_type": "collection"},
                {"id": "obs_cc", "op": "Observe", "inputs": [], "attributes": {"source": "credit_card"}, "output_type": "collection"},
                {"id": "map_bank_norm", "op": "Map", "inputs": ["obs_bank"], "attributes": {"normalize": "amount_date"}, "output_type": "collection"},
                {"id": "map_cc_norm", "op": "Map", "inputs": ["obs_cc"], "attributes": {"normalize": "amount_date"}, "output_type": "collection"},
                {"id": "join_match", "op": "Join", "inputs": ["map_bank_norm", "map_cc_norm"], "attributes": {"how": "outer", "on": "date_amount"}, "output_type": "collection"},
                {"id": "filt_mismatch", "op": "Filter", "inputs": ["join_match"], "attributes": {"condition": "unmatched"}, "output_type": "collection"},
                {"id": "map_detail", "op": "Map", "inputs": ["filt_mismatch"], "attributes": {"extract": "discrepancy_detail"}, "output_type": "collection"},
                {"id": "emit_disc", "op": "Emit", "inputs": ["map_detail"], "attributes": {"label": "discrepancies"}, "output_type": "collection"}
            ],
            "root_id": "emit_disc"
        }
    ),

    # 8. Comparative Trend (Observe x2 -> Filter x2 -> Map x2 -> Reduce x2 -> Join -> Map -> Emit)
    FewShotDemo(
        topology="comparative_trend",
        query_text="How has my grocery spending changed from Q1 to Q2?",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "comparative_trend",
            "reason": None,
            "contract": {"contract_type": "EXACT", "decision_boundary": None},
            "slots": {"category": "grocery", "period_a": "Q1", "period_b": "Q2"},
            "nodes": [
                {"id": "obs_q1", "op": "Observe", "inputs": [], "attributes": {"period": "Q1", "source": "expenses"}, "output_type": "collection"},
                {"id": "obs_q2", "op": "Observe", "inputs": [], "attributes": {"period": "Q2", "source": "expenses"}, "output_type": "collection"},
                {"id": "filt_q1", "op": "Filter", "inputs": ["obs_q1"], "attributes": {"category": "grocery"}, "output_type": "collection"},
                {"id": "filt_q2", "op": "Filter", "inputs": ["obs_q2"], "attributes": {"category": "grocery"}, "output_type": "collection"},
                {"id": "map_q1", "op": "Map", "inputs": ["filt_q1"], "attributes": {"field": "amount"}, "output_type": "collection"},
                {"id": "map_q2", "op": "Map", "inputs": ["filt_q2"], "attributes": {"field": "amount"}, "output_type": "collection"},
                {"id": "red_q1", "op": "Reduce", "inputs": ["map_q1"], "attributes": {"reducer": "sum"}, "output_type": "scalar"},
                {"id": "red_q2", "op": "Reduce", "inputs": ["map_q2"], "attributes": {"reducer": "sum"}, "output_type": "scalar"},
                {"id": "join_periods", "op": "Join", "inputs": ["red_q1", "red_q2"], "attributes": {"how": "cross"}, "output_type": "record"},
                {"id": "map_pct", "op": "Map", "inputs": ["join_periods"], "attributes": {"calc": "pct_change"}, "output_type": "scalar"},
                {"id": "emit_trend", "op": "Emit", "inputs": ["map_pct"], "attributes": {"label": "trend"}, "output_type": "scalar"}
            ],
            "root_id": "emit_trend"
        }
    ),

    # 9. Predictive Alert (Observe -> Filter -> Map -> Reduce -> Map -> Branch -> Emit)
    FewShotDemo(
        topology="predictive_alert",
        query_text="Will my disk space run out at the current growth rate?",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "predictive_alert",
            "reason": None,
            "contract": {"contract_type": "DECISION", "decision_boundary": 0.80},
            "slots": {"metric": "disk_space", "growth_rate_threshold": 0.15},
            "nodes": [
                {"id": "obs_telemetry", "op": "Observe", "inputs": [], "attributes": {"source": "disk_telemetry"}, "output_type": "collection"},
                {"id": "filt_valid", "op": "Filter", "inputs": ["obs_telemetry"], "attributes": {"non_null": True}, "output_type": "collection"},
                {"id": "map_velocity", "op": "Map", "inputs": ["filt_valid"], "attributes": {"calc": "delta"}, "output_type": "collection"},
                {"id": "red_mean", "op": "Reduce", "inputs": ["map_velocity"], "attributes": {"reducer": "mean"}, "output_type": "scalar"},
                {"id": "map_forecast", "op": "Map", "inputs": ["red_mean"], "attributes": {"model": "linear_extrapolate"}, "output_type": "scalar"},
                {"id": "branch_alert", "op": "Branch", "inputs": ["map_forecast"], "attributes": {"condition": "val > 0.85"}, "output_type": "bool"},
                {"id": "emit_alert", "op": "Emit", "inputs": ["branch_alert"], "attributes": {"label": "alert_decision"}, "output_type": "bool"}
            ],
            "root_id": "emit_alert"
        }
    ),

    # 10. Math Calculation (Literal -> Map -> Emit)
    FewShotDemo(
        topology="math_calculation",
        query_text="What is 15 percent tip on 85 dollars?",
        gold_ast={
            "outcome": "COMPILED",
            "intent": "math_calculation",
            "reason": None,
            "contract": {"contract_type": "EXACT", "decision_boundary": None},
            "slots": {"percentage": 15.0, "base_amount": 85.0},
            "nodes": [
                {"id": "lit_val", "op": "Literal", "inputs": [], "attributes": {"value": 85.0}, "output_type": "scalar"},
                {"id": "map_tip", "op": "Map", "inputs": ["lit_val"], "attributes": {"eval": "value * 0.15"}, "output_type": "scalar"},
                {"id": "emit_tip", "op": "Emit", "inputs": ["map_tip"], "attributes": {"label": "tip_amount"}, "output_type": "scalar"}
            ],
            "root_id": "emit_tip"
        }
    ),

    # 11. UNSUPPORTED_INTENT (Rejection example)
    FewShotDemo(
        topology="UNSUPPORTED",
        query_text="Turn on the living room lights",
        outcome="UNSUPPORTED_INTENT",
        gold_ast={
            "outcome": "UNSUPPORTED_INTENT",
            "intent": None,
            "reason": "Hardware device actuation is out of scope for CNE data computation.",
            "contract": {"contract_type": "NO_SOLUTION", "decision_boundary": None},
            "slots": {},
            "nodes": [],
            "root_id": ""
        }
    ),
]


class FewShotPool:
    """
    Manages canonical few-shot demonstrations for the constrained decoder.
    Provides topology-diverse selection for inference-time prompts.
    """

    def __init__(self, demos: Optional[List[FewShotDemo]] = None):
        self.demos = demos or list(_CANONICAL_DEMOS)
        self._by_topology: Dict[str, List[FewShotDemo]] = {}
        for d in self.demos:
            self._by_topology.setdefault(d.topology, []).append(d)

    @property
    def topologies(self) -> List[str]:
        return list(self._by_topology.keys())

    def select(
        self,
        query_text: str,
        k: int = 3,
        exclude_topology: Optional[str] = None,
        seed: Optional[int] = 42
    ) -> List[FewShotDemo]:
        """
        Select k topology-diverse demonstrations.
        
        Strategy:
        1. Always include 1 rejection example (UNSUPPORTED).
        2. Select remaining (k-1) from distinct topologies.
        3. If exclude_topology is specified, avoid that topology
           (prevents copying the few-shot pattern for known topologies).
        """
        rng = random.Random(seed) if seed is not None else random.Random()

        # Always include a rejection example
        rejection_demos = self._by_topology.get("UNSUPPORTED", [])
        selected: List[FewShotDemo] = []
        if rejection_demos:
            selected.append(rejection_demos[0])

        # Collect candidates from other topologies
        available_topos = [
            t for t in self.topologies
            if t != "UNSUPPORTED" and t != exclude_topology
        ]
        rng.shuffle(available_topos)

        for topo in available_topos:
            if len(selected) >= k:
                break
            candidates = self._by_topology[topo]
            selected.append(candidates[0])

        # If still under k, allow from excluded topology
        if len(selected) < k and exclude_topology and exclude_topology in self._by_topology:
            for d in self._by_topology[exclude_topology]:
                if len(selected) >= k:
                    break
                selected.append(d)

        return selected[:k]

    def get_all_messages(self) -> List[Dict[str, str]]:
        """Returns all demonstrations as flattened chat messages (for training)."""
        messages = []
        for d in self.demos:
            messages.extend(d.to_messages())
        return messages

    def get_demo_for_topology(self, topology: str) -> Optional[FewShotDemo]:
        """Returns the canonical demonstration for a given topology."""
        candidates = self._by_topology.get(topology)
        return candidates[0] if candidates else None
