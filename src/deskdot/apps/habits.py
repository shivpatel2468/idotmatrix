"""Habits — up to three daily habits: a 7-day dot row each, today's tick, and the streak with a flame.

Ticks live in the app's persisted data (``ctx.data["log"]``: habit number → ISO dates). Drive it from the
studio buttons, the HTTP API or an agent:

    POST /api/apps/habits/actions/tick    {"habit": 1}        (number or name; toggle / untick work alike)

At rest the screen is a baked clip (the flames flicker natively, zero Bluetooth traffic); a tick switches to
streaming for a moment to play the burst, then the new state is baked.
"""

from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Color, Kind, register
from ..gfx import PALETTE, Frame, Sprite, fit, measure, mix, scale, to_rgb
from ..gfx.color import RGB

WHITE: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
MISS: RGB = (50, 50, 70)  # a missed day stays a visible cell through the panel gamma
FX_SECONDS = 1.4
KEEP_DAYS = 400

FLAME_ROWS = (
    [".#...", ".##.#", "#oo##", ".#o#."],
    ["...#.", "#.##.", "##oo#", ".#o#."],
)
FLAMES = [Sprite.parse(r, {"#": (255, 90, 0), "o": (255, 214, 0)}) for r in FLAME_ROWS]
EMBER = Sprite.parse([".....", "..#..", "#ooo#", ".###."], {"#": (90, 40, 30), "o": (140, 60, 20)})
CHECK_ROWS = ["...#", "#.#.", ".#.."]


class HabitsSettings(AppSettings):
    habit1: str = Field("WATER", max_length=10, title="Habit 1")
    habit2: str = Field("READ", max_length=10, title="Habit 2")
    habit3: str = Field("MOVE", max_length=10, title="Habit 3", description="Leave a name empty to hide it.")
    color1: Color = Field("#00dcff", title="Colour 1", json_schema_extra={"group": "Look"})
    color2: Color = Field("#ffd600", title="Colour 2", json_schema_extra={"group": "Look"})
    color3: Color = Field("#00ff78", title="Colour 3", json_schema_extra={"group": "Look"})
    streak_style: str = Choice(
        "flame", {"flame": "Flame + days", "days": "Days only"}, title="Streak", group="Look"
    )
    day_starts: int = Field(
        4,
        ge=0,
        le=8,
        title="Day starts at (hour)",
        description="Ticks before this hour count for the previous day (night owls).",
        json_schema_extra={"group": "Look"},
    )


def streak(days: set[str], today: date) -> tuple[int, bool]:
    """(streak length, done today). A streak survives until the end of today even if today isn't ticked yet."""
    done_today = today.isoformat() in days
    d = today if done_today else today - timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n, done_today


