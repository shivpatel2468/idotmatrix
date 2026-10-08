"""Grand Prix calendar and results from the Jolpica API (the community successor of Ergast; keyless, CORS).

* ``api.jolpi.ca/ergast/f1/current/next.json`` — the next round with every session's UTC start;
* ``/current/last/results.json`` — the last race's classification (we keep the podium).

Ergast itself (``ergast.com/mrd``, still listed on public-apis) shut down at the end of 2024; Jolpica serves the
same JSON shape. ``value = {"next": {season, round, name, circuit, locality, country, lat, lon, start,
sessions: [(label, unix)]} | None, "last": {name, round, podium: [{pos, code, name, team}]} | None}``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from .base import Endpoint, Provider
from .daily import clean_text

API = "https://api.jolpi.ca/ergast/f1"
SESSIONS = (
    ("FirstPractice", "PRACTICE 1"),
    ("SecondPractice", "PRACTICE 2"),
    ("ThirdPractice", "PRACTICE 3"),
    ("SprintQualifying", "SPRINT QUALI"),
    ("Sprint", "SPRINT"),
    ("Qualifying", "QUALIFYING"),
)


def _when(d: Any) -> float | None:
    if not isinstance(d, dict) or not d.get("date"):
        return None
    t = str(d.get("time") or "00:00:00Z").replace("Z", "")
    try:
        return datetime.fromisoformat(f"{d['date']}T{t}").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _races(d: Any) -> list[dict[str, Any]]:
    try:
        return list(d["MRData"]["RaceTable"]["Races"])
    except (KeyError, TypeError):
        raise ValueError("jolpica: unexpected shape") from None


def parse_next(d: Any) -> dict[str, Any] | None:
    races = _races(d)
    if not races:
        return None  # the season is over
    r = races[0]
    circ = r.get("Circuit") or {}
    loc = circ.get("Location") or {}
    start = _when(r)
    sessions = [(label, ts) for key, label in SESSIONS if (ts := _when(r.get(key))) is not None]
    if start is not None:
        sessions.append(("RACE", start))
    sessions.sort(key=lambda s: s[1])
    return {
        "season": str(r.get("season") or ""),
        "round": int(r.get("round") or 0),
        "name": clean_text(str(r.get("raceName") or "").replace("Grand Prix", "GP"), 40),
        "circuit": clean_text(circ.get("circuitName"), 40),
        "locality": clean_text(loc.get("locality"), 30),
        "country": clean_text(loc.get("country"), 30),
        "lat": float(loc.get("lat") or 0),
        "lon": float(loc.get("long") or 0),
        "start": start,
        "sessions": sessions,
    }


def parse_last(d: Any) -> dict[str, Any] | None:
    races = _races(d)
    if not races:
        return None
    r = races[0]
    podium = []
    for res in (r.get("Results") or [])[:3]:
        drv = res.get("Driver") or {}
        podium.append(
            {
                "pos": int(res.get("position") or len(podium) + 1),
                "code": clean_text(drv.get("code") or str(drv.get("familyName") or "")[:3], 3),
                "name": clean_text(drv.get("familyName"), 16),
                "team": clean_text((res.get("Constructor") or {}).get("name"), 16),
            }
        )
    return {
        "name": clean_text(str(r.get("raceName") or "").replace("Grand Prix", "GP"), 40),
        "round": int(r.get("round") or 0),
        "date": _when(r),
        "podium": podium,
    }


class RacingProvider(Provider[dict[str, Any]]):
    name = "racing"
    endpoints = (
        Endpoint("Jolpica next race", API + "/current/next.json", expect=("MRData.RaceTable.Races",)),
        Endpoint(
            "Jolpica last results",
            API + "/current/last/results.json",
            check=lambda d: parse_last(d) is not None,
        ),
    )
    interval = 3600.0
    retry = 120.0

    def next_interval(self) -> float:
        nxt = (self.value or {}).get("next") or {}
        start = nxt.get("start")
        if start and -3 * 3600 < start - time.time() < 0:
            return 600.0  # a race is running: pick up the result soon after the flag
        return self.interval

    async def _json(self, path: str) -> Any:
        r = await self.hub.http.get(API + path, timeout=15.0)
        r.raise_for_status()
        return r.json()

    async def fetch(self) -> dict[str, Any]:
        nxt, last = await asyncio.gather(
            self._json("/current/next.json"), self._json("/current/last/results.json"), return_exceptions=True
        )
        if isinstance(nxt, BaseException) and isinstance(last, BaseException):
            raise nxt
        old = self.value or {}
        return {
            "next": old.get("next") if isinstance(nxt, BaseException) else parse_next(nxt),
            "last": old.get("last") if isinstance(last, BaseException) else parse_last(last),
            "updated": time.time(),
        }
