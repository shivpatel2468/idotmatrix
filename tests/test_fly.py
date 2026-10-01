"""The fruit-fly brain (dotdeck.fly) and where it drives things: the Fly Brain app and the games' fly pilot.

The brain is checked against the classic fly-vision experiments it models: direction selectivity of the
lobula-plate cells, looming -> giant-fibre escape, and phototaxis."""

from __future__ import annotations

import io
import math
import time
from typing import Any

import numpy as np
import pytest
from PIL import Image

import dotdeck.apps  # noqa: F401 — registers apps
import dotdeck.apps.flybrain as fb
from dotdeck.engine.app import REGISTRY
from dotdeck.fly import FlyBrain
from dotdeck.gfx import Frame
from dotdeck.gfx.image import encode_gif_budget


def blank() -> np.ndarray:
    return np.zeros((32, 32, 3), np.uint8)


def test_lobula_plate_cells_are_direction_selective() -> None:
    right, left = FlyBrain(1), FlyBrain(1)
    rr = rl = lr = ll = 0.0
    for t in range(24):
        f = blank()
        f[:, t % 30 : t % 30 + 2] = 255  # a bar moving right
        right.step(f)
        rr += right.state.hs_right
        rl += right.state.hs_left
        g = blank()
        x = 31 - t % 30
        g[:, x - 1 : x + 1] = 255  # a bar moving left
        left.step(g)
        lr += left.state.hs_right
        ll += left.state.hs_left
    assert rr > 5 * max(rl, 1e-6), "rightward motion drives HS-right, not HS-left"
    assert ll > 5 * max(lr, 1e-6), "leftward motion drives HS-left, not HS-right"


def test_looming_fires_the_giant_fibre() -> None:
    brain = FlyBrain(1)
    spikes: list[str] = []
    for r in range(1, 13):
        f = blank()
        f[16 - r : 16 + r, 16 - r : 16 + r] = 230  # something coming straight at the fly
        spikes += brain.step(f)
    assert "a" in spikes, "an expanding object triggers the escape jump"
    steady = FlyBrain(1)
    quiet = [k for _ in range(12) for k in steady.step(blank())]
    assert "a" not in quiet, "no escape without looming"


@pytest.mark.parametrize(("x", "expect"), [(27, "right"), (3, "left")])
def test_phototaxis_turns_towards_light(x: int, expect: str) -> None:
    brain = FlyBrain(1)
    f = blank()
    f[14:18, x : x + 3] = 255
    spikes = [k for _ in range(20) for k in brain.step(f)]
    other = "left" if expect == "right" else "right"
    assert spikes.count(expect) >= 3
    assert spikes.count(other) == 0


def test_the_eye_is_centred_on_the_fly() -> None:
    f = blank()
    f[4, 6] = 255
    eye = FlyBrain.see(f, anchor=(6, 4))
    assert eye[7:9, 7:9].max() > 0, "the anchor lands in the middle of the eye"
    FlyBrain.see(f, anchor=(-40, 99))  # an off-screen body doesn't crash the eye


def test_brain_is_fast_and_deterministic() -> None:
    f = (np.random.default_rng(3).random((32, 32, 3)) * 255).astype(np.uint8)
    a, b = FlyBrain(5), FlyBrain(5)
    t0 = time.perf_counter()
    for _ in range(200):
        assert a.step(f, (10, 20)) == b.step(f, (10, 20))
    assert (time.perf_counter() - t0) / 400 < 0.002, "well under the 2 ms render budget"


def test_the_fly_finds_fruit() -> None:
    brain = FlyBrain(3)
    x, y, vx, vy = 20.0, 16.0, 0.0, 0.0
    for _ in range(160):
        world = blank()
        world[:24] = fb.BG
        fb._blob(world, 8.0, 6.0, fb.FRUIT, 1.2)
        for k in brain.step(world, (x, y)):
            vx += {"left": -2.6, "right": 2.6}.get(k, 0.0)
            vy += {"up": -2.6, "down": 2.6}.get(k, 0.0)
        vx, vy = vx * 0.78, vy * 0.78
        x, y = min(30.0, max(1.0, x + vx / 8)), min(22.0, max(1.0, y + vy / 8))
        if math.hypot(x - 8, y - 6) < 2.2:
            return
    raise AssertionError(f"the fly never reached the fruit (ended at {x:.1f}, {y:.1f})")


class Ctx:
    data: dict[str, Any] = {}  # noqa: RUF012

    def save(self) -> None: ...


