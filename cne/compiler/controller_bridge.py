"""
CNE Controller-Compiler Bridge.
Provides a drop-in adapter allowing the LearnedSemanticController to be used
wherever NLCompiler.compile() is currently called.

This bridges ControllerOutput -> CompilationResult, ensuring all existing
evaluation infrastructure (SemanticGoldEvaluator, BlindSemanticValidator,
gate checks) works unchanged with the learned controller.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from cne.compiler.constrained_decoder import (
    ControllerOutcome,
    ControllerOutput,
    LearnedSemanticController,
)
from cne.compiler.nl_compiler import ClassificationOutcome, CompilationResult


class ControllerBridge:
    """
    Bridges LearnedSemanticController output into CompilationResult,
    making the learned controller a drop-in replacement for NLCompiler.
    """

    def __init__(
        self,
        controller: LearnedSemanticController,
    ):
        self.controller = controller

    def compile(self, query_text: str) -> CompilationResult:
        """
        Drop-in replacement for NLCompiler.compile().
        Translates ControllerOutput -> CompilationResult.
        """
        output = self.controller.predict(query_text)
        return self._to_compilation_result(query_text, output)

    @staticmethod
    def _to_compilation_result(
        query_text: str,
        output: ControllerOutput
    ) -> CompilationResult:
        """Convert a ControllerOutput into a CompilationResult."""
        # Map ControllerOutcome -> ClassificationOutcome
        outcome_map = {
            ControllerOutcome.COMPILED: ClassificationOutcome.COMPILED,
            ControllerOutcome.UNSUPPORTED_INTENT: ClassificationOutcome.UNSUPPORTED_INTENT,
            ControllerOutcome.AMBIGUOUS_INTENT: ClassificationOutcome.AMBIGUOUS_INTENT,
            ControllerOutcome.LOW_CONFIDENCE_MAPPING: ClassificationOutcome.LOW_CONFIDENCE_MAPPING,
        }
        classification = outcome_map.get(
            output.outcome, ClassificationOutcome.LOW_CONFIDENCE_MAPPING
        )

        # Infer intent from shape_key or raw_ast
        intent = None
        if output.raw_ast:
            intent = output.raw_ast.get("intent")

        return CompilationResult(
            query_text=query_text,
            outcome=classification,
            confidence=output.confidence_score,
            intent=intent,
            graph=output.graph,
            contract=output.contract,
            extracted_slots=output.slots or {},
            reason=output.decline_reason,
        )

    @staticmethod
    def output_to_result(
        query_text: str,
        output: ControllerOutput
    ) -> CompilationResult:
        """Public static method for one-off conversions."""
        return ControllerBridge._to_compilation_result(query_text, output)
