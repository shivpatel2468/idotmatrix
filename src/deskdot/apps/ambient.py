"""Ambient — generative light shows. Seamless loops are baked to GIFs and play natively."""

from __future__ import annotations

import math
import random
from functools import lru_cache

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame

YY, XX = np.mgrid[0:32, 0:32].astype(np.float32)
TAU = math.tau
FPS = 8.0  # busy full-screen motion reads smoothly at <= 8 fps on the panel (HARDWARE_PROTOCOL #13)
BASE_FRAMES = 51.2  # loop length at speed 1.0 (the default 0.8 gives a 64-frame, 8 s loop)
# Full-screen fields make big GIFs: their loops stop at 64 frames (<= 40 KB); sparse effects may run longer.
DENSE = {"plasma", "aurora", "lava", "zen", "fire", "ripple", "tunnel"}
IDX = np.arange(32, dtype=np.float32)


def loop_frames(effect: str, speed: float) -> int:
    """Frames in one loop: speed picks the loop length (a multiple of 8), never the frame duration."""
    n = round(BASE_FRAMES / speed / 8) * 8
    return max(24, min(64 if effect in DENSE else 96, n))


def _dot(f: Frame, x: float, y: float, c: tuple[int, int, int]) -> None:
    """A 1-px particle at a sub-pixel position: the four pixels it overlaps light in proportion (8 levels, the
    nearest at full strength), so slow particles glide instead of hopping a whole pixel at an uneven rhythm."""
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = round((x - x0) * 8) / 8, round((y - y0) * 8) / 8
    ws = ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy))
    peak = max(w for _, _, w in ws)
    for dx, dy, w in ws:
        xx, yy = x0 + dx, y0 + dy
        if w > 0 and 0 <= xx < 32 and 0 <= yy < 32:
            k = round(w / peak * 8) / 8
            f.px[yy, xx] = np.maximum(f.px[yy, xx], (np.asarray(c, np.float32) * k).astype(np.uint8))


def _cover(p: float, w: float) -> np.ndarray:
    """How much of each of the 32 pixel columns the span [p, p + w) covers (0..1)."""
    return np.clip(np.minimum(IDX + 1, p + w) - np.maximum(IDX, p), 0.0, 1.0)


def _tri(p: float) -> float:
    """Triangle wave 0 -> 1 -> 0 over one unit of p (a bounce between two walls)."""
    return 1.0 - abs(2.0 * (p % 1.0) - 1.0)


def _hsv_np(h: np.ndarray, s: np.ndarray | float, v: np.ndarray | float) -> np.ndarray:
    """Vectorised HSV -> RGB uint8, h in 0..1."""
    h = (h % 1.0) * 6.0
    s = np.broadcast_to(np.asarray(s, np.float32), h.shape)
    v = np.broadcast_to(np.asarray(v, np.float32), h.shape)
    i = np.floor(h).astype(int) % 6
    fr = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * fr), v * (1 - s * (1 - fr))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return (np.stack([r, g, b], axis=-1) * 255).clip(0, 255).astype(np.uint8)


PALETTES = {
    "rainbow": None,
    "ocean": [(0, 10, 40), (0, 80, 200), (0, 220, 255), (200, 255, 255)],
    "sunset": [(20, 0, 30), (160, 0, 90), (255, 80, 0), (255, 210, 60)],
    "forest": [(0, 10, 0), (0, 90, 30), (120, 220, 0), (230, 255, 120)],
    "ember": [(0, 0, 0), (120, 10, 0), (255, 72, 24), (255, 220, 120)],
    "neon": [(10, 0, 40), (255, 0, 190), (0, 220, 255), (255, 255, 255)],
}


def _ramp(v: np.ndarray, stops: list[tuple[int, int, int]]) -> np.ndarray:
    """Map 0..1 values through a colour ramp."""
    arr = np.asarray(stops, np.float32)
    pos = np.clip(v, 0, 1) * (len(stops) - 1)
    i = np.minimum(pos.astype(int), len(stops) - 2)
    fr = (pos - i)[..., None]
    return (arr[i] * (1 - fr) + arr[i + 1] * fr).astype(np.uint8)


