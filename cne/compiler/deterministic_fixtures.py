"""
CNE G0 Deterministic Fixtures.
Builds executable Semantic IR graphs for three core benchmark fixtures:
1. Expense analysis fixture
2. Troubleshooting / diagnostic fixture
3. Scheduling / constraint selection fixture

All three representable strictly using the frozen 11 semantic primitives with ZERO domain-specific nodes.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import DependencyKey, SemanticType


def build_expense_fixture(
    category: str = "Food",
    exclude_transfers: bool = True,
    threshold: float = 100.0
) -> tuple[SemanticIRGraph, OutcomeContract]:
    """
    Expense analysis fixture:
    - Observe transactions from account store
    - Filter by category and transfer exclusion
    - Filter transactions exceeding threshold
    - Map to extract amount
    - Reduce to compute total spending
    - Emit final total
    """
    g = SemanticIRGraph()

    # 1. Observe transactions
    obs = IRNode(
        id="obs_tx",
        op=OpKind.OBSERVE,
        attributes={
            "source": "transactions",
            "granularity": "predicate",
            "predicate_desc": f"Category == '{category}' and Amount > {threshold}"
        },
        output_type=SemanticType.collection(SemanticType.record({"id": SemanticType.string(), "category": SemanticType.string(), "amount": SemanticType.numeric()}))
    )
    g.add_node(obs)

    # 2. Filter transactions by category and transfers
    def category_filter(tx: Dict[str, Any]) -> bool:
        if tx.get("category") != category:
            return False
        if exclude_transfers and tx.get("is_transfer", False):
            return False
        return True

    filt = IRNode(
        id="filt_cat",
        op=OpKind.FILTER,
        inputs=["obs_tx"],
        attributes={"predicate": category_filter, "category": category, "exclude_transfers": exclude_transfers},
        output_type=obs.output_type
    )
    g.add_node(filt)

    # 3. Filter high-value transactions
    def threshold_filter(tx: Dict[str, Any]) -> bool:
        return tx.get("amount", 0.0) >= threshold

    filt_thresh = IRNode(
        id="filt_thresh",
        op=OpKind.FILTER,
        inputs=["filt_cat"],
        attributes={"predicate": threshold_filter, "threshold": threshold},
        output_type=obs.output_type
    )
    g.add_node(filt_thresh)

    # 4. Map to extract amount
    map_amt = IRNode(
        id="map_amt",
        op=OpKind.MAP,
        inputs=["filt_thresh"],
        attributes={"fn": lambda tx: tx.get("amount", 0.0)},
        output_type=SemanticType.collection(SemanticType.numeric())
    )
    g.add_node(map_amt)

    # 5. Reduce to sum
    red_sum = IRNode(
        id="red_sum",
        op=OpKind.REDUCE,
        inputs=["map_amt"],
        attributes={"op": lambda a, b: a + b, "init": 0.0},
        output_type=SemanticType.numeric()
    )
    g.add_node(red_sum)

    # 6. Emit result
    emit = IRNode(
        id="emit_res",
        op=OpKind.EMIT,
        inputs=["red_sum"],
        output_type=SemanticType.numeric()
    )
    g.add_node(emit)
    g.root_id = "emit_res"

    contract = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 1e-4, "abs_tol": 1e-6}
    )
    return g, contract


def build_troubleshooting_fixture(
    system_id: str = "node_1",
    error_threshold: int = 5
) -> tuple[SemanticIRGraph, OutcomeContract]:
    """
    Troubleshooting / diagnostic fixture:
    - Observe telemetry / health metric
    - Branch lazily on threshold (if error_count > threshold)
      - then region: Observe diagnostic log, run Bayesian Update on hypothesis space,
        Choose best remediation action under budget, Emit action
      - else region: Emit 'system_healthy'
    """
    g = SemanticIRGraph()

    # 1. Observe system telemetry
    obs_telemetry = IRNode(
        id="obs_telemetry",
        op=OpKind.OBSERVE,
        attributes={"source": "telemetry", "key": system_id, "granularity": "key"},
        output_type=SemanticType.record({"system_id": SemanticType.string(), "error_count": SemanticType.numeric()})
    )
    g.add_node(obs_telemetry)

    # 2. Extract error count condition
    def is_critical(telemetry: Optional[Dict[str, Any]]) -> bool:
        if not telemetry:
            return False
        return telemetry.get("error_count", 0) > error_threshold

    map_cond = IRNode(
        id="map_cond",
        op=OpKind.MAP,
        inputs=["obs_telemetry"],
        attributes={"fn": is_critical},
        output_type=SemanticType.boolean()
    )
    g.add_node(map_cond)

    # 3. Create THEN region for lazy branch
    then_reg = SemanticRegion(id="reg_troubleshoot_then")

    obs_diag = IRNode(
        id="obs_diag",
        op=OpKind.OBSERVE,
        attributes={"source": "diagnostic_evidence", "key": system_id, "granularity": "key"},
        output_type=SemanticType.string()
    )
    then_reg.add_node(obs_diag)

    # Prior hypotheses: disk_full, memory_leak, network_partition
    prior_hypotheses = {"disk_full": 0.33, "memory_leak": 0.34, "network_partition": 0.33}

    def likelihood(h: str, evidence: Any) -> float:
        ev_str = str(evidence)
        if "out_of_memory" in ev_str:
            return 0.9 if h == "memory_leak" else 0.05
        elif "no_space" in ev_str:
            return 0.9 if h == "disk_full" else 0.05
        elif "connection_refused" in ev_str:
            return 0.9 if h == "network_partition" else 0.05
        return 0.33

    update_node = IRNode(
        id="update_belief",
        op=OpKind.UPDATE,
        inputs=["obs_diag"],
        attributes={
            "prior": prior_hypotheses,
            "likelihood_fn": likelihood
        },
        output_type=SemanticType.record({"belief": SemanticType.any()})
    )
    then_reg.add_node(update_node)

    # Choose action: restart_service, clear_cache, reboot_node, escalate
    actions = [
        {"id": "clear_cache", "cost": {"latency": 5.0, "memory": 20.0}, "target_hypothesis": "disk_full"},
        {"id": "restart_service", "cost": {"latency": 15.0, "memory": 100.0}, "target_hypothesis": "memory_leak"},
        {"id": "reboot_node", "cost": {"latency": 60.0, "memory": 500.0}, "target_hypothesis": "network_partition"},
        {"id": "escalate", "cost": {"latency": 1.0, "memory": 5.0}, "target_hypothesis": "unknown"}
    ]

    def utility(act: Dict[str, Any], belief: Dict[str, float]) -> float:
        target = act.get("target_hypothesis")
        prob = belief.get(target, 0.1)
        latency_penalty = act["cost"]["latency"] * 0.01
        return prob * 10.0 - latency_penalty

    choose_node = IRNode(
        id="choose_action",
        op=OpKind.CHOOSE,
        inputs=["update_belief"],
        attributes={
            "actions": actions,
            "budget": {"latency": 50.0, "memory": 300.0},
            "utility_fn": utility
        },
        output_type=SemanticType.record({"action": SemanticType.string()})
    )
    then_reg.add_node(choose_node)
    then_reg.root_id = "choose_action"
    g.add_region(then_reg)

    # 4. Create ELSE region for lazy branch
    else_reg = SemanticRegion(id="reg_healthy_else")
    lit_healthy = IRNode(
        id="lit_healthy",
        op=OpKind.LITERAL,
        attributes={"value": {"status": "healthy", "action": "noop"}},
        output_type=SemanticType.record({"status": SemanticType.string()})
    )
    else_reg.add_node(lit_healthy)
    else_reg.root_id = "lit_healthy"
    g.add_region(else_reg)

    # 5. Branch node (LAZY)
    branch_node = IRNode(
        id="branch_eval",
        op=OpKind.BRANCH,
        inputs=["map_cond"],
        attributes={
            "then_region": "reg_troubleshoot_then",
            "else_region": "reg_healthy_else"
        },
        output_type=SemanticType.record({"action": SemanticType.string()})
    )
    g.add_node(branch_node)

    # 6. Emit
    emit_node = IRNode(
        id="emit_troubleshoot",
        op=OpKind.EMIT,
        inputs=["branch_eval"],
        output_type=SemanticType.record({"action": SemanticType.string()})
    )
    g.add_node(emit_node)
    g.root_id = "emit_troubleshoot"

    contract = OutcomeContract(
        contract_type=ContractType.DECISION,
        acceptable_equivalence=lambda cand, ref: (
            isinstance(cand, dict) and isinstance(ref, dict) and cand.get("id") == ref.get("id")
        ) if (isinstance(cand, dict) and "id" in cand) else (cand == ref)
    )
    return g, contract


def build_scheduling_fixture(
    user_id: str = "alice",
    required_slot_duration: int = 30
) -> tuple[SemanticIRGraph, OutcomeContract]:
    """
    Scheduling fixture:
    - Observe candidate available time slots
    - Observe participant preferences and constraints
    - Join slots with participant availability
    - Filter slots matching duration and non-conflicting constraints
    - Choose optimal slot under user utility and calendar constraints
    - Emit final scheduled slot
    """
    g = SemanticIRGraph()

    # 1. Observe calendar slots
    obs_slots = IRNode(
        id="obs_slots",
        op=OpKind.OBSERVE,
        attributes={"source": "calendar_slots", "granularity": "source"},
        output_type=SemanticType.collection(SemanticType.record({"slot_id": SemanticType.string(), "duration": SemanticType.numeric()}))
    )
    g.add_node(obs_slots)

    # 2. Observe user preferences
    obs_prefs = IRNode(
        id="obs_prefs",
        op=OpKind.OBSERVE,
        attributes={"source": "user_preferences", "key": user_id, "granularity": "key"},
        output_type=SemanticType.record({"preferred_start_hour": SemanticType.numeric()})
    )
    g.add_node(obs_prefs)

    # 3. Filter valid slots by duration
    def slot_duration_filter(slot: Dict[str, Any]) -> bool:
        return slot.get("duration", 0) >= required_slot_duration

    filt_slots = IRNode(
        id="filt_valid_slots",
        op=OpKind.FILTER,
        inputs=["obs_slots"],
        attributes={"predicate": slot_duration_filter, "min_duration": required_slot_duration},
        output_type=obs_slots.output_type
    )
    g.add_node(filt_slots)

    # 4. Join slots with preferences
    join_slots = IRNode(
        id="join_slots_prefs",
        op=OpKind.JOIN,
        inputs=["filt_valid_slots", "obs_prefs"],
        attributes={"on": lambda slot, pref: True},  # pair every valid slot with preferences
        output_type=SemanticType.collection(SemanticType.any())
    )
    g.add_node(join_slots)

    # 5. Map to scored candidate meetings
    def score_slot(pair: Any) -> Dict[str, Any]:
        slot, pref = pair
        start_hour = slot.get("start_hour", 9)
        pref_hour = pref.get("preferred_start_hour", 10)
        hour_diff = abs(start_hour - pref_hour)
        utility = max(0.0, 10.0 - hour_diff * 2.0)
        return {
            "slot_id": slot.get("slot_id"),
            "start_hour": start_hour,
            "cost": {"latency": 1.0, "thermal": 0.1},
            "expected_utility": utility
        }

    map_scored = IRNode(
        id="map_scored_slots",
        op=OpKind.MAP,
        inputs=["join_slots_prefs"],
        attributes={"fn": score_slot},
        output_type=SemanticType.collection(SemanticType.any())
    )
    g.add_node(map_scored)

    # 6. Choose best slot
    def pick_best_slot(scored_slots: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not scored_slots:
            return None
        return max(scored_slots, key=lambda s: s.get("expected_utility", 0.0))

    choose_slot = IRNode(
        id="choose_slot",
        op=OpKind.CHOOSE,
        inputs=["map_scored_slots"],
        attributes={
            "utility_fn": lambda act, b: act.get("expected_utility", 0.0),
            "budget": {"latency": 10.0, "thermal": 1.0}
        },
        output_type=SemanticType.record({"slot_id": SemanticType.string()})
    )
    g.add_node(choose_slot)

    # 7. Emit
    emit_slot = IRNode(
        id="emit_slot",
        op=OpKind.EMIT,
        inputs=["choose_slot"],
        output_type=SemanticType.record({"slot_id": SemanticType.string()})
    )
    g.add_node(emit_slot)
    g.root_id = "emit_slot"

    contract = OutcomeContract(
        contract_type=ContractType.DECISION,
        acceptable_equivalence=lambda cand, ref: (
            isinstance(cand, dict) and isinstance(ref, dict) and cand.get("slot_id") == ref.get("slot_id")
        ) if (isinstance(cand, dict) and "slot_id" in cand) else (cand == ref)
    )
    return g, contract
