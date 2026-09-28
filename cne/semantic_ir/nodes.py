"""
CNE Semantic IR Nodes.
Hardware-agnostic semantic primitives:
Observe, Map, Filter, Reduce, Join, Branch, Iterate, Choose, Update, Call, Emit.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union
from cne.effects.effect_set import Effect, EffectSet
from cne.semantic_ir.types import DependencyKey, SemanticType


class OpKind(Enum):
    OBSERVE = "Observe"
    MAP = "Map"
    FILTER = "Filter"
    REDUCE = "Reduce"
    JOIN = "Join"
    BRANCH = "Branch"
    ITERATE = "Iterate"
    CHOOSE = "Choose"
    UPDATE = "Update"
    CALL = "Call"
    EMIT = "Emit"
    # Literal/Constant node helper
    LITERAL = "Literal"


@dataclass
class IRNode:
    id: str
    op: OpKind
    inputs: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    output_type: SemanticType = field(default_factory=SemanticType.any)
    declared_effects: Optional[EffectSet] = None

    def get_immediate_effects(self) -> EffectSet:
        """
        Intrinsic effects of this operation, independent of inputs.
        """
        if self.declared_effects is not None:
            return self.declared_effects

        if self.op == OpKind.OBSERVE:
            return EffectSet.read_external()
        elif self.op == OpKind.CALL:
            # Must declare effects, defaults to read/write external if undeclared
            return EffectSet((Effect.ReadExternal, Effect.WriteExternal))
        elif self.op in (OpKind.MAP, OpKind.FILTER, OpKind.REDUCE):
            # Check if function passed in attributes has declared effects
            fn_effects = self.attributes.get("effects")
            if fn_effects and isinstance(fn_effects, EffectSet):
                return fn_effects
            return EffectSet.pure()
        elif self.op == OpKind.LITERAL:
            return EffectSet.pure()
        elif self.op == OpKind.EMIT:
            return EffectSet.pure()
        elif self.op in (OpKind.BRANCH, OpKind.ITERATE, OpKind.JOIN, OpKind.CHOOSE, OpKind.UPDATE):
            return EffectSet.pure()
        return EffectSet.pure()


@dataclass
class SemanticRegion:
    """
    A subgraph representing a lazy region (e.g. then_branch, else_branch, loop_body).
    """
    id: str
    nodes: Dict[str, IRNode] = field(default_factory=dict)
    root_id: str = ""

    def add_node(self, node: IRNode) -> None:
        self.nodes[node.id] = node
        if not self.root_id:
            self.root_id = node.id

    def get_static_effects(self, node_effects: Dict[str, EffectSet]) -> EffectSet:
        """
        Static conservative union of effects in this region.
        """
        eff = EffectSet.pure()
        for nid, node in self.nodes.items():
            eff = eff.union(node.get_immediate_effects())
            if nid in node_effects:
                eff = eff.union(node_effects[nid])
        return eff


@dataclass
class SemanticIRGraph:
    """
    A complete hardware-agnostic Semantic IR graph.
    """
    nodes: Dict[str, IRNode] = field(default_factory=dict)
    regions: Dict[str, SemanticRegion] = field(default_factory=dict)
    root_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def invalidate_structural_cache(self) -> None:
        """
        Invalidates all cached structural derivations (topological order,
        shape hash, descriptors, reachability, execution policy, physical plan) when graph topology mutates (Doc #10).
        """
        self._cached_topo = None
        self._cached_descriptors = None
        self._cached_shape_hash = None
        self._cached_reachable = None
        self._cached_execution_policy = None
        self._cached_observed_sources = None
        self._cached_observe_nodes = None
        self._cached_physical_plan = None
        self._cached_cost_structure = None
        self._cached_static_opt_res = None

    def get_observed_sources(self) -> List[str]:
        cached = getattr(self, "_cached_observed_sources", None)
        if cached is None:
            sources = []
            for n in self.nodes.values():
                if n.op == OpKind.OBSERVE:
                    src = n.attributes.get("source")
                    if src:
                        sources.append(src)
            self._cached_observed_sources = sources
            return sources
        return cached

    def get_observe_nodes(self) -> List[IRNode]:
        cached = getattr(self, "_cached_observe_nodes", None)
        if cached is None:
            obs = [n for n in self.get_all_nodes().values() if n.op == OpKind.OBSERVE]
            self._cached_observe_nodes = obs
            return obs
        return cached

    def add_node(self, node: IRNode) -> None:
        self.nodes[node.id] = node
        if not self.root_id:
            self.root_id = node.id
        self.invalidate_structural_cache()

    def remove_node(self, node_id: str) -> None:
        if node_id in self.nodes:
            del self.nodes[node_id]
            self.invalidate_structural_cache()

    def add_region(self, region: SemanticRegion) -> None:
        self.regions[region.id] = region
        self.invalidate_structural_cache()

    def get_node(self, node_id: str) -> Optional[IRNode]:
        if node_id in self.nodes:
            return self.nodes[node_id]
        for region in self.regions.values():
            if node_id in region.nodes:
                return region.nodes[node_id]
        return None

    def get_all_nodes(self) -> Dict[str, IRNode]:
        all_nodes = dict(self.nodes)
        for r in self.regions.values():
            all_nodes.update(r.nodes)
        return all_nodes

    def topological_order(self) -> List[str]:
        """
        Topological order of root-level nodes.
        """
        cached = getattr(self, "_cached_topo", None)
        if cached is not None and len(cached) == len(self.nodes):
            return cached

        visited = set()
        order = []

        def dfs(nid: str):
            if nid in visited:
                return
            visited.add(nid)
            node = self.nodes.get(nid)
            if node:
                for inp in node.inputs:
                    if inp in self.nodes:
                        dfs(inp)
                order.append(nid)

        for nid in self.nodes:
            dfs(nid)
        self._cached_topo = order
        return order

    def clone(self) -> SemanticIRGraph:
        """
        Fast structural clone without python's slow deepcopy overhead.
        """
        cloned_nodes = {
            nid: IRNode(
                id=n.id,
                op=n.op,
                inputs=list(n.inputs),
                attributes=dict(n.attributes),
                output_type=n.output_type,
                declared_effects=n.declared_effects
            )
            for nid, n in self.nodes.items()
        }
        cloned_regions = {}
        for rid, reg in self.regions.items():
            cr = SemanticRegion(id=reg.id, root_id=reg.root_id)
            for rnid, rn in reg.nodes.items():
                cr.nodes[rnid] = IRNode(
                    id=rn.id,
                    op=rn.op,
                    inputs=list(rn.inputs),
                    attributes=dict(rn.attributes),
                    output_type=rn.output_type,
                    declared_effects=rn.declared_effects
                )
            cloned_regions[rid] = cr

        return SemanticIRGraph(
            nodes=cloned_nodes,
            regions=cloned_regions,
            root_id=self.root_id,
            metadata=dict(self.metadata)
        )
