"""Air quality, UV and pollen from the Open-Meteo Air Quality API (no key).

``https://air-quality-api.open-meteo.com/v1/air-quality`` — CAMS global model (pollen only over Europe, where the
CAMS European model runs; elsewhere the pollen fields are ``null`` and the value carries ``pollen = {}``).
Location comes from ``hub.location()``.
"""

from __future__ import annotations

import math
from typing import Any

from .base import Provider

URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

#: API field -> our key (µg/m³ except the indices and UV)
CURRENT: dict[str, str] = {
    "us_aqi": "us_aqi",
    "european_aqi": "eu_aqi",
    "pm2_5": "pm2_5",
    "pm10": "pm10",
    "ozone": "o3",
    "nitrogen_dioxide": "no2",
    "sulphur_dioxide": "so2",
    "carbon_monoxide": "co",
    "uv_index": "uv",
}
POLLEN: dict[str, str] = {
    "grass_pollen": "grass",
    "birch_pollen": "birch",
    "alder_pollen": "alder",
    "ragweed_pollen": "ragweed",
    "mugwort_pollen": "mugwort",
    "olive_pollen": "olive",
}
HOURLY: dict[str, str] = {"us_aqi": "us_aqi", "european_aqi": "eu_aqi", "pm2_5": "pm2_5", "uv_index": "uv"}
HOURS = 24


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_air(payload: dict[str, Any], city: str = "") -> dict[str, Any]:
    """An Open-Meteo air-quality response -> the provider value.

    ``{city, time, us_aqi, eu_aqi, pm2_5, pm10, o3, no2, so2, co, uv, pollen: {name: grains/m³},
    hourly: {us_aqi|eu_aqi|pm2_5|uv: [24 values from the current hour]}, hour0}``. Missing numbers are None.
    """
    cur = payload.get("current") or {}
    if not cur:
        raise ValueError("no current air quality")
    out: dict[str, Any] = {"city": city, "time": str(cur.get("time") or "")}
    for src, key in CURRENT.items():
        out[key] = _num(cur.get(src))
    if out["us_aqi"] is None and out["eu_aqi"] is None:
        raise ValueError("no AQI for this location")
    out["pollen"] = {key: v for src, key in POLLEN.items() if (v := _num(cur.get(src))) is not None}
    hourly = payload.get("hourly") or {}
    times: list[str] = list(hourly.get("time") or [])
    now = out["time"][:13]
    start = next((i for i, ts in enumerate(times) if str(ts)[:13] >= now), 0) if now else 0
    out["hourly"] = {
        key: [_num(v) for v in list(hourly.get(src) or [])[start : start + HOURS]]
        for src, key in HOURLY.items()
    }
    out["hour0"] = int(times[start][11:13]) if start < len(times) and len(str(times[start])) >= 13 else 0
    return out


class AirQualityProvider(Provider[dict[str, Any]]):
    name = "airquality"
    interval = 900.0  # the model is hourly
    retry = 60.0

    async def fetch(self) -> dict[str, Any]:
        loc = await self.hub.location()
        params = {
            "latitude": loc["lat"],
            "longitude": loc["lon"],
            "current": ",".join([*CURRENT, *POLLEN]),
            "hourly": ",".join(HOURLY),
            "forecast_days": 2,
            "timezone": "auto",
        }
        r = await self.hub.http.get(URL, params=params)
        r.raise_for_status()
        return parse_air(r.json(), str(loc.get("city") or ""))
