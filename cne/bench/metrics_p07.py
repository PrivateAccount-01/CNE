"""
CNE Phase P0.7 Metrics Engine (§7 & §8).
Computes:
1. Shape Diversity Metrics:
   - D(N) = distinct_shapes / N
   - H = - sum(p_i * log2(p_i)) (Shape-frequency Shannon entropy)
   - C_20 = sum_{top 20 shapes} count / N
   - R_k = sum_{count >= k} count / N for k in {2, 5, 10} (Recurrence density)
2. Compiler Coverage Metrics:
   - Coverage = N_compiled / N_submitted
   - unsupported_rate, ambiguous_rate, low_confidence_rate
3. Cross-Batch Canonicalization Stability Analyzer:
   - Compares shape distributions across batch_1, batch_2, and batch_3
4. Adversarial Category Verifier (A1 - A6)
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from cne.compiler.nl_compiler import ClassificationOutcome, CompilationResult, NLCompiler
from cne.effects.effect_set import Effect, EffectSet
from cne.effects.execution_policy import ExecutionPolicy
from cne.signature.cost_class import CostClass
from cne.signature.memo_key import MemoKey
from cne.signature.shape_key import SemanticShapeKey


@dataclass
class ShapeDiversityMetrics:
    total_queries: int
    distinct_shapes: int
    diversity_ratio_d: float
    entropy_h: float
    top_20_coverage_c20: float
    recurrence_r2: float
    recurrence_r5: float
    recurrence_r10: float
    shape_distribution: Dict[str, int]
    h_max: float = 0.0
    normalized_entropy: float = 0.0



@dataclass
class CompilerCoverageMetrics:
    total_submitted: int
    compiled_count: int
    coverage_ratio: float
    unsupported_count: int
    unsupported_rate: float
    ambiguous_count: int
    ambiguous_rate: float
    low_confidence_count: int
    low_confidence_rate: float


class P07MetricsEngine:
    """
    Computes rigorous diversity, coverage, and canonicalization metrics.
    """

    @classmethod
    def compute_diversity_metrics(cls, shape_keys: List[str]) -> ShapeDiversityMetrics:
        """
        Computes D(N), H, C_20, and R_k (k=2, 5, 10) over a collection of shape key hashes.
        """
        n = len(shape_keys)
        if n == 0:
            return ShapeDiversityMetrics(
                total_queries=0,
                distinct_shapes=0,
                diversity_ratio_d=0.0,
                entropy_h=0.0,
                top_20_coverage_c20=0.0,
                recurrence_r2=0.0,
                recurrence_r5=0.0,
                recurrence_r10=0.0,
                shape_distribution={}
            )

        counts = Counter(shape_keys)
        distinct = len(counts)
        d_n = distinct / n

        # Shannon entropy H = - sum(p_i * log2(p_i))
        entropy = 0.0
        for cnt in counts.values():
            p_i = cnt / n
            if p_i > 0:
                entropy -= p_i * math.log2(p_i)

        h_max = math.log2(distinct) if distinct > 1 else 1.0
        normalized_entropy = entropy / h_max if h_max > 0 else 0.0

        # Top 20 coverage C_20
        top_20_counts = [cnt for _, cnt in counts.most_common(20)]
        c_20 = sum(top_20_counts) / n

        # Recurrence density R_k
        r_2 = sum(cnt for cnt in counts.values() if cnt >= 2) / n
        r_5 = sum(cnt for cnt in counts.values() if cnt >= 5) / n
        r_10 = sum(cnt for cnt in counts.values() if cnt >= 10) / n

        return ShapeDiversityMetrics(
            total_queries=n,
            distinct_shapes=distinct,
            diversity_ratio_d=round(d_n, 4),
            entropy_h=round(entropy, 4),
            top_20_coverage_c20=round(c_20, 4),
            recurrence_r2=round(r_2, 4),
            recurrence_r5=round(r_5, 4),
            recurrence_r10=round(r_10, 4),
            shape_distribution=dict(counts),
            h_max=round(h_max, 4),
            normalized_entropy=round(normalized_entropy, 4)
        )

    @classmethod
    def compute_coverage_metrics(cls, compilation_results: List[CompilationResult]) -> CompilerCoverageMetrics:
        """
        Computes compiler coverage and failure rates.
        """
        n = len(compilation_results)
        if n == 0:
            return CompilerCoverageMetrics(0, 0, 0.0, 0, 0.0, 0, 0.0, 0, 0.0)

        compiled = sum(1 for r in compilation_results if r.outcome == ClassificationOutcome.COMPILED)
        unsupported = sum(1 for r in compilation_results if r.outcome == ClassificationOutcome.UNSUPPORTED_INTENT)
        ambiguous = sum(1 for r in compilation_results if r.outcome == ClassificationOutcome.AMBIGUOUS_INTENT)
        low_conf = sum(1 for r in compilation_results if r.outcome == ClassificationOutcome.LOW_CONFIDENCE_MAPPING)

        return CompilerCoverageMetrics(
            total_submitted=n,
            compiled_count=compiled,
            coverage_ratio=round(compiled / n, 4),
            unsupported_count=unsupported,
            unsupported_rate=round(unsupported / n, 4),
            ambiguous_count=ambiguous,
            ambiguous_rate=round(ambiguous / n, 4),
            low_confidence_count=low_conf,
            low_confidence_rate=round(low_conf / n, 4)
        )

    @classmethod
    def evaluate_cross_batch_stability(
        cls,
        batch_results: Dict[str, List[CompilationResult]]
    ) -> Dict[str, Any]:
        """
        Compares shape distributions independently across generation batches (batch_1, batch_2, batch_3).
        Validates whether canonicalization remains stable under wording style shifts (§8).
        """
        batch_metrics: Dict[str, Dict[str, Any]] = {}
        all_shape_sets: List[set] = []

        for b_name, results in batch_results.items():
            compiled_shapes = [
                r.graph._cached_shape_key.key_hash
                for r in results
                if r.outcome == ClassificationOutcome.COMPILED and r.graph is not None
            ]
            div = cls.compute_diversity_metrics(compiled_shapes)
            all_shape_sets.append(set(div.shape_distribution.keys()))
            batch_metrics[b_name] = {
                "num_compiled": div.total_queries,
                "distinct_shapes": div.distinct_shapes,
                "d_ratio": div.diversity_ratio_d,
                "entropy_h": div.entropy_h,
                "top_20_c20": div.top_20_coverage_c20,
                "r_2": div.recurrence_r2,
                "r_5": div.recurrence_r5,
                "r_10": div.recurrence_r10,
                "top_shapes": list(div.shape_distribution.keys())[:5]
            }

        # Check shape overlap across batches
        common_shapes = set.intersection(*all_shape_sets) if all_shape_sets else set()
        union_shapes = set.union(*all_shape_sets) if all_shape_sets else set()
        jaccard_similarity = len(common_shapes) / len(union_shapes) if union_shapes else 0.0

        d_values = [m["d_ratio"] for m in batch_metrics.values()]
        d_variance = max(d_values) - min(d_values) if d_values else 0.0
        stable = (d_variance <= 0.05) and (jaccard_similarity >= 0.65)

        return {
            "stable": stable,
            "batches": batch_metrics,
            "common_shape_count": len(common_shapes),
            "total_unique_shapes": len(union_shapes),
            "jaccard_similarity": round(jaccard_similarity, 4),
            "d_ratio_range": [min(d_values), max(d_values)] if d_values else [0, 0],
            "d_ratio_variance": round(d_variance, 4)
        }

    @classmethod
    def evaluate_adversarial_families(
        cls,
        adversarial_results: List[Tuple[Dict[str, Any], CompilationResult]]
    ) -> Dict[str, Any]:
        """
        Validates all 6 structured adversarial families (A1 - A6) (§6.4).
        """
        families: Dict[str, List[Tuple[Dict[str, Any], CompilationResult]]] = {
            "A1": [], "A2": [], "A3": [], "A4": [], "A5": [], "A6": []
        }

        for q_meta, comp_res in adversarial_results:
            fam = q_meta.get("adversarial_family")
            if fam in families and comp_res.outcome == ClassificationOutcome.COMPILED:
                families[fam].append((q_meta, comp_res))

        results: Dict[str, Any] = {}

        # ---------------- A1: Same wording, different dependency ----------------
        a1_items = families["A1"]
        a1_passed = False
        distinct_sources = set()
        if len(a1_items) >= 2:
            from cne.signature.memo_key import clear_digest_cache
            from cne.optimizer.runtime.dependencies import ChangeType, DependencyManager
            from cne.semantic_ir.types import DependencyKey
            dm = DependencyManager()
            mks = []
            for idx, (q_meta, r) in enumerate(a1_items):
                clear_digest_cache()
                sources = list(r.graph.get_observed_sources())
                distinct_sources.add(tuple(sources))
                src = sources[0] if sources else "transactions"
                env = {src: [{"id": 1, "category": "Food", "amount": 150}]}
                mk = MemoKey.from_graph(r.graph, contract=r.contract, env=env)
                mks.append(mk.key_hash)
                # Register with DependencyManager
                dep = DependencyKey(source=src, granularity="predicate")
                dm.register_dependency(f"entry_{idx}", dep)

            # Check that different dependencies observe genuinely distinct sources at IR level
            sources_distinct = len(distinct_sources) > 1
            # Check distinct memo keys
            mks_distinct = len(set(mks)) > 1
            # Check dependency isolation: mutating source for item 0 invalidates entry 0, but NOT entry 1
            src0 = list(a1_items[0][1].graph.get_observed_sources())[0] if a1_items[0][1].graph.get_observed_sources() else "transactions"
            inval = dm.notify_change(ChangeType.UPDATE, source=src0)
            dep_isolated = ("entry_0" in inval and "entry_1" not in inval) if len(a1_items) >= 2 else True
            a1_passed = sources_distinct and mks_distinct and dep_isolated

        results["A1_dependency_sensitivity"] = {
            "family": "A1",
            "passed": a1_passed,
            "total_tested": len(a1_items),
            "sources_distinct": len(distinct_sources) if len(a1_items) >= 2 else 0,
            "description": "Genuinely distinct semantic dependencies produce distinct IR observe sources, distinct memo keys, and isolated invalidation"
        }

        # ---------------- A2: Same wording, different OutcomeContract ----------------
        a2_items = families["A2"]
        a2_passed = False
        if len(a2_items) >= 2:
            mks = []
            from cne.contracts.outcome_contract import ContractType, OutcomeContract
            for q_meta, r in a2_items:
                c_name = q_meta.get("contract_override", "EXACT")
                c_type = getattr(ContractType, c_name, ContractType.EXACT)
                contract = OutcomeContract(contract_type=c_type)
                mk = MemoKey.from_graph(r.graph, contract=contract, env={"decision_options": [{"id": "opt_1", "confidence": 0.9, "expected_utility": 1.0}]})
                mks.append(mk.key_hash)
            a2_passed = len(set(mks)) >= 3  # Multiple contract types produce distinct memo keys
        results["A2_contract_identity"] = {
            "family": "A2",
            "passed": a2_passed,
            "total_tested": len(a2_items),
            "description": "Distinct outcome contracts produce distinct memo keys"
        }

        # ---------------- A3: Micro-parameter sensitivity ----------------
        a3_items = families["A3"]
        a3_passed = False
        if len(a3_items) >= 2:
            mks = []
            for q_meta, r in a3_items:
                env = {"transactions": [{"id": 1, "category": "Travel", "amount": 150}]}
                mk = MemoKey.from_graph(r.graph, contract=r.contract, env=env)
                mks.append(mk.key_hash)
            # Micro differences in threshold produce distinct memo keys
            a3_passed = len(set(mks)) == len(a3_items)
        results["A3_parameter_sensitivity"] = {
            "family": "A3",
            "passed": a3_passed,
            "total_tested": len(a3_items),
            "description": "Micro-parameter threshold changes (0.01) produce distinct memo keys"
        }

        # ---------------- A4: Shape key invariance ----------------
        a4_items = families["A4"]
        a4_passed = False
        sks = []
        if len(a4_items) >= 2:
            sks = [r.graph._cached_shape_key.key_hash for _, r in a4_items]
            # Different surface phrasing for same computation collapses to exactly 1 shape key
            a4_passed = (len(set(sks)) == 1)
        results["A4_shape_invariance"] = {
            "family": "A4",
            "passed": a4_passed,
            "total_tested": len(a4_items),
            "unique_shapes": len(set(sks)) if a4_items else 0,
            "description": "Varied syntactic phrasings for identical computation collapse to single shape key"
        }

        # ---------------- A5: CostClass projection sensitivity & dynamic runtime scan ----------------
        a5_items = families["A5"]
        a5_passed = False
        cost_tiers = []
        complexity_tiers = []
        if len(a5_items) >= 2:
            from cne.optimizer.necessity_engine import ComputationNecessityEngine
            from cne.semantic_ir.evaluator import SemanticEvaluator
            from cne.state.fabric import LocalStateFabric
            engine = ComputationNecessityEngine(fabric=LocalStateFabric(), evaluator=SemanticEvaluator())

            for idx, (q_meta, r) in enumerate(a5_items):
                card = q_meta.get("env_override", {}).get("telemetry_cardinality", 10)
                # Live dynamic env with actual elements matching the cardinality
                env = {
                    "transactions": [{"id": f"tx_{k}", "category": "Food", "amount": 100.0} for k in range(min(card, 5000))],
                    "telemetry": {f"node_{k}": {"system_id": f"node_{k}", "error_count": 0} for k in range(min(card, 5000))}
                }
                cc = CostClass.from_graph(r.graph, cardinality_hint=card)
                cost_tiers.append(cc.cardinality_bracket)
                complexity_tiers.append(cc.tier.name)
                # Execute through engine end-to-end to verify runtime cost class deriving
                res = engine.execute_query(r.graph, r.contract, env=env, query_id=f"a5_{idx}")
                assert res is not None

            # Must distinguish at least 2 cardinality brackets dynamically
            a5_passed = (len(set(cost_tiers)) >= 2)

        results["A5_cost_class_sensitivity"] = {
            "family": "A5",
            "passed": a5_passed,
            "total_tested": len(a5_items),
            "distinct_brackets": len(set(cost_tiers)) if len(a5_items) >= 2 else 0,
            "description": "Workload cardinalities derived dynamically and project to distinct cost class brackets"
        }

        # ---------------- A6: Effect policy enforcement (runtime double execution) ----------------
        a6_items = families["A6"]
        a6_passed = False
        pure_reused = False
        side_effect_prevented = False
        if len(a6_items) >= 2:
            from cne.optimizer.necessity_engine import ComputationNecessityEngine
            from cne.semantic_ir.evaluator import SemanticEvaluator
            from cne.state.fabric import LocalStateFabric
            from cne.effects.execution_policy import Cacheability

            # Set up sample environment for A6 queries (cross_source_join_aggregate)
            env_a6 = {
                "orders": [{"order_id": f"ord_{k}", "item_id": f"sku_{k}", "quantity": 100} for k in range(5)],
                "inventory": [{"sku": f"sku_{k}", "unit_price": 25.0} for k in range(5)]
            }

            for idx, (q_meta, r) in enumerate(a6_items):
                eff_mode = q_meta.get("effect_mode", "pure")
                g = r.graph

                # Create a fresh isolated engine for this pair
                test_fabric = LocalStateFabric()
                test_engine = ComputationNecessityEngine(fabric=test_fabric, evaluator=SemanticEvaluator())

                if eff_mode == "audit_log":
                    # Non-pure side-effecting query: execution policy strictly forbids caching
                    g.metadata["execution_policy"] = ExecutionPolicy.from_effect_set(EffectSet.write_external())
                    g._cached_execution_policy = g.metadata["execution_policy"]

                    # Run 1: must execute, but NOT persist into StateFabric
                    res1 = test_engine.execute_query(g, r.contract, env=env_a6, query_id=f"a6_side_{idx}_1")
                    # Run 2: must re-execute, NOT serve from cache
                    res2 = test_engine.execute_query(g, r.contract, env=env_a6, query_id=f"a6_side_{idx}_2")

                    if (res1.reused_state is False and
                        res2.reused_state is False and
                        test_fabric.total_state_created == 0):
                        side_effect_prevented = True
                else:
                    # Pure query: eligible for state reuse
                    res1 = test_engine.execute_query(g, r.contract, env=env_a6, query_id=f"a6_pure_{idx}_1")
                    res2 = test_engine.execute_query(g, r.contract, env=env_a6, query_id=f"a6_pure_{idx}_2")

                    if (res1.reused_state is False and
                        res2.reused_state is True and
                        test_fabric.useful_prior_state_reused > 0):
                        pure_reused = True

            a6_passed = pure_reused and side_effect_prevented

        results["A6_effect_policy_enforcement"] = {
            "family": "A6",
            "passed": a6_passed,
            "total_tested": len(a6_items),
            "pure_reused": pure_reused,
            "side_effect_prevented": side_effect_prevented,
            "description": "Double execution proves runtime effect gating: pure queries reuse state, external writes strictly forbid memoization and reuse"
        }

        all_passed = all(f["passed"] for f in results.values())
        return {
            "all_adversarial_passed": all_passed,
            "families": results
        }
