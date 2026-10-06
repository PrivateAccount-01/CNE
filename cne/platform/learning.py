"""Executed regression evaluation and transactional adapter metadata; no training or RL."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from cne.platform.memory import (
    ExperienceRecord,
    ExperienceState,
    RedactionPolicy,
    request_fingerprint,
)


@dataclass(frozen=True)
class AdaptationCandidate:
    adapter_id: str
    version: str
    capability_id: str
    target_model_id: str
    training_sample_count: int
    created_at: float = field(default_factory=time.time)
    artifact_path: str | None = None
    artifact_sha256: str | None = None


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    inputs: object
    expected: object


@dataclass(frozen=True)
class RegressionEvaluationResult:
    candidate_id: str
    historical_error_recovery_rate: float | None
    repeated_error_recurrence_rate: float | None
    unrelated_task_regression_pp: float | None
    new_permission_violations: int
    new_unsafe_state_reuses: int
    passed: bool
    sample_counts: dict
    success_counts: dict
    failure_ids: dict
    confidence_intervals: dict
    metric_definitions: dict
    dataset_hashes: dict
    candidate_version: str
    baseline_version: str
    evaluation_timestamp: float
    candidate_identity: str

    def artifact_hash(self):
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()


def candidate_identity(candidate):
    return hashlib.sha256(
        json.dumps(asdict(candidate), sort_keys=True).encode()
    ).hexdigest()


class CandidateEvaluator:
    REQUIRED = (
        "HistoricalErrorSet",
        "UnrelatedRegressionSet",
        "SecurityRegressionSet",
        "CacheSafetyRegressionSet",
        "CapabilitySpecificValidationSet",
    )

    def __init__(self, datasets):
        if set(datasets) != set(self.REQUIRED):
            raise ValueError("All five evaluation sets required")
        self.datasets = {k: tuple(v) for k, v in datasets.items()}
        self._artifacts = {}

    def evaluate(self, candidate, candidate_fn, baseline_fn, baseline_version):
        counts, successes, failures, hashes, intervals, baseline_success = (
            {},
            {},
            {},
            {},
            {},
            {},
        )
        new_failures = {}
        for name, cases in self.datasets.items():
            if len({c.id for c in cases}) != len(cases):
                raise ValueError("Duplicate evaluation ID")
            counts[name] = len(cases)
            successes[name] = 0
            baseline_success[name] = 0
            failures[name] = []
            new_failures[name] = 0
            hashes[name] = hashlib.sha256(
                json.dumps([asdict(c) for c in cases], sort_keys=True).encode()
            ).hexdigest()
            for case in cases:
                # Each evaluator runs independent copies, preventing candidate mutation of gold/baseline input.
                try:
                    actual = (
                        candidate_fn(json.loads(json.dumps(case.inputs)))
                        == case.expected
                    )
                except Exception:
                    actual = False
                try:
                    baseline = (
                        baseline_fn(json.loads(json.dumps(case.inputs)))
                        == case.expected
                    )
                except Exception:
                    baseline = False
                successes[name] += int(actual)
                baseline_success[name] += int(baseline)
                if not actual:
                    failures[name].append(case.id)
                new_failures[name] += int(baseline and not actual)
            n = counts[name]
            if n:
                p = successes[name] / n
                z = 1.96
                den = 1 + z * z / n
                center = (p + z * z / (2 * n)) / den
                radius = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
                intervals[name] = [center - radius, center + radius]
            else:
                intervals[name] = None
        h, u = "HistoricalErrorSet", "UnrelatedRegressionSet"
        recovery = successes[h] / counts[h] if counts[h] else None
        repeat_name = "RepeatedHistoricalErrorSet"
        counts[repeat_name] = counts[h]
        successes[repeat_name] = 0
        failures[repeat_name] = []
        hashes[repeat_name] = hashes[h]
        for case in self.datasets[h]:
            try:
                correct = (
                    candidate_fn(json.loads(json.dumps(case.inputs))) == case.expected
                )
            except Exception:
                correct = False
            successes[repeat_name] += int(correct)
            if not correct:
                failures[repeat_name].append(case.id)
        recurrence = (
            len(failures[repeat_name]) / counts[repeat_name]
            if counts[repeat_name]
            else None
        )
        regression = (
            100 * (baseline_success[u] - successes[u]) / counts[u]
            if counts[u]
            else None
        )
        permissions = new_failures["SecurityRegressionSet"]
        cache = new_failures["CacheSafetyRegressionSet"]
        passed = (
            all(counts.values())
            and recovery >= 0.8
            and recurrence < 0.1
            and regression < 2
            and permissions == 0
            and cache == 0
            and not failures["CapabilitySpecificValidationSet"]
            and not failures["SecurityRegressionSet"]
            and not failures["CacheSafetyRegressionSet"]
        )
        result = RegressionEvaluationResult(
            candidate.adapter_id,
            recovery,
            recurrence,
            regression,
            permissions,
            cache,
            bool(passed),
            counts,
            successes,
            failures,
            intervals,
            {
                "success": "actual equals independently stored expected output",
                "recurrence": "failures on a second execution of historical requests / repeated request count",
                "unrelated_regression_pp": "100 * (baseline success - candidate success) / sample count",
            },
            hashes,
            candidate.version,
            baseline_version,
            time.time(),
            candidate_identity(candidate),
        )
        self._artifacts[result.artifact_hash()] = result
        return result


class LearningReplayStore:
    def __init__(self, max_capacity=5000, retention_s=30 * 86400):
        self.max_capacity = max_capacity
        self.retention_s = retention_s
        self._records = {}
        self._admitted = set()

    def admit(self, exp, audit_evidence, verification_evidence, privacy_approved=False):
        if (
            not audit_evidence
            or not verification_evidence
            or not privacy_approved
            or not exp.contract_satisfied
        ):
            raise ValueError(
                "Replay admission requires audit, verification and privacy approval"
            )
        if exp.query_text or exp.slot_values:
            raise ValueError(
                "Raw query and private slots must be removed before training admission"
            )
        exp.state = ExperienceState.TRAINING_ELIGIBLE
        self._admitted.add(id(exp))
        self.add_experience(exp)

    def add_experience(self, exp):
        if id(exp) not in self._admitted:
            raise ValueError("Admission process required")
        self._admitted.discard(id(exp))
        if exp.state != ExperienceState.TRAINING_ELIGIBLE:
            raise ValueError("Only TRAINING_ELIGIBLE records admitted")
        if exp.query_text or exp.slot_values:
            raise ValueError("Private values not admitted")
        now = time.time()
        self._records = {
            k: v
            for k, v in self._records.items()
            if now - v.timestamp < self.retention_s
        }
        if now - exp.timestamp >= self.retention_s:
            raise ValueError("EXPIRED")
        key = (exp.user_id, exp.input_fingerprint, exp.semantic_dsl, exp.outcome)
        if not exp.input_fingerprint:
            raise ValueError("Fingerprint required")
        import copy

        self._records[key] = copy.deepcopy(exp)
        while len(self._records) > self.max_capacity:
            del self._records[
                min(self._records, key=lambda k: self._records[k].timestamp)
            ]

    def sample_batch(self, capability_id, limit=100, user_id="default_user"):
        eligible = [
            e
            for e in self._records.values()
            if e.user_id == user_id
            and capability_id in e.capability_ids
            and e.state == ExperienceState.TRAINING_ELIGIBLE
            and time.time() - e.timestamp < self.retention_s
        ]
        # Round robin across outcomes, oldest first within a bucket preserves historical replay.
        buckets = {}
        for e in sorted(eligible, key=lambda e: e.timestamp):
            buckets.setdefault(e.outcome, []).append(e)
        out = []
        while buckets and len(out) < limit:
            for key in list(sorted(buckets)):
                if len(out) >= limit:
                    break
                out.append(buckets[key].pop(0))
                if not buckets[key]:
                    del buckets[key]
        return out

    def delete_user(self, user_id):
        self._records = {k: v for k, v in self._records.items() if v.user_id != user_id}

    @property
    def total_records(self):
        return len(self._records)


class GatedAdaptationPipeline:
    def __init__(self, replay_store=None, evaluator=None, database_path=":memory:"):
        self.replay_store = replay_store or LearningReplayStore()
        self.evaluator = evaluator
        self.db = sqlite3.connect(database_path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS adapters (capability TEXT PRIMARY KEY, active TEXT, previous TEXT, candidate TEXT, activated REAL, artifact TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS evaluations (hash TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.db.commit()

    def evaluate_candidate(
        self, candidate, candidate_fn, baseline_fn, baseline_version
    ):
        if self.evaluator is None:
            raise ValueError("CandidateEvaluator required")
        return self.evaluator.evaluate(
            candidate, candidate_fn, baseline_fn, baseline_version
        )

    def deploy_candidate(self, candidate, eval_result):
        if (
            self.evaluator is None
            or not eval_result.passed
            or eval_result.candidate_identity != candidate_identity(candidate)
            or self.evaluator._artifacts.get(eval_result.artifact_hash()) != eval_result
        ):
            return False
        payload = json.dumps(asdict(candidate))
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO evaluations VALUES (?,?)",
                (
                    eval_result.artifact_hash(),
                    json.dumps(asdict(eval_result), sort_keys=True),
                ),
            )
            self.db.execute(
                "INSERT INTO adapters VALUES (?,?,NULL,?,?,?) ON CONFLICT(capability) DO UPDATE SET previous=adapters.active,active=excluded.active,candidate=excluded.candidate,activated=excluded.activated,artifact=excluded.artifact",
                (
                    candidate.capability_id,
                    payload,
                    payload,
                    time.time(),
                    eval_result.artifact_hash(),
                ),
            )
        return True

    def get_active(self, capability_id):
        row = self.db.execute(
            "SELECT active FROM adapters WHERE capability=?", (capability_id,)
        ).fetchone()
        return AdaptationCandidate(**json.loads(row[0])) if row else None

    def rollback_adapter(self, capability_id):
        with self.db:
            row = self.db.execute(
                "SELECT previous FROM adapters WHERE capability=?", (capability_id,)
            ).fetchone()
            if not row or row[0] is None:
                return None
            self.db.execute(
                "UPDATE adapters SET active=previous,previous=active,activated=? WHERE capability=?",
                (time.time(), capability_id),
            )
        return self.get_active(capability_id)
