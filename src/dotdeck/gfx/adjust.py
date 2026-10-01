"""Image controls shared by Screen Mirror and Camera Mirror: exposure, colour, geometry, effects.

`ImageControls` is a settings mixin (the studio renders every field as a control). `adjust()` runs
the pipeline on a small RGB image (~96 px) before it is downsampled to the panel, so it stays well
under a millisecond or two.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter
from pydantic import Field

from ..engine.app import AppSettings, Choice


class ImageControls(AppSettings):
    # exposure
    auto_exposure: bool = Field(
        True,
        title="Auto exposure",
        description="Stretch levels to the content",
        json_schema_extra={"group": "Exposure"},
    )
    exposure: float = Field(
        0.0,
        ge=-3.0,
        le=3.0,
        title="Exposure (EV)",
        description="Manual, or on top of auto",
        json_schema_extra={"group": "Exposure"},
    )
    black_point: int = Field(
        8,
        ge=0,
        le=60,
        title="Black point %",
        description="Auto: this % of pixels go black",
        json_schema_extra={"group": "Exposure"},
    )
    white_point: int = Field(
        99, ge=80, le=100, title="White point %", json_schema_extra={"group": "Exposure"}
    )
    brightness: float = Field(
        0.0, ge=-1.0, le=1.0, title="Brightness", json_schema_extra={"group": "Exposure"}
    )
    contrast: float = Field(1.0, ge=0.2, le=3.0, title="Contrast", json_schema_extra={"group": "Exposure"})
    gamma: float = Field(
        1.0,
        ge=0.3,
        le=3.0,
        title="Gamma",
        description=">1 darker mid-tones",
        json_schema_extra={"group": "Exposure"},
    )
    # colour
    saturation: float = Field(1.35, ge=0.0, le=3.0, title="Saturation", json_schema_extra={"group": "Colour"})
    hue: int = Field(0, ge=-180, le=180, title="Hue shift (°)", json_schema_extra={"group": "Colour"})
    temperature: float = Field(
        0.0,
        ge=-1.0,
        le=1.0,
        title="White balance",
        description="Cool ← → warm",
        json_schema_extra={"group": "Colour"},
    )
    tint: float = Field(
        0.0,
        ge=-1.0,
        le=1.0,
        title="Tint",
        description="Green ← → magenta",
        json_schema_extra={"group": "Colour"},
    )
    # detail & effects
    sharpness: float = Field(
        0.5, ge=0.0, le=3.0, title="Sharpness", json_schema_extra={"group": "Detail & effects"}
    )
    posterize: int = Field(
        0,
        ge=0,
        le=8,
        title="Posterise levels",
        description="0 = off",
        json_schema_extra={"group": "Detail & effects"},
    )
    invert: bool = Field(False, title="Invert", json_schema_extra={"group": "Detail & effects"})
    # geometry
    flip_h: bool = Field(False, title="Flip horizontal", json_schema_extra={"group": "Framing"})
    flip_v: bool = Field(False, title="Flip vertical", json_schema_extra={"group": "Framing"})
    rotate: str = Choice(
        "0", {"0": "0°", "90": "90°", "180": "180°", "270": "270°"}, title="Rotate", group="Framing"
    )
    zoom: float = Field(1.0, ge=1.0, le=8.0, title="Zoom", json_schema_extra={"group": "Framing"})
    pan_x: float = Field(0.0, ge=-1.0, le=1.0, title="Pan ←→", json_schema_extra={"group": "Framing"})
    pan_y: float = Field(0.0, ge=-1.0, le=1.0, title="Pan ↑↓", json_schema_extra={"group": "Framing"})


def crop_box(
    w: int, h: int, zoom: float, pan_x: float, pan_y: float, square: bool
) -> tuple[int, int, int, int]:
    """Region to sample: zoomed around a panned centre; square when the output fills the panel."""
    cw, ch = (min(w, h), min(w, h)) if square else (w, h)
    cw, ch = max(8, int(cw / zoom)), max(8, int(ch / zoom))
    cx = w / 2 + pan_x * (w - cw) / 2
    cy = h / 2 + pan_y * (h - ch) / 2
    x0 = int(min(max(0, cx - cw / 2), w - cw))
    y0 = int(min(max(0, cy - ch / 2), h - ch))
    return x0, y0, x0 + cw, y0 + ch


def geometry(img: Image.Image, c: ImageControls) -> Image.Image:
    if c.flip_h:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if c.flip_v:
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if c.rotate != "0":
        img = img.rotate(-int(c.rotate), expand=True)
    return img


def to_panel(img: Image.Image, c: ImageControls, size: tuple[int, int] = (32, 32)) -> np.ndarray:
    """Sharpen at working resolution, shrink to the panel, THEN set levels and colour.

    Order matters: shrinking averages thin bright details (text strokes, outlines) with their
    surroundings, so exposure must be judged on the pixels the panel will actually show.
    """
    work = img.convert("RGB")
    if c.sharpness > 0:
        work = work.filter(ImageFilter.UnsharpMask(radius=1.4, percent=int(c.sharpness * 140), threshold=1))
    small = work.resize(size, Image.Resampling.LANCZOS)
    return adjust(small, c)


def adjust(img: Image.Image, c: ImageControls) -> np.ndarray:
    """Tone + colour + effects on an RGB image; returns uint8 RGB of the same size."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    # exposure / levels
    if c.auto_exposure:
        lum = a.max(axis=2)
        lo = float(np.percentile(lum, c.black_point))
        hi = max(lo + 0.08, float(np.percentile(lum, c.white_point)))
        a = (a - lo) / (hi - lo)
    a = a * (2.0**c.exposure) + c.brightness
    a = (a - 0.5) * c.contrast + 0.5
    a = np.clip(a, 0, 1) ** c.gamma
    # white balance / tint
    if c.temperature or c.tint:
        a[..., 0] *= 1 + 0.35 * c.temperature
        a[..., 2] *= 1 - 0.35 * c.temperature
        a[..., 1] *= 1 - 0.3 * c.tint
    # saturation + hue in one rotation around the grey axis
    if c.saturation != 1.0 or c.hue:
        grey = a.mean(axis=2, keepdims=True)
        a = grey + (a - grey) * c.saturation
        if c.hue:
            th = np.deg2rad(c.hue)
            cos, sin = np.cos(th), np.sin(th)
            k = 1 / 3
            sq = np.sqrt(k)
            m = np.array(
                [
                    [cos + (1 - cos) * k, k * (1 - cos) - sq * sin, k * (1 - cos) + sq * sin],
                    [k * (1 - cos) + sq * sin, cos + k * (1 - cos), k * (1 - cos) - sq * sin],
                    [k * (1 - cos) - sq * sin, k * (1 - cos) + sq * sin, cos + k * (1 - cos)],
                ],
                np.float32,
            )
            a = a @ m.T
    a = np.clip(a, 0, 1)
    if c.invert:
        a = 1 - a
    if c.posterize >= 2:
        n = c.posterize - 1
        a = np.round(a * n) / n
    out = (a * 255).astype(np.uint8)
    out[out.max(axis=2) < 8] = 0  # keep blacks truly off on the LEDs
    return out
