"""Stock market — stocks, indices, ETFs, forex and futures (Yahoo Finance) in five layouts.

Layouts: ``card`` (one symbol per screen: hero price + chart), ``ticker`` (a scrolling exchange tape, baked as
a clip), ``watchlist`` (rows with change and a diverging bar), ``chart`` (full-screen chart with a price
tag) and ``heatmap`` (equal tiles shaded by change). Every drawing routine here is written for the 32×32
grid; numbers use the tabular bitmap digits so they never jitter.
"""

from __future__ import annotations

import itertools
import json
import math
from typing import Any, ClassVar

import numpy as np
from pydantic import Field, field_validator

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import PALETTE, Frame, Sprite, hsv, measure, mix, scale, to_hex, to_rgb
from ..gfx.color import RGB
from ..providers.stocks import RANGES, aggregate_candles, parse_symbols
from ._kit import loading, offline

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)

# friendly short labels for well-known symbols (everything else: suffixes stripped)
ALIASES = {
    "^GSPC": "S&P500",
    "^DJI": "DOW",
    "^IXIC": "NASDAQ",
    "^NDX": "NDX100",
    "^RUT": "RUSSELL",
    "^NSEI": "NIFTY",
    "^NSEBANK": "BANKNIFTY",
    "^BSESN": "SENSEX",
    "^FTSE": "FTSE",
    "^N225": "NIKKEI",
    "^GDAXI": "DAX",
    "^HSI": "HANGSENG",
    "^VIX": "VIX",
    "GC=F": "GOLD",
    "SI=F": "SILVER",
    "CL=F": "OIL",
    "BZ=F": "BRENT",
    "NG=F": "NATGAS",
    "HG=F": "COPPER",
}

# currency signs drawn from scratch (5 px tall, tiny scale); USD uses the font's own '$'
CURRENCY_ROWS: dict[str, list[str]] = {
    "INR": ["###", "..#", "###", ".#.", "..#"],
    "EUR": [".##", "#..", "###", "#..", ".##"],
    "GBP": [".##", "#..", "###", "#..", "###"],
    "JPY": ["#.#", ".#.", "###", ".#.", ".#."],
    "CNY": ["#.#", ".#.", "###", ".#.", ".#."],
    "KRW": ["#.#", "###", "#.#", "###", "#.#"],
}
CURRENCY = {k: Sprite.parse(v, {"#": WHITE}) for k, v in CURRENCY_ROWS.items()}

STATE_COLORS: dict[str, RGB] = {
    "REGULAR": PALETTE["ok"],
    "PRE": PALETTE["amber"],
    "POST": PALETTE["violet"],
    "CLOSED": PALETTE["mute"],
}
# structure tones lifted to survive the panel gamma (PALETTE "shade"/"dim" read as black on the LEDs)
TRACK: RGB = (56, 56, 72)
DOT_OFF: RGB = (84, 84, 100)
TAPE_FRAMES = 110  # ~350 B per ticker frame: <= 110 frames keeps the baked GIF under 40 KB without drops
TAPE_MIN_MS = 100  # <= 10 fps, the fastest clip rate verified on the panel


