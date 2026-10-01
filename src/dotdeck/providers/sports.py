"""Live sports from ESPN's public, keyless endpoints, normalised into one game model.

Sources (all free, no key, verified live):
    scoreboards  https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard
    standings    https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings
    all cricket  https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=cricket
                 (every live cricket match worldwide — internationals included — in one call)

Every sport is parsed into the same game dict so apps never branch on ESPN's shapes::

    {"id", "league", "tag", "sport", "kind",          # kind: team | duel (tennis, mma) | field (golf, f1)
     "state": "pre"|"in"|"post", "detail", "short", "clock", "period", "start" (iso),
     "name", "note", "headline", "last_play", "situation": {...},
     "competitors": [{"id", "name", "abbr", "short", "score", "color", "alt", "home", "winner", "extra"}],
     "away", "home"}                                   # always present (field: P1 / P2)

Events on the hub (consumed by `Engine._on_event`; payload keys are a stable contract):
    game_start / game_final  {"league", "tag", "game"}
    score                    {"league", "tag", "game", "side", "team", "delta"}
"""

from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from datetime import datetime
from typing import Any

from .base import Provider

Game = dict[str, Any]

# key -> (espn path, display tag). Order = the order the studio lists them.
LEAGUES: dict[str, tuple[str, str]] = {
    "nba": ("basketball/nba", "NBA"),
    "wnba": ("basketball/wnba", "WNBA"),
    "ncaab": ("basketball/mens-college-basketball", "NCAAB"),
    "nfl": ("football/nfl", "NFL"),
    "ncaaf": ("football/college-football", "NCAAF"),
    "mlb": ("baseball/mlb", "MLB"),
    "nhl": ("hockey/nhl", "NHL"),
    "epl": ("soccer/eng.1", "EPL"),
    "laliga": ("soccer/esp.1", "LIGA"),
    "seriea": ("soccer/ita.1", "SERIE A"),
    "bundesliga": ("soccer/ger.1", "BUNDES"),
    "ligue1": ("soccer/fra.1", "LIGUE 1"),
    "ucl": ("soccer/uefa.champions", "UCL"),
    "uel": ("soccer/uefa.europa", "UEL"),
    "worldcup": ("soccer/fifa.world", "WORLD CUP"),
    "mls": ("soccer/usa.1", "MLS"),
    "isl": ("soccer/ind.1", "ISL"),
    "ipl": ("cricket/8048", "IPL"),
    "bbl": ("cricket/8044", "BBL"),
    "psl": ("cricket/8679", "PSL"),
    "cricket": ("cricket/all", "CRICKET"),  # every live match (header feed)
    "atp": ("tennis/atp", "ATP"),
    "wta": ("tennis/wta", "WTA"),
    "pga": ("golf/pga", "PGA"),
    "lpga": ("golf/lpga", "LPGA"),
    "f1": ("racing/f1", "F1"),
    "ufc": ("mma/ufc", "UFC"),
}

SITE = "https://site.api.espn.com/apis/site/v2/sports"
STANDINGS = "https://site.api.espn.com/apis/v2/sports"
CRICKET_ALL = "https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=cricket"

# sports whose standings endpoint returns a useful table
TABLE_SPORTS = {"basketball", "football", "baseball", "hockey", "soccer", "cricket", "racing"}

LIVE_EVERY = 20.0  # s, a league with a game in progress
SOON_EVERY = 60.0  # s, a game starts within 15 minutes
IDLE_EVERY = 300.0  # s, nothing happening
TABLE_EVERY = 1800.0  # s, standings
FAIL_EVERY = 30.0  # s, retry one league after an error
TIMEOUT = 10.0  # s, per request (the shared client also has its own timeouts)


def sport_of(league: str) -> str:
    return LEAGUES[league][0].split("/")[0] if league in LEAGUES else "other"


# league -> sport family (basketball, football, baseball, hockey, soccer, cricket, tennis, golf, racing, mma)
LEAGUE_SPORT: dict[str, str] = {k: sport_of(k) for k in LEAGUES}

