"""World games: Dig World, Neon Heat, Street Surge, Leaf Leap and Four Up.

The shared contract (self-play, themes, hand-over, restart) is covered for every GAME_IDS entry by test_games.py;
these tests pin each game's own promises: the AI actually plays the game, the camera moves in steps, frames stay
small enough to stream, and 2-seat games let a phone drive seat 2 while the AI keeps seat 1.
"""

from __future__ import annotations

from typing import Any

import pytest

from deskdot.apps import games_city, games_connect, games_platform, games_world
from deskdot.apps.games import GAME_IDS
from deskdot.apps.games_core import GameApp
from deskdot.gfx import Frame

NEW = ("digworld", "neonheat", "streetsurge", "leafleap", "fourup")


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


def _run(
    app: GameApp, clock: Clock, seconds: float, fps: float = 8.0, sizes: list[int] | None = None
) -> Frame:
    f = Frame()
    prev: Frame | None = None
    for i in range(int(seconds * fps)):
        clock.t += 1 / fps
        f = Frame()
        app.render(f, i / fps)
        if sizes is not None and (prev is None or f != prev):
            sizes.append(len(f.to_png()))
        prev = f
    return f


def test_registered() -> None:
    for gid in NEW:
        assert gid in GAME_IDS


@pytest.mark.parametrize(("gid", "budget"), [(g, 650 if g == "streetsurge" else 500) for g in NEW])
async def test_frames_stay_small(engine, gid: str, budget: int) -> None:  # type: ignore[no-untyped-def]
    """Streamed frames: most fit one BLE packet (~500 B); the pseudo-3D road is allowed a little more."""
    app, clock = _app(engine, gid)
    sizes: list[int] = []
    _run(app, clock, 20, sizes=sizes)
    assert sum(sizes) / len(sizes) <= budget, f"{gid}: average PNG {sum(sizes) / len(sizes):.0f} B"


# ------------------------------------------------------------------ Dig World
async def test_digworld_world_has_everything(engine) -> None:  # type: ignore[no-untyped-def]
    app, _ = _app(engine, "digworld")
    blocks = {b for row in app.g for b in row}
    for b in (
        games_world.GRASS,
        games_world.DIRT,
        games_world.STONE,
        games_world.COAL,
        games_world.COPPER,
        games_world.GOLD,
        games_world.GEM,
        games_world.WOOD,
        games_world.LEAF,
        games_world.WATER,
        games_world.BEDROCK,
    ):
        assert b in blocks, f"block {b} missing from the generated world"
    caves = sum(
        1
        for r, row in enumerate(app.g)
        for c, b in enumerate(row)
        if b == games_world.AIR and r > app.surface[c] + 3
    )
    assert caves > 20, "the generator carves caves"


@pytest.mark.parametrize("seed", [1, 2, 3])
async def test_digworld_ai_mines_then_builds_a_house(engine, seed: int) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "digworld", seed=seed)
    cams = set()
    for _ in range(24):
        _run(app, clock, 1)
        cams.add((app.cam_c, app.cam_r))
    assert app.score > 0, "the miner dug some ore"
    assert app.house is not None and app.mode in ("build", "sleep"), "dusk: a house is built"
    hc, hr = app.house
    placed = sum(
        1
        for r in range(hr - 4, hr + 2)
        for c in range(hc - 3, hc + 4)
        if app.g[r][c] in (games_world.PLANK, games_world.ROOF, games_world.GLASS)
    )
    assert placed >= 8
    assert hr < app.surface[hc], "the house stands under open sky, not down a shaft"
    # the camera only ever jumps in half-screen steps (or clamps at the world edge)
    for c, r in cams:
        assert c % 8 == app.cam_c % 8 or c in (0, games_world.WW - games_world.VW)
        assert 0 <= r <= games_world.WH - games_world.VW


async def test_digworld_human_digs_and_places(engine) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "digworld")
    _run(app, clock, 0.5)
    c, r = app.mc, app.mr
    await app.action("input", {"key": "down"})
    _run(app, clock, 1.0)
    assert app.mr > r, "down digs and the miner drops into the hole"
    await app.action("input", {"key": "b"})
    assert app.build_mode
    inv = app.inv
    await app.action("input", {"key": "left"})
    _run(app, clock, 0.3)
    await app.action("input", {"key": "a"})
    _run(app, clock, 0.5)
    assert app.inv == inv - 1 or app.g[app.mr][app.mc - 1] in games_world.SOLID
    assert app.status()["player"] == "you" and c >= 0


# ------------------------------------------------------------------ Neon Heat
def test_neonheat_roads_avoid_screen_seams() -> None:
    for x in games_city.VX:
        assert all(abs(x - k * games_city.SW) > games_city.HALF for k in range(1, 3))
    for y in games_city.HY:
        assert all(abs(y - k * games_city.SH) > games_city.HALF for k in range(1, 3))


