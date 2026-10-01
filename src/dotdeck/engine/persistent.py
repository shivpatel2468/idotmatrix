"""Persistent overlays drawn on top of every app: status indicators and the On-Air badge / border glow.

Unlike notices (which come and go), these stay up as long as their state holds. They are composited after
the app, the notice and the transition, so they never flicker during app switches.

Indicators follow AWTRIX 3: three small squares on the right edge (1 top, 2 middle, 3 bottom), each with a
colour, an optional blink or fade period in milliseconds, and a lifetime after which it clears itself.
"""

from __future__ import annotations

import math
import time
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..gfx import Frame, mix, scale, to_rgb
from ..providers.custom import color_hex

ONAIR_RED = (255, 16, 24)


class Indicator(BaseModel):
    color: str = Field("#ff143c", description="'#rrggbb', a palette name, or [r, g, b]")
    blink: int = Field(0, ge=0, le=10000, description="blink period in ms (0 = steady); true = 1000")
    fade: int = Field(0, ge=0, le=10000, description="fade (breathe) period in ms (0 = off); true = 2000")
    lifetime_s: float = Field(0, ge=0, le=7 * 86400, description="seconds until it clears itself; 0 = never")
    size: int = Field(2, ge=2, le=3, description="2 or 3 px square")

    @field_validator("color", mode="before")
    @classmethod
    def _color(cls, v: Any) -> str:
        return color_hex(v) or "#ff143c"

    @field_validator("blink", mode="before")
    @classmethod
    def _blink(cls, v: Any) -> Any:
        return (1000 if v else 0) if isinstance(v, bool) else v

    @field_validator("fade", mode="before")
    @classmethod
    def _fade(cls, v: Any) -> Any:
        return (2000 if v else 0) if isinstance(v, bool) else v


class ActiveIndicator:
    def __init__(self, ind: Indicator, now: float | None = None) -> None:
        self.ind = ind
        self.since = time.monotonic() if now is None else now
        self.rgb = to_rgb(ind.color)

    def expired(self, now: float) -> bool:
        return bool(self.ind.lifetime_s) and now - self.since >= self.ind.lifetime_s

    @property
    def animated(self) -> bool:
        return bool(self.ind.blink or self.ind.fade)

    def level(self, now: float) -> float:
        t = (now - self.since) * 1000
        if self.ind.blink and (t % self.ind.blink) >= self.ind.blink / 2:
            return 0.0
        if self.ind.fade:
            return 0.12 + 0.88 * (0.5 - 0.5 * math.cos(2 * math.pi * (t % self.ind.fade) / self.ind.fade))
        return 1.0

    def to_json(self, now: float) -> dict[str, Any]:
        rem = max(0.0, self.ind.lifetime_s - (now - self.since)) if self.ind.lifetime_s else None
        return {**self.ind.model_dump(), "remaining_s": round(rem, 1) if rem is not None else None}


def indicator_origin(slot: int, size: int) -> tuple[int, int]:
    """Top-left pixel of indicator 1 (top-right), 2 (right, middle) or 3 (bottom-right)."""
    x = 32 - size
    y = {1: 0, 2: (32 - size) // 2, 3: 32 - size}[slot]
    return x, y


def draw_indicators(f: Frame, indicators: dict[int, ActiveIndicator], now: float) -> None:
    for slot, ai in sorted(indicators.items()):
        k = ai.level(now)
        n = ai.ind.size
        x, y = indicator_origin(slot, n)
        # a 1 px black halo on the inner sides keeps the square legible over any content
        f.rect(x - 1, y - 1, n + 1, n + 2, (0, 0, 0))
        if k > 0:
            f.rect(x, y, n, n, scale(ai.rgb, k))


def draw_onair_badge(f: Frame, glyph: str, t: float) -> None:
    """A red mic / cam glyph on a black tab in the top-left corner (right-edge corners belong to indicators)."""
    from ..gfx.icons import draw_icon

    red = ONAIR_RED  # steady: a pulsing badge would stream a new frame every tick for the whole call
    names = {"mic": ["mic"], "cam": ["cam"], "both": ["cam", "mic"]}.get(glyph, ["mic"])
    w = 1 + sum(7 if n == "cam" else 5 for n in names) + (len(names) - 1)
    f.rect(0, 0, w + 1, 9, (0, 0, 0))  # black tab keeps the glyph legible over any app
    x = 1
    for n in names:
        dw, _h = draw_icon(f, n, x, 1, red)
        x += dw + 1


def draw_onair_glow(f: Frame, t: float) -> None:
    """A breathing red border around whatever is showing."""
    k = 0.55 + 0.45 * (0.5 - 0.5 * math.cos(t * math.tau / 2.4))
    outer = scale(ONAIR_RED, k)
    inner = mix((0, 0, 0), ONAIR_RED, 0.28 * k)
    f.rect(1, 1, 30, 30, inner, fill=False)
    f.rect(0, 0, 32, 32, outer, fill=False)