@register
class Habits(App):
    id = "habits"
    name = "Habits"
    description = "Up to three daily habits with a 7-day dot row, today's tick and a streak flame."
    icon = "flame"
    category = "productivity"
    Settings = HabitsSettings
    fps = 12.0
    clip_seconds = 2.0
    clip_fps = 6.0
    actions = (
        Action("tick1", "Tick 1", "check"),
        Action("tick2", "Tick 2", "check"),
        Action("tick3", "Tick 3", "check"),
        Action("undo", "Undo last", "undo-2"),
    )

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._fx: tuple[int, float, bool] | None = None  # (habit number, monotonic start, ticked?)

    # ------------------------------------------------------------------ data
    def today(self) -> date:
        return (datetime.now() - timedelta(hours=self.settings.day_starts)).date()

    def _log(self) -> dict[str, list[str]]:
        log = self.ctx.data.get("log")
        if not isinstance(log, dict):
            log = {}
            self.ctx.data["log"] = log
        return log

    def habits(self) -> list[tuple[int, str, RGB]]:
        s = self.settings
        out = []
        for n in (1, 2, 3):
            name = (getattr(s, f"habit{n}") or "").strip().upper()
            if name:
                out.append((n, name, to_rgb(getattr(s, f"color{n}"))))
        return out

    def days(self, n: int) -> set[str]:
        return set(self._log().get(str(n), []))

    def _resolve(self, key: Any) -> int:
        if isinstance(key, int) or (isinstance(key, str) and key.strip().isdigit()):
            n = int(key)
            if n in (1, 2, 3):
                return n
        if isinstance(key, str):
            for n, name, _ in self.habits():
                if name == key.strip().upper():
                    return n
        raise ValueError(f"unknown habit {key!r}; use 1-3 or a habit name")

    def set_done(self, n: int, done: bool, day: date | None = None) -> bool:
        """Mark habit `n` done/undone for `day` (default today). Returns whether anything changed."""
        day = day or self.today()
        log = self._log()
        cur = set(log.get(str(n), []))
        iso = day.isoformat()
        if (iso in cur) == done:
            return False
        if done:
            cur.add(iso)
        else:
            cur.discard(iso)
        cutoff = (day - timedelta(days=KEEP_DAYS)).isoformat()
        log[str(n)] = sorted(d for d in cur if d >= cutoff)
        self.ctx.data["last"] = {"habit": n, "day": iso, "done": done}
        self.ctx.save()
        self._fx = (n, time.monotonic(), done)
        self.ctx.invalidate()
        return True

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name in ("tick1", "tick2", "tick3"):
            n = int(name[-1])
            self.set_done(n, True)
        elif name in ("tick", "untick", "toggle"):
            n = self._resolve(payload.get("habit", 1))
            done = name == "tick" or (name == "toggle" and self.today().isoformat() not in self.days(n))
            day = date.fromisoformat(payload["date"]) if payload.get("date") else None
            self.set_done(n, done, day)
        elif name == "undo":
            last = self.ctx.data.get("last")
            if not last:
                return {"ok": False, "reason": "nothing to undo"}
            n = int(last["habit"])
            self.set_done(n, not last["done"], date.fromisoformat(last["day"]))
            self.ctx.data.pop("last", None)
        else:
            raise KeyError(name)
        return self.status()

    # ---------------------------------------------------------------- output
    def _fx_age(self) -> float | None:
        if self._fx is None:
            return None
        age = time.monotonic() - self._fx[1]
        if age > FX_SECONDS:
            self._fx = None
            return None
        return age

    def kind(self) -> Kind:
        return "stream" if self._fx_age() is not None else "clip"

    def clip_key(self) -> str:
        today = self.today()
        recent = {
            str(n): sorted(d for d in self.days(n) if d >= (today - timedelta(days=60)).isoformat())
            for n, _, _ in self.habits()
        }
        return json.dumps([self.settings.model_dump(mode="json"), today.isoformat(), recent], sort_keys=True)

    def render(self, f: Frame, t: float) -> None:
        habits = self.habits()
        if not habits:
            f.text_center(10, "NO", MUTE)
            f.text_center(17, "HABITS", MUTE)
            return
        today = self.today()
        n = len(habits)
        pitch = {1: 0, 2: 14, 3: 10}[n]
        top = {1: 9, 2: 3, 3: 1}[n]
        age = self._fx_age()
        for i, (num, name, col) in enumerate(habits):
            y = top + i * pitch
            fx = age if (self._fx and self._fx[0] == num) else None
            self._row(f, t, y, num, name, col, today, fx, big=n == 1)

    def _row(
        self,
        f: Frame,
        t: float,
        y: int,
        num: int,
        name: str,
        col: RGB,
        today: date,
        fx: float | None,
        big: bool,
    ) -> None:
        """Name + streak count on top; six past days, today's tick and the flame underneath."""
        days = self.days(num)
        n, done = streak(days, today)
        ticked = self._fx[2] if (fx is not None and self._fx) else True
        count = str(n)
        pop = fx is not None and ticked and fx < 0.6
        f.text_right(30, y, count, WHITE if (done or pop) else MUTE)
        f.text(1, y, fit(name, 30 - measure(count) - 2), col)
        dy = 6
        for k in range(6):
            d = today - timedelta(days=6 - k)
            f.rect(1 + k * 3, y + dy, 2, 3, scale(col, 0.7) if d.isoformat() in days else MISS)
        if done:  # today's tick
            f.sprite(Sprite.parse(CHECK_ROWS, {"#": mix(col, WHITE, 0.35)}), 20, y + dy)
        else:  # today, not yet: an empty box
            f.rect(20, y + dy, 3, 3, scale(col, 0.45), fill=False)
        if self.settings.streak_style == "flame" and n > 0:
            f.sprite(FLAMES[int(t * 3) % 2] if done else EMBER, 26, y + dy - 1)
        if big:
            f.text_center(y + 14, f"{n} DAY{'S' if n != 1 else ''}", col if done else MUTE)
        if fx is not None:
            self._burst(f, fx, 21, y + dy + 1, col, ticked)

    @staticmethod
    def _burst(f: Frame, age: float, cx: int, cy: int, col: RGB, ticked: bool) -> None:
        """The tick effect: an expanding spark ring from today's cell and a flash; a quick fade for untick."""
        k = age / FX_SECONDS
        if not ticked:
            f.rect(cx - 2, cy - 2, 5, 5, scale((255, 40, 60), max(0.0, 1 - k * 2)), fill=False)
            return
        if age < 0.12:
            f.rect(cx - 2, cy - 2, 5, 5, WHITE)
        r = 1.5 + k * 9
        fade = max(0.0, 1 - k) ** 1.2
        for i in range(10):
            a = i / 10 * math.tau + k * 1.5
            x = round(cx + math.cos(a) * r)
            y = round(cy + math.sin(a) * r * 0.75)
            f.set(x, y, mix(col, WHITE, 0.5 if i % 2 else 0.0) if fade > 0.3 else scale(col, fade * 2))
        for i in range(5):
            a = i / 5 * math.tau
            rr = r * 0.55
            f.set(round(cx + math.cos(a) * rr), round(cy + math.sin(a) * rr * 0.75), scale(WHITE, fade))

    def status(self) -> dict[str, Any]:
        today = self.today()
        out = {}
        for n, name, _ in self.habits():
            days = self.days(n)
            s, done = streak(days, today)
            week = [(today - timedelta(days=6 - k)).isoformat() in days for k in range(7)]
            out[str(n)] = {"name": name, "streak": s, "done_today": done, "last7": week}
        return {"today": today.isoformat(), "habits": out}
