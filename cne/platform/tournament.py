"""Production-path controller comparison harness; no automatic promotion."""
from dataclasses import dataclass
import hashlib
import json
import time


@dataclass(frozen=True)
class TournamentCase:
    case_id: str
    query: str
    expected_capability_ids: tuple
    expected_intent: str | None
    expected_outcome: str
    expected_value: object = None
    env: dict | None = None


class ProductionControllerTournament:
    """Evaluates descriptors through the same runtime controller, bridge and CNE."""

    def run(self, runtime_factory, descriptor, cases, user_id="tournament"):
        runtime = runtime_factory(descriptor)
        outcomes = []
        prompts = []
        latencies = []
        try:
            for case in cases:
                start = time.perf_counter()
                result = runtime.executor.execute(
                    user_id, "tournament-" + case.case_id, case.query, case.env or {}
                )
                latencies.append((time.perf_counter() - start) * 1000)
                decision = runtime.executor.bridge.last_decision
                ids = tuple(sorted(decision.selected_capability_ids))
                current = {
                    "case_id": case.case_id,
                    "outcome": decision.outcome.value,
                    "selected_capability_ids": ids,
                    "intent": decision.intent,
                    "value": getattr(result, "value", None),
                    "pass": decision.outcome.value == case.expected_outcome
                    and ids == tuple(sorted(case.expected_capability_ids))
                    and decision.intent == case.expected_intent
                    and (
                        case.expected_value is None
                        or getattr(result, "value", None) == case.expected_value
                    ),
                    "prompt_format_identity": decision.evidence.get(
                        "prompt_format_identity"
                    ),
                    "prompt_sha256": decision.evidence.get("prompt_sha256"),
                    "shortlisted_ids": decision.evidence.get("shortlisted_ids", []),
                    "candidate_k": decision.evidence.get("candidate_k"),
                    "model_dependencies": decision.evidence.get(
                        "model_dependencies", []
                    ),
                    "model_identity": decision.evidence.get("model_identity", {}),
                    "runtime_identity": decision.evidence.get("runtime", {}),
                }
                outcomes.append(current)
                prompts.append(decision.evidence.get("prompt_format_identity"))
        finally:
            runtime.close()
        report = {
            "case_count": len(outcomes),
            "pass_count": sum(x["pass"] for x in outcomes),
            "cases": outcomes,
            "latency_ms": latencies,
            "prompt_format_hashes": sorted(set(filter(None, prompts))),
            "descriptor": getattr(descriptor, "model_id", None),
            "automatic_promotion": False,
        }
        report["report_sha256"] = hashlib.sha256(
            json.dumps(report, sort_keys=True, default=list).encode()
        ).hexdigest()
        return report
