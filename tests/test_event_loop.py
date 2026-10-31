"""I-ENG-1 / I-ROOT-3 / CLAUDE.md rule 3: the event loop is never blocked.

1. Static: blocking calls (`time.sleep`, `requests.*`, `urllib.request.urlopen`, `subprocess.run/call/check_*`,
   `os.system`, `psutil.cpu_percent(interval>0)`) never appear in an `async def`, and anywhere else in
   `src/deskdot` only inside a function on the documented allowlist below (code that runs in a worker thread, through
   `asyncio.to_thread`, or in a process that has no event loop).
2. Runtime: the engine runs for a few seconds with the simulated panel under asyncio debug mode; no callback or task
   step from DeskDot may hold the loop longer than `SLOW` seconds.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import re
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "deskdot"

BLOCKING = {
    "time.sleep",
    "urllib.request.urlopen",
    "urlopen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "os.system",
}

#: (file relative to src/deskdot, enclosing function path) → why the blocking call there never runs on the loop
ALLOWED: dict[tuple[str, str], str] = {
    ("desktop.py", "run_app"): "the desktop shell's own process, before/without an event loop",
    ("launcher.py", "engine_alive"): "the launcher process (pywebview), which has no asyncio loop",
    ("launcher.py", "start_engine"): "the launcher process (pywebview), which has no asyncio loop",
    ("providers/camera.py", "_capture"): "runs on the camera's own threading.Thread",
    ("providers/idle.py", "mac_idle_seconds"): "called from IdleProvider._read via asyncio.to_thread",
    ("providers/window.py", "_linux_foreground/run"): "called via asyncio.to_thread(_linux_foreground)",
    ("updates.py", "_handoff_macos"): "the installer hand-off runs via asyncio.to_thread(self._handoff, …)",
    ("updates.py", "_exit_engine/hard"): "a daemon threading.Thread (hard exit if shutdown hangs)",
}

#: a slow-step report names the coroutine's file; ours live under src/deskdot (the test's own steps don't count)
OURS = re.compile(r"src[\\/]deskdot[\\/]")
SLOW = 0.1  # seconds: asyncio debug mode reports any step longer than this


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _blocking(call: ast.Call) -> str | None:
    name = _name(call.func)
    if name is None:
        return None
    if name in BLOCKING or name.startswith("requests."):
        return name
    if name.endswith("cpu_percent"):  # psutil.cpu_percent(interval>0) sleeps for `interval`
        interval = (
            call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "interval"), None)
        )
        if isinstance(interval, ast.Constant) and interval.value in (None, 0, 0.0):
            return None
        return f"{name}(interval={ast.unparse(interval) if interval else '…'})"
    return None


def _scan() -> tuple[list[str], set[tuple[str, str]]]:
    """(violations, allowlist entries that were used)."""
    bad: list[str] = []
    used: set[tuple[str, str]] = set()
    for f in sorted(SRC.rglob("*.py")):
        rel = f.relative_to(SRC).as_posix()
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))

        def visit(node: ast.AST, stack: list[str], in_async: bool, rel: str = rel) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit(child, [*stack, child.name], isinstance(child, ast.AsyncFunctionDef))
                    continue
                if isinstance(child, ast.Lambda):
                    visit(child, stack, False)
                    continue
                if isinstance(child, ast.Call) and (what := _blocking(child)):
                    where = f"{rel}:{child.lineno} {what} in {'/'.join(stack) or '<module>'}"
                    key = (rel, "/".join(stack))
                    if in_async:
                        bad.append(where + " (an async def: use asyncio.to_thread / asyncio.sleep / httpx)")
                    elif key in ALLOWED:
                        used.add(key)
                    else:
                        bad.append(where + " (not on the allowlist in tests/test_event_loop.py)")
                visit(child, stack, in_async)

        visit(tree, [], False)
    return bad, used


def test_no_blocking_calls_on_the_event_loop() -> None:
    bad, used = _scan()
    assert not bad, "blocking calls that could run on the event loop (CLAUDE.md rule 3):\n" + "\n".join(bad)
    stale = sorted(set(ALLOWED) - used)
    assert not stale, f"allowlist entries that no longer match a blocking call (remove them): {stale}"


def test_requests_library_is_never_imported() -> None:
    bad = []
    for f in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom) and not node.level
                else []
            )
            bad += [f"{f.relative_to(SRC)}:{node.lineno}" for m in mods if m.split(".")[0] == "requests"]
    assert not bad, f"sync HTTP (requests) imported; use the hub's httpx.AsyncClient: {bad}"


class _Slow(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "took" in msg and "seconds" in msg:
            self.messages.append(msg)


def test_engine_never_blocks_the_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the engine with the simulated panel through a few apps (stream, clip, a casino table, a game, a network
    provider) under asyncio debug mode: no step from DeskDot code may take longer than SLOW seconds."""
    import deskdot.apps  # noqa: F401 — registers built-in apps
    from deskdot.config import Config, Store
    from deskdot.device import SimDevice
    from deskdot.engine import Engine
    from deskdot.providers import build_hub

    monkeypatch.setenv("DESKDOT_UPDATE_CHECK", "0")
    handler = _Slow()
    log = logging.getLogger("asyncio")
    log.addHandler(handler)

    async def main() -> None:
        loop = asyncio.get_running_loop()
        loop.slow_callback_duration = SLOW
        store = Store(tmp_path / "state.json")
        hub = build_hub(store, lambda _n: None)
        # no network in tests (I-PROV-4): every provider fetch gets a fast 503
        await hub.http.aclose()
        hub.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(503)))
        cfg = Config(device="sim", data_dir=tmp_path)
        eng = Engine(cfg, store, SimDevice(bytes_per_second=1e7, min_frame_interval=0.0), hub)
        await eng.start()
        for app_id in ("clock", "agent", "casino_roulette", "tetris", "weather", "clock"):
            eng.activate(app_id)
            await asyncio.sleep(0.5)
        await eng.stop()

    try:
        asyncio.run(main(), debug=True)
    finally:
        log.removeHandler(handler)
    ours = [m for m in handler.messages if OURS.search(m)]
    assert not ours, "the event loop was blocked by DeskDot code:\n" + "\n".join(ours)
