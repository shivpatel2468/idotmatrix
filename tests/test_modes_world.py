"""Modes, maps, themes and multiplayer for the world games: Dig World, Neon Heat, Street Surge and Leaf Leap.

Each game builds its match from the menu (mode / players / map) with the AI filling empty seats, plays every
mode on every map, reaches a result in its competitive modes, flashes red only when a *person* is hurt, and keeps
every gameplay colour of its genre themes well clear of the background.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

import deskdot.apps  # noqa: F401 — registers the games
from deskdot.apps import games_city, games_road
from deskdot.apps.games_core import GameApp, Theme
from deskdot.engine import REGISTRY
from deskdot.gfx import Frame

GAMES = ("digworld", "neonheat", "streetsurge", "leafleap")


class Ctx:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def save(self) -> None: ...


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _make(gid: str, seed: int = 1, **settings: Any) -> tuple[Any, Clock]:
    cls = REGISTRY[gid]
    app = cls(Ctx(), cls.Settings(**settings))
    clock = Clock()
    app._clock = clock  # type: ignore[method-assign]
    app.rng.seed(seed)
    app.reset()
    return app, clock


def _run(app: GameApp, clock: Clock, seconds: float, fps: float = 5.0, until: Any = None) -> float:
    """Render `seconds` of wall time; return the worst render time."""
    worst = 0.0
    for i in range(int(seconds * fps)):
        clock.t += 1 / fps
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, i / fps)
        worst = max(worst, time.perf_counter() - t0)
        if until is not None and until():
            break
    return worst


async def _start(app: GameApp, clock: Clock, mode: str, players: int, map_id: str | None = None) -> None:
    payload: dict[str, Any] = {"mode": mode, "players": players}
    if map_id is not None:
        payload["map"] = map_id
    await app.action("start", payload)
    if app.flow == "teams":
        await app.action("input", {"key": "a"})  # seat 1 is the only person: ready → AI fills the other side
    assert app.flow in ("intro", "play")
    _run(app, clock, 3.0, fps=10)
    assert app.flow == "play"


def _combos() -> list[tuple[str, str, str]]:
    out = []
    for gid in GAMES:
        cls = REGISTRY[gid]
        for m in cls.modes:
            for mp in cls.maps:
                out.append((gid, m.id, mp))
    return out


# ------------------------------------------------------------------ declarations
@pytest.mark.parametrize("gid", GAMES)
def test_declares_modes_maps_themes_and_controls(gid: str) -> None:
    cls = REGISTRY[gid]
    assert len(cls.modes) >= 3 and cls.modes[0].id == "solo"
    assert any(m.teams in ("versus", "ffa") for m in cls.modes)
    assert 2 <= len(cls.maps) <= 4
    assert 2 <= len(cls.game_themes) <= 4
    assert cls.max_players == max(m.max_players for m in cls.modes)
    assert cls.controls
    props = cls.Settings.model_json_schema()["properties"]
    assert {"mode", "map", "players", "theme"} <= set(props)
    cls.Settings()  # every new field has a default


def _lum(c: tuple[int, int, int]) -> float:
    def lin(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = c
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


@pytest.mark.parametrize("gid", GAMES)
def test_genre_themes_never_camouflage(gid: str) -> None:
    """Dark, low-saturation backgrounds; players, enemies, pickups and HUD far brighter than them."""
    themes: dict[str, Theme] = REGISTRY[gid].game_themes
    for tid, th in themes.items():
        assert max(th.bg) <= 40 and max(th.bg) - min(th.bg) <= 24, f"{gid}/{tid}: bg too bright or saturated"
        for role in ("p", "e", "x", "hud"):
            gap = _lum(getattr(th, role)) - _lum(th.bg)
            assert gap >= 0.35, f"{gid}/{tid}: {role} only {gap:.2f} above the background"


def test_theme_backdrops_stay_dark() -> None:
    """The flat backdrop bands of the road and city looks are dark too."""
    for look in games_road.LOOKS.values():
        for band in (*look["sky"], *look["verge"], look["city"]):
            assert max(band) <= 60
    for look in games_city.LOOKS.values():
        assert max(look["roof"]) <= 30 and max(look["park"]) <= 30


@pytest.mark.parametrize("gid", GAMES)
async def test_every_theme_and_map_renders(gid: str) -> None:
    cls = REGISTRY[gid]
    for tid in cls.game_themes:
        for mp in cls.maps:
            app, clock = _make(gid, theme=tid, map=mp)
            _run(app, clock, 2)


def test_digworld_default_look_keeps_the_bright_world() -> None:
    from deskdot.apps import games_world as w

    pal = w._palette("overworld")
    assert pal[w.DIRT][0] == (140, 78, 32) and pal[w.STONE][0] == (92, 92, 108)
    for tid in ("frost", "dune"):  # new biomes are at least as bright as the meadow
        p = w._palette(tid)
        assert sum(p[w.DIRT][0]) >= sum((140, 78, 32)) - 40 and sum(p[w.STONE][0]) >= sum((92, 92, 108))


# ------------------------------------------------------------------ matches
@pytest.mark.parametrize("gid", GAMES)
async def test_each_mode_resets_with_ai_filling_the_seats(gid: str) -> None:
    cls = REGISTRY[gid]
    for m in cls.modes:
        app, clock = _make(gid)
        await _start(app, clock, m.id, m.max_players)
        assert app.play_mode.id == m.id
        assert sorted(app.roster) == list(range(1, m.max_players + 1))
        assert app.roster[1]["human"] and not any(app.roster[s]["human"] for s in app.roster if s > 1)
        seats = {
            "digworld": lambda a: set(a.miners),
            "neonheat": lambda a: set(a.players),
            "streetsurge": lambda a: set(a.players),
            "leafleap": lambda a: set(a.heroes),
        }[gid](app)
        assert seats == set(app.roster), f"{gid}/{m.id}: every seat has a player on the field"
        if m.teams == "versus":
            assert {app.team_of(s) for s in app.roster} == {0, 1}


@pytest.mark.parametrize(("gid", "mode", "map_id"), _combos())
async def test_every_mode_on_every_map_plays_30s(gid: str, mode: str, map_id: str) -> None:
    app, clock = _make(gid, seed=2)
    m = next(x for x in app.modes if x.id == mode)
    await _start(app, clock, mode, m.max_players, map_id)
    assert app.map_id == map_id
    worst = _run(app, clock, 30)
    assert worst < 0.05, f"{gid}/{mode}/{map_id}: render took {worst * 1000:.1f} ms"
    app.status()


FAST = {
    "digworld": {"day_length": 20, "match_days": 1},
    "neonheat": {"match_time": 60},
    "streetsurge": {"laps": 1, "rivals": 1},
    "leafleap": {"race_levels": 1},
}


@pytest.mark.parametrize(
    ("gid", "mode"),
    [(g, m.id) for g in GAMES for m in REGISTRY[g].modes if m.teams in ("versus", "ffa")],
)
async def test_competitive_modes_reach_a_result(gid: str, mode: str) -> None:
    app, clock = _make(gid, skill=1.0, **FAST[gid])
    m = next(x for x in app.modes if x.id == mode)
    await _start(app, clock, mode, m.max_players)
    _run(app, clock, 150, until=lambda: app.outcome is not None)
    assert app.outcome is not None, f"{gid}/{mode}: the match never ended"
    o = app.outcome
    assert o["seat"] is not None or o["team"] is not None
    assert o["scores"], "the results screen lists every seat's score"
    _run(app, clock, 2)
    assert app.flow == "outro"


# ------------------------------------------------------------------ damage feedback
def _hit(app: Any, gid: str) -> None:
    """Put a hazard right on seat 1."""
    if gid == "digworld":
        app.tod = 0.7  # night
        app.hurt = 0.0
        app._save(app._seat)
        app.mobs = [[float(app.mc + 1), float(app.mr), 2.0, 9.0, 0.0, 0.0, 0.0]]
    elif gid == "neonheat":
        me = app.players[1]
        me.carry, me.safe = True, 0.0
        me.car.stun = 5.0  # hold still on top of the police car
        app.cars.append(games_city.Car("police", me.car.x, me.car.y, me.car.dir, 0.0, games_city.POLICE))
    elif gid == "streetsurge":
        app.go = 0.0
        me = app.players[1]
        me.bump = 0.0
        for r in app.racers:
            if r.kind == "rival":
                r.d, r.x, r.v, r.vt = me.d + 0.4, me.x, 0.0, 0.0
                break
    else:
        app.safe, app.vy = 0.0, 0.0
        app.beetles = [[app.x - 0.5, app.y, 1.0, 1.0]]


@pytest.mark.parametrize("gid", GAMES)
@pytest.mark.parametrize("human", [True, False])
async def test_damage_flash_only_for_people(gid: str, human: bool) -> None:
    app, clock = _make(gid)
    if human:
        await _start(app, clock, "solo", 1)
    else:
        _run(app, clock, 1)
    calls: list[float] = []
    app.damage = lambda strength=1.0: calls.append(strength)  # type: ignore[method-assign]
    _hit(app, gid)
    clock.t += 0.05
    app._last = clock.t - 0.05
    app.advance(clock.t)
    if human:
        assert calls, f"{gid}: a person was hit but nothing flashed"
    else:
        assert not calls, f"{gid}: the demo AI got hit and the panel flashed red"


async def test_coop_partner_damage_counts_for_the_person_only() -> None:
    """Leaf Leap co-op: seat 1 (a person) falling in a pit flashes; the AI partner's deaths don't."""
    app, clock = _make("leafleap")
    await _start(app, clock, "coop", 2)
    calls: list[float] = []
    app.damage = lambda strength=1.0: calls.append(strength)  # type: ignore[method-assign]
    app._load(2)
    app._die()
    app._save(2)
    app._load(1)
    assert not calls
    app._die()
    assert calls
