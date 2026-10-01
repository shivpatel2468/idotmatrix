"""Drawing kit for Live Scores: a clipped/offset pen, original 5x5 sport glyphs, time formats, layouts.

Every layout draws through a `Pen`, so the same card can be the whole screen (focus mode), half of it
(compact), or one tile of a scrolling strip ("all" mode) without anything bleeding outside its box.
All art here is drawn from scratch — no logos, no downloaded assets.

Width budget (tiny ≈ 4 px/char, small ≈ 5 px/char, big digit 7 px): names are hard-cut to the room they
have rather than ellipsised — on a 32 px panel an ellipsis costs a whole character.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from typing import Any

from ..gfx import Frame, mix, scale, to_rgb
from ..gfx.color import RGB, ColorLike
from ..gfx.font import draw_text, marquee_x, measure, wrap

GOLD: RGB = (255, 214, 0)
WHITE: RGB = (255, 255, 255)
SOFT: RGB = (215, 215, 225)
MUTE: RGB = (140, 140, 160)
DIM: RGB = (70, 70, 90)
SHADE: RGB = (28, 28, 40)
LIVE: RGB = (255, 20, 40)
TICK: RGB = (200, 200, 120)  # live caption
UNDER: RGB = (255, 50, 60)  # golf: under par (red, as on every leaderboard)
OVER: RGB = (40, 140, 255)  # golf: over par

Game = dict[str, Any]


def led_team_color(hex_color: str, alt: str) -> RGB:
    """Team colours are designed for screens; very dark ones vanish on LEDs, so lift or swap them."""
    for c in (hex_color, alt):
        try:
            r, g, b = to_rgb(c)
        except ValueError:
            continue
        if max(r, g, b) >= 90 and (r, g, b) != (255, 255, 255):
            m = max(r, g, b)
            return scale((r, g, b), 255 / m)  # normalise to full brightness
    return WHITE


def cut(s: str, width: int, font: str = "tiny") -> str:
    """Hard-truncate to `width` px (no ellipsis)."""
    s = s or ""
    while s and measure(s, font) > width:
        s = s[:-1]
    return s.rstrip(" ./-")


# ================================================================== pen
class Pen:
    """Drawing into the box (ox, oy, w, h) of a frame; coordinates are local and everything clips."""

    __slots__ = ("clip", "f", "h", "ox", "oy", "w")

    def __init__(self, f: Frame, ox: int = 0, oy: int = 0, w: int = 32, h: int = 32) -> None:
        self.f, self.ox, self.oy, self.w, self.h = f, ox, oy, w, h
        self.clip = (max(0, ox), max(0, oy), min(31, ox + w - 1), min(31, oy + h - 1))

    def sub(self, x: int, y: int, w: int, h: int) -> Pen:
        p = Pen(self.f, self.ox + x, self.oy + y, w, h)
        a, b, c, d = p.clip
        p.clip = (max(a, self.clip[0]), max(b, self.clip[1]), min(c, self.clip[2]), min(d, self.clip[3]))
        return p

    def rect(self, x: int, y: int, w: int, h: int, c: ColorLike) -> None:
        x0, y0 = max(self.ox + x, self.clip[0]), max(self.oy + y, self.clip[1])
        x1, y1 = min(self.ox + x + w - 1, self.clip[2]), min(self.oy + y + h - 1, self.clip[3])
        if x0 <= x1 and y0 <= y1:
            self.f.rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1, c)

    def hline(self, x: int, y: int, w: int, c: ColorLike) -> None:
        self.rect(x, y, w, 1, c)

    def vline(self, x: int, y: int, h: int, c: ColorLike) -> None:
        self.rect(x, y, 1, h, c)

    def set(self, x: int, y: int, c: ColorLike) -> None:
        self.rect(x, y, 1, 1, c)

    def text(
        self, x: int, y: int, s: str, c: ColorLike, font: str = "tiny", box: tuple[int, int] | None = None
    ) -> int:
        """Draw text at local (x, y); `box` = (x0, x1) local horizontal limits. Returns the local end x."""
        cx0, cy0, cx1, cy1 = self.clip
        if box is not None:
            cx0, cx1 = max(cx0, self.ox + box[0]), min(cx1, self.ox + box[1])
        if cx0 > cx1 or cy0 > cy1 or not s:
            return x
        end = draw_text(self.f, self.ox + x, self.oy + y, s, to_rgb(c), font, (cx0, cy0, cx1, cy1))
        return end - self.ox

    def text_right(self, right: int, y: int, s: str, c: ColorLike, font: str = "tiny") -> int:
        """Right-aligned at `right`; returns the local x where the text starts."""
        x = right - measure(s, font) + 1
        self.text(x, y, s, c, font)
        return x

    def text_center(
        self, y: int, s: str, c: ColorLike, font: str = "tiny", x: int = 0, w: int | None = None
    ) -> None:
        w = self.w if w is None else w
        self.text(x + (w - measure(s, font)) // 2, y, s, c, font)

    def marquee(
        self, s: str, t: float, x: int, y: int, w: int, c: ColorLike, font: str = "tiny", speed: float = 12.0
    ) -> None:
        """Centred if it fits, else a seamless loop that pauses at the start (like `draw_marquee`)."""
        if not s or w <= 0:
            return
        tw = measure(s, font)
        sx = marquee_x(s, t, x, w, font, speed, 12, 1.2)
        self.text(sx, y, s, c, font, box=(x, x + w - 1))
        if tw > w:
            self.text(sx + tw + 12, y, s, c, font, box=(x, x + w - 1))

    def glyph(self, rows: tuple[str, ...], x: int, y: int, pal: dict[str, RGB]) -> None:
        for yy, row in enumerate(rows):
            for xx, ch in enumerate(row):
                if ch != ".":
                    self.set(x + xx, y + yy, pal[ch])


# ================================================================ glyphs
# Original 5x5 pixel art, one silhouette per sport family.
_R, _W = (255, 30, 50), (255, 255, 255)
ICONS: dict[str, tuple[tuple[str, ...], dict[str, RGB]]] = {
    "basketball": ((".ooo.", "obobo", "bbbbb", "obobo", ".ooo."), {"o": (255, 110, 0), "b": (110, 40, 0)}),
    "football": (("..bbb", ".bwbb", "bbwbb", "bbwb.", "bbb.."), {"b": (200, 90, 20), "w": _W}),
    "baseball": ((".www.", "wrwrw", "wwwww", "wrwrw", ".www."), {"w": _W, "r": _R}),
    "hockey": (("...s.", "...s.", "..s..", "ss...", ".kkk."), {"s": (230, 200, 150), "k": (130, 150, 255)}),
    "soccer": ((".www.", "wwkww", "wkkkw", "wwkww", ".www."), {"w": _W, "k": (60, 60, 80)}),
    "cricket": (("....s", "...s.", "..s..", "ss..r", "s...."), {"s": (240, 200, 120), "r": _R}),
    "tennis": ((".lll.", "lwlll", "llwll", "lllwl", ".lll."), {"l": (190, 255, 0), "w": _W}),
    "golf": ((".wrr.", ".wrrr", ".w...", ".w...", "ggggg"), {"w": _W, "r": _R, "g": (0, 200, 90)}),
    "racing": (
        ("wkwkw", "kwkwk", "wkwkw", "s....", "s...."),
        {"w": _W, "k": (40, 40, 55), "s": (160, 160, 180)},
    ),
    "mma": ((".rrr.", "rrrrr", "rrrrr", ".rrr.", ".www."), {"r": _R, "w": _W}),
    "other": (("g...g", "ggggg", ".ggg.", "..g..", ".ggg."), {"g": GOLD}),  # trophy
}


def icon(p: Pen, sport: str, x: int, y: int) -> None:
    rows, pal = ICONS.get(sport, ICONS["other"])
    p.glyph(rows, x, y, pal)


# ================================================================ options
@dataclass(frozen=True)
class Opts:
    colors: bool = True
    clock: bool = True
    records: bool = False
    icons: bool = True
    time_format: str = "12h"  # 12h | 24h | countdown
    layout: str = "classic"
    favs: frozenset[str] = field(default_factory=frozenset)
    now: float = 0.0

    def tc(self, team: dict[str, Any]) -> RGB:
        return (
            led_team_color(team.get("color", "#ffffff"), team.get("alt", "#888888")) if self.colors else SOFT
        )

    def fav(self, team: dict[str, Any]) -> bool:
        return bool(self.favs) and (team.get("abbr") in self.favs or team.get("short") in self.favs)

    def but(self, **kw: Any) -> Opts:
        return replace(self, **kw)


def is_fav(g: Game, favs: frozenset[str]) -> bool:
    if not favs:
        return False
    return any(
        c.get("abbr") in favs or c.get("short") in favs
        for c in g.get("competitors") or [g["away"], g["home"]]
    )


# ================================================================ time
@lru_cache(maxsize=512)
def start_ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _clock(ts: float, fmt: str) -> str:
    d = datetime.fromtimestamp(ts)
    if fmt == "24h":
        return f"{d.hour}:{d.minute:02d}"
    h = d.hour % 12 or 12
    ap = "A" if d.hour < 12 else "P"
    return f"{h}{ap}" if d.minute == 0 else f"{h}:{d.minute:02d}{ap}"


def countdown(ts: float, now: float, long: bool = False) -> str:
    s = ts - now
    if s <= 0:
        return "SOON"
    m = int(s // 60)
    if m < 60:
        return f"IN {max(1, m)}M" if long else f"{max(1, m)}M"
    h, mm = divmod(m, 60)
    if h < 24:
        return (f"IN {h}H {mm}M" if mm and h < 10 else f"IN {h}H") if long else f"{h}H"
    return f"IN {h // 24}D" if long else f"{h // 24}D"


def when(g: Game, o: Opts, long: bool = False) -> str:
    """Start time of an upcoming game in the chosen format ('7:30P', '19:30', '2H' / 'SAT 7:30P', 'IN 2H')."""
    ts = start_ts(g.get("start"))
    if ts is None:
        return "TBD"
    now = o.now or time.time()
    if o.time_format == "countdown":
        return countdown(ts, now, long)
    s = _clock(ts, o.time_format)
    if not long:
        return s
    day = datetime.fromtimestamp(ts).date()
    delta = (day - datetime.fromtimestamp(now).date()).days
    if delta == 0:
        return f"TODAY {s}"
    if delta == 1:
        return f"TMRW {s}"
    if 1 < delta < 7:
        return f"{datetime.fromtimestamp(ts).strftime('%a').upper()} {s}"
    return f"{day.month}/{day.day} {s}"


def status_short(g: Game, o: Opts) -> str:
    if g["state"] == "pre":
        return when(g, o)
    if g["state"] == "post":
        return "" if g.get("kind") in ("field", "duel") else (g.get("short") or "FT")
    return g.get("short") or "LIVE"


def footer(g: Game, o: Opts) -> str:
    """The scrolling caption line: clock / situation / last play, result headline, or start time."""
    sport, st = g["sport"], g["state"]
    parts: list[str] = []
    if st == "in":
        short, clock = g.get("short") or "", g.get("clock") or ""
        if short == "HT":
            parts.append("HALF TIME")
        elif sport in ("basketball", "football", "hockey"):
            parts.append(f"{short} {clock}" if o.clock and clock else short)
        elif sport == "baseball":
            outs = (g.get("situation") or {}).get("outs")
            parts.append(g["detail"] + (f" {outs} OUT" if outs is not None else ""))
        elif sport == "soccer":
            parts.append(clock if o.clock and clock else g["detail"])
        else:
            parts.append(g["detail"])
        down = (g.get("situation") or {}).get("down")
        if down:
            parts.append(down)
    elif st == "post":
        parts.append(g["detail"] or "FINAL")
    else:
        parts.append(when(g, o, long=True))
        if o.records:
            ra, rh = g["away"]["extra"].get("record"), g["home"]["extra"].get("record")
            if ra or rh:
                parts.append(f"{ra or '-'} V {rh or '-'}")
    if st != "pre" and g.get("last_play"):
        parts.append(g["last_play"])
    elif st == "post" and g.get("headline") and g["headline"] not in parts:
        parts.append(g["headline"])
    return " · ".join(p for p in parts if p)


def pulse(t: float) -> RGB:
    return mix((80, 0, 0), LIVE, 0.5 + 0.5 * math.sin(t * 5))


def leader(g: Game) -> str | None:
    try:
        a, h = float(g["away"]["score"]), float(g["home"]["score"])
    except (TypeError, ValueError):
        w = [s for s in ("away", "home") if g[s].get("winner")]
        return w[0] if w else None
    return None if a == h else ("away" if a > h else "home")


def header(
    p: Pen, g: Game, t: float, o: Opts, label: str | None = None, y: int = 1, scroll: bool = False
) -> None:
    """Icon + label on the left, compact status on the right (pulsing dot while live).

    When space is short, in order: the live dot becomes a pulsing status colour, the icon goes,
    and finally the label scrolls (`scroll=True`) or is cut. Label and status keep a 2 px gap.
    """
    st = status_short(g, o)
    live = g["state"] == "in"
    text = label if label is not None else g["tag"]
    sw = measure(st) if st else 0
    tw = measure(text)
    dot, show_icon = live, o.icons
    # a scrolling label keeps the icon and the dot; a static one gives them up before being cut
    full = ((live, o.icons), (False, o.icons), (live, False), (False, False))
    for dot, show_icon in full[:1] if scroll else full:
        if 1 + (6 if show_icon else 0) + tw + (2 + sw if sw else 0) + (3 if dot else 0) <= 31:
            break
    x = 7 if show_icon else 1
    if show_icon:
        icon(p, g["sport"], 1, y)
    right = 30
    if dot:
        p.rect(29, y + 1, 2, 2, pulse(t))
        right = 27
    sx = right + 1
    if st:
        color = (SOFT if dot else mix(SOFT, LIVE, 0.5 + 0.5 * math.sin(t * 5))) if live else MUTE
        if g["state"] == "pre":
            color = GOLD
        sx = p.text_right(right, y, st, color)
    room = sx - 2 - x if st else 31 - x
    if tw <= room:
        p.text(x, y, text, GOLD)
    elif scroll and room >= 12:
        p.marquee(text, t, x, y, room, GOLD)
    elif measure(cut(text, room)) >= 7:
        p.text(x, y, cut(text, room), GOLD)


# ================================================================ team layouts
def _row_metrics(g: Game, side: str, o: Opts) -> tuple[str, str, int]:
    """(score text, score font, px room left for the abbreviation) of one scoreboard row."""
    team = g[side]
    pre = g["state"] == "pre"
    score = (team["extra"].get("record", "") if o.records else "") if pre else team["score"]
    sfont = "tiny" if pre or measure(score, "small") > 20 else "small"
    sw = measure(score, sfont)
    room = 27 - sw if sw else 28  # abbr from x3, 1 px before the score
    if (g.get("situation") or {}).get("possession") == side:
        room -= 3
    return score, sfont, room


def abbr_font(g: Game, o: Opts) -> str:
    """Small type for both abbreviations when both fit, else tiny for both (rows stay consistent)."""
    ok = all(measure(g[s]["abbr"], "small") <= _row_metrics(g, s, o)[2] for s in ("away", "home"))
    return "small" if ok else "tiny"


def team_row(
    p: Pen, g: Game, side: str, y: int, t: float, o: Opts, lead: str | None, afont: str = "small"
) -> None:
    """Colour tab · abbreviation · score (small, right). One 7 px scoreboard row."""
    team = g[side]
    tc = o.tc(team)
    if o.colors:
        p.rect(0, y, 2, 7, tc)
    pre = g["state"] == "pre"
    score, sfont, room = _row_metrics(g, side, o)
    poss = (g.get("situation") or {}).get("possession") == side
    abbr = cut(team["abbr"], room, afont)
    end = p.text(3, y if afont == "small" else y + 1, abbr, tc, afont)
    if poss:
        red = (g.get("situation") or {}).get("redzone")
        p.rect(end + 1, y + 2, 2, 3, LIVE if red else GOLD)
    if o.fav(team) and not o.colors:
        p.rect(0, y + 2, 2, 3, GOLD)
    if score:
        win = lead in (side, None)
        col = DIM if pre else (WHITE if win else MUTE)
        p.text_right(30, y if sfont == "small" else y + 1, score, col, sfont)


def classic(p: Pen, g: Game, t: float, o: Opts) -> None:
    header(p, g, t, o)
    lead = leader(g)
    af = abbr_font(g, o)
    team_row(p, g, "away", 8, t, o, lead, af)
    team_row(p, g, "home", 17, t, o, lead, af)
    live = g["state"] == "in"
    if g["sport"] == "baseball" and live and g.get("situation"):
        bases(p, g, 26)
        p.marquee(footer(g, o), t, 11, 26, 20, TICK)
        return
    p.marquee(footer(g, o), t, 1, 26, 30, TICK if live else MUTE)


def bases(p: Pen, g: Game, y: int) -> None:
    """The diamond: three 3x3 bases (2nd on top), lit gold when occupied — 9x5 px."""
    b = (g.get("situation") or {}).get("bases") or [False, False, False]
    for (bx, by), occ in zip(((6, 2), (3, 0), (0, 2)), b, strict=True):
        c = GOLD if occ else DIM
        p.set(1 + bx + 1, y + by, c)
        p.rect(1 + bx, y + by + 1, 3, 1, c)
        p.set(1 + bx + 1, y + by + 2, c)


def _hero_font(scores: list[str]) -> str:
    for font, room in (("big", 14), ("small", 15)):
        if all((s.isdigit() or font != "big") and measure(s, font) <= room for s in scores):
            return font
    return "tiny"


def hero(p: Pen, g: Game, t: float, o: Opts) -> None:
    """Split screen in both teams' colours with the biggest score that fits both halves."""
    lead = leader(g)
    pre = g["state"] == "pre"
    font = _hero_font([g["away"]["score"], g["home"]["score"]])
    for side, x0 in (("away", 0), ("home", 16)):
        team = g[side]
        tc = o.tc(team)
        if o.colors:
            p.rect(x0, 0, 16, 25, scale(tc, 0.16))
            p.rect(x0, 0, 16, 2, tc)
        af = "small" if measure(team["abbr"], "small") <= 14 else "tiny"
        p.text_center(4 if af == "small" else 5, cut(team["abbr"], 15, af), tc, af, x=x0, w=16)
        if pre:
            rec = team["extra"].get("record", "") if o.records else ""
            if rec:
                p.text_center(13, cut(rec, 15), MUTE, x=x0, w=16)
            continue
        win = lead in (side, None)
        y = {"big": 13, "small": 15, "tiny": 16}[font]
        p.text_center(y, team["score"], WHITE if win else (150, 150, 165), font, x=x0, w=16)
    p.vline(15, 2, 23 if not pre else 10, (0, 0, 0))
    p.vline(16, 2, 23 if not pre else 10, (0, 0, 0))
    if pre:
        s = when(g, o)
        p.text_center(18, s, GOLD, "small" if measure(s, "small") <= 30 else "tiny")
    if g["state"] == "in":
        p.rect(15, 22, 2, 2, pulse(t))
    p.marquee(footer(g, o), t, 1, 26, 30, TICK if g["state"] == "in" else SOFT)


