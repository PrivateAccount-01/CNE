"""
CNE Exact Contract Simplification.
Simplifies computation graph where OutcomeContract permits (e.g. decision boundary, approximate numeric tolerance).
"""
from __future__ import annotations
import copy
from typing import Optional
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph


class ContractSimplifier:
    """
    Simplifies computation graph where OutcomeContract permits:
    - DECISION: folds statically known constants against decision_boundary.
      Status: Constant boundary folding active; dynamic path pruning is
      reserved, not yet active in static optimizer (Phase P4 extension).
    - EXACT / APPROXIMATE_NUMERIC: identity preservation.
    """
    @classmethod
    def simplify(cls, graph: SemanticIRGraph, contract: OutcomeContract) -> SemanticIRGraph:
        if contract.contract_type == ContractType.DECISION and contract.decision_boundary is not None:
            # Constant boundary folding: if emit input is a statically folded literal
            if graph.root_id and graph.root_id in graph.nodes:
                emit_node = graph.nodes[graph.root_id]
                if emit_node.inputs:
                    inp_id = emit_node.inputs[0]
                    inp_node = graph.nodes.get(inp_id)
                    if inp_node and inp_node.op == OpKind.LITERAL:
                        val = inp_node.attributes.get("value")
                        if isinstance(val, (int, float)):
                            decision_bool = (float(val) >= float(contract.decision_boundary))
                            inp_node.attributes["value"] = decision_bool
                            graph.invalidate_structural_cache()

        return graph
