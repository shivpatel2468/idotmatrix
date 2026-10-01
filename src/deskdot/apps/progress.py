"""Progress — how far through the day, week, month, year, your life, or a custom event you are.

Layouts: ``bars`` (stacked rows: label, percentage, a bar each; pages when more than four are on), ``ring``
(one period as a thick ring with the percentage in big digits), ``dots`` (one period as a grid of its units:
the year as 12 rows of day dots, the month as a calendar, the week as seven columns, the day as 24 hour
cells, a life as one cell per year, an event as 100 cells). Everything is local wall-clock maths: no data.
"""

from __future__ import annotations

import calendar
import math
import time
from datetime import date, datetime, timedelta
from typing import Any, NamedTuple

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, fit, measure, mix, scale
from ..gfx.color import RGB

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
DIM: RGB = PALETTE["dim"]
TRACK: RGB = (26, 26, 38)
EMPTY: RGB = (14, 14, 22)
#: units still to come in the dots grids: dim but visible through the panel gamma, so the grid keeps its shape
FUTURE: RGB = (48, 48, 68)
COLORS: dict[str, RGB] = {
    "day": PALETTE["gold"],
    "week": PALETTE["mint"],
    "month": PALETTE["cyan"],
    "year": PALETTE["ember"],
    "life": PALETTE["violet"],
    "event1": PALETTE["magenta"],
    "event2": PALETTE["lime"],
}
MONTH_HUES: list[RGB] = [
    (60, 140, 255),
    (90, 110, 255),
    (0, 220, 160),
    (60, 230, 60),
    (150, 240, 0),
    (255, 214, 0),
    (255, 170, 0),
    (255, 110, 0),
    (255, 72, 24),
    (255, 40, 80),
    (200, 50, 200),
    (110, 70, 255),
]


class Period(NamedTuple):
    key: str
    label: str  # short, drawn in tiny type
    frac: float  # 0..1
    start: datetime
    end: datetime


def _frac(now: datetime, start: datetime, end: datetime) -> float:
    span = (end - start).total_seconds()
    if span <= 0:
        return 1.0 if now >= end else 0.0
    return max(0.0, min(1.0, (now - start).total_seconds() / span))


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)


class ProgressSettings(AppSettings):
    layout: str = Choice(
        "bars",
        {"bars": "Stacked bars", "ring": "Big ring", "dots": "Dots grid"},
        title="Layout",
        group="Layout",
    )
    focus: str = Choice(
        "year",
        {
            "day": "Day",
            "week": "Week",
            "month": "Month",
            "year": "Year",
            "life": "Life",
            "event1": "Event 1",
            "event2": "Event 2",
        },
        title="Ring / dots show",
        group="Layout",
    )
    decimals: int = Field(1, ge=0, le=2, title="Decimals", json_schema_extra={"group": "Layout"})
    page_seconds: int = Field(6, ge=2, le=60, title="Seconds per page", json_schema_extra={"group": "Layout"})
    show_day: bool = Field(True, title="Day", json_schema_extra={"group": "Bars"})
    show_week: bool = Field(True, title="Week", json_schema_extra={"group": "Bars"})
    show_month: bool = Field(True, title="Month", json_schema_extra={"group": "Bars"})
    show_year: bool = Field(True, title="Year", json_schema_extra={"group": "Bars"})
    show_life: bool = Field(False, title="Life", json_schema_extra={"group": "Bars"})
    show_events: bool = Field(True, title="Custom events", json_schema_extra={"group": "Bars"})
    week_start: str = Choice("mon", {"mon": "Monday", "sun": "Sunday"}, title="Week starts", group="Bars")
    birth_date: date = Field(date(1990, 1, 1), title="Birth date", json_schema_extra={"group": "Life"})
    life_years: int = Field(
        80, ge=30, le=120, title="Life expectancy (years)", json_schema_extra={"group": "Life"}
    )
    event1_on: bool = Field(False, title="Event 1 on", json_schema_extra={"group": "Events"})
    event1_label: str = Field(
        "PROJECT", max_length=12, title="Event 1 label", json_schema_extra={"group": "Events"}
    )
    event1_start: datetime = Field(
        datetime(2026, 7, 1), title="Event 1 start", json_schema_extra={"group": "Events"}
    )
    event1_end: datetime = Field(
        datetime(2026, 12, 31, 18), title="Event 1 end", json_schema_extra={"group": "Events"}
    )
    event2_on: bool = Field(False, title="Event 2 on", json_schema_extra={"group": "Events"})
    event2_label: str = Field(
        "TRIP", max_length=12, title="Event 2 label", json_schema_extra={"group": "Events"}
    )
    event2_start: datetime = Field(
        datetime(2026, 9, 1), title="Event 2 start", json_schema_extra={"group": "Events"}
    )
    event2_end: datetime = Field(
        datetime(2026, 10, 15), title="Event 2 end", json_schema_extra={"group": "Events"}
    )


