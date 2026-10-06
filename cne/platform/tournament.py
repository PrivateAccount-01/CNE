"""Configurable real-GGUF tournament. Never downloads assets or opens held-out data."""
from __future__ import annotations
import argparse
from dataclasses import replace
import json
from pathlib import Path
from cne.platform.benchmark import ModelSelectionHarness
from cne.platform.models import (
    LlamaCppRuntimeAdapter,
    ModelDescriptor,
    ModelKind,
    ModelRequest,
)
from cne.optimizer.necessity_engine import ComputationNecessityEngine


def run_tournament(candidates, cases):
    """Candidates are host-supplied descriptors; cases are a non-blind development set."""
    reports = []
    for descriptor in candidates:
        runtime = LlamaCppRuntimeAdapter()
        try:
            runtime.load_model(descriptor)
        except (FileNotFoundError, RuntimeError) as exc:
            reports.append(
                {
                    "candidate": descriptor.model_id,
                    "status": "NOT_TESTED",
                    "reason": str(exc),
                }
            )
            continue
        try:

            def infer(query):
                prompt = (
                    "Return one JSON object with outcome (COMPILED, UNSUPPORTED_INTENT, AMBIGUOUS_INTENT, LOW_CONFIDENCE_MAPPING), selected_capability_ids, intent, extracted_slots, and semantic_dsl. DSL nodes require explicit IDs and input references.\nRequest: "
                    + query
                )
                return runtime.infer(
                    ModelRequest(
                        "tournament",
                        descriptor.model_id,
                        prompt,
                        {"max_tokens": 512, "temp": 0.0},
                        timeout_s=120,
                    )
                )

            result = ModelSelectionHarness().evaluate_candidate(
                descriptor, infer, cases
            )
            reports.append(
                {
                    "candidate": descriptor.model_id,
                    "status": "MEASURED",
                    "result": result.to_dict(),
                }
            )
        finally:
            runtime.unload_model(descriptor.model_id)
    return {
        "candidate_results": reports,
        "selected_controller": None,
        "selection_policy": "No final controller selection during hardening",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        required=True,
        help="JSON with candidates and non-blind development cases",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if config.get("dataset_role") != "development":
        raise ValueError(
            "Explicit development dataset required; held-out comparison is separate"
        )
    candidates = [
        ModelDescriptor(kind=ModelKind.TEXT_GENERATION, **c)
        for c in config["candidates"]
    ]
    cases = config["cases"]
    for case in cases:
        if "expected_output" in case:

            def execute_check(compiled, case=case):
                result = ComputationNecessityEngine().execute_query(
                    compiled.graph, compiled.contract, case.get("environment", {})
                )
                return (
                    result.contract_satisfied
                    and result.value == case["expected_output"]
                )

            case["execute_and_check"] = execute_check
        if "expected_contract_type" in case:
            case["contract_check"] = (
                lambda compiled, case=case: compiled.contract.contract_type.name
                == case["expected_contract_type"]
            )
    Path(args.output).write_text(
        json.dumps(run_tournament(candidates, cases), indent=2)
    )


if __name__ == "__main__":
    main()
