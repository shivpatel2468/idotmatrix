"""Bike Share — bikes and free docks at the stations nearest you (CityBikes, 700+ systems, no key).

The nearest system is found from the panel's location; set a network id (e.g. ``santander-cycles``, ``velib``,
``citi-bike-nyc``) or part of a station's name to pin it. Bikes are green when plenty, amber when few, red at 0.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, Sprite, measure
from ..gfx.color import RGB
from . import _feed
from ._kit import MUTE, empty, label

GREEN: RGB = PALETTE["ok"]
BIKE = Sprite.parse(
    [
        "....##...",
        ".....#...",
        ".###.##..",
        "#...#..#.",
        "#.#.#.#.#",
        "#...#..#.",
        ".###..##.",
    ],
    {"#": "#00ff78"},
)


def bikes_color(n: int) -> RGB:
    return PALETTE["bad"] if n == 0 else PALETTE["amber"] if n <= 2 else GREEN


def meters(m: int) -> str:
    return f"{m}M" if m < 1000 else f"{m / 1000:.1f}KM"


class BikeShareSettings(AppSettings):
    layout: str = Choice("nearest", {"nearest": "Nearest station", "list": "Three nearest"}, title="Layout")
    network: str = Field(
        "",
        max_length=60,
        title="Network id",
        description="Empty = the nearest system. Ids are on citybik.es (e.g. santander-cycles, velib)",
    )
    station: str = Field("", max_length=40, title="Station name contains", description="Pin one station")


@register
class BikeShare(App):
    id = "bikeshare"
    name = "Bike Share"
    description = "Bikes and free docks at the bike-share stations nearest you, in 700+ cities."
    icon = "bike"
    category = "data"
    Settings = BikeShareSettings
    fps = 2.0
    uses = ("bikeshare",)

    def on_start(self) -> None:
        p = _feed.provider(self.ctx, "bikeshare")
        if p is not None:
            p.want(self.settings.network, self.settings.station)

    def on_settings(self) -> None:
        self.on_start()

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "bikeshare")
        d = _feed.value_or_state(f, t, p, "BIKES", GREEN)
        if d is None:
            return
        st = d.get("stations") or []
        if not st:
            empty(f, "NO STATION", d.get("network", {}).get("city") or "")
            return
        if self.settings.layout == "list":
            self._list(f, t, st)
        else:
            self._nearest(f, t, st[0], d)
        _feed.stale_dot(f, p)

    def _nearest(self, f: Frame, t: float, s: dict[str, Any], d: dict[str, Any]) -> None:
        label(f, 1, s["name"], MUTE, t)
        f.sprite(BIKE, 1, 11)
        n = str(s["bikes"])
        f.text(30 - measure(n, "big") + 1, 9, n, bikes_color(s["bikes"]), "big")
        cap = f"{s['docks']} DOCKS" if s.get("docks") is not None else "DOCKS ?"
        f.text(1, 21, cap, PALETTE["sky"])
        f.text(1, 26, meters(s["dist_m"]), MUTE)
        if s.get("ebikes"):
            f.text_right(30, 26, f"{s['ebikes']}E", PALETTE["gold"])
        elif d.get("far"):
            f.text_right(30, 26, "FAR", PALETTE["amber"])

    def _list(self, f: Frame, t: float, st: list[dict[str, Any]]) -> None:
        f.sprite(BIKE, 1, 0)
        f.text_right(30, 1, "BIKES", MUTE)
        for i, s in enumerate(st[:3]):
            y = 9 + i * 8
            n = str(s["bikes"])
            w = measure(n)
            f.text_right(30, y, n, bikes_color(s["bikes"]))
            label(f, y, s["name"], PALETTE["white"] if i == 0 else MUTE, t, x=1, w=28 - w)

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "bikeshare")
        d = (p.value if p is not None else None) or {}
        st = d.get("stations") or []
        return {"network": (d.get("network") or {}).get("name"), "nearest": st[0] if st else None}
