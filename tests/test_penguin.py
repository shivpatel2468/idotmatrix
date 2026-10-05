"""Penguin Escape: the puzzle rules, every level solvable within its move budget, the sprites, the demo and the
human controls (undo, restart, level select, saved progress)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from deskdot.apps import _penguin as P
from deskdot.apps.games_penguin import KEEPER, OY, SPRITES, TILE, PenguinEscape, _xy
from deskdot.gfx import Frame

FPS = 12.0
_D = {"u": "up", "d": "down", "l": "left", "r": "right"}


class Ctx:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.saves = 0

    def save(self) -> None:
        self.saves += 1


class Clock:
    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t


def _make(**settings: Any) -> tuple[PenguinEscape, Clock]:
    app = PenguinEscape(Ctx(), PenguinEscape.Settings(**settings))  # type: ignore[arg-type]
    clock = Clock()
    app._clock = clock  # type: ignore[method-assign]
    app.rng.seed(1)
    app.reset()
    return app, clock


def _run(app: PenguinEscape, clock: Clock, seconds: float) -> list[float]:
    times = []
    for i in range(int(seconds * FPS)):
        clock.t += 1 / FPS
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, i / FPS)
        times.append(time.perf_counter() - t0)
    return times


def _level(*rows: str, guards: tuple[str, ...] = ()) -> P.Puzzle:
    return P.Puzzle(P.Level("t", rows, guards))


# ----------------------------------------------------------------------------- levels
def test_levels_are_well_formed() -> None:
    assert 12 <= len(P.LEVELS) <= 20
    assert len({lv.name for lv in P.LEVELS}) == len(P.LEVELS)
    for lv in P.LEVELS:
        pz = P.Puzzle(lv)
        assert len(pz.fish) == 3, lv.name
        assert "".join(lv.rows).count("E") == 1, lv.name
        assert len(pz.doors) <= len(pz.keys), lv.name


@pytest.mark.parametrize("n", range(len(P.LEVELS)), ids=[lv.name for lv in P.LEVELS])
def test_every_level_is_solvable_with_three_stars_within_its_budget(n: int) -> None:
    lv = P.LEVELS[n]
    pz = P.Puzzle(lv)
    plan = P.solve(pz)
    assert plan, f"{lv.name}: no 3-star solution"
    assert len(plan) <= lv.par, f"{lv.name}: {len(plan)} moves > budget {lv.par}"
    # the stored demo is a shortest 3-star solution and really wins
    assert len(lv.demo) == len(plan), f"{lv.name}: demo {len(lv.demo)} moves, BFS {len(plan)}"
    st = pz.start
    for i, c in enumerate(lv.demo):
        r = pz.step(st, _D[c])
        if i < len(lv.demo) - 1:
            assert r.outcome in ("move", "push"), f"{lv.name}: move {i} is a {r.outcome}"
        st = r.state
    assert r.outcome == "win" and pz.stars(st) == 3


def test_difficulty_rises() -> None:
    """Later levels need more thinking: the solutions of the second half are longer than the first half's."""
    n = len(P.LEVELS) // 2
    first = sum(len(lv.demo) for lv in P.LEVELS[:n]) / n
    second = sum(len(lv.demo) for lv in P.LEVELS[n:]) / (len(P.LEVELS) - n)
    assert second > first


# ----------------------------------------------------------------------------- rules
def test_ice_slides_until_something_stops_you() -> None:
    pz = _level(
        "S___#...",
        "........",
        "........",
        "........",
        "........",
        "........",
        ".......E",
    )
    r = pz.step(pz.start, "right")
    assert r.outcome == "move" and r.state[0] == 3 and r.path == (0, 1, 2, 3)
    r2 = pz.step(r.state, "down")  # onto snow: one step
    assert r2.state[0] == 11


def test_snow_stops_a_slide_and_fish_are_picked_up_on_the_way() -> None:
    pz = _level(
        "S_f__._.",
        "........",
        "........",
        "........",
        "........",
        "........",
        "F.....FE",
    )
    r = pz.step(pz.start, "right")
    assert r.state[0] == 5 and pz.stars(r.state) == 1


