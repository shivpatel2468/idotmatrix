"""Crypto Market — total market cap, the day's biggest movers and the Fear & Greed mood.

Data: CoinGecko (global + top coins) and alternative.me (Fear & Greed), see providers/cryptomarket.py. Stablecoins
and wrapped coins are left out of the movers. Direction is shown by colour *and* an arrow.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, fit, measure, mix, scale
from ..gfx.color import RGB
from ..providers.cryptomarket import movers
from . import _feed
from ._kit import MUTE, label

UP: RGB = PALETTE["ok"]
DOWN: RGB = PALETTE["bad"]
GOLD: RGB = PALETTE["gold"]


def money(v: float) -> str:
    """2.744e12 -> '$2.74T'."""
    for unit, k in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(v) >= k:
            x = v / k
            return f"${x:.2f}{unit}" if x < 10 else f"${x:.1f}{unit}" if x < 100 else f"${x:.0f}{unit}"
    return f"${v:,.0f}"


def pct(v: float) -> str:
    return f"{abs(v):.1f}%" if abs(v) < 10 else f"{abs(v):.0f}%"


def arrow(f: Frame, x: int, y: int, up: bool, c: RGB) -> None:
    """3×3 triangle, apex up or down, top-left at (x, y+1)."""
    if up:
        f.set(x + 1, y + 1, c)
        f.hline(x, y + 2, 3, c)
    else:
        f.hline(x, y + 1, 3, c)
        f.set(x + 1, y + 2, c)


def mood_color(v: float) -> RGB:
    return mix(DOWN, PALETTE["gold"], v / 50) if v < 50 else mix(PALETTE["gold"], UP, (v - 50) / 50)


class CryptoMarketSettings(AppSettings):
    layout: str = Choice(
        "cycle",
        {"cycle": "Cycle all", "overview": "Market cap", "movers": "Top movers", "mood": "Fear & greed"},
        title="Layout",
    )
    rotate: int = Field(8, ge=3, le=60, title="Seconds per page")


@register
class CryptoMarket(App):
    id = "cryptomarket"
    name = "Crypto Market"
    description = (
        "Total crypto market cap and BTC dominance, the day's top movers and the Fear & Greed index."
    )
    icon = "coins"
    category = "data"
    Settings = CryptoMarketSettings
    fps = 1.0
    uses = ("cryptomarket",)

    def render(self, f: Frame, t: float) -> None:
        p = _feed.provider(self.ctx, "cryptomarket")
        d = _feed.value_or_state(f, t, p, "MARKET", GOLD)
        if d is None:
            return
        views = [
            v
            for v, ok in (("overview", d.get("cap")), ("movers", d.get("coins")), ("mood", d.get("fng")))
            if ok
        ] or ["overview"]
        lay = self.settings.layout
        if lay == "cycle":
            lay = views[_feed.page(t, self.settings.rotate, len(views))]
        elif lay not in views:
            lay = views[0]
        {"overview": self._overview, "movers": self._movers, "mood": self._mood}[lay](f, t, d)
        _feed.stale_dot(f, p)

    def _overview(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        f.text(1, 1, "MKT CAP", MUTE)
        cap, ch = d.get("cap"), d.get("cap_change")
        if cap is None:
            label(f, 12, "NO DATA", MUTE)
            return
        label(f, 9, money(cap), PALETTE["white"], font="small")
        if ch is not None:
            c = UP if ch >= 0 else DOWN
            txt = pct(ch)
            w = measure(txt) + 5
            x = (32 - w) // 2
            arrow(f, x, 17, ch >= 0, c)
            f.text(x + 5, 18, txt, c)
        dom = d.get("btc_dom")
        if dom is not None:
            f.text(1, 24, "BTC", PALETTE["amber"])
            f.text_right(30, 24, f"{dom:.0f}%", PALETTE["amber"])
            f.bar(1, 30, 30, 1, dom / 100, PALETTE["amber"], (56, 44, 20))

    def _movers(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        up, down = movers(d.get("coins") or [], 2)
        f.text(1, 1, "TOP 24H", MUTE)
        rows = [*up, *down]
        for i, c in enumerate(rows[:4]):
            y = 8 + i * 6
            col = UP if c["change"] >= 0 else DOWN
            txt = pct(c["change"])
            ax = 30 - measure(txt) - 4
            f.text(
                1,
                y,
                fit(c["symbol"], ax - 2),
                PALETTE["white"] if i % 2 == 0 else scale(PALETTE["white"], 0.8),
            )
            arrow(f, ax, y - 1, c["change"] >= 0, col)
            f.text_right(30, y, txt, col)
        if not rows:
            label(f, 14, "FLAT DAY", MUTE)

    def _mood(self, f: Frame, t: float, d: dict[str, Any]) -> None:
        g = d["fng"]
        v = int(g["value"])
        c = mood_color(v)
        f.text(1, 1, "MOOD", MUTE)
        txt = str(v)
        f.text((32 - measure(txt, "big")) // 2, 8, txt, c, "big")
        label(f, 20, g["label"].replace("EXTREME ", "X."), c)
        for x in range(30):  # red → gold → green scale with a marker at the value
            f.set(1 + x, 28, scale(mood_color(x / 29 * 100), 0.55))
        mx = 1 + round(v / 100 * 29)
        f.vline(mx, 26, 5, PALETTE["white"])

    def status(self) -> dict[str, Any]:
        p = _feed.provider(self.ctx, "cryptomarket")
        d = (p.value if p is not None else None) or {}
        return {
            "cap_usd": d.get("cap"),
            "change_24h": d.get("cap_change"),
            "fear_greed": (d.get("fng") or {}).get("value"),
        }