# 2026 F1 grid: surname -> constructor, and constructor colours tuned for LEDs.
# ESPN's F1 scoreboard carries drivers only; this is plain reference data (no logos/assets).
F1_TEAMS: dict[str, tuple[str, str]] = {
    "MERCEDES": ("#00d2be", "#ffffff"),
    "FERRARI": ("#ff1020", "#ffd000"),
    "MCLAREN": ("#ff8000", "#47c7fc"),
    "RED BULL": ("#2858ff", "#ffd000"),
    "ASTON MARTIN": ("#00a070", "#c8ff00"),
    "ALPINE": ("#ff5ac8", "#0090ff"),
    "WILLIAMS": ("#40a0ff", "#ffffff"),
    "RACING BULLS": ("#7090ff", "#ffffff"),
    "HAAS": ("#d0d0d0", "#ff2030"),
    "AUDI": ("#ff3010", "#c0c0c0"),
    "CADILLAC": ("#e0e0e0", "#ffd000"),
}
F1_DRIVERS: dict[str, str] = {
    "RUSSELL": "MERCEDES",
    "ANTONELLI": "MERCEDES",
    "LECLERC": "FERRARI",
    "HAMILTON": "FERRARI",
    "NORRIS": "MCLAREN",
    "PIASTRI": "MCLAREN",
    "VERSTAPPEN": "RED BULL",
    "HADJAR": "RED BULL",
    "ALONSO": "ASTON MARTIN",
    "STROLL": "ASTON MARTIN",
    "GASLY": "ALPINE",
    "COLAPINTO": "ALPINE",
    "ALBON": "WILLIAMS",
    "SAINZ": "WILLIAMS",
    "LAWSON": "RACING BULLS",
    "LINDBLAD": "RACING BULLS",
    "OCON": "HAAS",
    "BEARMAN": "HAAS",
    "HULKENBERG": "AUDI",
    "BORTOLETO": "AUDI",
    "PEREZ": "CADILLAC",
    "BOTTAS": "CADILLAC",
}

# neutral identity colours for athletes (no team colours): first / second competitor
DUEL_COLORS = (("#28a0ff", "#0050c0"), ("#ff4818", "#ffaa00"))
CORNER_COLORS = (("#ff1e3c", "#ff8080"), ("#2860ff", "#80a0ff"))  # mma red / blue corner


# ============================================================== text helpers
def ascii_upper(s: Any) -> str:
    """'Növényi Jr.' -> 'NOVENYI JR.' — the LED fonts are ASCII only."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    return s.encode("ascii", "ignore").decode().upper().strip()


_SUFFIX = {"JR", "JR.", "SR", "SR.", "II", "III", "IV"}


def surname(short_name: str, display_name: str = "") -> str:
    """'N. Növényi Jr.' -> 'NOVENYI', 'A. Wang' -> 'WANG', 'Kimi Antonelli' -> 'ANTONELLI'."""
    for src in (short_name, display_name):
        toks = [t for t in ascii_upper(src).replace("/", " ").split() if t not in _SUFFIX]
        toks = [t for t in toks if not t.endswith(".")] or toks
        if toks:
            return toks[-1]
    return "?"


def _hex(c: Any, default: str) -> str:
    h = str(c or "").strip().lstrip("#")
    return "#" + (h.lower() if re.fullmatch(r"[0-9a-fA-F]{6}", h) else default)


def _truthy(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, str):
        return v.lower() == "true"
    return bool(v)


def _parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _blank(home: bool) -> dict[str, Any]:
    return {
        "id": "",
        "name": "",
        "abbr": "",
        "short": "",
        "score": "",
        "color": "#8c8ca0",
        "alt": "#46465a",
        "home": home,
        "winner": None,
        "extra": {},
    }


def _ordinal(n: int) -> str:
    return f"{n}{'TH' if 10 <= n % 100 <= 20 else {1: 'ST', 2: 'ND', 3: 'RD'}.get(n % 10, 'TH')}"


# ============================================================ status helpers
def _status(st: dict[str, Any]) -> dict[str, Any]:
    t = st.get("type") or {}
    return {
        "state": t.get("state") or "pre",
        "detail": ascii_upper(t.get("shortDetail") or t.get("detail") or t.get("description") or ""),
        "clock": str(st.get("displayClock") or ""),
        "period": int(st.get("period") or 0),
        "status_name": t.get("name") or "",
        "completed": bool(t.get("completed")),
    }


def _short(sport: str, league: str, s: dict[str, Any]) -> str:
    """Compact live status for a header (≤ 5 chars): Q3, 2H, ▲9, P2, 67', HT, FT, OT."""
    state, p, name, detail = s["state"], s["period"], s["status_name"], s["detail"]
    if state == "post":
        if sport in ("soccer",):
            return "FT"
        if "OT" in detail or "/OT" in detail:
            return "F/OT"
        return "FINAL" if sport not in ("basketball", "football", "hockey", "baseball") else "F"
    if state != "in":
        return ""
    if sport == "cricket":
        return "LIVE"
    if "HALFTIME" in name or detail in ("HT", "HALFTIME"):
        return "HT"
    if sport == "soccer":
        return s["clock"].split("+")[0] if s["clock"] else detail[:5]
    if sport == "baseball":
        arrow = "▲" if detail.startswith("TOP") else "▼" if detail.startswith(("BOT", "BOTTOM")) else ""
        if detail.startswith(("MID", "END")):
            arrow = "-"
        return f"{arrow}{p}" if p else detail[:5]
    if sport == "basketball" and league == "ncaab":
        return f"{p}H" if p <= 2 else f"OT{p - 2 if p > 3 else ''}"
    if sport in ("basketball", "football"):
        return f"Q{p}" if p <= 4 else ("OT" if p == 5 else f"{p - 4}OT")
    if sport == "hockey":
        return f"P{p}" if p <= 3 else ("OT" if p == 4 else "SO")
    return detail[:5]


