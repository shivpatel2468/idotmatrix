"""Sun & Moon: today's sun times for the panel's location, plus the astronomy the Sky and Space apps share.

Sources (keyless, verified live 2026-09-24):

* sunrise-sunset.org ``/json?lat&lng&date&formatted=0`` — sunrise, sunset, solar noon, day length and the three
  twilights to the second, in UTC.
* Open-Meteo ``/v1/forecast?daily=sunrise,sunset,daylight_duration&timezone=auto`` — the location's UTC offset
  and IANA zone (so times show in the *location's* clock), and a minute-precision fallback for the sun times.

Everything else is computed locally, so the Sky app keeps working offline:

* ``sun_position`` — low-precision solar ephemeris (Astronomical Almanac), good to ~0.01° for 1950–2050.
* ``sun_events`` — sunrise/sunset/noon, golden and blue hour, by sampling the altitude once a minute.
* ``moon_phase`` / ``moon_phase_time`` — illuminated fraction (Meeus ch. 48) and new/full moon instants
  (Meeus ch. 49 with its periodic terms, ~1 min accuracy). No API involved.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import numpy as np

from .base import Provider

SUNRISE_SUNSET = "https://api.sunrise-sunset.org/json"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

SYNODIC = 29.530588861  # mean synodic month, days
DELTA_T = 69.0 / 86400.0  # TT - UTC in days (2020s)
HORIZON = -0.833  # sunrise/sunset altitude (refraction + solar radius)
GOLDEN = 6.0  # golden hour: sun between -4 and +6 degrees
BLUE_HI, BLUE_LO = -4.0, -6.0  # blue hour: sun between -6 and -4 degrees
CIVIL = -6.0


# --------------------------------------------------------------------------- sun
def julian(ts: float) -> float:
    return ts / 86400.0 + 2440587.5


def _sun_radec(n: np.ndarray | float) -> tuple[Any, Any]:
    """Right ascension and declination (radians) for days since J2000."""
    g = np.radians((357.528 + 0.9856003 * n) % 360.0)
    lam = np.radians((280.460 + 0.9856474 * n) % 360.0 + 1.915 * np.sin(g) + 0.020 * np.sin(2 * g))
    eps = np.radians(23.439 - 0.0000004 * n)
    ra = np.arctan2(np.cos(eps) * np.sin(lam), np.cos(lam))
    dec = np.arcsin(np.sin(eps) * np.sin(lam))
    return ra, dec


def _gmst(n: np.ndarray | float) -> Any:
    return np.radians((280.46061837 + 360.98564736629 * n) % 360.0)


def sun_altitudes(ts: np.ndarray, lat: float, lon: float) -> np.ndarray:
    """Solar altitude in degrees for an array of unix times."""
    n = ts / 86400.0 + 2440587.5 - 2451545.0
    ra, dec = _sun_radec(n)
    ha = _gmst(n) + math.radians(lon) - ra
    phi = math.radians(lat)
    s = math.sin(phi) * np.sin(dec) + math.cos(phi) * np.cos(dec) * np.cos(ha)
    return np.degrees(np.arcsin(np.clip(s, -1.0, 1.0)))


def sun_position(ts: float, lat: float, lon: float) -> tuple[float, float]:
    """(altitude, azimuth) of the sun in degrees; azimuth clockwise from north."""
    n = julian(ts) - 2451545.0
    ra, dec = _sun_radec(n)
    ha = float(_gmst(n)) + math.radians(lon) - float(ra)
    phi = math.radians(lat)
    dec = float(dec)
    alt = math.asin(
        max(-1.0, min(1.0, math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(ha)))
    )
    az = math.atan2(math.sin(ha), math.cos(ha) * math.sin(phi) - math.tan(dec) * math.cos(phi))
    return math.degrees(alt), (math.degrees(az) + 180.0) % 360.0


def subsolar_point(ts: float) -> tuple[float, float]:
    """(lat, lon) where the sun is overhead — drives the day/night terminator on world maps."""
    n = julian(ts) - 2451545.0
    ra, dec = _sun_radec(n)
    lon = math.degrees(float(ra) - float(_gmst(n)))
    return math.degrees(float(dec)), (lon + 180.0) % 360.0 - 180.0


def _crossings(ts: np.ndarray, alt: np.ndarray, level: float) -> tuple[list[float], list[float]]:
    """Times the altitude rises through / sets through `level` (linear interpolation)."""
    above = alt >= level
    rises, sets = [], []
    for i in np.nonzero(above[1:] != above[:-1])[0]:
        a0, a1 = float(alt[i]), float(alt[i + 1])
        t = float(ts[i]) + (level - a0) / (a1 - a0) * float(ts[i + 1] - ts[i])
        (rises if a1 > a0 else sets).append(t)
    return rises, sets


def sun_events(day: date, lat: float, lon: float, tz_offset: float) -> dict[str, Any]:
    """Sun times (unix seconds) for the local calendar `day` at a place whose clock is UTC+`tz_offset` s.

    Keys: sunrise, sunset, noon, day_length, civil_begin/end, golden_am/pm (start, end), blue_am/pm (start, end),
    polar ("day" | "night" | None). Any event that doesn't happen (polar regions) is None.
    """
    start = datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() - tz_offset
    ts = start + np.arange(0, 86400 + 60, 60, dtype=np.float64)
    alt = sun_altitudes(ts, lat, lon)
    r0, s0 = _crossings(ts, alt, HORIZON)
    rc, sc = _crossings(ts, alt, CIVIL)
    rg, sg = _crossings(ts, alt, GOLDEN)
    rb, sb = _crossings(ts, alt, BLUE_HI)
    i_noon = int(np.argmax(alt))
    # refine noon with a parabola through the peak samples
    noon = float(ts[i_noon])
    if 0 < i_noon < len(ts) - 1:
        y0, y1, y2 = float(alt[i_noon - 1]), float(alt[i_noon]), float(alt[i_noon + 1])
        den = y0 - 2 * y1 + y2
        if den:
            noon += 30.0 * (y0 - y2) / den
    sunrise = r0[0] if r0 else None
    sunset = next((s for s in s0 if sunrise is None or s > sunrise), s0[0] if s0 else None)
    polar = None
    if sunrise is None and sunset is None:
        polar = "day" if float(alt.min()) > HORIZON else "night"

    def pair(first: float | None, second: float | None) -> tuple[float, float] | None:
        return (first, second) if first is not None and second is not None and second > first else None

    day_len = (
        (sunset - sunrise)
        if sunrise is not None and sunset is not None
        else (86400.0 if polar == "day" else 0.0)
    )
    return {
        "date": day.isoformat(),
        "sunrise": sunrise,
        "sunset": sunset,
        "noon": noon,
        "noon_alt": float(alt[i_noon]),
        "day_length": day_len,
        "civil_begin": rc[0] if rc else None,
        "civil_end": sc[-1] if sc else None,
        # morning: blue (-6 -> -4), then golden (-4 -> +6); evening mirrors it
        "blue_am": pair(rc[0] if rc else None, rb[0] if rb else None),
        "golden_am": pair(rb[0] if rb else None, rg[0] if rg else None),
        "golden_pm": pair(sg[-1] if sg else None, sb[-1] if sb else None),
        "blue_pm": pair(sb[-1] if sb else None, sc[-1] if sc else None),
        "polar": polar,
    }


# -------------------------------------------------------------------------- moon
_NEW_TERMS = (
    (-0.40720, 0, 0, 1, 0),
    (0.17241, 1, 1, 0, 0),
    (0.01608, 0, 0, 2, 0),
    (0.01039, 0, 0, 0, 2),
    (0.00739, 1, -1, 1, 0),
    (-0.00514, 1, 1, 1, 0),
    (0.00208, 2, 2, 0, 0),
    (-0.00111, 0, 0, 1, -2),
    (-0.00057, 0, 0, 1, 2),
    (0.00056, 1, 1, 2, 0),
    (-0.00042, 0, 0, 3, 0),
    (0.00042, 1, 1, 0, 2),
    (0.00038, 1, 1, 0, -2),
    (-0.00024, 1, -1, 2, 0),
)
_FULL_TERMS = (
    (-0.40614, 0, 0, 1, 0),
    (0.17302, 1, 1, 0, 0),
    (0.01614, 0, 0, 2, 0),
    (0.01043, 0, 0, 0, 2),
    (0.00734, 1, -1, 1, 0),
    (-0.00515, 1, 1, 1, 0),
    (0.00209, 2, 2, 0, 0),
    (-0.00111, 0, 0, 1, -2),
    (-0.00057, 0, 0, 1, 2),
    (0.00056, 1, 1, 2, 0),
    (-0.00042, 0, 0, 3, 0),
    (0.00042, 1, 1, 0, 2),
    (0.00038, 1, 1, 0, -2),
    (-0.00024, 1, -1, 2, 0),
)
# (coeff, M mult, M' mult, F mult) shared by both phases
_SMALL_TERMS = (
    (-0.00007, 2, 1, 0),
    (0.00004, 0, 2, -2),
    (0.00004, 3, 0, 0),
    (0.00003, 1, 1, -2),
    (0.00003, 0, 2, 2),
    (-0.00003, 1, 1, 2),
    (0.00003, -1, 1, 2),
    (-0.00002, -1, 1, -2),
    (-0.00002, 1, 3, 0),
    (0.00002, 0, 4, 0),
)


def moon_phase_time(k: float) -> float:
    """Unix time of the lunation `k` (integer = new moon, +0.5 = full moon; k=0 is 2000-01-06). Meeus ch. 49."""
    t = k / 1236.85
    jde = 2451550.09766 + SYNODIC * k + 0.00015437 * t**2 - 0.000000150 * t**3 + 0.00000000073 * t**4
    e = 1 - 0.002516 * t - 0.0000074 * t**2
    m = math.radians(2.5534 + 29.10535670 * k - 0.0000014 * t**2 - 0.00000011 * t**3)
    mp = math.radians(201.5643 + 385.81693528 * k + 0.0107582 * t**2 + 0.00001238 * t**3 - 0.000000058 * t**4)
    f = math.radians(160.7108 + 390.67050284 * k - 0.0016118 * t**2 - 0.00000227 * t**3 + 0.000000011 * t**4)
    om = math.radians(124.7746 - 1.56375588 * k + 0.0020672 * t**2 + 0.00000215 * t**3)
    full = abs(k - math.floor(k) - 0.5) < 1e-6
    corr = 0.0
    for c, ep, mm, mpm, fm in _FULL_TERMS if full else _NEW_TERMS:
        corr += c * e**ep * math.sin(mm * m + mpm * mp + fm * f)
    corr += -0.00017 * math.sin(om)
    for c, mm, mpm, fm in _SMALL_TERMS:
        corr += c * math.sin(mm * m + mpm * mp + fm * f)
    return (jde + corr - DELTA_T - 2440587.5) * 86400.0


def next_phase(ts: float, full: bool) -> float:
    """Unix time of the next new (full=False) or full moon strictly after `ts`."""
    k = math.floor((julian(ts) - 2451550.09766) / SYNODIC) - 1 + (0.5 if full else 0.0)
    while True:
        at = moon_phase_time(k)
        if at > ts:
            return at
        k += 1.0


def moon_phase(ts: float) -> dict[str, Any]:
    """Illuminated fraction, phase angle, age and name at `ts` (Meeus ch. 48, low precision)."""
    t = (julian(ts) + DELTA_T - 2451545.0) / 36525.0
    d = math.radians((297.8501921 + 445267.1114034 * t) % 360.0)
    m = math.radians((357.5291092 + 35999.0502909 * t) % 360.0)
    mp = math.radians((134.9633964 + 477198.8675055 * t) % 360.0)
    i = math.radians(
        180.0
        - math.degrees(d)
        - 6.289 * math.sin(mp)
        + 2.100 * math.sin(m)
        - 1.274 * math.sin(2 * d - mp)
        - 0.658 * math.sin(2 * d)
        - 0.214 * math.sin(2 * mp)
        - 0.110 * math.sin(d)
    )
    illum = (1 + math.cos(i)) / 2
    nxt_new = next_phase(ts, full=False)
    prev_new = next_phase(nxt_new - SYNODIC * 86400 - 3 * 86400, full=False)
    if prev_new >= ts:  # guard against the search landing on the upcoming one
        prev_new = next_phase(prev_new - SYNODIC * 86400 - 3 * 86400, full=False)
    age = (ts - prev_new) / 86400.0
    frac = max(0.0, min(1.0, (ts - prev_new) / (nxt_new - prev_new)))  # 0 new .. 0.5 full .. 1 new
    waxing = frac < 0.5
    return {
        "illumination": illum,
        "phase": frac,
        "phase_angle": math.degrees(i) % 360.0,
        "age_days": age,
        "waxing": waxing,
        "name": phase_name(frac),
        "next_new": nxt_new,
        "next_full": next_phase(ts, full=True),
    }


PHASE_NAMES = (
    "NEW MOON",
    "WAXING CRESCENT",
    "FIRST QUARTER",
    "WAXING GIBBOUS",
    "FULL MOON",
    "WANING GIBBOUS",
    "LAST QUARTER",
    "WANING CRESCENT",
)


def phase_name(frac: float) -> str:
    """Name of the phase for a lunation fraction (0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter)."""
    # principal phases get a +-1 day window (1/29.5 of a lunation) either side
    w = 1.0 / SYNODIC
    for centre, idx in ((0.0, 0), (0.25, 2), (0.5, 4), (0.75, 6), (1.0, 0)):
        if abs(frac - centre) <= w:
            return PHASE_NAMES[idx]
    if frac < 0.25:
        return PHASE_NAMES[1]
    if frac < 0.5:
        return PHASE_NAMES[3]
    if frac < 0.75:
        return PHASE_NAMES[5]
    return PHASE_NAMES[7]


# ---------------------------------------------------------------------- parsing
def _iso(s: Any) -> float | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.year < 1980:  # sunrise-sunset.org answers 1970-01-01T00:00:01 for "doesn't happen"
        return None
    return dt.timestamp()


def parse_sunrise_sunset(d: dict[str, Any]) -> dict[str, Any]:
    """sunrise-sunset.org (formatted=0) -> {sunrise, sunset, noon, day_length, civil_begin, civil_end} (unix)."""
    if d.get("status") != "OK":
        raise ValueError(f"sunrise-sunset: {d.get('status')}")
    r = d.get("results") or {}
    out: dict[str, Any] = {
        "sunrise": _iso(r.get("sunrise")),
        "sunset": _iso(r.get("sunset")),
        "noon": _iso(r.get("solar_noon")),
        "civil_begin": _iso(r.get("civil_twilight_begin")),
        "civil_end": _iso(r.get("civil_twilight_end")),
    }
    try:
        out["day_length"] = float(r.get("day_length"))
    except (TypeError, ValueError):
        out["day_length"] = None
    return out


def parse_open_meteo(d: dict[str, Any]) -> dict[str, Any]:
    """Open-Meteo daily sun block -> {tz_offset, tz, days: {date: {sunrise, sunset, day_length}}}."""
    off = float(d.get("utc_offset_seconds") or 0.0)
    tz = timezone(timedelta(seconds=off))
    daily = d.get("daily") or {}
    days: dict[str, dict[str, Any]] = {}
    for i, day in enumerate(daily.get("time") or []):

        def local(key: str, i: int = i) -> float | None:
            vals = daily.get(key) or []
            if i >= len(vals) or not vals[i]:
                return None
            try:
                return datetime.fromisoformat(vals[i]).replace(tzinfo=tz).timestamp()
            except ValueError:
                return None

        dl = (daily.get("daylight_duration") or [None] * (i + 1))[i]
        days[day] = {
            "sunrise": local("sunrise"),
            "sunset": local("sunset"),
            "day_length": float(dl) if dl is not None else None,
        }
    return {"tz_offset": off, "tz": str(d.get("timezone") or ""), "days": days}


def local_offset(ts: float | None = None) -> float:
    """This machine's UTC offset in seconds (fallback when Open-Meteo can't be reached)."""
    now = datetime.fromtimestamp(ts if ts is not None else time.time()).astimezone()
    off = now.utcoffset()
    return off.total_seconds() if off else 0.0


def local_date(ts: float, tz_offset: float) -> date:
    return datetime.fromtimestamp(ts + tz_offset, tz=UTC).date()


# ---------------------------------------------------------------------- provider
class SkyProvider(Provider[dict[str, Any]]):
    """Sun times for today and tomorrow at the panel's location (APIs once a day, local maths always)."""

    name = "sky"
    interval = 1800.0  # re-check the date / location; the APIs are only hit once per local day
    retry = 120.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._api_day: tuple[str, str] | None = None  # (location key, date) of the last API merge
        self._api: dict[str, Any] = {}
        self._tz: dict[str, Any] | None = None
        self.sources: list[str] = []

    async def _open_meteo(self, lat: float, lon: float) -> dict[str, Any]:
        r = await self.hub.http.get(
            OPEN_METEO,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "sunrise,sunset,daylight_duration",
                "timezone": "auto",
                "forecast_days": 2,
            },
        )
        r.raise_for_status()
        return parse_open_meteo(r.json())

    async def _sunrise_sunset(self, lat: float, lon: float, day: date) -> dict[str, Any]:
        r = await self.hub.http.get(
            SUNRISE_SUNSET, params={"lat": lat, "lng": lon, "date": day.isoformat(), "formatted": 0}
        )
        r.raise_for_status()
        return parse_sunrise_sunset(r.json())

    async def fetch(self) -> dict[str, Any]:
        loc = await self.hub.location()
        lat, lon = float(loc["lat"]), float(loc["lon"])
        now = time.time()
        key = f"{lat:.3f},{lon:.3f}"
        tz_off = self._tz["tz_offset"] if self._tz and self._tz.get("key") == key else None
        today = local_date(now, tz_off if tz_off is not None else local_offset(now))
        if self._api_day != (key, today.isoformat()):
            om, ss = await asyncio.gather(
                self._open_meteo(lat, lon), self._sunrise_sunset(lat, lon, today), return_exceptions=True
            )
            self.sources = []
            self._api = {}
            if not isinstance(om, BaseException):
                self._tz = {"key": key, "tz_offset": om["tz_offset"], "tz": om["tz"]}
                self._api.update({d: dict(v) for d, v in om["days"].items()})
                self.sources.append("open-meteo")
                tz_off = om["tz_offset"]
                today = local_date(now, tz_off)
            if not isinstance(ss, BaseException):
                day = self._api.setdefault(today.isoformat(), {})
                day.update({k: v for k, v in ss.items() if v is not None})
                self.sources.append("sunrise-sunset.org")
            if self.sources:
                self._api_day = (key, today.isoformat())
        if tz_off is None:
            tz_off = local_offset(now)
        days: dict[str, dict[str, Any]] = {}
        for d in (today, today + timedelta(days=1)):
            ev = await asyncio.to_thread(sun_events, d, lat, lon, tz_off)
            api = self._api.get(d.isoformat()) or {}
            for k in ("sunrise", "sunset", "noon", "day_length", "civil_begin", "civil_end"):
                if api.get(k) is not None:
                    ev[k] = api[k]
            days[d.isoformat()] = ev
        return {
            "city": loc.get("city") or "",
            "country": loc.get("country") or "",
            "lat": lat,
            "lon": lon,
            "tz_offset": tz_off,
            "tz": (self._tz or {}).get("tz") or "",
            "today": today.isoformat(),
            "days": days,
            "sources": list(self.sources) or ["local"],
        }
