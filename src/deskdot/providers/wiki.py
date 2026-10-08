"""Wikipedia's daily featured feed (``api.wikimedia.org/feed/v1/wikipedia/en/featured/YYYY/MM/DD``, keyless, CORS).

One request a day gives "most read" (yesterday's top articles with view counts and a 5-day view history), the
picture of the day and today's featured article. Titles go through `daily.clean_text` (ASCII bitmap fonts) and
the same safety filter as Daily Dose (`daily.is_safe`); obituaries and crime stay in, crude titles don't.

``value = {"date", "trending": [{title, views, description, history: [views…]}], "featured": title,
"picture": {url, title, artist}, "updated"}``.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any

from .base import Endpoint, Provider
from .daily import WIKI_HEADERS, clean_text, is_safe

FEED = "https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{y:04d}/{m:02d}/{d:02d}"
#: pages that top "most read" every day without being news
BORING = re.compile(
    r"^(MAIN PAGE|SPECIAL:|WIKIPEDIA:|FILE:|PORTAL:|XXX|DEATHS IN \d{4}|.*\(DISAMBIGUATION\))"
)


def parse_trending(d: Any, n: int = 15) -> list[dict[str, Any]]:
    mr = d.get("mostread") if isinstance(d, dict) else None
    if not isinstance(mr, dict):
        raise ValueError("wikimedia feed: no mostread")
    out = []
    for a in mr.get("articles") or []:
        title = clean_text(a.get("normalizedtitle") or str(a.get("title") or "").replace("_", " "), 60)
        desc = clean_text(a.get("description"), 80)
        if not title or BORING.match(title) or not is_safe(f"{title} {desc}"):
            continue
        out.append(
            {
                "title": title,
                "views": int(a.get("views") or 0),
                "description": desc,
                "history": [int(h.get("views") or 0) for h in a.get("view_history") or []],
            }
        )
        if len(out) >= n:
            break
    return out


def parse_picture(d: Any) -> dict[str, Any] | None:
    img = d.get("image") if isinstance(d, dict) else None
    if not isinstance(img, dict):
        return None
    url = ((img.get("thumbnail") or {}).get("source")) or ((img.get("image") or {}).get("source"))
    if not url:
        return None
    desc = clean_text((img.get("description") or {}).get("text") or img.get("title"), 60)
    artist = clean_text((img.get("artist") or {}).get("text"), 30)
    return {"url": str(url), "title": desc.removeprefix("FILE:").strip(), "artist": artist}


class WikiProvider(Provider[dict[str, Any]]):
    name = "wiki"
    endpoints = (
        Endpoint(
            "Wikimedia featured feed",
            FEED.format(y=2026, m=1, d=15),
            check=parse_trending,
            headers=tuple(WIKI_HEADERS.items()),
            note="~0.3 MB once a day",
        ),
    )
    interval = 3 * 3600.0
    retry = 300.0

    async def _day(self, day: dt.date) -> Any:
        r = await self.hub.http.get(
            FEED.format(y=day.year, m=day.month, d=day.day), headers=WIKI_HEADERS, timeout=20.0
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def fetch(self) -> dict[str, Any]:
        today = dt.datetime.now(dt.UTC).date()
        if self.value and self.value.get("date") == today.isoformat():
            return self.value  # the feed changes once a day
        day, d = today, await self._day(today)
        if not d or "mostread" not in d:  # early in the UTC day "most read" isn't there yet
            day, d = today - dt.timedelta(days=1), await self._day(today - dt.timedelta(days=1))
        if not d:
            raise RuntimeError("wikimedia feed unavailable")
        return {
            "date": today.isoformat() if day == today else day.isoformat(),
            "trending": parse_trending(d),
            "featured": clean_text(((d.get("tfa") or {}).get("normalizedtitle")), 60),
            "picture": parse_picture(d),
            "updated": time.time(),
        }
