"""The fruit-fly brain (deskdot.fly) and where it drives things: the Fly Brain app and the games' fly pilot.

The brain is checked against the classic fly-vision experiments it models: direction selectivity of the
lobula-plate cells, looming -> giant-fibre escape, and phototaxis."""

from __future__ import annotations

import io
import math
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import deskdot.apps  # noqa: F401 — registers apps
import deskdot.apps.flybrain as fb
from deskdot.config import Config
from deskdot.engine.app import REGISTRY
from deskdot.fly import FlyBrain
from deskdot.fly import config as flycfg
from deskdot.gfx import Frame
from deskdot.gfx.image import encode_gif_budget
from deskdot.server import create_app

PILOT_GAMES = sorted(
    gid for gid, cls in REGISTRY.items() if "pilot" in getattr(cls.Settings, "model_fields", {})
)


@pytest.fixture(autouse=True)
def _default_brain() -> Iterator[None]:
    """Every test starts (and leaves) the shared brain config at its defaults."""
    flycfg.set_current(flycfg.DEFAULT)
    yield
    flycfg.set_current(flycfg.DEFAULT)


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


async def test_the_studio_fly_takes_over_straight_away() -> None:
    cls = REGISTRY["pong"]
    app = cls(Ctx(), cls.Settings(pilot="fly"))  # type: ignore[arg-type,call-arg]
    clock = {"t": 1000.0}
    app._clock = lambda: clock["t"]  # type: ignore[method-assign]
    app.reset()
    await app.action("input", {"key": "up"})  # a person was just playing
    app.open_home()  # and had the menu open
    assert not app._fly_driving(clock["t"])
    await app.action("fly", {})
    assert app._fly_driving(clock["t"]), "clicking the fly hands it the game at once"


# ================================================================= tuning the brain (deskdot.fly.config)
DEFAULT_CONFIG = {
    "phototaxis": 0.3,
    "looming": 1.0,
    "motion": 1.0,
    "leak": 0.8,
    "threshold": 1.0,
    "refractory": 2,
    "noise": 0.06,
    "escape": 1.0,
    "lure": 1.0,
    "preset": "default",
}


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def test_the_default_config_is_the_original_brain() -> None:
    assert flycfg.DEFAULT.model_dump() == DEFAULT_CONFIG


