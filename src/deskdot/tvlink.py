"""TV view: any screen on the network watches what DeskDot plays, full screen and read-only (docs/TV_VIEW.md).

The studio opens a TV link (`POST /api/tv`) and shows its QR code; a TV browser opens `/tv/<code>` (tv.html +
the scripts in `tv/`), whose socket `/ws/tv/<code>` receives

- `hello` when it connects and whenever the app on the panel changes,
- `state` — the app's public `status()` (exactly what phones in a lobby get, never `private_status()`), the
  lobby snapshot and `tv` (the app's `tv_extra()`: TV-only animation anchors, e.g. a casino round's outcome once
  bets are locked) — about 5 times a second when something changed, else a heartbeat every 2 s,
- binary frames: the panel, 32×32×3 RGB, at most 12 a second, newest wins (no backlog per TV).

One TV code at a time, never equal to the lobby code. The socket is read-only: a TV can only ping.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect

from .gfx.avatars import AVATARS
from .multiplayer import CODE_ALPHABET, is_local, lan_ip

if TYPE_CHECKING:
    from .engine import Engine
    from .gfx import Frame
    from .multiplayer import Lobby

log = logging.getLogger("deskdot.tv")

TV_DIR = Path(__file__).with_name("tv")
TV_PAGE = Path(__file__).with_name("tv.html")
STATIC_NAME = re.compile(r"^[a-z0-9-]{1,40}\.js$")
MAX_FPS = 12.0
STATE_S = 0.2  # ~5 Hz
HEARTBEAT_S = 2.0
MAX_TVS = 8


def tv_page() -> str:
    """Read per request (tiny) so edits go live without a restart."""
    return TV_PAGE.read_text(encoding="utf-8")


def tv_script(name: str) -> bytes | None:
    """A TV script by file name (`tv.js`, `tv-games.js`, …), or None. Only plain names inside `tv/`."""
    if not STATIC_NAME.match(name):
        return None
    p = TV_DIR / name
    return p.read_bytes() if p.is_file() else None


class TvLink:
    """The one open TV code (or none)."""

    def __init__(self, host: str, port: int, public_url: str | None = None) -> None:
        self.bind_host = host
        self.port = port
        self.public_url = public_url.rstrip("/") if public_url else None
        self.code: str | None = None

    @property
    def lan_ready(self) -> bool:
        return self.public_url is not None or not is_local(self.bind_host)

    def open(self, avoid: str | None = None) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if code != (avoid or "").upper() and code != self.code:
                break
        self.code = code
        return code

    def close(self) -> None:
        self.code = None

    def url(self) -> str | None:
        if self.code is None:
            return None
        if self.public_url:
            return f"{self.public_url}/tv/{self.code}"
        return f"http://{lan_ip()}:{self.port}/tv/{self.code}"

    def valid(self, code: str) -> bool:
        return self.code is not None and secrets.compare_digest(code.upper()[:8], self.code)


class _Tv:
    """One connected TV: holds only the newest hello / state / frame (latest wins, no backlog)."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.hello: str | None = None
        self.state: str | None = None
        self.frame: bytes | None = None
        self.closed = False
        self.wake = asyncio.Event()
        self.last_frame = 0.0

    async def pump(self) -> None:
        while not self.closed:
            await self.wake.wait()
            self.wake.clear()
            if self.hello is not None:
                msg, self.hello = self.hello, None
                await self.ws.send_text(msg)
            if self.state is not None:
                msg, self.state = self.state, None
                await self.ws.send_text(msg)
            if self.frame is not None:
                wait = self.last_frame + 1.0 / MAX_FPS - time.monotonic()
                if wait > 0:  # pace to MAX_FPS; a newer frame replaces this one meanwhile
                    await asyncio.sleep(wait)
                fr, self.frame = self.frame, None
                if fr is not None:
                    self.last_frame = time.monotonic()
                    await self.ws.send_bytes(fr)
                if self.hello is not None or self.state is not None:
                    self.wake.set()