def big_score(p: Pen, g: Game, t: float, o: Opts) -> None:
    """Diagonal hero: away score top-right, home score bottom-left, 10 px digits; labels on the outer rows."""
    if g["state"] == "pre":
        preview(p, g, t, o)
        return
    lead = leader(g)
    live = g["state"] == "in"
    a, h = g["away"], g["home"]
    ta, th = o.tc(a), o.tc(h)
    if o.colors:
        p.rect(0, 0, 32, 16, scale(ta, 0.10))
        p.rect(0, 16, 32, 16, scale(th, 0.10))
        p.rect(0, 0, 2, 16, ta)
        p.rect(30, 16, 2, 16, th)
    # top label row: away abbr · status
    st = status_short(g, o)
    right = 27 if live else 29
    if live:
        p.rect(28, 2, 2, 2, pulse(t))
    sx = p.text_right(right, 1, st, SOFT if live else MUTE) if st else right + 1
    p.text(3, 1, cut(a["abbr"], sx - 4), ta)
    # bottom label row: clock / record · home abbr
    abbr_x = p.text_right(28, 26, cut(h["abbr"], 16), th)
    info = ""
    if live and o.clock and g["sport"] in ("basketball", "football", "hockey") and g.get("short") != "HT":
        info = g.get("clock") or ""
    elif live and g["sport"] == "baseball":
        outs = (g.get("situation") or {}).get("outs")
        info = f"{outs} OUT" if outs is not None else ""
    elif o.records:
        info = h["extra"].get("record", "")
    if info and measure(info) <= abbr_x - 3:
        p.text(2, 26, info, MUTE)
    for team, top in ((a, True), (h, False)):
        s = team["score"]
        font = "big" if s.isdigit() and measure(s, "big") <= 27 else "small"
        side = "away" if top else "home"
        col = WHITE if lead in (side, None) else scale(WHITE, 0.5)
        if top:
            p.text_right(29, 6 if font == "big" else 8, s, col, font)
        else:
            p.text(3 if not o.colors else 2, 16 if font == "big" else 18, s, col, font)


