"""Explicit, typed DAG DSL. Regions use `REGION name root=node` ... `END`."""
from __future__ import annotations
import json
import operator
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Optional
from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import SemanticType, TypeKind

_OP_MAP = {
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
# Required and optional attributes; references are explicit and never inferred.
SCHEMAS = {
    "OBS": ({"source"}, {"key", "type"}),
    "FIL": ({"in", "op", "val"}, {"field"}),
    "MAP": ({"in", "field"}, set()),
    "RED": ({"in", "reducer"}, {"initial"}),
    "JOI": ({"left", "right", "on"}, set()),
    "BRA": ({"in", "then_region", "else_region"}, set()),
    "ITE": ({"in", "step_region", "initial"}, set()),
    "CHO": ({"in"}, {"policy", "budget", "actions", "belief", "lookahead_depth"}),
    "UPD": ({"prior", "evidence"}, set()),
    "CAL": ({"target"}, {"in"}),
    "EMI": ({"in"}, {"label"}),
    "LIT": ({"value"}, set()),
}
COMPARISONS = {
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
    "eq": operator.eq,
    "ne": operator.ne,
}


@dataclass
class DSLNode:
    op_code: str
    attributes: dict
    line_number: int
    node_id: str


@dataclass
class DSLCompileResult:
    is_valid: bool
    graph: Optional[SemanticIRGraph] = None
    contract: Optional[OutcomeContract] = None
    extracted_slots: dict = field(default_factory=dict)
    error_message: Optional[str] = None


class SemanticDSLParser:
    @classmethod
    def parse_line(cls, line, line_no=1):
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        match = re.fullmatch(r"([A-Za-z_]\w*)\s*=\s*([A-Z]{3})(?:\s+(.*))?", line)
        if not match:
            raise ValueError(f"Line {line_no}: explicit node assignment required")
        nid, op, tail = match.groups()
        if op not in SCHEMAS:
            raise ValueError(f"Unknown primitive opcode '{op}'")
        attrs = {}
        for token in shlex.split(tail or ""):
            if "=" not in token:
                raise ValueError(f"Invalid attribute {token}")
            key, value = token.split("=", 1)
            if key in attrs:
                raise ValueError(f"Duplicate attribute {key}")
            try:
                attrs[key] = json.loads(value)
            except json.JSONDecodeError:
                attrs[key] = value
        required, optional = SCHEMAS[op]
        if required - attrs.keys() or attrs.keys() - required - optional:
            raise ValueError(
                f"{op}: missing {required - attrs.keys()}, unknown {attrs.keys() - required - optional}"
            )
        return DSLNode(op, attrs, line_no, nid)

    @classmethod
    def compile_dsl(cls, dsl_text, contract_type=ContractType.EXACT, intent=None):
        try:
            return cls._compile(dsl_text, contract_type, intent)
        except (ValueError, TypeError, KeyError) as exc:
            return DSLCompileResult(False, error_message=str(exc))

    @classmethod
    def _compile(cls, text, contract_type, intent):
        graph = SemanticIRGraph(
            metadata={"compiler_version": "dsl-2", "intent": intent}
        )
        parsed, owners = {}, {}
        region = None
        for number, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if line.startswith("REGION "):
                if region is not None:
                    raise ValueError(
                        "Region declarations cannot nest; use region references"
                    )
                match = re.fullmatch(r"REGION (\w+) root=(\w+)", line)
                if not match or match[1] in graph.regions:
                    raise ValueError("Invalid or duplicate region")
                region = SemanticRegion(match[1], root_id=match[2])
                graph.add_region(region)
                continue
            if line == "END":
                if region is None:
                    raise ValueError("Unmatched END")
                region = None
                continue
            node = cls.parse_line(line, number)
            if node is None:
                continue
            if node.node_id in parsed:
                raise ValueError("Duplicate node ID")
            parsed[node.node_id] = node
            owners[node.node_id] = region.id if region else None
        if region is not None:
            raise ValueError("Unclosed region")
        if not parsed:
            raise ValueError("Empty DSL")
        refs, region_refs = {}, {}
        for nid, node in parsed.items():
            a, op = node.attributes, node.op_code
            if op == "JOI":
                inputs = [a["left"], a["right"]]
            elif op == "UPD":
                inputs = [a["prior"], a["evidence"]]
            elif "in" in a:
                inputs = str(a["in"]).split(",")
            else:
                inputs = []
            if op != "CAL" and "in" in a and len(inputs) != 1:
                raise ValueError("Invalid arity")
            refs[nid] = inputs
            region_refs[nid] = [
                a[k] for k in ("then_region", "else_region", "step_region") if k in a
            ]
            for ref in inputs:
                if ref not in parsed:
                    raise ValueError(f"Unknown node reference: {ref}")
                if owners[ref] is not None and owners[ref] != owners[nid]:
                    raise ValueError("Illegal cross-region reference")
            for rid in region_refs[nid]:
                if rid not in graph.regions:
                    raise ValueError(f"Unknown region: {rid}")
        for reg in graph.regions.values():
            if reg.root_id not in parsed or owners[reg.root_id] != reg.id:
                raise ValueError("Invalid region root")
        emits = [
            nid
            for nid, n in parsed.items()
            if n.op_code == "EMI" and owners[nid] is None
        ]
        if len(emits) != 1:
            raise ValueError("Exactly one root Emit required")
        graph.root_id = emits[0]
        visiting, built = set(), {}

        def build(nid):
            if nid in visiting:
                raise ValueError("Cycle in graph or control regions")
            if nid in built:
                return built[nid]
            visiting.add(nid)
            d = parsed[nid]
            a, op = dict(d.attributes), d.op_code
            ins = [build(x) for x in refs[nid]]
            regions = [build(graph.regions[r].root_id) for r in region_refs[nid]]
            out = SemanticType.any()
            if op in ("FIL", "MAP", "RED", "JOI", "ITE"):
                for inp in ins:
                    if inp.output_type.kind not in (TypeKind.COLLECTION, TypeKind.ANY):
                        raise ValueError(f"{op} requires collection input")
            if op == "OBS":
                types = {
                    "collection": SemanticType.collection(SemanticType.any()),
                    "boolean": SemanticType.boolean(),
                    "numeric": SemanticType.numeric(),
                    "any": SemanticType.any(),
                }
                out = types[a.pop("type", "collection")]
            elif op == "LIT":
                v = a["value"]
                out = (
                    SemanticType.boolean()
                    if isinstance(v, bool)
                    else SemanticType.numeric()
                    if isinstance(v, (int, float))
                    else SemanticType.collection(SemanticType.any())
                    if isinstance(v, list)
                    else SemanticType.any()
                )
            elif op == "FIL":
                comparator = COMPARISONS.get(str(a["op"]).lower())
                if comparator is None:
                    raise ValueError("Invalid comparison")
                value, field_name = a["val"], a.get("field")
                a["predicate"] = lambda x, f=field_name, v=value, cmp=comparator: cmp(
                    x[f] if f else x, v
                )
                out = ins[0].output_type
            elif op == "MAP":
                a["fn"] = lambda x, f=a["field"]: x[f]
                out = SemanticType.collection(SemanticType.any())
            elif op == "RED":
                reducer = a["reducer"]
                if reducer not in ("sum", "count", "min", "max"):
                    raise ValueError("Invalid reducer")
                if reducer == "sum":
                    a["op"] = operator.add
                elif reducer == "count":
                    a["op"] = lambda acc, x: acc + 1
                elif reducer == "min":
                    a["op"] = lambda acc, x: x if acc is None else min(acc, x)
                else:
                    a["op"] = lambda acc, x: x if acc is None else max(acc, x)
                a["init"] = a.pop("initial", 0 if reducer in ("sum", "count") else None)
                out = SemanticType.numeric()
            elif op == "JOI":
                a["left_key"] = a["right_key"] = a.pop("on")
                out = SemanticType.collection(SemanticType.any())
            elif op == "BRA":
                if ins[0].output_type.kind not in (TypeKind.BOOLEAN, TypeKind.ANY):
                    raise ValueError("Branch requires boolean condition")
                if not regions[0].output_type.is_compatible_with(
                    regions[1].output_type
                ):
                    raise ValueError("Branch region type mismatch")
                out = regions[0].output_type
            elif op == "ITE":
                a["init"] = a.pop("initial")
                out = regions[0].output_type
            elif op == "CHO":
                if a.get("policy", "greedy") not in ("greedy", "bounded_lookahead"):
                    raise ValueError("Invalid Choose policy")
            elif op == "EMI":
                out = ins[0].output_type
            for key in ("in", "left", "right"):
                a.pop(key, None)
            if op == "UPD":
                a.pop("prior")
                a.pop("evidence")
            ir = IRNode(nid, _OP_MAP[op], refs[nid], a, out)
            built[nid] = ir
            visiting.remove(nid)
            if owners[nid] is None:
                graph.add_node(ir)
            else:
                graph.regions[owners[nid]].add_node(ir)
            return ir

        build(graph.root_id)
        if set(built) != set(parsed):
            raise ValueError("Unreachable nodes or multiple roots")
        graph.root_id = emits[0]
        return DSLCompileResult(
            True, graph, OutcomeContract(contract_type=contract_type)
        )