def test_fly_config_api(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.get("/api/fly/config").json() == DEFAULT_CONFIG
        got = c.patch("/api/fly/config", json={"noise": 0.2, "refractory": 4}).json()
        assert got == {**DEFAULT_CONFIG, "noise": 0.2, "refractory": 4, "preset": "custom"}
        assert flycfg.current().noise == 0.2, "every brain reads the new config"
        assert c.get("/api/fly/config").json()["noise"] == 0.2
        assert c.patch("/api/fly/config", json={"noise": 5}).status_code == 422
        assert c.patch("/api/fly/config", json={"refractory": -1}).status_code == 422
        assert c.patch("/api/fly/config", json={"preset": "nope"}).status_code == 422
        assert c.get("/api/fly/config").json()["noise"] == 0.2, "a refused patch changes nothing"
        presets = c.get("/api/fly/presets").json()
        ids = [p["id"] for p in presets]
        assert ids[0] == "default" and {"calm", "curious", "twitchy", "hunter", "daredevil"} <= set(ids)
        for p in presets:
            assert p["name"] and p["description"] and set(p["config"]) == set(DEFAULT_CONFIG)
        calm = next(p for p in presets if p["id"] == "calm")
        assert c.patch("/api/fly/config", json={"preset": "calm"}).json() == calm["config"]
        assert c.patch("/api/fly/config", json={"preset": "default"}).json() == DEFAULT_CONFIG
        c.patch("/api/fly/config", json={"lure": 2.0})
        store = c.app.state.engine.store  # type: ignore[attr-defined]
        assert store.get("fly")["lure"] == 2.0, "kept in state.json"
    store.save_now()
    flycfg.set_current(flycfg.DEFAULT)
    with _client(tmp_path) as c2:
        assert c2.get("/api/fly/config").json()["lure"] == 2.0, "and loaded back at start-up"


def test_stale_stored_config_is_repaired() -> None:
    cfg = flycfg.load({"noise": 9, "leak": 0.9, "bogus": 1})
    assert cfg.noise == 0.06 and cfg.leak == 0.9 and cfg.preset == "custom"
    assert flycfg.load("garbage") == flycfg.DEFAULT


def test_more_noise_means_more_spontaneous_spikes() -> None:
    def spikes(noise: float) -> int:
        brain = FlyBrain(4, config=flycfg.FlyConfig(noise=noise))
        return sum(len(brain.step(blank())) for _ in range(200))

    assert spikes(0.0) == 0, "a dark, still world and no noise: the fly sits still"
    assert spikes(0.5) > 40


def test_the_config_reaches_every_brain() -> None:
    f = blank()
    f[14:18, 27:30] = 255
    keen = flycfg.FlyConfig(phototaxis=0.9, refractory=0)
    brain = FlyBrain(1)
    flycfg.set_current(keen)
    a = sum(len(brain.step(f)) for _ in range(30))
    flycfg.set_current(flycfg.DEFAULT)
    b = sum(len(brain.step(f)) for _ in range(30))
    assert a > b, "a brain made earlier picks up the change on its next step"


def test_the_lure_is_a_smell_the_brain_follows() -> None:
    """A lure is a sensory cue: it pulls the fly through the same phototaxis pathway, scaled by `lure`."""
    sniff = FlyBrain(2)
    keys = [k for _ in range(30) for k in sniff.step(blank(), (16, 16), [(28, 16, 1.0)])]
    assert keys.count("right") >= 5 and keys.count("left") == 0
    snap = sniff.snapshot()
    assert snap["lures"] and max(snap["odour"]) > 0
    flycfg.set_current(flycfg.FlyConfig(lure=0.0))
    anosmic = FlyBrain(2)
    keys = [k for _ in range(30) for k in anosmic.step(blank(), (16, 16), [(28, 16, 1.0)])]
    assert keys.count("right") <= 2, "no sense of smell: the lure does nothing"


def test_a_lure_one_step_away_is_felt_on_either_side() -> None:
    for x, key in ((14, "left"), (18, "right")):
        brain = FlyBrain(5, config=flycfg.FlyConfig(noise=0.0))
        keys = [k for _ in range(12) for k in brain.step(blank(), (16, 16), [(x, 16, 1.0)])]
        assert keys.count(key) >= 2, key


def test_the_feeding_reflex_fires_only_on_the_sugar() -> None:
    brain = FlyBrain(3)
    on = [k for _ in range(12) for k in brain.step(blank(), (10, 10), [(10, 10, 1.0)], feed=True)]
    assert "a" in on
    off = FlyBrain(3)
    away = [k for _ in range(12) for k in off.step(blank(), (10, 10), [(24, 10, 1.0)], feed=True)]
    assert "a" not in away
    nofeed = FlyBrain(3)
    assert "a" not in [k for _ in range(12) for k in nofeed.step(blank(), (10, 10), [(10, 10, 1.0)])]


def test_the_fly_brain_app_rebakes_when_the_config_changes() -> None:
    app = fb.FlyBrainApp(Ctx(), fb.FlyBrainSettings())  # type: ignore[arg-type]
    before = app.clip_key()
    flycfg.set_current(flycfg.FlyConfig(noise=0.3))
    assert app.clip_key() != before
    assert app._key()[-1] == flycfg.tuning_key()


# ================================================================= the fly plays every game
def _fly_game(gid: str) -> tuple[Any, dict[str, float]]:
    cls = REGISTRY[gid]
    app = cls(Ctx(), cls.Settings(pilot="fly"))  # type: ignore[arg-type,call-arg]
    clock = {"t": 1000.0}
    app._clock = lambda: clock["t"]  # type: ignore[method-assign]
    app.reset()
    return app, clock


def _frames(app: Any, clock: dict[str, float], n: int, fps: float = 12.0) -> None:
    for i in range(n):
        clock["t"] += 1 / fps
        app.render(Frame(), i / fps)


def test_every_game_can_be_flown() -> None:
    assert len(PILOT_GAMES) >= 20
    assert {"arcade", "tetris", "pong", "g2048", "tictactoe", "fourup", "digworld"} <= set(PILOT_GAMES)


@pytest.mark.parametrize("gid", PILOT_GAMES)
def test_the_fly_plays_every_game(gid: str) -> None:
    app, clock = _fly_game(gid)
    pressed: list[str] = []
    orig = app.key_p

    def spy(k: str, p: int) -> None:
        pressed.append(k)
        orig(k, p)

    app.key_p = spy  # type: ignore[method-assign]
    worst, anchored, lured = 0.0, 0, 0
    for i in range(300):
        clock["t"] += 1 / 12
        t0 = time.perf_counter()
        app.render(Frame(), i / 12)
        worst = max(worst, time.perf_counter() - t0)
        anchored += app._fly.anchor is not None
        lured += bool(app._fly.lures)
    assert pressed, "the fly's neurons pressed the game's keys"
    assert anchored > 30, "the eye is centred on the fly's own character"
    assert lured > 5, "the game tells the fly where its goal is"
    assert worst < 0.05
    assert app.status()["player"] == "fly"
    snap = app.fly_telemetry(25.0)
    assert snap is not None and snap["keys"], "the studio sees the keys the fly pressed"


def test_the_fly_eats_in_snake() -> None:
    app, clock = _fly_game("arcade")
    for _ in range(600):
        _frames(app, clock, 1)
        if any(s.apples for s in app.snakes):
            return
    raise AssertionError("the fly never reached an apple")


def test_the_fly_returns_the_ball_in_pong() -> None:
    app, clock = _fly_game("pong")
    hits = 0
    orig = app._paddles

    def watch(p: int) -> None:
        nonlocal hits
        before = app.vx
        orig(p)
        hits += before < 0 < app.vx  # the left paddle (seat 1, the fly) sent it back

    app._paddles = watch  # type: ignore[method-assign]
    _frames(app, clock, 900)
    assert hits >= 1


def test_the_fly_stacks_tetris() -> None:
    app, clock = _fly_game("tetris")
    locks: list[int] = []
    orig = app._lock

    def watch(w: Any, p: Any) -> None:
        locks.append(p.seat)
        orig(w, p)

    app._lock = watch  # type: ignore[method-assign]
    _frames(app, clock, 1200)
    assert len(locks) >= 12, "it rotates, slides and drops piece after piece"
    assert app.wells[0].lines >= 1 or app.over_at is None, "it clears lines (or at least hasn't topped out)"


def test_the_fly_plays_board_games() -> None:
    app, clock = _fly_game("tictactoe")
    _frames(app, clock, 400)
    assert app.you, "the fly took the X seat"
    assert sum(app.wins) >= 1, "rounds get played to the end"
    mines, mclock = _fly_game("mines")
    _frames(mines, mclock, 400)
    assert len(mines.shown) >= 10, "the feeding reflex opens safe cells"


def test_taking_the_game_back_stops_reporting_the_fly() -> None:
    cls = REGISTRY["pong"]
    app = cls(Ctx(), cls.Settings(pilot="fly"))  # type: ignore[arg-type,call-arg]
    clock = {"t": 1000.0}
    app._clock = lambda: clock["t"]  # type: ignore[method-assign]
    app.reset()
    for i in range(40):
        clock["t"] += 0.1
        app.render(Frame(), i / 10)
    assert app.status()["player"] == "fly"
    app.settings = cls.Settings(pilot="ai")  # type: ignore[call-arg]
    assert app.status()["player"] == "ai", "the studio's Fly button flips back at once"
