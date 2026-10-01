"""Earthquakes — live USGS events on a world map, a regional zoom around you, a card and a list.

Every layout is a deterministic loop per data update, so it is baked as a clip: the highlighted quakes (latest,
nearest or strongest) take turns, each with pulsing rings sized by magnitude. The clip re-bakes when the feed
brings new events (or a shown "time ago" moves on). Alerts: a quake at or above the alert magnitude inside the
near-me radius raises a notification once per event; the first fetch only arms the alert.
"""

from __future__ import annotations

import itertools
import json
import math
import time
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale, to_hex, to_rgb
from ..gfx.color import RGB
from ..gfx.worldmap import draw_world
from ..providers.quakes import FEEDS, compass
from ._kit import label, loading, offline

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)

FEED_LABELS = {
    "all_hour": "All · past hour",
    "all_day": "All · past day",
    "2.5_day": "M2.5+ · past day",
    "2.5_week": "M2.5+ · past week",
    "4.5_day": "M4.5+ · past day",
    "4.5_week": "M4.5+ · past week",
    "4.5_month": "M4.5+ · past 30 days",
    "significant_week": "Significant · past week",
    "significant_month": "Significant · past 30 days",
}

# magnitude -> LED colour (interpolated between stops)
MAG_STOPS: list[tuple[float, RGB]] = [
    (1.0, (0, 140, 255)),
    (2.5, PALETTE["mint"]),
    (3.5, PALETTE["lime"]),
    (4.5, PALETTE["gold"]),
    (5.5, PALETTE["amber"]),
    (6.3, PALETTE["ember"]),
    (7.0, PALETTE["red"]),
    (8.0, PALETTE["magenta"]),
]
DEPTH_STOPS: list[tuple[float, RGB]] = [
    (0.0, PALETTE["ember"]),
    (70.0, PALETTE["amber"]),
    (150.0, PALETTE["gold"]),
    (300.0, PALETTE["lime"]),
    (500.0, PALETTE["sky"]),
    (700.0, PALETTE["violet"]),
]
CARD_LABELS = {  # longest first; the first that fits next to the age wins
    "latest": ("LATEST", "LAST", "NEW"),
    "nearest": ("NEAREST", "CLOSE", "NEAR"),
    "strongest": ("STRONG", "MAX"),
}
SLOT_S = 2.5  # seconds each highlighted quake is featured
CLIP_FPS = 10.0  # the fastest clip rate verified on the panel; the card marquee moves 1 px per frame
MARQUEE_SPEED = 10.0
DOT_OFF: RGB = (84, 84, 100)  # inactive page dots: PALETTE "shade" is black through the panel gamma
PULSE_S = 1.25  # ring period
MAP_Y = 8  # world map band: rows 8..23
KM_PER_PX_REGION = 40075.0 / 128  # 128×64 map: one pixel ≈ 313 km (lat)


def ramp(stops: list[tuple[float, RGB]], v: float) -> RGB:
    if v <= stops[0][0]:
        return stops[0][1]
    for (a, ca), (b, cb) in itertools.pairwise(stops):
        if v <= b:
            return mix(ca, cb, (v - a) / (b - a))
    return stops[-1][1]


def mag_color(m: float) -> RGB:
    return ramp(MAG_STOPS, m)


