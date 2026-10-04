"""
Unit tests for Phase P1 Controller components.
Tests:
1. FewShotPool selection and topology diversity
2. ControllerBridge output conversion
3. Confidence calibration
4. Chat dataset builder schema conformity
"""
from __future__ import annotations

import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cne.compiler.few_shot_pool import FewShotPool, FewShotDemo, _CANONICAL_DEMOS
from cne.compiler.constrained_decoder import (
    ControllerOutcome,
    ControllerOutput,
    LearnedSemanticController,
)
from cne.compiler.controller_bridge import ControllerBridge
from cne.compiler.grammar_schema import validate_raw_graph, CNE_SEMANTIC_IR_SCHEMA
from cne.compiler.nl_compiler import ClassificationOutcome
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.semantic_ir.types import SemanticType


# ─────────────────────────────────────────────────────────────────────────────
# FewShotPool Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFewShotPool:
    """Tests for the few-shot demonstration pool."""

    def test_pool_has_11_demos(self):
        """Pool must contain 11 canonical demonstrations (10 topologies + rejection)."""
        pool = FewShotPool()
        assert len(pool.demos) == 11

    def test_pool_covers_all_topologies(self):
        """Pool must cover all 10 topologies + UNSUPPORTED."""
        pool = FewShotPool()
        expected_topos = {
            "expense", "troubleshooting", "scheduling", "habit_fitness",
            "factual_decision", "recommendation", "cross_source_join_aggregate",
            "comparative_trend", "predictive_alert", "math_calculation",
            "UNSUPPORTED"
        }
        actual_topos = set(pool.topologies)
        assert actual_topos == expected_topos, f"Missing: {expected_topos - actual_topos}"

    def test_select_returns_k_demos(self):
        """Selection returns exactly k demonstrations."""
        pool = FewShotPool()
        demos = pool.select("test query", k=3)
        assert len(demos) == 3

    def test_select_includes_rejection(self):
        """Selection always includes at least one rejection example."""
        pool = FewShotPool()
        demos = pool.select("test query", k=3, seed=42)
        has_rejection = any(d.outcome == "UNSUPPORTED_INTENT" for d in demos)
        assert has_rejection, "Selection must always include a rejection example"

    def test_select_excludes_topology(self):
        """Selection excludes the specified topology when possible."""
        pool = FewShotPool()
        demos = pool.select("test query", k=3, exclude_topology="expense", seed=42)
        for d in demos:
            if d.topology != "UNSUPPORTED":
                assert d.topology != "expense" or len(pool.topologies) <= 3

    def test_select_topology_diversity(self):
        """Selected demos should come from different topologies."""
        pool = FewShotPool()
        demos = pool.select("test query", k=4, seed=42)
        topologies = [d.topology for d in demos]
        # Should have at least 3 unique topologies in 4 demos
        assert len(set(topologies)) >= 3

    def test_all_demos_have_valid_schema(self):
        """All canonical demonstrations must pass schema validation."""
        pool = FewShotPool()
        for demo in pool.demos:
            if demo.outcome == "COMPILED":
                is_valid, reason = validate_raw_graph(demo.gold_ast)
                assert is_valid, f"Demo '{demo.topology}' failed validation: {reason}"

    def test_demo_to_messages(self):
        """Demo converts to correct message format."""
        pool = FewShotPool()
        demo = pool.demos[0]  # expense
        messages = demo.to_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        # Assistant message should be valid JSON
        parsed = json.loads(messages[1]["content"])
        assert parsed["outcome"] == "COMPILED"


