"""Cross-session correction progression with actual execution, review and restart."""
from dataclasses import dataclass
import time, psutil


@dataclass(frozen=True)
class ProgressionCase:
    id: str
    request: str
    paraphrase: str
    env: dict
    expected: object
    constraint: dict
    verifier_id: str


class RepeatedErrorProgressionBenchmark:
    def run(self, runtime_factory, cases, unrelated=(), user_id="benchmark"):
        if not cases:
            raise ValueError("Independent labeled development cases required")
        runtime = runtime_factory()
        baseline = []
        ids = {}
        latencies = []
        rss_before = psutil.Process().memory_info().rss

        def execute(rt, case, session, paraphrase=False):
            started = time.perf_counter()
            result = rt.executor.execute(
                user_id,
                session,
                case.paraphrase if paraphrase else case.request,
                case.env,
            )
            latencies.append((time.perf_counter() - started) * 1000)
            return getattr(result, "value", object()) == case.expected

        for case in cases:
            correct = execute(runtime, case, "session-0-" + case.id)
            baseline.append(correct)
            if not correct:
                rec = runtime.review.submit_user_feedback(
                    user_id,
                    runtime.executor.last_experience_id,
                    case.request,
                    "Reviewed development correction",
                    case.constraint,
                )
                runtime.review.verify(user_id, rec.record_id, case.verifier_id)
                ids[case.id] = rec.record_id
        stages = {}
        retrieval_tp = retrieval_fp = retrieval_fn = false_applied = 0
        expected_retrieval_total = sum(bool(ids.get(case.id)) for case in cases) * 3
        for stage in (1, 2, 3):
            if stage == 3:
                runtime.close()
                runtime = runtime_factory()
            outcomes = []
            for case in cases:
                outcomes.append(
                    execute(runtime, case, f"session-{stage}-{case.id}", stage == 2)
                )
                got = set(
                    runtime.executor.bridge.last_decision.evidence.get(
                        "retrieved_correction_ids", []
                    )
                )
                expected = {ids[case.id]} if case.id in ids else set()
                retrieval_tp += len(got & expected)
                retrieval_fp += len(got - expected)
                retrieval_fn += len(expected - got)
            stages[str(stage)] = outcomes
        unrelated_correct = 0
        for case in unrelated:
            unrelated_correct += execute(runtime, case, "unrelated-" + case.id)
            false_applied += bool(
                runtime.executor.bridge.last_decision.evidence.get(
                    "applied_correction_ids", []
                )
            )
        failures = [i for i, correct in enumerate(baseline) if not correct]

        def recurrence(stage):
            return (
                sum(not stages[str(stage)][i] for i in failures) / len(failures)
                if failures
                else None
            )

        report = {
            "case_count": len(cases),
            "baseline_failures": len(failures),
            "exact_repeat_recurrence": recurrence(1),
            "paraphrase_recurrence": recurrence(2),
            "restart_recurrence": recurrence(3),
            "recovery_rate": 1 - recurrence(3) if failures else None,
            "retrieval_precision": retrieval_tp / (retrieval_tp + retrieval_fp)
            if retrieval_tp + retrieval_fp
            else (1.0 if expected_retrieval_total == 0 else 0.0),
            "retrieval_recall": retrieval_tp / (retrieval_tp + retrieval_fn)
            if retrieval_tp + retrieval_fn
            else (1.0 if expected_retrieval_total == 0 else 0.0),
            "false_correction_application_rate": false_applied / len(unrelated)
            if unrelated
            else None,
            "unrelated_success_count": unrelated_correct,
            "unrelated_sample_count": len(unrelated),
            "latency_ms": latencies,
            "baseline_latency_ms": latencies[: len(cases)],
            "rss_growth_bytes": psutil.Process().memory_info().rss - rss_before,
            "sessions": stages,
            "status": "MEASURED",
            "scope": "Supplied independent development cases only; not population-quality evidence",
        }
        runtime.close()
        return report
