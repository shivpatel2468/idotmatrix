"""Bitcoin Network — fees, the newest block and the halving countdown (mempool.space, no key).

Not a price ticker (Crypto Ticker does prices): this is the network's pulse. Fees are sat/vB for "next block",
"half an hour" and "an hour"; the block screen counts minutes since the last block with the last few block gaps
as bars; the halving screen counts down days with the era's progress around the edge.
"""

from __future__ import annotations

import itertools
import time
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, scale
from ..gfx.color import RGB
from . import _feed
from ._kit import DIM, MUTE, hero, label, ring

ORANGE: RGB = (255, 140, 0)


def fee_color(sat: float) -> RGB:
    return (
        PALETTE["ok"]
        if sat <= 5
        else PALETTE["gold"]
        if sat <= 20
        else ORANGE
        if sat <= 60
        else PALETTE["red"]
    )


def fee_text(v: float) -> str:
    return f"{v:.1f}" if 0 < v < 10 and v != int(v) else f"{v:.0f}"


class BtcNetSettings(AppSettings):
    layout: str = Choice(
        "cycle",
        {"cycle": "Cycle all", "fees": "Fees", "block": "Latest block", "halving": "Halving countdown"},
        title="Layout",
    )
    rotate: int = Field(8, ge=3, le=60, title="Seconds per page")


@register
class BitcoinNetwork(App):
    id = "btcnet"
    name = "Bitcoin Network"
    description = "Network fees (sat/vB), minutes since the last block and the countdown to the next halving."
    icon = "bitcoin"
    category = "data"
    Settings = BtcNetSettings
    fps = 1.0
    uses = ("bitcoin",)

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "bitcoin")
        d = _feed.value_or_state(f, t, p, "BITCOIN", ORANGE)
        if d is None:
            return
        lay = self.settings.layout
        if lay == "cycle":
            views = (["fees"] if d.get("fees") else []) + ["block", "halving"]
            lay = views[_feed.page(t, self.settings.rotate, len(views))]
        if lay == "fees" and not d.get("fees"):
            lay = "block"
        {"fees": self._fees, "block": self._block, "halving": self._halving}[lay](f, t, d)
        _feed.stale_dot(f, p)

    def _fees(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        fees = d["fees"]
        fast = fees["fastest"]
        f.text(1, 1, "FEE", ORANGE)
        f.text_right(30, 1, "SAT", MUTE)
        hero(f, 8, fee_text(fast), fee_color(fast))
        for y, name, key in ((20, "30M", "half_hour"), (26, "1H", "hour")):
            f.text(1, y, name, MUTE)
            f.text_right(30, y, fee_text(fees[key]), fee_color(fees[key]))

    def _block(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        now = time.time()
        mins = max(0, int((now - d["last_block"]) // 60))
        f.text(1, 1, f"#{d['height']}", ORANGE)
        hero(f, 8, str(mins) if mins < 1000 else "999", PALETTE["white"])
        label(f, 19, "MIN AGO", MUTE)
        recent = d.get("recent") or []
        gaps = [max(0.0, a - b) for a, b in itertools.pairwise(recent)][:7]
        for i, g in enumerate(reversed(gaps)):  # oldest left; 10 min = 4 px, capped at 6
            h = max(1, min(6, round(g / 150)))
            c = PALETTE["ok"] if g <= 900 else PALETTE["gold"] if g <= 1800 else ORANGE
            f.rect(4 + i * 4, 31 - h, 3, h, scale(c, 0.8))
        blink = int(t) % 2 == 0
        f.rect(4 + len(gaps) * 4, 30, 3, 1, ORANGE if blink else scale(ORANGE, 0.3))  # the block being mined

    def _halving(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        h = d["halving"]
        days = max(0, int((h["eta"] - time.time()) // 86400))
        ring(f, h["progress"], ORANGE, track=(40, 28, 10), gap=(8, 18))
        label(f, 3, "HALVING", ORANGE)
        hero(f, 9, str(days), PALETTE["white"])
        label(f, 20, "DAYS", MUTE)
        f.text(1, 25, f"ERA {h['era']}", DIM)

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "bitcoin")
        d = (p.value if p is not None else None) or {}
        return {
            "height": d.get("height"),
            "fees": d.get("fees"),
            "halving_blocks": (d.get("halving") or {}).get("remaining"),
        }
