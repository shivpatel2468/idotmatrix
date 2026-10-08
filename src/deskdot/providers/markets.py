"""Crypto prices from Binance public endpoints (no key): 24 h ticker + hourly klines.

``api.binance.com`` answers HTTP 451 to US IP addresses; Binance's public market-data mirror
``data-api.binance.vision`` serves the same ``/api/v3`` market endpoints without the geo-block, so the provider
switches to it after a 451/403 (and stays there for the session).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .base import Endpoint, Provider

HOSTS = ("https://api.binance.com", "https://data-api.binance.vision")


class MarketsProvider(Provider[dict[str, dict[str, Any]]]):
    name = "markets"
    endpoints = (
        Endpoint(
            "Binance 24h ticker",
            "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT",
            expect=("lastPrice", "priceChangePercent", "highPrice", "lowPrice"),
            note="geo-blocked (451) from the US",
        ),
        Endpoint(
            "Binance market-data mirror",
            "https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT",
            expect=("lastPrice", "priceChangePercent"),
            role="fallback",
            note="no geo-block",
        ),
        Endpoint(
            "Binance klines",
            "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=3",
            expect=("0.4",),
        ),
    )
    interval = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.symbols: set[str] = {"BTC"}
        self.host = HOSTS[0]

    def want(self, *symbols: str) -> None:
        new = {s.upper().strip() for s in symbols if s.strip()} - self.symbols
        if new:
            self.symbols |= new
            self.refresh()

    async def _klines(self, pair: str) -> list[float]:
        r = await self.hub.http.get(
            f"{self.host}/api/v3/klines", params={"symbol": pair, "interval": "1h", "limit": 24}
        )
        r.raise_for_status()
        return [float(k[4]) for k in r.json()]

    async def fetch(self) -> dict[str, dict[str, Any]]:
        pairs = sorted(f"{s}USDT" for s in self.symbols)
        params = {"symbols": json.dumps(pairs, separators=(",", ":"))}
        r = await self.hub.http.get(f"{self.host}/api/v3/ticker/24hr", params=params)
        if r.status_code in (403, 451) and self.host == HOSTS[0]:
            self.host = HOSTS[1]  # geo-blocked (the US): use the market-data mirror from now on
            r = await self.hub.http.get(f"{self.host}/api/v3/ticker/24hr", params=params)
        r.raise_for_status()
        tickers = {t["symbol"]: t for t in r.json()}
        klines = await asyncio.gather(
            *(self._klines(p) for p in pairs if p in tickers), return_exceptions=True
        )
        out: dict[str, dict[str, Any]] = dict(self.value or {})
        for pair, hist in zip([p for p in pairs if p in tickers], klines, strict=True):
            t = tickers[pair]
            out[pair.removesuffix("USDT")] = {
                "price": float(t["lastPrice"]),
                "change": float(t["priceChangePercent"]),
                "high": float(t["highPrice"]),
                "low": float(t["lowPrice"]),
                "history": hist if isinstance(hist, list) else [],
            }
        return out
