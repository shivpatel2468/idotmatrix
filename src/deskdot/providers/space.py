"""Space data: upcoming launches, people in orbit, spaceflight news (``space``) and the live ISS (``iss``).

Sources (all keyless, verified live 2026-09-24):

* Launch Library 2 ``/2.2.0/launch/upcoming/?mode=list`` — the free tier allows **15 requests per hour** per IP,
  so each launch list (one per provider filter) is refreshed at most every 15 minutes, cached, and a 429 benches
  the source for the time the API asks for (``Expected available in N seconds``), at least 15 minutes.
* corquaid ``people-in-space.json`` (GitHub Pages, current crews with craft and agency) with open-notify
  ``astros.json`` as the fallback (HTTP only; its crew list is years stale, so it is only used when the first fails).
* Spaceflight News API v4 ``/articles/?limit=10``.
* wheretheiss.at ``/v1/satellites/25544`` (current fix, ~1 req/s allowed; we poll every 5 s while visible) and
  ``/positions?timestamps=…`` (up to 10 instants per call, used once to seed the trailing ground track).

The ISS ground track ahead and the "over you in N min" pass prediction come from a circular-orbit model
fitted to the observed track (inclination 51.64°, orbital rate estimated from the fixes), which is good to a
couple of minutes over the next orbits — no TLE library needed.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import numpy as np

from .base import Provider

LL2_UPCOMING = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/"
PEOPLE_CORQUAID = "https://corquaid.github.io/international-space-station-APIs/JSON/people-in-space.json"
PEOPLE_OPEN_NOTIFY = "http://api.open-notify.org/astros.json"
SNAPI_ARTICLES = "https://api.spaceflightnewsapi.net/v4/articles/"
ISS_NOW = "https://api.wheretheiss.at/v1/satellites/25544"
ISS_POSITIONS = "https://api.wheretheiss.at/v1/satellites/25544/positions"

LAUNCH_TTL = 900.0  # 15 min: 4 requests/hour per filter, inside LL2's 15/hour
PEOPLE_TTL = 6 * 3600.0
NEWS_TTL = 900.0
MAX_FILTERS = 2  # launch lists kept fresh at once (any + one provider = 8 requests/hour)

# provider filter key -> (LL2 lsp name, label)
LAUNCH_FILTERS: dict[str, tuple[str | None, str]] = {
    "any": (None, "Any provider"),
    "spacex": ("SpaceX", "SpaceX"),
    "rocketlab": ("Rocket Lab", "Rocket Lab"),
    "isro": ("Indian Space Research Organization", "ISRO"),
    "nasa": ("National Aeronautics and Space Administration", "NASA"),
    "casc": ("China Aerospace Science and Technology Corporation", "China (CASC)"),
    "roscosmos": ("Russian Federal Space Agency (ROSCOSMOS)", "Roscosmos"),
    "ula": ("United Launch Alliance", "ULA"),
    "blueorigin": ("Blue Origin", "Blue Origin"),
    "arianespace": ("Arianespace", "Arianespace"),
    "mhi": ("Mitsubishi Heavy Industries", "Japan (MHI)"),
}

# LL2 service provider names -> short panel labels
PROVIDER_ABBR: dict[str, str] = {
    "SpaceX": "SPACEX",
    "Rocket Lab": "ROCKETLAB",
    "China Aerospace Science and Technology Corporation": "CASC",
    "Indian Space Research Organization": "ISRO",
    "National Aeronautics and Space Administration": "NASA",
    "Russian Federal Space Agency (ROSCOSMOS)": "ROSCOSMOS",
    "United Launch Alliance": "ULA",
    "Blue Origin": "BLUE ORIGIN",
    "Arianespace": "ARIANE",
    "Mitsubishi Heavy Industries": "MHI",
    "Japan Aerospace Exploration Agency": "JAXA",
    "Korea Aerospace Research Institute": "KARI",
    "European Space Agency": "ESA",
    "Galactic Energy": "GALACTIC",
    "LandSpace": "LANDSPACE",
    "Firefly Aerospace": "FIREFLY",
    "Northrop Grumman Space Systems": "NORTHROP",
    "China Aerospace Science and Industry Corporation": "CASIC",
    "Relativity Space": "RELATIVITY",
    "iSpace": "ISPACE",
    "CAS Space": "CAS SPACE",
    "Space Pioneer": "SPACEPIONEER",
    "Orienspace": "ORIENSPACE",
    "Gilmour Space Technologies": "GILMOUR",
}

# LL2 status abbreviations -> panel status
STATUS: dict[str, str] = {
    "Go": "GO",
    "TBD": "TBD",
    "TBC": "TBC",
    "Hold": "HOLD",
    "In Flight": "FLIGHT",
    "Success": "SUCCESS",
    "Failure": "FAILURE",
    "Partial Failure": "PARTIAL",
}

# ------------------------------------------------------------------------ text
_REPL = {
    "€": "EUR",
    "£": "GBP",
    "–": "-",
    "—": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "×": "X",
    "°": "°",
    "…": "…",
    "&amp;": "&",
}


def ascii_text(s: Any) -> str:
    """Fold a headline / name to what the bitmap fonts can draw (accents stripped, dashes and quotes plain)."""
    text = str(s or "")
    for a, b in _REPL.items():
        text = text.replace(a, b)
    out = []
    for ch in unicodedata.normalize("NFKD", text):
        if ch in "°…" or (32 <= ord(ch) < 127):
            out.append(ch)
        elif unicodedata.category(ch) == "Mn":
            continue
        elif ch.isspace():
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def provider_abbr(name: str) -> str:
    if name in PROVIDER_ABBR:
        return PROVIDER_ABBR[name]
    words = [w for w in re.split(r"[\s\-]+", ascii_text(name)) if w]
    short = ascii_text(name).upper()
    if len(short) <= 10:
        return short
    caps = "".join(w[0] for w in words if w[0].isupper())
    return caps if len(caps) >= 2 else short[:10]


def _ts(s: Any) -> float | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# --------------------------------------------------------------------- parsers
def parse_launches(d: dict[str, Any]) -> list[dict[str, Any]]:
    """LL2 ``launch/upcoming/?mode=list`` -> normalised launches sorted by NET."""
    out: list[dict[str, Any]] = []
    for r in d.get("results") or []:
        if not isinstance(r, dict):
            continue
        net = _ts(r.get("net"))
        if net is None:
            continue
        name = ascii_text(r.get("name"))
        rocket, _, mission = name.partition(" | ")
        lsp = str(r.get("lsp_name") or "")
        status = (r.get("status") or {}).get("abbrev") or ""
        prec = (r.get("net_precision") or {}).get("abbrev") or ""
        out.append(
            {
                "id": str(r.get("id") or r.get("slug") or name),
                "name": name,
                "rocket": rocket.strip() or name,
                "mission": ascii_text(r.get("mission")) or mission.strip(),
                "mission_type": ascii_text(r.get("mission_type")),
                "provider": ascii_text(lsp),
                "provider_abbr": provider_abbr(lsp) if lsp else "",
                "net": net,
                "precision": str(prec).upper(),
                "status": STATUS.get(status, str(status).upper()[:7] or "TBD"),
                "status_name": ascii_text((r.get("status") or {}).get("name")),
                "pad": ascii_text(r.get("pad")),
                "location": ascii_text(r.get("location")),
                "window_start": _ts(r.get("window_start")),
                "window_end": _ts(r.get("window_end")),
            }
        )
    out.sort(key=lambda x: x["net"])
    return out


def _station(p: dict[str, Any]) -> str:
    if p.get("iss") is True:
        return "ISS"
    craft = str(p.get("spacecraft") or p.get("craft") or "")
    if p.get("agency") == "CMSA" or "shenzhou" in craft.lower() or "tiangong" in craft.lower():
        return "TIANGONG"
    return ascii_text(craft).upper() or "SPACE"


def parse_people_corquaid(d: dict[str, Any]) -> dict[str, Any]:
    people = [
        {
            "name": ascii_text(p.get("name")),
            "craft": ascii_text(p.get("spacecraft")),
            "station": _station(p),
            "agency": ascii_text(p.get("agency")),
            "country": str(p.get("flag_code") or "").upper(),
            "position": ascii_text(p.get("position")),
            "launched": p.get("launched"),
        }
        for p in d.get("people") or []
        if isinstance(p, dict) and p.get("name")
    ]
    if not people:
        raise ValueError("people-in-space: empty")
    return {
        "number": int(d.get("number") or len(people)),
        "people": people,
        "expedition": d.get("iss_expedition"),
        "source": "corquaid",
    }


def parse_people_open_notify(d: dict[str, Any]) -> dict[str, Any]:
    if d.get("message") != "success":
        raise ValueError("open-notify: not success")
    people = [
        {
            "name": ascii_text(p.get("name")),
            "craft": ascii_text(p.get("craft")),
            "station": _station({"craft": p.get("craft"), "iss": p.get("craft") == "ISS"}),
            "agency": "",
            "country": "",
            "position": "",
            "launched": None,
        }
        for p in d.get("people") or []
        if isinstance(p, dict) and p.get("name")
    ]
    return {
        "number": int(d.get("number") or len(people)),
        "people": people,
        "expedition": None,
        "source": "open-notify",
    }


def parse_news(d: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for a in d.get("results") or []:
        if not isinstance(a, dict) or not a.get("title"):
            continue
        out.append(
            {
                "id": a.get("id"),
                "title": ascii_text(a.get("title")),
                "site": ascii_text(a.get("news_site")),
                "published": _ts(a.get("published_at")),
                "url": str(a.get("url") or ""),
            }
        )
    return out


def parse_iss(d: dict[str, Any]) -> dict[str, Any]:
    lat, lon = float(d["latitude"]), float(d["longitude"])
    return {
        "lat": lat,
        "lon": lon,
        "alt_km": float(d.get("altitude") or 0.0),
        "vel_kmh": float(d.get("velocity") or 0.0),
        "visibility": str(d.get("visibility") or ""),
        "footprint_km": float(d.get("footprint") or 0.0),
        "ts": float(d.get("timestamp") or time.time()),
        "solar": (float(d.get("solar_lat") or 0.0), float(d.get("solar_lon") or 0.0)),
    }


def throttle_seconds(r: Any) -> float:
    """How long LL2 wants us to wait after a 429 (header or the 'Expected available in N seconds' detail)."""
    try:
        ra = float(r.headers.get("Retry-After"))
        if ra > 0:
            return ra
    except (TypeError, ValueError):
        pass
    try:
        m = re.search(r"(\d+)\s*second", str(r.json().get("detail", "")))
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return LAUNCH_TTL


# ------------------------------------------------------------------ orbit model
EARTH_R = 6371.0
MU = 398600.4418
OMEGA_E = 7.2921159e-5  # Earth rotation, rad/s
ISS_INC = math.radians(51.64)
NODE_RATE = math.radians(-5.0) / 86400.0  # J2 nodal regression for the ISS, rad/s


def haversine_km(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> Any:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def elevation_deg(ground_km: Any, alt_km: float) -> Any:
    """Elevation of a satellite at `alt_km` seen from `ground_km` away along the surface."""
    th = np.asarray(ground_km) / EARTH_R
    return np.degrees(np.arctan2(np.cos(th) - EARTH_R / (EARTH_R + alt_km), np.sin(th)))


def _arg_lat(lat: float, ascending: bool) -> float:
    s = max(-1.0, min(1.0, math.sin(math.radians(lat)) / math.sin(ISS_INC)))
    u = math.asin(s)
    return u if ascending else math.pi - u


class Orbit:
    """Circular-orbit ground-track model anchored at one fix."""

    def __init__(
        self, ts: float, lat: float, lon: float, ascending: bool, alt_km: float, rate: float | None
    ) -> None:
        self.t0 = ts
        self.u0 = _arg_lat(lat, ascending)
        self.node = math.radians(lon) - math.atan2(math.cos(ISS_INC) * math.sin(self.u0), math.cos(self.u0))
        self.n = rate or 2 * math.pi / (2 * math.pi * math.sqrt((6378.137 + alt_km) ** 3 / MU))
        self.alt_km = alt_km

    def at(self, ts: Any) -> tuple[np.ndarray, np.ndarray]:
        dt = np.asarray(ts, dtype=np.float64) - self.t0
        u = self.u0 + self.n * dt
        lat = np.degrees(np.arcsin(np.sin(ISS_INC) * np.sin(u)))
        lon = self.node + np.arctan2(np.cos(ISS_INC) * np.sin(u), np.cos(u)) - (OMEGA_E - NODE_RATE) * dt
        lon = (np.degrees(lon) + 180.0) % 360.0 - 180.0
        return lat, lon


def fit_rate(track: list[tuple[float, float, float]]) -> tuple[bool, float | None]:
    """(ascending now?, argument-of-latitude rate rad/s) from a time-ordered track of (ts, lat, lon)."""
    if len(track) < 2:
        return True, None
    ascending = track[-1][1] >= track[-2][1]
    if len(track) < 4 or track[-1][0] - track[0][0] < 600:
        return ascending, None
    lats = np.array([p[1] for p in track])
    ts = np.array([p[0] for p in track])
    asc = np.gradient(lats, ts) >= 0
    u = np.array([_arg_lat(la, a) for la, a in zip(lats, asc, strict=True)])
    u = np.unwrap(u)
    rate = float(np.polyfit(ts - ts[0], u, 1)[0])
    # sanity: the ISS goes round in 88-96 minutes
    if not (2 * math.pi / (96 * 60) < rate < 2 * math.pi / (88 * 60)):
        return ascending, None
    return ascending, rate


def next_pass(
    orbit: Orbit, now: float, lat: float, lon: float, horizon_s: float = 12 * 3600, min_elev: float = 10.0
) -> dict[str, Any] | None:
    """First pass above `min_elev` degrees for an observer at (lat, lon) within `horizon_s` seconds."""
    ts = now + np.arange(0.0, horizon_s, 15.0)
    la, lo = orbit.at(ts)
    el = elevation_deg(haversine_km(lat, lon, la, lo), orbit.alt_km)
    up = el >= min_elev
    if not up.any():
        return None
    i0 = int(np.argmax(up))
    i1 = i0
    while i1 + 1 < len(up) and up[i1 + 1]:
        i1 += 1
    seg = el[i0 : i1 + 1]
    return {
        "start": float(ts[i0]),
        "end": float(ts[i1]),
        "max_elev": float(seg.max()),
        "peak": float(ts[i0 + int(np.argmax(seg))]),
        "now": i0 == 0,
    }


# ------------------------------------------------------------------- providers
class SpaceProvider(Provider[dict[str, Any]]):
    """Launches (per provider filter), people in space and news; each part has its own refresh budget."""

    name = "space"
    interval = 60.0  # wake-up rate; every part has its own TTL
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.parts: set[str] = {"launch", "people", "news"}
        self.filters: list[str] = ["any"]  # most recently wanted last
        self._due: dict[str, float] = {}  # part key -> next fetch time
        self._fails: dict[str, int] = {}

    # ------------------------------------------------------------ interface
    def want(self, parts: Iterable[str] = ("launch", "people", "news"), launch_filter: str = "any") -> None:
        new_parts = set(parts) - self.parts
        self.parts |= set(parts)
        key = launch_filter if launch_filter in LAUNCH_FILTERS else "any"
        fresh = key not in self.filters
        if key in self.filters:
            self.filters.remove(key)
        self.filters.append(key)
        del self.filters[:-MAX_FILTERS]
        if new_parts or fresh:
            self.refresh()

    def launches(self, key: str = "any") -> list[dict[str, Any]] | None:
        v = (self.value or {}).get("launches", {}).get(key)
        return None if v is None else v["items"]

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        def stamp(d: dict[str, Any] | None) -> Any:
            d = d or {}
            return (
                {k: v.get("updated") for k, v in (d.get("launches") or {}).items()},
                (d.get("people") or {}).get("updated"),
                (d.get("news") or {}).get("updated"),
            )

        return stamp(old) != stamp(new)

    # ------------------------------------------------------------ fetching
    async def _launches(self, key: str) -> list[dict[str, Any]]:
        lsp = LAUNCH_FILTERS[key][0]
        params: dict[str, Any] = {"limit": 12, "mode": "list"}
        if lsp:
            params["lsp__name"] = lsp
        r = await self.hub.http.get(LL2_UPCOMING, params=params)
        if r.status_code == 429:
            wait = max(LAUNCH_TTL, throttle_seconds(r))
            for k in LAUNCH_FILTERS:  # the budget is per IP: bench every launch list
                self._due[f"launch:{k}"] = max(self._due.get(f"launch:{k}", 0.0), time.time() + wait)
            raise RuntimeError(f"Launch Library rate limit; retry in {wait / 60:.0f} min")
        r.raise_for_status()
        return parse_launches(r.json())

    async def _people(self) -> dict[str, Any]:
        try:
            r = await self.hub.http.get(PEOPLE_CORQUAID)
            r.raise_for_status()
            return parse_people_corquaid(r.json())
        except Exception:
            r = await self.hub.http.get(PEOPLE_OPEN_NOTIFY)
            r.raise_for_status()
            return parse_people_open_notify(r.json())

    async def _news(self) -> list[dict[str, Any]]:
        r = await self.hub.http.get(SNAPI_ARTICLES, params={"limit": 10})
        r.raise_for_status()
        return parse_news(r.json())

    async def fetch(self) -> dict[str, Any]:
        now = time.time()
        val: dict[str, Any] = {
            "launches": dict((self.value or {}).get("launches") or {}),
            "people": (self.value or {}).get("people"),
            "news": (self.value or {}).get("news"),
            "errors": dict((self.value or {}).get("errors") or {}),
        }
        jobs: dict[str, Any] = {}
        if "launch" in self.parts:
            for k in self.filters:
                if self._due.get(f"launch:{k}", 0.0) <= now:
                    jobs[f"launch:{k}"] = self._launches(k)
        if "people" in self.parts and self._due.get("people", 0.0) <= now:
            jobs["people"] = self._people()
        if "news" in self.parts and self._due.get("news", 0.0) <= now:
            jobs["news"] = self._news()
        if not jobs:
            return val
        results = await asyncio.gather(*jobs.values(), return_exceptions=True)
        ok = 0
        for key, res in zip(jobs, results, strict=True):
            ttl = LAUNCH_TTL if key.startswith("launch") else PEOPLE_TTL if key == "people" else NEWS_TTL
            if isinstance(res, BaseException):
                n = self._fails[key] = self._fails.get(key, 0) + 1
                backoff = min(3600.0, 60.0 * 2 ** (n - 1))
                self._due[key] = max(self._due.get(key, 0.0), now + backoff)
                val["errors"][key] = f"{type(res).__name__}: {res}"[:160]
                continue
            ok += 1
            self._fails.pop(key, None)
            self._due[key] = now + ttl
            val["errors"].pop(key, None)
            if key.startswith("launch:"):
                val["launches"][key.split(":", 1)[1]] = {"items": res, "updated": now}
            else:
                val[key] = {"items" if key == "news" else "data": res, "updated": now}
        if not ok and self.value is None:
            raise RuntimeError("; ".join(val["errors"].values())[:200])
        return val


class IssProvider(Provider[dict[str, Any]]):
    """The ISS right now, its recent ground track, the modelled track ahead and the next pass over you."""

    name = "iss"
    interval = 5.0
    retry = 15.0
    TRACK_S = 95 * 60.0  # keep one orbit of history
    TRACK_STEP = 30.0  # thin the history to one point per 30 s
    AHEAD_S = 95 * 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.track: list[tuple[float, float, float]] = []
        self._seeded = False
        self._pass_t = 0.0
        self._pass: dict[str, Any] | None = None
        self._user: dict[str, Any] | None = None
        self.fast = True  # apps showing the map set this; otherwise poll once a minute

    def next_interval(self) -> float:
        return self.interval if self.fast else 60.0

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        # 5 s polling: tell the studio about the first fix and then once a minute, not every poll
        return old is None or int(old["ts"] // 60) != int(new["ts"] // 60)

    async def _seed(self, now: float) -> None:
        stamps = [int(now - self.TRACK_S + i * self.TRACK_S / 10) for i in range(10)]
        r = await self.hub.http.get(
            ISS_POSITIONS, params={"timestamps": ",".join(map(str, stamps)), "units": "kilometers"}
        )
        r.raise_for_status()
        for p in r.json():
            self._add(float(p["timestamp"]), float(p["latitude"]), float(p["longitude"]))

    def _add(self, ts: float, lat: float, lon: float) -> None:
        if self.track and ts <= self.track[-1][0]:
            return
        if len(self.track) >= 2 and ts - self.track[-2][0] < self.TRACK_STEP:
            self.track[-1] = (ts, lat, lon)  # thin: keep moving the newest point
        else:
            self.track.append((ts, lat, lon))
        cut = ts - self.TRACK_S
        while self.track and self.track[0][0] < cut:
            self.track.pop(0)

    async def fetch(self) -> dict[str, Any]:
        now = time.time()
        if not self._seeded:
            self._seeded = True
            try:
                await self._seed(now)
            except Exception:
                pass  # the trail simply grows from now on
        r = await self.hub.http.get(ISS_NOW, params={"units": "kilometers"})
        if r.status_code == 429:
            raise RuntimeError("wheretheiss.at rate limit")
        r.raise_for_status()
        fix = parse_iss(r.json())
        self._add(fix["ts"], fix["lat"], fix["lon"])
        ascending, rate = fit_rate(self.track)
        orbit = Orbit(fix["ts"], fix["lat"], fix["lon"], ascending, fix["alt_km"], rate)
        ahead_t = fix["ts"] + np.arange(60.0, self.AHEAD_S, 60.0)
        la, lo = orbit.at(ahead_t)
        if self._user is None or now - self._pass_t > 600:
            try:
                self._user = await self.hub.location()
            except Exception:
                self._user = self._user or None
        user = self._user
        dist = None
        if user:
            dist = float(haversine_km(user["lat"], user["lon"], fix["lat"], fix["lon"]))
            if now - self._pass_t > 60 or self._pass is None or self._pass["end"] < now:
                self._pass = await asyncio.to_thread(next_pass, orbit, now, user["lat"], user["lon"])
                self._pass_t = now
        return {
            **fix,
            "ascending": ascending,
            "period_min": (2 * math.pi / rate / 60.0) if rate else None,
            "track": [(round(t, 1), round(a, 3), round(b, 3)) for t, a, b in self.track],
            "ahead": [
                (float(t), round(float(a), 3), round(float(b), 3))
                for t, a, b in zip(ahead_t, la, lo, strict=True)
            ],
            "user": {"city": user.get("city"), "lat": user["lat"], "lon": user["lon"]} if user else None,
            "dist_km": dist,
            "elev_deg": float(elevation_deg(dist, fix["alt_km"])) if dist is not None else None,
            "next_pass": self._pass,
            "updated": now,
        }