def _game(
    league: str,
    gid: Any,
    comps: list[dict[str, Any]],
    s: dict[str, Any],
    start: str | None,
    kind: str,
    **extra: Any,
) -> Game:
    sport = sport_of(league)
    if kind == "field":
        away, home = [*comps, _blank(False), _blank(True)][:2]
    else:
        away = next((c for c in comps if not c["home"]), comps[0] if comps else _blank(False))
        home = next((c for c in comps if c["home"] and c is not away), None)
        if home is None:
            home = next((c for c in comps if c is not away), _blank(True))
    g: Game = {
        "id": str(gid),
        "league": league,
        "tag": LEAGUES[league][1],
        "sport": sport,
        "kind": kind,
        "state": s["state"],
        "detail": s["detail"],
        "short": _short(sport, league, s),
        "clock": s["clock"],
        "period": s["period"],
        "start": start,
        "name": "",
        "note": "",
        "headline": None,
        "last_play": None,
        "situation": {},
        "competitors": comps,
        "away": away,
        "home": home,
    }
    g.update(extra)
    return g


# ============================================================ team sports
def _record(c: dict[str, Any]) -> str:
    recs = c.get("records") or []
    if isinstance(recs, list):
        for r in recs:
            if isinstance(r, dict) and r.get("type") in ("total", None) and r.get("summary"):
                return str(r["summary"])
    return str(c.get("record") or "")


def _team_comp(c: dict[str, Any], sport: str) -> dict[str, Any]:
    t = c.get("team") or {}
    abbr = ascii_upper(t.get("abbreviation") or t.get("shortDisplayName") or c.get("abbreviation") or "???")
    extra: dict[str, Any] = {"record": _record(c)}
    score = str(c.get("score", "") or "")
    if sport == "cricket":
        score, cx = _cricket_score(score, c.get("linescores"))
        extra.update(cx)
    else:
        score = score or "0"
    if sport == "baseball":
        extra["hits"] = c.get("hits")
        extra["errors"] = c.get("errors")
    ls = c.get("linescores")
    if sport != "cricket" and isinstance(ls, list):
        extra["periods"] = [str(x.get("displayValue", "")) for x in ls if isinstance(x, dict)]
    return {
        "id": str(c.get("id") or t.get("id") or ""),
        "name": ascii_upper(t.get("displayName") or c.get("displayName") or abbr),
        "abbr": abbr[:5],
        "short": ascii_upper(t.get("shortDisplayName") or t.get("name") or abbr),
        "score": score,
        "color": _hex(t.get("color") or c.get("color"), "ffffff"),
        "alt": _hex(t.get("alternateColor"), "888888"),
        "home": c.get("homeAway") == "home",
        "winner": _truthy(c.get("winner")),
        "extra": extra,
    }


_CRICKET_RE = re.compile(r"(\d+)(?:/(\d+))?")


def _cricket_score(raw: str, linescores: Any = None) -> tuple[str, dict[str, Any]]:
    """'161/5 (18/20 ov, target 156)' -> ('161/5', {runs, wickets, overs, target})."""
    raw = (raw or "").strip()
    main, _, paren = raw.partition("(")
    main = main.strip()
    nums = _CRICKET_RE.findall(main)
    extra: dict[str, Any] = {"runs": sum(int(r) for r, _ in nums) if nums else None}
    if nums:
        extra["wickets"] = int(nums[-1][1]) if nums[-1][1] else None
    m = re.search(r"([\d.]+)(?:/\d+)?\s*ov", paren)
    if m:
        extra["overs"] = m.group(1)
    m = re.search(r"target (\d+)", paren)
    if m:
        extra["target"] = int(m.group(1))
    if isinstance(linescores, list):
        cur = next(
            (x for x in linescores if isinstance(x, dict) and x.get("isBatting") and x.get("isCurrent")), None
        )
        if cur:
            extra["batting"] = True
            extra.setdefault("overs", str(cur.get("overs", "")).removesuffix(".0"))
    return main, extra


def _situation(
    sport: str, comp: dict[str, Any], teams: list[dict[str, Any]]
) -> tuple[dict[str, Any], str | None]:
    sit = comp.get("situation") or {}
    last = ((sit.get("lastPlay") or {}).get("text")) or None
    out: dict[str, Any] = {}
    if sport == "baseball" and sit:
        out = {
            "balls": sit.get("balls", 0),
            "strikes": sit.get("strikes", 0),
            "outs": sit.get("outs", 0),
            "bases": [bool(sit.get("onFirst")), bool(sit.get("onSecond")), bool(sit.get("onThird"))],
        }
    elif sport == "football" and sit:
        pos = str(sit.get("possession") or "")
        side = next(("home" if t["home"] else "away" for t in teams if t["id"] and t["id"] == pos), None)
        out = {
            "down": ascii_upper(sit.get("shortDownDistanceText") or sit.get("downDistanceText") or ""),
            "possession": side,
            "redzone": bool(sit.get("isRedZone")),
        }
    if sport == "soccer":
        goals = [d for d in comp.get("details") or [] if isinstance(d, dict) and d.get("scoringPlay")]
        if goals:
            d = goals[-1]
            who = (d.get("athletesInvolved") or [{}])[0]
            mins = (d.get("clock") or {}).get("displayValue", "")
            name = surname(who.get("shortName", ""), who.get("displayName", ""))
            tag = " (OG)" if d.get("ownGoal") else " (P)" if d.get("penaltyKick") else ""
            last = f"{mins} {name}{tag}".strip()
        reds = {}
        for d in comp.get("details") or []:
            if isinstance(d, dict) and d.get("redCard"):
                tid = str((d.get("team") or {}).get("id", ""))
                reds[tid] = reds.get(tid, 0) + 1
        for t in teams:
            if reds.get(t["id"]):
                t["extra"]["red"] = reds[t["id"]]
    return out, (ascii_upper(last)[:120] if last else None)


