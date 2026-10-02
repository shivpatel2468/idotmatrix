"""Animated test "videos" for the calibration wizard and the motion lab (docs/CALIBRATION.md).

Everything here is pure and deterministic: a frame is a function of the time `t` (and the options), so the
engine can stream it to the panel and the studio preview shows the very same frame (like-for-like).

* Calibration videos are drawn at a given width so the A/B layout can show the same content twice, side by
  side: the left half through candidate A, the right half through candidate B. They change slowly
  (`CAL_FPS`): on a 32x32 panel a calm image is what you compare colours on, and the frames stay within a
  few BLE packets (tests pin the size).
* Motion tests (`MOTION_TESTS`) move something across the panel at a chosen frame rate and speed. Two
  configs can share the panel (stacked top/bottom, or alternating every few seconds) so the user picks the
  smoother one. Stream rates stay within the link's verified ceiling (docs/HARDWARE_PROTOCOL.md #4, #9, #13).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import numpy as np

from .calib import PanelCalibration
from .calib import apply as apply_calibration
from .color import RGB, hsv, mix
from .font import measure
from .frame import Frame

#: Calibration videos update at this rate: calm motion, small frames, well under the link ceiling.
CAL_FPS = 4.0
#: The motion lab never streams faster than this (above ~9-12 fps the BLE link only drops frames).
MOTION_MAX_FPS = 12.0
MOTION_MIN_FPS = 3.0
#: Baked GIF loops play natively; the verified smooth range tops out at 10 fps (HARDWARE_PROTOCOL.md #11, #13).
CLIP_MAX_FPS = 10.0
CLIP_MAX_FRAMES = 96

Draw = Callable[[Frame, int, float], None]


# =================================================================== calibration videos
def _bars(f: Frame, w: int, t: float) -> None:
    """Moving colour bars: seven saturated bars stacked, drifting down one row every half second."""
    cols: list[RGB] = [
        (255, 255, 255),
        (255, 220, 0),
        (0, 220, 255),
        (0, 230, 60),
        (255, 0, 200),
        (255, 20, 20),
        (30, 60, 255),
    ]
    off = int(t * 2) % 28
    for y in range(28):
        band = ((y - off) % 28) // 4
        f.hline(0, y, w, cols[band])
    for x in range(w):  # a grey ramp along the bottom: saturation must not tint it
        v = round(255 * x / max(1, w - 1))
        f.vline(x, 28, 4, (v, v, v))


def _ramp(f: Frame, w: int, t: float) -> None:
    """Grey ramp sweep: an 8-step staircase on top, a smooth ramp sweeping up underneath."""
    step = max(1, w // 8)
    for k in range(8):
        v = round(255 * (k + 1) / 8)
        f.rect(k * step, 2, step, 13, (v, v, v))
    k = int(t * 1.5) % 8  # a marker walks along the steps so the eye visits each one
    f.hline(k * step, 0, step, (255, 72, 24))
    off = (t * 3.0) % 16
    for y in range(16):
        v = round(255 * (((15 - y) + off) % 16) / 15)
        f.hline(0, 16 + y, w, (v, v, v))


def _skin(f: Frame, w: int, t: float) -> None:
    """Skin tones from light to deep, gently shaded, with a slow breathing highlight."""
    tones: list[RGB] = [(250, 215, 185), (226, 172, 125), (190, 125, 85), (120, 75, 50)]
    glow = 0.5 + 0.5 * math.sin(t * 1.3)
    for i, c in enumerate(tones):
        for y in range(8):
            shade = 1.0 - 0.28 * (y / 7) + 0.06 * glow
            f.hline(0, i * 8 + y, w, tuple(max(0, min(255, round(v * shade))) for v in c))  # type: ignore[arg-type]


def _sky(f: Frame, w: int, t: float) -> None:
    """Sky gradient: deep blue to pale horizon, a low orange glow, grass, and a slowly arcing sun."""
    stops: list[tuple[float, RGB]] = [
        (0.0, (10, 40, 140)),
        (0.45, (60, 150, 235)),
        (0.75, (190, 225, 245)),
        (0.88, (255, 170, 90)),
    ]
    for y in range(28):
        p = y / 27
        for (p0, c0), (p1, c1) in itertools.pairwise(stops):
            if p0 <= p <= p1:
                f.hline(0, y, w, mix(c0, c1, (p - p0) / (p1 - p0)))
                break
        else:
            f.hline(0, y, w, stops[-1][1])
    f.rect(0, 28, w, 4, (40, 150, 50))
    a = (t * 0.25) % 1.0
    sx = round(2 + (w - 5) * a)
    sy = round(18 - 12 * math.sin(math.pi * a))
    f.circle(sx, sy, 2, (255, 230, 120))


def _wheel(f: Frame, w: int, t: float) -> None:
    """A colour wheel spinning slowly: 12 hues around, three saturation rings."""
    cx, cy = (w - 1) / 2, 15.5
    r = min(w, 32) / 2 - 0.5
    rot = t * 0.2
    for y in range(32):
        for x in range(w):
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy)
            if d > r:
                continue
            sector = math.floor(((math.atan2(dy, dx) / (2 * math.pi) + rot) % 1.0) * 12) / 12
            ring = 0.35 if d < r * 0.34 else 0.7 if d < r * 0.67 else 1.0
            f.set(x, y, hsv(sector, ring, 1.0))


def _pulse(f: Frame, w: int, t: float) -> None:
    """Black and white level check: near-black patches, one patch pulsing through the shadows, near-whites."""
    levels = (2, 4, 6, 9, 12, 16, 20, 26)
    cols = 2 if w < 24 else 4
    pw = w // cols
    for i, v in enumerate(levels):
        x, y = (i % cols) * pw, (i // cols) * (6 if cols == 2 else 8)
        f.rect(x + 1, y + 1, pw - 2, (5 if cols == 2 else 7) - 1, (v, v, v))
    p = 0.5 - 0.5 * math.cos(t * 1.2)  # 0 -> 1 -> 0
    v = round(30 * p)
    f.rect(1, 25 - (1 if cols == 2 else 0), w - 2, 2, (v, v, v))
    for i, wv in enumerate((236, 246, 255)):  # white clipping check along the bottom
        seg = w // 3
        f.rect(i * seg, 28, seg if i < 2 else w - 2 * seg, 4, (wv, wv, wv))


def _white(f: Frame, w: int, t: float) -> None:
    """Neutral greys for white balance: white, light, mid and dark grey, with a small live dot."""
    for i, v in enumerate((255, 200, 140, 80)):
        f.rect(0, i * 8, w, 8, (v, v, v))
    x = int(t * 2) % w
    f.set(x, 31, (255, 72, 24))


def _card(f: Frame, w: int, t: float) -> None:
    """A mixed test card: rainbow, greys, skin and sky together (for the before/after check)."""
    off = t * 0.08
    for x in range(w):
        f.vline(x, 0, 8, hsv(x / w + off))
    step = max(1, w // 8)
    for k in range(8):
        v = round(255 * (k + 1) / 8)
        f.rect(k * step, 9, step, 5, (v, v, v))
    half = w // 2
    for y in range(15, 32):
        f.hline(0, y, half, mix((250, 210, 175), (170, 110, 70), (y - 15) / 16))
        f.hline(half, y, w - half, mix((30, 80, 190), (170, 215, 245), (y - 15) / 16))


@dataclass(frozen=True)
class Video:
    id: str
    name: str
    hint: str
    draw: Draw


CAL_VIDEOS: dict[str, Video] = {
    v.id: v
    for v in (
        Video("bars", "Moving colour bars", "Saturated primaries and a grey ramp", _bars),
        Video("ramp", "Grey ramp sweep", "Even steps from black to white", _ramp),
        Video(
            "pulse", "Black & white levels", "Near-black patches and one pulsing through the shadows", _pulse
        ),
        Video("white", "Neutral greys", "White and greys: no tint wanted", _white),
        Video("skin", "Skin tones", "Light to deep skin, gently shaded", _skin),
        Video("sky", "Sky gradient", "Blue sky, horizon glow and a moving sun", _sky),
        Video("wheel", "Colour wheel spin", "Twelve hues in three saturation rings", _wheel),
        Video("card", "Everything card", "Rainbow, greys, skin and sky together", _card),
    )
}
CalVideoName = Literal["bars", "ramp", "pulse", "white", "skin", "sky", "wheel", "card"]


def video_frame(video: str, t: float, width: int = 32) -> Frame:
    """The reference content of a calibration video (what the computer screen shows), `width` columns wide."""
    f = Frame()
    CAL_VIDEOS[video].draw(f, max(4, min(32, width)), t)
    if width < 32:
        f.rect(width, 0, 32 - width, 32, (0, 0, 0))
    return f


def _tag(f: Frame, x: int, y: int, s: str, right: bool = False) -> None:
    w = measure(s) + 2
    if right:
        x -= w
    f.rect(x, y, w, 7, (0, 0, 0))
    f.text(x + 1, y + 1, s, (255, 255, 255))


# =================================================================== motion tests
@dataclass(frozen=True)
class MotionCfg:
    fps: float = 8.0
    speed: float = 8.0  # pixels per second
    soft: bool = False  # sub-pixel edges (fractional coverage) for shapes; text always stays 1-bit
    smoothing: float = 0.0  # temporal smoothing of streamed data (EMA weight of the previous frame)
    transition: Literal["cut", "push", "fade", "wipe"] = "cut"


def _q(t: float, fps: float) -> float:
    """Time as the panel sees it at `fps`: frames only change on frame boundaries."""
    return math.floor(t * fps + 1e-6) / fps


def _blob(f: Frame, cx: float, cy: float, r: float, color: RGB, soft: bool, y0: int, h: int) -> None:
    if not soft:
        cx, cy = round(cx), round(cy)
    for y in range(max(y0, math.floor(cy - r - 1)), min(y0 + h, math.ceil(cy + r + 2))):
        for x in range(max(0, math.floor(cx - r - 1)), min(32, math.ceil(cx + r + 2))):
            d = math.hypot(x - cx, y - cy)
            a = max(0.0, min(1.0, r + 0.5 - d)) if soft else (1.0 if d <= r else 0.0)
            if a > 0:
                f.blend(x, y, color, a)


def _vbar(f: Frame, x: float, w: float, color: RGB, soft: bool, y0: int, h: int) -> None:
    if not soft:
        x = round(x)
    for px in range(max(0, math.floor(x)), min(32, math.ceil(x + w))):
        a = max(0.0, min(1.0, min(px + 1, x + w) - max(px, x)))
        if a > 0:
            for y in range(y0, y0 + h):
                f.blend(px, y, color, a)


_UFO = ("..##..", ".#..#.", "######", ".#.#.#")
_UFO_COL = {"#": (0, 220, 255)}


def _ufo_sprite(f: Frame, x: float, y: int, soft: bool) -> None:
    if soft:
        xi = math.floor(x)
        frac = x - xi
    else:
        xi, frac = round(x), 0.0
    for r, row in enumerate(_UFO):
        for c, ch in enumerate(row):
            if ch != "#":
                continue
            col = (255, 214, 0) if r == 3 else _UFO_COL["#"]
            f.blend(xi + c, y + r, col, 1.0 - frac)
            if frac:
                f.blend(xi + c + 1, y + r, col, frac)


def _tri(t: float, period: float) -> float:
    """Triangle wave 0 -> 1 -> 0 over `period`."""
    p = (t / period) % 1.0
    return 2 * p if p < 0.5 else 2 - 2 * p


def _noise(i: int, n: int) -> float:
    v = math.sin(i * 12.9898 + n * 78.233) * 43758.5453
    return v - math.floor(v)


def _m_scroll(f: Frame, t: float, c: MotionCfg, y0: int, h: int) -> None:
    text = "DESKDOT SMOOTH MOTION  "
    tw = measure(text, "small")
    x = 32 - (_q(t, c.fps) * c.speed) % (tw + 32)
    f.text(round(x), y0 + (h - 7) // 2, text, (255, 255, 255), font="small", clip=(0, y0, 31, y0 + h - 1))


def _m_ball(f: Frame, t: float, c: MotionCfg, y0: int, h: int) -> None:
    r = 2.0 if h < 24 else 3.0
    tq = _q(t, c.fps)
    span_x = 31 - 2 * r
    period = 2 * span_x / max(0.5, c.speed)
    cx = r + span_x * _tri(tq, period)
    bounce = abs(math.sin(math.pi * tq / (period / 2)))
    cy = y0 + (h - 1 - r) - (h - 1 - 2 * r) * bounce
    f.hline(0, y0 + h - 1, 32, (28, 28, 40))
    _blob(f, cx, cy, r, (255, 72, 24), c.soft, y0, h)


def _m_ufo(f: Frame, t: float, c: MotionCfg, y0: int, h: int) -> None:
    for x in range(0, 32, 4):  # a still track: the eye tracks the UFO against it (pursuit test)
        f.set(x, y0 + h - 2, (40, 40, 60))
        f.set(x + 2, y0 + 1, (40, 40, 60))
    span = 32 + 7
    x = (_q(t, c.fps) * c.speed) % span - 6
    _ufo_sprite(f, x, y0 + (h - 4) // 2, c.soft)


def _m_pan(f: Frame, t: float, c: MotionCfg, y0: int, h: int) -> None:
    off = _q(t, c.fps) * c.speed
    for x in range(32):
        f.vline(x, y0, h, hsv((x + off) / 32 if c.soft else (x + round(off)) / 32))


def _m_sweep(f: Frame, t: float, c: MotionCfg, y0: int, h: int) -> None:
    period = 2 * 30 / max(0.5, c.speed)
    x = 30 * _tri(_q(t, c.fps), period)
    _vbar(f, x, 2.0, (255, 255, 255), c.soft, y0, h)


def _m_live(f: Frame, t: float, c: MotionCfg, y0: int, h: int) -> None:
    """Jittery live data (like a visualiser), smoothed the way the engine smooths streams."""
    fps = max(1.0, c.fps)
    n = math.floor(t * fps + 1e-6)
    s = max(0.0, min(0.9, c.smoothing))
    for b in range(8):
        acc, wsum = 0.0, 0.0
        for k in range(12 if s else 1):
            wk = (1 - s) * s**k if s else 1.0
            acc += wk * _noise(b, n - k)
            wsum += wk
        v = acc / wsum
        bh = max(1, round(v * (h - 2)))
        f.rect(b * 4, y0 + h - bh, 3, bh, hsv(0.33 - 0.33 * v))


def _m_transition(f: Frame, t: float, c: MotionCfg, y0: int, h: int) -> None:
    from ..engine.overlay import transition  # the engine's own transition renderer

    scene = int(t // 2.0)
    p = (t % 2.0) / 0.4  # each switch takes TRANSITION_SECONDS (0.4 s)
    old, new = _scene(scene - 1), _scene(scene)
    out = (
        new
        if p >= 1 or c.transition == "cut"
        else transition(old, new, _q(p * 0.4, c.fps) / 0.4, c.transition)
    )
    f.px[y0 : y0 + h] = out.px[(32 - h) // 2 : (32 - h) // 2 + h]


def _scene(k: int) -> Frame:
    return _scene_cached(k % 2).copy()


@lru_cache(maxsize=2)
def _scene_cached(k: int) -> Frame:
    f = Frame()
    if k == 0:
        f.clear((10, 10, 16))
        f.text_center(12, "12:34", (255, 72, 24), font="small")
    else:
        f.gradient_v((0, 40, 120), (0, 140, 200))
        f.circle(16, 16, 6, (255, 214, 0))
    return f


@dataclass(frozen=True)
class MotionTest:
    id: str
    name: str
    hint: str
    draw: Callable[[Frame, float, MotionCfg, int, int], None]
    period: Callable[[MotionCfg], float]  # seconds per seamless loop (for baking)


MOTION_TESTS: dict[str, MotionTest] = {
    m.id: m
    for m in (
        MotionTest(
            "ufo",
            "Pursuit UFO",
            "Follow the UFO with your eyes: blur or doubled edges = judder",
            _m_ufo,
            lambda c: 39 / max(0.5, c.speed),
        ),
        MotionTest(
            "ball",
            "Bouncing ball",
            "Watch the arc: it should glide, not hop",
            _m_ball,
            lambda c: 2 * (31 - 6) / max(0.5, c.speed),
        ),
        MotionTest(
            "scroll",
            "Scrolling text",
            "Read it as it moves: letters should not stutter",
            _m_scroll,
            lambda c: (measure("DESKDOT SMOOTH MOTION  ", "small") + 32) / max(0.5, c.speed),
        ),
        MotionTest(
            "sweep",
            "Sweeping bar",
            "A bar sweeps across: look for steps or skipped columns",
            _m_sweep,
            lambda c: 60 / max(0.5, c.speed),
        ),
        MotionTest(
            "pan",
            "Gradient pan",
            "A full-screen rainbow pans: the heaviest frames, a link stress test",
            _m_pan,
            lambda c: 32 / max(0.5, c.speed),
        ),
        MotionTest(
            "live",
            "Live data",
            "Jittery bars like a visualiser: smoothing calms them",
            _m_live,
            lambda c: 4.0,
        ),
        MotionTest(
            "transition",
            "App transitions",
            "Two screens swap every 2 s with the chosen transition",
            _m_transition,
            lambda c: 4.0,
        ),
    )
}
MotionTestName = Literal["ufo", "ball", "scroll", "sweep", "pan", "live", "transition"]


def motion_frame(test: str, t: float, cfg: MotionCfg, y0: int = 0, h: int = 32) -> Frame:
    f = Frame()
    MOTION_TESTS[test].draw(f, t, cfg, y0, h)
    return f


# =================================================================== test cards (what the engine runs)
@dataclass
class CalCard:
    """A calibration video on the panel. `a` alone: full screen. `a` + `b`: layout "ab" shows the same content
    in both halves (A left, B right); layout "wipe" splits one full-width video at column `split` (before/after).
    """

    video: str
    a: PanelCalibration
    b: PanelCalibration | None = None
    layout: Literal["ab", "wipe"] = "ab"
    split: int = 16
    labels: tuple[str, str] | None = None
    fps: float = CAL_FPS
    kind: str = "calibration"

    @property
    def name(self) -> str:
        return f"video:{self.video}"

    def frames(self, t: float) -> tuple[Frame, Frame]:
        """(reference for the screen, frame for the panel)."""
        tq = _q(t, self.fps)
        if self.b is None:
            ref = video_frame(self.video, tq)
            return ref, Frame(apply_calibration(ref.px, self.a))
        if self.layout == "ab":
            half = video_frame(self.video, tq, 16)
            ref = half.copy()
            ref.px[:, 16:] = half.px[:, :16]
            pan = Frame(
                np.concatenate(
                    [apply_calibration(half.px[:, :16], self.a), apply_calibration(half.px[:, :16], self.b)],
                    axis=1,
                )
            )
            split = 16
        else:
            ref = video_frame(self.video, tq)
            split = max(0, min(32, self.split))
            pan = Frame(
                np.concatenate(
                    [
                        apply_calibration(ref.px[:, :split], self.a),
                        apply_calibration(ref.px[:, split:], self.b),
                    ],
                    axis=1,
                )
            )
            for fr in (ref, pan):  # a small tick marks the split at the top and bottom edge
                if 0 < split < 32:
                    fr.set(split, 0, (255, 72, 24))
                    fr.set(split, 31, (255, 72, 24))
        if self.labels:
            for fr in (ref, pan):
                if split >= 8:
                    _tag(fr, 0, 0, self.labels[0])
                if split <= 24:
                    _tag(fr, 32, 0, self.labels[1], right=True)
        return ref, pan


@dataclass
class MotionCard:
    """A motion test. `b` set: two configs share the panel — "stack" (A on top, B below) or "alternate"
    (A, then B, `ALT_SECONDS` each, labelled). Streams at the faster config's rate."""

    test: str
    a: MotionCfg
    b: MotionCfg | None = None
    layout: Literal["stack", "alternate"] = "stack"
    labels: bool = True
    panel: PanelCalibration = field(default_factory=PanelCalibration)
    kind: str = "motion"

    ALT_SECONDS = 4.0

    @property
    def name(self) -> str:
        return f"motion:{self.test}"

    @property
    def fps(self) -> float:
        rates = [self.a.fps] + ([self.b.fps] if self.b else [])
        return max(MOTION_MIN_FPS, min(MOTION_MAX_FPS, max(rates)))

    def _cfg(self, c: MotionCfg) -> MotionCfg:
        return MotionCfg(
            fps=max(MOTION_MIN_FPS, min(MOTION_MAX_FPS, c.fps)),
            speed=max(1.0, min(24.0, c.speed)),
            soft=c.soft,
            smoothing=max(0.0, min(0.6, c.smoothing)),
            transition=c.transition,
        )

    def frames(self, t: float) -> tuple[Frame, Frame]:
        a = self._cfg(self.a)
        if self.b is None:
            ref = motion_frame(self.test, t, a)
        elif self.layout == "stack":
            b = self._cfg(self.b)
            ref = motion_frame(self.test, t, a, 0, 16)
            ref.px[16:] = motion_frame(self.test, t, b, 16, 16).px[16:]
            ref.hline(0, 15, 32, (0, 0, 0))
            if self.labels:
                _tag(ref, 32, 0, "A", right=True)
                _tag(ref, 32, 16, "B", right=True)
        else:
            which = int(t // self.ALT_SECONDS) % 2
            ref = motion_frame(self.test, t, a if which == 0 else self._cfg(self.b))
            if self.labels:
                _tag(ref, 32, 0, "AB"[which], right=True)
        pan = ref if self.panel.identity else Frame(apply_calibration(ref.px, self.panel))
        return ref, pan

    def clip(self) -> tuple[list[Frame], list[int]]:
        """One seamless loop of config A for native GIF playback (<= 10 fps, <= 96 frames)."""
        a = self._cfg(self.a)
        fps = min(CLIP_MAX_FPS, a.fps)
        a = MotionCfg(fps=fps, speed=a.speed, soft=a.soft, smoothing=a.smoothing, transition=a.transition)
        period = MOTION_TESTS[self.test].period(a)
        n = max(2, min(CLIP_MAX_FRAMES, round(period * fps)))
        frames = [motion_frame(self.test, i / fps, a) for i in range(n)]
        if not self.panel.identity:
            frames = [Frame(apply_calibration(fr.px, self.panel)) for fr in frames]
        return frames, [round(1000 / fps)] * n


@dataclass
class StillCard:
    """A first-generation still test card (`calib.pattern`)."""

    pattern: str
    frame: Frame
    fps: float = 0.0
    kind: str = "still"

    @property
    def name(self) -> str:
        return self.pattern

    def frames(self, t: float) -> tuple[Frame, Frame]:
        return self.frame, self.frame