# ─────────────────────────────────────────────────────────────────────────────
# ControllerBridge Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestControllerBridge:
    """Tests for the Controller-Compiler bridge."""

    def _make_compiled_output(self) -> ControllerOutput:
        """Create a minimal compiled ControllerOutput for testing."""
        graph = SemanticIRGraph()
        obs = IRNode(id="obs", op=OpKind.OBSERVE, inputs=[], attributes={"source": "test"}, output_type=SemanticType.any())
        emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs"], attributes={}, output_type=SemanticType.any())
        graph.add_node(obs)
        graph.add_node(emit)
        graph.root_id = "emit"

        contract = OutcomeContract(contract_type=ContractType.EXACT)

        return ControllerOutput(
            outcome=ControllerOutcome.COMPILED,
            graph=graph,
            contract=contract,
            slots={"category": "test", "threshold": 100.0},
            confidence_score=0.85,
            shape_key="abc123",
            raw_ast={"outcome": "COMPILED", "intent": "expense", "nodes": [], "root_id": "emit"},
        )

    def _make_rejected_output(self) -> ControllerOutput:
        """Create a rejected ControllerOutput for testing."""
        return ControllerOutput(
            outcome=ControllerOutcome.UNSUPPORTED_INTENT,
            confidence_score=0.90,
            decline_reason="Hardware actuation out of scope",
            raw_ast={"outcome": "UNSUPPORTED_INTENT", "intent": None},
        )

    def test_compiled_conversion(self):
        """Compiled ControllerOutput maps to COMPILED CompilationResult."""
        output = self._make_compiled_output()
        result = ControllerBridge.output_to_result("test query", output)

        assert result.outcome == ClassificationOutcome.COMPILED
        assert result.confidence == 0.85
        assert result.intent == "expense"
        assert result.graph is not None
        assert result.contract is not None
        assert result.extracted_slots == {"category": "test", "threshold": 100.0}

    def test_rejected_conversion(self):
        """Rejected ControllerOutput maps to UNSUPPORTED CompilationResult."""
        output = self._make_rejected_output()
        result = ControllerBridge.output_to_result("test query", output)

        assert result.outcome == ClassificationOutcome.UNSUPPORTED_INTENT
        assert result.confidence == 0.90
        assert result.reason == "Hardware actuation out of scope"
        assert result.graph is None

    def test_all_outcomes_map_correctly(self):
        """All 4 ControllerOutcome values map to ClassificationOutcome."""
        for ctrl_outcome in ControllerOutcome:
            output = ControllerOutput(outcome=ctrl_outcome, raw_ast={"outcome": ctrl_outcome.value})
            result = ControllerBridge.output_to_result("test", output)
            assert result.outcome.value == ctrl_outcome.value


# ─────────────────────────────────────────────────────────────────────────────
# Confidence Calibration Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestConfidenceCalibration:
    """Tests for confidence calibration heuristics."""

    def test_non_compiled_with_reason(self):
        """Non-compiled with reason should have high confidence."""
        # We can't easily instantiate LearnedSemanticController without Ollama,
        # so we test the calibration logic directly
        controller = LearnedSemanticController.__new__(LearnedSemanticController)

        payload = {"outcome": "UNSUPPORTED_INTENT", "reason": "Out of scope"}
        conf = controller._calibrate_confidence(
            payload, None, ControllerOutcome.UNSUPPORTED_INTENT
        )
        assert conf == 0.85

    def test_non_compiled_without_reason(self):
        """Non-compiled without reason should have lower confidence."""
        controller = LearnedSemanticController.__new__(LearnedSemanticController)

        payload = {"outcome": "UNSUPPORTED_INTENT"}
        conf = controller._calibrate_confidence(
            payload, None, ControllerOutcome.UNSUPPORTED_INTENT
        )
        assert conf == 0.60

    def test_compiled_with_full_graph(self):
        """Compiled with valid graph should achieve high confidence."""
        controller = LearnedSemanticController.__new__(LearnedSemanticController)

        graph = SemanticIRGraph()
        obs = IRNode(id="obs", op=OpKind.OBSERVE, inputs=[], attributes={}, output_type=SemanticType.any())
        emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs"], attributes={}, output_type=SemanticType.any())
        graph.add_node(obs)
        graph.add_node(emit)
        graph.root_id = "emit"

        payload = {
            "outcome": "COMPILED",
            "root_id": "emit",
            "slots": {"category": "test"},
            "nodes": [
                {"id": "obs", "op": "Observe", "inputs": []},
                {"id": "emit", "op": "Emit", "inputs": ["obs"]},
            ]
        }

        conf = controller._calibrate_confidence(
            payload, graph, ControllerOutcome.COMPILED
        )
        # Schema valid (0.3) + DAG acyclic (0.2) + inputs resolved (0.2) + Emit root (0.15) + slots (0.15)
        assert conf == 1.0

    def test_confidence_never_exceeds_one(self):
        """Confidence should be clamped to [0, 1]."""
        controller = LearnedSemanticController.__new__(LearnedSemanticController)

        graph = SemanticIRGraph()
        obs = IRNode(id="obs", op=OpKind.OBSERVE, inputs=[], attributes={}, output_type=SemanticType.any())
        emit = IRNode(id="emit", op=OpKind.EMIT, inputs=["obs"], attributes={}, output_type=SemanticType.any())
        graph.add_node(obs)
        graph.add_node(emit)
        graph.root_id = "emit"

        payload = {
            "outcome": "COMPILED",
            "root_id": "emit",
            "slots": {"a": 1},
            "nodes": []
        }

        conf = controller._calibrate_confidence(payload, graph, ControllerOutcome.COMPILED)
        assert 0.0 <= conf <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Schema Validation Tests (extended)
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaValidation:
    """Extended schema validation tests."""

    def test_rejects_invalid_primitives(self):
        """Schema must reject non-frozen primitive names."""
        invalid_payload = {
            "outcome": "COMPILED",
            "intent": "test",
            "reason": None,
            "contract": {"contract_type": "EXACT", "decision_boundary": None},
            "slots": {},
            "nodes": [
                {"id": "n1", "op": "Delete", "inputs": [], "attributes": {}, "output_type": "any"},
                {"id": "emit", "op": "Emit", "inputs": ["n1"], "attributes": {}, "output_type": "any"}
            ],
            "root_id": "emit"
        }
        is_valid, reason = validate_raw_graph(invalid_payload)
        assert not is_valid
        assert "Delete" in reason or "enum" in reason.lower()

    def test_rejects_cyclic_graph(self):
        """Schema must reject cyclic graphs."""
        cyclic_payload = {
            "outcome": "COMPILED",
            "intent": "test",
            "reason": None,
            "contract": {"contract_type": "EXACT", "decision_boundary": None},
            "slots": {},
            "nodes": [
                {"id": "a", "op": "Observe", "inputs": ["b"], "attributes": {}, "output_type": "collection"},
                {"id": "b", "op": "Filter", "inputs": ["a"], "attributes": {}, "output_type": "collection"},
                {"id": "emit", "op": "Emit", "inputs": ["b"], "attributes": {}, "output_type": "any"}
            ],
            "root_id": "emit"
        }
        is_valid, reason = validate_raw_graph(cyclic_payload)
        assert not is_valid
        assert "cycle" in reason.lower() or "Cycle" in reason

    def test_accepts_valid_linear_graph(self):
        """Valid linear graph should pass."""
        valid_payload = {
            "outcome": "COMPILED",
            "intent": "expense",
            "reason": None,
            "contract": {"contract_type": "EXACT", "decision_boundary": None},
            "slots": {"category": "Food"},
            "nodes": [
                {"id": "obs", "op": "Observe", "inputs": [], "attributes": {"source": "tx"}, "output_type": "collection"},
                {"id": "filt", "op": "Filter", "inputs": ["obs"], "attributes": {"cat": "Food"}, "output_type": "collection"},
                {"id": "emit", "op": "Emit", "inputs": ["filt"], "attributes": {}, "output_type": "collection"}
            ],
            "root_id": "emit"
        }
        is_valid, reason = validate_raw_graph(valid_payload)
        assert is_valid, f"Valid graph failed: {reason}"


