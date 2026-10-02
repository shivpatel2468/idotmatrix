"""DeskDot Launcher: a system-wide, Spotlight-style command bar for the panel (docs/LAUNCHERS.md).

`deskdot launcher` opens a small frameless, always-on-top window (pywebview) that loads the launcher page the
engine serves at `/launcher` (web/launcher.html). A global hotkey (default Ctrl+Alt+Space, `launcher_hotkey` in
deskdot.toml) toggles it, Esc or clicking elsewhere hides it, and a tray icon offers Show / Open studio / Quit.

Like every other client it only talks to the engine over HTTP: the engine owns the Bluetooth link (CLAUDE.md
rule 4). When the engine isn't running, the window shows a local "Start DeskDot" page that launches
`deskdot serve` detached.

Platform notes
- Windows: the hotkey is a `RegisterHotKey` on a background thread (ctypes, no extra package); "start with
  login" is a value under HKCU\\...\\Run.
- macOS: the hotkey uses an AppKit global key monitor (needs Accessibility permission); "start with login" is a
  LaunchAgent plist. The native menu-bar app in integrations/macos/DeskDotBar is the better fit on a Mac.
- Linux: no global hotkey of our own; bind a desktop shortcut to `deskdot launcher --show`.

Start with login is never written unless the user turns it on (`--autostart on`, `launcher_autostart = true`
or the tray menu).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import plistlib
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("deskdot.launcher")

APP_NAME = "DeskDot Launcher"
DEFAULT_HOTKEY = "Ctrl+Alt+Space"
DEFAULT_URL = "http://127.0.0.1:8765"
#: local TCP port for single-instance control (`deskdot launcher --show` from a desktop shortcut)
CONTROL_PORT = 8797
WIDTH, HEIGHT = 780, 500

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "DeskDot Launcher"
LAUNCH_AGENT_ID = "com.deskdot.launcher"


# ===================================================================== hotkeys
MODIFIERS = ("ctrl", "alt", "shift", "win")
_MOD_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "^": "ctrl",
    "alt": "alt",
    "option": "alt",
    "opt": "alt",
    "⌥": "alt",
    "shift": "shift",
    "⇧": "shift",
    "win": "win",
    "super": "win",
    "meta": "win",
    "cmd": "win",
    "command": "win",
    "⌘": "win",
}
_KEY_ALIASES = {
    "space": "space",
    "spacebar": "space",
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "esc": "escape",
    "escape": "escape",
    "`": "backquote",
    "backquote": "backquote",
    "grave": "backquote",
    "tilde": "backquote",
    ".": "period",
    "period": "period",
    ",": "comma",
    "comma": "comma",
    "/": "slash",
    "slash": "slash",
    ";": "semicolon",
    "semicolon": "semicolon",
    "home": "home",
    "end": "end",
    "insert": "insert",
    "ins": "insert",
    "pause": "pause",
}
_WIN_MODS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
_WIN_VK = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "backquote": 0xC0,
    "period": 0xBE,
    "comma": 0xBC,
    "slash": 0xBF,
    "semicolon": 0xBA,
    "home": 0x24,
    "end": 0x23,
    "insert": 0x2D,
    "pause": 0x13,
}
#: Carbon virtual key codes (kVK_*), for the macOS key monitor
MAC_KEYCODES: dict[str, int] = {
    **dict(zip("asdfhgzxcv", (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), strict=True)),
    **dict(zip("bqweryt", (11, 12, 13, 14, 15, 16, 17), strict=True)),
    **dict(zip("123465", (18, 19, 20, 21, 22, 23), strict=True)),
    **dict(zip("97", (25, 26), strict=True)),
    "8": 28,
    "0": 29,
    "o": 31,
    "u": 32,
    "i": 34,
    "p": 35,
    "l": 37,
    "j": 38,
    "k": 40,
    "n": 45,
    "m": 46,
    "enter": 36,
    "tab": 48,
    "space": 49,
    "backquote": 50,
    "escape": 53,
    "period": 47,
    "comma": 43,
    "slash": 44,
    "semicolon": 41,
    "home": 115,
    "end": 119,
    **{
        f"f{i + 1}": c
        for i, c in enumerate((122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106))
    },
}


@dataclass(frozen=True)
class Hotkey:
    """A parsed shortcut. `win` is the Windows key on Windows/Linux and ⌘ on macOS."""

    mods: frozenset[str]
    key: str  # "space", "a".."z", "0".."9", "f1".."f24", "enter", "backquote", …

    def __str__(self) -> str:
        names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
        key = self.key.upper() if len(self.key) == 1 or self.key.startswith("f") else self.key.capitalize()
        return "+".join([*(names[m] for m in MODIFIERS if m in self.mods), key])


def parse_hotkey(text: str) -> Hotkey:
    """`"Ctrl+Alt+Space"`, `"cmd+shift+k"`, `"⌥ Space"`, `"F9"` → Hotkey. Raises ValueError when it can't be used."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty hotkey")
    parts = [p.strip().lower() for p in raw.replace(" ", "+").split("+") if p.strip()]
    mods: set[str] = set()
    key: str | None = None
    for p in parts:
        if p in _MOD_ALIASES:
            mods.add(_MOD_ALIASES[p])
            continue
        k = _KEY_ALIASES.get(p)
        if k is None and len(p) == 1 and p.isascii() and p.isalnum():
            k = p
        if k is None and p.startswith("f") and p[1:].isdigit() and 1 <= int(p[1:]) <= 24:
            k = p
        if k is None:
            raise ValueError(f"unknown key {p!r} in hotkey {text!r}")
        if key is not None:
            raise ValueError(f"hotkey {text!r} has more than one key")
        key = k
    if key is None:
        raise ValueError(f"hotkey {text!r} has no key, only modifiers")
    if not mods and not key.startswith("f"):
        raise ValueError(f"hotkey {text!r} needs a modifier (Ctrl, Alt, Shift or Win/⌘)")
    return Hotkey(frozenset(mods), key)


