"""Which operating system the engine runs on, and which host features work there.

Some apps read *the computer they run on* (its screen, media session, foreground window, webcam, sound,
notifications). Those depend on the OS; everything network-based works everywhere. This module is the one place
that knows the difference (docs/COMPATIBILITY.md has the full matrix):

* `current()` — "windows" | "macos" | "linux" | "android" (Raspberry Pi is "linux"; `is_raspberry_pi()` tells).
* `FEATURES` — host feature → the platforms it works on. Providers and apps declare a feature; the studio greys
  out what can't work here.
* `only_on(...)` — the JSON-schema marker for a setting (``json_schema_extra={"platforms": [...]}``) that the
  studio's schema form shows as a "Windows/macOS only" badge and disables on other hosts.

Pure and import-safe on every OS (no platform modules are imported here).
"""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path
from typing import Any, Literal

Platform = Literal["windows", "macos", "linux", "android"]
ALL: tuple[Platform, ...] = ("windows", "macos", "linux", "android")
DESKTOP: tuple[Platform, ...] = ("windows", "macos", "linux")

LABELS: dict[str, str] = {"windows": "Windows", "macos": "macOS", "linux": "Linux", "android": "Android"}
#: panel-sized names (tiny font, ≤ 30 px: the 1 px-margin text box)
SHORT: dict[str, str] = {"windows": "WIN", "macos": "MACOS", "linux": "LINUX", "android": "ANDROID"}

#: host feature -> platforms where it works (see docs/COMPATIBILITY.md for the reasons)
FEATURES: dict[str, tuple[Platform, ...]] = {
    # media session: Windows GSMTC (winrt), macOS AppleScript / nowplaying-cli, Linux MPRIS (playerctl)
    "media": ("windows", "macos", "linux"),
    # foreground window + icon: user32 (Windows), AppKit (macOS), xdotool on X11 (Linux; not Wayland)
    "window": ("windows", "macos", "linux"),
    # screen capture: Pillow ImageGrab (GDI, CoreGraphics, X11/XCB or gnome-screenshot on Linux)
    "screen": ("windows", "macos", "linux"),
    # "active window" / "around cursor" crops need the window rect / cursor position
    "screen_window": ("windows", "macos"),
    # audio capture through `soundcard` (WASAPI, CoreAudio, PulseAudio/PipeWire)
    "audio": ("windows", "macos", "linux"),
    # system-sound loopback: WASAPI loopback, PulseAudio monitor; macOS needs a virtual device (BlackHole)
    "audio_loopback": ("windows", "linux"),
    # webcam through OpenCV (DirectShow, AVFoundation, V4L2)
    "camera": ("windows", "macos", "linux"),
    # "is the camera / mic in use" from the Windows capability-access registry
    "onair": ("windows",),
    # seconds since the last input: GetLastInputInfo (Windows), IOHIDSystem (macOS)
    "idle": ("windows", "macos"),
    # full-screen app / game detection (holds back the eye-break nudge)
    "fullscreen": ("windows",),
    # mirror the OS's own notifications (Windows toast DB, macOS Notification Center DB)
    "notifications": ("windows", "macos"),
    # hand the panel its own clock when the computer goes to sleep (WM_POWERBROADCAST)
    "sleep_handoff": ("windows",),
    # CPU / RAM / disk / network via psutil (Android hides CPU and network counters from apps)
    "system": ALL,
}


@cache
def current() -> Platform:
    """The host OS. Android counts as its own platform (Chaquopy reports "android" on Python 3.13+, or
    "linux" with `sys.getandroidapilevel` on older builds)."""
    p = sys.platform
    if p == "win32" or p == "cygwin":
        return "windows"
    if p == "darwin":
        return "macos"
    if p == "android" or hasattr(sys, "getandroidapilevel"):
        return "android"
    return "linux"


@cache
def is_raspberry_pi() -> bool:
    try:
        model = Path("/proc/device-tree/model").read_bytes()
    except OSError:
        return False
    return b"raspberry pi" in model.lower()


def supported(feature: str, platform: str | None = None) -> bool:
    """Whether a host feature works on `platform` (default: this host). Unknown features count as supported."""
    plats = FEATURES.get(feature)
    return plats is None or (platform or current()) in plats


def label(platforms: tuple[str, ...] | list[str]) -> str:
    """("windows", "macos") -> "Windows/macOS only"."""
    return "/".join(LABELS.get(p, p) for p in platforms) + " only"


def only_on(*platforms: str, feature: str | None = None, **extra: Any) -> dict[str, Any]:
    """`json_schema_extra` for a setting that only works on some hosts.

    Pass platforms explicitly or a `feature` from FEATURES. Extra keys (e.g. ``group="Art"``) are merged, so::

        beat_sync: bool = Field(False, json_schema_extra=only_on(feature="audio", group="Art"))
    """
    plats = list(platforms) or list(FEATURES[feature or ""])
    return {"platforms": plats, **extra}


def info() -> dict[str, Any]:
    """What GET /api/meta reports: this host and every feature's support."""
    return {
        "platform": current(),
        "platform_label": LABELS[current()] + (" (Raspberry Pi)" if is_raspberry_pi() else ""),
        "features": {name: current() in plats for name, plats in FEATURES.items()},
    }
