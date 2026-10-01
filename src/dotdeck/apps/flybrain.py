"""Fly Brain — a fruit fly living on the panel, driven by a model of its real visual circuit.

A fly in a small arena looks for fruit (flies are drawn to light) and darts away when a swatter's shadow looms
over it. Everything it does comes from `dotdeck.fly.FlyBrain`: its eye sees only the arena's pixels (centred on
itself), T4/T5 motion detectors and LPLC2 looming detectors feed descending neurons and the giant fibre, and
their spikes are its moves. The strip below shows those neurons firing; the inset shows what its eye sees.

The circuit is the one the FlyWire whole-brain connectome maps (Princeton-led, AI reconstruction built with
Google Research; Nature 2024). See docs/FLY_BRAIN.md. The simulation is seeded and baked into a seamless loop.
"""

from __future__ import annotations

import math
import random

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..fly import FlyBrain
from ..gfx import Frame
from ._kit import loading

N_FRAMES = 128  # 16 s at 8 fps
FPS = 8.0
SEAM = 12  # frames blended across the loop seam
ARENA_H = 24  # arena rows; the brain strip is below
WARMUP = 24  # simulated frames before the loop starts (the brain settles)

BG = (14, 16, 24)
FLY = (215, 215, 228)
WING = ((150, 220, 255), (90, 140, 200))
FRUIT = (255, 120, 30)
STEM = (80, 200, 90)
SHADOW = (70, 44, 110)
SHADOW_RIM = (190, 120, 255)
BARS = (  # the descending neurons charging up (left, right, up, down), looming (LPLC2) and the giant fibre
    ("DN<", (0, 200, 255)),
    ("DN>", (0, 200, 255)),
    ("DN^", (80, 255, 120)),
    ("DNv", (80, 255, 120)),
    ("LOOM", (255, 70, 200)),
    ("GF", (255, 110, 40)),
)
DANGER = {"calm": 0.0, "normal": 1.0, "hectic": 2.2}

_READY: dict[tuple[str, int, bool, bool, int], list[np.ndarray]] = {}


class FlyBrainSettings(AppSettings):
    danger: str = Choice(
        "normal",
        {"calm": "Calm (no swatter)", "normal": "Normal", "hectic": "Hectic"},
        title="Swatter",
    )
    fruit: int = Field(2, ge=1, le=3, title="Fruit in the arena")
    show_brain: bool = Field(True, title="Show the neurons firing")
    show_eye: bool = Field(True, title="Show what the fly sees")
    seed: int = Field(7, ge=0, le=9999, title="Fly", description="Each number is a different fly and arena")


def _spawn(rng: random.Random, show_eye: bool) -> tuple[float, float]:
    """A fruit somewhere visible: never hidden behind the eye inset (top-right)."""
    while True:
        x, y = rng.uniform(3, 28), rng.uniform(3, ARENA_H - 3)
        if not (show_eye and x > 20 and y < 11):
            return x, y


