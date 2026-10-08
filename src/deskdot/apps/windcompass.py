"""Wind Compass — wind speed, gusts and direction on a compass, plus the next 12 hours (Open-Meteo).

The arrow points where the wind blows *to* (a north wind points south), the ring is coloured by the Beaufort
force, and the caption names it ("BREEZE", "GALE"…; the unit (km/h or mph) follows Settings). Units follow Settings → units (km/h or mph).
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, measure, mix, scale
from ..gfx.color import RGB
from . import _feed
from ._kit import MUTE, label

POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
#: Beaufort upper bounds in km/h with a short name and colour
BEAUFORT: tuple[tuple[float, str, RGB], ...] = (
    (2, "CALM", (120, 120, 150)),
    (12, "LIGHT", (0, 220, 160)),
    (29, "BREEZE", (0, 230, 90)),
    (39, "FRESH", (140, 255, 0)),
    (50, "STRONG", (255, 214, 0)),
    (62, "GUSTY", (255, 140, 0)),
    (89, "GALE", (255, 40, 40)),
    (999, "STORM", (255, 0, 190)),
)


def beaufort(kmh: float) -> tuple[str, RGB]:
    return next((name, c) for top, name, c in BEAUFORT if kmh < top)


def compass_point(deg: float) -> str:
    return POINTS[round(deg / 45) % 8]


class WindSettings(AppSettings):
    layout: str = Choice("compass", {"compass": "Compass", "hours": "Next 12 hours"}, title="Layout")
    arrow: str = Choice(
        "to", {"to": "Points where it blows to", "from": "Points where it comes from"}, title="Arrow"
    )
    hours: int = Field(12, ge=6, le=12, title="Hours ahead")


@register
class WindCompass(App):
    id = "windcompass"
    name = "Wind Compass"
    description = (
        "Wind speed, gusts and direction on a compass with its Beaufort name, and the next 12 hours."
    )
    icon = "wind"
    category = "data"
    Settings = WindSettings
    fps = 4.0
    uses = ("hourly",)

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "hourly")
        d = _feed.value_or_state(f, t, p, "WIND", PALETTE["mint"])
        if d is None:
            return
        if self.settings.layout == "hours":
            self._hours(f, t, d)
        else:
            self._compass(f, t, d)
        _feed.stale_dot(f, p)

    def _kmh(self, d: dict[str, Any], v: float) -> float:
        return v * 1.609 if d.get("unit_speed") == "MPH" else v

    def _compass(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        now = d.get("now") or {}
        speed, deg, gust = now.get("wind") or 0.0, now.get("dir") or 0.0, now.get("gust")
        _name, c = beaufort(self._kmh(d, speed))
        cx, cy, r = 15.5, 15.5, 14.5
        for i in range(64):  # the dial: dim ring, cardinal ticks brighter
            a = i / 64 * 2 * math.pi
            x, y = round(cx + r * math.sin(a)), round(cy - r * math.cos(a))
            f.set(x, y, scale(c, 0.7 if i % 16 == 0 else 0.22))
        f.text(14, 0, "N", PALETTE["white"])
        to = (deg + (180 if self.settings.arrow == "to" else 0)) % 360
        wob = math.sin(t * 3) * 3 * min(1.0, (gust or speed) / max(1.0, speed) - 1) if speed else 0.0
        a = math.radians(to + wob)
        # a pointer on the dial (not a needle through the middle): the numbers and the name stay clear
        for rr in (8.5, 9.5, 10.5, 11.5):
            f.set(round(cx + rr * math.sin(a)), round(cy - rr * math.cos(a)), scale(c, 0.4 + rr / 20))
        tx, ty = cx + 12.5 * math.sin(a), cy - 12.5 * math.cos(a)
        for side in (-0.5, 0.5):  # arrow head
            f.line(
                round(tx),
                round(ty),
                round(tx - 3.5 * math.sin(a + side)),
                round(ty + 3.5 * math.cos(a + side)),
                c,
            )
        f.set(round(tx), round(ty), mix(c, PALETTE["white"], 0.5))
        txt = f"{speed:.0f}"
        f.text(16 - measure(txt, "small") // 2, 13, txt, PALETTE["white"], "small")
        f.text(1, 26, compass_point(deg), MUTE)
        if gust:
            f.text_right(30, 26, f"G{gust:.0f}", PALETTE["amber"])

    def _hours(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        hours = (d.get("hours") or [])[: self.settings.hours]
        f.text(1, 1, "WIND", PALETTE["mint"])
        if not hours:
            return
        top = max(max(h["gust"] or h["wind"] or 0 for h in hours), 10.0)
        base, tall = 23, 15
        bw = 24 // len(hours)
        x0 = (32 - bw * len(hours)) // 2
        for i, h in enumerate(hours):
            w, g = h["wind"] or 0.0, h["gust"] or 0.0
            _n, c = beaufort(self._kmh(d, w))
            bh = max(1, round(w / top * tall))
            f.rect(x0 + i * bw, base - bh + 1, max(1, bw - 1), bh, c)
            if g > w:
                gy = base - round(g / top * tall) + 1
                f.hline(x0 + i * bw, gy, max(1, bw - 1), PALETTE["white"])
        peak = max(hours, key=lambda h: h["gust"] or h["wind"] or 0)
        label(f, 26, f"G{(peak['gust'] or peak['wind'] or 0):.0f} {peak['h']:02d}H", PALETTE["amber"])

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "hourly")
        now = ((p.value if p is not None else None) or {}).get("now") or {}
        return {"wind": now.get("wind"), "gust": now.get("gust"), "dir": now.get("dir")}
