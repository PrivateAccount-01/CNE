"""
CNE Blind Semantic Validator (Phase P0.7 Open Issues Resolution).
Performs independent semantic validation of topology-blind compiled queries,
specifically auditing queries that map into novel computational shapes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from cne.compiler.nl_compiler import NLCompiler, CompilationResult, ClassificationOutcome


@dataclass
class NovelShapeAudit:
    shape_hash: str
    query_count: int
    sample_queries: List[str]
    graph_ops: List[str]
    valid_count: int
    misinterpreted_count: int
    valid_reasons: List[str]
    misinterpretation_reasons: List[str]


@dataclass
class BlindValidationSummary:
    total_blind_queries: int
    compiled_count: int
    rejection_count: int
    rejection_rate: float
    unsupported_count: int
    ambiguous_count: int
    low_confidence_count: int
    distinct_blind_shapes: int
    novel_shapes_count: int
    novel_shape_rate: float
    total_novel_query_mass: int
    novel_query_mass_rate: float
    semantically_valid_novel_queries: int
    semantically_valid_novel_mass_rate: float
    misinterpreted_novel_queries: int
    misinterpreted_novel_mass_rate: float
    domain_breakdown: Dict[str, Dict[str, Any]]
    shape_audits: List[NovelShapeAudit]


class BlindSemanticValidator:
    """
    Audits the semantic validity of compiled blind queries.
    Distinguishes genuine compositional variations from compiler misinterpretations.
    """

    @classmethod
    def validate(cls, query_text: str, graph: Any = None, shape_hash: str = "") -> Tuple[bool, str]:
        """
        Validates a query against the compiled graph. Returns (is_valid, reason).
        """
        res = NLCompiler.compile(query_text)
        return cls.audit_query(query_text, res)

    @classmethod
    def audit_query(cls, query_text: str, result: CompilationResult) -> Tuple[bool, str]:
        """
        Determines whether the compiled graph faithfully represents the query's semantics.
        Returns (is_valid, rationale).
        """
        text = query_text.lower()
        slots = result.extracted_slots
        intent = result.intent

        # 1. Comparative / Trend / Inflation queries
        if re.search(r"\b(compare|versus|vs|increase|inflationary|trend|rate of change)\b", text):
            if result.graph and "Branch" not in [n.op.value for n in result.graph.nodes.values()] and "Join" not in [n.op.value for n in result.graph.nodes.values()]:
                return False, "Query requested comparative/trend analysis, but compiler produced a non-comparative scalar reduction"

        # 2. Categorization / Tagging queries
        if re.search(r"\b(categorize|tag|classify|label)\b", text):
            return False, "Query requested categorical classification/tagging, but compiler produced an aggregation sum"

        # 3. Predictive / Notification / Alert queries with rate or percentage
        if re.search(r"\b(alert|notify|when i am|running low)\b", text) and ("%" in text or "percent" in text or "running low" in text):
            if slots.get("threshold") in (15.0, 20.0):
                return False, "Query specified a percentage threshold (e.g. 15% or 20%), which was misinterpreted as a dollar amount threshold"
            return False, "Query requested predictive notification, but compiler generated a static reduction"

        # 4. Projections / Forecasting
        if re.search(r"\b(project|forecast|future|next quarter)\b", text):
            return False, "Query requested financial forecasting/projection, but compiler produced an historical aggregation"

        # 5. Day extraction misinterpretation (e.g. '90 days' -> threshold $90)
        if re.search(r"\b([0-9]+)\s+days\b", text):
            day_match = re.search(r"\b([0-9]+)\s+days\b", text)
            if day_match and float(day_match.group(1)) == slots.get("threshold"):
                return False, f"Time duration '{day_match.group(0)}' was erroneously extracted as a monetary amount threshold"

        # 6. Check for genuine single-filter category sums
        if intent == "expense" and slots.get("include_category_filter") and not slots.get("include_threshold_filter"):
            if re.search(r"\b(spend|spent|spending|cost|total amount|expenses)\b", text):
                return True, "Valid compositional single-filter category aggregation (filtered by category without arbitrary threshold)"

        # 7. Check for scheduling requests
        if intent == "scheduling" and re.search(r"\b(schedule|meeting|slot|appointment|call)\b", text):
            return True, "Valid calendar scheduling query with matching duration slot"

        # 8. Check for habit/fitness requests
        if intent == "habit_fitness" and re.search(r"\b(run|running|cycling|workout|steps|sleep|gym|swimming)\b", text):
            return True, "Valid activity logging query with activity matching"

        # 9. Check for recommendation requests
        if intent == "recommendation" and re.search(r"\b(recommend|suggest|top|catalog)\b", text):
            return True, "Valid item recommendation query"

        # Fallback for unexplained cases
        return False, "Query semantics do not match the instantiated fixture topology"

    @classmethod
    def evaluate_blind_corpus(
        cls,
        blind_data: Dict[str, Any],
        anchored_shape_keys: set[str]
    ) -> BlindValidationSummary:
        queries = blind_data["queries"]
        total = len(queries)

        blind_results: List[Tuple[Dict[str, Any], CompilationResult]] = []
        domain_breakdown: Dict[str, Dict[str, Any]] = {}

        for q in queries:
            res = NLCompiler.compile(q["query_text"])
            blind_results.append((q, res))
            d = q.get("domain", "unknown")
            if d not in domain_breakdown:
                domain_breakdown[d] = {
                    "total": 0, "compiled": 0, "unsupported": 0, "ambiguous": 0, "low_confidence": 0
                }
            domain_breakdown[d]["total"] += 1
            if res.outcome == ClassificationOutcome.COMPILED:
                domain_breakdown[d]["compiled"] += 1
            elif res.outcome == ClassificationOutcome.UNSUPPORTED_INTENT:
                domain_breakdown[d]["unsupported"] += 1
            elif res.outcome == ClassificationOutcome.AMBIGUOUS_INTENT:
                domain_breakdown[d]["ambiguous"] += 1
            elif res.outcome == ClassificationOutcome.LOW_CONFIDENCE_MAPPING:
                domain_breakdown[d]["low_confidence"] += 1

        compiled_queries = [r for _, r in blind_results if r.outcome == ClassificationOutcome.COMPILED]
        compiled_count = len(compiled_queries)
        rejection_count = total - compiled_count
        rejection_rate = rejection_count / total if total > 0 else 0.0

        unsupported_count = sum(1 for _, r in blind_results if r.outcome == ClassificationOutcome.UNSUPPORTED_INTENT)
        ambiguous_count = sum(1 for _, r in blind_results if r.outcome == ClassificationOutcome.AMBIGUOUS_INTENT)
        low_confidence_count = sum(1 for _, r in blind_results if r.outcome == ClassificationOutcome.LOW_CONFIDENCE_MAPPING)

        # Shapes
        shapes_map: Dict[str, List[Tuple[Dict[str, Any], CompilationResult]]] = {}
        for q, res in blind_results:
            if res.outcome == ClassificationOutcome.COMPILED and res.graph is not None:
                sh = res.graph._cached_shape_key.key_hash
                shapes_map.setdefault(sh, []).append((q, res))

        distinct_shapes_count = len(shapes_map)
        novel_shapes_set = set(shapes_map.keys()) - anchored_shape_keys
        novel_shapes_count = len(novel_shapes_set)
        novel_shape_rate = novel_shapes_count / distinct_shapes_count if distinct_shapes_count > 0 else 0.0

        total_novel_query_mass = sum(len(shapes_map[ns]) for ns in novel_shapes_set)
        novel_query_mass_rate = total_novel_query_mass / compiled_count if compiled_count > 0 else 0.0

        # Audits
        shape_audits: List[NovelShapeAudit] = []
        total_valid_novel = 0
        total_misinterpreted_novel = 0

        for ns in sorted(novel_shapes_set):
            q_items = shapes_map[ns]
            first_res = q_items[0][1]
            ops = [n.op.value for n in first_res.graph.nodes.values()]
            sample_texts = [qi[0]["query_text"] for qi in q_items[:3]]

            valid_count = 0
            misinterpreted_count = 0
            valid_reasons = []
            mis_reasons = []

            for q_meta, res in q_items:
                is_valid, rationale = cls.audit_query(q_meta["query_text"], res)
                if is_valid:
                    valid_count += 1
                    if rationale not in valid_reasons:
                        valid_reasons.append(rationale)
                else:
                    misinterpreted_count += 1
                    if rationale not in mis_reasons:
                        mis_reasons.append(rationale)

            total_valid_novel += valid_count
            total_misinterpreted_novel += misinterpreted_count

            shape_audits.append(NovelShapeAudit(
                shape_hash=ns,
                query_count=len(q_items),
                sample_queries=sample_texts,
                graph_ops=ops,
                valid_count=valid_count,
                misinterpreted_count=misinterpreted_count,
                valid_reasons=valid_reasons,
                misinterpretation_reasons=mis_reasons
            ))

        valid_mass_rate = total_valid_novel / compiled_count if compiled_count > 0 else 0.0
        misinterpreted_mass_rate = total_misinterpreted_novel / compiled_count if compiled_count > 0 else 0.0

        return BlindValidationSummary(
            total_blind_queries=total,
            compiled_count=compiled_count,
            rejection_count=rejection_count,
            rejection_rate=round(rejection_rate, 4),
            unsupported_count=unsupported_count,
            ambiguous_count=ambiguous_count,
            low_confidence_count=low_confidence_count,
            distinct_blind_shapes=distinct_shapes_count,
            novel_shapes_count=novel_shapes_count,
            novel_shape_rate=round(novel_shape_rate, 4),
            total_novel_query_mass=total_novel_query_mass,
            novel_query_mass_rate=round(novel_query_mass_rate, 4),
            semantically_valid_novel_queries=total_valid_novel,
            semantically_valid_novel_mass_rate=round(valid_mass_rate, 4),
            misinterpreted_novel_queries=total_misinterpreted_novel,
            misinterpreted_novel_mass_rate=round(misinterpreted_mass_rate, 4),
            domain_breakdown=domain_breakdown,
            shape_audits=shape_audits
        )
