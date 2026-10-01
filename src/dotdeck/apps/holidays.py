"""Holidays — countdown to the next public holiday, a list, a month calendar and a celebration on the day.

The country comes from the setting or the panel's location (``hub.location()``). All four screens are
deterministic loops for a given day, so they are baked as clips and re-baked when the date or the data change.
Festive icons (lamp, fireworks, tree, flag, crescent, colours, wheel, star, confetti) are drawn in code and
picked from the holiday's name in "auto" mode.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import math
import re
from collections.abc import Callable
from typing import Any

import numpy as np
from pydantic import Field, field_validator

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale, to_rgb
from ..gfx.color import RGB
from ._kit import loading, offline

WHITE: RGB = (255, 255, 255)
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
ICON = 11  # festive icons are 11×11
FPS = 10.0  # every animated screen is baked at the panel's fastest verified clip rate
SPEED = 10.0  # marquee px/s: exactly 1 px per frame at FPS, so names glide instead of stepping 1-2-1-1-2
UNIT = (
    4.4  # icon screens loop in multiples of this: 44 frames, so the 11-row confetti falls 1 row per 4 frames
)

# ---------------------------------------------------------------------------- festive icons
# Each icon draws into (x, y) .. (x+10, y+10) as a function of the loop phase `ph` (0..1, integer cycles).
Painter = Callable[[Frame, int, int, float, RGB], None]


def _plot(f: Frame, x: int, y: int, c: RGB) -> None:
    if 0 <= x < 32 and 0 <= y < 32:
        f.px[y, x] = np.maximum(f.px[y, x], np.asarray(c, dtype=np.uint8))


def icon_diya(f: Frame, x: int, y: int, ph: float, accent: RGB) -> None:
    """Oil lamp with a flickering flame (Diwali, Navratri, Gurpurab…)."""
    bowl = [
        "...........",
        "...........",
        "#.........#",
        "##.......##",
        ".#########.",
        "..#######..",
        "....###....",
    ]
    for j, row in enumerate(bowl):
        for i, ch in enumerate(row):
            if ch == "#":
                f.set(x + i, y + 4 + j, mix((200, 70, 0), (255, 150, 0), j / 6))
    f.hline(x + 2, y + 6, 7, (120, 40, 0))
    flick = 0.5 + 0.5 * math.sin(ph * 2 * math.pi * 3)
    sway = round(math.sin(ph * 2 * math.pi * 2))
    top = y + (0 if flick > 0.5 else 1)
    f.vline(x + 5, top + 2, 4 - (top - y), PALETTE["amber"])
    f.set(x + 5 + sway, top + 1, PALETTE["gold"])
    f.set(x + 5, top, mix(PALETTE["gold"], WHITE, 0.5 * flick))
    f.set(x + 5, y + 5, WHITE)


def icon_fireworks(f: Frame, x: int, y: int, ph: float, accent: RGB) -> None:
    bursts = ((5, 4, 0.0, accent), (2, 7, 0.33, PALETTE["magenta"]), (8, 7, 0.66, PALETTE["cyan"]))
    for bx, by, off, c in bursts:
        p = (ph * 2 + off) % 1.0
        if p < 0.2:  # the rocket rising
            f.set(x + bx, y + 10 - round(p / 0.2 * (10 - by)), scale(PALETTE["gold"], 0.8))
            continue
        q = (p - 0.2) / 0.8
        r = 1 + q * 4
        k = (1 - q) ** 1.2
        for a in range(8):
            ang = a * math.pi / 4
            _plot(f, x + bx + round(r * math.cos(ang)), y + by + round(r * math.sin(ang)), scale(c, k))
        _plot(f, x + bx, y + by, scale(WHITE, k))


def icon_confetti(f: Frame, x: int, y: int, ph: float, accent: RGB) -> None:
    cols = (accent, PALETTE["magenta"], PALETTE["cyan"], PALETTE["lime"], PALETTE["gold"], PALETTE["violet"])
    for k in range(9):
        cx = (k * 5 + 2) % 11
        speed = 1 + k % 2
        cy = (
            k * 7 + int(ph * 11 * speed + 1e-6)
        ) % 11  # floor, not round: round() is half-to-even, 4-4-3-5 steps
        f.set(x + cx, y + cy, cols[k % len(cols)])
        if k % 3 == 0:
            f.set(x + cx + (1 if (ph * 4 + k) % 2 < 1 else -1), y + cy, scale(cols[k % len(cols)], 0.5))


def icon_star(f: Frame, x: int, y: int, ph: float, accent: RGB) -> None:
    rows = [
        ".....#.....",
        "....###....",
        "###########",
        ".#########.",
        "..#######..",
        "..###.###..",
        ".##.....##.",
    ]
    k = 0.8 + 0.2 * math.sin(ph * 2 * math.pi)  # a glow, not a fade to black
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == "#":
                f.set(x + i, y + 2 + j, scale(mix(accent, WHITE, 0.2 if j < 2 else 0.0), k))
    for sx, sy, off in ((0, 0, 0.0), (10, 1, 0.5), (1, 10, 0.25), (10, 10, 0.75)):
        if ((ph + off) % 1.0) < 0.3:
            f.set(x + sx, y + sy, WHITE)


def icon_tree(f: Frame, x: int, y: int, ph: float, accent: RGB) -> None:
    green = (0, 170, 60)
    for j in range(8):
        half = j // 2 + (j % 2)
        f.hline(x + 5 - half, y + 1 + j, 2 * half + 1, scale(green, 0.7 + 0.3 * (j % 2)))
    f.rect(x + 4, y + 9, 3, 2, (130, 60, 10))
    f.set(x + 5, y, PALETTE["gold"])
    lights = ((5, 3), (3, 5), (7, 5), (2, 8), (5, 7), (8, 8))
    cols = (PALETTE["red"], PALETTE["gold"], PALETTE["cyan"], PALETTE["magenta"])
    for i, (lx, ly) in enumerate(lights):
        on = int(ph * 4 + i) % 2 == 0
        f.set(x + lx, y + ly, cols[i % 4] if on else scale(cols[i % 4], 0.3))


def icon_flag(f: Frame, x: int, y: int, ph: float, accent: RGB, india: bool = False) -> None:
    f.vline(x, y, 11, PALETTE["mute"])
    stripes = ((255, 110, 0), (230, 230, 230), (0, 170, 60)) if india else (accent, WHITE, accent)
    for i in range(1, 11):
        dy = round(math.sin(ph * 2 * math.pi * 2 - i * 0.7) * 0.9)
        for s, c in enumerate(stripes):
            f.rect(x + i, y + 1 + dy + s * 2, 1, 2, scale(c, 0.8 + 0.2 * ((i + s) % 2)))
    if india:
        dy = round(math.sin(ph * 2 * math.pi * 2 - 5 * 0.7) * 0.9)
        f.set(x + 5, y + 3 + dy, (20, 40, 200))
        f.set(x + 6, y + 3 + dy, (20, 40, 200))


def icon_crescent(f: Frame, x: int, y: int, ph: float, accent: RGB) -> None:
    moon = (255, 230, 150)
    for j in range(11):
        for i in range(11):
            d1 = (i - 4.5) ** 2 + (j - 5) ** 2
            d2 = (i - 6.5) ** 2 + (j - 4) ** 2
            if d1 <= 20 and d2 > 16:
                f.set(x + i, y + j, moon)
    k = 0.5 + 0.5 * math.sin(ph * 2 * math.pi * 2)
    c = mix(scale(PALETTE["gold"], 0.5), WHITE, k)
    f.set(x + 9, y + 3, c)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        f.set(x + 9 + dx, y + 3 + dy, scale(PALETTE["gold"], 0.35 + 0.5 * k))


def icon_holi(f: Frame, x: int, y: int, ph: float, accent: RGB) -> None:
    cols = (PALETTE["magenta"], PALETTE["lime"], PALETTE["cyan"], PALETTE["gold"], PALETTE["violet"])
    centres = ((3, 3), (8, 4), (5, 8))
    for n, (cx, cy) in enumerate(centres):
        p = (ph * 2 + n / 3) % 1.0
        r = 1 + p * 3
        c = cols[(n + int(ph * 2 + n / 3)) % len(cols)]
        for a in range(10):
            ang = a * math.pi / 5 + n
            _plot(
                f, x + cx + round(r * math.cos(ang)), y + cy + round(r * math.sin(ang)), scale(c, 1 - p * 0.7)
            )
        _plot(f, x + cx, y + cy, c)


def icon_wheel(f: Frame, x: int, y: int, ph: float, accent: RGB) -> None:
    """A spinning wheel (charkha)."""
    cx, cy, r = x + 5, y + 5, 4.6
    rim = (200, 140, 60)
    for a in range(24):
        ang = a * math.pi / 12
        f.set(cx + round(r * math.cos(ang)), cy + round(r * math.sin(ang)), rim)
    rot = ph * math.pi / 3  # one spoke step per loop -> seamless
    for s in range(6):
        ang = rot + s * math.pi / 3
        for rr in (1.5, 2.5, 3.5):
            f.set(cx + round(rr * math.cos(ang)), cy + round(rr * math.sin(ang)), scale(accent, 0.85))
    f.set(cx, cy, WHITE)


ICONS: dict[str, Painter] = {
    "diya": icon_diya,
    "fireworks": icon_fireworks,
    "confetti": icon_confetti,
    "star": icon_star,
    "tree": icon_tree,
    "flag": icon_flag,
    "crescent": icon_crescent,
    "holi": icon_holi,
    "wheel": icon_wheel,
}

AUTO_RULES: list[tuple[str, str]] = [
    (
        r"diwali|deepavali|navratri|durga|karva|chhat|bhai|dhanteras|lohri|gurpurab|guru nanak|lamp|hanukkah",
        "diya",
    ),
    (r"christmas|xmas", "tree"),
    (r"new year|nowruz|dussehra|vijaya|guy fawkes|bonfire|fireworks", "fireworks"),
    (
        r"independence|republic|national|liberation|unity|constitution|flag|federation|victory|statehood",
        "flag",
    ),
    (r"eid|ramadan|ramzan|muharram|milad|bakri|ashura|islamic|hijri|isra", "crescent"),
    (r"holi|color|colour", "holi"),
    (r"gandhi", "wheel"),
]


# celebration sparkles in the side columns: (x, y, phase offset), fixed so the loop is deterministic
SPARKLES = (
    (1, 8, 0.0),
    (3, 15, 0.45),
    (1, 21, 0.8),
    (29, 7, 0.3),
    (30, 13, 0.7),
    (28, 20, 0.15),
    (2, 11, 0.6),
    (30, 23, 0.9),
)


def auto_icon(name: str) -> str:
    n = name.lower()
    for pat, icon in AUTO_RULES:
        if re.search(pat, n):
            return icon
    return "star"


def clean_name(name: str) -> str:
    """'Chhat Puja (Pratihar Sashthi/Surya Sashthi)' -> 'CHHAT PUJA'."""
    s = re.sub(r"\s*\([^)]*\)", "", name).strip()
    return (s or name).upper()


def days_text(days: int) -> str:
    return "TODAY" if days == 0 else "TMRW" if days == 1 else f"{days}D"


# --------------------------------------------------------------------------- settings
class HolidaysSettings(AppSettings):
    country: str = Field(
        "",
        max_length=2,
        title="Country code",
        description="ISO code such as IN, US, DE. Blank = the country of your location",
        json_schema_extra={"group": "Data"},
    )
    observances: bool = Field(
        False,
        title="Include observances",
        description="Also show observances and regional-only days",
        json_schema_extra={"group": "Data"},
    )
    layout: str = Choice(
        "countdown",
        {"countdown": "Countdown", "list": "List", "calendar": "Month calendar"},
        title="Layout",
        group="Layout",
    )
    count: int = Field(4, ge=1, le=8, title="Holidays in the list", json_schema_extra={"group": "Layout"})
    celebrate: bool = Field(True, title="Celebrate on the day", json_schema_extra={"group": "Layout"})
    icon: str = Choice(
        "auto",
        {
            "auto": "Auto (by holiday)",
            "fireworks": "Fireworks",
            "confetti": "Confetti",
            "diya": "Lamp",
            "star": "Star",
            "none": "None",
        },
        title="Festive icon",
        group="Colours",
    )
    accent: Color = Field("#ffaa00", title="Accent", json_schema_extra={"group": "Colours"})
    text_color: Color = Field("#ffffff", title="Name colour", json_schema_extra={"group": "Colours"})

    @field_validator("country")
    @classmethod
    def _cc(cls, v: str) -> str:
        v = v.strip().upper()
        if v and not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError("a two-letter ISO country code, or blank")
        return v


# --------------------------------------------------------------------------- the app
@register
class Holidays(App):
    id = "holidays"
    name = "Holidays"
    description = (
        "Countdown to the next public holiday, a list, a month calendar and a celebration on the day."
    )
    icon = "party-popper"
    category = "time"
    Settings = HolidaysSettings
    fps = 2.0
    uses = ("holidays",)
    clip_fps = 10.0
    clip_colors = 64

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.on_settings()

    def on_settings(self) -> None:
        self._cache: dict[str, tuple[Any, Any]] = {}
        self.on_start()

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(self.settings.country)

    def _provider(self) -> Any:
        try:
            return self.ctx.provider("holidays")
        except KeyError:
            return None

    # ------------------------------------------------------------ data
    def _entry(self) -> tuple[Any, dict[str, Any] | None]:
        p = self._provider()
        v = (p.value if p is not None else None) or {}
        return p, v.get(self.settings.country)

    def upcoming(self, today: dt.date | None = None) -> list[dict[str, Any]]:
        """Holidays from today on, with `days` until each (observances only when enabled)."""
        _p, e = self._entry()
        if not e:
            return []
        today = today or dt.date.today()
        key = (id(e), e.get("fetched"), today)
        hit = self._cache.get("ups")
        if hit and hit[0] == key:
            return hit[1]  # type: ignore[no-any-return]
        out = []
        for h in e["holidays"]:
            if not (h.get("public", True) or self.settings.observances):
                continue
            d = dt.date.fromisoformat(h["date"])
            if d >= today:
                out.append({**h, "d": d, "days": (d - today).days, "label": clean_name(h["name"])})
        self._cache["ups"] = (key, out)
        return out

    def icon_for(self, name: str) -> str:
        return auto_icon(name) if self.settings.icon == "auto" else self.settings.icon

    def draw_icon(self, f: Frame, kind: str, x: int, y: int, ph: float, big: bool = False) -> None:
        if kind == "none" or kind not in ICONS:
            return
        accent = to_rgb(self.settings.accent)
        india = self._country() == "IN"
        target = Frame() if big else f
        ox, oy = (0, 0) if big else (x, y)
        if kind == "flag":
            icon_flag(target, ox, oy, ph, accent, india)
        else:
            ICONS[kind](target, ox, oy, ph, accent)
        if big:  # 2× nearest-neighbour: 22×22
            src = np.kron(target.px[:ICON, :ICON], np.ones((2, 2, 1), dtype=np.uint8))
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(32, x + 2 * ICON), min(32, y + 2 * ICON)
            if x1 > x0 and y1 > y0:
                sub = src[y0 - y : y1 - y, x0 - x : x1 - x]
                lit = sub.any(axis=2)
                f.px[y0:y1, x0:x1][lit] = sub[lit]

    def _country(self) -> str:
        _p, e = self._entry()
        return str((e or {}).get("country") or self.settings.country)

    # ------------------------------------------------------------ loop timing
    def _marquee_s(self, text: str, w: int = 30) -> float:
        tw = measure(text)
        return 1.2 + (tw + 12) / SPEED if tw > w else 0.0

    @staticmethod
    def _icon_loop(seconds: float) -> float:
        """The shortest whole number of UNITs that holds `seconds` (a full marquee pass)."""
        return round(UNIT * max(1, math.ceil(seconds / UNIT - 1e-9)), 6)

    def _plan(self) -> dict[str, Any]:
        """Deterministic loop plan for today: which screen, loop length, fps, list pages."""
        ups = self.upcoming()
        hit = self._cache.get("plan")
        if hit and hit[0] is ups:
            return hit[1]  # type: ignore[no-any-return]
        plan = self._make_plan(ups)
        self._cache["plan"] = (ups, plan)
        return plan

    def _make_plan(self, ups: list[dict[str, Any]]) -> dict[str, Any]:
        lay = self.settings.layout
        if not ups:
            return {"screen": "empty", "loop": 2.0, "fps": 2.0, "ups": ups}
        nxt = ups[0]
        if nxt["days"] == 0 and self.settings.celebrate and lay != "calendar":
            loop = self._icon_loop(self._marquee_s(nxt["label"]))
            return {"screen": "celebrate", "loop": loop, "fps": FPS, "ups": ups}
        if lay == "list":
            items = ups[: self.settings.count]
            pages, lens = [], []
            for i in range(0, len(items), 2):  # keep the loop under ~30 s (<= 180 frames at 6 fps)
                pg = items[i : i + 2]
                ln = math.ceil(max(3.0, *(self._marquee_s(h["label"]) for h in pg)) * 2) / 2
                if pages and sum(lens) + ln > 24:  # <= 240 frames: one GIF under the 40 KB budget
                    break
                pages.append(pg)
                lens.append(ln)
            return {"screen": "list", "loop": sum(lens), "fps": FPS, "ups": ups, "pages": pages, "lens": lens}
        if lay == "calendar":
            return {"screen": "calendar", "loop": 2.0, "fps": 2.0, "ups": ups}
        loop = self._icon_loop(self._marquee_s(nxt["label"]))
        return {"screen": "countdown", "loop": loop, "fps": FPS, "ups": ups}

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        p, e = self._entry()
        if e is None:
            if p is not None and p.error:
                offline(f, "HOLIDAYS", "OFFLINE")
            else:
                loading(f, t, "HOLIDAYS", to_rgb(self.settings.accent))
            return
        plan = self._plan()
        t = (t + 1e-6) % plan[
            "loop"
        ]  # the epsilon keeps int(px) from flooring 0.9999 onto the previous pixel
        ph = t / plan["loop"]
        {
            "empty": self._empty,
            "celebrate": self._celebrate,
            "list": self._list,
            "calendar": self._calendar,
            "countdown": self._countdown,
        }[plan["screen"]](f, t, ph, plan)

    def _empty(self, f: Frame, t: float, ph: float, plan: dict[str, Any]) -> None:
        f.text_center(10, "NO", PALETTE["mute"])
        f.text_center(17, "HOLIDAYS", PALETTE["mute"])
        f.text_center(25, self._country(), PALETTE["dim"])

    # countdown: date · big days + icon · DAYS · name marquee -----------------------------------------
    def _countdown(self, f: Frame, t: float, ph: float, plan: dict[str, Any]) -> None:
        h = plan["ups"][0]
        accent = to_rgb(self.settings.accent)
        d: dt.date = h["d"]
        date = f"{d.day} {MONTHS[d.month - 1]}"
        f.text(1, 1, date, PALETTE["mute"])
        cc = self._country()
        if measure(date) + measure(cc) + 3 <= 30:
            f.text_right(30, 1, cc, PALETTE["dim"])
        kind = self.icon_for(h["name"])
        num = str(h["days"])
        has_icon = kind != "none"
        room = 17 if has_icon else 30
        font = "big" if measure(num, "big") <= room else "small"
        nx = 1 if has_icon else 1 + (30 - measure(num, font)) // 2
        f.text(nx, 8 if font == "big" else 10, num, WHITE, font=font)
        unit = "DAY" if h["days"] == 1 else "DAYS" if h["days"] != 0 else "TODAY"
        f.text(1, 20, unit, accent)
        if measure(unit) + measure(DAYS[d.weekday()]) + 3 <= 30:
            f.text_right(30, 20, DAYS[d.weekday()], scale(accent, 0.6))
        if has_icon:
            self.draw_icon(f, kind, 20, 7, ph)
        draw_marquee(f, h["label"], t, 1, 26, 30, to_rgb(self.settings.text_color), speed=SPEED)

    # celebration: TODAY · 22×22 icon · name marquee · sparkles ---------------------------------------------
    def _celebrate(self, f: Frame, t: float, ph: float, plan: dict[str, Any]) -> None:
        h = plan["ups"][0]
        accent = to_rgb(self.settings.accent)
        kind = self.icon_for(h["name"])
        if kind == "none":
            kind = "fireworks"
        k = 0.8 + 0.2 * math.sin(ph * 2 * math.pi * round(plan["loop"]))  # breathes, never goes dark
        f.text_center(1, "HAPPY" if h.get("public", True) else "TODAY", scale(accent, k))
        self.draw_icon(f, kind, 5, 6, ph, big=True)
        for sx, sy, off in SPARKLES:
            b = max(0.0, 1 - ((ph * 2 + off) % 1.0) * 3)
            if b > 0:
                _plot(f, sx, sy, scale(WHITE, b))
        f.rect(0, 26, 32, 6, (0, 0, 0))
        draw_marquee(f, h["label"], t, 1, 27, 30, to_rgb(self.settings.text_color), speed=SPEED)

    # list: pages of two (name marquee · date · countdown) --------------------------------------------------
    def _list(self, f: Frame, t: float, ph: float, plan: dict[str, Any]) -> None:
        accent = to_rgb(self.settings.accent)
        acc = 0.0
        page, lt = 0, t
        for i, ln in enumerate(plan["lens"]):
            if t < acc + ln:
                page, lt = i, t - acc
                break
            acc += ln
        for k, h in enumerate(plan["pages"][page]):
            y = k * 16
            d: dt.date = h["d"]
            name_c = to_rgb(self.settings.text_color) if h["public"] else PALETTE["mute"]
            draw_marquee(f, h["label"], lt, 1, y + 1, 30, name_c, speed=SPEED)
            left = days_text(h["days"])
            room = 30 - measure(left) - 2
            mon = MONTHS[d.month - 1]
            date = next((c for c in (f"{d.day} {mon}", f"{d.day}{mon}", mon) if measure(c) <= room), "")
            f.text(1, y + 8, date, PALETTE["mute"])
            f.text_right(30, y + 8, left, accent if h["days"] > 0 else PALETTE["ok"])
        f.hline(1, 15, 30, PALETTE["shade"])
        n = len(plan["pages"])
        if n > 1:
            x0 = 16 - (n * 3 - 1) // 2
            for i in range(n):
                f.hline(x0 + i * 3, 31, 2, WHITE if i == page else PALETTE["shade"])

    # calendar: this month, holidays lit ---------------------------------------------------------------------
    def _calendar(self, f: Frame, t: float, ph: float, plan: dict[str, Any]) -> None:
        accent = to_rgb(self.settings.accent)
        today = dt.date.today()
        f.text(1, 1, MONTHS[today.month - 1], accent)
        nxt = plan["ups"][0]
        f.text_right(30, 1, days_text(nxt["days"]), WHITE)
        hol = {h["d"].day for h in plan["ups"] if h["d"].year == today.year and h["d"].month == today.month}
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(today.year, today.month)
        y0 = 8 if len(weeks) <= 5 else 7
        pitch = 5 if len(weeks) <= 5 else 4
        for r, week in enumerate(weeks):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                x, y = 2 + c * 4, y0 + r * pitch
                past = day < today.day
                if day in hol:
                    col = accent
                elif c >= 5:
                    col = (110, 64, 170)
                else:
                    col = (76, 76, 104)  # bright enough to survive the panel's gamma (was nearly black)
                if past:
                    col = scale(col, 0.6)
                f.rect(x, y, 3, 3, col)
                if day == today.day:
                    f.rect(x, y, 3, 3, WHITE if ph < 0.5 else scale(WHITE, 0.5))
                    if day in hol:
                        f.set(x + 1, y + 1, accent)

    # ------------------------------------------------------------ output
    def kind(self) -> Kind:
        _p, e = self._entry()
        return "clip" if e is not None else "stream"

    def clip_key(self) -> str:
        ups = [(h["date"], h["name"], h["public"]) for h in self.upcoming()[:10]]
        return super().clip_key() + json.dumps([dt.date.today().isoformat(), ups, self._country()])

    def clip_frames(self) -> Clip:
        plan = self._plan()
        fps = plan["fps"]
        n = max(1, round(plan["loop"] * fps))
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / fps)
            frames.append(f)
        return Clip(frames, [round(1000 / fps)] * n)

    def wants_focus(self) -> bool:
        ups = self.upcoming()
        return bool(ups) and ups[0]["days"] == 0 and self.settings.celebrate

    def status(self) -> dict[str, Any]:
        ups = self.upcoming()
        _p, e = self._entry()
        return {
            "country": self._country(),
            "source": (e or {}).get("source"),
            "next": None
            if not ups
            else {"date": ups[0]["date"], "name": ups[0]["name"], "days": ups[0]["days"]},
        }
