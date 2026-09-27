"""
CNE Cost Class Projection.
Categorizes computation to determine whether optimization overhead is worthwhile.
Is spending effort on optimization likely to be cheaper than simply executing?
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, Optional
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph


class CostTier(Enum):
    TRIVIAL = "trivial"          # e.g. single scalar lookup or 1 arithmetic op: skip optimization
    LIGHTWEIGHT = "lightweight"  # small collection scan < 100 rows
    MODERATE = "moderate"        # join/aggregation over 100-10,000 rows
    HEAVY = "heavy"              # large scan, model inference, external call, multi-way join


@dataclass(frozen=True)
class CostClass:
    tier: CostTier
    estimated_op_count: int
    cardinality_bracket: str
    involves_external_call: bool
    involves_lazy_region: bool

    @classmethod
    def from_graph(cls, graph: SemanticIRGraph, cardinality_hint: int = 100) -> CostClass:
        op_count = len(graph.nodes)
        for r in graph.regions.values():
            op_count += len(r.nodes)

        has_external = False
        has_lazy = False
        has_join = False
        has_reduce = False
        for n in graph.nodes.values():
            op = n.op
            if op in (OpKind.OBSERVE, OpKind.CALL):
                has_external = True
            elif op in (OpKind.BRANCH, OpKind.ITERATE):
                has_lazy = True
            elif op == OpKind.JOIN:
                has_join = True
            elif op == OpKind.REDUCE:
                has_reduce = True

        if cardinality_hint < 10:
            bracket = "<10"
        elif cardinality_hint <= 1000:
            bracket = "10-1k"
        elif cardinality_hint <= 100000:
            bracket = "1k-100k"
        else:
            bracket = ">100k"

        if op_count <= 2 and not has_external and cardinality_hint < 10:
            tier = CostTier.TRIVIAL
        elif has_join or (cardinality_hint > 10000) or (has_external and op_count > 6):
            tier = CostTier.HEAVY
        elif (has_external and has_lazy) or (cardinality_hint > 1000):
            tier = CostTier.MODERATE
        else:
            tier = CostTier.LIGHTWEIGHT

        return cls(
            tier=tier,
            estimated_op_count=op_count,
            cardinality_bracket=bracket,
            involves_external_call=has_external,
            involves_lazy_region=has_lazy
        )

    def is_worth_optimizing(self) -> bool:
        """
        Trivial computations execute directly; others are worth analyzing.
        """
        return self.tier != CostTier.TRIVIAL

    def __repr__(self) -> str:
        return f"CostClass({self.tier.value}, ops={self.estimated_op_count}, card={self.cardinality_bracket})"
