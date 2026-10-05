"""
CNE Compact Semantic DSL & Deterministic Compiler.
Replaces verbose JSON generation with a terse, formal domain-specific language.

Grammar:
A DSL script consists of newline-delimited operation lines:
<OP> <key>=<value> <key>=<value> ...

Allowed OPs strictly correspond to CNE's 11 frozen primitives (+ Literal):
OBS (Observe)
FIL (Filter)
MAP (Map)
RED (Reduce)
JOI (Join)
BRA (Branch)
ITE (Iterate)
CHO (Choose)
UPD (Update)
CAL (Call)
EMI (Emit)
LIT (Literal)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.semantic_ir.types import SemanticType


_OP_MAP: Dict[str, OpKind] = {
    "OBS": OpKind.OBSERVE,
    "FIL": OpKind.FILTER,
    "MAP": OpKind.MAP,
    "RED": OpKind.REDUCE,
    "JOI": OpKind.JOIN,
    "BRA": OpKind.BRANCH,
    "ITE": OpKind.ITERATE,
    "CHO": OpKind.CHOOSE,
    "UPD": OpKind.UPDATE,
    "CAL": OpKind.CALL,
    "EMI": OpKind.EMIT,
    "LIT": OpKind.LITERAL,
}


@dataclass
class DSLNode:
    op_code: str
    attributes: Dict[str, Any]
    line_number: int


@dataclass
class DSLCompileResult:
    is_valid: bool
    graph: Optional[SemanticIRGraph] = None
    contract: Optional[OutcomeContract] = None
    extracted_slots: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


class SemanticDSLParser:
    """
    Parses and compiles compact CNE DSL scripts into type-safe SemanticIRGraph instances.
    """

    @classmethod
    def parse_line(cls, line: str, line_no: int = 1) -> Optional[DSLNode]:
        line = line.strip()
        if not line or line.startswith("#"):
            return None

        # Support optional assignment syntax, e.g. "t0 = OBS source=..."
        if "=" in line:
            parts_eq = line.split("=", 1)
            first_word = parts_eq[0].strip()
            rest = parts_eq[1].strip()
            rest_tokens = rest.split()
            if " " not in first_word and rest_tokens and rest_tokens[0].upper() in _OP_MAP:
                line = rest

        parts = line.split()
        op_code = parts[0].upper()
        if op_code not in _OP_MAP:
            raise ValueError(f"Line {line_no}: Unknown primitive opcode '{op_code}'")

        attrs: Dict[str, Any] = {}
        for token in parts[1:]:
            if "=" not in token:
                continue
            k, v = token.split("=", 1)
            # Deterministic type parsing
            if v.lower() == "true":
                val: Any = True
            elif v.lower() == "false":
                val = False
            else:
                try:
                    val = int(v) if "." not in v else float(v)
                except ValueError:
                    val = v
            attrs[k] = val

        return DSLNode(op_code=op_code, attributes=attrs, line_number=line_no)

    @classmethod
    def compile_dsl(
        cls,
        dsl_text: str,
        contract_type: ContractType = ContractType.EXACT,
        intent: Optional[str] = None
    ) -> DSLCompileResult:
        """
        Deterministically compiles DSL text into a valid CNE SemanticIRGraph.
        """
        lines = dsl_text.strip().splitlines()
        nodes: List[DSLNode] = []

        try:
            for i, l in enumerate(lines):
                node = cls.parse_line(l, line_no=i + 1)
                if node:
                    nodes.append(node)
        except Exception as e:
            return DSLCompileResult(
                is_valid=False,
                error_message=f"DSL Parsing error: {str(e)}"
            )

        if not nodes:
            return DSLCompileResult(
                is_valid=False,
                error_message="Empty DSL script: no operational nodes defined."
            )

        # Invariant: Must end with exactly ONE Emit node
        if nodes[-1].op_code != "EMI":
            return DSLCompileResult(
                is_valid=False,
                error_message=f"Last node must be 'EMI' (Emit), got '{nodes[-1].op_code}'"
            )

        graph = SemanticIRGraph()
        slots: Dict[str, Any] = {}
        prev_node_id: Optional[str] = None

        for idx, d_node in enumerate(nodes):
            node_id = f"n{idx}_{d_node.op_code.lower()}"
            op_kind = _OP_MAP[d_node.op_code]
            inputs = [prev_node_id] if prev_node_id else []

            # Set output type heuristically based on primitive
            if op_kind in (OpKind.OBSERVE, OpKind.FILTER, OpKind.MAP):
                out_type = SemanticType.collection(SemanticType.any())
            elif op_kind in (OpKind.REDUCE, OpKind.EMIT, OpKind.LITERAL):
                out_type = SemanticType.scalar()
            elif op_kind == OpKind.BRANCH:
                out_type = SemanticType.boolean()
            else:
                out_type = SemanticType.record({})

            # Extract slots from node attributes deterministically
            for k, v in d_node.attributes.items():
                if k in ("category", "threshold", "aggregation", "metric", "account", "source"):
                    slots[k] = v

            attrs = dict(d_node.attributes)
            if op_kind == OpKind.REDUCE:
                reducer_name = str(attrs.get("reducer") or attrs.get("op", "sum")).lower()
                init_val = float(attrs.get("initial", attrs.get("init", 0)))
                if reducer_name in ("sum", "+"):
                    attrs["op"] = lambda a, b: (0.0 if a is None else a) + (b or 0.0)
                    attrs["init"] = init_val
                elif reducer_name == "count":
                    attrs["op"] = lambda a, _: (0 if a is None else a) + 1
                    attrs["init"] = int(init_val)
                elif reducer_name == "max":
                    attrs["op"] = lambda a, b: max(a, b)
                    attrs["init"] = init_val
                elif reducer_name == "min":
                    attrs["op"] = lambda a, b: min(a, b)
                    attrs["init"] = init_val
            elif op_kind == OpKind.MAP:
                field = attrs.get("field")
                if field:
                    attrs["fn"] = lambda x, f=field: (x.get(f) if isinstance(x, dict) else getattr(x, f, x))
            elif op_kind == OpKind.FILTER:
                field = attrs.get("field")
                val = attrs.get("val") or attrs.get("threshold")
                op_sym = attrs.get("op", "eq")
                if field and val is not None:
                    if op_sym == "gt":
                        attrs["predicate"] = lambda x, f=field, v=val: float(x.get(f, 0)) > float(v)
                    elif op_sym == "lt":
                        attrs["predicate"] = lambda x, f=field, v=val: float(x.get(f, 0)) < float(v)
                    else:
                        attrs["predicate"] = lambda x, f=field, v=val: str(x.get(f, "")).lower() == str(v).lower()
                elif val is not None:
                    if op_sym == "gt":
                        attrs["predicate"] = lambda x, v=val: float(x) > float(v)
                    elif op_sym == "lt":
                        attrs["predicate"] = lambda x, v=val: float(x) < float(v)
                    else:
                        attrs["predicate"] = lambda x, v=val: str(x).lower() == str(v).lower()

            ir_node = IRNode(
                id=node_id,
                op=op_kind,
                inputs=inputs,
                attributes=attrs,
                output_type=out_type
            )
            graph.add_node(ir_node)
            prev_node_id = node_id

        # Root node is the emit node
        root_id = prev_node_id
        graph.root_id = root_id
        contract = OutcomeContract(
            contract_type=contract_type
        )

        return DSLCompileResult(
            is_valid=True,
            graph=graph,
            contract=contract,
            extracted_slots=slots
        )
