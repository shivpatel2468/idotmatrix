"""Day / Night — the world with the live terminator, city lights on the night side, you, the sun and the moon.

Layouts: ``world`` (the whole 32×16 world with your day/night state above and the next sunrise/sunset below),
``half`` (a full-bleed 64×32 map window, half the planet), ``globe`` (an orthographic globe centred on you).

The terminator is computed per pixel from the subsolar point (low-precision solar ephemeris), with a
civil-to-astronomical twilight band; the sublunar point comes from a short lunar series (Meeus ch. 47, main
terms, ~0.5°). Your location comes from the `sky` provider; without it the map still renders. The scene only
changes when the terminator moves by a pixel, so it is a baked clip (city lights twinkle natively) that re-bakes
every 20-45 minutes.
"""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import PALETTE, Frame, mix, scale, to_rgb
from ..gfx.color import RGB
from ..gfx.worldmap import land
from ..providers.sky import julian, subsolar_point, sun_position

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
SUN_C: RGB = (255, 214, 0)
MOON_C: RGB = (220, 225, 255)
HOME_C: RGB = PALETTE["ember"]

# major metro areas (lat, lon) whose lights show on the night side
CITIES: tuple[tuple[float, float], ...] = (
    (40.7, -74.0), (34.1, -118.2), (41.9, -87.6), (29.8, -95.4), (33.7, -84.4), (25.8, -80.2), (47.6, -122.3),
    (37.8, -122.4), (32.8, -96.8), (39.0, -77.0), (42.4, -71.1), (43.7, -79.4), (45.5, -73.6), (49.3, -123.1),
    (19.4, -99.1), (20.7, -103.3), (25.7, -100.3), (4.7, -74.1), (-12.0, -77.0), (-33.4, -70.6), (-23.5, -46.6),
    (-22.9, -43.2), (-34.6, -58.4), (10.5, -66.9), (23.1, -82.4), (51.5, -0.1), (48.9, 2.4), (52.5, 13.4),
    (40.4, -3.7), (41.9, 12.5), (45.5, 9.2), (52.4, 4.9), (50.1, 8.7), (48.2, 16.4), (52.2, 21.0), (55.8, 37.6),
    (59.9, 30.3), (41.0, 29.0), (37.98, 23.7), (30.0, 31.2), (6.5, 3.4), (-1.3, 36.8), (-26.2, 28.0), (-33.9, 18.4),
    (33.6, -7.6), (36.8, 3.1), (24.7, 46.7), (25.2, 55.3), (35.7, 51.4), (33.3, 44.4), (24.9, 67.0), (31.5, 74.3),
    (28.6, 77.2), (19.1, 72.9), (13.1, 80.3), (12.97, 77.6), (22.6, 88.4), (17.4, 78.5), (23.8, 90.4),
    (13.8, 100.5), (21.0, 105.8), (10.8, 106.7), (1.35, 103.8), (3.1, 101.7), (-6.2, 106.8), (14.6, 121.0),
    (22.3, 114.2), (23.1, 113.3), (31.2, 121.5), (39.9, 116.4), (30.6, 114.3), (30.7, 104.1), (34.3, 108.9),
    (37.6, 127.0), (35.7, 139.7), (34.7, 135.5), (25.0, 121.5), (-33.9, 151.2), (-37.8, 145.0), (-27.5, 153.0),
    (-31.95, 115.9), (-36.8, 174.8), (61.2, -149.9), (21.3, -157.9), (64.1, -21.9), (60.2, 24.9), (59.3, 18.1),
)  # fmt: skip


