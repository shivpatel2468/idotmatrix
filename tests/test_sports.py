"""Live sports: ESPN parsers per sport family, diff events, polling, settings and every render variant.

Fixtures in tests/fixtures/sports/ are real ESPN captures (Sept 2026), trimmed to a few items.
"""

from __future__ import annotations

import copy
import itertools
import json
import time
from pathlib import Path
from typing import Any

import pytest

from deskdot.apps import scores as scores_app
from deskdot.apps import sports_draw as sd
from deskdot.apps.scores import Scores, ScoresSettings, parse_leagues
from deskdot.gfx import Frame
from deskdot.providers import sports
from deskdot.providers.sports import (
    LEAGUE_SPORT,
    LEAGUES,
    SportsProvider,
    parse_scoreboard,
    parse_standings,
    round_abbr,
    surname,
)

FIX = Path(__file__).parent / "fixtures" / "sports"
GAME_KEYS = {
    "id", "league", "tag", "sport", "kind", "state", "detail", "short", "clock", "period", "start",
    "name", "note", "headline", "last_play", "situation", "competitors", "away", "home",
}  # fmt: skip
COMP_KEYS = {"id", "name", "abbr", "short", "score", "color", "alt", "home", "winner", "extra"}
NOW = 1790200000.0  # 2026-09-24, when the fixtures were captured


def fx(name: str) -> dict[str, Any]:
    return json.loads((FIX / f"{name}.json").read_text())


def games(league: str, name: str) -> list[dict[str, Any]]:
    return parse_scoreboard(league, fx(name), now=NOW)


ALL = {
    "nba": "nba",
    "mlb": "mlb",
    "nhl": "nhl",
    "nfl": "nfl",
    "epl": "epl",
    "ipl": "ipl",
    "cricket": "cricket_all",
    "atp": "atp",
    "pga": "pga_final",
    "f1": "f1_race",
    "ufc": "ufc",
}


# ================================================================ parsers
@pytest.mark.parametrize(("league", "name"), [*ALL.items(), ("pga", "pga_cup"), ("f1", "f1_pre")])
def test_every_family_parses_into_the_common_schema(league: str, name: str) -> None:
    gs = games(league, name)
    assert gs, f"{league}: no games parsed"
    for g in gs:
        assert set(g) >= GAME_KEYS, GAME_KEYS - set(g)
        assert g["state"] in ("pre", "in", "post")
        assert g["league"] == league and g["tag"] == LEAGUES[league][1] and g["sport"] == LEAGUE_SPORT[league]
        assert g["kind"] in ("team", "duel", "field")
        for c in [*g["competitors"], g["away"], g["home"]]:
            assert set(c) >= COMP_KEYS
            assert c["color"].startswith("#") and len(c["color"]) == 7
            assert c["abbr"].isascii() and c["short"].isascii() and c["name"].isascii()
        json.dumps(g)  # plain data only


def test_team_sports_details() -> None:
    mlb = games("mlb", "mlb")
    live = next(g for g in mlb if g["state"] == "in")
    assert live["short"] in ("▲9", "▼9") or live["short"]
    assert set(live["situation"]) == {"balls", "strikes", "outs", "bases"}
    assert live["away"]["home"] is False and live["home"]["home"] is True
    assert live["away"]["extra"]["record"]
    epl = games("epl", "epl")
    assert all(g["short"] == "FT" for g in epl)
    assert any(g["last_play"] and "'" in g["last_play"] for g in epl)  # "57' ISAK"
    assert any(c["winner"] is True for g in epl for c in g["competitors"])
    nfl = games("nfl", "nfl")
    assert nfl[0]["state"] == "pre" and nfl[0]["start"]


def test_cricket_scores_are_parsed_into_runs_wickets_overs() -> None:
    (final,) = games("ipl", "ipl")
    rcb = next(c for c in final["competitors"] if c["abbr"] == "RCB")
    assert rcb["score"] == "161/5" and rcb["extra"]["runs"] == 161 and rcb["extra"]["wickets"] == 5
    assert rcb["extra"]["overs"] == "18" and rcb["extra"]["target"] == 156 and rcb["winner"] is True
    assert "WON" in final["headline"]
    world = games("cricket", "cricket_all")
    assert world and all(g["kind"] == "team" for g in world)
    assert any(g["state"] == "in" and g["short"] == "LIVE" for g in world)
    assert sports._cricket_score("110 & 78/4 (18 ov)")[1]["runs"] == 188