def parse_team(league: str, data: dict[str, Any]) -> list[Game]:
    sport = sport_of(league)
    games: list[Game] = []
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        cs = comp.get("competitors") or []
        if len(cs) < 2:
            continue
        teams = [_team_comp(c, sport) for c in cs[:2]]
        s = _status(comp.get("status") or ev.get("status") or {})
        situation, last = _situation(sport, comp, teams)
        hl = (comp.get("headlines") or [{}])[0].get("shortLinkText")
        extra: dict[str, Any] = {
            "name": ascii_upper(ev.get("shortName") or ev.get("name") or ""),
            "note": ascii_upper(
                comp.get("description") or (comp.get("notes") or [{}])[0].get("headline") or ""
            ),
            "situation": situation,
            "last_play": last,
            "headline": ascii_upper(hl) if hl else None,
        }
        if sport == "cricket":
            summ = (comp.get("status") or {}).get("summary") or (ev.get("status") or {}).get("summary")
            if summ:
                extra["headline"] = ascii_upper(summ)
        games.append(_game(league, ev.get("id"), teams, s, ev.get("date"), "team", **extra))
    return games


def parse_cricket_all(league: str, data: dict[str, Any]) -> list[Game]:
    """The cricket header feed: every live series with its matches, flat competitor shape."""
    games: list[Game] = []
    for sp in data.get("sports") or []:
        for lg in sp.get("leagues") or []:
            series = ascii_upper(lg.get("shortName") or lg.get("abbreviation") or lg.get("name") or "")
            for ev in lg.get("events") or []:
                cs = ev.get("competitors") or []
                if len(cs) < 2:
                    continue
                fs = ev.get("fullStatus") or {}
                s = _status(fs)
                s["detail"] = ascii_upper(fs.get("summary") or ev.get("summary") or s["detail"])
                teams = []
                for c in cs[:2]:
                    score, cx = _cricket_score(str(c.get("score") or ""))
                    abbr = ascii_upper(c.get("abbreviation") or c.get("name") or "???")
                    cx["record"] = str(c.get("record") or "")
                    if str(c.get("id")) == str(fs.get("battingTeamId")):
                        cx["batting"] = True
                    teams.append(
                        {
                            "id": str(c.get("id") or ""),
                            "name": ascii_upper(c.get("displayName") or abbr),
                            "abbr": abbr[:6],
                            "short": abbr,
                            "score": score,
                            "color": _hex(c.get("color"), "ffffff"),
                            "alt": "#888888",
                            "home": c.get("homeAway") == "home",
                            "winner": _truthy(c.get("winner")),
                            "extra": cx,
                        }
                    )
                games.append(
                    _game(
                        league,
                        ev.get("id"),
                        teams,
                        s,
                        ev.get("date"),
                        "team",
                        name=ascii_upper(ev.get("shortName") or ""),
                        note=series,
                        headline=ascii_upper(fs.get("longSummary") or "") or None,
                    )
                )
    return games


# ============================================================ athlete sports
def _athlete(c: dict[str, Any], colors: tuple[str, str], n: int = 3) -> dict[str, Any]:
    a = c.get("athlete") or {}
    roster = c.get("roster") or {}
    if not a and roster:  # doubles pair
        a = {"displayName": roster.get("displayName"), "shortName": roster.get("shortDisplayName")}
        names = [
            surname(x.get("shortName", ""), x.get("displayName", "")) for x in roster.get("athletes") or []
        ]
        last = "/".join(x[:3] for x in names) if names else "?"
    else:
        last = surname(a.get("shortName", ""), a.get("displayName", ""))
    abbr = ascii_upper(a.get("abbreviation") or "") or last.replace(" ", "")[:n]
    return {
        "id": str(c.get("id") or ""),
        "name": ascii_upper(a.get("displayName") or a.get("fullName") or last),
        "abbr": abbr,
        "short": last,
        "score": str(c.get("score") or ""),
        "color": colors[0],
        "alt": colors[1],
        "home": c.get("homeAway") == "home",
        "winner": _truthy(c.get("winner")),
        "extra": {"record": _record(c), "country": ascii_upper((a.get("flag") or {}).get("alt") or "")},
    }


