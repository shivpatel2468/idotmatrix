"""The app you're using right now: foreground window, its process, its real icon, and time spent today.

* Windows — user32/shell32 via ctypes. Icons are extracted from the executable once and cached as 32x32 RGBA
  arrays, so any app — not just a curated list — gets its own artwork on the panel.
* macOS — AppKit (pyobjc): frontmost app + its bundle icon; window titles need Screen Recording permission.
* Linux — X11 only, through `xdotool` (if installed); no icons (a monogram tile is drawn). Wayland compositors
  don't reveal the focused window to other apps, so there it reports an error.
* Android — not available (`feature = "window"`).
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import sys
import time
from datetime import date
from typing import Any

import numpy as np

from .base import Provider

try:
    import psutil
except ImportError:  # optional: only used to name the foreground process
    psutil = None  # type: ignore[assignment]

log = logging.getLogger("deskdot.window")
IS_WIN = sys.platform == "win32"

# Friendly names for common executables (the process name is used otherwise)
FRIENDLY = {
    "code.exe": "VS Code",
    "cursor.exe": "Cursor",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "spotify.exe": "Spotify",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "ms-teams.exe": "Teams",
    "teams.exe": "Teams",
    "outlook.exe": "Outlook",
    "olk.exe": "Outlook",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "windowsterminal.exe": "Terminal",
    "cmd.exe": "Command",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell",
    "explorer.exe": "Explorer",
    "figma.exe": "Figma",
    "notion.exe": "Notion",
    "obsidian.exe": "Obsidian",
    "steam.exe": "Steam",
    "steamwebhelper.exe": "Steam",
    "vlc.exe": "VLC",
    "photoshop.exe": "Photoshop",
    "claude.exe": "Claude",
    "whatsapp.exe": "WhatsApp",
    "zoom.exe": "Zoom",
    "idea64.exe": "IntelliJ",
    "pycharm64.exe": "PyCharm",
    "devenv.exe": "Visual Studio",
    "blender.exe": "Blender",
    "obs64.exe": "OBS",
    "telegram.exe": "Telegram",
    "notepad.exe": "Notepad",
    "cs2.exe": "CS2",
    "valorant.exe": "Valorant",
    "minecraft.exe": "Minecraft",
    "javaw.exe": "Java",
}

# Category drives the micro-animation around the icon
CATEGORY = {
    "code": {
        "code.exe",
        "cursor.exe",
        "idea64.exe",
        "pycharm64.exe",
        "devenv.exe",
        "windowsterminal.exe",
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "notepad.exe",
        "claude.exe",
    },
    "browser": {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"},
    "music": {"spotify.exe", "vlc.exe", "music.ui.exe", "applemusic.exe"},
    "chat": {
        "discord.exe",
        "slack.exe",
        "ms-teams.exe",
        "teams.exe",
        "whatsapp.exe",
        "telegram.exe",
        "zoom.exe",
        "outlook.exe",
        "olk.exe",
    },
    "game": {"steam.exe", "steamwebhelper.exe", "cs2.exe", "valorant.exe", "minecraft.exe", "javaw.exe"},
    "design": {"figma.exe", "photoshop.exe", "blender.exe", "illustrator.exe"},
}


# macOS: process names are the app's localizedName lower-cased without spaces + ".app"
FRIENDLY.update(
    {
        "visualstudiocode.app": "VS Code",
        "code.app": "VS Code",
        "googlechrome.app": "Chrome",
        "safari.app": "Safari",
        "spotify.app": "Spotify",
        "music.app": "Music",
        "discord.app": "Discord",
        "slack.app": "Slack",
        "terminal.app": "Terminal",
        "iterm2.app": "iTerm",
        "finder.app": "Finder",
        "xcode.app": "Xcode",
        "claude.app": "Claude",
        "cursor.app": "Cursor",
        "figma.app": "Figma",
        "arc.app": "Arc",
    }
)
CATEGORY["code"] |= {
    "visualstudiocode.app",
    "code.app",
    "cursor.app",
    "terminal.app",
    "iterm2.app",
    "xcode.app",
    "claude.app",
}
CATEGORY["browser"] |= {"googlechrome.app", "safari.app", "arc.app", "firefox.app"}
CATEGORY["music"] |= {"spotify.app", "music.app"}
CATEGORY["chat"] |= {"discord.app", "slack.app", "messages.app", "whatsapp.app"}
CATEGORY["design"] |= {"figma.app"}


def category_of(proc: str) -> str:
    p = proc.lower()
    for cat, names in CATEGORY.items():
        if p in names or f"{p}.exe" in names:  # Linux process names have no ".exe"
            return cat
    return "other"


def friendly_name(proc: str) -> str:
    key = proc.lower()
    return (
        FRIENDLY.get(key)
        or FRIENDLY.get(f"{key}.exe")
        or (proc.removesuffix(".exe").removesuffix(".EXE").title() or "Desktop")
    )


def _linux_foreground() -> tuple[str, str, str]:
    """(process name, exe path, window title) of the focused X11 window through `xdotool`. Blocking: run it
    in a thread."""
    import shutil
    import subprocess

    if not shutil.which("xdotool"):
        raise RuntimeError("active-window tracking on Linux needs xdotool (sudo apt install xdotool) and X11")

    def run(*args: str) -> str:
        r = subprocess.run(["xdotool", "getactivewindow", *args], capture_output=True, text=True, timeout=1.5)
        if r.returncode != 0:
            raise RuntimeError("no focused X11 window (Wayland hides it from other apps; use an X11 session)")
        return r.stdout.strip()

    title = run("getwindowname")
    proc, exe = "", ""
    try:
        pid = int(run("getwindowpid"))
        if psutil is not None:
            p = psutil.Process(pid)
            proc, exe = p.name(), p.exe()
        else:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
                proc = fh.read().strip()
    except (ValueError, OSError, RuntimeError) as e:
        log.debug("foreground pid: %s", e)
    except Exception as e:  # psutil.Error
        log.debug("foreground process: %s", e)
    return proc, exe, title


if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    gdi32 = ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.DrawIconEx.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HICON,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.HBRUSH,
        wintypes.UINT,
    ]
    shell32.ExtractIconExW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HICON),
        ctypes.POINTER(wintypes.HICON),
        wintypes.UINT,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    user32.DestroyIcon.argtypes = [wintypes.HICON]


def extract_icon(exe: str, size: int = 32) -> np.ndarray | None:
    """Return the executable's large icon as an (size, size, 4) RGBA uint8 array, or None."""
    if not IS_WIN or not exe:
        return None
    large = wintypes.HICON()
    if shell32.ExtractIconExW(exe, 0, ctypes.byref(large), None, 1) <= 0 or not large:
        return None
    hdc = gdi32.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), size, -size, 1, 32, 0, 0, 0, 0, 0, 0)
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    try:
        old = gdi32.SelectObject(hdc, hbmp)
        user32.DrawIconEx(hdc, 0, 0, large, size, size, 0, None, 3)  # DI_NORMAL
        buf = (ctypes.c_uint8 * (size * size * 4)).from_address(bits.value)
        bgra = np.frombuffer(buf, dtype=np.uint8).reshape(size, size, 4).copy()
        gdi32.SelectObject(hdc, old)
    finally:
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc)
        user32.DestroyIcon(large)
    rgba = bgra[..., [2, 1, 0, 3]]
    if not rgba[..., 3].any():  # legacy icons without alpha: treat non-black as opaque
        rgba[..., 3] = np.where(rgba[..., :3].any(axis=2), 255, 0)
    return rgba


