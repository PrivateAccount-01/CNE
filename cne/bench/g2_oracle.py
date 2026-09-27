"""
CNE Gate G2 Benchmark Runner.
Executes the G2 Oracle over the evaluation partition with strict train/test separation.
Computes recoverable computation bound R*.
"""
from __future__ import annotations
from typing import Any, Dict, List
from cne.bench.corpus.corpus_generator import CorpusGenerator
from cne.compiler.fixture_compiler import FixtureCompiler
from cne.optimizer.oracle import G2Oracle, OracleResult


class GateG2Runner:
    @classmethod
    def run_g2(cls) -> Dict[str, Any]:
        corpus = CorpusGenerator.generate_corpus()
        queries = corpus["queries"]

        # Train / Evaluation split (50/50 partition)
        n = len(queries)
        train_queries = queries[:n // 2]
        eval_queries = queries[n // 2:]

        train_ids = {q["id"] for q in train_queries}
        eval_ids = {q["id"] for q in eval_queries}

        # Assert zero contamination
        assert train_ids.isdisjoint(eval_ids), "Contamination detected between train and eval splits!"

        oracle = G2Oracle()
        results: List[OracleResult] = []

        # Synthetic test environment
        test_env = {
            "transactions": [
                {"id": f"tx_{k}", "category": "Food" if k % 2 == 0 else "Travel", "amount": 25.0 * (k % 8 + 1), "is_transfer": (k % 7 == 0)}
                for k in range(100)
            ],
            "telemetry": {
                f"node_{k}": {"system_id": f"node_{k}", "error_count": k % 10}
                for k in range(1, 21)
            },
            "diagnostic_evidence": {
                f"node_{k}": "log: out_of_memory in process" if k % 3 == 0 else "system normal"
                for k in range(1, 21)
            }
        }

        total_baseline_cost = 0.0
        total_optimal_cost = 0.0

        for q in eval_queries:
            graph, contract = FixtureCompiler.compile_query(q)
            ores = oracle.find_recoverable_bound(
                query_id=q["id"],
                graph=graph,
                contract=contract,
                env=test_env,
                train_corpus_ids=train_ids
            )
            results.append(ores)
            total_baseline_cost += ores.baseline_cost
            total_optimal_cost += ores.optimal_cost

        # Corpus-level recoverable mass R*
        corpus_r_star = max(0.0, (total_baseline_cost - total_optimal_cost) / total_baseline_cost) if total_baseline_cost > 0 else 0.0
        all_contracts_satisfied = all(r.contract_satisfied for r in results)

        # Gate G2 specification: R* >= 0.25 provisional floor (system.md §20 & §61)
        r_star_threshold = 0.25
        passed = all_contracts_satisfied and len(results) == len(eval_queries) and (corpus_r_star >= r_star_threshold)

        return {
            "gate": "G2",
            "passed": passed,
            "total_eval_queries": len(eval_queries),
            "train_eval_disjoint": True,
            "all_contracts_satisfied": all_contracts_satisfied,
            "corpus_baseline_cost_ns": total_baseline_cost,
            "corpus_optimal_cost_ns": total_optimal_cost,
            "corpus_r_star": round(corpus_r_star, 4),
            "r_star_threshold": r_star_threshold,
            "sample_results": [
                {
                    "query_id": r.query_id,
                    "baseline_cost_ns": r.baseline_cost,
                    "optimal_cost_ns": r.optimal_cost,
                    "r_star": round(r.recoverable_ratio, 4),
                    "intervention": r.optimal_intervention_desc
                }
                for r in results[:5]
            ]
        }


if __name__ == "__main__":
    res = GateG2Runner.run_g2()
    print("G2 Result:", res)