@pytest.mark.parametrize("danger", ["calm", "normal", "hectic"])
def test_fly_brain_app_bakes_a_seamless_loop(danger: str) -> None:
    fb._READY.clear()
    fb._TELEMETRY.clear()
    app = fb.FlyBrainApp(Ctx(), fb.FlyBrainSettings(danger=danger))  # type: ignore[arg-type]
    clip = app.clip_frames()
    assert len(clip.frames) == fb.N_FRAMES
    assert len(set(clip.durations_ms)) == 1
    assert 1000 / clip.durations_ms[0] <= 10, "at most 10 fps, the panel's verified smooth rate"
    gif = encode_gif_budget(clip.frames, clip.durations_ms, app.clip_colors)
    assert len(gif) <= 40 * 1024
    assert Image.open(io.BytesIO(gif)).n_frames == len(clip.frames), "fits the budget without dropping frames"
    # the seam: the last frame flows into the first, no bigger than a normal step
    steps = [
        np.abs(clip.frames[i].px.astype(int) - clip.frames[i + 1].px.astype(int)).mean()
        for i in range(20, 60)
    ]
    seam = np.abs(clip.frames[0].px.astype(int) - clip.frames[-1].px.astype(int)).mean()
    assert seam <= max(4.0, 3 * float(np.mean(steps)))
    f = Frame()
    t0 = time.perf_counter()
    app.render(f, 1.25)
    assert time.perf_counter() - t0 < 0.002, "render only reads the baked loop"


def test_the_panel_shows_only_the_fly_world() -> None:
    """The brain's activity is for the studio's 3D view; the panel shows just the arena (no bars, no eye inset)."""
    fb._READY.clear()
    fb._TELEMETRY.clear()
    app = fb.FlyBrainApp(Ctx(), fb.FlyBrainSettings(danger="calm"))  # type: ignore[arg-type]
    clip = app.clip_frames()
    for fr in clip.frames[::16]:
        bottom = fr.px[26:32].reshape(-1, 3)
        assert (bottom == fb.BG).all(axis=1).mean() > 0.6, "the bottom rows are arena, not a neuron strip"


def test_fly_brain_app_reports_its_brain_to_the_studio() -> None:
    fb._READY.clear()
    fb._TELEMETRY.clear()
    app = fb.FlyBrainApp(Ctx(), fb.FlyBrainSettings())  # type: ignore[arg-type]
    assert app.fly_telemetry(0.0) is None, "nothing until the loop is baked"
    app.clip_frames()
    snap = app.fly_telemetry(2.0)
    assert snap is not None
    assert len(snap["eye"]) == len(snap["on"]) == len(snap["mh"]) == len(snap["mv"]) == 256
    assert set(snap["dn"]) == {"left", "right", "up", "down"}
    assert snap["world"]["fly"] and len(snap["world"]["fruit"]) == 2
    keys = [k for i in range(fb.N_FRAMES) for _n, k in (app.fly_telemetry(i / fb.FPS) or {})["keys"]]
    assert {"left", "right"} & set(keys), "the keyboard view has key presses to show"
    import json

    assert len(json.dumps(snap)) < 12_000, "small enough to poll ~10 times a second"


def test_snapshot_logs_every_key_press() -> None:
    brain = FlyBrain(1)
    f = blank()
    f[14:18, 27:30] = 255
    fired = [k for _ in range(20) for k in brain.step(f)]
    logged = [k for _n, k in brain.snapshot()["keys"]]
    assert logged == fired[-len(logged) :] and logged


@pytest.mark.parametrize("gid", ["pong", "flappy", "arcade", "cycles", "racer", "tetris"])
def test_the_fly_can_pilot_games(gid: str) -> None:
    cls = REGISTRY[gid]
    app = cls(Ctx(), cls.Settings(pilot="fly"))  # type: ignore[arg-type,call-arg]
    clock = {"t": 1000.0}
    app._clock = lambda: clock["t"]  # type: ignore[method-assign]
    app.reset()
    pressed: list[str] = []
    orig = app.key_p

    def spy(k: str, p: int) -> None:
        pressed.append(k)
        orig(k, p)

    app.key_p = spy  # type: ignore[method-assign]
    worst = 0.0
    for i in range(300):
        clock["t"] += 0.1
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, i / 10)
        worst = max(worst, time.perf_counter() - t0)
    assert pressed, "the fly's descending neurons pressed keys"
    assert app.status()["player"] in ("fly", "ai")
    assert worst < 0.05
    snap = app.fly_telemetry(30.0)
    assert snap is not None and snap["keys"], "the studio sees the keys the fly pressed"


def test_games_report_no_fly_with_the_built_in_ai() -> None:
    cls = REGISTRY["pong"]
    app = cls(Ctx(), cls.Settings())  # type: ignore[arg-type,call-arg]
    for i in range(20):
        app.render(Frame(), i / 10)
    assert app.fly_telemetry(2.0) is None


async def test_a_person_takes_over_from_the_fly() -> None:
    cls = REGISTRY["pong"]
    app = cls(Ctx(), cls.Settings(pilot="fly"))  # type: ignore[arg-type,call-arg]
    clock = {"t": 1000.0}
    app._clock = lambda: clock["t"]  # type: ignore[method-assign]
    app.reset()
    for i in range(30):
        clock["t"] += 0.1
        app.render(Frame(), i / 10)
    await app.action("input", {"key": "up"})
    assert not app._fly_driving(clock["t"]), "a real key press hands control to the person"
    assert app.status()["player"] == "you"


def test_the_built_in_ai_stays_the_default() -> None:
    assert REGISTRY["pong"].Settings().pilot == "ai"  # type: ignore[attr-defined]
