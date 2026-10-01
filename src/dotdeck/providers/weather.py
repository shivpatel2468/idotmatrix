"""Weather from Open-Meteo (no key). Location: studio setting, else IP geolocation (cached 6 h)."""

from __future__ import annotations

import time
from typing import Any

from .base import Provider

# WMO weather code -> (condition id, label)
WMO: dict[int, tuple[str, str]] = {
    0: ("clear", "CLEAR"),
    1: ("clear", "FAIR"),
    2: ("partly", "PARTLY"),
    3: ("cloudy", "CLOUDY"),
    45: ("fog", "FOG"),
    48: ("fog", "FOG"),
    51: ("drizzle", "DRIZZLE"),
    53: ("drizzle", "DRIZZLE"),
    55: ("drizzle", "DRIZZLE"),
    56: ("drizzle", "ICY"),
    57: ("drizzle", "ICY"),
    61: ("rain", "RAIN"),
    63: ("rain", "RAIN"),
    65: ("rain", "HEAVY"),
    66: ("rain", "ICY"),
    67: ("rain", "ICY"),
    71: ("snow", "SNOW"),
    73: ("snow", "SNOW"),
    75: ("snow", "HEAVY"),
    77: ("snow", "SNOW"),
    80: ("rain", "SHOWER"),
    81: ("rain", "SHOWER"),
    82: ("rain", "STORM"),
    85: ("snow", "SNOW"),
    86: ("snow", "SNOW"),
    95: ("storm", "STORM"),
    96: ("storm", "STORM"),
    99: ("storm", "STORM"),
}


class WeatherProvider(Provider[dict[str, Any]]):
    name = "weather"
    interval = 600.0
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._geo: dict[str, Any] | None = None
        self._geo_t = 0.0

    async def _location(self) -> dict[str, Any]:
        if hasattr(self.hub, "location"):
            return await self.hub.location()
        loc = self.hub.store.get("location") or {}
        if loc.get("lat") is not None and loc.get("lon") is not None:
            return {"city": loc.get("city") or "HOME", "lat": float(loc["lat"]), "lon": float(loc["lon"])}
        if loc.get("city"):
            r = await self.hub.http.get(
                "https://geocoding-api.open-meteo.com/v1/search", params={"name": loc["city"], "count": 1}
            )
            r.raise_for_status()
            hits = r.json().get("results") or []
            if hits:
                h = hits[0]
                return {"city": h["name"], "lat": h["latitude"], "lon": h["longitude"]}
        if self._geo and time.time() - self._geo_t < 6 * 3600:
            return self._geo
        r = await self.hub.http.get("http://ip-api.com/json/?fields=status,city,lat,lon")
        r.raise_for_status()
        d = r.json()
        if d.get("status") != "success":
            raise RuntimeError("IP geolocation failed; set a city in Settings")
        self._geo, self._geo_t = {"city": d["city"], "lat": d["lat"], "lon": d["lon"]}, time.time()
        return self._geo

    async def fetch(self) -> dict[str, Any]:
        loc = await self._location()
        units = self.hub.store.get("units", "metric")
        params = {
            "latitude": loc["lat"],
            "longitude": loc["lon"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
            "hourly": "temperature_2m",
            "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
            "forecast_days": 2,
            "timezone": "auto",
            "temperature_unit": "fahrenheit" if units == "imperial" else "celsius",
            "wind_speed_unit": "mph" if units == "imperial" else "kmh",
        }
        r = await self.hub.http.get("https://api.open-meteo.com/v1/forecast", params=params)
        r.raise_for_status()
        d = r.json()
        cur = d["current"]
        code = int(cur.get("weather_code", 0))
        cond, label = WMO.get(code, ("cloudy", "CLOUDY"))
        # next 24 hours of temperatures, starting at the current hour
        hourly = d.get("hourly", {})
        times: list[str] = hourly.get("time", [])
        temps: list[float] = hourly.get("temperature_2m", [])
        now_iso = cur.get("time", "")[:13]
        start = next((i for i, ts in enumerate(times) if ts[:13] >= now_iso), 0)
        return {
            "city": loc["city"],
            "temp": round(cur["temperature_2m"]),
            "feels": round(cur.get("apparent_temperature", cur["temperature_2m"])),
            "humidity": cur.get("relative_humidity_2m"),
            "wind": round(cur.get("wind_speed_10m", 0)),
            "code": code,
            "condition": cond,
            "label": label,
            "is_day": bool(cur.get("is_day", 1)),
            "hi": round(d["daily"]["temperature_2m_max"][0]),
            "lo": round(d["daily"]["temperature_2m_min"][0]),
            "hourly": [round(t, 1) for t in temps[start : start + 24]],
            "unit": "F" if units == "imperial" else "C",
        }
