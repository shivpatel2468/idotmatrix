"""Natural events happening now from NASA's EONET v3 (``eonet.gsfc.nasa.gov/api/v3/events``, keyless, CORS).

Wildfires, severe storms, volcanoes, sea and lake ice, floods, dust and haze… curated from many feeds. Each open
event keeps its latest position (storms move: the track's newest point; areas: the polygon's centre).

``value = {"events": [{id, title, category, lat, lon, date (unix), magnitude, unit}] newest first,
"counts": {category: n}, "updated"}``. EONET is slow (2–7 s): it is polled every 30 minutes.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .base import Endpoint, Provider
from .daily import clean_text

API = "https://eonet.gsfc.nasa.gov/api/v3/events"
#: EONET category id -> short panel label
CATEGORIES = {
    "wildfires": "FIRE",
    "severeStorms": "STORM",
    "volcanoes": "VOLCANO",
    "seaLakeIce": "ICE",
    "floods": "FLOOD",
    "dustHaze": "DUST",
    "earthquakes": "QUAKE",
    "landslides": "SLIDE",
    "drought": "DROUGHT",
    "snow": "SNOW",
    "tempExtremes": "HEAT",
    "waterColor": "WATER",
    "manmade": "MANMADE",
}


def _ts(s: Any) -> float:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _point(geom: dict[str, Any]) -> tuple[float, float] | None:
    c = geom.get("coordinates")
    if geom.get("type") == "Point" and isinstance(c, list) and len(c) >= 2:
        return float(c[1]), float(c[0])
    if geom.get("type") == "Polygon" and c and c[0]:
        ring = c[0]
        return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)
    return None


def short_title(title: str, category: str) -> str:
    """'Wildfire - Kangaroo Creek Fire, Queensland, Australia' -> 'KANGAROO CREEK FIRE, QUEENSLAND, AUSTRALIA'."""
    t = clean_text(title, 80)
    if category == "wildfires" and t.startswith("WILDFIRE"):
        t = t[len("WILDFIRE") :].strip(" -") or t
    return t


def parse_events(d: Any) -> list[dict[str, Any]]:
    events = d.get("events") if isinstance(d, dict) else None
    if events is None:
        raise ValueError("eonet: unexpected shape")
    out = []
    for e in events:
        geoms = [g for g in e.get("geometry") or [] if isinstance(g, dict)]
        if not geoms:
            continue
        geoms.sort(key=lambda g: _ts(g.get("date")))
        pt = _point(geoms[-1])
        if pt is None:
            continue
        cat = ((e.get("categories") or [{}])[0] or {}).get("id") or ""
        mag = geoms[-1].get("magnitudeValue")
        out.append(
            {
                "id": str(e.get("id") or ""),
                "title": short_title(str(e.get("title") or ""), cat),
                "category": cat,
                "label": CATEGORIES.get(cat, "EVENT"),
                "lat": round(pt[0], 3),
                "lon": round(pt[1], 3),
                "date": _ts(geoms[-1].get("date")),
                "magnitude": float(mag) if isinstance(mag, (int, float)) else None,
                "unit": str(geoms[-1].get("magnitudeUnit") or ""),
            }
        )
    out.sort(key=lambda e: -e["date"])
    return out


class EarthEventsProvider(Provider[dict[str, Any]]):
    name = "earthevents"
    endpoints = (
        Endpoint(
            "NASA EONET events",
            API + "?status=open&days=20&limit=20",
            check=parse_events,
            note="slow (2-7 s)",
        ),
    )
    interval = 1800.0
    retry = 300.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.days = 30

    def want(self, days: int) -> None:
        days = max(3, min(90, int(days)))
        if days != self.days:
            self.days = days
            self.refresh()

    async def fetch(self) -> dict[str, Any]:
        r = await self.hub.http.get(
            API, params={"status": "open", "days": self.days, "limit": 300}, timeout=30.0
        )
        r.raise_for_status()
        events = parse_events(r.json())
        counts: dict[str, int] = {}
        for e in events:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
        return {"events": events[:200], "counts": counts, "updated": time.time()}
