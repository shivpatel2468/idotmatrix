"""Modes, maps and themes of the board/party group: X and 0, Four Up, Mines, Starship and Light Cycles.

Every mode × map is started from the menu (AI filling the empty seats) and played for 30 s; versus / free-for-all
modes reach the results screen; a human who gets hit sees the damage flash; and no theme lets the gameplay
camouflage into the background.
"""

from __future__ import annotations

import gc
import time
from typing import Any

import pytest

from deskdot.apps.games_board import TicTacToe, _vanish
from deskdot.apps.games_bonus import Mines, Starship
from deskdot.apps.games_connect import Board, FourUp, _bit, best_move_pop, pop_outcome, won
from deskdot.apps.games_core import GameApp
from deskdot.apps.games_party import LightCycles
from deskdot.gfx import Frame

GAMES: dict[str, type[GameApp]] = {
    "tictactoe": TicTacToe,
    "fourup": FourUp,
    "mines": Mines,
    "starship": Starship,
    "cycles": LightCycles,
}
FPS = 6.0
DRIVE = ("right", "a", "down", "a", "left", "b", "up", "a")


class Ctx:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def save(self) -> None: ...


class Clock:
    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t


def _make(gid: str, seed: int = 1, **settings: Any) -> tuple[Any, Clock]:
    cls = GAMES[gid]
    app = cls(Ctx(), cls.Settings(**settings))  # type: ignore[arg-type]
    clock = Clock()
    app._clock = clock  # type: ignore[method-assign]
    app.rng.seed(seed)
    app.reset()
    return app, clock


def _render(app: GameApp, clock: Clock, seconds: float) -> float:
    worst = 0.0
    for _ in range(int(seconds * FPS)):
        clock.t += 1 / FPS
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, clock.t)
        worst = max(worst, time.perf_counter() - t0)
    return worst


async def _start(
    gid: str, mode: str, players: int, map_id: str, seed: int = 1, **settings: Any
) -> tuple[Any, Clock]:
    app, clock = _make(gid, seed, **settings)
    await app.action("start", {"mode": mode, "players": players, "map": map_id})
    if app.flow == "teams":
        await app.action("input", {"key": "a", "player": 1})  # seat 1 is ready on its default side
    assert app.flow == "intro"
    _render(app, clock, 3)
    assert app.flow == "play"
    return app, clock


def _all_ai(app: GameApp) -> None:
    """Hand seat 1 to the AI too, so a whole match plays out by itself."""
    app.roster[1]["human"] = False


def _record_damage(app: GameApp) -> list[float]:
    calls: list[float] = []
    orig = app.damage

    def rec(strength: float = 1.0) -> None:
        calls.append(strength)
        orig(strength)

    app.damage = rec  # type: ignore[method-assign]
    return calls


CASES = [(gid, m.id, mp) for gid, cls in GAMES.items() for m in cls.modes for mp in cls.maps]


# ------------------------------------------------------------------ every mode × map plays
@pytest.mark.parametrize(("gid", "mode", "map_id"), CASES)
async def test_mode_map_plays_30s(gid: str, mode: str, map_id: str) -> None:
    m = next(x for x in GAMES[gid].modes if x.id == mode)
    app, clock = await _start(gid, mode, m.max_players, map_id)
    assert len(app.roster) == m.max_players
    assert app.roster[1]["human"] and all(not app.roster[s]["human"] for s in app.roster if s != 1), (
        "the AI fills every empty seat"
    )
    if m.teams == "versus":
        assert {app.team_of(s) for s in app.roster} == {0, 1}
    assert app.map_id == map_id
    worst = 0.0
    gc.collect()
    gc.disable()
    try:
        for i in range(60):  # 30 s, seat 1 pressing keys now and then
            await app.action("input", {"key": DRIVE[i % len(DRIVE)], "player": 1})
            worst = max(worst, _render(app, clock, 0.5))
    finally:
        gc.enable()
    assert worst < 0.05, f"{gid}/{mode}/{map_id} render took {worst * 1000:.1f} ms"


