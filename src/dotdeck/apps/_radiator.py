"""Drawing and plumbing shared by the information-radiator apps (ci, uptime, obs, printer, mediaserver, anki).

Everything here is pure drawing or bookkeeping; no I/O. Icons are drawn from scratch for the 32×32 grid.
"""

from __future__ import annotations

import math
from typing import Any

from ..gfx import PALETTE, Frame, Sprite, measure, mix, scale
from ..gfx.color import RGB, ColorLike
from ._kit import label as fit_label

WHITE: RGB = (255, 255, 255)
BLACK: RGB = (0, 0, 0)

STATE_COLORS: dict[str, RGB] = {
    "pass": PALETTE["ok"],
    "fail": PALETTE["bad"],
    "running": PALETTE["amber"],
    "cancelled": PALETTE["dim"],
    "none": PALETTE["shade"],
}

# 9×9-ish app glyphs: one colour, silhouette first (docs/DISPLAY_DESIGN.md §7)
GLYPHS: dict[str, list[str]] = {
    "ci": [
        ".###.....",
        ".#.#..###",
        ".###..#.#",
        "..#...###",
        "..#....#.",
        "..#...#..",
        "..#..#...",
        ".###.....",
        ".#.#.....",
        ".###.....",
    ],
    "uptime": [
        "....#....",
        "....#....",
        "...#.#...",
        "...#.#...",
        "##.#..#.#",
        "..#...#.#",
        "..#....#.",
    ],
    "obs": [
        "..#####..",
        ".#.....#.",
        "#..###..#",
        "#.#####.#",
        "#.#####.#",
        "#.#####.#",
        "#..###..#",
        ".#.....#.",
        "..#####..",
    ],
    "printer": [
        "#########",
        "#..###..#",
        "#...#...#",
        "#.......#",
        "#.......#",
        "#..###..#",
        "#.#####.#",
        "#########",
    ],
    "media": [
        ".#.....#.",
        "..#...#..",
        "...#.#...",
        "#########",
        "#.......#",
        "#.......#",
        "#.......#",
        "#########",
        ".##...##.",
    ],
    "anki": [
        "...######",
        "...#....#",
        "######..#",
        "#....#..#",
        "#.##.#..#",
        "#....####",
        "#.##.#...",
        "#....#...",
        "######...",
    ],
}

CHECK = ["......##", ".....##.", "##..##..", ".####...", "..##...."]
CROSS = ["##...##", ".##.##.", "..###..", ".##.##.", "##...##"]
MINUS = ["#####", "#####"]
SMALL_CHECK = ["....#", "...#.", "#.#..", ".#..."]
SMALL_CROSS = ["#.#", ".#.", "#.#"]


def glyph(name: str, color: ColorLike) -> Sprite:
    return Sprite.parse(GLYPHS[name], {"#": color})


def provider(ctx: Any, name: str) -> Any:
    """The provider, or None when it isn't registered (bare test engines, previews)."""
    try:
        return ctx.provider(name)
    except (KeyError, AttributeError):
        return None


# ------------------------------------------------------------------------ formatting
def fmt_age(seconds: float | None) -> str:
    """42 -> '42S', 300 -> '5M', 7200 -> '2H', 200000 -> '2D'."""
    if seconds is None or seconds != seconds:
        return "--"
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}S"
    if s < 3600:
        return f"{s // 60}M"
    if s < 86400:
        return f"{s // 3600}H"
    return f"{min(999, s // 86400)}D"


def fmt_clock(seconds: float | None, force_hours: bool = False) -> str:
    """Elapsed/remaining time: 75 -> '1:15', 3725 -> '1:02:05'."""
    if seconds is None:
        return "--:--"
    s = max(0, int(seconds))
    h, m, sec = s // 3600, (s // 60) % 60, s % 60
    if h or force_hours:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def fmt_eta(seconds: float | None) -> str:
    """Compact remaining time for tiny type: '45S', '12M', '1H05', '14H'."""
    if seconds is None:
        return "--"
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}S"
    if s < 3600:
        return f"{s // 60}M"
    h, m = s // 3600, (s // 60) % 60
    return f"{h}H{m:02d}" if h < 10 else f"{h}H"


def fit_chars(text: str, width: int, font: str = "tiny") -> str:
    """Hard-trim (no ellipsis) so `text` fits in `width` px."""
    while text and measure(text, font) > width:
        text = text[:-1]
    return text


def short_name(text: str, width: int, font: str = "tiny") -> str:
    """Trim with a trailing '.' only when needed (tighter than an ellipsis on 32 px)."""
    if measure(text, font) <= width:
        return text
    return fit_chars(text, width - 2, font).rstrip() + "."


# ------------------------------------------------------------------------ drawing
def pulse(t: float, lo: float = 0.35, speed: float = 5.0) -> float:
    return lo + (1 - lo) * (0.5 + 0.5 * math.sin(t * speed))


