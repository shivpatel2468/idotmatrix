"""Media server — the latest additions to Plex or Jellyfin as posters, and who's streaming now.

Layouts: ``poster`` (full-bleed cover of each new item with a caption marquee), ``shelf`` (the three newest
posters side by side, the current one lit, title + detail underneath) and ``streams`` (now-streaming
sessions). Posters are calibrated once by the provider, never per frame.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, scale
from ..gfx.color import RGB
from ._kit import loading
from ._radiator import WHITE, glyph, offline_screen, page_dots, provider, setup_screen

ACCENT: RGB = PALETTE["gold"]
KIND_COLORS: dict[str, RGB] = {"MOVIE": PALETTE["gold"], "TV": PALETTE["sky"], "MUSIC": PALETTE["magenta"]}


class MediaServerSettings(AppSettings):
    server: str = Choice("plex", {"plex": "Plex", "jellyfin": "Jellyfin"}, title="Server", group="Connection")
    host: str = Field(
        "",
        max_length=120,
        title="Host",
        description="e.g. 192.168.1.20 (blank = not set up)",
        json_schema_extra={"group": "Connection"},
    )
    port: int = Field(
        0,
        ge=0,
        le=65535,
        title="Port",
        description="0 = default (Plex 32400, Jellyfin 8096)",
        json_schema_extra={"group": "Connection"},
    )
    token: str = Field(
        "",
        max_length=200,
        title="Token / API key",
        description="Plex: X-Plex-Token. Jellyfin: Dashboard → API Keys. Sent as a header, never logged.",
        json_schema_extra={"group": "Connection", "format": "password", "writeOnly": True},
    )
    user: str = Field(
        "",
        max_length=60,
        title="Jellyfin user",
        description="Blank = the first user",
        json_schema_extra={"group": "Connection"},
    )
    layout: str = Choice(
        "poster",
        {"poster": "Poster", "shelf": "Shelf", "streams": "Now streaming"},
        title="Layout",
        group="Display",
    )
    rotate: int = Field(8, ge=3, le=60, title="Seconds per item", json_schema_extra={"group": "Display"})
    sessions: bool = Field(
        True,
        title="Show now-streaming count",
        description="Polls sessions every minute",
        json_schema_extra={"group": "Display"},
    )


#: marquee px/s = the stream's frame rate, so titles move exactly 1 px per frame (12 px/s at 8 fps hopped 1-2 px)
MARQUEE = 8.0
TRACK = (56, 56, 72)  # progress track: PALETTE "shade" is black through the panel gamma


def _marquee(f: Frame, text: str, t: float, y: int, color: tuple[int, int, int]) -> None:
    # half a frame in keeps int(phase * speed) exact (float error otherwise repeats a position, then skips one)
    draw_marquee(f, text, t + 0.5 / MARQUEE, 1, y, 30, color, speed=MARQUEE)


@register
class MediaServer(App):
    id = "mediaserver"
    name = "Media Server"
    description = "Latest Plex or Jellyfin additions as posters, plus who's streaming now."
    icon = "clapperboard"
    category = "media"
    Settings = MediaServerSettings
    fps = MARQUEE
    uses = ("mediaserver",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.on_settings()

    def on_start(self) -> None:
        p = provider(self.ctx, "mediaserver")
        if p is not None and hasattr(p, "configure"):
            s = self.settings
            p.configure(
                s.server, s.host, s.port, s.token, s.user, sessions=s.sessions or s.layout == "streams"
            )

    def on_settings(self) -> None:
        self.on_start()

    def _value(self) -> tuple[Any, dict[str, Any] | None]:
        p = provider(self.ctx, "mediaserver")
        return p, (p.value if p is not None else None)

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        p, v = self._value()
        s = self.settings
        label = "PLEX" if s.server == "plex" else "JELLYFIN"
        if not s.host.strip() or not s.token:
            setup_screen(f, t, "media", label, "SET HOST" if not s.host.strip() else "SET KEY", ACCENT)
            return
        if v is None:
            if p is not None and p.error:
                offline_screen(f, "media", label, "OFFLINE")
            else:
                loading(f, t, label, ACCENT)
            return
        if v.get("state") == "auth":
            offline_screen(f, "media", label, "BAD KEY")
            return
        items, sessions = v.get("items") or [], v.get("sessions") or []
        if s.layout == "streams":
            self._streams(f, t, sessions)
        elif not items:
            setup_screen(f, t, "media", label, "NOTHING", PALETTE["mute"])
        elif s.layout == "shelf":
            self._shelf(f, t, items, sessions)
        else:
            self._poster(f, t, items, sessions)
        if p is not None and p.error:
            f.set(0, 31, PALETTE["amber"])

    def _now_badge(self, f: Frame, sessions: list[dict[str, Any]], t: float) -> None:
        """'▶2' in the top-right corner while anyone is streaming."""
        if not self.settings.sessions or not sessions:
            return
        n = str(min(9, len(sessions)))
        w = 4 + measure(n)
        x = 31 - w
        f.rect(x - 1, 0, w + 2, 7, (0, 0, 0))
        c = PALETTE["ok"]
        for i in range(3):  # a 3×5 play triangle
            f.vline(x + i, 1 + i, 5 - 2 * i, c)
        f.text(x + 4, 1, n, WHITE)

    def _placeholder_art(self, f: Frame, x: int, y: int, w: int, h: int, item: dict[str, Any]) -> None:
        c = KIND_COLORS.get(item.get("kind", ""), PALETTE["mute"])
        f.rect(x, y, w, h, scale(c, 0.25))
        f.rect(x, y, w, h, scale(c, 0.6), fill=False)

    # poster: full-bleed cover + caption band -----------------------------------------------------
    def _poster(
        self, f: Frame, t: float, items: list[dict[str, Any]], sessions: list[dict[str, Any]]
    ) -> None:
        n = len(items)
        i = int(t // self.settings.rotate) % n
        it = items[i]
        tr = t % self.settings.rotate
        cover = it.get("cover")
        if isinstance(cover, np.ndarray) and cover.shape == (32, 32, 3):
            f.blit(cover)
            f.px[21:] = (f.px[21:].astype(np.uint16) * 46 // 255).astype(
                np.uint8
            )  # darken caption band ×0.18
        else:
            self._placeholder_art(f, 0, 0, 32, 21, it)
            g = glyph("media", KIND_COLORS.get(it.get("kind", ""), PALETTE["mute"]))
            f.sprite(g, (32 - g.w) // 2, 6)
        kc = KIND_COLORS.get(it.get("kind", ""), ACCENT)
        _marquee(f, it.get("title") or "?", tr, 23, WHITE)
        # 1 px progress through this item's slot, in the kind's colour
        f.hline(0, 31, round(32 * tr / self.settings.rotate), scale(kc, 0.8))
        self._now_badge(f, sessions, t)

    # shelf: three posters, the current one lit ---------------------------------------------------
    def _shelf(self, f: Frame, t: float, items: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> None:
        shelf = items[:3]
        i = int(t // self.settings.rotate) % len(shelf)
        tr = t % self.settings.rotate
        for k, it in enumerate(shelf):
            x = k * 11
            thumb = it.get("thumb")
            if isinstance(thumb, np.ndarray) and thumb.shape == (15, 10, 3):
                f.blit(thumb if k == i else (thumb.astype(np.uint16) * 90 // 255).astype(np.uint8), x, 0)
            else:
                self._placeholder_art(f, x, 0, 10, 15, it)
            if k == i:
                f.hline(x, 16, 10, KIND_COLORS.get(it.get("kind", ""), ACCENT))
        it = shelf[i]
        _marquee(f, it.get("title") or "?", tr, 19, WHITE)
        sub = it.get("sub") or it.get("kind") or ""
        kc = KIND_COLORS.get(it.get("kind", ""), ACCENT)
        _marquee(f, sub, tr, 26, scale(kc, 0.9))
        self._now_badge(f, sessions, t)

    # streams: who's watching -------------------------------------------------------------------
    def _streams(self, f: Frame, t: float, sessions: list[dict[str, Any]]) -> None:
        if not sessions:
            g = glyph("media", PALETTE["mute"])
            f.sprite(g, (32 - g.w) // 2, 4)
            f.text_center(16, "NOBODY", PALETTE["mute"])
            f.text_center(24, "WATCHING", PALETTE["mute"])
            return
        per = 2
        pages = -(-len(sessions) // per)
        pg = int(t // self.settings.rotate) % pages
        tr = t % self.settings.rotate
        f.text(1, 1, "NOW", PALETTE["ok"])
        f.text_right(30, 1, str(len(sessions)), WHITE)
        for k, s in enumerate(sessions[pg * per : pg * per + per]):
            y = 8 + k * 12
            paused = s.get("state") == "paused"
            c = PALETTE["amber"] if paused else PALETTE["ok"]
            _marquee(f, s.get("title") or "?", tr, y, WHITE)
            f.text(1, y + 6, (s.get("user") or "?")[:5], c)
            prog = s.get("progress")
            if prog is not None:
                f.bar(22, y + 8, 9, 1, float(prog), c, track=TRACK)
        page_dots(f, pages, pg)

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        _p, v = self._value()
        v = v or {}
        items = v.get("items") or []
        return {
            "server": self.settings.server,
            "latest": [i.get("title") for i in items[:3]],
            "streaming": len(v.get("sessions") or []),
            "token": "set" if self.settings.token else "",
        }