def moon_radec(ts: float) -> tuple[float, float]:
    """Geocentric right ascension and declination of the moon (radians), main terms of Meeus ch. 47."""
    t = (julian(ts) - 2451545.0) / 36525.0
    lp = math.radians(218.316 + 481267.881 * t)
    mp = math.radians(134.963 + 477198.867 * t)
    f = math.radians(93.272 + 483202.018 * t)
    d = math.radians(297.850 + 445267.111 * t)
    m = math.radians(357.529 + 35999.050 * t)
    lon = lp + math.radians(
        6.289 * math.sin(mp)
        - 1.274 * math.sin(2 * d - mp)
        + 0.658 * math.sin(2 * d)
        + 0.214 * math.sin(2 * mp)
        - 0.186 * math.sin(m)
        - 0.114 * math.sin(2 * f)
    )
    lat = math.radians(
        5.128 * math.sin(f)
        + 0.281 * math.sin(mp + f)
        - 0.278 * math.sin(f - mp)
        - 0.173 * math.sin(f - 2 * d)
    )
    eps = math.radians(23.4393 - 0.0130 * t)
    ra = math.atan2(math.sin(lon) * math.cos(eps) - math.tan(lat) * math.sin(eps), math.cos(lon))
    dec = math.asin(math.sin(lat) * math.cos(eps) + math.cos(lat) * math.sin(eps) * math.sin(lon))
    return ra, dec


def sublunar_point(ts: float) -> tuple[float, float]:
    ra, dec = moon_radec(ts)
    n = julian(ts) - 2451545.0
    gmst = math.radians((280.46061837 + 360.98564736629 * n) % 360.0)
    lon = math.degrees(ra - gmst)
    return math.degrees(dec), (lon + 180.0) % 360.0 - 180.0


def solar_altitude(lat: np.ndarray, lon: np.ndarray, sub_lat: float, sub_lon: float) -> np.ndarray:
    """Sun altitude in degrees over a lat/lon grid (degrees), from the subsolar point."""
    la, lo = np.radians(lat), np.radians(lon)
    d, s = math.radians(sub_lat), math.radians(sub_lon)
    c = np.sin(la) * math.sin(d) + np.cos(la) * math.cos(d) * np.cos(lo - s)
    return np.degrees(np.arcsin(np.clip(c, -1, 1)))


# --------------------------------------------------------------------------------------- projections
class Projection:
    """Pixel grid <-> lat/lon for one layout. `lat`/`lon`/`inside` are (32, 32) arrays; `land` is a bool mask."""

    def __init__(self, layout: str, lat0: float, lon0: float) -> None:
        self.layout, self.lat0, self.lon0 = layout, lat0, lon0
        yy, xx = np.mgrid[0:32, 0:32].astype(np.float64)
        if layout == "world":
            self.top = 8
            self.shift = round(lon0 / 360 * 32)
            gy = yy - self.top
            self.inside = (gy >= 0) & (gy < 16)
            self.lat = 90 - (gy + 0.5) * 180 / 16
            self.lon = ((xx + self.shift + 0.5) * 360 / 32) % 360 - 180
            m = np.roll(land(32, 16), -self.shift, axis=1)
            self.land = np.zeros((32, 32), bool)
            self.land[self.top : self.top + 16] = m
        elif layout == "half":
            self.ox = round((lon0 + 180) / 360 * 64) - 16
            cols = (self.ox + xx) % 64
            self.inside = np.ones((32, 32), bool)
            self.lat = 90 - (yy + 0.5) * 180 / 32
            self.lon = (cols + 0.5) * 360 / 64 - 180
            self.land = land(64, 32)[yy.astype(int), cols.astype(int)]
        else:  # orthographic globe, radius 15.5 px
            u = (xx - 15.5) / 15.5
            v = (15.5 - yy) / 15.5
            rho = np.hypot(u, v)
            self.inside = rho <= 1.0
            self.rho = rho
            c = np.arcsin(np.clip(rho, 0, 1))
            p0 = math.radians(lat0)
            with np.errstate(invalid="ignore", divide="ignore"):
                lat = np.arcsin(
                    np.cos(c) * math.sin(p0) + np.where(rho > 0, v * np.sin(c) * math.cos(p0) / rho, 0)
                )
                lon = math.radians(lon0) + np.arctan2(
                    u * np.sin(c), rho * np.cos(c) * math.cos(p0) - v * np.sin(c) * math.sin(p0)
                )
            self.lat = np.degrees(lat)
            self.lon = (np.degrees(lon) + 180) % 360 - 180
            mask = land(128, 64)
            my = np.clip(((90 - self.lat) / 180 * 64).astype(int), 0, 63)
            mx = np.clip(((self.lon + 180) / 360 * 128).astype(int), 0, 127)
            self.land = mask[my, mx] & self.inside

    def to_px(self, lat: float, lon: float) -> tuple[int, int] | None:
        if self.layout == "world":
            x = ((lon + 180) / 360 * 32 - self.shift) % 32
            return int(x), self.top + min(15, int((90 - lat) / 180 * 16))
        if self.layout == "half":
            x = ((lon + 180) / 360 * 64 - self.ox) % 64
            if x >= 32:
                return None
            return int(x), min(31, int((90 - lat) / 180 * 32))
        p, lam = math.radians(lat), math.radians(lon - self.lon0)
        p0 = math.radians(self.lat0)
        cosc = math.sin(p0) * math.sin(p) + math.cos(p0) * math.cos(p) * math.cos(lam)
        if cosc < 0:
            return None
        u = math.cos(p) * math.sin(lam)
        v = math.cos(p0) * math.sin(p) - math.sin(p0) * math.cos(p) * math.cos(lam)
        return round(15.5 + u * 15.5 - 0.5), round(15.5 - v * 15.5 - 0.5)


