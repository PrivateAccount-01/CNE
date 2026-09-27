"""
CNE Policy State Projection.
Captures decision state for Choose: {belief, action_set, budget, contract_impact}.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PolicyState:
    belief: Dict[str, float]
    action_set: List[Dict[str, Any]]
    budget: Dict[str, float]  # latency, energy, memory, CPU, thermal
    contract_impact: Optional[Dict[str, Any]] = None

    def get_admissible_actions(self) -> List[Dict[str, Any]]:
        """
        Filter actions that satisfy all budget limits.
        """
        admissible = []
        for act in self.action_set:
            costs = act.get("cost", {})
            satisfies = True
            for resource, limit in self.budget.items():
                if costs.get(resource, 0.0) > limit:
                    satisfies = False
                    break
            if satisfies:
                admissible.append(act)
        return admissible
