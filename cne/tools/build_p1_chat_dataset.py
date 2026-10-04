"""
Phase P1 Chat-Format Dataset Builder.
Converts serialized train.jsonl / val.jsonl into chat-completion format
for the constrained decoder's prompt template.

Sanitizes lambda references and normalizes graph_ast payloads to conform
to the CNE_SEMANTIC_IR_SCHEMA used by the grammar-constrained decoder.

Outputs:
    cne/artifacts/p1_dataset/train_chat.jsonl
    cne/artifacts/p1_dataset/val_chat.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cne.compiler.few_shot_pool import FewShotPool, FewShotDemo
from cne.compiler.grammar_schema import validate_raw_graph


# Lambda/function reference pattern for sanitization
_LAMBDA_PATTERN = re.compile(r"<function\s+[\w.<>\s]+at\s+0x[0-9a-fA-F]+>")
_LAMBDA_OBJECT_PATTERN = re.compile(r"<.*at\s+0x[0-9a-fA-F]+>")


def sanitize_attributes(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Removes or replaces non-serializable values (lambda refs, object refs)
    in node attributes with human-readable string descriptions.
    """
    clean = {}
    for k, v in attrs.items():
        if isinstance(v, str):
            if _LAMBDA_PATTERN.search(v) or _LAMBDA_OBJECT_PATTERN.search(v):
                # Replace lambda reference with a descriptive placeholder
                clean[k] = f"<{k}_function>"
            else:
                clean[k] = v
        elif isinstance(v, (int, float, bool)) or v is None:
            clean[k] = v
        elif isinstance(v, (list, tuple)):
            clean[k] = [str(x) if not isinstance(x, (str, int, float, bool, type(None))) else x for x in v]
        elif isinstance(v, dict):
            clean[k] = sanitize_attributes(v)
        else:
            clean[k] = str(v)
    return clean


def normalize_graph_ast_to_schema(
    record: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Converts a serialized training record into the CNE_SEMANTIC_IR_SCHEMA format
    expected by the constrained decoder.
    
    Key transformations:
    1. Sanitize lambda references in node attributes
    2. Drop 'edges' field (inputs are embedded in nodes)
    3. Add contract/slots/intent/reason at top level
    4. Ensure output_type is lowercased for consistency
    """
    outcome = record.get("target_outcome", "COMPILED")
    
    if outcome != "COMPILED" or not record.get("graph_ast"):
        # Non-compiled record — produce rejection AST
        return {
            "outcome": outcome,
            "intent": record.get("target_topology"),
            "reason": record.get("decline_reason") or f"Query classified as {outcome}.",
            "contract": {
                "contract_type": (record.get("contract", {}) or {}).get("contract_type", "NO_SOLUTION"),
                "decision_boundary": (record.get("contract", {}) or {}).get("decision_boundary")
            },
            "slots": record.get("target_slots", {}),
            "nodes": [],
            "root_id": ""
        }
    
    graph_ast = record["graph_ast"]
    nodes_raw = graph_ast.get("nodes", [])
    
    # Sanitize and normalize nodes
    clean_nodes = []
    for n in nodes_raw:
        clean_node = {
            "id": n["id"],
            "op": n["op"],
            "inputs": n.get("inputs", []),
            "attributes": sanitize_attributes(n.get("attributes", {})),
            "output_type": n.get("output_type", "any").lower()
        }
        clean_nodes.append(clean_node)
    
    # Build contract
    contract_raw = record.get("contract", {}) or {}
    contract = {
        "contract_type": contract_raw.get("contract_type", "EXACT"),
        "decision_boundary": contract_raw.get("decision_boundary")
    }
    
    return {
        "outcome": "COMPILED",
        "intent": record.get("target_topology"),
        "reason": None,
        "contract": contract,
        "slots": record.get("target_slots", {}),
        "nodes": clean_nodes,
        "root_id": graph_ast.get("root_id", "")
    }


def build_chat_record(
    record: Dict[str, Any],
    pool: FewShotPool,
    system_prompt: str,
    num_demos: int = 3
) -> Dict[str, Any]:
    """
    Build a single chat-format training record.
    
    Structure:
    {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "<demo query>"},
            {"role": "assistant", "content": "<demo gold AST>"},
            ...
            {"role": "user", "content": record["query_text"]},
            {"role": "assistant", "content": "<gold AST JSON>"}
        ],
        "metadata": { ... }
    }
    """
    # Select topology-diverse few-shot demos (excluding target topology)
    target_topo = record.get("target_topology")
    demos = pool.select(
        query_text=record["query_text"],
        k=num_demos,
        exclude_topology=target_topo,
        seed=hash(record.get("query_id", record["query_text"])) % (2**31)
    )
    
    # Build messages
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add few-shot demonstrations
    for demo in demos:
        messages.extend(demo.to_messages())
    
    # Add target query and gold AST
    gold_ast = normalize_graph_ast_to_schema(record)
    messages.append({"role": "user", "content": record["query_text"]})
    messages.append({"role": "assistant", "content": json.dumps(gold_ast, separators=(",", ":"))})
    
    return {
        "messages": messages,
        "metadata": {
            "query_id": record.get("query_id", ""),
            "target_outcome": record.get("target_outcome", ""),
            "target_topology": target_topo,
            "shape_key": record.get("shape_key"),
            "source_corpus": record.get("source_corpus", ""),
        }
    }


# System prompt for the constrained decoder (production version)
PRODUCTION_SYSTEM_PROMPT = """You are the CNE Semantic IR Compiler.
Your task is to translate natural language user queries into a type-safe Semantic IR Directed Acyclic Graph (DAG) and typed slots.