@pytest.mark.parametrize("gid", list(GAMES))
async def test_attract_honours_the_map_and_plays_classic(gid: str) -> None:
    cls = GAMES[gid]
    for map_id in cls.maps:
        app, clock = _make(gid, map=map_id)
        assert app.flow == "attract" and not app.roster and app.map_id == map_id
        calls = _record_damage(app)
        assert _render(app, clock, 12) < 0.05
        assert not calls, "no damage flash while only the AI plays"


# ------------------------------------------------------------------ results screens
RESULT_CASES = [
    ("tictactoe", "duel", "classic", {"first_to": 1}),
    ("tictactoe", "duel", "vanish", {"first_to": 1}),
    ("fourup", "duel", "classic", {"first_to": 1}),
    ("fourup", "duel", "popout", {"first_to": 1}),
    ("mines", "race", "square", {"mines": 8}),
    ("mines", "coop", "cross", {"mines": 8}),
    ("starship", "ace", "deep", {"ace_time": 30}),
    ("starship", "coop", "rocks", {"lives": 1}),
    ("cycles", "party", "open", {"first_to": 1, "pace": 14.0}),
    ("cycles", "teams", "core", {"first_to": 1, "pace": 14.0}),
]


@pytest.mark.parametrize(("gid", "mode", "map_id", "settings"), RESULT_CASES)
async def test_match_reaches_the_results_screen(
    gid: str, mode: str, map_id: str, settings: dict[str, Any]
) -> None:
    m = next(x for x in GAMES[gid].modes if x.id == mode)
    app, clock = await _start(gid, mode, m.max_players, map_id, speed=10, **settings)
    _all_ai(app)
    for _ in range(240):
        _render(app, clock, 1)
        if app.outcome is not None:
            break
    assert app.outcome is not None, f"{gid}/{mode} never finished"
    o = app.outcome
    assert o["seat"] or o["team"] is not None or o["text"]
    _render(app, clock, 1.5)
    assert app.flow == "outro"
    f = Frame()
    app.render(f, clock.t)
    assert f.px.any()


# ------------------------------------------------------------------ damage for humans
async def test_tictactoe_damage_when_you_lose_a_round() -> None:
    app, _ = await _start("tictactoe", "solo", 1, "classic", skill=1.0)
    calls = _record_damage(app)
    app.board = (2, 2, 0, 1, 1, 0, 1, 0, 0)
    app.turn = 2
    for _ in range(10):
        app.update(0.2)
    assert app.wins[2] == 1 and calls


async def test_fourup_damage_when_you_lose_a_round() -> None:
    app, _ = await _start("fourup", "solo", 1, "classic", skill=1.0)
    calls = _record_damage(app)
    app.bd = Board()
    for c in (0, 1, 2):
        app.bd.play(c, 1)
    app.bd.play(6, 0)
    app.bd.play(6, 0)
    app.turn = 1
    app.think = 0
    app._plan = ("drop", 3)
    for _ in range(80):
        app.update(0.05)
    assert app.wins[2] == 1 and calls


