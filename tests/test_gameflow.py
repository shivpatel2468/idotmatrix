"""The shared game flow: home menu (mode / players / map / theme), FIFA-style side select, intro, results,
the damage flash, and the per-game settings that GameApp builds from `modes`, `maps` and `game_themes`."""

from __future__ import annotations

from typing import Any, ClassVar

from deskdot.apps.games_core import THEMES, GameApp, Mode, Theme
from deskdot.gfx import Frame


class Ctx:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def save(self) -> None: ...


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Duel(GameApp):
    """A tiny versus game used only to exercise the framework."""

    id = "_duel_test"
    name = "Duel"
    max_players = 4
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("duel", "Versus", 2, 4, "versus"),
        Mode("party", "Party", 2, 4, "ffa"),
    )
    maps: ClassVar[dict[str, str]] = {"arena": "Arena", "cave": "Cave"}
    game_themes: ClassVar[dict[str, Theme]] = {"lava": THEMES["neon"]}

    def reset(self) -> None:
        super().reset()
        self.hits = 0

    def draw(self, f: Frame, now: float) -> None:
        f.clear(self.theme.bg)


def _game() -> tuple[Duel, Clock]:
    g = Duel(Ctx(), Duel.Settings())  # type: ignore[arg-type]
    c = Clock()
    g._clock = c  # type: ignore[method-assign]
    g.reset()
    return g, c


def _frames(g: GameApp, c: Clock, seconds: float) -> Frame:
    f = Frame()
    for _ in range(int(seconds * 10)):
        c.t += 0.1
        f = Frame()
        g.render(f, c.t)
    return f


async def _key(g: GameApp, k: str, player: int = 1, **extra: Any) -> dict[str, Any]:
    return await g.action("input", {"key": k, "player": player, **extra})


def test_settings_are_built_from_modes_maps_and_themes() -> None:
    props = Duel.Settings.model_json_schema()["properties"]
    assert set(props["mode"]["enum"] if "enum" in props["mode"] else props["mode"]["options"]) >= {
        "solo",
        "duel",
    }
    assert {"map", "players", "effects", "intro_outro", "attract", "theme"} <= set(props)
    s = Duel.Settings()
    assert s.mode == "solo" and s.map == "arena" and s.theme == "lava" and s.players == 1
    assert "mode" not in GameApp.Settings.model_json_schema()["properties"], "solo games keep a lean form"


async def test_b_opens_the_home_menu_and_start_plays() -> None:
    g, c = _game()
    _frames(g, c, 1)
    assert g.flow == "attract"
    await _key(g, "b")
    assert g.flow == "home"
    await _key(g, "right")  # mode row: Solo → Versus
    assert g.play_mode.id == "duel" and g.sel["players"] == 2
    await _key(g, "down")  # players
    await _key(g, "right")
    assert g.sel["players"] == 3
    await _key(g, "down")  # map
    await _key(g, "right")
    assert g.map_id == "cave"
    await _key(g, "a")  # jumps to START
    await _key(g, "a")
    assert g.flow == "teams"
    assert g.roster[1]["human"] and not g.roster[2]["human"]


async def test_side_select_like_fifa() -> None:
    g, c = _game()
    await g.action("seat", {"player": 2, "joined": True})
    await g.action("start", {"mode": "duel", "players": 4})
    assert g.flow == "teams"
    assert g.team_of(1) == 0 and g.team_of(2) == 1, "people start on alternating sides"
    await _key(g, "right")  # P1 → middle
    assert g.team_of(1) is None
    await _key(g, "a")  # can't ready in the middle
    assert not g.roster[1]["ready"]
    await _key(g, "right")  # P1 → team B, with P2: 2 v (AI, AI)
    await _key(g, "a")
    assert g.flow == "teams", "waits for every person"
    await _key(g, "a", player=2)
    assert g.flow == "intro"
    teams = [g.team_of(s) for s in (1, 2, 3, 4)]
    assert teams.count(0) == 2 and teams.count(1) == 2, "AI fills the smaller side: 2 v 2"
    assert g.team_of(1) == g.team_of(2) == 1
    assert g.colour_of(1) != g.colour_of(2), "teammates stay distinguishable"
    _frames(g, c, 3)
    assert g.flow == "play"
    assert g.is_human(1) and g.is_human(2) and not g.is_human(3)


async def test_everyone_on_one_side_still_makes_a_match() -> None:
    g, _ = _game()
    await g.action("start", {"mode": "duel", "players": 2})
    await _key(g, "left")
    await _key(g, "a")
    assert {g.team_of(1), g.team_of(2)} == {0, 1}


async def test_results_screen_rematch_and_menu() -> None:
    g, c = _game()
    await g.action("start", {"mode": "party", "players": 2})
    _frames(g, c, 3)
    assert g.flow == "play"
    g.result(winner_seat=2, scores={1: 3, 2: 5})
    _frames(g, c, 2.0)
    assert g.flow == "outro" and g.status()["outcome"]["seat"] == 2
    await _key(g, "a")
    assert g.flow == "intro", "A = rematch"
    _frames(g, c, 3)
    g.game_over()
    _frames(g, c, 2.0)
    await _key(g, "b")
    assert g.flow == "home", "B = back to the menu"


async def test_intro_outro_can_be_switched_off() -> None:
    g = Duel(Ctx(), Duel.Settings(intro_outro=False))  # type: ignore[arg-type]
    c = Clock()
    g._clock = c  # type: ignore[method-assign]
    await g.action("start", {"mode": "solo"})
    assert g.flow == "play"


async def test_idle_menu_falls_back_to_self_play() -> None:
    g, c = _game()
    await _key(g, "b")
    _frames(g, c, 50)
    assert g.flow == "attract"


def test_damage_flash_fades_and_respects_effects() -> None:
    g, c = _game()
    _frames(g, c, 0.5)
    clean = _frames(g, c, 0.1)
    g.damage()
    hit = _frames(g, c, 0.1)
    r, gg, _b = hit.px[16, 0]
    assert r > gg + 40, "red edge flash"
    assert tuple(hit.px[16, 16]) == tuple(clean.px[16, 16]), "the middle of the play-field stays clear"
    faded = _frames(g, c, 1.0)
    assert tuple(faded.px[16, 0]) == tuple(clean.px[16, 0])
    g2 = Duel(Ctx(), Duel.Settings(effects="minimal"))  # type: ignore[arg-type]
    g2.damage()
    assert g2.hurt_t == 0


def test_every_flow_screen_renders() -> None:
    g, c = _game()
    for flow in ("home", "teams", "intro", "outro"):
        g.flow, g.flow_t = flow, c.t
        if flow == "teams":
            g.sel["mode"] = "duel"
            g.begin()
        f = Frame()
        g.render(f, 0)
        assert f.px.any(), flow
