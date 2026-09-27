"""
CNE Gate G1 Benchmark Runner.
Validates:
- G1a: >=80% paraphrase-group invariance (semantic shape key).
- G1b: Distinct genuine topologies -> distinct shape keys (report complete distribution).
- G1c: Memo-key sensitivity (anti-reuse differs in memo key; false-difference shares shape and cost class).
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
from cne.bench.corpus.corpus_generator import CorpusGenerator
from cne.compiler.fixture_compiler import FixtureCompiler
from cne.signature.cost_class import CostClass
from cne.signature.memo_key import MemoKey
from cne.signature.shape_key import SemanticShapeKey


class GateG1Runner:
    @classmethod
    def run_g1(cls) -> Dict[str, Any]:
        corpus = CorpusGenerator.generate_corpus()

        # ---------------- G1a: Paraphrase Group Invariance ----------------
        paraphrase_groups = corpus["paraphrase_groups"]
        group_invariances: List[float] = []

        for group in paraphrase_groups:
            shape_counts: Dict[str, int] = {}
            for q in group:
                g, _ = FixtureCompiler.compile_query(q)
                sk = SemanticShapeKey.from_graph(g)
                shape_counts[sk.key_hash] = shape_counts.get(sk.key_hash, 0) + 1

            max_count = max(shape_counts.values()) if shape_counts else 0
            invariance = max_count / len(group) if group else 0.0
            group_invariances.append(invariance)

        avg_invariance = sum(group_invariances) / len(group_invariances) if group_invariances else 0.0
        min_invariance = min(group_invariances) if group_invariances else 0.0
        g1a_passed = min_invariance >= 0.80

        # ---------------- G1b: Topology Discrimination ----------------
        distinct_topologies = corpus["distinct_topologies"]
        topo_shapes: Dict[str, str] = {}
        for item in distinct_topologies:
            g, _ = FixtureCompiler.compile_query(item)
            sk = SemanticShapeKey.from_graph(g)
            topo_shapes[item["id"]] = sk.key_hash

        unique_shapes = set(topo_shapes.values())
        g1b_passed = (len(unique_shapes) == len(distinct_topologies))

        # ---------------- G1c: Memo-Key Sensitivity ----------------
        anti_pair = corpus["anti_reuse_pair"]
        g_anti1, _ = FixtureCompiler.compile_query(anti_pair[0])
        g_anti2, _ = FixtureCompiler.compile_query(anti_pair[1])
        sk_anti1 = SemanticShapeKey.from_graph(g_anti1)
        sk_anti2 = SemanticShapeKey.from_graph(g_anti2)
        mk_anti1 = MemoKey.from_graph(g_anti1)
        mk_anti2 = MemoKey.from_graph(g_anti2)

        # Anti-reuse: shapes may match, memo keys MUST differ
        anti_memo_differs = (mk_anti1.key_hash != mk_anti2.key_hash)

        false_diff_pair = corpus["false_difference_pair"]
        g_fd1, _ = FixtureCompiler.compile_query(false_diff_pair[0])
        g_fd2, _ = FixtureCompiler.compile_query(false_diff_pair[1])
        sk_fd1 = SemanticShapeKey.from_graph(g_fd1)
        sk_fd2 = SemanticShapeKey.from_graph(g_fd2)
        cc_fd1 = CostClass.from_graph(g_fd1)
        cc_fd2 = CostClass.from_graph(g_fd2)

        # False-difference: same shape key, same cost class
        false_diff_shape_matches = (sk_fd1.key_hash == sk_fd2.key_hash)
        false_diff_cost_matches = (cc_fd1.tier == cc_fd2.tier and cc_fd1.cardinality_bracket == cc_fd2.cardinality_bracket)

        g1c_passed = anti_memo_differs and false_diff_shape_matches and false_diff_cost_matches

        overall_passed = g1a_passed and g1b_passed and g1c_passed

        return {
            "gate": "G1",
            "passed": overall_passed,
            "g1a": {
                "passed": g1a_passed,
                "avg_invariance": avg_invariance,
                "min_invariance": min_invariance,
                "threshold": 0.80,
                "total_groups": len(paraphrase_groups)
            },
            "g1b": {
                "passed": g1b_passed,
                "num_distinct_topologies": len(distinct_topologies),
                "num_unique_shape_keys": len(unique_shapes),
                "topology_distribution": topo_shapes
            },
            "g1c": {
                "passed": g1c_passed,
                "anti_reuse_memo_keys_differ": anti_memo_differs,
                "false_diff_shapes_match": false_diff_shape_matches,
                "false_diff_costs_match": false_diff_cost_matches
            }
        }


if __name__ == "__main__":
    res = GateG1Runner.run_g1()
    print("G1 Result:", res)
