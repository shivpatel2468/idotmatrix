"""GitHub contribution graph and a Countdown to any date."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import Frame, fit, measure, mix, scale
from ._kit import compact_number, loading, offline
from .timer import smooth_ring

GREENS = [(14, 14, 22), (0, 70, 30), (0, 140, 55), (20, 210, 80), (120, 255, 140)]
PALETTES = {
    "green": GREENS,
    "ember": [(14, 14, 22), (80, 20, 5), (160, 40, 10), (255, 72, 24), (255, 190, 120)],
    "ice": [(14, 14, 22), (0, 40, 90), (0, 90, 180), (0, 170, 255), (160, 230, 255)],
}


class GitHubSettings(AppSettings):
    user: str = Field("torvalds", max_length=39, title="GitHub username")
    weeks: str = Choice("16", {"16": "16 weeks (wide cells)", "32": "32 weeks"})
    palette: str = Choice("green", {"green": "GitHub green", "ember": "Ember", "ice": "Ice"})


@register
class GitHub(App):
    id = "github"
    name = "GitHub Graph"
    description = "Your contribution graph, total and streak — straight from your public profile."
    icon = "git-commit-horizontal"
    category = "data"
    Settings = GitHubSettings
    fps = 2.0
    uses = ("github",)

    def on_start(self) -> None:
        self.ctx.provider("github").want(self.settings.user)

    on_settings = on_start

    def render(self, f: Frame, t: float) -> None:
        p = self.ctx.provider("github")
        d = p.value
        if not d:
            (offline(f, "GITHUB", "NO USER") if p.error else loading(f, t, "GITHUB", (20, 210, 80)))
            return
        pal = PALETTES[self.settings.palette]
        weeks = int(self.settings.weeks)
        cw = 32 // weeks
        days = d["days"]
        # align to weeks ending today: last column holds the current (partial) week
        last = date.fromisoformat(days[-1][0]) if days else date.today()
        wd = (last.weekday() + 1) % 7  # Sunday = 0 like GitHub
        levels = {dd: lv for dd, lv in days}
        top = 10
        for col in range(weeks):
            for row in range(7):
                offset = (weeks - 1 - col) * 7 + (wd - row)
                if offset < 0:
                    continue
                dday = date.fromordinal(last.toordinal() - offset).isoformat()
                lv = levels.get(dday, 0)
                c = pal[lv]
                if offset == 0 and int(t * 2) % 2 == 0:
                    c = mix(c, (255, 255, 255), 0.35)  # today blinks softly
                f.rect(col * cw, top + row * 3, cw - (1 if cw > 1 else 0), 2, c)
        total = d.get("total")
        tot = compact_number(total) if total else ""
        f.text_right(30, 1, tot, (255, 255, 255))
        room = 30 - (measure(tot) + 2 if tot else 0)  # the name never runs into the total
        f.text(1, 1, fit(str(d["user"]).upper(), room), scale(pal[4], 0.9))
        streak = d.get("streak", 0)
        # streak meter along the bottom edge: full at 30 days
        f.hline(0, 31, round(32 * min(1.0, streak / 30)), scale(pal[3], 0.8))

    def status(self) -> dict[str, Any]:
        d = self.ctx.provider("github").value or {}
        return {"total": d.get("total"), "streak": d.get("streak")}


class CountdownSettings(AppSettings):
    label: str = Field("LAUNCH", max_length=10, title="Label")
    target: datetime = Field(datetime(2026, 12, 31, 23, 59), title="Date & time")
    color: Color = Field("#00dcff", title="Colour")
    style: str = Choice("auto", {"auto": "Auto (days → clock)", "days": "Days only"})


@register
class Countdown(App):
    id = "countdown"
    name = "Countdown"
    description = "Counts down to any moment — days, then hours, then a live seconds clock."
    icon = "hourglass"
    category = "time"
    Settings = CountdownSettings
    fps = 2.0

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        target = s.target.replace(tzinfo=None) if s.target.tzinfo else s.target
        left = (target - datetime.now()).total_seconds()
        f.text_center(4, fit(s.label.upper(), 30), scale(s.color, 0.85))  # same rows as the Clock hero
        if left <= 0:
            k = int(t * 3) % 2
            f.text_center(13, "NOW!", (255, 255, 255) if k else s.color, font="small")
            smooth_ring(f, 1.0, s.color if k else mix(s.color, (255, 255, 255), 0.55), head=False)
            return
        days = int(left // 86400)
        if days >= 1 or s.style == "days":
            f.text_center(11, str(days), (255, 255, 255), font="big" if days < 1000 else "small")
            f.text_center(24, "DAY" if days == 1 else "DAYS", scale(s.color, 0.7))
        else:
            h, rem = divmod(int(left), 3600)
            m, sec = divmod(rem, 60)
            f.text(1, 11, f"{h:02d}:{m:02d}", (255, 255, 255), font="big")
            f.text_center(24, f"{sec:02d} SEC", scale(s.color, 0.7))
            # the last day: the ring drains with the seconds (a year-scale ring would sit at 100 %)
            smooth_ring(f, (left % 60) / 60, s.color, track=scale(s.color, 0.1), head=False)
            return
        smooth_ring(f, 1 - min(1.0, left / (365 * 86400)), s.color, track=scale(s.color, 0.1), head=False)
