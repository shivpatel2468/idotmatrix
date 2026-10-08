"""Rain Chance — "do I need an umbrella?": the chance of rain for the next 12 hours, hour by hour (Open-Meteo).

The hero is the highest chance in the window with the hour it peaks; twelve 2 px bars show each hour (taller and
bluer = likelier, a bright cap where real rain is expected). A dry window says so with a sun.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, register
from ..gfx import PALETTE, Frame, measure, mix, scale
from ..gfx.color import RGB
from ..gfx.icons import draw_icon
from . import _feed
from ._kit import MUTE, label

RAIN: RGB = (40, 140, 255)
DRY: RGB = (60, 60, 80)


def prob_color(p: float) -> RGB:
    return mix((70, 90, 130), RAIN, min(1.0, p / 70)) if p < 70 else mix(RAIN, PALETTE["cyan"], (p - 70) / 30)


class RainChanceSettings(AppSettings):
    hours: int = Field(12, ge=6, le=12, title="Hours ahead")
    dry_below: int = Field(20, ge=5, le=60, title="Call it dry below (%)")


@register
class RainChance(App):
    id = "rainchance"
    name = "Rain Chance"
    description = "The chance of rain for each of the next 12 hours, and when it peaks — umbrella or not."
    icon = "umbrella"
    category = "data"
    Settings = RainChanceSettings
    fps = 1.0
    uses = ("hourly",)

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "hourly")
        d = _feed.value_or_state(f, t, p, "RAIN", RAIN)
        if d is None:
            return
        hours = (d.get("hours") or [])[: self.settings.hours]
        probs = [h["prob"] or 0.0 for h in hours]
        if not probs:
            label(f, 12, "NO DATA", MUTE)
            return
        peak_i = max(range(len(probs)), key=lambda i: probs[i])
        peak = probs[peak_i]
        dry = peak < self.settings.dry_below
        f.text(1, 1, "RAIN", RAIN)
        f.text_right(30, 1, f"{len(hours)}H", MUTE)
        if dry:
            draw_icon(f, "sun", 3, 8, PALETTE["gold"], k=1)
            f.text(13, 9, "DRY", PALETTE["gold"], "small")
        else:
            txt = f"{peak:.0f}"
            w = measure(txt, "big") + 5
            x = (32 - w) // 2
            f.text(x, 7, txt, PALETTE["white"], "big")
            f.text(x + measure(txt, "big") + 1, 12, "%", MUTE)
        # 12 bars x 2 px, baseline y 28, up to 8 px tall; the peak hour is labelled under the hero
        base, tall = 29, 6
        bw = max(2, 24 // len(hours))
        x0 = (32 - bw * len(hours)) // 2
        for i, h in enumerate(hours):
            pr = probs[i]
            bh = max(1, round(pr / 100 * tall))
            c = prob_color(pr) if pr >= self.settings.dry_below else DRY
            f.rect(
                x0 + i * bw,
                base - bh + 1,
                bw - (1 if bw > 2 else 0) or 1,
                bh,
                c if i % 2 == 0 else scale(c, 0.8),
            )
            if (h.get("rain") or 0) >= 0.2:
                f.hline(x0 + i * bw, base - bh, bw - (1 if bw > 2 else 0) or 1, PALETTE["cyan"])
        f.hline(x0, base + 2, max(1, bw - 1), PALETTE["white"])  # "now"
        if not dry:
            hh = hours[peak_i]["h"]
            label(f, 18, f"AT {hh:02d}H" if peak_i else "NOW", prob_color(peak))
        else:
            label(f, 18, "NO RAIN", MUTE)
        _feed.stale_dot(f, p)

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "hourly")
        d = (p.value if p is not None else None) or {}
        hours = (d.get("hours") or [])[: self.settings.hours]
        return {"max_chance": max((h["prob"] or 0 for h in hours), default=None)}
