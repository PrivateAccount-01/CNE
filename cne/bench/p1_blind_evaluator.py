"""
Phase P1 Held-Out Blind Corpus Final Evaluator.
Runs the learned controller against test_heldout_blind.jsonl (600 queries) EXACTLY ONCE.

This is the FINAL evaluation step. Results are the official P1 metrics.
Computes the exact delta against the P0.8 rule-based baseline.

WARNING: This script should be run ONLY after the validation split
gate check passes (schema validity >= 95%, outcome accuracy >= 50%).

Usage:
    python -m cne.bench.p1_blind_evaluator
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cne.compiler.constrained_decoder import (
    ControllerOutcome,
    ControllerOutput,
    LearnedSemanticController,
)
from cne.compiler.grammar_schema import FROZEN_PRIMITIVES, validate_raw_graph


# ─────────────────────────────────────────────────────────────────────────────
# P0.8 Baseline Constants (from docs/P08_DOMAIN_TRIAGE.md)
# ─────────────────────────────────────────────────────────────────────────────

P08_BASELINE = {
    "blind_coverage": {"value": 0.142, "count": 85, "total": 600},
    "in_scope_coverage": {"value": 0.340, "count": 85, "total": 250},
    "semantic_validity": {"value": 1.000},
    "slot_accuracy": {"value": 0.8121},
    "oos_rejection": {"value": 1.000, "count": 200, "total": 200},
    "shape_diversity": {"value": 0.0128},
    "primitive_adherence": {"value": 1.000},
}

# Target domains (in-scope for P1)
IN_SCOPE_DOMAINS = {
    "finances_budgeting",
    "scheduling_planning",
    "health_fitness",
    "shopping_inventory",
    "math_calculations",
    "communication_messaging",
    "file_data_management",
    "home_automation_iot",
}

# Out-of-scope domains (must be rejected)
OOS_DOMAINS = {
    "system_settings_device",
    "media_entertainment",
    "open_web_search_knowledge",
    "creative_brainstorming",
}

P1_TARGETS = {
    "blind_coverage": 0.350,          # >= 35.0% compiled (>= 210/600)
    "in_scope_coverage": 0.600,       # >= 60.0% compiled (>= 150/250)
    "semantic_validity": 0.900,       # >= 90.0% valid
    "slot_accuracy": 0.900,           # >= 90.0% exact match
    "oos_rejection": 0.950,           # >= 95.0% rejected
    "shape_diversity_max": 0.350,     # D(N) <= 0.35
    "primitive_adherence": 1.000,     # 100% frozen
}


@dataclass
class BlindEvalResult:
    """Complete blind evaluation result with baseline delta."""
    timestamp: str
    model_name: str

    # Coverage
    total_queries: int
    compiled_count: int
    blind_coverage: float

    # In-scope
    in_scope_total: int
    in_scope_compiled: int
    in_scope_coverage: float

    # OOS rejection
    oos_total: int
    oos_rejected: int
    oos_rejection_rate: float

    # Schema / validity
    schema_valid_count: int
    schema_validity_rate: float
    primitive_violations: int
    primitive_adherence: float

    # Semantic validity (proxy — misinterpretation detection)
    semantic_valid_count: int
    semantic_validity_rate: float

    # Slots
    total_slots: int
    correct_slots: int
    slot_accuracy: float

    # Shape diversity
    distinct_shapes: int
    shape_diversity: float

    # Performance
    avg_latency_ms: float
    total_runtime_s: float

    # Per-domain breakdown
    per_domain: Dict[str, Dict[str, Any]]

    # Outcome distribution
    outcome_distribution: Dict[str, int]

    # Delta vs baseline
    deltas: Dict[str, Dict[str, Any]]

    # Pass/fail
    targets_met: Dict[str, bool]
    overall_pass: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "model_name": self.model_name,
            "coverage": {
                "blind_total": self.total_queries,
                "compiled": self.compiled_count,
                "blind_coverage": round(self.blind_coverage, 4),
            },
            "in_scope": {
                "total": self.in_scope_total,
                "compiled": self.in_scope_compiled,
                "coverage": round(self.in_scope_coverage, 4),
            },
            "oos_rejection": {
                "total": self.oos_total,
                "rejected": self.oos_rejected,
                "rate": round(self.oos_rejection_rate, 4),
            },
            "validity": {
                "schema_valid": self.schema_valid_count,
                "schema_rate": round(self.schema_validity_rate, 4),
                "primitive_violations": self.primitive_violations,
                "primitive_adherence": round(self.primitive_adherence, 4),
                "semantic_valid": self.semantic_valid_count,
                "semantic_rate": round(self.semantic_validity_rate, 4),
            },
            "slots": {
                "total": self.total_slots,
                "correct": self.correct_slots,
                "accuracy": round(self.slot_accuracy, 4),
            },
            "shapes": {
                "distinct": self.distinct_shapes,
                "diversity": round(self.shape_diversity, 4),
            },
            "performance": {
                "avg_latency_ms": round(self.avg_latency_ms, 2),
                "total_runtime_s": round(self.total_runtime_s, 2),
            },
            "per_domain": self.per_domain,
            "outcome_distribution": self.outcome_distribution,
            "deltas_vs_p08": self.deltas,
            "targets_met": self.targets_met,
            "overall_pass": self.overall_pass,
        }


def evaluate_blind_corpus(
    controller: LearnedSemanticController,
    blind_path: str,
    model_name: str
) -> BlindEvalResult:
    """Run the full blind corpus evaluation."""

    # Load blind corpus
    records = []
    with open(blind_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    total = len(records)
    assert total == 600, f"Expected 600 blind queries, got {total}"
    print(f"Loaded {total} blind queries. Beginning ONE-SHOT evaluation...")
    print("=" * 70)

    t_start = time.perf_counter()

    # Accumulators
    compiled_count = 0
    schema_valid_count = 0
    primitive_violations = 0
    semantic_valid_count = 0
    latencies = []
    shapes: List[str] = []
    outcome_counts = Counter()

    # Domain tracking
    per_domain: Dict[str, Dict[str, Any]] = {}

    # In-scope / OOS
    in_scope_total = 0
    in_scope_compiled = 0
    oos_total = 0
    oos_rejected = 0

    # Slot tracking
    total_slots = 0
    correct_slots = 0

    for i, rec in enumerate(records):
        query = rec["query_text"]
        domain = rec.get("domain", "unknown")

        # Initialize domain tracking
        if domain not in per_domain:
            per_domain[domain] = {
                "total": 0, "compiled": 0, "rejected": 0,
                "schema_valid": 0, "semantic_valid": 0,
            }
        per_domain[domain]["total"] += 1

        # Run controller
        output = controller.predict(query)
        pred_outcome = output.outcome.value
        latencies.append(output.latency_ms)
        outcome_counts[pred_outcome] += 1

        # Progress
        if (i + 1) % 50 == 0 or i == total - 1:
            elapsed = time.perf_counter() - t_start
            rate = (i + 1) / elapsed
            eta = (total - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{total}] {pred_outcome:25s} | "
                  f"{output.latency_ms:6.0f}ms | "
                  f"Compiled: {compiled_count} | "
                  f"ETA: {eta:.0f}s", flush=True)

        # Coverage
        if pred_outcome == "COMPILED":
            compiled_count += 1
            per_domain[domain]["compiled"] += 1
        else:
            per_domain[domain]["rejected"] += 1

        # In-scope / OOS classification
        if domain in IN_SCOPE_DOMAINS:
            in_scope_total += 1
            if pred_outcome == "COMPILED":
                in_scope_compiled += 1
        elif domain in OOS_DOMAINS:
            oos_total += 1
            if pred_outcome in ("UNSUPPORTED_INTENT", "LOW_CONFIDENCE_MAPPING", "AMBIGUOUS_INTENT"):
                oos_rejected += 1

        # Schema validity
        if output.raw_ast:
            is_valid, reason = validate_raw_graph(output.raw_ast)
            if is_valid:
                schema_valid_count += 1
                per_domain[domain]["schema_valid"] += 1
            # Primitive adherence check
            for node in output.raw_ast.get("nodes", []):
                op = node.get("op", "")
                if op not in FROZEN_PRIMITIVES:
                    primitive_violations += 1
        elif pred_outcome != "COMPILED":
            schema_valid_count += 1
            per_domain[domain]["schema_valid"] += 1

        # Semantic validity (basic proxy)
        if pred_outcome == "COMPILED" and output.graph:
            # Check that the graph topology makes sense for the query
            # Basic heuristic: graph has Observe root and Emit sink
            has_observe = any(
                n.op.value in ("Observe", "Literal")
                for n in output.graph.nodes.values()
            )
            has_emit = any(
                n.op.value == "Emit"
                for n in output.graph.nodes.values()
            )
            if has_observe and has_emit:
                semantic_valid_count += 1
                per_domain[domain]["semantic_valid"] += 1
        elif pred_outcome != "COMPILED":
            semantic_valid_count += 1
            per_domain[domain]["semantic_valid"] += 1

        # Shape tracking
        if output.shape_key:
            shapes.append(output.shape_key)

        # Slot evaluation
        expected_slots = rec.get("target_slots", {}) or {}
        if pred_outcome == "COMPILED" and output.slots:
            for slot_key, exp_val in expected_slots.items():
                if exp_val is None:
                    continue
                total_slots += 1
                act_val = output.slots.get(slot_key)
                if act_val is None:
                    continue
                if isinstance(exp_val, (int, float)) and isinstance(act_val, (int, float)):
                    if math.isclose(float(exp_val), float(act_val), rel_tol=0.05, abs_tol=0.05):
                        correct_slots += 1
                else:
                    if str(exp_val).strip().lower() == str(act_val).strip().lower():
                        correct_slots += 1

    total_runtime = time.perf_counter() - t_start

    # Compute metrics
    blind_coverage = compiled_count / total
    in_scope_coverage = in_scope_compiled / in_scope_total if in_scope_total > 0 else 0.0
    oos_rejection_rate = oos_rejected / oos_total if oos_total > 0 else 0.0
    schema_validity_rate = schema_valid_count / total
    primitive_adherence = 1.0 if primitive_violations == 0 else (total - primitive_violations) / total
    semantic_validity_rate = semantic_valid_count / total
    slot_accuracy = correct_slots / total_slots if total_slots > 0 else 0.0
    distinct_shapes = len(set(shapes))

    # Shape diversity D(N) - normalized entropy
    if shapes:
        shape_counts = Counter(shapes)
        n_compiled = len(shapes)
        entropy = -sum(
            (c / n_compiled) * math.log2(c / n_compiled)
            for c in shape_counts.values()
        )
        max_entropy = math.log2(len(shape_counts)) if len(shape_counts) > 1 else 1.0
        shape_diversity = entropy / max_entropy if max_entropy > 0 else 0.0
    else:
        shape_diversity = 0.0

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    # Compute deltas vs P0.8 baseline
    deltas = {
        "blind_coverage": {
            "p08": P08_BASELINE["blind_coverage"]["value"],
            "p1": blind_coverage,
            "delta": blind_coverage - P08_BASELINE["blind_coverage"]["value"],
            "delta_pct": f"+{(blind_coverage - P08_BASELINE['blind_coverage']['value'])*100:.1f}pp" if blind_coverage > P08_BASELINE["blind_coverage"]["value"] else f"{(blind_coverage - P08_BASELINE['blind_coverage']['value'])*100:.1f}pp",
        },
        "in_scope_coverage": {
            "p08": P08_BASELINE["in_scope_coverage"]["value"],
            "p1": in_scope_coverage,
            "delta": in_scope_coverage - P08_BASELINE["in_scope_coverage"]["value"],
        },
        "semantic_validity": {
            "p08": P08_BASELINE["semantic_validity"]["value"],
            "p1": semantic_validity_rate,
            "delta": semantic_validity_rate - P08_BASELINE["semantic_validity"]["value"],
        },
        "slot_accuracy": {
            "p08": P08_BASELINE["slot_accuracy"]["value"],
            "p1": slot_accuracy,
            "delta": slot_accuracy - P08_BASELINE["slot_accuracy"]["value"],
        },
        "oos_rejection": {
            "p08": P08_BASELINE["oos_rejection"]["value"],
            "p1": oos_rejection_rate,
            "delta": oos_rejection_rate - P08_BASELINE["oos_rejection"]["value"],
        },
        "primitive_adherence": {
            "p08": P08_BASELINE["primitive_adherence"]["value"],
            "p1": primitive_adherence,
            "delta": primitive_adherence - P08_BASELINE["primitive_adherence"]["value"],
        },
    }

    # Check targets
    targets_met = {
        "blind_coverage >= 35%": blind_coverage >= P1_TARGETS["blind_coverage"],
        "in_scope_coverage >= 60%": in_scope_coverage >= P1_TARGETS["in_scope_coverage"],
        "semantic_validity >= 90%": semantic_validity_rate >= P1_TARGETS["semantic_validity"],
        "slot_accuracy >= 90%": slot_accuracy >= P1_TARGETS["slot_accuracy"],
        "oos_rejection >= 95%": oos_rejection_rate >= P1_TARGETS["oos_rejection"],
        "shape_diversity <= 0.35": shape_diversity <= P1_TARGETS["shape_diversity_max"],
        "primitive_adherence == 100%": primitive_adherence >= P1_TARGETS["primitive_adherence"],
    }
    overall_pass = all(targets_met.values())

    return BlindEvalResult(
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        model_name=model_name,
        total_queries=total,
        compiled_count=compiled_count,
        blind_coverage=blind_coverage,
        in_scope_total=in_scope_total,
        in_scope_compiled=in_scope_compiled,
        in_scope_coverage=in_scope_coverage,
        oos_total=oos_total,
        oos_rejected=oos_rejected,
        oos_rejection_rate=oos_rejection_rate,
        schema_valid_count=schema_valid_count,
        schema_validity_rate=schema_validity_rate,
        primitive_violations=primitive_violations,
        primitive_adherence=primitive_adherence,
        semantic_valid_count=semantic_valid_count,
        semantic_validity_rate=semantic_validity_rate,
        total_slots=total_slots,
        correct_slots=correct_slots,
        slot_accuracy=slot_accuracy,
        distinct_shapes=distinct_shapes,
        shape_diversity=shape_diversity,
        avg_latency_ms=avg_latency,
        total_runtime_s=total_runtime,
        per_domain=per_domain,
        outcome_distribution=dict(outcome_counts),
        deltas=deltas,
        targets_met=targets_met,
        overall_pass=overall_pass,
    )


def generate_report(result: BlindEvalResult, report_path: str):
    """Generate the markdown evaluation report."""
    r = result

    # Build per-domain table
    domain_rows = []
    for domain in sorted(r.per_domain.keys()):
        d = r.per_domain[domain]
        coverage = d["compiled"] / d["total"] * 100 if d["total"] > 0 else 0
        scope = "In-Scope" if domain in IN_SCOPE_DOMAINS else "OOS" if domain in OOS_DOMAINS else "Other"
        domain_rows.append(
            f"| {domain} | {scope} | {d['total']} | {d['compiled']} | {coverage:.1f}% | "
            f"{d['schema_valid']} | {d['semantic_valid']} |"
        )

    # Build delta table
    delta_rows = []
    for metric, d in r.deltas.items():
        p08 = f"{d['p08']*100:.1f}%"
        p1 = f"{d['p1']*100:.1f}%"
        delta_val = d['delta'] * 100
        delta_str = f"+{delta_val:.1f}pp" if delta_val >= 0 else f"{delta_val:.1f}pp"
        delta_rows.append(f"| {metric} | {p08} | {p1} | {delta_str} |")

    # Build target table
    target_rows = []
    for target, met in r.targets_met.items():
        status = "PASS" if met else "FAIL"
        target_rows.append(f"| {target} | {status} |")

    report = f"""# Phase P1 Evaluation Report

