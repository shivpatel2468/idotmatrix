"""A fruit-fly brain that watches the 32×32 panel and plays.

This is a *model of the circuit*, not a simulation of every neuron. It follows the fly's visual motion pathway,
the part of the brain that the FlyWire whole-brain connectome (Princeton-led, AI reconstruction built with
Google Research; Nature, 2 Oct 2024: 139,255 neurons, ~54.5 M synapses) maps in detail:

    retina (R1–6) ─▶ lamina L1 (ON) / L2 (OFF) ─▶ T4 (ON) / T5 (OFF) direction-selective cells
        ─▶ lobula plate HS (horizontal) / VS (vertical) tangential cells ─┐
        ─▶ LPLC2 looming detectors ─▶ giant fibre (escape) ───────────────┼─▶ descending neurons ─▶ keys
    phototaxis (flies are drawn to light) ─────────────────────────────────┘

* **Eye**: 16×16 ommatidia (2×2 panel pixels each), *ego-centric*: centred on the fly's own body when the game
  says where that is (`anchor`), like an eye that moves with the fly.
* **T4/T5**: Hassenstein–Reichardt elementary motion detectors (a delayed neighbour × the present signal, minus
  the mirror term) on separate ON and OFF channels; the T4/T5 → lobula-plate wiring is exactly what the
  connectome confirmed.
* **HS / VS**: hemifield sums of horizontal / vertical motion (optomotor response: turn with wide-field rotation).
* **LPLC2 → giant fibre**: radial expansion around the centre = something looming. Strong looming fires the giant
  fibre: the escape jump (key A), and a saccade away from the expanding side.
* **Descending neurons**: leaky integrate-and-fire units (steer left/right/up/down); a spike = one key press.
* **Smell (lure)**: a game may say where the fly's goal is (`lures`). It is a *sensory cue*, an odour source the
  antennae pick up, added to the light map phototaxis chooses from; the brain still decides and presses the keys.
* **Feeding reflex**: when a game allows it (`feed`), standing on the smell fires the proboscis-extension reflex
  (taste receptors on the legs → PER), pressed as key A: "eat here" = place, drop, open.

The knobs (phototaxis, looming, leak, threshold, ...) come from `deskdot.fly.config` (GET/PATCH /api/fly/config).

Pure numpy, deterministic for a given seed, well under 1 ms per frame.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .config import FlyConfig, current

EYE = 16  # ommatidia per side
DNS = ("left", "right", "up", "down")


@dataclass
class FlyState:
    """What the brain is doing right now (for drawing it, and for tests)."""

    eye: np.ndarray = field(default_factory=lambda: np.zeros((EYE, EYE), np.float32))  # what it sees, 0..1
    hs_left: float = 0.0  # leftward wide-field motion (lobula plate HS)
    hs_right: float = 0.0
    vs_up: float = 0.0  # upward wide-field motion (VS)
    vs_down: float = 0.0
    looming: float = 0.0  # LPLC2: radial expansion
    # phototaxis: where the light is, relative to the eye centre (-1..1)
    light: tuple[float, float] = (0.0, 0.0)
    dn: dict[str, float] = field(default_factory=lambda: dict.fromkeys(DNS, 0.0))  # membrane potentials 0..1
    gf: float = 0.0  # giant fibre potential
    spikes: list[str] = field(default_factory=list)  # keys fired this step
    # the layers' activity maps (16×16), for the studio's 3D view of the brain
    on: np.ndarray = field(
        default_factory=lambda: np.zeros((EYE, EYE), np.float32)
    )  # lamina L1 (brightening)
    off: np.ndarray = field(default_factory=lambda: np.zeros((EYE, EYE), np.float32))  # lamina L2 (dimming)
    motion_h: np.ndarray = field(default_factory=lambda: np.zeros((EYE, EYE), np.float32))  # T4/T5, + = right
    motion_v: np.ndarray = field(default_factory=lambda: np.zeros((EYE, EYE), np.float32))  # T4/T5, + = down
    odour: np.ndarray = field(default_factory=lambda: np.zeros((EYE, EYE), np.float32))  # smelled lures


KEYLOG = 32  # recent key presses kept for the studio's keyboard view


def _u8(a: np.ndarray, scale: float) -> list[int]:
    return np.clip(a * scale, 0, 255).astype(np.uint8).ravel().tolist()


def _s8(a: np.ndarray, scale: float) -> list[int]:
    return np.clip(a * scale, -127, 127).astype(np.int8).ravel().tolist()


Lure = tuple[float, float, float]  # (x, y, strength 0..1) in panel pixels


class FlyBrain:
    """The tunable constants (leak, threshold, refractory period, phototaxis, noise, gains) live in `FlyConfig`;
    its defaults are the original values: leak 0.80, threshold 1.0, refractory 2 steps, phototaxis 0.3 (steady
    state 1.5 x threshold: about one turn every 3 steps), noise 0.06."""

    TAU_DELAY = 0.35  # low-pass "delay" arm of the motion detector (frames)
    GF_THRESHOLD = 1.0
    ODOUR_WEIGHT = 1.5  # a lure of strength 1 outweighs a bright pixel next to the fly
    ODOUR_PULL = 0.3  # extra drive while heading for a smell

    def __init__(self, seed: int = 7, config: FlyConfig | None = None) -> None:
        self.rng = random.Random(seed)
        self.config = config  # None = the shared config (deskdot.fly.config.current())
        self.reset()

    @property
    def cfg(self) -> FlyConfig:
        return self.config or current()

    def reset(self) -> None:
        self._prev: np.ndarray | None = None
        self._delay_on = np.zeros((EYE, EYE), np.float32)
        self._delay_off = np.zeros((EYE, EYE), np.float32)
        self._v = dict.fromkeys(DNS, 0.0)
        self._gf = 0.0
        self._refractory = dict.fromkeys((*DNS, "a"), 0)
        self._per = 0.0  # proboscis-extension (feeding) reflex potential
        self._per_rest = 0
        self.state = FlyState()
        self.steps = 0
        self.keylog: deque[tuple[int, str]] = deque(maxlen=KEYLOG)
        self.anchor: tuple[float, float] | None = None
        self.lures: list[Lure] = []

    # ------------------------------------------------------------------ eye
    @staticmethod
    def see(px: np.ndarray, anchor: tuple[float, float] | None = None) -> np.ndarray:
        """Panel RGB (32×32×3) → 16×16 luminance, re-centred on `anchor` (x, y) so the fly is in the middle."""
        lum = (px[..., 0] * 0.3 + px[..., 1] * 0.59 + px[..., 2] * 0.11).astype(np.float32) / 255.0
        if anchor is not None:
            ax = min(31, max(0, round(anchor[0])))  # an off-screen body is seen from the nearest edge
            ay = min(31, max(0, round(anchor[1])))
            canvas = np.zeros((64, 64), np.float32)  # outside the world is dark
            canvas[32 - ay : 64 - ay, 32 - ax : 64 - ax] = lum  # put the anchor at (32, 32)
            lum = canvas[16:48, 16:48]
        return lum.reshape(EYE, 2, EYE, 2).mean(axis=(1, 3))

    @staticmethod
    def smell(lures: list[Lure], anchor: tuple[float, float] | None, gain: float) -> np.ndarray:
        """Lures (panel x, y, strength) -> a 16x16 odour map in eye coordinates. A source beyond the eye's view is
        smelled at the edge in its direction (the gradient still points the right way)."""
        od = np.zeros((EYE, EYE), np.float32)
        if not lures or gain <= 0:
            return od
        ax, ay = (16.0, 16.0) if anchor is None else (float(anchor[0]), float(anchor[1]))
        half = EYE // 2

        def cell(o: float) -> int:
            # symmetric about the eye's centre (between cells 7 and 8): within one cell = the middle two cells,
            # under the fly's body; beyond that, one more cell out per cell of distance
            if abs(o) < 1:
                return half if o >= 0 else half - 1
            n = int(abs(o))
            return min(EYE - 1, half + n) if o > 0 else max(0, half - 1 - n)

        for x, y, strength in lures:
            k = max(0.0, min(1.0, float(strength))) * gain
            if k <= 0 or not (math.isfinite(x) and math.isfinite(y)):
                continue
            ox, oy = (x - ax) / 2, (y - ay) / 2  # eye cells from the centre
            m = max(abs(ox), abs(oy)) / 7.4
            if m > 1:
                ox, oy = ox / m, oy / m
            cx, cy = cell(ox), cell(oy)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    xx, yy = cx + dx, cy + dy
                    if 0 <= xx < EYE and 0 <= yy < EYE:
                        v = k if dx == dy == 0 else k * 0.4
                        od[yy, xx] = max(od[yy, xx], v)
        return od

    # ------------------------------------------------------------------ one step of the brain
    def step(
        self,
        px: np.ndarray,
        anchor: tuple[float, float] | None = None,
        lures: list[Lure] | None = None,
        feed: bool = False,
    ) -> list[str]:
        cfg = self.cfg
        eye = self.see(px, anchor)
        self.steps += 1
        self.anchor = anchor
        self.lures = list(lures or [])
        prev = self._prev if self._prev is not None else eye
        self._prev = eye
        d = eye - prev  # lamina: temporal contrast
        on, off = np.maximum(d, 0), np.maximum(-d, 0)  # L1 (ON) / L2 (OFF)
        k = self.TAU_DELAY
        dl_on = self._delay_on = self._delay_on * (1 - k) + on * k
        dl_off = self._delay_off = self._delay_off * (1 - k) + off * k

        def emd(x: np.ndarray, dl: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            # Hassenstein–Reichardt: rightward = delayed(left neighbour) × now(right) − mirror
            h = dl[:, :-1] * x[:, 1:] - x[:, :-1] * dl[:, 1:]
            v = dl[:-1, :] * x[1:, :] - x[:-1, :] * dl[1:, :]  # downward positive
            return h, v

        h1, v1 = emd(on, dl_on)  # T4
        h2, v2 = emd(off, dl_off)  # T5
        h, v = h1 + h2, v1 + v2
        gain = 40.0
        s = self.state
        s.eye = eye
        s.hs_right = float(np.maximum(h, 0).mean() * gain)
        s.hs_left = float(np.maximum(-h, 0).mean() * gain)
        s.vs_down = float(np.maximum(v, 0).mean() * gain)
        s.vs_up = float(np.maximum(-v, 0).mean() * gain)

        # LPLC2: outward motion on each side of the centre = expansion (something coming at the fly)
        c = EYE // 2
        loom_l = float(np.maximum(-h[:, : c - 1], 0).mean())  # left half moving further left
        loom_r = float(np.maximum(h[:, c:], 0).mean())
        loom_u = float(np.maximum(-v[: c - 1, :], 0).mean())
        loom_d = float(np.maximum(v[c:, :], 0).mean())
        s.looming = (
            min(loom_l, loom_r, loom_u, loom_d) * gain * 4 + (loom_l + loom_r + loom_u + loom_d) * gain * 0.25
        ) * cfg.looming

        # phototaxis: steer towards the strongest nearby light. A fly commits to one source; averaging two
        # lights would leave it hovering between them.
        ys, xs = np.mgrid[0:EYE, 0:EYE]
        w = eye.copy()
        w[c - 1 : c + 1, c - 1 : c + 1] = 0  # ignore its own body
        w = np.maximum(w - w.mean(), 0)
        dist = np.hypot(xs - c + 0.5, ys - c + 0.5)
        score = w / (1.0 + 0.35 * dist)
        # smell: the game's goal cue is an odour source; it joins the light map (and fades less with distance)
        od = self.smell(self.lures, anchor, cfg.lure)
        taste = float(od[c - 1 : c + 1, c - 1 : c + 1].max()) / max(cfg.lure, 1e-6)  # under its feet
        od[c - 1 : c + 1, c - 1 : c + 1] = 0  # already there
        s.odour = od
        smelled = float(od.max()) > 0
        if smelled:
            score = score + od * self.ODOUR_WEIGHT / (1.0 + 0.05 * dist)
            w = w + od * self.ODOUR_WEIGHT
        odour_at = 0.0
        if float(score.max()) > 0.02:
            py, pxi = np.unravel_index(int(np.argmax(score)), score.shape)
            odour_at = float(od[py, pxi]) if smelled else 0.0
            near = (np.hypot(xs - pxi, ys - py) <= 1.5) * w  # the chosen light's own spot
            tot = float(near.sum()) or 1.0
            lx = float((near * (xs - c + 0.5)).sum() / tot) / c
            ly = float((near * (ys - c + 0.5)).sum() / tot) / c
        else:
            lx = ly = 0.0
        s.light = (lx, ly)

        # descending neurons: light attraction + saccade away from the looming side + a little spontaneous noise
        side_loom = (loom_r - loom_l) * gain * 3 * cfg.looming  # expansion on the right → turn left
        vert_loom = (loom_d - loom_u) * gain * 3 * cfg.looming
        # the pull follows the light's direction, not its distance (otherwise it would stall just short of it)
        n = math.hypot(lx, ly)
        ux, uy = (lx / n, ly / n) if n > 1e-3 else (0.0, 0.0)
        pull = cfg.phototaxis + self.ODOUR_PULL * min(1.5, odour_at)
        om = 0.15 * cfg.motion
        drive = {
            "left": max(0.0, -ux) * pull + max(0.0, side_loom) + s.hs_left * om,
            "right": max(0.0, ux) * pull + max(0.0, -side_loom) + s.hs_right * om,
            "up": max(0.0, -uy) * pull + max(0.0, vert_loom) + s.vs_up * om,
            "down": max(0.0, uy) * pull + max(0.0, -vert_loom) + s.vs_down * om,
        }
        leak, threshold, noise = cfg.leak, cfg.threshold, cfg.noise
        spikes: list[str] = []
        for n in DNS:
            if self._refractory[n] > 0:
                self._refractory[n] -= 1
                self._v[n] *= leak
                continue
            self._v[n] = self._v[n] * leak + drive[n] + self.rng.uniform(0, noise)
            if self._v[n] >= threshold:
                spikes.append(n)
                self._v[n] = 0.0
                self._refractory[n] = cfg.refractory
        # opposite directions inhibit each other: keep the stronger one
        for a, b in (("left", "right"), ("up", "down")):
            if a in spikes and b in spikes:
                spikes.remove(b if drive[a] >= drive[b] else a)

        # giant fibre: escape on strong looming
        if self._refractory["a"] > 0:
            self._refractory["a"] -= 1
        self._gf = self._gf * 0.6 + s.looming * 0.9 * cfg.escape
        if self._gf >= self.GF_THRESHOLD and self._refractory["a"] == 0:
            spikes.append("a")
            self._gf = 0.0
            self._refractory["a"] = 4
        # proboscis extension: standing on the sugar for a moment → feed (key A)
        if self._per_rest > 0:
            self._per_rest -= 1
        self._per = self._per * 0.5 + (taste if feed else 0.0)
        if feed and self._per >= 0.9 and self._per_rest == 0 and "a" not in spikes:
            spikes.append("a")
            self._per = 0.0
            self._per_rest = 3 + cfg.refractory
        s.dn = {n: min(1.0, self._v[n] / threshold) for n in DNS}
        s.gf = min(1.0, self._gf / self.GF_THRESHOLD)
        s.spikes = spikes
        s.on, s.off = on, off
        s.motion_h = np.pad(h, ((0, 0), (0, 1)))
        s.motion_v = np.pad(v, ((0, 1), (0, 0)))
        self.keylog.extend((self.steps, k) for k in spikes)
        return spikes

    def snapshot(self) -> dict[str, Any]:
        """What the brain is doing right now, as JSON for the studio (GET /api/fly). Never drawn on the panel."""
        s = self.state
        r3 = lambda v: round(float(v), 3)  # noqa: E731
        return {
            "step": self.steps,
            "eye": _u8(s.eye, 255),
            "on": _u8(s.on, 1200),
            "off": _u8(s.off, 1200),
            "mh": _s8(s.motion_h, 900),
            "mv": _s8(s.motion_v, 900),
            "hs": {"left": r3(s.hs_left), "right": r3(s.hs_right), "up": r3(s.vs_up), "down": r3(s.vs_down)},
            "looming": r3(s.looming),
            "gf": r3(s.gf),
            "dn": {k: r3(v) for k, v in s.dn.items()},
            "light": [r3(s.light[0]), r3(s.light[1])],
            "spikes": list(s.spikes),
            "keys": [[n, k] for n, k in self.keylog],
            "anchor": None if self.anchor is None else [r3(self.anchor[0]), r3(self.anchor[1])],
            "lures": [[r3(x), r3(y), r3(k)] for x, y, k in self.lures[:8]],
            "odour": _u8(s.odour, 255 / 3),
            "preset": self.cfg.preset,
        }
