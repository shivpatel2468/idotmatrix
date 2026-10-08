"""Earth Events — wildfires, storms, volcanoes and ice happening now, on a world map (NASA EONET, no key).

Each open event is a blinking dot in its category's colour; the caption scrolls the newest one. The "counts"
layout lists how many of each kind are open.
"""

from __future__ import annotations

import math
import time
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, scale
from ..gfx.color import RGB
from ..gfx.worldmap import draw_world, project
from ..providers.earthevents import CATEGORIES
from . import _feed
from ._kit import empty, label

COLORS: dict[str, RGB] = {
    "wildfires": (255, 90, 0),
    "severeStorms": (0, 200, 255),
    "volcanoes": (255, 0, 120),
    "seaLakeIce": (200, 230, 255),
    "floods": (40, 110, 255),
    "dustHaze": (210, 170, 90),
    "earthquakes": (255, 214, 0),
    "landslides": (170, 110, 60),
    "drought": (255, 170, 0),
    "snow": (230, 230, 255),
    "tempExtremes": (255, 40, 40),
}
FILTERS = {
    "all": "All events",
    "wildfires": "Wildfires",
    "severeStorms": "Storms",
    "volcanoes": "Volcanoes",
    "seaLakeIce": "Sea & lake ice",
}
SHORT = {
    "all": "NO EVENTS",
    "wildfires": "NO FIRES",
    "severeStorms": "NO STORMS",
    "volcanoes": "NO VOLC.",
    "seaLakeIce": "NO ICE",
}
LAND: RGB = (40, 70, 52)


def color_of(cat: str) -> RGB:
    return COLORS.get(cat, PALETTE["mute"])


class EarthEventsSettings(AppSettings):
    layout: str = Choice("map", {"map": "World map", "counts": "Counts by kind"}, title="Layout")
    show: str = Choice("all", FILTERS, title="Show")
    days: int = Field(30, ge=3, le=90, title="Started within (days)")


@register
class EarthEvents(App):
    id = "earthevents"
    name = "Earth Events"
    description = (
        "Wildfires, storms, volcanoes and sea ice happening now, as dots on a world map (NASA EONET)."
    )
    icon = "earth"
    category = "data"
    Settings = EarthEventsSettings
    fps = 4.0
    uses = ("earthevents",)

    def on_start(self) -> None:
        p = _feed.provider(self.ctx, "earthevents")
        if p is not None:
            p.want(self.settings.days)

    def on_settings(self) -> None:
        self.on_start()

    def _events(self, d: dict[str, Any]) -> list[dict[str, Any]]:
        ev = d.get("events") or []
        cut = time.time() - self.settings.days * 86400
        ev = [e for e in ev if e["date"] >= cut or self.settings.days >= 30]
        if self.settings.show != "all":
            ev = [e for e in ev if e["category"] == self.settings.show]
        return ev

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "earthevents")
        d = _feed.value_or_state(f, t, p, "EARTH", PALETTE["mint"])
        if d is None:
            return
        ev = self._events(d)
        if not ev:
            empty(f, "CALM", SHORT[self.settings.show])
            return
        if self.settings.layout == "counts":
            self._counts(f, ev)
        else:
            self._map(f, t, ev)
        _feed.stale_dot(f, p)

    def _map(self, f: Frame, t: float, ev: list[dict[str, Any]]) -> None:
        y0 = 2
        draw_world(f, LAND, None, y=y0)
        focus = ev[int(t // 6) % min(len(ev), 8)]  # the caption walks the 8 newest
        for e in reversed(ev):
            x, y = project(e["lat"], e["lon"])
            px, py = min(31, int(x)), y0 + min(15, int(y))
            c = color_of(e["category"])
            if e is focus:
                k = 0.5 + 0.5 * math.sin(t * 6)
                f.set(px, py, PALETTE["white"] if k > 0.5 else c)
            else:
                f.set(px, py, scale(c, 0.8))
        c = color_of(focus["category"])
        f.text(1, 20, focus["label"], c)
        label(f, 26, focus["title"], PALETTE["white"], t)

    def _counts(self, f: Frame, ev: list[dict[str, Any]]) -> None:
        counts: dict[str, int] = {}
        for e in ev:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
        rows = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
        top = max(n for _c, n in rows)
        for i, (cat, n) in enumerate(rows):
            y = 1 + i * 6
            c = color_of(cat)
            f.text(1, y, CATEGORIES.get(cat, "EVENT")[:7], c)
            f.text_right(30, y, str(n), PALETTE["white"])
            w = max(1, round(n / top * 6))
            f.hline(30 - 13 - w + 1, y + 2, w, scale(c, 0.6))

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "earthevents")
        d = (p.value if p is not None else None) or {}
        return {"open": len(d.get("events") or []), "counts": d.get("counts")}
