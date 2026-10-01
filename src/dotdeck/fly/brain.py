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

Pure numpy, deterministic for a given seed, well under 1 ms per frame.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

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


class FlyBrain:
    TAU_DELAY = 0.35  # low-pass "delay" arm of the motion detector (frames)
    LEAK = 0.80  # descending-neuron leak per step
    THRESHOLD = 1.0
    GF_THRESHOLD = 1.0
    REFRACTORY = 2  # steps after a spike
    PHOTOTAXIS = (
        0.3  # drive towards light per step (steady state 1.5 × threshold: about one turn every 3 steps)
    )

    def __init__(self, seed: int = 7) -> None:
        self.rng = random.Random(seed)
        self.reset()

    def reset(self) -> None:
        self._prev: np.ndarray | None = None
        self._delay_on = np.zeros((EYE, EYE), np.float32)
        self._delay_off = np.zeros((EYE, EYE), np.float32)
        self._v = dict.fromkeys(DNS, 0.0)
        self._gf = 0.0
        self._refractory = dict.fromkeys((*DNS, "a"), 0)
        self.state = FlyState()

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

    # ------------------------------------------------------------------ one step of the brain
    def step(self, px: np.ndarray, anchor: tuple[float, float] | None = None) -> list[str]:
        eye = self.see(px, anchor)
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
        )

        # phototaxis: steer towards the strongest nearby light. A fly commits to one source; averaging two
        # lights would leave it hovering between them.
        ys, xs = np.mgrid[0:EYE, 0:EYE]
        w = eye.copy()
        w[c - 1 : c + 1, c - 1 : c + 1] = 0  # ignore its own body
        w = np.maximum(w - w.mean(), 0)
        dist = np.hypot(xs - c + 0.5, ys - c + 0.5)
        score = w / (1.0 + 0.35 * dist)
        if float(score.max()) > 0.02:
            py, pxi = np.unravel_index(int(np.argmax(score)), score.shape)
            near = (np.hypot(xs - pxi, ys - py) <= 1.5) * w  # the chosen light's own spot
            tot = float(near.sum()) or 1.0
            lx = float((near * (xs - c + 0.5)).sum() / tot) / c
            ly = float((near * (ys - c + 0.5)).sum() / tot) / c
        else:
            lx = ly = 0.0
        s.light = (lx, ly)

        # descending neurons: light attraction + saccade away from the looming side + a little spontaneous noise
        side_loom = (loom_r - loom_l) * gain * 3  # expansion on the right → turn left
        vert_loom = (loom_d - loom_u) * gain * 3
        # the pull follows the light's direction, not its distance (otherwise it would stall just short of it)
        n = math.hypot(lx, ly)
        ux, uy = (lx / n, ly / n) if n > 1e-3 else (0.0, 0.0)
        pull = self.PHOTOTAXIS
        drive = {
            "left": max(0.0, -ux) * pull + max(0.0, side_loom) + s.hs_left * 0.15,
            "right": max(0.0, ux) * pull + max(0.0, -side_loom) + s.hs_right * 0.15,
            "up": max(0.0, -uy) * pull + max(0.0, vert_loom) + s.vs_up * 0.15,
            "down": max(0.0, uy) * pull + max(0.0, -vert_loom) + s.vs_down * 0.15,
        }
        spikes: list[str] = []
        for n in DNS:
            if self._refractory[n] > 0:
                self._refractory[n] -= 1
                self._v[n] *= self.LEAK
                continue
            self._v[n] = self._v[n] * self.LEAK + drive[n] + self.rng.uniform(0, 0.06)
            if self._v[n] >= self.THRESHOLD:
                spikes.append(n)
                self._v[n] = 0.0
                self._refractory[n] = self.REFRACTORY
        # opposite directions inhibit each other: keep the stronger one
        for a, b in (("left", "right"), ("up", "down")):
            if a in spikes and b in spikes:
                spikes.remove(b if drive[a] >= drive[b] else a)

        # giant fibre: escape on strong looming
        if self._refractory["a"] > 0:
            self._refractory["a"] -= 1
        self._gf = self._gf * 0.6 + s.looming * 0.9
        if self._gf >= self.GF_THRESHOLD and self._refractory["a"] == 0:
            spikes.append("a")
            self._gf = 0.0
            self._refractory["a"] = 4
        s.dn = {n: min(1.0, self._v[n] / self.THRESHOLD) for n in DNS}
        s.gf = min(1.0, self._gf / self.GF_THRESHOLD)
        s.spikes = spikes
        return spikes
