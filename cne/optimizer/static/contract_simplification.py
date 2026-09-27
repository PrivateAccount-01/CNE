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
    @classmethod
    def simplify(cls, graph: SemanticIRGraph, contract: OutcomeContract) -> SemanticIRGraph:
        g = copy.deepcopy(graph)

        # If contract is DECISION and root is Emit of a comparison
        if contract.contract_type == ContractType.DECISION:
            # We can simplify redundant downstream formatting if any exists before Emit
            pass

        return g
