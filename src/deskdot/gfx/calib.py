"""Panel colour calibration: a per-panel correction applied to every frame on its way to the LEDs.

This is different from `color.calibrate` (which adapts *photos* to LEDs once at import). Panels vary:
some run blue-hot, some crush shadows. The studio's calibration wizard compares animated test videos on the
real panel against the same videos on the computer screen (A/B choices that converge, docs/CALIBRATION.md)
and stores the answers as a `PanelCalibration`. Picture-style presets live in `calib_presets.py`, the test
videos in `testvideo.py`.

The studio mirrors this exact maths in `web/src/lib/calib.ts` (so its preview can show the calibrated panel);
`tests/test_calibration.py` pins golden values both sides must agree on — change them together.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, ValidationError

from .font import measure
from .frame import Frame

#: Colour temperature that leaves white untouched (the panel's own white point after the RGB gains).
NEUTRAL_K = 6500

#: 4x4 ordered-dither thresholds, centred on 0 (about -0.47..+0.47 of one level). Static per pixel, so a still
#: frame stays still (no temporal shimmer); off channels stay off and lit ones never switch off: 1-bit-safe.
BAYER4 = (
    np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) + 0.5
) / 16 - 0.5


class PanelCalibration(BaseModel):
    """Every field defaults to "no change": the default model is the identity (frames pass through untouched)."""

    red: float = Field(1.0, ge=0.3, le=1.2, title="Red gain", description="White balance: red drive level")
    green: float = Field(
        1.0, ge=0.3, le=1.2, title="Green gain", description="White balance: green drive level"
    )
    blue: float = Field(1.0, ge=0.3, le=1.2, title="Blue gain", description="White balance: blue drive level")
    gamma: float = Field(1.0, ge=0.5, le=2.5, title="Gamma", description="Higher = darker mid-tones")
    gamma_red: float = Field(
        1.0, ge=0.7, le=1.4, title="Red gamma", description="Per-channel gamma multiplier"
    )
    gamma_green: float = Field(
        1.0, ge=0.7, le=1.4, title="Green gamma", description="Per-channel gamma multiplier"
    )
    gamma_blue: float = Field(
        1.0, ge=0.7, le=1.4, title="Blue gamma", description="Per-channel gamma multiplier"
    )
    black_level: int = Field(0, ge=0, le=40, title="Black cutoff", description="Values below this turn off")
    lift: int = Field(0, ge=0, le=40, title="Shadow lift", description="Raises the dimmest visible level")
    saturation: float = Field(1.0, ge=0.0, le=2.0, title="Saturation")
    contrast: float = Field(
        1.0, ge=0.6, le=1.6, title="Contrast", description="S-curve; black and white stay put"
    )
    temperature: int = Field(
        NEUTRAL_K, ge=3000, le=9500, title="Colour temperature", description="Kelvin; 6500 = no change"
    )
    level: float = Field(
        1.0, ge=0.5, le=1.0, title="Peak level", description="Caps the brightest drive level"
    )
    dither: bool = Field(
        False, title="Dithering", description="Ordered dither hides banding in dark gradients"
    )
    preset: str = Field("", max_length=40, title="Preset", description="Id of the preset this came from")

    @property
    def identity(self) -> bool:
        return self.model_dump(exclude={"preset"}) == _IDENTITY

    @classmethod
    def load(cls, raw: Any) -> PanelCalibration:
        """Tolerant load for stored state (rule 15): keys that no longer validate are dropped, never fatal."""
        if not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except ValidationError:
            pass
        good: dict[str, Any] = {}
        for k, v in raw.items():
            if k not in cls.model_fields:
                continue
            try:
                cls.model_validate({k: v})
            except ValidationError:
                continue
            good[k] = v
        return cls.model_validate(good)


_IDENTITY = PanelCalibration().model_dump(exclude={"preset"})


def _blackbody(kelvin: float) -> tuple[float, float, float]:
    """Tanner Helland's fit of blackbody colour (0..255 per channel)."""
    k = max(1000.0, min(40000.0, kelvin)) / 100.0
    r = 255.0 if k <= 66 else 329.698727446 * (k - 60) ** -0.1332047592
    g = (
        99.4708025861 * math.log(k) - 161.1195681661
        if k <= 66
        else 288.1221695283 * (k - 60) ** -0.0755148492
    )
    if k >= 66:
        b = 255.0
    elif k <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(k - 10) - 305.0447927307
    return (max(1.0, min(255.0, r)), max(1.0, min(255.0, g)), max(1.0, min(255.0, b)))


