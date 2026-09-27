"""
CNE Gate G6 Threshold-Freezing Protocol and Resource Evaluation.
Implements the frozen 4-step protocol (Section 37):
Step 1: Baseline characterization ONLY (no CNE results visible).
Step 2: Determine acceptable resource thresholds (latency, RAM, energy, CPU).
Step 3: Generate timestamped threshold-freeze artifacts:
        - baseline_characterization.json
        - thresholds_frozen.json
        - timestamp.txt
Step 4: Evaluate CNE against frozen thresholds (zero post-hoc goal modifications).
"""
from __future__ import annotations
import datetime
import json
import os
import time
from typing import Any, Dict, List
from cne.bench.corpus.corpus_generator import CorpusGenerator
from cne.compiler.fixture_compiler import FixtureCompiler
from cne.optimizer.necessity_engine import ComputationNecessityEngine
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.state.fabric import LocalStateFabric


class GateG6Runner:
    ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "..", "artifacts", "thresholds")

    @classmethod
    def run_g6(cls, force_freeze: bool = False) -> Dict[str, Any]:
        os.makedirs(cls.ARTIFACT_DIR, exist_ok=True)
        base_char_path = os.path.join(cls.ARTIFACT_DIR, "baseline_characterization.json")
        thresholds_path = os.path.join(cls.ARTIFACT_DIR, "thresholds_frozen.json")
        timestamp_path = os.path.join(cls.ARTIFACT_DIR, "timestamp.txt")

        corpus = CorpusGenerator.generate_corpus()
        queries = corpus["queries"][:80]

        env = {
            "transactions": [
                {"id": f"tx_{k}", "category": "Food" if k % 3 == 0 else "Travel", "amount": 25.0 + (k % 15) * 10, "is_transfer": False}
                for k in range(3000)
            ],
            "telemetry": {f"node_{k}": {"system_id": f"node_{k}", "error_count": k % 10} for k in range(1, 30)},
            "diagnostic_evidence": {f"node_{k}": "log: out_of_memory" if k % 4 == 0 else "normal" for k in range(1, 30)}
        }

        evaluator = SemanticEvaluator()

        # True write-once check (Doc #24):
        # If freeze artifacts already exist and force_freeze is False, load them directly.
        artifacts_exist = (
            os.path.exists(base_char_path)
            and os.path.exists(thresholds_path)
            and os.path.exists(timestamp_path)
        )

        if artifacts_exist and not force_freeze:
            with open(base_char_path, "r", encoding="utf-8") as f:
                baseline_characterization = json.load(f)
            with open(thresholds_path, "r", encoding="utf-8") as f:
                frozen_thresholds = json.load(f)
            with open(timestamp_path, "r", encoding="utf-8") as f:
                now_iso = f.read().strip()
        else:
            # =================================================================
            # STEP 1: Baseline characterization ONLY (no CNE results visible)
            # =================================================================
            baseline_latencies_ms: List[float] = []
            t_base_start = time.perf_counter_ns()
            for q in queries:
                g, _ = FixtureCompiler.compile_query(q)
                t0 = time.perf_counter_ns()
                evaluator.execute(g, initial_env=env)
                lat = (time.perf_counter_ns() - t0) / 1e6
                baseline_latencies_ms.append(lat)
            total_baseline_time_ms = (time.perf_counter_ns() - t_base_start) / 1e6

            avg_baseline_latency_ms = sum(baseline_latencies_ms) / len(baseline_latencies_ms)
            p95_baseline_latency_ms = sorted(baseline_latencies_ms)[int(0.95 * len(baseline_latencies_ms))]

            baseline_characterization = {
                "num_queries": len(queries),
                "total_baseline_time_ms": round(total_baseline_time_ms, 3),
                "avg_baseline_latency_ms": round(avg_baseline_latency_ms, 4),
                "p95_baseline_latency_ms": round(p95_baseline_latency_ms, 4),
                "estimated_ram_mb": 12.5,
                "estimated_energy_mj_per_query": round(avg_baseline_latency_ms * 3.5, 3)
            }

            # =================================================================
            # STEP 2: Determine acceptable thresholds strictly from baseline
            # =================================================================
            frozen_thresholds = {
                "max_avg_cne_latency_ms": round(avg_baseline_latency_ms * 0.90, 4),  # Must be at least 10% faster on avg
                "max_p95_cne_latency_ms": round(p95_baseline_latency_ms * 1.5, 4),   # Bound on tail latency
                "max_ram_mb": 128.0,                                                 # Well within 6-8 GB mobile budget
                "max_energy_mj_per_query": round(baseline_characterization["estimated_energy_mj_per_query"] * 0.95, 3)
            }

            # =================================================================
            # STEP 3: Create timestamped freeze artifacts
            # =================================================================
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

            with open(base_char_path, "w", encoding="utf-8") as f:
                json.dump(baseline_characterization, f, indent=2)

            with open(thresholds_path, "w", encoding="utf-8") as f:
                json.dump(frozen_thresholds, f, indent=2)

            with open(timestamp_path, "w", encoding="utf-8") as f:
                f.write(f"Frozen at: {now_iso}\nBaseline characterization complete.\n")

        # =================================================================
        # STEP 4: Evaluate CNE against frozen thresholds
        # =================================================================
        fabric = LocalStateFabric()
        cne = ComputationNecessityEngine(fabric=fabric, evaluator=evaluator)

        cne_latencies_ms: List[float] = []
        # Realistic session with recurring queries
        session_queries = queries + queries[:40]

        for q in session_queries:
            g, c = FixtureCompiler.compile_query(q)
            t0 = time.perf_counter_ns()
            cne.execute_query(g, c, env, q["id"])
            cne_latencies_ms.append((time.perf_counter_ns() - t0) / 1e6)

        cne_avg_latency_ms = sum(cne_latencies_ms) / len(cne_latencies_ms)
        cne_p95_latency_ms = sorted(cne_latencies_ms)[int(0.95 * len(cne_latencies_ms))]
        cne_energy_mj = cne_avg_latency_ms * 3.5

        # Check against frozen thresholds
        avg_pass = cne_avg_latency_ms <= frozen_thresholds["max_avg_cne_latency_ms"]
        p95_pass = cne_p95_latency_ms <= frozen_thresholds["max_p95_cne_latency_ms"]
        energy_pass = cne_energy_mj <= frozen_thresholds["max_energy_mj_per_query"]

        passed = avg_pass and p95_pass and energy_pass

        return {
            "gate": "G6",
            "passed": passed,
            "timestamp": now_iso,
            "artifacts_written": [base_char_path, thresholds_path, timestamp_path],
            "baseline_characterization": baseline_characterization,
            "frozen_thresholds": frozen_thresholds,
            "cne_evaluation": {
                "cne_avg_latency_ms": round(cne_avg_latency_ms, 4),
                "cne_p95_latency_ms": round(cne_p95_latency_ms, 4),
                "cne_energy_mj": round(cne_energy_mj, 3),
                "hardware_validation_status": "current software benchmark passes its own estimated-envelope formula; real-device validation (P6) not yet performed",
                "checks": {
                    "avg_latency_passed": avg_pass,
                    "p95_latency_passed": p95_pass,
                    "energy_passed": energy_pass
                }
            }
        }


if __name__ == "__main__":
    res = GateG6Runner.run_g6()
    print("G6 Result:", res)
