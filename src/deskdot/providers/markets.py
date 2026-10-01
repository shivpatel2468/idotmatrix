"""Crypto prices from Binance public endpoints (no key): 24 h ticker + hourly klines."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .base import Provider


class MarketsProvider(Provider[dict[str, dict[str, Any]]]):
    name = "markets"
    interval = 30.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.symbols: set[str] = {"BTC"}

    def want(self, *symbols: str) -> None:
        new = {s.upper().strip() for s in symbols if s.strip()} - self.symbols
        if new:
            self.symbols |= new
            self.refresh()

    async def _klines(self, pair: str) -> list[float]:
        r = await self.hub.http.get(
            "https://api.binance.com/api/v3/klines", params={"symbol": pair, "interval": "1h", "limit": 24}
        )
        r.raise_for_status()
        return [float(k[4]) for k in r.json()]

    async def fetch(self) -> dict[str, dict[str, Any]]:
        pairs = sorted(f"{s}USDT" for s in self.symbols)
        r = await self.hub.http.get(
            "https://api.binance.com/api/v3/ticker/24hr",
            params={"symbols": json.dumps(pairs, separators=(",", ":"))},
        )
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
