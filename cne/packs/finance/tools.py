"""
Finance Reference Capability Pack — Deterministic Tools.
Performs deterministic filtering and calculation. Never delegates arithmetic to an LLM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def filter_transactions(
    transactions: List[Dict[str, Any]],
    category: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    account: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Deterministic filtering over transaction records."""
    filtered = []
    for tx in transactions:
        if category and tx.get("category", "").lower() != category.lower():
            continue
        amt = float(tx.get("amount", 0.0))
        if min_amount is not None and amt <= min_amount:
            continue
        if max_amount is not None and amt >= max_amount:
            continue
        if account and tx.get("account", "").lower() != account.lower():
            continue
        filtered.append(tx)
    return filtered


def calculate_total(
    transactions: List[Dict[str, Any]],
    aggregation: str = "sum"
) -> float:
    """Deterministic mathematical aggregation."""
    if not transactions:
        return 0.0
    amounts = [float(tx.get("amount", 0.0)) for tx in transactions]
    if aggregation == "sum":
        return round(sum(amounts), 2)
    elif aggregation == "avg":
        return round(sum(amounts) / len(amounts), 2)
    elif aggregation == "count":
        return float(len(amounts))
    elif aggregation == "min":
        return round(min(amounts), 2)
    elif aggregation == "max":
        return round(max(amounts), 2)
    else:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