_ROUNDS = (
    ("QUALIFYING", "Q"),
    ("QUARTERFINAL", "QF"),
    ("SEMIFINAL", "SF"),
    ("FINAL", "F"),
    ("ROUND OF 16", "R16"),
    ("ROUND OF 32", "R32"),
    ("ROUND OF 64", "R64"),
    ("ROUND OF 128", "R128"),
)


def round_abbr(name: str) -> str:
    """'Qualifying 1st Round' -> 'Q1', 'Quarterfinal' -> 'QF', 'Round 2' -> 'R2'."""
    n = ascii_upper(name)
    num = re.search(r"(\d+)", n)
    if n.startswith("QUALIFYING"):
        return f"Q{num.group(1)}" if num else "Q"
    for key, ab in _ROUNDS[1:]:
        if n.startswith(key):
            return ab
    if n.startswith("ROUND") and num:
        return f"R{num.group(1)}"
    return n[:4]


def parse_tennis(league: str, data: dict[str, Any], now: float | None = None) -> list[Game]:
    now = time.time() if now is None else now
    games: list[Game] = []
    for ev in data.get("events") or []:
        tour = ascii_upper(ev.get("shortName") or ev.get("name") or "")
        for grp in ev.get("groupings") or []:
            slug = ((grp.get("grouping") or {}).get("slug") or "").lower()
            if "singles" not in slug:
                continue
            for comp in grp.get("competitions") or []:
                cs = comp.get("competitors") or []
                if len(cs) < 2:
                    continue
                players = [_athlete(c, DUEL_COLORS[i % 2]) for i, c in enumerate(cs[:2])]
                for p, c in zip(players, cs[:2], strict=True):
                    sets = [
                        {
                            "games": int(x.get("value") or 0),
                            "tb": x.get("tiebreak"),
                            "won": bool(x.get("winner")),
                        }
                        for x in c.get("linescores") or []
                        if isinstance(x, dict)
                    ]
                    p["extra"]["sets"] = sets
                    p["extra"]["seed"] = (c.get("curatedRank") or {}).get("current")
                    if c.get("possession") is not None:
                        p["extra"]["serving"] = bool(c.get("possession"))
                    p["score"] = str(sum(1 for x in sets if x["won"]))
                s = _status(comp.get("status") or {})
                rnd = (comp.get("round") or {}).get("displayName") or ""
                g = _game(
                    league,
                    comp.get("id"),
                    players,
                    s,
                    comp.get("date") or comp.get("startDate"),
                    "duel",
                    name=tour,
                    note=round_abbr(rnd),
                    headline=f"{tour} {ascii_upper(rnd)}".strip(),
                )
                if s["state"] == "in":
                    g["short"] = f"S{max(1, len(players[0]['extra']['sets']))}"
                elif s["state"] == "post":
                    g["short"] = "FINAL"
                games.append(g)

    def keep(g: Game) -> bool:
        ts = _parse_iso(g["start"]) or 0
        if g["state"] == "in":
            return True
        if g["state"] == "pre":
            return -3 * 3600 < ts - now < 18 * 3600 and "TBD" not in g["detail"]
        return now - ts < 20 * 3600

    kept = [g for g in games if keep(g)]
    if not kept:  # quiet day: the latest results rather than an empty screen
        kept = sorted((g for g in games if g["state"] == "post"), key=lambda g: g["start"] or "")[-6:]
    return _sort(kept)[:24]


def parse_golf(league: str, data: dict[str, Any]) -> list[Game]:
    games: list[Game] = []
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        cs = comp.get("competitors") or []
        if not cs:
            continue
        if cs[0].get("type") == "team" or (len(cs) == 2 and cs[0].get("team")):
            # team events (Presidents / Ryder Cup): a normal two-sided scoreboard
            teams = [_team_comp(c, "golf") for c in cs[:2]]
            s = _status(comp.get("status") or ev.get("status") or {})
            games.append(
                _game(
                    league,
                    ev.get("id"),
                    teams,
                    s,
                    ev.get("date"),
                    "team",
                    name=ascii_upper(ev.get("shortName")),
                )
            )
            continue
        ordered = sorted(cs, key=lambda c: int(c.get("order") or 999))
        scores = [str(c.get("score") or "") for c in ordered]
        players = []
        for i, c in enumerate(ordered[:15]):
            p = _athlete(c, ("#ffd600", "#ff4818"))
            sc = scores[i]
            first = scores.index(sc) + 1
            tied = scores.count(sc) > 1
            rounds = [x for x in c.get("linescores") or [] if isinstance(x, dict) and x.get("linescores")]
            holes = len(rounds[-1]["linescores"]) if rounds else 0
            p["extra"].update(
                {
                    "pos": f"T{first}" if tied else str(first),
                    "thru": "F" if holes >= 18 else (str(holes) if holes else ""),
                    "today": str(rounds[-1].get("displayValue", "")) if rounds else "",
                    "round": len(rounds),
                }
            )
            p["score"] = sc or "E"
            players.append(p)
        s = _status(comp.get("status") or ev.get("status") or {})
        g = _game(
            league,
            ev.get("id"),
            players,
            s,
            ev.get("date"),
            "field",
            name=ascii_upper(ev.get("shortName") or ev.get("name") or ""),
        )
        g["note"] = f"R{s['period']}" if s["period"] else ""
        if s["state"] == "in":
            g["short"] = f"R{s['period']}" if s["period"] else "LIVE"
        games.append(g)
    return _sort(games)


