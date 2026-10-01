"""Live aircraft around you from free, keyless ADS-B aggregators.

Sources are tried in order; one that fails is benched for a while so we never hammer it:

* adsb.lol        ``/v2/point/{lat}/{lon}/{nm}``  (readsb JSON: ``{"ac": [...]}``; needs a descriptive User-Agent)
* airplanes.live  ``/v2/point/{lat}/{lon}/{nm}``  (same schema; blocks some networks with 403)
* OpenSky         ``/api/states/all?lamin…``     (anonymous, rate limited, positional ``states`` arrays)

Routes (origin/destination, airline) come from adsbdb and are cached per callsign, misses included.
Location is shared with the weather provider: studio setting, else IP geolocation.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

from .base import Provider

EARTH_NM = 3440.065  # mean Earth radius in nautical miles
M_TO_FT = 3.28084
MS_TO_KT = 1.943844
MS_TO_FPM = 196.8504
MAX_QUERY_NM = 250.0  # the readsb point APIs cap the radius here
STALE_S = 60.0  # drop positions older than this

READSB_SOURCES: dict[str, str] = {
    "adsb.lol": "https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{r:.0f}",
    "airplanes.live": "https://api.airplanes.live/v2/point/{lat:.4f}/{lon:.4f}/{r:.0f}",
}
OPENSKY = "https://opensky-network.org/api/states/all"
ADSBDB = "https://api.adsbdb.com/v0/callsign/{cs}"
SOURCES = (*READSB_SOURCES, "opensky")


# ------------------------------------------------------------------ geometry
def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine) in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial true bearing from point 1 to point 2, 0..360 clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _aircraft(
    center: tuple[float, float],
    *,
    id: str,
    callsign: str,
    lat: float,
    lon: float,
    alt_ft: float | None,
    speed_kt: float | None,
    track: float | None,
    vrate: float | None,
    type: str,
    reg: str,
    squawk: str,
    ground: bool,
) -> dict[str, Any]:
    return {
        "id": id,
        "callsign": callsign or reg.upper() or id.upper(),
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "alt_ft": 0 if ground else (round(alt_ft) if alt_ft is not None else None),
        "speed_kt": round(speed_kt) if speed_kt is not None else None,
        "track": round(track, 1) if track is not None else None,
        "vrate": round(vrate) if vrate is not None else None,
        "type": type,
        "reg": reg,
        "squawk": squawk,
        "dist_nm": round(distance_nm(center[0], center[1], lat, lon), 2),
        "bearing_deg": round(bearing_deg(center[0], center[1], lat, lon), 1),
        "ground": ground,
    }


def parse_readsb(data: dict[str, Any], center: tuple[float, float]) -> list[dict[str, Any]]:
    """adsb.lol / airplanes.live (readsb/tar1090 JSON) -> normalised aircraft, nearest first."""
    out: list[dict[str, Any]] = []
    for a in data.get("ac") or []:
        if not isinstance(a, dict):
            continue
        lat, lon = _num(a.get("lat")), _num(a.get("lon"))
        if lat is None or lon is None:  # MLAT-less / position-less targets
            lat, lon = (
                _num((a.get("lastPosition") or {}).get("lat")),
                _num((a.get("lastPosition") or {}).get("lon")),
            )
            if lat is None or lon is None:
                continue
        seen = _num(a.get("seen_pos"))
        if seen is not None and seen > STALE_S:
            continue
        alt = a.get("alt_baro")
        ground = alt == "ground"
        alt_ft = None if ground else _num(alt)
        if alt_ft is None and not ground:
            alt_ft = _num(a.get("alt_geom"))
        vr = _num(a.get("baro_rate"))
        if vr is None:
            vr = _num(a.get("geom_rate"))
        track = _num(a.get("track"))
        if track is None:
            track = _num(a.get("true_heading"))
        out.append(
            _aircraft(
                center,
                id=str(a.get("hex") or "").lower().lstrip("~") or f"{lat:.3f},{lon:.3f}",
                callsign=str(a.get("flight") or "").strip().upper(),
                lat=lat,
                lon=lon,
                alt_ft=alt_ft,
                speed_kt=_num(a.get("gs")),
                track=track,
                vrate=vr,
                type=str(a.get("t") or "").upper(),
                reg=str(a.get("r") or "").upper(),
                squawk=str(a.get("squawk") or ""),
                ground=ground,
            )
        )
    out.sort(key=lambda x: x["dist_nm"])
    return out


def parse_opensky(data: dict[str, Any], center: tuple[float, float]) -> list[dict[str, Any]]:
    """OpenSky /states/all positional arrays -> normalised aircraft, nearest first."""
    out: list[dict[str, Any]] = []
    now = _num(data.get("time")) or time.time()
    for s in data.get("states") or []:
        if not isinstance(s, list | tuple) or len(s) < 12:
            continue
        lon, lat = _num(s[5]), _num(s[6])
        if lat is None or lon is None:
            continue
        tpos = _num(s[3])
        if tpos is not None and now - tpos > STALE_S:
            continue
        ground = bool(s[8])
        alt_m = _num(s[7])
        if alt_m is None and len(s) > 13:
            alt_m = _num(s[13])
        vel, vr = _num(s[9]), _num(s[11])
        out.append(
            _aircraft(
                center,
                id=str(s[0] or "").lower(),
                callsign=str(s[1] or "").strip().upper(),
                lat=lat,
                lon=lon,
                alt_ft=alt_m * M_TO_FT if alt_m is not None else None,
                speed_kt=vel * MS_TO_KT if vel is not None else None,
                track=_num(s[10]),
                vrate=vr * MS_TO_FPM if vr is not None else None,
                type="",
                reg="",
                squawk=str(s[14] or "") if len(s) > 14 else "",
                ground=ground,
            )
        )
    out.sort(key=lambda x: x["dist_nm"])
    return out


def _airport(a: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(a, dict):
        return None
    return {
        "iata": a.get("iata_code") or "",
        "icao": a.get("icao_code") or "",
        "name": a.get("name") or "",
        "city": a.get("municipality") or "",
        "country": a.get("country_iso_name") or a.get("country_name") or "",
    }


def parse_route(data: dict[str, Any]) -> dict[str, Any] | None:
    """adsbdb /v0/callsign response -> {callsign, airline, origin, destination} or None."""
    fr = (data.get("response") or {}) if isinstance(data, dict) else {}
    fr = fr.get("flightroute") if isinstance(fr, dict) else None
    if not isinstance(fr, dict):
        return None
    al = fr.get("airline") or {}
    return {
        "callsign": fr.get("callsign") or "",
        "callsign_iata": fr.get("callsign_iata") or "",
        "airline": al.get("name") or "",
        "airline_iata": al.get("iata") or "",
        "airline_icao": al.get("icao") or "",
        "origin": _airport(fr.get("origin")),
        "destination": _airport(fr.get("destination")),
    }


class FlightsProvider(Provider[dict[str, Any]]):
    """Aircraft within `radius_nm` of home, nearest first. Polls every ~8 s while in use."""

    name = "flights"
    interval = 8.0
    retry = 20.0
    ROUTE_HIT_TTL = 6 * 3600.0
    ROUTE_MISS_TTL = 3600.0
    ROUTE_GAP = 1.5  # seconds between adsbdb lookups

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.radius_nm = 30.0
        self._geo: dict[str, Any] | None = None
        self._geo_t = 0.0
        self._bench: dict[str, float] = {}  # source -> monotonic time it may be retried
        self._routes: dict[str, tuple[dict[str, Any] | None, float]] = {}
        self._route_tasks: dict[str, asyncio.Task[dict[str, Any] | None]] = {}
        self._route_lock = asyncio.Lock()
        self._route_last = 0.0

    # -------------------------------------------------------------- config
    def configure(self, radius_nm: float) -> None:
        r = max(1.0, min(MAX_QUERY_NM, float(radius_nm)))
        if abs(r - self.radius_nm) > 0.01:
            grow = r > self.radius_nm
            self.radius_nm = r
            if grow:  # a smaller range is just a filter on data we already have
                self.refresh()

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        """Only when aircraft enter or leave; position updates every 8 s would flood the studio."""
        if old is None:
            return True
        ids_old = {a["id"] for a in old.get("aircraft", [])}
        ids_new = {a["id"] for a in new.get("aircraft", [])}
        return ids_old != ids_new or old.get("source") != new.get("source")

    # ------------------------------------------------------------ location
    async def _location(self) -> dict[str, Any]:
        if hasattr(self.hub, "location"):
            return await self.hub.location()
        weather = self.hub.providers.get("weather")
        if weather is not None and hasattr(weather, "_location"):
            loc = await weather._location()
            return {"city": loc.get("city") or "HOME", "lat": float(loc["lat"]), "lon": float(loc["lon"])}
        loc = self.hub.store.get("location") or {}
        if loc.get("lat") is not None and loc.get("lon") is not None:
            return {"city": loc.get("city") or "HOME", "lat": float(loc["lat"]), "lon": float(loc["lon"])}
        if self._geo and time.time() - self._geo_t < 6 * 3600:
            return self._geo
        r = await self.hub.http.get("http://ip-api.com/json/?fields=status,city,lat,lon")
        r.raise_for_status()
        d = r.json()
        if d.get("status") != "success":
            raise RuntimeError("IP geolocation failed; set a city in Settings")
        self._geo, self._geo_t = {"city": d["city"], "lat": d["lat"], "lon": d["lon"]}, time.time()
        return self._geo

    # --------------------------------------------------------------- fetch
    def _benched(self, src: str) -> bool:
        return time.monotonic() < self._bench.get(src, 0.0)

    def _bench_for(self, src: str, status: int | None) -> None:
        # 403 = blocked (don't retry for an hour), 429 = rate limited, else a short cool-down
        secs = 3600.0 if status in (401, 403) else 180.0 if status == 429 else 60.0
        self._bench[src] = time.monotonic() + secs

    async def _query(self, src: str, lat: float, lon: float, r: float) -> list[dict[str, Any]]:
        if src == "opensky":
            dlat = r / 60.0
            dlon = r / (60.0 * max(0.05, math.cos(math.radians(lat))))
            resp = await self.hub.http.get(
                OPENSKY,
                params={"lamin": lat - dlat, "lomin": lon - dlon, "lamax": lat + dlat, "lomax": lon + dlon},
            )
            resp.raise_for_status()
            return parse_opensky(resp.json(), (lat, lon))
        resp = await self.hub.http.get(READSB_SOURCES[src].format(lat=lat, lon=lon, r=r))
        resp.raise_for_status()
        return parse_readsb(resp.json(), (lat, lon))

    async def fetch(self) -> dict[str, Any]:
        loc = await self._location()
        lat, lon = float(loc["lat"]), float(loc["lon"])
        query_r = min(MAX_QUERY_NM, self.radius_nm * 1.15 + 2)  # a margin so arrivals appear at the rim
        errors: list[str] = []
        candidates = [s for s in SOURCES if not self._benched(s)] or list(SOURCES)
        for src in candidates:
            try:
                aircraft = await self._query(src, lat, lon, query_r)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                self._bench_for(src, status)
                errors.append(f"{src}: {status or type(e).__name__}")
                continue
            return {
                "center": {"lat": lat, "lon": lon, "city": loc.get("city") or "HOME"},
                "radius_nm": query_r,
                "aircraft": aircraft,
                "source": src,
                "updated": time.time(),
            }
        raise RuntimeError("no ADS-B source reachable (" + "; ".join(errors) + ")")

    # --------------------------------------------------------------- routes
    def cached_route(self, callsign: str) -> dict[str, Any] | None:
        """Cached route for `callsign` (never does I/O; safe from render/status)."""
        hit = self._routes.get((callsign or "").strip().upper())
        return hit[0] if hit else None

    def route_known(self, callsign: str) -> bool:
        cs = (callsign or "").strip().upper()
        hit = self._routes.get(cs)
        if not hit:
            return False
        ttl = self.ROUTE_HIT_TTL if hit[0] else self.ROUTE_MISS_TTL
        return time.time() - hit[1] < ttl

    async def route(self, callsign: str) -> dict[str, Any] | None:
        """Origin/destination/airline for a callsign via adsbdb. Cached (misses too); concurrent calls share one request."""
        cs = (callsign or "").strip().upper()
        if not cs or not cs.isalnum() or len(cs) > 8:
            return None
        if self.route_known(cs):
            return self._routes[cs][0]
        task = self._route_tasks.get(cs)
        if task is None or task.done():
            task = asyncio.ensure_future(self._lookup(cs))
            self._route_tasks[cs] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._route_tasks.pop(cs, None)

    async def _lookup(self, cs: str) -> dict[str, Any] | None:
        async with self._route_lock:  # serialise and space out lookups
            if self.route_known(cs):
                return self._routes[cs][0]
            gap = self.ROUTE_GAP - (time.monotonic() - self._route_last)
            if gap > 0:
                await asyncio.sleep(gap)
            self._route_last = time.monotonic()
            try:
                r = await self.hub.http.get(ADSBDB.format(cs=cs))
            except Exception:
                return None  # network trouble: don't cache, try again next time
            if r.status_code == 404:
                result = None
            elif r.status_code >= 400:
                return None
            else:
                try:
                    result = parse_route(r.json())
                except ValueError:
                    result = None
            self._routes[cs] = (result, time.time())
            if len(self._routes) > 500:  # bound the cache
                for k in sorted(self._routes, key=lambda k: self._routes[k][1])[:100]:
                    self._routes.pop(k, None)
            return result
