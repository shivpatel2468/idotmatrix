"""Crypto ticker — price, 24 h change and a real 24 h sparkline; rotates through symbols."""

from __future__ import annotations

from pydantic import Field, field_validator

from ..engine.app import App, AppSettings, register
from ..gfx import PALETTE, Frame, scale
from ._kit import compact_number, loading, offline

BRAND = {
    "BTC": (255, 150, 20),
    "ETH": (120, 140, 255),
    "SOL": (170, 80, 255),
    "DOGE": (230, 190, 40),
    "XRP": (200, 220, 255),
    "ADA": (40, 120, 255),
    "BNB": (240, 185, 11),
    "AVAX": (255, 50, 50),
    "LINK": (50, 90, 255),
    "DOT": (230, 0, 122),
}


class MarketsSettings(AppSettings):
    symbols: str = Field("BTC,ETH,SOL", title="Symbols", description="Comma-separated, quoted in USDT")
    rotate: int = Field(6, ge=2, le=120, title="Seconds per symbol")
    currency: str = Field("$", max_length=2, title="Currency sign")

    @field_validator("symbols")
    @classmethod
    def _clean(cls, v: str) -> str:
        syms = [s.strip().upper() for s in v.split(",") if s.strip()]
        if not syms:
            raise ValueError("at least one symbol")
        return ",".join(dict.fromkeys(syms))


@register
class Markets(App):
    id = "markets"
    name = "Crypto Ticker"
    description = "Binance prices with 24-hour change and trend line."
    icon = "chart-candlestick"
    category = "data"
    Settings = MarketsSettings
    fps = 1.0
    uses = ("markets",)

    @property
    def symbols(self) -> list[str]:
        return self.settings.symbols.split(",")

    def on_start(self) -> None:
        self.ctx.provider("markets").want(*self.symbols)

    on_settings = on_start

    def render(self, f: Frame, t: float) -> None:
        p = self.ctx.provider("markets")
        data = p.value or {}
        syms = self.symbols
        i = int(t // self.settings.rotate) % len(syms)
        sym = syms[i]
        d = data.get(sym)
        if not d:
            (offline(f, sym, "NO DATA") if p.error else loading(f, t, sym, BRAND.get(sym, PALETTE["amber"])))
            return
        up = d["change"] >= 0
        trend = PALETTE["ok"] if up else PALETTE["bad"]
        f.text(1, 1, sym, BRAND.get(sym, PALETTE["amber"]))
        f.text_right(30, 1, f"{'▲' if up else '▼'}{abs(d['change']):.1f}%", trend)
        f.text_center(
            9, f"{self.settings.currency}{compact_number(d['price'])}", (255, 255, 255), font="small"
        )
        hist = d.get("history") or []
        if len(hist) >= 2:
            f.sparkline(0, 18, 32, 11, hist, trend, fill=scale(trend, 0.3))
        if len(syms) > 1:
            x0 = 16 - len(syms) * 2 + 1
            for k in range(len(syms)):
                f.set(
                    x0 + k * 3, 31, (255, 255, 255) if k == i else PALETTE["mute"]
                )  # dimmer greys vanish on the panel

    def status(self) -> dict:  # type: ignore[type-arg]
        return {s: (self.ctx.provider("markets").value or {}).get(s, {}).get("price") for s in self.symbols}