def _simulate(danger: str, n_fruit: int, show_brain: bool, show_eye: bool, seed: int) -> list[np.ndarray]:
    rng = random.Random(seed)
    brain = FlyBrain(seed=seed * 31 + 1)
    x, y, vx, vy = 16.0, 12.0, 0.0, 0.0
    fruit = [_spawn(rng, show_eye) for _ in range(n_fruit)]
    shadow: dict[str, float] | None = None
    next_threat = rng.uniform(3.0, 6.0) / max(0.01, DANGER[danger]) if DANGER[danger] else math.inf
    sparks: list[list[float]] = []
    frames: list[np.ndarray] = []
    for i in range(WARMUP + N_FRAMES + SEAM):
        t = i / FPS
        # ---------------------------------------------------------------- the world the fly sees
        world = np.zeros((32, 32, 3), np.uint8)
        world[:ARENA_H] = BG
        for fx, fy in fruit:
            _blob(world, fx, fy, FRUIT, 1.2)
            _set(world, round(fx), round(fy) - 2, STEM)
        if shadow is not None:
            r = shadow["r"]
            _disc(world, shadow["x"], shadow["y"], r, SHADOW, SHADOW_RIM)
        # ---------------------------------------------------------------- the brain decides
        spikes = brain.step(world, (x, y))
        st = brain.state
        imp = 2.6
        for k in spikes:
            if k == "left":
                vx -= imp
            elif k == "right":
                vx += imp
            elif k == "up":
                vy -= imp
            elif k == "down":
                vy += imp
            elif k == "a":  # giant fibre: jump away from the looming shadow
                ax, ay = (
                    (x - shadow["x"], y - shadow["y"]) if shadow else (rng.uniform(-1, 1), rng.uniform(-1, 1))
                )
                d = math.hypot(ax, ay) or 1.0
                vx += ax / d * 9.0
                vy += ay / d * 9.0
        # ---------------------------------------------------------------- physics
        vx *= 0.78
        vy *= 0.78
        x = min(30.0, max(1.0, x + vx / FPS))
        y = min(ARENA_H - 2.0, max(1.0, y + vy / FPS))
        for j, (fx, fy) in enumerate(fruit):
            if math.hypot(fx - x, fy - y) < 2.2:  # eaten: sparkle, and a new fruit somewhere else
                for _ in range(8):
                    a = rng.uniform(0, math.tau)
                    sparks.append([fx, fy, math.cos(a) * 6, math.sin(a) * 6, 0.6])
                fruit[j] = _spawn(rng, show_eye)
        if shadow is None and t >= next_threat:
            shadow = {
                "x": min(28.0, max(4.0, x + rng.uniform(-3, 3))),
                "y": min(20.0, max(4.0, y + rng.uniform(-3, 3))),
                "r": 1.0,
            }
        elif shadow is not None:
            shadow["r"] += 0.75  # it comes closer: grows on the eye
            if shadow["r"] > 9.0:
                shadow = None
                next_threat = t + rng.uniform(4.0, 8.0) / max(0.01, DANGER[danger])
        for s in sparks:
            s[0] += s[2] / FPS
            s[1] += s[3] / FPS
            s[4] -= 1 / FPS
        sparks = [s for s in sparks if s[4] > 0]
        if i < WARMUP:
            continue
        # ---------------------------------------------------------------- draw the panel
        f = world.copy()
        for sx, sy, _vx, _vy, life in sparks:
            _set(f, round(sx), round(sy), tuple(int(c * min(1.0, life / 0.4)) for c in (255, 220, 120)))
        _fly(f, x, y, i)
        if show_eye:
            _eye_inset(f, st.eye)
        if show_brain:
            _brain_strip(f, st, spikes)
        else:
            f[ARENA_H:] = BG
        frames.append(f)
    # blend the extra frames over the start, so the loop wraps without a jump
    loop = frames[:N_FRAMES]
    for k in range(SEAM):
        a = (k + 1) / (SEAM + 1)
        loop[k] = (frames[N_FRAMES + k].astype(np.float32) * (1 - a) + loop[k].astype(np.float32) * a).astype(
            np.uint8
        )
    return loop


def _set(f: np.ndarray, x: int, y: int, c: tuple[int, ...]) -> None:
    if 0 <= x < 32 and 0 <= y < ARENA_H:
        f[y, x] = c


def _blob(f: np.ndarray, x: float, y: float, c: tuple[int, int, int], r: float) -> None:
    for yy in range(int(y - r - 1), int(y + r + 2)):
        for xx in range(int(x - r - 1), int(x + r + 2)):
            if math.hypot(xx + 0.5 - x, yy + 0.5 - y) <= r:
                _set(f, xx, yy, c)


def _disc(
    f: np.ndarray, x: float, y: float, r: float, fill: tuple[int, int, int], rim: tuple[int, int, int]
) -> None:
    for yy in range(int(y - r - 1), int(y + r + 2)):
        for xx in range(int(x - r - 1), int(x + r + 2)):
            d = math.hypot(xx + 0.5 - x, yy + 0.5 - y)
            if d <= r - 1:
                _set(f, xx, yy, fill)
            elif d <= r:
                _set(f, xx, yy, rim)


