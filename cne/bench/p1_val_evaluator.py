"""
Phase P1 Validation & Anchored Test Evaluator.
Runs the learned controller against val.jsonl (172 queries) or test_anchored.jsonl (174 queries)
and computes comprehensive evaluation metrics.

Usage:
    python -m cne.bench.p1_val_evaluator                    # Evaluate val split
    python -m cne.bench.p1_val_evaluator --split test_anchored  # Evaluate anchored test split

Metrics computed:
1. Schema validity rate
2. Outcome classification accuracy (4-way)
3. Topology routing accuracy (for COMPILED queries)
4. Slot extraction exact match rate
5. Per-topology breakdown
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cne.compiler.constrained_decoder import (
    ControllerOutcome,
    ControllerOutput,
    LearnedSemanticController,
)
from cne.compiler.controller_bridge import ControllerBridge
from cne.compiler.grammar_schema import validate_raw_graph


@dataclass
class EvalMetrics:
    split: str
    total_queries: int
    schema_validity_rate: float
    outcome_accuracy: float
    compiled_count: int
    unsupported_count: int
    ambiguous_count: int
    low_confidence_count: int
    decoder_error_count: int
    topology_accuracy: float
    slot_accuracy: float
    total_slots_evaluated: int
    correct_slots: int
    per_topology: Dict[str, Dict[str, Any]]
    avg_latency_ms: float
    outcome_confusion: Dict[str, Dict[str, int]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "split": self.split,
            "total_queries": self.total_queries,
            "schema_validity_rate": round(self.schema_validity_rate, 4),
            "outcome_accuracy": round(self.outcome_accuracy, 4),
            "outcome_distribution": {
                "COMPILED": self.compiled_count,
                "UNSUPPORTED_INTENT": self.unsupported_count,
                "AMBIGUOUS_INTENT": self.ambiguous_count,
                "LOW_CONFIDENCE_MAPPING": self.low_confidence_count,
                "DECODER_ERROR": self.decoder_error_count,
            },
            "topology_accuracy": round(self.topology_accuracy, 4),
            "slot_accuracy": round(self.slot_accuracy, 4),
            "total_slots_evaluated": self.total_slots_evaluated,
            "correct_slots": self.correct_slots,
            "per_topology": self.per_topology,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "outcome_confusion": self.outcome_confusion,
        }



def evaluate_split(
    controller: LearnedSemanticController,
    split_path: str,
    split_name: str,
    limit: Optional[int] = None
) -> EvalMetrics:
    """
    Evaluate the controller on a JSONL dataset split.
    """
    # Load records
    records = []
    with open(split_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if limit is not None and limit > 0:
        records = records[:limit]

    total = len(records)
    print(f"Evaluating {split_name}: {total} queries")

    # Outcome tracking
    outcomes = ["COMPILED", "UNSUPPORTED_INTENT", "AMBIGUOUS_INTENT", "LOW_CONFIDENCE_MAPPING"]
    confusion = {a: {p: 0 for p in outcomes} for a in outcomes}

    schema_valid = 0
    outcome_correct = 0
    compiled_count = 0
    unsupported_count = 0
    ambiguous_count = 0
    low_conf_count = 0
    decoder_error_count = 0

    # Topology tracking
    topo_total = 0
    topo_correct = 0
    per_topology: Dict[str, Dict[str, Any]] = {}

    # Slot tracking
    total_slots = 0
    correct_slots = 0

    # Latency tracking
    latencies = []

    for i, rec in enumerate(records):
        query = rec["query_text"]
        expected_outcome = rec.get("target_outcome", "COMPILED")
        expected_topo = rec.get("target_topology")
        expected_slots = rec.get("target_slots", {}) or {}

        # Run controller
        output = controller.predict(query)
        pred_outcome = output.outcome.value
        latencies.append(output.latency_ms)

        # Progress output
        if (i + 1) % 10 == 0 or i == total - 1:
            print(f"  [{i+1}/{total}] Last: {pred_outcome} | "
                  f"Latency: {output.latency_ms:.0f}ms", flush=True)

        # Schema validity
        if output.raw_ast:
            is_valid, _ = validate_raw_graph(output.raw_ast)
            if is_valid:
                schema_valid += 1
        elif pred_outcome != "COMPILED":
            schema_valid += 1  # Non-compiled with no AST is valid

        # Outcome accuracy
        if pred_outcome == expected_outcome:
            outcome_correct += 1

        # Confusion matrix
        if expected_outcome in confusion and pred_outcome in confusion[expected_outcome]:
            confusion[expected_outcome][pred_outcome] += 1

        # Count outcomes
        if pred_outcome == "COMPILED":
            compiled_count += 1
        elif pred_outcome == "UNSUPPORTED_INTENT":
            unsupported_count += 1
        elif pred_outcome == "AMBIGUOUS_INTENT":
            ambiguous_count += 1
        elif pred_outcome == "LOW_CONFIDENCE_MAPPING":
            low_conf_count += 1
        else:
            decoder_error_count += 1

        # Topology routing (only when both expected and predicted are COMPILED)
        if expected_outcome == "COMPILED" and pred_outcome == "COMPILED":
            topo_total += 1
            pred_intent = output.raw_ast.get("intent") if output.raw_ast else None

            if expected_topo not in per_topology:
                per_topology[expected_topo] = {
                    "total": 0, "correct": 0, "compiled": 0
                }
            per_topology[expected_topo]["total"] += 1
            per_topology[expected_topo]["compiled"] += 1

            if pred_intent == expected_topo:
                topo_correct += 1
                per_topology[expected_topo]["correct"] += 1

        # Slot evaluation
        if expected_outcome == "COMPILED" and pred_outcome == "COMPILED":
            pred_slots = output.slots or {}
            for slot_key, exp_val in expected_slots.items():
                if exp_val is None:
                    continue
                total_slots += 1
                act_val = pred_slots.get(slot_key)
                if act_val is None:
                    continue
                # Try numeric comparison first
                matched = False
                try:
                    num_exp = float(exp_val)
                    num_act = float(act_val)
                    if math.isclose(num_exp, num_act, rel_tol=0.05, abs_tol=0.05):
                        correct_slots += 1
                        matched = True
                except (ValueError, TypeError):
                    pass

                if not matched:
                    if str(exp_val).strip().lower() == str(act_val).strip().lower():
                        correct_slots += 1

    return EvalMetrics(
        split=split_name,
        total_queries=total,
        schema_validity_rate=schema_valid / total if total > 0 else 0.0,
        outcome_accuracy=outcome_correct / total if total > 0 else 0.0,
        compiled_count=compiled_count,
        unsupported_count=unsupported_count,
        ambiguous_count=ambiguous_count,
        low_confidence_count=low_conf_count,
        decoder_error_count=decoder_error_count,
        topology_accuracy=topo_correct / topo_total if topo_total > 0 else 0.0,
        slot_accuracy=correct_slots / total_slots if total_slots > 0 else 0.0,
        total_slots_evaluated=total_slots,
        correct_slots=correct_slots,
        per_topology=per_topology,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
        outcome_confusion=confusion,
    )


def main():
    parser = argparse.ArgumentParser(description="P1 Validation/Anchored Test Evaluator")
    parser.add_argument("--split", type=str, default="val",
                       choices=["val", "test_anchored"],
                       help="Which split to evaluate")
    parser.add_argument("--model", type=str, default="qwen2.5-coder:1.5b",
                       help="Ollama model name")
    parser.add_argument("--base-url", type=str, default="http://localhost:11434/v1",
                       help="Ollama API base URL")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit evaluation to first N queries")
    args = parser.parse_args()

    base_dir = os.path.join(
        os.path.dirname(__file__), "..", "artifacts", "p1_dataset"
    )

    if args.split == "val":
        split_path = os.path.join(base_dir, "val.jsonl")
        output_name = "val_eval_results.json" if not args.limit else "val_eval_results_sample.json"
    else:
        split_path = os.path.join(base_dir, "test_anchored.jsonl")
        output_name = "anchored_eval_results.json" if not args.limit else "anchored_eval_results_sample.json"

    if not os.path.exists(split_path):
        print(f"ERROR: {split_path} not found!")
        sys.exit(1)

    # Initialize controller
    controller = LearnedSemanticController(
        model_name=args.model,
        base_url=args.base_url,
    )

    print(f"P1 {args.split} Evaluation")
    print(f"Model: {args.model}")
    print(f"Split: {split_path}")
    if args.limit:
        print(f"Limit: {args.limit} queries")
    print("-" * 60)

    metrics = evaluate_split(controller, split_path, args.split, limit=args.limit)

    # Print summary
    print("\n" + "=" * 60)
    print(f"RESULTS: {args.split}")
    print("=" * 60)
    print(f"  Schema Validity:    {metrics.schema_validity_rate*100:.1f}%")
    print(f"  Outcome Accuracy:   {metrics.outcome_accuracy*100:.1f}%")
    print(f"  COMPILED:           {metrics.compiled_count}/{metrics.total_queries}")
    print(f"  UNSUPPORTED:        {metrics.unsupported_count}/{metrics.total_queries}")
    print(f"  AMBIGUOUS:          {metrics.ambiguous_count}/{metrics.total_queries}")
    print(f"  LOW_CONFIDENCE:     {metrics.low_confidence_count}/{metrics.total_queries}")
    print(f"  DECODER_ERROR:      {metrics.decoder_error_count}/{metrics.total_queries}")
    print(f"  Topology Accuracy:  {metrics.topology_accuracy*100:.1f}%")
    print(f"  Slot Accuracy:      {metrics.slot_accuracy*100:.1f}% ({metrics.correct_slots}/{metrics.total_slots_evaluated})")
    print(f"  Avg Latency:        {metrics.avg_latency_ms:.0f}ms")

    # Save results
    output_path = os.path.join(base_dir, output_name)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metrics.to_dict(), f, indent=2)
    print(f"\nResults saved to: {output_path}")

    # Decision gate check
    print("\n" + "=" * 60)
    print("DECISION GATE CHECK")
    print("=" * 60)
    schema_pass = metrics.schema_validity_rate >= 0.95
    accuracy_pass = metrics.outcome_accuracy >= 0.50

    print(f"  Schema validity >= 95%: {'PASS' if schema_pass else 'FAIL'} ({metrics.schema_validity_rate*100:.1f}%)")
    print(f"  Outcome accuracy >= 50%: {'PASS' if accuracy_pass else 'FAIL'} ({metrics.outcome_accuracy*100:.1f}%)")

    if schema_pass and accuracy_pass:
        print("\n  >> GATE PASSED: Safe to proceed to blind evaluation.")
    else:
        print("\n  >> GATE FAILED: Iterate on prompt engineering before blind eval.")

    return metrics


if __name__ == "__main__":
    main()
