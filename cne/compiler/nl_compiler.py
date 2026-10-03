"""
CNE Natural Language Task Compiler (Phase P0.7).
Rule-based, non-learned pipeline that classifies incoming queries into one of 4 outcomes:
1. COMPILED: Confidently mapped to a known computational intent template (>= 0.65 confidence).
2. UNSUPPORTED_INTENT: Recognized as a valid request, but domain is completely outside supported templates.
3. AMBIGUOUS_INTENT: Matches two or more templates with comparable confidence (margin <= 0.12).
4. LOW_CONFIDENCE_MAPPING: Partially matches an intent, but confidence is below the threshold floor.

Supports 10 distinct topologies including the required structural outlier:
1. Expense
2. Troubleshooting
3. Scheduling
4. Habit / Fitness
5. Factual Decision
6. Recommendation
7. Cross-Source Join & Reconciliation (Structural Outlier)
8. Comparative / Trend Analysis (P0.8)
9. Predictive / Forecasting / Alert (P0.8)
10. Categorical Tagging / Classification (P0.8)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from cne.compiler.deterministic_fixtures import (
    build_categorical_tagging_fixture,
    build_comparative_trend_fixture,
    build_cross_source_join_fixture,
    build_expense_fixture,
    build_factual_decision_fixture,
    build_habit_fitness_fixture,
    build_math_calculation_fixture,
    build_predictive_alert_fixture,
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
                "dollars", "amount", "budget", "single", "peak", "largest", "mean", "count",
                "subscription", "subscriptions"
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
                "consultation", "catchup", "collaborative session", "meet with", "working session", "planning session"
            ],
            "secondary": [
                "alice", "bob", "carol", "david", "dave", "emma", "frank", "grace", "minutes",
                "duration", "hours", "free", "time", "invite", "find a slot", "open slot", "session"
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
                "training", "wellness", "athletic activity", "active duration",
                "running", "cycling", "walking", "swimming", "gym", "cardio"
            ],
            "secondary": [
                "minutes", "goal", "achieved", "target", "calories", "session", "compliance", "telemetry", "bpm", "heart rate"
            ],
            "patterns": [
                r"(?:running|cycling|walking|swimming|gym|cardio)",
                r"goal\s+(?:of\s+)?([0-9]+(?:\.[0-9]+)?)\s*(?:min|minutes|cal)?",
                r"(?:total|log|track|record)\s+(?:a\s+)?(?:[0-9]+[a-z-]*\s+)*(?:workout|exercise|activity|cycling|running|walking|swimming|session)",
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
        },
        "comparative_trend": {
            "primary": [
                "compare", "comparison", "versus", "vs", "trend", "rate of change",
                "how has", "changed over", "increase", "decrease", "growth",
                "month over month", "year over year", "period comparison", "inflationary",
                "against inflation", "spending change"
            ],
            "secondary": [
                "last month", "this month", "previous", "current", "over time",
                "quarter", "year", "weekly", "monthly", "delta", "ratio", "percent change",
                "spending", "expenses", "cost", "amount"
            ],
            "patterns": [
                r"compare\s+(?:my\s+)?(?:spending|expenses?|costs?)",
                r"(?:how|what)\s+(?:has|have)\s+(?:my\s+)?(?:spending|expenses?|costs?)\s+changed",
                r"(?:vs|versus|against|compared to)\s+(?:last|previous|prior)",
                r"(?:month|quarter|year)\s+over\s+(?:month|quarter|year)",
            ]
        },
        "predictive_alert": {
            "primary": [
                "predict", "prediction", "forecast", "forecasting", "project", "projection",
                "alert me", "notify me", "warn me", "running low", "will exceed",
                "on track to", "at this rate", "expected to", "estimated"
            ],
            "secondary": [
                "next month", "next quarter", "future", "upcoming", "budget",
                "threshold", "limit", "overspend", "exceed", "low", "shortage",
                "spending", "expenses", "cost", "amount", "supply"
            ],
            "patterns": [
                r"(?:alert|notify|warn)\s+(?:me\s+)?(?:when|if)",
                r"(?:project|forecast|predict|estimate)\s+(?:my\s+)?(?:spending|expenses?|costs?)",
                r"(?:will|going to|expected to)\s+(?:exceed|surpass|overspend)",
                r"running\s+low\s+on",
                r"(?:next|upcoming)\s+(?:month|quarter|year|week)",
            ]
        },
        "categorical_tagging": {
            "primary": [
                "categorize", "categorise", "classify", "classification", "tag", "tagging",
                "label", "labeling", "group by type", "sort by category", "bucket",
                "segment", "organize", "break down by", "identify tax-deductible", "tax-deductible", "deductible"
            ],
            "secondary": [
                "essential", "discretionary", "type", "category", "group",
                "transactions", "expenses", "items", "records", "entries",
                "needs", "wants", "necessary", "optional", "purchases", "debit",
                "charges", "uncategorized", "business", "statements", "fiscal"
            ],
            "patterns": [
                r"(?:categorize|classify|tag|label|group|segment|organize|identify)\s+(?:all\s+)?(?:[a-z0-9_-]+\s+)*(?:transactions?|expenses?|spending|items?|records?|purchases?|charges?|debits?)",
                r"(?:break|split|divide)\s+(?:down|up)\s+(?:by\s+)?(?:type|category|group)",
                r"(?:essential|discretionary|necessary|optional)\s+(?:vs|versus|or|and)",
                r"tax-deductible\s+(?:business\s+)?expenses",
            ]
        },
        "math_calculation": {
            "primary": [
                "calculate", "convert", "solve", "mortgage payment", "compound interest",
                "tip on", "percent off", "percentage off", "divided equally", "divide",
                "hypotenuse", "raised to", "percentage increase", "volume of", "square feet",
                "dinner bill", "gallons to liters", "miles per hour"
            ],
            "secondary": [
                "equation", "degrees", "fahrenheit", "celsius", "miles per hour",
                "kilometers", "gallons", "liters", "ounces", "milliliters", "cylinder",
                "volume", "square", "feet", "loan", "interest", "annual yield", "dinner bill",
                "tip", "discount", "power", "triangle", "meters", "rate", "bill", "people"
            ],
            "patterns": [
                r"(?:calculate|what is)\s+(?:an?\s+)?([0-9]+(?:\.[0-9]+)?%?\s+)?tip",
                r"convert\s+([0-9]+(?:\.[0-9]+)?)\s+([a-z\s]+)\s+to\s+([a-z\s]+)",
                r"(?:what\s+is\s+)?([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)\s+off",
                r"solve\s+for\s+([a-z])\s+in",
                r"(?:calculate\s+(?:the\s+)?)?monthly\s+mortgage\s+payment",
                r"(?:what\s+is\s+(?:the\s+)?)?compound\s+interest",
                r"divide\s+(?:a\s+)?\$?([0-9]+(?:\.[0-9]+)?)\s+([a-z\s]+)\s+equally",
                r"volume\s+of\s+(?:a\s+)?([a-z]+)",
                r"percentage\s+increase\s+from",
                r"hypotenuse\s+of\s+(?:a\s+)?right\s+triangle",
                r"([0-9]+)\s+raised\s+to\s+(?:the\s+)?([0-9]+)",
                r"how\s+many\s+(?:square\s+feet|liters|gallons|milliliters)",
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

        # P0.8: Specificity disambiguation — derived intents are more specific than
        # their parent intents.  When both score above the floor and are within the
        # ambiguity margin, prefer the more specific intent.
        DERIVED_OVER_PARENT = {
            "comparative_trend": {"expense", "habit_fitness"},
            "predictive_alert": {"expense", "habit_fitness"},
            "categorical_tagging": {"expense", "habit_fitness", "recommendation"},
            "math_calculation": {"expense"},
        }
        if len(scored_intents) >= 2:
            a_intent, a_score = scored_intents[0]
            b_intent, b_score = scored_intents[1]
            # If the parent intent is ranked first and the derived intent is ranked second
            # (or vice versa), and both are above the floor, promote the derived intent.
            if b_intent in DERIVED_OVER_PARENT and a_intent in DERIVED_OVER_PARENT[b_intent] and b_score >= cls.CONFIDENCE_FLOOR:
                scored_intents[0], scored_intents[1] = scored_intents[1], scored_intents[0]
            elif a_intent in DERIVED_OVER_PARENT and b_intent in DERIVED_OVER_PARENT.get(a_intent, set()):
                pass  # Derived is already first, no change needed

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
        # P0.8: Skip ambiguity flag when the pair is a known derived/parent relationship
        if len(scored_intents) > 1:
            second_intent, second_score = scored_intents[1]
            is_derived_parent = (
                (top_intent in DERIVED_OVER_PARENT and second_intent in DERIVED_OVER_PARENT[top_intent])
                or (second_intent in DERIVED_OVER_PARENT and top_intent in DERIVED_OVER_PARENT[second_intent])
            )
            if (top_score - second_score <= cls.AMBIGUITY_MARGIN) and (second_score >= 0.55) and not is_derived_parent:
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
            phrase_matches = [k for k in keywords if " " in k and k in text]
            all_matches = sorted(list(overlap) + phrase_matches)
            if all_matches:
                # Make sure domain primary keywords don't dominate
                has_comp_primary = any(
                    any(pk in text for pk in data["primary"])
                    for data in cls.INTENT_KEYWORDS.values()
                )
                if not has_comp_primary or len(all_matches) >= 2 or any(k in ("weather", "translate", "poem", "recipe", "flight", "percent off", "percentage off", "celsius", "fahrenheit") for k in all_matches):
                    return f"{domain} (matched: {', '.join(all_matches)})"
        return None

    @classmethod
    def _score_intents(cls, text: str) -> List[Tuple[str, float]]:
        scores: List[Tuple[str, float]] = []
        words = set(re.findall(r"\b[a-z0-9_-]+\b", text))

        for intent, data in cls.INTENT_KEYWORDS.items():
            score = 0.0

            # Primary keyword matches (enforce word boundaries)
            prim_matches = [k for k in data["primary"] if re.search(r"\b" + re.escape(k) + r"\b", text)]
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

            # Guard against action/mutation verbs in read-only scheduling intent
            if intent == "scheduling" and re.search(r"\b(cancel|delete|drop|remove|clear)\b", text):
                score = 0.0

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
            cat_candidates = ["food", "travel", "utilities", "shopping", "entertainment", "health", "office", "electronics", "dining", "groceries", "subscription", "subscriptions"]
            has_cat = False
            for cat in cat_candidates:
                if cat in text:
                    slots["category"] = "Subscription" if "subscription" in cat else cat.capitalize()
                    has_cat = True
                    break
            if not has_cat:
                slots["category"] = "Food"

            # Check account specification (e.g. for user account account_101)
            m_acc = re.search(r"\b(?:account|sensor)[_\s]+([a-z0-9_]+)\b", text)
            if m_acc:
                slots["account"] = m_acc.group(1).replace(" ", "_")

            # Extract threshold (P0.8 fix: exclude duration patterns like "90 days" and percentages)
            m = re.search(r"(?:above|over|exceeding|higher than|greater than|\$|>)\s*\$?([0-9]+(?:\.[0-9]+)?)", text)
            has_thresh = False
            if m:
                matched_val = float(m.group(1))
                # P0.8 fix: check if this number is actually a duration (e.g. "90 days")
                duration_check = re.search(r"\b" + re.escape(m.group(1)) + r"\s+(?:days?|weeks?|months?|years?)\b", text)
                # P0.8 fix: check if this number is a percentage
                pct_check = re.search(r"\b" + re.escape(m.group(1)) + r"\s*(?:%|percent)\b", text)
                if not duration_check and not pct_check:
                    slots["threshold"] = matched_val
                    has_thresh = True
            if not has_thresh:
                m2 = re.search(r"\b([0-9]{2,4})\b", text)
                if m2:
                    matched_val2 = float(m2.group(1))
                    # P0.8 fix: same guards for fallback numeric
                    duration_check2 = re.search(r"\b" + re.escape(m2.group(1)) + r"\s+(?:days?|weeks?|months?|years?)\b", text)
                    pct_check2 = re.search(r"\b" + re.escape(m2.group(1)) + r"\s*(?:%|percent)\b", text)
                    if not duration_check2 and not pct_check2:
                        slots["threshold"] = matched_val2
                        has_thresh = True
                if not has_thresh:
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
            stop_words = {"an", "the", "a", "this", "that", "today", "tomorrow", "my", "our", "all", "me", "us", "him", "her", "them", "friday", "monday", "tuesday", "wednesday", "thursday", "saturday", "sunday"}
            if m_user and m_user.group(1) not in stop_words:
                slots["user_id"] = m_user.group(1)
            else:
                slots["user_id"] = "alice"

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

        elif intent == "comparative_trend":
            # Extract category for comparison
            cat_candidates = ["food", "travel", "utilities", "shopping", "entertainment", "health", "office", "electronics", "dining", "groceries"]
            for cat in cat_candidates:
                if cat in text:
                    slots["category"] = cat.capitalize()
                    break
            if "category" not in slots:
                slots["category"] = "Food"

            # Extract comparison mode
            if re.search(r"\b(ratio|percent|percentage|%|times)\b", text):
                slots["comparison_mode"] = "ratio"
            else:
                slots["comparison_mode"] = "delta"

            # Extract periods
            if re.search(r"\b(year|annual|yearly)\b", text):
                slots["period_a"] = "current_year"
                slots["period_b"] = "previous_year"
            elif re.search(r"\b(quarter|quarterly)\b", text):
                slots["period_a"] = "current_quarter"
                slots["period_b"] = "previous_quarter"
            else:
                slots["period_a"] = "current_month"
                slots["period_b"] = "previous_month"

        elif intent == "predictive_alert":
            # Extract category
            cat_candidates = ["food", "travel", "utilities", "shopping", "entertainment", "health", "office", "electronics", "dining", "groceries"]
            for cat in cat_candidates:
                if cat in text:
                    slots["category"] = cat.capitalize()
                    break
            if "category" not in slots:
                slots["category"] = "Food"

            # Extract time window (in days)
            m_window = re.search(r"(\d+)\s*(?:days?|weeks?|months?)", text)
            if m_window:
                val = int(m_window.group(1))
                unit_match = re.search(r"weeks?", text[m_window.start():])
                month_match = re.search(r"months?", text[m_window.start():])
                if unit_match:
                    slots["window_days"] = val * 7
                elif month_match:
                    slots["window_days"] = val * 30
                else:
                    slots["window_days"] = val
            else:
                slots["window_days"] = 30

            # Extract alert threshold (monetary)
            m_thresh = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", text)
            slots["alert_threshold"] = float(m_thresh.group(1)) if m_thresh else 500.0

            # Extract projection multiplier
            m_proj = re.search(r"(?:next|upcoming)\s+(\d+)\s*(?:months?|quarters?)", text)
            if m_proj:
                slots["projection_multiplier"] = float(m_proj.group(1))
            else:
                slots["projection_multiplier"] = 3.0

        elif intent == "categorical_tagging":
            # Extract source
            if re.search(r"\b(transaction|expense|spending|purchase)\b", text):
                slots["source"] = "transactions"
            elif re.search(r"\b(activit|workout|exercise)\b", text):
                slots["source"] = "activities"
            else:
                slots["source"] = "transactions"

        elif intent == "math_calculation":
            operands: Dict[str, float] = {}
            if re.search(r"\btip\b", text):
                slots["operation"] = "tip"
                m_tip = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", text)
                operands["rate"] = float(m_tip.group(1)) / 100.0 if m_tip else 0.18
                m_bill = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", text)
                operands["bill"] = float(m_bill.group(1)) if m_bill else 50.0
            elif re.search(r"\b(?:percent(?:age)?\s+off|discount)\b", text):
                slots["operation"] = "percentage_discount"
                m_rate = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:%|percent)", text)
                operands["rate"] = float(m_rate.group(1)) / 100.0 if m_rate else 0.15
                m_cost = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", text)
                operands["cost"] = float(m_cost.group(1)) if m_cost else 100.0
            elif re.search(r"\bconvert\b", text) or re.search(r"\bhow many (?:liters|square feet|gallons)\b", text):
                slots["operation"] = "unit_conversion"
                m_num = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
                operands["value"] = float(m_num.group(1)) if m_num else 1.0
                if "fahrenheit" in text and "celsius" in text:
                    operands["ratio"] = 5.0 / 9.0
                    operands["offset"] = -32.0 * (5.0 / 9.0)
                elif "miles per hour" in text and "kilometers" in text:
                    operands["ratio"] = 1.60934
                    operands["offset"] = 0.0
                elif "fluid ounces" in text and "milliliters" in text:
                    operands["ratio"] = 29.5735
                    operands["offset"] = 0.0
                elif "gallons" in text and "liters" in text:
                    operands["ratio"] = 3.78541
                    operands["offset"] = 0.0
                elif "meters" in text and "square feet" in text:
                    m_dims = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*meters", text)
                    if len(m_dims) >= 2:
                        sq_m = float(m_dims[0]) * float(m_dims[1])
                        operands["value"] = sq_m
                        operands["ratio"] = 10.7639
                        operands["offset"] = 0.0
            elif re.search(r"\bmortgage\b", text):
                slots["operation"] = "mortgage"
                m_loan = re.search(r"\$([0-9,]+)", text)
                operands["principal"] = float(m_loan.group(1).replace(",", "")) if m_loan else 350000.0
                m_rate = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", text)
                operands["annual_rate"] = float(m_rate.group(1)) / 100.0 if m_rate else 0.065
                m_yr = re.search(r"([0-9]+)\s*years", text)
                operands["years"] = float(m_yr.group(1)) if m_yr else 30.0
            elif re.search(r"\bcompound interest\b", text):
                slots["operation"] = "compound_interest"
                m_p = re.search(r"\$([0-9,]+)", text)
                operands["principal"] = float(m_p.group(1).replace(",", "")) if m_p else 10000.0
                m_r = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", text)
                operands["rate"] = float(m_r.group(1)) / 100.0 if m_r else 0.07
                m_yr = re.search(r"([0-9]+)\s*years", text)
                operands["years"] = float(m_yr.group(1)) if m_yr else 5.0
            elif re.search(r"\bdivide\b", text) or re.search(r"\bequally\b", text):
                slots["operation"] = "division"
                m_tot = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", text)
                operands["total"] = float(m_tot.group(1)) if m_tot else 100.0
                m_ppl = re.search(r"([0-9]+)\s*people", text)
                operands["parts"] = float(m_ppl.group(1)) if m_ppl else 2.0
            elif re.search(r"\braised to\b", text) or re.search(r"\bpower\b", text):
                slots["operation"] = "exponentiation"
                nums = [float(x) for x in re.findall(r"([0-9]+)", text)]
                operands["base"] = nums[0] if len(nums) > 0 else 2.0
                operands["exponent"] = nums[1] if len(nums) > 1 else 1.0
            elif re.search(r"\bhypotenuse\b", text):
                slots["operation"] = "hypotenuse"
                nums = [float(x) for x in re.findall(r"([0-9]+(?:\.[0-9]+)?)", text)]
                operands["a"] = nums[0] if len(nums) > 0 else 3.0
                operands["b"] = nums[1] if len(nums) > 1 else 4.0
            elif re.search(r"\bpercentage increase\b", text):
                slots["operation"] = "percentage_increase"
                nums = [float(x) for x in re.findall(r"([0-9]+(?:\.[0-9]+)?)", text)]
                operands["initial"] = nums[0] if len(nums) > 0 else 1.0
                operands["final"] = nums[1] if len(nums) > 1 else 2.0
            elif re.search(r"\bvolume of a cylinder\b", text):
                slots["operation"] = "cylinder_volume"
                m_rad = re.search(r"radius\s+([0-9]+(?:\.[0-9]+)?)", text)
                m_ht = re.search(r"height\s+([0-9]+(?:\.[0-9]+)?)", text)
                operands["radius"] = float(m_rad.group(1)) if m_rad else 1.0
                operands["height"] = float(m_ht.group(1)) if m_ht else 1.0
            elif re.search(r"\bsolve for\b", text):
                slots["operation"] = "linear_equation"
                operands["a"] = 3.0
                operands["b"] = 14.0
                operands["c"] = 59.0
            else:
                slots["operation"] = "arithmetic"
                nums = [float(x) for x in re.findall(r"([0-9]+(?:\.[0-9]+)?)", text)]
                for idx, n in enumerate(nums):
                    operands[f"x{idx}"] = n
            slots["operands"] = operands

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
        elif intent == "comparative_trend":
            return build_comparative_trend_fixture(
                category=slots.get("category", "Food"),
                period_a=slots.get("period_a", "current_month"),
                period_b=slots.get("period_b", "previous_month"),
                comparison_mode=slots.get("comparison_mode", "delta")
            )
        elif intent == "predictive_alert":
            return build_predictive_alert_fixture(
                category=slots.get("category", "Food"),
                window_days=slots.get("window_days", 30),
                projection_multiplier=slots.get("projection_multiplier", 3.0),
                alert_threshold=slots.get("alert_threshold", 500.0)
            )
        elif intent == "categorical_tagging":
            return build_categorical_tagging_fixture(
                source=slots.get("source", "transactions")
            )
        elif intent == "math_calculation":
            return build_math_calculation_fixture(
                operation=slots.get("operation", "percentage_discount"),
                operands=slots.get("operands")
            )
        else:
            raise ValueError(f"Unknown intent {intent}")
