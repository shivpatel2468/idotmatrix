"""Host telemetry via psutil — all calls are non-blocking."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import psutil

from .base import Provider


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


class SystemProvider(Provider[dict[str, Any]]):
    name = "system"
    interval = 1.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        psutil.cpu_percent(interval=None)  # prime: first call always returns 0
        self.cpu_hist: deque[float] = deque(maxlen=60)
        self.ram_hist: deque[float] = deque(maxlen=60)
        self._net = psutil.net_io_counters()
        self._net_t = time.monotonic()
        self._disk: dict[str, float] = {"percent": 0.0, "total_gb": 0.0}
        self._disk_t = 0.0

    async def fetch(self) -> dict[str, Any]:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        now = time.monotonic()
        if now - self._disk_t > 30:
            self._disk, self._disk_t = disk_usage_all(), now
        net = psutil.net_io_counters()
        dt = max(1e-3, now - self._net_t)
        down = (net.bytes_recv - self._net.bytes_recv) / dt
        up = (net.bytes_sent - self._net.bytes_sent) / dt
        self._net, self._net_t = net, now
        self.cpu_hist.append(cpu)
        self.ram_hist.append(mem.percent)
        batt = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        return {
            "cpu": round(cpu),
            "ram": round(mem.percent),
            "ram_used_gb": round(mem.used / 1e9, 1),
            "disk": round(self._disk["percent"]),
            "net_down": down,
            "net_up": up,
            "battery": round(batt.percent) if batt else None,
            "plugged": bool(batt.power_plugged) if batt else None,
            "uptime": int(time.time() - psutil.boot_time()),
            "cpu_hist": list(self.cpu_hist),
            "ram_hist": list(self.ram_hist),
        }
