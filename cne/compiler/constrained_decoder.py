"""
CNE Grammar-Constrained Autoregressive Decoder & Production Controller.
Implements Layer 2 (L2) controller generation using token-level grammar-constrained decoding.

Uses local instruction model with JSON Schema grammar masking to guarantee
100% syntactically valid Semantic IR outputs conforming to the 11 frozen primitives.

Production upgrade (P1 Steps 2-4):
- LearnedSemanticController: Protocol-conformant controller with dynamic few-shot selection,
  confidence calibration, retry logic, and batch decoding support.
- ConstrainedDecoder: Original spike decoder preserved for backward compatibility.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import openai

from cne.compiler.few_shot_pool import FewShotPool
from cne.compiler.grammar_schema import (
    CNE_SEMANTIC_IR_SCHEMA,
    payload_to_semantic_ir,
    validate_raw_graph,
)
from cne.contracts.outcome_contract import OutcomeContract
from cne.semantic_ir.nodes import SemanticIRGraph
from cne.signature.canonicalization import Canonicalizer
from cne.signature.shape_key import SemanticShapeKey


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# System Prompt (Production Version)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the CNE Semantic IR Compiler.
Your task is to translate natural language user queries into a type-safe Semantic IR Directed Acyclic Graph (DAG) and typed slots.

CANONICAL TOPOLOGIES:
When outcome is "COMPILED", "intent" MUST be exactly one of these canonical topologies:
- "expense": tracking or aggregating spending, expenses, purchases, budgets, account transactions with filters
- "troubleshooting": diagnosing system errors, crash logs, CPU/memory/network performance, hardware faults
- "scheduling": calendar events, meetings, appointments, shift planning, reminders
- "habit_fitness": tracking physical activity, steps, workouts, sleep, hydration, calorie burning
- "factual_decision": evaluating multi-criteria policies, rule checks, credit/loan/release decisions
- "recommendation": scoring, ranking, or recommending venues, books, products, movies based on user criteria
- "cross_source_join_aggregate": joining two distinct sources (e.g. orders & inventory, bank & card) and computing aggregates
- "math_calculation": deterministic arithmetic, tips, percentages, geometric or unit calculations

OUTCOME DECISION RULES:
1. "COMPILED": The query clearly maps to one of the 8 canonical topologies above.
2. "UNSUPPORTED_INTENT": The query is out of scope. Out of scope includes: stock trading/purchases, live web search, smart home IoT/lights, system OS settings, music/media playback, creative writing, or general knowledge chat. For unsupported requests, set outcome to "UNSUPPORTED_INTENT", intent to null, nodes to [], and root_id to "".
3. "LOW_CONFIDENCE_MAPPING": The query is vague, incomplete, or contains uncertainty hedges (e.g., "perhaps", "maybe", "ref_"), making exact intent uncertain.
4. "AMBIGUOUS_INTENT": The query conflates two conflicting intents with equal plausibility.

INVARIANTS:
1. You may ONLY use the 11 frozen OpKind primitives: Observe, Filter, Map, Reduce, Join, Branch, Iterate, Choose, Update, Call, Emit (+ Literal).
2. Every compiled graph must end in exactly ONE root node with op "Emit", referenced by "root_id".
3. The "inputs" list in each node must refer to valid predecessor node IDs in topological order (no cycles).
4. Extract typed slots where numeric values (threshold, quantity, amount) are numbers (not strings), and aggregations are lowercase strings ("sum", "avg", "count", "min", "max").

OUTPUT FORMAT: A single JSON object conforming to the CNE Semantic IR schema."""


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatible spike types (preserved)
# ─────────────────────────────────────────────────────────────────────────────