def preview(p: Pen, g: Game, t: float, o: Opts) -> None:
    """Pre-game card: both teams in colour, and the start time as the hero."""
    header(p, g, t, o, label=g["tag"])
    for side, y in (("away", 8), ("home", 15)):
        team = g[side]
        tc = o.tc(team)
        if o.colors:
            p.rect(0, y, 2, 5, tc)
        rec = team["extra"].get("record", "") if o.records else ""
        p.text(3, y, cut(team["abbr"], 26 - measure(rec)), tc)
        if rec:
            p.text_right(30, y, rec, MUTE)
    s = when(g, o)
    if all(ch.isdigit() or ch == ":" for ch in s) and measure(s, "big") <= 30:
        p.text_center(21, s, GOLD, "big")
    else:
        p.text_center(22, s, GOLD, "small" if measure(s, "small") <= 30 else "tiny")


def compact_block(p: Pen, g: Game, t: float, o: Opts) -> None:
    """16 px tall: two 7 px rows (tab, abbr, score) — a half-screen game."""
    kind = g.get("kind", "team")
    if kind == "field":
        _compact_field(p, g, t, o)
        return
    label = "abbr" if kind == "team" else "short"
    if g["state"] == "pre":
        a, h = g["away"], g["home"]
        if o.colors:
            p.rect(0, 1, 2, 5, o.tc(a))
            p.rect(0, 9, 2, 5, o.tc(h))
        s = when(g, o)
        if measure(s) + measure(a[label][:3]) > 25 and s[-1:] in ("A", "P"):
            s = s[:-1]  # '5:45A' -> '5:45' when the row is tight (half-screen card)
        sx = p.text_right(30, 1, s, GOLD)
        p.text(3, 1, cut(a[label], sx - 5), o.tc(a))
        rec = h["extra"].get("record", "") if o.records else ""
        p.text(3, 9, cut(h[label], 26 - measure(rec)), o.tc(h))
        if rec:
            p.text_right(30, 9, rec, MUTE)
        return
    lead = leader(g)
    live = g["state"] == "in"
    for side, y in (("away", 1), ("home", 8)):
        team = g[side]
        tc = o.tc(team)
        if o.colors:
            p.rect(0, y, 2, 7, mix(tc, WHITE, 0.25 + 0.25 * math.sin(t * 5)) if live else tc)
        s = team["score"]
        font = "small" if measure(s, "small") <= 20 else "tiny"
        sw = measure(s, font)
        p.text(3, y + 1, cut(team[label], 27 - sw), tc)
        win = lead in (side, None)
        col = WHITE if win else (MUTE if live else DIM)
        p.text_right(30, y if font == "small" else y + 1, s, col, font)


