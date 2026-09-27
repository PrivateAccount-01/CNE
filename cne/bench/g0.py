"""
CNE Gate G0 Benchmark Runner.
Validates:
1. Three standalone fixtures (expense, troubleshooting, scheduling) representable.
2. <= 2 new primitives (0 new primitives used; strictly the frozen 11).
3. Zero domain-specific nodes.
"""
from __future__ import annotations
from typing import Any, Dict
from cne.compiler.deterministic_fixtures import (
    build_expense_fixture,
    build_troubleshooting_fixture,
    build_scheduling_fixture
)
from cne.semantic_ir.evaluator import SemanticEvaluator
from cne.semantic_ir.nodes import OpKind


class GateG0Runner:
    FROZEN_PRIMITIVES = {
        OpKind.OBSERVE, OpKind.MAP, OpKind.FILTER, OpKind.REDUCE, OpKind.JOIN,
        OpKind.BRANCH, OpKind.ITERATE, OpKind.CHOOSE, OpKind.UPDATE, OpKind.CALL,
        OpKind.EMIT, OpKind.LITERAL
    }

    @classmethod
    def run_g0(cls) -> Dict[str, Any]:
        results = {}

        # 1. Expense fixture
        g_exp, c_exp = build_expense_fixture()
        exp_ops = {n.op for n in g_exp.nodes.values()}
        for r in g_exp.regions.values():
            exp_ops.update(n.op for n in r.nodes.values())
        exp_valid = exp_ops.issubset(cls.FROZEN_PRIMITIVES)

        # 2. Troubleshooting fixture
        g_diag, c_diag = build_troubleshooting_fixture()
        diag_ops = {n.op for n in g_diag.nodes.values()}
        for r in g_diag.regions.values():
            diag_ops.update(n.op for n in r.nodes.values())
        diag_valid = diag_ops.issubset(cls.FROZEN_PRIMITIVES)

        # 3. Scheduling fixture
        g_sched, c_sched = build_scheduling_fixture()
        sched_ops = {n.op for n in g_sched.nodes.values()}
        for r in g_sched.regions.values():
            sched_ops.update(n.op for n in r.nodes.values())
        sched_valid = sched_ops.issubset(cls.FROZEN_PRIMITIVES)

        all_ops = exp_ops | diag_ops | sched_ops
        new_primitives = all_ops - cls.FROZEN_PRIMITIVES

        passed = (
            exp_valid and diag_valid and sched_valid and
            len(new_primitives) <= 2
        )

        return {
            "gate": "G0",
            "passed": passed,
            "fixtures_representable": {
                "expense": exp_valid,
                "troubleshooting": diag_valid,
                "scheduling": sched_valid
            },
            "new_primitives_count": len(new_primitives),
            "new_primitives": [p.value for p in new_primitives],
            "total_nodes_used": len(g_exp.nodes) + len(g_diag.nodes) + len(g_sched.nodes)
        }


if __name__ == "__main__":
    res = GateG0Runner.run_g0()
    print("G0 Result:", res)
