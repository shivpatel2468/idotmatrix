"""Tides & Surf — the tide curve with a "now" marker and the next high/low, or wave height, period and direction.

Layouts: ``tide`` (24 h of modelled sea level around now as a filled curve, next high/low water above, the
current level and trend below), ``surf`` (wave height hero, a direction arrow, period, and a 24 h wave sparkline)
and ``both`` (alternates). Data: the `tides` provider (Open-Meteo Marine, keyless) for your location or a coast
point you set. Inland locations get a NO SEA screen that says how to fix it.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, mix, scale
from ..gfx.color import RGB
from ..providers.tides import at, compass
from ._kit import empty, loading, offline

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
DIM: RGB = PALETTE["dim"]
WATER_TOP: RGB = (0, 150, 255)
WATER_DEEP: RGB = (0, 20, 70)
# flat fills (a per-row gradient dithered into speckles and its deep rows vanished through the panel gamma)
FILL: RGB = (0, 70, 160)
FILL_PAST: RGB = (0, 45, 105)
CREST: RGB = (128, 202, 255)  # the curve itself: one unbroken bright line
CREST_PAST: RGB = (0, 110, 190)
NOW_LINE: RGB = (90, 90, 115)
HIGH_C: RGB = PALETTE["cyan"]
LOW_C: RGB = PALETTE["amber"]
WAVE_C: RGB = PALETTE["mint"]


class TidesSettings(AppSettings):
    layout: str = Choice(
        "tide", {"tide": "Tide curve", "surf": "Surf", "both": "Both (alternate)"}, title="Layout"
    )
    hours_back: int = Field(6, ge=0, le=12, title="Hours before now on the curve")
    hours_ahead: int = Field(18, ge=6, le=36, title="Hours after now on the curve")
    page_seconds: int = Field(8, ge=3, le=60, title="Seconds per page (both)")
    coast_lat: float = Field(
        0.0, ge=-90, le=90, title="Coast latitude", description="0/0 = your location.",
        json_schema_extra={"group": "Coast"},
    )  # fmt: skip
    coast_lon: float = Field(
        0.0, ge=-180, le=180, title="Coast longitude", json_schema_extra={"group": "Coast"}
    )
    hour24: bool = Field(True, title="24-hour times")


@register
class Tides(App):
    id = "tides"
    name = "Tides & Surf"
    description = "Tide curve with a now marker and next high/low, plus wave height, period and direction."
    icon = "waves-horizontal"
    category = "data"
    Settings = TidesSettings
    fps = 1.0
    uses = ("tides",)

    def _prov(self) -> Any:
        try:
            return self.ctx.provider("tides")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._prov()
        if p is not None and hasattr(p, "want"):
            p.want(self.settings.coast_lat, self.settings.coast_lon)

    def on_settings(self) -> None:
        self.on_start()

    def _hm(self, ts: float, d: dict[str, Any]) -> str:
        lt = datetime.fromtimestamp(ts + d.get("tz_offset", 0.0), tz=UTC)
        return lt.strftime("%H:%M") if self.settings.hour24 else f"{lt.hour % 12 or 12}:{lt.minute:02d}"

    @staticmethod
    def _len(v: float, d: dict[str, Any]) -> str:
        if d.get("unit") == "ft":
            return f"{v * 3.281:.1f}FT"
        return f"{v:.1f}M"

    def render(self, f: Frame, t: float) -> None:
        p = self._prov()
        d = p.value if p is not None else None
        if d is None:
            if p is None or p.error:
                offline(f, "TIDES", "OFFLINE")
            else:
                loading(f, t, "TIDES", WATER_TOP)
            return
        layout = self.settings.layout
        if layout == "both":
            layout = ("tide", "surf")[int(t // self.settings.page_seconds) % 2]
        if layout == "tide" and not d.get("has_tide"):
            layout = "surf"
        if layout == "surf" and not d.get("has_waves"):
            if d.get("has_tide"):
                layout = "tide"
            else:
                self._no_sea(f)
                return
        now = time.time()
        (self._tide if layout == "tide" else self._surf)(f, t, d, now)

    @staticmethod
    def _no_sea(f: Frame) -> None:
        f.text_center(6, "NO SEA", LOW_C)
        f.text_center(14, "SET A", MUTE)
        f.text_center(21, "COAST", MUTE)
        for x in range(3, 29):
            f.set(x, 29, scale(WATER_TOP, 0.4 if (x // 2) % 2 else 0.2))

    # ------------------------------------------------------------------ tide
    def _tide(self, f: Frame, t: float, d: dict[str, Any], now: float) -> None:
        s = self.settings
        t0 = now - s.hours_back * 3600
        t1 = now + s.hours_ahead * 3600
        xs = range(1, 31)
        vals: list[float | None] = [at(d, "sea", t0 + (x - 1) / 29 * (t1 - t0)) for x in xs]
        known = [v for v in vals if v is not None]
        if not known:
            self._no_sea(f)
            return
        lo, hi = min(known), max(known)
        span = max(0.2, hi - lo)
        top, bottom = 9, 24

        def ypos(v: float) -> int:
            return bottom - round((v - lo) / span * (bottom - top))

        now_x = 1 + round((now - t0) / (t1 - t0) * 29)
        pts = [(x, ypos(v)) for x, v in zip(xs, vals, strict=True) if v is not None]
        for x, y in pts:  # water: flat fill under the curve
            f.vline(x, y + 1, bottom - y, FILL_PAST if x < now_x else FILL)
        cur = at(d, "sea", now)
        # now marker: only in the open sky above the water, so it never cuts through the fill
        sky_to = ypos(cur) - 1 if cur is not None else bottom
        f.vline(now_x, top - 1, max(0, sky_to - top + 2), NOW_LINE)
        prev: tuple[int, int] | None = None
        for x, y in pts:  # the crest as a connected line: steep flanks stay unbroken, no dotted zigzag
            c = CREST_PAST if x < now_x else CREST
            if prev is not None and prev[0] == x - 1 and abs(y - prev[1]) > 1:
                py = prev[1]
                f.vline(x, y if y < py else py + 1, abs(y - py), c)
            f.set(x, y, c)
            prev = (x, y)
        if cur is not None:
            f.set(now_x, ypos(cur), WHITE)
            f.set(now_x - 1, ypos(cur), scale(WHITE, 0.5))
            f.set(now_x + 1, ypos(cur), scale(WHITE, 0.5))
        # next high/low water
        nxt = next((e for e in d.get("extrema", []) if e["ts"] > now), None)
        if nxt is not None:
            hi_next = nxt["kind"] == "high"
            col = HIGH_C if hi_next else LOW_C
            f.text(1, 1, "HI" if hi_next else "LO", col)
            f.text_right(30, 1, self._hm(nxt["ts"], d), WHITE)
            ex = 1 + round((nxt["ts"] - t0) / (t1 - t0) * 29)
            if 1 <= ex <= 30:
                f.set(ex, ypos(nxt["h"]) - 1, col)
        if cur is not None:
            f.text(1, 26, self._len(cur, d), MUTE)
            nxt_v = at(d, "sea", now + 1800)
            rising = nxt_v is not None and nxt_v > cur
            arrow = "▲" if rising else "▼"
            f.text_right(30, 26, arrow, HIGH_C if rising else LOW_C)

    # ------------------------------------------------------------------ surf
    def _surf(self, f: Frame, t: float, d: dict[str, Any], now: float) -> None:
        h = at(d, "wave", now)
        per = at(d, "period", now)
        dire = at(d, "direction", now)
        if h is None and per is None:  # forecast doesn't cover now (stale data): say so, never a blank panel
            empty(f, "SURF", "NO DATA", WAVE_C)
            return
        f.text(1, 1, "SURF", MUTE)
        if dire is not None:
            f.text_right(30, 1, compass(dire), WAVE_C)
        if h is not None:
            f.text(1, 8, self._len(h, d), WHITE, font="small")
        if per is not None:
            f.text(1, 17, f"{per:.0f}S", mix(WAVE_C, WHITE, 0.3))
        if dire is not None:
            self._arrow(f, 26, 12, dire + 180.0)  # waves travel away from where they come from
        # 24 h of wave height ahead
        vals = [at(d, "wave", now + i * 3600) for i in range(25)]
        vals_k = [v for v in vals if v is not None]
        if len(vals_k) >= 2:
            f.sparkline(1, 23, 30, 8, vals_k, WAVE_C, fill=scale(WAVE_C, 0.25))

    @staticmethod
    def _arrow(f: Frame, cx: int, cy: int, bearing: float) -> None:
        a = math.radians(bearing)
        dx, dy = math.sin(a), -math.cos(a)
        for k in range(-3, 4):
            f.set(round(cx + dx * k), round(cy + dy * k), WAVE_C)
        tipx, tipy = cx + dx * 3, cy + dy * 3
        for side in (-1, 1):
            b = a + side * 2.5
            for k in (1, 2):
                f.set(round(tipx + math.sin(b) * k), round(tipy - math.cos(b) * k), WAVE_C)
        f.set(round(tipx), round(tipy), WHITE)

    def status(self) -> dict[str, Any]:
        p = self._prov()
        d = p.value if p is not None else None
        if not d:
            return {}
        now = time.time()
        out: dict[str, Any] = {
            "place": d.get("place"),
            "has_tide": d.get("has_tide"),
            "has_waves": d.get("has_waves"),
        }
        if d.get("has_tide"):
            out["sea_level_m"] = at(d, "sea", now)
            out["next"] = [
                {"kind": e["kind"], "at": self._hm(e["ts"], d), "height_m": round(e["h"], 2)}
                for e in d.get("extrema", [])
                if e["ts"] > now
            ][:4]
        if d.get("has_waves"):
            out.update(
                {
                    "wave_m": at(d, "wave", now),
                    "period_s": at(d, "period", now),
                    "direction_deg": at(d, "direction", now),
                }
            )
        return out
