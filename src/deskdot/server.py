"""HTTP + WebSocket API and static studio hosting.

REST is for commands; one WebSocket (/ws) streams state JSON and raw frames
(3072-byte RGB binary messages) to the studio. See docs/API.md.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import random
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import (
    Body,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi import Path as FPath
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .apps import load_plugins
from .apps.canvas import frame_from_rows
from .apps.games_core import KEYS
from .config import Config, Store
from .device import Device, SimDevice
from .engine import REGISTRY, Engine, Notice, Playlist, presets
from .engine.integrations import SECTIONS
from .engine.overlay import ICONS
from .engine.persistent import Indicator
from .engine.runtime import PlaylistItem
from .gfx import PALETTE, Frame, to_hex
from .gfx.calib import PanelCalibration
from .gfx.font import FONTS
from .gfx.image import encode_gif_budget, import_media
from .media import MediaLibrary
from .multiplayer import (
    CONTROLLER_HTML,
    PLAYER_COLORS,
    LanGate,
    Lobby,
    Room,
    avatar_table,
    clean_cid,
    game_profile,
)
from .power import start_power_watch
from .previews import Previews
from .providers import build_hub
from .providers.custom import NAME as CUSTOM_NAME
from .providers.custom import CustomApp
from .providers.sports import LEAGUES

log = logging.getLogger("deskdot.server")
# the built studio; the Android app ships it elsewhere and points DESKDOT_WEB_DIST at it
WEB_DIST = Path(os.environ.get("DESKDOT_WEB_DIST") or os.environ.get("DOTDECK_WEB_DIST") or Path(__file__).resolve().parents[2] / "web" / "dist")


# ============================================================ websocket hub
class Client:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.frame: bytes | None = None
        self.state: str | None = None
        self.wake = asyncio.Event()

    async def pump(self) -> None:
        while True:
            await self.wake.wait()
            self.wake.clear()
            if self.state is not None:
                msg, self.state = self.state, None
                await self.ws.send_text(msg)
            if self.frame is not None:
                fr, self.frame = self.frame, None
                await self.ws.send_bytes(fr)


class Hub:
    """Fan-out to studio clients. Each client holds only the newest frame and state (no backlog)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.clients: set[Client] = set()
        self._state_task: asyncio.Task[None] | None = None
        engine.state_listeners.add(self.state_changed)
        engine.device._on_change = self.state_changed

    def on_frame(self, frame: Frame) -> None:
        data = frame.to_bytes()
        for c in self.clients:
            c.frame = data
            c.wake.set()

    def state_changed(self) -> None:
        if self._state_task and not self._state_task.done():
            return
        with contextlib.suppress(RuntimeError):
            self._state_task = asyncio.get_running_loop().create_task(self._send_state())

    async def _send_state(self) -> None:
        await asyncio.sleep(0.05)  # coalesce bursts
        msg = json.dumps({"type": "state", "state": self.engine.snapshot()}, default=str)
        for c in self.clients:
            c.state = msg
            c.wake.set()

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(2.0)
            if self.clients:
                self.state_changed()

    def add(self, c: Client) -> None:
        self.clients.add(c)
        if len(self.clients) == 1:
            self.engine.frame_listeners.add(self.on_frame)
        c.frame = self.engine.frame.to_bytes()
        self.state_changed()

    def remove(self, c: Client) -> None:
        self.clients.discard(c)
        if not self.clients:
            self.engine.frame_listeners.discard(self.on_frame)


# ================================================================ request models
class ActivateBody(BaseModel):
    settings: dict[str, Any] | None = None
    revert_after: float | None = Field(default=None, ge=1, le=3600)


class DisplayPatch(BaseModel):
    max_fps: float | None = Field(default=None, ge=0.5, le=30)
    packet_gap_ms: float | None = Field(default=None, ge=0, le=200)
    idle_dim: int | None = Field(default=None, ge=0, le=240)
    night: dict[str, Any] | None = None


class SettingsPatch(BaseModel):
    brightness: int | None = Field(default=None, ge=5, le=100)
    power: bool | None = None
    flip: bool | None = None
    transition: Literal["cut", "push", "fade", "wipe"] | None = None
    units: Literal["metric", "imperial"] | None = None
    location: dict[str, Any] | None = None
    audio_source: Literal["system", "mic"] | None = None
    os_notifications: dict[str, Any] | None = None


class HandoffPatch(BaseModel):
    on_exit: bool | None = None
    on_sleep: bool | None = None
    mode: Literal["clock", "app", "last"] | None = None
    app: str | None = None
    seconds: float | None = Field(default=None, ge=2, le=30)
    clock_style: int | None = Field(default=None, ge=0, le=7)
    hour24: bool | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class AutopilotRule(BaseModel):
    match: str = Field(
        min_length=1, max_length=80, description="process name part, or 'title:' + window title part"
    )
    app: str
    settings: dict[str, Any] = Field(default_factory=dict)


class AutopilotBody(BaseModel):
    enabled: bool
    rules: list[AutopilotRule] = Field(default_factory=list, max_length=40)


class TextBody(BaseModel):
    text: str = Field(max_length=500)
    color: str | None = None
    effect: str | None = None
    revert_after: float | None = Field(default=None, ge=1, le=3600)


class SimulateBody(BaseModel):
    seconds: float = Field(default=10, ge=0, le=600)


