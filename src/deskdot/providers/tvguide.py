"""What's on TV tonight from TVMaze (``api.tvmaze.com/schedule?country=XX``, keyless, CORS).

The country is the setting or the panel's location; TVMaze lists broadcast TV for ~60 countries (streaming
premieres live on a separate "web" schedule and are left out). Episodes are kept from 2 hours ago onwards so
what is on air now still shows.

``value = {"country", "date", "shows": [{show, episode, start (unix), runtime (min), network, type, genres}]
sorted by start, "updated"}``.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from .base import Endpoint, Provider
from .daily import clean_text

API = "https://api.tvmaze.com/schedule"


def _ts(s: Any) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(s)).timestamp()
    except ValueError:
        return None


def parse_schedule(d: Any) -> list[dict[str, Any]]:
    if not isinstance(d, list):
        raise ValueError("tvmaze: unexpected shape")
    out = []
    seen = set()
    for e in d:
        show = (e or {}).get("show") or {}
        start = _ts(e.get("airstamp"))
        name = clean_text(show.get("name"), 40)
        if not name or start is None or (name, start) in seen:
            continue
        seen.add((name, start))
        net = show.get("network") or show.get("webChannel") or {}
        ep = clean_text(e.get("name"), 40)
        se = f"S{e['season']}E{e['number']}" if e.get("season") and e.get("number") else ""
        out.append(
            {
                "show": name,
                "episode": ep if ep and not ep[0].isdigit() else se,
                "start": start,
                "runtime": int(e.get("runtime") or show.get("runtime") or 30),
                "network": clean_text(net.get("name"), 16),
                "type": str(show.get("type") or ""),
                "genres": [str(g) for g in show.get("genres") or []],
            }
        )
    out.sort(key=lambda s: s["start"])
    return out


def on_air(shows: list[dict[str, Any]], now: float, hour_from: int = 0) -> list[dict[str, Any]]:
    """Shows still running or starting later today, from local hour `hour_from` on (prime time = 19)."""
    out = []
    for s in shows:
        end = s["start"] + s["runtime"] * 60
        if end <= now:
            continue
        if dt.datetime.fromtimestamp(s["start"]).hour < hour_from and s["start"] > now:
            continue
        out.append(s)
    return out


class TvGuideProvider(Provider[dict[str, Any]]):
    name = "tvguide"
    endpoints = (Endpoint("TVMaze schedule", API + "?country=GB", check=parse_schedule),)
    interval = 1800.0
    retry = 300.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.country = ""

    def want(self, country: str) -> None:
        cc = country.strip().upper()[:2]
        if cc != self.country:
            self.country = cc
            self.refresh()

    async def fetch(self) -> dict[str, Any]:
        cc = self.country or str((await self.hub.location()).get("country") or "US").upper()
        today = dt.date.today()
        r = await self.hub.http.get(API, params={"country": cc, "date": today.isoformat()}, timeout=20.0)
        r.raise_for_status()
        now = time.time()
        shows = [s for s in parse_schedule(r.json()) if s["start"] + s["runtime"] * 60 > now - 2 * 3600]
        return {"country": cc, "date": today.isoformat(), "shows": shows[:120], "updated": now}
