"""Race Countdown — the next Grand Prix: countdown to lights out, the next session, and the last podium.

Data: the Jolpica API (Ergast-compatible, keyless; providers/racing.py). Session times are shown in the panel's
local time. During the race window the screen says LIVE; for a day after a race the podium takes over.
"""

from __future__ import annotations

import time
from typing import Any

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, measure, scale
from ..gfx.color import RGB
from . import _feed
from ._kit import MUTE, empty, label

RED: RGB = (255, 24, 24)
PODIUM: tuple[RGB, RGB, RGB] = ((255, 214, 0), (190, 190, 210), (205, 110, 40))
RACE_S = 2 * 3600  # a Grand Prix lasts up to two hours


def countdown(seconds: float) -> tuple[str, str]:
    """(hero text, unit caption): '3D 04H'-style above a day, 'HH:MM' below."""
    s = max(0, int(seconds))
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    if d >= 1:
        return f"{d}D{h:02d}H", "TO RACE"
    return f"{h:02d}:{m:02d}", "TO LIGHTS OUT"


def flag(f: Frame, x: int, y: int, t: float) -> None:
    """A 7×5 waving chequered flag on a pole."""
    f.vline(x, y, 7, MUTE)
    for j in range(5):
        for i in range(6):
            wave = 1 if (i + int(t * 4)) % 6 >= 3 and j == 0 else 0
            if (i + j) % 2 == 0:
                f.set(x + 1 + i, y + j + wave, PALETTE["white"])
            else:
                f.set(x + 1 + i, y + j + wave, (40, 40, 52))


class RaceSettings(AppSettings):
    layout: str = Choice(
        "auto",
        {"auto": "Countdown (podium after a race)", "countdown": "Countdown", "podium": "Last podium"},
        title="Layout",
    )


@register
class RaceCountdown(App):
    id = "racecountdown"
    name = "Race Countdown"
    description = (
        "Countdown to the next Grand Prix with its session times, LIVE during the race, then the podium."
    )
    icon = "flag"
    category = "data"
    Settings = RaceSettings
    fps = 2.0
    uses = ("racing",)

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "racing")
        d = _feed.value_or_state(f, t, p, "RACE", RED)
        if d is None:
            return
        nxt, last = d.get("next"), d.get("last")
        now = time.time()
        lay = self.settings.layout
        if lay == "auto":
            fresh = last and last.get("date") and now - last["date"] < 30 * 3600 and last.get("podium")
            lay = (
                "podium"
                if fresh and not (nxt and nxt.get("start") and nxt["start"] - now < RACE_S)
                else "countdown"
            )
        if lay == "podium" and last and last.get("podium"):
            self._podium(f, t, last)
        elif nxt:
            self._countdown(f, t, nxt, now)
        elif last and last.get("podium"):
            self._podium(f, t, last)
        else:
            empty(f, "SEASON OVER", "SEE YOU SOON")
        _feed.stale_dot(f, p)

    def _countdown(self, f: Frame, t: float, n: dict[str, Any], now: float) -> None:
        flag(f, 1, 1, t)
        f.text_right(30, 1, f"R{n['round']}", MUTE)
        start = n.get("start") or now
        if start <= now < start + RACE_S:
            pulse = 0.55 + 0.45 * abs(((t * 1.5) % 2) - 1)
            label(f, 10, "LIVE", scale(RED, pulse), font="small")
            label(f, 19, n["name"], PALETTE["white"], t)
            return
        hero_txt, _cap = countdown(start - now)
        font = "big" if measure(hero_txt, "big") <= 30 and ":" in hero_txt else "small"
        if font == "big":
            f.text((32 - measure(hero_txt, "big")) // 2, 9, hero_txt, PALETTE["white"], "big")
        else:
            label(f, 11, hero_txt, PALETTE["white"], font="small")
        label(f, 20, n["name"], RED, t)
        upcoming = [(lab, ts) for lab, ts in n.get("sessions") or [] if ts + 3600 > now]
        if upcoming:
            lab, ts = upcoming[0]
            txt = f"{lab} {_feed.local_day(ts)} {_feed.local_hhmm(ts)}"
            label(f, 26, txt, MUTE, t)

    def _podium(self, f: Frame, t: float, last: dict[str, Any]) -> None:
        label(f, 1, last["name"], MUTE, t)
        for i, r in enumerate(last["podium"][:3]):  # 1-2-3 rows: medal colour bar, place, driver code
            y = 8 + i * 8
            c = PODIUM[min(2, max(0, r["pos"] - 1))]
            f.rect(1, y, 2, 7, c)
            f.text(5, y, str(r["pos"]), c, "small")
            f.text(
                12,
                y,
                (r["code"] or r["name"][:3])[:3],
                PALETTE["white"] if i == 0 else (200, 200, 215),
                "small",
            )

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "racing")
        d = (p.value if p is not None else None) or {}
        n = d.get("next") or {}
        return {"next": n.get("name"), "start": n.get("start"), "round": n.get("round")}
