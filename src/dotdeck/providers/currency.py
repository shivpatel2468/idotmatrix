"""Exchange rates: Frankfurter (ECB reference rates) with the fawazahmed0 currency API as fallback.

Both keyless, verified live:

* **Frankfurter** ``https://api.frankfurter.dev/v1/{start}..?symbols=A,B`` — one time-series request (base EUR)
  returns every ECB currency for the whole range; any pair is a cross of two EUR rates, which keeps full
  precision (``base=INR`` would round 1/95.7 to five decimals). ~30 currencies, weekdays only.
  (``api.frankfurter.app`` 301-redirects here.)
* **fawazahmed0/currency-api** ``https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date|latest}/v1/
  currencies/{base}.json`` (mirror ``{date|latest}.currency-api.pages.dev``) — 150+ fiat currencies, metals and
  crypto, daily snapshots. Used for anything the ECB lacks (AED, SAR, BTC…) or when Frankfurter is down; the
  sparkline comes from a handful of dated snapshots, which never change and are cached forever.

``value = {"base", "range", "date", "pairs": {CODE: {code, rate, prev, change_pct, range_pct, history, date,
source}}}`` where ``rate`` is the price of **one CODE in base** (1 USD = 95.74 INR).
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from .base import Provider

FRANKFURTER = "https://api.frankfurter.dev/v1"
FAWAZ = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{tag}/v1/currencies/{base}.json",
    "https://{tag}.currency-api.pages.dev/v1/currencies/{base}.json",
)
# ECB reference currencies (Frankfurter /v1/currencies); refreshed from the API when reachable
_ECB_CODES = (
    "AUD BGN BRL CAD CHF CNY CZK DKK EUR GBP HKD HUF IDR ILS INR ISK JPY KRW MXN MYR NOK NZD PHP PLN RON SEK"
)
ECB = frozenset([*_ECB_CODES.split(), "SGD", "THB", "TRY", "USD", "ZAR"])
RANGES = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
CODE_RE = re.compile(r"^[A-Z0-9]{2,6}$")
SNAPSHOTS = 8  # dated fawaz snapshots per sparkline
HISTORY_POINTS = 64


def parse_codes(text: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[,\s;/]+", text or ""):
        c = part.strip().upper()
        if c and CODE_RE.match(c) and c not in out:
            out.append(c)
    return out


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _downsample(vals: list[float], n: int) -> list[float]:
    if len(vals) <= n:
        return vals
    step = (len(vals) - 1) / (n - 1)
    return [vals[round(i * step)] for i in range(n)]


def pair_entry(code: str, series: list[tuple[str, float]], source: str) -> dict[str, Any] | None:
    """[(date, price of 1 code in base)] oldest first → a pair entry."""
    pts = [(d, v) for d, v in series if v is not None and v > 0]
    if not pts:
        return None
    rate = pts[-1][1]
    prev = pts[-2][1] if len(pts) > 1 else rate
    first = pts[0][1]
    return {
        "code": code,
        "rate": rate,
        "prev": prev,
        "change_pct": (rate - prev) / prev * 100 if prev else 0.0,
        "range_pct": (rate - first) / first * 100 if first else 0.0,
        "history": _downsample([v for _d, v in pts], HISTORY_POINTS),
        "date": pts[-1][0],
        "source": source,
    }


def parse_frankfurter(payload: dict[str, Any], base: str, codes: Sequence[str]) -> dict[str, dict[str, Any]]:
    """A base-EUR time series → {CODE: entry} priced in `base` (crosses via EUR)."""
    rates = payload.get("rates") or {}
    if payload.get("base") and "rates" in payload and not isinstance(next(iter(rates.values()), {}), dict):
        rates = {payload.get("date", ""): rates}  # a /latest payload
    out: dict[str, dict[str, Any]] = {}
    days = sorted(rates)
    for code in codes:
        series: list[tuple[str, float]] = []
        for d in days:
            row = rates[d] or {}
            eur_base = 1.0 if base == "EUR" else _num(row.get(base))
            eur_code = 1.0 if code == "EUR" else _num(row.get(code))
            if eur_base and eur_code:
                series.append((d, eur_base / eur_code))
        e = pair_entry(code, series, "ecb")
        if e:
            out[code] = e
    return out


def fawaz_rate(payload: dict[str, Any], base: str, code: str) -> float | None:
    """1 `code` expressed in `base`, from a ``currencies/{base}.json`` snapshot."""
    table = payload.get(base.lower()) or {}
    x = _num(table.get(code.lower()))
    return 1.0 / x if x else None


class CurrencyProvider(Provider[dict[str, Any]]):
    name = "currency"
    interval = 1800.0  # reference rates change once a day; crypto on fawaz daily too
    retry = 60.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.base = "INR"
        self.codes: list[str] = ["USD", "EUR", "GBP"]
        self.range = "30d"
        self.ecb: frozenset[str] = ECB
        self._ecb_checked = False
        self._snap: dict[tuple[str, str], dict[str, Any]] = {}  # (date, base) -> fawaz payload

    def want(self, base: str, codes: Sequence[str], range_: str = "30d") -> None:
        b = base.upper() if CODE_RE.match(base.upper()) else "INR"
        cs = [c for c in (x.upper() for x in codes) if CODE_RE.match(c) and c != b][:16]
        rng = range_ if range_ in RANGES else "30d"
        if (b, cs, rng) != (self.base, self.codes, self.range):
            changed = b != self.base or rng != self.range or any(c not in self.codes for c in cs)
            self.base, self.codes, self.range = b, cs, rng
            if changed:
                self.refresh()

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        def sig(v: dict[str, Any] | None) -> Any:
            return v and (v["base"], v["range"], {k: (e["rate"], e["date"]) for k, e in v["pairs"].items()})

        return sig(old) != sig(new)

    # ------------------------------------------------------------ fetching
    async def _json(self, url: str, **kw: Any) -> Any:
        r = await self.hub.http.get(url, **kw)
        r.raise_for_status()
        return r.json()

    async def _frankfurter(self, codes: list[str], days: int) -> dict[str, dict[str, Any]]:
        if not self._ecb_checked:
            try:
                cur = await self._json(f"{FRANKFURTER}/currencies")
                self.ecb = frozenset(cur) | {"EUR"}
            except Exception:
                pass
            self._ecb_checked = True
        need = sorted({c for c in [*codes, self.base] if c != "EUR"})
        start = (date.today() - timedelta(days=days + 4)).isoformat()
        payload = await self._json(f"{FRANKFURTER}/{start}..", params={"symbols": ",".join(need)})
        return parse_frankfurter(payload, self.base, codes)

    async def _fawaz_snapshot(self, tag: str, base: str) -> dict[str, Any]:
        key = (tag, base.lower())
        if key in self._snap and tag != "latest":
            return self._snap[key]
        err: Exception | None = None
        for tpl in FAWAZ:
            try:
                d = await self._json(tpl.format(tag=tag, base=base.lower()))
                if tag != "latest":
                    self._snap[key] = d
                    if len(self._snap) > 64:
                        self._snap.pop(next(iter(self._snap)))
                return d  # type: ignore[no-any-return]
            except Exception as e:
                err = e
        raise err or RuntimeError("fawaz unavailable")

    async def _fawaz(self, codes: list[str], days: int) -> dict[str, dict[str, Any]]:
        today = date.today()
        tags = sorted(
            {
                (today - timedelta(days=round(days * k / (SNAPSHOTS - 1)))).isoformat()
                for k in range(1, SNAPSHOTS)
            }
            | {(today - timedelta(days=1)).isoformat()}
        )
        latest = await self._fawaz_snapshot("latest", self.base)
        res = await asyncio.gather(
            *(self._fawaz_snapshot(t, self.base) for t in tags), return_exceptions=True
        )
        snaps = [d for d in res if isinstance(d, dict)] + [latest]
        snaps.sort(key=lambda d: str(d.get("date", "")))
        out: dict[str, dict[str, Any]] = {}
        for code in codes:
            series = []
            seen: set[str] = set()
            for d in snaps:
                day = str(d.get("date", ""))
                v = fawaz_rate(d, self.base, code)
                if v and day not in seen:
                    seen.add(day)
                    series.append((day, v))
            e = pair_entry(code, series, "fawaz")
            if e:
                out[code] = e
        return out

    async def fetch(self) -> dict[str, Any]:
        base, codes, rng = self.base, list(self.codes), self.range
        days = RANGES[rng]
        pairs: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        ecb_codes = [c for c in codes if c in self.ecb] if base in self.ecb else []
        if ecb_codes:
            try:
                pairs.update(await self._frankfurter(ecb_codes, days))
            except Exception as e:
                errors.append(f"frankfurter: {type(e).__name__}: {e}")
        rest = [c for c in codes if c not in pairs]
        if rest:
            try:
                pairs.update(await self._fawaz(rest, days))
            except Exception as e:
                errors.append(f"fawaz: {type(e).__name__}: {e}")
        if not pairs and codes:
            raise RuntimeError("; ".join(errors)[:200] or "no rates")
        dates = sorted(e["date"] for e in pairs.values())
        return {"base": base, "range": rng, "date": dates[-1] if dates else "", "pairs": pairs}
