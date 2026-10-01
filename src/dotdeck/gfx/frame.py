"""The 32x32 frame buffer and its drawing primitives.

Every primitive clips to the panel, so nothing drawn through a Frame can ever
overflow or wrap. Coordinates are integers; (0, 0) is the top-left LED.
"""

from __future__ import annotations

import io
import itertools
import math
from collections.abc import Iterable, Sequence

import numpy as np
from PIL import Image

from .color import RGB, ColorLike, to_rgb

W = 32
H = 32
FRAME_BYTES = W * H * 3


class Frame:
    """A mutable 32x32 RGB image backed by a (H, W, 3) uint8 numpy array."""

    __slots__ = ("px",)

    def __init__(self, px: np.ndarray | None = None, fill: ColorLike = (0, 0, 0)) -> None:
        if px is None:
            px = np.empty((H, W, 3), dtype=np.uint8)
            px[:, :] = to_rgb(fill)
        if px.shape != (H, W, 3) or px.dtype != np.uint8:
            raise ValueError(f"Frame expects a ({H}, {W}, 3) uint8 array, got {px.shape} {px.dtype}")
        self.px = px

    # ---------------------------------------------------------------- basics
    @classmethod
    def from_bytes(cls, data: bytes) -> Frame:
        if len(data) != FRAME_BYTES:
            raise ValueError(f"expected {FRAME_BYTES} bytes, got {len(data)}")
        return cls(np.frombuffer(data, dtype=np.uint8).reshape(H, W, 3).copy())

    @classmethod
    def from_image(cls, img: Image.Image) -> Frame:
        if img.size != (W, H):
            raise ValueError(f"image must be {W}x{H}, got {img.size}")
        return cls(np.asarray(img.convert("RGB"), dtype=np.uint8).copy())

    def copy(self) -> Frame:
        return Frame(self.px.copy())

    def to_bytes(self) -> bytes:
        return self.px.tobytes()

    def to_image(self) -> Image.Image:
        return Image.fromarray(self.px, "RGB")

    def to_png(self, scale: int = 1) -> bytes:
        """Truecolour PNG. (Indexed-colour PNGs are smaller but the panel firmware renders them garbled —
        verified on hardware 2026-09-27, see docs/HARDWARE_PROTOCOL.md — so frames stay RGB.)"""
        img = self.to_image()
        if scale > 1:
            img = img.resize((W * scale, H * scale), Image.Resampling.NEAREST)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Frame) and np.array_equal(self.px, other.px)

    __hash__ = None  # type: ignore[assignment]

    # ------------------------------------------------------------ primitives
    def clear(self, color: ColorLike = (0, 0, 0)) -> Frame:
        self.px[:, :] = to_rgb(color)
        return self

    def get(self, x: int, y: int) -> RGB:
        r, g, b = self.px[y, x]
        return int(r), int(g), int(b)

    def set(self, x: int, y: int, color: ColorLike) -> None:
        if 0 <= x < W and 0 <= y < H:
            self.px[y, x] = to_rgb(color)

    def rect(self, x: int, y: int, w: int, h: int, color: ColorLike, fill: bool = True) -> None:
        """Axis-aligned rectangle with top-left (x, y) and size (w, h)."""
        if w <= 0 or h <= 0:
            return
        c = to_rgb(color)
        if fill:
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(W, x + w), min(H, y + h)
            if x0 < x1 and y0 < y1:
                self.px[y0:y1, x0:x1] = c
            return
        self.hline(x, y, w, c)
        self.hline(x, y + h - 1, w, c)
        self.vline(x, y, h, c)
        self.vline(x + w - 1, y, h, c)

    def hline(self, x: int, y: int, w: int, color: ColorLike) -> None:
        self.rect(x, y, w, 1, color)

    def vline(self, x: int, y: int, h: int, color: ColorLike) -> None:
        self.rect(x, y, 1, h, color)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: ColorLike) -> None:
        """Bresenham line, both endpoints inclusive."""
        c = to_rgb(color)
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.set(x0, y0, c)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def polyline(self, points: Sequence[tuple[int, int]], color: ColorLike) -> None:
        for (ax, ay), (bx, by) in itertools.pairwise(points):
            self.line(ax, ay, bx, by, color)

    def circle(self, cx: int, cy: int, r: int, color: ColorLike, fill: bool = True) -> None:
        """Pixel circle. Filled circles use a distance test for a round silhouette at tiny radii."""
        c = to_rgb(color)
        if fill:
            yy, xx = np.ogrid[:H, :W]
            mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r + r * 0.8
            self.px[mask] = c
            return
        x, y, err = r, 0, 1 - r
        while x >= y:
            for px, py in ((x, y), (y, x), (-y, x), (-x, y), (-x, -y), (-y, -x), (y, -x), (x, -y)):
                self.set(cx + px, cy + py, c)
            y += 1
            if err < 0:
                err += 2 * y + 1
            else:
                x -= 1
                err += 2 * (y - x) + 1

    def gradient_v(self, top: ColorLike, bottom: ColorLike, y: int = 0, h: int = H) -> None:
        a = np.array(to_rgb(top), dtype=np.float32)
        b = np.array(to_rgb(bottom), dtype=np.float32)
        y0, y1 = max(0, y), min(H, y + h)
        for row in range(y0, y1):
            t = (row - y) / max(1, h - 1)
            self.px[row, :] = (a + (b - a) * t).astype(np.uint8)

    def blend(self, x: int, y: int, color: ColorLike, alpha: float) -> None:
        if 0 <= x < W and 0 <= y < H:
            src = np.array(to_rgb(color), dtype=np.float32)
            dst = self.px[y, x].astype(np.float32)
            self.px[y, x] = (dst + (src - dst) * max(0.0, min(1.0, alpha))).astype(np.uint8)

    def dim(self, factor: float) -> Frame:
        self.px[:] = (self.px.astype(np.float32) * max(0.0, factor)).clip(0, 255).astype(np.uint8)
        return self

    def blit(self, src: Frame | np.ndarray, x: int = 0, y: int = 0, mask: np.ndarray | None = None) -> None:
        """Copy `src` onto this frame at (x, y). Black pixels are transparent unless a mask is given."""
        arr = src.px if isinstance(src, Frame) else src
        sh, sw = arr.shape[:2]
        if mask is None:
            mask = arr.any(axis=2)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(W, x + sw), min(H, y + sh)
        if x0 >= x1 or y0 >= y1:
            return
        sub = arr[y0 - y : y1 - y, x0 - x : x1 - x]
        m = mask[y0 - y : y1 - y, x0 - x : x1 - x]
        self.px[y0:y1, x0:x1][m] = sub[m]

    def sprite(self, sprite: Sprite, x: int, y: int) -> None:
        self.blit(sprite.px, x, y, sprite.mask)

    # ------------------------------------------------------------------ text
    def text(
        self,
        x: int,
        y: int,
        text: str,
        color: ColorLike = (255, 255, 255),
        font: str = "tiny",
        clip: tuple[int, int, int, int] | None = None,
        spacing: int = 1,
    ) -> int:
        """Draw text with a 1-bit bitmap font. Returns the x after the last glyph.

        `clip` is (x0, y0, x1, y1) inclusive; defaults to the whole panel.
        """
        from .font import draw_text

        return draw_text(self, x, y, text, to_rgb(color), font, clip, spacing)

    def text_center(
        self, y: int, text: str, color: ColorLike = (255, 255, 255), font: str = "tiny", spacing: int = 1
    ) -> None:
        from .font import measure

        self.text((W - measure(text, font, spacing=spacing)) // 2, y, text, color, font, spacing=spacing)

    def text_right(
        self,
        right: int,
        y: int,
        text: str,
        color: ColorLike = (255, 255, 255),
        font: str = "tiny",
        spacing: int = 1,
    ) -> None:
        from .font import measure

        self.text(right - measure(text, font, spacing=spacing) + 1, y, text, color, font, spacing=spacing)

    # ---------------------------------------------------------------- charts
    def bar(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        value: float,
        color: ColorLike,
        track: ColorLike = (24, 24, 32),
    ) -> None:
        """Horizontal progress bar; value in 0..1."""
        self.rect(x, y, w, h, track)
        filled = round(w * max(0.0, min(1.0, value)))
        self.rect(x, y, filled, h, color)

    def sparkline(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        values: Iterable[float],
        color: ColorLike,
        fill: ColorLike | None = None,
    ) -> None:
        """Resample `values` to `w` columns and draw a line chart in the box."""
        vals = np.asarray(list(values), dtype=np.float64)
        if vals.size < 2 or w < 2 or h < 1:
            return
        cols = np.interp(np.linspace(0, vals.size - 1, w), np.arange(vals.size), vals)
        lo, hi = float(cols.min()), float(cols.max())
        span = hi - lo or 1.0
        ys = [y + h - 1 - round((v - lo) / span * (h - 1)) for v in cols]
        if fill is not None:
            for i, py in enumerate(ys):
                self.vline(x + i, py + 1, y + h - py - 1, fill)
        self.polyline([(x + i, py) for i, py in enumerate(ys)], color)


class Sprite:
    """A small RGB image with a transparency mask, built from ASCII art.

    >>> Sprite.parse([".#.", "###"], {"#": "#ff0000"})
    """

    __slots__ = ("mask", "px")

    def __init__(self, px: np.ndarray, mask: np.ndarray) -> None:
        self.px = px
        self.mask = mask

    @property
    def w(self) -> int:
        return self.px.shape[1]

    @property
    def h(self) -> int:
        return self.px.shape[0]

    @classmethod
    def parse(cls, rows: Sequence[str], palette: dict[str, ColorLike]) -> Sprite:
        """Rows of characters; '.' and ' ' are transparent, others map through `palette`."""
        h = len(rows)
        w = max((len(r) for r in rows), default=0)
        px = np.zeros((h, w, 3), dtype=np.uint8)
        mask = np.zeros((h, w), dtype=bool)
        lut = {k: to_rgb(v) for k, v in palette.items()}
        for yy, row in enumerate(rows):
            for xx, ch in enumerate(row):
                if ch in ". ":
                    continue
                if ch not in lut:
                    raise KeyError(f"sprite char {ch!r} missing from palette")
                px[yy, xx] = lut[ch]
                mask[yy, xx] = True
        return cls(px, mask)

    def flipped(self) -> Sprite:
        return Sprite(self.px[:, ::-1].copy(), self.mask[:, ::-1].copy())


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)