def parse_racing(league: str, data: dict[str, Any]) -> list[Game]:
    games: list[Game] = []
    for ev in data.get("events") or []:
        sessions = ev.get("competitions") or []
        if not sessions:
            continue
        states = [(_status(c.get("status") or {}), c) for c in sessions]
        cur = next(((s, c) for s, c in states if s["state"] == "in"), None)
        if cur is None:
            done = [(s, c) for s, c in states if s["state"] == "post" and c.get("competitors")]
            cur = done[-1] if done else states[0]
        s, comp = cur
        nxt = next(((s2, c2) for s2, c2 in states if s2["state"] == "pre"), None)
        drivers = []
        for c in sorted(comp.get("competitors") or [], key=lambda c: int(c.get("order") or 999))[:10]:
            p = _athlete(c, ("#ffffff", "#8c8ca0"))
            team = F1_DRIVERS.get(p["short"].split()[-1] if p["short"] else "", "")
            if team:
                p["color"], p["alt"] = F1_TEAMS[team]
            p["extra"].update({"pos": str(c.get("order") or ""), "team": team})
            p["score"] = p["extra"]["pos"]
            drivers.append(p)
        session = ascii_upper((comp.get("type") or {}).get("abbreviation") or "")
        session = {"QUAL": "QUALI"}.get(session, session)
        g = _game(
            league,
            comp.get("id") or ev.get("id"),
            drivers,
            s,
            comp.get("date") or ev.get("date"),
            "field",
            name=ascii_upper(ev.get("shortName") or ev.get("name") or ""),
            note=session,
            headline=ascii_upper((ev.get("circuit") or {}).get("fullName") or "") or None,
        )
        if s["state"] == "in":
            g["short"] = f"L{s['period']}" if session == "RACE" and s["period"] else "LIVE"
        elif s["state"] == "post":
            g["short"] = "FINAL"
        if nxt is not None:
            g["next"] = {
                "session": ascii_upper((nxt[1].get("type") or {}).get("abbreviation") or ""),
                "start": nxt[1].get("date"),
            }
            if s["state"] == "post" and not drivers:
                g["state"], g["start"] = "pre", nxt[1].get("date")
        games.append(g)
    return _sort(games)


def parse_mma(league: str, data: dict[str, Any]) -> list[Game]:
    games: list[Game] = []
    for ev in data.get("events") or []:
        card = ascii_upper(ev.get("shortName") or ev.get("name") or "")
        bouts = ev.get("competitions") or []
        for i, comp in enumerate(reversed(bouts)):  # ESPN lists the main event last
            cs = comp.get("competitors") or []
            if len(cs) < 2:
                continue
            fighters = [_athlete(c, CORNER_COLORS[j % 2], n=4) for j, c in enumerate(cs[:2])]
            fighters[0]["home"], fighters[1]["home"] = False, True
            s = _status(comp.get("status") or {})
            if s["state"] == "post":
                for f in fighters:
                    f["score"] = "W" if f["winner"] else ("L" if f["winner"] is False else "D")
                s["detail"] = f"FINAL R{s['period']} {s['clock']}".strip() if s["period"] else "FINAL"
            elif s["state"] == "in":
                s["detail"] = f"R{s['period']} {s['clock']}"
            g = _game(
                league,
                comp.get("id"),
                fighters,
                s,
                comp.get("date") or ev.get("date"),
                "duel",
                name=card,
                note=ascii_upper((comp.get("type") or {}).get("abbreviation") or ""),
                headline=card,
            )
            g["main"] = i == 0
            g["short"] = (
                f"R{s['period']}" if s["state"] == "in" else ("FINAL" if s["state"] == "post" else "")
            )
            games.append(g)
    return games  # card order: main event first


def _sort(games: list[Game]) -> list[Game]:
    order = {"in": 0, "pre": 1, "post": 2}
    pre_post = sorted(games, key=lambda g: (order.get(g["state"], 3), g["start"] or ""))
    live = [g for g in pre_post if g["state"] == "in"]
    pre = [g for g in pre_post if g["state"] == "pre"]
    post = sorted((g for g in pre_post if g["state"] == "post"), key=lambda g: g["start"] or "", reverse=True)
    other = [g for g in pre_post if g["state"] not in order]
    return live + pre + post + other


def parse_scoreboard(league: str, data: dict[str, Any], now: float | None = None) -> list[Game]:
    """ESPN JSON for one league -> normalised, sorted games (live, upcoming, recent)."""
    sport = sport_of(league)
    if league == "cricket":
        return _sort(parse_cricket_all(league, data))
    if sport == "tennis":
        return parse_tennis(league, data, now)
    if sport == "golf":
        return parse_golf(league, data)
    if sport == "racing":
        return parse_racing(league, data)
    if sport == "mma":
        return parse_mma(league, data)
    return _sort(parse_team(league, data))


