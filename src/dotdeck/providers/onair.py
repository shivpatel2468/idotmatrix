"""On-Air detection: is the webcam or microphone in use by any app right now? (Windows)

Windows records every capability access under

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\{webcam,microphone}

One subkey per packaged (Store) app, plus a `NonPackaged` key with one subkey per classic .exe (its path with
`\\` replaced by `#`). Each has `LastUsedTimeStart` / `LastUsedTimeStop` FILETIMEs; **a stop time of 0 means the
app is using the device right now**. Reading it is cheap and needs no permissions, so we poll every 2 s.

On other operating systems the provider reports `{"supported": False}` and never triggers.
DotDeck's own Python process is ignored (the Camera app would otherwise put the panel "on air").
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from .base import Provider

CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
DEVICES = ("webcam", "microphone")


def friendly(key: str) -> str:
    """'C:#Program Files#Zoom#bin#Zoom.exe' -> 'Zoom'; 'MSTeams_8wekyb3d8bbwe' -> 'MSTeams'."""
    if "#" in key:
        base = key.rsplit("#", 1)[-1]
        return base[:-4] if base.lower().endswith(".exe") else base
    name = key.split("_", 1)[0]
    return name.rsplit(".", 1)[-1] if "." in name else name


def _self_paths() -> set[str]:
    paths = {sys.executable, getattr(sys, "_base_executable", "") or ""}
    out = set()
    for p in paths:
        if p:
            out.add(os.path.normcase(os.path.realpath(p)).replace("\\", "#"))
            out.add(os.path.normcase(p).replace("\\", "#"))
    return out


def _values(winreg: Any, key: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = 0
    while True:
        try:
            name, value, _kind = winreg.EnumValue(key, i)
        except OSError:
            return out
        out[name] = value
        i += 1


def _subkeys(winreg: Any, key: Any) -> list[str]:
    out: list[str] = []
    i = 0
    while True:
        try:
            out.append(winreg.EnumKey(key, i))
        except OSError:
            return out
        i += 1


def scan_consent(
    winreg: Any, devices: tuple[str, ...] = DEVICES, ignore: set[str] | None = None
) -> dict[str, list[str]]:
    """Registry key names (packaged ids or '#'-paths) currently using each device.

    `winreg` is injected so tests can pass a fake. An entry is "in use" when it has a
    `LastUsedTimeStart` and its `LastUsedTimeStop` is 0.
    """
    ignore = ignore or set()
    found: dict[str, list[str]] = {d: [] for d in devices}
    for dev in devices:
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{CONSENT}\\{dev}")
        except OSError:
            continue
        for name in _subkeys(winreg, root):
            try:
                sub = winreg.OpenKey(root, name)
            except OSError:
                continue
            children = [(name, sub)]
            if name == "NonPackaged":
                children = []
                for exe in _subkeys(winreg, sub):
                    try:
                        children.append((exe, winreg.OpenKey(sub, exe)))
                    except OSError:
                        continue
            for key_name, key in children:
                v = _values(winreg, key)
                live = v.get("LastUsedTimeStart") and v.get("LastUsedTimeStop", 1) == 0
                if live and os.path.normcase(key_name) not in ignore:
                    found[dev].append(key_name)
    return found


def filter_apps(found: dict[str, list[str]], devices: set[str], exclude: str) -> dict[str, list[str]]:
    """Keep only watched devices, drop apps whose name or path contains an excluded word."""
    words = [w.strip().lower() for w in exclude.split(",") if w.strip()]
    out: dict[str, list[str]] = {}
    for dev, keys in found.items():
        if dev not in devices:
            continue
        keep = [friendly(k) for k in keys if not any(w in k.lower() for w in words)]
        if keep:
            out[dev] = sorted(set(keep))
    return out


class OnAirProvider(Provider[dict[str, Any]]):
    name = "onair"
    interval = 2.0
    retry = 10.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._ignore = _self_paths()

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        return old is None or old.get("in_use") != new.get("in_use")

    def _scan(self) -> dict[str, Any]:
        if sys.platform != "win32":
            return {"supported": False, "in_use": {}}
        import winreg

        return {"supported": True, "in_use": scan_consent(winreg, DEVICES, self._ignore)}

    async def fetch(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._scan)