def _mac_foreground() -> tuple[str, str, str]:
    """(process name, app bundle path, window title) of the frontmost macOS app (pyobjc)."""
    from AppKit import NSWorkspace  # type: ignore[import-not-found]

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    name = str(app.localizedName() or "")
    bundle = str(app.bundleURL().path()) if app.bundleURL() else ""
    title = ""
    try:  # window titles need Screen Recording permission; degrade silently
        from Quartz import (  # type: ignore[import-not-found]
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
        )

        pid = app.processIdentifier()
        for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []:
            if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0:
                title = str(w.get("kCGWindowName") or "")
                break
    except Exception:
        pass
    return name, bundle, title


def _mac_icon(bundle: str, size: int = 32) -> np.ndarray | None:
    import io

    from AppKit import (  # type: ignore[import-not-found]
        NSBitmapImageRep,
        NSMakeSize,
        NSPNGFileType,
        NSWorkspace,
    )
    from PIL import Image

    img = NSWorkspace.sharedWorkspace().iconForFile_(bundle)
    img.setSize_(NSMakeSize(size, size))
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    png = rep.representationUsingType_properties_(NSPNGFileType, None)
    pil = Image.open(io.BytesIO(bytes(png))).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    return np.asarray(pil, dtype=np.uint8).copy()


class WindowProvider(Provider[dict[str, Any]]):
    name = "window"
    interval = 0.5
    retry = 5.0
    feature = "window"

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.icons: dict[str, np.ndarray | None] = {}
        self._cur: str | None = None
        self._since = time.time()
        self._usage_day = date.today()
        self.usage: dict[str, float] = {}  # proc -> seconds today
        self.exes: dict[str, str] = {}  # proc -> exe path (for icons in focus stats)
        self._last_tick = time.time()

    def icon(self, exe: str) -> np.ndarray | None:
        if exe not in self.icons:
            try:
                self.icons[exe] = _mac_icon(exe) if sys.platform == "darwin" else extract_icon(exe)
            except Exception as e:
                log.debug("icon for %s: %s", exe, e)
                self.icons[exe] = None
        return self.icons[exe]

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        return not old or old.get("proc") != new.get("proc") or old.get("title") != new.get("title")

    def _foreground(self) -> tuple[str, str, str]:
        if sys.platform == "darwin":
            name, bundle, title = _mac_foreground()
            return name.lower().replace(" ", "") + ".app", bundle, title
        if not IS_WIN:
            raise RuntimeError("active-window tracking needs Windows, macOS or Linux (X11)")
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc, exe = "", ""
        if psutil is not None:
            try:
                p = psutil.Process(pid.value)
                proc, exe = p.name(), p.exe()
            except (psutil.Error, OSError):
                pass
        return proc, exe, title_buf.value

    async def fetch(self) -> dict[str, Any]:
        from ..platforms import current

        if current() == "linux":
            proc, exe, title = await asyncio.to_thread(_linux_foreground)
        else:
            proc, exe, title = self._foreground()
        now = time.time()
        if date.today() != self._usage_day:
            self.usage, self._usage_day = {}, date.today()
        if self._cur:
            self.usage[self._cur] = self.usage.get(self._cur, 0.0) + (now - self._last_tick)
        self._last_tick = now
        if proc.lower() != (self._cur or ""):
            self._cur, self._since = proc.lower(), now
        if exe:
            self.icon(exe)
            self.exes[proc.lower()] = exe
        key = proc.lower()
        top = sorted(self.usage.items(), key=lambda kv: -kv[1])[:5]
        return {
            "proc": key,
            "exe": exe,
            "name": friendly_name(proc),
            "title": title,
            "category": category_of(key),
            "since": self._since,
            "top": [
                {
                    "proc": k,
                    "exe": self.exes.get(k, ""),
                    "name": friendly_name(k),
                    "seconds": v,
                }
                for k, v in top
            ],
        }