@lru_cache(maxsize=8)
def projection(layout: str, lat0: float, lon0: float) -> Projection:
    return Projection(layout, lat0, lon0)


class DayNightSettings(AppSettings):
    layout: str = Choice(
        "world",
        {"world": "World + times", "half": "Half world", "globe": "Globe"},
        title="Layout",
        group="Map",
    )
    center_on_home: bool = Field(True, title="Centre on my location", json_schema_extra={"group": "Map"})
    center_lon: int = Field(
        0, ge=-180, le=180, title="Centre longitude", description="Used when not centred on your location.",
        json_schema_extra={"group": "Map"},
    )  # fmt: skip
    show_cities: bool = Field(True, title="City lights", json_schema_extra={"group": "Markers"})
    show_home: bool = Field(True, title="My location", json_schema_extra={"group": "Markers"})
    show_sun: bool = Field(True, title="Sun marker", json_schema_extra={"group": "Markers"})
    show_moon: bool = Field(True, title="Moon marker", json_schema_extra={"group": "Markers"})
    hour24: bool = Field(True, title="24-hour times", json_schema_extra={"group": "Markers"})
    day_land: Color = Field("#1e9a3c", title="Land (day)", json_schema_extra={"group": "Colours"})
    day_sea: Color = Field("#002a78", title="Sea (day)", json_schema_extra={"group": "Colours"})
    night_land: Color = Field("#1c2a4a", title="Land (night)", json_schema_extra={"group": "Colours"})
    lights: Color = Field("#ffbe50", title="City lights", json_schema_extra={"group": "Colours"})