def test_tennis_golf_racing_mma() -> None:
    tennis = parse_scoreboard("atp", fx("atp"), now=NOW + 30 * 86400)  # quiet day: latest results
    post = next(g for g in tennis if g["state"] == "post")
    assert post["kind"] == "duel" and post["note"].startswith(("Q", "R"))
    sets = post["away"]["extra"]["sets"]
    assert sets and {"games", "tb", "won"} <= set(sets[0])
    assert post["away"]["score"] == str(sum(s["won"] for s in sets))

    (golf,) = games("pga", "pga_final")
    assert golf["kind"] == "field" and golf["competitors"][0]["extra"]["pos"] == "1"
    assert golf["competitors"][0]["short"] == "SCHEFFLER" and golf["competitors"][0]["score"] == "-16"
    assert any(c["extra"]["pos"].startswith("T") for c in golf["competitors"])  # ties
    (cup,) = games("pga", "pga_cup")
    assert cup["kind"] == "team" and {cup["away"]["abbr"], cup["home"]["abbr"]} == {"USA", "INTL"}

    (race,) = games("f1", "f1_race")
    assert race["note"] == "RACE" and race["state"] == "post"
    p1 = race["competitors"][0]
    assert p1["abbr"] == "ANT" and p1["extra"]["team"] == "MERCEDES" and p1["color"] == "#00d2be"
    (pre,) = games("f1", "f1_pre")
    assert pre["state"] == "pre" and pre["competitors"] == [] and pre["away"]["abbr"] == ""

    ufc = games("ufc", "ufc")
    assert ufc[0]["main"] is True and all(g["kind"] == "duel" for g in ufc)
    done = next(g for g in ufc if g["state"] == "post")
    assert {done["away"]["score"], done["home"]["score"]} <= {"W", "L", "D"}
    assert done["away"]["extra"]["record"]


def test_text_helpers() -> None:
    assert surname("N. Növényi Jr.") == "NOVENYI"
    assert surname("A. Wang") == "WANG"
    assert surname("", "Kimi Antonelli") == "ANTONELLI"
    assert round_abbr("Qualifying 1st Round") == "Q1"
    assert round_abbr("Quarterfinal") == "QF" and round_abbr("Round 2") == "R2" and round_abbr("Final") == "F"


def test_standings() -> None:
    epl = parse_standings("epl", fx("standings_epl"))
    assert [r["rank"] for r in epl] == list(range(1, len(epl) + 1))
    assert epl[0]["label"] == "PTS" and epl[0]["value"].isdigit()
    nba = parse_standings("nba", fx("standings_nba"), {"ATL": ("#e03a3e", "#c1d32f")})
    assert {r["group"] for r in nba} >= {"EAST", "WEST"} or len({r["group"] for r in nba}) == 2
    assert next(r for r in nba if r["abbr"] == "ATL")["color"] == "#e03a3e"
    f1 = parse_standings("f1", fx("standings_f1"))
    assert f1[0]["abbr"] == "ANT" and f1[0]["color"] == "#00d2be" and "DRIVER" in f1[0]["group"]


# ================================================================ provider
class FakeResp:
    def __init__(self, data: dict[str, Any]) -> None:
        self._d = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._d


class FakeHttp:
    def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
        self.routes, self.calls = routes, []

    async def get(self, url: str) -> FakeResp:
        self.calls.append(url)
        for key, data in self.routes.items():
            if key in url:
                return FakeResp(data)
        raise RuntimeError(f"no route for {url}")


class FakeStore:
    def __init__(self, apps: dict[str, Any] | None = None) -> None:
        self.apps = apps or {}

    def section(self, name: str) -> dict[str, Any]:
        return self.apps


class FakeHub:
    def __init__(self, routes: dict[str, dict[str, Any]], apps: dict[str, Any] | None = None) -> None:
        self.http = FakeHttp(routes)
        self.store = FakeStore(apps)
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))


ROUTES = {
    "baseball/mlb/scoreboard": fx("mlb"),
    "soccer/eng.1/scoreboard": fx("epl"),
    "basketball/nba/scoreboard": fx("nba"),
    "cricket/8048/scoreboard": fx("ipl"),
    "soccer/eng.1/standings": fx("standings_epl"),
}