def ago(seconds: float) -> str:
    """Compact, bucketed age: NOW, 7M, 25M (5-min steps), 3H, 2D."""
    s = max(0.0, seconds)
    m = int(s // 60)
    if m < 1:
        return "NOW"
    if m < 10:
        return f"{m}M"
    if m < 60:
        return f"{m // 5 * 5}M"
    h = m // 60
    if h < 48:
        return f"{h}H"
    return f"{h // 24}D"


def fmt_km(km: float, width: int = 99) -> str:
    """Richest distance text that fits `width` px: '620KM', '9911KM', '9911', '12.3K', '12K'."""
    cands = [f"{km:.1f}KM"] if km < 10 else []
    if km < 10000:
        cands += [f"{km:.0f}KM", f"{km:.0f}"]
    cands += [f"{km / 1000:.1f}K", f"{km / 1000:.0f}K"]
    for c in cands:
        if measure(c) <= width:
            return c
    return cands[-1]


def fit_chars(s: str, w: int) -> str:
    while s and measure(s) > w:
        s = s[:-1]
    return s.rstrip(" ,")


# ring offsets per radius (unique integer points on a circle), computed once
def _ring_points(r: int) -> list[tuple[int, int]]:
    if r <= 0:
        return [(0, 0)]
    pts: set[tuple[int, int]] = set()
    n = max(8, int(2 * math.pi * r * 2))
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.add((round(r * math.cos(a)), round(r * math.sin(a))))
    return sorted(pts)


RINGS = {r: _ring_points(r) for r in range(0, 9)}


def add_px(f: Frame, x: int, y: int, c: RGB, clip: tuple[int, int, int, int] = (0, 0, 31, 31)) -> None:
    """Additive-max plot (rings over dots never darken them), clipped to `clip` (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = clip
    if x0 <= x <= x1 and y0 <= y <= y1:
        f.px[y, x] = np.maximum(f.px[y, x], np.asarray(c, dtype=np.uint8))


# --------------------------------------------------------------------------- settings
class QuakesSettings(AppSettings):
    feed: str = Choice("2.5_day", FEED_LABELS, title="Feed", group="Data")
    min_mag: float = Field(
        0.0,
        ge=0.0,
        le=9.0,
        title="Minimum magnitude",
        description="Hide smaller events (on top of the feed's own threshold)",
        json_schema_extra={"group": "Data"},
    )
    radius_km: int = Field(
        1000,
        ge=50,
        le=5000,
        title="Near-me radius (km)",
        description="Used by the regional map ring and the alert",
        json_schema_extra={"group": "Data"},
    )
    layout: str = Choice(
        "world",
        {"world": "World map", "region": "Regional map", "card": "Card", "list": "List"},
        title="Layout",
        group="Layout",
    )
    focus: str = Choice(
        "latest",
        {"latest": "Latest", "nearest": "Nearest", "strongest": "Strongest"},
        title="Highlight",
        description="Which quakes the card, the map rings and the list feature",
        group="Layout",
    )
    center: str = Choice(
        "home",
        {"home": "My longitude", "pacific": "Pacific (150°E)", "greenwich": "Greenwich (0°)"},
        title="World map centre",
        group="Layout",
    )
    highlights: int = Field(3, ge=1, le=5, title="Quakes featured", json_schema_extra={"group": "Layout"})
    color_by: str = Choice(
        "magnitude",
        {"magnitude": "Magnitude", "depth": "Depth", "age": "Age"},
        title="Colour by",
        group="Colours",
    )
    land: Color = Field("#343a4a", title="Land", json_schema_extra={"group": "Colours"})
    home_color: Color = Field("#00dcff", title="You are here", json_schema_extra={"group": "Colours"})
    pulse: bool = Field(True, title="Pulsing rings", json_schema_extra={"group": "Colours"})
    alert: bool = Field(True, title="Alert on nearby quakes", json_schema_extra={"group": "Alerts"})
    alert_mag: float = Field(
        4.5, ge=1.0, le=9.0, title="Alert magnitude", json_schema_extra={"group": "Alerts"}
    )


# --------------------------------------------------------------------------- the app
@register
class Quakes(App):
    id = "quakes"
    name = "Earthquakes"
    description = (
        "Live USGS earthquakes: world map with pulsing rings, regional zoom, nearest/latest card, list."
    )
    icon = "activity"
    category = "data"
    Settings = QuakesSettings
    fps = 2.0
    uses = ("quakes",)
    clip_fps = CLIP_FPS
    clip_colors = 64
    #: "time ago" labels only move the loop's chunk, re-baked at most this often (GIF uploads freeze the panel
    #: when they come back to back, docs/HARDWARE_PROTOCOL.md #16); new quakes change the key and bake at once
    clip_refresh = 90.0

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.on_settings()

    # ------------------------------------------------------------ lifecycle / data
    def on_settings(self) -> None:
        self._seen: set[str] | None = None  # alert state: None = not armed yet
        self._alert_updated = -1.0
        self.on_start()

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(self.settings.feed)

    def _provider(self) -> Any:
        try:
            return self.ctx.provider("quakes")
        except KeyError:
            return None

    def _data(self) -> tuple[Any, dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
        p = self._provider()
        v = (p.value if p is not None else None) or {}
        feed = (v.get("feeds") or {}).get(self.settings.feed)
        if feed is None:
            return p, None, [], v.get("home") or {}
        qs = [q for q in feed["quakes"] if q["mag"] >= self.settings.min_mag]
        return p, feed, qs, v.get("home") or {}

    def _featured(
        self, qs: list[dict[str, Any]], home: dict[str, Any], region: bool = False
    ) -> list[dict[str, Any]]:
        s = self.settings
        pool = qs
        if region and home:
            pool = [q for q in qs if self._region_xy(q, home) is not None]
        if s.focus == "nearest" and home:
            pool = sorted(pool, key=lambda q: q.get("dist_km", 1e9))
        elif s.focus == "strongest":
            pool = sorted(pool, key=lambda q: (-q["mag"], -q["time"]))
        return pool[: s.highlights]

    # ------------------------------------------------------------ colours
    def color(self, q: dict[str, Any], newest: float = 0.0, oldest: float = 0.0) -> RGB:
        mode = self.settings.color_by
        if mode == "depth":
            return ramp(DEPTH_STOPS, q.get("depth_km") or 0.0)
        if mode == "age":
            span = max(1.0, newest - oldest)
            k = (newest - q["time"]) / span
            return ramp(
                [(0.0, WHITE), (0.25, PALETTE["gold"]), (0.6, PALETTE["ember"]), (1.0, (120, 10, 30))], k
            )
        return mag_color(q["mag"])

    # ------------------------------------------------------------ alerts (main thread, once per fetch)
    def _check_alerts(self) -> None:
        p = self._provider()
        if p is None or not p.updated or p.updated == self._alert_updated:
            return
        self._alert_updated = p.updated
        _p, feed, qs, home = self._data()
        if feed is None or not home:
            return
        s = self.settings
        hits = [q for q in qs if q["mag"] >= s.alert_mag and q.get("dist_km", 1e9) <= s.radius_km]
        if self._seen is None:  # first fetch arms: never alert for what was already there
            self._seen = {q["id"] for q in hits}
            return
        for q in reversed(hits):
            if q["id"] in self._seen:
                continue
            self._seen.add(q["id"])
            if not s.alert:
                continue
            self.ctx.notify(
                title=f"QUAKE M{q['mag']:.1f}"[:40],
                message=f"{q['region']} · {fmt_km(q.get('dist_km', 0))} {compass(q.get('bearing', 0))}"[:280],
                icon="warn",
                color=to_hex(mag_color(q["mag"])),
                style="full" if q["mag"] >= 6.0 else "banner",
                duration=10.0,
            )

    # ------------------------------------------------------------ loop timing
    def _cycle(self) -> tuple[float, float]:
        """(loop seconds, frames per second) for the current layout and data."""
        _p, feed, qs, home = self._data()
        lay = self.settings.layout
        if feed is None or not qs:
            return 2.0, 6.0
        if lay == "list":
            pages = max(1, min(3, math.ceil(len(qs) / 4)))
            return 3.0 * pages, 2.0
        if lay == "card":
            q = self._featured(qs, home)[0]
            w = measure(q["region"])
            loop = 1.2 + (w + 12) / MARQUEE_SPEED if w > 30 else 2.5  # = the marquee's own period
            return max(2.5, round(loop * CLIP_FPS) / CLIP_FPS), CLIP_FPS
        n = len(self._featured(qs, home, region=lay == "region")) or 1
        return SLOT_S * n, self.clip_fps

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        p, feed, qs, home = self._data()
        if feed is None:
            if p is not None and p.error:
                offline(f, "QUAKES", "OFFLINE")
            else:
                loading(f, t, "QUAKES", PALETTE["amber"])
            return
        loop, _fps = self._cycle()
        t = t % loop
        self._pulse = loop / max(1, round(loop / PULSE_S))  # whole ring pulses per loop: no jump at the wrap
        {"world": self._world, "region": self._region, "card": self._card, "list": self._list}[
            self.settings.layout
        ](f, t, qs, home, feed)
        if p is not None and p.error:
            f.set(0, 31, PALETTE["amber"])

    def _rings(
        self, f: Frame, cx: int, cy: int, mag: float, c: RGB, t: float, clip: tuple[int, int, int, int]
    ) -> None:
        rmax = max(2.0, min(7.0, mag - 0.5))
        if not self.settings.pulse:
            for dx, dy in RINGS[max(1, round(rmax * 0.6))]:
                add_px(f, cx + dx, cy + dy, scale(c, 0.45), clip)
            return
        pulse = getattr(self, "_pulse", PULSE_S)
        for k in (0.0, 0.5):
            ph = ((t / pulse) + k) % 1.0
            r = round(1 + ph * (rmax - 1))
            b = (1.0 - ph) ** 1.3
            for dx, dy in RINGS[r]:
                add_px(f, cx + dx, cy + dy, scale(c, 0.15 + 0.85 * b), clip)

    def _empty(self, f: Frame, feed: dict[str, Any]) -> None:
        f.text_center(10, "NO QUAKES", PALETTE["mute"])
        label(f, 18, FEEDS.get(self.settings.feed, ""), PALETTE["mute"])

    def _slot(self, t: float, n: int) -> int:
        return min(n - 1, int(t // SLOT_S)) if n else 0

    def _dots(self, f: Frame, t: float, n: int, y: int) -> None:
        if n < 2:
            return
        x0 = 16 - (n * 3 - 1) // 2
        for i in range(n):
            f.hline(x0 + i * 3, y, 2, WHITE if i == self._slot(t, n) else DOT_OFF)

    # world: header · 32×16 map with rings · area caption ---------------------------------------------
    def _world_lon0(self, home: dict[str, Any]) -> float:
        c = {"home": float(home.get("lon") or 0.0), "pacific": 150.0, "greenwich": 0.0}[self.settings.center]
        return round(c / 360.0 * 32) * (360.0 / 32)

    def _world(
        self, f: Frame, t: float, qs: list[dict[str, Any]], home: dict[str, Any], feed: dict[str, Any]
    ) -> None:
        c0 = self._world_lon0(home)
        draw_world(f, self.settings.land, None, size=(32, 16), y=MAP_Y, center_lon=c0)
        clip = (0, MAP_Y, 31, MAP_Y + 15)

        def xy(lat: float, lon: float) -> tuple[int, int]:
            x = ((lon - (c0 - 180.0)) % 360.0) / 360.0 * 32
            y = MAP_Y + (90.0 - lat) / 180.0 * 16
            return min(31, int(x)), min(MAP_Y + 15, int(y))

        if home:
            hx, hy = xy(float(home["lat"]), float(home["lon"]))
            f.set(hx, hy, scale(self.settings.home_color, 0.8))
        if not qs:
            f.text_center(1, "NO QUAKES", PALETTE["mute"])
            label(f, 26, FEEDS.get(self.settings.feed, ""), PALETTE["mute"])
            return
        newest, oldest = qs[0]["time"], qs[-1]["time"]
        for q in reversed(qs):  # oldest first, newest on top
            x, y = xy(q["lat"], q["lon"])
            k = 0.4 + 0.6 * (1 - (newest - q["time"]) / max(1.0, newest - oldest))
            add_px(f, x, y, scale(self.color(q, newest, oldest), k), clip)
        feat = self._featured(qs, home)
        q = feat[self._slot(t, len(feat))]
        c = self.color(q, newest, oldest)
        x, y = xy(q["lat"], q["lon"])
        self._rings(f, x, y, q["mag"], c, t, clip)
        add_px(f, x, y, mix(c, WHITE, 0.6), clip)
        self._caption_top(f, q, c)
        f.text_center(25, fit_chars(q["area"], 30), mix(WHITE, c, 0.15))
        self._dots(f, t, len(feat), 31)

    def _caption_top(self, f: Frame, q: dict[str, Any], c: RGB) -> None:
        f.text(1, 1, f"M{q['mag']:.1f}", c)
        f.text_right(30, 1, ago(time.time() - q["time"]), PALETTE["mute"])

    # region: 90°×90° window of the 128×64 map around you ---------------------------------------------
    @staticmethod
    def _region_origin(home: dict[str, Any]) -> tuple[int, int]:
        hx = (float(home.get("lon") or 0.0) + 180.0) / 360.0 * 128
        hy = (90.0 - float(home.get("lat") or 0.0)) / 180.0 * 64
        return int(hx) - 16, max(0, min(32, int(hy) - 16))

    def _region_xy(self, q: dict[str, Any], home: dict[str, Any]) -> tuple[int, int] | None:
        ox, oy = self._region_origin(home)
        x = int((((q["lon"] + 180.0) / 360.0 * 128) - ox) % 128)
        y = int((90.0 - q["lat"]) / 180.0 * 64) - oy
        return (x, y) if 0 <= x < 32 and 0 <= y < 32 else None

    def _region(
        self, f: Frame, t: float, qs: list[dict[str, Any]], home: dict[str, Any], feed: dict[str, Any]
    ) -> None:
        if not home:
            offline(f, "QUAKES", "NO PLACE")
            return
        ox, oy = self._region_origin(home)
        draw_world(f, self.settings.land, None, size=(128, 64), view=(32, 32), offset=(ox, oy))
        hc = to_rgb(self.settings.home_color)
        r = self.settings.radius_km / KM_PER_PX_REGION
        if r >= 1.5:
            pts = RINGS[min(8, round(r))] if r <= 8.4 else _ring_points(round(r))
            for i, (dx, dy) in enumerate(pts):
                if i % 2 == 0:
                    add_px(f, 16 + dx, 16 + dy, scale(hc, 0.55))
        f.set(16, 16, hc)
        inside = [(q, xy) for q in qs if (xy := self._region_xy(q, home)) is not None]
        if not inside:
            f.rect(0, 25, 32, 7, BLACK)
            label(f, 26, "QUIET", PALETTE["mute"])  # "ALL QUIET" ran past both margins
            return
        newest, oldest = qs[0]["time"], qs[-1]["time"]
        for q, (x, y) in reversed(inside):
            add_px(f, x, y, scale(self.color(q, newest, oldest), 0.75))
        feat = self._featured(qs, home, region=True)
        q = feat[self._slot(t, len(feat))]
        c = self.color(q, newest, oldest)
        x, y = self._region_xy(q, home) or (16, 16)
        self._rings(f, x, y, q["mag"], c, t, (0, 0, 31, 24))
        add_px(f, x, y, mix(c, WHITE, 0.6))
        f.px[25:32] = (f.px[25:32] * 0.15).astype(np.uint8)
        mag = f"{q['mag']:.1f}"
        f.text(1, 26, mag, c)
        f.text_right(30, 26, fmt_km(q.get("dist_km", 0.0), 28 - measure(mag)), mix(WHITE, c, 0.2))
        self._dots(f, t, len(feat), 31)

    # card: label · big magnitude + epicentre rings · distance · place marquee ------------------------------
    def _card(
        self, f: Frame, t: float, qs: list[dict[str, Any]], home: dict[str, Any], feed: dict[str, Any]
    ) -> None:
        if not qs:
            self._empty(f, feed)
            return
        q = self._featured(qs, home)[0]
        c = self.color(q, qs[0]["time"], qs[-1]["time"])
        age = ago(time.time() - q["time"])
        if q["tsunami"]:  # the warning wins the whole header row
            f.text_center(1, "TSUNAMI", PALETTE["red"] if int(t * 2) % 2 == 0 else scale(PALETTE["red"], 0.4))
        else:
            room = 28 - measure(age)
            label = next(
                (lb for lb in CARD_LABELS[self.settings.focus] if measure(lb) <= room),
                CARD_LABELS[self.settings.focus][-1],
            )
            f.text(1, 1, label, PALETTE["mute"])
            f.text_right(30, 1, age, WHITE)
        f.text(1, 8, f"{q['mag']:.1f}", c, font="big")
        self._rings(f, 25, 12, min(q["mag"], 6.5), c, t, (19, 7, 31, 17))
        f.set(25, 12, mix(c, WHITE, 0.7))
        if "dist_km" in q:
            cp = compass(q.get("bearing", 0.0))
            f.text(1, 20, fmt_km(q["dist_km"], 27 - measure(cp)), WHITE)
            f.text_right(30, 20, cp, PALETTE["mute"])
        elif q.get("depth_km") is not None:
            f.text(1, 20, f"{q['depth_km']:.0f}KM DEEP", PALETTE["mute"])
        # half a frame of offset keeps int(phase * speed) exact: 1 px per frame, never 0-then-2
        draw_marquee(
            f, q["region"], t + 0.5 / CLIP_FPS, 1, 26, 30, mix(PALETTE["mute"], c, 0.25), speed=MARQUEE_SPEED
        )

    # list: pages of four rows (magnitude tag · area) ------------------------------------------------------
    def _list(
        self, f: Frame, t: float, qs: list[dict[str, Any]], home: dict[str, Any], feed: dict[str, Any]
    ) -> None:
        if not qs:
            self._empty(f, feed)
            return
        pool = qs
        if self.settings.focus == "nearest" and home:
            pool = sorted(qs, key=lambda q: q.get("dist_km", 1e9))
        elif self.settings.focus == "strongest":
            pool = sorted(qs, key=lambda q: (-q["mag"], -q["time"]))
        pages = max(1, min(3, math.ceil(len(pool) / 4)))
        page = min(pages - 1, int(t // 3.0))
        rows = pool[page * 4 : page * 4 + 4]
        for k, q in enumerate(rows):
            y = k * 8
            c = self.color(q, qs[0]["time"], qs[-1]["time"])
            f.text(1, y + 1, f"{q['mag']:.1f}", c)
            f.text(12, y + 1, fit_chars(q["area"], 18), WHITE if k == 0 and page == 0 else PALETTE["mute"])
        if pages > 1:
            for i in range(pages):
                f.set(31, 12 + i * 3, WHITE if i == page else DOT_OFF)

    # ------------------------------------------------------------ output
    def kind(self) -> Kind:
        self._check_alerts()  # kind() runs on the engine loop every tick, also while a clip plays
        _p, feed, _qs, _home = self._data()
        return "clip" if feed is not None else "stream"

    def clip_key(self) -> str:
        _p, _feed, qs, home = self._data()
        sig = [(q["id"], q["mag"]) for q in qs[:40]]
        return super().clip_key() + json.dumps([sig, bool(home)])

    def clip_chunk(self) -> str:
        _p, _feed, qs, _home = self._data()
        now = time.time()
        return json.dumps([ago(now - q["time"]) for q in qs[:40]])

    def clip_frames(self) -> Clip:
        loop, fps = self._cycle()
        n = max(1, round(loop * fps))
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / fps)
            frames.append(f)
        return Clip(frames, [round(1000 / fps)] * n)

    def relevant(self) -> bool:
        _p, feed, qs, _home = self._data()
        return feed is None or bool(qs)

    def status(self) -> dict[str, Any]:
        _p, _feed, qs, home = self._data()
        q = self._featured(qs, home)[0] if qs else None
        return {
            "feed": self.settings.feed,
            "count": len(qs),
            "featured": None
            if q is None
            else {"mag": q["mag"], "place": q["place"], "dist_km": q.get("dist_km"), "time": q["time"]},
        }
