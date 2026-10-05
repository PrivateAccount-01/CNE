"""
CNE Model Runtime Abstraction & Residency Manager.
Model-family neutral execution interfaces supporting SLMs, CV, speech, embeddings, and time-series.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from cne.platform.device import RuntimeBackend

logger = logging.getLogger(__name__)


class ModelKind(str, Enum):
    TEXT_GENERATION = "TEXT_GENERATION"
    CLASSIFICATION = "CLASSIFICATION"
    COMPUTER_VISION = "COMPUTER_VISION"
    EMBEDDING = "EMBEDDING"
    ASR = "ASR"
    TIME_SERIES = "TIME_SERIES"
    REGRESSION = "REGRESSION"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class ModelDescriptor:
    """Metadata identifying a deployable model asset."""
    model_id: str
    kind: ModelKind
    version: str
    parameter_count_m: float
    quantization: str = "Q4_K_M"
    format: str = "GGUF"
    file_size_mb: float = 0.0
    estimated_ram_mb: float = 0.0
    preferred_backend: RuntimeBackend = RuntimeBackend.CPU
    context_window: int = 4096


@dataclass(frozen=True)
class ModelRequest:
    """Input payload to a model runtime."""
    request_id: str
    model_id: str
    inputs: Any
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 30.0


@dataclass(frozen=True)
class ModelResult:
    """Output result produced by a model runtime."""
    request_id: str
    model_id: str
    outputs: Any
    latency_ms: float
    tokens_generated: Optional[int] = None
    confidence_score: Optional[float] = None
    backend_used: RuntimeBackend = RuntimeBackend.CPU
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModelRuntimeAdapter(ABC):
    """Abstract adapter interface for underlying inference engines."""

    @abstractmethod
    def load_model(self, descriptor: ModelDescriptor, backend: RuntimeBackend) -> bool:
        """Load model weights into memory."""
        pass

    @abstractmethod
    def unload_model(self, model_id: str) -> bool:
        """Unload model weights from memory."""
        pass

    @abstractmethod
    def is_loaded(self, model_id: str) -> bool:
        pass

    @abstractmethod
    def infer(self, request: ModelRequest) -> ModelResult:
        """Execute inference."""
        pass


@dataclass
class LoadedModelEntry:
    descriptor: ModelDescriptor
    backend: RuntimeBackend
    memory_footprint_mb: float
    loaded_at: float
    last_accessed: float
    access_count: int = 0
    reload_penalty_ms: float = 500.0
    associated_capability_ids: Set[str] = field(default_factory=set)


class ModelResidencyManager:
    """
    Manages resident model weights, memory budgets, and eviction policies.
    Guarantees active process stays within the 1.0 GB steady / 1.5 GB peak budget.
    """

    def __init__(self, max_resident_memory_mb: float = 1024.0):
        self.max_resident_memory_mb = max_resident_memory_mb
        self._entries: Dict[str, LoadedModelEntry] = {}

    @property
    def current_resident_memory_mb(self) -> float:
        return sum(e.memory_footprint_mb for e in self._entries.values())

    def record_load(
        self,
        descriptor: ModelDescriptor,
        backend: RuntimeBackend,
        actual_memory_mb: Optional[float] = None,
        capability_id: Optional[str] = None
    ) -> None:
        now = time.time()
        mem = actual_memory_mb or descriptor.estimated_ram_mb
        entry = LoadedModelEntry(
            descriptor=descriptor,
            backend=backend,
            memory_footprint_mb=mem,
            loaded_at=now,
            last_accessed=now,
            access_count=1,
            associated_capability_ids={capability_id} if capability_id else set()
        )
        self._entries[descriptor.model_id] = entry

    def record_access(self, model_id: str) -> None:
        if model_id in self._entries:
            e = self._entries[model_id]
            e.last_accessed = time.time()
            e.access_count += 1

    def record_unload(self, model_id: str) -> bool:
        if model_id in self._entries:
            del self._entries[model_id]
            return True
        return False

    def select_eviction_candidates(self, needed_memory_mb: float) -> List[str]:
        """
        Deterministic cost-aware LRU eviction.
        Evicts models with oldest access and lowest reload penalty.
        """
        candidates: List[str] = []
        projected_mem = self.current_resident_memory_mb + needed_memory_mb
        if projected_mem <= self.max_resident_memory_mb:
            return candidates

        # Sort by (last_accessed, reload_penalty_ms)
        sorted_entries = sorted(
            self._entries.values(),
            key=lambda e: (e.last_accessed, e.reload_penalty_ms)
        )

        freed = 0.0
        for entry in sorted_entries:
            candidates.append(entry.descriptor.model_id)
            freed += entry.memory_footprint_mb
            if (self.current_resident_memory_mb - freed + needed_memory_mb) <= self.max_resident_memory_mb:
                break

        return candidates
