"""Tides & surf from the Open-Meteo Marine API (keyless): sea level (tide model), waves and swell.

``/v1/marine?hourly=wave_height,wave_period,wave_direction,swell_wave_height,swell_wave_period,
sea_level_height_msl&timezone=auto&past_days=1&forecast_days=2`` — verified live 2026-09-25. Inland points
answer 200 with all-null series; the provider reports that as ``has_tide/has_waves = False`` so the app can say
NO SEA. The target is the panel's location unless the app sets a coast point with `want(lat, lon)`.
High and low water are found from the hourly sea level with a parabola through each turning point.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from .base import Provider

MARINE = "https://marine-api.open-meteo.com/v1/marine"
HOURLY = "wave_height,wave_period,wave_direction,swell_wave_height,swell_wave_period,sea_level_height_msl"


def extrema(ts: list[float], h: list[float | None]) -> list[dict[str, Any]]:
    """High/low waters: hourly turning points refined with a parabola (time and height)."""
    out = []
    for i in range(1, len(h) - 1):
        a, b, c = h[i - 1], h[i], h[i + 1]
        if a is None or b is None or c is None:
            continue
        if (b > a and b >= c) or (b < a and b <= c):
            den = a - 2 * b + c
            off = 0.5 * (a - c) / den if den else 0.0
            off = max(-0.5, min(0.5, off))
            step = ts[i + 1] - ts[i]
            out.append(
                {
                    "ts": ts[i] + off * step,
                    "h": b - 0.25 * (a - c) * off,
                    "kind": "high" if b > a else "low",
                }
            )
    return out


def parse_marine(d: dict[str, Any]) -> dict[str, Any]:
    off = float(d.get("utc_offset_seconds") or 0.0)
    tz = timezone(timedelta(seconds=off))
    hourly = d.get("hourly") or {}
    times = [datetime.fromisoformat(t).replace(tzinfo=tz).timestamp() for t in hourly.get("time") or []]

    def series(key: str) -> list[float | None]:
        vals = hourly.get(key) or []
        return [float(v) if v is not None else None for v in vals][: len(times)]

    sea = series("sea_level_height_msl")
    wave = series("wave_height")
    has_tide = sum(v is not None for v in sea) >= 6
    has_waves = sum(v is not None for v in wave) >= 6
    return {
        "lat": d.get("latitude"),
        "lon": d.get("longitude"),
        "tz_offset": off,
        "ts": times,
        "sea": sea,
        "wave": wave,
        "period": series("wave_period"),
        "direction": series("wave_direction"),
        "swell": series("swell_wave_height"),
        "swell_period": series("swell_wave_period"),
        "extrema": extrema(times, sea) if has_tide else [],
        "has_tide": has_tide,
        "has_waves": has_waves,
    }


def at(d: dict[str, Any], key: str, ts: float) -> float | None:
    """Linear interpolation of an hourly series at `ts` (None outside or on gaps)."""
    times, vals = d["ts"], d[key]
    for i in range(len(times) - 1):
        if times[i] <= ts <= times[i + 1]:
            a, b = vals[i], vals[i + 1]
            if a is None or b is None:
                return a if b is None else b
            k = (ts - times[i]) / (times[i + 1] - times[i])
            return a + (b - a) * k
    return None


def compass(deg: float) -> str:
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[round((deg % 360) / 45) % 8]


class TidesProvider(Provider[dict[str, Any]]):
    name = "tides"
    interval = 1800.0
    retry = 120.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.target: tuple[float, float] | None = None

    def want(self, lat: float | None, lon: float | None) -> None:
        """Use a coast point instead of the panel's location (None/0,0 = home)."""
        t = None if lat is None or lon is None or (lat == 0 and lon == 0) else (float(lat), float(lon))
        if t != self.target:
            self.target = t
            self.refresh()

    async def fetch(self) -> dict[str, Any]:
        if self.target:
            lat, lon = self.target
            place = f"{lat:.2f},{lon:.2f}"
        else:
            loc = await self.hub.location()
            lat, lon, place = float(loc["lat"]), float(loc["lon"]), str(loc.get("city") or "")
        r = await self.hub.http.get(
            MARINE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": HOURLY,
                "timezone": "auto",
                "past_days": 1,
                "forecast_days": 2,
            },
        )
        r.raise_for_status()
        out = parse_marine(r.json())
        out["place"] = place
        out["unit"] = "ft" if self.hub.store.get("units", "metric") == "imperial" else "m"
        out["fetched"] = datetime.now(UTC).timestamp()
        return out