class PixelsBody(BaseModel):
    rows: list[str] | None = None
    palette: dict[str, str] | None = None
    rgb: str | None = None  # base64, 3072 bytes
    pixels: list[tuple[int, int, str]] | None = None
    clear: bool = False
    revert_after: float | None = Field(default=None, ge=1, le=3600)


class AiCreateBody(BaseModel):
    prompt: str = Field(..., max_length=1500)
    api_key: str | None = None
    model: str = "gemini-2.5-flash"
    fps: int = Field(default=8, ge=1, le=20)
    num_frames: int = Field(default=8, ge=1, le=16)
    action: Literal["preview", "canvas", "clip", "stream"] = "preview"
    revert_after: float | None = Field(default=None, ge=1, le=3600)


class AiConfigPatch(BaseModel):
    api_key: str | None = None
    model: str | None = None


class TransferCalibBody(BaseModel):
    max_fps: float = Field(default=12.0, ge=1.0, le=20.0)
    packet_gap_ms: float = Field(default=18.0, ge=5.0, le=80.0)
    transition: Literal["cut", "push", "fade", "wipe"] = "cut"


# ======================================================================= app
def build_device(cfg: Config) -> Device:
    interval = 1.0 / cfg.max_fps
    if cfg.device == "sim":
        return SimDevice(min_frame_interval=interval)
    if cfg.device == "android":
        from .device.android import AndroidBleDevice

        return AndroidBleDevice(cfg.address, min_frame_interval=interval, packet_gap=cfg.packet_gap_ms / 1000)
    from .device.ble import BleDevice

    return BleDevice(cfg.address, min_frame_interval=interval, packet_gap=cfg.packet_gap_ms / 1000)