def periods(now: datetime, s: ProgressSettings) -> dict[str, Period]:
    """Every period the settings can show, keyed by the `focus` ids."""
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    wd = now.weekday() if s.week_start == "mon" else (now.weekday() + 1) % 7
    week0 = day0 - timedelta(days=wd)
    month0 = day0.replace(day=1)
    month1 = (month0 + timedelta(days=32)).replace(day=1)
    year0 = day0.replace(month=1, day=1)
    year1 = year0.replace(year=year0.year + 1)
    b = s.birth_date
    life0 = datetime(b.year, b.month, b.day)
    e = _add_years(b, s.life_years)
    life1 = datetime(e.year, e.month, e.day)
    out = {
        "day": Period("day", now.strftime("%a").upper(), _frac(now, day0, day0 + timedelta(days=1)), day0,
                      day0 + timedelta(days=1)),
        "week": Period("week", f"W{now.isocalendar().week}", _frac(now, week0, week0 + timedelta(days=7)), week0,
                       week0 + timedelta(days=7)),
        "month": Period("month", now.strftime("%b").upper(), _frac(now, month0, month1), month0, month1),
        "year": Period("year", str(now.year), _frac(now, year0, year1), year0, year1),
        "life": Period("life", "LIFE", _frac(now, life0, life1), life0, life1),
    }  # fmt: skip
    for k in ("event1", "event2"):
        st, en = getattr(s, f"{k}_start"), getattr(s, f"{k}_end")
        st, en = st.replace(tzinfo=None), en.replace(tzinfo=None)
        label = (getattr(s, f"{k}_label") or k.upper()).upper()
        out[k] = Period(k, label, _frac(now, st, en), st, en)
    return out