# Legacy few-shot demonstrations (kept for spike backward compatibility)
FEW_SHOT_DEMONSTRATIONS = [
    {
        "role": "user",
        "content": "Calculate total spending on Groceries over 50 dollars"
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "outcome": "COMPILED",
            "intent": "expense",
            "reason": None,
            "contract": {
                "contract_type": "EXACT",
                "decision_boundary": None
            },
            "slots": {
                "category": "Groceries",
                "threshold": 50.0,
                "aggregation": "sum"
            },
            "nodes": [
                {"id": "obs_tx", "op": "Observe", "inputs": [], "attributes": {"source": "transactions"}, "output_type": "collection"},
                {"id": "filt_cat", "op": "Filter", "inputs": ["obs_tx"], "attributes": {"category": "Groceries"}, "output_type": "collection"},
                {"id": "filt_amt", "op": "Filter", "inputs": ["filt_cat"], "attributes": {"threshold": 50.0}, "output_type": "collection"},
                {"id": "map_amt", "op": "Map", "inputs": ["filt_amt"], "attributes": {"field": "amount"}, "output_type": "collection"},
                {"id": "red_sum", "op": "Reduce", "inputs": ["map_amt"], "attributes": {"reducer": "sum"}, "output_type": "scalar"},
                {"id": "emit_out", "op": "Emit", "inputs": ["red_sum"], "attributes": {"label": "total_expense"}, "output_type": "scalar"}
            ],
            "root_id": "emit_out"
        })
    },
    {
        "role": "user",
        "content": "What is 15 percent tip on 85 dollars?"
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "outcome": "COMPILED",
            "intent": "math_calculation",
            "reason": None,
            "contract": {
                "contract_type": "EXACT",
                "decision_boundary": None
            },
            "slots": {
                "percentage": 15.0,
                "base_amount": 85.0
            },
            "nodes": [
                {"id": "lit_val", "op": "Literal", "inputs": [], "attributes": {"value": 85.0}, "output_type": "scalar"},
                {"id": "map_tip", "op": "Map", "inputs": ["lit_val"], "attributes": {"eval": "value * 0.15"}, "output_type": "scalar"},
                {"id": "emit_tip", "op": "Emit", "inputs": ["map_tip"], "attributes": {"label": "tip_amount"}, "output_type": "scalar"}
            ],
            "root_id": "emit_tip"
        })
    },
    {
        "role": "user",
        "content": "Turn on the living room lights"
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "outcome": "UNSUPPORTED_INTENT",
            "intent": None,
            "reason": "Hardware device actuation is out of scope for CNE data computation.",
            "contract": {
                "contract_type": "NO_SOLUTION",
                "decision_boundary": None
            },
            "slots": {},
            "nodes": [],
            "root_id": ""
        })
    }
]


@dataclass
class DecoderResult:
    """Result from the spike ConstrainedDecoder (backward compatible)."""
    query_text: str
    outcome: str
    intent: Optional[str]
    is_valid_schema: bool
    is_valid_dag: bool
    validation_error: Optional[str]
    graph: Optional[SemanticIRGraph]
    contract: Optional[OutcomeContract]
    slots: Dict[str, Any]
    shape_key: Optional[str]
    raw_payload: Dict[str, Any]
    latency_ms: float