# ─────────────────────────────────────────────────────────────────────────────
# Chat Dataset Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestChatDataset:
    """Tests for the chat dataset builder output."""

    def test_chat_dataset_exists(self):
        """Chat dataset files should exist after build."""
        base_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "artifacts", "p1_dataset"
        )
        train_path = os.path.join(base_dir, "train_chat.jsonl")
        val_path = os.path.join(base_dir, "val_chat.jsonl")
        assert os.path.exists(train_path), "train_chat.jsonl not found"
        assert os.path.exists(val_path), "val_chat.jsonl not found"

    def test_chat_records_have_correct_structure(self):
        """Chat records must have messages array and metadata."""
        base_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "artifacts", "p1_dataset"
        )
        train_path = os.path.join(base_dir, "train_chat.jsonl")
        if not os.path.exists(train_path):
            pytest.skip("train_chat.jsonl not built yet")

        with open(train_path, "r", encoding="utf-8") as f:
            first_line = f.readline()
        rec = json.loads(first_line)

        assert "messages" in rec
        assert "metadata" in rec
        assert isinstance(rec["messages"], list)
        assert len(rec["messages"]) >= 4  # system + at least 1 demo pair + query pair

        # First message must be system
        assert rec["messages"][0]["role"] == "system"

        # Last two must be user query + assistant gold AST
        assert rec["messages"][-2]["role"] == "user"
        assert rec["messages"][-1]["role"] == "assistant"

        # Gold AST must be valid JSON
        gold = json.loads(rec["messages"][-1]["content"])
        assert "outcome" in gold

    def test_no_lambda_references_in_gold(self):
        """Gold ASTs must not contain raw Python lambda references."""
        base_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "artifacts", "p1_dataset"
        )
        train_path = os.path.join(base_dir, "train_chat.jsonl")
        if not os.path.exists(train_path):
            pytest.skip("train_chat.jsonl not built yet")

        import re
        lambda_pattern = re.compile(r"<function\s+[\w.<>\s]+at\s+0x[0-9a-fA-F]+>")

        with open(train_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                rec = json.loads(line)
                gold_str = rec["messages"][-1]["content"]
                match = lambda_pattern.search(gold_str)
                assert match is None, (
                    f"Lambda reference found in record {i}: {match.group()}"
                )
                if i >= 50:  # Sample check
                    break