def _color(v: np.ndarray, palette: str, hue_shift: float) -> np.ndarray:
    stops = PALETTES.get(palette)
    if stops is None:
        return _hsv_np(v + hue_shift, 1.0, 1.0)
    return _ramp(v, stops)


@lru_cache(maxsize=1)
def _life_simulation(n_frames: int = 48) -> list[np.ndarray]:
    """Precompute Conway's Life generations from harmonious seeds."""
    g0 = np.zeros((32, 32), bool)
    glider = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], bool)
    g0[2:5, 2:5] = glider
    g0[20:23, 22:25] = glider
    g0[14:18, 14:18] = np.array([[1, 1, 0, 1], [1, 0, 1, 0], [0, 1, 0, 1], [1, 0, 1, 1]], bool)
    frames: list[np.ndarray] = []
    curr = g0.copy()
    for _ in range(n_frames):
        frames.append(curr.copy())
        n = sum(np.roll(np.roll(curr, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)
        curr = (n == 3) | (curr & (n == 2))
    return frames


class AmbientSettings(AppSettings):
    effect: str = Choice(
        "plasma",
        {
            "plasma": "Plasma",
            "aurora": "Aurora",
            "lava": "Lava lamp",
            "zen": "Zen ripples",
            "embers": "Campfire embers",
            "fire": "Fire",
            "matrix": "Digital rain",
            "starfield": "Starfield",
            "ripple": "Ripple",
            "life": "Game of Life",
            "fireworks": "Fireworks",
            "snow": "Snowfall",
            "tunnel": "Tunnel",
            "bounce": "Bounce",
        },
    )
    palette: str = Choice("rainbow", list(PALETTES))
    speed: float = Field(0.8, ge=0.2, le=3.0, title="Speed")
    brightness: float = Field(0.85, ge=0.1, le=1.0, title="Intensity")


@register
class Ambient(App):
    id = "ambient"
    name = "Ambient"
    description = "Plasma, aurora, lava, zen, embers, fire, rain, stars, ripples, fireworks, snow, Life."
    icon = "sparkles"
    category = "ambient"
    Settings = AmbientSettings
    clip_seconds = 8.0
    clip_fps = FPS
    clip_colors = 32  # 32 colours guarantee lightweight GIF (15-32 KB) that panel decodes effortlessly
    fps = 8.0

    def kind(self) -> Kind:
        return "clip"

    def n_frames(self) -> int:
        return loop_frames(self.settings.effect, self.settings.speed)

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        # loop phase: effects are written in terms of `ph` (0..1 over one loop) with whole cycles per loop, so
        # render(0) == render(n_frames / fps) and the baked GIF wraps without a jump
        ph = (t * self.clip_fps / self.n_frames()) % 1.0
        fn = getattr(self, f"fx_{s.effect}")
        fn(f, ph, t)
        if s.brightness < 1:
            f.px[:] = (f.px.astype(np.float32) * s.brightness).astype(np.uint8)

    def clip_frames(self) -> Clip:
        n = self.n_frames()
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / self.clip_fps)
            frames.append(f)
        return Clip(frames, [round(1000 / self.clip_fps)] * n)

    # ----------------------------------------------------------------- effects
    def fx_plasma(self, f: Frame, ph: float, t: float) -> None:
        """Gentle drifting fluid plasma with small displacement steps."""
        a = ph * TAU
        cx = 16.0 + 3.2 * math.sin(a)
        cy = 16.0 + 3.2 * math.cos(a)
        v = (
            np.sin(XX / 6.0 + a)
            + np.sin(YY / 5.2 - a)
            + 0.7 * np.sin((XX + YY) / 8.5 + a)
            + np.sin(np.hypot(XX - cx, YY - cy) / 4.8)
        ) / 7.4 + 0.5
        f.px[:] = _color(v, self.settings.palette, ph)

    def fx_aurora(self, f: Frame, ph: float, t: float) -> None:
        """Graceful polar aurora ribbon with calm, sub-pixel undulation."""
        a = ph * TAU
        band = 13.0 + 3.0 * np.sin(XX / 8.0 + a) + 1.2 * np.sin(XX / 4.0 - a)
        d = np.abs(YY - band)
        v = np.clip(1.0 - d / 8.0, 0.0, 1.0) ** 1.5
        hue = 0.34 + 0.08 * np.sin(XX / 10.0 + a)
        pal = self.settings.palette
        rgb = _hsv_np(hue, 0.9, v) if pal == "rainbow" else _ramp(v, PALETTES[pal])  # type: ignore[arg-type]
        f.px[:] = rgb
        rnd = random.Random(3)
        for i in range(8):
            x, y = rnd.randrange(32), rnd.randrange(23, 32)
            k = 0.35 + 0.35 * math.sin(a + i * 0.8)
            f.set(x, y, (int(70 * k), int(70 * k), int(100 * k)))

    def fx_lava(self, f: Frame, ph: float, t: float) -> None:
        """Slow, buoyant lava lamp blobs rising and sinking meditatively."""
        a = ph * TAU
        field = np.zeros((32, 32), np.float32)
        for i in range(4):
            cx = 16.0 + 5.5 * math.sin(a + i * 1.5708)
            cy = 16.0 + 7.5 * math.sin(a * (1 if i % 2 == 0 else -1) + i * 1.5708)
            field += 20.0 / ((XX - cx) ** 2 + (YY - cy) ** 2 + 5.0)
        v = np.clip((field - 0.32) * 1.6, 0.0, 1.0)
        pal = self.settings.palette if self.settings.palette != "rainbow" else "sunset"
        f.px[:] = _ramp(v, PALETTES[pal])  # type: ignore[arg-type]

    def fx_ripple(self, f: Frame, ph: float, t: float) -> None:
        """Calm, expanding water ripples moving in gentle, wide wave crests."""
        a = ph * TAU
        d = np.hypot(XX - 15.5, YY - 15.5)
        v = 0.5 + 0.5 * np.sin(d / 2.4 - a)
        v *= np.clip(1.15 - d / 22.0, 0.0, 1.0)
        f.px[:] = _color(v, self.settings.palette, ph)

    def fx_zen(self, f: Frame, ph: float, t: float) -> None:
        """Calm, breathing concentric water ripples expanding from center."""
        a = ph * TAU
        d = np.hypot(XX - 15.5, YY - 15.5)
        ripple = 0.5 + 0.5 * np.sin(d / 2.8 - a)
        falloff = np.clip(1.0 - d / 20.0, 0.0, 1.0) ** 1.3
        v = ripple * falloff
        pal = self.settings.palette if self.settings.palette != "rainbow" else "ocean"
        f.px[:] = _ramp(v, PALETTES[pal])  # type: ignore[arg-type]

    def fx_embers(self, f: Frame, ph: float, t: float) -> None:
        """Cozy warm fireplace hearth with gentle breathing embers rising slowly."""
        a = ph * TAU
        hearth = np.clip((YY - 14.0) / 18.0, 0.0, 1.0) ** 2.0
        breathe = 0.75 + 0.25 * math.sin(a)
        base = hearth * breathe * 0.45
        f.px[:] = _ramp(base, PALETTES["ember"])
        rnd = random.Random(17)
        for _ in range(16):
            off = rnd.random()
            prog = (ph + off) % 1.0
            x = 15.5 + rnd.uniform(-10.0, 10.0) * (1.0 - prog * 0.3)
            y = 29.0 - prog * 20.0
            fade = math.sin(prog * math.pi) ** 1.2
            c_int = int(255 * fade)
            _dot(f, x, y, (c_int, int(c_int * 0.65), int(c_int * 0.15)))

    def fx_fire(self, f: Frame, ph: float, t: float) -> None:
        """Smooth procedural flame convection with rising embers, perfectly seamless."""
        a = ph * TAU
        turb = (
            np.sin(XX / 3.2 + a + YY / 6.0)
            + 0.6 * np.sin(XX / 2.0 - a - YY / 4.0)
            + 0.3 * np.sin(XX / 4.5 + 2 * a + YY / 3.0)
        ) / 1.9
        center_dist = np.abs(XX - 15.5) / 15.5
        shape = np.clip(1.0 - center_dist**1.6, 0.0, 1.0)
        height = np.clip((YY - 3.0) / 26.0, 0.0, 1.0)
        heat = np.clip((height * shape + turb * 0.22 * shape) * 1.3, 0.0, 1.0)
        rnd = random.Random(42)
        for _ in range(8):
            off = rnd.random()
            prog = (ph + off) % 1.0
            ex = 15.5 + rnd.uniform(-8.0, 8.0) * (1.0 - prog * 0.4)
            ey = 28.0 - prog * 24.0
            if 0 <= ey < 32 and 0 <= ex < 32:
                efade = math.sin(prog * math.pi)
                heat[round(ey), round(ex)] = max(heat[round(ey), round(ex)], 0.7 * efade)
        pal = self.settings.palette if self.settings.palette != "rainbow" else "ember"
        f.px[:] = _ramp(heat**1.2, PALETTES[pal])  # type: ignore[arg-type]

    def fx_matrix(self, f: Frame, ph: float, t: float) -> None:
        """Clean digital rain trickling down under 1 px/frame, each drop gliding between rows (no strobing)."""
        rnd = random.Random(11)
        head = np.array((220, 255, 220), np.float32)
        green = np.array(
            (0, 255, 90) if self.settings.palette == "rainbow" else PALETTES[self.settings.palette][2],
            np.float32,
        )
        for x in range(0, 32, 2):
            length = rnd.randint(7, 12)
            off = rnd.random()
            ramp = [head] + [green * (1.0 - k / length) ** 1.3 for k in range(1, length)]
            y = ((ph + off) % 1.0) * (32 + length)  # the head, in rows (a sub-pixel position)
            y0 = math.floor(y)
            fr = round((y - y0) * 8) / 8
            xx = x + (1 if (x // 2) % 3 == 0 else 0)
            for yy in range(max(0, y0 - length), min(32, y0 + 2)):
                # the drop between its two whole-row positions: blend the trail as drawn at y0 and at y0 + 1
                a, b = y0 - yy, y0 + 1 - yy
                ca = ramp[a] if 0 <= a < length else 0.0
                cb = ramp[b] if 0 <= b < length else 0.0
                c = np.asarray(ca * (1 - fr) + cb * fr, np.float32)
                if c.max() >= 1:
                    f.px[yy, xx] = c.astype(np.uint8)

    def fx_starfield(self, f: Frame, ph: float, t: float) -> None:
        """Serene starfield with bounded radial speeds that never teleport across the screen."""
        rnd = random.Random(5)
        for _ in range(28):
            sx, sy = rnd.uniform(-1, 1), rnd.uniform(-1, 1)
            dist = math.hypot(sx, sy)
            if dist < 0.15:
                continue
            sx, sy = sx / dist, sy / dist
            off = rnd.random()
            prog = (ph + off) % 1.0
            r = prog * 15.5
            fade = math.sin(prog * math.pi) ** 0.8
            if self.settings.palette == "rainbow":
                c = (int(255 * fade),) * 3
            else:
                c = tuple(int(v * fade) for v in PALETTES[self.settings.palette][3])
            _dot(f, 15.0 + sx * r, 15.0 + sy * r, c)  # type: ignore[arg-type]

    def fx_life(self, f: Frame, ph: float, t: float) -> None:
        """Conway's Game of Life baked into a smooth, native clip loop."""
        life_cache = _life_simulation(self.n_frames())
        idx = int(ph * len(life_cache)) % len(life_cache)
        g = life_cache[idx]
        hue = (XX + YY) / 64.0 + ph * 0.5
        rgb = (
            _color(hue, self.settings.palette, 0)
            if self.settings.palette != "rainbow"
            else _hsv_np(hue, 0.8, 1.0)
        )
        fade = 1.0
        if idx >= len(life_cache) - 4:
            fade = (len(life_cache) - 1 - idx) / 4.0
        elif idx < 4:
            fade = (idx + 1) / 4.0
        f.px[:] = np.where(g[..., None], (rgb * fade).astype(np.uint8), 0).astype(np.uint8)

    def fx_fireworks(self, f: Frame, ph: float, t: float) -> None:
        """Staggered grand firework bursts with gentle air drag and gravity decay."""
        rnd = random.Random(21)
        for k in range(2):
            cx, cy = rnd.randint(7, 24), rnd.randint(6, 13)
            hue = (k * 0.5 + 0.15) % 1.0
            local = (ph - k * 0.5) % 1.0
            if local > 0.85:
                continue
            if local < 0.25:
                y = 31.0 - (31.0 - cy) * (local / 0.25)
                _dot(f, cx, y + 1.5, (120, 80, 40))  # the rocket's glowing tail
                _dot(f, cx, y, (255, 230, 180))
                continue
            age = (local - 0.25) / 0.60
            r = age * 9.0
            fade = max(0.0, 1.0 - age) ** 1.4
            n = 10
            for i in range(n):
                ang = i / n * TAU
                col = _hsv_np(np.array([hue + i * 0.015]), 0.85, fade)[0]
                _dot(
                    f,
                    cx + math.cos(ang) * r,
                    cy + math.sin(ang) * r + age * age * 3.5,
                    tuple(int(v) for v in col),
                )  # type: ignore[arg-type]

    def fx_snow(self, f: Frame, ph: float, t: float) -> None:
        """Peaceful, steady winter snow drifting softly down the screen."""
        rnd = random.Random(8)
        for _ in range(22):
            x0, off = rnd.uniform(0, 32), rnd.random()
            depth = rnd.choice((0.4, 0.7, 1.0))
            y = ((ph + off) % 1.0) * 34.0 - 1.5
            c = int(255 * depth)
            # straight down, gliding between rows (a sideways wobble of < 1 px only flickers between columns)
            _dot(f, int(x0) % 32, y, (c, c, min(255, c + 20)))
        f.hline(0, 31, 32, (180, 190, 210))

    def fx_tunnel(self, f: Frame, ph: float, t: float) -> None:
        """Smooth forward warp tunnel with subtle rotation and gentle gradients."""
        d = np.hypot(XX - 15.5, YY - 15.5) + 0.5
        ang = np.arctan2(YY - 15.5, XX - 15.5) / TAU
        v = (6.0 / d + ph) % 1.0
        stripes = ((ang * 6.0 + ph) % 1.0) < 0.5  # turns one stripe pitch per loop: seamless
        bright = np.clip(d / 18.0, 0.0, 1.0)
        rgb = _color(v, self.settings.palette, ph)
        f.px[:] = (rgb * (bright * np.where(stripes, 1.0, 0.6))[..., None]).astype(np.uint8)

    def fx_bounce(self, f: Frame, ph: float, t: float) -> None:
        """DVD-style block bouncing off all four walls once per loop, drawn with sub-pixel edges (< 1 px/frame)."""
        x = _tri(ph) * 22.0
        y = _tri(ph + 0.25) * 24.0
        hue = (ph * 2.0) % 1.0
        col = _hsv_np(np.array([hue]), 0.9, 1.0)[0].astype(np.float32)

        def box(x0: float, y0: float, w: float, h: float) -> np.ndarray:
            return _cover(y0, h)[:, None] * _cover(x0, w)[None, :]

        cover = box(x, y, 10, 8) - box(x + 2, y + 2, 6, 4) + box(x + 4, y + 3, 2, 2)
        cover = np.round(np.clip(cover, 0.0, 1.0) * 8) / 8  # 8 levels keep the GIF palette small
        f.px[:] = (cover[..., None] * col).astype(np.uint8)