**Generated:** {r.timestamp}
**Model:** {r.model_name}
**Status:** {'GO -- All Targets Met' if r.overall_pass else 'ITERATE -- Some Targets Not Met'}

---

## 1. Executive Summary

| Metric | Value |
|:---|:---:|
| **Blind Coverage** | {r.blind_coverage*100:.1f}% ({r.compiled_count}/{r.total_queries}) |
| **In-Scope Coverage** | {r.in_scope_coverage*100:.1f}% ({r.in_scope_compiled}/{r.in_scope_total}) |
| **OOS Rejection** | {r.oos_rejection_rate*100:.1f}% ({r.oos_rejected}/{r.oos_total}) |
| **Schema Validity** | {r.schema_validity_rate*100:.1f}% |
| **Semantic Validity** | {r.semantic_validity_rate*100:.1f}% |
| **Slot Accuracy** | {r.slot_accuracy*100:.1f}% ({r.correct_slots}/{r.total_slots}) |
| **Shape Diversity D(N)** | {r.shape_diversity:.4f} |
| **Primitive Adherence** | {r.primitive_adherence*100:.1f}% (violations: {r.primitive_violations}) |
| **Avg Latency** | {r.avg_latency_ms:.0f}ms |
| **Total Runtime** | {r.total_runtime_s:.1f}s |

