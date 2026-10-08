"""Wiki Trending — what the world read most on Wikipedia yesterday, one article at a time.

Data: Wikimedia's daily featured feed (providers/wiki.py): rank, title, views and the last five days of views as
a sparkline, so a sudden spike (news) looks different from an evergreen favourite.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, register
from ..gfx import PALETTE, Frame, wrap
from ..gfx.color import RGB
from . import _feed
from ._kit import MUTE, compact_number, label

ACCENT: RGB = (230, 230, 240)
RANK: RGB = PALETTE["sky"]


class WikiTrendingSettings(AppSettings):
    count: int = Field(10, ge=1, le=15, title="Articles", description="Top N most-read articles to rotate")
    seconds: int = Field(10, ge=4, le=60, title="Seconds per article")
    show_description: bool = Field(True, title="Scroll the short description")


@register
class WikiTrending(App):
    id = "wikitrending"
    name = "Wiki Trending"
    description = "Yesterday's most-read Wikipedia articles with their views and a 5-day spike chart."
    icon = "trending-up"
    category = "data"
    Settings = WikiTrendingSettings
    fps = 4.0
    uses = ("wiki",)

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "wiki")
        d = _feed.value_or_state(f, t, p, "WIKI", RANK)
        if d is None:
            return
        items = (d.get("trending") or [])[: self.settings.count]
        if not items:
            label(f, 12, "NO LIST YET", MUTE)
            return
        i = _feed.page(t, self.settings.seconds, len(items))
        a = items[i]
        f.text(1, 1, f"#{i + 1}", RANK)
        f.text_right(30, 1, compact_number(a["views"]), MUTE)
        lines = wrap(a["title"], 30)
        local_t = t % self.settings.seconds
        if len(lines) <= 2:
            for j, line in enumerate(lines):
                label(f, 9 + j * 7, line, PALETTE["white"])
        else:
            label(f, 9, a["title"], PALETTE["white"], local_t)
        if self.settings.show_description and a.get("description") and len(lines) <= 1:
            label(f, 16, a["description"], MUTE, local_t)
        hist = a.get("history") or []
        if len(hist) >= 2:
            f.sparkline(1, 23, 30, 8, hist, RANK, fill=(20, 50, 100))
        _feed.stale_dot(f, p)

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "wiki")
        d = (p.value if p is not None else None) or {}
        top = (d.get("trending") or [None])[0]
        return {"top": top["title"] if top else None, "views": top["views"] if top else None}
