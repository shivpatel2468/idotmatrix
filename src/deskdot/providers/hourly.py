"""The next 24 hours of rain and wind from Open-Meteo (keyless, CORS) for the Rain Chance and Wind apps.

``value = {"city", "unit_speed" (km/h|mph), "unit_rain" (mm|in), "now": {precip, wind, dir, gust, code},
"hours": [{"t": unix, "h": local hour, "prob": %, "rain": amount, "wind", "dir", "gust"}] (24, from the current
hour), "updated"}``.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import Endpoint, Provider

URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = "precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
CURRENT = "precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code"


def _n(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def parse_hourly(d: Any) -> dict[str, Any]:
    if not isinstance(d, dict) or "hourly" not in d:
        raise ValueError("open-meteo: no hourly block")
    off = float(d.get("utc_offset_seconds") or 0)
    tz = timezone(timedelta(seconds=off))
    h = d["hourly"]
    times = h.get("time") or []
    cur = d.get("current") or {}
    now_iso = str(cur.get("time") or "")[:13]
    start = next((i for i, ts in enumerate(times) if str(ts)[:13] >= now_iso), 0) if now_iso else 0

    def col(k: str) -> list[Any]:
        return list(h.get(k) or [])

    prob, rain, wind, dirs, gust = (col(k) for k in HOURLY.split(","))
    hours = []
    for i in range(start, min(len(times), start + 24)):
        t = datetime.fromisoformat(times[i]).replace(tzinfo=tz)
        hours.append(
            {
                "t": t.timestamp(),
                "h": t.hour,
                "prob": _n(prob[i]) if i < len(prob) else None,
                "rain": _n(rain[i]) if i < len(rain) else None,
                "wind": _n(wind[i]) if i < len(wind) else None,
                "dir": _n(dirs[i]) if i < len(dirs) else None,
                "gust": _n(gust[i]) if i < len(gust) else None,
            }
        )
    if not hours:
        raise ValueError("open-meteo: empty hourly block")
    return {
        "now": {
            "precip": _n(cur.get("precipitation")),
            "wind": _n(cur.get("wind_speed_10m")),
            "dir": _n(cur.get("wind_direction_10m")),
            "gust": _n(cur.get("wind_gusts_10m")),
            "code": int(cur.get("weather_code") or 0),
        },
        "hours": hours,
    }


class HourlyProvider(Provider[dict[str, Any]]):
    name = "hourly"
    endpoints = (
        Endpoint(
            "Open-Meteo hourly rain & wind",
            URL
            + "?latitude=51.5074&longitude=-0.1278&current="
            + CURRENT
            + "&hourly="
            + HOURLY
            + "&forecast_hours=24&timezone=auto",
            check=lambda d: parse_hourly(d)["hours"],
        ),
    )
    interval = 900.0
    retry = 60.0

    async def fetch(self) -> dict[str, Any]:
        loc = await self.hub.location()
        imperial = self.hub.store.get("units", "metric") == "imperial"
        r = await self.hub.http.get(
            URL,
            params={
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "current": CURRENT,
                "hourly": HOURLY,
                "forecast_hours": 25,
                "timezone": "auto",
                "wind_speed_unit": "mph" if imperial else "kmh",
                "precipitation_unit": "inch" if imperial else "mm",
            },
        )
        r.raise_for_status()
        out = parse_hourly(r.json())
        out.update(
            city=str(loc.get("city") or ""),
            unit_speed="MPH" if imperial else "KMH",
            unit_rain="IN" if imperial else "MM",
            updated=time.time(),
        )
        return out
