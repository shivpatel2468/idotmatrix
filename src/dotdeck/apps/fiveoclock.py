"""Five O'Clock Somewhere — a city where it is 17:xx right now, and two glasses clinking to it.

The city comes from local time-zone data: `zoneinfo` when the machine has an IANA database, otherwise the
built-in table in `providers.tzlite` (every UTC offset is covered, so there is always somewhere). Nothing on
screen depends on the minute, so the whole thing is a baked clip that only re-bakes when the set of 17:xx
cities changes (at most every quarter hour).
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import PALETTE, Frame, measure, mix, scale, to_rgb
from ..gfx.color import RGB
from ..providers.tzlite import CITIES, City, local_time

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
GLASS: RGB = (120, 150, 190)
GLASS_HI: RGB = (200, 225, 255)
FOAM: RGB = (255, 250, 236)
BEER: RGB = (255, 150, 0)
BEER_DK: RGB = (200, 90, 0)
WINE: RGB = (200, 0, 60)
WINE_DK: RGB = (120, 0, 40)
COCKTAIL: RGB = (0, 220, 180)
COCKTAIL_DK: RGB = (0, 130, 120)
CHERRY: RGB = (255, 20, 60)
DRINKS = ("beer", "wine", "cocktail")


def five_oclock_cities(ts: float) -> list[tuple[City, int]]:
    """Cities whose local hour is 17 at `ts`, with the minutes past five, freshest first."""
    out = []
    for c in CITIES:
        lt = local_time(c, ts)
        if lt.hour == 17:
            out.append((c, lt.minute))
    out.sort(key=lambda cm: cm[1])
    return out


class FiveSettings(AppSettings):
    drink: str = Choice(
        "mixed",
        {"mixed": "Mixed", "beer": "Beer", "wine": "Wine", "cocktail": "Cocktail"},
        title="Drink",
    )
    count: int = Field(3, ge=1, le=4, title="Cities per loop", description="How many 17:xx cities to toast.")
    show_country: bool = Field(False, title="Show country code")
    accent: Color = Field("#ffd600", title="Accent colour")


# ---------------------------------------------------------------------------- glasses
def _body(f: Frame, x: int, y: int, w: int, h: int, tilt: float, fill: RGB, dark: RGB, level: float) -> None:
    """A tilted straight-sided glass: 1 px walls, liquid up to `level` (0..1), shade on the far side."""
    for row in range(h):
        dx = round(tilt * (h - 1 - row) / max(1, h - 1))
        yy = y + row
        liquid_from = round(h * (1 - level))
        for col in range(w):
            xx = x + col + dx
            edge = col in (0, w - 1) or row == h - 1
            if edge:
                f.set(xx, yy, GLASS if col else GLASS_HI)
            elif row >= liquid_from:
                f.set(xx, yy, dark if col >= w - 2 else fill)


def draw_beer(
    f: Frame, x: int, y: int, flip: bool, tilt: float, t: float, seed: int, seg: float = 4.0
) -> None:
    """Mug 10×13 (handle included), top-left at (x, y); `flip` puts the handle on the right."""
    bx = x + (0 if flip else 3)
    _body(f, bx, y + 2, 7, 11, tilt, BEER, BEER_DK, 0.95)
    # foam: two rows plus a lumpy crown that spills over the rim
    for row, cols in ((0, (1, 2, 4, 5)), (1, range(0, 7)), (2, range(0, 7))):
        dx = round(tilt * (12 - row) / 12)
        for c in cols:
            f.set(bx + c + dx, y + row, FOAM if row else mix(FOAM, BEER, 0.15))
    # bubbles rising through the beer (deterministic per glass), a whole number of rises per `seg` seconds so
    # a one-city loop wraps without a jump
    for i in range(3):
        rises = max(1, round((0.9 + 0.3 * i) * seg))
        ph = (t / seg * rises + (seed * 0.37 + i * 0.29)) % 1.0
        by = y + 11 - round(ph * 7)
        bxx = bx + 2 + (i * 2 + seed) % 3
        f.set(bxx + round(tilt * (y + 12 - by) / 12), by, mix(BEER, FOAM, 0.55))
    # handle: a 3-wide loop on the outer side
    hx = bx + 7 if flip else bx - 3
    for dy in range(4, 10):
        dx = round(tilt * (12 - dy) / 12)
        if dy in (4, 9):
            for k in range(3):
                f.set(hx + k + dx, y + dy, GLASS)
        else:
            f.set(hx + (2 if flip else 0) + dx, y + dy, GLASS)


def draw_wine(
    f: Frame, x: int, y: int, flip: bool, tilt: float, t: float, seed: int, seg: float = 4.0
) -> None:
    """Wine glass 8×14: round bowl, stem, foot."""
    rows = [
        (0, 1, 6),
        (1, 0, 8),
        (2, 0, 8),
        (3, 0, 8),
        (4, 0, 8),
        (5, 0, 8),
        (6, 1, 6),
        (7, 2, 4),
    ]
    for row, start, width in rows:
        dx = round(tilt * (13 - row) / 13)
        for c in range(width):
            xx = x + start + c + dx
            edge = c in (0, width - 1) or row == 7
            wine = row >= 3
            if edge:
                f.set(xx, y + row, GLASS_HI if (c == 0) != flip else GLASS)
            elif wine:
                f.set(xx, y + row, WINE_DK if (c >= width - 2) != flip else WINE)
    # a glint on the bowl
    f.set(x + (2 if not flip else 5) + round(tilt * 12 / 13), y + 1, WHITE)
    for row in range(8, 12):
        f.set(x + 3 + round(tilt * (13 - row) / 13), y + row, GLASS)
        f.set(x + 4 + round(tilt * (13 - row) / 13), y + row, GLASS if row == 8 else (60, 75, 100))
    for c in range(1, 7):
        f.set(x + c, y + 12, GLASS)
    for c in range(2, 6):
        f.set(x + c, y + 13, scale(GLASS, 0.5))
    _ = (t, seed, seg)


def draw_cocktail(
    f: Frame, x: int, y: int, flip: bool, tilt: float, t: float, seed: int, seg: float = 4.0
) -> None:
    """Martini glass 10×13 with a cherry on a pick."""
    for row in range(6):
        dx = round(tilt * (12 - row) / 12)
        start, end = row, 9 - row
        for c in range(start, end + 1):
            xx = x + c + dx
            if row == 0 or c in (start, end):
                f.set(xx, y + row + 1, GLASS_HI if c == start else GLASS)
            else:
                f.set(xx, y + row + 1, COCKTAIL_DK if c > 5 else COCKTAIL)
    for row in range(7, 11):
        f.set(x + 4 + round(tilt * (12 - row) / 12), y + row, GLASS)
        f.set(x + 5 + round(tilt * (12 - row) / 12), y + row, scale(GLASS, 0.6))
    for c in range(2, 8):
        f.set(x + c, y + 11, GLASS)
    # cherry on a pick, bobbing
    bobs = max(1, round(6 * seg / math.tau))  # ~1 bob a second, whole bobs per segment
    bob = round(0.5 + 0.5 * math.sin(t / seg * bobs * math.tau + seed))
    cx = x + (7 if not flip else 2) + round(tilt)
    f.set(cx, y + bob, CHERRY)
    f.set(cx + 1, y + bob, CHERRY)
    f.set(cx, y + 1 + bob, scale(CHERRY, 0.6))
    f.line(cx - (1 if not flip else -2), y + 2 + bob, cx - (3 if not flip else -4), y + 4, (140, 100, 60))


DRAW = {"beer": draw_beer, "wine": draw_wine, "cocktail": draw_cocktail}
WIDTH = {"beer": 10, "wine": 8, "cocktail": 10}


@register
class FiveOClock(App):
    id = "fiveoclock"
    name = "Five O'Clock Somewhere"
    description = (
        "A city where it's 17:xx right now (from local time-zone data), toasted with clinking glasses."
    )
    icon = "beer"
    category = "time"
    Settings = FiveSettings
    fps = 10.0
    clip_fps = 10.0
    clip_colors = 64
    SEG = 4.0  # seconds per city (longer if the name has to pan)

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        now = time.time()
        self._cache: tuple[float, list[tuple[City, int]]] | None = (now, five_oclock_cities(now))

    def kind(self) -> Kind:
        return "clip"

    # ------------------------------------------------------------------ data
    def cities(self, now: float | None = None) -> list[tuple[City, int]]:
        now = time.time() if now is None else now
        if self._cache is None or abs(now - self._cache[0]) > 20:
            self._cache = (now, five_oclock_cities(now))
        return self._cache[1][: self.settings.count]

    @staticmethod
    def _label(c: City) -> str:
        return c.name

    def _segments(self) -> list[tuple[City, float, str]]:
        out = []
        for i, (c, _m) in enumerate(self.cities()):
            label = self._label(c)
            over = max(0, measure(label) - 30)
            seg = max(self.SEG, round(1.6 + over / 12.0 + 0.5))
            drink = (
                self.settings.drink
                if self.settings.drink != "mixed"
                else DRINKS[(sum(map(ord, c.name)) + i) % 3]
            )
            out.append((c, float(seg), drink if drink in DRAW else "beer"))
        return out

    def clip_key(self) -> str:
        names = [c.name for c, _ in self.cities()]
        return json.dumps([self.settings.model_dump(mode="json"), names], sort_keys=True)

    def clip_frames(self) -> Clip:
        segs = self._segments()
        total = sum(s for _, s, _ in segs) or self.SEG
        n = round(total * self.clip_fps)
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / self.clip_fps)
            frames.append(f)
        return Clip(frames, [round(1000 / self.clip_fps)] * n)

    # ---------------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        segs = self._segments()
        if not segs:
            f.text_center(10, "NO BAR", MUTE, font="small")
            f.text_center(20, "OPEN", PALETTE["dim"])
            return
        total = sum(s for _, s, _ in segs)
        lt = t % total
        for city, seg, drink in segs:
            if lt < seg:
                self._scene(f, lt, seg, city, drink)
                return
            lt -= seg

    def _scene(self, f: Frame, lt: float, seg: float, city: City, drink: str) -> None:
        accent = to_rgb(self.settings.accent)
        # glasses approach, clink at 40 % of the segment, then settle back
        clink = seg * 0.4
        d = lt - clink
        # 1 s approach; after the clink hold together 0.5 s, then part
        gap = min(1.0, -d) if d < 0 else min(1.0, max(0.0, (d - 0.5) / 1.2))
        eased = gap * gap * (3 - 2 * gap)
        w = WIDTH[drink]
        sep = round(5 * eased)
        tilt = 1.6 * (1 - eased) if d > -1.0 else 0.0
        top = 9
        left_x = 16 - w - sep
        right_x = 16 + sep
        DRAW[drink](f, left_x, top, False, tilt, lt, 1, seg)
        DRAW[drink](f, right_x, top, True, -tilt, lt, 2, seg)
        # the clink: a star burst at the rims and a few droplets
        if 0 <= d < 0.9:
            k = 1 - d / 0.9
            cx, cy = 15, top + 1
            col = mix(accent, WHITE, 0.5)
            for i in range(8):
                a = i / 8 * math.tau
                r = 2 + d * 7
                f.set(round(cx + 0.5 + math.cos(a) * r), round(cy + math.sin(a) * r * 0.8), scale(col, k))
            for i, vx in enumerate((-3.0, -1.2, 1.4, 3.2)):
                px = cx + 0.5 + vx * d * 2.2
                py = cy - 1 - 7 * d + 14 * d * d
                f.set(round(px), round(py), scale(BEER if drink == "beer" else WINE, k) if i % 2 else col)
        # top row: "5PM IN" normally, "CHEERS!" around the clink
        if -0.2 <= d < 1.1:
            f.text_center(1, "CHEERS!", accent)
        elif self.settings.show_country:
            f.text(1, 1, "5PM", MUTE)
            f.text_right(30, 1, city.country, accent)
        else:
            f.text_center(1, "5PM IN", MUTE)
        # bottom: the city (pans once if it doesn't fit)
        label = self._label(city)
        wlab = measure(label)
        if wlab <= 30:
            f.text_center(25, label, WHITE)
        else:
            travel = wlab - 30
            p = max(0.0, min(1.0, (lt - 0.8) / max(0.1, seg - 1.6)))
            f.text(1 - round(travel * p), 25, label, WHITE, clip=(1, 25, 30, 29))

    def status(self) -> dict[str, Any]:
        now = time.time()
        return {
            "cities": [
                {"city": c.name.title(), "country": c.country, "zone": c.zone, "local": f"17:{m:02d}"}
                for c, m in self.cities(now)
            ]
        }