class ConstrainedDecoder:
    """
    Grammar-constrained autoregressive controller using local instruction model.
    (Original spike implementation — preserved for backward compatibility)
    """

    def __init__(
        self,
        model_name: str = "qwen2.5-coder:1.5b",
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama"
    ):
        self.model_name = model_name
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)

    def decode(self, query_text: str) -> DecoderResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        messages.extend(FEW_SHOT_DEMONSTRATIONS)
        messages.append({"role": "user", "content": query_text})

        t0 = time.perf_counter_ns()
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "cne_semantic_ir",
                        "strict": True,
                        "schema": CNE_SEMANTIC_IR_SCHEMA
                    }
                },
                temperature=0.0,
                max_tokens=600
            )
            raw_text = resp.choices[0].message.content or "{}"
            payload = json.loads(raw_text)
        except Exception as e:
            latency_ms = (time.perf_counter_ns() - t0) / 1e6
            return DecoderResult(
                query_text=query_text,
                outcome="DECODER_ERROR",
                intent=None,
                is_valid_schema=False,
                is_valid_dag=False,
                validation_error=str(e),
                graph=None,
                contract=None,
                slots={},
                shape_key=None,
                raw_payload={},
                latency_ms=round(latency_ms, 2)
            )

        latency_ms = (time.perf_counter_ns() - t0) / 1e6
        is_valid, reason = validate_raw_graph(payload)

        graph = None
        contract = None
        slots = payload.get("slots", {})
        shape_key = None

        if is_valid and payload.get("outcome") == "COMPILED":
            try:
                graph, contract, slots = payload_to_semantic_ir(payload)
                if graph:
                    shape_key = SemanticShapeKey.from_graph(graph).key_hash
            except Exception as e:
                is_valid = False
                reason = f"Deserialization error: {e}"

        return DecoderResult(
            query_text=query_text,
            outcome=payload.get("outcome", "UNKNOWN"),
            intent=payload.get("intent"),
            is_valid_schema=is_valid,
            is_valid_dag=is_valid if payload.get("outcome") == "COMPILED" else True,
            validation_error=None if is_valid else reason,
            graph=graph,
            contract=contract,
            slots=slots,
            shape_key=shape_key,
            raw_payload=payload,
            latency_ms=round(latency_ms, 2)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Production Controller (P1 Steps 2-4)
# ─────────────────────────────────────────────────────────────────────────────

class ControllerOutcome(Enum):
    """4-way classification outcomes for the learned controller."""
    COMPILED = "COMPILED"
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"
    LOW_CONFIDENCE_MAPPING = "LOW_CONFIDENCE_MAPPING"


@dataclass(frozen=True)
class ControllerOutput:
    """
    Authoritative output of the L2 Learned Semantic Controller.
    Conforms to the protocol defined in P1_CONTROLLER_ARCHITECTURE.md Section 4.
    """
    outcome: ControllerOutcome
    graph: Optional[SemanticIRGraph] = None
    contract: Optional[OutcomeContract] = None
    slots: Optional[Dict[str, Any]] = None
    confidence_score: float = 0.0
    decline_reason: Optional[str] = None
    shape_key: Optional[str] = None
    raw_ast: Optional[Dict[str, Any]] = None
    latency_ms: float = 0.0


# Retry temperatures for progressive decoding attempts
_RETRY_TEMPERATURES = [0.0, 0.3, 0.7]


class LearnedSemanticController:
    """
    Production Layer 2 Controller conforming to the P1 protocol.
    
    Upgrades from the spike ConstrainedDecoder:
    1. Protocol Conformance: Returns ControllerOutput (not DecoderResult)
    2. Dynamic Few-Shot Selection: Uses FewShotPool for topology-diverse demonstrations
    3. Confidence Calibration: Heuristic confidence based on validation signals
    4. Retry Logic: Up to 3 attempts with increasing temperature
    5. Batch Support: predict_batch() for efficient corpus evaluation
    """

    def __init__(
        self,
        model_name: str = "qwen2.5-coder:1.5b",
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        few_shot_pool: Optional[FewShotPool] = None,
        num_demos: int = 3,
        max_retries: int = 3,
        max_tokens: int = 800
    ):
        self.model_name = model_name
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.few_shot_pool = few_shot_pool or FewShotPool()
        self.num_demos = num_demos
        self.max_retries = min(max_retries, len(_RETRY_TEMPERATURES))
        self.max_tokens = max_tokens

    def predict(
        self,
        query_text: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ControllerOutput:
        """
        Authoritative Layer 2 Controller prediction.
        Maps a natural language query to a validated Semantic IR DAG.
        """
        # 1. Select topology-diverse few-shot demonstrations
        demos = self.few_shot_pool.select(query_text, k=self.num_demos)

        # 2. Build messages
        messages = self._build_messages(query_text, demos)

        # 3. Decode with retry
        result = self._decode_with_retry(query_text, messages)

        return result

    def predict_batch(
        self,
        queries: List[str],
        progress_callback: Optional[Any] = None
    ) -> List[ControllerOutput]:
        """
        Batch prediction for corpus evaluation.
        Processes queries sequentially (Ollama is single-threaded).
        """
        results = []
        for i, query in enumerate(queries):
            result = self.predict(query)
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, len(queries), result)
        return results

    def _build_messages(
        self,
        query_text: str,
        demos: List[Any]
    ) -> List[Dict[str, str]]:
        """Construct the full chat message sequence."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add few-shot demonstrations
        for demo in demos:
            messages.extend(demo.to_messages())

        # Add the target query
        messages.append({"role": "user", "content": query_text})

        return messages

    def _decode_with_retry(
        self,
        query_text: str,
        messages: List[Dict[str, str]]
    ) -> ControllerOutput:
        """
        Attempt decoding with progressive temperature increases.
        Returns the first valid result or the last attempt's result.
        """
        last_error = None
        last_payload = {}

        for attempt_idx in range(self.max_retries):
            temp = _RETRY_TEMPERATURES[attempt_idx]

            t0 = time.perf_counter_ns()
            try:
                resp = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "cne_semantic_ir",
                            "strict": True,
                            "schema": CNE_SEMANTIC_IR_SCHEMA
                        }
                    },
                    temperature=temp,
                    max_tokens=self.max_tokens
                )
                raw_text = resp.choices[0].message.content or "{}"
                payload = json.loads(raw_text)
            except Exception as e:
                latency_ms = (time.perf_counter_ns() - t0) / 1e6
                last_error = str(e)
                logger.warning(
                    f"Decode attempt {attempt_idx+1}/{self.max_retries} failed "
                    f"for query '{query_text[:50]}...': {e}"
                )
                continue

            latency_ms = (time.perf_counter_ns() - t0) / 1e6
            last_payload = payload

            # Validate
            is_valid, reason = validate_raw_graph(payload)

            if is_valid:
                # Success — build ControllerOutput
                return self._build_output(
                    query_text, payload, latency_ms
                )
            else:
                last_error = reason
                logger.warning(
                    f"Decode attempt {attempt_idx+1}/{self.max_retries} schema "
                    f"invalid for query '{query_text[:50]}...': {reason}"
                )

        # All retries exhausted — return error/fallback
        return ControllerOutput(
            outcome=ControllerOutcome.LOW_CONFIDENCE_MAPPING,
            confidence_score=0.0,
            decline_reason=f"All {self.max_retries} decode attempts failed: {last_error}",
            raw_ast=last_payload,
            latency_ms=latency_ms if 'latency_ms' in dir() else 0.0
        )

    def _build_output(
        self,
        query_text: str,
        payload: Dict[str, Any],
        latency_ms: float
    ) -> ControllerOutput:
        """Convert a validated payload into a ControllerOutput."""
        outcome_str = payload.get("outcome", "COMPILED")

        try:
            outcome = ControllerOutcome(outcome_str)
        except ValueError:
            outcome = ControllerOutcome.LOW_CONFIDENCE_MAPPING

        graph = None
        contract = None
        slots = payload.get("slots", {})
        shape_key = None

        if outcome == ControllerOutcome.COMPILED:
            try:
                graph, contract, slots = payload_to_semantic_ir(payload)
                if graph:
                    shape_key = SemanticShapeKey.from_graph(graph).key_hash
            except Exception as e:
                logger.warning(f"Deserialization failed: {e}")
                return ControllerOutput(
                    outcome=ControllerOutcome.LOW_CONFIDENCE_MAPPING,
                    confidence_score=0.1,
                    decline_reason=f"Deserialization error: {e}",
                    raw_ast=payload,
                    latency_ms=latency_ms
                )

        # Compute calibrated confidence
        confidence = self._calibrate_confidence(payload, graph, outcome)

        return ControllerOutput(
            outcome=outcome,
            graph=graph,
            contract=contract,
            slots=slots,
            confidence_score=confidence,
            decline_reason=payload.get("reason"),
            shape_key=shape_key,
            raw_ast=payload,
            latency_ms=latency_ms
        )

    def _calibrate_confidence(
        self,
        payload: Dict[str, Any],
        graph: Optional[SemanticIRGraph],
        outcome: ControllerOutcome
    ) -> float:
        """
        Heuristic confidence calibration based on structural validation signals.
        
        Signals:
        - Schema validation passed: +0.30
        - DAG acyclicity (topo sort succeeded): +0.20
        - All inputs resolved: +0.20
        - Emit node present as root: +0.15
        - Non-empty slots for COMPILED: +0.15
        
        For non-COMPILED outcomes, confidence is based on reason presence.
        """
        if outcome != ControllerOutcome.COMPILED:
            # Non-compiled confidence: high if reason is present
            has_reason = bool(payload.get("reason"))
            return 0.85 if has_reason else 0.60

        score = 0.0

        # Schema validation already passed (we only call this on valid payloads)
        score += 0.30

        # DAG acyclicity
        if graph is not None:
            try:
                topo = graph.topological_order()
                if len(topo) == len(graph.nodes):
                    score += 0.20
            except Exception:
                pass

            # All inputs resolved
            node_ids = set(graph.nodes.keys())
            all_resolved = True
            for nid, node in graph.nodes.items():
                for inp in node.inputs:
                    if inp not in node_ids:
                        all_resolved = False
                        break
            if all_resolved:
                score += 0.20

            # Emit as root
            root_id = payload.get("root_id", "")
            if root_id in graph.nodes and graph.nodes[root_id].op.value == "Emit":
                score += 0.15

        # Non-empty slots
        slots = payload.get("slots", {})
        if slots and any(v is not None for v in slots.values()):
            score += 0.15

        return min(score, 1.0)