async def test_fetch_only_wanted_and_due_leagues() -> None:
    hub = FakeHub(ROUTES)
    p = SportsProvider(hub)
    p.want("mlb", "epl")
    v = await p.fetch()
    assert set(v) == {"nba", "mlb", "epl"}  # nba is the historical default want
    assert len(hub.http.calls) == 3
    hub.http.calls.clear()
    p.value = v
    await p.fetch()
    assert hub.http.calls == []  # nothing due yet: no refetch of every league every tick
    p._due["mlb"] = 0.0
    await p.fetch()
    assert len(hub.http.calls) == 1 and "baseball/mlb" in hub.http.calls[0]
    # a live league polls every 20 s, a quiet one every 5 min
    assert p._cadence(v["mlb"]) == sports.LIVE_EVERY
    assert p._cadence(v["epl"]) == sports.IDLE_EVERY
    assert 2.0 <= p.next_interval() <= sports.LIVE_EVERY


async def test_tables_and_stored_leagues_and_errors() -> None:
    hub = FakeHub(ROUTES, apps={"scores": {"leagues": "ipl,epl,bogus"}})
    p = SportsProvider(hub)
    p.want_table("epl", "atp")  # atp has no table and is ignored for tables
    v = await p.fetch()
    assert "ipl" in v  # from the saved Live Scores settings, so background alerts cover it
    assert p.tables["epl"][0]["rank"] == 1 and "atp" not in p.table_leagues
    p.want("nhl")  # no route -> error recorded for that league only
    p.value = v
    v2 = await p.fetch()
    assert "nhl" in p.errors and "nhl" not in v2 and v2["epl"]


def _bump(g: dict[str, Any], side: str, by: int) -> dict[str, Any]:
    g = copy.deepcopy(g)
    g[side]["score"] = str(int(g[side]["score"]) + by)
    return g


def test_diff_events_keep_the_engine_contract() -> None:
    hub = FakeHub({})
    p = SportsProvider(hub)
    mlb = games("mlb", "mlb")
    live = next(g for g in mlb if g["state"] == "in")
    p._diff({}, {"mlb": mlb})
    assert hub.events == []  # first load: nothing happened
    p._diff({"mlb": [live]}, {"mlb": [_bump(live, "home", 2)]})
    (ev, data) = hub.events[-1]
    assert ev == "score" and set(data) == {"league", "tag", "game", "side", "team", "delta"}
    assert data["league"] == "mlb" and data["tag"] == "MLB" and data["side"] == "home" and data["delta"] == 2
    assert data["team"]["abbr"] == live["home"]["abbr"]
    pre = {**copy.deepcopy(live), "state": "pre"}
    post = {**copy.deepcopy(live), "state": "post"}
    hub.events.clear()
    p._diff({"mlb": [pre]}, {"mlb": [live]})
    p._diff({"mlb": [live]}, {"mlb": [post]})
    assert [e for e, _ in hub.events] == ["game_start", "game_final"]
    assert all(set(d) == {"league", "tag", "game"} for _, d in hub.events)


def test_diff_sport_rules() -> None:
    hub = FakeHub({})
    p = SportsProvider(hub)
    (race,) = games("f1", "f1_race")
    p._diff({"f1": [{**race, "state": "in"}]}, {"f1": [race]})
    assert hub.events == []  # field sports (golf, F1) emit nothing
    (ipl,) = games("ipl", "ipl")
    before = copy.deepcopy(ipl)
    after = copy.deepcopy(ipl)
    after["home"]["extra"]["runs"] += 2
    p._diff({"ipl": [before]}, {"ipl": [after]})
    assert hub.events == []  # singles/twos are not alerts
    after["home"]["extra"]["runs"] += 4
    p._diff({"ipl": [before]}, {"ipl": [after]})
    assert hub.events[-1][0] == "score" and hub.events[-1][1]["delta"] == 6
    ufc = games("ufc", "ufc")
    hub.events.clear()
    p._diff({"ufc": [{**ufc[1], "state": "in"}]}, {"ufc": [ufc[1]]})
    assert [e for e, _ in hub.events] == ["game_final"]


async def test_engine_consumes_the_events(engine) -> None:  # type: ignore[no-untyped-def]
    engine.store.section("apps")["scores"] = {"alerts": "all", "team": ""}
    live = next(g for g in games("mlb", "mlb") if g["state"] == "in")
    base = {"league": "mlb", "tag": "MLB", "game": live}
    engine._on_event("score", {**base, "side": "home", "team": live["home"], "delta": 1})
    engine._on_event("game_start", base)
    engine._on_event("game_final", base)
    for g in games("atp", "atp")[:1] + games("ufc", "ufc")[:1] + games("cricket", "cricket_all")[:1]:
        engine._on_event("game_final", {"league": g["league"], "tag": g["tag"], "game": g})
    assert len(engine.notices) >= 3


