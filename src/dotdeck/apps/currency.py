"""Currency — exchange rates for a home currency (default INR): pair, board, converter and heat grid.

Rates come from the ``currency`` provider (Frankfurter/ECB with the fawazahmed0 API as fallback). Currency signs
(₹ € £ ¥ ₩ ₽ ₿ $) are 5 px glyphs drawn from scratch; INR amounts use Indian digit grouping (1,00,000).
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

import numpy as np
from pydantic import Field, field_validator

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import PALETTE, Frame, Sprite, measure, mix, scale, to_rgb
from ..gfx.color import RGB
from ..providers.currency import RANGES, parse_codes
from ._kit import loading, offline

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)

SIGN_ROWS: dict[str, list[str]] = {
    "INR": ["###", "..#", "###", ".#.", "..#"],
    "EUR": [".##", "#..", "###", "#..", ".##"],
    "GBP": [".##", "#..", "###", "#..", "###"],
    "YEN": ["#.#", ".#.", "###", ".#.", ".#."],
    "KRW": ["#.#", "###", "#.#", "###", "#.#"],
    "RUB": ["##.", "#.#", "##.", "###", "#.."],
    "BTC": ["###.", "#..#", "###.", "#..#", "###."],
    "USD": [".##", "##.", ".#.", ".##", "##."],
}
SIGN_OF = {
    "INR": "INR",
    "EUR": "EUR",
    "GBP": "GBP",
    "JPY": "YEN",
    "CNY": "YEN",
    "KRW": "KRW",
    "RUB": "RUB",
    "BTC": "BTC",
    **dict.fromkeys(("USD", "CAD", "AUD", "SGD", "HKD", "NZD", "MXN", "TWD", "BRL"), "USD"),
}
SIGNS = {k: Sprite.parse(v, {"#": WHITE}) for k, v in SIGN_ROWS.items()}
NAMES = {  # a few friendly names for the pair header; codes otherwise
    "BTC": "BITCOIN",
    "ETH": "ETHER",
    "XAU": "GOLD",
    "XAG": "SILVER",
}


def sign_width(code: str) -> int:
    s = SIGN_OF.get(code)
    return SIGNS[s].w if s else 0


def draw_sign(f: Frame, code: str, x: int, y: int, color: RGB) -> int:
    """Draw the currency sign at (x, y); returns its width (0 if the currency has no sign)."""
    s = SIGN_OF.get(code)
    if not s:
        return 0
    sp = SIGNS[s]
    for yy, xx in zip(*np.nonzero(sp.mask), strict=True):
        f.set(x + int(xx), y + int(yy), color)
    return sp.w


def group_digits(int_part: str, indian: bool) -> str:
    neg = int_part.startswith("-")
    s = int_part.lstrip("-")
    if len(s) <= 3:
        out = s
    elif indian:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join([*parts, tail])
    else:
        out = f"{int(s):,}"
    return ("-" if neg else "") + out


def decimals_for(v: float) -> int:
    a = abs(v)
    if a >= 1000:
        return 0
    if a >= 10:
        return 2
    if a >= 1:
        return 3
    if a == 0:
        return 2
    return min(6, 2 - math.floor(math.log10(a)) + 1)  # 0.0104 -> 4, 0.00012 -> 6


def fmt_num(v: float, d: int, commas: bool = False, indian: bool = False) -> str:
    s = f"{v:.{max(0, d)}f}"
    if commas:
        ip, dot, fp = s.partition(".")
        s = group_digits(ip, indian) + (dot + fp if dot else "")
    return s


def compact(v: float, indian: bool = False) -> str:
    """95740 -> '95.7K'; with `indian`, 8298817 -> '82.99L' (lakh) and 3.2e8 -> '32CR' (crore)."""
    a = abs(v)
    units = (("CR", 1e7), ("L", 1e5)) if indian else (("B", 1e9), ("M", 1e6), ("K", 1e3))
    for suffix, k in units:
        if a >= k:
            x = v / k
            return (
                f"{x:.2f}{suffix}"
                if abs(x) < 10
                else f"{x:.1f}{suffix}"
                if abs(x) < 100
                else f"{x:.0f}{suffix}"
            )
    return fmt_num(v, decimals_for(v))


def short_num(v: float, room: int, indian: bool = False) -> str:
    """The most precise tiny rendering of `v` within `room` px (drops a leading zero, then compacts)."""
    d0 = decimals_for(v)
    for d in range(d0, -1, -1):
        txt = fmt_num(v, d)
        if 0 < abs(v) < 1:
            txt = txt.replace("0.", ".", 1)
        if measure(txt) <= room and (d >= 1 or abs(v) >= 10) and any(ch in "123456789" for ch in txt):
            return txt
    if abs(v) >= 1:
        return compact(v, indian)
    return next((t for t in ("<.001", "<.01", "<.1") if measure(t) <= room), "0")  # never a missing glyph


def sig_text(v: float, room: int) -> tuple[str, int]:
    """(text, significant digits) — the most precise tiny rendering of `v` within `room` px, else ("", 0)."""
    for d in range(6, -1, -1):
        txt = fmt_num(v, d)
        if 0 < abs(v) < 1:
            txt = txt.replace("0.", ".", 1)
        if measure(txt) > room:
            continue
        digits = txt.replace("-", "").replace(".", "").lstrip("0")
        return txt, len(digits)
    return "", 0


def unit_token(unit: int, indian: bool) -> str:
    """100 -> '100', 1000 -> '1K', 100000 -> '1L' (INR) / '100K', 1e7 -> '1CR' / '10M'."""
    names = {1e7: "CR", 1e5: "L", 1e3: "K"} if indian else {1e9: "B", 1e6: "M", 1e3: "K"}
    for k, suffix in names.items():
        if unit >= k:
            return f"{round(unit / k)}{suffix}"
    return str(unit)


def page_unit(rates: list[float], room: int) -> int:
    """One power-of-ten multiplier for a board page that shows every rate with the most significant digits."""
    best, best_score = 1, -1
    for k in range(9):
        unit = 10**k
        cells = [sig_text(r * unit, room) for r in rates]
        if any(not txt for txt, _n in cells):
            continue
        below_one = sum(1 for r in rates if abs(r * unit) < 1)  # ".915" reads worse than "9.153"
        score = sum(min(n, 4) for _t, n in cells) * 10 - 3 * below_one - k  # then the smaller multiplier
        if score > best_score:
            best, best_score = unit, score
    return best


def unit_for(rate: float) -> int:
    """Smallest power of ten that lifts a tiny rate to >= 1 (1 INR = 0.0104 USD -> 100 INR = 1.04 USD)."""
    unit = 1
    while rate * unit < 1 and unit < 1_000_000:
        unit *= 10
    return unit


def fmt_pct(p: float, arrow: bool = True) -> str:
    a = abs(p)
    d = 2 if a < 10 else 1 if a < 100 else 0
    head = "" if a < 0.005 or not arrow else ("▲" if p > 0 else "▼")
    return f"{head}{a:.{d}f}%"


class CurrencySettings(AppSettings):
    base: str = Field(
        "INR",
        title="Home currency",
        description="ISO code, e.g. INR, USD, EUR, AED",
        max_length=6,
        json_schema_extra={"group": "Currencies"},
    )
    quotes: str = Field(
        "USD,EUR,GBP",
        title="Currencies",
        description="Comma-separated: USD, EUR, GBP, JPY, AED, SGD, BTC… (fiat, metals and crypto)",
        json_schema_extra={"group": "Currencies"},
    )
    direction: str = Choice(
        "to_home",
        {"to_home": "1 USD = ₹95.7", "from_home": "1 INR = $0.0104"},
        title="Show",
        group="Currencies",
    )
    amount: float = Field(
        100.0, ge=0.01, le=1e9, title="Converter amount", json_schema_extra={"group": "Currencies"}
    )
    layout: str = Choice(
        "pair",
        {"pair": "Big pair", "board": "Board", "converter": "Converter", "heat": "Heat grid"},
        title="Layout",
        group="Layout",
    )
    range: str = Choice("30d", {k: k.upper() for k in RANGES}, title="Chart range", group="Layout")
    change: str = Choice(
        "day", {"day": "Since yesterday", "range": "Over the chart range"}, title="Change", group="Layout"
    )
    rotate: int = Field(8, ge=2, le=120, title="Seconds per page", json_schema_extra={"group": "Layout"})
    up: Color = Field("#00ff78", title="Up colour", json_schema_extra={"group": "Colours"})
    down: Color = Field("#ff143c", title="Down colour", json_schema_extra={"group": "Colours"})
    accent: Color = Field("#ffaa00", title="Accent", json_schema_extra={"group": "Colours"})
    home_view: bool = Field(
        False,
        title="Home view colours",
        description="Red when the home currency weakens (the foreign price rises)",
        json_schema_extra={"group": "Colours"},
    )
    heat_scale: float = Field(
        1.0, ge=0.1, le=10.0, title="Full-scale change %", json_schema_extra={"group": "Colours"}
    )

    @field_validator("base")
    @classmethod
    def _base(cls, v: str) -> str:
        codes = parse_codes(v)
        if not codes:
            raise ValueError("a currency code such as INR")
        return codes[0]

    @field_validator("quotes")
    @classmethod
    def _quotes(cls, v: str) -> str:
        codes = parse_codes(v)
        if not codes:
            raise ValueError("at least one currency code, e.g. USD,EUR")
        return ",".join(codes[:16])


# structure tones lifted to survive the panel gamma (PALETTE "shade"/"dim"/"ink" read as black on the LEDs)
TRACK: RGB = (56, 56, 72)
DOT_OFF: RGB = (84, 84, 100)
FAINT: RGB = PALETTE["mute"]


@register
class Currency(App):
    id = "currency"
    name = "Currency"
    description = (
        "Exchange rates for your home currency: big pair with a sparkline, board, converter, heat grid."
    )
    icon = "banknote"
    category = "data"
    Settings = CurrencySettings
    fps = 1.0
    uses = ("currency",)
    GRID: ClassVar[dict[int, tuple[int, int]]] = {1: (1, 1), 2: (1, 2), 3: (1, 3), 4: (2, 2)}

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.on_settings()

    # ------------------------------------------------------------ lifecycle / data
    @property
    def codes(self) -> list[str]:
        return [c for c in self.settings.quotes.split(",") if c != self.settings.base] or ["USD"]

    def _provider(self) -> Any:
        try:
            return self.ctx.provider("currency")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(self.settings.base, self.codes, self.settings.range)

    def on_settings(self) -> None:
        s = self.settings
        self.upc, self.downc, self.acc = to_rgb(s.up), to_rgb(s.down), to_rgb(s.accent)
        self.on_start()

    def data(self) -> dict[str, Any] | None:
        p = self._provider()
        v = p.value if p is not None else None
        if not v or v.get("base") != self.settings.base:
            return None
        return v  # type: ignore[no-any-return]

    # ------------------------------------------------------------ values in the chosen direction
    def view(self, e: dict[str, Any]) -> tuple[str, str, float, float, list[float]]:
        """(from, to, rate, change %, history) as displayed: 1 `from` = rate `to`."""
        home, code = self.settings.base, e["code"]
        pct = e["change_pct"] if self.settings.change == "day" else e["range_pct"]
        if self.settings.direction == "to_home":
            return code, home, e["rate"], pct, list(e["history"])
        inv = [1 / v for v in e["history"] if v]
        return home, code, 1 / e["rate"], (1 / (1 + pct / 100) - 1) * 100, inv

    def col(self, pct: float, frm: str) -> RGB:
        if abs(pct) < 0.005:
            return self.acc
        up = pct > 0
        if self.settings.home_view and frm != self.settings.base:
            up = not up  # the foreign price rising = the home currency weakening
        return self.upc if up else self.downc

    # ------------------------------------------------------------ pieces
    def hero(
        self, value: float, avail: int, fonts: tuple[str, ...] = ("big", "small"), home: str = ""
    ) -> tuple[str, str]:
        """The richest rendering of `value` that fits: big digits with >= 3 significant figures, then small
        (with lakh/crore or K/M/B suffixes for huge numbers), then tiny."""
        d0 = decimals_for(value)
        a = abs(value)
        sig_min = 0 if a >= 100 else max(0, 2 - math.floor(math.log10(a))) if a > 0 else 2
        cands: list[tuple[str, str]] = []
        for font in fonts:
            cands += [(font, fmt_num(value, d)) for d in range(d0, sig_min - 1, -1)]
        cands.append(("small", compact(value, home == "INR")))
        cands.append(("tiny", fmt_num(value, min(2, d0))))
        for font, txt in cands:
            if measure(txt, font) <= avail:
                return font, txt
        return cands[-1]

    def spark(self, f: Frame, x: int, y: int, w: int, h: int, vals: list[float], c: RGB) -> None:
        if len(vals) < 2:
            f.hline(x, y + h // 2, w, PALETTE["shade"])
            return
        cols = np.interp(np.linspace(0, len(vals) - 1, w), np.arange(len(vals)), np.asarray(vals, float))
        lo, hi = float(cols.min()), float(cols.max())
        span = hi - lo or 1.0
        ys = [y + h - 1 - round((v - lo) / span * (h - 1)) for v in cols]
        bottom = y + h - 1
        for i, py in enumerate(ys):
            depth = max(1, bottom - py)
            for yy in range(py + 1, bottom + 1):
                f.set(x + i, yy, scale(c, max(0.05, 0.36 - 0.3 * (yy - py) / depth)))
        f.polyline([(x + i, py) for i, py in enumerate(ys)], c)
        f.set(x + w - 1, ys[-1], mix(c, WHITE, 0.6))

    def ticks(self, f: Frame, n: int, i: int) -> None:
        if n < 2:
            return
        seg = max(1, min(4, (32 - (n - 1)) // n))
        x0 = (32 - (n * seg + n - 1)) // 2
        for k in range(n):
            f.hline(x0 + k * (seg + 1), 31, seg, WHITE if k == i else DOT_OFF)

    def page(self, t: float, n: int) -> int:
        return int(t // self.settings.rotate) % max(1, n)

    # ------------------------------------------------------------ layouts
    def draw_pair(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        codes = [c for c in self.codes if c in v["pairs"]] or self.codes
        i = self.page(t, len(codes))
        e = v["pairs"].get(codes[i])
        if not e:
            self._missing(f, codes[i])
            return
        frm, to, rate, pct, hist = self.view(e)
        c = self.col(pct, frm)
        unit = unit_for(rate)
        if unit > 1:  # "100 INR" on the left, the target code on the right
            x = f.text(1, 1, f"{unit} {frm}", WHITE)
            if x + 3 + measure(to) <= 31:
                f.text_right(30, 1, to, PALETTE["mute"])
        else:
            x = f.text(1, 1, frm, WHITE)
            f.text(x + 1, 1, ">", FAINT)
            f.text(x + 5, 1, to, PALETTE["mute"])
        font, txt = self.hero(rate * unit, 30, home=to)
        y = 8 if font == "big" else 9
        f.text_center(y, txt, WHITE, font=font)
        f.text(1, 19, fmt_pct(pct), c)
        rng = self.settings.range.upper() if self.settings.change == "range" else "1D"
        f.text_right(30, 19, rng, FAINT)
        self.spark(f, 0, 25, 32, 6, hist, c)
        self.ticks(f, len(codes), i)

    def draw_board(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        if self.settings.direction == "from_home":
            self.draw_board_scaled(f, t, v)
            return
        codes = self.codes
        rows = 4
        pages = math.ceil(len(codes) / rows)
        pg = self.page(t, pages)
        shown = codes[pg * rows : (pg + 1) * rows]
        full = self.settings.heat_scale
        for k, code in enumerate(shown):
            y0 = k * 8
            e = v["pairs"].get(code)
            if not e:
                f.text(1, y0 + 1, code, FAINT)
                f.text_right(30, y0 + 1, "--", FAINT)
                continue
            frm, _to, rate, pct, _h = self.view(e)
            c = self.col(pct, frm)
            end = f.text(1, y0 + 1, code, WHITE)
            txt = short_num(rate, 30 - end - 2, self.settings.base == "INR" and _to == "INR")
            f.text_right(30, y0 + 1, txt, mix(WHITE, c, 0.25))
            f.rect(1, y0 + 7, 30, 1, TRACK)
            ln = max(1, round(min(1.0, abs(pct) / full) * 15)) if abs(pct) >= 0.005 else 0
            if pct >= 0:
                f.rect(16, y0 + 7, ln, 1, c)
            else:
                f.rect(16 - ln, y0 + 7, ln, 1, c)
            if not ln:
                f.set(15, y0 + 7, scale(self.acc, 0.5))
                f.set(16, y0 + 7, scale(self.acc, 0.5))
        if pages > 1 and len(shown) < 4:
            self.ticks(f, pages, pg)

    def draw_board_scaled(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        """1 home unit is worth tiny amounts of most currencies: scale the whole page ("1K INR =")."""
        base = self.settings.base
        codes = self.codes
        rows = 4
        pages = math.ceil(len(codes) / rows)
        pg = self.page(t, pages)
        shown = codes[pg * rows : (pg + 1) * rows]
        cells = []
        for code in shown:
            e = v["pairs"].get(code)
            cells.append((code, self.view(e) if e else None))
        room = 30 - max(measure(c) for c, _v in cells) - 2  # right of the widest code on this page
        unit = page_unit([c[1][2] for c in cells if c[1]] or [1.0], room)
        head = f"{unit_token(unit, base == 'INR')} {base} ="
        if measure(head) > 30:
            head = head[:-2]
        f.text(1, 1, head, self.acc)
        f.hline(1, 6, measure(head), scale(self.acc, 0.45))
        for k, (code, vw) in enumerate(cells):
            y = 8 + k * 6
            if vw is None:
                f.text(1, y, code, FAINT)
                f.text_right(30, y, "--", FAINT)
                continue
            frm, _to, rate, pct, _h = vw
            f.text(1, y, code, WHITE)
            txt, _n = sig_text(rate * unit, room)
            f.text_right(30, y, txt or short_num(rate * unit, room), mix(WHITE, self.col(pct, frm), 0.45))
        if pages > 1:
            self.ticks(f, pages, pg)

    def draw_converter(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        codes = [c for c in self.codes if c in v["pairs"]] or self.codes
        i = self.page(t, len(codes))
        e = v["pairs"].get(codes[i])
        if not e:
            self._missing(f, codes[i])
            return
        frm, to, rate, pct, _h = self.view(e)
        amt = self.settings.amount
        res = amt * rate
        # top: amount + source code
        ind = frm == "INR"
        full_amt = fmt_num(amt, 0 if amt == int(amt) else 2, commas=True, indian=ind)
        a_font, a_txt = next(
            (
                (fo, tx)
                for fo, tx in (
                    ("small", full_amt),
                    ("small", compact(amt, ind)),
                    ("tiny", full_amt),
                    ("tiny", compact(amt, ind)),
                )
                if measure(tx, fo) + 1 + measure(frm) <= 30
            ),
            ("tiny", compact(amt, ind)),
        )
        w = measure(a_txt, a_font) + 1 + measure(frm)
        x = (32 - w) // 2
        x = f.text(x, 2, a_txt, WHITE, font=a_font) + 1
        f.text(x, 2 + (2 if a_font == "small" else 0), frm, self.acc)
        # equals rule (rows 10/12), a clear row, then the result on rows 14-23 and the caption on 26-30
        f.hline(12, 10, 8, scale(FAINT, 0.7))
        f.hline(12, 12, 8, scale(FAINT, 0.7))
        # result: the richest rendering that fits (big digits, then small with grouping)
        indian = to == "INR"
        d0 = 0 if abs(res) >= 100 else decimals_for(res)
        cands: list[tuple[str, str]] = []
        for d in range(d0, -1, -1):
            cands.append(("big", fmt_num(res, d)))
        for d in range(d0, -1, -1):
            cands.append(("small", fmt_num(res, d, commas=True, indian=indian)))
        cands.append(("small", compact(res, indian)))
        cands.append(("tiny", compact(res, indian)))
        font, txt = next(((fo, tx) for fo, tx in cands if measure(tx, fo) <= 30), cands[-1])
        y = 14 if font == "big" else 16
        f.text_center(y, txt, WHITE, font=font)
        sw = sign_width(to)
        cap_w = measure(to) + (sw + 2 if sw else 0)
        cx = (32 - cap_w) // 2
        if sw:
            draw_sign(f, to, cx, 26, self.acc)
            cx += sw + 2
        f.text(cx, 26, to, scale(self.col(pct, frm), 0.9) if abs(pct) >= 0.005 else self.acc)
        self.ticks(f, len(codes), i)

    def draw_heat(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        codes = self.codes
        per = 8
        pages = math.ceil(len(codes) / per)
        pg = self.page(t, pages)
        shown = codes[pg * per : (pg + 1) * per]
        n = len(shown)
        cols, rows = self.GRID.get(n, (2, 3) if n <= 6 else (2, 4))
        for k, code in enumerate(shown):
            cx, cy = k % cols, k // cols
            x0, y0 = cx * 32 // cols, cy * 32 // rows
            x1 = (cx + 1) * 32 // cols - (1 if cx < cols - 1 else 0)
            y1 = (cy + 1) * 32 // rows - (1 if cy < rows - 1 else 0)
            w, h = x1 - x0, y1 - y0
            e = v["pairs"].get(code)
            if not e:
                f.rect(x0, y0, w, h, PALETTE["ink"])
                f.text(x0 + (w - measure(code)) // 2, y0 + (h - 5) // 2, code, FAINT)
                continue
            frm, _to, rate, pct, _h = self.view(e)
            c = self.col(pct, frm)
            mag = min(1.0, abs(pct) / self.settings.heat_scale)
            # >= 0.22: the weakest tile still glows its colour on the LEDs (0.12 read as black)
            f.rect(x0, y0, w, h, scale(c, 0.22 + 0.4 * mag) if abs(pct) >= 0.005 else scale(self.acc, 0.22))
            if h < 12 and w >= 24:  # a wide, short tile: code left, change right
                ty = y0 + (h - 5) // 2
                end = f.text(x0 + 1, ty, code, WHITE)
                room = x0 + w - 2 - end - 1
                arrow = "" if abs(pct) < 0.005 else ("▲" if pct > 0 else "▼")
                opts = (fmt_pct(pct), f"{arrow}{abs(pct):.1f}%", fmt_pct(pct, False), f"{abs(pct):.1f}%")
                pt = next((q for q in opts if measure(q) <= room), "")
                f.text_right(x0 + w - 2, ty, pt, mix(c, WHITE, 0.7))
                continue
            if measure(code) > w - 1:  # narrow 3x3 tiles: letters touch rather than get cut
                f.text(x0 + (w - measure(code, spacing=0)) // 2, y0 + (h - 5) // 2, code, WHITE, spacing=0)
                continue
            lines: list[tuple[str, RGB]] = [(code, WHITE)]
            p_txt = next(
                (s for s in (fmt_pct(pct), fmt_pct(pct, False), f"{abs(pct):.1f}%") if measure(s) <= w - 2),
                "",
            )
            if h >= 17:
                r_txt = short_num(rate, w - 2, self.settings.base == "INR")
                if measure(r_txt) <= w - 2:
                    lines.append((r_txt, mix(WHITE, c, 0.2)))
            if p_txt and h >= 11:
                lines.append((p_txt, mix(c, WHITE, 0.7)))
            total = len(lines) * 6 - 1
            ty = y0 + (h - total) // 2
            for txt, col in lines:
                f.text(x0 + (w - measure(txt)) // 2, ty, txt, col)
                ty += 6
        self.ticks(f, pages, pg)

    # ------------------------------------------------------------ render
    def _missing(self, f: Frame, code: str) -> None:
        f.text_center(10, code, self.acc)
        f.text_center(17, "NO RATE", FAINT)

    def render(self, f: Frame, t: float) -> None:
        v = self.data()
        p = self._provider()
        if v is None:
            if p is not None and p.error:
                offline(f, "FX", "OFFLINE")
            else:
                loading(f, t, "FX", self.acc)
            return
        {
            "pair": self.draw_pair,
            "board": self.draw_board,
            "converter": self.draw_converter,
            "heat": self.draw_heat,
        }[self.settings.layout](f, t, v)
        if p is not None and p.error:  # cached values: one amber corner LED says "stale"
            f.set(0, 31, PALETTE["amber"])

    def status(self) -> dict[str, Any]:
        v = self.data() or {}
        pairs = v.get("pairs") or {}
        return {
            "base": self.settings.base,
            "date": v.get("date"),
            "rates": {k: round(e["rate"], 6) for k, e in pairs.items()},
        }
