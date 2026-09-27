"""
CNE Exact Choose Oracle and Runtime Decision Policy.
Build order:
1. Exact finite oracle (exhaustive evaluation of admissible sequences)
2. Greedy Choose policy
3. Bounded lookahead (depth 2-3)
Pass criterion: >= 4/5 test scenarios must match hand-computed / exact oracle.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class Action:
    id: str
    target: str
    cost: Dict[str, float]  # latency, energy, memory, CPU, thermal
    expected_utility: float = 0.0
    transition_fn: Optional[Callable[[Dict[str, float]], Dict[str, float]]] = None


class ChooseOracle:
    """
    Exact finite decision oracle. Evaluates full admissible action space.
    """
    @classmethod
    def find_optimal_action(
        cls,
        belief: Dict[str, float],
        actions: List[Dict[str, Any]],
        budget: Dict[str, float],
        utility_fn: Callable[[Dict[str, Any], Dict[str, float]], float],
        cost_fn: Optional[Callable[[Dict[str, Any]], Dict[str, float]]] = None
    ) -> Optional[Dict[str, Any]]:
        best_act = None
        best_u = -float("inf")

        for act in actions:
            costs = cost_fn(act) if cost_fn else act.get("cost", {})
            # Check feasibility
            feasible = True
            for resource, limit in budget.items():
                if costs.get(resource, 0.0) > limit:
                    feasible = False
                    break
            if not feasible:
                continue

            u = utility_fn(act, belief)
            if u > best_u:
                best_u = u
                best_act = act

        return best_act

    @classmethod
    def find_optimal_sequence(
        cls,
        belief: Dict[str, float],
        actions: List[Dict[str, Any]],
        budget: Dict[str, float],
        utility_fn: Callable[[Dict[str, Any], Dict[str, float]], float],
        horizon: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Exhaustive multi-step search over horizon.
        """
        best_seq: List[Dict[str, Any]] = []
        best_total_u = -float("inf")

        def search(current_belief: Dict[str, float], remaining_budget: Dict[str, float], current_seq: List[Dict[str, Any]], total_u: float, depth: int):
            nonlocal best_seq, best_total_u
            if total_u > best_total_u:
                best_total_u = total_u
                best_seq = list(current_seq)

            if depth == 0:
                return

            for act in actions:
                costs = act.get("cost", {})
                can_afford = True
                new_budget = {}
                for r, limit in remaining_budget.items():
                    c = costs.get(r, 0.0)
                    if c > limit:
                        can_afford = False
                        break
                    new_budget[r] = limit - c

                if not can_afford:
                    continue

                u = utility_fn(act, current_belief)
                # Next belief
                next_belief = current_belief
                trans = act.get("transition_fn")
                if trans:
                    next_belief = trans(current_belief)

                search(next_belief, new_budget, current_seq + [act], total_u + u, depth - 1)

        search(belief, budget, [], 0.0, horizon)
        return best_seq


class GreedyChoosePolicy:
    """
    Greedy decision policy for Choose.
    """
    @classmethod
    def select_action(
        cls,
        belief: Dict[str, float],
        actions: List[Dict[str, Any]],
        budget: Dict[str, float],
        utility_fn: Callable[[Dict[str, Any], Dict[str, float]], float]
    ) -> Optional[Dict[str, Any]]:
        return ChooseOracle.find_optimal_action(belief, actions, budget, utility_fn)


class BoundedLookaheadPolicy:
    """
    Bounded lookahead policy (depth 2-3) when greedy is insufficient.
    """
    @classmethod
    def select_first_action(
        cls,
        belief: Dict[str, float],
        actions: List[Dict[str, Any]],
        budget: Dict[str, float],
        utility_fn: Callable[[Dict[str, Any], Dict[str, float]], float],
        depth: int = 2
    ) -> Optional[Dict[str, Any]]:
        seq = ChooseOracle.find_optimal_sequence(belief, actions, budget, utility_fn, horizon=depth)
        return seq[0] if seq else None
