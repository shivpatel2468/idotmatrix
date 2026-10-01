"""Weather — animated pixel icons, temperature, high/low and a 24 h trend.

The icon animation is deterministic for a given forecast, so the screen is a baked clip (`N_FRAMES` at
`clip_fps`) that re-bakes only when the forecast changes. Every moving part repeats a whole number of times per
loop and moves by whole pixels per frame (rain), 1 px per k frames (snow), or by sub-pixel coverage (drifting
clouds, fog), so the loop never jumps or stutters.
"""

from __future__ import annotations

import json
import math
import random
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, Kind, register
from ..gfx import Frame, mix, scale
from ._kit import label, loading, offline

CLOUD = (210, 220, 240)
CLOUD_DARK = (110, 115, 145)  # lifted: the old (90, 95, 120) all but vanished through the panel gamma
SUN = (255, 190, 0)
RAIN = (40, 150, 255)

N_FRAMES = 32  # one loop: 4 s at 8 fps
FPS = 8.0
RAIN_FALL = 8  # px a drop falls per cycle: 1 px per frame, 4 cycles per loop
DROP_PHASE = (0, 5, 2, 6, 3)  # staggered, so drops and flakes don't line up into a diagonal
COVERAGE_LEVELS = 8  # sub-pixel blends are quantised so the GIF palette stays small


def temp_color(c: float, unit: str) -> tuple[int, int, int]:
    """Blue when cold, white when mild, amber/red when hot."""
    if unit == "F":
        c = (c - 32) * 5 / 9
    if c <= 0:
        return (80, 160, 255)
    if c <= 18:
        return mix((80, 160, 255), (255, 255, 255), c / 18)
    if c <= 30:
        return mix((255, 255, 255), (255, 170, 0), (c - 18) / 12)
    return mix((255, 170, 0), (255, 40, 40), min(1.0, (c - 30) / 10))


def cloud(f: Frame, x: int, y: int, color: tuple[int, int, int] = CLOUD) -> None:
    """A 13x7 cloud with its top-left at (x, y)."""
    shade = scale(color, 0.7)
    f.circle(x + 3, y + 4, 2, color)
    f.circle(x + 7, y + 3, 3, color)
    f.circle(x + 10, y + 4, 2, color)
    f.rect(x + 2, y + 4, 10, 3, color)
    f.hline(x + 2, y + 6, 10, shade)


def drift(f: Frame, draw: Any, x: float, y: int) -> None:
    """Draw a shape at a fractional x: the two neighbouring whole-pixel positions blended by coverage."""
    x0 = math.floor(x)
    a = round((x - x0) * COVERAGE_LEVELS) / COVERAGE_LEVELS
    if a >= 1.0:
        x0, a = x0 + 1, 0.0
    lo, hi = Frame(), Frame()
    draw(lo, x0, y)
    if a > 0:
        draw(hi, x0 + 1, y)
        px = lo.px.astype(np.float32) * (1 - a) + hi.px.astype(np.float32) * a
    else:
        px = lo.px.astype(np.float32)
    mask = px.max(axis=2) > 0
    f.px[mask] = px[mask].round().astype(np.uint8)  # opaque: whatever is behind the shape stays hidden


def soft_hline(f: Frame, x: float, y: int, w: int, c: tuple[int, int, int]) -> None:
    """A horizontal band starting at a fractional x (end pixels lit by coverage)."""
    x0 = math.floor(x)
    a = round((x - x0) * COVERAGE_LEVELS) / COVERAGE_LEVELS
    f.set(x0, y, scale(c, 1 - a))
    f.hline(x0 + 1, y, w - 1, c)
    f.set(x0 + w, y, scale(c, a))


