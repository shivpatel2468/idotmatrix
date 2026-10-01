"""Planets — which naked-eye planets are up now (or tonight) at your location, on a sky dome or as a list.

Layouts: ``dome`` (the whole sky as a circle: horizon ring, north up and east left as you'd see it lying on
your back; planets as coloured dots, one labelled at a time) and ``list`` (Mercury…Saturn with altitude when up,
else the next rise; planets lost in the sun's glare are greyed). ``when``: ``now`` or ``tonight`` (the moment
the sky gets dark, or now if it already is).

Data: the `planets` provider (local JPL-elements ephemeris). Altitudes are recomputed from RA/Dec every frame, so
the dome keeps moving between provider updates.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, mix, scale
from ..gfx.color import RGB
from ..providers.planets import altaz
from ._kit import loading, offline
from .daynight import moon_radec

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
DIM: RGB = PALETTE["dim"]
INFO: dict[str, tuple[str, str, RGB]] = {  # id -> (short, label, colour)
    "mercury": ("ME", "MER", (190, 170, 150)),
    "venus": ("VE", "VEN", (255, 240, 170)),
    "mars": ("MA", "MAR", (255, 80, 30)),
    "jupiter": ("JU", "JUP", (255, 190, 110)),
    "saturn": ("SA", "SAT", (230, 200, 80)),
}
MOON: RGB = (200, 210, 240)
# dome furniture, lifted so the horizon still reads through the panel gamma ((30, 40, 70) was black on the LEDs)
HORIZON: RGB = (60, 76, 120)
RING_45: RGB = (44, 54, 88)
TICK: RGB = (110, 120, 160)


class PlanetsSettings(AppSettings):
    layout: str = Choice("dome", {"dome": "Sky dome", "list": "List"}, title="Layout")
    when: str = Choice("tonight", {"tonight": "Tonight", "now": "Right now"}, title="Sky at")
    show_moon: bool = Field(True, title="Show the moon")
    show_below: bool = Field(False, title="List planets below the horizon", description="List layout.")
    hour24: bool = Field(True, title="24-hour times")
    page_seconds: int = Field(3, ge=2, le=15, title="Seconds per label")


def dome_xy(alt: float, az: float) -> tuple[int, int]:
    """Zenith at the centre, horizon on a radius-14 circle, north up, east left."""
    r = (90.0 - max(0.0, alt)) / 90.0 * 14.0
    a = math.radians(az)
    return round(15 - r * math.sin(a)), round(15 - r * math.cos(a))


@register
class Planets(App):
    id = "planets"
    name = "Planets Tonight"
    description = (
        "Which naked-eye planets are up now or tonight, on a sky dome or a list with rise/set times."
    )
    icon = "orbit"
    category = "data"
    Settings = PlanetsSettings
    fps = 1.0
    uses = ("planets",)

    def _prov(self) -> Any:
        try:
            return self.ctx.provider("planets")
        except KeyError:
            return None

    def when_ts(self, d: dict[str, Any], now: float) -> float:
        if self.settings.when == "now":
            return now
        night = d.get("night")
        if not night:
            return now
        start, end = night
        return now if start <= now <= end else start + 1800  # half an hour into darkness

    def positions(self, d: dict[str, Any], ts: float) -> list[dict[str, Any]]:
        """Planets with alt/az at `ts` (RA/Dec extrapolated from the provider's daily motion)."""
        out = []
        dt = (ts - d["computed"]) / 86400.0
        for p in d["planets"]:
            ra = p["ra"] + p.get("dra", 0.0) * dt
            dec = p["dec"] + p.get("ddec", 0.0) * dt
            alt, az = altaz(ra, dec, ts, d["lat"], d["lon"])
            out.append(p | {"alt_t": float(alt), "az_t": float(az)})
        return out

    def _hm(self, ts: float | None, d: dict[str, Any]) -> str:
        if ts is None:
            return "--:--"
        lt = datetime.fromtimestamp(ts + d.get("tz_offset", 0.0), tz=UTC)
        return lt.strftime("%H:%M") if self.settings.hour24 else f"{lt.hour % 12 or 12}:{lt.minute:02d}"

    def render(self, f: Frame, t: float) -> None:
        p = self._prov()
        d = p.value if p is not None else None
        if d is None:
            if p is None or p.error:
                offline(f, "PLANETS", "NO LOC")
            else:
                loading(f, t, "PLANETS", INFO["jupiter"][2])
            return
        now = time.time()
        ts = self.when_ts(d, now)
        pos = self.positions(d, ts)
        if self.settings.layout == "dome":
            self._dome(f, t, d, ts, pos)
        else:
            self._list(f, t, d, ts, pos)

    # ------------------------------------------------------------------ dome
    def _dome(self, f: Frame, t: float, d: dict[str, Any], ts: float, pos: list[dict[str, Any]]) -> None:
        # the sky: a faint disc, darker towards the horizon, with a ring and cardinal ticks
        sun_alt = d.get("sun_alt", -20.0) if self.settings.when == "now" else -20.0
        sky = (0, 8, 40) if sun_alt > 0 else (4, 4, 22) if sun_alt > -8 else (2, 2, 12)
        f.circle(15, 15, 14, sky)
        f.circle(15, 15, 14, HORIZON, fill=False)
        f.circle(15, 15, 7, RING_45, fill=False)  # 45° altitude
        for x, y in ((15, 1), (15, 29), (1, 15), (29, 15)):
            f.set(x, y, TICK)
        f.set(15, 0, (255, 72, 24))  # north
        up = [p for p in pos if p["alt_t"] > 0]
        if self.settings.show_moon:
            ra, dec = moon_radec(ts)
            malt, maz = altaz(ra, dec, ts, d["lat"], d["lon"])
            if malt > 0:
                mx, my = dome_xy(float(malt), float(maz))
                f.rect(mx, my, 2, 2, MOON)
        dots = []
        for p in up:
            x, y = dome_xy(p["alt_t"], p["az_t"])
            col = INFO[p["id"]][2]
            glare = p["elong"] < 12
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                f.blend(x + dx, y + dy, col, 0.3 if glare else 0.6)  # a small plus: the hero, not a speck
            f.set(x, y, scale(col, 0.4) if glare else col)
            dots.append((x, y))
        if up:
            # label one planet at a time, cycling; the label goes where it hides no other planet
            i = int(t // self.settings.page_seconds) % len(up)
            p = up[i]
            x, y = dots[i]
            short = INFO[p["id"]][0]
            w = 7 if short[0] != "M" else 9
            for lx, ly in ((x + 3, y - 2), (x - w - 2, y - 2), (x - w // 2, y - 7), (x - w // 2, y + 2)):
                box = (lx - 1, ly - 1, lx + w, ly + 5)
                inside = lx >= 1 and lx + w - 1 <= 30 and ly >= 1 and ly + 4 <= 30
                hides = any(
                    box[0] <= ox <= box[2] and box[1] <= oy <= box[3]
                    for j, (ox, oy) in enumerate(dots)
                    if j != i
                )
                if inside and not hides:
                    break
            else:  # nothing fits cleanly: keep the first spot, pulled inside the margins (was cut at the edge)
                lx = max(1, min(31 - w, x + 3 if x < 16 else x - w - 2))
                ly = max(1, min(26, y - 2))
            f.rect(lx - 1, ly - 1, w + 1, 7, (0, 0, 0))
            f.text(lx, ly, short, mix(INFO[p["id"]][2], WHITE, 0.4))
            f.set(x, y, WHITE)
        else:
            f.text_center(11, "NONE", MUTE)
            f.text_center(18, "UP", MUTE)

    # ------------------------------------------------------------------ list
    def _list(self, f: Frame, t: float, d: dict[str, Any], ts: float, pos: list[dict[str, Any]]) -> None:
        """Name in the planet's colour; up: altitude (white) alternating with set time (rose);
        down: rise time (amber); lost in the sun's glare: SUN."""
        page = int(t // self.settings.page_seconds) % 2
        rows = []
        for p in pos:
            label, _, col = INFO[p["id"]]
            glare = p["elong"] < 12
            if p["alt_t"] > 0 and not glare:
                if page and p.get("set"):
                    rows.append((label, self._hm(p["set"], d), col, PALETTE["rose"], True))
                else:
                    rows.append((label, f"{round(p['alt_t'])}°", col, WHITE, True))
            elif glare:
                rows.append((label, "SUN", scale(col, 0.5), scale(MUTE, 0.75), False))
            else:
                nxt = p.get("rise")
                rows.append(
                    (
                        label,
                        self._hm(nxt, d) if nxt else "--",
                        scale(col, 0.5),
                        scale(PALETTE["amber"], 0.8),
                        False,
                    )
                )
        if not self.settings.show_below:
            rows = [r for r in rows if r[4]] or rows
        top = 1 if len(rows) >= 4 else (16 - len(rows) * 3)
        for i, (label, val, col, vcol, _up) in enumerate(rows[:5]):
            y = top + i * 6
            f.vline(1, y + 1, 3, col)
            f.text(3, y, label, col)
            f.text_right(30, y, val, vcol)

    def status(self) -> dict[str, Any]:
        p = self._prov()
        d = p.value if p is not None else None
        if d is None:
            return {}
        now = time.time()
        ts = self.when_ts(d, now)
        return {
            "at": self._hm(ts, d),
            "planets": [
                {
                    "name": q["id"].title(),
                    "altitude": round(q["alt_t"], 1),
                    "azimuth": round(q["az_t"], 1),
                    "elongation": q["elong"],
                    "rise": self._hm(q.get("rise"), d),
                    "set": self._hm(q.get("set"), d),
                    "visible_tonight": q.get("visible_tonight"),
                }
                for q in self.positions(d, ts)
            ],
        }
