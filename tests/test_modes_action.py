"""Action games (Invaders, Maze Chase, Asteroids, Infinity): modes, maps, themes, results and damage."""

from __future__ import annotations

import time
from typing import Any

import pytest

from dotdeck.apps.games_action import Asteroids, Infinity, Invaders, Maze, invader_shields
from dotdeck.apps.games_core import GameApp
from dotdeck.gfx import Frame

GAMES: dict[str, type[GameApp]] = {
    "invaders": Invaders,
    "maze": Maze,
    "asteroids": Asteroids,
    "infinity": Infinity,
}
FPS = 10


class Clock:
    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t


def _app(engine: Any, gid: str, settings: dict[str, Any] | None = None, seed: int = 1) -> tuple[Any, Clock]:
    engine.store.section("apps")[gid] = settings or {}
    app = engine._slot(gid).app
    assert isinstance(app, GameApp)
    clock = Clock()
    app._clock = clock  # type: ignore[method-assign]
    app.rng.seed(seed)
    app.reset()
    return app, clock


def _run(app: GameApp, clock: Clock, seconds: float, stop: Any = None) -> float:
    """Render `seconds` of wall time; return the worst render time. `stop(app)` ends early."""
    worst = 0.0
    for _ in range(int(seconds * FPS)):
        clock.t += 1 / FPS
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, clock.t)
        worst = max(worst, time.perf_counter() - t0)
        if stop is not None and stop(app):
            break
    return worst


async def _start(app: Any, clock: Clock, mode: str, players: int, map_id: str, ai_only: bool = False) -> None:
    await app.action("start", {"mode": mode, "players": players, "map": map_id})
    if app.flow == "teams":
        await app.action("input", {"key": "a"})  # seat 1 ready; the AI fills the other side
    assert app.flow == "intro"
    clock.t += 3.0
    app.render(Frame(), clock.t)
    assert app.flow == "play"
    if ai_only:
        for r in app.roster.values():
            r["human"] = False


def _seats_in_play(app: Any) -> set[int]:
    if isinstance(app, Invaders):
        return {c["seat"] for c in app.cannons}
    if isinstance(app, Maze):
        return {r["seat"] for r in app.runners} | {g["seat"] for g in app.ghosts if g["seat"] is not None}
    return {s["seat"] for s in app.ships}


CASES = [(gid, m.id, m.max_players) for gid, cls in GAMES.items() for m in cls.modes]
PLAY_CASES = [
    (gid, m.id, m.max_players, mp) for gid, cls in GAMES.items() for m in cls.modes for mp in cls.maps
]
VERSUS = [
    (gid, m.id, m.max_players)
    for gid, cls in GAMES.items()
    for m in cls.modes
    if m.teams in ("ffa", "versus")
]


@pytest.mark.parametrize(("gid", "mode", "n"), CASES)
async def test_mode_reset_fills_seats_with_ai(engine, gid: str, mode: str, n: int) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid)
    await _start(app, clock, mode, n, next(iter(GAMES[gid].maps)))
    assert len(app.roster) == n
    assert app.roster[1]["human"] and not any(app.roster[s]["human"] for s in range(2, n + 1))
    assert _seats_in_play(app) == set(range(1, n + 1)), "every seat has a cannon / ship / runner / ghost"
    assert app.is_human(1) and not any(app.is_human(s) for s in range(2, n + 1))


@pytest.mark.parametrize(("gid", "mode", "n", "map_id"), PLAY_CASES)
async def test_every_mode_and_map_plays_30s(engine, gid: str, mode: str, n: int, map_id: str) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid)
    await _start(app, clock, mode, n, map_id, ai_only=True)
    worst = _run(app, clock, 30)
    assert worst < 0.05, f"{gid}/{mode}/{map_id} render took {worst * 1000:.1f} ms"


FAST = {
    "invaders": {"speed": 10, "duel_waves": 1},
    "maze": {"speed": 10, "hunt_time": 15},
    "asteroids": {"speed": 10, "time_limit": 40},
    "infinity": {"speed": 10, "accel": 1.0},
}


@pytest.mark.parametrize(("gid", "mode", "n"), VERSUS)
async def test_versus_and_ffa_reach_a_result(engine, gid: str, mode: str, n: int) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid, FAST[gid])
    await _start(app, clock, mode, n, next(iter(GAMES[gid].maps)), ai_only=True)
    _run(app, clock, 300, stop=lambda a: a.outcome is not None)
    o = app.outcome
    assert o is not None, f"{gid}/{mode} never called result()"
    assert o["seat"] or o["team"] is not None or o["text"]
    assert o["scores"], "the results screen lists every seat's score"
    _run(app, clock, 1.5)
    assert app.flow == "outro"


def _force_hit(app: Any) -> None:
    if isinstance(app, Invaders):
        c = app.cannons[0]
        c["respawn"] = 0.0
        app.shots = [[c["x"], 28.4]]
    elif isinstance(app, Maze):
        r = app.runners[0]
        g = app.ghosts[0]
        g.update(wait=0.0, eaten=0.0, pos=r["pos"], t=r["t"], dir=r["dir"])
        app.fright = 0.0
    elif isinstance(app, Asteroids):
        s = app.ships[0]
        s["inv"] = 0.0
        app._rock(s["x"], s["y"], 3)
    else:
        s = app.ships[0]
        s.update(y=0.0, ty=0.0, vy=0.0, inv=0.0)