def win_hotkey(hk: Hotkey) -> tuple[int, int]:
    """(fsModifiers, virtual-key) for user32.RegisterHotKey."""
    mods = MOD_NOREPEAT
    for m in hk.mods:
        mods |= _WIN_MODS[m]
    if hk.key in _WIN_VK:
        vk = _WIN_VK[hk.key]
    elif len(hk.key) == 1:
        vk = ord(hk.key.upper())
    else:  # f1..f24
        vk = 0x70 + int(hk.key[1:]) - 1
    return mods, vk


# ===================================================================== configuration
@dataclass
class LauncherConfig:
    url: str = DEFAULT_URL
    hotkey: Hotkey = field(default_factory=lambda: parse_hotkey(DEFAULT_HOTKEY))
    autostart: bool = False  # deskdot.toml `launcher_autostart`; only acted on when True
    project_dir: Path = field(default_factory=Path.cwd)
    config_path: Path | None = None
    data_dir: Path = Path("data")


def load_launcher_config(path: Path | None = None, env: dict[str, str] | None = None) -> LauncherConfig:
    """Read the launcher keys from deskdot.toml (the engine ignores keys it doesn't know) + DESKDOT_* env."""
    env = dict(os.environ) if env is None else env
    p = path or Path(env.get("DESKDOT_CONFIG") or "deskdot.toml")
    raw: dict[str, Any] = {}
    if p.is_file():
        try:
            raw = tomllib.loads(p.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            log.warning("can't read %s: %s", p, e)
    port = int(raw.get("port", 8765))
    url = env.get("DESKDOT_URL") or raw.get("launcher_url") or f"http://127.0.0.1:{port}"
    hk_text = env.get("DESKDOT_LAUNCHER_HOTKEY") or raw.get("launcher_hotkey") or DEFAULT_HOTKEY
    try:
        hotkey = parse_hotkey(str(hk_text))
    except ValueError as e:
        log.warning("%s; using %s", e, DEFAULT_HOTKEY)
        hotkey = parse_hotkey(DEFAULT_HOTKEY)
    auto = raw.get("launcher_autostart", False)
    if "DESKDOT_LAUNCHER_AUTOSTART" in env:
        auto = env["DESKDOT_LAUNCHER_AUTOSTART"].strip().lower() in ("1", "true", "yes", "on")
    project = (p.resolve().parent if p.is_file() else Path.cwd()).resolve()
    data_dir = Path(raw.get("data_dir", "data"))
    return LauncherConfig(
        url=str(url).rstrip("/"),
        hotkey=hotkey,
        autostart=bool(auto),
        project_dir=project,
        config_path=p.resolve() if p.is_file() else None,
        data_dir=data_dir if data_dir.is_absolute() else project / data_dir,
    )


# ===================================================================== start with login
def _gui_python() -> str:
    """pythonw.exe on Windows so the login item opens no console window."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def autostart_command(cfg: LauncherConfig) -> list[str]:
    cmd = [_gui_python(), "-m", "deskdot", "launcher", "--background"]
    if cfg.config_path:
        cmd += ["--config", str(cfg.config_path)]
    return cmd


def _launch_agent_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_ID}.plist"


def _desktop_entry_path(home: Path) -> Path:
    return home / ".config" / "autostart" / "deskdot-launcher.desktop"


def autostart_enabled(*, platform: str | None = None, home: Path | None = None, reg: Any = None) -> bool:
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "win32":
        reg = reg or _winreg()
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as k:
                reg.QueryValueEx(k, RUN_VALUE)
            return True
        except OSError:
            return False
    if platform == "darwin":
        return _launch_agent_path(home).exists()
    return _desktop_entry_path(home).exists()


def set_autostart(
    enabled: bool,
    command: list[str],
    *,
    workdir: Path | None = None,
    platform: str | None = None,
    home: Path | None = None,
    reg: Any = None,
) -> str:
    """Turn "start with login" on or off for this user. Returns where it was written (or removed)."""
    platform = platform or sys.platform
    home = home or Path.home()
    if platform == "win32":
        reg = reg or _winreg()
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as k:
            if enabled:
                reg.SetValueEx(k, RUN_VALUE, 0, reg.REG_SZ, subprocess.list2cmdline(command))
            else:
                with contextlib.suppress(FileNotFoundError):
                    reg.DeleteValue(k, RUN_VALUE)
        return f"HKCU\\{RUN_KEY}\\{RUN_VALUE}"
    if platform == "darwin":
        path = _launch_agent_path(home)
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            plist: dict[str, Any] = {
                "Label": LAUNCH_AGENT_ID,
                "ProgramArguments": command,
                "RunAtLoad": True,
                "ProcessType": "Interactive",
            }
            if workdir:
                plist["WorkingDirectory"] = str(workdir)
            path.write_bytes(plistlib.dumps(plist))
        else:
            path.unlink(missing_ok=True)
        return str(path)
    path = _desktop_entry_path(home)
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        exec_line = " ".join(f'"{c}"' if " " in c else c for c in command)
        path.write_text(
            "[Desktop Entry]\nType=Application\nName=DeskDot Launcher\n"
            f"Exec={exec_line}\n"
            + (f"Path={workdir}\n" if workdir else "")
            + "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    else:
        path.unlink(missing_ok=True)
    return str(path)


def _winreg() -> Any:
    import winreg

    return winreg


# ===================================================================== the engine
def engine_alive(url: str, timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as r:
            return bool(json.loads(r.read().decode()).get("ok"))
    except (OSError, ValueError):
        return False


def engine_command(cfg: LauncherConfig) -> list[str]:
    cmd = [sys.executable, "-m", "deskdot", "serve"]
    if cfg.config_path:
        cmd += ["--config", str(cfg.config_path)]
    return cmd


def start_engine(cfg: LauncherConfig) -> subprocess.Popen[bytes]:
    """Start `deskdot serve` detached from the launcher (it keeps running when the launcher quits)."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    logf = (cfg.data_dir / "engine-launcher.log").open("ab")
    kw: dict[str, Any] = {"cwd": str(cfg.project_dir), "stdout": logf, "stderr": subprocess.STDOUT}
    kw["stdin"] = subprocess.DEVNULL
    if sys.platform == "win32":
        kw["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
            | 0x01000000  # BREAKAWAY_FROM_JOB
        )
    else:
        kw["start_new_session"] = True
    try:
        return subprocess.Popen(engine_command(cfg), **kw)
    except OSError:
        if sys.platform != "win32":
            raise
        kw["creationflags"] &= ~0x01000000  # not allowed to break away from our job: stay in it
        return subprocess.Popen(engine_command(cfg), **kw)


# ===================================================================== single instance
def send_control(cmd: str, port: int = CONTROL_PORT, timeout: float = 0.6) -> bool:
    """Ask a running launcher to `show` / `toggle` / `hide` / `quit`. False when none is running."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall(f"deskdot-launcher {cmd}\n".encode())
            return s.recv(16).startswith(b"ok")
    except OSError:
        return False


class ControlServer(threading.Thread):
    """Listens on 127.0.0.1:CONTROL_PORT so a second `deskdot launcher` (or a desktop shortcut) can reach us."""

    def __init__(self, handler: Callable[[str], None], port: int = CONTROL_PORT) -> None:
        super().__init__(daemon=True, name="launcher-control")
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.sock.bind(("127.0.0.1", port))  # OSError when another launcher already owns it
        self.sock.listen(4)

    def run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(1.0)
                    line = conn.recv(128).decode(errors="ignore").strip()
                    if line.startswith("deskdot-launcher "):
                        cmd = line.split(" ", 1)[1]
                        if cmd in ("show", "toggle", "hide", "quit"):
                            conn.sendall(b"ok\n")
                            self.handler(cmd)
                            continue
                    conn.sendall(b"no\n")
                except OSError:
                    pass

    def stop(self) -> None:
        with contextlib.suppress(OSError):
            self.sock.close()


# ===================================================================== global hotkey backends
class WinHotkey(threading.Thread):
    """RegisterHotKey + a message loop on its own thread; WM_HOTKEY calls `callback`."""

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    def __init__(self, hk: Hotkey, callback: Callable[[], None]) -> None:
        super().__init__(daemon=True, name="launcher-hotkey")
        self.hk = hk
        self.callback = callback
        self.tid = 0
        self.ready = threading.Event()
        self.error: str | None = None

    def run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self.tid = kernel32.GetCurrentThreadId()
        mods, vk = win_hotkey(self.hk)
        if not user32.RegisterHotKey(None, 1, mods, vk):
            self.error = f"{self.hk} is already taken by another app (set launcher_hotkey in deskdot.toml)"
            self.ready.set()
            return
        self.ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception:
                        log.exception("hotkey handler failed")
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self.tid:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self.tid, self.WM_QUIT, 0, 0)  # type: ignore[attr-defined]


class MacHotkey:
    """AppKit key monitors (global + local). The global one needs Accessibility / Input Monitoring permission."""

    def __init__(self, hk: Hotkey, callback: Callable[[], None]) -> None:
        self.hk = hk
        self.callback = callback
        self.monitors: list[Any] = []
        self.error: str | None = None

    def start(self) -> None:
        try:
            import AppKit  # type: ignore[import-not-found]
            from PyObjCTools import AppHelper  # type: ignore[import-not-found]
        except ImportError:
            self.error = "pyobjc isn't installed; use DeskDot Bar or Raycast for a global hotkey"
            return
        code = MAC_KEYCODES.get(self.hk.key)
        if code is None:
            self.error = f"{self.hk.key} can't be used as a macOS hotkey here"
            return
        flags = {
            "ctrl": AppKit.NSEventModifierFlagControl,
            "alt": AppKit.NSEventModifierFlagOption,
            "shift": AppKit.NSEventModifierFlagShift,
            "win": AppKit.NSEventModifierFlagCommand,
        }
        want = 0
        for m in self.hk.mods:
            want |= flags[m]
        mask = sum(flags.values())

        def matches(ev: Any) -> bool:
            return ev.keyCode() == code and (ev.modifierFlags() & mask) == want

        def on_global(ev: Any) -> None:
            if matches(ev):
                self.callback()

        def on_local(ev: Any) -> Any:
            if matches(ev):
                self.callback()
                return None
            return ev

        def install() -> None:
            self.monitors.append(
                AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    AppKit.NSEventMaskKeyDown, on_global
                )
            )
            self.monitors.append(
                AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                    AppKit.NSEventMaskKeyDown, on_local
                )
            )

        AppHelper.callAfter(install)

    def stop(self) -> None:
        with contextlib.suppress(Exception):
            import AppKit  # type: ignore[import-not-found]

            for m in self.monitors:
                AppKit.NSEvent.removeMonitor_(m)


# ===================================================================== the window
OFFLINE_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>DeskDot Launcher</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}
html,body{margin:0;height:100%;background:__BG__;font:15px "Segoe UI Variable Text","SF Pro Text",system-ui,sans-serif;color:#efece4}
.card{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:28px;
background:radial-gradient(120% 90% at 50% 0%,#2a1410 0%,#0f0f13 60%);border:1px solid #25252d;border-radius:__RADIUS__}
.dots{display:grid;grid-template-columns:repeat(4,10px);gap:5px}.dots i{width:10px;height:10px;border-radius:2px;background:#27272f}
.dots i.on{background:#ff4818;box-shadow:0 0 10px #ff481888}h1{margin:6px 0 0;font-size:20px;font-weight:650}
p{margin:0;color:#a9a7b0;text-align:center;max-width:440px;line-height:1.45}
button{font:inherit;border:0;border-radius:10px;padding:11px 20px;cursor:pointer;color:#120805;font-weight:650;
background:linear-gradient(90deg,#ff3f78,#ff7419 55%,#ffcc33)}button:disabled{opacity:.6;cursor:default}
.row{display:flex;gap:10px}.ghost{background:#1e1e25;color:#efece4;border:1px solid #33333d;font-weight:500}
kbd{font:11px "Cascadia Mono",ui-monospace,monospace;color:#6f6d78;border:1px solid #33333d;border-radius:5px;padding:1px 5px}
.hint{font-size:12px;color:#6f6d78}</style></head><body><div class="card">
<div class="dots"><i class="on"></i><i></i><i></i><i class="on"></i><i></i><i class="on"></i><i class="on"></i><i></i>
<i></i><i class="on"></i><i class="on"></i><i></i><i class="on"></i><i></i><i></i><i class="on"></i></div>
<h1>DeskDot isn't running</h1><p id="msg">The launcher talks to the DeskDot engine at <b>__URL__</b>.
Start it and your panel's apps, presets and controls show up here.</p>
<div class="row"><button id="go" autofocus>Start DeskDot</button><button class="ghost" id="quit">Quit launcher</button></div>
<div class="hint"><kbd>Enter</kbd> start &nbsp; <kbd>Esc</kbd> hide</div></div><script>
const api=()=>window.pywebview&&window.pywebview.api;const go=document.getElementById('go');
go.onclick=async()=>{go.disabled=true;go.textContent='Starting…';document.getElementById('msg').textContent=
'Starting the engine. The panel connects over Bluetooth in a few seconds.';try{await api().start_engine()}catch(e){}};
document.getElementById('quit').onclick=()=>api()&&api().quit();
addEventListener('keydown',e=>{if(e.key==='Escape')api()&&api().hide();if(e.key==='Enter'&&!go.disabled)go.click()});
addEventListener('blur',()=>setTimeout(()=>{if(!document.hasFocus())api()&&api().hide()},120));
</script></body></html>"""


class LauncherApi:
    """Exposed to the page as `window.pywebview.api` (all calls arrive on pywebview worker threads)."""

    def __init__(self, shell: LauncherShell) -> None:
        self._shell = shell

    def hide(self) -> bool:
        self._shell.hide()
        return True

    def open_url(self, url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            url = self._shell.cfg.url + "/" + url.lstrip("/")
        self._shell.hide()
        webbrowser.open(url)
        return True

    def start_engine(self) -> bool:
        return self._shell.start_engine()

    def quit(self) -> bool:
        threading.Thread(target=self._shell.quit, daemon=True).start()
        return True

    def info(self) -> dict[str, Any]:
        return {
            "hotkey": str(self._shell.cfg.hotkey),
            "url": self._shell.cfg.url,
            "autostart": autostart_enabled(),
            "platform": sys.platform,
        }

    def set_autostart(self, enabled: bool) -> bool:
        self._shell.set_autostart(bool(enabled))
        return autostart_enabled()


class LauncherShell:
    def __init__(self, cfg: LauncherConfig) -> None:
        self.cfg = cfg
        self.window: Any = None
        self.visible = False
        self.online: bool | None = None
        self.shown_at = 0.0
        self.hotkey: Any = None
        self.tray: Any = None
        self.control: ControlServer | None = None
        self._stop = threading.Event()
        self._engine_proc: subprocess.Popen[bytes] | None = None

    # ------------------------------------------------------------------ pages
    @property
    def shell_kind(self) -> str:
        return {"win32": "win", "darwin": "mac"}.get(sys.platform, "gtk")

    def page_url(self) -> str:
        return f"{self.cfg.url}/launcher?shell={self.shell_kind}"

    def offline_html(self) -> str:
        transparent = self.shell_kind != "win"
        return (
            OFFLINE_HTML.replace("__URL__", self.cfg.url)
            .replace("__BG__", "transparent" if transparent else "#0f0f13")
            .replace("__RADIUS__", "16px" if transparent else "0")
        )

    # ------------------------------------------------------------------ visibility
    def show(self) -> None:
        if not self.window:
            return
        self._center()
        self.window.show()
        self.visible = True
        self.shown_at = time.monotonic()
        if sys.platform == "win32":
            self._win_focus()
        self._emit("deskdot:show")

    def hide(self) -> None:
        if not self.window or not self.visible:
            return
        self.visible = False
        self._emit("deskdot:hide")
        self.window.hide()

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    def _emit(self, name: str) -> None:
        with contextlib.suppress(Exception):
            self.window.evaluate_js(f"window.dispatchEvent(new Event({name!r}))")

    def _center(self) -> None:
        with contextlib.suppress(Exception):
            import webview

            scr = webview.screens[0]
            self.window.move(max(0, (scr.width - WIDTH) // 2), max(0, int(scr.height * 0.2)))

    # ------------------------------------------------------------------ windows niceties
    def _hwnd(self) -> int:
        import ctypes

        return int(ctypes.windll.user32.FindWindowW(None, APP_NAME) or 0)  # type: ignore[attr-defined]

    def _win_style(self) -> None:
        """Rounded corners (Windows 11 DWM) and no taskbar button (a tool window), like Spotlight."""
        import ctypes

        hwnd = self._hwnd()
        if not hwnd:
            return
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        with contextlib.suppress(OSError, AttributeError):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)  # type: ignore[attr-defined]
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        gwl_exstyle, ws_ex_toolwindow, ws_ex_appwindow = -20, 0x80, 0x40000
        ex = user32.GetWindowLongW(hwnd, gwl_exstyle)
        user32.SetWindowLongW(hwnd, gwl_exstyle, (ex | ws_ex_toolwindow) & ~ws_ex_appwindow)

    def _win_focus(self) -> None:
        import ctypes

        hwnd = self._hwnd()
        if hwnd:
            ctypes.windll.user32.SetForegroundWindow(hwnd)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ engine
    def start_engine(self) -> bool:
        if engine_alive(self.cfg.url):
            self._set_online(True)
            return True
        if self._engine_proc is None or self._engine_proc.poll() is not None:
            log.info("starting the engine: %s", " ".join(engine_command(self.cfg)))
            self._engine_proc = start_engine(self.cfg)
        for _ in range(60):
            if engine_alive(self.cfg.url):
                self._set_online(True)
                return True
            if self._engine_proc.poll() is not None:
                break
            time.sleep(0.5)
        log.error("the engine didn't come up; see %s", self.cfg.data_dir / "engine-launcher.log")
        return False

    def _set_online(self, online: bool) -> None:
        if online == self.online or not self.window:
            return
        self.online = online
        if online:
            self.window.load_url(self.page_url())
        else:
            self.window.load_html(self.offline_html())

    def _watch(self) -> None:
        while not self._stop.is_set():
            self._set_online(engine_alive(self.cfg.url))
            self._stop.wait(2.0 if self.visible else 6.0)

    # ------------------------------------------------------------------ autostart
    def set_autostart(self, enabled: bool) -> None:
        where = set_autostart(enabled, autostart_command(self.cfg), workdir=self.cfg.project_dir)
        log.info("start with login %s (%s)", "on" if enabled else "off", where)

    # ------------------------------------------------------------------ tray
    def _start_tray(self) -> None:
        if sys.platform == "darwin":
            return  # pystray needs the main thread there (pywebview has it); DeskDot Bar is the Mac menu-bar app
        try:
            import pystray
        except ImportError:
            log.warning("pystray isn't installed: no tray icon (uv sync --extra launcher)")
            return

        def toggle_autostart(_icon: Any, _item: Any) -> None:
            self.set_autostart(not autostart_enabled())

        menu = pystray.Menu(
            pystray.MenuItem(f"Show  ({self.cfg.hotkey})", lambda: self.show(), default=True),
            pystray.MenuItem("Open studio", lambda: webbrowser.open(self.cfg.url + "/")),
            pystray.MenuItem(
                "Start DeskDot engine",
                lambda: threading.Thread(target=self.start_engine, daemon=True).start(),
                visible=lambda _i: not self.online,
            ),
            pystray.MenuItem("Start with login", toggle_autostart, checked=lambda _i: autostart_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit launcher", lambda: self.quit()),
        )
        self.tray = pystray.Icon("deskdot-launcher", tray_image(), APP_NAME, menu)
        self.tray.run_detached()

    # ------------------------------------------------------------------ lifecycle
    def _started(self, background: bool) -> None:
        """Runs on a pywebview worker thread once the GUI loop is up."""
        if sys.platform == "win32":
            self._win_style()
        self._start_tray()
        if sys.platform == "win32":
            self.hotkey = WinHotkey(self.cfg.hotkey, self.toggle)
            self.hotkey.start()
            self.hotkey.ready.wait(2)
        elif sys.platform == "darwin":
            self.hotkey = MacHotkey(self.cfg.hotkey, self.toggle)
            self.hotkey.start()
        if self.hotkey is not None and self.hotkey.error:
            log.warning("global hotkey: %s", self.hotkey.error)
        elif self.hotkey is not None:
            log.info("press %s to open the launcher", self.cfg.hotkey)
        else:
            log.info("no global hotkey on this OS: bind a desktop shortcut to `deskdot launcher --show`")
        threading.Thread(target=self._watch, daemon=True, name="launcher-health").start()
        if not background:
            self.show()

    def _control(self, cmd: str) -> None:
        {"show": self.show, "hide": self.hide, "toggle": self.toggle, "quit": self.quit}[cmd]()

    def quit(self) -> None:
        self._stop.set()
        if self.hotkey is not None:
            self.hotkey.stop()
        if self.control is not None:
            self.control.stop()
        if self.tray is not None:
            with contextlib.suppress(Exception):
                self.tray.stop()
        if self.window is not None:
            with contextlib.suppress(Exception):
                self.window.destroy()

    def run(self, background: bool = False) -> None:
        import webview

        try:
            self.control = ControlServer(self._control)
            self.control.start()
        except OSError:
            log.warning(
                "control port %d is busy; `deskdot launcher --show` won't reach this one", CONTROL_PORT
            )
        self.online = engine_alive(self.cfg.url)
        self.window = webview.create_window(
            APP_NAME,
            url=self.page_url() if self.online else None,
            html=None if self.online else self.offline_html(),
            js_api=LauncherApi(self),
            width=WIDTH,
            height=HEIGHT,
            resizable=False,
            frameless=True,
            easy_drag=False,
            on_top=True,
            hidden=True,
            background_color="#0f0f13",
            transparent=self.shell_kind != "win",
        )
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        webview.start(
            self._started,
            (background,),
            private_mode=False,  # keep localStorage (recent items) between runs
            storage_path=str(self.cfg.data_dir / "launcher-webview"),
        )
        self.quit()


def tray_image(size: int = 64) -> Any:
    """A 4×4 dot-matrix glyph in the brand gradient (rose → tangerine → gold)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=(15, 15, 19, 255))
    on = {0, 3, 5, 6, 9, 10, 12, 15}
    stops = [(255, 63, 120), (255, 116, 25), (255, 204, 51)]
    cell = size // 5
    pad = (size - 4 * cell) // 2
    for i in range(16):
        x, y = i % 4, i // 4
        t = (x + y) / 6
        a, b = (stops[0], stops[1]) if t < 0.5 else (stops[1], stops[2])
        u = t * 2 if t < 0.5 else t * 2 - 1
        col = tuple(round(a[k] + (b[k] - a[k]) * u) for k in range(3))
        x0, y0 = pad + x * cell + cell // 8, pad + y * cell + cell // 8
        box = (x0, y0, x0 + cell - cell // 4, y0 + cell - cell // 4)
        d.rounded_rectangle(box, radius=max(1, cell // 6), fill=(*col, 255) if i in on else (39, 39, 47, 255))
    return img


# ===================================================================== CLI entry
def main(
    config: str | None = None,
    *,
    show: bool = False,
    hide: bool = False,
    quit_: bool = False,
    background: bool = False,
    autostart: str | None = None,
) -> int:
    cfg = load_launcher_config(Path(config) if config else None)
    if autostart in ("on", "off"):
        where = set_autostart(autostart == "on", autostart_command(cfg), workdir=cfg.project_dir)
        print(f"start with login: {autostart} ({where})")
        return 0
    if cfg.autostart and not autostart_enabled():
        set_autostart(True, autostart_command(cfg), workdir=cfg.project_dir)  # launcher_autostart = true
    cmd = "quit" if quit_ else "hide" if hide else "show" if show else None
    if send_control(cmd or "show"):
        return 0  # an instance is already running; it handled the request
    if cmd in ("quit", "hide"):
        print("no launcher is running")
        return 1
    try:
        import webview  # noqa: F401
    except ImportError:
        print("The launcher needs the optional extra:  uv sync --extra launcher", file=sys.stderr)
        return 2
    print(f"DeskDot Launcher: {cfg.hotkey} opens it · engine {cfg.url}")
    LauncherShell(cfg).run(background=background)
    return 0