# ================================================================ settings
def test_parse_leagues() -> None:
    assert parse_leagues("NBA, epl ,Serie A,liga,f1") == ["nba", "epl", "seriea", "laliga", "f1"]
    assert parse_leagues("nba,nba,") == ["nba"]
    assert parse_leagues("premier league,wc") == ["epl", "worldcup"]
    with pytest.raises(ValueError):
        parse_leagues("nba,quidditch")


def test_settings_backward_compat() -> None:
    old = ScoresSettings.model_validate(
        {"league": "nba", "layout": "hero", "team": "LAL", "alerts": "favorite"}
    )
    assert old.mode == "favorites" and old.layout == "hero" and old.team == "LAL" and old.leagues == ""
    assert ScoresSettings.model_validate({"league": "epl"}).mode == "focus"
    s = ScoresSettings.model_validate({"leagues": "EPL, ipl", "team": " lal, ars ,mi", "mode": "all"})
    assert s.leagues == "epl,ipl" and s.team == "LAL,ARS,MI"
    with pytest.raises(ValueError):
        ScoresSettings.model_validate({"leagues": "nba,nope"})
    # the engine reads these three keys directly
    assert {"alerts", "team", "league"} <= set(ScoresSettings.model_fields)
    assert scores_app.led_team_color("#000000", "#fdb927") == sd.led_team_color("#000000", "#fdb927")


# ================================================================ app
class Prov:
    def __init__(self, value: Any = None, tables: Any = None, error: str | None = None) -> None:
        self.value, self.tables, self.error, self.errors = value, tables or {}, error, {}
        self.updated = time.time()
        self.wanted: list[str] = []
        self.tabled: list[str] = []

    def want(self, *a: str) -> None:
        self.wanted += a

    def want_table(self, *a: str) -> None:
        self.tabled += a


class Ctx:
    def __init__(self, p: Prov) -> None:
        self.p = p

    def provider(self, name: str) -> Prov:
        return self.p


VALUE = {k: games(k, n) for k, n in ALL.items()}
TABLES = {
    "epl": parse_standings("epl", fx("standings_epl")),
    "nba": parse_standings("nba", fx("standings_nba")),
    "f1": parse_standings("f1", fx("standings_f1")),
}


def app_for(settings: dict[str, Any], prov: Prov) -> Scores:
    a = Scores(Ctx(prov), ScoresSettings.model_validate(settings))  # type: ignore[arg-type]
    a.on_start()
    return a


def _variants() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{}]
    for name, f in ScoresSettings.model_fields.items():
        extra = f.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra and name != "league":
            out += [{name: v} for v in extra["enum"]]
    modes = ["focus", "all", "live_only", "favorites", "table"]
    layouts = ["classic", "hero", "big_score", "compact", "ticker"]
    for m, lay in itertools.product(modes, layouts):
        out.append(
            {"mode": m, "layout": lay, "scroll_direction": "horizontal" if lay == "hero" else "vertical"}
        )
    for flag in ("show_logos_colors", "show_clock", "show_records", "show_icons"):
        out.append({flag: False})
        out.append({flag: True})
    out.append({"league": "nba", "layout": "hero", "team": "LAL", "alerts": "favorite"})  # legacy dict
    return out


LEAGUE_SETS = ["", *ALL, "mlb,epl,ipl,atp,pga,f1,ufc,cricket,nba,nfl,nhl"]


@pytest.mark.parametrize("settings", _variants(), ids=lambda s: json.dumps(s, sort_keys=True))
@pytest.mark.parametrize("leagues", LEAGUE_SETS)
def test_every_variant_renders_with_and_without_data(settings: dict[str, Any], leagues: str) -> None:
    cfg = {**settings, "leagues": leagues, "team": settings.get("team", "MIA,RCB,SCHEFFLER")}
    for prov in (Prov(), Prov(error="boom"), Prov(VALUE, TABLES), Prov({k: [] for k in VALUE}, {})):
        app = app_for(cfg, prov)
        worst = 0.0
        for t in (0.0, 0.37, 3.3, 7.3, 19.9):
            f = Frame()
            t0 = time.perf_counter()
            app.render(f, t)
            worst = max(worst, time.perf_counter() - t0)
            assert f.px.shape == (32, 32, 3)
        assert worst < 0.05, f"render took {worst * 1000:.1f} ms"
        app.status()
        app.relevant()
        app.wants_focus()
        app.watches_focus()
    if prov.value:
        f = Frame()
        app_for(cfg, Prov(VALUE, TABLES)).render(f, 1.0)
        assert f.px.any(), "blank panel with data"