@pytest.mark.parametrize("gid", list(GAMES))
async def test_damage_flash_when_a_human_is_hit(engine, gid: str) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid)
    await _start(app, clock, "solo", 1, next(iter(GAMES[gid].maps)))
    if isinstance(app, Maze):
        app.between = 0.0
    calls: list[float] = []
    orig = app.damage
    app.damage = lambda s=1.0: (calls.append(s), orig(s))  # type: ignore[method-assign]
    _run(app, clock, 0.2)
    _force_hit(app)
    _run(app, clock, 0.3)
    assert calls, f"{gid}: a hit on a human must call damage()"
    assert app.hurt_t > 0


@pytest.mark.parametrize("gid", list(GAMES))
async def test_no_damage_flash_in_attract(engine, gid: str) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, gid, {"skill": 0.0})
    calls: list[float] = []
    app.damage = lambda s=1.0: calls.append(s)  # type: ignore[method-assign]
    _run(app, clock, 25)
    assert not calls, "the self-playing demo never flashes red"


@pytest.mark.parametrize("gid", list(GAMES))
@pytest.mark.parametrize("mode", ["coop"])
async def test_coop_game_over_is_a_shared_score(engine, gid: str, mode: str) -> None:  # type: ignore[no-untyped-def]
    cls = GAMES[gid]
    m = next(m for m in cls.modes if m.teams == "coop")
    app, clock = _app(
        engine,
        gid,
        {"skill": 0.0, "speed": 10, "lives": 1, "ghosts": 4} if gid != "infinity" else {"skill": 0.0},
    )
    await _start(app, clock, m.id, m.max_players, next(iter(cls.maps)), ai_only=True)
    _run(app, clock, 900, stop=lambda a: a.over)
    assert app.over and app.outcome is None, "co-op ends with the team score (no winner)"


def _lum(c: tuple[int, int, int]) -> float:
    """Luma of the colour as sent to the LEDs (Rec. 709 weights on the 8-bit values)."""
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


@pytest.mark.parametrize("gid", list(GAMES))
def test_game_themes_never_camouflage(gid: str) -> None:
    cls = GAMES[gid]
    assert len(cls.game_themes) >= 2
    for tid, th in cls.game_themes.items():
        assert max(th.bg) <= 24 and max(th.bg) - min(th.bg) <= 12, (
            f"{tid}: background must be dark and grey-ish"
        )
        for role in ("p", "e", "x", "hud"):
            c = getattr(th, role)
            assert _lum(c) - _lum(th.bg) >= 0.35, f"{gid}/{tid}.{role} {c} is too close to the background"
        assert _lum(th.w) - _lum(th.bg) >= 0.2 and max(th.w) >= 45, f"{gid}/{tid}: walls must stay visible"
        for c in th.r:
            assert _lum(c) - _lum(th.bg) >= 0.3, f"{gid}/{tid}: tile colour {c} too dark"
        assert tid in cls.game_theme_labels


async def test_maze_maps_change_the_layout(engine) -> None:  # type: ignore[no-untyped-def]
    masks = {}
    for mp in Maze.maps:
        app, _ = _app(engine, "maze")
        app.sel["map"] = mp  # the engine keeps one app per id: pick the map like the home menu does
        app.reset()
        masks[mp] = app.walls.copy()
        # every room reachable
        assert len(app._bfs((0, 0))) == 64, mp
        # no dead ends
        assert all(len(d) >= 2 for d in app.open.values()), mp
        if mp == "boxed":
            assert not any("left" in app.open[(0, y)] for y in range(8)), "boxed maze: no wrap tunnels"
        if mp == "mirror":
            m = app.walls
            for x in range(32):
                assert (m[:, x] == m[:, (32 - x) % 32]).all(), "mirror maze is left/right symmetric"
    assert masks["open"].sum() < masks["boxed"].sum() + 40
    assert len({m.tobytes() for m in masks.values()}) == len(masks)


def test_invader_maps_change_the_cover() -> None:
    layouts = {mp: invader_shields(mp) for mp in Invaders.maps}
    assert not layouts["open"].any()
    assert len({v.tobytes() for v in layouts.values()}) == len(layouts)


async def test_infinity_canyon_has_boulders_and_the_ai_flies_it(engine) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "infinity", {"map": "canyon", "skill": 1.0})
    seen = False
    for _ in range(40):
        _run(app, clock, 0.5)
        seen = seen or any(c[3] >= 0 for c in app.cols)
    assert seen, "the canyon spawns floating boulders"


async def test_hunt_rotates_the_runner(engine) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "maze", {"hunt_time": 15})
    await _start(app, clock, "hunt", 3, "random", ai_only=True)
    runners = [app.runners[0]["seat"]]
    for _ in range(200):
        _run(app, clock, 0.5)
        if app.over:
            break
        if app.runners[0]["seat"] != runners[-1]:
            runners.append(app.runners[0]["seat"])
    assert runners == [1, 2, 3], "each player is the runner once"
    assert app.outcome is not None