def left_text(p: Period, now: datetime) -> str:
    """Compact time remaining: '4H48', '2D', '98D', '44Y', 'IN 3D', 'DONE'."""
    if now < p.start:
        d = (p.start - now).days
        return f"IN {d}D" if d else "SOON"
    sec = (p.end - now).total_seconds()
    if sec <= 0:
        return "DONE"
    if sec < 86400:
        h, m = divmod(int(sec // 60), 60)
        return f"{h}H" if h >= 10 else f"{h}H{m:02d}" if h else f"{m}M"
    days = sec / 86400
    return f"{days / 365.2425:.0f}Y" if days >= 730 else f"{days:.0f}D"


def pct_text(frac: float, decimals: int) -> str:
    v = frac * 100
    if decimals and v < 100:
        return f"{math.floor(v * 10**decimals) / 10**decimals:.{decimals}f}%"
    return f"{math.floor(v)}%"


# ring geometry: a 3 px annulus around the centre, angle measured clockwise from 12 o'clock
_YY, _XX = np.mgrid[0:32, 0:32].astype(np.float32)
_DIST = np.hypot(_XX - 15.5, _YY - 15.5)
_ANG = (np.degrees(np.arctan2(_XX - 15.5, -(_YY - 15.5))) % 360.0) / 360.0
_RING = (_DIST >= 13.1) & (_DIST <= 15.6)


@register
class Progress(App):
    id = "progress"
    name = "Progress"
    description = "Day, week, month, year, life and custom-event progress as bars, a big ring or a dots grid."
    icon = "hourglass"
    category = "time"
    Settings = ProgressSettings
    fps = 1.0

    def _now(self) -> datetime:
        return datetime.now()

    def _enabled(self, ps: dict[str, Period]) -> list[Period]:
        s = self.settings
        keys = [k for k in ("day", "week", "month", "year", "life") if getattr(s, f"show_{k}")]
        if s.show_events:
            keys += [k for k in ("event1", "event2") if getattr(s, f"{k}_on")]
        return [ps[k] for k in keys] or [ps["year"]]

    def render(self, f: Frame, t: float) -> None:
        now = self._now()
        ps = periods(now, self.settings)
        layout = self.settings.layout
        if layout == "bars":
            self._bars(f, t, self._enabled(ps))
        elif layout == "ring":
            self._ring(f, ps[self.settings.focus])
        else:
            getattr(self, f"_dots_{self.settings.focus.rstrip('12')}")(f, now, ps[self.settings.focus])

    # ------------------------------------------------------------------ bars
    def _bars(self, f: Frame, t: float, rows: list[Period]) -> None:
        per = 4
        pages = [rows[i : i + per] for i in range(0, len(rows), per)]
        page = pages[int(t // self.settings.page_seconds) % len(pages)]
        n = len(page)
        pitch, bar_h = (8, 1) if n == 4 else (10, 2) if n == 3 else (15, 3) if n == 2 else (16, 4)
        top = 1 if n >= 3 else (4 if n == 2 else 8)
        for i, p in enumerate(page):
            y = top + i * pitch
            col = COLORS[p.key]
            pct = pct_text(p.frac, self.settings.decimals)
            label_room = 30 - measure(pct) - 3
            if label_room < measure(p.label):
                pct = pct_text(p.frac, 0)
                label_room = 30 - measure(pct) - 3
            f.text(1, y, fit(p.label, label_room), mix(col, WHITE, 0.25))
            f.text_right(30, y, pct, WHITE)
            self._bar(f, 1, y + 6, 30, bar_h, p.frac, col)
        if len(pages) > 1 and n < 4:
            for q in range(len(pages)):
                f.set(15 - len(pages) + q * 2, 31, WHITE if pages[q] is page else DIM)

    @staticmethod
    def _bar(f: Frame, x: int, y: int, w: int, h: int, frac: float, col: RGB) -> None:
        f.rect(x, y, w, h, TRACK)
        exact = w * frac
        full = int(exact)
        for i in range(full):
            f.vline(x + i, y, h, scale(col, 0.55 + 0.45 * (i / max(1, w - 1))))
        rem = exact - full
        if full < w and rem > 0.05:
            f.vline(x + full, y, h, scale(col, 0.2 + 0.6 * rem))

    # ------------------------------------------------------------------ ring
    def _ring(self, f: Frame, p: Period) -> None:
        col = np.array(COLORS[p.key], np.float32)
        lit = _RING & (p.frac > _ANG)
        k = (0.5 + 0.5 * (_ANG / max(p.frac, 1e-3)))[..., None]  # the start of the arc stays visible
        f.px[_RING] = TRACK
        f.px[lit] = (col * k).clip(0, 255).astype(np.uint8)[lit]
        if 0 < p.frac < 1:  # a bright head where the ring ends
            a = p.frac * math.tau
            for r in (13.6, 14.8):
                f.set(round(15.5 + math.sin(a) * r - 0.5), round(15.5 - math.cos(a) * r - 0.5), WHITE)
        f.text_center(6, fit(p.label, 17), mix(COLORS[p.key], WHITE, 0.3))
        digits = str(min(100, math.floor(p.frac * 100)))
        wd = measure(digits, "big")
        x = (32 - wd - 4) // 2
        f.text(x, 12, digits, WHITE, font="big")
        f.text(x + wd + 1, 12, "%", MUTE)
        f.text_center(23, left_text(p, self._now()), MUTE)

    # ------------------------------------------------------------------ dots
    def _header(self, f: Frame, p: Period) -> None:
        pct = pct_text(p.frac, self.settings.decimals)
        room = 30 - measure(pct) - 3
        if room < measure(p.label):
            pct = pct_text(p.frac, 0)
            room = 30 - measure(pct) - 3
        f.text(1, 1, fit(p.label, room), mix(COLORS[p.key], WHITE, 0.25))
        f.text_right(30, 1, pct, WHITE)

    def _dots_year(self, f: Frame, now: datetime, p: Period) -> None:
        self._header(f, p)
        today = now.date()
        for m in range(12):
            y = 8 + m * 2
            days = calendar.monthrange(now.year, m + 1)[1]
            hue = MONTH_HUES[m]
            for d in range(days):
                dd = date(now.year, m + 1, d + 1)
                if dd < today:
                    c = hue
                elif dd == today:
                    c = WHITE
                else:
                    c = scale(hue, 0.3)
                f.set(d, y, c)

    def _dots_month(self, f: Frame, now: datetime, p: Period) -> None:
        self._header(f, p)
        first = now.replace(day=1)
        offset = first.weekday() if self.settings.week_start == "mon" else (first.weekday() + 1) % 7
        days = calendar.monthrange(now.year, now.month)[1]
        pitch, top = 4, 8
        col = COLORS["month"]
        for d in range(days):
            cell = offset + d
            x = 2 + (cell % 7) * 4
            y = top + (cell // 7) * pitch
            if d + 1 < now.day:
                c = scale(col, 0.75)
            elif d + 1 == now.day:
                c = WHITE
            else:
                c = FUTURE
            weekend = (cell % 7) in ((5, 6) if self.settings.week_start == "mon" else (0, 6))
            if weekend and d + 1 != now.day:
                c = scale(col, 0.45) if d + 1 < now.day else (70, 44, 62)
            f.rect(x, y, 3, 3, c)

    def _dots_week(self, f: Frame, now: datetime, p: Period) -> None:
        self._header(f, p)
        wd = now.weekday() if self.settings.week_start == "mon" else (now.weekday() + 1) % 7
        weekend = (5, 6) if self.settings.week_start == "mon" else (0, 6)
        day_frac = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 86400
        col = COLORS["week"]
        top, h = 8, 20
        for i in range(7):
            x = 2 + i * 4
            c = mix(col, PALETTE["ember"], 0.6) if i in weekend else col
            f.rect(x, top, 3, h, FUTURE)
            fill = h if i < wd else round(h * day_frac) if i == wd else 0
            if fill:
                f.rect(x, top + h - fill, 3, fill, scale(c, 0.8))
                if i == wd:
                    f.hline(x, top + h - fill, 3, WHITE)
            f.hline(x, 30, 3, WHITE if i == wd else scale(c, 0.35))

    def _dots_day(self, f: Frame, now: datetime, p: Period) -> None:
        self._header(f, p)
        col = COLORS["day"]
        for h in range(24):
            x = 1 + (h % 6) * 5
            y = 9 + (h // 6) * 5
            if h < now.hour:
                c = mix((255, 110, 0), col, h / 23) if 6 <= h < 18 else scale(PALETTE["sky"], 0.7)
                f.rect(x, y, 4, 4, c)
            elif h == now.hour:
                f.rect(x, y, 4, 4, FUTURE)
                fill = max(1, round(4 * now.minute / 60))
                f.rect(x, y + 4 - fill, 4, fill, WHITE)
            else:
                f.rect(x, y, 4, 4, FUTURE)

    def _dots_life(self, f: Frame, now: datetime, p: Period) -> None:
        self._header(f, p)
        years = self.settings.life_years
        age = (now - p.start).total_seconds() / (365.2425 * 86400)
        cols = 10
        rows = math.ceil(years / cols)
        pitch = 3 if rows <= 8 else 2
        size = 2 if pitch == 3 else 1
        x0 = (32 - (cols * pitch - (pitch - size))) // 2
        col = COLORS["life"]
        for i in range(years):
            x = x0 + (i % cols) * pitch
            y = 8 + (i // cols) * pitch
            if i + 1 <= age:
                c = mix(col, PALETTE["magenta"], i / max(1, years - 1))
            elif i < age:
                c = WHITE
            else:
                c = FUTURE
            f.rect(x, y, size, size, c)

    def _dots_event(self, f: Frame, now: datetime, p: Period) -> None:
        self._header(f, p)
        done = math.floor(p.frac * 100)
        col = COLORS[p.key]
        for i in range(100):
            x = 6 + (i % 10) * 2
            y = 9 + (i // 10) * 2
            c = (
                scale(col, 0.5 + 0.5 * (i / 99))
                if i < done
                else (WHITE if i == done and done < 100 else FUTURE)
            )
            f.set(x, y, c)

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        ps = periods(self._now(), self.settings)
        return {p.key: round(p.frac * 100, 2) for p in self._enabled(ps)} | {"epoch": round(time.time())}
