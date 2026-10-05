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
    supports_fp16: bool = False
    supports_int8: bool = True
    supports_int4: bool = True
    compute_units: int = 1
    driver_version: Optional[str] = None


@dataclass(frozen=True)
class ResourceSnapshot:
    """Instantaneous snapshot of device resource utilization."""
    available_ram_mb: float
    used_ram_mb: float
    process_rss_mb: float
    process_pss_mb: float
    cpu_percent: float
    battery_percent: Optional[float] = None
    is_charging: Optional[bool] = None
    is_thermal_throttled: bool = False
    storage_free_mb: float = 0.0


@dataclass(frozen=True)
class ResourceBudget:
    """Hardware resource budget limits for the active process."""
    max_peak_pss_mb: float = 1536.0        # 1.5 GB peak PSS target
    max_steady_ram_mb: float = 1024.0      # 1.0 GB steady active target
    max_model_storage_mb: float = 500.0    # 500 MB model storage target
    max_framework_storage_mb: float = 150.0 # 150 MB core framework target
    max_concurrent_inferences: int = 1
    allow_accelerator: bool = True

    def is_within_budget(self, snapshot: ResourceSnapshot) -> bool:
        """Check if current process snapshot satisfies budget."""
        pss_to_check = snapshot.process_pss_mb if snapshot.process_pss_mb > 0 else snapshot.process_rss_mb
        return pss_to_check <= self.max_peak_pss_mb


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
            supports_fp16=True,
            supports_int8=True,
            supports_int4=True,
            compute_units=cpu_count
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
        pss_mb = getattr(mem_info, "pss", mem_info.rss) / (1024 * 1024)
        rss_mb = mem_info.rss / (1024 * 1024)

        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        battery_pct = battery.percent if battery else None
        charging = battery.power_plugged if battery else None

        return ResourceSnapshot(
            available_ram_mb=vm.available / (1024 * 1024),
            used_ram_mb=vm.used / (1024 * 1024),
            process_rss_mb=round(rss_mb, 2),
            process_pss_mb=round(pss_mb, 2),
            cpu_percent=psutil.cpu_percent(interval=None),
            battery_percent=battery_pct,
            is_charging=charging,
            is_thermal_throttled=False,
            storage_free_mb=round(storage_free_mb, 2)
        )
