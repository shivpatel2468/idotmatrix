"""Sun & Moon — today's sun path with the sun where it is now, a shaded moon at tonight's phase, and the times.

Layouts: ``arc`` (sky that changes colour with the sun's altitude, the day's arc, stars after dark), ``moon``
(a large shaded disc at the current phase with maria, illumination and the next full/new moon), ``times``
(sunrise, sunset, solar noon, day length, golden and blue hour, moon) and ``combined``.

Sun times come from the `sky` provider (sunrise-sunset.org + Open-Meteo, local maths as fallback); the sun's
current position and the moon are computed locally every frame, so the moon screen works with no data at all.
"""

from __future__ import annotations

import itertools
import math
import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, measure, mix, scale
from ..gfx.color import RGB
from ..gfx.frame import Sprite
from ..providers.sky import moon_phase, sun_position
from ._kit import loading, offline

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
DIM: RGB = PALETTE["dim"]
RISE_C: RGB = PALETTE["amber"]
SET_C: RGB = PALETTE["rose"]
GOLD: RGB = PALETTE["gold"]
BLUE: RGB = PALETTE["sky"]
MOON_C = np.array((255, 236, 196), np.float32)

# sky gradient keyframes by solar altitude: (alt, top colour, horizon colour)
SKY_KEYS: list[tuple[float, RGB, RGB]] = [
    (-18.0, (0, 0, 4), (0, 0, 8)),
    (-9.0, (0, 1, 10), (2, 6, 30)),
    (-5.0, (0, 6, 34), (22, 34, 110)),
    (-1.0, (18, 12, 60), (190, 70, 30)),
    (3.0, (14, 22, 80), (230, 110, 24)),
    (8.0, (0, 26, 80), (60, 110, 160)),
    (30.0, (0, 30, 96), (26, 96, 180)),
]

_rng = np.random.default_rng(11)
STARS = [
    (int(x), int(y), float(p))
    for x, y, p in zip(_rng.integers(1, 31, 30), _rng.integers(0, 22, 30), _rng.random(30), strict=True)
]

# maria as soft ellipses in disc coordinates (u right, v down, seen from the northern hemisphere):
# (u, v, rx, ry, darkness)
MARIA = (
    (-0.25, -0.38, 0.27, 0.22, 0.42),  # Imbrium
    (0.16, -0.33, 0.15, 0.14, 0.40),  # Serenitatis
    (0.30, -0.04, 0.20, 0.16, 0.40),  # Tranquillitatis
    (0.66, -0.26, 0.10, 0.09, 0.45),  # Crisium
    (-0.58, -0.05, 0.22, 0.40, 0.35),  # Procellarum
    (-0.22, 0.32, 0.17, 0.12, 0.32),  # Nubium
    (0.55, 0.18, 0.11, 0.13, 0.34),  # Fecunditatis
    (0.32, 0.30, 0.10, 0.09, 0.30),  # Nectaris
)


def sky_colors(alt: float) -> tuple[RGB, RGB]:
    """(top, horizon) sky colours for a solar altitude, interpolated between the keyframes."""
    if alt <= SKY_KEYS[0][0]:
        return SKY_KEYS[0][1], SKY_KEYS[0][2]
    for (a0, t0, h0), (a1, t1, h1) in itertools.pairwise(SKY_KEYS):
        if alt <= a1:
            k = (alt - a0) / (a1 - a0)
            return mix(t0, t1, k), mix(h0, h1, k)
    return SKY_KEYS[-1][1], SKY_KEYS[-1][2]