async def test_mines_damage_and_modes() -> None:
    app, _ = await _start("mines", "solo", 1, "square")
    calls = _record_damage(app)
    app.mines = {(0, 0), (9, 9)}
    app.cur[1]["x"], app.cur[1]["y"] = 0, 0
    app.key_p("a", 1)
    assert calls and app.over, "solo: a mine ends the game"

    app, _ = await _start("mines", "coop", 2, "donut", lives=2)
    app.roster[2]["human"] = True
    app.seats[2] = {"name": "P2", "at": 0.0}
    calls = _record_damage(app)
    app.mines = {(0, 0), (9, 9)}
    app.cur[2]["x"], app.cur[2]["y"] = 0, 0
    app.key_p("a", 2)
    assert calls and not app.over and app.lives == 1, "co-op: the team loses a life, the field survives"
    assert (0, 0) in app.blown and (0, 0) in app.flags
    app.cur[2]["x"], app.cur[2]["y"] = 9, 9
    app.key_p("a", 2)
    assert app.over and app.outcome and app.outcome["text"] == "BOOM"

    app, _ = await _start("mines", "race", 2, "cross")
    app.mines = {(4, 4), (5, 9)}
    app.cur[1]["x"], app.cur[1]["y"] = 4, 4
    app.key_p("a", 1)
    assert app.cur[1]["stun"] > 0 and not app.over, "race: a mine stuns you"
    app.key_p("right", 1)
    assert app.cur[1]["x"] == 4, "stunned cursors don't move"
    assert (0, 0) not in app.cells, "the cross field has no corners"


async def test_starship_damage_and_coop_revive() -> None:
    app, _ = await _start("starship", "coop", 2, "deep", lives=1)
    calls = _record_damage(app)
    s1 = app.ships[1]
    s1["inv"] = 0.0
    app.bolts.append([s1["x"], 27.0])
    app.update(1 / 30)
    assert calls and not s1["alive"], "seat 1 (a person) was hit"
    assert app.ships[2]["alive"] and not app.over, "the wingman flies on"
    app.foes = []
    app.wave_t = 0.0
    app.update(1 / 30)
    assert s1["alive"] and s1["lives"] == 1, "a new wave revives the downed wingman"


async def test_starship_ace_hit_costs_points_not_ships() -> None:
    app, _ = await _start("starship", "ace", 2, "canyon")
    s1 = app.ships[1]
    s1["pts"], s1["inv"] = 100, 0.0
    app.bolts.append([s1["x"], 27.0])
    app.update(1 / 30)
    assert s1["alive"] and s1["pts"] == 75 and app.hurt_t > 0
    lo, hi = app._gap(28)
    assert all(lo + 2 <= s["x"] <= hi - 2 for s in app.ships.values()), "ships stay inside the canyon"


async def test_cycles_damage_when_your_bike_crashes() -> None:
    app, clock = await _start("cycles", "solo", 1, "open")
    calls = _record_damage(app)
    for _ in range(30):  # seat 1 is a person who never steers: straight into the wall
        _render(app, clock, 0.5)
        if calls:
            break
    assert calls and not app.bikes[1]["alive"]


# ------------------------------------------------------------------ rules
async def test_tictactoe_vanishing_keeps_three_marks() -> None:
    app, _ = await _start("tictactoe", "duel", 2, "vanish")
    app.roster[2]["human"] = True
    app.seats[2] = {"name": "P2", "at": 0.0}
    app.turn = 1
    for x_cell, o_cell in ((0, 3), (1, 4), (6, 8), (7, 5)):
        app.curs[1] = x_cell
        app.key_p("a", 1)
        app.curs[2] = o_cell
        app.key_p("a", 2)
    assert app.board.count(1) == 3 and app.board[0] == 0, "X's oldest mark vanished"
    assert app.order[1] == [1, 6, 7]
    assert app.board.count(2) == 3 and app.board[3] == 0
    # the variant AI takes a win and blocks one
    assert _vanish((0, 1), (3, 4), 1, 4)[1] == 2
    assert _vanish((0, 1), (4,), 2, 4)[1] == 2


async def test_tictactoe_misere_three_in_a_row_loses() -> None:
    app, _ = await _start("tictactoe", "solo", 1, "misere")
    app.board = (1, 1, 0, 2, 2, 0, 0, 0, 0)
    app.turn = 1
    app.curs[1] = 2
    app.key_p("a", 1)
    assert app.wins[2] == 1 and app.wins[1] == 0


def test_tictactoe_two_player_attract_path_unchanged() -> None:
    app, _ = _make("tictactoe")
    assert not app.match and app.variant == "classic"


