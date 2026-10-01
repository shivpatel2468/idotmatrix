"""Smoothness and clarity rules for the creative apps (the "Synthwave treatment").

* Seamless loops: rendering one loop length past the start gives the first frame again, at every speed.
* Even frame durations at <= 10 fps (the fastest GIF rate verified on the panel); speed picks the loop
  length, never stretches the frame duration.
* The baked GIF fits the 40 KB budget at the app's own palette, so the encoder never drops frames.
* Heroes and surfaces stay bright enough to survive the panel's gamma-1.5 calibration.
"""

from __future__ import annotations

import io
import itertools
from typing import Any

import numpy as np
import pytest
from PIL import Image

from deskdot.engine import REGISTRY
from deskdot.gfx import Frame
from deskdot.gfx.calib import PanelCalibration, apply
from deskdot.gfx.image import GIF_BUDGET, encode_gif_budget

USER_PANEL = PanelCalibration(gamma=1.5)  # the user's calibration (docs/HARDWARE_PROTOCOL.md #10)


class Ctx:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def provider(self, name: str) -> Any:
        raise KeyError(name)

    def save(self) -> None: ...
    def invalidate(self) -> None: ...
    def notify(self, **_: Any) -> None: ...


def make(app_id: str, **settings: Any) -> Any:
    cls = REGISTRY[app_id]
    return cls(Ctx(), cls.Settings(**settings))  # type: ignore[arg-type]


# (app, settings) pairs with motion; the slow simulations get one representative variant each
LOOPS: list[tuple[str, dict[str, Any]]] = [
    *[
        ("ambient", {"effect": e, "speed": sp})
        for e in ("plasma", "matrix", "snow", "tunnel", "bounce", "life", "fireworks", "starfield", "embers")
        for sp in (0.2, 0.8, 1.7, 3.0)
    ],
    *[
        ("wireframe", {"shape": sh, "speed": sp})
        for sh in ("tesseract", "torus", "starfighter")
        for sp in (0.5, 1.0, 1.3, 2.0)
    ],
    *[("raycaster", {"speed": sp}) for sp in (0.5, 1.0, 2.0)],
    *[
        ("pixabots", {"character": c, "speed": sp})
        for c in ("sparky", "nyan", "parrot")
        for sp in (0.5, 1.0, 1.4, 2.0)
    ],
    *[
        ("focuspet", {"activity": a, "speed": sp})
        for a in ("focus", "break", "sleep")
        for sp in (0.5, 1.0, 2.0)
    ],
    *[
        ("emotes", {"emote": e, "background": b, "speed": sp})
        for e, b in (("laugh", "rays"), ("party", "hearts"), ("fire", "burst"))
        for sp in (0.25, 1.0, 3.0)
    ],
    ("boids", {}),
    ("boids", {"predator": "on", "speed": 2.0}),
    ("brain", {"mode": "spiral"}),
    ("brain", {"speed": 0.5}),
    ("sand", {}),
    ("sand", {"scenario": "volcano", "speed": 2.0}),
    ("fontlab", {"animation": "scroll"}),
    ("fontlab", {"animation": "wave", "fill": "rainbow", "speed": 1.7}),
    ("fontlab", {"animation": "typewriter", "speed": 0.6}),
    ("fontlab", {"style": "neon", "fill": "stripes"}),
    ("text", {"text": "A LONG MESSAGE THAT MUST SCROLL", "mode": "scroll", "speed": 40}),
    ("text", {"text": "HELLO WORLD", "frame": "glow"}),
    ("playercard", {}),
    ("playercard", {"flip_to_stats": False}),
    ("fiveoclock", {"count": 1, "drink": "cocktail"}),
]


