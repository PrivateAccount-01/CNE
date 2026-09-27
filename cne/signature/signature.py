"""
CNE Computational Signature.
Provides access to the four separate projections:
1. Semantic shape key
2. Memo key
3. Cost class
4. Policy state
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional
from cne.semantic_ir.nodes import SemanticIRGraph
from cne.signature.cost_class import CostClass
from cne.signature.memo_key import MemoKey, SystemVersions
from cne.signature.policy_state import PolicyState
from cne.signature.shape_key import SemanticShapeKey


@dataclass
class ComputationalSignature:
    shape_key: SemanticShapeKey
    memo_key: MemoKey
    cost_class: CostClass
    policy_state: Optional[PolicyState] = None

    @classmethod
    def compute(
        cls,
        graph: SemanticIRGraph,
        input_data: Optional[Dict[str, Any]] = None,
        versions: Optional[SystemVersions] = None,
        cardinality_hint: int = 100,
        policy_state: Optional[PolicyState] = None
    ) -> ComputationalSignature:
        sk = SemanticShapeKey.from_graph(graph)
        mk = MemoKey.from_graph(graph, input_data=input_data, versions=versions)
        cc = CostClass.from_graph(graph, cardinality_hint=cardinality_hint)
        return cls(shape_key=sk, memo_key=mk, cost_class=cc, policy_state=policy_state)