def test_fourup_pop_out() -> None:
    bd = Board()
    for who in (0, 1, 0):  # column 0, bottom up: X O X
        bd.play(0, who)
    for c in (1, 2, 3):  # O O O along the bottom, X X X on top of them
        bd.play(c, 1)
        bd.play(c, 0)
    assert not won(bd.pos[0]) and not won(bd.pos[1])
    assert bd.can_pop(0, 0) and not bd.can_pop(0, 1) and not bd.can_pop(1, 0), (
        "only your own bottom disc pops"
    )
    saved = bd.pop(0)
    assert bd.heights[0] == 2 and bd.pos[1] & _bit(0, 0) and bd.pos[0] & _bit(0, 1), "the column slid down"
    assert won(bd.pos[0]) and won(bd.pos[1]), "both sides have four after this pop..."
    assert pop_outcome(bd, 0) == 0, "...and the popper wins the tie"
    bd.restore(0, saved)
    assert bd.heights[0] == 3 and bd.pos[0] & _bit(0, 0) and not won(bd.pos[0])
    assert best_move_pop(bd, 0) == ("pop", 0), "the AI finds the winning pop"


async def test_fourup_stones_block_holes() -> None:
    app, _ = await _start("fourup", "solo", 1, "stones", stones=3)
    assert len(app.stones) == 3
    for c, r in app.stones:
        assert app.bd.heights[c] == r + 1 and app.bd.blk & _bit(c, 0)
    assert all(not w & app.bd.blk for w in app.bd.windows)


async def test_cycles_teams_and_wrap() -> None:
    app, _ = await _start("cycles", "teams", 4, "wrap")
    assert app.teams and set(app.bikes) == {1, 2, 3, 4}
    assert app.rgb(1) != app.rgb(3) or app.team_of(1) != app.team_of(3)
    assert app._nxt(30, 5, 1, 0) == (1, 5) and app._nxt(5, 1, 0, -1) == (5, 30), "edges wrap"
    team_a = [s for s in app.bikes if app.team_of(s) == 0]
    for s, b in app.bikes.items():
        b["alive"] = s in team_a[:1]
    app.countdown = 0
    app._step()
    assert app.round_team == 0 and app.team_wins[0] == 1


def test_cycles_arenas_keep_the_starts_clear() -> None:
    from deskdot.apps.games_party import STARTS, WALLS

    for walls in WALLS.values():
        for x, y, d in STARTS.values():
            dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[d]
            assert all((x + k * dx, y + k * dy) not in walls for k in range(5))


# ------------------------------------------------------------------ themes never camouflage the gameplay
def _lum(c: tuple[int, int, int]) -> float:
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = c
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


THEME_CASES = [(gid, tid) for gid, cls in GAMES.items() for tid in cls.game_themes]


@pytest.mark.parametrize(("gid", "tid"), THEME_CASES)
def test_theme_contrast(gid: str, tid: str) -> None:
    th = GAMES[gid].game_themes[tid]
    assert max(th.bg) <= 16 and max(th.bg) - min(th.bg) <= 12, "the background is dark and low-saturation"
    for role in ("p", "e", "x", "hud"):
        c = getattr(th, role)
        assert _lum(c) - _lum(th.bg) >= 0.35, f"{tid}.{role} {c} camouflages into the background"
    assert max(th.w) >= 45 and _lum(th.w) - _lum(th.bg) >= 0.05, "walls / structure stay visible on the LEDs"
    assert len(th.r) == 7 and all(max(c) >= 45 for c in th.r)


@pytest.mark.parametrize(("gid", "tid"), THEME_CASES)
async def test_game_themes_render(gid: str, tid: str) -> None:
    app, clock = _make(gid, theme=tid)
    _render(app, clock, 3)
    f = Frame()
    app.render(f, clock.t)
    assert f.px.any()