def _compact_field(p: Pen, g: Game, t: float, o: Opts) -> None:
    rows = g["competitors"][:2]
    if not rows:
        p.text(3, 1, cut(g.get("name") or g["tag"], 28), GOLD)
        p.text(3, 9, cut(when(g, o, long=True) if g["state"] == "pre" else g["detail"], 28), MUTE)
        return
    for c, y in zip(rows, (1, 8), strict=False):
        pos = c["extra"].get("pos", "").lstrip("T")
        tc = led_team_color(c["color"], c["alt"]) if o.colors else SOFT
        p.rect(0, y, 2, 7, tc if g["sport"] == "racing" else (GOLD if pos == "1" else DIM))
        end = p.text(3, y + 1, pos, MUTE)
        sc = golf_score(c["score"]) if g["sport"] == "golf" else ""
        room = 30 - measure(sc) - 2 - end - 2
        p.text(end + 2, y + 1, cut(c["short"], room), WHITE if pos == "1" else SOFT)
        if sc:
            p.text_right(30, y + 1, sc, golf_color(c["score"]))


def compact(p: Pen, games: list[Game], t: float, o: Opts) -> None:
    for i, g in enumerate(games[:2]):
        compact_block(p.sub(0, i * 16, 32, 16), g, t, o)
    if len(games) > 1:
        p.hline(3, 15, 28, SHADE)


