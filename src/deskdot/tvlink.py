"""TV view: any screen on the network watches what DeskDot plays, full screen and read-only (docs/TV_VIEW.md).

The studio opens a TV link (`POST /api/tv`) and shows its QR code; a TV browser opens `/tv/<code>` (tv.html +
the scripts in `tv/`), whose socket `/ws/tv/<code>` receives

- `hello` when it connects and whenever the app on the panel changes,
- `state` — the app's public `status()` (exactly what phones in a lobby get, never `private_status()`), the
  lobby snapshot and `tv` (the app's `tv_extra()`: TV-only animation anchors, e.g. a casino round's outcome once
  bets are locked) — about 5 times a second when something changed, else a heartbeat every 2 s,
- binary frames: the panel, 32×32×3 RGB, at most 12 a second, newest wins (no backlog per TV).

Both text messages carry `display` — the studio's choice of panel look and quality for every TV of the link
(`POST /api/tv/settings`), `{"look", "quality", "rev"}`: a TV applies it whenever `rev` changes (until someone picks
on that TV again). One TV code at a time, never equal to the lobby code.

The socket is read-only but for one narrow message: while a casino table shows, a TV's options menu may set the
house's two *display* settings — the roulette dolly and the chip set — with `{"type": "house", "dolly": id}` /
`{"type": "house", "chip_set": id}`. Only those two keys, only known values, only from a socket opened with the valid
TV code, at most a few times a second; everything else (credits, limits, timers, rules, any other app) stays
studio-only. The reply is `house_ok` / `house_err`. Anything else a TV sends is ignored (pings get a pong).
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
STATIC_NAME = re.compile(r"^[a-z0-9-]{1,40}\.(?:js|woff2)$")  # the TV scripts and its font
MAX_FPS = 12.0
STATE_S = 0.2  # ~5 Hz
HEARTBEAT_S = 2.0
MAX_TVS = 8
LOOKS = ("pixel", "led", "glow")  # the studio's panel looks (web/src/lib/look.ts)
QUALITIES = ("auto", "hq", "lite")
# the only house settings a TV may change (display only: no credits, limits or rules)
HOUSE_KEYS = ("dolly", "chip_set")
HOUSE_MIN_S = 0.25  # one house change per TV per this many seconds


def house_patch(msg: dict[str, Any]) -> dict[str, str]:
    """The house display settings in a TV's `house` message, validated; raises ValueError for anything else."""
    from .casino.chips import CHIP_SETS
    from .casino.session import DOLLIES

    allowed = {"dolly": set(DOLLIES), "chip_set": {"auto", *CHIP_SETS}}
    extra = set(msg) - {"type", *HOUSE_KEYS}
    if extra:
        raise ValueError(f"a TV can't set {', '.join(sorted(extra))}")
    patch = {k: msg[k] for k in HOUSE_KEYS if k in msg}
    if len(patch) != 1:
        raise ValueError("one of dolly / chip_set")
    for k, v in patch.items():
        if not isinstance(v, str) or v not in allowed[k]:
            raise ValueError(f"unknown {k}")
    return patch


def tv_page() -> str:
    """Read per request (tiny) so edits go live without a restart."""
    return TV_PAGE.read_text(encoding="utf-8")


def tv_script(name: str) -> bytes | None:
    """A TV script (`tv.js`, `tv-games.js`, …) or its font (`tv-sans.woff2`) by file name, or None. Only plain
    names inside `tv/`."""
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
        # the studio's display choices for every TV of the link (None = each TV keeps its own); `rev` changes on
        # every change so a TV that picked something itself takes the studio's choice again
        self.display: dict[str, Any] = {"look": None, "quality": None, "rev": None}

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

    def set_display(self, **choices: str | None) -> dict[str, Any]:
        """Set the studio's look / quality (a value, or None to leave it to each TV); keys not given are kept."""
        for key, allowed in (("look", LOOKS), ("quality", QUALITIES)):
            if key not in choices:
                continue
            v = choices[key]
            if v is not None and v not in allowed:
                raise ValueError(f"{key} must be one of {', '.join(allowed)} (or null)")
        for key in ("look", "quality"):
            if key in choices:
                self.display[key] = choices[key]
        prev = self.display["rev"] or 0.0
        self.display["rev"] = round(
            max(time.time(), prev + 0.001), 6
        )  # always new, even within one clock tick
        return dict(self.display)


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
        self.last_house = 0.0

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
                "display": self.link.display,
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
            {
                "app": app_id,
                "status": status,
                "lobby": self.lobby.snapshot(),
                "tv": tv,
                "display": self.link.display,
            },
            default=str,
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

    async def _house(self, tv: _Tv, code: str, msg: dict[str, Any]) -> dict[str, Any]:
        """A TV's options menu sets the house's dolly or chip set (see the module docstring). Never raises."""

        def err(text: str) -> dict[str, Any]:
            return {"type": "house_err", "error": text}

        if not self.link.valid(code):
            return err("This TV link has closed")
        now = time.monotonic()
        if now - tv.last_house < HOUSE_MIN_S:
            return err("One moment")
        tv.last_house = now
        try:
            patch = house_patch(msg)
        except ValueError as e:
            return err(str(e))
        app_id, app = self._current()
        if app is None or getattr(type(app), "category", "") != "casino" or not hasattr(app, "casino"):
            return err("No casino table is showing")
        try:
            res = await self.engine.action(app_id, "casino", {"op": "settings", "player": "host", **patch})
        except (KeyError, ValueError, TypeError) as e:
            log.debug("TV house change refused: %s", e)
            return err("The table didn't take that")
        house = res.get("house", {}) if isinstance(res, dict) else {}
        self.tick(force=True)  # every screen gets the new look now
        return {"type": "house_ok", **{k: house.get(k) for k in patch}}

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
                if isinstance(msg, dict) and msg.get("type") == "house":
                    await sock.send_text(json.dumps(await self._house(tv, code, msg)))
                elif isinstance(msg, dict) and msg.get("type") == "ping":
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
