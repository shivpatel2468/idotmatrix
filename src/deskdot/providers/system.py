"""Host telemetry via psutil — all calls are non-blocking.

Every metric is read on its own and is None when this host won't tell: Android (8+) hides /proc/stat and the
network counters from apps, containers may hide disks, desktops without a battery have none. A missing metric
never fails the whole reading; without psutil at all, the provider reports an error instead of crashing.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from .base import Provider

try:
    import psutil
except ImportError:  # pragma: no cover — psutil is a dependency, but never let it break the engine
    psutil = None  # type: ignore[assignment]

log = logging.getLogger("deskdot.system")


def disk_usage_all() -> dict[str, float]:
    """Aggregate usage across fixed drives (skips optical and unreadable mounts)."""
    total = used = 0
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.mountpoint:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        total += u.total
        used += u.used
    return {"percent": round(used / total * 100, 1) if total else 0.0, "total_gb": round(total / 1e9, 1)}


def _try(fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except Exception:  # PermissionError on Android, NotImplementedError, psutil.Error …
        return None


class SystemProvider(Provider[dict[str, Any]]):
    name = "system"
    interval = 1.0
    feature = "system"  # not in a browser tab (no psutil there)

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.cpu_hist: deque[float] = deque(maxlen=60)
        self.ram_hist: deque[float] = deque(maxlen=60)
        self._disk: dict[str, float] | None = {"percent": 0.0, "total_gb": 0.0}
        self._disk_t = 0.0
        self._net: Any = None
        self._net_t = time.monotonic()
        if psutil is not None:
            _try(psutil.cpu_percent, None)  # prime: first call always returns 0
            self._net = _try(psutil.net_io_counters)

    async def fetch(self) -> dict[str, Any]:
        if psutil is None:
            raise RuntimeError("system stats need psutil (uv sync)")
        cpu = _try(psutil.cpu_percent, None)
        mem = _try(psutil.virtual_memory)
        now = time.monotonic()
        if now - self._disk_t > 30:
            self._disk, self._disk_t = _try(disk_usage_all), now
        net = _try(psutil.net_io_counters)
        down = up = None
        if net is not None and self._net is not None:
            dt = max(1e-3, now - self._net_t)
            down = (net.bytes_recv - self._net.bytes_recv) / dt
            up = (net.bytes_sent - self._net.bytes_sent) / dt
        self._net, self._net_t = net, now
        if cpu is not None:
            self.cpu_hist.append(cpu)
        if mem is not None:
            self.ram_hist.append(mem.percent)
        batt = _try(psutil.sensors_battery) if hasattr(psutil, "sensors_battery") else None
        boot = _try(psutil.boot_time)
        return {
            "cpu": round(cpu) if cpu is not None else None,
            "ram": round(mem.percent) if mem is not None else None,
            "ram_used_gb": round(mem.used / 1e9, 1) if mem is not None else None,
            "disk": round(self._disk["percent"]) if self._disk else None,
            "net_down": down,
            "net_up": up,
            "battery": round(batt.percent) if batt else None,
            "plugged": bool(batt.power_plugged) if batt else None,
            "uptime": int(time.time() - boot) if boot else None,
            "cpu_hist": list(self.cpu_hist),
            "ram_hist": list(self.ram_hist),
        }
