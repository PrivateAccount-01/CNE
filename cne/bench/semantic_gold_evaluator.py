"""
CNE Semantic Gold Ground-Truth Evaluator (Phase P0.7 Revision 3).
Computes rigorous ground-truth validation metrics against the realistic corpus:
1. Classification Confusion Matrix across all 4 outcomes:
   - COMPILED
   - UNSUPPORTED_INTENT
   - AMBIGUOUS_INTENT
   - LOW_CONFIDENCE_MAPPING
2. Precision, Recall, and F1 per classification category.
3. Topology Routing Accuracy: verifies whether compiled queries routed to the intended Semantic IR topology.
4. Slot Extraction Accuracy: checks categorical and numeric slot precision against ground truth.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from cne.compiler.nl_compiler import ClassificationOutcome, CompilationResult


@dataclass
class ClassMetrics:
    name: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


@dataclass
class SemanticGoldReport:
    total_evaluated: int
    overall_accuracy: float
    confusion_matrix: Dict[str, Dict[str, int]]
    class_metrics: Dict[str, ClassMetrics]
    topology_routing_accuracy: float
    topology_counts: Dict[str, Dict[str, int]]
    slot_extraction_accuracy: float
    total_slots_evaluated: int
    correct_slots_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_evaluated": self.total_evaluated,
            "overall_accuracy": round(self.overall_accuracy, 4),
            "confusion_matrix": self.confusion_matrix,
            "class_metrics": {
                name: {
                    "tp": m.tp, "fp": m.fp, "fn": m.fn, "tn": m.tn,
                    "precision": round(m.precision, 4),
                    "recall": round(m.recall, 4),
                    "f1": round(m.f1, 4),
                    "support": m.tp + m.fn
                }
                for name, m in self.class_metrics.items()
            },
            "metrics_per_outcome": {
                name: {
                    "tp": m.tp, "fp": m.fp, "fn": m.fn, "tn": m.tn,
                    "precision": round(m.precision, 4),
                    "recall": round(m.recall, 4),
                    "f1": round(m.f1, 4),
                    "support": m.tp + m.fn
                }
                for name, m in self.class_metrics.items()
            },
            "topology_routing_accuracy": round(self.topology_routing_accuracy, 4),
            "topology_counts": self.topology_counts,
            "slot_extraction_accuracy": round(self.slot_extraction_accuracy, 4),
            "total_slots_evaluated": self.total_slots_evaluated,
            "correct_slots_count": self.correct_slots_count
        }


class SemanticGoldEvaluator:
    OUTCOMES = [
        ClassificationOutcome.COMPILED.value,
        ClassificationOutcome.UNSUPPORTED_INTENT.value,
        ClassificationOutcome.AMBIGUOUS_INTENT.value,
        ClassificationOutcome.LOW_CONFIDENCE_MAPPING.value
    ]

    @classmethod
    def evaluate(
        cls,
        eval_items: List[Tuple[Dict[str, Any], CompilationResult]]
    ) -> SemanticGoldReport:
        total = len(eval_items)
        if total == 0:
            return SemanticGoldReport(0, 0.0, {}, {}, 0.0, {}, 0.0, 0, 0)

        # 1. Confusion Matrix: actual (row) vs predicted (col)
        cm: Dict[str, Dict[str, int]] = {
            act: {pred: 0 for pred in cls.OUTCOMES}
            for act in cls.OUTCOMES
        }

        correct_classification = 0

        # Topology routing tracking
        topology_matches = 0
        total_compiled_pairs = 0
        topo_counts: Dict[str, Dict[str, int]] = {}

        # Slot accuracy tracking
        total_slots = 0
        correct_slots = 0

        for q_meta, comp_res in eval_items:
            exp_outcome = q_meta.get("expected_classification", ClassificationOutcome.COMPILED.value)
            pred_outcome = comp_res.outcome.value

            if exp_outcome in cm and pred_outcome in cm[exp_outcome]:
                cm[exp_outcome][pred_outcome] += 1

            if exp_outcome == pred_outcome:
                correct_classification += 1

            # Topology routing evaluation (only meaningful when intended to compile and was compiled)
            if exp_outcome == ClassificationOutcome.COMPILED.value and pred_outcome == ClassificationOutcome.COMPILED.value:
                total_compiled_pairs += 1
                intended_topo = q_meta.get("intended_topology")
                pred_topo = comp_res.intent

                if intended_topo not in topo_counts:
                    topo_counts[intended_topo] = {"total": 0, "correct": 0}
                topo_counts[intended_topo]["total"] += 1

                if intended_topo == pred_topo:
                    topology_matches += 1
                    topo_counts[intended_topo]["correct"] += 1

            # Slot evaluation
            gt_slots = q_meta.get("slots", {}) or q_meta.get("ground_truth_slots", {})
            pred_slots = comp_res.extracted_slots or {}

            for slot_key, exp_val in gt_slots.items():
                if slot_key in ("source_dep", "contract_override", "env_override", "effect_mode"):
                    continue
                if exp_val is None:
                    continue

                total_slots += 1
                act_val = pred_slots.get(slot_key)

                if act_val is None:
                    continue

                # Numeric slot comparison
                if isinstance(exp_val, (int, float)) and isinstance(act_val, (int, float)):
                    if math.isclose(float(exp_val), float(act_val), rel_tol=0.05, abs_tol=0.05):
                        correct_slots += 1
                else:
                    # Categorical / string comparison
                    if str(exp_val).strip().lower() == str(act_val).strip().lower():
                        correct_slots += 1

        overall_acc = correct_classification / total if total > 0 else 0.0
        topo_acc = topology_matches / total_compiled_pairs if total_compiled_pairs > 0 else 0.0
        slot_acc = correct_slots / total_slots if total_slots > 0 else 0.0

        # Compute per-class precision, recall, F1
        class_metrics: Dict[str, ClassMetrics] = {}
        for c in cls.OUTCOMES:
            tp = cm[c][c]
            fp = sum(cm[other][c] for other in cls.OUTCOMES if other != c)
            fn = sum(cm[c][other] for other in cls.OUTCOMES if other != c)
            tn = sum(cm[o1][o2] for o1 in cls.OUTCOMES for o2 in cls.OUTCOMES if o1 != c and o2 != c)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

            class_metrics[c] = ClassMetrics(
                name=c, tp=tp, fp=fp, fn=fn, tn=tn,
                precision=prec, recall=rec, f1=f1
            )

        return SemanticGoldReport(
            total_evaluated=total,
            overall_accuracy=overall_acc,
            confusion_matrix=cm,
            class_metrics=class_metrics,
            topology_routing_accuracy=topo_acc,
            topology_counts=topo_counts,
            slot_extraction_accuracy=slot_acc,
            total_slots_evaluated=total_slots,
            correct_slots_count=correct_slots
        )