async def test_neonheat_ai_delivers_and_police_chase(engine) -> None:  # type: ignore[no-untyped-def]
    delivered = 0
    police = 0
    for seed in (1, 2, 3):
        app, clock = _app(engine, "neonheat", seed=seed)
        for _ in range(60):
            _run(app, clock, 1)
            police = max(police, sum(1 for c in app.cars if c.kind == "police"))
        delivered += sum(p.cash for p in app.players.values())
    assert delivered > 0, "packages get delivered"
    assert police >= 1, "picking up a package calls the police"


async def test_neonheat_seat_2_drives(engine) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "neonheat")
    await app.action("seat", {"player": 2, "joined": True})
    _run(app, clock, 1)
    p1, p2 = app.players[1].car, app.players[2].car
    d2 = p2.dir
    back = {0: "down", 1: "left", 2: "up", 3: "right"}[d2]
    x1, y1 = p1.x, p1.y
    res = await app.action("input", {"key": back, "player": 2})
    assert p2.dir == (d2 + 2) % 4, "the opposite arrow U-turns seat 2's car at once"
    assert app.is_human(2) and not app.is_human(1)
    _run(app, clock, 2)
    assert (p1.x, p1.y) != (x1, y1), "seat 1 kept driving as AI"
    assert [s["human"] for s in res["seats"]] == [False, True]


# ----------------------------------------------------------------- Street Surge
async def test_streetsurge_race_finishes(engine) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "streetsurge", {"skill": 1.0})
    for _ in range(150):
        _run(app, clock, 1)
        if app.over:
            break
    assert app.over, "two laps end the race"
    assert app.players[1].done is not None
    assert app.score > 0


async def test_streetsurge_seat_2_steers(engine) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "streetsurge")
    await app.action("seat", {"player": 2, "joined": True})
    _run(app, clock, 4)  # past the countdown
    p1, p2 = app.players[1], app.players[2]
    x2, d1 = p2.x, p1.d
    for _ in range(6):
        await app.action("input", {"key": "left", "player": 2})
        _run(app, clock, 0.25)
    assert p2.x < x2 - 0.2, "seat 2 steered left"
    assert p1.d > d1 and not app.is_human(1), "seat 1 kept racing as AI"


# ------------------------------------------------------------------ Leaf Leap
async def test_leafleap_seams_are_solid(engine) -> None:  # type: ignore[no-untyped-def]
    app, _ = _app(engine, "leafleap")
    for lvl in (1, 3, 6):
        app.level = lvl
        app._build()
        for sc in range(1, games_platform.SCREENS):
            for c in (sc * 8 - 1, sc * 8):
                assert app.g[7][c] == games_platform.GROUND, f"level {lvl}: pit at screen seam {c}"


@pytest.mark.parametrize("seed", [1, 2])
async def test_leafleap_ai_clears_levels(engine, seed: int) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "leafleap", {"skill": 1.0}, seed=seed)
    screens = set()
    for _ in range(45):
        _run(app, clock, 1)
        screens.add(app.screen)
    assert app.level >= 2, "the AI reached the flag"
    assert len(screens) == games_platform.SCREENS, "the camera flipped through every screen"


# ------------------------------------------------------------------ Four Up
def test_fourup_ai_wins_and_blocks() -> None:
    bd = games_connect.Board()
    for c in (0, 1, 2):
        bd.play(c, 0)
        bd.play(c, 1)  # seat 2 stacks on top
    assert games_connect.best_move(bd, 0, 3) == 3, "take the win on the bottom row"
    assert games_connect.best_move(bd, 1, 3) == 3, "block the bottom-row four"
    b = 0
    for r in range(4):
        b |= games_connect._bit(5, r)
    assert games_connect.won(b)
    assert len(games_connect.win_cells(b)) == 4


async def test_fourup_seat_2_aims_while_ai_plays_seat_1(engine) -> None:  # type: ignore[no-untyped-def]
    app, clock = _app(engine, "fourup")
    await app.action("seat", {"player": 2, "joined": True})
    before = app.cursor[1]
    await app.action("input", {"key": "left", "player": 2})
    assert app.cursor[1] == (before - 1) % 7, "seat 2's own cursor moved"
    moves = app.bd.moves
    _run(app, clock, 3)
    assert app.bd.moves >= moves + 1 or app.turn == 1, "seat 1 (AI) moved; seat 2 waits for its human"
    assert app.is_human(2) and not app.is_human(1)
    if app.turn == 1 and app.drop is None:
        m = app.bd.moves
        _run(app, clock, 3)
        assert app.bd.moves == m, "the AI never plays a seated human's turn"
