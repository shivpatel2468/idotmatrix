"""The whole crypto market: CoinGecko's keyless public API plus alternative.me's Fear & Greed index.

* ``api.coingecko.com/api/v3/global`` — total market cap, 24 h change, BTC/ETH dominance;
* ``/coins/markets?vs_currency=usd&per_page=30`` — the biggest coins with their 24 h change (top movers);
* ``api.alternative.me/fng/?limit=30`` — the sentiment index (0 extreme fear … 100 extreme greed), daily.

CoinGecko's public tier allows ~5–15 calls/min per IP; this polls 2 calls every 5 minutes.

``value = {"cap", "cap_change", "volume", "btc_dom", "eth_dom", "coins": [{symbol, name, price, change}],
"fng": {value, label, history: [30 values, oldest first], next_update} | None, "updated"}``.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

from .base import Endpoint, Provider

COINGECKO = "https://api.coingecko.com/api/v3"
FNG = "https://api.alternative.me/fng/"
STABLE = {
    "usdt",
    "usdc",
    "dai",
    "fdusd",
    "usde",
    "tusd",
    "pyusd",
    "usds",
    "busd",
    "usd1",
    "steth",
    "wbtc",
    "weth",
}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def parse_global(d: Any) -> dict[str, Any]:
    g = d.get("data") if isinstance(d, dict) else None
    if not isinstance(g, dict) or "total_market_cap" not in g:
        raise ValueError("coingecko global: unexpected shape")
    dom = g.get("market_cap_percentage") or {}
    return {
        "cap": _f((g.get("total_market_cap") or {}).get("usd")),
        "volume": _f((g.get("total_volume") or {}).get("usd")),
        "cap_change": _f(g.get("market_cap_change_percentage_24h_usd")),
        "btc_dom": _f(dom.get("btc")),
        "eth_dom": _f(dom.get("eth")),
    }


def parse_markets(d: Any) -> list[dict[str, Any]]:
    out = []
    for c in d if isinstance(d, list) else []:
        if not isinstance(c, dict):
            continue
        sym = str(c.get("symbol") or "").lower()
        price, ch = _f(c.get("current_price")), _f(c.get("price_change_percentage_24h"))
        if not sym or price is None or ch is None:
            continue
        out.append(
            {
                "symbol": sym.upper()[:6],
                "name": str(c.get("name") or sym),
                "price": price,
                "change": ch,
                "rank": int(c.get("market_cap_rank") or 999),
                "stable": sym in STABLE,
            }
        )
    return out


def fng_label(v: float) -> str:
    return (
        "EXTREME FEAR"
        if v < 25
        else "FEAR"
        if v < 46
        else "NEUTRAL"
        if v < 55
        else "GREED"
        if v < 76
        else "EXTREME GREED"
    )


def parse_fng(d: Any) -> dict[str, Any]:
    rows = d.get("data") if isinstance(d, dict) else None
    vals = [(int(r["timestamp"]), int(r["value"])) for r in rows or [] if str(r.get("value", "")).isdigit()]
    if not vals:
        raise ValueError("fng: no data")
    vals.sort()
    v = vals[-1][1]
    nxt = _f(rows[0].get("time_until_update")) if rows else None
    return {"value": v, "label": fng_label(v), "history": [x for _t, x in vals], "next_update": nxt}


def movers(coins: list[dict[str, Any]], n: int = 3) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(top gainers, top losers) among non-stable coins, biggest move first."""
    pool = [c for c in coins if not c.get("stable")]
    up = sorted((c for c in pool if c["change"] > 0), key=lambda c: -c["change"])[:n]
    down = sorted((c for c in pool if c["change"] < 0), key=lambda c: c["change"])[:n]
    return up, down


class CryptoMarketProvider(Provider[dict[str, Any]]):
    name = "cryptomarket"
    endpoints = (
        Endpoint(
            "CoinGecko global", COINGECKO + "/global", check=parse_global, note="public tier ~5-15 calls/min"
        ),
        Endpoint(
            "CoinGecko markets",
            COINGECKO + "/coins/markets?vs_currency=usd&per_page=5&price_change_percentage=24h",
            check=parse_markets,
        ),
        Endpoint("Fear & Greed (alternative.me)", FNG + "?limit=30", check=parse_fng),
    )
    interval = 300.0
    retry = 90.0

    async def _json(self, url: str, **params: Any) -> Any:
        r = await self.hub.http.get(url, params=params or None)
        r.raise_for_status()
        return r.json()

    async def fetch(self) -> dict[str, Any]:
        g, m, f = await asyncio.gather(
            self._json(COINGECKO + "/global"),
            self._json(
                COINGECKO + "/coins/markets", vs_currency="usd", per_page=40, price_change_percentage="24h"
            ),
            self._json(FNG, limit=30),
            return_exceptions=True,
        )
        old = self.value or {}
        if isinstance(g, BaseException) and isinstance(m, BaseException):
            raise g
        out: dict[str, Any] = dict(old)
        if not isinstance(g, BaseException):
            out.update(parse_global(g))
        if not isinstance(m, BaseException):
            out["coins"] = parse_markets(m)
        out.setdefault("coins", [])
        if not isinstance(f, BaseException):
            try:
                out["fng"] = parse_fng(f)
            except ValueError:
                pass
        out.setdefault("fng", None)
        out["updated"] = time.time()
        return out
