"""Stocks, indices, ETFs, forex and futures from Yahoo Finance's public chart API (no key).

Sources, in order of preference (all keyless, verified live):

1. ``/v8/finance/chart/{SYMBOL}`` — one request per symbol, fetched concurrently. Carries the quote meta
   (price, previous close, day range, volume, currency, exchange, trading periods) and OHLC bars.
2. ``/v7/finance/spark?symbols=A,B,C`` — one batched request, closes only. Used for symbols whose chart
   request failed.
3. Stooq CSV quotes — last-resort fallback for US tickers and a few indices.

A symbol that keeps failing is backed off exponentially; its last good value stays in the cache.
"""

from __future__ import annotations

import asyncio
import csv
import io
import itertools
import math
import re
import time
from collections.abc import Sequence
from typing import Any

from .base import Provider

# range -> bar interval (chosen so every range yields ~70-400 points: enough for a 32-column chart)
RANGES: dict[str, str] = {"1d": "5m", "5d": "15m", "1mo": "1h", "6mo": "1d", "1y": "1d", "5y": "1wk"}

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_SPARK = "https://query1.finance.yahoo.com/v7/finance/spark"
STOOQ_QUOTE = "https://stooq.com/q/l/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json,text/csv,*/*",
}

SYMBOL_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-=&]{0,14}$")
HISTORY_POINTS = 120  # history is downsampled to at most this many closes
CANDLES = 32  # candles are aggregated into this many buckets
MAX_SYMBOLS = 24  # the provider remembers at most this many recently wanted symbols
STATES = ("PRE", "REGULAR", "POST", "CLOSED")


def normalize_symbol(raw: str) -> str | None:
    """'  aapl ' -> 'AAPL'; returns None for anything that can't be a Yahoo symbol."""
    s = raw.strip().upper()
    return s if SYMBOL_RE.match(s) else None


def parse_symbols(text: str) -> list[str]:
    """Comma/space separated list -> unique, valid, upper-cased symbols (order kept)."""
    out: list[str] = []
    for part in re.split(r"[,\s;]+", text):
        s = normalize_symbol(part) if part.strip() else None
        if s and s not in out:
            out.append(s)
    return out


# ---------------------------------------------------------------------------- helpers
def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def downsample(values: Sequence[float], n: int) -> list[float]:
    """Keep at most `n` points, evenly spaced, always keeping the first and last."""
    vals = list(values)
    if len(vals) <= n or n < 2:
        return vals
    step = (len(vals) - 1) / (n - 1)
    return [vals[round(i * step)] for i in range(n)]


def aggregate_candles(
    candles: Sequence[tuple[float, float, float, float]], n: int
) -> list[tuple[float, ...]]:
    """Merge consecutive OHLC bars into at most `n` buckets (open of first, extremes, close of last)."""
    c = list(candles)
    if len(c) <= n or n < 1:
        return [tuple(k) for k in c]
    out: list[tuple[float, ...]] = []
    for i in range(n):
        a, b = round(i * len(c) / n), round((i + 1) * len(c) / n)
        chunk = c[a : max(b, a + 1)]
        out.append((chunk[0][0], max(k[1] for k in chunk), min(k[2] for k in chunk), chunk[-1][3]))
    return out


def market_state(meta: dict[str, Any], now: float) -> str:
    """PRE / REGULAR / POST / CLOSED from Yahoo's currentTradingPeriod."""
    period = meta.get("currentTradingPeriod") or {}
    for key, state in (("regular", "REGULAR"), ("pre", "PRE"), ("post", "POST")):
        p = period.get(key) or {}
        start, end = _num(p.get("start")), _num(p.get("end"))
        if start is not None and end is not None and start <= now < end:
            return state
    return "CLOSED"


def _entry(
    symbol: str,
    meta: dict[str, Any],
    closes: list[float],
    candles: list[tuple[float, float, float, float]],
    range_: str,
    now: float,
) -> dict[str, Any]:
    price = _num(meta.get("regularMarketPrice"))
    if price is None:
        if not closes:
            raise ValueError(f"{symbol}: no price")
        price = closes[-1]
    # Yahoo's own day change % is authoritative (previousClose is occasionally stale, e.g. ^BSESN)
    pct = _num(meta.get("regularMarketChangePercent"))
    if pct is not None and pct > -100:
        prev = price / (1 + pct / 100)
    else:
        prev = _num(meta.get("previousClose"))
        if prev is None:
            prev = _num(meta.get("chartPreviousClose"))
    if prev is None or prev == 0:
        prev = closes[0] if closes else price
    change = price - prev
    hint = meta.get("priceHint")
    ref = prev if range_ == "1d" or not closes else closes[0]
    return {
        "symbol": symbol,
        "name": str(meta.get("shortName") or meta.get("longName") or symbol),
        "price": price,
        "prev_close": prev,
        "change": change,
        "change_pct": change / prev * 100 if prev else 0.0,
        "currency": str(meta.get("currency") or ""),
        "exchange": str(meta.get("fullExchangeName") or meta.get("exchangeName") or ""),
        "market_state": market_state(meta, now),
        "day_high": _num(meta.get("regularMarketDayHigh")),
        "day_low": _num(meta.get("regularMarketDayLow")),
        "volume": _num(meta.get("regularMarketVolume")),
        "decimals": int(hint) if isinstance(hint, int) and 0 <= hint <= 6 else (2 if price >= 1 else 4),
        "range": range_,
        "range_ref": ref,
        "history": downsample(closes, HISTORY_POINTS),
        "candles": [tuple(k) for k in aggregate_candles(candles, CANDLES)],
        "updated": now,
    }


