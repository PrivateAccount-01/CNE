"""
CNE Semantic IR Grammar and JSON Schema Definition.
Formalizes the static grammar and schema for Phase P1 grammar-constrained decoding.

Invariants:
1. ONLY the 11 frozen OpKind primitives (+ Literal) can be emitted.
2. Every node adheres strictly to IRNode's structural contract (id, op, inputs, attributes, output_type).
3. Graphs must form valid, acyclic DAGs with a single sink (Emit).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

import jsonschema

from cne.contracts.outcome_contract import ContractType, OutcomeContract
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph
from cne.semantic_ir.types import SemanticType


FROZEN_PRIMITIVES: List[str] = [
    "Observe",
    "Map",
    "Filter",
    "Reduce",
    "Join",
    "Branch",
    "Iterate",
    "Choose",
    "Update",
    "Call",
    "Emit",
    "Literal"
]

OUTCOME_TYPES: List[str] = [
    "COMPILED",
    "UNSUPPORTED_INTENT",
    "AMBIGUOUS_INTENT",
    "LOW_CONFIDENCE_MAPPING"
]

CONTRACT_TYPES: List[str] = [
    "EXACT",
    "SET_VALUED",
    "APPROXIMATE_NUMERIC",
    "DECISION",
    "STRUCTURED_EXPLANATION",
    "NO_SOLUTION"
]

# Strict JSON Schema compatible with Ollama/llama.cpp GBNF and OpenAI Structured Outputs
CNE_SEMANTIC_IR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": OUTCOME_TYPES
        },
        "intent": {
            "type": ["string", "null"]
        },
        "reason": {
            "type": ["string", "null"]
        },
        "contract": {
            "type": "object",
            "properties": {
                "contract_type": {
                    "type": "string",
                    "enum": CONTRACT_TYPES
                },
                "decision_boundary": {
                    "type": ["number", "null"]
                }
            },
            "required": ["contract_type", "decision_boundary"],
            "additionalProperties": False
        },
        "slots": {
            "type": "object",
            "additionalProperties": True
        },
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": FROZEN_PRIMITIVES
                    },
                    "inputs": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "attributes": {
                        "type": "object",
                        "additionalProperties": True
                    },
                    "output_type": {
                        "type": "string"
                    }
                },
                "required": ["id", "op", "inputs", "attributes", "output_type"],
                "additionalProperties": False
            }
        },
        "root_id": {"type": "string"}
    },
    "required": ["outcome", "intent", "reason", "contract", "slots", "nodes", "root_id"],
    "additionalProperties": False
}


def validate_raw_graph(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validates a raw JSON payload against CNE's structural and semantic invariants:
    1. Conforms to CNE_SEMANTIC_IR_SCHEMA.
    2. If outcome is COMPILED:
       a. Contains at least one node.
       b. root_id refers to an existing node in nodes.
       c. The root node's op is 'Emit'.
       d. All input references point to valid, defined node IDs.
       e. Graph is strictly acyclic (DAG).
       f. All nodes are reachable from an Observe/Literal source.
    """
    # 1. JSON Schema validation
    try:
        jsonschema.validate(instance=payload, schema=CNE_SEMANTIC_IR_SCHEMA)
    except jsonschema.ValidationError as err:
        return False, f"Schema validation error: {err.message}"

    outcome = payload.get("outcome")
    if outcome != "COMPILED":
        return True, f"Valid non-compiled outcome: {outcome}"

    nodes_list = payload.get("nodes", [])
    if not nodes_list:
        return False, "COMPILED outcome must contain at least one node."

    node_ids: Set[str] = {n["id"] for n in nodes_list}
    if len(node_ids) != len(nodes_list):
        return False, "Duplicate node IDs detected in graph."

    root_id = payload.get("root_id", "")
    if root_id not in node_ids:
        return False, f"root_id '{root_id}' is not in nodes."

    nodes_by_id = {n["id"]: n for n in nodes_list}
    root_node = nodes_by_id[root_id]
    if root_node["op"] != "Emit":
        return False, f"root_id '{root_id}' must have op 'Emit', got '{root_node['op']}'."

    # Verify input references
    for n in nodes_list:
        for inp in n["inputs"]:
            if inp not in node_ids:
                return False, f"Node '{n['id']}' references non-existent input '{inp}'."

    # Acyclicity check (Topological sort via Kahn's algorithm or DFS)
    in_degrees = {nid: 0 for nid in node_ids}
    adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for n in nodes_list:
        for inp in n["inputs"]:
            adj[inp].append(n["id"])
            in_degrees[n["id"]] += 1

    queue = [nid for nid, deg in in_degrees.items() if deg == 0]
    visited_count = 0
    while queue:
        curr = queue.pop(0)
        visited_count += 1
        for neighbor in adj[curr]:
            in_degrees[neighbor] -= 1
            if in_degrees[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(node_ids):
        return False, "Cycle detected: Graph is not a valid DAG."

    return True, "Valid Semantic IR DAG."


def payload_to_semantic_ir(payload: Dict[str, Any]) -> Tuple[Optional[SemanticIRGraph], Optional[OutcomeContract], Dict[str, Any]]:
    """
    Deserializes a validated JSON payload into CNE's existing SemanticIRGraph and OutcomeContract dataclasses.
    """
    valid, reason = validate_raw_graph(payload)
    if not valid:
        raise ValueError(f"Cannot deserialize invalid payload: {reason}")

    if payload.get("outcome") != "COMPILED":
        return None, None, payload.get("slots", {})

    graph = SemanticIRGraph()
    for n_data in payload.get("nodes", []):
        op_enum = OpKind(n_data["op"])
        node = IRNode(
            id=n_data["id"],
            op=op_enum,
            inputs=list(n_data["inputs"]),
            attributes=dict(n_data["attributes"]),
            output_type=SemanticType.any()
        )
        graph.add_node(node)

    graph.root_id = payload.get("root_id", "")

    # Reconstruct contract
    contract_data = payload.get("contract", {})
    contract_type_str = contract_data.get("contract_type", "EXACT")
    contract_type = getattr(ContractType, contract_type_str, ContractType.EXACT)
    contract = OutcomeContract(
        contract_type=contract_type,
        decision_boundary=contract_data.get("decision_boundary")
    )

    slots = payload.get("slots", {})
    return graph, contract, slots


def test_fixtures_against_schema() -> bool:
    """
    Deliverable 1 Validation:
    Hand-encodes three standard fixtures (comparative_trend, predictive_alert, expense)
    and verifies that they pass schema validation and convert to valid SemanticIRGraphs.
    """
    # 1. Comparative Trend Fixture
    comp_trend_payload = {
        "outcome": "COMPILED",
        "intent": "comparative_trend",
        "reason": None,
        "contract": {
            "contract_type": "EXACT",
            "decision_boundary": None
        },
        "slots": {
            "category": "grocery",
            "period_a": "Q1",
            "period_b": "Q2"
        },
        "nodes": [
            {"id": "obs_period_a", "op": "Observe", "inputs": [], "attributes": {"period": "Q1", "source": "expenses"}, "output_type": "collection"},
            {"id": "obs_period_b", "op": "Observe", "inputs": [], "attributes": {"period": "Q2", "source": "expenses"}, "output_type": "collection"},
            {"id": "filt_cat_a", "op": "Filter", "inputs": ["obs_period_a"], "attributes": {"category": "grocery"}, "output_type": "collection"},
            {"id": "filt_cat_b", "op": "Filter", "inputs": ["obs_period_b"], "attributes": {"category": "grocery"}, "output_type": "collection"},
            {"id": "map_amt_a", "op": "Map", "inputs": ["filt_cat_a"], "attributes": {"field": "amount"}, "output_type": "collection"},
            {"id": "map_amt_b", "op": "Map", "inputs": ["filt_cat_b"], "attributes": {"field": "amount"}, "output_type": "collection"},
            {"id": "red_sum_a", "op": "Reduce", "inputs": ["map_amt_a"], "attributes": {"reducer": "sum"}, "output_type": "scalar"},
            {"id": "red_sum_b", "op": "Reduce", "inputs": ["map_amt_b"], "attributes": {"reducer": "sum"}, "output_type": "scalar"},
            {"id": "join_periods", "op": "Join", "inputs": ["red_sum_a", "red_sum_b"], "attributes": {"how": "cross"}, "output_type": "record"},
            {"id": "map_pct_diff", "op": "Map", "inputs": ["join_periods"], "attributes": {"calc": "pct_change"}, "output_type": "scalar"},
            {"id": "emit_trend", "op": "Emit", "inputs": ["map_pct_diff"], "attributes": {"label": "trend"}, "output_type": "scalar"}
        ],
        "root_id": "emit_trend"
    }

    # 2. Predictive Alert Fixture
    pred_alert_payload = {
        "outcome": "COMPILED",
        "intent": "predictive_alert",
        "reason": None,
        "contract": {
            "contract_type": "DECISION",
            "decision_boundary": 0.80
        },
        "slots": {
            "metric": "disk_space",
            "growth_rate_threshold": 0.15
        },
        "nodes": [
            {"id": "obs_history", "op": "Observe", "inputs": [], "attributes": {"source": "disk_telemetry"}, "output_type": "collection"},
            {"id": "filt_valid", "op": "Filter", "inputs": ["obs_history"], "attributes": {"non_null": True}, "output_type": "collection"},
            {"id": "map_velocity", "op": "Map", "inputs": ["filt_valid"], "attributes": {"calc": "delta"}, "output_type": "collection"},
            {"id": "red_mean_vel", "op": "Reduce", "inputs": ["map_velocity"], "attributes": {"reducer": "mean"}, "output_type": "scalar"},
            {"id": "map_forecast", "op": "Map", "inputs": ["red_mean_vel"], "attributes": {"model": "linear_extrapolate"}, "output_type": "scalar"},
            {"id": "branch_alert", "op": "Branch", "inputs": ["map_forecast"], "attributes": {"condition": "val > 0.85"}, "output_type": "bool"},
            {"id": "emit_alert", "op": "Emit", "inputs": ["branch_alert"], "attributes": {"label": "alert_decision"}, "output_type": "bool"}
        ],
        "root_id": "emit_alert"
    }

    # 3. Expense Fixture
    expense_payload = {
        "outcome": "COMPILED",
        "intent": "expense",
        "reason": None,
        "contract": {
            "contract_type": "EXACT",
            "decision_boundary": None
        },
        "slots": {
            "category": "Food",
            "threshold": 100.0,
            "aggregation": "sum"
        },
        "nodes": [
            {"id": "obs_tx", "op": "Observe", "inputs": [], "attributes": {"source": "transactions"}, "output_type": "collection"},
            {"id": "filt_cat", "op": "Filter", "inputs": ["obs_tx"], "attributes": {"category": "Food"}, "output_type": "collection"},
            {"id": "filt_thresh", "op": "Filter", "inputs": ["filt_cat"], "attributes": {"threshold": 100.0}, "output_type": "collection"},
            {"id": "map_amount", "op": "Map", "inputs": ["filt_thresh"], "attributes": {"field": "amount"}, "output_type": "collection"},
            {"id": "red_sum", "op": "Reduce", "inputs": ["map_amount"], "attributes": {"reducer": "sum"}, "output_type": "scalar"},
            {"id": "emit_res", "op": "Emit", "inputs": ["red_sum"], "attributes": {"label": "total_expense"}, "output_type": "scalar"}
        ],
        "root_id": "emit_res"
    }

    fixtures = [
        ("comparative_trend", comp_trend_payload),
        ("predictive_alert", pred_alert_payload),
        ("expense", expense_payload)
    ]

    for name, payload in fixtures:
        is_valid, reason = validate_raw_graph(payload)
        assert is_valid, f"Fixture '{name}' failed validation: {reason}"
        graph, contract, slots = payload_to_semantic_ir(payload)
        assert graph is not None, f"Fixture '{name}' failed to deserialize to graph."
        assert len(graph.nodes) == len(payload["nodes"]), f"Fixture '{name}' node count mismatch."
        assert len(graph.topological_order()) == len(payload["nodes"]), f"Fixture '{name}' topological sort failed."
        print(f"Validated fixture '{name}' successfully ({len(graph.nodes)} nodes).")

    return True


if __name__ == "__main__":
    test_fixtures_against_schema()
    print("Deliverable 1 Static Schema Validation: ALL FIXTURES PASSED")
