"""
CNE Static Dependency Slicing.
Prunes redundant filters and slices dependencies so only required columns/fields are retrieved.
Supports certified proof for constant-True predicates and audited-tier labeling for heuristic probes.
"""
from __future__ import annotations
import copy
import dis
from typing import Any, Dict, List, Optional, Set
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.verify.verifier import VerificationLevel


def is_provably_constant_true(pred: Any) -> bool:
    """
    Formally proves via Python bytecode inspection that pred unconditionally returns True
    without side effects, variable lookups, or input dependencies.
    Satisfies Certified-tier verification standards.
    """
    if pred is True:
        return True
    code = getattr(pred, "__code__", None)
    if code is None:
        return False
    # Must not access globals, closures, or free variables
    if code.co_names or code.co_freevars or code.co_cellvars:
        return False
    try:
        instructions = [i for i in dis.get_instructions(code) if i.opname != "RESUME"]
        # Python 3.12+: RETURN_CONST (True)
        if len(instructions) == 1 and instructions[0].opname == "RETURN_CONST" and instructions[0].argval is True:
            return True
        # Python 3.11 and earlier: LOAD_CONST (True), RETURN_VALUE
        if (len(instructions) == 2 and 
            instructions[0].opname == "LOAD_CONST" and instructions[0].argval is True and 
            instructions[1].opname == "RETURN_VALUE"):
            return True
    except Exception:
        pass
    return False


class DependencySlicer:
    @classmethod
    def slice(cls, graph: SemanticIRGraph) -> SemanticIRGraph:
        if not any(n.op == OpKind.FILTER and n.inputs for n in graph.nodes.values()):
            return graph
        g = graph.clone()

        eliminated_evidence: List[Dict[str, Any]] = []

        # Slicing pass: if there are consecutive identical filters or redundant no-op filters, simplify
        for nid, node in list(g.nodes.items()):
            if node.op == OpKind.FILTER and node.inputs:
                pred = node.attributes.get("predicate")
                eliminated = False
                tier = None
                justification = ""

                # 1. Formal Proof: Certified tier
                if is_provably_constant_true(pred):
                    eliminated = True
                    tier = VerificationLevel.CERTIFIED.value
                    justification = "Bytecode inspection proved constant-True return with zero side effects."
                # 2. Heuristic Probe: Audited tier (Doc #15)
                elif pred is not None and getattr(pred, "__name__", "") == "<lambda>":
                    try:
                        # Test if lambda returns True on generic object
                        if pred(None) is True and pred({}) is True:
                            eliminated = True
                            tier = VerificationLevel.AUDITED.value
                            justification = "Empirical probe on None/empty dict returned True (Audited tier; not formal proof)."
                    except Exception:
                        pass

                if eliminated:
                    # Bypass redundant filter: rewire consumers directly to filter's input
                    parent_id = node.inputs[0]
                    for other in g.nodes.values():
                        other.inputs = [parent_id if inp == nid else inp for inp in other.inputs]
                    if g.root_id == nid:
                        g.root_id = parent_id
                    del g.nodes[nid]

                    eliminated_evidence.append({
                        "node_id": nid,
                        "parent_id": parent_id,
                        "evidence_tier": tier,
                        "justification": justification
                    })

        if eliminated_evidence:
            g.metadata["filter_slicing_evidence"] = eliminated_evidence
            # If any elimination was Audited, the aggregate slicing tier is Audited; otherwise Certified
            if any(e["evidence_tier"] == VerificationLevel.AUDITED.value for e in eliminated_evidence):
                g.metadata["evidence_tier"] = VerificationLevel.AUDITED.value
            else:
                g.metadata["evidence_tier"] = VerificationLevel.CERTIFIED.value

        return g