def test_render_is_not_blank_for_each_sport_and_layout() -> None:
    for league, lay in itertools.product(ALL, ["classic", "hero", "big_score", "compact", "ticker"]):
        f = Frame()
        app_for({"leagues": league, "layout": lay}, Prov(VALUE, TABLES)).render(f, 0.5)
        assert int(f.px.sum()) > 2000, (league, lay)


def test_modes_select_the_right_games() -> None:
    prov = Prov(VALUE, TABLES)
    multi = "mlb,epl,ipl,atp"
    everything = app_for({"leagues": multi, "mode": "focus"}, prov).games()
    assert {g["league"] for g in everything} == {"mlb", "epl", "ipl", "atp"}
    order = [g["state"] for g in everything]
    assert order == sorted(order, key={"in": 0, "pre": 1, "post": 2}.get)  # live first
    live = app_for({"leagues": multi, "mode": "live_only"}, prov).games()
    assert live and all(g["state"] == "in" for g in live)
    fav_team = everything[0]["home"]["abbr"]
    favs = app_for({"leagues": multi, "mode": "favorites", "team": f"{fav_team},RCB"}, prov).games()
    assert favs and all(sd.is_fav(g, frozenset({fav_team, "RCB"})) for g in favs)
    assert {g["league"] for g in favs} >= {"ipl"}
    # focus with favourites: the favourites come first
    f = app_for({"leagues": multi, "mode": "focus", "team": "RCB"}, prov).games()
    posts = [g for g in f if g["state"] == "post"]
    assert sd.is_fav(posts[0], frozenset({"RCB"}))
    assert len(f) == len(everything)  # focus keeps every game
    # scheduling across leagues
    a = app_for({"leagues": multi, "team": fav_team, "take_over": True, "mode": "focus"}, prov)
    assert a.watches_focus() and a.relevant()
    assert a.wants_focus() == any(
        g["state"] == "in" for g in favs if g["league"] in ("mlb", "epl", "ipl", "atp")
    )
    assert not app_for({"leagues": "epl", "mode": "live_only"}, prov).relevant()  # nothing live in EPL
    assert app_for({"leagues": "epl", "mode": "table"}, prov).relevant()
    assert prov.wanted and "mlb" in prov.wanted
    app_for({"leagues": "epl,nba", "mode": "table"}, prov)
    assert {"epl", "nba"} <= set(prov.tabled)
    assert not app_for({"league": "nba", "team": "ZZZ"}, prov).relevant()


def test_scroll_mode_moves_and_fps_follows_speed() -> None:
    prov = Prov(VALUE, TABLES)
    for d in ("vertical", "horizontal"):
        app = app_for({"leagues": "mlb,epl", "mode": "all", "scroll_direction": d, "scroll_speed": 12}, prov)
        assert app.fps == 12
        a, b = Frame(), Frame()
        app.render(a, 1.0)
        app.render(b, 1.5)
        assert (a.px != b.px).any(), f"{d} scroll did not move"
    assert app_for({"mode": "focus"}, prov).fps == 6.0


def test_time_formats() -> None:
    g = {"start": "2026-09-24T19:00Z"}
    o = sd.Opts(now=sports._parse_iso("2026-09-24T17:00Z") or 0)
    assert sd.when(g, o.but(time_format="countdown")) == "2H"
    assert sd.when(g, o.but(time_format="countdown"), long=True) == "IN 2H"
    assert ":" in sd.when(g, o.but(time_format="24h")) or sd.when(g, o.but(time_format="24h")).isdigit()
    assert sd.when(g, o)[-1] in "AP"
    assert sd.when({"start": None}, o) == "TBD"


def test_icons_are_5x5_and_every_sport_has_one() -> None:
    for sport in {*LEAGUE_SPORT.values(), "other"}:
        rows, pal = sd.ICONS[sport]
        assert len(rows) == 5 and all(len(r) == 5 for r in rows)
        assert all(ch in pal for r in rows for ch in r if ch != ".")