def kelvin_gains(kelvin: float) -> tuple[float, float, float]:
    """RGB multipliers that move the panel's white from 6500 K to `kelvin` (max channel = 1: never brightens)."""
    if round(kelvin) == NEUTRAL_K:
        return (1.0, 1.0, 1.0)
    a, b = _blackbody(kelvin), _blackbody(NEUTRAL_K)
    rel = [x / y for x, y in zip(a, b, strict=True)]
    top = max(rel)
    return (round(rel[0] / top, 4), round(rel[1] / top, 4), round(rel[2] / top, 4))


def channel_gains(c: PanelCalibration) -> tuple[float, float, float]:
    """Final per-channel gain: white balance x colour temperature x peak level."""
    t = kelvin_gains(c.temperature)
    return (c.red * t[0] * c.level, c.green * t[1] * c.level, c.blue * t[2] * c.level)


def _key(c: PanelCalibration) -> tuple[Any, ...]:
    r, g, b = channel_gains(c)
    return (
        round(r, 4),
        round(g, 4),
        round(b, 4),
        round(c.gamma, 4),
        (round(c.gamma_red, 4), round(c.gamma_green, 4), round(c.gamma_blue, 4)),
        c.black_level,
        c.lift,
        round(c.contrast, 4),
    )


@lru_cache(maxsize=64)
def _lut_f(
    red: float,
    green: float,
    blue: float,
    gamma: float,
    gammas: tuple[float, float, float],
    black: int,
    lift: int,
    contrast: float,
) -> np.ndarray:
    """(3, 256) float32 drive levels before rounding. Order: contrast S-curve, gamma, gain, lift, black cut."""
    i = np.arange(256, dtype=np.float64) / 255.0
    if contrast != 1.0:
        a, b = i**contrast, (1.0 - i) ** contrast
        x = a / (a + b)  # symmetric S-curve around mid-grey; 0 -> 0 and 1 -> 1 for every contrast
    else:
        x = i
    out = np.empty((3, 256), np.float32)
    for ch, (gain, gch) in enumerate(zip((red, green, blue), gammas, strict=True)):
        v = x ** (gamma * gch) * gain * 255.0
        v = np.where(v > 0.5, lift + v * (255.0 - lift) / 255.0, 0.0)  # lift keeps faint levels visible
        v[np.arange(256) < black] = 0
        out[ch] = np.clip(v, 0, 255)
    out.setflags(write=False)
    return out


@lru_cache(maxsize=64)
def _lut(
    red: float,
    green: float,
    blue: float,
    gamma: float,
    gammas: tuple[float, float, float] = (1.0, 1.0, 1.0),
    black: int = 0,
    lift: int = 0,
    contrast: float = 1.0,
) -> np.ndarray:
    """(3, 256) uint8 lookup table."""
    t = np.round(_lut_f(red, green, blue, gamma, gammas, black, lift, contrast)).astype(np.uint8)
    t.setflags(write=False)
    return t


def lut(c: PanelCalibration) -> np.ndarray:
    """The (3, 256) uint8 table for `c` (saturation and dithering are applied around it)."""
    return _lut(*_key(c))


def apply(px: np.ndarray, c: PanelCalibration) -> np.ndarray:
    """Return a calibrated copy of an (H, W, 3) uint8 array."""
    if c.identity:
        return px
    a = px
    if c.saturation != 1.0:
        f = a.astype(np.float32)
        grey = f.mean(axis=2, keepdims=True)
        a = np.clip(np.round(grey + (f - grey) * c.saturation), 0, 255).astype(np.uint8)
    out = np.empty_like(a)
    if c.dither:
        table = _lut_f(*_key(c))
        h, w = a.shape[:2]
        thr = np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
        for ch in range(3):
            v = table[ch][a[..., ch]]
            d = np.where(v > 0, np.clip(np.round(v + thr), 1, 255), 0)  # off stays off, lit never turns off
            out[..., ch] = d.astype(np.uint8)
    else:
        table = lut(c)
        for ch in range(3):
            out[..., ch] = table[ch][a[..., ch]]
    return out


# ------------------------------------------------------------------ legacy wizard patterns (still cards)
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
    """Still test cards (the first-generation wizard; kept for the API). They include their own corrections."""
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
