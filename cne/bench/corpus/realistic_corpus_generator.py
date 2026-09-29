"""
CNE Realistic Benchmark Corpus Generator (Phase P0.7).
Constructs a 1,550-query corpus with complete provenance, generation-batch tagging,
and structured adversarial families across 7 topologies.

Composition:
1. Template-canonical: 7 queries (1 per topology, baseline sanity check).
2. LLM-generated paraphrases: 990 queries (>=60%) across 3 independent generation batches:
   - batch_1: formal, precise phrasing (330 queries)
   - batch_2: conversational, colloquial phrasing (330 queries)
   - batch_3: compound, multi-clause phrasing (330 queries)
3. Adversarial families: 330 queries (>=20%) across 6 structured families (A1-A6, 55 each):
   - A1: Same wording, different dependency (sensors/accounts)
   - A2: Same wording, different OutcomeContract
   - A3: Small parameter change (micro-parameter sensitivity)
   - A4: Different wording, identical computation (shape invariance)
   - A5: Same topology, different cost class (cardinality 10 vs 100,000)
   - A6: Same topology, different effect set (Pure vs WriteExternal)
4. Out-of-distribution: 223 queries:
   - 123 unsupported domain requests (weather, crypto, travel, translation, recipe, code)
   - 50 ambiguous cross-domain queries
   - 50 low-confidence / fragment queries

Total: 1,550 queries. Deterministic via frozen seed.
"""
import json
import os
import random
from typing import Any, Dict, List, Optional


