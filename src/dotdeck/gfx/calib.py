"""Panel colour calibration: a per-panel correction applied to every frame on its way to the LEDs.

This is different from `color.calibrate` (which adapts *photos* to LEDs once at import). Panels vary:
some run blue-hot, some crush shadows. The studio's calibration wizard asks a few visual questions
against test patterns shown on the real panel and stores the answers as a `PanelCalibration`.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from pydantic import BaseModel, Field

from .font import measure
from .frame import Frame


class PanelCalibration(BaseModel):
    red: float = Field(1.0, ge=0.3, le=1.2, title="Red gain")
    green: float = Field(1.0, ge=0.3, le=1.2, title="Green gain")
    blue: float = Field(1.0, ge=0.3, le=1.2, title="Blue gain")
    gamma: float = Field(1.0, ge=0.5, le=2.5, title="Gamma")
    black_level: int = Field(0, ge=0, le=40, title="Black cutoff", description="Values below this turn off")
    lift: int = Field(0, ge=0, le=40, title="Shadow lift", description="Raises the dimmest visible level")
    saturation: float = Field(1.0, ge=0.0, le=2.0, title="Saturation")

    @property
    def identity(self) -> bool:
        return self == PanelCalibration()


@lru_cache(maxsize=32)
def _lut(red: float, green: float, blue: float, gamma: float, black: int, lift: int) -> np.ndarray:
    i = np.arange(256, dtype=np.float32) / 255.0
    base = i**gamma
    out = np.empty((3, 256), np.uint8)
    for ch, gain in enumerate((red, green, blue)):
        v = base * gain * 255.0
        v = np.where(v > 0.5, lift + v * (255.0 - lift) / 255.0, 0.0)  # lift keeps faint levels visible
        v[np.arange(256) < black] = 0
        out[ch] = np.clip(np.round(v), 0, 255).astype(np.uint8)
    return out


def apply(px: np.ndarray, c: PanelCalibration) -> np.ndarray:
    """Return a calibrated copy of an (H, W, 3) uint8 array."""
    if c.identity:
        return px
    a = px
    if c.saturation != 1.0:
        f = a.astype(np.float32)
        grey = f.mean(axis=2, keepdims=True)
        a = np.clip(grey + (f - grey) * c.saturation, 0, 255).astype(np.uint8)
    lut = _lut(c.red, c.green, c.blue, c.gamma, c.black_level, c.lift)
    out = np.empty_like(a)
    for ch in range(3):
        out[..., ch] = lut[ch][a[..., ch]]
    return out


# ------------------------------------------------------------------ wizard patterns
WHITE_CANDIDATES = {  # label -> (r, g, b) gains; LEDs usually run blue/green-heavy
    "A": (1.0, 1.0, 1.0),
    "B": (1.0, 0.9, 0.8),
    "C": (1.0, 0.82, 0.7),
    "D": (1.0, 0.75, 0.6),
}
GAMMA_CANDIDATES = {"A": 1.0, "B": 1.5, "C": 2.0}
SAT_CANDIDATES = {"A": 0.8, "B": 1.0, "C": 1.3}


def _label(f: Frame, x: int, y: int, s: str) -> None:
    f.rect(x, y, measure(s) + 2, 7, (0, 0, 0))
    f.text(x + 1, y + 1, s, (255, 255, 255))


def pattern(name: str, current: PanelCalibration) -> Frame:
    """Test patterns for the calibration wizard (already include the candidate corrections)."""
    f = Frame()
    if name == "white":
        for i, (lab, (r, g, b)) in enumerate(WHITE_CANDIDATES.items()):
            x, y = (i % 2) * 16, (i // 2) * 16
            f.rect(x, y, 16, 16, (round(255 * r), round(255 * g), round(255 * b)))
            _label(f, x + 1, y + 1, lab)
    elif name == "gamma":
        for row, (lab, gm) in enumerate(GAMMA_CANDIDATES.items()):
            y = row * 11
            for k in range(8):
                v = round(255 * ((k + 1) / 8) ** gm)
                f.rect(k * 4, y + 3, 4, 7, (v, v, v))
            f.text(0, y, lab, (255, 72, 24))
    elif name == "black":
        for k in range(8):
            v = 2 + k * 3
            x, y = (k % 4) * 8, 6 + (k // 4) * 13
            f.rect(x + 1, y, 6, 6, (v, v, v))
            f.text(x + 2, y + 7, str(k + 1), (120, 120, 140))
    elif name == "saturation":
        for row, (lab, sat) in enumerate(SAT_CANDIDATES.items()):
            y = row * 11
            strip = Frame()
            for x in range(32):
                h = x / 32
                strip.vline(x, 0, 8, _hue(h))
            c = PanelCalibration(saturation=sat)
            f.px[y + 2 : y + 10] = apply(strip.px, c)[:8]
            _label(f, 0, y, lab)
    elif name == "rgb":
        for i, col in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))):
            f.rect(i * 8, 0, 8, 32, col)
        f.px[:] = apply(f.px, current)
    elif name == "protocol_tear":
        for x in range(32):
            col = (0, 240, 255) if (x % 4 < 2) else (10, 10, 20)
            f.vline(x, 0, 24, col)
        f.rect(0, 24, 32, 8, (0, 0, 0))
        f.text_center(25, "TEAR TEST", (255, 72, 24), font="tiny")
    elif name == "protocol_stress":
        for y in range(32):
            for x in range(32):
                f.set(x, y, (round(255 * x / 31), round(255 * y / 31), round(255 * (x ^ y) / 31)))
        f.rect(3, 11, 26, 10, (0, 0, 0))
        f.text_center(13, "3-PACKET", (255, 255, 255), font="small")
    elif name == "protocol_cut":
        f.clear((0, 255, 120))
        f.rect(2, 2, 28, 28, (0, 0, 0))
        f.text_center(12, "ZERO NOISE", (0, 255, 120), font="small")
    else:  # "preview": a varied test card through the current calibration
        for x in range(32):
            f.vline(x, 0, 10, _hue(x / 32))
        for k in range(8):
            v = round(255 * (k + 1) / 8)
            f.rect(k * 4, 11, 4, 5, (v, v, v))
        f.rect(0, 17, 16, 15, (224, 172, 105))  # skin tone
        f.rect(16, 17, 16, 15, (255, 255, 255))
        f.text(2, 22, "SKIN", (60, 30, 10))
        f.px[:] = apply(f.px, current)
    return f


def _hue(h: float) -> tuple[int, int, int]:
    from .color import hsv

    return hsv(h)