# ============================================================ standings
def _stat(entry: dict[str, Any], *names: str) -> str | None:
    for s in entry.get("stats") or []:
        if s.get("name") in names or s.get("type") in names:
            v = s.get("displayValue")
            if v not in (None, "", " "):
                return str(v)
    return None


def _num(v: str | None, default: float = 0.0) -> float:
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return default


def parse_standings(
    league: str, data: dict[str, Any], colors: dict[str, tuple[str, str]] | None = None
) -> list[dict[str, Any]]:
    """Standings JSON -> rows {rank, abbr, name, value, label, color, alt, group} (group order kept)."""
    sport = sport_of(league)
    colors = colors or {}
    groups: list[tuple[str, list[dict[str, Any]]]] = []

    def walk(node: dict[str, Any], name: str) -> None:
        entries = (node.get("standings") or {}).get("entries") or []
        if entries:
            groups.append((name, entries))
        for ch in node.get("children") or []:
            walk(ch, ascii_upper(ch.get("abbreviation") or ch.get("name") or ""))

    walk(data, "")
    if sport == "racing":
        groups = [g for g in groups if "DRIVER" in g[0]] or groups[:1]
    rows: list[dict[str, Any]] = []
    for gname, entries in groups:
        parsed = []
        for e in entries:
            t = e.get("team") or {}
            a = e.get("athlete") or {}
            if a:
                last = surname(a.get("shortName", ""), a.get("displayName", ""))
                abbr = ascii_upper(a.get("abbreviation") or last[:3])
                team = F1_DRIVERS.get(last, "")
                col = F1_TEAMS.get(team, ("#ffffff", "#8c8ca0"))
                name = last
            else:
                abbr = ascii_upper(t.get("abbreviation") or t.get("shortDisplayName") or "?")[:5]
                col = colors.get(abbr) or (
                    (_hex(t.get("color"), "ffffff"), _hex(t.get("alternateColor"), "888888"))
                    if t.get("color")
                    else ("#8c8ca0", "#46465a")
                )
                name = ascii_upper(t.get("shortDisplayName") or t.get("displayName") or abbr)
            if sport == "soccer":
                value, label = _stat(e, "points") or "0", "PTS"
            elif sport == "cricket":
                value, label = _stat(e, "matchPoints", "points") or "0", "PTS"
            elif sport == "racing":
                value, label = _stat(e, "championshipPts", "points") or "0", "PTS"
            elif sport == "hockey":
                value, label = _stat(e, "points") or "0", "PTS"
            else:
                value, label = (
                    _stat(e, "overall", "total") or f"{_stat(e, 'wins') or 0}-{_stat(e, 'losses') or 0}",
                    "W-L",
                )
            rank = _num(_stat(e, "rank"), 0) or _num(_stat(e, "playoffSeed"), 0)
            key = (
                -_num(_stat(e, "points"))
                if sport == "hockey"
                else -_num(_stat(e, "winPercent"), 0)
                if sport in ("basketball", "football", "baseball")
                else 0.0
            )
            parsed.append(
                {
                    "rank": int(rank) if rank else 0,
                    "abbr": abbr,
                    "name": name,
                    "value": value,
                    "label": label,
                    "color": col[0],
                    "alt": col[1],
                    "group": gname,
                    "_k": key,
                }
            )
        if sport in ("basketball", "football", "baseball", "hockey"):
            parsed.sort(key=lambda r: (r["_k"], r["abbr"]))
        elif any(r["rank"] for r in parsed):
            parsed.sort(key=lambda r: r["rank"] or 999)
        for i, r in enumerate(parsed, 1):
            r["rank"] = i
            del r["_k"]
        rows += parsed
    return rows


