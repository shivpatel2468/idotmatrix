"""Hand the panel off when the computer sleeps, and take it back on wake (Windows).

Windows announces sleep with WM_POWERBROADCAST / PBT_APMSUSPEND — but only to top-level windows (message-only
windows don't get broadcasts), so a hidden window runs a message loop on a daemon thread. The system allows
only a moment before suspending, so on sleep we always send the panel's firmware clock (a few bytes) rather
than uploading a GIF. On other platforms this is a no-op; exit hand-off still works everywhere.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import sys
import threading
from typing import Any

log = logging.getLogger("deskdot.power")

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012


def start_power_watch(engine: Any, loop: asyncio.AbstractEventLoop) -> threading.Thread | None:
    if sys.platform != "win32":
        return None
    t = threading.Thread(target=_run, args=(engine, loop), name="deskdot-power", daemon=True)
    t.start()
    return t


def _run(engine: Any, loop: asyncio.AbstractEventLoop) -> None:
    from ctypes import wintypes  # Windows only: keep the module importable everywhere

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    lresult = ctypes.c_ssize_t
    wndproc_t = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.DefWindowProcW.restype = lresult
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    state = {"slept": False}

    def on_msg(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_POWERBROADCAST:
            try:
                if wparam == PBT_APMSUSPEND and engine.handoff_config()["on_sleep"] and not engine.released:
                    fut = asyncio.run_coroutine_threadsafe(engine.handoff("clock"), loop)
                    try:
                        fut.result(timeout=2.5)  # Windows gives us only a moment
                    except Exception:
                        pass
                    state["slept"] = True
                    log.info("computer is going to sleep: panel handed off to its clock")
                elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND) and state["slept"]:
                    state["slept"] = False
                    loop.call_soon_threadsafe(engine.take_back)
                    log.info("computer woke up: taking the panel back")
            except Exception:
                log.exception("power event handling failed")
            return 1
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc = wndproc_t(on_msg)  # keep a reference for the thread's lifetime

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", wndproc_t),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.hInstance = hinst
    wc.lpszClassName = "DeskDotPowerWatch"
    if not user32.RegisterClassW(ctypes.byref(wc)):
        log.warning("power watch: RegisterClass failed; sleep hand-off disabled")
        return
    user32.CreateWindowExW.restype = wintypes.HWND
    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "DeskDot", 0, 0, 0, 0, 0, None, None, hinst, None)
    if not hwnd:
        log.warning("power watch: CreateWindow failed; sleep hand-off disabled")
        return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
