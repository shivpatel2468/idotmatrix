"""The engine: decides what is on screen, renders it, and routes frames to the panel and the studio.

One asyncio task runs `_tick()` at the pace the visible app needs (1-20 Hz).
Rendering is synchronous and cheap; every slow thing (network, BLE, GIF
baking) happens in other tasks, so a tick never blocks.

Output routing per tick:
    stream app            -> PNG frame to the device slot (latest wins, deduped)
    clip app              -> GIF uploaded once per clip_key; preview plays the clip locally
    native app            -> firmware command sent once per settings change
    overlay / transition  -> always streamed (then the clip / native state is re-asserted)
    persistent overlays   -> status indicators and the On-Air badge / glow, composited last; while any is
                             visible the frame is streamed (a clip app plays from its baked frames)

Takeovers: while a call is live (On Air, full-screen style) or an eye break is due, a hidden app (`onair`,
`eyebreak`) replaces the playlist; the playlist resumes with a fresh item timer when it ends.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..config import Config, Store
from ..device import Device
from ..device import protocol as P
from ..gfx import Frame, to_rgb
from ..gfx.calib import PanelCalibration
from ..gfx.calib import apply as apply_calibration
from ..gfx.calib import pattern as calibration_pattern
from ..gfx.image import encode_gif_budget
from ..providers import Hub, Provider
from ..providers.custom import NAME as CUSTOM_NAME
from ..providers.custom import CustomApp
from ..providers.onair import filter_apps
from ..providers.sports import LEAGUE_SPORT
from . import integrations as integ
from .app import REGISTRY, App, AppSettings, Clip
from .overlay import ActiveNotice, Notice, Transition, transition
from .persistent import ActiveIndicator, Indicator, draw_indicators, draw_onair_badge, draw_onair_glow

log = logging.getLogger("dotdeck.engine")

TRANSITION_SECONDS = 0.4
IDLE_RESET_S = (
    120.0  # this long without keyboard/mouse input counts as a natural break (eye-break timer resets)
)


class PlaylistItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    app: str
    duration: float = Field(default=15.0, ge=3.0, le=3600.0)
    settings: dict[str, Any] = Field(default_factory=dict)  # overrides on top of the app's settings
    enabled: bool = True


class Playlist(BaseModel):
    enabled: bool = False
    items: list[PlaylistItem] = Field(default_factory=list)


DEFAULT_PLAYLIST = Playlist(
    items=[
        PlaylistItem(app="clock", duration=20),
        PlaylistItem(app="weather", duration=12),
        PlaylistItem(app="sysmon", duration=12),
        PlaylistItem(app="markets", duration=12),
        PlaylistItem(app="nowplaying", duration=20, settings={"take_over": True}),
    ]
)


class AppContext:
    """What an app may touch. Deliberately small."""

    def __init__(self, engine: Engine, key: str, app_id: str) -> None:
        self._engine = engine
        self.key = key
        self.app_id = app_id

    def provider(self, name: str) -> Provider[Any]:
        return self._engine.hub.get(name)

    @property
    def data(self) -> dict[str, Any]:
        """Persisted per-app scratch data (e.g. canvas pixels). Call save() after changing it."""
        return self._engine.store.section("app_data").setdefault(self.app_id, {})

    def save(self) -> None:
        self._engine.store.save_soon()

    def invalidate(self) -> None:
        """Re-render now (and re-bake the clip if the app is a clip app)."""
        self._engine.invalidate(self.key)

    def notify(self, **kw: Any) -> None:
        self._engine.notify(Notice(**kw))

    @property
    def media_dir(self) -> Path:
        return self._engine.config.media_dir

    @property
    def library(self) -> Any:
        """The MediaLibrary (uploads), or None in bare test engines."""
        return self._engine.library


class Slot:
    """One app instance — the manual app, or one playlist item (items may override settings)."""

    def __init__(self, key: str, app: App, item_id: str | None) -> None:
        self.key = key
        self.app = app
        self.item_id = item_id
        self.started = 0.0
        self.visible = False
        self.holding = False  # providers acquired
        self.clip: Clip | None = None
        self.clip_key: str | None = None
        self.baking: str | None = None
        self.gif: bytes | None = None
        self.gif_sent: str | None = None
        self.baked_at = 0.0  # monotonic time of the last finished bake (rate-limits chunk refreshes)
        self.native_sent: str | None = None
        self.error: str | None = None


class Engine:
    def __init__(self, config: Config, store: Store, device: Device, hub: Hub) -> None:
        self.config = config
        self.store = store
        self.device = device
        self.hub = hub
        self.slots: dict[str, Slot] = {}
        self.current: Slot | None = None
        self.mode: Literal["manual", "playlist"] = store.get("mode", "manual")
        self.manual_app: str = store.get("active", "clock")
        self.playlist = Playlist.model_validate(store.get("playlist") or DEFAULT_PLAYLIST.model_dump())
        self.pl_index = 0
        self.pl_started = time.monotonic()
        self.focus_key: str | None = None
        self.notices: deque[Notice] = deque(maxlen=20)
        self.overlay: ActiveNotice | None = None
        self._trans: tuple[Frame, float] | None = None
        self.frame = Frame()
        self._device_frame: Frame | None = None
        self.frame_listeners: set[Callable[[Frame], None]] = set()
        self.state_listeners: set[Callable[[], None]] = set()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.render_ms = 0.0
        self.ticks = 0
        self.library: Any = None
        self._revert: asyncio.Task[None] | None = None
        self._revert_to: tuple[Any, str, bool] | None = None
        self.auto_rule: int | None = None  # index of the autopilot rule currently in control
        self.calibration = PanelCalibration.model_validate(store.get("calibration") or {})
        self.released = False  # True after a hand-off: the panel runs on its own until we take it back
        self.pattern: tuple[str, Frame, float] | None = None  # calibration test pattern (name, frame, until)
        self._night_active = False
        self._night_checked = 0.0
        self._bg: set[str] = set()  # providers held in the background (alerts, autopilot)
        # platform features
        self.indicators: dict[int, ActiveIndicator] = {}
        self.onair: dict[str, Any] = {"active": False, "glyph": "mic", "apps": {}, "simulated": False}
        self._onair_sim_until = 0.0
        self._break_until = 0.0  # monotonic end of the running eye break (0 = none)
        self._active_since = time.monotonic()  # start of continuous activity (eye-break timer)
        self.takeover: str | None = None  # hidden app currently replacing the playlist
        self._persist_drawn = False
        self._persist_anim = False
        self._custom_checked = 0.0
        self._custom_items: tuple[float, list[PlaylistItem]] = (-1.0, [])
        self._integ_cache: dict[str, tuple[Any, dict[str, Any]]] = {}
        hub.listeners.append(self._on_event)

    # ================================================================ lifecycle
    async def start(self) -> None:
        self.apply_display(self.display())
        self.device.info.power = bool(self.store.get("power", True))
        self.device.set_brightness(int(self.store.get("brightness", 60)))
        self.device.command(P.set_time())
        if self.store.get("flip"):
            self.device.command(P.flip(True))
        await self.device.start()
        self._refresh_background()
        self._task = asyncio.create_task(self._run(), name="engine")

    async def stop(self) -> None:
        if self.handoff_config()["on_exit"] and self.device.connected:
            try:  # leave the panel showing something that runs without us
                await asyncio.wait_for(self.handoff(), 35)
            except Exception as e:
                log.warning("hand-off on exit failed: %s", e)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        for s in list(self.slots.values()):
            self._hide(s)
            self._release(s)
        await self.device.stop()
        await self.hub.close()
        self.store.save_now()

    def invalidate(self, key: str | None = None) -> None:
        if key and key in self.slots:
            self.slots[key].clip_key = None
        self._wake.set()

    def changed(self) -> None:
        for cb in list(self.state_listeners):
            cb()

    # =================================================================== apps
    def base_settings(self, app_id: str) -> dict[str, Any]:
        return dict(self.store.section("apps").get(app_id, {}))

    def _make_settings(self, app_id: str, overrides: dict[str, Any] | None = None) -> AppSettings:
        cls = REGISTRY[app_id]
        merged = {**self.base_settings(app_id), **(overrides or {})}
        try:
            return cls.Settings.model_validate(merged)
        except ValidationError as e:
            log.warning("invalid stored settings for %s (%s); using defaults", app_id, e.error_count())
            return cls.Settings()

    def _slot(self, app_id: str, item: PlaylistItem | None = None) -> Slot:
        key = f"{app_id}#{item.id}" if item and item.settings else app_id
        slot = self.slots.get(key)
        if slot is None:
            cls = REGISTRY[app_id]
            ctx = AppContext(self, key, app_id)
            app = cls(ctx, self._make_settings(app_id, item.settings if item else None))
            slot = Slot(key, app, item.id if item else None)
            self.slots[key] = slot
        return slot

    def _hold(self, s: Slot) -> None:
        if not s.holding:
            for name in s.app.uses:
                self.hub.get(name).acquire()
            s.holding = True

    def _release(self, s: Slot) -> None:
        if s.holding:
            for name in s.app.uses:
                self.hub.get(name).release()
            s.holding = False

    def _show(self, s: Slot) -> None:
        self._hold(s)
        s.visible = True
        s.started = time.monotonic()
        s.gif_sent = None
        s.native_sent = None
        try:
            s.app.on_start()
        except Exception:
            log.exception("%s.on_start failed", s.key)

    def _hide(self, s: Slot) -> None:
        if not s.visible:
            return
        s.visible = False
        try:
            s.app.on_stop()
        except Exception:
            log.exception("%s.on_stop failed", s.key)
        if not (self.mode == "playlist" and self.playlist.enabled and s.app.watches_focus()):
            self._release(s)

    def _switch(self, s: Slot) -> None:
        if self.current is s:
            return
        old = self.current
        if old is not None:
            self._trans = (self.frame.copy(), time.monotonic())
            self._hide(old)
        self.current = s
        self._show(s)
        self.changed()

    # ============================================================== selection
    def _playlist_items(self) -> list[PlaylistItem]:
        items = [i for i in self.playlist.items if i.enabled and i.app in REGISTRY]
        return items + self._custom_playlist() if "custom" in REGISTRY else items

    def _custom_playlist(self) -> list[PlaylistItem]:
        """Fresh custom push apps join the rotation after the user's items (rebuilt only when they change)."""
        prov = self.hub.get("custom")
        if self._custom_items[0] != prov.updated:
            apps = prov.value or {}
            self._custom_items = (
                prov.updated,
                [
                    PlaylistItem(
                        id=f"custom-{n}",
                        app="custom",
                        duration=float(d.get("duration") or 10),
                        settings={"name": n},
                    )
                    for n, d in apps.items()
                ],
            )
        return self._custom_items[1]

    # ============================================================= autopilot
    def autopilot(self) -> dict[str, Any]:
        ap = self.store.get("autopilot") or {}
        return {"enabled": bool(ap.get("enabled")), "rules": list(ap.get("rules") or DEFAULT_RULES)}

    def set_autopilot(self, enabled: bool, rules: list[dict[str, Any]]) -> None:
        clean = []
        for r in rules:
            if r.get("app") not in REGISTRY or not str(r.get("match", "")).strip():
                raise ValueError(f"bad autopilot rule {r}")
            clean.append(
                {"match": str(r["match"]).strip(), "app": r["app"], "settings": r.get("settings") or {}}
            )
        self.store.set("autopilot", {"enabled": enabled, "rules": clean})
        for key in [k for k in self.slots if "@auto" in k and self.slots[k] is not self.current]:
            self._release(self.slots.pop(key))
        self._refresh_background()
        self._wake.set()
        self.changed()

    def _autopilot_slot(self) -> Slot | None:
        ap = self.autopilot()
        if not ap["enabled"]:
            self._set_rule(None)
            return None
        w = self.hub.get("window").value or {}
        proc, title = str(w.get("proc", "")), str(w.get("title", "")).lower()
        for i, rule in enumerate(ap["rules"]):
            needle = rule["match"].lower()
            hay = title if needle.startswith("title:") else proc
            needle = needle.removeprefix("title:").strip()
            if needle and needle in hay and rule["app"] in REGISTRY:
                self._set_rule(i)
                item = PlaylistItem(id=f"auto{i}", app=rule["app"], settings=rule.get("settings") or {})
                s = self._slot(rule["app"], item)
                return s
        self._set_rule(None)
        return None

    def _set_rule(self, idx: int | None) -> None:
        if self.auto_rule != idx:
            self.auto_rule = idx
            self.changed()

    def _refresh_background(self) -> None:
        """Keep providers alive that background features need (autopilot, score alerts)."""
        want: set[str] = set()
        if self.autopilot()["enabled"]:
            want.add("window")
        if self.os_notifications()["enabled"]:
            want.add("notifications")
        if self.integration("onair")["enabled"]:
            want.add("onair")
        if self.integration("eyebreak")["enabled"]:
            want |= {"idle", "onair"}
        nt = self.integration("ntfy")
        if nt["enabled"] and nt["topics"].strip():
            want.add("ntfy")
        sc = self.base_settings("scores")
        if sc.get("alerts", "favorite") != "off" and (sc.get("team") or sc.get("alerts") == "all"):
            want.add("sports")
            from ..apps.scores import parse_leagues

            leagues = parse_leagues(str(sc.get("leagues") or "")) or [sc.get("league") or "nba"]
            self.hub.get("sports").want(*leagues)  # type: ignore[attr-defined]
        for name in want - self._bg:
            self.hub.get(name).acquire()
        for name in self._bg - want:
            self.hub.get(name).release()
        self._bg = want

    # ================================================================ events
    def os_notifications(self) -> dict[str, Any]:
        d = {"enabled": False, "style": "banner", "duration": 6, "only": "", "exclude": ""}
        d.update(self.store.get("os_notifications") or {})
        return d

    def _on_os_notification(self, n: dict[str, Any]) -> None:
        cfg = self.os_notifications()
        if not cfg["enabled"]:
            return
        app = str(n.get("app", ""))
        only = [a.strip().lower() for a in str(cfg["only"]).split(",") if a.strip()]
        excl = [a.strip().lower() for a in str(cfg["exclude"]).split(",") if a.strip()]
        if (only and app.lower() not in only) or app.lower() in excl:
            return
        color, icon = APP_STYLE.get(app, ("#00dcff", "bell"))
        title = (n.get("title") or app)[:40]
        body = n.get("body") or ""
        msg = f"{title} · {body}" if body and cfg["style"] == "banner" else (body or title)
        self.notify(
            Notice(
                title=app.upper()[:12],
                message=msg[:280],
                color=color,
                icon=icon,
                style=cfg["style"] if cfg["style"] in ("banner", "full") else "banner",
                duration=float(cfg["duration"]),
            )
        )

    def _on_event(self, event: str, data: dict[str, Any]) -> None:
        """Provider events → overlays: OS notifications, sports score / start / final alerts."""
        if event == "os_notification":
            self._on_os_notification(data)
            return
        if event == "ntfy":
            self._on_ntfy(data)
            return
        if event not in ("score", "game_start", "game_final"):
            return
        sc = self.base_settings("scores")
        mode = sc.get("alerts", "favorite")
        favs = {x.strip() for x in str(sc.get("team", "")).upper().split(",") if x.strip()}
        g = data["game"]
        names = {str(c.get(k) or "").upper() for c in (g["away"], g["home"]) for k in ("abbr", "short")}
        if mode == "off" or (mode == "favorite" and not favs & names):
            return
        league = data["league"]
        sport = LEAGUE_SPORT.get(league, "other")
        score_line = f"{g['away']['abbr']} {g['away']['score']}-{g['home']['score']} {g['home']['abbr']}"
        if event == "score":
            t = data["team"]
            if sport == "basketball" and mode == "all":
                return  # every basket would be noise; basketball alerts only for your team
            word = {
                "soccer": "GOAL!",
                "hockey": "GOAL!",
                "football": "SCORE!",
                "baseball": "RUN!",
                "basketball": f"+{data['delta']}",
                "cricket": f"+{data['delta']}",
            }.get(sport, "SCORE!")
            self.notify(
                Notice(
                    title=t["abbr"],
                    message=f"{word} {score_line}",
                    color=_led_hex(t["color"], t["alt"]),
                    icon=None,
                    style="celebrate",
                    duration=7 if sport != "basketball" else 4,
                )
            )
        elif event == "game_start":
            self.notify(Notice(title=data["tag"], message=f"KICKOFF {score_line}", icon="bell", duration=6))
        else:
            self.notify(Notice(title="FINAL", message=score_line, icon="ok", duration=8, style="full"))

    def _select(self, now: float) -> Slot:
        take = self._takeover_slot(now)
        if take is not None:
            return take
        auto = self._autopilot_slot()
        if auto is not None:
            return auto
        items = self._playlist_items()
        if self.mode != "playlist" or not self.playlist.enabled or not items:
            return self._slot(self.manual_app if self.manual_app in REGISTRY else "clock")
        # focus: an app that asks to be shown right now (music started, favourite team live…)
        for it in items:
            s = self._slot(it.app, it)
            if s.app.watches_focus():
                self._hold(s)
                if s.app.wants_focus():
                    if self.focus_key != s.key:
                        self.focus_key = s.key
                        self.changed()
                    return s
        if self.focus_key is not None:
            self.focus_key = None
            self.pl_started = now
            self.changed()
        self.pl_index %= len(items)
        cur = items[self.pl_index]
        if now - self.pl_started >= cur.duration:
            self._advance(items, +1, now)
            cur = items[self.pl_index]
        return self._slot(cur.app, cur)

    def _advance(self, items: list[PlaylistItem], step: int, now: float) -> None:
        for _ in range(len(items)):
            self.pl_index = (self.pl_index + step) % len(items)
            s = self._slot(items[self.pl_index].app, items[self.pl_index])
            if s.app.relevant():
                break
        self.pl_started = now
        self.changed()

    # ============================================================== platform
    def integration(self, section: str) -> dict[str, Any]:
        """One integration section (onair / eyebreak / ntfy / homeassistant), unmasked: engine use only.

        Cached per stored object: the store replaces the dict on every change, so identity is the version.
        """
        raw = self.store.get(section)
        hit = self._integ_cache.get(section)
        if hit is not None and hit[0] is raw:
            return hit[1]
        data = integ.load(self.store, section)
        self._integ_cache[section] = (raw, data)
        return data

    def integrations(self) -> dict[str, Any]:
        """All integration sections with secrets masked (for snapshots and API responses)."""
        return {name: integ.public(name, self.integration(name)) for name in integ.SECTIONS}

    def set_integration(self, section: str, patch: dict[str, Any]) -> dict[str, Any]:
        data = integ.merge(self.store, section, patch)
        if section == "ntfy":
            self._refresh_background()
            self.hub.get("ntfy").restart()  # type: ignore[attr-defined]
        elif section == "homeassistant":
            self.hub.get("homeassistant").reset()  # type: ignore[attr-defined]
        else:
            self._refresh_background()
        self._wake.set()
        self.changed()
        return integ.public(section, data)

    def _platform(self, now: float) -> None:
        """Per-tick upkeep of the platform features. Cheap: dict lookups on cached provider values."""
        gone = [k for k, a in self.indicators.items() if a.expired(now)]
        for k in gone:
            del self.indicators[k]
        if gone:
            self.changed()
        self._update_onair(now)
        self._update_eyebreak(now)
        if now - self._custom_checked >= 1.0:
            self._custom_checked = now
            before = set(self.hub.get("custom").value or {})
            after = set(self.hub.get("custom").fresh())  # type: ignore[attr-defined]
            if before - after:
                self._drop_custom_slots(before - after)
                self.changed()

    # ------------------------------------------------------------- on air
    def _update_onair(self, now: float) -> None:
        cfg = self.integration("onair")
        apps: dict[str, list[str]] = {}
        if cfg["enabled"]:
            raw = (self.hub.get("onair").value or {}).get("in_use") or {}
            devices = {d for d in ("webcam", "microphone") if cfg[d]}
            apps = filter_apps(raw, devices, cfg["exclude"])
        simulated = now < self._onair_sim_until and not apps
        if simulated:
            apps = {"webcam": ["PREVIEW"], "microphone": ["PREVIEW"]}
        glyph = "both" if len(apps) == 2 else ("cam" if "webcam" in apps else "mic")
        state = {"active": bool(apps), "glyph": glyph, "apps": apps, "simulated": simulated}
        if state != self.onair:
            if state["active"] != self.onair["active"]:
                log.info("on air: %s %s", "ON" if state["active"] else "off", apps or "")
                self._wake.set()
            self.onair = state
            self.changed()

    def simulate_onair(self, seconds: float) -> None:
        """Preview the On-Air look for a few seconds (works even while the feature is disabled)."""
        self._onair_sim_until = time.monotonic() + seconds if seconds > 0 else 0.0
        self._update_onair(time.monotonic())
        self._wake.set()

    def _call_busy(self) -> bool:
        """Camera or mic in use by a non-excluded app (checked even when the On-Air display is off)."""
        if self.onair["active"]:
            return True
        raw = (self.hub.get("onair").value or {}).get("in_use") or {}
        return bool(filter_apps(raw, {"webcam", "microphone"}, self.integration("onair")["exclude"]))

    # ---------------------------------------------------------- eye break
    def _update_eyebreak(self, now: float) -> None:
        from ..apps.eyebreak import TOTAL

        if self._break_until:
            if now >= self._break_until or self.onair["active"]:
                self._break_until = 0.0
                self._active_since = now
                self._wake.set()
                self.changed()
            return
        cfg = self.integration("eyebreak")
        idle = self.hub.get("idle").value or {}
        if not cfg["enabled"] or not idle.get("supported"):
            self._active_since = now
            return
        if float(idle.get("idle_s", 0)) >= IDLE_RESET_S:
            self._active_since = now  # away from the keyboard: that is a break already
            return
        if now - self._active_since < cfg["interval_min"] * 60:
            return
        if idle.get("fullscreen") or self._call_busy() or self.released or self.pattern is not None:
            return  # postponed: checked again on the next tick
        if not self.store.get("power", True):
            return
        log.info("eye break (20-20-20) after %.0f min of activity", (now - self._active_since) / 60)
        self._break_until = now + TOTAL
        self._wake.set()
        self.changed()

    def start_break(self) -> None:
        """Show the eye-break nudge now (the studio's "try it")."""
        from ..apps.eyebreak import TOTAL

        self.take_back()
        self._break_until = time.monotonic() + TOTAL
        self._wake.set()
        self.changed()

    def _eyebreak_state(self, now: float) -> dict[str, Any]:
        cfg = self.integration("eyebreak")
        nxt = None
        if cfg["enabled"] and not self._break_until:
            nxt = max(0.0, cfg["interval_min"] * 60 - (now - self._active_since))
        return {
            "active": bool(self._break_until),
            "next_in_s": round(nxt) if nxt is not None else None,
            "supported": bool((self.hub.get("idle").value or {}).get("supported", True)),
        }

    # ----------------------------------------------------------- takeover
    def _takeover_slot(self, now: float) -> Slot | None:
        name: str | None = None
        slot: Slot | None = None
        cfg = self.integration("onair")
        if self.onair["active"] and cfg["style"] == "full":
            name = "onair"
            g, look = self.onair["glyph"], cfg["look"]
            item = PlaylistItem(id=f"onair-{g}-{look}", app="onair", settings={"glyph": g, "look": look})
            slot = self._slot("onair", item)
        elif self._break_until:
            name = "eyebreak"
            style = self.integration("eyebreak")["style"]
            item = PlaylistItem(id=f"break-{style}", app="eyebreak", settings={"style": style})
            slot = self._slot("eyebreak", item)
        if name != self.takeover:
            if self.takeover is not None and name is None:
                self.pl_started = now  # hand the playlist back with a fresh timer for its current item
            self.takeover = name
            self.changed()
        return slot

    # ---------------------------------------------------- persistent overlays
    def _draw_persistent(self, frame: Frame, now: float) -> bool:
        drawn = anim = False
        if self.onair["active"] and self.takeover != "onair":
            style = self.integration("onair")["style"]
            if style == "badge":
                draw_onair_badge(frame, self.onair["glyph"], now)
                drawn = True
            elif style == "glow":
                draw_onair_glow(frame, now)
                drawn = anim = True
        if self.indicators:
            draw_indicators(frame, self.indicators, now)
            drawn = True
            anim = anim or any(a.animated for a in self.indicators.values())
        self._persist_drawn, self._persist_anim = drawn, anim
        return drawn

    def set_indicator(self, slot: int, ind: Indicator) -> dict[str, Any]:
        if slot not in (1, 2, 3):
            raise KeyError(f"indicator {slot}")
        self.indicators[slot] = ActiveIndicator(ind)
        self._wake.set()
        self.changed()
        return self.indicators[slot].to_json(time.monotonic())

    def clear_indicator(self, slot: int) -> bool:
        had = self.indicators.pop(slot, None) is not None
        self._wake.set()
        self.changed()
        return had

    def indicators_json(self) -> dict[str, Any]:
        now = time.monotonic()
        return {str(k): a.to_json(now) for k, a in sorted(self.indicators.items())}

    # --------------------------------------------------------- custom apps
    def push_custom(self, name: str, app: CustomApp) -> dict[str, Any]:
        entry = self.hub.get("custom").push(name, app)  # type: ignore[attr-defined]
        for s in self.slots.values():
            if s.app.id == "custom":
                s.clip_key = None
        self._wake.set()
        self.changed()
        return entry

    def remove_custom(self, name: str) -> bool:
        ok = self.hub.get("custom").remove(name)  # type: ignore[attr-defined]
        if ok:
            self._drop_custom_slots({name})
            self._wake.set()
            self.changed()
        return ok

    def _drop_custom_slots(self, names: set[str]) -> None:
        for key in [f"custom#custom-{n}" for n in names]:
            s = self.slots.get(key)
            if s is not None and s is not self.current:
                self._release(self.slots.pop(key))

    # ---------------------------------------------------------------- ntfy
    def _on_ntfy(self, m: dict[str, Any]) -> None:
        cfg = self.integration("ntfy")
        tags = [str(t) for t in m.get("tags") or []]
        icon = next((NTFY_ICONS[t] for t in tags if t in NTFY_ICONS), None)
        prio = int(m.get("priority") or 3)
        color = NTFY_COLORS.get(prio, "#00dcff")
        prefix = cfg["route_prefix"]
        route = next(
            (
                t[len(prefix) :]
                for t in tags
                if prefix and t.startswith(prefix) and CUSTOM_NAME.match(t[len(prefix) :])
            ),
            None,
        )
        text = str(m.get("message") or m.get("title") or "")
        if route:
            try:
                app = CustomApp(text=text[:500], icon=icon, color=color, lifetime=float(cfg["lifetime"]))
                self.push_custom(route, app)
            except ValueError as e:
                log.info("ntfy route to custom app %r failed: %s", route, e)
            return
        style = cfg["style"] if cfg["style"] != "auto" else ("full" if prio >= 4 else "banner")
        title = str(m.get("title") or m.get("topic") or "NTFY").upper()
        self.notify(
            Notice(
                title=title[:40],
                message=text[:280] if m.get("message") else "",
                color=color,
                icon=icon or ("warn" if prio >= 4 else "bell"),
                duration=float(cfg["duration"]) + (4 if prio == 5 else 0),
                style=style,
            )
        )

    # ================================================================== loop
    async def _run(self) -> None:
        while True:
            t0 = time.perf_counter()
            try:
                self._tick()
            except Exception:
                log.exception("tick failed")
            self.render_ms = round((time.perf_counter() - t0) * 1000, 2)
            self.ticks += 1
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._delay())
            except TimeoutError:
                pass

    def fly_telemetry(self) -> dict[str, Any]:
        """The current app's fruit-fly brain activity (docs/FLY_BRAIN.md); {"active": False} when no fly plays."""
        s = self.current
        if s is None:
            return {"active": False, "app": None}
        try:
            snap = s.app.fly_telemetry(time.monotonic() - s.started)
        except Exception:
            log.exception("%s.fly_telemetry failed", s.key)
            snap = None
        if snap is None:
            return {"active": False, "app": s.app.id}
        return {"active": True, "app": s.app.id, **snap}

    def _delay(self) -> float:
        if self._trans or self.overlay:
            return 1 / 20
        s = self.current
        if s is None:
            return 0.5
        kind = s.app.kind()
        if self._persist_anim:  # blinking / fading indicators, the On-Air glow
            return min(1 / 10, 1 / max(0.2, min(30.0, s.app.fps)))
        if kind == "clip":
            return 1 / s.app.clip_fps if self.frame_listeners or self._persist_drawn else 0.5
        if kind == "native":
            return 1.0 if self.frame_listeners else 2.0
        return 1 / max(0.2, min(30.0, s.app.fps))

    def _panel(self, frame: Frame) -> Frame:
        """The frame as sent to the LEDs: design colours through this panel's calibration."""
        if self.calibration.identity:
            return frame
        return Frame(apply_calibration(frame.px, self.calibration))

    def _tick(self) -> None:
        now = time.monotonic()
        self._night(now)
        self._platform(now)
        if self.released:  # handed off: the panel runs on its own until the user shows something again
            return
        if self.pattern is not None:  # calibration wizard owns the panel
            _name, pat, until = self.pattern
            if now < until:
                if self._device_frame is None or pat != self._device_frame:
                    self._device_frame = pat.copy()
                    self.device.show_frame(pat.to_png())  # patterns carry their own corrections
                if pat != self.frame:
                    self.frame = pat
                    for cb in list(self.frame_listeners):
                        cb(pat)
                return
            self.pattern = None
            self._device_frame = None
            if self.current:
                self.current.gif_sent = None
                self.current.native_sent = None
            self.changed()
        self._switch(self._select(now))
        s = self.current
        assert s is not None
        app = s.app
        kind = app.kind()
        t = now - s.started

        frame = Frame()
        try:
            if kind == "clip":
                self._ensure_clip(s)
                if s.clip is not None:
                    frame = s.clip.frame_at(t).copy()
                else:
                    app.render(frame, t)
            else:
                app.render(frame, t)
            s.error = None
        except Exception as e:
            if s.error is None:
                log.exception("%s.render failed", s.key)
            s.error = f"{type(e).__name__}: {e}"
            frame = _error_frame()

        # overlays
        if self.overlay and self.overlay.done:
            self.overlay = None
            self.changed()
        if self.overlay is None and self.notices:
            self.overlay = ActiveNotice(self.notices.popleft())
            self.changed()
        if self.overlay:
            self.overlay.render(frame)
        if self._trans:
            old, t0 = self._trans
            p = (now - t0) / TRANSITION_SECONDS
            style: Transition = self.store.get("transition", "cut")
            if p >= 1 or style == "cut" or kind in ("clip", "native"):
                self._trans = None
            else:
                frame = transition(old, frame, p, style)
        drawn = self._draw_persistent(frame, now)

        streaming = kind == "stream" or self.overlay is not None or self._trans is not None or drawn
        if streaming:
            if kind == "clip":
                s.gif_sent = None
            if kind == "native":
                s.native_sent = None
            if self._device_frame is None or frame != self._device_frame:
                self._device_frame = frame.copy()
                self.device.show_frame(self._panel(frame).to_png())
        elif kind == "clip":
            if s.gif is not None and s.gif_sent != s.clip_key:
                s.gif_sent = s.clip_key
                self._device_frame = None
                self.device.show_gif(s.gif)
        elif kind == "native":
            key = app.clip_key()
            if s.native_sent != key:
                s.native_sent = key
                self._device_frame = None
                try:
                    self.device.command(app.native_command(), mode="native")
                except Exception as e:
                    log.warning("%s native command failed: %s", s.key, e)

        if frame != self.frame:
            self.frame = frame
            for cb in list(self.frame_listeners):
                cb(frame)

    def _ensure_clip(self, s: Slot) -> None:
        ident, chunk = s.app.clip_key(), s.app.clip_chunk()
        key = f"{ident}||{chunk}"
        if s.clip_key == key or s.baking == key:
            return
        # A new time-slice of the same clip (identity unchanged) is rate-limited: back-to-back GIF uploads make
        # the panel stop acking chunks and freeze (docs/HARDWARE_PROTOCOL.md #16). Real changes bake at once.
        same_ident = s.clip_key is not None and s.clip_key.split("||", 1)[0] == ident
        if same_ident and time.monotonic() - s.baked_at < s.app.clip_refresh:
            return
        s.baking = key

        async def bake() -> None:
            try:
                clip = await asyncio.to_thread(s.app.clip_frames)
                panel_frames = [self._panel(fr) for fr in clip.frames]  # through the panel calibration
                gif = await asyncio.to_thread(
                    encode_gif_budget, panel_frames, clip.durations_ms, s.app.clip_colors
                )
                if s.baking == key:
                    s.clip, s.gif, s.clip_key = clip, gif, key
                    s.baked_at = time.monotonic()
                    log.info("baked clip %s: %d frames, %.1f KB", s.key, len(clip.frames), len(gif) / 1024)
            except Exception:
                log.exception("baking clip for %s failed", s.key)
            finally:
                if s.baking == key:
                    s.baking = None
                self._wake.set()

        asyncio.get_running_loop().create_task(bake())

    # ============================================================== commands
    def activate(
        self, app_id: str, settings: dict[str, Any] | None = None, revert_after: float | None = None
    ) -> None:
        """Show an app now. Pauses the playlist (the studio offers 'resume').

        Also takes the panel back after a hand-off.

        With `revert_after`, whatever was showing before comes back after that many seconds
        (used by agent status pings and one-off "show this" requests).
        """
        if app_id not in REGISTRY:
            raise KeyError(app_id)
        if settings:
            settings = strip_masked(REGISTRY[app_id], settings)
        self.take_back()
        if self._revert and not self._revert.done():
            self._revert.cancel()
        if revert_after:
            # chained temporary activations all return to the state before the first one
            prev = self._revert_to or (self.mode, self.manual_app, self.playlist.enabled)
            self._revert_to = prev

            async def later() -> None:
                await asyncio.sleep(revert_after)
                self.mode, self.manual_app = prev[0], prev[1]
                self.playlist.enabled = prev[2]
                self._revert_to = None
                self.pl_started = time.monotonic()
                self._wake.set()
                self.changed()

            self._revert = asyncio.get_running_loop().create_task(later())
        else:
            self._revert_to = None
        if settings:
            self.update_settings(app_id, settings)
        self.manual_app = app_id
        self.mode = "manual"
        if not revert_after:
            self.store.set("active", app_id)
            self.store.set("mode", "manual")
        self._wake.set()
        self.changed()

    def update_settings(self, app_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        cls = REGISTRY[app_id]
        patch = strip_masked(cls, patch)  # "••••••" from the studio means "keep the stored secret"
        base = self.base_settings(app_id)
        # Stored values can go stale when an app's schema changes (renamed/re-ranged fields). Drop the
        # stored keys that no longer validate so they fall back to defaults; the patch itself is strict.
        for _ in range(len(base) + 1):
            try:
                validated = cls.Settings.model_validate({**base, **patch})
                break
            except ValidationError as e:
                bad = {str(err["loc"][0]) for err in e.errors() if err["loc"]} - set(patch)
                if not bad:  # model-level errors (Choice checks) carry no field: find the culprit
                    bad = {k for k in base if k not in patch and _valid_without(cls, base, patch, k)}
                if not bad:
                    raise  # the patch itself is invalid -> 422
                for k in bad:
                    base.pop(k, None)
        data = validated.model_dump(mode="json")
        self.store.section("apps")[app_id] = data
        self.store.save_soon()
        items = {i.id: i for i in self.playlist.items}
        for s in self.slots.values():
            if s.app.id == app_id:
                ov = items[s.item_id].settings if s.item_id in items else None
                s.app.settings = self._make_settings(app_id, ov)
                s.clip_key = None
                try:
                    s.app.on_settings()
                except Exception:
                    log.exception("%s.on_settings failed", s.key)
        if app_id == "scores":
            self._refresh_background()
        self._wake.set()
        self.changed()
        return redact_secrets(cls, data)

    async def action(self, app_id: str, name: str, payload: dict[str, Any]) -> Any:
        s = self.current if self.current and self.current.app.id == app_id else self._slot(app_id)
        result = await s.app.action(name, payload)
        self._wake.set()
        self.changed()
        return result

    # ============================================================== hand-off
    def handoff_config(self) -> dict[str, Any]:
        d = dict(HANDOFF_DEFAULT)
        d.update(self.store.get("handoff") or {})
        return d

    def set_handoff(self, patch: dict[str, Any]) -> dict[str, Any]:
        cur = self.handoff_config()
        cur.update({k: v for k, v in patch.items() if k in HANDOFF_DEFAULT})
        self.store.set("handoff", cur)
        self.changed()
        return cur

    async def handoff(self, mode: str | None = None) -> str:
        """Leave the panel showing something it can run by itself (before exit, sleep, or on request).

        "clock": the panel's firmware clock (keeps time, tiny to send). "app": a looping GIF of an app, baked
        now through the panel calibration (the panel loops GIFs natively). "last": leave whatever is showing.
        The engine stops streaming until something is shown again (`take_back`).
        """
        cfg = self.handoff_config()
        mode = mode or cfg["mode"]
        if not self.device.connected:
            return "not connected"
        if mode == "last":
            self.released = True
            self.changed()
            return "left as is"
        self.released = True
        self._device_frame = None
        if self.current:
            self.current.gif_sent = None
            self.current.native_sent = None
        if mode == "clock":
            self.device.command(
                [
                    P.set_time(),
                    P.clock(int(cfg["clock_style"]), True, bool(cfg["hour24"]), to_rgb(cfg["color"])),
                ],
                mode="native",
            )
        else:
            app_id = cfg["app"] if cfg["app"] in REGISTRY else "clock"
            app = self._slot(app_id).app
            seconds = max(2.0, min(30.0, float(cfg["seconds"])))

            def bake() -> bytes:
                if app.kind() == "clip":
                    clip = app.clip_frames()
                    frames, durations = clip.frames, clip.durations_ms
                else:
                    fps = 8.0
                    frames = []
                    for i in range(round(seconds * fps)):
                        fr = Frame()
                        app.render(fr, i / fps)
                        frames.append(fr)
                    durations = [round(1000 / fps)] * len(frames)
                return encode_gif_budget([self._panel(fr) for fr in frames], durations, app.clip_colors)

            self.device.show_gif(await asyncio.to_thread(bake))
        ok = await self.device.flush(30.0)
        self.changed()
        log.info("handed off to the panel (%s)%s", mode, "" if ok else " — upload did not finish")
        return mode if ok else f"{mode} (incomplete)"

    def _preset_info(self) -> dict[str, Any] | None:
        """{id, name, shuffle} of the preset driving the playlist, if any (for the studio's playback line)."""
        from . import presets

        pid = self.store.get("active_preset")
        p = presets.find(self.store, pid) if pid else None
        if p is None:
            return None
        return {"id": pid, "name": p["name"], "shuffle": bool(self.store.get("active_preset_shuffle", False))}

    def take_back(self) -> None:
        """Resume driving the panel after a hand-off."""
        if self.released:
            self.released = False
            self._device_frame = None
            if self.current:
                self.current.gif_sent = None
                self.current.native_sent = None
            self._wake.set()
            self.changed()

    def set_playlist(self, pl: Playlist) -> None:
        for key in [k for k, s in self.slots.items() if s.item_id and s is not self.current]:
            self._release(self.slots.pop(key))
        self.playlist = pl
        self.pl_index = min(self.pl_index, max(0, len(pl.items) - 1))
        self.store.set("playlist", pl.model_dump(mode="json"))
        self._wake.set()
        self.changed()

    def playlist_control(self, op: Literal["play", "stop", "next", "prev"]) -> None:
        if op != "stop":
            self.take_back()
        now = time.monotonic()
        items = self._playlist_items()
        if op == "play":
            self.playlist.enabled = True
            self.mode = "playlist"
            self.pl_started = now
        elif op == "stop":
            self.playlist.enabled = False
            self.mode = "manual"
            for s in self.slots.values():
                if not s.visible:
                    self._release(s)
        elif items:
            self.mode = "playlist"
            self.playlist.enabled = True
            self.focus_key = None
            self._advance(items, 1 if op == "next" else -1, now)
        self.store.set("mode", self.mode)
        self.store.set("playlist", self.playlist.model_dump(mode="json"))
        self._wake.set()
        self.changed()

    def notify(self, notice: Notice) -> None:
        self.notices.append(notice)
        self._wake.set()
        self.changed()

    def dismiss(self) -> None:
        self.overlay = None
        self.notices.clear()
        self._wake.set()
        self.changed()

    # ============================================================ display
    def display(self) -> dict[str, Any]:
        d = {
            "max_fps": self.config.max_fps,
            "packet_gap_ms": self.config.packet_gap_ms,
            "night": {"enabled": False, "start": "23:00", "end": "07:00", "brightness": 10},
            "idle_dim": 0,
        }
        stored = self.store.get("display") or {}
        d.update({k: v for k, v in stored.items() if k != "night"})
        d["night"].update(stored.get("night") or {})
        return d

    def apply_display(self, d: dict[str, Any]) -> None:
        self.device.min_frame_interval = 1.0 / max(0.5, min(30.0, float(d["max_fps"])))
        if self.device.kind == "ble":
            self.device.packet_gap = max(0.0, min(0.2, float(d["packet_gap_ms"]) / 1000))

    def set_display(self, patch: dict[str, Any]) -> dict[str, Any]:
        cur = self.display()
        if "night" in patch:
            cur["night"].update(patch.pop("night") or {})
        cur.update(patch)
        self.store.set("display", cur)
        self.apply_display(cur)
        self._night_checked = 0.0
        self.changed()
        return cur

    def _night(self, now: float) -> None:
        """Night mode: lower the brightness between start and end (checked every 20 s)."""
        if now - self._night_checked < 20:
            return
        self._night_checked = now
        n = self.display()["night"]
        active = False
        if n.get("enabled"):
            from datetime import datetime

            hm = datetime.now().strftime("%H:%M")
            a, b = str(n.get("start", "23:00")), str(n.get("end", "07:00"))
            active = (a <= hm < b) if a <= b else (hm >= a or hm < b)
        if active != self._night_active:
            self._night_active = active
            level = int(n.get("brightness", 10)) if active else int(self.store.get("brightness", 60))
            self.device.set_brightness(level)
            self.changed()

    # ========================================================== calibration
    def set_calibration(self, c: PanelCalibration) -> None:
        self.calibration = c
        self.store.set("calibration", c.model_dump())
        self._device_frame = None
        for s in self.slots.values():
            s.clip_key = None  # re-bake clips through the new calibration
        self._wake.set()
        self.changed()

    def show_pattern(self, name: str, seconds: float = 600.0) -> None:
        self.take_back()
        self.pattern = (name, calibration_pattern(name, self.calibration), time.monotonic() + seconds)
        self._device_frame = None
        self._wake.set()
        self.changed()

    def clear_pattern(self) -> None:
        if self.pattern:
            self.pattern = (self.pattern[0], self.pattern[1], 0.0)
        self._wake.set()

    # device-level settings
    def set_brightness(self, level: int) -> None:
        level = max(5, min(100, int(level)))
        self.store.set("brightness", level)
        self.device.set_brightness(level)
        self.changed()

    def set_power(self, on: bool) -> None:
        self.store.set("power", on)
        self.device.set_power(on)
        self._device_frame = None
        for s in self.slots.values():  # re-assert clips / firmware modes when the screen returns
            s.gif_sent = None
            s.native_sent = None
        self._wake.set()
        self.changed()

    def set_flip(self, on: bool) -> None:
        self.store.set("flip", on)
        self.device.command(P.flip(on))
        self.changed()

    # ================================================================= state
    def snapshot(self) -> dict[str, Any]:
        s = self.current
        items = self._playlist_items()
        pl_cur = items[self.pl_index % len(items)] if items else None
        remaining = None
        if pl_cur and self.mode == "playlist" and self.playlist.enabled and not self.focus_key:
            remaining = max(0.0, pl_cur.duration - (time.monotonic() - self.pl_started))
        return {
            "device": self.device.info.model_dump(),
            "engine": {
                "mode": self.mode,
                "current": {
                    "key": s.key,
                    "app": s.app.id,
                    "item": s.item_id,
                    "kind": s.app.kind(),
                    "error": s.error,
                    "baking": s.baking is not None,
                    "status": _safe_status(s.app),
                }
                if s
                else None,
                "focus": self.focus_key,
                "playlist": {
                    **self.playlist.model_dump(mode="json"),
                    "index": self.pl_index,
                    "current_item": pl_cur.id if pl_cur else None,
                    "remaining": remaining,
                },
                "overlay": self.overlay.n.model_dump() if self.overlay else None,
                "pattern": self.pattern[0] if self.pattern else None,
                "released": self.released,
                "active_preset": self.store.get("active_preset") if self.mode == "playlist" else None,
                "preset": self._preset_info() if self.mode == "playlist" else None,
                "autopilot": {**self.autopilot(), "active": self.auto_rule},
                "queued_notices": len(self.notices),
                "render_ms": self.render_ms,
                "takeover": self.takeover,
                "onair": dict(self.onair),
                "eyebreak": self._eyebreak_state(time.monotonic()),
                "indicators": self.indicators_json(),
                "custom": self.hub.get("custom").listing(),  # type: ignore[attr-defined]
            },
            "settings": {
                "brightness": self.store.get("brightness", 60),
                "power": self.store.get("power", True),
                "flip": self.store.get("flip", False),
                "transition": self.store.get("transition", "push"),
                "units": self.store.get("units", "metric"),
                "location": self.store.get("location") or {},
                "audio_source": self.store.get("audio_source", "system"),
                "os_notifications": self.os_notifications(),
                "display": self.display(),
                "night_active": self._night_active,
                "calibration": self.calibration.model_dump(),
                "integrations": self.integrations(),
            },
            "apps": {
                aid: redact_secrets(
                    REGISTRY[aid], self.base_settings(aid) or REGISTRY[aid].Settings().model_dump(mode="json")
                )
                for aid in REGISTRY
            },
            "providers": {n: p.snapshot() for n, p in self.hub.providers.items()},
        }


SECRET_MASK = "••••••"


def secret_fields(cls: type[App]) -> tuple[str, ...]:
    """Settings fields marked `format: "password"` (tokens, API keys, passwords)."""
    out = []
    for name, field in cls.Settings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get("format") == "password":
            out.append(name)
    return tuple(out)


def redact_secrets(cls: type[App], data: dict[str, Any]) -> dict[str, Any]:
    """Settings as sent to the studio / API: secrets that are set become SECRET_MASK, never the value."""
    fields = secret_fields(cls)
    if not fields:
        return data
    return {k: (SECRET_MASK if k in fields and v else v) for k, v in data.items()}


def strip_masked(cls: type[App], patch: dict[str, Any]) -> dict[str, Any]:
    """Drop masked secrets coming back from the studio so the stored value is kept ("" still clears)."""
    fields = secret_fields(cls)
    return {k: v for k, v in patch.items() if not (k in fields and v == SECRET_MASK)}


HANDOFF_DEFAULT: dict[str, Any] = {
    "on_exit": True,  # hand off when the engine stops (Ctrl+C, closing the terminal, service stop)
    "on_sleep": True,  # hand off when the computer goes to sleep (Windows)
    "mode": "clock",  # clock | app | last
    "app": "clock",  # for mode "app": which app to bake into a looping GIF
    "seconds": 8,  # loop length for stream apps baked in "app" mode
    "clock_style": 0,  # firmware clock face 0..7
    "hour24": True,
    "color": "#f94a18",
}

NTFY_COLORS = {1: "#8c8ca0", 2: "#288cff", 3: "#00dcff", 4: "#ffaa00", 5: "#ff143c"}  # by priority
_SAME = ("bell", "info", "warn", "ok", "error", "mail", "chat", "heart", "home", "bolt", "drop", "temp")
NTFY_ICONS = {  # ntfy tag (emoji short code or DotDeck icon name) -> overlay icon
    **{name: name for name in (*_SAME, "sun", "bulb", "battery", "door", "lock", "fire", "star", "eye")},
    "warning": "warn",
    "rotating_light": "error",
    "x": "error",
    "no_entry": "error",
    "skull": "error",
    "white_check_mark": "ok",
    "heavy_check_mark": "ok",
    "tada": "ok",
    "envelope": "mail",
    "email": "mail",
    "speech_balloon": "chat",
    "house": "home",
    "zap": "bolt",
    "droplet": "drop",
    "thermometer": "temp",
    "sunny": "sun",
    "alarm_clock": "clock",
    "eyes": "eye",
    "camera": "cam",
    "microphone": "mic",
    "musical_note": "music",
    "loudspeaker": "bell",
}

APP_STYLE = {  # OS notification source -> (colour, overlay icon)
    "Teams": ("#8c7bff", "chat"),
    "WhatsApp": ("#25d366", "chat"),
    "Discord": ("#5865f2", "chat"),
    "Slack": ("#ff2d95", "chat"),
    "Telegram": ("#2aa3ef", "chat"),
    "Messages": ("#34c759", "chat"),
    "Outlook": ("#1f8fff", "mail"),
    "Mail": ("#1f8fff", "mail"),
    "Gmail": ("#ff3b30", "mail"),
    "Chrome": ("#ffcc00", "bell"),
    "Edge": ("#27d0ff", "bell"),
    "Firefox": ("#ff8a00", "bell"),
    "Calendar": ("#ff453a", "bell"),
    "Security": ("#ff143c", "warn"),
    "Spotify": ("#1ed760", "heart"),
    "Instagram": ("#ff2d78", "heart"),
    "Zoom": ("#2d8cff", "chat"),
}

DEFAULT_RULES: list[dict[str, Any]] = [
    {"match": "spotify", "app": "nowplaying", "settings": {}},
    {"match": "code", "app": "activeapp", "settings": {}},
    {"match": "title:youtube", "app": "mirror", "settings": {"mode": "window"}},
]


def _led_hex(color: str, alt: str) -> str:
    from ..apps.scores import led_team_color
    from ..gfx import to_hex

    return to_hex(led_team_color(color, alt))


def _valid_without(cls: type[App], base: dict[str, Any], patch: dict[str, Any], key: str) -> bool:
    trial = {k: v for k, v in base.items() if k != key}
    try:
        cls.Settings.model_validate({**trial, **patch})
        return True
    except ValidationError:
        return False


def _safe_status(app: App) -> dict[str, Any]:
    try:
        return app.status()
    except Exception as e:
        return {"error": str(e)}


def _error_frame() -> Frame:
    f = Frame()
    f.rect(0, 0, 32, 32, (40, 0, 8), fill=False)
    f.text_center(10, "APP", (255, 30, 60), font="small")
    f.text_center(19, "ERROR", (255, 30, 60))
    return f