def test_water_is_a_splash_and_a_block_fills_it() -> None:
    pz = _level(
        "SB~.....",
        "~.......",
        "........",
        "........",
        "........",
        "........",
        "F.F.F..E",
    )
    assert pz.step(pz.start, "down").outcome == "fall"
    r = pz.step(pz.start, "right")  # shove the block into the hole
    assert r.outcome == "push" and r.sank and not r.state[4]
    r2 = pz.step(r.state, "right")  # the slush holds the penguin
    assert r2.outcome == "move" and r2.state[0] == 1
    r3 = pz.step(r2.state, "right")
    assert r3.outcome == "move" and r3.state[0] == 2


def test_blocks_slide_on_ice_and_stop_on_snow() -> None:
    pz = _level(
        "Sb___.._",
        "........",
        "........",
        "........",
        "........",
        "........",
        "F.F.F..E",
    )
    r = pz.step(pz.start, "right")
    assert r.outcome == "push" and r.block == (1, 2, 3, 4, 5) and r.state[4] == frozenset({5})
    assert r.state[0] == 0  # the penguin stays where it shoved


def test_keys_open_doors_once() -> None:
    pz = _level(
        "SKDD....",
        "########",
        "........",
        "........",
        "........",
        "........",
        "F.F.F..E",
    )
    r = pz.step(pz.start, "right")
    assert pz.held_keys(r.state) == 1
    r = pz.step(r.state, "right")  # opens the first door and stops in the doorway
    assert r.state[0] == 2 and pz.held_keys(r.state) == 0
    assert pz.step(r.state, "right").outcome == "bump"  # no key for the second door


def test_keepers_see_three_tiles_ahead_but_not_a_fast_slide() -> None:
    walled = _level(
        "S.......",
        "........",
        "#.......",
        "........",
        "G.......",
        "........",
        "F.F.F..E",
        guards=("u",),
    )
    assert walled.sight(0, 0, frozenset()) == [[32, 24]]  # the wall at (0,2) blocks the view
    rows = ["S.......", "s______.", "........", "........", "...G....", "........", "F.F.F..E"]
    pz = _level(*rows, guards=("u",))
    assert pz.sight(0, 0, frozenset()) == [[35, 27, 19, 11]]
    st = (8, 0, 0, 0, frozenset(), 0, 0)  # on the ice at (0,1)
    r = pz.step(st, "right")  # slides through the beam at (3,1) and stops on snow at (7,1)
    assert r.outcome == "move" and 11 in r.path and r.state[0] == 15
    rows[1] = "s___#__."
    blocked = _level(*rows, guards=("u",))
    assert blocked.step(st, "right").outcome == "caught"  # stops at (3,1), right in the beam


def test_walking_into_a_keeper_is_caught_and_keepers_step_each_turn() -> None:
    pz = _level(
        "S..G....",
        "........",
        "........",
        "........",
        "........",
        "........",
        "F.F.F..E",
        guards=("dRLu",),
    )
    assert [p for p, _ in pz.keepers(0)] == [3] and [p for p, _ in pz.keepers(2)] == [4]
    st = (2, 0, 0, 0, frozenset(), 0, 0)
    assert pz.step(st, "right").outcome == "caught"  # bumping into the keeper
    r = pz.step(pz.start, "down")  # (0,1): out of view while the keeper looks down
    assert r.outcome == "move" and r.state[6] == 1


# ----------------------------------------------------------------------------- sprites and rendering
def test_sprites_fit_their_tile_and_the_board_fits_the_panel() -> None:
    for spr in (*SPRITES.values(), *KEEPER.values()):
        assert spr.w <= TILE and spr.h <= TILE
    for i in range(P.COLS * P.ROWS):
        x, y = _xy(i)
        assert 0 <= x <= 32 - TILE and OY <= y <= 32 - TILE


