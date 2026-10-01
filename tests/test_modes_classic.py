"""Modes, maps and themes of the classic games (Pong, Breakout, Flappy, Dino Runner, Racer): every mode starts
with the AI filling the empty seats, every mode × map plays 30 s quickly, versus/ffa matches reach a result,
people get the damage flash, and no theme lets the gameplay camouflage into the background."""

from __future__ import annotations

import time
from typing import Any

import pytest

from deskdot.apps.games_classic import Breakout, Dino, Flappy, Pong, Racer
from deskdot.apps.games_core import GameApp
from deskdot.gfx import Frame

GAMES: list[type[GameApp]] = [Pong, Breakout, Flappy, Dino, Racer]


class Ctx:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def save(self) -> None: ...


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _make(cls: type[GameApp], seed: int = 1, **settings: Any) -> tuple[GameApp, Clock]:
    g = cls(Ctx(), cls.Settings(**settings))  # type: ignore[arg-type]
    c = Clock()
    g._clock = c  # type: ignore[method-assign]
    g.rng.seed(seed)
    g.reset()
    return g, c


def _run(g: GameApp, c: Clock, seconds: float, fps: float = 12.0, stop_at_result: bool = False) -> float:
    """Render `seconds` of wall time; returns the worst render time."""
    worst = 0.0
    for _ in range(int(seconds * fps)):
        c.t += 1 / fps
        f = Frame()
        t0 = time.perf_counter()
        g.render(f, c.t)
        worst = max(worst, time.perf_counter() - t0)
        if stop_at_result and g.outcome is not None:
            break
    return worst


async def _start(g: GameApp, c: Clock, mode: str, players: int, map_id: str | None = None) -> None:
    payload: dict[str, Any] = {"mode": mode, "players": players}
    if map_id:
        payload["map"] = map_id
    await g.action("start", payload)
    if g.flow == "teams":
        await g.action("input", {"key": "a", "player": 1})  # ready on the default side; AI fills the rest
    assert g.flow == "intro"
    _run(g, c, 3)
    assert g.flow == "play"


CASES = [(cls, m.id, mp) for cls in GAMES for m in cls.modes for mp in cls.maps]


def _ids(case: tuple[type[GameApp], str, str]) -> str:
    return f"{case[0].id}-{case[1]}-{case[2]}"


@pytest.mark.parametrize("case", CASES, ids=_ids)
async def test_every_mode_and_map_plays_30s(case: tuple[type[GameApp], str, str]) -> None:
    cls, mode, map_id = case
    g, c = _make(cls)
    m = next(x for x in cls.modes if x.id == mode)
    n = m.max_players
    await _start(g, c, mode, n, map_id)
    assert g.map_id == map_id and g.play_mode.id == mode
    assert len(g.roster) == n, "the AI fills every empty seat"
    assert g.is_human(1) and not any(g.is_human(s) for s in range(2, n + 1))
    worst = _run(g, c, 30)
    assert worst < 0.05, f"{cls.id}/{mode}/{map_id}: render took {worst * 1000:.1f} ms"


def _players(g: GameApp) -> list[dict[str, Any]]:
    for attr in ("pads", "birds", "dinos", "players"):
        if hasattr(g, attr):
            return list(getattr(g, attr))
    raise AssertionError("no players")


@pytest.mark.parametrize("cls", GAMES, ids=lambda c: c.id)
async def test_multiplayer_modes_seat_everyone(cls: type[GameApp]) -> None:
    for m in cls.modes:
        if m.max_players < 2:
            continue
        g, c = _make(cls)
        await _start(g, c, m.id, m.max_players)
        seats = {p["seat"] for p in _players(g)}
        assert seats == set(g.roster), f"{cls.id}/{m.id}: every seat controls something"


# settings that make matches end sooner (weak AI, few points/lives)
QUICK: dict[str, dict[str, Any]] = {
    "pong": {"points": 3, "lives": 1, "skill": 0.2},
    "breakout": {"lives": 1, "skill": 0.0},
    "flappy": {"skill": 0.0, "gap": 8},
    "dino": {"skill": 0.0},
    "racer": {"skill": 0.0, "traffic": 10},
}
VERSUS = [(cls, m.id) for cls in GAMES for m in cls.modes if m.teams in ("versus", "ffa")]


@pytest.mark.parametrize("case", VERSUS, ids=lambda c: f"{c[0].id}-{c[1]}")
async def test_versus_and_ffa_reach_a_result(case: tuple[type[GameApp], str]) -> None:
    cls, mode = case
    g, c = _make(cls, **QUICK[cls.id])
    m = next(x for x in cls.modes if x.id == mode)
    await _start(g, c, mode, m.max_players)
    _run(g, c, 240, fps=10, stop_at_result=True)
    assert g.outcome is not None, f"{cls.id}/{mode}: no result"
    assert g.outcome["seat"] is not None or g.outcome["team"] is not None
    _run(g, c, 1.5)
    assert g.flow == "outro"


