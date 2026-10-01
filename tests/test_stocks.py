"""Stocks provider parsing (offline fixtures) and the Stocks app: every variant renders, alerts fire once."""

from __future__ import annotations

import itertools
import json
import time
from typing import Any

import pytest
from pydantic import ValidationError

from dotdeck.apps.stocks import Stocks, StocksSettings, short_label
from dotdeck.gfx import Frame
from dotdeck.providers.stocks import (
    StocksProvider,
    aggregate_candles,
    downsample,
    market_state,
    normalize_symbol,
    parse_chart,
    parse_spark,
    parse_stooq,
    parse_symbols,
    stooq_symbol,
)

NOW = 1790190000.0  # inside the regular session of the fixture below


def _meta(symbol: str, price: float, pct: float, **kw: Any) -> dict[str, Any]:
    m = {
        "currency": "USD",
        "symbol": symbol,
        "exchangeName": "NMS",
        "fullExchangeName": "NasdaqGS",
        "regularMarketPrice": price,
        "regularMarketChangePercent": pct,
        "regularMarketDayHigh": price * 1.01,
        "regularMarketDayLow": price * 0.99,
        "regularMarketVolume": 31482942,
        "longName": "Apple Inc.",
        "shortName": "Apple Inc.",
        "chartPreviousClose": 339.75,
        "previousClose": 339.75,
        "priceHint": 2,
        "currentTradingPeriod": {
            "pre": {"start": 1790150400, "end": 1790170200},
            "regular": {"start": 1790170200, "end": 1790193600},
            "post": {"start": 1790193600, "end": 1790208000},
        },
    }
    m.update(kw)
    return m


# trimmed real /v8/finance/chart/AAPL?range=1d&interval=5m response (one null bar, as Yahoo sends)
YAHOO_CHART = {
    "chart": {
        "result": [
            {
                "meta": _meta("AAPL", 337.02, -0.804),
                "timestamp": [1790170200, 1790170500, 1790170800, 1790171100, 1790171400],
                "indicators": {
                    "quote": [
                        {
                            "open": [339.0, 338.5, None, 337.5, 337.2],
                            "high": [339.4, 338.9, None, 337.9, 337.4],
                            "low": [338.2, 337.8, None, 337.0, 336.8],
                            "close": [338.6, 338.0, None, 337.3, 337.02],
                            "volume": [100, 200, None, 300, 400],
                        }
                    ]
                },
            }
        ],
        "error": None,
    }
}
YAHOO_404 = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
YAHOO_SPARK = {
    "spark": {
        "result": [
            {
                "symbol": "^NSEI",
                "response": [
                    {
                        "meta": _meta("^NSEI", 23446.8, 0.139, currency="INR", exchangeName="NSI"),
                        "timestamp": [1, 2, 3],
                        "indicators": {"quote": [{"close": [23400.0, 23420.5, 23446.8]}]},
                    }
                ],
            }
        ],
        "error": None,
    }
}
STOOQ_CSV = "Symbol,Date,Time,Open,High,Low,Close,Volume\r\nAAPL.US,2026-09-23,22:00:00,339.1,341.8,335.61,337.02,31482942\r\n"


# ----------------------------------------------------------------------------- provider parsing
def test_parse_yahoo_chart() -> None:
    e = parse_chart(YAHOO_CHART, "1d", NOW)
    assert e["symbol"] == "AAPL" and e["price"] == 337.02
    assert e["change_pct"] == pytest.approx(-0.804, abs=1e-6)
    assert e["prev_close"] == pytest.approx(339.75, abs=0.01)
    assert e["change"] == pytest.approx(-2.73, abs=0.01)
    assert e["currency"] == "USD" and e["exchange"] == "NasdaqGS"
    assert e["market_state"] == "REGULAR"
    assert e["history"] == [338.6, 338.0, 337.3, 337.02]  # null bar dropped
    assert len(e["candles"]) == 4 and all(h >= max(o, c) and lo <= min(o, c) for o, h, lo, c in e["candles"])
    assert e["volume"] == 31482942 and e["day_high"] > e["day_low"]
    assert e["decimals"] == 2 and e["range_ref"] == pytest.approx(339.75, abs=0.01)
    json.dumps(e)  # the value is pushed to the studio as JSON