# ---------------------------------------------------------------------------- parsers
def parse_chart(payload: dict[str, Any], range_: str = "1d", now: float | None = None) -> dict[str, Any]:
    """One ``/v8/finance/chart`` response -> one entry of the provider value."""
    now = time.time() if now is None else now
    chart = payload.get("chart") or {}
    if chart.get("error"):
        err = chart["error"]
        raise ValueError(str(err.get("description") or err) if isinstance(err, dict) else str(err))
    result = (chart.get("result") or [None])[0]
    if not result:
        raise ValueError("empty chart result")
    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    opens, highs, lows, raw_closes = (list(quote.get(k) or []) for k in ("open", "high", "low", "close"))

    def at(col: list[Any], i: int) -> float | None:
        return _num(col[i]) if i < len(col) else None

    closes: list[float] = []
    candles: list[tuple[float, float, float, float]] = []
    for i, raw in enumerate(raw_closes):
        c = _num(raw)
        if c is None:
            continue
        closes.append(c)
        o, h, lo = at(opens, i), at(highs, i), at(lows, i)
        if o is not None and h is not None and lo is not None:
            candles.append((o, max(h, o, c), min(lo, o, c), c))
    if not candles and len(closes) > 1:  # closes only (spark): synthesise bars from consecutive closes
        candles = [(a, max(a, b), min(a, b), b) for a, b in itertools.pairwise(closes)]
    symbol = str(meta.get("symbol") or "").upper()
    return _entry(symbol, meta, closes, candles, range_, now)


def parse_spark(
    payload: dict[str, Any], range_: str = "1d", now: float | None = None
) -> dict[str, dict[str, Any]]:
    """A batched ``/v7/finance/spark`` response -> {SYMBOL: entry} (closes only, candles synthesised)."""
    now = time.time() if now is None else now
    out: dict[str, dict[str, Any]] = {}
    for item in (payload.get("spark") or {}).get("result") or []:
        for resp in item.get("response") or []:
            try:
                e = parse_chart({"chart": {"result": [resp]}}, range_, now)
            except (ValueError, TypeError, KeyError):
                continue
            out[e["symbol"] or str(item.get("symbol")).upper()] = e
    return out


def stooq_symbol(symbol: str) -> str | None:
    """Yahoo symbol -> Stooq symbol (US listings and a few indices only)."""
    idx = {"^GSPC": "^spx", "^DJI": "^dji", "^IXIC": "^ndq", "^NDX": "^ndx"}
    if symbol in idx:
        return idx[symbol]
    if re.fullmatch(r"[A-Z]{1,5}(-[A-Z])?", symbol):
        return f"{symbol.lower()}.us"
    return None


def parse_stooq(
    text: str, symbols: dict[str, str], range_: str = "1d", now: float | None = None
) -> dict[str, Any]:
    """Stooq ``f=sd2t2ohlcv&h&e=csv`` quote CSV -> {SYMBOL: entry}; `symbols` maps stooq -> Yahoo symbol.

    Stooq has no previous close in this format, so the day's open stands in as the reference.
    """
    now = time.time() if now is None else now
    out: dict[str, Any] = {}
    for row in csv.DictReader(io.StringIO(text.strip())):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        sym = symbols.get(row.get("symbol", "").lower())
        o, h, lo, c = (_num(row.get(k)) for k in ("open", "high", "low", "close"))
        if not sym or c is None or o is None:
            continue
        meta = {
            "symbol": sym,
            "regularMarketPrice": c,
            "previousClose": o,
            "regularMarketDayHigh": h,
            "regularMarketDayLow": lo,
            "regularMarketVolume": _num(row.get("volume")),
            "currency": "USD",
            "exchangeName": "STOOQ",
        }
        out[sym] = _entry(sym, meta, [o, c], [(o, h or c, lo or c, c)], range_, now)
    return out


