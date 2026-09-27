"""
CNE Retention and Eviction Policy.
Eviction reduces reuse and increases cost, but must NEVER silently change correctness.
Supports LRU, Cost-Benefit, and TTL eviction policies.
"""
from __future__ import annotations
import time
from typing import Dict, List, Optional
from cne.state.lifecycle import StateLifecycle
from cne.state.state_entry import StateClass, StateEntry


class EvictionPolicy:
    def __init__(self, max_entries: int = 1000, ttl_seconds: Optional[float] = 3600.0):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

    def prune_expired(self, entries: Dict[str, StateEntry]) -> List[str]:
        """
        Marks entries exceeding TTL as SUPERSEDED or ARCHIVED.
        """
        if not self.ttl_seconds:
            return []

        now_ns = time.perf_counter_ns()
        ttl_ns = int(self.ttl_seconds * 1e9)
        evicted = []

        for eid, entry in list(entries.items()):
            if now_ns - entry.created_at_ns > ttl_ns:
                entry.transition(StateLifecycle.SUPERSEDED)
                evicted.append(eid)

        return evicted

    def select_eviction_candidates(self, entries: Dict[str, StateEntry], target_count: int) -> List[str]:
        """
        Cost-Benefit & LRU hybrid eviction:
        Score = (computation_cost_saved + 1.0) / (time_since_last_access_seconds + 1.0)
        Lowest score evicted first. Working and Stale state evicted before active computational state.
        """
        if len(entries) <= target_count:
            return []

        now_ns = time.perf_counter_ns()
        scored: List[tuple[float, str]] = []

        for eid, entry in entries.items():
            # Stale or Superseded items should be evicted first
            if entry.lifecycle in (StateLifecycle.STALE, StateLifecycle.SUPERSEDED):
                scored.append((-1e9, eid))
                continue

            idle_sec = max(0.0, (now_ns - entry.last_accessed_at_ns) / 1e9)
            score = (entry.computation_cost_saved + 1.0) / (idle_sec + 1.0)
            scored.append((score, eid))

        scored.sort(key=lambda x: x[0])
        num_to_evict = len(entries) - target_count
        return [eid for _, eid in scored[:num_to_evict]]
