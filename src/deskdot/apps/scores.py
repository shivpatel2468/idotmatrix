"""Live Scores — every ESPN sport in team colours: focus cards, a continuous all-games scroll, tables.

Modes
    focus      one game at a time (layout: classic / hero / big_score / compact / ticker), rotating
    all        every game of every chosen league in one smooth vertical or horizontal scroll
    live_only  only games in progress; otherwise "NO LIVE GAMES" and a countdown to the next one
    favorites  only your teams / players (comma list, e.g. "LAL,ARS,MI,SINNER")
    table      league standings, paged smoothly

Athlete sports always use their own card: tennis sets grid, golf leaderboard, F1 top 3 in constructor
colours, UFC fighter vs fighter. Cricket alternates a scores face and a match-situation face.
"""

from __future__ import annotations

import math
import time
from typing import Any

from pydantic import Field, field_validator, model_validator

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import Frame
from ..gfx.font import measure
from ..providers.sports import LEAGUES, TABLE_SPORTS, sport_of
from . import sports_draw as sd
from ._kit import loading, offline
from .sports_draw import led_team_color

__all__ = ["Scores", "ScoresSettings", "led_team_color", "parse_leagues"]

_TAGS = {v[1].replace(" ", "").lower(): k for k, v in LEAGUES.items()}
_ALIASES = {
    "premierleague": "epl",
    "premier": "epl",
    "championsleague": "ucl",
    "europa": "uel",
    "wc": "worldcup",
}


def parse_leagues(raw: str) -> list[str]:
    """'NBA, epl ,Serie A' -> ['nba', 'epl', 'seriea'] (keys or tags, any case); raises on unknown names."""
    out: list[str] = []
    bad: list[str] = []
    for part in str(raw or "").split(","):
        tok = part.strip().lower()
        if not tok:
            continue
        flat = tok.replace(" ", "")
        key = (
            tok
            if tok in LEAGUES
            else _TAGS.get(flat) or _ALIASES.get(flat) or (flat if flat in LEAGUES else None)
        )
        if key is None:
            bad.append(part.strip())
        elif key not in out:
            out.append(key)
    if bad:
        raise ValueError(f"unknown league(s) {', '.join(bad)}; choose from {', '.join(LEAGUES)}")
    return out


class ScoresSettings(AppSettings):
    league: str = Choice(
        "nba",
        {k: v[1] for k, v in LEAGUES.items()},
        title="League",
        group="Leagues",
        description="Used when 'Leagues' is empty",
    )
    leagues: str = Field(
        "",
        max_length=200,
        title="Leagues",
        description=f"Comma list, several at once: e.g. nba,epl,ipl,f1. Options: {', '.join(LEAGUES)}",
        json_schema_extra={"group": "Leagues"},
    )
    team: str = Field(
        "",
        max_length=80,
        title="Favourite teams",
        description="Comma list of abbreviations or player surnames, e.g. LAL,ARS,MI,SINNER",
        json_schema_extra={"group": "Leagues"},
    )
    mode: str = Choice(
        "focus",
        {
            "focus": "One game at a time",
            "all": "All games (scroll)",
            "live_only": "Live games only",
            "favorites": "Favourites only",
            "table": "League table",
        },
        title="Mode",
        group="Display",
    )
    layout: str = Choice(
        "classic",
        {
            "classic": "Classic",
            "hero": "Split hero",
            "big_score": "Big score",
            "compact": "Compact (2 games)",
            "ticker": "Ticker (all games)",
        },
        title="Layout",
        group="Display",
        description="Team sports; tennis, golf, F1 and UFC always use their own card",
    )
    rotate: int = Field(6, ge=3, le=60, title="Seconds per game", json_schema_extra={"group": "Display"})
    time_format: str = Choice(
        "12h",
        {"12h": "7:30P", "24h": "19:30", "countdown": "IN 2H"},
        title="Upcoming games",
        group="Display",
    )
    show_logos_colors: bool = Field(True, title="Team colours", json_schema_extra={"group": "Display"})
    show_clock: bool = Field(True, title="Game clock", json_schema_extra={"group": "Display"})
    show_records: bool = Field(False, title="Team records", json_schema_extra={"group": "Display"})
    show_icons: bool = Field(True, title="Sport icons", json_schema_extra={"group": "Display"})
    scroll_direction: str = Choice(
        "vertical",
        {"vertical": "Vertical", "horizontal": "Horizontal"},
        title="Scroll direction",
        group="Scroll",
    )
    scroll_speed: int = Field(
        10,
        ge=4,
        le=30,
        title="Scroll speed",
        description="Pixels per second",
        json_schema_extra={"group": "Scroll"},
    )
    take_over: bool = Field(
        False, title="Take over when favourite is live", json_schema_extra={"group": "Alerts"}
    )
    alerts: str = Choice(
        "favorite",
        {"off": "Off", "favorite": "Favourite team", "all": "All games"},
        title="Goal / score alerts",
        description="Celebration overlay, even when not on screen",
        group="Alerts",
    )

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data: Any) -> Any:
        # Before modes existed, a favourite team meant "only that team's games".
        if isinstance(data, dict) and "mode" not in data and str(data.get("team") or "").strip():
            data = {**data, "mode": "favorites"}
        return data

    @field_validator("leagues", mode="before")
    @classmethod
    def _check_leagues(cls, v: Any) -> str:
        return ",".join(parse_leagues(str(v or "")))

    @field_validator("team", mode="before")
    @classmethod
    def _norm_team(cls, v: Any) -> str:
        return ",".join(p.strip().upper() for p in str(v or "").split(",") if p.strip())