# ---------------------------------------------------------------------------- provider
class StocksProvider(Provider[dict[str, dict[str, Any]]]):
    """``value = {SYMBOL: entry}``; see `_entry` for the fields. Apps call ``want(symbols, range_)``."""

    name = "stocks"
    interval = 45.0  # while any wanted market is trading
    closed_interval = 180.0  # when every wanted market is closed
    retry = 20.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.symbols: list[str] = []  # most recently wanted last
        self.range = "1d"
        self._fails: dict[str, int] = {}
        self._skip_until: dict[str, float] = {}
        self._last_error = ""

    # ------------------------------------------------------------ interface
    def want(self, symbols: Sequence[str], range_: str = "1d") -> None:
        clean = [s for s in (normalize_symbol(x) for x in symbols) if s]
        rng = range_ if range_ in RANGES else "1d"
        new = [s for s in clean if s not in self.symbols]
        for s in clean:  # refresh recency
            if s in self.symbols:
                self.symbols.remove(s)
            self.symbols.append(s)
        del self.symbols[:-MAX_SYMBOLS]
        if new or rng != self.range:
            if rng != self.range:
                self._skip_until.clear()
            self.range = rng
            self.refresh()

    def next_interval(self) -> float:
        vals = [(self.value or {}).get(s) for s in self.symbols]
        if vals and all(v and v.get("market_state") == "CLOSED" for v in vals):
            return self.closed_interval
        return self.interval

    def announce(self, old: dict[str, dict[str, Any]] | None, new: dict[str, dict[str, Any]]) -> bool:
        def key(d: dict[str, dict[str, Any]] | None) -> Any:
            return {
                k: (v["price"], v["market_state"], v["range"], len(v["history"]))
                for k, v in (d or {}).items()
            }

        return key(old) != key(new)

    # ------------------------------------------------------------ fetching
    async def _chart(self, symbol: str, range_: str) -> dict[str, Any]:
        r = await self.hub.http.get(
            YAHOO_CHART.format(symbol=symbol),
            params={"range": range_, "interval": RANGES[range_], "includePrePost": "true"},
            headers=HEADERS,
        )
        if r.status_code == 404:
            raise ValueError(f"{symbol}: unknown symbol")
        r.raise_for_status()
        e = parse_chart(r.json(), range_)
        e["symbol"] = symbol  # keep the requested spelling as the key
        return e

    async def _spark(self, symbols: list[str], range_: str) -> dict[str, Any]:
        r = await self.hub.http.get(
            YAHOO_SPARK,
            params={"symbols": ",".join(symbols), "range": range_, "interval": RANGES[range_]},
            headers=HEADERS,
        )
        r.raise_for_status()
        return parse_spark(r.json(), range_)

    async def _stooq(self, symbols: list[str], range_: str) -> dict[str, Any]:
        mapping = {m: s for s in symbols if (m := stooq_symbol(s))}
        if not mapping:
            return {}
        r = await self.hub.http.get(
            f"{STOOQ_QUOTE}?s={','.join(mapping)}&f=sd2t2ohlcv&h&e=csv", headers=HEADERS
        )
        r.raise_for_status()
        return parse_stooq(r.text, mapping, range_)

    async def fetch(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        rng = self.range
        todo = [s for s in self.symbols if self._skip_until.get(s, 0) <= now]
        out: dict[str, dict[str, Any]] = dict(self.value or {})
        if not todo:
            if not self.symbols:
                return out
            raise RuntimeError(self._last_error or "backing off")
        sem = asyncio.Semaphore(6)

        async def one(s: str) -> dict[str, Any]:
            async with sem:
                return await self._chart(s, rng)

        results = await asyncio.gather(*(one(s) for s in todo), return_exceptions=True)
        failed: list[str] = []
        errors: list[str] = []
        for s, res in zip(todo, results, strict=True):
            if isinstance(res, BaseException):
                failed.append(s)
                errors.append(f"{s}: {type(res).__name__}: {res}")
            else:
                out[s] = res
        for fallback in (self._spark, self._stooq):
            if not failed:
                break
            try:
                got = await fallback(failed, rng)
            except Exception as e:  # a fallback failing is expected
                errors.append(f"{fallback.__name__}: {type(e).__name__}")
                continue
            for s in list(failed):
                if s in got:
                    got[s]["symbol"] = s
                    out[s] = got[s]
                    failed.remove(s)
        for s in todo:
            if s in failed:
                n = self._fails[s] = self._fails.get(s, 0) + 1
                self._skip_until[s] = now + min(900.0, self.retry * 2 ** (n - 1))
            else:
                self._fails.pop(s, None)
                self._skip_until.pop(s, None)
        if failed and len(failed) == len(todo):
            self._last_error = "; ".join(errors)[:200]
            raise RuntimeError(self._last_error)
        # forget symbols nobody wants any more
        return {k: v for k, v in out.items() if k in self.symbols}
