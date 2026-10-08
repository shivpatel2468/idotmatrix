"""World Flags — a flag of the day, a shuffle, or a quiz (name revealed after a pause). Flags from flagcdn.com.

Flags are drawn pixel-for-pixel from a 30×20 downscale (design colours, no photo calibration). Pick order is a
fixed shuffle of every country seeded by the date, so everyone sees the same "flag of the day".
"""

from __future__ import annotations

import datetime as dt
import random
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame
from ..gfx.color import RGB
from . import _feed
from ._kit import MUTE, label

FRAME: RGB = (60, 60, 78)


def order(codes: list[str], seed: int) -> list[str]:
    out = sorted(codes)
    random.Random(seed).shuffle(out)
    return out


class WorldFlagsSettings(AppSettings):
    mode: str = Choice(
        "daily", {"daily": "Flag of the day", "shuffle": "Shuffle", "quiz": "Quiz"}, title="Mode"
    )
    seconds: int = Field(12, ge=4, le=120, title="Seconds per flag", description="Shuffle and quiz")


@register
class WorldFlags(App):
    id = "worldflags"
    name = "World Flags"
    description = "A flag of the day, a shuffle of every country's flag, or a guess-the-flag quiz."
    icon = "flag-triangle-right"
    category = "data"
    Settings = WorldFlagsSettings
    fps = 4.0
    uses = ("flags",)

    def _pick(self, names: dict[str, str], t: float) -> tuple[str, str]:
        today = dt.date.today()
        seq = order(list(names), today.toordinal() if self.settings.mode == "daily" else 7)
        if not seq:
            return "", ""
        i = 0 if self.settings.mode == "daily" else int(t // self.settings.seconds) + today.toordinal()
        cur, nxt = seq[i % len(seq)], seq[(i + 1) % len(seq)]
        return cur, nxt

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "flags")
        d = _feed.value_or_state(f, t, p, "FLAGS", PALETTE["sky"])
        if d is None:
            return
        names = d.get("names") or {}
        cc, nxt = self._pick(names, t)
        flags = d.get("flags") or {}
        if cc not in flags or nxt not in flags:
            p.want(cc, nxt)  # cheap: records the wish; the provider downloads in the background
        img = flags.get(cc)
        if img is None:
            label(f, 10, "LOADING", MUTE)
            label(f, 22, names.get(cc, ""), PALETTE["white"], t)
            return
        h, w = img.shape[:2]
        x0, y0 = (32 - w) // 2, 1 + (21 - h) // 2
        f.rect(x0 - 1, y0 - 1, w + 2, h + 2, FRAME, fill=False)
        f.blit(np.asarray(img, dtype=np.uint8), x0, y0)
        name = names.get(cc, cc.upper())
        if self.settings.mode == "quiz":
            phase = (t % self.settings.seconds) / self.settings.seconds
            if phase < 0.6:
                label(f, 25, "?" * min(6, max(3, len(name) // 3)), MUTE)
                return
        label(f, 25, name, PALETTE["white"], t)

    def status(self) -> dict[str, Any]:
        return {"mode": self.settings.mode}
