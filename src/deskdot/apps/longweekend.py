"""Long Weekend — days until the next 3+ day weekend made by a public holiday (Nager.Date, no key).

Shows the dates and length, and whether you'd need one day of leave ("bridge day") to get it. During a long
weekend it says so. Countries Nager.Date doesn't cover get a calm "not covered" screen.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from pydantic import Field, field_validator

from ..engine.app import App, AppSettings, register
from ..gfx import PALETTE, Frame, measure, scale
from ..gfx.color import RGB
from ..providers.longweekend import upcoming
from . import _feed
from ._kit import MUTE, empty, label

SEA: RGB = (0, 200, 255)
SAND: RGB = (255, 200, 90)
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def span(start: str, end: str) -> str:
    """'2026-12-24','2026-12-27' -> 'DEC 24-27'; across months 'DEC 31-JAN 2'."""
    a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if a.month == b.month:
        return f"{MONTHS[a.month - 1]} {a.day}-{b.day}"
    return f"{MONTHS[a.month - 1]} {a.day}-{MONTHS[b.month - 1]} {b.day}"


def palm(f: Frame, x: int, y: int, t: float) -> None:
    """A 9×9 palm tree swaying over a strip of sand."""
    sway = round(math.sin(t * 1.5))
    trunk = (150, 90, 30)
    for j in range(5):
        f.set(x + 4 + (sway if j < 2 else 0), y + 3 + j, trunk)
    leaf = (0, 200, 80)
    cx, cy = x + 4 + sway, y + 2
    for dx, dy in ((-3, 1), (-2, 0), (-1, -1), (1, -1), (2, 0), (3, 1), (0, -1), (-1, 0), (1, 0)):
        f.set(cx + dx, cy + dy, leaf)
    f.hline(x, y + 8, 9, scale(SAND, 0.7))


class LongWeekendSettings(AppSettings):
    country: str = Field(
        "",
        max_length=2,
        title="Country",
        description="Two-letter code (GB, US, DE, FR…). Empty = from your location",
    )
    bridges: bool = Field(True, title="Include ones that need a day of leave")

    @field_validator("country")
    @classmethod
    def _cc(cls, v: str) -> str:
        return "".join(ch for ch in v.upper() if ch.isalpha())[:2]


@register
class LongWeekend(App):
    id = "longweekend"
    name = "Long Weekend"
    description = (
        "Days until the next long weekend from public holidays — and when one day off makes it longer."
    )
    icon = "tree-palm"
    category = "time"
    Settings = LongWeekendSettings
    fps = 2.0
    uses = ("longweekend",)

    def on_start(self) -> None:
        p = _feed.provider(self.ctx, "longweekend")
        if p is not None:
            p.want(self.settings.country)

    def on_settings(self) -> None:
        self.on_start()

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "longweekend")
        d = _feed.value_or_state(f, t, p, "WEEKEND", SEA)
        if d is None:
            return
        if not d.get("supported"):
            empty(f, "NOT COVERED", d.get("country") or "")
            return
        today = dt.date.today()
        nxt = upcoming(d.get("weekends") or [], today, self.settings.bridges)
        if not nxt:
            empty(f, "NONE LEFT", str(today.year))
            return
        w = nxt[0]
        start = dt.date.fromisoformat(w["start"])
        days = (start - today).days
        f.text(1, 1, "LONG", SEA)
        f.text_right(30, 1, d.get("country") or "", MUTE)
        if days <= 0:
            palm(f, 11, 8, t)
            label(f, 19, "ENJOY IT!", SAND)
            left = (dt.date.fromisoformat(w["end"]) - today).days
            label(f, 26, f"{left + 1} DAY{'S' if left else ''} LEFT", MUTE)
            return
        txt = str(days)
        tw = measure(txt, "big")
        x = (32 - tw - 5) // 2
        f.text(x, 8, txt, PALETTE["white"], "big")
        f.text(x + tw + 2, 13, "D", MUTE)
        label(f, 19, f"{MONTHS[start.month - 1]} {start.day}", SAND)
        f.text(1, 26, f"{w['days']} DAYS", PALETTE["white"])
        if w["bridge"]:
            f.text_right(30, 26, "+1", PALETTE["amber"])  # one day of leave makes it
        _feed.stale_dot(f, p)

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "longweekend")
        d = (p.value if p is not None else None) or {}
        nxt = upcoming(d.get("weekends") or [], dt.date.today(), self.settings.bridges)
        return {"country": d.get("country"), "next": nxt[0] if nxt else None}
