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
    asset_path: Optional[str] = None


@dataclass(frozen=True)
class ModelRequest:
    """Input payload to a model runtime."""

    request_id: str
    model_id: str
    inputs: Any
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 30.0
    user_scope: str = "local_device"
    cache_namespace: str = "default"


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
    pinned: bool = False
    active_owners: Set[str] = field(default_factory=set)
    state: str = "RESIDENT"
    load_latency_ms: Optional[float] = None
    measured_ram_mb: Optional[float] = None


class ModelResidencyManager:
    """
    Manages resident model weights, memory budgets, and eviction policies.
    Enforces model accounting budgets around runtime calls. Process-wide peak
    allocation and Android PSS limits require independent hardware validation.
    """

    def __init__(self, max_resident_memory_mb: float = 1024.0, runtime=None):
        self.max_resident_memory_mb = max_resident_memory_mb
        self._entries: Dict[str, LoadedModelEntry] = {}
        self.runtime = runtime
        import threading

        self._lock = threading.RLock()

    @property
    def current_resident_memory_mb(self) -> float:
        return sum(e.memory_footprint_mb for e in self._entries.values())

    def record_load(
        self,
        descriptor: ModelDescriptor,
        backend: RuntimeBackend,
        actual_memory_mb: Optional[float] = None,
        capability_id: Optional[str] = None,
    ) -> None:
        now = time.time()
        mem = (
            actual_memory_mb
            if actual_memory_mb is not None
            else descriptor.estimated_ram_mb
        )
        entry = LoadedModelEntry(
            descriptor=descriptor,
            backend=backend,
            memory_footprint_mb=mem,
            loaded_at=now,
            last_accessed=now,
            access_count=1,
            associated_capability_ids={capability_id} if capability_id else set(),
        )
        self._entries[descriptor.model_id] = entry
        entry.measured_ram_mb = actual_memory_mb

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
            (e for e in self._entries.values() if not e.pinned and not e.active_owners),
            key=lambda e: -(time.time() - e.last_accessed)
            * e.memory_footprint_mb
            / (max(e.reload_penalty_ms, 1) * (e.access_count + 1)),
        )

        freed = 0.0
        for entry in sorted_entries:
            candidates.append(entry.descriptor.model_id)
            freed += entry.memory_footprint_mb
            if (
                self.current_resident_memory_mb - freed + needed_memory_mb
            ) <= self.max_resident_memory_mb:
                break

        return candidates

    def ensure_resident(self, descriptor, owner=None, pinned=False):
        import psutil

        with self._lock:
            if self.runtime is None:
                raise RuntimeError("BACKEND_UNAVAILABLE")
            if descriptor.model_id in self._entries:
                entry = self._entries[descriptor.model_id]
                if entry.descriptor != descriptor:
                    raise ValueError("MODEL_VERSION_MISMATCH")
                self.record_access(descriptor.model_id)
            else:
                needed = descriptor.estimated_ram_mb
                if needed <= 0:
                    raise ValueError("Positive allocation estimate required")
                self.evict_if_needed(needed)
                if (
                    needed > psutil.virtual_memory().available / 1048576
                    or self.current_resident_memory_mb + needed
                    > self.max_resident_memory_mb
                ):
                    raise MemoryError("Model allocation exceeds available budget")
                before = psutil.Process().memory_info().rss
                start = time.perf_counter()
                if not self.runtime.load_model(
                    descriptor, descriptor.preferred_backend
                ):
                    raise RuntimeError("MODEL_LOAD_FAILED")
                latency = (time.perf_counter() - start) * 1000
                measured = max(0, psutil.Process().memory_info().rss - before) / 1048576
                if (
                    self.current_resident_memory_mb + measured
                    > self.max_resident_memory_mb
                ):
                    self.runtime.unload_model(descriptor.model_id)
                    raise MemoryError("Measured model footprint exceeds budget")
                self.record_load(descriptor, descriptor.preferred_backend, measured)
                entry = self._entries[descriptor.model_id]
                entry.load_latency_ms = latency
                entry.reload_penalty_ms = latency
            entry.pinned = entry.pinned or pinned
            if owner:
                entry.active_owners.add(owner)
            entry.state = "PINNED" if entry.pinned else "RESIDENT"
            return entry

    def release(self, model_id, owner=None):
        with self._lock:
            entry = self._entries.get(model_id)
            if entry is None:
                return False
            if owner:
                entry.active_owners.discard(owner)
            if not entry.active_owners and not entry.pinned:
                entry.state = "EVICTABLE"
            return True

    def evict_if_needed(self, needed_memory_mb=0):
        import psutil

        with self._lock:
            for model_id in self.select_eviction_candidates(needed_memory_mb):
                entry = self._entries[model_id]
                entry.state = "UNLOADING"
                before = psutil.Process().memory_info().rss
                if not self.runtime.unload_model(model_id) or self.runtime.is_loaded(
                    model_id
                ):
                    entry.state = "FAILED"
                    raise RuntimeError("MODEL_UNLOAD_FAILED")
                entry.released_rss_mb = (
                    before - psutil.Process().memory_info().rss
                ) / 1048576
                self.record_unload(model_id)

    def preload(self, descriptors):
        return [self.ensure_resident(d) for d in descriptors]

    def get_residency_snapshot(self):
        return {
            k: {
                "state": e.state,
                "estimated_ram_mb": e.descriptor.estimated_ram_mb,
                "measured_ram_mb": e.measured_ram_mb,
                "load_latency_ms": e.load_latency_ms,
                "last_access": e.last_accessed,
                "access_count": e.access_count,
                "owners": sorted(e.active_owners),
            }
            for k, e in self._entries.items()
        }


