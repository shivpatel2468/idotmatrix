"""OBS status — LIVE / REC badges with elapsed time, the program scene and dropped frames.

Talks to OBS Studio's built-in obs-websocket v5 server (Tools → WebSocket Server Settings). With OBS closed
the panel shows a calm "OBS OFF" idle screen and the provider retries quietly with backoff. Optionally the
app takes over the playlist while you're live or recording.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale
from ..gfx.color import RGB
from ..platforms import FEATURES
from ..providers.radiator import panel_text
from ._kit import loading, unsupported
from ._radiator import WHITE, fmt_clock, glyph, offline_screen, provider, setup_screen

LIVE: RGB = PALETTE["red"]
REC: RGB = PALETTE["rose"]
PAUSE: RGB = PALETTE["amber"]
SCENE: RGB = PALETTE["cyan"]
IDLE: RGB = PALETTE["mute"]
SPEED = 8.0  # marquee px/s: 1 px per streamed frame at fps 8 (12 px/s at 2 fps jumped 6 px)


class OBSSettings(AppSettings):
    host: str = Field(
        "127.0.0.1",
        max_length=120,
        title="Host",
        description="Machine running OBS",
        json_schema_extra={"group": "Connection"},
    )
    port: int = Field(4455, ge=1, le=65535, title="Port", json_schema_extra={"group": "Connection"})
    password: str = Field(
        "",
        max_length=120,
        title="Password",
        description="OBS → Tools → WebSocket Server Settings → Show Connect Info. Never logged.",
        json_schema_extra={"group": "Connection", "format": "password", "writeOnly": True},
    )
    layout: str = Choice(
        "timer", {"timer": "Timer hero", "scene": "Scene hero"}, title="Layout", group="Display"
    )
    show_drops: bool = Field(True, title="Dropped frames", json_schema_extra={"group": "Display"})
    takeover: bool = Field(
        True, title="Take over the playlist while live or recording", json_schema_extra={"group": "Display"}
    )


def fmt_hero(seconds: float) -> str:
    """MM:SS (fits `big` exactly); callers switch to small H:MM:SS after an hour."""
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def fmt_bytes(n: int) -> str:
    for unit, k in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= k:
            v = n / k
            return f"{v:.1f}{unit}" if v < 10 else f"{v:.0f}{unit}"
    return f"{n}B"


def lamp(f: Frame, x: int, y: int, text: str, color: RGB, t: float, blink: bool) -> int:
    """An on-air lamp: a 2×3 dot (blinking when live) and the word in the same colour. Returns the end x."""
    on = not blink or int(t * 2) % 2 == 0
    f.rect(x, y + 1, 2, 3, color if on else scale(color, 0.25))
    return f.text(x + 3, y, text, color)


@register
class OBS(App):
    id = "obs"
    name = "OBS Status"
    description = "LIVE/REC badges with elapsed time, current scene and dropped frames from OBS Studio."
    icon = "radio"
    category = "productivity"
    Settings = OBSSettings
    fps = 8.0  # marquees move 1 px per frame; static screens are deduped, so rest costs nothing
    uses = ("obs",)
    platforms = FEATURES["lan"]  # obs-websocket is a plain ws:// socket on your computer / LAN
    web_reason = (
        "OBS talks over a plain ws:// WebSocket on your computer, which an https page may not open; "
        "use the desktop, Raspberry Pi or Android app."
    )

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.on_settings()

    def on_start(self) -> None:
        p = provider(self.ctx, "obs")
        if p is not None and hasattr(p, "configure"):
            s = self.settings
            p.configure(s.host, s.port, s.password)

    def on_settings(self) -> None:
        self.on_start()

    def _value(self) -> tuple[Any, dict[str, Any] | None]:
        p = provider(self.ctx, "obs")
        return p, (p.value if p is not None else None)

    def watches_focus(self) -> bool:
        return self.settings.takeover

    def wants_focus(self) -> bool:
        _p, v = self._value()
        return bool(
            self.settings.takeover
            and v
            and v.get("state") == "on"
            and (v.get("streaming") or v.get("recording"))
        )

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        if not self.supported_here():
            unsupported(f, "OBS")
            return
        _p, v = self._value()
        if not self.settings.host.strip():
            setup_screen(f, t, "obs", "OBS", "SET HOST", IDLE)
            return
        if v is None:
            loading(f, t, "OBS", SCENE)
            return
        state = v.get("state")
        if state == "auth":
            offline_screen(f, "obs", "OBS", "AUTH ERR")
            return
        if state != "on":
            self._off(f, t)
            return
        if v.get("streaming") or v.get("recording"):
            (self._timer if self.settings.layout == "timer" else self._scene_hero)(f, t, v)
        else:
            self._ready(f, t, v)

    def _off(self, f: Frame, t: float) -> None:
        g = glyph("obs", PALETTE["dim"])
        f.sprite(g, (32 - g.w) // 2, 4)
        f.text_center(16, "OBS", IDLE)
        f.text_center(24, "OFF", PALETTE["dim"])

    def _badges(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        live, rec, paused = v.get("streaming"), v.get("recording"), v.get("paused")
        rc = PAUSE if paused else REC
        if live:
            lamp(f, 1, 1, "LIVE", PAUSE if v.get("reconnecting") else LIVE, t, blink=True)
            if rec:  # the universal round REC lamp on the right
                f.circle(28, 3, 2, rc if paused or int(t * 2 + 1) % 2 == 0 else scale(rc, 0.3))
        elif rec:
            lamp(f, 1, 1, "PAUSED" if paused else "REC", rc, t, blink=not paused)

    def _elapsed(self, v: dict[str, Any]) -> float:
        since = v.get("stream_since") if v.get("streaming") else v.get("rec_since")
        return time.time() - since if since else 0.0

    def _drops(self, f: Frame, y: int, v: dict[str, Any]) -> None:
        skipped, total = int(v.get("skipped") or 0), int(v.get("total") or 0)
        if not v.get("streaming"):
            f.text(1, y, "DISK", PALETTE["dim"])
            f.text_right(30, y, fmt_bytes(int(v.get("rec_bytes") or 0)), PALETTE["mute"])
            return
        pct = skipped / total * 100 if total else 0.0
        c = PALETTE["ok"] if pct < 0.5 else PALETTE["amber"] if pct < 5 else PALETTE["bad"]
        label = f"{pct:.1f}%" if skipped else "0"
        f.text(1, y, "DROP", PALETTE["dim"])
        f.text_right(30, y, label, c)
        cong = max(0.0, min(1.0, float(v.get("congestion") or 0.0)))
        if cong > 0.02:
            f.hline(17, y + 2, max(1, round(cong * 6)), PALETTE["amber"])

    def _timer(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        self._badges(f, t, v)
        secs = self._elapsed(v)
        col = PAUSE if v.get("paused") and not v.get("streaming") else WHITE
        drops = self.settings.show_drops
        top = 9 if drops else 10
        if secs < 3600:
            f.text_center(top, fmt_hero(secs), col, font="big")
        else:  # H:MM:SS in small type (big digits can't fit 7 characters)
            f.text_center(top + 2, fmt_clock(secs), col, font="small")
        scene = panel_text(v.get("scene") or "", 60) or "-"
        draw_marquee(f, scene, t, 1, 20 if drops else 23, 30, SCENE, speed=SPEED)
        if drops:
            self._drops(f, 26, v)

    def _scene_hero(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        self._badges(f, t, v)
        scene = panel_text(v.get("scene") or "", 60) or "-"
        if measure(scene, "small") <= 30:
            f.text_center(10, scene, SCENE, font="small")
        else:
            draw_marquee(f, scene, t, 1, 11, 30, SCENE, speed=SPEED)
        f.text_center(19, fmt_clock(self._elapsed(v)), WHITE)
        if self.settings.show_drops:
            self._drops(f, 26, v)

    def _ready(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        g = glyph("obs", mix(PALETTE["ok"], PALETTE["black"], 0.3))
        f.sprite(g, 1, 1)
        f.text(12, 3, "READY", PALETTE["ok"])
        f.text(1, 13, "SCENE", PALETTE["dim"])
        scene = panel_text(v.get("scene") or "", 60) or "-"
        draw_marquee(f, scene, t, 1, 20, 30, SCENE, speed=SPEED)
        f.text(1, 26, "IDLE", PALETTE["dim"])

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        _p, v = self._value()
        v = v or {}
        return {
            "state": v.get("state", "unset"),
            "live": bool(v.get("streaming")),
            "recording": bool(v.get("recording")),
            "scene": v.get("scene") or None,
            "elapsed_s": round(self._elapsed(v)) if v.get("streaming") or v.get("recording") else None,
            "dropped": v.get("skipped"),
            "host": f"{self.settings.host}:{self.settings.port}",
            "password": "set" if self.settings.password else "",
        }
