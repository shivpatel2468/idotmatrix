"""Space weather from NOAA's Space Weather Prediction Center (services.swpc.noaa.gov, keyless, CORS).

* ``products/noaa-planetary-k-index.json`` — observed planetary Kp, 3-hourly, the last 7 days. NOAA switched this
  product from a header row + lists to a list of objects in 2026; `parse_kp` reads both.
* ``products/noaa-planetary-k-index-forecast.json`` — observed + estimated + predicted Kp (3 days ahead).
* ``json/ovation_aurora_latest.json`` — the OVATION aurora nowcast: ``[lon, lat, probability %]`` on a 1° grid
  (~0.9 MB, refreshed every few minutes). Reduced here to the chance seen from the panel's location and a 32×16
  world grid for the map view.

``value = {"kp", "kp_time", "history": [kp × 24 (3 days, oldest first)], "forecast": [(unix, kp)…],
"kp_max_24h", "chance", "lat", "oval": [[0..100] × 32] × 16, "updated"}``.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime
from typing import Any

from .base import Endpoint, Provider

SWPC = "https://services.swpc.noaa.gov"
KP = SWPC + "/products/noaa-planetary-k-index.json"
KP_FORECAST = SWPC + "/products/noaa-planetary-k-index-forecast.json"
OVATION = SWPC + "/json/ovation_aurora_latest.json"

#: NOAA geomagnetic storm scale: Kp 5 = G1 … Kp 9 = G5
STORM = ((9.0, "G5"), (8.0, "G4"), (7.0, "G3"), (6.0, "G2"), (5.0, "G1"))
#: Kp comes in thirds (5- = 4.67, 5o = 5, 5+ = 5.33); NOAA counts 5- as Kp 5 for its storm scale
THIRD = 0.34
#: how far the aurora is visible towards the equator from under it (degrees of latitude, ~1000 km)
VIEW_DEG = 9


def _ts(s: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "")).replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Both SWPC table shapes -> list of dicts: objects (2026+) or a header row followed by value rows."""
    if not isinstance(payload, list) or not payload:
        return []
    if isinstance(payload[0], dict):  # keys vary in case between products ("Kp" vs "kp")
        return [{str(k).lower(): v for k, v in r.items()} for r in payload if isinstance(r, dict)]
    head = [str(h).lower() for h in payload[0]]
    return [dict(zip(head, r, strict=False)) for r in payload[1:] if isinstance(r, list)]


def storm_level(kp: float) -> str:
    """'G1'..'G5' for storms, '' below Kp 5."""
    return next((g for k, g in STORM if kp >= k - THIRD), "")


def activity(kp: float) -> str:
    """One word for the panel."""
    g = storm_level(kp)
    if g:
        return f"STORM {g}"
    return "ACTIVE" if kp >= 4 - THIRD else "UNSETTLED" if kp >= 3 - THIRD else "QUIET"


def short(kp: float) -> str:
    """The panel word (fits 30 px in tiny): QUIET / MILD / ACTIVE / STORM."""
    if storm_level(kp):
        return "STORM"
    return "ACTIVE" if kp >= 4 - THIRD else "MILD" if kp >= 3 - THIRD else "QUIET"


def parse_kp(payload: Any) -> list[tuple[float, float]]:
    """Observed Kp -> [(unix, kp)] oldest first."""
    out = []
    for r in _rows(payload):
        ts, kp = _ts(r.get("time_tag")), _f(r.get("kp") if "kp" in r else r.get("kp_index"))
        if ts is not None and kp is not None:
            out.append((ts, kp))
    out.sort()
    return out


def parse_kp_forecast(payload: Any) -> list[tuple[float, float, str]]:
    """Kp forecast -> [(unix, kp, 'observed'|'estimated'|'predicted')] oldest first."""
    out = []
    for r in _rows(payload):
        ts, kp = _ts(r.get("time_tag")), _f(r.get("kp"))
        if ts is not None and kp is not None:
            out.append((ts, kp, str(r.get("observed") or "")))
    out.sort()
    return out


