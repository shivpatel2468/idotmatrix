"""Puzzle group game modes: Snake (arcade), Tetris and 2048 — modes, maps, themes, results and damage."""

from __future__ import annotations

import time
from typing import Any

import pytest

from dotdeck.apps.arcade import WALLS, Arcade
from dotdeck.apps.games_core import GameApp
from dotdeck.apps.games_puzzle import G2048, STONE, Tetris
from dotdeck.gfx import Frame

WH_LAST = 15
GAMES: tuple[type[GameApp], ...] = (Arcade, Tetris, G2048)


class Ctx:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def save(self) -> None: ...


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _game(cls: type[GameApp], seed: int = 1, **settings: Any) -> tuple[Any, Clock]:
    g = cls(Ctx(), cls.Settings(**settings))  # type: ignore[arg-type]
    c = Clock()
    g._clock = c  # type: ignore[method-assign]
    g.rng.seed(seed)
    g.reset()
    return g, c


def _run(g: GameApp, c: Clock, seconds: float, fps: float = 10.0, stop_on_outcome: bool = False) -> float:
    """Render `seconds` of wall time; return the worst render time."""
    worst = 0.0
    for _ in range(int(seconds * fps)):
        c.t += 1 / fps
        f = Frame()
        t0 = time.perf_counter()
        g.render(f, c.t)
        worst = max(worst, time.perf_counter() - t0)
        if stop_on_outcome and g.outcome:
            break
    return worst


async def _start(g: GameApp, c: Clock, mode: str, players: int, mp: str, ai_only: bool = False) -> None:
    await g.action("start", {"mode": mode, "players": players, "map": mp})
    if g.flow == "teams":
        await g.action("input", {"key": "a", "player": 1})
    if ai_only:
        for r in g.roster.values():
            r["human"] = False
    _run(g, c, 3)  # past the 3-2-1 intro
    assert g.flow == "play"


def _count_damage(g: GameApp) -> list[float]:
    hits: list[float] = []
    orig = g.damage

    def spy(strength: float = 1.0) -> None:
        hits.append(strength)
        orig(strength)

    g.damage = spy  # type: ignore[method-assign]
    return hits


def _cases() -> list[tuple[type[GameApp], str, str]]:
    return [(cls, m.id, mp) for cls in GAMES for m in cls.modes for mp in cls.maps]


# ------------------------------------------------------------------------------------------ generic
def _luma(c: tuple[int, int, int]) -> float:
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


@pytest.mark.parametrize("cls", GAMES, ids=lambda c: c.id)
def test_themes_never_camouflage(cls: type[GameApp]) -> None:
    assert len(cls.game_themes) >= 2
    for tid, th in cls.game_themes.items():
        assert max(th.bg) <= 24 and max(th.bg) - min(th.bg) <= 16, (
            f"{tid}: background must be dark and grey-ish"
        )
        for role in ("p", "e", "x", "hud"):
            gap = _luma(getattr(th, role)) - _luma(th.bg)
            assert gap >= 0.35, f"{cls.id}/{tid}.{role} too close to the background ({gap:.2f})"
        assert _luma(th.w) - _luma(th.bg) >= 0.12, f"{cls.id}/{tid}: walls must stay visible"
        assert len(th.r) == 7


@pytest.mark.parametrize("cls", GAMES, ids=lambda c: c.id)
def test_attract_falls_back_to_classic_solo(cls: type[GameApp]) -> None:
    g, c = _game(cls)
    assert g.flow == "attract" and not g.roster
    _run(g, c, 3)
    assert g.status()["player"] == "ai"
    if cls is Arcade:
        assert len(g.snakes) == 1 and not g.multi
    elif cls is Tetris:
        assert g.layout == "solo" and g.wells[0].w == 10
    else:
        assert g.layout == "solo" and len(g.boards) == 1


@pytest.mark.parametrize(("cls", "mode", "mp"), _cases(), ids=lambda v: getattr(v, "id", v))
async def test_every_mode_and_map_plays_30s(cls: type[GameApp], mode: str, mp: str) -> None:
    g, c = _game(cls)
    m = next(x for x in cls.modes if x.id == mode)
    await _start(g, c, mode, m.max_players, mp)
    assert g.n_players == m.max_players
    for seat in range(2, m.max_players + 1):
        assert not g.is_human(seat), "empty seats are AI"
    if m.max_players > 1:
        assert g.is_human(1)
    worst = _run(g, c, 30)
    assert worst < 0.05, f"{cls.id} {mode}/{mp} render took {worst * 1000:.1f} ms"


# ------------------------------------------------------------------------------------------ Snake
def test_snake_keeps_id_and_old_settings() -> None:
    assert Arcade.id == "arcade"
    s = Arcade.Settings(**{"speed": 12, "color": "#ff0000", "food": "#00ff00", "walls": True, "gone": 1})
    assert (s.speed, s.color, s.food, s.walls) == (12, "#ff0000", "#00ff00", True)
    g, c = _game(Arcade, speed=12, color="#ff0000", walls=True)
    _run(g, c, 0.5)
    f = Frame()
    g.render(f, 0)
    body = list(g.snakes[0].body)
    x, y = body[1]
    assert int(f.px[y * 2, x * 2, 0]) > 120, "the snake is drawn in the chosen colour"
    assert not g.wrap, "solid walls on the open map"


def test_snake_maps_leave_the_starts_clear() -> None:
    from dotdeck.apps.arcade import STARTS, Snake

    for mid, walls in WALLS.items():
        for seat, (head, d) in STARTS.items():
            s = Snake(seat, head, d)
            assert not set(s.body) & walls, (mid, seat)
            nxt = (head[0] + d[0], head[1] + d[1])
            assert nxt not in walls, (mid, seat)


