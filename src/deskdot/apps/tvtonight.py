"""TV Tonight — what's on broadcast TV now and next in your country (TVMaze, no key).

Three rows at a time: start time (amber while on air) and the show's name; pages advance every few seconds.
The country comes from the setting or the panel's location; "prime time" keeps only shows from 18:00.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import Field, field_validator

from ..engine.app import App, AppSettings, register
from ..gfx import PALETTE, Frame, fit, measure
from ..gfx.color import RGB
from ..providers.tvguide import on_air
from . import _feed
from ._kit import MUTE, empty, label

TV: RGB = (180, 120, 255)
LIVE: RGB = PALETTE["amber"]


class TvTonightSettings(AppSettings):
    country: str = Field(
        "", max_length=2, title="Country", description="Two-letter code; empty = your location"
    )
    prime_time: bool = Field(True, title="Prime time only (from 18:00)")
    seconds: int = Field(6, ge=3, le=30, title="Seconds per page")

    @field_validator("country")
    @classmethod
    def _cc(cls, v: str) -> str:
        return "".join(ch for ch in v.upper() if ch.isalpha())[:2]


@register
class TvTonight(App):
    id = "tvtonight"
    name = "TV Tonight"
    description = "What's on broadcast TV now and later tonight in your country, three shows at a time."
    icon = "tv"
    category = "data"
    Settings = TvTonightSettings
    fps = 2.0
    uses = ("tvguide",)

    def on_start(self) -> None:
        p = _feed.provider(self.ctx, "tvguide")
        if p is not None:
            p.want(self.settings.country)

    def on_settings(self) -> None:
        self.on_start()

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "tvguide")
        d = _feed.value_or_state(f, t, p, "TV", TV)
        if d is None:
            return
        now = time.time()
        shows = on_air(d.get("shows") or [], now, 18 if self.settings.prime_time else 0)
        if not shows:
            empty(f, "NOTHING ON", d.get("country") or "")
            return
        per = 2  # two shows a page: time + channel, then the name (scrolls when long)
        pages = min(8, max(1, (len(shows) + per - 1) // per))
        pg = _feed.page(t, self.settings.seconds, pages)
        local_t = t % self.settings.seconds
        f.text(1, 1, "ON TV", TV)
        for i in range(pages):  # page dots, top right
            f.set(30 - (pages - 1 - i) * 2, 3, TV if i == pg else (50, 40, 70))
        for i, s in enumerate(shows[pg * per : pg * per + per]):
            y = 9 + i * 12
            live = s["start"] <= now
            f.text(1, y, "NOW" if live else _feed.local_hhmm(s["start"]), LIVE if live else MUTE)
            if s.get("network"):
                tw = measure("00:00") + 3
                f.text(tw, y, fit(s["network"], 30 - tw + 1), (110, 110, 130))
            label(f, y + 6, s["show"], PALETTE["white"] if live else (210, 210, 225), local_t)
        _feed.stale_dot(f, p)

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "tvguide")
        d = (p.value if p is not None else None) or {}
        return {"country": d.get("country"), "shows": len(d.get("shows") or [])}
