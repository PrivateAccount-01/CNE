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
    active_keys: Optional[Set[Any]] = None


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
        # Field subscriptions: source -> field_name -> set of entry_ids
        self._field_subscriptions: Dict[str, Dict[str, Set[str]]] = {}
        # Keyed field subscriptions: source -> key -> field_name -> set of entry_ids
        self._keyed_field_subscriptions: Dict[str, Dict[str, Dict[str, Set[str]]]] = {}
        # Source version counter: source -> int
        self.source_versions: Dict[str, int] = {}

    def get_source_version(self, source: str) -> int:
        return self.source_versions.get(source, 0)

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

        elif granularity == "field" and dep_key.field_name:
            if dep_key.key is not None:
                self._keyed_field_subscriptions.setdefault(src, {}).setdefault(str(dep_key.key), {}).setdefault(dep_key.field_name, set()).add(entry_id)
            else:
                self._field_subscriptions.setdefault(src, {}).setdefault(dep_key.field_name, set()).add(entry_id)

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
            active_keys = None
            if hasattr(dep_key, "attributes") and isinstance(dep_key.attributes, dict):
                active_keys = dep_key.attributes.get("active_keys")
            sub_j = JoinKeySubscription(
                entry_id=entry_id,
                source_a=src,
                source_b=dep_key.key or "",
                key_field=dep_key.field_name or "id",
                active_keys=set(active_keys) if active_keys is not None else None
            )
            self._join_subscriptions.setdefault(src, []).append(sub_j)
            if sub_j.source_b and sub_j.source_b != src:
                self._join_subscriptions.setdefault(sub_j.source_b, []).append(sub_j)

    def notify_change(
        self,
        change_type: ChangeType,
        source: str,
        changed_row: Optional[Dict[str, Any]] = None,
        row_key: Optional[str] = None,
        old_row: Optional[Dict[str, Any]] = None,
        new_row: Optional[Dict[str, Any]] = None
    ) -> Set[str]:
        """
        Evaluates fine-grained invalidation for all registered subscriptions.
        Supports sound update semantics: P(old) OR P(new) and old in R OR new in R.
        Returns the set of entry_ids that MUST be invalidated.
        """
        # Increment source version
        self.source_versions[source] = self.source_versions.get(source, 0) + 1

        # Reconcile old_row and new_row
        if new_row is None and old_row is None:
            if change_type == ChangeType.INSERT:
                new_row = changed_row or {}
            elif change_type == ChangeType.DELETE:
                old_row = changed_row or {}
            elif change_type == ChangeType.UPDATE:
                new_row = changed_row or {}
        elif new_row is None and changed_row is not None:
            new_row = changed_row

        invalidated: Set[str] = set()

        # 1. Coarse source invalidations
        if source in self._source_subscriptions:
            invalidated.update(self._source_subscriptions[source])

        # 2. Key-level invalidations
        keys_to_check = set()
        if row_key is not None:
            keys_to_check.add(str(row_key))
        for r in (old_row, new_row, changed_row):
            if r:
                k = r.get("id") or r.get("key")
                if k is not None:
                    keys_to_check.add(str(k))

        if source in self._key_subscriptions:
            for k in keys_to_check:
                if k in self._key_subscriptions[source]:
                    invalidated.update(self._key_subscriptions[source][k])

        # 3. Predicate subscriptions (Section 13.2)
        # Evaluates whether the mutation satisfies P(old) OR P(new)
        if source in self._predicate_subscriptions:
            for sub in self._predicate_subscriptions[source]:
                matched = False
                try:
                    if change_type == ChangeType.INSERT and new_row:
                        matched = sub.predicate_fn(new_row)
                    elif change_type == ChangeType.DELETE and old_row:
                        matched = sub.predicate_fn(old_row)
                    elif change_type == ChangeType.UPDATE:
                        matched_new = bool(new_row and sub.predicate_fn(new_row))
                        matched_old = bool(old_row and sub.predicate_fn(old_row))
                        matched = matched_new or matched_old
                    elif changed_row:
                        matched = sub.predicate_fn(changed_row)
                except Exception:
                    # Conservative fallback: if predicate evaluation errors, invalidate
                    matched = True

                if matched:
                    invalidated.add(sub.entry_id)

        # 4. Range subscriptions: old in R OR new in R
        def _row_in_range(row: Optional[Dict[str, Any]], sub_r: RangeSubscription) -> bool:
            if not row:
                return False
            val = row.get(sub_r.field_name)
            if val is not None and isinstance(val, (int, float)):
                return sub_r.min_val <= float(val) <= sub_r.max_val
            return False

        if source in self._range_subscriptions:
            for sub_r in self._range_subscriptions[source]:
                in_rng = False
                if change_type == ChangeType.INSERT:
                    in_rng = _row_in_range(new_row, sub_r)
                elif change_type == ChangeType.DELETE:
                    in_rng = _row_in_range(old_row, sub_r)
                elif change_type == ChangeType.UPDATE:
                    in_rng = _row_in_range(new_row, sub_r) or _row_in_range(old_row, sub_r)
                elif changed_row:
                    in_rng = _row_in_range(changed_row, sub_r)
                if in_rng:
                    invalidated.add(sub_r.entry_id)

        # 5. Field-level subscriptions
        if source in self._field_subscriptions or source in self._keyed_field_subscriptions:
            changed_fields: Set[str] = set()
            if old_row and new_row:
                all_keys = set(old_row.keys()) | set(new_row.keys())
                changed_fields = {k for k in all_keys if old_row.get(k) != new_row.get(k)}
            elif new_row:
                changed_fields = set(new_row.keys())
            elif old_row:
                changed_fields = set(old_row.keys())
            elif changed_row:
                changed_fields = set(changed_row.keys())

            if source in self._field_subscriptions:
                for f in changed_fields:
                    if f in self._field_subscriptions[source]:
                        invalidated.update(self._field_subscriptions[source][f])

            if source in self._keyed_field_subscriptions:
                for k in keys_to_check:
                    if k in self._keyed_field_subscriptions[source]:
                        for f in changed_fields:
                            if f in self._keyed_field_subscriptions[source][k]:
                                invalidated.update(self._keyed_field_subscriptions[source][k][f])

        # 6. Join key subscriptions
        if source in self._join_subscriptions:
            for sub_j in self._join_subscriptions[source]:
                for r in (new_row, old_row, changed_row):
                    if r and sub_j.key_field in r:
                        key_val = r[sub_j.key_field]
                        if sub_j.active_keys is not None:
                            if key_val in sub_j.active_keys:
                                invalidated.add(sub_j.entry_id)
                                break
                        else:
                            invalidated.add(sub_j.entry_id)
                            break

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

        for src, fields in self._field_subscriptions.items():
            for f in fields:
                fields[f].discard(entry_id)

        for src, keys in self._keyed_field_subscriptions.items():
            for k, fields in keys.items():
                for f in fields:
                    fields[f].discard(entry_id)

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
