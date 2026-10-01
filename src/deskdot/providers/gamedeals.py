"""Free-game giveaways (GamerPower) and discounted games (CheapShark). Keyless, verified live 2026-09-24.

* ``https://www.gamerpower.com/api/giveaways?platform=pc&type=game&sort-by=popularity`` — live giveaways with
  ``title``, ``worth`` ("$5.99" / "N/A"), ``end_date`` ("2026-09-30 23:59:00" / "N/A"), ``platforms``.
  Answers HTTP 201 with an object (not a list) when nothing matches.
* ``https://www.cheapshark.com/api/1.0/deals?sortBy=Deal%20Rating&pageSize=20`` (+ ``storeID``,
  ``upperPrice``) — ``title``, ``salePrice``, ``normalPrice``, ``savings``, ``storeID``;
  ``/stores`` — store names (cached for a day).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
from typing import Any

from .base import Provider

GAMERPOWER = "https://www.gamerpower.com/api/giveaways"
CHEAPSHARK = "https://www.cheapshark.com/api/1.0"
PLATFORMS = {
    "pc": "PC (all stores)",
    "steam": "Steam",
    "epic-games-store": "Epic Games Store",
    "gog": "GOG",
    "itchio": "itch.io",
    "ubisoft": "Ubisoft",
    "ps4": "PlayStation",
    "xbox-one": "Xbox",
    "switch": "Switch",
    "android": "Android",
    "ios": "iOS",
}
STORES = {  # CheapShark store ids worth offering as a filter
    "any": "Any store",
    "1": "Steam",
    "25": "Epic Games Store",
    "7": "GOG",
    "11": "Humble Store",
    "15": "Fanatical",
    "3": "GreenManGaming",
    "27": "Gamesplanet",
    "23": "GameBillet",
}
# store → (short tag, LED colour)
STORE_STYLE: dict[str, tuple[str, tuple[int, int, int]]] = {
    "steam": ("STEAM", (40, 120, 255)),
    "epic": ("EPIC", (220, 220, 230)),
    "gog": ("GOG", (170, 60, 255)),
    "itch": ("ITCH", (255, 40, 90)),
    "humble": ("HUMBLE", (255, 70, 40)),
    "fanatical": ("FANATIC", (255, 120, 0)),
    "greenmangaming": ("GMG", (40, 220, 90)),
    "gamesplanet": ("GPLANET", (0, 200, 255)),
    "gamebillet": ("BILLET", (255, 190, 0)),
    "ubisoft": ("UBI", (0, 140, 255)),
    "uplay": ("UBI", (0, 140, 255)),
    "stove": ("STOVE", (255, 140, 0)),
    "playstation": ("PSN", (30, 80, 255)),
    "xbox": ("XBOX", (40, 220, 40)),
    "switch": ("SWITCH", (255, 30, 30)),
    "android": ("ANDROID", (120, 230, 60)),
    "ios": ("IOS", (200, 200, 220)),
    "prime": ("PRIME", (0, 170, 255)),
    "amazon": ("PRIME", (0, 170, 255)),
    "indiegala": ("GALA", (255, 60, 60)),
    "wingamestore": ("WINGS", (60, 160, 255)),
    "dreamgame": ("DREAM", (160, 90, 255)),
    "gamersgate": ("GGATE", (255, 110, 30)),
}


def store_style(name: str) -> tuple[str, tuple[int, int, int]]:
    key = re.sub(r"[^a-z]", "", name.lower())
    for k, v in STORE_STYLE.items():
        if key.startswith(k) or k in key:
            return v
    tag = re.sub(r"[^A-Z0-9]", "", name.upper())[:6] or "STORE"
    return tag, (140, 140, 160)


def money(v: Any) -> float | None:
    try:
        f = float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def parse_end(s: Any) -> float | None:
    """'2026-09-30 23:59:00' (GamerPower, UTC) → epoch seconds; 'N/A' → None."""
    try:
        d = dt.datetime.strptime(str(s).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return d.replace(tzinfo=dt.UTC).timestamp()


def clean_giveaway_title(title: str) -> tuple[str, str]:
    """'Dire Echo (itchio) Giveaway' → ('Dire Echo', 'itchio'); 'Dwarven Realms (Steam) Key Giveaway' → …"""
    t = re.sub(r"\s+(Key\s+)?Giveaway$", "", str(title or "").strip(), flags=re.I)
    m = re.search(r"\s*\(([^)]+)\)\s*$", t)
    store = ""
    if m:
        store = m.group(1)
        t = t[: m.start()].strip()
    return t, store


def parse_giveaways(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):  # {"status": 0, "status_message": "No active giveaways…"}
        return []
    out = []
    for g in payload:
        if str(g.get("status", "Active")).lower() not in ("active", ""):
            continue
        title, store = clean_giveaway_title(g.get("title", ""))
        platforms = [p.strip() for p in str(g.get("platforms") or "").split(",") if p.strip()]
        if not store:
            store = next(
                (p for p in platforms if p.lower() not in ("pc", "drm-free")),
                platforms[0] if platforms else "PC",
            )
        tag, color = store_style(store)
        out.append(
            {
                "id": f"gp:{g.get('id')}",
                "kind": "free",
                "title": title,
                "store": store,
                "tag": tag,
                "color": color,
                "was": money(g.get("worth")),
                "now": 0.0,
                "savings": 100.0,
                "ends": parse_end(g.get("end_date")),
                "type": str(g.get("type") or ""),
                "url": str(g.get("open_giveaway_url") or g.get("gamerpower_url") or ""),
            }
        )
    return out


def parse_deals(payload: Any, stores: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for d in payload if isinstance(payload, list) else []:
        title = str(d.get("title") or "").strip()
        if not title or title.lower() in seen:  # CheapShark lists one row per store; keep the best-rated
            continue
        seen.add(title.lower())
        store = stores.get(str(d.get("storeID")), f"Store {d.get('storeID')}")
        tag, color = store_style(store)
        now, was = money(d.get("salePrice")), money(d.get("normalPrice"))
        sav = money(d.get("savings")) or 0.0
        out.append(
            {
                "id": f"cs:{d.get('dealID')}",
                "kind": "free" if now == 0 else "deal",
                "title": title,
                "store": store,
                "tag": tag,
                "color": color,
                "was": was,
                "now": now,
                "savings": round(sav),
                "ends": None,
                "rating": money(d.get("dealRating")),
                "url": f"https://www.cheapshark.com/redirect?dealID={d.get('dealID')}",
            }
        )
    return out


class GameDealsProvider(Provider[dict[str, Any]]):
    """``value = {"giveaways": [...], "deals": [...], "updated": epoch}``; see the parsers for item fields."""

    name = "gamedeals"
    interval = 1800.0
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.source = "both"
        self.platform = "pc"
        self.store = "any"
        self.max_price = 0.0
        self.sort = "popularity"
        self._stores: tuple[float, dict[str, str]] | None = None

    def want(
        self,
        source: str = "both",
        platform: str = "pc",
        store: str = "any",
        max_price: float = 0.0,
        sort: str = "popularity",
    ) -> None:
        cfg = (source, platform, store, float(max_price), sort)
        if cfg != (self.source, self.platform, self.store, self.max_price, self.sort):
            self.source, self.platform, self.store, self.max_price, self.sort = cfg
            self.refresh()

    async def _store_names(self) -> dict[str, str]:
        if self._stores and time.time() - self._stores[0] < 86400:
            return self._stores[1]
        r = await self.hub.http.get(f"{CHEAPSHARK}/stores")
        r.raise_for_status()
        names = {str(s["storeID"]): str(s["storeName"]) for s in r.json()}
        self._stores = (time.time(), names)
        return names

    async def _giveaways(self) -> list[dict[str, Any]]:
        r = await self.hub.http.get(
            GAMERPOWER, params={"platform": self.platform, "type": "game", "sort-by": self.sort}
        )
        r.raise_for_status()
        return parse_giveaways(r.json())

    async def _deals(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"sortBy": "Deal Rating", "pageSize": 30, "onSale": 1}
        if self.store != "any":
            params["storeID"] = self.store
        if self.max_price > 0:
            params["upperPrice"] = f"{self.max_price:g}"
        stores, r = await asyncio.gather(
            self._store_names(), self.hub.http.get(f"{CHEAPSHARK}/deals", params=params)
        )
        r.raise_for_status()
        return parse_deals(r.json(), stores)

    async def fetch(self) -> dict[str, Any]:
        out = dict(self.value or {})
        jobs = {}
        if self.source in ("giveaways", "both"):
            jobs["giveaways"] = self._giveaways()
        if self.source in ("deals", "both"):
            jobs["deals"] = self._deals()
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
        errors = []
        for key, res in zip(jobs, results, strict=True):
            if isinstance(res, BaseException):
                errors.append(f"{key}: {type(res).__name__}: {res}")
            else:
                out[key] = res
        if errors and len(errors) == len(jobs):
            raise RuntimeError("; ".join(errors)[:200])
        out["updated"] = time.time()
        return out