def _fly(f: np.ndarray, x: float, y: float, i: int) -> None:
    cx, cy = round(x), round(y)
    for dx, dy in ((0, 0), (-1, 0), (0, -1), (-1, -1)):
        _set(f, cx + dx, cy + dy, FLY)
    w = WING[(i // 1) % 2]  # wings beat every frame
    _set(f, cx - 2, cy - 2, w)
    _set(f, cx + 1, cy - 2, w)


def _eye_inset(f: np.ndarray, eye: np.ndarray) -> None:
    """Top-right: what the fly's compound eye sees (16×16 ommatidia shown at 8×8)."""
    small = eye.reshape(8, 2, 8, 2).mean(axis=(1, 3))
    x0, y0 = 23, 1
    f[y0 - 1 : y0 + 9, x0 - 1 : x0 + 9] = (60, 60, 84)
    tint = np.array([120, 230, 255], np.float32)
    norm = np.clip(small / max(0.08, float(small.max())), 0, 1)  # the eye adapts to its brightest point
    img = (norm[..., None] ** 0.8 * tint + 18).clip(0, 255).astype(np.uint8)
    f[y0 : y0 + 8, x0 : x0 + 8] = img


def _brain_strip(f: np.ndarray, st: object, spikes: list[str]) -> None:
    """Bottom: the neurons — wide-field motion (HS / VS), looming (LPLC2) and the giant fibre."""
    f[ARENA_H:] = (8, 8, 12)
    f[ARENA_H, :] = (34, 34, 46)
    dn = st.dn  # type: ignore[attr-defined]
    vals = (
        dn["left"],
        dn["right"],
        dn["up"],
        dn["down"],
        min(1.0, st.looming * 0.8),  # type: ignore[attr-defined]
        st.gf,  # type: ignore[attr-defined]
    )
    fired = {
        0: "left" in spikes,
        1: "right" in spikes,
        2: "up" in spikes,
        3: "down" in spikes,
        4: "a" in spikes,
        5: "a" in spikes,
    }
    for b, ((_label, col), v) in enumerate(zip(BARS, vals, strict=True)):
        x0 = 1 + b * 5
        h = min(6, round(min(1.0, v) * 6))
        f[ARENA_H + 1 : 32, x0 : x0 + 4] = (24, 24, 34)  # the empty bar is still visible
        if h:
            f[32 - h : 32, x0 : x0 + 4] = col
        if fired[b]:
            f[ARENA_H + 1, x0 : x0 + 4] = (255, 255, 255)  # a spike


@register
class FlyBrainApp(App):
    id = "flybrain"
    name = "Fly Brain"
    category = "creative"
    icon = "bug"
    description = (
        "A fruit fly driven by a model of its real visual circuit (FlyWire connectome): it hunts fruit, "
        "dodges a looming swatter, and you watch its neurons fire."
    )
    Settings = FlyBrainSettings

    clip_seconds = N_FRAMES / FPS
    clip_fps = FPS
    clip_colors = 48
    fps = FPS

    def kind(self) -> Kind:
        return "clip"

    def _key(self) -> tuple[str, int, bool, bool, int]:
        s = self.settings
        return (s.danger, s.fruit, s.show_brain, s.show_eye, s.seed)

    def render(self, f: Frame, t: float) -> None:
        frames = _READY.get(self._key())
        if frames is None:  # the simulation runs on the bake thread (clip_frames), never in render()
            loading(f, t, "FLY")
            return
        f.px[:] = frames[int(round(t * self.clip_fps, 6)) % len(frames)]

    def clip_frames(self) -> Clip:
        key = self._key()
        frames = _READY.get(key) or _simulate(*key)
        _READY[key] = frames
        out = []
        for img in frames:
            fr = Frame()
            fr.px[:] = img
            out.append(fr)
        return Clip(out, [round(1000 / self.clip_fps)] * len(out))