def _ids(cases: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [f"{a}-{'-'.join(f'{k}={v}' for k, v in s.items())}" for a, s in cases]


@pytest.mark.parametrize(("app_id", "settings"), LOOPS, ids=_ids(LOOPS))
def test_loop_is_seamless(app_id: str, settings: dict[str, Any]) -> None:
    """Frame N (one past the end of the baked loop) equals frame 0: the GIF wraps without a jump."""
    app = make(app_id, **settings)
    assert app.kind() == "clip"
    clip = app.clip_frames()  # also fills the simulation caches render() reads
    loop = sum(clip.durations_ms) / 1000
    first, wrapped = Frame(), Frame()
    app.render(first, 0.0)
    app.render(wrapped, loop)
    diff = np.abs(first.px.astype(int) - wrapped.px.astype(int)).max()
    assert diff <= 2, f"the loop jumps (max channel difference {diff})"
    assert first == clip.frames[0]


EVEN = [c for c in LOOPS if c[0] not in ("playercard",)]  # the card holds its pages (merged frames)


@pytest.mark.parametrize(("app_id", "settings"), EVEN, ids=_ids(EVEN))
def test_even_frame_rate_at_most_10fps(app_id: str, settings: dict[str, Any]) -> None:
    clip = make(app_id, **settings).clip_frames()
    assert len(set(clip.durations_ms)) == 1, "an even frame rate"
    assert clip.durations_ms[0] >= 100, "no faster than 10 fps"
    assert 1 <= len(clip.frames) <= 200


@pytest.mark.parametrize(
    "app_id", ["ambient", "wireframe", "pixabots", "focuspet", "emotes", "boids", "brain", "raycaster"]
)
def test_speed_never_stretches_frames(app_id: str) -> None:
    """Speed is applied once — to the loop, not to the frame duration (which would also speed the loop)."""
    durs = {make(app_id, speed=sp).clip_frames().durations_ms[0] for sp in (0.5, 1.0, 2.0)}
    assert len(durs) == 1


HEAVY = [
    ("ambient", {"effect": "plasma", "speed": 0.2}),
    ("ambient", {"effect": "ripple", "speed": 0.2}),
    ("ambient", {"effect": "matrix", "speed": 0.2}),
    ("wireframe", {"shape": "icosahedron", "speed": 0.5}),
    ("wireframe", {"shape": "torus", "speed": 0.5}),
    *[("raycaster", {"theme": th, "speed": 0.5}) for th in ("dungeon", "cyberpunk", "inferno")],
    ("brain", {"mode": "synapse", "speed": 0.5}),
    ("emotes", {"emote": "fire", "speed": 0.25}),
]


@pytest.mark.parametrize(("app_id", "settings"), HEAVY, ids=_ids(HEAVY))
def test_gif_fits_budget_without_dropping_frames(app_id: str, settings: dict[str, Any]) -> None:
    """The heaviest variants fit 40 KB by palette alone: `encode_gif_budget` never has to drop every other
    frame (which would halve the frame rate and bring back the stutter)."""
    app = make(app_id, **settings)
    clip = app.clip_frames()
    frames = [Frame(apply(f.px, USER_PANEL)) for f in clip.frames]  # as the engine sends them
    gif = encode_gif_budget(frames, clip.durations_ms, app.clip_colors)
    assert len(gif) <= GIF_BUDGET, f"{len(gif) / 1024:.1f} KB"
    distinct = 1 + sum(a != b for a, b in itertools.pairwise(frames))  # the encoder merges repeats
    assert Image.open(io.BytesIO(gif)).n_frames == distinct, "the encoder dropped frames to fit the budget"


# ------------------------------------------------------------------ clarity
def test_pixabots_body_survives_the_panel_gamma() -> None:
    from deskdot.apps.pixabots import PALETTES

    for name, pal in PALETTES.items():
        assert max(pal["metal"]) >= 80, f"{name}: the robot body vanishes"
        assert max(pal["metal_dark"]) >= 45, f"{name}: the robot's dark panels vanish"


def test_focuspet_furniture_is_visible() -> None:
    from deskdot.apps.focuspet import THEMES

    for name, th in THEMES.items():
        assert max(th["wood"]) >= 70 and max(th["wood_dark"]) >= 50, name


def test_raycaster_floor_and_walls_are_lit() -> None:
    from deskdot.apps.raycaster import THEME_COLORS

    for name, th in THEME_COLORS.items():
        assert max(th["floor"]) >= 45, name
        assert min(max(th[k]) for k in ("wall_1", "wall_2", "wall_3")) >= 90, name


def test_wireframe_fills_the_panel_without_leaving_it() -> None:
    from deskdot.apps.wireframe import MODELS, SCALE, _project

    for name in MODELS:
        reach = []
        for a in np.linspace(0, 2 * np.pi, 32, endpoint=False):
            _, sx, sy = _project(name, float(a), SCALE[name])
            reach.append(float(np.abs(np.concatenate([sx, sy]) - 15.5).max()))
        assert 11.0 <= max(reach) <= 15.5, f"{name}: furthest vertex {max(reach):.1f} px from the centre"


def test_hourglass_keeps_its_sand_inside_the_glass() -> None:
    from deskdot.apps.sand import PALETTES, SAND

    app = make("sand")
    clip = app.clip_frames()
    sand = np.array(PALETTES["vibrant"][SAND], np.int32)
    for fr in clip.frames:
        px = fr.px.astype(np.int32)
        outside = np.ones((32, 32), bool)
        outside[4:28, 4:28] = False
        grains = (np.abs(px - sand).sum(axis=2) < 60) & outside
        assert not grains.any(), "sand leaked out of the glass"


def test_marquees_move_whole_pixels_at_most_10fps() -> None:
    fl = make("fontlab", animation="scroll")
    _, ms, step = fl._pacing()
    assert (step, ms) == (1, 100), "Font Lab scrolls exactly 1 px per 100 ms frame"
    for speed in (4, 18, 40):
        clip = make("text", text="A LONG MESSAGE THAT MUST SCROLL", mode="scroll", speed=speed).clip_frames()
        assert clip.durations_ms[0] >= 100


def test_playercard_is_a_baked_clip_that_flips_through_black() -> None:
    app = make("playercard")
    assert app.kind() == "clip"
    f = Frame()
    app.render(f, app.settings.page_seconds - 0.05)  # squeezing shut at the end of the front side
    assert not f.px[:, :8].any() and not f.px[:, 24:].any()