class TvHub:
    """Fans the panel out to every connected TV. Status is built once per tick for all of them."""

    def __init__(self, engine: Engine, link: TvLink, lobby: Lobby) -> None:
        self.engine = engine
        self.link = link
        self.lobby = lobby
        self.tvs: set[_Tv] = set()
        self._poke = asyncio.Event()
        self._ticker: asyncio.Task[None] | None = None
        self._app: object = object()  # the app the last hello was about
        self._last_state = ""
        self._sent_at = 0.0
        self._avatars = {k: {"name": v[0], "px": list(v[1])} for k, v in AVATARS.items()}

    @property
    def viewers(self) -> int:
        return len(self.tvs)

    # ------------------------------------------------------------------ messages
    def _current(self) -> tuple[str | None, Any]:
        cur = self.engine.current
        return (cur.app.id, cur.app) if cur is not None else (None, None)

    def hello_msg(self) -> str:
        app_id, app = self._current()
        meta = None
        if app is not None:
            cls = type(app)
            meta = {
                "id": app_id,
                "name": cls.name,
                "category": cls.category,
                "icon": cls.icon,
                "max_players": int(getattr(cls, "max_players", 1)),
            }
        return json.dumps(
            {
                "type": "hello",
                "app": app_id,
                "meta": meta,
                "avatars": self._avatars,
                "server_time": time.time(),
            }
        )

    def _state_body(self) -> str:
        """The state without its timestamp (compared to decide whether anything changed)."""
        app_id, app = self._current()
        status: dict[str, Any] = {}
        tv: dict[str, Any] | None = None
        if app is not None:
            try:
                status = app.status() or {}  # the public status only — never private_status()
                extra = getattr(app, "tv_extra", None)  # TV-only animation anchors (casino: the locked round)
                tv = extra() if callable(extra) else None
            except Exception:
                log.exception("%s.status() failed", app_id)
        return json.dumps(
            {"app": app_id, "status": status, "lobby": self.lobby.snapshot(), "tv": tv}, default=str
        )

    @staticmethod
    def _stamp(body: str) -> str:
        return '{"type":"state",' + body[1:-1] + f',"server_time":{time.time():.3f}}}'

    # ------------------------------------------------------------------ fan-out
    def _on_frame(self, frame: Frame) -> None:
        data = frame.to_bytes()
        for tv in self.tvs:
            tv.frame = data
            tv.wake.set()

    def _on_change(self) -> None:
        self._poke.set()

    def tick(self, force: bool = False) -> None:
        """Send hello when the app changed and the state when it changed (or the heartbeat is due)."""
        if not self.tvs:
            return
        app_id, _ = self._current()
        hello = None
        if app_id != self._app:
            self._app = app_id
            hello = self.hello_msg()
        body = self._state_body()
        now = time.monotonic()
        if hello is None and not force and body == self._last_state and now - self._sent_at < HEARTBEAT_S:
            return
        self._last_state, self._sent_at = body, now
        state = self._stamp(body)
        for tv in self.tvs:
            if hello is not None:
                tv.hello = hello
            tv.state = state
            tv.wake.set()

    async def _tick_loop(self) -> None:
        while self.tvs:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._poke.wait(), STATE_S)
            self._poke.clear()
            self.tick()
            await asyncio.sleep(0.05)  # coalesce bursts of engine changes

    # ------------------------------------------------------------------ sockets
    async def close_all(self) -> None:
        """The TV link closed (or its code was replaced): tell every TV and hang up."""
        msg = json.dumps({"type": "closed"})
        for tv in list(self.tvs):
            tv.closed = True
            with contextlib.suppress(Exception):
                await tv.ws.send_text(msg)
                await tv.ws.close()
            self._remove(tv)

    def _add(self, tv: _Tv) -> None:
        self.tvs.add(tv)
        if len(self.tvs) == 1:
            self.engine.frame_listeners.add(self._on_frame)
            self.engine.state_listeners.add(self._on_change)
        if self._ticker is None or self._ticker.done():
            self._ticker = asyncio.get_running_loop().create_task(self._tick_loop())

    def _remove(self, tv: _Tv) -> None:
        self.tvs.discard(tv)
        if not self.tvs:
            self.engine.frame_listeners.discard(self._on_frame)
            self.engine.state_listeners.discard(self._on_change)

    async def serve(self, sock: WebSocket, code: str) -> None:
        await sock.accept()
        if not self.link.valid(code) or len(self.tvs) >= MAX_TVS:
            await sock.send_text(json.dumps({"type": "closed" if not self.link.valid(code) else "full"}))
            await sock.close()
            return
        tv = _Tv(sock)
        # a new TV starts with everything: hello, the current state and the current frame
        tv.hello = self.hello_msg()
        tv.state = self._stamp(self._state_body())
        tv.frame = self.engine.frame.to_bytes()
        tv.wake.set()
        self._add(tv)
        self._app = self._current()[0] if len(self.tvs) == 1 else self._app
        pump = asyncio.create_task(tv.pump())
        try:
            while True:
                raw = await sock.receive_text()
                if len(raw) > 512:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    t = msg.get("t")
                    await sock.send_text(
                        json.dumps(
                            {
                                "type": "pong",
                                "t": t if isinstance(t, (int, float)) else None,
                                "server_time": time.time(),
                            }
                        )
                    )
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            tv.closed = True
            pump.cancel()
            self._remove(tv)
