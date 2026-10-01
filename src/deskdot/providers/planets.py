"""Naked-eye planets (Mercury…Saturn) for the panel's location, computed locally — no API, no library.

Positions come from the JPL "Keplerian Elements for Approximate Positions of the Major Planets" (E. M. Standish,
Table 1, valid 1800–2050; ~1' for the outer planets, a few ' for Mercury): solve Kepler's equation for each
planet and the Earth–Moon barycentre, take the difference, rotate to equatorial J2000 (precession to date is
~0.4° and ignored), then to altitude/azimuth for the location. Rise and set times come from sampling the
altitude over the next 26 hours; "tonight" is the dark window (sun below -8°) that is under way or next.

The provider recomputes every 5 minutes; the app redraws from RA/Dec so the dome stays live between updates.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

import numpy as np

from .base import Provider
from .sky import local_offset, sun_altitudes

J2000 = 2451545.0
OBLIQUITY = math.radians(23.43928)
HORIZON = -0.5667  # refraction at the horizon (planets are points)

# a, e, I, L, long.peri, long.node  and their rates per Julian century (JPL Table 1, 1800-2050)
ELEMENTS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    "mercury": (
        (0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
        (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081),
    ),
    "venus": (
        (0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
        (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418),
    ),
    "earth": (
        (1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
        (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0),
    ),
    "mars": (
        (1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
        (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343),
    ),
    "jupiter": (
        (5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
        (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106),
    ),
    "saturn": (
        (9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
        (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794),
    ),
}
PLANETS = ("mercury", "venus", "mars", "jupiter", "saturn")
# minimum solar elongation to be seen in twilight/dark (degrees)
MIN_ELONGATION = {"mercury": 12.0, "venus": 8.0, "mars": 12.0, "jupiter": 12.0, "saturn": 12.0}


def heliocentric(name: str, jd: float) -> np.ndarray:
    """Heliocentric ecliptic J2000 position (au) of a planet (or 'earth' = Earth–Moon barycentre)."""
    base, rate = ELEMENTS[name]
    t = (jd - J2000) / 36525.0
    a, e, inc, mean_long, peri, node = (b + r * t for b, r in zip(base, rate, strict=True))
    w = peri - node
    m = math.radians((mean_long - peri + 180.0) % 360.0 - 180.0)
    ecc = m + e * math.sin(m)
    for _ in range(12):
        d = (ecc - e * math.sin(ecc) - m) / (1 - e * math.cos(ecc))
        ecc -= d
        if abs(d) < 1e-10:
            break
    xp = a * (math.cos(ecc) - e)
    yp = a * math.sqrt(1 - e * e) * math.sin(ecc)
    w, node, inc = math.radians(w), math.radians(node), math.radians(inc)
    cw, sw, cn, sn, ci, si = (
        math.cos(w),
        math.sin(w),
        math.cos(node),
        math.sin(node),
        math.cos(inc),
        math.sin(inc),
    )
    x = (cw * cn - sw * sn * ci) * xp + (-sw * cn - cw * sn * ci) * yp
    y = (cw * sn + sw * cn * ci) * xp + (-sw * sn + cw * cn * ci) * yp
    z = (sw * si) * xp + (cw * si) * yp
    return np.array((x, y, z))


def _to_equatorial(v: np.ndarray) -> tuple[float, float]:
    x, y, z = v
    ye = y * math.cos(OBLIQUITY) - z * math.sin(OBLIQUITY)
    ze = y * math.sin(OBLIQUITY) + z * math.cos(OBLIQUITY)
    return math.atan2(ye, x) % math.tau, math.atan2(ze, math.hypot(x, ye))


def geocentric(name: str, ts: float) -> dict[str, float]:
    """RA/Dec (radians), distance (au) and solar elongation (degrees) of a planet at unix time `ts`."""
    jd = ts / 86400.0 + 2440587.5 + 69.0 / 86400.0  # TT
    earth = heliocentric("earth", jd)
    p = heliocentric(name, jd) - earth
    ra, dec = _to_equatorial(p)
    sun = -earth
    cosang = float(np.dot(p, sun) / (np.linalg.norm(p) * np.linalg.norm(sun)))
    return {
        "ra": ra,
        "dec": dec,
        "dist": float(np.linalg.norm(p)),
        "elong": math.degrees(math.acos(max(-1.0, min(1.0, cosang)))),
    }


def gmst(ts: float | np.ndarray) -> Any:
    n = np.asarray(ts) / 86400.0 + 2440587.5 - J2000
    return np.radians((280.46061837 + 360.98564736629 * n) % 360.0)


def altaz(ra: float, dec: float, ts: float | np.ndarray, lat: float, lon: float) -> tuple[Any, Any]:
    """Altitude and azimuth (degrees, azimuth clockwise from north) for RA/Dec in radians."""
    h = gmst(ts) + math.radians(lon) - ra
    phi = math.radians(lat)
    s = math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * np.cos(h)
    alt = np.degrees(np.arcsin(np.clip(s, -1, 1)))
    az = np.degrees(np.arctan2(np.sin(h), np.cos(h) * math.sin(phi) - math.tan(dec) * math.cos(phi))) + 180.0
    return alt, az % 360.0


def _crossings(ts: np.ndarray, alt: np.ndarray, level: float) -> tuple[list[float], list[float]]:
    above = alt >= level
    rises, sets = [], []
    for i in np.nonzero(above[1:] != above[:-1])[0]:
        a0, a1 = float(alt[i]), float(alt[i + 1])
        t = float(ts[i]) + (level - a0) / (a1 - a0) * float(ts[i + 1] - ts[i])
        (rises if a1 > a0 else sets).append(t)
    return rises, sets


def dark_window(now: float, lat: float, lon: float, level: float = -8.0) -> tuple[float, float] | None:
    """The night (sun below `level`) that contains `now`, else the next one; None in polar day."""
    ts = now - 12 * 3600 + np.arange(0, 48 * 3600, 300, dtype=np.float64)
    alt = sun_altitudes(ts, lat, lon)
    dark = alt < level
    if not dark.any():
        return None
    i_now = int(np.searchsorted(ts, now))
    # find the dark run containing now, else the first run starting after now
    runs = []
    start = None
    for i, d in enumerate(dark):
        if d and start is None:
            start = i
        if not d and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(dark) - 1))
    for a, b in runs:
        if a <= i_now <= b or a > i_now:
            return float(ts[a]), float(ts[b])
    return None


def compute(now: float, lat: float, lon: float) -> dict[str, Any]:
    """Everything the Planets app draws, for the location at `now`."""
    sun_now = float(sun_altitudes(np.array([now]), lat, lon)[0])
    night = dark_window(now, lat, lon)
    grid = now + np.arange(0, 26 * 3600, 300, dtype=np.float64)
    planets = []
    for name in PLANETS:
        g0 = geocentric(name, now)
        g1 = geocentric(name, now + 86400)
        dra = (g1["ra"] - g0["ra"] + math.pi) % math.tau - math.pi
        frac = (grid - now) / 86400.0
        ra_t = g0["ra"] + dra * frac
        dec_t = g0["dec"] + (g1["dec"] - g0["dec"]) * frac
        h = gmst(grid) + math.radians(lon) - ra_t
        phi = math.radians(lat)
        alt = np.degrees(
            np.arcsin(np.clip(np.sin(phi) * np.sin(dec_t) + np.cos(phi) * np.cos(dec_t) * np.cos(h), -1, 1))
        )
        rises, sets = _crossings(grid, alt, HORIZON)
        alt_now, az_now = altaz(g0["ra"], g0["dec"], now, lat, lon)
        best = None
        if night is not None:
            sel = (grid >= night[0]) & (grid <= night[1])
            if sel.any():
                i = int(np.argmax(np.where(sel, alt, -99)))
                best = {"ts": float(grid[i]), "alt": float(alt[i])}
        elong_ok = g0["elong"] >= MIN_ELONGATION[name]
        planets.append(
            {
                "id": name,
                "ra": g0["ra"],
                "dec": g0["dec"],
                "dra": dra,
                "ddec": g1["dec"] - g0["dec"],
                "dist": round(g0["dist"], 4),
                "elong": round(g0["elong"], 1),
                "alt": round(float(alt_now), 2),
                "az": round(float(az_now), 2),
                "rise": rises[0] if rises else None,
                "set": sets[0] if sets else None,
                "circumpolar": bool(not rises and not sets and alt.min() > HORIZON),
                "never": bool(not rises and not sets and alt.max() < HORIZON),
                "visible_now": bool(alt_now > 0 and sun_now < -6 and elong_ok),
                "tonight": best,
                "visible_tonight": bool(best is not None and best["alt"] > 5 and elong_ok),
            }
        )
    return {
        "computed": now,
        "lat": lat,
        "lon": lon,
        "sun_alt": round(sun_now, 2),
        "night": list(night) if night else None,
        "planets": planets,
    }


class PlanetsProvider(Provider[dict[str, Any]]):
    name = "planets"
    interval = 300.0
    retry = 60.0

    async def fetch(self) -> dict[str, Any]:
        loc = await self.hub.location()
        lat, lon = float(loc["lat"]), float(loc["lon"])
        data = await asyncio.to_thread(compute, time.time(), lat, lon)
        sky = self.hub.providers.get("sky")
        tz = sky.value.get("tz_offset") if sky is not None and sky.value else None
        data.update(
            {"city": loc.get("city") or "", "tz_offset": float(tz) if tz is not None else local_offset()}
        )
        return data
