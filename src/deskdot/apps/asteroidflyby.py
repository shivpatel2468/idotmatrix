"""Asteroid Flyby — the next asteroid to pass within 10 Moon-distances of Earth (NASA/JPL, no key).

A to-scale strip shows Earth, the Moon's distance and where the rock will pass; the caption scrolls its name,
size estimate and speed. "LD" = lunar distance (384 400 km). Nothing here is dangerous: these are routine.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, measure, scale
from ..gfx.color import RGB
from . import _feed
from ._kit import MUTE, empty, label

ROCK: RGB = (255, 170, 60)
EARTH: RGB = (40, 140, 255)
MOON: RGB = (200, 200, 215)


def size_text(size: tuple[float, float] | None) -> str:
    if not size:
        return ""
    lo, hi = size
    if hi >= 1000:
        return f"{lo / 1000:.1f}-{hi / 1000:.1f}KM"
    return f"{lo:.0f}-{hi:.0f}M"


class AsteroidSettings(AppSettings):
    pick: str = Choice("next", {"next": "Next to pass", "closest": "Closest in 60 days"}, title="Show")
    max_ld: int = Field(10, ge=1, le=10, title="Within (lunar distances)")


@register
class AsteroidFlyby(App):
    id = "asteroidflyby"
    name = "Asteroid Flyby"
    description = (
        "The next asteroid to pass Earth within 10 Moon distances: when, how close, how big, how fast."
    )
    icon = "orbit"
    category = "data"
    Settings = AsteroidSettings
    fps = 4.0
    uses = ("asteroids",)

    def _pick(self, d: dict[str, Any]) -> dict[str, Any] | None:
        now = time.time()
        rocks = [a for a in d.get("approaches") or [] if a["dist_ld"] <= self.settings.max_ld]
        later = [a for a in rocks if a["time"] >= now - 3600]
        if not later:
            return None
        if self.settings.pick == "closest":
            return min(later, key=lambda a: a["dist_ld"])
        return later[0]

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "asteroids")
        d = _feed.value_or_state(f, t, p, "ASTEROID", ROCK)
        if d is None:
            return
        a = self._pick(d)
        if a is None:
            empty(f, "ALL CLEAR", f"< {self.settings.max_ld} LD")
            return
        dt_s = a["time"] - time.time()
        label(f, 1, "NOW" if abs(dt_s) < 3600 else f"IN {_feed.until(dt_s)}", ROCK)
        ld = a["dist_ld"]
        txt = f"{ld:.1f}" if ld < 10 else f"{ld:.0f}"
        w = measure(txt, "big")
        x = (32 - w - 10) // 2
        f.text(x, 8, txt, PALETTE["white"], "big")
        f.text(x + w + 2, 13, "LD", MUTE)
        # to scale: 3 px per lunar distance (10 LD = 30 px); Earth at x 1, the Moon's orbit at x 4
        y = 21
        f.hline(1, y, 30, (24, 24, 34))
        f.rect(0, y - 1, 2, 3, EARTH)
        f.set(4, y, MOON)
        rx = min(30, 1 + round(ld * 3))
        k = 0.6 + 0.4 * abs(((t * 1.2) % 2) - 1)
        f.set(rx, y, scale(ROCK, k))
        f.set(rx, y - 1, scale(ROCK, k * 0.5))
        cap = " ".join(
            x
            for x in (
                a["name"],
                size_text(a.get("size_m")),
                f"{a['speed']:.0f}KM/S" if a.get("speed") else "",
            )
            if x
        )
        label(f, 26, cap, MUTE, t)
        _feed.stale_dot(f, p)

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "asteroids")
        d = (p.value if p is not None else None) or {}
        a = self._pick(d) if d else None
        return {"name": a["name"], "ld": round(a["dist_ld"], 2), "time": a["time"]} if a else {}
