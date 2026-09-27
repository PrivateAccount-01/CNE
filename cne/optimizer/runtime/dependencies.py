"""
CNE Predicate-Aware Dependency Tracking.
Implements Section 13 dependency model:
- Coarse granularity: source, table
- Fine granularity: exact key, row, field, range, predicate, join relationship

CRITICAL REQUIREMENT (Section 13.2):
A computation over Filter(predicate) must be capable of receiving invalidation
from a newly inserted row that satisfies the predicate, even if that row did not exist
when the computation was registered!
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from cne.semantic_ir.types import DependencyKey


class ChangeType(Enum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


@dataclass
class PredicateSubscription:
    entry_id: str
    source: str
    predicate_fn: Callable[[Dict[str, Any]], bool]
    predicate_desc: str = ""


@dataclass
class RangeSubscription:
    entry_id: str
    source: str
    field_name: str
    min_val: float
    max_val: float


@dataclass
class JoinKeySubscription:
    entry_id: str
    source_a: str
    source_b: str
    key_field: str


class DependencyManager:
    def __init__(self):
        # Key subscriptions: source -> key -> set of entry_ids
        self._key_subscriptions: Dict[str, Dict[str, Set[str]]] = {}
        # Coarse source subscriptions: source -> set of entry_ids
        self._source_subscriptions: Dict[str, Set[str]] = {}
        # Predicate subscriptions: source -> list of PredicateSubscription
        self._predicate_subscriptions: Dict[str, List[PredicateSubscription]] = {}
        # Range subscriptions: source -> list of RangeSubscription
        self._range_subscriptions: Dict[str, List[RangeSubscription]] = {}
        # Join key subscriptions: source -> list of JoinKeySubscription
        self._join_subscriptions: Dict[str, List[JoinKeySubscription]] = {}

    def register_dependency(
        self,
        entry_id: str,
        dep_key: DependencyKey,
        predicate_fn: Optional[Callable[[Dict[str, Any]], bool]] = None
    ) -> None:
        src = dep_key.source
        granularity = dep_key.granularity

        if granularity in ("source", "table"):
            self._source_subscriptions.setdefault(src, set()).add(entry_id)

        elif granularity == "key" and dep_key.key is not None:
            self._key_subscriptions.setdefault(src, {}).setdefault(str(dep_key.key), set()).add(entry_id)

        elif granularity == "predicate":
            if predicate_fn:
                sub = PredicateSubscription(
                    entry_id=entry_id,
                    source=src,
                    predicate_fn=predicate_fn,
                    predicate_desc=dep_key.predicate_desc or ""
                )
                self._predicate_subscriptions.setdefault(src, []).append(sub)
            else:
                # If no predicate function supplied, fallback to table granularity
                self._source_subscriptions.setdefault(src, set()).add(entry_id)

        elif granularity == "range" and dep_key.range_bounds and dep_key.field_name:
            sub_r = RangeSubscription(
                entry_id=entry_id,
                source=src,
                field_name=dep_key.field_name,
                min_val=float(dep_key.range_bounds[0]),
                max_val=float(dep_key.range_bounds[1])
            )
            self._range_subscriptions.setdefault(src, []).append(sub_r)

        elif granularity == "join":
            sub_j = JoinKeySubscription(
                entry_id=entry_id,
                source_a=src,
                source_b=dep_key.key or "",
                key_field=dep_key.field_name or "id"
            )
            self._join_subscriptions.setdefault(src, []).append(sub_j)

    def notify_change(
        self,
        change_type: ChangeType,
        source: str,
        changed_row: Dict[str, Any],
        row_key: Optional[str] = None
    ) -> Set[str]:
        """
        Evaluates fine-grained invalidation for all registered subscriptions.
        Returns the set of entry_ids that MUST be invalidated.
        """
        invalidated: Set[str] = set()

        # 1. Coarse source invalidations
        if source in self._source_subscriptions:
            invalidated.update(self._source_subscriptions[source])

        # 2. Key-level invalidations
        k = row_key or changed_row.get("id") or changed_row.get("key")
        if k is not None and source in self._key_subscriptions:
            str_k = str(k)
            if str_k in self._key_subscriptions[source]:
                invalidated.update(self._key_subscriptions[source][str_k])

        # 3. Predicate subscriptions (Section 13.2)
        # Evaluates whether the inserted/modified/deleted row satisfies the subscribed predicate
        if source in self._predicate_subscriptions:
            for sub in self._predicate_subscriptions[source]:
                try:
                    if sub.predicate_fn(changed_row):
                        invalidated.add(sub.entry_id)
                except Exception:
                    # Conservative fallback: if predicate evaluation errors, invalidate
                    invalidated.add(sub.entry_id)

        # 4. Range subscriptions
        if source in self._range_subscriptions:
            for sub_r in self._range_subscriptions[source]:
                val = changed_row.get(sub_r.field_name)
                if val is not None and isinstance(val, (int, float)):
                    if sub_r.min_val <= float(val) <= sub_r.max_val:
                        invalidated.add(sub_r.entry_id)

        # 5. Join key subscriptions
        if source in self._join_subscriptions:
            for sub_j in self._join_subscriptions[source]:
                if sub_j.key_field in changed_row:
                    invalidated.add(sub_j.entry_id)

        return invalidated

    def unregister_entry(self, entry_id: str) -> None:
        """
        Clean up all subscriptions for an evicted or deleted entry.
        """
        for src, keys in self._key_subscriptions.items():
            for k in keys:
                keys[k].discard(entry_id)

        for src, entries in self._source_subscriptions.items():
            entries.discard(entry_id)

        for src in self._predicate_subscriptions:
            self._predicate_subscriptions[src] = [
                s for s in self._predicate_subscriptions[src] if s.entry_id != entry_id
            ]

        for src in self._range_subscriptions:
            self._range_subscriptions[src] = [
                s for s in self._range_subscriptions[src] if s.entry_id != entry_id
            ]

        for src in self._join_subscriptions:
            self._join_subscriptions[src] = [
                s for s in self._join_subscriptions[src] if s.entry_id != entry_id
            ]