def test_parse_yahoo_errors() -> None:
    with pytest.raises(ValueError):
        parse_chart(YAHOO_404)
    with pytest.raises(ValueError):
        parse_chart({"chart": {"result": []}})


def test_market_states() -> None:
    meta = _meta("AAPL", 1, 0)
    assert market_state(meta, 1790160000) == "PRE"
    assert market_state(meta, 1790200000) == "POST"
    assert market_state(meta, 1790300000) == "CLOSED"
    assert market_state({}, NOW) == "CLOSED"


def test_parse_spark_batch() -> None:
    out = parse_spark(YAHOO_SPARK, "1d", NOW)
    e = out["^NSEI"]
    assert e["currency"] == "INR" and e["history"] == [23400.0, 23420.5, 23446.8]
    assert len(e["candles"]) == 2  # synthesised from consecutive closes


def test_parse_stooq_csv() -> None:
    out = parse_stooq(STOOQ_CSV, {"aapl.us": "AAPL"}, "1d", NOW)
    e = out["AAPL"]
    assert e["price"] == 337.02 and e["prev_close"] == 339.1 and e["change"] < 0
    assert stooq_symbol("AAPL") == "aapl.us" and stooq_symbol("^GSPC") == "^spx"
    assert stooq_symbol("RELIANCE.NS") is None


def test_symbol_validation() -> None:
    assert normalize_symbol(" aapl ") == "AAPL"
    assert normalize_symbol("^nsei") == "^NSEI"
    for ok in ("RELIANCE.NS", "USDINR=X", "GC=F", "BRK-B", "M&M.NS"):
        assert normalize_symbol(ok) == ok
    for bad in ("", "  ", "AA PL", "$$$", "^", "A" * 20, "x/y"):
        assert normalize_symbol(bad) is None
    assert parse_symbols("aapl, nvda;tsla  aapl,, bad/sym") == ["AAPL", "NVDA", "TSLA"]
    assert StocksSettings(symbols=" aapl , ^nsei ,aapl").symbols == "AAPL,^NSEI"
    with pytest.raises(ValidationError):
        StocksSettings(symbols=" , ;")


def test_downsample_and_candles() -> None:
    v = list(range(500))
    d = downsample(v, 120)
    assert len(d) == 120 and d[0] == 0 and d[-1] == 499
    c = aggregate_candles([(i, i + 2, i - 1, i + 1) for i in range(100)], 10)
    assert len(c) == 10 and c[0][0] == 0 and c[-1][3] == 100
    assert (
        short_label("^NSEI") == "NIFTY"
        and short_label("TCS.NS") == "TCS"
        and short_label("EURUSD=X") == "EURUSD"
    )


async def test_provider_fetch_with_fallback() -> None:
    """Chart fails for one symbol -> spark fallback fills it; unknown symbols back off; cache survives."""

    class Resp:
        def __init__(self, status: int, payload: Any) -> None:
            self.status_code, self._p = status, payload
            self.text = payload if isinstance(payload, str) else json.dumps(payload)

        def json(self) -> Any:
            return self._p

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class Http:
        async def get(self, url: str, params: Any = None, headers: Any = None) -> Resp:
            if "/v8/finance/chart/AAPL" in url:
                return Resp(200, YAHOO_CHART)
            if "/v8/finance/chart/" in url:
                return Resp(404 if "NOPE" in url else 500, YAHOO_404)
            if "/v7/finance/spark" in url:
                return Resp(200, YAHOO_SPARK)
            return Resp(404, "gone")

    class Hub:
        http = Http()

        def on_change(self, name: str) -> None:
            pass

    p = StocksProvider(Hub())  # type: ignore[arg-type]
    p.want(["aapl", "^NSEI", "NOPE1"], "5d")
    assert p.range == "5d" and p.symbols == ["AAPL", "^NSEI", "NOPE1"]
    v = await p.fetch()
    assert set(v) == {"AAPL", "^NSEI"}
    assert "NOPE1" in p._skip_until  # backed off
    p.value = v
    p.want(["NOPE1"], "5d")
    with pytest.raises(RuntimeError):  # only a backed-off symbol left to fetch -> error, cache kept
        p.symbols = ["NOPE1"]
        await p.fetch()