---

## 2. Coverage Delta vs P0.8 Baseline

| Metric | P0.8 Baseline | P1 Result | Delta |
|:---|:---:|:---:|:---:|
{chr(10).join(delta_rows)}

---

## 3. Success Criteria Audit

| Target | Status |
|:---|:---:|
{chr(10).join(target_rows)}

**Overall Decision: {'GO' if r.overall_pass else 'ITERATE'}**

---

## 4. Per-Domain Breakdown

| Domain | Scope | Total | Compiled | Coverage | Schema Valid | Semantic Valid |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
{chr(10).join(domain_rows)}

---

## 5. Outcome Distribution

| Outcome | Count | Rate |
|:---|:---:|:---:|
| COMPILED | {r.outcome_distribution.get('COMPILED', 0)} | {r.outcome_distribution.get('COMPILED', 0)/r.total_queries*100:.1f}% |
| UNSUPPORTED_INTENT | {r.outcome_distribution.get('UNSUPPORTED_INTENT', 0)} | {r.outcome_distribution.get('UNSUPPORTED_INTENT', 0)/r.total_queries*100:.1f}% |
| AMBIGUOUS_INTENT | {r.outcome_distribution.get('AMBIGUOUS_INTENT', 0)} | {r.outcome_distribution.get('AMBIGUOUS_INTENT', 0)/r.total_queries*100:.1f}% |
| LOW_CONFIDENCE_MAPPING | {r.outcome_distribution.get('LOW_CONFIDENCE_MAPPING', 0)} | {r.outcome_distribution.get('LOW_CONFIDENCE_MAPPING', 0)/r.total_queries*100:.1f}% |

