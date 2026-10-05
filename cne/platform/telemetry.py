"""
CNE Local Structured Observability & Telemetry Subsystem.
Captures per-request performance, memory, cache layer hits, and contract status locally.
Never leaks private data into telemetry records.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RequestTelemetry:
    request_id: str
    session_id: str
    active_capabilities: List[str]
    active_models: List[str]
    backend: str
    shape_hash: Optional[str]
    cache_hits_by_layer: Dict[str, int] = field(default_factory=dict)
    control_latency_ms: float = 0.0
    inference_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0
    verification_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    peak_memory_mb: float = 0.0
    cpu_percent: float = 0.0
    contract_status: str = "SATISFIED"
    error_category: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LocalTelemetryCollector:
    """Collects and aggregates telemetry records on-device."""

    def __init__(self, max_records: int = 1000):
        self.max_records = max_records
        self._records: List[RequestTelemetry] = []

    def record(self, telemetry: RequestTelemetry) -> None:
        self._records.append(telemetry)
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]

    @property
    def total_requests(self) -> int:
        return len(self._records)

    def get_average_latency_ms(self) -> float:
        if not self._records:
            return 0.0
        return sum(r.total_latency_ms for r in self._records) / len(self._records)

    def get_cache_hit_rate(self) -> float:
        if not self._records:
            return 0.0
        hits = sum(1 for r in self._records if any(count > 0 for count in r.cache_hits_by_layer.values()))
        return hits / len(self._records)