@register
class Scores(App):
    id = "scores"
    name = "Live Scores"
    description = "NBA, NFL, MLB, NHL, soccer, cricket, tennis, golf, F1 and UFC — live, in team colours."
    icon = "trophy"
    category = "data"
    Settings = ScoresSettings
    fps = 6.0
    uses = ("sports",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._cache_key: tuple[Any, ...] | None = None
        self._pool: list[dict[str, Any]] = []
        self._configure()

    # ------------------------------------------------------------ settings
    def _configure(self) -> None:
        s = self.settings
        self.fps = float(min(15, max(4, s.scroll_speed))) if s.mode == "all" else 6.0
        self._cache_key = None

    def league_keys(self) -> list[str]:
        try:
            keys = parse_leagues(self.settings.leagues)
        except ValueError:
            keys = []
        return keys or [self.settings.league]

    def favs(self) -> frozenset[str]:
        return frozenset(p for p in self.settings.team.split(",") if p)

    def on_start(self) -> None:
        p = self.ctx.provider("sports")
        keys = self.league_keys()
        p.want(*keys)
        if self.settings.mode == "table" and hasattr(p, "want_table"):
            p.want_table(*keys)

    def on_settings(self) -> None:
        self._configure()
        self.on_start()

    # ---------------------------------------------------------------- data
    def all_games(self) -> list[dict[str, Any]]:
        value = self.ctx.provider("sports").value or {}
        out: list[dict[str, Any]] = []
        for k in self.league_keys():
            out += value.get(k, [])
        return out

    def games(self) -> list[dict[str, Any]]:
        """The games the current mode shows, live first (favourites first within each state)."""
        p = self.ctx.provider("sports")
        key = (id(p.value), p.updated, id(self.settings))
        if key == self._cache_key:
            return self._pool
        favs = self.favs()
        mode = self.settings.mode
        games = self.all_games()
        if mode == "live_only":
            games = [g for g in games if g["state"] == "in"]
        elif mode == "favorites":
            games = [g for g in games if sd.is_fav(g, favs)]
        order = {"in": 0, "pre": 1, "post": 2}
        idx = {id(g): i for i, g in enumerate(games)}
        games = sorted(games, key=lambda g: (order.get(g["state"], 3), not sd.is_fav(g, favs), idx[id(g)]))
        self._cache_key, self._pool = key, games
        return games

    def _focus_games(self) -> list[dict[str, Any]]:
        favs = self.favs()
        gs = self.all_games()
        return [g for g in gs if sd.is_fav(g, favs)] if favs else gs

    # ---------------------------------------------------------- scheduling
    def relevant(self) -> bool:
        p = self.ctx.provider("sports")
        if p.value is None:
            return True
        if self.settings.mode == "table":
            return any((getattr(p, "tables", {}) or {}).get(k) for k in self.league_keys()) or not getattr(
                p, "tables", None
            )
        return bool(self.games())

    def watches_focus(self) -> bool:
        return self.settings.take_over and bool(self.favs())

    def wants_focus(self) -> bool:
        return any(g["state"] == "in" for g in self._focus_games())

    def status(self) -> dict[str, Any]:
        gs = self.games()
        return {
            "games": len(gs),
            "live": sum(g["state"] == "in" for g in gs),
            "leagues": self.league_keys(),
            "mode": self.settings.mode,
        }

    # -------------------------------------------------------------- render
    def _opts(self) -> sd.Opts:
        s = self.settings
        return sd.Opts(
            colors=s.show_logos_colors,
            clock=s.show_clock,
            records=s.show_records,
            icons=s.show_icons,
            time_format=s.time_format,
            layout=s.layout,
            favs=self.favs(),
            now=time.time(),
        )

    def _tag(self) -> str:
        keys = self.league_keys()
        return LEAGUES[keys[0]][1] if len(keys) == 1 else "SCORES"

    def render(self, f: Frame, t: float) -> None:
        p = self.ctx.provider("sports")
        keys = self.league_keys()
        tag = self._tag()
        o = self._opts()
        sport = sport_of(keys[0]) if len(keys) == 1 else "other"
        if p.value is None:
            (offline(f, tag, "OFFLINE") if p.error else loading(f, t, tag, sd.GOLD))
            return
        if not any(k in p.value for k in keys):
            errs = getattr(p, "errors", {}) or {}
            (offline(f, tag, "OFFLINE") if any(k in errs for k in keys) else loading(f, t, tag, sd.GOLD))
            return
        pen = sd.Pen(f)
        mode = self.settings.mode
        if mode == "table":
            self._table(pen, t, o, keys)
            return
        games = self.games()
        if not games:
            self._empty(pen, t, o, sport, tag, mode)
            return
        if mode == "all":
            (self._scroll_h if self.settings.scroll_direction == "horizontal" else self._scroll_v)(
                f, t, o, games
            )
            return
        rot = self.settings.rotate
        if self.settings.layout == "compact":
            pages = [games[i : i + 2] for i in range(0, len(games), 2)]
            page = pages[int(t // rot) % len(pages)]
            if any(g.get("kind") == "field" for g in page) and len(page) > 1:
                page = page[:1]
            if len(page) == 1 and page[0].get("kind") == "field":
                sd.card(pen, page[0], t, o, "classic")
            else:
                sd.compact(pen, page, t, o)
            return
        g = games[int(t // rot) % len(games)]
        face = 1 if g["sport"] == "cricket" and g["state"] != "pre" and (t % rot) > rot * 0.55 else 0
        if self.settings.layout == "ticker":
            sd.card(pen, g, t, o, "classic", face)
            if len(games) > 1:
                f.rect(0, 25, 32, 7, (0, 0, 0))
                f.hline(0, 25, 32, sd.SHADE)
                # 12 px/s = exactly 2 px per streamed frame at 6 fps (14 px/s hopped 2-3 px unevenly)
                sd.Pen(f).marquee(sd.ticker_line(games, o), t, 1, 26, 30, (200, 200, 120), speed=12)
            return
        sd.card(pen, g, t, o, face=face)

    # ------------------------------------------------------------- states
    def _empty(self, p: sd.Pen, t: float, o: sd.Opts, sport: str, tag: str, mode: str) -> None:
        upcoming = sorted(
            (g for g in self.all_games() if g["state"] == "pre" and sd.start_ts(g.get("start"))),
            key=lambda g: sd.start_ts(g["start"]) or 0,
        )
        if mode == "favorites":
            upcoming = [g for g in upcoming if sd.is_fav(g, o.favs)]
        nxt = upcoming[0] if upcoming else None
        if mode == "favorites" and not o.favs:
            sd.message(p, sport, tag, "NO TEAMS", o, t, foot="ADD FAVOURITE TEAMS IN SETTINGS")
            return
        big = "NO LIVE" if mode == "live_only" else "NO GAMES"
        foot = ""
        if nxt is not None:
            label = "abbr" if nxt.get("kind") == "team" else "short"
            if nxt.get("kind") == "field":
                who = nxt.get("name") or nxt["tag"]
            else:
                who = f"{nxt['away'][label]} V {nxt['home'][label]}"
            cd = sd.when(nxt, o.but(time_format="countdown"), long=True)
            foot = f"NEXT {who} {cd}" + (
                f" · {sd.when(nxt, o, long=True)}" if o.time_format != "countdown" else ""
            )
        elif mode == "favorites":
            foot = " ".join(sorted(o.favs))
        sd.message(p, sport, tag, big, o, t, foot=foot)

    # ------------------------------------------------------------- scrolls
    def _scroll_v(self, f: Frame, t: float, o: sd.Opts, games: list[dict[str, Any]]) -> None:
        """Continuous upward scroll: a league strip, then each game as a 16 px block."""
        items: list[tuple[str, Any, int]] = []
        last = None
        for g in games:
            if g["league"] != last:
                items.append(("hdr", g, 8))
                last = g["league"]
            items.append(("game", g, 16))
        total = sum(h for _, _, h in items)
        off = (t * self.settings.scroll_speed) % total if total > 32 else 0.0
        oi = int(off)
        for rep in (0, total) if total > 32 else (0,):
            y = rep - oi
            for kind, g, h in items:
                if y + h > 0 and y < 32:
                    pen = sd.Pen(f, 0, y, 32, h)
                    if kind == "hdr":
                        self._strip(pen, g, t, o)
                    else:
                        sd.compact_block(pen, g, t, o)
                        pen.hline(3, 15, 28, (56, 56, 72))  # divider: (12, 12, 18) was black on the LEDs
                y += h
                if y >= 32:
                    break

    def _strip(self, p: sd.Pen, g: dict[str, Any], t: float, o: sd.Opts) -> None:
        live = sum(1 for x in self.games() if x["league"] == g["league"] and x["state"] == "in")
        p.rect(0, 0, 32, 7, (14, 12, 0))
        x = 1
        if o.icons:
            sd.icon(p, g["sport"], 1, 1)
            x = 7
        p.text(x, 1, g["tag"], sd.GOLD)
        if live:
            p.text_right(27, 1, str(live), sd.SOFT)
            p.rect(29, 2, 2, 2, sd.pulse(t))

    def _scroll_h(self, f: Frame, t: float, o: sd.Opts, games: list[dict[str, Any]]) -> None:
        """Continuous leftward strip of full game cards, 4 px apart."""
        pitch = 36
        total = pitch * len(games)
        if len(games) == 1:
            sd.card(sd.Pen(f), games[0], t, o, self._h_layout())
            return
        off = int((t * self.settings.scroll_speed) % total)
        for rep in (0, total):
            for i, g in enumerate(games):
                x = rep + i * pitch - off
                if -32 < x < 32:
                    sd.card(sd.Pen(f, x, 0, 32, 32), g, t, o, self._h_layout())

    def _h_layout(self) -> str:
        return self.settings.layout if self.settings.layout in ("classic", "hero", "big_score") else "classic"

    # --------------------------------------------------------------- table
    def _table(self, p: sd.Pen, t: float, o: sd.Opts, keys: list[str]) -> None:
        """Standings, 4 rows a page (each conference/group starts a page), eased page flips."""
        prov = self.ctx.provider("sports")
        tables = getattr(prov, "tables", {}) or {}
        usable = [k for k in keys if sport_of(k) in TABLE_SPORTS and k != "cricket"]
        if not usable:
            sd.message(
                p,
                sport_of(keys[0]),
                LEAGUES[keys[0]][1],
                "NO TABLE",
                o,
                t,
                foot="NOT AVAILABLE FOR THIS SPORT",
            )
            return
        rot = self.settings.rotate
        per_page = 4
        padded = {k: _pad_groups(tables.get(k) or [], per_page) for k in usable}
        pages_of = {k: max(1, len(padded[k]) // per_page) for k in usable}
        spans = [max(2, pages_of[k]) * rot for k in usable]  # a league stays for all of its pages
        cyc = t % sum(spans)
        li = 0
        while cyc >= spans[li]:
            cyc -= spans[li]
            li += 1
        key = usable[li]
        tag = LEAGUES[key][1]
        if tables.get(key) is None:
            loading(p.f, t, tag, sd.GOLD)
            return
        rows = padded[key]
        if not rows:
            sd.message(p, sport_of(key), tag, "NO TABLE", o, t)
            return
        pages = pages_of[key]
        page_f = cyc / rot
        page = int(page_f) % pages
        frac = page_f - int(page_f)
        pitch = 6
        pos = page * per_page * pitch
        if frac < 0.12 and page > 0:  # ease in from the previous page
            k = 0.5 - 0.5 * math.cos(math.pi * frac / 0.12)
            pos = int((page - 1 + k) * per_page * pitch)
        visible = [r for r in rows[pos // pitch : pos // pitch + per_page + 1] if r]
        group = GROUP_LABELS.get(visible[0].get("group", ""), visible[0].get("group", "")) if visible else ""
        group = group if group and len(group) <= 5 else ""
        need = measure(tag) + (measure(group) + 2 if group else 0)
        x = 7 if o.icons and need <= 24 else 1  # the icon gives way to "NBA  EAST"
        if x == 7:
            sd.icon(p, sport_of(key), 1, 1)
        gx = 31
        if group and need <= 31 - x:
            gx = p.text_right(30, 1, group, sd.MUTE)
        p.text(x, 1, sd.cut(tag, gx - 2 - x), sd.GOLD)
        body = p.sub(0, 7, 32, 25)
        rank_w = max((measure(str(r["rank"])) for r in visible), default=3)
        ax = 1 + rank_w + 2
        for i, r in enumerate(rows):
            y = i * pitch - pos
            if r is None or y < -pitch or y >= 25:
                continue
            fav = r["abbr"] in o.favs or r.get("name") in o.favs
            tc = led_team_color(r["color"], r["alt"]) if o.colors and r["color"] != "#8c8ca0" else sd.SOFT
            value = r["value"]
            if measure(value) > 12 and "-" in value:  # W-L too wide for 32 px: wins only
                value = value.split("-")[0]
            body.text_right(ax - 2, y, str(r["rank"]), sd.GOLD if fav else sd.MUTE)
            vx = body.text_right(30, y, value, sd.WHITE if fav or r["rank"] == 1 else sd.SOFT)
            body.text(ax, y, sd.cut(r["abbr"], vx - 2 - ax), sd.WHITE if fav else tc)
            if fav:
                body.rect(0, y + 1, 1, 3, sd.GOLD)


GROUP_LABELS = {
    "EASTERN CONFERENCE": "EAST",
    "WESTERN CONFERENCE": "WEST",
    "AMERICAN LEAGUE": "AL",
    "NATIONAL LEAGUE": "NL",
    "AMERICAN FOOTBALL CONFERENCE": "AFC",
    "NATIONAL FOOTBALL CONFERENCE": "NFC",
}


def _pad_groups(rows: list[dict[str, Any]], per_page: int) -> list[dict[str, Any] | None]:
    """Pad with None so every group (conference) starts on a fresh page."""
    out: list[dict[str, Any] | None] = []
    last = object()
    for r in rows:
        if r.get("group") != last and out and len(out) % per_page:
            out += [None] * (per_page - len(out) % per_page)
        last = r.get("group")
        out.append(r)
    return out
