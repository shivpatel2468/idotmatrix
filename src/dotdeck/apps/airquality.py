"""Air Quality — AQI gauge, pollutant bars, UV focus and a 24-hour AQI forecast (Open-Meteo, no key).

Colours are semantic (category colours tuned for LEDs) and every value is also encoded by position — the gauge
fill, bar length, bar height — so the screen reads without colour. Pollen (Europe only) appears as an extra
pollutant page when the model provides it and is simply absent elsewhere.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import PALETTE, Frame, measure, mix, scale, to_hex, to_rgb
from ..gfx.color import RGB
from ._kit import label as kit_label
from ._kit import loading, offline, ring

WHITE: RGB = (255, 255, 255)
# Tracks and unlit gauge segments must stay lit through the panel's gamma: PALETTE "shade"/"dim" and 20 %
# band colours read as black on the LEDs, so the gauge showed a lone sliver with no scale around it.
TRACK: RGB = (56, 56, 72)
UNLIT_K = 0.4

GREEN: RGB = (0, 230, 90)
YELLOW: RGB = (255, 214, 0)
ORANGE: RGB = (255, 120, 0)
RED: RGB = (255, 10, 30)
PURPLE: RGB = (150, 50, 255)
MAROON: RGB = (190, 0, 90)

# (upper bound, label, colour); labels fit 30 px in the tiny font
US_BANDS: list[tuple[float, str, RGB]] = [
    (50, "GOOD", GREEN),
    (100, "FAIR", YELLOW),
    (150, "POOR", ORANGE),
    (200, "UNSAFE", RED),
    (300, "V.UNSAFE", PURPLE),
    (500, "HAZARD", MAROON),
]
EU_BANDS: list[tuple[float, str, RGB]] = [
    (20, "GOOD", GREEN),
    (40, "FAIR", (150, 240, 0)),
    (60, "MEDIUM", YELLOW),
    (80, "POOR", ORANGE),
    (100, "V.POOR", RED),
    (150, "EXTREME", PURPLE),
]
UV_BANDS: list[tuple[float, str, RGB]] = [
    (2.5, "LOW", GREEN),
    (5.5, "MEDIUM", YELLOW),
    (7.5, "HIGH", ORANGE),
    (10.5, "V.HIGH", RED),
    (99, "EXTREME", PURPLE),
]
UV_ADVICE = ("ENJOY", "HAT+SPF", "SPF 30+", "SHADE!", "STAY IN")

# WHO 2021 air quality guideline levels (µg/m³) — the bar is "1×" at the guideline
POLLUTANTS: list[tuple[str, str, float]] = [
    ("pm2_5", "PM2.5", 15.0),
    ("pm10", "PM10", 45.0),
    ("o3", "O3", 100.0),
    ("no2", "NO2", 25.0),
    ("so2", "SO2", 40.0),
    ("co", "CO", 4000.0),
]
# pollen: label and a "moderate" level in grains/m³
POLLEN: dict[str, tuple[str, float]] = {
    "grass": ("GRASS", 20.0),
    "birch": ("BIRCH", 50.0),
    "alder": ("ALDER", 50.0),
    "ragweed": ("RAGWD", 10.0),
    "mugwort": ("MUGWT", 10.0),
    "olive": ("OLIVE", 50.0),
}

# gauge: 220° arc, 2 px thick, centred on the panel's middle column
ARC_CX, ARC_CY, ARC_R = 15.5, 17.5, 14.4
ARC_START, ARC_SWEEP = 200.0, 220.0


def _arc() -> list[tuple[int, int, float]]:
    pts = []
    for y in range(32):
        for x in range(32):
            dx, dy = x - ARC_CX, ARC_CY - y
            r = math.hypot(dx, dy)
            if not (ARC_R - 1.3 <= r <= ARC_R + 0.3):
                continue
            a = math.degrees(math.atan2(dy, dx)) % 360.0
            along = (ARC_START - a) % 360.0
            if along <= ARC_SWEEP:
                pts.append((x, y, along / ARC_SWEEP))
    return pts


ARC = _arc()


def band(v: float, bands: list[tuple[float, str, RGB]]) -> tuple[int, str, RGB]:
    for i, (hi, label, c) in enumerate(bands):
        if v <= hi:
            return i, label, c
    return len(bands) - 1, bands[-1][1], bands[-1][2]


def band_frac(v: float, bands: list[tuple[float, str, RGB]]) -> float:
    """Value -> 0..1 where every band gets an equal share of the scale (reads like the official charts)."""
    lo = 0.0
    for i, (hi, _l, _c) in enumerate(bands):
        if v <= hi:
            return (i + (v - lo) / max(1e-9, hi - lo)) / len(bands)
        lo = hi
    return 1.0


def ratio_color(r: float) -> RGB:
    return GREEN if r <= 1 else YELLOW if r <= 2 else ORANGE if r <= 4 else RED


def fmt_val(v: float | None) -> str:
    if v is None:
        return "--"
    return f"{v:.1f}" if v < 10 and v != int(v) else f"{v:.0f}"


# --------------------------------------------------------------------------- settings
class AirQualitySettings(AppSettings):
    index: str = Choice("us", {"us": "US AQI", "eu": "European AQI"}, title="Index", group="Data")
    layout: str = Choice(
        "gauge",
        {
            "gauge": "AQI gauge",
            "pollutants": "Pollutants",
            "uv": "UV index",
            "forecast": "24 h forecast",
            "cycle": "Cycle all",
        },
        title="Layout",
        group="Layout",
    )
    gauge: str = Choice("arc", {"arc": "Arc", "ring": "Edge ring"}, title="Gauge style", group="Layout")
    rotate: int = Field(8, ge=3, le=60, title="Seconds per page", json_schema_extra={"group": "Layout"})
    label_color: Color = Field("#8c8ca0", title="Label colour", json_schema_extra={"group": "Colours"})
    alert: bool = Field(True, title="Alert when AQI rises past", json_schema_extra={"group": "Alerts"})
    alert_aqi: int = Field(
        150,
        ge=20,
        le=500,
        title="Alert threshold",
        description="In the chosen index (US 150 = unhealthy, EU 80 = very poor)",
        json_schema_extra={"group": "Alerts"},
    )


# --------------------------------------------------------------------------- the app
@register
class AirQuality(App):
    id = "airquality"
    name = "Air Quality"
    description = "AQI gauge, PM2.5/PM10/O3/NO2 bars, UV index advice, pollen (Europe) and a 24 h forecast."
    icon = "wind"
    category = "data"
    Settings = AirQualitySettings
    fps = 1.0
    uses = ("airquality",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.on_settings()

    def on_settings(self) -> None:
        self._above: bool | None = None
        self._alert_updated = -1.0

    def _provider(self) -> Any:
        try:
            return self.ctx.provider("airquality")
        except KeyError:
            return None

    @property
    def bands(self) -> list[tuple[float, str, RGB]]:
        return EU_BANDS if self.settings.index == "eu" else US_BANDS

    def aqi(self, d: dict[str, Any]) -> float | None:
        v = d.get("eu_aqi" if self.settings.index == "eu" else "us_aqi")
        return None if v is None else float(v)

    @property
    def index_label(self) -> str:
        return "EU AQI" if self.settings.index == "eu" else "US AQI"

    # ------------------------------------------------------------ alerts (once per crossing)
    def _check_alert(self, p: Any, d: dict[str, Any]) -> None:
        if p is None or not p.updated or p.updated == self._alert_updated:
            return
        self._alert_updated = p.updated
        v = self.aqi(d)
        if v is None:
            return
        above = v >= self.settings.alert_aqi
        if self._above is False and above and self.settings.alert:
            _i, label, c = band(v, self.bands)
            self.ctx.notify(
                title=f"AIR {label}"[:40],
                message=f"{self.index_label} {v:.0f} {d.get('city') or ''}".strip()[:280],
                icon="warn",
                color=to_hex(c),
            )
        self._above = above

    # ------------------------------------------------------------ render
    def pages(self, d: dict[str, Any]) -> list[tuple[str, int]]:
        out = [("gauge", 0), ("pollutants", 0), ("pollutants", 1)]
        if d.get("pollen"):
            out.append(("pollutants", 2))
        return [*out, ("uv", 0), ("forecast", 0)]

    def render(self, f: Frame, t: float) -> None:
        p = self._provider()
        d = p.value if p is not None else None
        if d is None:
            if p is not None and p.error:
                offline(f, "AIR", "OFFLINE")
            else:
                loading(f, t, "AIR", GREEN)
            return
        self._check_alert(p, d)
        lay = self.settings.layout
        page = int(t // self.settings.rotate)
        if lay == "cycle":
            pages = self.pages(d)
            lay, page = pages[page % len(pages)]
        {"gauge": self._gauge, "pollutants": self._pollutants, "uv": self._uv, "forecast": self._forecast}[
            lay
        ](f, d, page)
        if p.error:
            f.set(0, 31, PALETTE["amber"])

    # gauge: arc (or edge ring) · big AQI · category -----------------------------------------------------
    def _gauge(self, f: Frame, d: dict[str, Any], page: int) -> None:
        v = self.aqi(d)
        lab = to_rgb(self.settings.label_color)
        if v is None:
            f.text_center(10, self.index_label, lab)
            f.text_center(18, "NO DATA", PALETTE["mute"])
            return
        _i, label, c = band(v, self.bands)
        frac = band_frac(v, self.bands)
        n = len(self.bands)
        txt = f"{v:.0f}"
        if self.settings.gauge == "ring":
            ring(f, frac, c, track=TRACK, head=True)
            f.text_center(3, self.index_label, lab)
            f.text_center(10, txt, WHITE, font="big")
            f.text_center(23, label, c)
            return
        for x, y, a in ARC:
            seg_c = self.bands[min(n - 1, int(a * n))][2]
            f.set(x, y, seg_c if a <= frac else scale(seg_c, UNLIT_K))
        # needle tip: a white notch on the arc at the value
        ang = math.radians(ARC_START - frac * ARC_SWEEP)
        for rr in (ARC_R - 1.0, ARC_R):
            f.set(round(ARC_CX + rr * math.cos(ang)), round(ARC_CY - rr * math.sin(ang)), WHITE)
        # inside the arc: short "AQI" tag (rows 6-10 are clear between x 10 and 21), the big value, and the
        # category below the arc's open ends (the arc stops at row 22) so no text ever touches it
        f.text_center(6, "AQI", lab)
        f.text_center(11, txt, WHITE, font="big")
        kit_label(f, 24, label, c)

    # pollutants: three rows of label · value · bar ------------------------------------------------------
    def _rows(self, d: dict[str, Any], page: int) -> list[tuple[str, float | None, float]]:
        if page == 2 and d.get("pollen"):
            pol = sorted(d["pollen"].items(), key=lambda kv: -kv[1])[:3]
            return [(POLLEN[k][0], v, POLLEN[k][1]) for k, v in pol if k in POLLEN]
        chunk = POLLUTANTS[(page % 2) * 3 : (page % 2) * 3 + 3]
        return [(label, d.get(key), ref) for key, label, ref in chunk]

    def _pollutants(self, f: Frame, d: dict[str, Any], page: int) -> None:
        if self.settings.layout == "pollutants":
            n = 3 if d.get("pollen") else 2
            page %= n
        lab = to_rgb(self.settings.label_color)
        for k, (label, v, ref) in enumerate(self._rows(d, page)):
            y = 1 + k * 11
            f.text(1, y, label, lab)
            if v is None:
                f.text_right(30, y, "--", PALETTE["mute"])
                f.rect(1, y + 7, 30, 2, TRACK)
                continue
            r = v / ref if ref else 0.0
            c = ratio_color(r)
            val = fmt_val(v)
            if measure(label) + measure(val) + 3 > 30:
                val = f"{v:.0f}"
            f.text_right(30, y, val, WHITE)
            f.rect(1, y + 7, 30, 2, TRACK)
            f.rect(1, y + 7, max(1, round(min(1.0, r / 5.0) * 30)) if v > 0 else 0, 2, c)
            gx = 1 + round(30 / 5.0)  # the guideline tick (1×)
            f.set(gx, y + 6, scale(WHITE, 0.75))

    # uv: sun · big index · category · advice · today's strip ---------------------------------------------
    def _uv(self, f: Frame, d: dict[str, Any], page: int) -> None:
        uv = d.get("uv")
        lab = to_rgb(self.settings.label_color)
        if uv is None:
            f.text_center(10, "UV", lab)
            f.text_center(18, "NO DATA", PALETTE["mute"])
            return
        i, label, c = band(uv, UV_BANDS)
        cx, cy = 7, 8
        f.circle(cx, cy, 3, c)
        f.set(cx - 1, cy - 1, mix(c, WHITE, 0.6))
        for k in range(8):
            a = k * math.pi / 4
            for rr in (5, 6):
                f.set(
                    round(cx + rr * math.cos(a)),
                    round(cy + rr * math.sin(a)),
                    scale(c, 0.8 if rr == 5 else 0.45),
                )
        f.text(17, 1, "UV", lab)
        f.text_right(30, 4, f"{uv:.0f}", WHITE, font="big")
        f.text_center(17, label, c)
        f.text_center(23, UV_ADVICE[i], WHITE)
        hours = [x for x in (d.get("hourly") or {}).get("uv") or []][:24]
        x0 = 16 - len(hours) // 2
        for k, u in enumerate(hours):
            if u is None:
                continue
            _j, _l, hc = band(u, UV_BANDS)
            f.set(x0 + k, 30, scale(hc, 0.35 + 0.65 * min(1.0, u / 11.0)) if u > 0.05 else PALETTE["ink"])
        if hours:
            f.set(x0, 31, WHITE)

    # forecast: header · 24 hourly bars coloured by category ------------------------------------------------
    def _forecast(self, f: Frame, d: dict[str, Any], page: int) -> None:
        key = "eu_aqi" if self.settings.index == "eu" else "us_aqi"
        vals = list((d.get("hourly") or {}).get(key) or [])[:24]
        lab = to_rgb(self.settings.label_color)
        v = self.aqi(d)
        f.text(1, 1, "24H", lab)
        if v is not None:
            f.text_right(30, 1, f"{v:.0f}", band(v, self.bands)[2])
        nums = [x for x in vals if x is not None]
        if not nums:
            f.text_center(16, "NO DATA", PALETTE["mute"])
            return
        top = max(max(nums), self.bands[1][0])
        base, h = 26, 18
        x0 = 16 - len(vals) // 2
        for k, x in enumerate(vals):
            if x is None:
                continue
            _i, _l, c = band(x, self.bands)
            bh = max(1, round(x / top * h))
            f.vline(x0 + k, base - bh + 1, bh, scale(c, 0.55))
            f.set(x0 + k, base - bh + 1, c)
        f.set(x0, base - max(1, round((vals[0] or 0) / top * h)) + 1, WHITE)
        peak = max(range(len(vals)), key=lambda k: vals[k] or -1)
        hour0 = int(d.get("hour0") or 0)
        f.text(1, 28, "NOW", PALETTE["mute"])
        ptxt = f"{(hour0 + peak) % 24:02d}H"
        f.text_right(30, 28, ptxt, band(vals[peak] or 0, self.bands)[2])
        f.set(x0 + peak, base + 1, scale(WHITE, 0.6))

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        p = self._provider()
        d = (p.value if p is not None else None) or {}
        v = self.aqi(d) if d else None
        return {
            "index": self.index_label,
            "aqi": v,
            "category": band(v, self.bands)[1] if v is not None else None,
            "uv": d.get("uv"),
            "pm2_5": d.get("pm2_5"),
        }