def parse_ovation(payload: Any, lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
    """OVATION nowcast -> {"chance": % seen from (lat, lon), "oval": 16×32 grid of max %, "time"}.

    "Seen from" = the strongest aurora at your longitude (±2°) between your latitude and VIEW_DEG towards the
    nearest pole: an aurora overhead 900 km north is still low on the horizon.
    """
    coords = payload.get("coordinates") if isinstance(payload, dict) else None
    if not coords:
        raise ValueError("ovation: no coordinates")
    oval = [[0] * 32 for _ in range(16)]
    chance = 0
    if lat is not None and lon is not None:
        lon360 = lon % 360
        lo, hi = (lat, lat + VIEW_DEG) if lat >= 0 else (lat - VIEW_DEG, lat)
    for p in coords:
        try:
            x, y, v = float(p[0]), float(p[1]), int(p[2])
        except (TypeError, ValueError, IndexError):
            continue
        if v <= 0:
            continue
        gx = int(((x + 180) % 360) / 360 * 32) % 32  # the map is centred on Greenwich like gfx.worldmap
        gy = min(15, max(0, int((90 - y) / 180 * 16)))
        if v > oval[gy][gx]:
            oval[gy][gx] = v
        if lat is not None and lo <= y <= hi:
            d = abs((x - lon360 + 180) % 360 - 180)
            if d <= 2 and v > chance:
                chance = v
    return {
        "chance": min(100, chance) if lat is not None else None,
        "oval": oval,
        "time": _ts(payload.get("Forecast Time") or payload.get("Observation Time")),
    }


def summarise(
    kp: list[tuple[float, float]], forecast: list[tuple[float, float, str]], now: float | None = None
) -> dict[str, Any]:
    now = time.time() if now is None else now
    if not kp:
        raise ValueError("no Kp observations")
    ahead = [(ts, k) for ts, k, kind in forecast if kind == "predicted" and ts >= now - 3 * 3600]
    nxt = [k for ts, k in ahead if ts <= now + 24 * 3600]
    return {
        "kp": kp[-1][1],
        "kp_time": kp[-1][0],
        "history": [k for _ts_, k in kp[-24:]],
        "forecast": ahead[:16],
        "kp_max_24h": max(nxt) if nxt else None,
    }


class SpaceWeatherProvider(Provider[dict[str, Any]]):
    name = "spaceweather"
    endpoints = (
        Endpoint("SWPC planetary Kp", KP, check=parse_kp),
        Endpoint("SWPC Kp forecast", KP_FORECAST, check=parse_kp_forecast),
        Endpoint(
            "SWPC OVATION aurora",
            OVATION,
            check=lambda d: parse_ovation(d, 64.8, -147.7)["oval"],
            note="~0.9 MB",
        ),
    )
    interval = 900.0  # Kp is 3-hourly, the nowcast refreshes every ~5 min: 15 min is plenty for a desk
    retry = 120.0

    async def _json(self, url: str) -> Any:
        r = await self.hub.http.get(url, timeout=20.0)
        r.raise_for_status()
        return r.json()

    async def fetch(self) -> dict[str, Any]:
        try:
            loc = await self.hub.location()
            lat, lon = float(loc["lat"]), float(loc["lon"])
        except Exception:
            lat = lon = None  # the Kp screens work without a location
        kp_raw, fc_raw, ov_raw = await asyncio.gather(
            self._json(KP), self._json(KP_FORECAST), self._json(OVATION), return_exceptions=True
        )
        if isinstance(kp_raw, BaseException):
            raise kp_raw
        out = summarise(
            parse_kp(kp_raw), [] if isinstance(fc_raw, BaseException) else parse_kp_forecast(fc_raw)
        )
        ov: dict[str, Any] = {"chance": None, "oval": None}
        if not isinstance(ov_raw, BaseException):
            try:
                ov = await asyncio.to_thread(parse_ovation, ov_raw, lat, lon)
            except ValueError:
                pass
        elif self.value:  # keep the last map through a failed nowcast
            ov = {"chance": self.value.get("chance"), "oval": self.value.get("oval")}
        out.update(chance=ov.get("chance"), oval=ov.get("oval"), lat=lat, lon=lon, updated=time.time())
        return out
