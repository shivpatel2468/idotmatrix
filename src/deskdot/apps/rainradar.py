"""Rain Radar — an animated loop of the last two hours of radar around you (RainViewer, no key).

The provider hands over 32×32 reflectivity grids (dBZ) per radar frame plus a basemap (elevation / land) for the
same window, so this app only paints: an LED colour ramp per scheme, the basemap, a home marker and the frame
time. The loop is deterministic for a given set of frames, so it is baked as a clip (well under the 40 KB GIF
budget: ~13–26 small frames) and re-baked when a new radar frame arrives.
"""

from __future__ import annotations

import itertools
import json
import time
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import PALETTE, Frame, measure, mix, scale, to_rgb
from ..gfx.color import RGB
from ._kit import loading, offline

WHITE: RGB = (255, 255, 255)
DBZ_LO, DBZ_HI = -10, 80  # LUT range
HOME = (15, 15)  # the provider centres the window on this LED

SCHEMES: dict[str, list[tuple[float, RGB]]] = {
    "classic": [
        (5, (0, 100, 40)),
        (15, (0, 150, 50)),
        (25, (0, 230, 70)),
        (32, (255, 214, 0)),
        (40, (255, 120, 0)),
        (48, (255, 0, 30)),
        (58, (255, 0, 190)),
        (65, (255, 255, 255)),
    ],
    "blue": [
        (5, (0, 50, 130)),
        (15, (0, 90, 200)),
        (25, (0, 190, 255)),
        (35, (255, 214, 0)),
        (45, (255, 60, 0)),
        (55, (255, 0, 190)),
        (65, (255, 255, 255)),
    ],
    "heat": [
        (5, (80, 0, 110)),
        (15, (110, 0, 150)),
        (25, (230, 0, 120)),
        (35, (255, 110, 0)),
        (45, (255, 220, 0)),
        (58, (255, 255, 255)),
    ],
}
SNOW: list[tuple[float, RGB]] = [(0, (70, 85, 140)), (15, (90, 130, 200)), (30, (170, 210, 255)), (45, WHITE)]
SPEEDS = {"slow": 500, "normal": 300, "fast": 180}  # ms per radar frame
# Basemap tones: neutral slate (no rain hue, so land never reads as light rain) and just bright enough to
# survive the panel's gamma — the old greens (5, 12, 8) / (34, 64, 44) were invisible or looked like drizzle.
LAND: RGB = (44, 46, 58)
COAST: RGB = (86, 90, 112)
TERRAIN_LO: RGB = (42, 46, 56)
TERRAIN_HI: RGB = (96, 84, 64)
NO_COVER: RGB = (48, 40, 58)  # hatched where the radar has no coverage
TRACK: RGB = (56, 56, 72)  # the loop-position bar under the map
BLEND_STEPS = (1 / 3, 2 / 3)  # cross-fade frames between two radar frames

ZOOM_LABELS = {"7": "300 km", "6": "600 km", "5": "1 200 km", "4": "2 400 km", "3": "4 800 km"}


def ramp(stops: list[tuple[float, RGB]], v: float) -> RGB:
    if v <= stops[0][0]:
        return stops[0][1]
    for (a, ca), (b, cb) in itertools.pairwise(stops):
        if v <= b:
            return mix(ca, cb, (v - a) / (b - a))
    return stops[-1][1]


def lut(stops: list[tuple[float, RGB]]) -> np.ndarray:
    return np.array([ramp(stops, d) for d in range(DBZ_LO, DBZ_HI + 1)], dtype=np.uint8)


# --------------------------------------------------------------------------- settings
class RainRadarSettings(AppSettings):
    zoom: str = Choice("6", ZOOM_LABELS, title="Area (width)", group="Map")
    basemap: str = Choice(
        "outline",
        {"outline": "Coastline", "terrain": "Terrain", "land": "Land fill", "none": "None"},
        title="Basemap",
        group="Map",
    )
    coverage: bool = Field(True, title="Mark areas without radar", json_schema_extra={"group": "Map"})
    home: bool = Field(True, title="Home marker", json_schema_extra={"group": "Map"})
    scheme: str = Choice(
        "classic",
        {"classic": "Classic", "blue": "Blue", "heat": "Heat", "mono": "Mono"},
        title="Colour scheme",
        group="Colours",
    )
    mono_color: Color = Field("#00dcff", title="Mono colour", json_schema_extra={"group": "Colours"})
    home_color: Color = Field("#ffffff", title="Home colour", json_schema_extra={"group": "Colours"})
    threshold: int = Field(
        10,
        ge=-10,
        le=40,
        title="Minimum intensity (dBZ)",
        description="Hide weaker echoes: 10 ≈ drizzle, 20 light rain, 30 moderate",
        json_schema_extra={"group": "Colours"},
    )
    speed: str = Choice(
        "normal", {"slow": "Slow", "normal": "Normal", "fast": "Fast"}, title="Loop speed", group="Loop"
    )
    smooth: bool = Field(True, title="Cross-fade frames", json_schema_extra={"group": "Loop"})
    time_label: str = Choice(
        "clock",
        {"clock": "Clock time", "relative": "Minutes ago", "off": "Off"},
        title="Frame time",
        group="Loop",
    )
    hour24: bool = Field(True, title="24-hour clock", json_schema_extra={"group": "Loop"})