# ================================================================ sport layouts
def golf_color(score: str) -> RGB:
    if score.startswith("-"):
        return UNDER
    if score.startswith("+"):
        return OVER
    return WHITE


def golf_score(score: str) -> str:
    """Leaderboard convention: under par is red *without* the minus sign ('-16' -> '16')."""
    return score[1:] if score.startswith("-") else score


def tennis(p: Pen, g: Game, t: float, o: Opts) -> None:
    """Sets grid: colour tab, 3-letter player code, one small-digit column per set (live set in gold)."""
    label = f"{g.get('note') or ''} {g.get('name') or g['tag']}".strip()
    header(p, g, t, o, label=label, scroll=True)
    sa = g["away"]["extra"].get("sets") or []
    sh = g["home"]["extra"].get("sets") or []
    n = max(len(sa), len(sh))
    first = max(0, n - 3)  # 4th/5th sets push the oldest out of view
    cols = n - first
    pitch = 5  # 4 px digit per striped column: adjacent sets never read as one number
    grid_x = 32 - cols * pitch
    live = g["state"] == "in"
    for i in range(cols):
        cx = grid_x + i * pitch
        if live and i == cols - 1:
            p.rect(cx, 7, pitch, 17, (40, 34, 0))
        elif i % 2 == (cols - 1) % 2:
            p.rect(cx, 7, pitch, 17, (14, 14, 22))
    for side, y, sets in (("away", 8, sa), ("home", 16, sh)):
        c = g[side]
        p.rect(0, y, 2, 7, o.tc(c))
        col = MUTE if c.get("winner") is False else WHITE
        room = grid_x - 1 - 3
        name = c["short"]
        if measure(name, "small") <= room:
            font = "small"
        elif measure(name) <= room:
            font = "tiny"
        else:
            font, name = ("small", cut(name, room, "small")) if room >= 14 else ("tiny", cut(name, room))
        p.text(3, y if font == "small" else y + 1, name, col, font)
        if c["extra"].get("serving") and live:
            p.set(2, y + 3, GOLD)
        for i, st in enumerate(sets[first:]):
            gcol = GOLD if (live and i == cols - 1) else (WHITE if st["won"] else MUTE)
            p.text(grid_x + i * pitch + 1, y, str(min(st["games"], 9)), gcol, "small")
    cap = tennis_footer(g, o)
    p.marquee(cap, t, 1, 26, 30, TICK if live else MUTE)