# ----------------------------------------------------------------------------- the app
class FakeProvider:
    def __init__(self, value: Any = None, error: str | None = None) -> None:
        self.value, self.error, self.updated = value, error, time.time()
        self.wants: list[Any] = []

    def want(self, symbols: list[str], range_: str) -> None:
        self.wants.append((list(symbols), range_))


class FakeCtx:
    def __init__(self, provider: FakeProvider | None) -> None:
        self.p = provider
        self.notes: list[dict[str, Any]] = []

    def provider(self, name: str) -> FakeProvider:
        if self.p is None:
            raise KeyError(name)
        return self.p

    def notify(self, **kw: Any) -> None:
        self.notes.append(kw)


def _fake_data() -> dict[str, Any]:
    base = parse_chart(YAHOO_CHART, "1d", NOW)
    out = {}
    specs = [
        ("AAPL", 337.02, -0.8, "USD"),
        ("NVDA", 225.51, 1.47, "USD"),
        ("^NSEI", 23446.8, 0.0, "INR"),
        ("RELIANCE.NS", 1248.0, 3.9, "INR"),
        ("EURUSD=X", 1.1388, -0.57, "EUR"),
    ]
    for sym, price, pct, cur in specs:
        e = dict(base, symbol=sym, price=price, change_pct=pct, change=price * pct / 100, currency=cur)
        e["history"] = [price * (1 + 0.01 * ((i * 7) % 11 - 5) / 5) for i in range(60)]
        e["candles"] = [
            (h, h * 1.002, h * 0.997, h * (1.001 if i % 2 else 0.999))
            for i, h in enumerate(e["history"][:32])
        ]
        e["range_ref"] = price / (1 + pct / 100)
        out[sym] = e
    return out


def _choices() -> dict[str, list[str]]:
    out = {}
    for name, field in StocksSettings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            out[name] = list(extra["enum"])
    return out


SYMS = "AAPL,NVDA,^NSEI,RELIANCE.NS,EURUSD=X,MISSING"
CH = _choices()
MATRIX = list(itertools.product(CH["layout"], CH["chart"]))
OTHERS = [(k, v) for k, vs in CH.items() if k not in ("layout", "chart") for v in vs]


def _render(app: Stocks, ts: tuple[float, ...] = (0.0, 0.37, 8.5, 17.3, 40.0)) -> list[Frame]:
    frames = []
    for t in ts:
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, t)
        assert time.perf_counter() - t0 < 0.05
        frames.append(f)
    return frames


@pytest.mark.parametrize(("layout", "chart"), MATRIX, ids=[f"{a}-{b}" for a, b in MATRIX])
def test_layout_chart_matrix(layout: str, chart: str) -> None:
    app = Stocks(
        FakeCtx(FakeProvider(_fake_data())), StocksSettings(symbols=SYMS, layout=layout, chart=chart)
    )  # type: ignore[arg-type]
    frames = _render(app)
    assert any(f.px.any() for f in frames)
    st = app.status()
    assert st["symbols"] == 6 and st["shown"] in SYMS.split(",")


@pytest.mark.parametrize(("field", "value"), OTHERS, ids=[f"{a}={b}" for a, b in OTHERS])
@pytest.mark.parametrize("layout", CH["layout"])
def test_every_option(layout: str, field: str, value: str) -> None:
    s = StocksSettings(symbols=SYMS, layout=layout, **{field: value})
    _render(Stocks(FakeCtx(FakeProvider(_fake_data())), s))  # type: ignore[arg-type]


