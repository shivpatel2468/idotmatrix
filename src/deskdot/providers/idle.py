"""User activity (Windows): seconds since the last keyboard/mouse input, and whether a full-screen app is up.

* idle time: `GetLastInputInfo` (user32) against `GetTickCount` — both 32-bit millisecond ticks.
* full screen: `SHQueryUserNotificationState` (shell32). It reports QUNS_BUSY (2) for a full-screen app,
  QUNS_RUNNING_D3D_FULL_SCREEN (3) for exclusive-mode games and QUNS_PRESENTATION_MODE (4); these are the
  states in which Windows itself holds back notifications, so we hold back the eye-break nudge too.

macOS reports idle time from `ioreg` (IOHIDSystem's HIDIdleTime); it has no full-screen signal, so
`fullscreen` stays False there. Other operating systems report `{"supported": False}`; features built on this
provider stay dormant.
"""

from __future__ import annotations

import asyncio
import ctypes
import re
import subprocess
import sys
from typing import Any

from .base import Provider

FULLSCREEN_STATES = {2, 3, 4}


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_seconds() -> float:
    info = _LastInput()
    info.cbSize = ctypes.sizeof(_LastInput)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):  # type: ignore[attr-defined]
        return 0.0
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF  # type: ignore[attr-defined]
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


def notification_state() -> int:
    state = ctypes.c_int(0)
    try:
        hr = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return 0
    return state.value if hr == 0 else 0


def mac_idle_seconds() -> float | None:
    """Seconds since the last input on macOS (blocking: ~10 ms `ioreg` call). None if unreadable."""
    try:
        out = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True, timeout=2.0
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    return int(m.group(1)) / 1e9 if m else None


class IdleProvider(Provider[dict[str, Any]]):
    name = "idle"
    interval = 5.0
    retry = 30.0

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        # the studio doesn't need a push every 5 s; only when full-screen state flips
        return old is None or old.get("fullscreen") != new.get("fullscreen")

    async def fetch(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._read)

    def _read(self) -> dict[str, Any]:
        if sys.platform == "darwin":
            idle = mac_idle_seconds()
            if idle is not None:
                return {"supported": True, "idle_s": round(idle, 1), "fullscreen": False, "state": 0}
        if sys.platform != "win32":
            return {"supported": False, "idle_s": 0.0, "fullscreen": False, "state": 0}
        state = notification_state()
        return {
            "supported": True,
            "idle_s": round(idle_seconds(), 1),
            "fullscreen": state in FULLSCREEN_STATES,
            "state": state,
        }