def create_app(cfg: Config) -> FastAPI:
    store = Store(cfg.data_dir / "state.json")
    plugins = load_plugins(cfg.plugins_dir)
    library = MediaLibrary(cfg.media_dir)
    holder: dict[str, Any] = {}

    def provider_changed(_name: str) -> None:
        if "hub" in holder:
            holder["hub"].state_changed()

    phub = build_hub(store, provider_changed)
    device = build_device(cfg)
    engine = Engine(cfg, store, device, phub)
    engine.library = library
    ws_hub = Hub(engine)
    holder["hub"] = ws_hub
    previews = Previews(engine)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await engine.start()
        if cfg.device != "sim":
            start_power_watch(engine, asyncio.get_running_loop())  # sleep -> hand the panel its clock
        beat = asyncio.create_task(ws_hub.heartbeat())
        log.info(
            "DeskDot %s on http://%s:%d (device=%s, plugins=%s)",
            __version__,
            cfg.host,
            cfg.port,
            cfg.device,
            plugins,
        )
        try:
            yield
        finally:
            beat.cancel()
            await engine.stop()

    app = FastAPI(title="DeskDot", version=__version__, lifespan=lifespan)
    app.add_middleware(LanGate, allow_all=cfg.lan_studio)
    app.state.engine = engine
    app.state.library = library
    lobby = Lobby(cfg.host, cfg.port)
    app.state.lobby = lobby
    phones: dict[int, WebSocket] = {}  # seat -> socket (one phone per seat)

    def game_class(app_id: str) -> Any:
        cls = REGISTRY.get(app_id)
        if cls is None or getattr(cls, "max_players", 1) < 2:
            raise HTTPException(422, f"{app_id!r} isn't a multiplayer game")
        return cls

    # ------------------------------------------------------------ multiplayer
    @app.get("/api/play/lobby")
    async def lobby_get() -> dict[str, Any]:
        return {
            "lobby": lobby.snapshot(),
            "lan_ready": lobby.lan_ready,
            "games": [
                {"id": aid, "name": c.name, "max_players": c.max_players, "controls": list(c.controls)}
                for aid, c in REGISTRY.items()
                if getattr(c, "max_players", 1) > 1
            ],
        }

    @app.post("/api/play/lobby")
    async def lobby_open(app_id: str = Body(..., embed=True, alias="app")) -> dict[str, Any]:
        """Open a lobby: the panel shows the game with a join QR code friends scan with their phones."""
        cls = game_class(app_id)
        await lobby_close()
        room = lobby.open(app_id, int(cls.max_players))
        engine.activate(app_id)
        await engine.action(app_id, "lobby", {"url": lobby.url()})
        snap = lobby.snapshot() or {}
        if not lobby.lan_ready:
            snap["warning"] = (
                'Phones can\'t reach this computer: set host = "0.0.0.0" in deskdot.toml and restart.'
            )
        return {"ok": True, "code": room.code, **snap}

    @app.delete("/api/play/lobby")
    async def lobby_close() -> dict[str, Any]:
        room = lobby.room
        if room is None:
            return {"ok": True}
        for seat, sock in list(phones.items()):
            with contextlib.suppress(Exception):
                await sock.send_text(json.dumps({"type": "closed"}))
                await sock.close()
            phones.pop(seat, None)
        with contextlib.suppress(Exception):
            await engine.action(room.app, "lobby", {"url": None})
        lobby.close()
        return {"ok": True}

    @app.post("/api/play/lobby/start")
    async def lobby_start() -> dict[str, Any]:
        """Hide the QR code and play with whoever has joined (seats left empty are played by the AI)."""
        room = lobby.room
        if room is None:
            raise HTTPException(404, "no lobby")
        await engine.action(room.app, "lobby", {"url": None, "keep_seats": True})
        return {"ok": True}

    @app.get("/p/{code}")
    async def controller_page(code: str) -> HTMLResponse:
        if not lobby.valid(code):
            return HTMLResponse(
                "<h2 style='font-family:sans-serif'>This game link has expired.</h2>", status_code=404
            )
        return HTMLResponse(CONTROLLER_HTML, headers={"Cache-Control": "no-store"})

    async def broadcast_roster(room: Room) -> None:
        """Tell every phone in the room who is in the lobby (after a join, leave or profile change)."""
        msg = json.dumps({"type": "roster", "players": room.roster()})
        for sock in list(phones.values()):
            with contextlib.suppress(Exception):
                await sock.send_text(msg)

    @app.websocket("/ws/p/{code}")
    async def controller_ws(sock: WebSocket, code: str) -> None:
        """A phone controller. Messages in: {"k": key} (a press), {"type": "ping", "t"},
        {"type": "profile", name?, color?, avatar?, team?, ready?}. Out: hello, state, pong, roster,
        full, closed, replaced. Connect with ?cid=<client id> to get the same seat back after a reconnect."""
        await sock.accept()
        room = lobby.room
        if room is None or not lobby.valid(code):
            await sock.send_text(json.dumps({"type": "closed"}))
            await sock.close()
            return
        cid = clean_cid(sock.query_params.get("cid"))
        got = room.join(cid)
        if got is None:
            await sock.send_text(json.dumps({"type": "full"}))
            await sock.close()
            return
        seat, prof, resumed = got
        old = phones.get(seat)
        phones[seat] = sock
        if old is not None and old is not sock:  # the same phone reconnected before its old socket closed
            with contextlib.suppress(Exception):
                await old.send_text(json.dumps({"type": "replaced"}))
                await old.close()
        app_id = room.app
        await engine.action(app_id, "seat", {"player": seat, "joined": True, **game_profile(prof)})
        cls = REGISTRY[app_id]
        await sock.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "seat": seat,
                    "color": prof["color"],
                    "game": cls.name,
                    "controls": list(getattr(cls, "controls", ("dpad",))),
                    "cid": prof.get("cid"),
                    "resumed": resumed,
                    "profile": game_profile(prof),
                    "max_players": room.max_players,
                    "palette": [{"color": c, "name": n} for c, n in PLAYER_COLORS.items()],
                    "avatars": avatar_table(),
                    "modes": [
                        {"id": m.id, "name": m.name, "teams": m.teams} for m in getattr(cls, "modes", ())
                    ],
                }
            )
        )
        await broadcast_roster(room)
        engine.changed()

        async def push_state() -> None:
            # poll fast, send only on change (plus a heartbeat) so turn / flow changes reach the phone quickly
            last, sent_at = "", 0.0
            while True:
                await asyncio.sleep(0.12)
                cur = engine.current
                st = cur.app.status() if cur and cur.app.id == app_id else {}
                txt = json.dumps({"type": "state", "status": st}, default=str)
                t = time.monotonic()
                if txt != last or t - sent_at > 2.0:
                    await sock.send_text(txt)
                    last, sent_at = txt, t

        pusher = asyncio.create_task(push_state())
        try:
            while True:
                raw = await sock.receive_text()
                if len(raw) > 2048:  # nothing legitimate is this big
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict) or phones.get(seat) is not sock:
                    continue
                kind = msg.get("type")
                if kind == "ping":
                    t = msg.get("t")
                    await sock.send_text(
                        json.dumps({"type": "pong", "t": t if isinstance(t, (int, float)) else None})
                    )
                elif kind == "profile" and lobby.room is room:
                    if room.apply_profile(seat, msg):
                        await engine.action(
                            app_id, "seat", {"player": seat, "joined": True, **game_profile(room.seats[seat])}
                        )
                        engine.changed()
                    await broadcast_roster(room)  # also corrects a phone whose pick was refused
                elif "k" in msg and lobby.room is room:
                    k = str(msg["k"]).lower()[:8]
                    if k in KEYS:  # the press goes straight to the game, no queue
                        await engine.action(app_id, "input", {"key": k, "player": seat})
        except (WebSocketDisconnect, RuntimeError, KeyError):
            pass
        finally:
            pusher.cancel()
            if phones.get(seat) is sock:
                phones.pop(seat, None)
                if lobby.room is room:
                    room.leave(seat)
                    with contextlib.suppress(Exception):
                        await engine.action(app_id, "seat", {"player": seat, "joined": False})
                    await broadcast_roster(room)
            engine.changed()

    @app.exception_handler(ValidationError)
    async def _validation(_r: Request, e: ValidationError) -> JSONResponse:
        return JSONResponse({"detail": e.errors(include_url=False, include_context=False)}, status_code=422)

    @app.exception_handler(KeyError)
    async def _missing(_r: Request, e: KeyError) -> JSONResponse:
        return JSONResponse({"detail": f"not found: {e.args[0] if e.args else ''}"}, status_code=404)

    def need_app(app_id: str) -> None:
        if app_id not in REGISTRY:
            raise HTTPException(404, f"unknown app {app_id!r}; see GET /api/meta")

    # ------------------------------------------------------------------ read
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "device": device.info.status}

    @app.get("/api/meta")
    async def meta() -> dict[str, Any]:
        apps = []
        for cls in REGISTRY.values():
            if cls.hidden:
                continue
            m = cls.meta()
            apps.append(
                {
                    "id": m.id,
                    "name": m.name,
                    "description": m.description,
                    "icon": m.icon,
                    "category": m.category,
                    "schema": m.settings_schema,
                    "actions": [{"id": a.id, "label": a.label, "icon": a.icon} for a in m.actions],
                    # games: how many can play and which controllers suit them (best first)
                    "max_players": int(getattr(cls, "max_players", 1)),
                    "controls": list(getattr(cls, "controls", ())),
                    # games: ways to play with their player ranges (the schema only has the overall max)
                    "modes": [
                        {
                            "id": md.id,
                            "name": md.name,
                            "min_players": md.min_players,
                            "max_players": md.max_players,
                            "teams": md.teams,
                        }
                        for md in getattr(cls, "modes", ())
                    ],
                }
            )
        return {
            "version": __version__,
            "apps": apps,
            "palette": {k: to_hex(v) for k, v in PALETTE.items()},
            "fonts": {k: f.height for k, f in FONTS.items()},
            "icons": sorted(ICONS),
            "leagues": {k: v[1] for k, v in LEAGUES.items()},
            "plugins": plugins,
            "size": [32, 32],
        }

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return engine.snapshot()

    @app.get("/api/fly")
    async def fly() -> dict[str, Any]:
        """The fruit-fly brain's live activity (eye, layers, neurons, keys) when a fly is playing. Studio only."""
        return engine.fly_telemetry()

    @app.get("/api/frame.png")
    async def frame_png(scale: int = Query(1, ge=1, le=32)) -> Response:
        return Response(
            engine.frame.to_png(scale), media_type="image/png", headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/frame")
    async def frame_raw() -> dict[str, Any]:
        return {"width": 32, "height": 32, "rgb": base64.b64encode(engine.frame.to_bytes()).decode()}

    # ------------------------------------------------------------------ apps
    @app.post("/api/apps/{app_id}/activate")
    async def activate(
        app_id: str, body: ActivateBody = Body(default_factory=ActivateBody)
    ) -> dict[str, Any]:
        need_app(app_id)
        engine.activate(app_id, body.settings, body.revert_after)
        return {"ok": True, "active": app_id}

    @app.get("/api/apps/{app_id}/preview.gif")
    async def app_preview(app_id: str) -> Response:
        need_app(app_id)
        gif = await previews.get(app_id)
        return Response(gif, media_type="image/gif", headers={"Cache-Control": "max-age=15"})

    @app.patch("/api/apps/{app_id}/settings")
    async def patch_settings(app_id: str, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
        need_app(app_id)
        return engine.update_settings(app_id, patch)

    @app.post("/api/apps/{app_id}/actions/{action}")
    async def app_action(
        app_id: str, action: str, payload: dict[str, Any] = Body(default_factory=dict)
    ) -> Any:
        need_app(app_id)
        try:
            return {"ok": True, "result": await engine.action(app_id, action, payload)}
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e)) from e

    # -------------------------------------------------------------- playlist
    @app.get("/api/playlist")
    async def get_playlist() -> dict[str, Any]:
        return engine.playlist.model_dump(mode="json")

    @app.put("/api/playlist")
    async def put_playlist(pl: Playlist) -> dict[str, Any]:
        unknown = [i.app for i in pl.items if i.app not in REGISTRY]
        if unknown:
            raise HTTPException(422, f"unknown apps: {unknown}")
        for it in pl.items:  # validate overrides against each app's schema
            if it.settings:
                REGISTRY[it.app].Settings.model_validate({**engine.base_settings(it.app), **it.settings})
        engine.set_playlist(pl)
        return pl.model_dump(mode="json")

    # ------------------------------------------------------------------ presets
    @app.get("/api/presets")
    async def presets_list() -> list[dict[str, Any]]:
        return presets.all_presets(store)

    @app.post("/api/presets/{preset_id}/play")
    async def presets_play(preset_id: str, shuffle: bool = Body(False, embed=True)) -> dict[str, Any]:
        """Replace the playlist with a preset and start playing it (e.g. every game in sequence)."""
        p = presets.find(store, preset_id)
        if p is None:
            raise HTTPException(404, f"no preset {preset_id!r}")
        items = [PlaylistItem(app=it["app"], duration=float(it.get("duration", 20))) for it in p["items"]]
        if shuffle:
            random.shuffle(items)
        engine.set_playlist(Playlist(enabled=True, items=items))
        engine.playlist_control("play")
        store.set("active_preset", preset_id)
        store.set("active_preset_shuffle", bool(shuffle))
        return {"ok": True, "preset": preset_id, "items": len(items)}

    @app.post("/api/presets")
    async def presets_save(name: str = Body(..., embed=True, min_length=1, max_length=40)) -> dict[str, Any]:
        """Save the current playlist as your own preset."""
        items = [{"app": i.app, "duration": i.duration} for i in engine.playlist.items if i.enabled]
        if not items:
            raise HTTPException(422, "the playlist is empty")
        return presets.save(store, name, items)

    @app.delete("/api/presets/{preset_id}")
    async def presets_delete(preset_id: str) -> dict[str, Any]:
        if not presets.delete(store, preset_id):
            raise HTTPException(404, "only your own presets can be deleted")
        return {"ok": True}

    @app.post("/api/playlist/{op}")
    async def playlist_op(op: Literal["play", "stop", "next", "prev"]) -> dict[str, Any]:
        engine.playlist_control(op)
        return {"ok": True, "mode": engine.mode}

    # -------------------------------------------------------------- autopilot
    @app.get("/api/autopilot")
    async def get_autopilot() -> dict[str, Any]:
        return {**engine.autopilot(), "active": engine.auto_rule}

    @app.put("/api/autopilot")
    async def put_autopilot(body: AutopilotBody) -> dict[str, Any]:
        try:
            engine.set_autopilot(body.enabled, [r.model_dump() for r in body.rules])
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return engine.autopilot()

    # ---------------------------------------------------------- notifications
    @app.post("/api/notify")
    async def notify(n: Notice) -> dict[str, Any]:
        engine.notify(n)
        return {"ok": True, "queued": len(engine.notices)}

    @app.delete("/api/notify")
    async def dismiss() -> dict[str, Any]:
        engine.dismiss()
        return {"ok": True}

    # ------------------------------------------------------------- shortcuts
    @app.post("/api/text")
    async def show_text(body: TextBody) -> dict[str, Any]:
        patch: dict[str, Any] = {"text": body.text}
        if body.color:
            patch["color"] = body.color
        if body.effect:
            patch["effect"] = body.effect
        engine.activate("text", patch, body.revert_after)
        return {"ok": True}

    @app.post("/api/agent/{state}")
    async def agent_state(state: str, hold: float | None = Query(None, ge=1, le=3600)) -> dict[str, Any]:
        from .apps.agent import STATES

        if state not in STATES:
            raise HTTPException(400, f"state must be one of {list(STATES)}")
        engine.activate("agent", {"state": state}, hold)
        return {"ok": True, "state": state}

    @app.post("/api/pixels")
    async def pixels(body: PixelsBody) -> dict[str, Any]:
        if body.clear:
            await engine.action("canvas", "clear", {})
        if body.rows is not None:
            await engine.action("canvas", "load", {"rows": body.rows, "palette": body.palette or {}})
        elif body.rgb is not None:
            await engine.action("canvas", "load", {"rgb": body.rgb})
        if body.pixels:
            await engine.action("canvas", "paint", {"pixels": body.pixels})
        engine.activate("canvas", None, body.revert_after)
        return {"ok": True}

    # ------------------------------------------------------------ Gemini AI Studio
    SYSTEM_GEMINI_PIXEL_PROMPT = """You are an expert retro pixel artist and animation director specializing exclusively in 32x32 RGB LED matrix displays (specifically the iDotMatrix 32x32 physical LED panel).
Your task is to generate visually stunning, high-contrast, perfectly glanceable pixel art and pixel animations.

CRITICAL PHYSICAL CONSTRAINTS & DESIGN RULES FOR 32x32 LED PANELS:
1. RESOLUTION: Strictly 32 pixels wide by 32 pixels high (rows 0 to 31, columns 0 to 31).
2. COLOR THEORY FOR EMISSIVE LEDS:
   - The panel background is pure unlit black: "#000000". Always use "." or " " mapped to "#000000" for unlit/empty space.
   - LEDs are additive light emitters: High-saturation, vibrant neon and primary colors (e.g. #FF0055, #00FFCC, #FFD700, #FF4500, #00E5FF, #76FF03, #D500F9, #FFFFFF) look crisp and brilliant on the matrix.
   - Avoid muddy, low-contrast, low-brightness dark pastel colors that wash out under LED diffuser lenses.
   - Use contrast shading: 1 bright highlight, 1 core body color, 1 subtle edge shade.
3. MOTION DYNAMICS & ANIMATION PHYSICS:
   - On a 32x32 grid, large jumps look like chaotic strobing. Displace moving elements by at most 1 to 2 pixels per frame for fluid, buttery-smooth motion.
   - For looping animations: The animation MUST loop seamlessly (the final frame flows smoothly back into frame 1).
   - Frame count: typically 4 to 12 frames at 8-12 fps gives the optimal balance of smoothness and LED hardware decode speed.
4. GLANCEABILITY:
   - Must be instantly recognizable from 2 meters away across a desk or room.
   - Strong silhouettes, clean 1-pixel outlines or solid punchy shapes.

OUTPUT SPECIFICATION:
Return valid JSON matching this schema:
{
  "title": "Short descriptive name",
  "palette": {
    ".": "#000000",
    "R": "#FF1744",
    "Y": "#FFEA00",
    "W": "#FFFFFF"
  },
  "frames": [
    {
      "duration_ms": 125,
      "rows": [
        "................................",
        ... (exactly 32 rows of 32 characters)
      ]
    }
  ]
}
Each row MUST be exactly 32 characters long.
There MUST be exactly 32 rows per frame.
Each character in each row MUST be defined in the palette dictionary with a 6-digit hex color "#RRGGBB".
"""

    @app.get("/api/ai/config")
    async def ai_config_get() -> dict[str, Any]:
        s = store.section("settings")
        has_env = bool(os.environ.get("GEMINI_API_KEY"))
        has_stored = bool(s.get("gemini_api_key"))
        masked = ""
        raw_key = os.environ.get("GEMINI_API_KEY") or s.get("gemini_api_key", "")
        if raw_key:
            masked = raw_key[:4] + "..." + raw_key[-4:] if len(raw_key) > 8 else "***"
        return {
            "configured": has_env or has_stored,
            "source": "env" if has_env else ("stored" if has_stored else "none"),
            "masked_key": masked,
            "model": s.get("gemini_model", "gemini-2.5-flash"),
        }

    @app.post("/api/ai/config")
    async def ai_config_set(body: AiConfigPatch) -> dict[str, Any]:
        s = store.section("settings")
        if body.api_key is not None:
            s["gemini_api_key"] = body.api_key.strip()
        if body.model is not None:
            s["gemini_model"] = body.model.strip()
        store.save()
        return await ai_config_get()

    @app.post("/api/ai/create")
    async def ai_create(body: AiCreateBody) -> dict[str, Any]:
        s = store.section("settings")
        key = (body.api_key or os.environ.get("GEMINI_API_KEY") or s.get("gemini_api_key", "")).strip()
        if not key:
            raise HTTPException(
                400,
                "Gemini API key required. Please enter your API key in the studio or set GEMINI_API_KEY in the environment.",
            )

        model = body.model or s.get("gemini_model", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

        user_content = (
            f"User Prompt: {body.prompt}\n"
            f"Desired number of frames: {body.num_frames}\n"
            f"Target playback rate: {body.fps} FPS (frame duration: {round(1000 / body.fps)} ms)\n"
            f"Generate a {body.num_frames}-frame looping 32x32 pixel animation."
        )

        req_payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{SYSTEM_GEMINI_PIXEL_PROMPT}\n\n{user_content}"}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.4,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(url, json=req_payload)
        except Exception as e:
            raise HTTPException(502, f"Failed to connect to Gemini API: {e}") from e

        if res.status_code != 200:
            err_msg = res.text
            try:
                err_json = res.json()
                err_msg = err_json.get("error", {}).get("message", res.text)
            except Exception:
                pass
            raise HTTPException(res.status_code, f"Gemini API error: {err_msg}")

        try:
            data = res.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned no candidates")
            part_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            cleaned = part_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            parsed = json.loads(cleaned.strip())
        except Exception as e:
            log.warning("failed to parse Gemini response: %s", e)
            raise HTTPException(502, f"Failed to parse Gemini response: {e}") from e

        title = str(parsed.get("title", body.prompt[:30]))
        palette = parsed.get("palette", {})
        if not isinstance(palette, dict):
            palette = {}
        if "." not in palette:
            palette["."] = "#000000"
        if " " not in palette:
            palette[" "] = "#000000"

        raw_frames = parsed.get("frames", [])
        if not raw_frames:
            raise HTTPException(502, "Gemini did not return any frames in the animation")

        default_dur = max(30, round(1000 / body.fps))
        frames: list[Frame] = []
        durations: list[int] = []
        clean_frames_json: list[dict[str, Any]] = []

        for idx, rf in enumerate(raw_frames[:16]):
            r_rows = rf.get("rows", [])
            norm_rows: list[str] = []
            for r in r_rows[:32]:
                s_row = str(r)
                s_row = s_row.ljust(32, ".") if len(s_row) < 32 else s_row[:32]
                norm_rows.append(s_row)
            while len(norm_rows) < 32:
                norm_rows.append("." * 32)

            try:
                fr = frame_from_rows(norm_rows, palette)
            except Exception as e:
                log.warning("frame_from_rows error on frame %s: %s; falling back to blank", idx, e)
                fr = Frame()

            dur = int(rf.get("duration_ms", default_dur))
            frames.append(fr)
            durations.append(dur)
            clean_frames_json.append({"rows": norm_rows, "duration_ms": dur})

        # Encode to native hardware-compatible GIF
        gif_bytes = encode_gif_budget(frames, durations)
        safe_name = "".join(c for c in title if c.isalnum() or c in ("-", "_", " ")).strip()[:30] or "gemini"
        item = await asyncio.to_thread(library.add, f"gemini_{safe_name}", gif_bytes)

        if body.action == "clip":
            engine.activate("gallery", {"media": item["id"]}, body.revert_after)
        elif body.action == "canvas" and clean_frames_json:
            await engine.action("canvas", "load", {"rows": clean_frames_json[0]["rows"], "palette": palette})
            engine.activate("canvas", None, body.revert_after)

        return {
            "ok": True,
            "title": title,
            "media_id": item["id"],
            "fps": body.fps,
            "frame_count": len(frames),
            "frames": clean_frames_json,
            "palette": palette,
            "gif_url": f"/api/media/{item['id']}/raw",
            "action": body.action,
        }

    # ------------------------------------------------------------ indicators
    @app.get("/api/indicators")
    async def indicators_get() -> dict[str, Any]:
        return engine.indicators_json()

    @app.post("/api/indicators/{slot}")
    async def indicator_set(
        slot: int = FPath(..., ge=1, le=3), body: Indicator = Body(default_factory=Indicator)
    ) -> dict[str, Any]:
        """AWTRIX-style corner indicator: 1 top-right, 2 right-middle, 3 bottom-right."""
        return {"ok": True, "slot": slot, "indicator": engine.set_indicator(slot, body)}

    @app.delete("/api/indicators/{slot}")
    async def indicator_clear(slot: int = FPath(..., ge=1, le=3)) -> dict[str, Any]:
        return {"ok": True, "cleared": engine.clear_indicator(slot)}

    # ------------------------------------------------------------ custom apps
    @app.get("/api/custom")
    async def custom_list() -> list[dict[str, Any]]:
        return phub.get("custom").listing()  # type: ignore[attr-defined,no-any-return]

    @app.post("/api/custom/{name}")
    async def custom_push(
        name: str, body: dict[str, Any] = Body(default_factory=dict), show: bool = Query(False)
    ) -> dict[str, Any]:
        """AWTRIX 3 custom app: push or replace; an empty body removes it (as in AWTRIX)."""
        if not CUSTOM_NAME.match(name):
            raise HTTPException(422, "name: 1-32 characters of letters, digits, _ and -")
        app_body = CustomApp.model_validate(body)
        if app_body.empty:
            return {"ok": True, "removed": engine.remove_custom(name)}
        try:
            entry = engine.push_custom(name, app_body)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        if show:
            engine.activate("custom", {"name": name})
        return {"ok": True, "name": name, "app": entry}

    @app.delete("/api/custom/{name}")
    async def custom_delete(name: str) -> dict[str, Any]:
        if not engine.remove_custom(name):
            raise HTTPException(404, f"no custom app {name!r}")
        return {"ok": True}

    # ------------------------------------------------------------ integrations
    @app.get("/api/integrations")
    async def integrations_get() -> dict[str, Any]:
        """On Air, Eye break, ntfy and Home Assistant settings (tokens masked) plus live status."""
        snap = engine.snapshot()["engine"]
        return {
            **engine.integrations(),
            "status": {
                "onair": snap["onair"],
                "eyebreak": snap["eyebreak"],
                "ntfy": phub.get("ntfy").snapshot(),
                "homeassistant": phub.get("homeassistant").snapshot(),
            },
        }

    @app.patch("/api/integrations/{section}")
    async def integrations_patch(section: str, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if section not in SECTIONS:
            raise HTTPException(404, f"section must be one of {list(SECTIONS)}")
        return engine.set_integration(section, patch)

    @app.post("/api/integrations/homeassistant/test")
    async def hass_test() -> dict[str, Any]:
        return await phub.get("homeassistant").check()  # type: ignore[attr-defined,no-any-return]

    @app.post("/api/onair/simulate")
    async def onair_simulate(body: SimulateBody = Body(default_factory=SimulateBody)) -> dict[str, Any]:
        """Preview the On-Air look for `seconds` (0 stops the preview)."""
        engine.simulate_onair(body.seconds)
        return {"ok": True, "onair": engine.onair}

    @app.post("/api/eyebreak/now")
    async def eyebreak_now() -> dict[str, Any]:
        engine.start_break()
        return {"ok": True}

    # ---------------------------------------------------------------- settings
    @app.patch("/api/settings")
    async def patch_global(p: SettingsPatch) -> dict[str, Any]:
        if p.brightness is not None:
            engine.set_brightness(p.brightness)
        if p.power is not None:
            engine.set_power(p.power)
        if p.flip is not None:
            engine.set_flip(p.flip)
        if p.transition is not None:
            store.set("transition", p.transition)
        if p.units is not None:
            store.set("units", p.units)
            phub.get("weather").refresh()
        if p.location is not None:
            store.set("location", p.location)
            phub.get("weather").refresh()
        if p.os_notifications is not None:
            cur = engine.os_notifications()
            cur.update({k: v for k, v in p.os_notifications.items() if k in cur})
            store.set("os_notifications", cur)
            engine._refresh_background()
        if p.audio_source is not None:
            store.set("audio_source", p.audio_source)
            phub.get("audio").restart()  # type: ignore[attr-defined]
        engine.changed()
        return engine.snapshot()["settings"]

    # ----------------------------------------------------------------- display
    @app.patch("/api/display")
    async def patch_display(p: DisplayPatch) -> dict[str, Any]:
        return engine.set_display(p.model_dump(exclude_none=True))

    @app.get("/api/calibration")
    async def get_calibration() -> dict[str, Any]:
        return engine.calibration.model_dump()

    @app.put("/api/calibration")
    async def put_calibration(c: PanelCalibration) -> dict[str, Any]:
        engine.set_calibration(c)
        return c.model_dump()

    @app.post("/api/calibration/pattern/{name}")
    async def calibration_pattern(
        name: Literal[
            "white",
            "gamma",
            "black",
            "saturation",
            "rgb",
            "preview",
            "protocol_tear",
            "protocol_stress",
            "protocol_cut",
        ],
    ) -> dict[str, Any]:
        engine.show_pattern(name)
        return {"ok": True, "pattern": name}

    @app.delete("/api/calibration/pattern")
    async def calibration_pattern_clear() -> dict[str, Any]:
        engine.clear_pattern()
        return {"ok": True}

    @app.post("/api/calibration/transfer/apply")
    async def calibration_transfer_apply(body: TransferCalibBody) -> dict[str, Any]:
        s = store.section("settings")
        d = store.section("display")
        d["max_fps"] = body.max_fps
        d["packet_gap_ms"] = body.packet_gap_ms
        s["transition"] = body.transition
        store.save()
        engine.device.min_frame_interval = 1.0 / body.max_fps
        engine.device.packet_gap = body.packet_gap_ms / 1000.0
        engine.clear_pattern()
        return {
            "ok": True,
            "max_fps": body.max_fps,
            "packet_gap_ms": body.packet_gap_ms,
            "transition": body.transition,
        }

    # ------------------------------------------------------------------ device
    @app.get("/api/handoff")
    async def handoff_get() -> dict[str, Any]:
        return {**engine.handoff_config(), "released": engine.released}

    @app.put("/api/handoff")
    async def handoff_put(body: HandoffPatch) -> dict[str, Any]:
        return engine.set_handoff(body.model_dump(exclude_none=True))

    @app.post("/api/handoff/now")
    async def handoff_now(
        mode: Literal["clock", "app", "last"] | None = Body(None, embed=True),
    ) -> dict[str, Any]:
        """Leave the panel running on its own (firmware clock or a looping GIF) — e.g. before closing the lid."""
        return {"ok": True, "result": await engine.handoff(mode), "released": engine.released}

    @app.post("/api/handoff/take-back")
    async def handoff_take_back() -> dict[str, Any]:
        engine.take_back()
        return {"ok": True, "released": engine.released}

    @app.post("/api/device/link")
    async def device_link(enabled: bool = Body(..., embed=True)) -> dict[str, Any]:
        await device.set_link(enabled)
        return {"ok": True, "link_enabled": enabled}

    @app.post("/api/device/reconnect")
    async def reconnect() -> dict[str, Any]:
        await device.reconnect()
        return {"ok": True}

    @app.get("/api/device/scan")
    async def scan() -> list[dict[str, Any]]:
        if cfg.device == "sim":
            return [{"address": "SIM:00:00:00:00:00", "name": "IDM-Simulator", "rssi": -40}]
        from .device.ble import scan as ble_scan

        return await ble_scan()

    @app.post("/api/device/raw")
    async def raw(hex_payload: str = Body(..., embed=True, alias="hex")) -> dict[str, Any]:
        """Advanced: send raw protocol bytes, e.g. {"hex": "05 00 04 80 32"}."""
        try:
            data = bytes.fromhex(hex_payload)
        except ValueError as e:
            raise HTTPException(400, "invalid hex") from e
        device.command(data)
        return {"ok": True, "bytes": len(data)}

    # ------------------------------------------------------------------- media
    @app.get("/api/media")
    async def media_list() -> list[dict[str, Any]]:
        return library.list()

    @app.post("/api/media")
    async def media_upload(file: UploadFile = File(...), show: bool = Query(True)) -> dict[str, Any]:
        data = await file.read()
        try:
            item = await asyncio.to_thread(library.add, file.filename or "upload", data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if show:
            engine.activate("gallery", {"media": item["id"]})
        return item

    @app.delete("/api/media/{mid}")
    async def media_delete(mid: str) -> dict[str, Any]:
        library.delete(mid)
        return {"ok": True}

    @app.get("/api/media/{mid}/raw")
    async def media_raw(mid: str) -> FileResponse:
        return FileResponse(library.path(mid))

    @app.get("/api/media/{mid}/preview.png")
    async def media_preview(
        mid: str, fit: str = "contain", profile: str = "auto", scale: int = Query(4, ge=1, le=16)
    ) -> Response:
        frames, _ = await asyncio.to_thread(import_media, library.read(mid), fit, profile)  # type: ignore[arg-type]
        return Response(
            frames[0].to_png(scale), media_type="image/png", headers={"Cache-Control": "max-age=60"}
        )

    @app.get("/api/nowplaying/art")
    async def nowplaying_art() -> Response:
        mp = phub.get("media")
        if not getattr(mp, "art", None):
            raise HTTPException(404, "no album art")
        art: bytes = mp.art
        kind = (
            "image/jpeg"
            if art.startswith(bytes((0xFF, 0xD8, 0xFF)))
            else "image/webp"
            if art[8:12] == b"WEBP"
            else "image/png"
        )
        return Response(art, media_type=kind, headers={"Cache-Control": "max-age=30"})

    @app.post("/api/nowplaying/{op}")
    async def nowplaying_control(op: Literal["toggle", "play", "pause", "next", "prev"]) -> dict[str, Any]:
        mp = phub.get("media")
        mp.acquire()
        try:
            return {"ok": await mp.control(op)}
        finally:
            mp.release()

    # -------------------------------------------------------------- websocket
    @app.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        await sock.accept()
        client = Client(sock)
        ws_hub.add(client)
        pump = asyncio.create_task(client.pump())
        try:
            while True:
                msg = json.loads(await sock.receive_text())
                if msg.get("type") == "paint":
                    await engine.action("canvas", "paint", {"pixels": msg.get("pixels", [])})
                elif msg.get("type") == "input" and msg.get("app") in REGISTRY:
                    # game controls: keys go straight to the app, no REST round-trip. `player` > 1 = a second
                    # local player on this computer (other keyboard half, another gamepad): seated on first press.
                    player = int(msg.get("player", 1) or 1)
                    with contextlib.suppress(KeyError, ValueError):
                        await engine.action(
                            msg["app"],
                            "input",
                            {"key": msg.get("key", ""), "player": player, "local": player > 1},
                        )
                elif msg.get("type") == "ping":
                    await sock.send_text(json.dumps({"type": "pong", "t": time.time()}))
        except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
            pass
        finally:
            pump.cancel()
            ws_hub.remove(client)

    # ------------------------------------------------------------------ studio
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="studio")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def no_studio() -> str:
            return (
                "<body style='font:15px system-ui;background:#0b0b10;color:#ddd;padding:40px'>"
                "<h2>DeskDot engine is running</h2><p>The studio isn't built yet. Run "
                "<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>, or use "
                "<code>npm run dev</code> for live reload.</p><p>API docs: <a style='color:#6cf' href='/docs'>/docs</a></p></body>"
            )

    return app
