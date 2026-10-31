"""Host telemetry via psutil — all calls are non-blocking.

Every metric is read on its own and is None when this host won't tell: Android (8+) hides /proc/stat and the
network counters from apps, containers may hide disks, desktops without a battery have none. A missing metric
never fails the whole reading; without psutil at all, the provider reports an error instead of crashing.

In the browser app (platform "web") there is no psutil and no access to the computer's counters. The page reports
what browsers do expose (web/webapp/host.js → worker → `browser_stats`, every 2 s) and the same keys are filled
from it: `cpu` from the Compute Pressure API (nominal / fair / serious / critical → 25 / 50 / 75 / 95 %, Chrome and
Edge), `ram` = this tab's JavaScript memory as a share of its limit (Chrome / Edge), `battery` / `plugged` (Battery
Status API), `net_down` = the browser's downlink estimate (Network Information API), plus `fps` (the page's frame
rate while visible), `cores` and `device_memory_gb`. Disk and uptime stay None. Every value is None where the
browser doesn't tell.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from ..platforms import current
from .base import Provider

try:
    import psutil
except ImportError:  # pragma: no cover — psutil is a dependency, but never let it break the engine
    psutil = None  # type: ignore[assignment]

log = logging.getLogger("deskdot.system")

#: Compute Pressure states → a CPU percentage for the bars (coarse on purpose: that's all a page may know)
PRESSURE = {"nominal": 25, "fair": 50, "serious": 75, "critical": 95}
#: the latest stats the page sent (browser app only); `browser_stats()` replaces it
_browser: dict[str, Any] | None = None
_browser_at = 0.0


def _num(v: Any, lo: float = 0.0, hi: float = 1e12) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if lo <= f <= hi and f == f else None


def browser_stats(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise what the page measured (web/webapp/host.js `sysStats`) into this provider's keys."""
    global _browser, _browser_at
    pressure = str(raw.get("pressure") or "")
    heap, limit = _num(raw.get("heap_used")), _num(raw.get("heap_limit"))
    batt = _num(raw.get("battery"), 0, 1)
    down = _num(raw.get("downlink_mbps"), 0, 1e5)
    out = {
        "cpu": PRESSURE.get(pressure),
        "pressure": pressure or None,
        "ram": round(heap / limit * 100) if heap is not None and limit else None,
        "ram_used_gb": round(heap / 1e9, 2) if heap is not None else None,
        "battery": round(batt * 100) if batt is not None else None,
        "plugged": bool(raw["charging"]) if isinstance(raw.get("charging"), bool) else None,
        "net_down": down * 125_000 if down is not None else None,  # Mbit/s → bytes/s, like psutil's rate
        "rtt_ms": _num(raw.get("rtt_ms"), 0, 1e5),
        "fps": _num(raw.get("fps"), 0, 1000),
        "cores": _num(raw.get("cores"), 1, 4096),
        "device_memory_gb": _num(raw.get("device_memory_gb"), 0, 4096),
    }
    _browser, _browser_at = out, time.monotonic()
    return out


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
    feature = "system"  # in a browser tab: what the page measures (`browser_stats`)

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

    def _from_browser(self) -> dict[str, Any] | None:
        b = _browser
        if b is None or time.monotonic() - _browser_at > 30:
            return None  # the page hasn't reported (yet), or the tab stopped reporting
        if b["cpu"] is not None:
            self.cpu_hist.append(b["cpu"])
        if b["ram"] is not None:
            self.ram_hist.append(b["ram"])
        return {
            **b,
            "disk": None,
            "net_up": None,
            "uptime": None,
            "cpu_hist": list(self.cpu_hist),
            "ram_hist": list(self.ram_hist),
            "browser": True,
        }

    async def fetch(self) -> dict[str, Any]:
        if current() == "web":
            return self._from_browser()  # type: ignore[return-value]  # None until the page reports: loading
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