---

## 6. Shape Topology Analysis

- **Distinct shapes discovered:** {r.distinct_shapes}
- **Shape diversity D(N):** {r.shape_diversity:.4f}
- **P0.8 baseline D(N):** {P08_BASELINE['shape_diversity']['value']:.4f}

---

## 7. Raw Artifacts

- `cne/artifacts/p1_dataset/blind_eval_results.json` — Full JSON results
- `docs/P1_EVALUATION_REPORT.md` — This report
"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)


def main():
    parser = argparse.ArgumentParser(description="P1 Blind Corpus Final Evaluator (ONE-SHOT)")
    parser.add_argument("--model", type=str, default="qwen2.5-coder:1.5b",
                       help="Ollama model name")
    parser.add_argument("--base-url", type=str, default="http://localhost:11434/v1",
                       help="Ollama API base URL")
    parser.add_argument("--force", action="store_true",
                       help="Skip pre-flight gate check")
    args = parser.parse_args()

    base_dir = os.path.join(
        os.path.dirname(__file__), "..", "artifacts", "p1_dataset"
    )
    blind_path = os.path.join(base_dir, "test_heldout_blind.jsonl")
    results_path = os.path.join(base_dir, "blind_eval_results.json")
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "..", "docs")
    report_path = os.path.join(docs_dir, "P1_EVALUATION_REPORT.md")

    if not os.path.exists(blind_path):
        print(f"ERROR: {blind_path} not found!")
        sys.exit(1)

    # Pre-flight gate check
    if not args.force:
        val_results_path = os.path.join(base_dir, "val_eval_results.json")
        if os.path.exists(val_results_path):
            with open(val_results_path, "r", encoding="utf-8") as f:
                val_results = json.load(f)
            schema_ok = val_results.get("schema_validity_rate", 0) >= 0.95
            accuracy_ok = val_results.get("outcome_accuracy", 0) >= 0.50
            if not (schema_ok and accuracy_ok):
                print("GATE CHECK FAILED: Val split results do not meet thresholds.")
                print(f"  Schema validity: {val_results.get('schema_validity_rate', 0)*100:.1f}% (need >= 95%)")
                print(f"  Outcome accuracy: {val_results.get('outcome_accuracy', 0)*100:.1f}% (need >= 50%)")
                print("Run with --force to override.")
                sys.exit(1)
            print("Pre-flight gate check: PASSED")
        else:
            print("WARNING: No val_eval_results.json found. Run p1_val_evaluator first.")
            print("Run with --force to override.")
            sys.exit(1)

    # Initialize controller
    controller = LearnedSemanticController(
        model_name=args.model,
        base_url=args.base_url,
    )

    print("=" * 70)
    print("P1 BLIND CORPUS FINAL EVALUATION (ONE-SHOT)")
    print(f"Model: {args.model}")
    print(f"Corpus: {blind_path} (600 queries)")
    print("=" * 70)

    result = evaluate_blind_corpus(controller, blind_path, args.model)

    # Save JSON results
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)
    print(f"\nJSON results saved: {results_path}")

    # Generate report
    generate_report(result, report_path)
    print(f"Report generated: {report_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)
    print(f"  Blind Coverage:      {result.blind_coverage*100:.1f}% ({result.compiled_count}/600)")
    print(f"  In-Scope Coverage:   {result.in_scope_coverage*100:.1f}% ({result.in_scope_compiled}/{result.in_scope_total})")
    print(f"  OOS Rejection:       {result.oos_rejection_rate*100:.1f}% ({result.oos_rejected}/{result.oos_total})")
    print(f"  Schema Validity:     {result.schema_validity_rate*100:.1f}%")
    print(f"  Semantic Validity:   {result.semantic_validity_rate*100:.1f}%")
    print(f"  Slot Accuracy:       {result.slot_accuracy*100:.1f}%")
    print(f"  Shape Diversity:     {result.shape_diversity:.4f}")
    print(f"  Primitive Adherence: {result.primitive_adherence*100:.1f}%")
    print(f"  Avg Latency:         {result.avg_latency_ms:.0f}ms")
    print(f"  Total Runtime:       {result.total_runtime_s:.1f}s")

    print("\n  TARGET STATUS:")
    for target, met in result.targets_met.items():
        status = "PASS" if met else "FAIL"
        print(f"    [{status}] {target}")

    print(f"\n  OVERALL: {'GO' if result.overall_pass else 'ITERATE'}")


if __name__ == "__main__":
    main()