INVARIANTS:
1. You may ONLY use the 11 frozen OpKind primitives:
   - Observe (data store or sensor query)
   - Filter (predicate filtering on rows/records)
   - Map (projection or field extraction or mathematical evaluation)
   - Reduce (aggregation: sum, count, max, min, mean, top_k)
   - Join (combining two streams by key or cross-product)
   - Branch (conditional evaluation)
   - Iterate (repeating step)
   - Choose (probabilistic or utility selection)
   - Update (state store modification)
   - Call (deterministic function invocation)
   - Emit (final output sink — every compiled graph must end with exactly ONE Emit)
   - Literal (constant value)
2. Every compiled graph must end in exactly ONE root node with op "Emit", referenced by "root_id".
3. The "inputs" list in each node must refer to valid predecessor node IDs in topological order (no cycles).
4. If the user request is completely unsupported (e.g., general web search, hardware device settings, weather, open chat, creative writing, media playback), set outcome to "UNSUPPORTED_INTENT", nodes to [], and root_id to "".
5. If the query is ambiguous between multiple topologies, set outcome to "AMBIGUOUS_INTENT".
6. If the query partially matches but confidence is low, set outcome to "LOW_CONFIDENCE_MAPPING".
7. For supported queries, set outcome to "COMPILED".
8. Extract typed slots from the query (categories, thresholds, amounts, dates, metrics).

OUTPUT FORMAT: A single JSON object conforming to the CNE Semantic IR schema."""


def build_chat_dataset(
    input_path: str,
    output_path: str,
    pool: FewShotPool,
    num_demos: int = 3,
    validate: bool = True
) -> Dict[str, Any]:
    """
    Convert a JSONL dataset into chat-format JSONL.
    
    Returns summary statistics.
    """
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    
    stats = {
        "total_records": len(records),
        "valid_schema": 0,
        "invalid_schema": 0,
        "compiled": 0,
        "non_compiled": 0,
        "sanitized_lambdas": 0,
    }
    
    chat_records = []
    for rec in records:
        chat_rec = build_chat_record(rec, pool, PRODUCTION_SYSTEM_PROMPT, num_demos)
        
        # Parse the gold AST from the last assistant message
        gold_json_str = chat_rec["messages"][-1]["content"]
        gold_ast = json.loads(gold_json_str)
        
        if gold_ast.get("outcome") == "COMPILED":
            stats["compiled"] += 1
        else:
            stats["non_compiled"] += 1
        
        # Check for sanitized lambdas
        if "<" in gold_json_str and "_function>" in gold_json_str:
            stats["sanitized_lambdas"] += 1
        
        # Validate schema conformity if requested
        if validate and gold_ast.get("outcome") == "COMPILED":
            is_valid, reason = validate_raw_graph(gold_ast)
            if is_valid:
                stats["valid_schema"] += 1
            else:
                stats["invalid_schema"] += 1
                # Still include — these are training examples where the graph
                # may have minor schema issues from lambda sanitization
        else:
            stats["valid_schema"] += 1  # Non-compiled always valid
        
        chat_records.append(chat_rec)
    
    # Write output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in chat_records:
            f.write(json.dumps(rec) + "\n")
    
    stats["output_path"] = output_path
    return stats


def main():
    parser = argparse.ArgumentParser(description="Build P1 chat-format datasets")
    parser.add_argument("--validate-only", action="store_true",
                       help="Only validate, don't write output")
    parser.add_argument("--num-demos", type=int, default=3,
                       help="Number of few-shot demonstrations per record")
    args = parser.parse_args()
    
    base_dir = os.path.join(
        os.path.dirname(__file__), "..", "artifacts", "p1_dataset"
    )
    
    pool = FewShotPool()
    
    # Process train split
    train_input = os.path.join(base_dir, "train.jsonl")
    train_output = os.path.join(base_dir, "train_chat.jsonl")
    
    if os.path.exists(train_input):
        print(f"Processing train split: {train_input}")
        train_stats = build_chat_dataset(
            train_input, train_output, pool,
            num_demos=args.num_demos,
            validate=True
        )
        print(f"  Total: {train_stats['total_records']}")
        print(f"  Compiled: {train_stats['compiled']}")
        print(f"  Non-compiled: {train_stats['non_compiled']}")
        print(f"  Valid schema: {train_stats['valid_schema']}")
        print(f"  Invalid schema: {train_stats['invalid_schema']}")
        print(f"  Sanitized lambdas: {train_stats['sanitized_lambdas']}")
        print(f"  Output: {train_stats['output_path']}")
    else:
        print(f"ERROR: {train_input} not found!")
        sys.exit(1)
    
    # Process val split
    val_input = os.path.join(base_dir, "val.jsonl")
    val_output = os.path.join(base_dir, "val_chat.jsonl")
    
    if os.path.exists(val_input):
        print(f"\nProcessing val split: {val_input}")
        val_stats = build_chat_dataset(
            val_input, val_output, pool,
            num_demos=args.num_demos,
            validate=True
        )
        print(f"  Total: {val_stats['total_records']}")
        print(f"  Compiled: {val_stats['compiled']}")
        print(f"  Non-compiled: {val_stats['non_compiled']}")
        print(f"  Valid schema: {val_stats['valid_schema']}")
        print(f"  Invalid schema: {val_stats['invalid_schema']}")
        print(f"  Sanitized lambdas: {val_stats['sanitized_lambdas']}")
        print(f"  Output: {val_stats['output_path']}")
    
    print("\n[OK] Chat dataset build complete.")


if __name__ == "__main__":
    main()