# ============================================================ provider
class SportsProvider(Provider[dict[str, list[Game]]]):
    """Scoreboards for the leagues something asked for, each on its own polling schedule.

    A league with a live game refreshes every 20 s, one with a game about to start every minute and a
    quiet one every 5 minutes; each fetch only requests the leagues that are due. Standings are fetched
    (every 30 min) only for leagues passed to `want_table()`.
    """

    name = "sports"
    interval = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.leagues: set[str] = {"nba"}
        self.table_leagues: set[str] = set()
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.errors: dict[str, str] = {}
        self._due: dict[str, float] = {}
        self._table_due: dict[str, float] = {}
        self._colors: dict[str, dict[str, tuple[str, str]]] = {}

    # ------------------------------------------------------------- wants
    def want(self, *leagues: str) -> None:
        new = [lg for lg in leagues if lg in LEAGUES and lg not in self.leagues]
        if new:
            self.leagues.update(new)
            self.refresh()

    def want_table(self, *leagues: str) -> None:
        new = [lg for lg in leagues if lg in LEAGUES and sport_of(lg) in TABLE_SPORTS and lg != "cricket"]
        new = [lg for lg in new if lg not in self.table_leagues]
        if new:
            self.table_leagues.update(new)
            self.want(*new)
            self.refresh()

    def _stored_wants(self) -> set[str]:
        """Leagues the saved Live Scores settings ask for, so background alerts cover all of them."""
        try:
            sc = self.hub.store.section("apps").get("scores", {}) or {}
        except Exception:
            return set()
        raw = str(sc.get("leagues") or "")
        return {k.strip().lower() for k in raw.split(",") if k.strip().lower() in LEAGUES}

    def wanted(self) -> set[str]:
        return self.leagues | self._stored_wants()

    # ---------------------------------------------------------- schedule
    def next_interval(self) -> float:
        now = time.monotonic()
        dues = [self._due.get(k, 0.0) for k in self.wanted()]
        dues += [self._table_due.get(k, 0.0) for k in self.table_leagues]
        return max(2.0, min(IDLE_EVERY, min(dues, default=now + IDLE_EVERY) - now))

    @staticmethod
    def _cadence(games: list[Game], now: float | None = None) -> float:
        now = time.time() if now is None else now
        if any(g["state"] == "in" for g in games):
            return LIVE_EVERY
        for g in games:
            ts = _parse_iso(g.get("start")) if g["state"] == "pre" else None
            if ts is not None and -3600 < ts - now < 900:
                return SOON_EVERY
        return IDLE_EVERY

    def url(self, league: str) -> str:
        path = LEAGUES[league][0]
        return CRICKET_ALL if league == "cricket" else f"{SITE}/{path}/scoreboard"

    async def _get(self, url: str) -> dict[str, Any]:
        r = await asyncio.wait_for(self.hub.http.get(url), TIMEOUT)
        r.raise_for_status()
        return r.json()

    async def _league(self, key: str) -> list[Game]:
        return parse_scoreboard(key, await self._get(self.url(key)))

    async def _table(self, key: str) -> list[dict[str, Any]]:
        data = await self._get(f"{STANDINGS}/{LEAGUES[key][0]}/standings")
        return parse_standings(key, data, self._colors.get(key))

    async def fetch(self) -> dict[str, list[Game]]:
        now = time.monotonic()
        first = self.value is None
        have = self.value or {}
        keys = sorted(
            k for k in self.wanted() if first or k not in have or self._due.get(k, 0.0) <= now + 0.5
        )
        tkeys = sorted(k for k in self.table_leagues if self._table_due.get(k, 0.0) <= now + 0.5)
        res = await asyncio.gather(
            *(self._league(k) for k in keys), *(self._table(k) for k in tkeys), return_exceptions=True
        )
        out = dict(have)
        errors = []
        for k, v in zip(keys, res[: len(keys)], strict=True):
            if isinstance(v, BaseException):
                msg = f"{type(v).__name__}: {v}"[:120]
                errors.append(f"{k}: {msg}")
                self.errors[k] = msg
                self._due[k] = now + FAIL_EVERY
            else:
                out[k] = v
                self.errors.pop(k, None)
                self._due[k] = now + self._cadence(v)
                cols = self._colors.setdefault(k, {})
                for g in v:
                    for c in g["competitors"]:
                        if c["abbr"]:
                            cols[c["abbr"]] = (c["color"], c["alt"])
        for k, v in zip(tkeys, res[len(keys) :], strict=True):
            if isinstance(v, BaseException):
                self._table_due[k] = now + FAIL_EVERY * 4
            else:
                self.tables[k] = v
                self._table_due[k] = now + TABLE_EVERY
        if errors and not out:
            raise RuntimeError("; ".join(errors))
        self._diff(have, out)
        return out

    # ------------------------------------------------------------ events
    def _diff(self, old: dict[str, list[Game]], new: dict[str, list[Game]]) -> None:
        """Emit score / start / final events by comparing with the previous fetch."""
        if not old:
            return  # first load: nothing "happened"
        for league, games in new.items():
            if league not in old or games is old[league]:
                continue
            before = {g["id"]: g for g in old[league]}
            sport = sport_of(league)
            for g in games:
                p = before.get(g["id"])
                if p is None or g.get("kind", "team") == "field":
                    continue
                base = {"league": league, "tag": LEAGUES[league][1], "game": g}
                if p["state"] == "pre" and g["state"] == "in":
                    self.hub.emit("game_start", base)
                elif p["state"] == "in" and g["state"] == "post":
                    self.hub.emit("game_final", base)
                if g.get("kind", "team") != "team":
                    continue  # tennis sets / fight results are not "scores"
                for side in ("away", "home"):
                    delta = _points(g[side], sport) - _points(p[side], sport)
                    if delta > 0 and (sport != "cricket" or delta >= 4):
                        self.hub.emit("score", {**base, "side": side, "team": g[side], "delta": delta})


def _points(team: dict[str, Any], sport: str) -> int:
    if sport == "cricket":
        return int((team.get("extra") or {}).get("runs") or 0)
    try:
        return int(team.get("score") or 0)
    except (TypeError, ValueError):
        return 0