class RealisticCorpusGenerator:
    """
    Builds the 1,550-query realistic corpus with generation batch and provenance dimensions.
    """

    TOPOLOGIES = [
        "expense",
        "troubleshooting",
        "scheduling",
        "habit_fitness",
        "factual_decision",
        "recommendation",
        "cross_source_join_aggregate"
    ]

    @classmethod
    def generate_corpus(cls, seed: int = 42) -> Dict[str, Any]:
        rng = random.Random(seed)
        queries: List[Dict[str, Any]] = []

        # =====================================================================
        # 1. Template-Canonical Baseline (7 queries: 1 per topology)
        # =====================================================================
        canonical_queries = [
            ("p07_canon_expense", "expense", "Calculate total food spending over $100"),
            ("p07_canon_troubleshooting", "troubleshooting", "Diagnose telemetry alerts on node_1 with error threshold exceeding 5"),
            ("p07_canon_scheduling", "scheduling", "Schedule a meeting with alice for duration of 30 minutes"),
            ("p07_canon_habit_fitness", "habit_fitness", "Log my running workout activity and verify goal of 30 minutes"),
            ("p07_canon_factual_decision", "factual_decision", "Decide on deployment options with confidence above 0.75"),
            ("p07_canon_recommendation", "recommendation", "Recommend catalog items with rating above 4.0 for user_1"),
            ("p07_canon_join", "cross_source_join_aggregate", "Reconcile orders and inventory matching stock quantity exceeding 5")
        ]

        for qid, topo, text in canonical_queries:
            queries.append({
                "id": qid,
                "query_text": text,
                "category": "template_canonical",
                "generation_batch": "canonical",
                "intended_topology": topo,
                "expected_classification": "COMPILED",
                "adversarial_family": None,
                "slots": {}
            })

        # =====================================================================
        # 2. LLM-Generated Paraphrases (990 queries: loaded from frozen artifact)
        # =====================================================================
        artifact_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "artifacts", "corpus", "llm_paraphrases_v1.json"
        )
        if os.path.exists(artifact_path):
            with open(artifact_path, "r", encoding="utf-8") as f:
                artifact_data = json.load(f)
            paraphrases = artifact_data.get("paraphrases", [])
            for p in paraphrases:
                queries.append({
                    "id": p["id"],
                    "query_text": p["query_text"],
                    "category": "llm_paraphrase",
                    "generation_batch": p["generation_batch"],
                    "generator_metadata": p.get("generator_metadata", {}),
                    "intended_topology": p["intended_topology"],
                    "expected_classification": p.get("expected_classification", "COMPILED"),
                    "adversarial_family": None,
                    "slots": p.get("ground_truth_slots", {})
                })
        else:
            raise FileNotFoundError(f"Paraphrase generation artifact not found at {artifact_path}")

        # =====================================================================
        # 3. Adversarial Families (330 queries: 6 families x 55 queries)
        # =====================================================================
        # A1: Same wording, different dependency (sensors/accounts)
        for i in range(55):
            src_variant = f"sensor_cluster_{i % 5}"
            account_id = f"account_{100 + i}"
            text = f"Calculate total food spending over $100 for user account {account_id}"
            queries.append({
                "id": f"p07_adv_a1_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a1",
                "intended_topology": "expense",
                "expected_classification": "COMPILED",
                "adversarial_family": "A1",
                "slots": {"category": "Food", "threshold": 100.0, "source_dep": src_variant, "account": account_id}
            })

        # A2: Same wording, different OutcomeContract
        contracts = ["EXACT", "APPROXIMATE_NUMERIC", "SET_VALUED", "DECISION"]
        for i in range(55):
            c_type = contracts[i % len(contracts)]
            text = f"Evaluate options and decide on deployment strategy with confidence >= 0.80"
            queries.append({
                "id": f"p07_adv_a2_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a2",
                "intended_topology": "factual_decision",
                "expected_classification": "COMPILED",
                "adversarial_family": "A2",
                "contract_override": c_type,
                "slots": {"topic": "deployment", "min_confidence": 0.80}
            })

        # A3: Small parameter change (micro-parameter sensitivity)
        for i in range(55):
            micro_thresh = 100.0 + (i * 0.01)
            text = f"Calculate total travel spending over ${micro_thresh:.2f}"
            queries.append({
                "id": f"p07_adv_a3_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a3",
                "intended_topology": "expense",
                "expected_classification": "COMPILED",
                "adversarial_family": "A3",
                "slots": {"category": "Travel", "threshold": micro_thresh}
            })

        # A4: Different wording, identical computation (shape invariance)
        a4_phrasings = [
            "Calculate total food spending over $100",
            "Show me all food expenses exceeding 100 dollars",
            "Sum food purchases greater than 100",
            "Give total spent on food above $100",
            "Find net food costs higher than 100"
        ]
        for i in range(55):
            text = a4_phrasings[i % len(a4_phrasings)]
            queries.append({
                "id": f"p07_adv_a4_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a4",
                "intended_topology": "expense",
                "expected_classification": "COMPILED",
                "adversarial_family": "A4",
                "slots": {"category": "Food", "threshold": 100.0}
            })

        # A5: Same topology, different cost class (cardinality 10 vs 100,000)
        for i in range(55):
            cardinality = 10 if (i % 2 == 0) else 100000
            text = f"Diagnose telemetry alerts on node_1 with error threshold exceeding 5"
            queries.append({
                "id": f"p07_adv_a5_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a5",
                "intended_topology": "troubleshooting",
                "expected_classification": "COMPILED",
                "adversarial_family": "A5",
                "env_override": {"telemetry_cardinality": cardinality},
                "slots": {"system_id": "node_1", "error_threshold": 5}
            })

        # A6: Same topology, different effect set (Pure vs WriteExternal)
        for i in range(55):
            effect_mode = "pure" if (i % 2 == 0) else "audit_log"
            text = f"Reconcile orders and inventory matching stock quantity exceeding 10"
            queries.append({
                "id": f"p07_adv_a6_{i}",
                "query_text": text,
                "category": "adversarial",
                "generation_batch": "adv_a6",
                "intended_topology": "cross_source_join_aggregate",
                "expected_classification": "COMPILED",
                "adversarial_family": "A6",
                "effect_mode": effect_mode,
                "slots": {"min_quantity": 10}
            })

        # =====================================================================
        # 4. Out-of-Distribution / Non-compilable (223 queries)
        # =====================================================================
        # 4a. Unsupported domain queries (123 queries)
        unsupported_pool = [
            "What will the weather forecast be in Tokyo tomorrow with rain?",
            "Can you translate this official legal contract into Spanish and French?",
            "Buy 500 shares of Apple stock on Nasdaq and track dividend yield",
            "Write a poem about the beauty of the starry night sky",
            "Generate a high-resolution photograph of a futuristic cyberpunk city",
            "Write a python script with recursive backtracking to solve sudoku",
            "Book a roundtrip flight from San Francisco to Paris next Monday",
            "Provide an authentic Italian recipe for making homemade pizza dough",
            "What is the current temperature and humidity in London?",
            "Can you write a funny rhyming joke about a software developer?"
        ]
        for i in range(123):
            base_text = unsupported_pool[i % len(unsupported_pool)]
            queries.append({
                "id": f"p07_ood_unsupported_{i}",
                "query_text": f"{base_text} (variant {i})",
                "category": "out_of_distribution",
                "generation_batch": "ood_unsupported",
                "intended_topology": "none",
                "expected_classification": "UNSUPPORTED_INTENT",
                "adversarial_family": None,
                "slots": {}
            })

        # 4b. Ambiguous cross-domain queries (50 queries)
        ambiguous_pool = [
            "Schedule a meeting with alice to reconcile orders and inventory spending",
            "Diagnose telemetry alerts on node_1 while evaluating decision options with confidence 0.8",
            "Recommend catalog items for user_1 and schedule appointment slot for 30 minutes",
            "Calculate total food spending and diagnose node_2 error limit exceeding 5",
            "Decide on deployment options and recommend products for user_3"
        ]
        for i in range(50):
            base_text = ambiguous_pool[i % len(ambiguous_pool)]
            queries.append({
                "id": f"p07_ood_ambiguous_{i}",
                "query_text": f"{base_text} (case {i})",
                "category": "out_of_distribution",
                "generation_batch": "ood_ambiguous",
                "intended_topology": "none",
                "expected_classification": "AMBIGUOUS_INTENT",
                "adversarial_family": None,
                "slots": {}
            })

        # 4c. Low-confidence / fragment queries (50 queries)
        # Calibrated to exhibit partial intent keywords below the 0.65 confidence floor
        vague_pool = [
            "maybe spend on miscellaneous stuff",
            "some transaction items perhaps",
            "a fitness log entry maybe",
            "perhaps an appointment detail maybe",
            "perhaps some decision alternatives maybe"
        ]
        for i in range(50):
            base_text = vague_pool[i % len(vague_pool)]
            queries.append({
                "id": f"p07_ood_vague_{i}",
                "query_text": f"{base_text} ref_{i}",
                "category": "out_of_distribution",
                "generation_batch": "ood_vague",
                "intended_topology": "none",
                "expected_classification": "LOW_CONFIDENCE_MAPPING",
                "adversarial_family": None,
                "slots": {}
            })

        assert len(queries) == 1550, f"Expected 1,550 queries, got {len(queries)}"

        return {
            "metadata": {
                "total_queries": len(queries),
                "seed": seed,
                "num_canonical": len(canonical_queries),
                "num_paraphrases": 990,
                "num_adversarial": 330,
                "num_ood": 223,
                "batches": ["canonical", "batch_1", "batch_2", "batch_3", "adv_a1", "adv_a2", "adv_a3", "adv_a4", "adv_a5", "adv_a6", "ood_unsupported", "ood_ambiguous", "ood_vague"]
            },
            "queries": queries
        }
