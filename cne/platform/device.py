"""
L1 Device Abstraction & Resource Budget.
Hardware-agnostic device profiling, resource monitoring, and backend discovery.

Invariants:
1. CPU is the mandatory reference backend. Absence of accelerators never invalidates platform claims.
2. Accelerator-only capabilities are explicitly flagged and excluded from baseline claims.
3. Process memory targets for reference 6 GB device:
   - Peak PSS <= 1.5 GB
   - Steady runtime <= 1.0 GB
   - Base model storage <= 500 MB
   - Core framework storage <= 150 MB
"""
from __future__ import annotations

import os
import platform
import psutil
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class RuntimeBackend(str, Enum):
    """Execution backends available on the device."""

    CPU = "CPU"
    GPU = "GPU"
    NPU = "NPU"
    DSP = "DSP"
    USB = "USB"


@dataclass(frozen=True)
class BackendCapabilities:
    """Hardware and instruction set capabilities for a specific backend."""

    backend: RuntimeBackend
    is_available: bool = True
    device_name: str = "Host CPU"
    total_memory_mb: float = 0.0
    supports_fp16: Optional[bool] = None
    supports_int8: Optional[bool] = None
    supports_int4: Optional[bool] = None
    compute_units: int = 1
    driver_version: Optional[str] = None


@dataclass(frozen=True)
class ResourceSnapshot:
    """Instantaneous snapshot of device resource utilization."""

    available_ram_mb: float
    used_ram_mb: float
    process_rss_mb: float
    process_pss_mb: Optional[float]
    cpu_percent: float
    battery_percent: Optional[float] = None
    is_charging: Optional[bool] = None
    is_thermal_throttled: Optional[bool] = None
    storage_free_mb: float = 0.0
    thermal_state: str = "UNKNOWN"


@dataclass(frozen=True)
class BudgetDecision:
    passed: bool
    violations: List[str]
    observed: Dict[str, Any]
    limits: Dict[str, Any]


@dataclass(frozen=True)
class ResourceBudget:
    """Hardware resource budget limits for the active process."""

    max_peak_pss_mb: float = 1536.0  # 1.5 GB peak PSS target
    max_steady_ram_mb: float = 1024.0  # 1.0 GB steady active target
    max_model_storage_mb: float = 500.0  # 500 MB model storage target
    max_framework_storage_mb: float = 150.0  # 150 MB core framework target
    max_concurrent_inferences: int = 1
    allow_accelerator: bool = True

    def is_within_budget(self, snapshot: ResourceSnapshot) -> bool:
        """Check if current process snapshot satisfies budget."""
        return self.evaluate(snapshot).passed

    def evaluate(
        self,
        snapshot,
        peak_memory_mb=None,
        steady_memory_mb=None,
        required_storage_mb=0,
        concurrent_inferences=0,
    ):
        observed = {
            "peak_memory_mb": peak_memory_mb,
            "steady_memory_mb": steady_memory_mb,
            "required_storage_mb": required_storage_mb,
            "concurrent_inferences": concurrent_inferences,
        }
        limits = {
            "peak_memory_mb": self.max_peak_pss_mb,
            "steady_memory_mb": self.max_steady_ram_mb,
            "required_storage_mb": snapshot.storage_free_mb,
            "concurrent_inferences": self.max_concurrent_inferences,
        }
        violations = [
            ("NOT_MEASURED:" + key) if observed[key] is None else key
            for key in limits
            if observed[key] is None or observed[key] > limits[key]
        ]
        return BudgetDecision(not violations, violations, observed, limits)


class DeviceProfile:
    """
    Hardware-agnostic device profile and environment inspector.
    Discovers available CPU, memory, and optional accelerator backends.
    """

    def __init__(self, budget: Optional[ResourceBudget] = None):
        self.budget = budget or ResourceBudget()
        self._backends: Dict[RuntimeBackend, BackendCapabilities] = {}
        self._discover_backends()

    def _discover_backends(self) -> None:
        """Discover CPU (mandatory) and optional accelerators."""
        # 1. CPU is always mandatory reference
        cpu_count = os.cpu_count() or 1
        total_ram_mb = psutil.virtual_memory().total / (1024 * 1024)
        self._backends[RuntimeBackend.CPU] = BackendCapabilities(
            backend=RuntimeBackend.CPU,
            is_available=True,
            device_name=f"{platform.processor() or 'ARM/x86'} CPU",
            total_memory_mb=total_ram_mb,
            supports_fp16=None,
            supports_int8=None,
            supports_int4=None,
            compute_units=cpu_count,
        )

        # 2. Check for optional GPU / NPU / USB accelerators without making them required
        # (Default: not present in baseline CPU reference environment)

    @property
    def backends(self) -> Dict[RuntimeBackend, BackendCapabilities]:
        return dict(self._backends)

    def is_backend_available(self, backend: RuntimeBackend) -> bool:
        return backend in self._backends and self._backends[backend].is_available

    def register_optional_accelerator(self, caps: BackendCapabilities) -> None:
        """Registers a discovered optional accelerator backend."""
        self._backends[caps.backend] = caps

    def capture_snapshot(self) -> ResourceSnapshot:
        """Captures current system and process resource metrics."""
        vm = psutil.virtual_memory()
        proc = psutil.Process()
        mem_info = proc.memory_info()

        # Storage info for current drive
        disk = psutil.disk_usage(os.path.abspath("."))
        storage_free_mb = disk.free / (1024 * 1024)

        # PSS approximation on Windows/generic (falls back to RSS if pss attribute missing)
        try:
            pss = getattr(proc.memory_full_info(), "pss", None)
        except (psutil.AccessDenied, AttributeError):
            pss = None
        pss_mb = pss / (1024 * 1024) if pss is not None else None
        rss_mb = mem_info.rss / (1024 * 1024)

        battery = (
            psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        )
        battery_pct = battery.percent if battery else None
        charging = battery.power_plugged if battery else None

        return ResourceSnapshot(
            available_ram_mb=vm.available / (1024 * 1024),
            used_ram_mb=vm.used / (1024 * 1024),
            process_rss_mb=round(rss_mb, 2),
            process_pss_mb=round(pss_mb, 2) if pss_mb is not None else None,
            cpu_percent=psutil.cpu_percent(interval=None),
            battery_percent=battery_pct,
            is_charging=charging,
            is_thermal_throttled=None,
            storage_free_mb=round(storage_free_mb, 2),
        )
