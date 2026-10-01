"""Colour parsing, the LED design palette, and photo calibration for RGB LEDs.

Two kinds of colour live in DeskDot:

* **Design colours** (UI, text, icons) are authored *for the LEDs* using the
  `PALETTE` tokens below. They are sent to the panel untouched.
* **Photographic colours** (uploads, album art) come from sRGB screens and look
  washed out on LEDs, so they pass through `calibrate()` once at import time.

Never run calibration on design colours; it would darken every UI element.
"""

from __future__ import annotations

import colorsys
from functools import lru_cache
from typing import Literal

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from pydantic import BaseModel

RGB = tuple[int, int, int]
ColorLike = RGB | str | list[int] | tuple[int, ...]


def to_rgb(c: ColorLike) -> RGB:
    """Accept '#rgb', '#rrggbb', 'rrggbb', a palette token name, or an (r, g, b) sequence."""
    if isinstance(c, str):
        if c in PALETTE:
            return PALETTE[c]
        h = c.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) != 6:
            raise ValueError(f"bad colour {c!r}")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r, g, b = (int(v) for v in c[:3])
    return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))


def to_hex(c: ColorLike) -> str:
    r, g, b = to_rgb(c)
    return f"#{r:02x}{g:02x}{b:02x}"


def hsv(h: float, s: float = 1.0, v: float = 1.0) -> RGB:
    """h in 0..1 (wraps), s and v in 0..1."""
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return round(r * 255), round(g * 255), round(b * 255)


def mix(a: ColorLike, b: ColorLike, t: float) -> RGB:
    ra, ga, ba = to_rgb(a)
    rb, gb, bb = to_rgb(b)
    t = max(0.0, min(1.0, t))
    return round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t)


def scale(c: ColorLike, k: float) -> RGB:
    r, g, b = to_rgb(c)
    return to_rgb((r * k, g * k, b * k))


# ---------------------------------------------------------------------------
# LED design palette. Tuned on a real panel: saturated primaries read best;
# mid-greys look blue and muddy, so neutrals are kept few and deliberate.
# The studio UI imports these same tokens from /api/meta.
# ---------------------------------------------------------------------------
PALETTE: dict[str, RGB] = {
    # neutrals
    "black": (0, 0, 0),
    "ink": (10, 10, 16),  # "off" tint for tracks and empty cells
    "shade": (28, 28, 40),  # dividers, bar tracks
    "dim": (70, 70, 90),  # tertiary text
    "mute": (140, 140, 160),  # secondary text
    "white": (255, 255, 255),  # primary text
    # accents
    "ember": (255, 72, 24),  # DeskDot signature (Claude-adjacent terracotta tuned for LEDs)
    "amber": (255, 170, 0),
    "gold": (255, 214, 0),
    "lime": (140, 255, 0),
    "mint": (0, 255, 140),
    "cyan": (0, 220, 255),
    "sky": (40, 140, 255),
    "blue": (30, 60, 255),
    "violet": (140, 60, 255),
    "magenta": (255, 0, 190),
    "rose": (255, 30, 90),
    "red": (255, 0, 0),
    # semantic
    "ok": (0, 255, 120),
    "warn": (255, 170, 0),
    "bad": (255, 20, 60),
    "info": (0, 200, 255),
}


# ---------------------------------------------------------------------------
# Photo calibration
# ---------------------------------------------------------------------------
class CalibrationProfile(BaseModel):
    name: str
    gamma: float
    saturation: float
    contrast: float
    white_balance: tuple[float, float, float]
    black_threshold: int
    sharpen: bool


PROFILES: dict[str, CalibrationProfile] = {
    "vibrant": CalibrationProfile(
        name="Vibrant",
        gamma=2.2,
        saturation=1.25,
        contrast=1.10,
        white_balance=(1.0, 0.88, 0.82),
        black_threshold=10,
        sharpen=True,
    ),
    "natural": CalibrationProfile(
        name="Natural",
        gamma=2.0,
        saturation=1.08,
        contrast=1.05,
        white_balance=(1.0, 0.90, 0.85),
        black_threshold=6,
        sharpen=False,
    ),
    "raw": CalibrationProfile(
        name="Raw 1:1",
        gamma=1.0,
        saturation=1.0,
        contrast=1.0,
        white_balance=(1.0, 1.0, 1.0),
        black_threshold=0,
        sharpen=False,
    ),
}
ProfileName = Literal["vibrant", "natural", "raw"]


@lru_cache(maxsize=16)
def _lut(gamma: float, wb: tuple[float, float, float], black: int) -> list[int]:
    """768-entry Pillow point() table: gamma curve, per-channel white balance, black crush."""
    i = np.arange(256, dtype=np.float64)
    norm = np.clip((i - black) / (255.0 - black), 0.0, 1.0)
    base = np.where(i < black, 0.0, norm**gamma * 255.0)
    out: list[int] = []
    for k in wb:
        out.extend(np.clip(np.round(base * k), 0, 255).astype(int).tolist())
    return out


def calibrate(img: Image.Image, profile: str = "vibrant") -> Image.Image:
    """Map an sRGB photo to LED drive levels. Input and output are RGB images."""
    p = PROFILES.get(profile, PROFILES["vibrant"])
    rgb = img.convert("RGB")
    if p.saturation != 1.0:
        rgb = ImageEnhance.Color(rgb).enhance(p.saturation)
    if p.contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(p.contrast)
    if p.sharpen:
        rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=2))
    return rgb.point(_lut(p.gamma, p.white_balance, p.black_threshold))
