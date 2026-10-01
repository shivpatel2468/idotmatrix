"""Example plugin — copy to `plugins/days_until.py` (no leading underscore) and restart.

Files starting with "_" are skipped by the loader. See docs/APP_SDK.md.
"""

from datetime import date

from pydantic import Field

from deskdot.apps._kit import ring
from deskdot.engine import App, AppSettings, Color, register
from deskdot.gfx import Frame, scale


class DaysUntilSettings(AppSettings):
    label: str = Field("TRIP", max_length=8, title="Label")
    target: date = Field(date(2026, 12, 25), title="Date")
    color: Color = Field("#00dcff", title="Colour")


@register
class DaysUntil(App):
    id = "days_until"
    name = "Days Until"
    description = "Counts down the days to a date."
    icon = "calendar-days"
    category = "time"
    Settings = DaysUntilSettings
    fps = 0.2  # changes once a day; frames are deduped anyway

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        days = max(0, (s.target - date.today()).days)
        f.text_center(5, s.label, scale(s.color, 0.8))
        f.text_center(12, str(days), (255, 255, 255), font="big" if days < 1000 else "small")
        f.text_center(24, "DAY" if days == 1 else "DAYS", scale(s.color, 0.6))
        ring(f, 1 - min(1.0, days / 365), s.color, track=scale(s.color, 0.1), head=False)
