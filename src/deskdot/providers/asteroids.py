"""Asteroid close approaches from NASA/JPL's SBDB Close-Approach Data API (``ssd-api.jpl.nasa.gov/cad.api``).

Keyless (unlike NASA's NeoWs, which needs an api.nasa.gov key). No CORS: the web app goes through the proxy.
We ask for every approach within 10 lunar distances (LD) over the next 60 days.

``value = {"approaches": [{name, time (unix), dist_ld, dist_km, speed (km/s), size_m: (lo, hi) | None}] soonest
first, "updated"}``. Size comes from the absolute magnitude H with albedo 0.25–0.05 (the usual range).
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any

from .base import Endpoint, Provider

API = "https://ssd-api.jpl.nasa.gov/cad.api"
LD_KM = 384_400.0
AU_KM = 149_597_870.7


def size_m(h: float) -> tuple[float, float]:
    """Diameter range (m) from absolute magnitude H for albedo 0.25 (small) .. 0.05 (large)."""
    d = lambda p: 1329.0 / math.sqrt(p) * 10 ** (-h / 5) * 1000  # noqa: E731
    return d(0.25), d(0.05)


def parse_cad(d: Any) -> list[dict[str, Any]]:
    if not isinstance(d, dict) or "fields" not in d:
        raise ValueError("cad: unexpected shape")
    if not d.get("data"):
        return []
    f = {name: i for i, name in enumerate(d["fields"])}
    out = []
    for row in d["data"]:
        try:
            when = datetime.strptime(row[f["cd"]], "%Y-%b-%d %H:%M").replace(tzinfo=UTC).timestamp()
            au = float(row[f["dist"]])
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        h = row[f["h"]] if "h" in f else None
        try:
            size = size_m(float(h)) if h not in (None, "") else None
        except ValueError:
            size = None
        out.append(
            {
                "name": str(row[f["des"]]).strip().upper(),
                "time": when,
                "dist_km": au * AU_KM,
                "dist_ld": au * AU_KM / LD_KM,
                "speed": float(row[f["v_rel"]]) if row[f["v_rel"]] else None,
                "size_m": size,
            }
        )
    out.sort(key=lambda a: a["time"])
    return out


class AsteroidsProvider(Provider[dict[str, Any]]):
    name = "asteroids"
    endpoints = (
        Endpoint(
            "JPL close approaches",
            API + "?dist-max=10LD&date-min=now&date-max=%2B60&sort=date",
            check=lambda d: parse_cad(d) is not None,
            expect=("signature.version", "fields"),
        ),
    )
    interval = 6 * 3600.0
    retry = 600.0

    async def fetch(self) -> dict[str, Any]:
        r = await self.hub.http.get(
            API,
            params={"dist-max": "10LD", "date-min": "now", "date-max": "+60", "sort": "date"},
            timeout=20.0,
        )
        r.raise_for_status()
        now = time.time()
        approaches = [a for a in parse_cad(r.json()) if a["time"] >= now - 6 * 3600]
        return {"approaches": approaches[:40], "updated": now}