@pytest.mark.parametrize("layout", CH["layout"])
@pytest.mark.parametrize(
    "settings",
    [
        {"show_currency": True, "compact": True, "decimals": 4},
        {"show_market_state": False, "decimals": 0, "heat_scale": 0.5},
        {"symbols": "AAPL"},
        {"symbols": ",".join(f"S{i}" for i in range(20))},
    ],
)
def test_detail_options(layout: str, settings: dict[str, Any]) -> None:
    s = StocksSettings(**{"symbols": SYMS, "layout": layout, **settings})
    _render(Stocks(FakeCtx(FakeProvider(_fake_data())), s))  # type: ignore[arg-type]


@pytest.mark.parametrize("layout", CH["layout"])
@pytest.mark.parametrize("state", ["no-provider", "loading", "offline", "stale"])
def test_no_data_states(layout: str, state: str) -> None:
    prov = {
        "no-provider": None,
        "loading": FakeProvider(None),
        "offline": FakeProvider(None, "ConnectError"),
        "stale": FakeProvider(_fake_data(), "ConnectError"),
    }[state]
    app = Stocks(FakeCtx(prov), StocksSettings(layout=layout))  # type: ignore[arg-type]
    frames = _render(app)
    assert any(f.px.any() for f in frames)
    assert app.kind() in ("stream", "clip")
    if state == "stale":
        assert frames[0].get(0, 31) != (0, 0, 0)


def test_themes_change_pixels() -> None:
    data = _fake_data()
    seen = set()
    for theme in CH["theme"]:
        f = Frame()
        Stocks(FakeCtx(FakeProvider(data)), StocksSettings(symbols="AAPL", theme=theme)).render(f, 0)  # type: ignore[arg-type]
        seen.add(f.to_bytes())
    assert len(seen) == len(CH["theme"])


def test_ticker_is_a_seamless_clip() -> None:
    app = Stocks(FakeCtx(FakeProvider(_fake_data())), StocksSettings(symbols=SYMS, layout="ticker"))  # type: ignore[arg-type]
    assert app.kind() == "clip"
    clip = app.clip_frames()
    assert 1 <= len(clip.frames) <= 160 and len(clip.durations_ms) == len(clip.frames)
    key = app.clip_key()
    app.ctx.p.value["AAPL"] = dict(app.ctx.p.value["AAPL"], price=400.0)  # type: ignore[attr-defined]
    assert app.clip_key() != key  # new prices re-bake the tape
    assert Stocks(FakeCtx(FakeProvider(None)), StocksSettings(layout="ticker")).kind() == "stream"  # type: ignore[arg-type]


def test_want_on_start_and_settings() -> None:
    prov = FakeProvider(None)
    app = Stocks(FakeCtx(prov), StocksSettings(symbols="aapl,tcs.ns", range="5y"))  # type: ignore[arg-type]
    app.on_start()
    assert prov.wants[-1] == (["AAPL", "TCS.NS"], "5y")


def test_alert_crossing_fires_once() -> None:
    data = _fake_data()
    prov = FakeProvider(data)
    ctx = FakeCtx(prov)
    app = Stocks(ctx, StocksSettings(symbols="AAPL,NVDA", alert_above=340, alert_below=330))  # type: ignore[arg-type]

    def tick(price: float) -> None:
        data["AAPL"] = dict(data["AAPL"], price=price)
        prov.updated += 1
        for t in (0.0, 0.5, 1.0):  # several frames per fetch must not re-fire
            app.render(Frame(), t)

    tick(335)  # first observation only arms
    assert ctx.notes == []
    tick(341)
    assert [n["message"] for n in ctx.notes] == ["ABOVE 340.00"]
    tick(345)
    assert len(ctx.notes) == 1
    tick(338)
    tick(342)  # re-crossing fires again
    assert len(ctx.notes) == 2
    tick(329)
    assert ctx.notes[-1]["message"] == "BELOW 330.00" and ctx.notes[-1]["title"] == "AAPL"
    assert ctx.notes[-1]["icon"] == "warn"
    assert len(ctx.notes) == 3
