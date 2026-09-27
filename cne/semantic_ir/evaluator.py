"""
CNE Deterministic Semantic IR Evaluator.
Executes typed Semantic IR graphs deterministically.
CRITICAL SAFETY INVARIANT: Branch and Iterate are LAZY control regions.
Unselected regions MUST NEVER execute.
Tracks execution trace and dependencies for selective invalidation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from cne.effects.effect_set import Effect, EffectSet
from cne.semantic_ir.nodes import IRNode, OpKind, SemanticIRGraph, SemanticRegion
from cne.semantic_ir.types import DependencyKey


@dataclass
class ExecutionContext:
    values: Dict[str, Any] = field(default_factory=dict)
    observed_dependencies: List[DependencyKey] = field(default_factory=list)
    executed_nodes: List[str] = field(default_factory=list)
    runtime_effects: EffectSet = field(default_factory=EffectSet.pure)
    environment: Dict[str, Any] = field(default_factory=dict)
    tools: Dict[str, Callable[..., Any]] = field(default_factory=dict)


class SemanticEvaluator:
    """
    Hardware-agnostic, deterministic executor for Semantic IR.
    """
    def __init__(self, tools: Optional[Dict[str, Callable[..., Any]]] = None):
        self.tools = tools or {}

    @staticmethod
    def compute_reachable_nodes(graph: SemanticIRGraph) -> Set[str]:
        """
        Computes the set of nodes reachable from root_id or containing
        mandatory external side-effects (requires_execution()).
        Dead work not in this set is skipped during evaluation.
        """
        cached = getattr(graph, "_cached_reachable", None)
        if cached is not None:
            return cached

        if not graph.nodes:
            return set()
        if not graph.root_id or graph.root_id not in graph.nodes:
            return set(graph.nodes.keys())

        reachable: Set[str] = set()
        queue: List[str] = [graph.root_id]

        for nid, node in graph.nodes.items():
            imm = node.get_immediate_effects()
            if imm.contains(Effect.WriteExternal) or imm.contains(Effect.Interactive):
                queue.append(nid)

        while queue:
            curr = queue.pop()
            if curr not in reachable and curr in graph.nodes:
                reachable.add(curr)
                queue.extend(graph.nodes[curr].inputs)

        graph._cached_reachable = reachable
        return reachable

    def execute(
        self,
        graph: SemanticIRGraph,
        initial_env: Optional[Dict[str, Any]] = None,
        physical_plan: Optional[Any] = None
    ) -> Tuple[Any, ExecutionContext]:
        ctx = ExecutionContext(
            environment=dict(initial_env or {}),
            tools=dict(self.tools)
        )
        if physical_plan is not None:
            ctx.environment["_physical_plan"] = physical_plan
        reachable = self.compute_reachable_nodes(graph)
        order = graph.topological_order()

        for nid in order:
            if nid not in reachable:
                continue
            if nid in ctx.values:
                continue
            self._evaluate_node(graph.nodes[nid], graph, ctx)

        final_val = ctx.values.get(graph.root_id)
        return final_val, ctx

    def _evaluate_node(self, node: IRNode, graph: SemanticIRGraph, ctx: ExecutionContext) -> Any:
        ctx.executed_nodes.append(node.id)
        ctx.runtime_effects = ctx.runtime_effects.union(node.get_immediate_effects())

        val = None

        if node.op == OpKind.LITERAL:
            val = node.attributes.get("value")

        elif node.op == OpKind.OBSERVE:
            source = node.attributes.get("source", "")
            key = node.attributes.get("key")
            granularity = node.attributes.get("granularity", "key" if key else "source")
            field_name = node.attributes.get("field")
            range_bounds = node.attributes.get("range_bounds")
            predicate_desc = node.attributes.get("predicate_desc")

            # Record mandatory dependency identity
            dep_key = DependencyKey(
                source=source,
                granularity=granularity,
                key=key,
                field_name=field_name,
                range_bounds=range_bounds,
                predicate_desc=predicate_desc
            )
            ctx.observed_dependencies.append(dep_key)

            # Retrieve from environment
            src_obj = ctx.environment.get(source)
            if key is not None and isinstance(src_obj, dict):
                val = src_obj.get(key)
            elif key is not None and isinstance(src_obj, (list, tuple)) and isinstance(key, int):
                val = src_obj[key] if 0 <= key < len(src_obj) else None
            else:
                val = src_obj

        elif node.op == OpKind.MAP:
            fn = node.attributes.get("fn")
            in_val = ctx.values.get(node.inputs[0]) if node.inputs else []
            if fn:
                if isinstance(in_val, list):
                    val = [fn(x) for x in in_val]
                elif in_val is not None:
                    val = fn(in_val)
                else:
                    val = fn(None)
            else:
                val = list(in_val) if isinstance(in_val, (list, tuple)) else in_val

        elif node.op == OpKind.FILTER:
            predicate = node.attributes.get("predicate")
            in_val = ctx.values.get(node.inputs[0]) if node.inputs else []
            if isinstance(in_val, list):
                val = [x for x in in_val if predicate(x)] if predicate else list(in_val)
            elif in_val is not None:
                val = in_val if (not predicate or predicate(in_val)) else None
            else:
                val = []

        elif node.op == OpKind.REDUCE:
            op_fn = node.attributes.get("op")
            init_val = node.attributes.get("init")
            in_val = ctx.values.get(node.inputs[0]) if node.inputs else []
            acc = init_val
            if op_fn and isinstance(in_val, (list, tuple)):
                for x in in_val:
                    acc = op_fn(acc, x)
            val = acc

        elif node.op == OpKind.JOIN:
            left_raw = ctx.values.get(node.inputs[0]) if node.inputs else []
            right_raw = ctx.values.get(node.inputs[1]) if len(node.inputs) > 1 else []
            left_val = left_raw if isinstance(left_raw, list) else ([left_raw] if left_raw is not None else [])
            right_val = right_raw if isinstance(right_raw, list) else ([right_raw] if right_raw is not None else [])
            on_fn = node.attributes.get("on")
            left_key = node.attributes.get("left_key")
            right_key = node.attributes.get("right_key")

            res = []
            if on_fn:
                for l in left_val:
                    for r in right_val:
                        if on_fn(l, r):
                            res.append((l, r))
            elif left_key and right_key:
                # Relational equijoin
                right_lookup: Dict[Any, List[Any]] = {}
                for r in right_val:
                    rk = r.get(right_key) if isinstance(r, dict) else getattr(r, right_key, None)
                    right_lookup.setdefault(rk, []).append(r)
                for l in left_val:
                    lk = l.get(left_key) if isinstance(l, dict) else getattr(l, left_key, None)
                    for r in right_lookup.get(lk, []):
                        merged = {}
                        if isinstance(l, dict): merged.update(l)
                        if isinstance(r, dict): merged.update(r)
                        res.append(merged if merged else (l, r))
            else:
                # Cartesian product
                for l in left_val:
                    for r in right_val:
                        res.append((l, r))
            val = res

        elif node.op == OpKind.BRANCH:
            # LAZY CONTROL REGION: only evaluate the selected region!
            cond_val = bool(ctx.values.get(node.inputs[0]))
            then_reg_id = node.attributes.get("then_region")
            else_reg_id = node.attributes.get("else_region")

            chosen_reg_id = then_reg_id if cond_val else else_reg_id
            if isinstance(chosen_reg_id, SemanticRegion):
                val = self._evaluate_region(chosen_reg_id, graph, ctx)
            elif chosen_reg_id and isinstance(chosen_reg_id, str) and chosen_reg_id in graph.regions:
                reg = graph.regions[chosen_reg_id]
                val = self._evaluate_region(reg, graph, ctx)
            else:
                val = cond_val

        elif node.op == OpKind.ITERATE:
            # LAZY CONTROL REGION
            items_input = node.inputs[0] if node.inputs else None
            items = ctx.values.get(items_input, []) if items_input else node.attributes.get("items", [])
            init_val = node.attributes.get("init")
            step_reg_id = node.attributes.get("step_region")
            step_fn = node.attributes.get("step_fn")
            stop_condition = node.attributes.get("stop_condition")

            acc = init_val
            reg = None
            if isinstance(step_reg_id, SemanticRegion):
                reg = step_reg_id
            elif step_reg_id and isinstance(step_reg_id, str) and step_reg_id in graph.regions:
                reg = graph.regions[step_reg_id]

            if reg:
                for item in items:
                    ctx.environment["_loop_item"] = item
                    ctx.environment["_loop_acc"] = acc
                    acc = self._evaluate_region(reg, graph, ctx)
                    if stop_condition and stop_condition(acc):
                        break
            elif step_fn:
                for item in items:
                    acc = step_fn(acc, item)
                    if stop_condition and stop_condition(acc):
                        break
            val = acc

        elif node.op == OpKind.UPDATE:
            # Finite Bayesian belief update: N <= 50, O(N) deterministic
            prior = node.attributes.get("prior")
            evidence = node.attributes.get("evidence")
            if prior is not None:
                if evidence is None and node.inputs:
                    evidence = ctx.values.get(node.inputs[0])
            else:
                if node.inputs:
                    prior = ctx.values.get(node.inputs[0])
                if len(node.inputs) > 1:
                    evidence = ctx.values.get(node.inputs[1])
            likelihood_fn = node.attributes.get("likelihood_fn")

            val = self._bayesian_update(prior, evidence, likelihood_fn)

        elif node.op == OpKind.CHOOSE:
            inp_val = ctx.values.get(node.inputs[0]) if node.inputs else None
            if isinstance(inp_val, list):
                actions = inp_val
                belief = node.attributes.get("belief", {})
            elif isinstance(inp_val, dict):
                belief = inp_val
                actions = node.attributes.get("actions", [])
            else:
                belief = node.attributes.get("belief", {})
                actions = node.attributes.get("actions", [])

            budget = node.attributes.get("budget", {})
            utility_fn = node.attributes.get("utility_fn")
            cost_fn = node.attributes.get("cost_fn")
            policy_type = node.attributes.get("policy", "greedy")
            lookahead_depth = node.attributes.get("lookahead_depth", 2)

            if policy_type == "bounded_lookahead" or node.attributes.get("lookahead", False):
                from cne.optimizer.runtime.choose import BoundedLookaheadPolicy
                u_fn = utility_fn if utility_fn else (lambda act, b: act.get("expected_utility", 0.0))
                val = BoundedLookaheadPolicy.select_first_action(
                    belief=belief,
                    actions=actions,
                    budget=budget,
                    utility_fn=u_fn,
                    depth=lookahead_depth
                )
            else:
                val = self._choose_action(belief, actions, budget, utility_fn, cost_fn)

        elif node.op == OpKind.CALL:
            target = node.attributes.get("target")
            args = [ctx.values.get(inp) for inp in node.inputs]
            kwargs = node.attributes.get("kwargs", {})
            fn = node.attributes.get("fn") or (ctx.tools.get(target) if target else None)
            if fn:
                val = fn(*args, **kwargs)
            else:
                val = None

        elif node.op == OpKind.EMIT:
            val = ctx.values.get(node.inputs[0]) if node.inputs else node.attributes.get("value")

        ctx.values[node.id] = val
        return val

    def _evaluate_region(self, region: SemanticRegion, graph: SemanticIRGraph, ctx: ExecutionContext) -> Any:
        order = []
        visited = set()

        def dfs(nid: str):
            if nid in visited:
                return
            visited.add(nid)
            n = region.nodes.get(nid)
            if n:
                for inp in n.inputs:
                    if inp in region.nodes:
                        dfs(inp)
                order.append(nid)

        for nid in region.nodes:
            dfs(nid)

        for nid in order:
            if nid not in ctx.values:
                self._evaluate_node(region.nodes[nid], graph, ctx)

        return ctx.values.get(region.root_id)

    @staticmethod
    def _bayesian_update(prior: Dict[str, float], evidence: Any, likelihood_fn: Optional[Callable[[str, Any], float]]) -> Dict[str, float]:
        """
        Exact deterministic finite Bayesian belief update:
        P(h|e) = P(e|h) * P(h) / sum_{h'} P(e|h') * P(h')
        N <= 50, O(N).
        """
        if not prior:
            return {}
        if not likelihood_fn:
            return dict(prior)

        unnormalized = {}
        total = 0.0
        for h, p in prior.items():
            lh = float(likelihood_fn(h, evidence))
            post = p * lh
            unnormalized[h] = post
            total += post

        if total <= 1e-12:
            # Degenerate case: uniform over hypothesis space
            k = len(prior)
            return {h: 1.0 / k for h in prior}

        return {h: round(post / total, 8) for h, post in unnormalized.items()}

    @staticmethod
    def _choose_action(belief: Dict[str, float], actions: List[Dict[str, Any]], budget: Dict[str, float],
                       utility_fn: Optional[Callable[[Dict[str, Any], Dict[str, float]], float]],
                       cost_fn: Optional[Callable[[Dict[str, Any]], Dict[str, float]]]) -> Optional[Dict[str, Any]]:
        """
        Decision rule: a* = argmax E[Delta U(a)] subject to C_i(a) <= B_i.
        """
        best_action = None
        best_delta_u = -float("inf")

        for act in actions:
            # Check budget constraints: latency, energy, memory, CPU, thermal
            costs = cost_fn(act) if cost_fn else act.get("cost", {})
            feasible = True
            for resource, limit in budget.items():
                if costs.get(resource, 0.0) > limit:
                    feasible = False
                    break
            if not feasible:
                continue

            # Expected delta utility
            expected_du = utility_fn(act, belief) if utility_fn else act.get("expected_utility", 0.0)
            if expected_du > best_delta_u:
                best_delta_u = expected_du
                best_action = act

        return best_action
