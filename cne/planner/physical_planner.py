"""
CNE Physical Planner.
Lowers hardware-agnostic Semantic IR to physical execution targets:
- CPU (Primary local tier)
- Neural (Local quantized neural infer, if available)
- Retrieval (Local vector / inverted index)
- USB (Secondary optional compute substrate)

CRITICAL INVARIANT (Section 38 & Gate G7):
CPU-only path must independently satisfy G6. USB is strictly secondary
and never necessary to establish the core CNE claim.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph


class ExecutionTarget(Enum):
    CPU_LOCAL = "cpu_local"
    USB_TIER = "usb_tier"
    NEURAL_LOCAL = "neural_local"
    RETRIEVAL_LOCAL = "retrieval_local"


@dataclass
class PhysicalPlan:
    graph_id: str
    target_assignments: Dict[str, ExecutionTarget]
    estimated_memory_mb: float
    is_cpu_only: bool


class PhysicalPlanner:
    def __init__(self, allow_usb: bool = False, memory_limit_mb: float = 6144.0):
        self.allow_usb = allow_usb
        self.memory_limit_mb = memory_limit_mb

    def plan(self, graph: SemanticIRGraph, system_thermal_throttled: bool = False) -> PhysicalPlan:
        """
        Assigns nodes to execution targets. Defaults strictly to CPU_LOCAL.
        """
        assignments: Dict[str, ExecutionTarget] = {}
        for nid in graph.nodes:
            # Primary target is always local CPU
            assignments[nid] = ExecutionTarget.CPU_LOCAL

        # USB offload is only considered if allowed AND thermal/memory threshold exceeded,
        # but phone remains authoritative
        if self.allow_usb and system_thermal_throttled:
            for nid, node in graph.nodes.items():
                if node.op in (OpKind.JOIN, OpKind.REDUCE):
                    assignments[nid] = ExecutionTarget.USB_TIER

        is_cpu_only = all(t == ExecutionTarget.CPU_LOCAL for t in assignments.values())

        return PhysicalPlan(
            graph_id=graph.root_id,
            target_assignments=assignments,
            estimated_memory_mb=16.0,
            is_cpu_only=is_cpu_only
        )