def sun(f: Frame, cx: int, cy: int, i: int, r: int = 3) -> None:
    """Sun disc with 8 rays that swap long/short twice per loop (a calm twinkle, no rotation jitter)."""
    f.circle(cx, cy, r, SUN)
    swap = (i * 4 // N_FRAMES) % 2
    for k in range(8):
        a = k / 8 * math.tau
        long = (k + swap) % 2 == 0
        for d in range(r + 2, r + (4 if long else 3)):
            f.set(round(cx + math.cos(a) * d), round(cy + math.sin(a) * d), scale(SUN, 0.9 if long else 0.6))


def moon(f: Frame, cx: int, cy: int, i: int) -> None:
    f.circle(cx, cy, 5, (230, 230, 200))
    f.circle(cx + 3, cy - 2, 4, (0, 0, 0))
    rnd = random.Random(7)
    ph = i / N_FRAMES
    for k in range(4):
        x, y = rnd.randint(1, 14), rnd.randint(1, 15)
        if abs(x - cx) + abs(y - cy) > 7:
            tw = 0.5 + 0.5 * math.sin(ph * math.tau * 2 + k * 1.7)
            f.set(x, y, scale((255, 255, 255), round((0.35 + 0.65 * tw) * 8) / 8))


def icon(f: Frame, cond: str, day: bool, i: int) -> None:
    """Draw the condition icon in the 16x17 box at the top-left, for loop frame `i` (0..N_FRAMES-1)."""
    ph = i / N_FRAMES
    sway = math.sin(ph * math.tau)  # one slow drift per loop
    if cond == "clear":
        (sun(f, 7, 8, i) if day else moon(f, 7, 8, i))
    elif cond == "partly":
        if day:
            sun(f, 10, 5, i, r=2)
        else:
            f.circle(11, 5, 3, (230, 230, 200))
            f.circle(13, 4, 2, (0, 0, 0))
        drift(f, cloud, 1.5 + sway, 7)
    elif cond == "cloudy":
        # both clouds stay left of x 16 so they never touch the temperature
        drift(f, lambda g, x, y: cloud(g, x, y, CLOUD_DARK), 2.25 + 0.75 * sway, 2)
        drift(f, cloud, 1.25 - 0.75 * sway, 7)
    elif cond == "fog":
        for k, y in enumerate((4, 7, 10, 13)):
            off = 1.5 * math.sin(ph * math.tau + k * math.pi / 2)
            soft_hline(f, 2.5 + off, y, 11, scale(CLOUD, 0.85 - k * 0.1))
    elif cond in ("rain", "drizzle", "storm"):
        dark = cond == "storm"
        cloud(f, 1, 1, CLOUD_DARK if dark else CLOUD)
        cols = (3, 9, 13) if cond == "drizzle" else (2, 5, 8, 11, 14)
        for k, x in enumerate(cols):
            y = 9 + (i + DROP_PHASE[k]) % RAIN_FALL  # 1 px per frame, whole cycles per loop
            f.set(x, y, RAIN)
            if y > 9:
                f.set(x, y - 1, scale(RAIN, 0.45))
        if dark and i in (0, 1, 3):  # one double flash per loop
            f.polyline([(9, 8), (7, 11), (10, 11), (8, 15)], (255, 240, 80))
    elif cond == "snow":
        cloud(f, 1, 1)
        for k in range(5):
            x = 2 + k * 3 + (1 if ((i // 8) + k) % 4 in (1, 2) else 0)  # 1 px sway, 1 px per 8 frames
            y = 9 + ((i // 2) + DROP_PHASE[k]) % 8  # 1 px per 2 frames (4 px/s)
            f.set(x, y, (255, 255, 255))


class WeatherSettings(AppSettings):
    layout: str = Choice("icon", {"icon": "Icon + condition", "forecast": "Icon + 24h trend"})
    accent: Color = Field("#00dcff", title="Accent")


@register
class Weather(App):
    id = "weather"
    name = "Weather"
    description = "Animated conditions, temperature, high/low and a 24-hour trend. Location in Settings."
    icon = "cloud-sun"
    category = "data"
    Settings = WeatherSettings
    fps = 5.0
    uses = ("weather",)
    clip_fps = FPS
    clip_seconds = N_FRAMES / FPS
    clip_colors = 64

    def _data(self) -> tuple[Any, dict[str, Any] | None]:
        try:
            p = self.ctx.provider("weather")
        except KeyError:
            return None, None
        return p, p.value or None

    def kind(self) -> Kind:
        _p, d = self._data()
        return "clip" if d else "stream"

    def clip_key(self) -> str:
        _p, d = self._data()
        sig = None
        if d:
            sig = [d.get(k) for k in ("condition", "is_day", "temp", "hi", "lo", "label", "unit")]
            sig.append([round(v, 1) for v in d.get("hourly") or []])
        return super().clip_key() + json.dumps(sig, default=str)

    def render(self, f: Frame, t: float) -> None:
        p, d = self._data()
        if not d:
            if p is not None and p.error:
                offline(f, "WEATHER", "OFFLINE")
            else:
                loading(f, t, "WEATHER", self.settings.accent)
            return
        i = int(t * FPS + 1e-6) % N_FRAMES
        icon(f, d["condition"], d["is_day"], i)
        unit = d["unit"]
        tc = temp_color(d["temp"], unit)
        f.text_right(30, 2, f"{d['temp']}°", tc, font="small")
        f.text(18, 11, "↑", (255, 120, 60))
        f.text_right(30, 11, str(d["hi"]), (200, 200, 210))
        f.text(18, 17, "↓", (80, 160, 255))
        f.text_right(30, 17, str(d["lo"]), (200, 200, 210))
        if self.settings.layout == "forecast" and len(d.get("hourly", [])) > 2:
            f.sparkline(
                0,
                24,
                32,
                8,
                d["hourly"],
                scale(self.settings.accent, 0.9),
                fill=scale(self.settings.accent, 0.3),
            )
        else:
            label(f, 25, d["label"], scale(self.settings.accent, 0.9))

    def status(self) -> dict:  # type: ignore[type-arg]
        _p, d = self._data()
        d = d or {}
        return {k: d.get(k) for k in ("city", "temp", "label", "hi", "lo", "unit")}