def tennis_footer(g: Game, o: Opts) -> str:
    a, h = g["away"]["short"], g["home"]["short"]
    if g["state"] == "pre":
        return f"{a} V {h} · {when(g, o, long=True)}"
    if g["state"] == "in":
        return (
            f"{a} V {h} · SET {len(g['away']['extra'].get('sets') or []) or 1} · {g.get('name') or ''}".strip(
                " ·"
            )
        )
    w = next((c for c in (g["away"], g["home"]) if c.get("winner")), None)
    return f"{w['short']} WINS · {g.get('name') or ''}".strip(" ·") if w else (g["detail"] or "FINAL")


def golf(p: Pen, g: Game, t: float, o: Opts) -> None:
    """Leaderboard top 3 (a favourite outside it takes row 3); red = under par."""
    if g.get("kind") != "field":
        classic(p, g, t, o)
        return
    header(p, g, t, o, label=g.get("name") or g["tag"], scroll=True)
    rows = list(g["competitors"][:3])
    favs = [c for c in g["competitors"][3:] if o.fav(c)]
    if favs and len(rows) == 3:
        rows[2] = favs[0]
    if not rows:
        p.text_center(10, "TEE TIMES" if g["state"] == "pre" else "NO FIELD", MUTE)
        p.marquee(when(g, o, long=True), t, 1, 18, 30, GOLD)
        return
    for c, y in zip(rows, (8, 14, 20), strict=False):
        pos = c["extra"].get("pos", "")
        num = pos.lstrip("T")
        p.text_right(7, y, num, GOLD if num == "1" else MUTE)
        if pos.startswith("T"):
            p.set(0, y + 2, DIM)
        sc = golf_score(c["score"])
        sx = p.text_right(30, y, sc, golf_color(c["score"]))
        name_col = GOLD if o.fav(c) else (WHITE if num == "1" else SOFT)
        p.text(9, y, cut(c["short"], sx - 2 - 9), name_col)
    lead = rows[0]
    thru = lead["extra"].get("thru")
    if g["state"] == "pre":
        cap = when(g, o, long=True)
    elif g["state"] == "in" and thru:
        cap = f"{g.get('note') or ''} THRU {thru}".strip()
    else:
        cap = g["detail"] or "FINAL"
    p.marquee(cap, t, 1, 26, 30, MUTE)


