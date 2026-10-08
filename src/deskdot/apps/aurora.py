"""Aurora Watch — the planetary Kp index, a 3-day Kp chart with NOAA's forecast and a live aurora map.

Data: NOAA SWPC (providers/spaceweather.py). Kp 0–9 measures how disturbed Earth's magnetic field is; from Kp 5
it is a geomagnetic storm (G1–G5) and the aurora reaches lower latitudes. "Chance" is the OVATION nowcast's
probability of aurora seen from the panel's location.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, measure, mix, scale
from ..gfx.color import RGB
from ..gfx.worldmap import draw_world, project
from ..providers.spaceweather import THIRD, activity, short, storm_level
from . import _feed
from ._kit import MUTE, label

GREEN: RGB = (0, 230, 110)
TRACK: RGB = (52, 52, 68)


def kp_color(kp: float) -> RGB:
    """Quiet green → unsettled lime → active amber → storm red → severe magenta."""
    if kp < 3 - THIRD:
        return GREEN
    if kp < 4 - THIRD:
        return PALETTE["lime"]
    if kp < 5 - THIRD:
        return PALETTE["amber"]
    if kp < 7 - THIRD:
        return PALETTE["red"]
    return PALETTE["magenta"]


def kp_text(kp: float) -> str:
    """NOAA style: 2.33 -> '2+', 2.67 -> '3-', 3.0 -> '3'."""
    whole = round(kp)
    frac = kp - whole
    return f"{whole}{'+' if frac > 0.15 else '-' if frac < -0.15 else ''}"


class AuroraSettings(AppSettings):
    layout: str = Choice(
        "cycle",
        {"cycle": "Cycle all", "gauge": "Kp now", "chart": "3-day chart", "map": "Aurora map"},
        title="Layout",
    )
    rotate: int = Field(8, ge=3, le=60, title="Seconds per page")
    alert: bool = Field(True, title="Alert when Kp reaches the threshold")
    alert_kp: int = Field(
        5, ge=3, le=9, title="Alert at Kp", description="5 = G1 storm: aurora at lower latitudes"
    )


@register
class AuroraWatch(App):
    id = "aurora"
    name = "Aurora Watch"
    description = "Kp index, NOAA's 3-day forecast and the live aurora oval — with your chance of seeing it."
    icon = "sparkles"
    category = "data"
    Settings = AuroraSettings
    fps = 2.0
    uses = ("spaceweather",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._above: bool | None = None
        self._seen = -1.0

    def _alert(self, p: Any, d: dict[str, Any]) -> None:
        if not p.updated or p.updated == self._seen:
            return
        self._seen = p.updated
        above = d["kp"] >= self.settings.alert_kp - THIRD
        if self._above is False and above and self.settings.alert:
            self.ctx.notify(
                title=f"AURORA KP {kp_text(d['kp'])}",
                message=activity(d["kp"]),
                icon="star",
                color="#00e66e",
            )
        self._above = above

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "spaceweather")
        d = _feed.value_or_state(f, t, p, "AURORA", GREEN)
        if d is None:
            return
        self._alert(p, d)
        lay = self.settings.layout
        if lay == "cycle":
            views = ["gauge", "chart"] + (["map"] if d.get("oval") else [])
            lay = views[_feed.page(t, self.settings.rotate, len(views))]
        {"gauge": self._gauge, "chart": self._chart, "map": self._map}[lay](f, t, d)
        _feed.stale_dot(f, p)

    # Kp now: hero value, 9-step scale, activity word --------------------------------------------------
    def _gauge(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        kp = float(d["kp"])
        c = kp_color(kp)
        f.text(1, 1, "KP", MUTE)
        chance = d.get("chance")
        g = storm_level(kp)
        if g:
            f.text_right(30, 1, g, c)
        elif chance is not None:
            f.text_right(30, 1, f"{chance}%", GREEN if chance >= 10 else MUTE)
        txt = kp_text(kp)
        digit, suffix = txt[:-1] if txt[-1] in "+-" else txt, txt[-1] if txt[-1] in "+-" else ""
        w = measure(digit, "big")
        x = (32 - w - (4 if suffix else 0)) // 2
        f.text(x, 8, digit, c, "big")
        if suffix:  # NOAA writes thirds as 2+ / 3- : a small sign beside the big digit
            f.text(x + w + 1, 9, suffix, c, "small")
        for i in range(9):  # 9 cells x 3 px = 27 px + the end caps: one cell per Kp unit
            x = 2 + i * 3
            lit = kp >= i + 0.5
            cell = kp_color(i + 1)
            f.rect(x, 20, 2, 3, cell if lit else scale(cell, 0.22))
        label(f, 25, short(kp), c, t)

    # 3-day chart: 10 observed bars + 5 forecast bars, 2 px each -------------------------------------
    def _chart(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        obs = list(d.get("history") or [])[-10:]
        fc = [k for _ts, k in d.get("forecast") or []][:5]
        f.text(1, 1, "KP", MUTE)
        f.text_right(30, 1, "NEXT", (110, 110, 130))
        top, h = 8, 17
        for k in range(0, 10, 3):  # grid lines at Kp 0/3/6/9
            y = top + h - 1 - round(k / 9 * (h - 1))
            f.hline(1, y, 30, scale(TRACK, 0.6))
        bars = [(k, False) for k in obs] + [(k, True) for k in fc]
        x = 1
        for k, ahead in bars:
            bh = max(1, round(min(9.0, k) / 9 * h))
            c = kp_color(k)
            f.rect(x, top + h - bh, 2, bh, scale(c, 0.45) if ahead else c)
            x += 2
        now_x = 1 + 2 * len(obs)
        if fc and now_x < 31:
            f.vline(now_x, top - 1, h + 1, scale(PALETTE["white"], 0.55))
        peak = d.get("kp_max_24h")
        if peak is not None:
            label(f, 26, f"PEAK {kp_text(peak)}", kp_color(peak))
        else:
            label(f, 26, short(float(d["kp"])), kp_color(float(d["kp"])))

    # map: the auroral oval glowing over a dim world, you as a white dot ------------------------------
    def _map(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        f.text(1, 1, "AURORA", GREEN)
        y0 = 8
        draw_world(f, (44, 52, 70), None, y=y0)
        shimmer = 0.85 + 0.15 * math.sin(t * 2.0)
        for gy, row in enumerate(d.get("oval") or []):
            for gx, v in enumerate(row):
                if v >= 3:
                    k = min(1.0, v / 40) * shimmer
                    f.set(
                        gx, y0 + gy, scale(mix(GREEN, PALETTE["magenta"], min(1.0, v / 90)), 0.25 + 0.75 * k)
                    )
        lat, lon = d.get("lat"), d.get("lon")
        if lat is not None and lon is not None and int(t * 2) % 2 == 0:
            px, py = project(lat, lon)
            f.set(min(31, int(px)), y0 + min(15, int(py)), PALETTE["white"])
        chance = d.get("chance")
        if chance is not None:
            label(f, 26, f"SKY {chance}%", GREEN if chance >= 10 else MUTE)
        else:
            label(f, 26, short(float(d["kp"])), kp_color(float(d["kp"])))

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "spaceweather")
        d = (p.value if p is not None else None) or {}
        kp = d.get("kp")
        return {"kp": kp, "activity": activity(kp) if kp is not None else None, "chance": d.get("chance")}
