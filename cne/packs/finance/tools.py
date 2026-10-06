"""
Finance Reference Capability Pack — Deterministic Tools.
Performs deterministic filtering and calculation. Never delegates arithmetic to an LLM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import operator


def validate_transaction(tx):
    """Strict production schema. Currency conversion is deliberately not implicit."""
    required = {"amount", "currency", "date", "category", "account"}
    if required - tx.keys():
        raise ValueError(f"Missing transaction fields: {sorted(required - tx.keys())}")
    if isinstance(tx["amount"], bool) or not isinstance(
        tx["amount"], (int, float, Decimal)
    ):
        raise ValueError("amount must be numeric")
    if not Decimal(str(tx["amount"])).is_finite():
        raise ValueError("amount must be finite")
    if not isinstance(tx["currency"], str) or not re.fullmatch(
        "[A-Z]{3}", tx["currency"]
    ):
        raise ValueError("currency must be ISO-style uppercase code")
    date.fromisoformat(tx["date"])
    for field in ("category", "account"):
        if not isinstance(tx[field], str) or not tx[field].strip():
            raise ValueError(f"Invalid {field}")
    return tx


def validate_transactions(transactions):
    if not isinstance(transactions, list):
        raise ValueError("transactions must be a list")
    for tx in transactions:
        validate_transaction(tx)
    if len({tx["currency"] for tx in transactions}) > 1:
        raise ValueError("Mixed currencies require explicit conversion")
    return transactions


def filter_transactions(
    transactions: List[Dict[str, Any]],
    category: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    account: Optional[str] = None,
    amount_operator: Optional[str] = None,
    amount_value: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Validated filtering; legacy min/max are explicitly exclusive GT/LT."""
    operators = {
        "GT": operator.gt,
        "GTE": operator.ge,
        "LT": operator.lt,
        "LTE": operator.le,
        "EQ": operator.eq,
        "NE": operator.ne,
    }
    if (amount_operator is None) != (amount_value is None):
        raise ValueError("Comparison requires operator and value")
    if amount_operator is not None and amount_operator not in operators:
        raise ValueError("Invalid amount operator")
    filtered = []
    for tx in transactions:
        validate_transaction(tx)
        if category and tx.get("category", "").lower() != category.lower():
            continue
        amt = float(tx.get("amount", 0.0))
        if amount_operator and not operators[amount_operator](amt, amount_value):
            continue
        if min_amount is not None and amt <= min_amount:
            continue
        if max_amount is not None and amt >= max_amount:
            continue
        if account and tx.get("account", "").lower() != account.lower():
            continue
        filtered.append(tx)
    return filtered


def calculate_total(
    transactions: List[Dict[str, Any]], aggregation: str = "sum"
) -> float:
    """Deterministic mathematical aggregation."""
    if not transactions:
        return 0.0
    for tx in transactions:
        validate_transaction(tx)
    if len({tx["currency"] for tx in transactions}) != 1:
        raise ValueError("Mixed currencies require explicit conversion")
    amounts = [Decimal(str(tx["amount"])) for tx in transactions]
    if aggregation == "sum":
        return float(round(sum(amounts), 2))
    elif aggregation == "avg":
        return float(round(sum(amounts) / len(amounts), 2))
    elif aggregation == "count":
        return float(len(amounts))
    elif aggregation == "min":
        return float(round(min(amounts), 2))
    elif aggregation == "max":
        return float(round(max(amounts), 2))
    else:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