async def test_breakout_coop_ends_with_the_level() -> None:
    g, c = _make(Breakout, **QUICK["breakout"])
    await _start(g, c, "coop", 2)
    _run(g, c, 240, fps=10, stop_at_result=True)
    assert g.outcome is not None and "LEVEL" in str(g.outcome["text"])


@pytest.mark.parametrize("cls", GAMES, ids=lambda c: c.id)
async def test_damage_when_a_human_is_hit(cls: type[GameApp]) -> None:
    """Seat 1 plays (and presses nothing): losing a point / life / the run flashes red."""
    g, c = _make(cls)
    hits: list[float] = []
    orig = g.damage

    def hit(strength: float = 1.0) -> None:
        orig(strength)
        hits.append(g.hurt_t)

    g.damage = hit  # type: ignore[method-assign]
    await _start(g, c, cls.modes[0].id, 1)
    for _ in range(120):
        _run(g, c, 0.5, fps=10)
        if hits:
            break
    assert hits, f"{cls.id}: no damage flash for the human"
    assert hits[0] > 0, "the red flash starts"


@pytest.mark.parametrize("cls", GAMES, ids=lambda c: c.id)
async def test_no_damage_in_self_play(cls: type[GameApp]) -> None:
    g, c = _make(cls, skill=0.0)
    hits: list[float] = []
    g.damage = lambda s=1.0: hits.append(s)  # type: ignore[method-assign,assignment,func-returns-value]
    _run(g, c, 20, fps=10)
    assert g.flow == "attract" and not hits


def _luma(c: tuple[int, int, int]) -> float:
    """Relative luminance of the 8-bit (panel) colour, Rec. 709 weights."""
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


THEME_CASES = [(cls, tid) for cls in GAMES for tid in cls.game_themes]


@pytest.mark.parametrize("case", THEME_CASES, ids=lambda c: f"{c[0].id}-{c[1]}")
def test_themes_never_camouflage_the_gameplay(case: tuple[type[GameApp], str]) -> None:
    cls, tid = case
    th = cls.game_themes[tid]
    assert max(th.bg) <= 60 and max(th.bg) - min(th.bg) <= 45, "background: dark and low-saturation"
    bg = _luma(th.bg)
    for role in ("p", "e", "x", "hud"):
        gap = _luma(getattr(th, role)) - bg
        assert gap >= 0.35, f"{cls.id}/{tid}.{role}: luminance gap {gap:.2f} vs the background"
    assert _luma(th.w) - bg >= 0.2, f"{cls.id}/{tid}.w: walls must read against the background"
    assert len(th.r) == 7 and all(max(col) >= 45 for col in th.r)
    assert cls.game_theme_labels.get(tid)


@pytest.mark.parametrize("cls", GAMES, ids=lambda c: c.id)
def test_every_theme_and_map_renders_in_attract(cls: type[GameApp]) -> None:
    for tid in cls.game_themes:
        for mp in cls.maps:
            g, c = _make(cls, theme=tid, map=mp)
            _run(g, c, 2)


async def test_pong_seat_two_still_drives_the_right_paddle() -> None:
    g, c = _make(Pong)
    await g.action("seat", {"player": 2, "joined": True})
    _run(g, c, 0.5)
    assert g.is_human(2)
    right = next(p for p in g.pads if p["side"] == "R")
    assert right["seat"] == 2
    before = right["tgt"]
    await g.action("input", {"key": "down", "player": 2})
    assert right["tgt"] != before or before >= 32 - g.settings.paddle
    _run(g, c, 1)
    # the 1 v 1 mode with two people puts the phone on the other side
    await g.action("start", {"mode": "classic", "players": 2})
    await g.action("input", {"key": "a", "player": 1})
    await g.action("input", {"key": "a", "player": 2})
    assert g.flow == "intro"
    assert {p["seat"] for p in g.pads} == {1, 2}
    assert g.team_of(1) != g.team_of(2)


async def test_pong_doubles_has_front_and_back_paddles() -> None:
    g, c = _make(Pong)
    await _start(g, c, "doubles", 4)
    sides = sorted((p["side"], p["d"]) for p in g.pads)
    assert sides == [("L", 0), ("L", 6), ("R", 0), ("R", 6)]
    assert len({p["seat"] for p in g.pads}) == 4


async def test_pong_fourway_eliminates_a_side() -> None:
    g, c = _make(Pong, lives=1)
    await _start(g, c, "fourway", 4)
    assert g.open == {"L", "R", "T", "B"}
    g._goal("T")
    assert "T" not in g.open and all(p["side"] != "T" for p in g.pads)


async def test_racer_lives_give_a_second_chance() -> None:
    g, c = _make(Racer, lives=2)
    await _start(g, c, "solo", 1)
    pl = g.players[0]
    g._crash(pl)
    assert pl["alive"] and pl["inv"] > 0 and pl["lives"] == 1
    g._crash(pl)
    assert not pl["alive"]
