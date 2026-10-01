"""Neuromorphic Cortex — 1,024-neuron biological spiking neural network simulation on 32x32.

Simulates nonlinear membrane potential dynamics (FitzHugh-Nagumo / Izhikevich model),
synaptic coupling diffusion, action potential spikes, and traveling cortical waves.
Seamless loops are precomputed and baked into native hardware GIFs.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame
from ._kit import loading

PALETTES = {
    "bioluminescent": {
        "rest": np.array([4, 6, 14], dtype=np.float32),
        "depol": np.array([0, 140, 230], dtype=np.float32),
        "active": np.array([0, 230, 255], dtype=np.float32),
        "spike": np.array([255, 255, 255], dtype=np.float32),
        "refract": np.array([15, 10, 40], dtype=np.float32),
    },
    "neuro_gold": {
        "rest": np.array([12, 8, 4], dtype=np.float32),
        "depol": np.array([200, 100, 20], dtype=np.float32),
        "active": np.array([255, 200, 40], dtype=np.float32),
        "spike": np.array([255, 255, 240], dtype=np.float32),
        "refract": np.array([30, 15, 8], dtype=np.float32),
    },
    "infrared": {
        "rest": np.array([6, 2, 16], dtype=np.float32),
        "depol": np.array([180, 20, 120], dtype=np.float32),
        "active": np.array([255, 60, 40], dtype=np.float32),
        "spike": np.array([255, 240, 180], dtype=np.float32),
        "refract": np.array([20, 6, 30], dtype=np.float32),
    },
    "matrix": {
        "rest": np.array([2, 8, 4], dtype=np.float32),
        "depol": np.array([20, 160, 40], dtype=np.float32),
        "active": np.array([40, 255, 80], dtype=np.float32),
        "spike": np.array([240, 255, 240], dtype=np.float32),
        "refract": np.array([6, 25, 10], dtype=np.float32),
    },
}


def _render_cortex_frame(V: np.ndarray, U: np.ndarray, pal_name: str) -> np.ndarray:
    """Map membrane potential and recovery variables to RGB color array."""
    pal = PALETTES.get(pal_name, PALETTES["bioluminescent"])
    c_rest = pal["rest"]
    c_depol = pal["depol"]
    c_active = pal["active"]
    c_spike = pal["spike"]
    c_refract = pal["refract"]

    # Normalize V from [-1.3, 1.8] -> [0.0, 1.0]
    v_norm = np.clip((V + 1.2) / 2.7, 0.0, 1.0)[..., None]
    u_norm = np.clip((U + 0.5) / 1.8, 0.0, 1.0)[..., None]

    # Detect action potential peak spikes (V > 1.2)
    is_spike = (V > 1.2)[..., None]

    # Interpolate color: Rest -> Depol -> Active
    base = np.where(
        v_norm < 0.5,
        c_rest * (1.0 - v_norm * 2.0) + c_depol * (v_norm * 2.0),
        c_depol * (1.0 - (v_norm - 0.5) * 2.0) + c_active * ((v_norm - 0.5) * 2.0),
    )

    # Spike highlight: a bright tint of the active colour, not full white — whole-panel wave fronts at
    # 100 % white read as a flash-bang on the LEDs (and bloat the GIF palette).
    base = np.where(is_spike, c_active * 0.55 + c_spike * 0.45, base)

    # Recovery variable adds slight refractory hue shift
    base = base * (1.0 - 0.3 * u_norm) + c_refract * (0.3 * u_norm)

    return np.clip(base, 0, 255).astype(np.uint8)


def _fhn_step(
    V: np.ndarray, U: np.ndarray, drive: np.ndarray, dt: float = 0.12
) -> tuple[np.ndarray, np.ndarray]:
    lap = np.roll(V, 1, 0) + np.roll(V, -1, 0) + np.roll(V, 1, 1) + np.roll(V, -1, 1) - 4.0 * V
    v2 = V + dt * (V - V**3 / 3.0 - U + 0.22 * lap + drive)
    return v2, U + dt * 0.08 * (V + 0.7 - 0.8 * U)


def _pacemaker_loop(mode: str, palette: str, n_frames: int) -> list[np.ndarray]:
    """Excitable tissue (dark at rest) driven by a few pacemaker spots: rings of activity travel out, collide
    and die, over a dark background. The recording spans exactly one period of the (periodic) dynamics, so
    the baked GIF loops seamlessly. Replaces the old uniformly-oscillating field that lit the whole panel at
    once (a full-screen flash on the LEDs, and a muddy GIF)."""
    yy, xx = np.mgrid[0:32, 0:32].astype(np.float32)

    def spot(cx: float, cy: float, s: float) -> np.ndarray:
        return np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / s)

    V = np.full((32, 32), -1.2, np.float32)
    U = np.full((32, 32), -0.6, np.float32)
    if mode == "burst":
        drive = 0.2 + sum(0.33 * spot(cx, cy, 6) for cx, cy in ((6, 6), (25, 6), (6, 25), (25, 25)))
        drive = drive + 0.4 * spot(15.5, 15.5, 8)
    elif mode == "synapse":  # axon cross: only the tracts conduct, pacemakers at two ends
        drive = np.full((32, 32), 0.05, np.float32)
        drive[14:18, :] = 0.2
        drive[:, 14:18] = 0.2
        drive[14:18, 0:3] += 0.4
        drive[0:3, 14:18] += 0.35
    else:  # cortex: two columns of different strength beat against each other
        drive = 0.2 + 0.35 * spot(8, 10, 12) + 0.3 * spot(24, 22, 12)
    drive = np.asarray(drive, np.float32)
    return _one_period(V, U, drive, palette, n_frames)


_READY: dict[tuple[str, str, int], list[np.ndarray]] = {}  # finished loops, filled by clip_frames()


def _one_period(
    V: np.ndarray, U: np.ndarray, drive: np.ndarray | float, palette: str, n_frames: int, settle: int = 800
) -> list[np.ndarray]:
    """Settle onto the limit cycle, find its period from the autocorrelation of the mean potential, and sample
    exactly one period into `n_frames` frames: the loop is seamless by construction."""
    d = np.asarray(drive, np.float32)
    for _ in range(settle):
        V, U = _fhn_step(V, U, d)
    states: list[tuple[np.ndarray, np.ndarray]] = []
    for _ in range(900):
        V, U = _fhn_step(V, U, d)
        states.append((V, U))
    sig = np.array([v.mean() for v, _ in states])
    sig -= sig.mean()
    ac = np.array([np.dot(sig[:-lag], sig[lag:]) / (len(sig) - lag) for lag in range(1, 700)])
    neg = int(np.argmax(ac < 0)) if (ac < 0).any() else 0
    period = neg + 1 + int(np.argmax(ac[neg:]))
    # refine against the whole field (the mean alone can be off by a few steps): the lag whose states match best
    stack = np.stack([v for v, _ in states])
    lags = range(max(2, period - 6), min(len(states) - 50, period + 7))
    period = min(lags, key=lambda lag: float(np.abs(stack[lag : lag + 50] - stack[:50]).mean()))
    for _ in range(period + 2):  # a little of the next period, for the seam blend below
        V, U = _fhn_step(V, U, d)
        states.append((V, U))
    blend = 8
    frames = [
        _render_cortex_frame(*states[round(k * period / n_frames)], palette).astype(np.float32)
        for k in range(n_frames + blend)
    ]
    # some media (the spiral's core meanders) are only nearly periodic: over the first frames, fade from the
    # continuation of the last period into the first one, so the wrap never jumps
    for k in range(blend):
        w = (k + 1) / (blend + 1)
        frames[k] = frames[n_frames + k] * (1 - w) + frames[k] * w
    return [np.clip(fr, 0, 255).astype(np.uint8) for fr in frames[:n_frames]]


@lru_cache(maxsize=16)
def _simulate_cortex_loop(mode: str, palette: str, n_frames: int = 48) -> list[np.ndarray]:
    """One period of the (periodic) dynamics, sampled into `n_frames` frames."""
    if mode != "spiral":
        return _pacemaker_loop(mode, palette, n_frames)
    # a rotating spiral wave in an excitable medium: periodic once it has settled
    yy, xx = np.mgrid[0:32, 0:32].astype(np.float32)
    ang = np.arctan2(yy - 15.5, xx - 15.5)
    d = np.hypot(yy - 15.5, xx - 15.5)
    V = (np.sin(ang + d / 4.0) * 1.2).astype(np.float32)
    U = (np.cos(ang + d / 4.0) * 0.8).astype(np.float32)
    return _one_period(V, U, 0.42, palette, n_frames)


def loop_frames(speed: float) -> int:
    """Frames per period: speed picks the loop length (a multiple of 8), never the frame duration."""
    return max(24, min(72, round(48 / speed / 8) * 8))


class BrainSettings(AppSettings):
    mode: str = Choice(
        "cortex",
        {
            "cortex": "Resting Cortex Waves",
            "spiral": "Cortical Spiral Vortex",
            "burst": "Synchronized Gamma Burst",
            "synapse": "Axonal Signal Cascade",
        },
        title="Neural Dynamics Mode",
    )
    palette: str = Choice(
        "bioluminescent",
        {
            "bioluminescent": "Bioluminescent Cyan",
            "neuro_gold": "Synaptic Gold",
            "infrared": "Infrared Thermal",
            "matrix": "Neural Matrix",
        },
        title="Spike Palette",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, title="Oscillation Speed")
    brightness: float = Field(default=1.0, ge=0.2, le=1.0, title="LED Brightness")


@register
class Brain(App):
    id = "brain"
    name = "Neuromorphic Cortex"
    category = "creative"
    description = "1,024-neuron biological spiking neural network simulation with traveling waves."
    Settings = BrainSettings

    clip_seconds = 6.0  # 48 frames at 8 fps = 6.0 s loop
    clip_fps = 8.0
    clip_colors = 32
    fps = 8.0

    def kind(self) -> Kind:
        return "clip"

    def _key(self) -> tuple[str, str, int]:
        return (self.settings.mode, self.settings.palette, loop_frames(self.settings.speed))

    def render(self, f: Frame, t: float) -> None:
        # the simulation takes ~150 ms, far over the render budget: it runs in clip_frames() (the engine's bake
        # thread) and render() only reads the finished loop (same pattern as boids / sand)
        frames = _READY.get(self._key())
        if frames is None:
            loading(f, t, "CORTEX", (0, 200, 255))
            return
        img = frames[int(round(t * self.clip_fps, 6)) % len(frames)]
        if self.settings.brightness < 1.0:
            f.px[:] = (img.astype(np.float32) * self.settings.brightness).astype(np.uint8)
        else:
            f.px[:] = img

    def clip_frames(self) -> Clip:
        key = self._key()
        frames = _READY.get(key) or _simulate_cortex_loop(*key)
        _READY[key] = frames
        out: list[Frame] = []
        for i in range(len(frames)):
            f = Frame()
            self.render(f, i / self.clip_fps)
            out.append(f)
        return Clip(out, [round(1000 / self.clip_fps)] * len(out))