@lru_cache(maxsize=16)
def moon_disc(radius: float, phase_q: int, south: bool, size: int) -> tuple[np.ndarray, np.ndarray]:
    """(rgb uint8 (size, size, 3), alpha (size, size)) of the moon at lunation fraction phase_q/1000.

    Supersampled 4×4 per pixel: phase terminator, soft maria, a touch of limb darkening and earthshine.
    """
    frac = phase_q / 1000.0
    ang = 2 * math.pi * frac  # 0 new, pi full
    # sun direction in the viewer frame (x right, z towards us); waxing = lit on the right (north)
    sx, sz = math.sin(ang), -math.cos(ang)
    ss = 4
    c = size / 2.0
    o = (np.arange(size * ss) + 0.5) / ss - c
    u = o[None, :] / radius
    v = o[:, None] / radius
    r2 = u * u + v * v
    inside = r2 <= 1.0
    z = np.sqrt(np.clip(1.0 - r2, 0.0, 1.0))
    lit = u * sx + z * sz
    light = np.clip((lit + 0.04) / 0.12, 0.0, 1.0)
    albedo = np.ones_like(r2)
    for mu, mv, rx, ry, dark in MARIA:
        d = ((u - mu) / rx) ** 2 + ((v - mv) / ry) ** 2
        albedo -= dark * np.clip(1.2 - d, 0.0, 1.0) / 1.2
    tycho = ((u + 0.1) ** 2 + (v - 0.66) ** 2) < 0.004
    albedo = np.where(tycho, 1.15, albedo)
    limb = 0.72 + 0.28 * z**0.5
    b = (light * albedo * limb + (1 - light) * 0.045) * inside
    # box-filter the supersamples
    b = b.reshape(size, ss, size, ss).mean(axis=(1, 3))
    a = inside.reshape(size, ss, size, ss).mean(axis=(1, 3))
    if south:  # seen from the southern hemisphere the moon is upside down
        b, a = b[::-1, ::-1], a[::-1, ::-1]
    rgb = np.clip(b[..., None] * MOON_C, 0, 255).astype(np.uint8)
    return rgb, a


@lru_cache(maxsize=8)
def _arc(
    rise: float, sset: float, peak: float, lat: float, lon: float, x0: int, x1: int, apex: int, horizon: int
) -> list[tuple[int, int, float]]:
    pts = []
    for x in range(x0, x1 + 1):
        ts = rise + (sset - rise) * (x - x0) / max(1, x1 - x0)
        a, _ = sun_position(ts, lat, lon)
        pts.append((x, horizon - round(max(0.0, a) / peak * (horizon - apex)), ts))
    return pts


def _hm(ts: float | None, off: float, h24: bool) -> str:
    if ts is None:
        return "--:--"
    d = datetime.fromtimestamp(ts + off, tz=UTC)
    if h24:
        return d.strftime("%H:%M")
    return f"{d.hour % 12 or 12}:{d.minute:02d}{'A' if d.hour < 12 else 'P'}"


