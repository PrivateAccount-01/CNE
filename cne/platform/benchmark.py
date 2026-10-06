"""Independent labeled metrics. Missing observations never become passing scores."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import time
from cne.platform.dsl import SemanticDSLParser
from cne.platform.models import ModelResult
from pathlib import Path
import json
import threading
import psutil


class ProcessMemorySampler:
    """Sampled process peaks, not model allocation or Android measurements."""

    def __init__(self, interval_s=0.005):
        self.interval_s = interval_s
        self.rss = []
        self.pss = []
        self.stop = threading.Event()

    def sample(self):
        proc = psutil.Process()
        self.rss.append(proc.memory_info().rss / 1048576)
        try:
            pss = getattr(proc.memory_full_info(), "pss", None)
            if pss is not None:
                self.pss.append(pss / 1048576)
        except psutil.AccessDenied:
            pass

    def run(self):
        while not self.stop.wait(self.interval_s):
            self.sample()

    def __enter__(self):
        self.sample()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join()
        self.sample()


@dataclass
class Metric:
    numerator: int = 0
    denominator: int = 0
    status: str = "NOT_APPLICABLE"

    @property
    def value(self):
        return self.numerator / self.denominator if self.denominator else None

    def observe(self, success):
        self.denominator += 1
        self.numerator += int(success)
        self.status = "MEASURED"

    def to_dict(self):
        return {**asdict(self), "value": self.value}


@dataclass
class CandidateBenchmarkMetrics:
    candidate_name: str
    parameter_class: str
    model_size_mb: float | None
    metrics: dict
    avg_latency_ms: float | None
    ttft_ms: float | None = None
    peak_ram_mb: float | None = None
    tokens_per_second: float | None = None
    passed_all_gates: bool = False
    provenance: dict = field(default_factory=dict)

    def __getattr__(self, name):
        if name in self.metrics:
            return self.metrics[name].value
        raise AttributeError(name)

    def to_dict(self):
        out = asdict(self)
        out["metrics"] = {k: v.to_dict() for k, v in self.metrics.items()}
        return out


class ModelSelectionHarness:
    def __init__(self, quality_thresholds=None):
        self.quality_thresholds = quality_thresholds or {
            "routing_accuracy": 0.95,
            "intent_accuracy": 0.95,
            "oos_rejection_rate": 0.95,
            "ambiguity_accuracy": 0.95,
            "slot_exact_match_rate": 0.9,
            "dsl_validity_rate": 0.99,
            "semantic_validity_rate": 0.95,
            "contract_correctness": 0.95,
            "post_execution_correctness": 0.95,
            "in_scope_coverage": 0.6,
            "primitive_adherence": 1.0,
        }

    def evaluate_candidate(self, descriptor, inference_fn, eval_cases):
        metrics = {
            k: Metric()
            for k in (
                "routing_accuracy",
                "intent_accuracy",
                "oos_rejection_rate",
                "ambiguity_accuracy",
                "slot_exact_match_rate",
                "dsl_validity_rate",
                "semantic_validity_rate",
                "contract_correctness",
                "post_execution_correctness",
                "in_scope_coverage",
                "primitive_adherence",
            )
        }
        latencies = []
        ttfts = []
        runtime_results = []
        peaks = []
        pss_peaks = []
        memory_samples = 0
        for case in eval_cases:
            start = time.perf_counter()
            with ProcessMemorySampler() as sampler:
                try:
                    raw = inference_fn(case["query"])
                except Exception as exc:
                    raw = {"error": type(exc).__name__}
            latencies.append((time.perf_counter() - start) * 1000)
            peaks.extend(sampler.rss)
            pss_peaks.extend(sampler.pss)
            memory_samples += len(sampler.rss)
            if isinstance(raw, ModelResult):
                runtime_results.append(raw)
                if raw.metadata.get("ttft_ms") is not None:
                    ttfts.append(raw.metadata["ttft_ms"])
                try:
                    raw = (
                        json.loads(raw.outputs)
                        if isinstance(raw.outputs, str)
                        else raw.outputs
                    )
                except (ValueError, TypeError):
                    raw = {"semantic_dsl": raw.outputs}
            actual = raw if isinstance(raw, dict) else {"semantic_dsl": raw}
            for expected_key, actual_key, metric in [
                (
                    "expected_capabilities",
                    "selected_capability_ids",
                    "routing_accuracy",
                ),
                ("expected_intent", "intent", "intent_accuracy"),
                ("expected_slots", "extracted_slots", "slot_exact_match_rate"),
            ]:
                if expected_key in case:
                    expected = case[expected_key]
                    observed = actual.get(actual_key)
                    if expected_key == "expected_capabilities":
                        expected = sorted(expected)
                        observed = sorted(observed) if observed is not None else None
                    metrics[metric].observe(observed == expected)
            if case.get("is_oos"):
                metrics["oos_rejection_rate"].observe(
                    actual.get("outcome") == "UNSUPPORTED_INTENT"
                )
            if case.get("is_ambiguous"):
                metrics["ambiguity_accuracy"].observe(
                    actual.get("outcome") == "AMBIGUOUS_INTENT"
                )
            if not case.get("is_oos") and not case.get("is_ambiguous"):
                metrics["in_scope_coverage"].observe(
                    actual.get("outcome") == "COMPILED"
                )
                result = SemanticDSLParser.compile_dsl(actual.get("semantic_dsl") or "")
                metrics["dsl_validity_rate"].observe(result.is_valid)
                metrics["primitive_adherence"].observe(result.is_valid)
                # Semantic/contract/task checks must be independently supplied test oracles,
                # not self-reported fields from the model under evaluation.
                for name, checker in [
                    ("semantic_validity_rate", "semantic_check"),
                    ("contract_correctness", "contract_check"),
                    ("post_execution_correctness", "execute_and_check"),
                ]:
                    if checker in case:
                        try:
                            correct = (
                                bool(case[checker](result))
                                if result.is_valid
                                else False
                            )
                        except Exception:
                            correct = False
                        metrics[name].observe(correct)
        for name in (
            "semantic_validity_rate",
            "contract_correctness",
            "post_execution_correctness",
        ):
            if eval_cases and metrics[name].denominator == 0:
                metrics[name].status = "NOT_MEASURED"
        size = (
            Path(descriptor.asset_path).stat().st_size / 1048576
            if descriptor.asset_path and Path(descriptor.asset_path).is_file()
            else None
        )
        token_counts = [
            r.tokens_generated
            for r in runtime_results
            if r.tokens_generated is not None
        ]
        inference_seconds = sum(r.latency_ms for r in runtime_results) / 1000
        tps = (
            sum(token_counts) / inference_seconds
            if token_counts
            and len(token_counts) == len(runtime_results)
            and inference_seconds > 0
            else None
        )
        quality = all(
            metrics[k].value is not None and metrics[k].value >= threshold
            for k, threshold in self.quality_thresholds.items()
        )
        runtime_complete = (
            bool(eval_cases)
            and len(runtime_results) == len(eval_cases)
            and len(ttfts) == len(eval_cases)
            and size is not None
        )
        passed = (
            quality
            and runtime_complete
            and max(peaks, default=float("inf")) <= 1536
            and max(latencies, default=float("inf")) <= 15000
        )
        return CandidateBenchmarkMetrics(
            descriptor.model_id,
            f"~{descriptor.parameter_count_m:g}M",
            size,
            metrics,
            sum(latencies) / len(latencies) if latencies else None,
            ttft_ms=sum(ttfts) / len(ttfts) if ttfts else None,
            peak_ram_mb=max(peaks) if peaks else None,
            tokens_per_second=tps,
            passed_all_gates=bool(passed),
            provenance={
                "latency": {
                    "source": "perf_counter around callback and memory sampler; not necessarily model inference",
                    "samples": len(latencies),
                },
                "TTFT": {
                    "source": "runtime first generated token"
                    if ttfts
                    else "NOT_MEASURED",
                    "samples": len(ttfts),
                },
                "peak_RSS": {
                    "source": "psutil sampled process RSS",
                    "samples": memory_samples,
                    "sampling_interval_s": 0.005,
                },
                "peak_PSS": {
                    "value": max(pss_peaks) if pss_peaks else None,
                    "status": "MEASURED" if pss_peaks else "NOT_MEASURED",
                    "samples": len(pss_peaks),
                },
                "model_file_size": "filesystem stat"
                if size is not None
                else "NOT_MEASURED",
                "tokens_per_second": "runtime generated token count / runtime inference seconds"
                if tps is not None
                else "NOT_MEASURED",
                "gate_status": "PASSED" if passed else "FAILED_OR_NOT_MEASURED",
            },
        )

    def select_smallest_admissible_model(self, candidate_results):
        qualified = [
            r
            for r in candidate_results
            if r.passed_all_gates and r.model_size_mb is not None
        ]
        return min(qualified, key=lambda r: r.model_size_mb) if qualified else None
