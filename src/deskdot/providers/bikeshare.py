"""Bike-share docks near you from CityBikes (``api.citybik.es/v2``, keyless, CORS; 700+ systems worldwide).

The network is picked once a day: the one whose centre is nearest the panel's location (``hub.location()``), or
the network id set in the app. Stations are then sorted by distance, or filtered by a name fragment.

``value = {"network": {id, name, city}, "stations": [{name, bikes, ebikes, docks, dist_m, lat, lon}] (nearest
first, up to 12), "far": bool (the nearest network is > 25 km away), "updated"}``.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any

from .base import Endpoint, Provider
from .daily import clean_text

API = "https://api.citybik.es/v2/networks"
EARTH_M = 6_371_000.0
MAX_STATIONS = 12
FAR_KM = 25.0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(min(1.0, math.sqrt(a)))


def parse_networks(d: Any) -> list[dict[str, Any]]:
    out = []
    for n in (d or {}).get("networks") or [] if isinstance(d, dict) else []:
        loc = n.get("location") or {}
        try:
            out.append(
                {
                    "id": str(n["id"]),
                    "name": str(n.get("name") or n["id"]),
                    "city": str(loc.get("city") or ""),
                    "lat": float(loc["latitude"]),
                    "lon": float(loc["longitude"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def nearest_network(
    nets: list[dict[str, Any]], lat: float, lon: float
) -> tuple[dict[str, Any], float] | None:
    best = min(nets, key=lambda n: distance_m(lat, lon, n["lat"], n["lon"]), default=None)
    return (best, distance_m(lat, lon, best["lat"], best["lon"])) if best else None


def short_station(name: str) -> str:
    """'300073 - Prince of Wales Drive, Battersea Park' -> 'PRINCE OF WALES DRIVE' (ids and areas dropped)."""
    s = re.sub(r"^\s*[\w-]*\d[\w-]*\s*[-:]\s*", "", name or "")
    s = s.split(",")[0]
    return clean_text(s, 40) or clean_text(name, 40)


def parse_stations(d: Any, lat: float, lon: float, match: str = "") -> list[dict[str, Any]]:
    net = d.get("network") if isinstance(d, dict) else None
    if not isinstance(net, dict) or "stations" not in net:
        raise ValueError("citybikes: unexpected shape")
    want = match.strip().upper()
    out = []
    for s in net.get("stations") or []:
        try:
            slat, slon = float(s["latitude"]), float(s["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        extra = s.get("extra") or {}
        if extra.get("installed") is False or extra.get("renting") in (0, False):
            continue
        name = short_station(str(s.get("name") or ""))
        if want and want not in name and want not in str(s.get("name") or "").upper():
            continue
        out.append(
            {
                "name": name,
                "bikes": int(s.get("free_bikes") or 0),
                "ebikes": int(extra.get("ebikes") or 0),
                "docks": int(s.get("empty_slots") or 0) if s.get("empty_slots") is not None else None,
                "dist_m": round(distance_m(lat, lon, slat, slon)),
                "lat": slat,
                "lon": slon,
            }
        )
    out.sort(key=lambda s: s["dist_m"])
    return out[:MAX_STATIONS]


class BikeShareProvider(Provider[dict[str, Any]]):
    name = "bikeshare"
    endpoints = (
        Endpoint("CityBikes networks", API + "?fields=id,name,location", check=parse_networks),
        Endpoint(
            "CityBikes stations",
            API + "/santander-cycles",
            check=lambda d: parse_stations(d, 51.5074, -0.1278),
            note="~0.3 MB for big systems",
        ),
    )
    interval = 90.0
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.network_id = ""
        self.match = ""
        self._nets: tuple[float, list[dict[str, Any]]] | None = None

    def want(self, network: str = "", match: str = "") -> None:
        net = re.sub(r"[^a-z0-9-]", "", network.strip().lower())
        if (net, match) != (self.network_id, self.match):
            self.network_id, self.match = net, match
            self.refresh()

    async def _networks(self) -> list[dict[str, Any]]:
        if self._nets and time.time() - self._nets[0] < 86400:
            return self._nets[1]
        r = await self.hub.http.get(API, params={"fields": "id,name,location"}, timeout=20.0)
        r.raise_for_status()
        nets = parse_networks(r.json())
        self._nets = (time.time(), nets)
        return nets

    async def fetch(self) -> dict[str, Any]:
        loc = await self.hub.location()
        lat, lon = float(loc["lat"]), float(loc["lon"])
        nets = await self._networks()
        net = next((n for n in nets if n["id"] == self.network_id), None) if self.network_id else None
        far = False
        if net is None:
            hit = nearest_network(nets, lat, lon)
            if hit is None:
                raise RuntimeError("no bike-share networks")
            net, dist = hit
            far = dist > FAR_KM * 1000
        r = await self.hub.http.get(f"{API}/{net['id']}", params={"fields": "stations"}, timeout=20.0)
        r.raise_for_status()
        return {
            "network": {
                "id": net["id"],
                "name": clean_text(net["name"], 30),
                "city": clean_text(net["city"], 30),
            },
            "stations": parse_stations(r.json(), lat, lon, self.match),
            "far": far,
            "updated": time.time(),
        }