# --------------------------------------------------------------------------- settings
class StocksSettings(AppSettings):
    symbols: str = Field(
        "AAPL,NVDA,^NSEI,RELIANCE.NS",
        title="Symbols",
        description="Yahoo symbols, comma-separated: AAPL, ^GSPC, ^NSEI, TCS.NS, SPY, USDINR=X, GC=F",
        json_schema_extra={"group": "Symbols"},
    )
    label: str = Choice(
        "short", {"short": "Short", "ticker": "Ticker", "name": "Name"}, title="Labels", group="Symbols"
    )
    layout: str = Choice(
        "card",
        {
            "card": "Card",
            "ticker": "Ticker tape",
            "watchlist": "Watchlist",
            "chart": "Chart",
            "heatmap": "Heatmap",
        },
        title="Layout",
        group="Layout",
    )
    range: str = Choice("1d", {r: r.upper() for r in RANGES}, title="Chart range", group="Layout")
    chart: str = Choice(
        "area",
        {"line": "Line", "area": "Area", "candles": "Candles", "bars": "Bars", "dots": "Dots"},
        title="Chart style",
        group="Layout",
    )
    show: str = Choice(
        "percent",
        {"percent": "Percent", "absolute": "Absolute", "both": "Both"},
        title="Change",
        group="Layout",
    )
    rotate: int = Field(8, ge=2, le=120, title="Seconds per symbol", json_schema_extra={"group": "Layout"})
    speed: int = Field(12, ge=4, le=30, title="Ticker speed (px/s)", json_schema_extra={"group": "Layout"})
    theme: str = Choice(
        "classic",
        {"classic": "Classic", "vivid": "Vivid", "mono": "Mono", "inverse": "Inverse (red up)"},
        title="Theme",
        group="Colours",
    )
    up: Color = Field("#00ff78", title="Up colour", json_schema_extra={"group": "Colours"})
    down: Color = Field("#ff143c", title="Down colour", json_schema_extra={"group": "Colours"})
    neutral: Color = Field("#ffaa00", title="Neutral colour", json_schema_extra={"group": "Colours"})
    heat_scale: float = Field(
        3.0,
        ge=0.5,
        le=10.0,
        title="Full-scale change %",
        description="Change that saturates heatmap tiles and watchlist bars",
        json_schema_extra={"group": "Colours"},
    )
    show_market_state: bool = Field(
        True,
        title="Market state dot",
        description="Green = open (blinks), amber = pre, violet = post, grey = closed",
        json_schema_extra={"group": "Details"},
    )
    show_currency: bool = Field(False, title="Currency sign", json_schema_extra={"group": "Details"})
    compact: bool = Field(
        False, title="Compact numbers", description="23446.8 → 23.4K", json_schema_extra={"group": "Details"}
    )
    decimals: int = Field(
        -1,
        ge=-1,
        le=4,
        title="Decimals",
        description="-1 = the exchange's own precision",
        json_schema_extra={"group": "Details"},
    )
    alert_above: float = Field(
        0.0,
        ge=0,
        title="Alert above",
        description="Price of the first symbol; 0 = off",
        json_schema_extra={"group": "Alerts"},
    )
    alert_below: float = Field(
        0.0,
        ge=0,
        title="Alert below",
        description="Price of the first symbol; 0 = off",
        json_schema_extra={"group": "Alerts"},
    )

    @field_validator("symbols")
    @classmethod
    def _clean(cls, v: str) -> str:
        syms = parse_symbols(v)
        if not syms:
            raise ValueError("at least one valid symbol (e.g. AAPL, ^NSEI, TCS.NS)")
        return ",".join(syms[:24])


# --------------------------------------------------------------------------- formatting
def short_label(sym: str) -> str:
    if sym in ALIASES:
        return ALIASES[sym]
    s = sym.lstrip("^")
    for suffix in ("=X", "=F", "-USD"):
        s = s.removesuffix(suffix)
    if "." in s:
        s = s.split(".", 1)[0]
    return s or sym


def fmt_price(v: float, d: int) -> str:
    return f"{v:.{max(0, d)}f}"


def fmt_compact(v: float) -> str | None:
    a = abs(v)
    for suffix, k in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if a >= k and a >= 1e4:
            x = v / k
            return f"{x:.1f}{suffix}" if abs(x) < 100 else f"{x:.0f}{suffix}"
    return None


def fmt_pct(p: float, arrow: bool = True, digits: int | None = None) -> str:
    a = abs(p)
    d = digits if digits is not None else (2 if a < 10 else 1 if a < 100 else 0)
    return f"{arrow_for(p) if arrow else ''}{a:.{d}f}%"


def arrow_for(p: float) -> str:
    return "" if abs(p) < 0.005 else ("▲" if p > 0 else "▼")


def text_w(s: str, font: str = "tiny") -> int:
    return measure(s, font) if s else 0


def fit_chars(s: str, w: int, font: str = "tiny") -> str:
    """Hard-cut (no ellipsis) so tiny tiles keep as many letters as possible."""
    while s and text_w(s, font) > w:
        s = s[:-1]
    return s


def fit_ellipsis(s: str, w: int) -> str:
    if text_w(s) <= w:
        return s
    while s and text_w(s + "…") > w:
        s = s[:-1]
    return s + "…" if s else ""


