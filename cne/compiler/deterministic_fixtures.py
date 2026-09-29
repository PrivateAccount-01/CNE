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


def build_habit_fitness_fixture(
    activity_type: str = "running",
    goal: float = 30.0
) -> tuple[SemanticIRGraph, OutcomeContract]:
    """
    Habit / fitness tracking fixture:
    - Observe activities log
    - Filter by activity type
    - Map to extract duration
    - Reduce to compute total duration
    - Branch to check if goal is met
    - Emit status record
    """
    g = SemanticIRGraph()

    obs = IRNode(
        id="obs_activities",
        op=OpKind.OBSERVE,
        attributes={"source": "activities", "granularity": "predicate", "predicate_desc": f"type == '{activity_type}'"},
        output_type=SemanticType.collection(SemanticType.record({"type": SemanticType.string(), "duration": SemanticType.numeric()}))
    )
    g.add_node(obs)

    filt = IRNode(
        id="filt_activity",
        op=OpKind.FILTER,
        inputs=["obs_activities"],
        attributes={"predicate": lambda a: a.get("type") == activity_type, "activity_type": activity_type},
        output_type=obs.output_type
    )
    g.add_node(filt)

    map_dur = IRNode(
        id="map_duration",
        op=OpKind.MAP,
        inputs=["filt_activity"],
        attributes={"fn": lambda a: float(a.get("duration", 0.0))},
        output_type=SemanticType.collection(SemanticType.numeric())
    )
    g.add_node(map_dur)

    red_total = IRNode(
        id="red_total_duration",
        op=OpKind.REDUCE,
        inputs=["map_duration"],
        attributes={"op": lambda a, b: a + b, "init": 0.0},
        output_type=SemanticType.numeric()
    )
    g.add_node(red_total)

    # Lazy branch: then (goal_met) / else (goal_pending)
    branch_reg_then = SemanticRegion(id="reg_then_goal")
    branch_reg_then.nodes["node_then"] = IRNode(
        id="node_then", op=OpKind.LITERAL, attributes={"value": "goal_achieved"}, output_type=SemanticType.string()
    )
    branch_reg_then.root_id = "node_then"

    branch_reg_else = SemanticRegion(id="reg_else_goal")
    branch_reg_else.nodes["node_else"] = IRNode(
        id="node_else", op=OpKind.LITERAL, attributes={"value": "goal_pending"}, output_type=SemanticType.string()
    )
    branch_reg_else.root_id = "node_else"

    g.add_region(branch_reg_then)
    g.add_region(branch_reg_else)

    branch_goal = IRNode(
        id="branch_goal_check",
        op=OpKind.BRANCH,
        inputs=["red_total_duration"],
        attributes={
            "condition": lambda tot: float(tot or 0.0) >= goal,
            "then_region": "reg_then_goal",
            "else_region": "reg_else_goal"
        },
        output_type=SemanticType.string()
    )
    g.add_node(branch_goal)

    emit = IRNode(
        id="emit_fitness",
        op=OpKind.EMIT,
        inputs=["branch_goal_check"],
        output_type=SemanticType.string()
    )
    g.add_node(emit)
    g.root_id = "emit_fitness"

    contract = OutcomeContract(contract_type=ContractType.EXACT)
    return g, contract


def build_factual_decision_fixture(
    topic: str = "deployment",
    min_confidence: float = 0.75
) -> tuple[SemanticIRGraph, OutcomeContract]:
    """
    Factual decision / hypothesis selection fixture:
    - Observe candidate options
    - Filter options by minimum confidence
    - Choose best alternative under latency/utility budget
    - Emit selected option
    """
    g = SemanticIRGraph()

    obs = IRNode(
        id="obs_options",
        op=OpKind.OBSERVE,
        attributes={"source": "decision_options", "topic": topic, "granularity": "key"},
        output_type=SemanticType.collection(SemanticType.record({"id": SemanticType.string(), "confidence": SemanticType.numeric(), "expected_utility": SemanticType.numeric()}))
    )
    g.add_node(obs)

    filt = IRNode(
        id="filt_confidence",
        op=OpKind.FILTER,
        inputs=["obs_options"],
        attributes={"predicate": lambda opt: opt.get("confidence", 0.0) >= min_confidence, "min_confidence": min_confidence},
        output_type=obs.output_type
    )
    g.add_node(filt)

    choose = IRNode(
        id="choose_decision",
        op=OpKind.CHOOSE,
        inputs=["filt_confidence"],
        attributes={
            "utility_fn": lambda opt, b: opt.get("expected_utility", 0.0) if isinstance(opt, dict) else 0.0,
            "budget": {"latency": 5.0}
        },
        output_type=SemanticType.record({"id": SemanticType.string()})
    )
    g.add_node(choose)

    emit = IRNode(
        id="emit_decision",
        op=OpKind.EMIT,
        inputs=["choose_decision"],
        output_type=SemanticType.record({"id": SemanticType.string()})
    )
    g.add_node(emit)
    g.root_id = "emit_decision"

    contract = OutcomeContract(
        contract_type=ContractType.DECISION,
        acceptable_equivalence=lambda cand, ref: (
            cand.get("id") == ref.get("id") if (isinstance(cand, dict) and isinstance(ref, dict)) else (cand == ref)
        )
    )
    return g, contract