def badge(f: Frame, cx: int, cy: int, r: int, state: str, t: float, color: ColorLike | None = None) -> None:
    """A round status badge: ✓ pass, ✕ fail, spinner running, – cancelled, ? unknown."""
    c = STATE_COLORS.get(state, STATE_COLORS["none"]) if color is None else color
    if state == "running":
        spinner(f, cx, cy, r, c, t)
        return
    if state == "none":
        f.circle(cx, cy, r, PALETTE["shade"], fill=False)
        f.text(cx - 1, cy - 2, "?", PALETTE["dim"])
        return
    f.circle(cx, cy, r, c)
    rows = {"pass": CHECK, "fail": CROSS}.get(state, MINUS)
    s = Sprite.parse(rows, {"#": BLACK})
    f.sprite(s, cx - s.w // 2, cy - s.h // 2)


def spinner(f: Frame, cx: int, cy: int, r: int, color: ColorLike, t: float, n: int = 16) -> None:
    """A rotating comet on a dim ring (1 rev / 1.6 s)."""
    f.circle(cx, cy, r, scale(color, 0.3), fill=False)
    head = (t / 1.6) % 1.0
    for i in range(n):
        a = 2 * math.pi * i / n
        age = (head - i / n) % 1.0
        if age > 0.6:
            continue
        k = 1.0 - age / 0.6
        x = cx + round(r * math.sin(a))
        y = cy - round(r * math.cos(a))
        f.set(x, y, mix(scale(color, 0.2 + 0.8 * k), WHITE, 0.35 * k * k))


def dot(f: Frame, x: int, y: int, color: ColorLike, size: int = 3) -> None:
    """A status dot: 3×3 with rounded corners (2×2 for size 2)."""
    if size <= 2:
        f.rect(x, y, size, size, color)
        return
    f.rect(x + 1, y, size - 2, size, color)
    f.rect(x, y + 1, size, size - 2, color)


def page_dots(f: Frame, n: int, i: int, y: int = 31, color: ColorLike = PALETTE["mute"]) -> None:
    """Pager ticks centred on the bottom row (2 px wide, 1 px gap) when there's more than one page."""
    if n <= 1:
        return
    n = min(n, 10)
    w = n * 3 - 1
    x0 = (32 - w) // 2
    for k in range(n):
        f.hline(x0 + k * 3, y, 2, color if k == i % n else PALETTE["shade"])


def setup_screen(f: Frame, t: float, icon: str, label: str, detail: str, color: ColorLike) -> None:
    """'Not configured' / idle: app glyph, label, one-line hint. Calm on purpose (no error red)."""
    g = glyph(icon, scale(color, 0.85))
    f.sprite(g, (32 - g.w) // 2, 4)
    fit_label(f, 16, label, color)
    fit_label(f, 24, detail, PALETTE["mute"])


def offline_screen(f: Frame, icon: str, label: str, detail: str = "OFFLINE") -> None:
    """Configured but unreachable: amber glyph + label, grey detail."""
    g = glyph(icon, PALETTE["amber"])
    f.sprite(g, (32 - g.w) // 2, 4)
    fit_label(f, 16, label, PALETTE["amber"])
    fit_label(f, 24, detail, PALETTE["mute"])


def stale_mark(f: Frame) -> None:
    """One amber corner LED: showing cached data because the last refresh failed."""
    f.set(0, 31, PALETTE["amber"])


def celebrate(f: Frame, t: float, color: ColorLike, seed: int = 7) -> None:
    """Falling confetti across the whole panel (deterministic for a given `t`)."""
    cols = [PALETTE["gold"], PALETTE["mint"], PALETTE["magenta"], PALETTE["cyan"], to_color(color)]
    for i in range(34):
        h = (i * 2654435761 + seed * 97) & 0xFFFF
        x = (h % 32 + int(3 * math.sin(t * 2 + i))) % 32
        speed = 6 + (h >> 5) % 9
        y = int(t * speed + (h >> 8) % 32) % 36 - 2
        f.set(x, y, cols[i % len(cols)])


def to_color(c: ColorLike) -> RGB:
    from ..gfx import to_rgb

    return to_rgb(c)


# ------------------------------------------------------------------------ events → notify
class Alerts:
    """Turns a provider's EventLog into notifications, once per event, across all slots.

    Primed at construction so events that happened before the app existed never replay. Studio previews
    (a sandboxed context whose key starts with ``preview:``) never drain events.
    """

    def __init__(self, ctx: Any, p: Any) -> None:
        self.ctx = ctx
        self.seq = getattr(p, "seq", 0) if p is not None else 0

    def drain(self, p: Any) -> list[dict[str, Any]]:
        if p is None or not hasattr(p, "events_since"):
            return []
        if str(getattr(self.ctx, "key", "")).startswith("preview:"):
            return []
        since = max(self.seq, getattr(p, "claimed_seq", 0))
        new = p.events_since(since)
        if not new:
            return []
        self.seq = new[-1]["seq"]
        p.claimed_seq = self.seq  # other slots of the same app skip what we already announced
        return new
