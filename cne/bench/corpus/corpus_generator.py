"""
CNE Benchmark Corpus Generator.
Constructs the 200-query benchmark corpus (100 expense, 100 troubleshooting),
plus explicit adversarial cases (anti-reuse pairs, false-difference pairs, paraphrase groups, and distinct topologies).
"""
from __future__ import annotations
import random
from typing import Any, Dict, List, Tuple


class CorpusGenerator:
    @classmethod
    def generate_corpus(cls) -> Dict[str, Any]:
        """
        Generates 200 queries + adversarial pairs and paraphrase groups.
        """
        random.seed(42)  # Benchmark discipline: frozen deterministic seed

        queries: List[Dict[str, Any]] = []

        # 1. 100 Expense queries
        categories = ["Food", "Travel", "Utilities", "Shopping", "Entertainment", "Health", "Office", "Electronics"]
        expense_paraphrase_templates = [
            "Calculate total {cat} spending over {thresh}",
            "Show me how much I spent on {cat} above {thresh}",
            "Sum up {cat} expenses exceeding {thresh}",
            "Give me aggregate {cat} purchases higher than {thresh}",
            "What was the total {cat} spend over {thresh} dollars?",
        ]

        # Build 10 paraphrase groups of 5 queries each = 50 queries
        paraphrase_groups: List[List[Dict[str, Any]]] = []
        for i in range(10):
            cat = categories[i % len(categories)]
            thresh = 50.0 + i * 15.0
            group = []
            for j, tmpl in enumerate(expense_paraphrase_templates):
                qid = f"exp_para_{i}_{j}"
                q = {
                    "id": qid,
                    "domain": "expense",
                    "category": cat,
                    "threshold": thresh,
                    "exclude_transfers": True,
                    "wording": tmpl.format(cat=cat, thresh=thresh),
                    "paraphrase_group_id": f"group_exp_{i}"
                }
                group.append(q)
                queries.append(q)
            paraphrase_groups.append(group)

        # 50 diverse individual expense queries
        for i in range(50):
            cat = categories[i % len(categories)]
            thresh = 20.0 + (i * 7) % 300
            exclude = (i % 2 == 0)
            qid = f"exp_div_{i}"
            q = {
                "id": qid,
                "domain": "expense",
                "category": cat,
                "threshold": float(thresh),
                "exclude_transfers": exclude,
                "wording": f"Analyze {cat} expenses with threshold {thresh} (exclude transfers={exclude})"
            }
            queries.append(q)

        # 2. 100 Troubleshooting queries
        system_nodes = [f"node_{k}" for k in range(1, 21)]
        troubleshoot_templates = [
            "Diagnose telemetry alerts on {node} with threshold {thresh}",
            "Check if {node} has critical errors exceeding {thresh}",
            "Inspect system status for {node} and remediate if errors > {thresh}",
            "Run automated troubleshooting on {node} above error limit {thresh}",
            "Evaluate health of {node} against error bound {thresh}"
        ]

        # 10 paraphrase groups of 5 queries each = 50 queries
        for i in range(10):
            node = system_nodes[i % len(system_nodes)]
            thresh = 2 + (i % 5)
            group = []
            for j, tmpl in enumerate(troubleshoot_templates):
                qid = f"diag_para_{i}_{j}"
                q = {
                    "id": qid,
                    "domain": "troubleshooting",
                    "system_id": node,
                    "error_threshold": thresh,
                    "wording": tmpl.format(node=node, thresh=thresh),
                    "paraphrase_group_id": f"group_diag_{i}"
                }
                group.append(q)
                queries.append(q)
            paraphrase_groups.append(group)

        # 50 diverse individual troubleshooting queries
        for i in range(50):
            node = system_nodes[i % len(system_nodes)]
            thresh = 1 + (i % 8)
            qid = f"diag_div_{i}"
            q = {
                "id": qid,
                "domain": "troubleshooting",
                "system_id": node,
                "error_threshold": thresh,
                "wording": f"Monitor system health for {node} with alert boundary {thresh}"
            }
            queries.append(q)

        # 3. Explicit Adversarial Cases: Anti-reuse pairs
        # Anti-reuse: Similar wording, different computation
        # "Compare expenses excluding transfers" vs "Compare expenses including transfers"
        anti_reuse_pair = (
            {
                "id": "anti_reuse_1",
                "domain": "expense",
                "category": "Food",
                "threshold": 100.0,
                "exclude_transfers": True,
                "wording": "Compare expenses excluding transfers"
            },
            {
                "id": "anti_reuse_2",
                "domain": "expense",
                "category": "Food",
                "threshold": 100.0,
                "exclude_transfers": False,
                "wording": "Compare expenses including transfers"
            }
        )

        # 4. Explicit Adversarial Cases: False-difference pairs
        # False-difference: Different surface wording, identical computational structure & cost
        # "Compare spending this month with last month" vs "Tell me how much more I spent this month than the previous month"
        false_difference_pair = (
            {
                "id": "false_diff_1",
                "domain": "expense",
                "category": "Shopping",
                "threshold": 50.0,
                "exclude_transfers": True,
                "wording": "Compare spending this month with last month"
            },
            {
                "id": "false_diff_2",
                "domain": "expense",
                "category": "Shopping",
                "threshold": 50.0,
                "exclude_transfers": True,
                "wording": "Tell me how much more I spent this month than the previous month"
            }
        )

        # 5. Distinct topology fixtures for G1b
        distinct_topologies = [
            {"id": "topo_expense", "domain": "expense", "category": "Food", "threshold": 50.0, "exclude_transfers": True},
            {"id": "topo_troubleshoot", "domain": "troubleshooting", "system_id": "node_1", "error_threshold": 3},
            {"id": "topo_scheduling", "domain": "scheduling", "user_id": "alice", "duration": 30},
            {"id": "topo_simple_lookup", "domain": "simple_lookup", "key": "status"},
            {"id": "topo_multi_join", "domain": "multi_join_analytics"}
        ]

        return {
            "queries": queries,  # exactly 200 queries
            "paraphrase_groups": paraphrase_groups,
            "anti_reuse_pair": anti_reuse_pair,
            "false_difference_pair": false_difference_pair,
            "distinct_topologies": distinct_topologies
        }