@pytest.mark.parametrize("theme", ["ice", "night", "aurora", "classic"])
def test_every_level_renders_fast_in_every_theme(theme: str) -> None:
    app, clock = _make(theme=theme)
    worst = 0.0
    for n in range(len(P.LEVELS)):
        app.load(n)
        app.card = None
        for _ in range(3):
            clock.t += 0.2
            f = Frame()
            t0 = time.perf_counter()
            app.render(f, clock.t)
            worst = max(worst, time.perf_counter() - t0)
            assert f.px.shape == (32, 32, 3)
            assert f.px[OY:].any()
    assert worst < 0.05


def test_penguin_is_drawn_inside_the_grid_at_every_corner() -> None:
    app, clock = _make()
    app.card = None
    for i in (0, 7, 48, 55):
        app.state = (i, *app.state[1:])
        f = Frame()
        app.draw(f, clock.t)
        x, y = _xy(i)
        tile = f.px[y : y + TILE, x : x + TILE]
        assert (tile == (12, 12, 26)).all(axis=2).any(), f"penguin body missing at tile {i}"


# ----------------------------------------------------------------------------- the demo and the controls
def test_the_demo_clears_levels_quickly_and_renders_fast() -> None:
    app, clock = _make(skill=1.0)
    times = _run(app, clock, 40)
    assert app.level >= 2, f"the AI is still on level {app.level + 1}"
    assert app.score >= 6  # three stars per cleared level
    assert max(times) < 0.05
    assert sorted(times)[len(times) // 2] < 0.004
    assert app.ctx.data.get("stars") is None  # the demo never writes your progress
    assert app.status()["player"] == "ai" and not app.over


def test_a_clumsy_demo_slips_undoes_and_still_wins() -> None:
    app, clock = _make(skill=0.0)
    _run(app, clock, 60)
    assert app.level >= 1


async def test_human_moves_undo_restart_and_progress() -> None:
    app, clock = _make()
    await app.action("input", {"key": "up"})  # dismisses the level card
    assert app.card is None
    lv = P.LEVELS[0]
    await app.action("input", {"key": _D[lv.demo[0]]})
    _run(app, clock, 1)
    assert len(app.history) == 1
    await app.action("input", {"key": "a"})  # undo
    assert app.state == app.pz.start and not app.history
    for c in lv.demo:
        await app.action("input", {"key": _D[c]})
        _run(app, clock, 1.2)
    _run(app, clock, 1.5)
    assert app.card == "clear"
    assert app.ctx.data["stars"] == {"1": 3} and app.ctx.data["reached"] == 1
    await app.action("input", {"key": "a"})
    assert app.level == 1 and app.card == "level"
    await app.action("input", {"key": "right"})  # level 3 isn't reached yet
    assert app.level == 1
    await app.action("input", {"key": "left"})
    assert app.level == 0
    await app.action("input", {"key": "a"})
    await app.action("input", {"key": "b"})  # restart → the level card again
    assert app.card == "level" and app.state == app.pz.start


async def test_splash_then_undo() -> None:
    app, clock = _make(start_level=6)  # "Bridge Builder"
    await app.action("input", {"key": "a"})
    pz = app.pz
    bad: list[str] = []
    for c in P.LEVELS[app.level].demo:  # follow the solution until a wrong turn would end in the water
        bad = [d for d in P.DIRS if pz.step(app.state, d).outcome == "fall"]
        if bad:
            break
        await app.action("input", {"key": _D[c]})
        _run(app, clock, 1.5)
    assert bad
    before = app.state
    await app.action("input", {"key": bad[0]})
    _run(app, clock, 2)
    assert app.card == "fail" and app.status()["stage"] == "fail"
    await app.action("input", {"key": "a"})
    assert app.card is None and app.state == before


async def test_the_ai_replans_after_a_person_walks_off() -> None:
    app, clock = _make(skill=1.0, start_level=2)
    await app.action("input", {"key": "a"})
    pz = app.pz
    d = next(d for d in P.DIRS if pz.step(pz.start, d).outcome == "move")
    await app.action("input", {"key": d})
    _run(app, clock, 12)  # idle: the AI takes over from where the penguin stands
    assert app.status()["player"] == "ai"
    _run(app, clock, 25)
    assert app.level >= 2


def test_the_start_level_setting_and_menu_start() -> None:
    app, _clock = _make(start_level=9)
    assert app.level == 8 and app.status()["level"] == 9
