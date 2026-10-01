"""Calendar — the next meeting from your secret ICS links: a countdown ring, the title, and today's timeline.

Layouts: ``next`` (the edge ring fills over the last hour before the next event and drains while one is on;
a big countdown, the title as a marquee, and a strip of today's events with a "now" tick) and ``agenda`` (the
next three events: start time and countdown over a title marquee). With "take over" on, the app asks the
playlist for the screen a few minutes before an event starts.

Data: the `calendar` provider parses the ICS feeds itself (RRULE, EXDATE, TZID…, see `providers/calendar.py`).
Paste the "secret address in iCal format" (Google) or the published ICS link (Outlook) into the settings; the
links are never shown on the panel or in the status.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, Sprite, draw_marquee, measure, mix, scale
from ..gfx.color import RGB
from ..providers.calendar import day_bounds, split_urls
from ._kit import loading, offline, setup
from .timer import smooth_ring

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
DIM: RGB = PALETTE["dim"]
NOW_C: RGB = PALETTE["ember"]
CAL_COLORS: list[RGB] = [PALETTE["cyan"], PALETTE["magenta"], PALETTE["lime"], PALETTE["amber"]]
FPS = 8.0
SPEED = 8.0  # marquee px/s = 1 px per streamed frame (12 px/s at 8 fps stepped 1-2-1-2)
CAL_ICON = Sprite.parse(
    [
        ".#......#.",
        "##########",
        "##########",
        "#........#",
        "#.##.##..#",
        "#........#",
        "#.##.##..#",
        "#........#",
        "##########",
    ],
    {"#": PALETTE["cyan"]},
)


def countdown(sec: float) -> str:
    """'45M', '1H05', '9H', '2D'."""
    m = max(0, int(sec // 60))
    if m < 60:
        return f"{m}M"
    h, mm = divmod(m, 60)
    if h < 10:
        return f"{h}H{mm:02d}"
    if h < 48:
        return f"{h}H"
    return f"{h // 24}D"


class CalendarSettings(AppSettings):
    urls: str = Field(
        "",
        max_length=2000,
        title="ICS links",
        description="Secret iCal/ICS URLs (Google 'secret address in iCal format', Outlook 'published ICS'), "
        "one per line. They are never shown on the panel.",
    )
    layout: str = Choice("next", {"next": "Next meeting", "agenda": "Agenda"}, title="Layout")
    lookahead: int = Field(12, ge=1, le=72, title="Look ahead (hours)")
    all_day: bool = Field(False, title="Include all-day events")
    take_over: bool = Field(True, title="Take over before a meeting", json_schema_extra={"group": "Focus"})
    take_over_minutes: int = Field(
        5, ge=1, le=30, title="Minutes before", json_schema_extra={"group": "Focus"}
    )
    hour24: bool = Field(True, title="24-hour times")


@register
class Calendar(App):
    id = "calendar"
    name = "Calendar"
    description = (
        "Next meeting from your ICS calendars: countdown ring, scrolling title and today's timeline."
    )
    icon = "calendar-clock"
    category = "productivity"
    Settings = CalendarSettings
    fps = FPS
    uses = ("calendar",)

    # ------------------------------------------------------------------ data
    def _prov(self) -> Any:
        try:
            return self.ctx.provider("calendar")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._prov()
        if p is not None and hasattr(p, "want"):
            p.want(split_urls(self.settings.urls), self.settings.lookahead)

    def on_settings(self) -> None:
        self.on_start()

    def events(self, now: float) -> list[dict[str, Any]]:
        p = self._prov()
        d = p.value if p is not None else None
        if not d:
            return []
        horizon = now + self.settings.lookahead * 3600
        return [
            e
            for e in d.get("events", [])
            if e["end"] > now and e["start"] < horizon and (self.settings.all_day or not e.get("all_day"))
        ]

    def current_and_next(self, now: float) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        evs = self.events(now)
        cur = next((e for e in evs if e["start"] <= now < e["end"]), None)
        nxt = next((e for e in evs if e["start"] > now), None)
        return cur, nxt

    def _hm(self, ts: float) -> str:
        d = datetime.fromtimestamp(ts)
        return d.strftime("%H:%M") if self.settings.hour24 else f"{d.hour % 12 or 12}:{d.minute:02d}"

    # ---------------------------------------------------------------- focus
    def watches_focus(self) -> bool:
        return self.settings.take_over

    def wants_focus(self) -> bool:
        if not self.settings.take_over:
            return False
        now = time.time()
        _, nxt = self.current_and_next(now)
        return nxt is not None and nxt["start"] - now <= self.settings.take_over_minutes * 60

    # ---------------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        p = self._prov()
        d = p.value if p is not None else None
        if not split_urls(self.settings.urls) and not (d and d.get("events")):
            setup(f, "AGENDA", "ADD URL", CAL_COLORS[0], icon=CAL_ICON)
            return
        if d is None:
            if p is None or p.error:
                offline(f, "CAL", "OFFLINE")
            else:
                loading(f, t, "CAL", CAL_COLORS[0])
            return
        now = time.time()
        if self.settings.layout == "agenda":
            self._agenda(f, t, now)
        else:
            self._next(f, t, now)

    def _ring(self, f: Frame, frac: float, col: RGB) -> None:
        smooth_ring(f, frac, col, track=(16, 16, 24), tail=0.35, head=False)

    def _timeline(self, f: Frame, now: float, y: int) -> None:
        """Today 07:00–21:00 (widened to fit any event) as a 28 px strip of blocks, with a now tick."""
        d0, _ = day_bounds(now)
        p = self._prov()
        d = (p.value if p is not None else None) or {}
        # all of today's timed events, past ones included (events() only looks ahead from `now`)
        evs = [
            e
            for e in d.get("events", [])
            if e["end"] > d0 and e["start"] < d0 + 86400 and not e.get("all_day")
        ]
        lo, hi = d0 + 7 * 3600, d0 + 21 * 3600
        for e in evs:
            lo, hi = min(lo, max(d0, e["start"])), max(hi, min(d0 + 86400, e["end"]))
        span = hi - lo

        def x_of(ts: float) -> int:
            return 2 + round((ts - lo) / span * 27)

        f.hline(2, y + 1, 28, (44, 44, 60))  # the day's track, visible through the panel gamma
        for e in evs:
            col = CAL_COLORS[e.get("cal", 0) % len(CAL_COLORS)]
            x0, x1 = x_of(max(lo, e["start"])), x_of(min(hi, e["end"]))
            active = e["start"] <= now < e["end"]
            past = e["end"] <= now
            c = scale(col, 0.25) if past else (col if active else scale(col, 0.6))
            # the meeting on now stays visible beside the now tick, however short its part of the day is
            w = max(3 if active else 1, x1 - x0)
            f.rect(min(x0, 30 - w), y, w, 2, c)
        if lo <= now <= hi:
            f.vline(x_of(now), y - 1, 4, WHITE)

    def _next(self, f: Frame, t: float, now: float) -> None:
        cur, nxt = self.current_and_next(now)
        ev = cur or nxt
        if ev is None:
            self._ring(f, 0.0, DIM)
            f.text_center(6, "FREE", PALETTE["ok"], font="small")
            f.text_center(15, f"FOR {self.settings.lookahead}H", MUTE)
            self._timeline(f, now, 25)
            return
        col = CAL_COLORS[ev.get("cal", 0) % len(CAL_COLORS)]
        if cur is not None:
            total = cur["end"] - cur["start"]
            left = cur["end"] - now
            self._ring(f, left / total if total else 0, NOW_C)
            f.text_center(3, "NOW", NOW_C)
            f.text_center(10, countdown(left), WHITE, font="small")
            label_col = mix(col, WHITE, 0.2)
        else:
            left = ev["start"] - now
            self._ring(f, 1 - min(1.0, left / 3600), col)
            f.text_center(3, self._hm(ev["start"]), mix(col, WHITE, 0.3))
            soon = left <= self.settings.take_over_minutes * 60
            pulse = 0.6 + 0.4 * abs(((t * 2) % 2) - 1) if soon else 1.0
            f.text_center(10, countdown(left), scale(WHITE, pulse), font="small")
            label_col = col
        draw_marquee(f, ev["title"].upper(), t, 2, 19, 28, label_col, speed=SPEED)
        self._timeline(f, now, 25)

    def _agenda(self, f: Frame, t: float, now: float) -> None:
        """The next two events (time + countdown over a title marquee) and today's timeline."""
        evs = self.events(now)[:2]
        if not evs:
            f.text_center(8, "FREE", PALETTE["ok"], font="small")
            f.text_center(18, f"FOR {self.settings.lookahead}H", MUTE)
            self._timeline(f, now, 27)
            return
        for i, e in enumerate(evs):
            y = 1 + i * 13
            col = CAL_COLORS[e.get("cal", 0) % len(CAL_COLORS)]
            on = e["start"] <= now
            head = "NOW" if on else self._hm(e["start"])
            f.text(1, y, head, NOW_C if on else col)
            cd = countdown((e["end"] if on else e["start"]) - now)
            if measure(head) + measure(cd) + 3 <= 30:
                f.text_right(30, y, cd, MUTE)
            draw_marquee(
                f, e["title"].upper(), t, 1, y + 6, 30, WHITE if on else scale(WHITE, 0.85), speed=SPEED
            )
        self._timeline(f, now, 28)

    def status(self) -> dict[str, Any]:
        p = self._prov()
        d = p.value if p is not None else None
        now = time.time()
        cur, nxt = self.current_and_next(now)

        def brief(e: dict[str, Any] | None) -> dict[str, Any] | None:
            if not e:
                return None
            return {"title": e["title"][:80], "start": self._hm(e["start"]), "end": self._hm(e["end"])}

        return {
            "calendars": len(split_urls(self.settings.urls)),
            "errors": (d or {}).get("errors", []),
            "now": brief(cur),
            "next": brief(nxt),
            "next_in_min": round((nxt["start"] - now) / 60) if nxt else None,
            "upcoming": len(self.events(now)),
        }