# --------------------------------------------------------------------------- the app
@register
class RainRadar(App):
    id = "rainradar"
    name = "Rain Radar"
    description = "Animated rain radar around you (past 2 hours), with a home marker and coastline."
    icon = "cloud-rain"
    category = "data"
    Settings = RainRadarSettings
    fps = 2.0
    uses = ("rainradar",)
    clip_colors = 64

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._base_cache: tuple[Any, np.ndarray] | None = None
        self.on_settings()

    # ------------------------------------------------------------ lifecycle
    def on_settings(self) -> None:
        s = self.settings
        if s.scheme == "mono":
            c = to_rgb(s.mono_color)
            self.lut = lut([(5, scale(c, 0.35)), (25, scale(c, 0.6)), (45, c), (60, mix(c, WHITE, 0.6))])
        else:
            self.lut = lut(SCHEMES[s.scheme])
        self.snow_lut = lut(SNOW)
        self._base_cache = None
        self._radar_cache: dict[int, tuple[Any, np.ndarray, np.ndarray]] = {}
        self._dry: tuple[int, bool] | None = None
        self.on_start()

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(int(self.settings.zoom))

    def _provider(self) -> Any:
        try:
            return self.ctx.provider("rainradar")
        except KeyError:
            return None

    def _data(self) -> tuple[Any, dict[str, Any] | None]:
        p = self._provider()
        v = p.value if p is not None else None
        if not v or v.get("zoom") != int(self.settings.zoom) or not v.get("frames"):
            return p, None
        return p, v

    # ------------------------------------------------------------ painting
    def basemap(self, v: dict[str, Any]) -> np.ndarray:
        """Static background (32, 32, 3), cached per data object and settings."""
        key = (id(v.get("land")), id(v.get("nocov")))
        if self._base_cache and self._base_cache[0] == key:
            return self._base_cache[1]
        s = self.settings
        img = np.zeros((32, 32, 3), dtype=np.uint8)
        land = v.get("land")
        nocov = v.get("nocov")
        if s.coverage and nocov is not None:
            yy, xx = np.mgrid[0:32, 0:32]
            img[nocov & ((xx + yy) % 2 == 0)] = NO_COVER
        if land is not None and s.basemap != "none":
            land = land.astype(bool)
            if s.basemap == "land":
                img[land] = LAND
            elif s.basemap == "terrain":
                elev = v.get("elev")
                if elev is None:
                    img[land] = LAND
                else:
                    k = np.clip(np.asarray(elev, dtype=np.float32) / 1500.0, 0.0, 1.0)[..., None]
                    k = np.round(k * 4) / 4  # four flat bands, not a smooth gradient (GIF size, banding)
                    lo = np.array(TERRAIN_LO, np.float32)
                    hi = np.array(TERRAIN_HI, np.float32)
                    img[land] = (lo + (hi - lo) * k)[land].astype(np.uint8)
            else:  # coastline: land cells that touch the sea
                pad = np.pad(land, 1, mode="edge")
                sea_n = ~pad[:-2, 1:-1] | ~pad[2:, 1:-1] | ~pad[1:-1, :-2] | ~pad[1:-1, 2:]
                img[land & sea_n] = COAST
        self._base_cache = (key, img)
        return img

    def radar(self, fr: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        """One radar frame -> (rgb (32, 32, 3), mask of echoes above the threshold), cached per frame."""
        hit = self._radar_cache.get(id(fr))
        if hit is not None and hit[0] is fr["dbz"]:
            return hit[1], hit[2]
        if len(self._radar_cache) > 40:
            self._radar_cache.clear()
        dbz = np.asarray(fr["dbz"], dtype=np.int16)
        mask = dbz >= self.settings.threshold
        idx = np.clip(dbz - DBZ_LO, 0, DBZ_HI - DBZ_LO)
        rgb = np.where(np.asarray(fr["snow"], dtype=bool)[..., None], self.snow_lut[idx], self.lut[idx])
        self._radar_cache[id(fr)] = (fr["dbz"], rgb, mask)
        return rgb, mask

    def dry(self, v: dict[str, Any]) -> bool:
        if self._dry is None or self._dry[0] != id(v["frames"]):
            self._dry = (id(v["frames"]), not any(self.radar(fr)[1].any() for fr in v["frames"]))
        return self._dry[1]

    def schedule(self, v: dict[str, Any]) -> list[tuple[int, int, float, int]]:
        """Loop steps: (frame a, frame b, blend 0..1, duration ms). The newest past frame is held longer."""
        n = len(v["frames"])
        ms = SPEEDS[self.settings.speed]
        last_past = max((i for i, fr in enumerate(v["frames"]) if fr["kind"] == "past"), default=n - 1)
        steps: list[tuple[int, int, float, int]] = []
        for i in range(n):
            hold = ms * 4 if i == last_past or i == n - 1 else ms
            if self.settings.smooth and i < n - 1:
                fade = ms // 4  # two in-between frames: echoes glide instead of popping
                steps.append((i, i, 0.0, max(60, hold - fade * len(BLEND_STEPS))))
                steps.extend((i, i + 1, k, fade) for k in BLEND_STEPS)
            else:
                steps.append((i, i, 0.0, hold))
        return steps

    def _time_text(self, v: dict[str, Any], i: int) -> str:
        fr = v["frames"][i]
        mode = self.settings.time_label
        if mode == "off":
            return ""
        if mode == "relative":
            ref = max((f["time"] for f in v["frames"] if f["kind"] == "past"), default=fr["time"])
            m = round((fr["time"] - ref) / 60)
            return "NOW" if m == 0 else f"{m:+d}M"
        lt = time.localtime(fr["time"])
        if self.settings.hour24:
            return f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
        return f"{(lt.tm_hour % 12) or 12}:{lt.tm_min:02d}"

    def paint(self, f: Frame, v: dict[str, Any], step: tuple[int, int, float, int]) -> None:
        a, b, k, _ms = step
        frames = v["frames"]
        img = self.basemap(v).copy()
        ra, ma = self.radar(frames[a])
        if b != a and k > 0:
            rb, mb = self.radar(frames[b])
            both = ma & mb
            mixed = (ra.astype(np.float32) * (1 - k) + rb.astype(np.float32) * k).astype(np.uint8)
            img[ma & ~mb] = (ra[ma & ~mb] * (1 - k)).astype(np.uint8)
            img[mb & ~ma] = np.maximum(img[mb & ~ma], (rb[mb & ~ma] * k).astype(np.uint8))
            img[both] = mixed[both]
        else:
            img[ma] = ra[ma]
        f.px[:, :] = img
        s = self.settings
        if s.home:
            hc = to_rgb(s.home_color)
            hx, hy = HOME
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                f.set(hx + dx, hy + dy, scale(hc, 0.55))
            f.set(hx, hy, hc)
        fr = frames[a if k < 0.5 else b]
        idx = a if k < 0.5 else b
        forecast = fr["kind"] != "past"
        txt = self._time_text(v, idx)
        if txt:
            w = measure(txt)
            f.px[25:31, 0 : w + 2] = (f.px[25:31, 0 : w + 2] * 0.15).astype(np.uint8)
            f.text(1, 26, txt, PALETTE["magenta"] if forecast else WHITE)
        n = len(frames)
        pos = round(idx / max(1, n - 1) * 31)
        f.hline(0, 31, 32, TRACK)
        f.hline(0, 31, pos + 1, scale(PALETTE["magenta"] if forecast else PALETTE["sky"], 0.6))
        f.set(pos, 31, WHITE)
        if self.dry(v):
            f.text_right(30, 1, "DRY", PALETTE["mute"])

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        p, v = self._data()
        if v is None:
            if p is not None and p.error and not p.value:
                offline(f, "RADAR", "OFFLINE")
            else:
                loading(f, t, "RADAR", PALETTE["sky"])
            return
        steps = self.schedule(v)
        total = sum(st[3] for st in steps)
        ms = (t * 1000) % total
        for st in steps:
            if ms < st[3]:
                self.paint(f, v, st)
                break
            ms -= st[3]
        if p is not None and p.error:
            f.set(31, 0, PALETTE["amber"])

    # ------------------------------------------------------------ output
    def kind(self) -> Kind:
        _p, v = self._data()
        return "clip" if v is not None else "stream"

    def clip_key(self) -> str:
        _p, v = self._data()
        sig = None if v is None else [v["zoom"], [fr["time"] for fr in v["frames"]], id(v.get("land"))]
        return super().clip_key() + json.dumps(sig)

    def clip_frames(self) -> Clip:
        _p, v = self._data()
        if v is None:
            return super().clip_frames()
        frames, durs = [], []
        for st in self.schedule(v):
            f = Frame()
            self.paint(f, v, st)
            frames.append(f)
            durs.append(st[3])
        return Clip(frames, durs)

    def status(self) -> dict[str, Any]:
        _p, v = self._data()
        if v is None:
            return {"frames": 0}
        last = v["frames"][-1]
        cells = int((np.asarray(last["dbz"]) >= self.settings.threshold).sum())
        return {
            "frames": len(v["frames"]),
            "latest": last["time"],
            "rain_cells": cells,
            "km_per_led": round(float(v.get("km_per_led") or 0), 1),
        }
