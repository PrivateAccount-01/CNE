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
    control_latency_ms: Optional[float] = None
    inference_latency_ms: Optional[float] = None
    execution_latency_ms: Optional[float] = None
    verification_latency_ms: Optional[float] = None
    total_latency_ms: Optional[float] = None
    peak_memory_mb: Optional[float] = None
    cpu_percent: Optional[float] = None
    contract_status: str = "NOT_MEASURED"
    error_category: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    controller_latency_ms: Optional[float] = None
    routing_latency_ms: Optional[float] = None
    slot_binding_latency_ms: Optional[float] = None
    model_load_latency_ms: Optional[float] = None
    inference_ttft_ms: Optional[float] = None
    tokens_generated: Optional[int] = None
    tokens_per_second: Optional[float] = None
    dsl_compile_latency_ms: Optional[float] = None
    persistence_latency_ms: Optional[float] = None
    peak_pss_mb: Optional[float] = None
    peak_rss_mb: Optional[float] = None
    capability_vector: Optional[str] = None
    model_versions: Dict[str, str] = field(default_factory=dict)
    fallback: Optional[str] = None

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
            self._records = self._records[-self.max_records :]

    @property
    def total_requests(self) -> int:
        return len(self._records)

    def get_average_latency_ms(self) -> float:
        if not self._records:
            return None
        measured = [
            r.total_latency_ms for r in self._records if r.total_latency_ms is not None
        ]
        return sum(measured) / len(measured) if measured else None

    def get_cache_hit_rate(self) -> float:
        if not self._records:
            return 0.0
        hits = sum(
            1
            for r in self._records
            if any(count > 0 for count in r.cache_hits_by_layer.values())
        )
        return hits / len(self._records)