@register
class DayNight(App):
    id = "daynight"
    name = "Day & Night"
    description = (
        "World map with the live day/night terminator, twinkling city lights, you, the sun and the moon."
    )
    icon = "earth"
    category = "time"
    Settings = DayNightSettings
    fps = 4.0
    uses = ("sky",)
    clip_seconds = 4.0
    clip_fps = 8.0
    clip_colors = 64

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._scene: tuple[str, dict[str, Any]] | None = None
        self._frozen: float | None = None  # the instant a clip is baked for

    def kind(self) -> Kind:
        return "clip"

    # ------------------------------------------------------------------ data
    def _sky(self) -> dict[str, Any] | None:
        try:
            return self.ctx.provider("sky").value
        except KeyError:
            return None

    def _home(self) -> tuple[float, float] | None:
        d = self._sky()
        if d and d.get("lat") is not None:
            return float(d["lat"]), float(d["lon"])
        return None

    def _proj(self) -> Projection:
        s = self.settings
        home = self._home()
        lon0 = float(home[1]) if (s.center_on_home and home) else float(s.center_lon)
        lat0 = 0.0
        if s.layout == "globe":
            lat0 = max(-60.0, min(60.0, home[0])) if (s.center_on_home and home) else 20.0
        return projection(s.layout, round(lat0, 1), round(lon0, 1))

    def _quanta(self, now: float) -> tuple[Any, ...]:
        """What the static scene depends on, quantised to the map's resolution."""
        s = self.settings
        sub_lat, sub_lon = subsolar_point(now)
        step = {"world": 360 / 32, "half": 360 / 64, "globe": 5.0}[s.layout]
        moon = sublunar_point(now) if s.show_moon else (0.0, 0.0)
        return (round(sub_lon / step), round(sub_lat), round(moon[0] / step), round(moon[1] / step))

    def _caption(self, now: float) -> tuple[str, RGB, str, RGB]:
        """(top label, colour, bottom label, colour) for the world layout."""
        d = self._sky()
        home = self._home()
        if d is None or home is None:
            return "WORLD", MUTE, datetime.fromtimestamp(now, tz=UTC).strftime("UTC %H"), scale(MUTE, 0.7)
        alt, _ = sun_position(now, home[0], home[1])
        if alt > 0:
            top, col = "DAY", SUN_C
        elif alt > -6:
            top, col = "DUSK" if datetime.fromtimestamp(now).hour >= 12 else "DAWN", PALETTE["rose"]
        else:
            top, col = "NIGHT", PALETTE["sky"]
        nxt: tuple[float, str] | None = None
        for day in sorted(d.get("days", {})):
            ev = d["days"][day]
            for key, sym in (("sunrise", "▲"), ("sunset", "▼")):
                ts = ev.get(key)
                if ts and ts > now and (nxt is None or ts < nxt[0]):
                    nxt = (ts, sym)
        if nxt is None:
            return top, col, "", MUTE
        lt = datetime.fromtimestamp(nxt[0] + float(d.get("tz_offset", 0)), tz=UTC)
        hm = lt.strftime("%H:%M") if self.settings.hour24 else f"{lt.hour % 12 or 12}:{lt.minute:02d}"
        return top, col, f"{nxt[1]}{hm}", (PALETTE["amber"] if nxt[1] == "▲" else PALETTE["rose"])

    def clip_key(self) -> str:
        now = time.time()
        home = self._home()
        cap = self._caption(now) if self.settings.layout == "world" else ()
        return json.dumps(
            [
                self.settings.model_dump(mode="json"),
                self._quanta(now),
                home and [round(v, 2) for v in home],
                cap,
            ]
        )

    def clip_frames(self) -> Clip:
        self._frozen = time.time()
        try:
            return super().clip_frames()
        finally:
            self._frozen = None

    # ---------------------------------------------------------------- render
    def _static(self, now: float) -> dict[str, Any]:
        key = json.dumps([self.settings.model_dump(mode="json"), self._quanta(now), self._home()])
        if self._scene and self._scene[0] == key:
            return self._scene[1]
        s = self.settings
        pr = self._proj()
        sub_lat, sub_lon = subsolar_point(now)
        alt = solar_altitude(pr.lat, pr.lon, sub_lat, sub_lon)
        k = np.clip((alt + 12.0) / 12.0, 0.0, 1.0) ** 1.4  # 0 = night (sun < -12°), 1 = day
        day_land = np.array(to_rgb(s.day_land), np.float32)
        day_sea = np.array(to_rgb(s.day_sea), np.float32)
        night_land = np.array(to_rgb(s.night_land), np.float32)
        night_sea = np.array((0, 0, 6), np.float32)
        lk = k[..., None]
        landc = night_land * (1 - lk) + day_land * lk
        seac = night_sea * (1 - lk) + day_sea * lk
        img = np.where(pr.land[..., None], landc, seac)
        # a warm band where the sun is on the horizon
        band = np.clip(1 - np.abs(alt + 1.5) / 3.5, 0, 1)[..., None] * 0.5
        img = img * (1 - band) + np.array((255, 100, 20), np.float32) * band * 0.75
        img = np.where(pr.inside[..., None], img, 0)
        if s.layout == "globe":  # thin atmosphere rim
            rim = (pr.rho > 1.0) & (pr.rho < 1.08)
            img[rim] = (30, 90, 170)
        lights: list[tuple[int, int, float]] = []
        if s.show_cities:
            seen: set[tuple[int, int]] = set()
            for i, (clat, clon) in enumerate(CITIES):
                p = pr.to_px(clat, clon)
                if (
                    p is None
                    or p in seen
                    or not (0 <= p[0] < 32 and 0 <= p[1] < 32)
                    or not pr.inside[p[1], p[0]]
                ):
                    continue
                a = float(solar_altitude(np.array(clat), np.array(clon), sub_lat, sub_lon))
                if a < -4:
                    seen.add(p)
                    lights.append((p[0], p[1], (i * 0.618) % 1.0))
        markers: list[tuple[str, tuple[int, int]]] = []
        if s.show_sun:
            p = pr.to_px(sub_lat, sub_lon)
            if p:
                markers.append(("sun", p))
        if s.show_moon:
            ml, mo = sublunar_point(now)
            p = pr.to_px(ml, mo)
            if p:
                markers.append(("moon", p))
        home = self._home()
        home_px = pr.to_px(*home) if (home and s.show_home) else None
        scene = {
            "img": img.clip(0, 255).astype(np.uint8),
            "lights": lights,
            "markers": markers,
            "home": home_px,
        }
        self._scene = (key, scene)
        return scene

    def render(self, f: Frame, t: float) -> None:
        now = self._frozen or time.time()
        sc = self._static(now)
        f.px[:] = sc["img"]
        ph = (t / self.clip_seconds) % 1.0
        lights = to_rgb(self.settings.lights)
        for x, y, seed in sc["lights"]:
            tw = 0.55 + 0.45 * math.sin(math.tau * (ph * (1 + int(seed * 3)) + seed))
            f.set(x, y, scale(lights, tw))
        for kind, (x, y) in sc["markers"]:
            if kind == "sun":
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    f.blend(x + dx, y + dy, SUN_C, 0.45)
                f.set(x, y, mix(SUN_C, WHITE, 0.4))
            else:
                f.set(x, y, MOON_C)
        if sc["home"] is not None:
            x, y = sc["home"]
            pulse = 0.5 + 0.5 * math.cos(ph * math.tau * 2)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                f.blend(x + dx, y + dy, HOME_C, 0.25 + 0.5 * pulse)
            f.set(x, y, mix(HOME_C, WHITE, 0.3 + 0.5 * pulse))
        if self.settings.layout == "world":
            top, tcol, bottom, bcol = self._caption(now)
            f.text_center(1, top, tcol)
            if bottom:
                f.text_center(26, bottom, bcol)

    def status(self) -> dict[str, Any]:
        now = time.time()
        sub = subsolar_point(now)
        moon = sublunar_point(now)
        out: dict[str, Any] = {
            "subsolar": {"lat": round(sub[0], 2), "lon": round(sub[1], 2)},
            "sublunar": {"lat": round(moon[0], 2), "lon": round(moon[1], 2)},
        }
        home = self._home()
        if home:
            alt, az = sun_position(now, *home)
            out["home"] = {
                "lat": home[0],
                "lon": home[1],
                "sun_altitude": round(alt, 1),
                "sun_azimuth": round(az, 1),
            }
        return out