def racing(p: Pen, g: Game, t: float, o: Opts) -> None:
    """Top 3 drivers in 7 px type with their constructor's colour; next session when idle."""
    session = g.get("note") or "F1"
    rows = g["competitors"][:3]
    if not rows:  # between sessions: GP name, the next session as hero, its start time
        nxt = g.get("next") or {}
        nx = {**g, "start": nxt.get("start") or g.get("start"), "state": "pre"}
        header(p, nx, t, o, label=g["tag"])
        p.marquee(g.get("name") or g["tag"], t, 1, 8, 30, SOFT)
        name = "QUALI" if (nxt.get("session") or session).upper() == "QUAL" else nxt.get("session") or session
        p.text_center(15, cut(name.upper(), 30, "small"), GOLD, "small")
        p.marquee(when(nx, o, long=True), t, 1, 26, 30, MUTE)
        return
    header(p, g, t, o, label=session)
    for c, y in zip(rows, (8, 16, 24), strict=False):
        pos = c["extra"].get("pos", "")
        tc = led_team_color(c["color"], c["alt"]) if o.colors else SOFT
        p.text_right(5, y + 1, pos, GOLD if pos == "1" else MUTE)
        p.rect(7, y, 2, 7, tc)
        p.text(11, y, c["abbr"][:3], WHITE if pos == "1" else SOFT, "small")
        if o.fav(c):
            p.rect(29, y + 2, 2, 3, GOLD)


def mma(p: Pen, g: Game, t: float, o: Opts) -> None:
    """Fighter vs fighter in corner colours; winner bright, loser dimmed, result or records below."""
    label = ("MAIN " if g.get("main") else "") + (g.get("note") or g["tag"])
    header(p, g, t, o, label=label, scroll=True)
    for side, y in (("away", 8), ("home", 17)):
        c = g[side]
        p.rect(0, y, 2, 7, o.tc(c))
        name = c["short"]
        if measure(name, "small") <= 27:
            font = "small"
        elif measure(name) <= 27:
            font = "tiny"  # a whole surname in tiny beats a cut one in small
        else:
            font, name = "small", cut(name, 27, "small")
        col = MUTE if c.get("winner") is False else WHITE
        p.text(3, y if font == "small" else y + 1, cut(name, 27, font), col, font)
        if c.get("winner"):
            p.rect(0, y, 2, 7, GOLD)
    if g["state"] == "pre":
        cap = when(g, o, long=True)
        p.marquee(cap, t, 1, 26, 30, GOLD)
        return
    ra, rh = g["away"]["extra"].get("record"), g["home"]["extra"].get("record")
    w = next((c for c in (g["away"], g["home"]) if c.get("winner")), None)
    cap = f"{ra} V {rh}" if (o.records and ra and rh) else (g["detail"] or "")
    if w and not o.records:
        cap = f"{w['short']} WINS · {cap}"
    p.marquee(cap, t, 1, 26, 30, TICK if g["state"] == "in" else MUTE)


