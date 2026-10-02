"""Fly Brain — a fruit fly living on the panel, driven by a model of its real visual circuit.

A fly in a small arena looks for fruit (flies are drawn to light) and darts away when a swatter's shadow looms
over it. Everything it does comes from `deskdot.fly.FlyBrain`: its eye sees only the arena's pixels (centred on
itself), T4/T5 motion detectors and LPLC2 looming detectors feed descending neurons and the giant fibre, and
their spikes are its moves. The panel shows only the fly's world; its brain activity (eye, motion detectors,
neurons firing, the keys it presses) is shown in the studio's 3D Fly view, from `fly_telemetry`.

The circuit is the one the FlyWire whole-brain connectome maps (Princeton-led, AI reconstruction built with
Google Research; Nature 2024). See docs/FLY_BRAIN.md. The simulation is seeded and baked into a seamless loop.
"""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..fly import FlyBrain, FlyConfig
from ..fly import config as flycfg
from ..gfx import Frame
from ._kit import loading

N_FRAMES = 128  # 16 s at 8 fps
FPS = 8.0
SEAM = 12  # frames blended across the loop seam
ARENA_H = 32  # the whole panel is the fly's arena
WARMUP = 24  # simulated frames before the loop starts (the brain settles)

BG = (14, 16, 24)
FLY = (215, 215, 228)
WING = ((150, 220, 255), (90, 140, 200))
FRUIT = (255, 120, 30)
STEM = (80, 200, 90)
SHADOW = (70, 44, 110)
SHADOW_RIM = (190, 120, 255)
DANGER = {"calm": 0.0, "normal": 1.0, "hectic": 2.2}

Key = tuple[str, int, int, tuple[float, ...]]  # settings + the brain's tuning (deskdot.fly.config)
_READY: dict[Key, list[np.ndarray]] = {}
_TELEMETRY: dict[Key, list[dict[str, Any]]] = {}  # the brain's activity for each frame of the loop


class FlyBrainSettings(AppSettings):
    danger: str = Choice(
        "normal",
        {"calm": "Calm (no swatter)", "normal": "Normal", "hectic": "Hectic"},
        title="Swatter",
    )
    fruit: int = Field(2, ge=1, le=3, title="Fruit in the arena")
    seed: int = Field(7, ge=0, le=9999, title="Fly", description="Each number is a different fly and arena")


def _spawn(rng: random.Random) -> tuple[float, float]:
    """A fruit somewhere in the arena, clear of the edges."""
    return rng.uniform(3, 28), rng.uniform(4, ARENA_H - 3)


def _simulate(
    danger: str, n_fruit: int, seed: int, tuning: tuple[float, ...] | None = None
) -> tuple[list[np.ndarray], list[dict[str, Any]]]:
    rng = random.Random(seed)
    cfg = flycfg.current() if tuning is None else FlyConfig(**dict(zip(flycfg.TUNING, tuning, strict=True)))
    brain = FlyBrain(seed=seed * 31 + 1, config=cfg)  # pinned for the whole bake
    x, y, vx, vy = 16.0, 12.0, 0.0, 0.0
    fruit = [_spawn(rng) for _ in range(n_fruit)]
    shadow: dict[str, float] | None = None
    next_threat = rng.uniform(3.0, 6.0) / max(0.01, DANGER[danger]) if DANGER[danger] else math.inf
    sparks: list[list[float]] = []
    frames: list[np.ndarray] = []
    tele: list[dict[str, Any]] = []
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
                fruit[j] = _spawn(rng)
        if shadow is None and t >= next_threat:
            shadow = {
                "x": min(28.0, max(4.0, x + rng.uniform(-3, 3))),
                "y": min(ARENA_H - 4.0, max(4.0, y + rng.uniform(-3, 3))),
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
        frames.append(f)
        snap = brain.snapshot()
        snap["world"] = {
            "fly": [round(x, 2), round(y, 2)],
            "fruit": [[round(a, 2), round(b, 2)] for a, b in fruit],
            "shadow": None if shadow is None else [round(shadow["x"], 2), round(shadow["y"], 2), shadow["r"]],
        }
        tele.append(snap)
    # blend the extra frames over the start, so the loop wraps without a jump
    loop = frames[:N_FRAMES]
    for k in range(SEAM):
        a = (k + 1) / (SEAM + 1)
        loop[k] = (frames[N_FRAMES + k].astype(np.float32) * (1 - a) + loop[k].astype(np.float32) * a).astype(
            np.uint8
        )
    # the studio gets the activity of the frame on show; seam frames keep their later (blended-in) activity
    tele_loop = tele[:N_FRAMES]
    for k in range(SEAM // 2):
        tele_loop[k] = tele[N_FRAMES + k]
    return loop, tele_loop


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


@register
class FlyBrainApp(App):
    id = "flybrain"
    name = "Fly Brain"
    category = "creative"
    icon = "bug"
    description = (
        "A fruit fly driven by a model of its real visual circuit (FlyWire connectome): it hunts fruit, "
        "dodges a looming swatter. Its neurons firing and the keys it presses play in the studio's 3D Fly view."
    )
    Settings = FlyBrainSettings

    clip_seconds = N_FRAMES / FPS
    clip_fps = FPS
    clip_colors = 48
    fps = FPS

    def kind(self) -> Kind:
        return "clip"

    def _key(self) -> Key:
        s = self.settings
        return (s.danger, s.fruit, s.seed, flycfg.tuning_key())

    def clip_key(self) -> str:
        """Settings + the brain's tuning: changing the fly's config (PATCH /api/fly/config) re-bakes the loop."""
        return f"{super().clip_key()}|fly={flycfg.tuning_key()}"

    def _index(self, t: float) -> int:
        return int(round(t * self.clip_fps, 6)) % N_FRAMES

    def render(self, f: Frame, t: float) -> None:
        frames = _READY.get(self._key())
        if frames is None:  # the simulation runs on the bake thread (clip_frames), never in render()
            loading(f, t, "FLY")
            return
        f.px[:] = frames[self._index(t)]

    def fly_telemetry(self, t: float) -> dict[str, Any] | None:
        tele = _TELEMETRY.get(self._key())
        if not tele:
            return None
        snap = dict(tele[self._index(t)])
        snap["driving"] = True
        return snap

    def clip_frames(self) -> Clip:
        key = self._key()
        frames = _READY.get(key)
        if frames is None or key not in _TELEMETRY:
            frames, _TELEMETRY[key] = _simulate(*key)
            _READY[key] = frames
        out = []
        for img in frames:
            fr = Frame()
            fr.px[:] = img
            out.append(fr)
        return Clip(out, [round(1000 / self.clip_fps)] * len(out))
