"""Tech & space headlines from four keyless sources (all verified live).

========== ======================================================================= ===========================
source     endpoint                                                                 feeds
========== ======================================================================= ===========================
hn         hacker-news.firebaseio.com/v0/{top,best,new,ask,show}stories.json        items fetched concurrently
           + /v0/item/{id}.json
space      api.spaceflightnewsapi.net/v4/articles/?limit=N                          latest articles
devto      dev.to/api/articles?top=1|7 · /api/articles/latest                       top (day) / best (week) / new
lobsters   lobste.rs/hottest.json · /newest.json · /active.json                     hottest / newest / active
========== ======================================================================= ===========================

Every story is normalised to ``{id, title, score, comments, time, by, site}``; ``score``/``comments`` are
``None`` where a source has none (Spaceflight News). Reddit's JSON API was tried and is dead without OAuth
(HTTP 403).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from .base import Provider
from .daily import clean_text

HN_FEED = "https://hacker-news.firebaseio.com/v0/{feed}stories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
SPACE = "https://api.spaceflightnewsapi.net/v4/articles/"
DEVTO = "https://dev.to/api/articles"
LOBSTERS = "https://lobste.rs/{feed}.json"

SOURCES: dict[str, str] = {
    "hn": "Hacker News",
    "space": "Spaceflight News",
    "devto": "DEV Community",
    "lobsters": "Lobsters",
}
FEEDS = ("top", "best", "new", "ask", "show")
LOBSTER_FEEDS = {"top": "hottest", "best": "active", "new": "newest", "ask": "hottest", "show": "hottest"}
MAX_STORIES = 30
ITEM_TTL = 240.0  # seconds an HN item (score/comments) is trusted before it is fetched again


def _iso(ts: Any) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def domain(url: Any) -> str:
    host = urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    return clean_text(host, 40)


def _story(sid: Any, title: Any, **kw: Any) -> dict[str, Any] | None:
    t = clean_text(title, 200)
    if not t:
        return None
    return {"id": str(sid), "title": t, **kw}


def parse_hn_item(d: Any) -> dict[str, Any] | None:
    if not isinstance(d, dict) or d.get("dead") or d.get("deleted") or d.get("type") not in ("story", "job"):
        return None
    return _story(
        d.get("id"),
        d.get("title"),
        score=int(d.get("score") or 0),
        comments=int(d.get("descendants") or 0) if d.get("type") == "story" else None,
        time=float(d.get("time") or 0) or None,
        by=clean_text(d.get("by"), 20),
        site=domain(d.get("url")) or "YCOMBINATOR.COM",
    )


def parse_space(d: Any) -> list[dict[str, Any]]:
    out = []
    for a in (d or {}).get("results") or []:
        s = _story(
            a.get("id"),
            a.get("title"),
            score=None,
            comments=None,
            time=_iso(a.get("published_at")),
            by=clean_text(a.get("news_site"), 24),
            site=clean_text(a.get("news_site"), 24) or domain(a.get("url")),
        )
        if s:
            out.append(s)
    return out


def parse_devto(d: Any) -> list[dict[str, Any]]:
    out = []
    for a in d if isinstance(d, list) else []:
        s = _story(
            a.get("id"),
            a.get("title"),
            score=int(a.get("public_reactions_count") or a.get("positive_reactions_count") or 0),
            comments=int(a.get("comments_count") or 0),
            time=_iso(a.get("published_timestamp") or a.get("published_at")),
            by=clean_text((a.get("user") or {}).get("name"), 20),
            site="DEV.TO",
        )
        if s:
            out.append(s)
    return out


def parse_lobsters(d: Any) -> list[dict[str, Any]]:
    out = []
    for a in d if isinstance(d, list) else []:
        s = _story(
            a.get("short_id"),
            a.get("title"),
            score=int(a.get("score") or 0),
            comments=int(a.get("comment_count") or 0),
            time=_iso(a.get("created_at")),
            by=clean_text(a.get("submitter_user"), 20),
            site=domain(a.get("url")) or "LOBSTE.RS",
        )
        if s:
            out.append(s)
    return out


class HeadlinesProvider(Provider[dict[str, list[dict[str, Any]]]]):
    """``value = {"source:feed": [stories, ranked]}``. Apps call ``want(source, feed, count)``."""

    name = "headlines"
    interval = 180.0
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.wanted: dict[str, int] = {}  # "source:feed" -> count
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}  # hn id -> (fetched, story)

    @staticmethod
    def key(source: str, feed: str) -> str:
        if source == "space":
            feed = "top"
        return f"{source}:{feed}"

    def want(self, source: str, feed: str = "top", count: int = 10) -> None:
        k = self.key(source if source in SOURCES else "hn", feed if feed in FEEDS else "top")
        n = max(1, min(MAX_STORIES, int(count)))
        if self.wanted.get(k, 0) < n:
            self.wanted[k] = n
            self.refresh()
        # keep the latest few keys only
        while len(self.wanted) > 3:
            self.wanted.pop(next(iter(self.wanted)))

    def announce(self, old: Any, new: dict[str, list[dict[str, Any]]]) -> bool:
        def sig(v: Any) -> Any:
            return {k: [(s["id"], s.get("score")) for s in lst] for k, lst in (v or {}).items()}

        return sig(old) != sig(new)

    async def _json(self, url: str, **kw: Any) -> Any:
        r = await self.hub.http.get(url, **kw)
        r.raise_for_status()
        return r.json()

    async def _hn(self, feed: str, n: int) -> list[dict[str, Any]]:
        ids = (await self._json(HN_FEED.format(feed=feed)))[: n + 5]  # a few spares for dead items
        now = time.time()
        sem = asyncio.Semaphore(10)

        async def item(i: int) -> dict[str, Any] | None:
            hit = self._items.get(str(i))
            if hit and now - hit[0] < ITEM_TTL:
                return hit[1]
            async with sem:
                s = parse_hn_item(await self._json(HN_ITEM.format(id=i)))
            if s:
                self._items[str(i)] = (now, s)
            return s

        res = await asyncio.gather(*(item(i) for i in ids), return_exceptions=True)
        stories = [r for r in res if isinstance(r, dict)]
        if not stories and ids:
            raise RuntimeError("hacker news items unavailable")
        keep = {str(i) for i in ids}
        self._items = {k: v for k, v in self._items.items() if k in keep or now - v[0] < 3600}
        return stories[:n]

    async def _one(self, key: str, n: int) -> list[dict[str, Any]]:
        source, feed = key.split(":")
        if source == "hn":
            return await self._hn(feed, n)
        if source == "space":
            return parse_space(await self._json(SPACE, params={"limit": n}))[:n]
        if source == "devto":
            if feed == "new":
                return parse_devto(await self._json(f"{DEVTO}/latest", params={"per_page": n}))[:n]
            top = 7 if feed == "best" else 1
            return parse_devto(await self._json(DEVTO, params={"top": top, "per_page": n}))[:n]
        return parse_lobsters(await self._json(LOBSTERS.format(feed=LOBSTER_FEEDS.get(feed, "hottest"))))[:n]

    async def fetch(self) -> dict[str, list[dict[str, Any]]]:
        keys = list(self.wanted)
        out = dict(self.value or {})
        if not keys:
            return out
        res = await asyncio.gather(*(self._one(k, self.wanted[k]) for k in keys), return_exceptions=True)
        errors = []
        for k, r in zip(keys, res, strict=True):
            if isinstance(r, BaseException):
                errors.append(f"{k}: {type(r).__name__}: {r}")
            else:
                for rank, s in enumerate(r, 1):
                    s["rank"] = rank
                out[k] = r
        if errors and not any(k in out for k in keys):
            raise RuntimeError("; ".join(errors)[:200])
        return {k: v for k, v in out.items() if k in self.wanted}