def cricket(p: Pen, g: Game, t: float, o: Opts, face: int = 0) -> None:
    """Two faces: scores (label line + 7 px runs/wkts per side), then the match situation."""
    if face == 1 and (g.get("headline") or g["detail"]):
        header(p, g, t, o, label=g.get("note") if g["league"] == "cricket" else g["tag"], scroll=True)
        lines = wrap(g.get("headline") or g["detail"], 30)
        for i, line in enumerate(lines[:3]):
            p.text(1, 8 + i * 6, line, SOFT if i == 0 else MUTE)
        if len(lines) > 3:
            p.marquee(" ".join(lines[3:]), t, 1, 26, 30, MUTE)
        return
    for side, y0 in (("away", 1), ("home", 17)):
        c = g[side]
        tc = o.tc(c)
        bat = c["extra"].get("batting") and g["state"] == "in"
        if o.colors:
            p.rect(0, y0, 2, 13, GOLD if c.get("winner") else tc)
        ov = c["extra"].get("overs")
        end = p.text(3, y0, cut(c["abbr"], 27), tc)  # the team first; overs only in the room left
        for info in (f"{ov} OV", f"{ov}") if ov else ((c["extra"].get("record", ""),) if o.records else ()):
            if info and measure(info) <= 30 - end - 2:
                p.text_right(30, y0, info, MUTE)
                break
        if g["state"] == "pre":
            continue
        s = c["score"] or "-"
        font = "small" if measure(s, "small") <= 27 else "tiny"
        col = WHITE if (bat or c.get("winner")) else MUTE
        p.text_right(30, y0 + 6 if font == "small" else y0 + 7, s, col, font)
        if bat:
            p.rect(3, y0 + 8, 2, 2, pulse(t))
    if g["state"] == "pre":
        p.text_center(8, "V", DIM)
        s = when(g, o)
        p.text_center(24, s, GOLD, "small" if measure(s, "small") <= 30 else "tiny")


# ================================================================ dispatch
def card(p: Pen, g: Game, t: float, o: Opts, layout: str | None = None, face: int = 0) -> None:
    """One full 32x32 game card in the right layout for its sport."""
    layout = layout or o.layout
    sport, kind = g["sport"], g.get("kind", "team")
    if sport == "tennis" and kind == "duel":
        tennis(p, g, t, o)
    elif sport == "mma":
        mma(p, g, t, o)
    elif sport == "golf":
        golf(p, g, t, o)
    elif sport == "racing":
        racing(p, g, t, o)
    elif sport == "cricket" and layout != "hero":
        cricket(p, g, t, o, face)
    elif layout == "hero":
        hero(p, g, t, o)
    elif layout == "big_score":
        big_score(p, g, t, o)
    else:
        classic(p, g, t, o)


def ticker_line(games: list[Game], o: Opts) -> str:
    out = []
    for x in games:
        if x.get("kind") == "field":
            lead = x["competitors"][0] if x["competitors"] else None
            out.append(
                f"{x['tag']} {lead['short']} {lead['score']}" if lead else f"{x['tag']} {x.get('name', '')}"
            )
        elif x["state"] == "pre":
            label = "abbr" if x.get("kind") == "team" else "short"
            out.append(f"{x['away'][label]} V {x['home'][label]} {when(x, o)}")
        else:
            a, h = x["away"], x["home"]
            label = "abbr" if x.get("kind") == "team" else "short"
            out.append(f"{a[label]} {a['score']}-{h['score']} {h[label]}")
    return "  ·  ".join(out)


def message(
    p: Pen,
    sport: str,
    tag: str,
    big: str,
    o: Opts,
    t: float,
    detail: str = "",
    foot: str = "",
    color: RGB = MUTE,
) -> None:
    """Empty / info state: header, a bold message (small type, up to 2 lines), a detail, a caption."""
    x = 1
    if o.icons:
        icon(p, sport, 1, 1)
        x = 7
    p.text(x, 1, cut(tag, 30 - x), GOLD)
    lines = wrap(big, 30, "small")[:2]
    y = 8
    for line in lines:
        p.text_center(y, line, color, "small")
        y += 9
    if detail and y <= 20:
        p.marquee(detail, t, 1, y, 30, SOFT)
    if foot:
        p.marquee(foot, t, 1, 26, 30, GOLD)