class LlamaCppRuntimeAdapter(ModelRuntimeAdapter):
    """Actual optional CPU GGUF backend. No fallback or synthetic inference.

    API: https://llama-cpp-python.readthedocs.io/en/latest/api-reference/
    """

    def __init__(self):
        self._models = {}
        self._cache_scopes = {}
        self._adapter_hashes = {}
        import threading

        self._lock = threading.RLock()

    def load_model(self, descriptor, backend=RuntimeBackend.CPU):
        from pathlib import Path

        if backend != RuntimeBackend.CPU:
            raise RuntimeError("BACKEND_UNAVAILABLE")
        if not descriptor.asset_path or not Path(descriptor.asset_path).is_file():
            raise FileNotFoundError("MODEL_ASSET_MISSING")
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError("BACKEND_UNAVAILABLE: install llama-cpp-python") from exc
        with self._lock:
            if descriptor.model_id in self._models:
                raise ValueError("Model already loaded")
            self._models[descriptor.model_id] = Llama(
                model_path=descriptor.asset_path,
                n_ctx=descriptor.context_window,
                n_batch=min(128, descriptor.context_window),
                n_ubatch=min(128, descriptor.context_window),
                n_threads=2,
                n_gpu_layers=0,
                verbose=False,
            )
        return True

    def unload_model(self, model_id):
        with self._lock:
            model = self._models.pop(model_id, None)
            if model is None:
                return False
            model.close()
            self._cache_scopes.pop(model_id, None)
            self._adapter_hashes.pop(model_id, None)
            return True

    def is_loaded(self, model_id):
        return model_id in self._models

    def activate_adapter(self, descriptor, adapter_path, commit):
        """Load real GGUF LoRA weights before committing the durable active pointer.

        Inference is locked during publication; a failed load/commit leaves the
        previous complete model usable. Restart resolves the committed pointer.
        """
        from llama_cpp import Llama

        import hashlib
        from pathlib import Path

        adapter_digest = (
            hashlib.sha256(Path(adapter_path).read_bytes()).hexdigest()
            if adapter_path is not None
            else None
        )

        replacement = Llama(
            model_path=descriptor.asset_path,
            lora_path=adapter_path,
            n_ctx=descriptor.context_window,
            n_batch=min(128, descriptor.context_window),
            n_ubatch=min(128, descriptor.context_window),
            n_threads=2,
            n_gpu_layers=0,
            verbose=False,
        )
        with self._lock:
            try:
                commit()
            except BaseException:
                replacement.close()
                raise
            previous = self._models.get(descriptor.model_id)
            self._models[descriptor.model_id] = replacement
            if adapter_digest is None:
                self._adapter_hashes.pop(descriptor.model_id, None)
            else:
                self._adapter_hashes[descriptor.model_id] = adapter_digest
            self._cache_scopes.pop(descriptor.model_id, None)
            if previous is not None:
                previous.close()

    def stream_inference(self, request):
        """Yield actual generated token IDs and elapsed time, including first token."""
        with self._lock:
            model = self._models[request.model_id]
            scope = (request.user_scope, request.cache_namespace)
            if not request.user_scope:
                raise PermissionError("ACCESS_DENIED: model cache user scope required")
            if self._cache_scopes.get(request.model_id) != scope:
                model.reset()
                self._cache_scopes[request.model_id] = scope
            start = time.perf_counter()
            inputs = model.tokenize(str(request.inputs).encode("utf-8"))
            if len(inputs) >= model.n_ctx():
                raise ValueError("MODEL_CONTEXT_EXCEEDED")
            params = dict(request.parameters)
            limit = params.pop("max_tokens", 128)
            if not isinstance(limit, int) or limit <= 0:
                raise ValueError("max_tokens must be positive")
            limit = min(limit, model.n_ctx() - len(inputs))
            if set(params) - {"temp", "top_k", "top_p", "min_p", "repeat_penalty"}:
                raise ValueError("Unsupported inference parameters")
            generator = model.generate(inputs, **params)
            try:
                for index, token in enumerate(generator):
                    elapsed = (time.perf_counter() - start) * 1000
                    if elapsed > request.timeout_s * 1000:
                        raise TimeoutError("Inference deadline exceeded")
                    if token == model.token_eos():
                        break
                    yield token, elapsed
                    if index + 1 >= limit:
                        break
            finally:
                generator.close()

    def infer(self, request):
        with self._lock:
            start = time.perf_counter()
            tokens = []
            ttft = None
            for token, elapsed in self.stream_inference(request):
                if ttft is None:
                    ttft = elapsed
                tokens.append(token)
            output = (
                self._models[request.model_id]
                .detokenize(tokens)
                .decode("utf-8", errors="replace")
            )
            latency = (time.perf_counter() - start) * 1000
            return ModelResult(
                request.request_id,
                request.model_id,
                output,
                latency,
                len(tokens),
                backend_used=RuntimeBackend.CPU,
                metadata={
                    "backend_identity": "llama-cpp-python/CPU",
                    "ttft_ms": ttft,
                    "tokens_per_second": len(tokens) / (latency / 1000)
                    if latency
                    else None,
                    "token_count_provenance": "generated token IDs",
                    "adapter_dependencies": [
                        (
                            request.model_id + "/lora",
                            self._adapter_hashes[request.model_id],
                        )
                    ]
                    if request.model_id in self._adapter_hashes
                    else [],
                    "cache_scope": request.user_scope,
                },
            )