def dur_text(sec: float) -> str:
    """'12H06' / '42M' for day lengths and countdowns."""
    m = max(0, int(sec // 60))
    h, m = divmod(m, 60)
    return f"{h}H{m:02d}" if h else f"{m}M"


def days_text(sec: float) -> str:
    d, rem = divmod(max(0.0, sec), 86400)
    if d >= 1:
        return f"{int(d)}D {int(rem // 3600)}H"
    return dur_text(sec)


def _icon(rows: list[str], col: RGB) -> Sprite:
    return Sprite.parse(rows, {"#": col})


ICONS: dict[str, Sprite] = {
    "rise": _icon(["..#..", ".###.", "#.#.#", "..#..", "#####"], RISE_C),
    "set": _icon(["..#..", "#.#.#", ".###.", "..#..", "#####"], SET_C),
    "noon": _icon(["..#..", ".###.", "#####", ".###.", "..#.."], GOLD),
    "day": _icon(["#####", ".###.", "..#..", ".###.", "#####"], WHITE),
    "golden": _icon([".....", ".###.", "#####", "#####", "#.#.#"], GOLD),
    "blue": _icon([".....", ".###.", "#####", "#####", "#.#.#"], BLUE),
    "moon": _icon([".###.", "##...", "##...", "##...", ".###."], (230, 220, 190)),
    "full": _icon([".###.", "#####", "#####", "#####", ".###."], (255, 236, 196)),
    "new": _icon([".###.", "#...#", "#...#", "#...#", ".###."], BLUE),
}


def tight_text(f: Frame, y: int, text: str, col: RGB) -> None:
    """Centre `text`; if it is a pixel or two too wide, close the gap after wide glyphs (N, M, W) to fit."""
    w = measure(text)
    if w <= 30:
        f.text_center(y, text, col)
        return
    squeeze = {i for i, ch in enumerate(text[:-1]) if ch in "NMW"}
    need = w - 30
    drop = set(sorted(squeeze)[:need])
    width = w - len(drop)
    x = (32 - width) // 2
    for i, ch in enumerate(text):
        x = f.text(x, y, ch, col) + (0 if i in drop else 1)


class SkySettings(AppSettings):
    layout: str = Choice(
        "arc",
        {"arc": "Sun arc", "moon": "Moon", "times": "Sun times", "combined": "Combined"},
        title="Layout",
        group="Layout",
    )
    hour24: bool = Field(True, title="24-hour times", json_schema_extra={"group": "Layout"})
    stars: bool = Field(True, title="Stars after dark", json_schema_extra={"group": "Layout"})
    page_seconds: int = Field(5, ge=2, le=30, title="Seconds per page", json_schema_extra={"group": "Layout"})
    hemisphere: str = Choice(
        "auto",
        {"auto": "From location", "north": "Northern", "south": "Southern"},
        title="Moon orientation",
        group="Moon",
    )


@register
class Sky(App):
    id = "sky"
    name = "Sun & Moon"
    description = "Sunrise, sunset and the sun's path today, golden and blue hour, and the moon's phase."
    icon = "sunrise"
    category = "time"
    Settings = SkySettings
    fps = 2.0
    uses = ("sky",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._moon: tuple[float, dict[str, Any]] | None = None

    # ------------------------------------------------------------------ data
    def _prov(self) -> Any:
        try:
            return self.ctx.provider("sky")
        except KeyError:
            return None

    def _data(self) -> tuple[Any, dict[str, Any] | None]:
        p = self._prov()
        return p, (p.value if p is not None else None)

    def moon(self, now: float) -> dict[str, Any]:
        if self._moon is None or abs(now - self._moon[0]) > 60:
            self._moon = (now, moon_phase(now))
        return self._moon[1]

    @staticmethod
    def day_for(d: dict[str, Any], now: float) -> dict[str, Any]:
        """Today's events in the location's calendar (tomorrow's once the provider's day has rolled over)."""
        today = datetime.fromtimestamp(now + d["tz_offset"], tz=UTC).date().isoformat()
        days = d["days"]
        if today in days:
            return days[today]
        return days[sorted(days)[-1]]

    @staticmethod
    def next_rise(d: dict[str, Any], now: float) -> float | None:
        for key in sorted(d["days"]):
            r = d["days"][key].get("sunrise")
            if r is not None and r > now:
                return r
        return None

    def _south(self, d: dict[str, Any] | None) -> bool:
        h = self.settings.hemisphere
        if h == "auto":
            return bool(d and d.get("lat", 0) < 0)
        return h == "south"

    # ---------------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        now = time.time()
        p, d = self._data()
        layout = self.settings.layout
        if layout == "moon":
            self._render_moon(f, t, now, d)
            return
        if d is None:
            if p is None or p.error:
                offline(f, "SUN", "OFFLINE")
            else:
                loading(f, t, "SUN", GOLD)
            return
        getattr(self, f"_render_{layout}")(f, t, now, d)

    # ------------------------------------------------------------------- arc
    def _sky(self, f: Frame, alt: float, top: int, horizon: int, t: float) -> None:
        c_top, c_hor = sky_colors(alt)
        f.gradient_v(c_top, c_hor, top, horizon - top)
        if self.settings.stars and alt < -4:
            k = min(1.0, (-4 - alt) / 8)
            for x, y, ph in STARS:
                if top <= y < horizon - 2:
                    tw = 0.55 + 0.45 * math.sin(t * 1.3 + ph * 20)
                    f.blend(x, y, WHITE, k * tw * (0.35 + 0.5 * ph))

    def _arc_points(
        self, day: dict[str, Any], d: dict[str, Any], x0: int, x1: int, apex: int, horizon: int
    ) -> list[tuple[int, int, float]]:
        """(x, y, ts) along the day's sun path from sunrise to sunset, scaled so noon sits at `apex`."""
        rise, sset = day.get("sunrise"), day.get("sunset")
        if rise is None or sset is None:
            return []
        peak = max(1.0, day.get("noon_alt") or 45.0)
        return _arc(rise, sset, peak, d["lat"], d["lon"], x0, x1, apex, horizon)

    def _draw_arc(self, f: Frame, pts: list[tuple[int, int, float]], now: float) -> None:
        """The day's path as one unbroken line: steep steps near the horizon are filled in vertically."""
        prev: int | None = None
        for x, y, ts in pts:
            a = 0.55 if ts <= now else 0.28
            ys: range | list[int] = [y]
            if prev is not None and abs(prev - y) > 1:  # fill the gap in this column
                ys = range(y, prev) if y < prev else range(prev + 1, y + 1)
            for yy in ys:
                f.blend(x, yy, GOLD, a)
            prev = y

    def _sun_at(self, pts: list[tuple[int, int, float]], now: float) -> tuple[int, int] | None:
        if not pts or not (pts[0][2] <= now <= pts[-1][2]):
            return None
        best = min(pts, key=lambda p: abs(p[2] - now))
        return best[0], best[1]

    def _draw_sun(self, f: Frame, x: int, y: int, alt: float, r: int, t: float) -> None:
        # low, the sun is pale and bright so it stands out from the orange horizon band (an orange disc on an
        # orange sky vanished); high up it turns gold against the blue
        core = mix((255, 236, 170), GOLD, min(1.0, max(0.0, (alt - 3) / 7)))
        for dx in range(-r - 2, r + 3):
            for dy in range(-r - 2, r + 3):
                dist = math.hypot(dx, dy)
                if r < dist <= r + 2:
                    f.blend(x + dx, y + dy, core, 0.28 * (1 - (dist - r) / 2.2))
        f.circle(x, y, r, core)
        f.set(x, y, mix(core, WHITE, 0.6))

    def _draw_moon_small(self, f: Frame, cx: int, cy: int, size: int, now: float, south: bool) -> None:
        m = self.moon(now)
        rgb, a = moon_disc(size / 2 - 0.25, round(m["phase"] * 1000), south, size)
        self._blit_disc(f, rgb, a, cx - size // 2, cy - size // 2)

    @staticmethod
    def _blit_disc(f: Frame, rgb: np.ndarray, a: np.ndarray, x0: int, y0: int) -> None:
        """Alpha-blend a (fully on-panel) disc image at (x0, y0)."""
        h, w = a.shape
        region = f.px[y0 : y0 + h, x0 : x0 + w].astype(np.float32)
        al = np.clip(a * 1.25, 0.0, 1.0)[..., None]
        f.px[y0 : y0 + h, x0 : x0 + w] = (region * (1 - al) + rgb.astype(np.float32) * al).astype(np.uint8)

    def _render_arc(self, f: Frame, t: float, now: float, d: dict[str, Any]) -> None:
        s = self.settings
        day = self.day_for(d, now)
        alt, _ = sun_position(now, d["lat"], d["lon"])
        horizon = 19
        self._sky(f, alt, 0, horizon, t)
        pts = self._arc_points(day, d, 3, 28, 8, horizon)
        self._draw_arc(f, pts, now)
        # the horizon goes down before the sun, so a rising/setting sun sits on it instead of vanishing under it
        f.hline(0, horizon, 32, (70, 56, 40) if alt > -6 else (48, 48, 64))
        sun = self._sun_at(pts, now)
        if sun is not None and alt > -1:
            self._draw_sun(f, sun[0], sun[1], alt, 2 if alt > 3 else 1, t)
            f.rect(0, horizon + 1, 32, 32 - horizon - 1, (0, 0, 0))  # its glow stays in the sky
        elif alt < -2:
            self._draw_moon_small(f, 25, 11, 7, now, self._south(d))
        label, col = self._phase_label(day, d, now, alt)
        f.text_center(1, label, col)
        off = d["tz_offset"]
        rise, sset = day.get("sunrise"), day.get("sunset")
        if sset is not None and now > sset:
            rise = self.next_rise(d, now) or rise
        for y, key, ts in ((21, "rise", rise), (27, "set", sset)):
            f.sprite(ICONS[key], 1, y)
            f.text_right(30, y, _hm(ts, off, s.hour24), WHITE if ts and ts > now else MUTE)

    def _phase_label(self, day: dict[str, Any], d: dict[str, Any], now: float, alt: float) -> tuple[str, RGB]:
        if day.get("polar") == "day":
            return "MIDNIGHT", GOLD
        if day.get("polar") == "night":
            return "POLAR", BLUE
        if -4.0 <= alt < 6.0:
            return "GOLDEN", GOLD
        if -6.0 <= alt < -4.0:
            return "BLUE HR", BLUE
        sset = day.get("sunset")
        if alt >= 6.0 and sset is not None and now < sset:
            return f"▼{dur_text(sset - now)}", mix(SET_C, WHITE, 0.4)
        nr = self.next_rise(d, now)
        if nr is not None:
            return f"▲{dur_text(nr - now)}", mix(RISE_C, WHITE, 0.3)
        return "NIGHT", MUTE

    # ------------------------------------------------------------------ moon
    def _render_moon(self, f: Frame, t: float, now: float, d: dict[str, Any] | None) -> None:
        m = self.moon(now)
        if self.settings.stars:
            for x, y, ph in STARS:
                if y < 20:
                    f.blend(x, y, WHITE, 0.12 + 0.18 * ph * (0.6 + 0.4 * math.sin(t * 1.3 + ph * 20)))
        size = 19
        rgb, a = moon_disc(9.3, round(m["phase"] * 1000), self._south(d), size)
        self._blit_disc(f, rgb, a, 16 - size // 2 - 1, 1)
        rows = self._moon_pages(m, now)
        top, bottom = rows[int(t // self.settings.page_seconds) % len(rows)]
        tight_text(f, 20, top[0], top[1])
        tight_text(f, 26, bottom[0], bottom[1])

    def _moon_pages(self, m: dict[str, Any], now: float) -> list[tuple[tuple[str, RGB], tuple[str, RGB]]]:
        words = m["name"].split()
        if len(words) == 1:
            words.append("")
        name = ((words[0], WHITE), (" ".join(words[1:]), MUTE))
        pct = f"{round(m['illumination'] * 100)}%"
        full_in, new_in = m["next_full"] - now, m["next_new"] - now
        first_full = full_in < new_in
        nxt = (
            (("FULL", GOLD), (days_text(full_in), WHITE))
            if first_full
            else (("NEW", BLUE), (days_text(new_in), WHITE))
        )
        lit = ((pct, WHITE), ("LIT", MUTE))
        when_full = datetime.fromtimestamp(m["next_full"]).strftime("%b %d").upper()
        when_new = datetime.fromtimestamp(m["next_new"]).strftime("%b %d").upper()
        later = (("NEW", BLUE), (when_new, MUTE)) if first_full else (("FULL", GOLD), (when_full, MUTE))
        return [name, lit, nxt, later]

    # ----------------------------------------------------------------- times
    def _render_times(self, f: Frame, t: float, now: float, d: dict[str, Any]) -> None:
        s = self.settings
        day = self.day_for(d, now)
        off = d["tz_offset"]
        m = self.moon(now)
        evening = now > (day.get("noon") or now)
        gold = day.get("golden_pm" if evening else "golden_am")
        blue = day.get("blue_pm" if evening else "blue_am")
        full_in, new_in = m["next_full"] - now, m["next_new"] - now
        g0 = gold[0] if gold else None
        b0 = blue[0] if blue else None
        rows1 = [
            ("rise", _hm(day.get("sunrise"), off, s.hour24), day.get("sunrise")),
            ("set", _hm(day.get("sunset"), off, s.hour24), day.get("sunset")),
            ("noon", _hm(day.get("noon"), off, s.hour24), day.get("noon")),
            ("day", dur_text(day.get("day_length") or 0.0), None),
        ]
        nxt_moon = ("full", days_text(full_in)) if full_in < new_in else ("new", days_text(new_in))
        rows2 = [
            ("golden", _hm(g0, off, s.hour24), g0),
            ("blue", _hm(b0, off, s.hour24), b0),
            ("moon", f"{round(m['illumination'] * 100)}%", None),
            (nxt_moon[0], nxt_moon[1], None),
        ]
        pages = [rows1, rows2]
        page = int(t // s.page_seconds) % len(pages)
        upcoming = [ts for *_, ts in rows1 + rows2 if ts is not None and ts > now]
        nxt = min(upcoming) if upcoming else None
        for i, (icon, value, ts) in enumerate(pages[page]):
            y = 1 + i * 7
            f.sprite(ICONS[icon], 1, y)
            vcol = WHITE if ts is None or ts == nxt else (MUTE if ts > now else DIM)
            f.text_right(30, y, value, vcol)
            if ts is not None and ts == nxt:  # the next thing to happen gets a marker
                f.set(8, y + 2, WHITE)
        for q in range(len(pages)):
            f.set(15 + q * 2, 30, WHITE if q == page else DIM)

    # -------------------------------------------------------------- combined
    def _render_combined(self, f: Frame, t: float, now: float, d: dict[str, Any]) -> None:
        s = self.settings
        day = self.day_for(d, now)
        alt, _ = sun_position(now, d["lat"], d["lon"])
        horizon = 15
        self._sky(f, alt, 0, horizon, t)
        pts = self._arc_points(day, d, 2, 29, 3, horizon)
        self._draw_arc(f, pts, now)
        f.hline(0, horizon, 32, (60, 50, 40) if alt > -6 else (48, 48, 64))
        sun = self._sun_at(pts, now)
        if sun is not None and alt > -1:
            self._draw_sun(f, sun[0], sun[1], alt, 1, t)
            f.rect(0, horizon + 1, 32, 32 - horizon - 1, (0, 0, 0))
        self._draw_moon_small(f, 6, 23, 11, now, self._south(d))
        off = d["tz_offset"]
        f.text_right(30, 18, _hm(day.get("sunrise"), off, s.hour24), RISE_C)
        f.text_right(30, 25, _hm(day.get("sunset"), off, s.hour24), SET_C)
        rise, sset = day.get("sunrise"), day.get("sunset")
        f.set(12, 20, RISE_C if rise and now < rise else scale(RISE_C, 0.3))
        f.set(12, 27, SET_C if sset and now < sset else scale(SET_C, 0.3))

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        now = time.time()
        _, d = self._data()
        m = self.moon(now)
        out: dict[str, Any] = {
            "moon": {
                "phase": m["name"],
                "illumination_pct": round(m["illumination"] * 100, 1),
                "age_days": round(m["age_days"], 1),
                "next_full": datetime.fromtimestamp(m["next_full"])
                .astimezone()
                .isoformat(timespec="minutes"),
                "next_new": datetime.fromtimestamp(m["next_new"]).astimezone().isoformat(timespec="minutes"),
            }
        }
        if d is not None:
            day = self.day_for(d, now)
            off = d["tz_offset"]
            alt, az = sun_position(now, d["lat"], d["lon"])
            out.update(
                {
                    "city": d.get("city"),
                    "sunrise": _hm(day.get("sunrise"), off, True),
                    "sunset": _hm(day.get("sunset"), off, True),
                    "solar_noon": _hm(day.get("noon"), off, True),
                    "day_length": dur_text(day.get("day_length") or 0.0),
                    "sun_altitude": round(alt, 1),
                    "sun_azimuth": round(az, 1),
                    "golden_hour_pm": [_hm(x, off, True) for x in day["golden_pm"]]
                    if day.get("golden_pm")
                    else None,
                    "blue_hour_pm": [_hm(x, off, True) for x in day["blue_pm"]]
                    if day.get("blue_pm")
                    else None,
                    "sources": d.get("sources"),
                }
            )
        return out
