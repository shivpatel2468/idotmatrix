"""Earthquakes from the USGS real-time GeoJSON summary feeds (no key).

``https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{feed}.geojson`` — updated every minute. Apps call
``want(feed)``; the provider fetches every recently wanted feed and adds distance/bearing from the panel's
location (``hub.location()``) to each event.

``value = {"home": {city, lat, lon, country}, "feeds": {feed: {"title", "generated", "quakes": [...]}}}``;
quakes are newest first, see `parse_feed` for the fields.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from typing import Any

from .base import Provider

URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{feed}.geojson"

#: feed id -> short label (the studio shows the long label from the app's Choice)
FEEDS: dict[str, str] = {
    "all_hour": "ALL 1H",
    "all_day": "ALL 24H",
    "2.5_day": "M2.5+ 24H",
    "2.5_week": "M2.5+ 7D",
    "4.5_day": "M4.5+ 24H",
    "4.5_week": "M4.5+ 7D",
    "4.5_month": "M4.5+ 30D",
    "significant_week": "BIG 7D",
    "significant_month": "BIG 30D",
}
MAX_FEEDS = 4  # remember at most this many recently wanted feeds
MAX_QUAKES = 300  # per feed (all_day can carry ~400 events)
EARTH_KM = 6371.0088

_PLACE_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)?\s*km\s+[NSEW]{1,3}\s+of\s+", re.IGNORECASE)
# US state codes used by USGS place names ("10 km NE of Aguanga, CA")
_US_STATES = {
    "AK": "ALASKA",
    "CA": "CALIF",
    "HI": "HAWAII",
    "NV": "NEVADA",
    "WA": "WASHINGTN",
    "OR": "OREGON",
    "ID": "IDAHO",
    "MT": "MONTANA",
    "WY": "WYOMING",
    "UT": "UTAH",
    "OK": "OKLAHOMA",
    "TX": "TEXAS",
    "NM": "N.MEXICO",
    "AZ": "ARIZONA",
    "CO": "COLORADO",
    "KS": "KANSAS",
    "PR": "P.RICO",
    "TN": "TENNESSEE",
    "MO": "MISSOURI",
    "AR": "ARKANSAS",
}


# ---------------------------------------------------------------------------- geometry
def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine) in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial true bearing from point 1 to point 2, 0..360 clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass(deg: float) -> str:
    """0..360 -> 'N', 'NE', 'E', … (8 points)."""
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[round(deg / 45.0) % 8]


# ---------------------------------------------------------------------------- text
def region_of(place: str) -> str:
    """'16 km SE of Karluk, Alaska' -> 'KARLUK, ALASKA' (the distance prefix is relative to a town, not you)."""
    s = _PLACE_PREFIX.sub("", place or "").strip()
    return s.upper() or "UNKNOWN"


def area_of(place: str) -> str:
    """The broadest part of a place name: 'KARLUK, ALASKA' -> 'ALASKA', '… , CA' -> 'CALIF'."""
    r = region_of(place)
    tail = r.rsplit(",", 1)[-1].strip()
    return _US_STATES.get(tail, tail) or r


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------- parsing
def parse_feed(payload: dict[str, Any], home: dict[str, Any] | None = None) -> dict[str, Any]:
    """A USGS summary GeoJSON document -> ``{"title", "generated", "quakes": [...]}`` (newest first).

    Each quake: ``id, mag, mag_type, place, region, area, time (unix s), lat, lon, depth_km, tsunami,
    alert (None|green|yellow|orange|red), sig, felt, status`` plus ``dist_km, bearing`` when `home` is given.
    Events without a magnitude or position are dropped.
    """
    meta = payload.get("metadata") or {}
    out: list[dict[str, Any]] = []
    hlat = _num((home or {}).get("lat"))
    hlon = _num((home or {}).get("lon"))
    for feat in payload.get("features") or []:
        if not isinstance(feat, dict):
            continue
        p = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        mag = _num(p.get("mag"))
        if mag is None or len(coords) < 2:
            continue
        lon, lat = _num(coords[0]), _num(coords[1])
        if lat is None or lon is None:
            continue
        depth = _num(coords[2]) if len(coords) > 2 else None
        t = _num(p.get("time"))
        place = str(p.get("place") or p.get("title") or "")
        q: dict[str, Any] = {
            "id": str(feat.get("id") or p.get("code") or f"{lat:.2f},{lon:.2f},{t}"),
            "mag": round(mag, 1),
            "mag_type": str(p.get("magType") or ""),
            "place": place,
            "region": region_of(place),
            "area": area_of(place),
            "time": (t or 0.0) / 1000.0,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "depth_km": round(depth, 1) if depth is not None else None,
            "tsunami": bool(p.get("tsunami")),
            "alert": p.get("alert") if p.get("alert") in ("green", "yellow", "orange", "red") else None,
            "sig": int(_num(p.get("sig")) or 0),
            "felt": int(_num(p.get("felt")) or 0),
            "status": str(p.get("status") or ""),
        }
        if hlat is not None and hlon is not None:
            q["dist_km"] = round(distance_km(hlat, hlon, lat, lon), 1)
            q["bearing"] = round(bearing_deg(hlat, hlon, lat, lon), 1)
        out.append(q)
    out.sort(key=lambda q: q["time"], reverse=True)
    return {
        "title": str(meta.get("title") or ""),
        "generated": (_num(meta.get("generated")) or 0.0) / 1000.0,
        "quakes": out[:MAX_QUAKES],
    }


# ---------------------------------------------------------------------------- provider
class QuakesProvider(Provider[dict[str, Any]]):
    name = "quakes"
    interval = 60.0  # USGS regenerates the feeds every minute
    retry = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.feeds: list[str] = []  # most recently wanted last

    def want(self, feed: str) -> None:
        if feed not in FEEDS:
            return
        new = feed not in self.feeds
        if not new:
            self.feeds.remove(feed)
        self.feeds.append(feed)
        del self.feeds[:-MAX_FEEDS]
        if new:
            self.refresh()

    def next_interval(self) -> float:
        if any(f.endswith("month") for f in self.feeds) and not any(
            f.endswith(("hour", "day")) for f in self.feeds
        ):
            return 300.0
        return self.interval

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        def key(d: dict[str, Any] | None) -> Any:
            feeds = (d or {}).get("feeds") or {}
            return {k: [q["id"] for q in v["quakes"][:40]] for k, v in feeds.items()}

        return key(old) != key(new)

    async def _one(self, feed: str, home: dict[str, Any]) -> dict[str, Any]:
        r = await self.hub.http.get(URL.format(feed=feed), timeout=15.0)
        r.raise_for_status()
        return parse_feed(r.json(), home)

    async def fetch(self) -> dict[str, Any]:
        try:
            home = await self.hub.location()
        except Exception:  # distances are a bonus; the map still works without a location
            home = (self.value or {}).get("home") or {}
        feeds = list(self.feeds) or ["2.5_day"]
        results = await asyncio.gather(*(self._one(f, home) for f in feeds), return_exceptions=True)
        out: dict[str, Any] = dict((self.value or {}).get("feeds") or {})
        errors: list[str] = []
        for f, res in zip(feeds, results, strict=True):
            if isinstance(res, BaseException):
                errors.append(f"{f}: {type(res).__name__}")
            else:
                res["fetched"] = time.time()
                out[f] = res
        if len(errors) == len(feeds):
            raise RuntimeError("; ".join(errors))
        return {"home": home, "feeds": {k: v for k, v in out.items() if k in feeds}}
