"""
CNE Natural Language Task Compiler (Phase P0.7).
Rule-based, non-learned pipeline that classifies incoming queries into one of 4 outcomes:
1. COMPILED: Confidently mapped to a known computational intent template (>= 0.65 confidence).
2. UNSUPPORTED_INTENT: Recognized as a valid request, but domain is completely outside supported templates.
3. AMBIGUOUS_INTENT: Matches two or more templates with comparable confidence (margin <= 0.12).
4. LOW_CONFIDENCE_MAPPING: Partially matches an intent, but confidence is below the threshold floor.

Supports 7 distinct topologies including the required structural outlier:
1. Expense
2. Troubleshooting
3. Scheduling
4. Habit / Fitness
5. Factual Decision
6. Recommendation
7. Cross-Source Join & Reconciliation (Structural Outlier)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from cne.compiler.deterministic_fixtures import (
    build_cross_source_join_fixture,
    build_expense_fixture,
    build_factual_decision_fixture,
    build_habit_fitness_fixture,
    build_recommendation_fixture,
    build_scheduling_fixture,
    build_troubleshooting_fixture,
)
from cne.contracts.outcome_contract import OutcomeContract
from cne.effects.effect_set import EffectSet
from cne.effects.execution_policy import ExecutionPolicy
from cne.effects.propagation import EffectPropagator
from cne.semantic_ir.nodes import SemanticIRGraph
from cne.signature.canonicalization import Canonicalizer
from cne.signature.shape_key import SemanticShapeKey


class ClassificationOutcome(str, Enum):
    COMPILED = "COMPILED"
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"
    LOW_CONFIDENCE_MAPPING = "LOW_CONFIDENCE_MAPPING"


@dataclass
class CompilationResult:
    query_text: str
    outcome: ClassificationOutcome
    confidence: float
    intent: Optional[str] = None
    graph: Optional[SemanticIRGraph] = None
    contract: Optional[OutcomeContract] = None
    extracted_slots: Dict[str, Any] = field(default_factory=dict)
    competing_intents: List[Tuple[str, float]] = field(default_factory=list)
    reason: Optional[str] = None


class NLCompiler:
    """
    Hardware-agnostic, deterministic natural language compiler for CNE.
    """

    CONFIDENCE_FLOOR = 0.65
    AMBIGUITY_MARGIN = 0.12

    UNSUPPORTED_DOMAINS: Dict[str, List[str]] = {
        "weather": ["weather", "forecast", "rain", "temperature", "sunny", "humidity", "climate"],
        "translation": ["translate", "spanish", "french", "german", "language", "translation"],
        "crypto_stocks": ["stock", "shares", "crypto", "bitcoin", "nasdaq", "ticker", "dividend"],
        "creative": ["poem", "poetry", "write a story", "joke", "rhyme", "essay", "song lyrics"],
        "media": ["generate image", "draw picture", "paint", "photograph", "play music", "stream"],
        "code_gen": ["write python", "write javascript", "compile c++", "debug function", "css style"],
        "travel_booking": ["book flight", "hotel reservation", "airline ticket", "airport boarding"],
        "cooking": ["recipe", "ingredients", "bake", "cook dinner", "boil pasta"],
    }

    INTENT_KEYWORDS: Dict[str, Dict[str, Any]] = {
        "expense": {
            "primary": [
                "spend", "spent", "spending", "expense", "expenses", "expenditure", "expenditures",
                "disbursement", "disbursements", "purchase", "purchases", "cost", "costs",
                "transaction", "transactions", "debit", "debits", "charge", "charges", "ledger",
                "total spend", "net total"
            ],
            "secondary": [
                "food", "travel", "groceries", "utilities", "shopping", "entertainment", "dining",
                "health", "office", "electronics", "above", "exceeding", "over", "threshold",
                "dollars", "amount", "budget", "single", "peak", "largest", "mean", "count"
            ],
            "patterns": [
                r"(?:spent|spending|expenses?|purchases?|disbursements?|expenditures?)\s+(?:on\s+|for\s+)?([a-z]+)",
                r"(?:above|over|exceeding|higher than|greater than)\s+\$?([0-9]+(?:\.[0-9]+)?)",
                r"total\s+([a-z]+)\s+(?:spend|cost|expenditure)",
            ]
        },
        "troubleshooting": {
            "primary": [
                "diagnose", "diagnosing", "troubleshoot", "troubleshooting", "telemetry", "remediate",
                "diagnostic", "error limit", "incident", "failure", "health check", "health status",
                "operational integrity"
            ],
            "secondary": [
                "node", "server", "host", "errors", "alerts", "health", "system", "critical",
                "threshold", "failure", "incident", "trouble", "failing", "spikes"
            ],
            "patterns": [
                r"(?:node|server|host|system)[_\s]+([a-z0-9]+)",
                r"(?:error[s]?|alerts?)\s+(?:exceeding|above|over|>)\s+([0-9]+)",
                r"diagnose\s+([a-z0-9_]+)",
            ]
        },
        "scheduling": {
            "primary": [
                "schedule", "meeting", "calendar", "appointment", "slot", "availability", "book time",
                "consultation", "session", "catchup", "collaborative session", "meet with"
            ],
            "secondary": [
                "alice", "bob", "carol", "david", "dave", "emma", "frank", "grace", "minutes",
                "duration", "hours", "free", "time", "invite", "find a slot", "open slot"
            ],
            "patterns": [
                r"(?:with|for)\s+([a-z]+)",
                r"(?:duration|slot)\s+(?:of\s+)?([0-9]+)\s*(?:min|minutes)?",
                r"schedule\s+(?:a\s+)?(?:meeting|consultation|session)",
            ]
        },
        "habit_fitness": {
            "primary": [
                "fitness", "workout", "exercise", "habit", "activity", "activities", "active time",
                "training", "wellness", "athletic activity", "active duration"
            ],
            "secondary": [
                "running", "cycling", "walking", "swimming", "gym", "cardio", "minutes", "goal",
                "achieved", "target", "calories", "session", "compliance", "telemetry"
            ],
            "patterns": [
                r"(?:running|cycling|walking|swimming|gym|cardio)",
                r"goal\s+(?:of\s+)?([0-9]+(?:\.[0-9]+)?)\s*(?:min|minutes|cal)?",
                r"(?:total|log)\s+(?:workout|exercise|activity)",
            ]
        },
        "factual_decision": {
            "primary": [
                "decide", "decision", "choose option", "best alternative", "evaluate alternative",
                "pick option", "decision matrix", "hypothesis", "strategic alternatives", "tradeoff"
            ],
            "secondary": [
                "confidence", "certainty", "criteria", "tradeoff", "utility", "options", "deployment",
                "strategy", "policy", "hypothesis", "infrastructure", "release", "architecture"
            ],
            "patterns": [
                r"decide\s+(?:on\s+)?([a-z_]+)",
                r"(?:confidence|certainty)\s+(?:above|>=|over|exceeds?)\s+([0-9]+(?:\.[0-9]+)?)",
                r"evaluate\s+(?:options|alternatives|decision)",
            ]
        },
        "recommendation": {
            "primary": [
                "recommend", "recommendation", "recommendations", "suggest", "suggestions", "top items",
                "top rated", "picks", "personalized", "curated", "product suggestions"
            ],
            "secondary": [
                "catalog", "rating", "rated", "stars", "preference", "items", "score", "products",
                "top", "inventory", "client", "customer"
            ],
            "patterns": [
                r"recommend\s+(?:items|products|catalog|merchandise)",
                r"rating\s+(?:above|>=|over|exceeds?)\s+([0-9]+(?:\.[0-9]+)?)",
                r"for\s+(?:user\s+)?([a-z0-9_]+)",
            ]
        },
        "cross_source_join_aggregate": {
            "primary": [
                "reconcile", "reconciliation", "cross-reference", "join orders", "orders and inventory",
                "inventory matching", "cross source", "match orders", "connect orders", "cross-check",
                "multi-table", "cross-source"
            ],
            "secondary": [
                "orders", "inventory", "stock", "sku", "warehouse", "quantity", "unit price",
                "line total", "suppliers", "item_id", "units", "items"
            ],
            "patterns": [
                r"(?:orders?\s+(?:and|with)\s+inventory|inventory\s+(?:and|with)\s+orders?)",
                r"reconcile\s+(?:orders?|inventory|stock)",
                r"quantity\s+(?:exceeding|above|over|>=|higher than)\s+([0-9]+)",
            ]
        }
    }

    @classmethod
    def compile(cls, nl_query: str) -> CompilationResult:
        """
        Main entry point: parses text into CompilationResult with 4-way classification.
        """
        text = nl_query.strip().lower()
        if not text:
            return CompilationResult(
                query_text=nl_query,
                outcome=ClassificationOutcome.UNSUPPORTED_INTENT,
                confidence=0.0,
                reason="Empty query"
            )

        # 1. Check for explicit unsupported domains
        unsupported_match = cls._check_unsupported_domains(text)
        if unsupported_match:
            return CompilationResult(
                query_text=nl_query,
                outcome=ClassificationOutcome.UNSUPPORTED_INTENT,
                confidence=0.92,
                reason=f"Detected unsupported domain request: {unsupported_match}"
            )

        # 2. Score candidate intents
        scored_intents = cls._score_intents(text)
        if not scored_intents:
            return CompilationResult(
                query_text=nl_query,
                outcome=ClassificationOutcome.UNSUPPORTED_INTENT,
                confidence=0.85,
                reason="No recognizable computational intent pattern"
            )

        top_intent, top_score = scored_intents[0]

        # 3. Check confidence floor
        if top_score < cls.CONFIDENCE_FLOOR:
            # Check if there is a partial domain match
            if top_score >= 0.35:
                return CompilationResult(
                    query_text=nl_query,
                    outcome=ClassificationOutcome.LOW_CONFIDENCE_MAPPING,
                    confidence=round(top_score, 3),
                    intent=top_intent,
                    reason=f"Top candidate '{top_intent}' confidence {top_score:.2f} is below floor {cls.CONFIDENCE_FLOOR}"
                )
            else:
                return CompilationResult(
                    query_text=nl_query,
                    outcome=ClassificationOutcome.UNSUPPORTED_INTENT,
                    confidence=0.80,
                    reason="Intent score too low to map to known computational templates"
                )

        # 4. Check ambiguity with competitor intents
        if len(scored_intents) > 1:
            second_intent, second_score = scored_intents[1]
            if (top_score - second_score <= cls.AMBIGUITY_MARGIN) and (second_score >= 0.55):
                return CompilationResult(
                    query_text=nl_query,
                    outcome=ClassificationOutcome.AMBIGUOUS_INTENT,
                    confidence=round(top_score, 3),
                    intent=top_intent,
                    competing_intents=[(top_intent, round(top_score, 3)), (second_intent, round(second_score, 3))],
                    reason=f"Ambiguous between '{top_intent}' ({top_score:.2f}) and '{second_intent}' ({second_score:.2f})"
                )

        # 5. Intent successfully compiled -> extract slots and instantiate graph & contract
        slots = cls._extract_slots(top_intent, text)
        graph, contract = cls._instantiate_fixture(top_intent, slots)

        # Attach canonical descriptors and shape key
        descriptors, _ = Canonicalizer.canonicalize_graph(graph)
        graph._cached_descriptors = descriptors
        graph._cached_shape_hash = hashlib.sha256(json.dumps(descriptors, sort_keys=True).encode("utf-8")).hexdigest()
        graph._cached_shape_key = SemanticShapeKey.from_graph(graph)

        # Attach compile-time execution policy
        static_effects = EffectPropagator.compute_static_effects(graph)
        root_eff = static_effects.get(graph.root_id) if graph.root_id else EffectSet.pure()
        policy = ExecutionPolicy.from_effect_set(root_eff)
        graph.metadata["execution_policy"] = policy
        graph._cached_execution_policy = policy

        # Attach compile-time observed sources, observe nodes, and executable order
        graph.get_observed_sources()
        graph.get_observe_nodes()
        _ = contract.contract_repr
        from cne.semantic_ir.evaluator import SemanticEvaluator
        reachable = SemanticEvaluator.compute_reachable_nodes(graph)
        graph._cached_executable_order = [nid for nid in graph.topological_order() if nid in reachable]

        return CompilationResult(
            query_text=nl_query,
            outcome=ClassificationOutcome.COMPILED,
            confidence=round(top_score, 3),
            intent=top_intent,
            graph=graph,
            contract=contract,
            extracted_slots=slots
        )

    @classmethod
    def _check_unsupported_domains(cls, text: str) -> Optional[str]:
        words = set(re.findall(r"\b[a-z]+\b", text))
        for domain, keywords in cls.UNSUPPORTED_DOMAINS.items():
            overlap = words.intersection(keywords)
            if overlap:
                # Make sure domain primary keywords don't dominate
                has_comp_primary = any(
                    any(pk in text for pk in data["primary"])
                    for data in cls.INTENT_KEYWORDS.values()
                )
                if not has_comp_primary or len(overlap) >= 2 or any(k in ("weather", "translate", "poem", "recipe", "flight") for k in overlap):
                    return f"{domain} (matched: {', '.join(sorted(overlap))})"
        return None

    @classmethod
    def _score_intents(cls, text: str) -> List[Tuple[str, float]]:
        scores: List[Tuple[str, float]] = []
        words = set(re.findall(r"\b[a-z0-9_-]+\b", text))

        for intent, data in cls.INTENT_KEYWORDS.items():
            score = 0.0

            # Primary keyword matches
            prim_matches = [k for k in data["primary"] if k in text]
            if prim_matches:
                score += 0.45 + min(0.30, len(prim_matches) * 0.15)

            # Secondary keyword matches
            sec_matches = [k for k in data["secondary"] if k in words or k in text]
            if sec_matches:
                score += min(0.25, len(sec_matches) * 0.08)

            # Regex pattern boosts
            pattern_matches = 0
            for pat in data["patterns"]:
                if re.search(pat, text):
                    pattern_matches += 1
            if pattern_matches > 0:
                score += min(0.25, pattern_matches * 0.12)

            score = min(1.0, score)
            if score > 0.15:
                scores.append((intent, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    @classmethod
    def _extract_slots(cls, intent: str, text: str) -> Dict[str, Any]:
        slots: Dict[str, Any] = {}

        # Extract general aggregation modifier
        agg = "sum"
        if re.search(r"\b(count|how many|number of|tally|enumerate)\b", text):
            agg = "count"
        elif re.search(r"\b(max|maximum|highest|peak|largest)\b", text):
            agg = "max"
        elif re.search(r"\b(average|mean)\b", text):
            agg = "average"
        slots["aggregation"] = agg

        if intent == "expense":
            # Extract category
            cat_candidates = ["food", "travel", "utilities", "shopping", "entertainment", "health", "office", "electronics", "dining", "groceries"]
            has_cat = False
            for cat in cat_candidates:
                if cat in text:
                    slots["category"] = cat.capitalize()
                    has_cat = True
                    break
            if not has_cat:
                slots["category"] = "Food"

            # Check account specification (e.g. for user account account_101)
            m_acc = re.search(r"\b(?:account|sensor)[_\s]+([a-z0-9_]+)\b", text)
            if m_acc:
                slots["account"] = m_acc.group(1).replace(" ", "_")

            # Extract threshold
            m = re.search(r"(?:above|over|exceeding|higher than|greater than|\$|>)\s*\$?([0-9]+(?:\.[0-9]+)?)", text)
            has_thresh = False
            if m:
                slots["threshold"] = float(m.group(1))
                has_thresh = True
            else:
                m2 = re.search(r"\b([0-9]{2,4})\b", text)
                if m2:
                    slots["threshold"] = float(m2.group(1))
                    has_thresh = True
                else:
                    slots["threshold"] = 100.0

            slots["include_category_filter"] = has_cat
            slots["include_threshold_filter"] = has_thresh
            slots["exclude_transfers"] = ("include transfers" not in text)

        elif intent == "troubleshooting":
            m_node = re.search(r"\b(node_[0-9]+|node\s+[0-9]+|server_[0-9]+|host_[0-9]+)\b", text)
            if m_node:
                slots["system_id"] = m_node.group(1).replace(" ", "_")
            else:
                slots["system_id"] = "node_1"

            m_thresh = re.search(r"(?:error[s]?|limit|threshold|above|>)\s*([0-9]+)", text)
            slots["error_threshold"] = int(m_thresh.group(1)) if m_thresh else 5

        elif intent == "scheduling":
            m_user = re.search(r"(?:with|for)\s+([a-z]+)", text)
            slots["user_id"] = m_user.group(1) if m_user else "alice"

            m_dur = re.search(r"([0-9]+)\s*(?:min|minutes|hour)?", text)
            slots["duration"] = int(m_dur.group(1)) if m_dur else 30

        elif intent == "habit_fitness":
            activities = ["running", "cycling", "walking", "swimming", "gym", "cardio"]
            for act in activities:
                if act in text:
                    slots["activity_type"] = act
                    break
            if "activity_type" not in slots:
                slots["activity_type"] = "running"

            m_goal = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:min|minutes|cal|miles|km)?", text)
            slots["goal"] = float(m_goal.group(1)) if m_goal else 30.0

        elif intent == "factual_decision":
            m_top = re.search(r"decide\s+(?:on\s+)?([a-z_]+)", text)
            slots["topic"] = m_top.group(1) if m_top else "deployment"

            m_conf = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
            val = float(m_conf.group(1)) if m_conf else 0.75
            slots["min_confidence"] = val if val <= 1.0 else val / 100.0

        elif intent == "recommendation":
            m_user = re.search(r"(?:for\s+user|user)\s+([a-z0-9_]+)", text)
            slots["user_id"] = m_user.group(1) if m_user else "user_1"

            m_rate = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:stars?|rating)?", text)
            slots["min_rating"] = float(m_rate.group(1)) if m_rate else 4.0

        elif intent == "cross_source_join_aggregate":
            m_qty = re.search(r"([0-9]+)", text)
            slots["min_quantity"] = int(m_qty.group(1)) if m_qty else 5

        return slots

    @classmethod
    def _instantiate_fixture(cls, intent: str, slots: Dict[str, Any]) -> Tuple[SemanticIRGraph, OutcomeContract]:
        if intent == "expense":
            return build_expense_fixture(
                category=slots.get("category", "Food"),
                exclude_transfers=slots.get("exclude_transfers", True),
                threshold=slots.get("threshold", 100.0),
                aggregation=slots.get("aggregation", "sum"),
                include_category_filter=slots.get("include_category_filter", True),
                include_threshold_filter=slots.get("include_threshold_filter", True),
                account=slots.get("account")
            )
        elif intent == "troubleshooting":
            return build_troubleshooting_fixture(
                system_id=slots.get("system_id", "node_1"),
                error_threshold=slots.get("error_threshold", 5)
            )
        elif intent == "scheduling":
            return build_scheduling_fixture(
                user_id=slots.get("user_id", "alice"),
                required_slot_duration=slots.get("duration", 30)
            )
        elif intent == "habit_fitness":
            return build_habit_fitness_fixture(
                activity_type=slots.get("activity_type", "running"),
                goal=slots.get("goal", 30.0),
                aggregation=slots.get("aggregation", "sum")
            )
        elif intent == "factual_decision":
            return build_factual_decision_fixture(
                topic=slots.get("topic", "deployment"),
                min_confidence=slots.get("min_confidence", 0.75)
            )
        elif intent == "recommendation":
            return build_recommendation_fixture(
                user_id=slots.get("user_id", "user_1"),
                min_rating=slots.get("min_rating", 4.0)
            )
        elif intent == "cross_source_join_aggregate":
            return build_cross_source_join_fixture(
                min_quantity=slots.get("min_quantity", 5),
                aggregation=slots.get("aggregation", "sum")
            )
        else:
            raise ValueError(f"Unknown intent {intent}")
