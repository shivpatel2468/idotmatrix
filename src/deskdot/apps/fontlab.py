"""Font Lab — type customisation: built-in bitmap fonts or any pixel TTF, rendered 1-bit, styled, animated.

TTF fonts are rasterised with antialiasing OFF (Pillow mode "1") so every pixel is fully on or off,
exactly like the built-in fonts. Put extra .ttf/.otf files in assets/fonts or data/fonts.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import Frame, hsv, mix, scale
from ..gfx.font import FONTS

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[3] if len(_HERE.parents) > 3 else _HERE.parent  # the repo (installed/packaged: unused)
# repo assets, the repo's data dir, and ./data/fonts (the engine's working dir: Pi service, packaged installs)
FONT_DIRS = tuple(dict.fromkeys((ROOT / "assets" / "fonts", ROOT / "data" / "fonts", Path("data") / "fonts")))


def discover_fonts() -> dict[str, str]:
    fonts = {
        "tiny": "Built-in tiny (5px)",
        "small": "Built-in small (7px)",
        "big": "Built-in big digits (10px)",
    }
    for d in FONT_DIRS:
        try:
            files = (
                sorted(p for p in d.iterdir() if p.suffix.lower() in (".ttf", ".otf")) if d.is_dir() else []
            )
        except OSError:  # unreadable dir (permissions, a packaged app's read-only assets)
            files = []
        for p in files:  # any case: ".TTF" on a case-sensitive Linux / Android file system too
            fonts[f"ttf:{p.name}"] = p.stem.replace("_", " ")
    return fonts


FONT_CHOICES = discover_fonts()


@lru_cache(maxsize=64)
def raster(text: str, font: str, size: int, spacing: int) -> np.ndarray:
    """Render `text` to a boolean mask (h, w) with no antialiasing."""
    if not font.startswith("ttf:"):
        f = FONTS[font]
        cols = []
        for i, ch in enumerate(text):
            g = f.glyph(ch)
            cols.append(g)
            if i < len(text) - 1:
                cols.append(np.zeros((f.height, max(0, spacing)), bool))
        return np.concatenate(cols, axis=1) if cols else np.zeros((f.height, 1), bool)
    name = font[4:]
    path = next((d / name for d in FONT_DIRS if (d / name).exists()), None)
    if path is None:
        return raster(text, "small", size, spacing)
    try:
        ttf = ImageFont.truetype(str(path), size)
    except (OSError, ImportError):  # unreadable font, or a Pillow built without FreeType
        return raster(text, "small", size, spacing)
    w = int(ttf.getlength(text)) + 4 + spacing * len(text)
    img = Image.new("1", (max(1, w), size * 3), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # no antialiasing
    x = 0
    for ch in text:
        d.text((x, size), ch, font=ttf, fill=1, anchor="ls")  # baseline mid-canvas: nothing clips
        x += int(ttf.getlength(ch)) + spacing
    arr = np.asarray(img, dtype=bool)
    rows = np.where(arr.any(axis=1))[0]
    colsx = np.where(arr.any(axis=0))[0]
    if len(rows) == 0:
        return np.zeros((1, 1), bool)
    return arr[rows[0] : rows[-1] + 1, colsx[0] : colsx[-1] + 1]


class FontLabSettings(AppSettings):
    text: str = Field("PIXEL", max_length=60, title="Text")
    font: str = Choice("small", FONT_CHOICES, title="Font")
    size: int = Field(12, ge=6, le=32, title="TTF size (px)")
    spacing: int = Field(1, ge=-1, le=6, title="Letter spacing")
    uppercase: bool = Field(True, title="Uppercase")
    style: str = Choice(
        "plain",
        {
            "plain": "Plain",
            "bold": "Bold",
            "outline": "Outline",
            "shadow": "Shadow",
            "italic": "Italic",
            "double": "Double (2x)",
            "neon": "Neon glow",
        },
        title="Style",
    )
    align: str = Choice("center", {"left": "Left", "center": "Centre", "right": "Right"}, title="Align")
    valign: str = Choice("middle", {"top": "Top", "middle": "Middle", "bottom": "Bottom"}, title="Vertical")
    color: Color = Field("#ffffff", title="Colour")
    color2: Color = Field("#ff00be", title="Second colour")
    fill: str = Choice(
        "solid",
        {
            "solid": "Solid",
            "gradient": "Gradient",
            "rainbow": "Rainbow",
            "stripes": "Stripes",
            "fire": "Fire",
        },
        title="Fill",
    )
    animation: str = Choice(
        "none",
        {
            "none": "None",
            "scroll": "Scroll",
            "typewriter": "Typewriter",
            "wave": "Wave",
            "bounce": "Bounce",
            "flicker": "Flicker",
            "zoom": "Pulse",
        },
        title="Animation",
    )
    speed: float = Field(1.0, ge=0.2, le=4.0, title="Speed")
    background: Color = Field("#000000", title="Background")


@register
class FontLab(App):
    id = "fontlab"
    name = "Font Lab"
    description = (
        "Every font (built-in and pixel TTFs like Minecraft / VCR OSD), styles, fills and text animations."
    )
    icon = "case-sensitive"
    category = "creative"
    Settings = FontLabSettings
    fps = 10.0
    clip_fps = 10.0  # the fastest GIF rate verified on the panel
    clip_colors = 64
    SCROLL = 10.0  # px/s at speed 1: exactly 1 px per frame at 10 fps (marquees read best at 10-16 px/s)

    # --------------------------------------------------------------- the loop
    def _text(self) -> str:
        return self.settings.text.upper() if self.settings.uppercase else self.settings.text

    def _scrolls(self) -> bool:
        return self.settings.animation == "scroll" or self._mask(self._text() or " ").shape[1] > 32

    def kind(self) -> Kind:
        s = self.settings
        moving = s.animation != "none" or s.fill in ("rainbow", "stripes") or s.style == "neon"
        return "clip" if (moving or self._scrolls()) and self._text() else "stream"

    def _pacing(self) -> tuple[int, int, int]:
        """(frames per loop, frame ms, scroll px per frame). Deterministic text animation is baked as a clip:
        a scroll moves whole pixels at an even rate (<= 10 frames/s); everything else loops in 1-16 s."""
        s = self.settings
        if self._scrolls():
            v = self.SCROLL * s.speed
            travel = self._mask(self._text()).shape[1] + 32
            step = max(1, math.ceil(v / 10), math.ceil(travel / 160))
            return math.ceil(travel / step), round(1000 * step / v), step
        if s.animation == "typewriter":
            per_char = max(1, round(10 / (6 * s.speed)))  # ~6 chars/s
            # a multiple of 4 frames, so the blinking cursor (2 on, 2 off) closes the loop too
            return min(160, math.ceil((len(self._text()) + 8) * per_char / 4) * 4), 100, 0
        return max(10, min(160, round(40 / s.speed))), 100, 0

    def _cyc(self, t: float, period: float) -> float:
        """Phase (0..1) of something with a natural `period` (seconds at speed 1), rounded to a whole number of
        cycles per loop so the baked GIF wraps seamlessly."""
        n, ms, _ = self._pacing()
        loop = n * ms / 1000
        cycles = max(1, round(loop * self.settings.speed / period))
        return (t / loop * cycles) % 1.0

    def clip_frames(self) -> Clip:
        n, ms, _ = self._pacing()
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i * ms / 1000)
            frames.append(f)
        return Clip(frames, [ms] * n)

    def _mask(self, text: str) -> np.ndarray:
        s = self.settings
        font = s.font
        if font == "big" and not all(ch in "0123456789:.- " for ch in text):
            font = "small"  # `big` has digits only: letters would render as nothing
        m = raster(text, font, s.size, s.spacing)
        if s.style == "double":
            m = np.repeat(np.repeat(m, 2, 0), 2, 1)
        if s.style == "bold":
            m = m | np.roll(m, 1, 1)
        if s.style == "italic":
            h = m.shape[0]
            out = np.zeros((h, m.shape[1] + h // 3 + 1), bool)
            for y in range(h):
                sh = (h - 1 - y) // 3
                out[y, sh : sh + m.shape[1]] = m[y]
            m = out
        return m

    def _color_map(self, h: int, w: int, t: float) -> np.ndarray:
        s = self.settings
        a = np.array(mix(s.color, s.color, 0), np.float32)
        b = np.array(mix(s.color2, s.color2, 0), np.float32)
        xs = np.linspace(0, 1, max(1, w), dtype=np.float32)[None, :, None]
        ys = np.linspace(0, 1, max(1, h), dtype=np.float32)[:, None, None]
        if s.fill == "gradient":
            c = a + (b - a) * xs
            return np.broadcast_to(c, (h, w, 3))
        if s.fill == "rainbow":
            out = np.zeros((h, w, 3), np.float32)
            hue = self._cyc(t, 5.0)
            for x in range(w):
                out[:, x] = hsv(x / 28 + hue)
            return out
        if s.fill == "stripes":
            band = ((np.arange(h)[:, None] + int(self._cyc(t, 4 / 6) * 4)) // 2) % 2
            return np.where(band[..., None] == 0, a, b).repeat(w, 1) if w else np.zeros((h, w, 3))
        if s.fill == "fire":
            return np.broadcast_to(
                np.array((255, 40, 0), np.float32) + (np.array((255, 230, 90)) - (255, 40, 0)) * (1 - ys),
                (h, w, 3),
            )
        return np.broadcast_to(a, (h, w, 3))

    def render(self, f: Frame, t: float) -> None:
        # `t` is real time; every animation is a loop-aligned phase (`_cyc`), so render(0) == render(loop)
        s = self.settings
        f.clear(s.background)
        text = self._text()
        n, ms, step = self._pacing()
        i = int(round(t * 1000 / ms, 6)) % max(1, n)  # frame index in the loop
        if s.animation == "typewriter" and not self._scrolls():
            per_char = max(1, round(10 / (6 * s.speed)))
            k = i // per_char
            cursor = (i // 2) % 2 == 0
            text = text[: min(len(text), k)] + ("_" if k <= len(text) and cursor else "")
        if not text:
            return
        m = self._mask(text)
        h, w = m.shape
        colors = self._color_map(h, w, t)
        # placement
        if self._scrolls():
            x0 = 32 - (i * step) % (n * step)
        else:
            x0 = {"left": 1, "center": (32 - w) // 2, "right": 31 - w}[s.align]
        y0 = {"top": 1, "middle": (32 - h) // 2, "bottom": 31 - h}[s.valign]
        if s.animation == "bounce":
            y0 += round(-abs(math.sin(self._cyc(t, math.pi / 3) * math.pi)) * 4)
        glow = s.style in ("outline", "shadow", "neon")
        if glow:
            neon = 0.3 + 0.1 * math.sin(self._cyc(t, math.tau / 6) * math.tau)
            gcol = scale(s.color2, 0.9) if s.style != "neon" else scale(s.color, neon)
            offs = {
                "outline": ((-1, 0), (1, 0), (0, -1), (0, 1)),
                "shadow": ((1, 1),),
                "neon": ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)),
            }[s.style]
            for dx, dy in offs:
                self._stamp(f, m, None, x0 + dx, y0 + dy, gcol, t)
        self._stamp(f, m, colors, x0, y0, None, t)

    def _stamp(
        self,
        f: Frame,
        m: np.ndarray,
        colors: np.ndarray | None,
        x0: int,
        y0: int,
        solid: tuple[int, int, int] | None,
        t: float,
    ) -> None:
        s = self.settings
        wave = s.animation == "wave"
        wph = self._cyc(t, math.tau / 6) * math.tau
        fl = int(self._cyc(t, 1.0) * 12)  # flicker: 12 random draws per second-long cycle
        zoom = 0.6 + 0.4 * (0.5 + 0.5 * math.sin(self._cyc(t, math.tau / 4) * math.tau))
        for y, x in zip(*np.nonzero(m), strict=True):
            yy = y0 + int(y) + (round(math.sin(wph + x * 0.5) * 2) if wave else 0)
            xx = x0 + int(x)
            if not (0 <= xx < 32 and 0 <= yy < 32):
                continue
            if s.animation == "flicker" and (fl * 7919 + int(x) * 104729) % 9 == 0:
                continue
            c = solid if solid is not None else tuple(int(v) for v in colors[y, x])  # type: ignore[index]
            if s.animation == "zoom":
                c = scale(c, round(zoom * 8) / 8)
            f.px[yy, xx] = c