def build_recommendation_fixture(
    user_id: str = "user_1",
    min_rating: float = 4.0
) -> tuple[SemanticIRGraph, OutcomeContract]:
    """
    Recommendation / top-k retrieval fixture:
    - Observe catalog items
    - Filter items above rating threshold
    - Map to item ids
    - Reduce to ordered collection
    - Emit recommendation set
    """
    g = SemanticIRGraph()

    obs = IRNode(
        id="obs_items",
        op=OpKind.OBSERVE,
        attributes={"source": "catalog_items", "user_id": user_id, "granularity": "unconstrained"},
        output_type=SemanticType.collection(SemanticType.record({"item_id": SemanticType.string(), "rating": SemanticType.numeric()}))
    )
    g.add_node(obs)

    filt = IRNode(
        id="filt_rating",
        op=OpKind.FILTER,
        inputs=["obs_items"],
        attributes={"predicate": lambda item: item.get("rating", 0.0) >= min_rating, "min_rating": min_rating},
        output_type=obs.output_type
    )
    g.add_node(filt)

    map_id = IRNode(
        id="map_item_id",
        op=OpKind.MAP,
        inputs=["filt_rating"],
        attributes={"fn": lambda item: item.get("item_id")},
        output_type=SemanticType.collection(SemanticType.string())
    )
    g.add_node(map_id)

    def accumulate_items(acc: List[Any], item_id: Any) -> List[Any]:
        res = list(acc)
        if item_id is not None:
            res.append(item_id)
        return res

    red_coll = IRNode(
        id="red_recommendations",
        op=OpKind.REDUCE,
        inputs=["map_item_id"],
        attributes={"op": accumulate_items, "init": []},
        output_type=SemanticType.collection(SemanticType.string())
    )
    g.add_node(red_coll)

    emit = IRNode(
        id="emit_recs",
        op=OpKind.EMIT,
        inputs=["red_recommendations"],
        output_type=SemanticType.collection(SemanticType.string())
    )
    g.add_node(emit)
    g.root_id = "emit_recs"

    contract = OutcomeContract(
        contract_type=ContractType.SET_VALUED,
        acceptable_equivalence=lambda cand, ref: set(cand or []) == set(ref or [])
    )
    return g, contract


def build_cross_source_join_fixture(
    min_quantity: int = 5
) -> tuple[SemanticIRGraph, OutcomeContract]:
    """
    Structural Outlier Fixture: Cross-Source Join & Reconciliation
    Exercises a materially different primitive combination:
    - 2 Observers (orders, inventory)
    - Join on item_id == sku
    - Filter by order quantity
    - Map to line cost (quantity * unit_price)
    - Reduce to compute total cost
    - Emit final total
    """
    g = SemanticIRGraph()

    obs_orders = IRNode(
        id="obs_orders",
        op=OpKind.OBSERVE,
        attributes={"source": "orders", "granularity": "unconstrained"},
        output_type=SemanticType.collection(SemanticType.record({"order_id": SemanticType.string(), "item_id": SemanticType.string(), "quantity": SemanticType.numeric()}))
    )
    g.add_node(obs_orders)

    obs_inv = IRNode(
        id="obs_inventory",
        op=OpKind.OBSERVE,
        attributes={"source": "inventory", "granularity": "unconstrained"},
        output_type=SemanticType.collection(SemanticType.record({"sku": SemanticType.string(), "unit_price": SemanticType.numeric()}))
    )
    g.add_node(obs_inv)

    join_nodes = IRNode(
        id="join_orders_inventory",
        op=OpKind.JOIN,
        inputs=["obs_orders", "obs_inventory"],
        attributes={
            "left_key": "item_id",
            "right_key": "sku",
            "on": lambda order, inv: order.get("item_id") == inv.get("sku")
        },
        output_type=SemanticType.collection(SemanticType.any())
    )
    g.add_node(join_nodes)

    def qty_filter(pair: Any) -> bool:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            return False
        order, _ = pair
        return order.get("quantity", 0) >= min_quantity

    filt_qty = IRNode(
        id="filt_min_quantity",
        op=OpKind.FILTER,
        inputs=["join_orders_inventory"],
        attributes={"predicate": qty_filter, "min_quantity": min_quantity},
        output_type=join_nodes.output_type
    )
    g.add_node(filt_qty)

    def compute_cost(pair: Any) -> float:
        order, inv = pair
        return float(order.get("quantity", 0) * inv.get("unit_price", 0.0))

    map_cost = IRNode(
        id="map_line_cost",
        op=OpKind.MAP,
        inputs=["filt_min_quantity"],
        attributes={"fn": compute_cost},
        output_type=SemanticType.collection(SemanticType.numeric())
    )
    g.add_node(map_cost)

    red_sum = IRNode(
        id="red_total_cost",
        op=OpKind.REDUCE,
        inputs=["map_line_cost"],
        attributes={"op": lambda a, b: a + b, "init": 0.0},
        output_type=SemanticType.numeric()
    )
    g.add_node(red_sum)

    emit = IRNode(
        id="emit_reconciliation",
        op=OpKind.EMIT,
        inputs=["red_total_cost"],
        output_type=SemanticType.numeric()
    )
    g.add_node(emit)
    g.root_id = "emit_reconciliation"

    contract = OutcomeContract(
        contract_type=ContractType.APPROXIMATE_NUMERIC,
        tolerances={"rel_tol": 1e-4, "abs_tol": 1e-6}
    )
    return g, contract