# --------------------------------------------------------------------------- the app
@register
class Stocks(App):
    id = "stocks"
    name = "Stocks"
    description = "Stocks, indices, forex and futures: cards, ticker tape, watchlist, charts and heatmap."
    icon = "trending-up"
    category = "data"
    Settings = StocksSettings
    fps = 2.0
    uses = ("stocks",)
    clip_fps = 12.0

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._shown: str | None = None
        self._tape: tuple[str, list[dict[str, Any]], int] | None = None
        self.on_settings()

    # ------------------------------------------------------------ lifecycle
    @property
    def symbols(self) -> list[str]:
        return self.settings.symbols.split(",")

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(self.symbols, self.settings.range)

    def on_settings(self) -> None:
        s = self.settings
        up, down, neu = to_rgb(s.up), to_rgb(s.down), to_rgb(s.neutral)
        self.fill_k = 1.0
        self.tint_price = False
        self.label_col: RGB = WHITE
        if s.theme == "inverse":
            up, down = down, up
        elif s.theme == "vivid":
            up, down, neu = (self._vivid(c) for c in (up, down, neu))
            self.fill_k, self.tint_price = 1.9, True
        elif s.theme == "mono":
            up, down = neu, scale(neu, 0.65)  # 0.5 turned "down" into an unreadable brown on the LEDs
            self.label_col = mix(neu, WHITE, 0.55)
        self.up, self.down, self.neu = up, down, neu
        self._alert_prev: dict[str, bool | None] = {"above": None, "below": None}
        self._alert_seen = -1.0
        self._tape = None
        self.on_start()

    @staticmethod
    def _vivid(c: RGB) -> RGB:
        import colorsys

        h, _s, _v = colorsys.rgb_to_hsv(*(x / 255 for x in c))
        return hsv(h, 1.0, 1.0)

    def _provider(self) -> Any:
        try:
            return self.ctx.provider("stocks")
        except KeyError:
            return None

    # ------------------------------------------------------------ colours
    def col(self, p: float) -> RGB:
        if abs(p) < 0.005:
            return self.neu
        return self.up if p > 0 else self.down

    def decimals(self, e: dict[str, Any]) -> int:
        d = self.settings.decimals
        return int(e.get("decimals", 2)) if d < 0 else d

    def label(self, sym: str, e: dict[str, Any] | None) -> str:
        mode = self.settings.label
        if mode == "ticker":
            return sym
        if mode == "name" and e and e.get("name"):
            return str(e["name"]).upper()
        return short_label(sym)

    def change_text(self, e: dict[str, Any], mode: str, arrow: bool = True) -> str:
        if mode == "absolute":
            ch = e["change"]
            c = fmt_compact(abs(ch)) if self.settings.compact else None
            return f"{arrow_for(e['change_pct']) if arrow else ''}{c or fmt_price(abs(ch), self.decimals(e))}"
        return fmt_pct(e["change_pct"], arrow)

    def fit_change(self, e: dict[str, Any], w: int, mode: str | None = None) -> str:
        """The richest change text that fits `w` px (drops decimals, then the arrow; colour still encodes it)."""
        mode = mode or ("absolute" if self.settings.show == "absolute" else "percent")
        if mode == "absolute":
            cands = [self.change_text(e, "absolute"), self.change_text(e, "absolute", False)]
            d = self.decimals(e)
            cands += [fmt_price(abs(e["change"]), k) for k in range(d - 1, -1, -1)]
        else:
            p = e["change_pct"]
            cands = [
                fmt_pct(p),
                fmt_pct(p, True, 1),
                fmt_pct(p, False),
                fmt_pct(p, False, 1),
                fmt_pct(p, False, 0),
            ]
        for c in cands:
            if text_w(c) <= w:
                return c
        return ""

    # ------------------------------------------------------------ small pieces
    def state_dot(self, f: Frame, x: int, y: int, e: dict[str, Any], t: float) -> None:
        if not self.settings.show_market_state:
            return
        st = e.get("market_state", "CLOSED")
        c = STATE_COLORS.get(st, PALETTE["dim"])
        if st == "REGULAR" and int(t * 2) % 2:
            c = scale(c, 0.35)
        f.set(x, y, c)

    def currency_w(self, e: dict[str, Any]) -> int:
        if not self.settings.show_currency:
            return 0
        cur = e.get("currency", "")
        return 3 if cur in CURRENCY or cur == "USD" else 0

    def draw_currency(self, f: Frame, x: int, y: int, e: dict[str, Any], color: RGB) -> None:
        cur = e.get("currency", "")
        if cur == "USD":
            f.text(x, y, "$", color)
        elif cur in CURRENCY:
            for yy, xx in zip(*np.nonzero(CURRENCY[cur].mask), strict=True):
                f.set(x + int(xx), y + int(yy), color)

    def hero_layout(
        self, e: dict[str, Any], avail: int, fonts: tuple[str, ...] = ("big", "small"), currency: bool = True
    ) -> dict[str, Any]:
        """Pick the richest rendering of the price that fits `avail` px (big > small, more decimals first)."""
        price = e["price"]
        dmax = self.decimals(e)
        cw = self.currency_w(e) if currency else 0
        cands: list[tuple[str, str, str]] = []
        comp = fmt_compact(price) if self.settings.compact else None
        if comp:
            cands.append(("small", comp, ""))
        for font in fonts:
            for d in range(dmax, -1, -1):
                s = fmt_price(price, d)
                ip, _, fp = s.partition(".")
                cands.append((font, s, ""))
                if fp and len(ip.lstrip("-")) >= 2:
                    cands.append((font, ip, "." + fp))
        cands.append(("tiny", comp or fmt_price(price, min(dmax, 2)), ""))
        for font, main, frac in cands:
            mw = text_w(main, font)
            fw = text_w(frac)
            w = mw + (1 + fw if frac else 0) + (cw + 1 if cw else 0)
            if w <= avail:
                return {"font": font, "main": main, "frac": frac, "w": w, "cw": cw}
        font, main, frac = cands[-1]
        return {"font": font, "main": main, "frac": frac, "w": text_w(main, font), "cw": 0}

    def draw_hero(
        self, f: Frame, x: int, y: int, box_h: int, e: dict[str, Any], lay: dict[str, Any], color: RGB
    ) -> None:
        font = lay["font"]
        fh = {"big": 10, "small": 7, "tiny": 5}[font]
        yy = y + (box_h - fh) // 2
        if lay["cw"]:
            self.draw_currency(f, x, yy, e, scale(color, 0.7))
            x += lay["cw"] + 1
        x = f.text(x, yy, lay["main"], color, font=font) + 1
        if lay["frac"]:
            f.text(x, yy, lay["frac"], color)

    def price_color(self, e: dict[str, Any]) -> RGB:
        return mix(self.col(e["change_pct"]), WHITE, 0.25) if self.tint_price else WHITE

    def page_ticks(self, f: Frame, y: int, n: int, i: int) -> None:
        if n < 2:
            return
        seg = max(1, min(4, (32 - (n - 1)) // n))
        total = n * seg + (n - 1)
        x0 = (32 - total) // 2
        for k in range(n):
            f.hline(x0 + k * (seg + 1), y, seg, self.label_col if k == i else DOT_OFF)

    # ------------------------------------------------------------ charts
    def draw_chart(
        self, f: Frame, x: int, y: int, w: int, h: int, e: dict[str, Any], kind: str | None = None
    ) -> None:
        kind = kind or self.settings.chart
        vals = [v for v in e.get("history") or [] if v is not None]
        ref = float(e.get("range_ref") or (vals[0] if vals else e["price"]))
        if len(vals) < 2 or w < 2 or h < 2:
            f.hline(x, y + h // 2, w, PALETTE["shade"])
            return
        trend = self.col((vals[-1] - ref) / ref * 100 if ref else 0.0)
        if kind == "candles":
            self._candles(f, x, y, w, h, e, vals)
            return
        cols = np.interp(np.linspace(0, len(vals) - 1, w), np.arange(len(vals)), np.asarray(vals, float))
        lo, hi = float(cols.min()), float(cols.max())
        if kind == "bars":
            lo, hi = min(lo, ref), max(hi, ref)
        span = hi - lo or 1.0

        def row(v: float) -> int:
            return y + h - 1 - round((v - lo) / span * (h - 1))

        ys = [row(v) for v in cols]
        bottom = y + h - 1
        if lo < ref < hi and kind != "bars":  # dashed reference (previous close / range start)
            ry = row(ref)
            for xx in range(x, x + w, 2):
                f.set(xx, ry, scale(self.neu, 0.4))
        if kind == "bars":
            base = max(y, min(bottom, row(ref)))
            n = w // 2
            idx = np.linspace(0, len(cols) - 1, n).round().astype(int)
            x0 = x + w - (2 * n - 1)
            for i, j in enumerate(idx):
                v = float(cols[j])
                c = self.up if v >= ref else self.down
                py = row(v)
                top, ln = min(py, base), abs(py - base) + 1
                f.vline(x0 + 2 * i, top, ln, scale(c, 0.55 if i < n - 1 else 1.0))
                f.set(x0 + 2 * i, py, c)
            return
        if kind == "dots":
            for i in range(w - 1, -1, -2):
                v = float(cols[i])
                c = self.up if v >= ref else self.down
                f.set(x + i, ys[i], c if i == w - 1 else scale(c, 0.8))
            f.set(x + w - 1, ys[-1], mix(trend, WHITE, 0.5))
            return
        if kind == "area":
            for i, py in enumerate(ys):
                depth = max(1, bottom - py)
                for yy in range(py + 1, bottom + 1):
                    k = (0.42 - 0.34 * (yy - py) / depth) * self.fill_k
                    f.set(x + i, yy, scale(trend, max(0.05, min(0.9, k))))
        f.polyline([(x + i, py) for i, py in enumerate(ys)], trend)
        f.set(x + w - 1, ys[-1], mix(trend, WHITE, 0.6))

    def _candles(
        self, f: Frame, x: int, y: int, w: int, h: int, e: dict[str, Any], vals: list[float]
    ) -> None:
        raw = e.get("candles") or [(a, max(a, b), min(a, b), b) for a, b in itertools.pairwise(vals)]
        n = max(1, w // 2)
        cs = aggregate_candles([tuple(c) for c in raw], n)  # type: ignore[misc]
        if not cs:
            return
        lo = min(c[2] for c in cs)
        hi = max(c[1] for c in cs)
        span = hi - lo or 1.0

        def row(v: float) -> int:
            return y + h - 1 - round((v - lo) / span * (h - 1))

        x0 = x + w - (2 * len(cs) - 1)
        for i, (o, hh, ll, c) in enumerate(cs):
            col = self.up if c >= o else self.down
            cx = x0 + 2 * i
            f.vline(cx, row(hh), row(ll) - row(hh) + 1, scale(col, 0.4))
            top, bot = sorted((row(o), row(c)))
            f.vline(cx, top, bot - top + 1, col)

    # ------------------------------------------------------------ data access
    def _data(self) -> tuple[Any, dict[str, Any]]:
        p = self._provider()
        return p, ((p.value if p is not None else None) or {})

    def _placeholder(self, f: Frame, t: float, p: Any, label: str = "STOCKS") -> None:
        if p is not None and p.error:
            offline(f, label, "OFFLINE")
        else:
            loading(f, t, label, self.neu)

    def _check_alerts(self, p: Any, data: dict[str, Any]) -> None:
        """One-shot notifications when the first symbol crosses a threshold (runs once per fetch)."""
        s = self.settings
        if p is None or p.updated == self._alert_seen:
            return
        self._alert_seen = p.updated
        sym = self.symbols[0]
        e = data.get(sym)
        if not e:
            return
        price = float(e["price"])
        for key, level, hit, color in (
            ("above", s.alert_above, price >= s.alert_above, self.up),
            ("below", s.alert_below, price <= s.alert_below, self.down),
        ):
            if level <= 0:
                continue
            if self._alert_prev[key] is False and hit:
                self.ctx.notify(
                    title=sym[:40],
                    message=f"{key.upper()} {fmt_price(level, self.decimals(e))}",
                    icon="warn",
                    color=to_hex(color),
                )
            self._alert_prev[key] = hit

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        p, data = self._data()
        self._check_alerts(p, data)
        if not data:
            self._placeholder(f, t, p)
            return
        {
            "card": self._card,
            "ticker": self._ticker,
            "watchlist": self._watchlist,
            "chart": self._chart_screen,
            "heatmap": self._heatmap,
        }[self.settings.layout](f, t, p, data)
        if p is not None and p.error:  # showing cached values: one amber corner LED says "stale"
            f.set(0, 31, PALETTE["amber"])

    def _current(self, t: float) -> tuple[int, str]:
        syms = self.symbols
        i = int(t // self.settings.rotate) % len(syms)
        self._shown = syms[i]
        return i, syms[i]

    # card: header · hero price · change · chart ------------------------------------------------
    def _card(self, f: Frame, t: float, p: Any, data: dict[str, Any]) -> None:
        _i, sym = self._current(t)
        e = data.get(sym)
        label = self.label(sym, e)
        if not e:
            self._placeholder(f, t, p, short_label(sym)[:7])
            return
        s = self.settings
        c = self.col(e["change_pct"])
        head = self.change_text(e, "absolute" if s.show == "absolute" else "percent")
        fits = text_w(label) + 3 + text_w(head) <= 30
        cw = self.currency_w(e)
        lab = label if fits else fit_ellipsis(label, 30 - (cw + 2 if cw else 0))
        end = f.text(1, 1, lab, self.label_col)
        if cw and not fits:
            self.draw_currency(f, end + 2, 1, e, scale(self.label_col, 0.6))
        if fits:
            f.text_right(30, 1, head, c)
        self.state_dot(f, 31, 0, e, t)
        lay = self.hero_layout(e, 30, currency=False)
        self.draw_hero(f, 1 + (30 - lay["w"]) // 2, 7, 10, e, lay, self.price_color(e))
        left, right = "", ""
        if s.show == "both" and not fits:
            pairs = []
            for arrow in (True, False):
                lt = self.change_text(e, "absolute", arrow)
                pairs.append((lt, self.fit_change(e, 30 - text_w(lt) - 3, "percent")))
            left, right = max(pairs, key=lambda lr: len(lr[1]))
        elif s.show == "both":
            left = self.change_text(e, "absolute")
        elif not fits:
            left = head
        top = 18
        if left:
            if right:
                f.text(1, 18, left, c)
                f.text_right(30, 18, right, c)
            else:
                f.text_center(18, left, c)
            top = 24
        self.draw_chart(f, 0, top, 32, 32 - top, e)

    # chart: header · full-bleed chart with a price tag -------------------------------------------
    def _chart_screen(self, f: Frame, t: float, p: Any, data: dict[str, Any]) -> None:
        _i, sym = self._current(t)
        e = data.get(sym)
        if not e:
            self._placeholder(f, t, p, short_label(sym)[:7])
            return
        c = self.col(e["change_pct"])
        lab = fit_chars(self.label(sym, e), 15)
        f.text(1, 1, lab, self.label_col)
        f.text_right(30, 1, self.fit_change(e, 30 - text_w(lab) - 2), c)
        self.state_dot(f, 31, 0, e, t)
        self.draw_chart(f, 0, 7, 32, 25, e)
        # price tag + change tag, in whichever band (top/bottom of the chart) the curve leaves free
        tag = self.hero_layout(e, 29, fonts=("tiny",))
        txt = tag["main"] + tag["frac"]
        tw = text_w(txt) + (tag["cw"] + 1 if tag["cw"] else 0)
        hist = e.get("history") or [0.0, 0.0]
        lo, hi = min(hist), max(hist)
        start = (sum(hist[: max(1, len(hist) // 3)]) / max(1, len(hist) // 3) - lo) / ((hi - lo) or 1)
        end = (hist[-1] - lo) / ((hi - lo) or 1)
        low_band = (start + end) / 2 > 0.5  # the curve lives high -> tags go to the bottom
        ty = 25 if low_band else 8
        f.rect(0, ty - 1, tw + 2, 7, BLACK)
        x = 1
        if tag["cw"]:
            self.draw_currency(f, x, ty, e, scale(WHITE, 0.7))
            x += tag["cw"] + 1
        f.text(x, ty, txt, self.price_color(e))
        if self.settings.show == "both":  # absolute change in its own tag, same band if it fits
            ab = self.change_text(e, "absolute")
            yy = ty if text_w(ab) + tw + 5 <= 32 else (ty - 6 if low_band else ty + 6)
            f.rect(31 - text_w(ab) - 1, yy - 1, text_w(ab) + 2, 7, BLACK)
            f.text_right(30, yy, ab, c)

    # watchlist: rows of label · change · diverging bar ---------------------------------------------
    def _watchlist(self, f: Frame, t: float, p: Any, data: dict[str, Any]) -> None:
        syms = self.symbols
        rows = 4 if len(syms) >= 4 else 3
        rh = 32 // rows
        pages = math.ceil(len(syms) / rows)
        page = int(t // self.settings.rotate) % pages
        shown = syms[page * rows : (page + 1) * rows]
        self._shown = shown[0]
        mode = self.settings.show
        if mode == "both":
            mode = "percent" if int(t // 3) % 2 == 0 else "absolute"
        full = self.settings.heat_scale
        for k, sym in enumerate(shown):
            y0 = k * rh
            e = data.get(sym)
            label = self.label(sym, e)
            if not e:
                f.text(1, y0 + 1, fit_chars(label, 20), scale(self.label_col, 0.5))
                f.text_right(30, y0 + 1, "--", PALETTE["mute"])
                f.hline(1, y0 + 7, 30, TRACK)
                continue
            pct = e["change_pct"]
            c = self.col(pct)
            self.state_dot(f, 0, y0 + 3, e, t)
            lab = fit_chars(label, 15)
            val = self.fit_change(e, 30 - text_w(lab) - 2, mode)
            f.text(1, y0 + 1, lab, self.label_col)
            f.text_right(30, y0 + 1, val, c)
            bh = 1 if rh < 10 else 2
            by = y0 + 7
            f.rect(1, by, 30, bh, TRACK)
            ln = max(1, round(min(1.0, abs(pct) / full) * 15)) if abs(pct) >= 0.005 else 0
            if pct >= 0:
                f.rect(16, by, ln, bh, c)
            else:
                f.rect(16 - ln, by, ln, bh, c)
            if ln == 0:
                f.rect(15, by, 2, bh, scale(self.neu, 0.5))

    # heatmap: equal tiles shaded by change ------------------------------------------------------------
    GRID: ClassVar[dict[int, tuple[int, int]]] = {
        1: (1, 1),
        2: (1, 2),
        3: (1, 3),
        4: (2, 2),
        5: (2, 3),
        6: (2, 3),
        7: (3, 3),
        8: (3, 3),
        9: (3, 3),
    }

    def _heatmap(self, f: Frame, t: float, p: Any, data: dict[str, Any]) -> None:
        syms = self.symbols
        per = 16
        pages = math.ceil(len(syms) / per)
        page = int(t // self.settings.rotate) % pages
        shown = syms[page * per : (page + 1) * per]
        self._shown = shown[0]
        n = len(shown)
        cols, rows = self.GRID.get(n, (3, 4) if n <= 12 else (4, 4))
        lo_k, hi_k = (0.22, 0.75) if self.fill_k > 1 else (0.12, 0.5)
        for k, sym in enumerate(shown):
            cx, cy = k % cols, k // cols
            x0, y0 = cx * 32 // cols, cy * 32 // rows
            x1 = (cx + 1) * 32 // cols - (1 if cx < cols - 1 else 0)
            y1 = (cy + 1) * 32 // rows - (1 if cy < rows - 1 else 0)
            w, h = x1 - x0, y1 - y0
            e = data.get(sym)
            pct = e["change_pct"] if e else 0.0
            c = self.col(pct) if e else PALETTE["shade"]
            mag = min(1.0, abs(pct) / self.settings.heat_scale)
            f.rect(x0, y0, w, h, scale(c, lo_k + (hi_k - lo_k) * mag) if e else PALETTE["ink"])
            label = self.label(sym, e)
            txt_c = WHITE
            chg = ""
            if e:
                for cand in (
                    self.change_text(e, "percent"),
                    fmt_pct(pct, True, 1),
                    fmt_pct(pct, False, 1),
                    fmt_pct(pct, False, 0),
                ):
                    if text_w(cand) <= w - 2:
                        chg = cand
                        break
                if self.settings.show == "absolute":
                    ab = self.fit_change(e, w - 2, "absolute")
                    chg = ab or chg
            chg_c = mix(c, WHITE, 0.75)
            if h < 12:  # one line: label left, change right
                ty = y0 + (h - 5) // 2
                lab = fit_chars(label, 15)
                one = self.fit_change(e, w - 4 - text_w(lab)) if e and w >= 24 else ""
                if one:
                    f.text(x0 + 1, ty, lab, txt_c)
                    f.text_right(x0 + w - 2, ty, one, chg_c)
                else:
                    f.text(x0 + 1, ty, fit_chars(label, w - 2), txt_c)
                continue
            lines: list[tuple[str, RGB]] = [(fit_chars(label, w - 2), txt_c)]
            if e and h >= 18 and self.settings.show == "both":
                lines.append((fit_chars(self.change_text(e, "absolute"), w - 2), chg_c))
            if chg:
                lines.append((chg, chg_c))
            if e and h >= 18 and self.settings.show != "both":
                lay = self.hero_layout(e, w - 2, fonts=("tiny",))
                lines.insert(1, (lay["main"] + lay["frac"], mix(WHITE, c, 0.2)))
            total = len(lines) * 6 - 1
            ty = y0 + (h - total) // 2
            for txt, col in lines:
                f.text(x0 + (w - text_w(txt)) // 2, ty, txt, col)
                ty += 6

    # ticker: a scrolling tape of mini cards (baked as a clip) --------------------------------------
    GAP = 7

    def _tape_items(self, data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        sig = json.dumps(
            {
                s: (e["price"], e["change"], e["market_state"], len(e.get("history") or []))
                for s, e in data.items()
            },
            sort_keys=True,
        )
        if self._tape and self._tape[0] == sig:
            return self._tape[1], self._tape[2]
        items: list[dict[str, Any]] = []
        x = 0
        for sym in self.symbols:
            e = data.get(sym)
            label = self.label(sym, e)
            it: dict[str, Any] = {"sym": sym, "e": e, "label": label, "x": x}
            if e:
                it["hero"] = self.hero_layout(e, 999)
                it["chg"] = (
                    f"{self.change_text(e, 'absolute')} {self.change_text(e, 'percent', False)}"
                    if self.settings.show == "both"
                    else self.change_text(e, self.settings.show)
                )
                w = max(
                    text_w(label) + (3 if self.settings.show_market_state else 0),
                    it["hero"]["w"],
                    text_w(it["chg"]),
                    20,
                )
            else:
                w = max(text_w(label), 20)
            it["w"] = w
            items.append(it)
            x += w + self.GAP
        step = max(1, math.ceil(x / TAPE_FRAMES))
        x = math.ceil(x / step) * step  # a whole number of equal steps per loop: no hitch at the wrap
        self._tape = (sig, items, x)
        return items, x

    def _ticker(self, f: Frame, t: float, p: Any, data: dict[str, Any]) -> None:
        items, total = self._tape_items(data)
        off = int(t * self.settings.speed) % max(1, total)
        self._shown = items[0]["sym"] if items else None
        for rep in (0, total):
            for it in items:
                x = it["x"] - off + rep + 1
                if x > 31 or x + it["w"] + self.GAP < 0:
                    continue
                if x <= 16 < x + it["w"] + self.GAP:
                    self._shown = it["sym"]
                self._tape_item(f, x, it, t)
                sx = x + it["w"] + self.GAP // 2
                for yy in range(2, 30, 3):
                    f.set(sx, yy, TRACK)

    def _tape_item(self, f: Frame, x: int, it: dict[str, Any], t: float) -> None:
        e = it["e"]
        if not e:
            f.text(x, 1, it["label"], scale(self.label_col, 0.5))
            f.text(x, 12, "--", PALETTE["mute"], font="small")
            return
        c = self.col(e["change_pct"])
        dx = 0
        if self.settings.show_market_state:
            self.state_dot(f, x, 3, e, 0.0)
            dx = 3
        f.text(x + dx, 1, it["label"], self.label_col)
        self.draw_hero(f, x, 7, 10, e, it["hero"], self.price_color(e))
        f.text(x, 18, it["chg"], c)
        self.draw_chart(f, x, 24, it["w"], 8, e)

    # ------------------------------------------------------------ output kind / clip
    def kind(self) -> Kind:
        if self.settings.layout == "ticker":
            _p, data = self._data()
            if data:
                return "clip"
        return "stream"

    def clip_key(self) -> str:
        _p, data = self._data()
        items, total = self._tape_items(data) if data else ([], 0)
        tape = [
            (it["label"], it.get("chg"), it.get("hero", {}).get("main"), it.get("hero", {}).get("frac"))
            for it in items
        ]
        return super().clip_key() + json.dumps([tape, total])

    def clip_frames(self) -> Clip:
        _p, data = self._data()
        _items, total = self._tape_items(data) if data else ([], 32)
        speed = self.settings.speed
        step = max(1, math.ceil(total / TAPE_FRAMES))  # px per frame; `total` is a multiple of it
        n = max(1, total // step)
        # even steps at <= 10 fps: faster speed settings cap at the panel's frame rate instead of skipping px
        ms = max(TAPE_MIN_MS * step, round(1000 * step / speed))
        frames = []
        for i in range(n):
            f = Frame()
            # half a step past the pixel boundary: int(t * speed) is then exact (float error made 0/2 px hops)
            self.render(f, (i * step + 0.5) / speed)
            frames.append(f)
        return Clip(frames, [ms] * n)

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        _p, data = self._data()
        sym = self._shown or self.symbols[0]
        e = data.get(sym) or {}
        return {
            "symbols": len(self.symbols),
            "shown": sym,
            "price": e.get("price"),
            "change_pct": round(e["change_pct"], 2) if "change_pct" in e else None,
        }
