"""What to wear: the next few hours of Open-Meteo forecast (keyless), summarised for the What to Wear app.

Always fetched in °C / km/h so the app's thresholds mean one thing; the app converts for display using the
store's ``units`` (echoed here as ``unit``).
"""

from __future__ import annotations

from typing import Any

from .base import Provider

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
HOURLY = (
    "temperature_2m,apparent_temperature,precipitation_probability,precipitation,snowfall,"
    "uv_index,weather_code,wind_speed_10m,is_day"
)
SNOW_CODES = {71, 73, 75, 77, 85, 86}
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}


def summarise(d: dict[str, Any], hours: int = 6) -> dict[str, Any]:
    """Open-Meteo /forecast JSON -> the window's extremes, starting at the current hour."""
    h = d.get("hourly") or {}
    times: list[str] = h.get("time") or []
    now_iso = str((d.get("current") or {}).get("time") or "")[:13]
    start = next((i for i, ts in enumerate(times) if ts[:13] >= now_iso), 0) if now_iso else 0
    sl = slice(start, start + hours)

    def col(key: str) -> list[float]:
        return [float(v) for v in (h.get(key) or [])[sl] if v is not None]

    temps, feels = col("temperature_2m"), col("apparent_temperature")
    if not temps:
        raise ValueError("forecast has no hourly temperatures")
    codes = [int(c) for c in col("weather_code")]
    return {
        "temp": temps[0],
        "feels_min": min(feels or temps),
        "feels_max": max(feels or temps),
        "temp_min": min(temps),
        "temp_max": max(temps),
        "rain_prob": max(col("precipitation_probability") or [0.0]),
        "rain_mm": sum(col("precipitation")),
        "snow_cm": sum(col("snowfall")),
        "uv_max": max(col("uv_index") or [0.0]),
        "wind_max": max(col("wind_speed_10m") or [0.0]),
        "day": any(v >= 1 for v in col("is_day")),
        "snow_code": any(c in SNOW_CODES for c in codes),
        "rain_code": any(c in RAIN_CODES for c in codes),
        "hours": len(temps),
        "time": times[start] if times else "",
    }


class WearProvider(Provider[dict[str, Any]]):
    name = "wear"
    interval = 900.0
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.hours = 6

    def want(self, hours: int) -> None:
        """Set the look-ahead window (hours); refetches if it changed."""
        hours = max(1, min(12, int(hours)))
        if hours != self.hours:
            self.hours = hours
            self.refresh()

    async def fetch(self) -> dict[str, Any]:
        loc = await self.hub.location()
        r = await self.hub.http.get(
            OPEN_METEO,
            params={
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "current": "temperature_2m",
                "hourly": HOURLY,
                "forecast_hours": 13,
                "timezone": "auto",
            },
        )
        r.raise_for_status()
        out = summarise(r.json(), self.hours)
        out["city"] = loc.get("city") or ""
        out["unit"] = "F" if self.hub.store.get("units", "metric") == "imperial" else "C"
        return out