@pytest.mark.parametrize("mode", ["battle", "teams"])
async def test_snake_matches_end_with_a_result(mode: str) -> None:
    g, c = _game(Arcade, match_time=30)
    await _start(g, c, mode, 4, "pillars", ai_only=True)
    _run(g, c, 40, stop_on_outcome=True)
    assert g.outcome is not None
    o = g.status()["outcome"]
    assert o["seat"] or o["team"] is not None or o["text"] == "DRAW"


async def test_snake_coop_shares_lives_and_respawns() -> None:
    g, c = _game(Arcade, lives=2)
    await _start(g, c, "coop", 2, "classic", ai_only=True)
    s2 = g.snakes[1]
    g._die(s2)
    assert not s2.alive and g.lives == 1 and s2.respawn > 0
    _run(g, c, 3)
    assert s2.alive or s2.respawn > 0
    assert not g.over


async def test_snake_human_death_flashes_damage_but_ai_death_does_not() -> None:
    g, c = _game(Arcade)
    hits = _count_damage(g)
    await _start(g, c, "battle", 2, "maze")  # seat 1 is a person who never steers: it hits the maze wall
    _run(g, c, 5)
    assert not g.snakes[0].alive
    assert hits
    g2, _c2 = _game(Arcade)  # attract: the AI plays alone, no damage feedback
    hits2 = _count_damage(g2)
    g2._die(g2.snakes[0])
    assert not hits2


# ------------------------------------------------------------------------------------------ Tetris
async def test_tetris_versus_layout_and_garbage() -> None:
    g, c = _game(Tetris)
    hits = _count_damage(g)
    await _start(g, c, "versus", 2, "classic")
    assert g.layout == "versus" and [w.w for w in g.wells] == [7, 7]
    mine = next(w for w in g.wells if w.pilots[0].seat == 1)
    other = next(w for w in g.wells if w is not mine)
    # the opponent clears 2 lines → 1 garbage row heads our way
    other.grid[WH_LAST] = [1] * 7
    other.grid[WH_LAST - 1] = [1] * 7
    other.clearing = [WH_LAST - 1, WH_LAST]
    g._finish_clear(other)
    assert mine.pending == 1
    g._add_garbage(mine, 1)
    assert hits, "a person receiving garbage gets the damage flash"
    assert any(v == 8 for v in mine.grid[-1])


async def test_tetris_versus_top_out_gives_a_winner() -> None:
    g, c = _game(Tetris, rise_every=5)
    await _start(g, c, "versus", 2, "rising", ai_only=True)
    _run(g, c, 240, fps=5, stop_on_outcome=True)
    assert g.outcome is not None and g.outcome["seat"] in (1, 2)


async def test_tetris_coop_one_wide_well_two_pieces() -> None:
    g, c = _game(Tetris)
    hits = _count_damage(g)
    await _start(g, c, "coop", 2, "classic")
    w = g.wells[0]
    assert g.layout == "coop" and w.w == 13 and [p.seat for p in w.pilots] == [1, 2]
    _run(g, c, 2)
    a, b = w.pilots
    if not a.waiting and not b.waiting:
        assert not set(g._cells(a.kind, a.rot, a.px, a.py)) & set(g._cells(b.kind, b.rot, b.px, b.py))
    w.grid = [[1] * 13 for _ in range(16)]  # stack to the ceiling → top out
    g._top_out(w)
    assert g.outcome is not None and "LINE" in g.outcome["text"]
    assert hits


def test_tetris_solo_still_classic() -> None:
    g, c = _game(Tetris)
    _run(g, c, 20)
    assert g.layout == "solo" and g.wells[0].w == 10
    assert g.lines == g.wells[0].lines


# ------------------------------------------------------------------------------------------ 2048
async def test_2048_race_ends_with_a_winner() -> None:
    g, c = _game(G2048, race_target="128")
    await _start(g, c, "race", 4, "classic", ai_only=True)
    assert len(g.boards) == 4
    _run(g, c, 300, fps=5, stop_on_outcome=True)
    assert g.outcome is not None and g.outcome["seat"] in (1, 2, 3, 4)


async def test_2048_junk_and_stuck_boards_hurt_the_person() -> None:
    g, c = _game(G2048)
    hits = _count_damage(g)
    await _start(g, c, "race", 2, "classic")
    me, rival = g.boards
    before = sum(1 for v in me.board if v)
    g._race_events(rival, 6)  # the rival merged a 64: a junk tile lands on our board
    assert sum(1 for v in me.board if v) == before + 1
    assert hits
    me.board = tuple((i % 2) + 1 + (i // 4) * 2 for i in range(16))  # a board with no moves
    g._stuck(me)
    assert not me.alive and len(hits) >= 2
    assert g.outcome is not None and g.outcome["seat"] == rival.seat


async def test_2048_relay_takes_turns() -> None:
    g, c = _game(G2048)
    await _start(g, c, "relay", 2, "classic")
    assert g.layout == "coop" and g.turn == 1
    await g.action("input", {"key": "left", "player": 2})  # not your turn
    assert not g.boards[0].pending
    for k in ("left", "right", "up", "down"):
        await g.action("input", {"key": k, "player": 1})
        _run(g, c, 0.5)
        if g.turn == 2:
            break
    assert g.turn == 2
    _run(g, c, 2)  # seat 2 is AI: it moves and hands the turn back
    assert g.turn == 1


def test_2048_stones_never_move() -> None:
    g, _c = _game(G2048)
    g.sel["map"] = "stones"
    g.reset()
    b = g.boards[0]
    assert b.board[5] == STONE and b.board[10] == STONE
    for d in ("left", "up", "right", "down") * 10:
        g._do(b, d)
    assert b.board[5] == STONE and b.board[10] == STONE
