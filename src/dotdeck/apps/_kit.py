"""The panel design kit: shared layouts, state screens, status colours and formatting for apps.

Everything here draws through `Frame` primitives (so it clips) and is pure: no I/O, cheap enough to call every
frame. See docs/DISPLAY_DESIGN.md §9 for pictures and rules. In short:

* **State screens** — `loading()`, `offline()`, `setup()` (not configured) and `empty()` share one layout:
  optional glyph at the top, a label on row 10 (16 with a glyph), a grey hint underneath. Calm on purpose.
* **Text that always fits** — `label()` centres tiny/small text inside the 1 px margins and falls back to a
  smaller font, then a marquee (when a time is given) or an ellipsis, instead of running off the edge.
* **Layouts** — `header()` (tiny title row + status on the right), `hero()` (the biggest font that fits),
  `icon_value()` (the "icon + one number" screen that reads best at a glance).
* **Status colours** — `OK`, `WARN`, `BAD`, `INFO` (+ `TEXT`, `MUTE`, `DIM`, `SHADE`) tuned for LEDs; use them
  instead of ad-hoc RGB tuples so every app means the same thing by "green".
"""

from __future__ import annotations

import math

from ..gfx import PALETTE, Frame, draw_marquee, fit, measure, mix, scale, to_rgb
from ..gfx.color import RGB, ColorLike
from ..gfx.icons import ICONS, draw_icon

# ------------------------------------------------------------------ status colours (LED-tuned)
OK: RGB = PALETTE["ok"]
WARN: RGB = PALETTE["warn"]
BAD: RGB = PALETTE["bad"]
INFO: RGB = PALETTE["info"]
TEXT: RGB = PALETTE["white"]
MUTE: RGB = PALETTE["mute"]
DIM: RGB = PALETTE["dim"]
SHADE: RGB = PALETTE["shade"]

#: inner text box: 1 px margin on each side
LEFT, RIGHT = 1, 30
INNER_W = RIGHT - LEFT + 1

# perimeter of the panel, clockwise from top-centre: 124 LEDs
PERIMETER: list[tuple[int, int]] = (
    [(x, 0) for x in range(16, 32)]
    + [(31, y) for y in range(1, 32)]
    + [(x, 31) for x in range(30, -1, -1)]
    + [(0, y) for y in range(30, -1, -1)]
    + [(x, 0) for x in range(1, 16)]
)


def ring(
    f: Frame,
    progress: float,
    color: ColorLike,
    track: ColorLike | None = (18, 18, 26),
    head: bool = True,
    gap: tuple[int, int] | None = None,
) -> None:
    """Progress around the panel edge (0..1), clockwise from 12 o'clock.

    `gap=(y0, y1)` leaves the side columns dark on rows y0..y1, so full-width hero text (a 30 px `big` time)
    never touches the ring and reads as part of it.
    """
    n = len(PERIMETER)
    lit = round(n * max(0.0, min(1.0, progress)))
    c = to_rgb(color)

    def skip(x: int, y: int) -> bool:
        return gap is not None and x in (0, 31) and gap[0] <= y <= gap[1]

    if track is not None:
        for x, y in PERIMETER[lit:]:
            if not skip(x, y):
                f.set(x, y, track)
    for i, (x, y) in enumerate(PERIMETER[:lit]):
        if skip(x, y):
            continue
        # fade the tail so the leading edge reads as motion
        k = 0.35 + 0.65 * (i / max(1, lit - 1)) if lit > 1 else 1.0
        f.set(x, y, scale(c, k))
    if head and 0 < lit <= n and not skip(*PERIMETER[lit - 1]):
        f.set(*PERIMETER[lit - 1], mix(c, (255, 255, 255), 0.6))


# ------------------------------------------------------------------ formatting
def compact_number(v: float) -> str:
    """84213.2 -> '84.2K', 3210.5 -> '3210', 0.5412 -> '.5412'."""
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.1f}B"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f}M"
    elif a >= 1e5:
        s = f"{v / 1e3:.0f}K"
    elif a >= 1e4:
        s = f"{v / 1e3:.1f}K"
    elif a >= 100:
        s = f"{v:.0f}"
    elif a >= 1:
        s = f"{v:.2f}"
    else:
        s = f"{v:.4f}".lstrip("0")
    return s


def bytes_rate(bps: float) -> str:
    for unit, k in (("G", 1e9), ("M", 1e6), ("K", 1e3)):
        if bps >= k:
            v = bps / k
            return f"{v:.0f}{unit}" if v >= 10 else f"{v:.1f}{unit}"
    return f"{bps:.0f}B"


# ------------------------------------------------------------------ text that always fits
def label(
    f: Frame,
    y: int,
    text: str,
    color: ColorLike,
    t: float | None = None,
    font: str = "tiny",
    x: int = LEFT,
    w: int = INNER_W,
) -> str:
    """Centre `text` in the box [x, x+w) on row `y`, never past the margins. Returns the font used.

    `small` falls back to `tiny` when it doesn't fit; tiny text that still doesn't fit scrolls as a marquee
    when `t` is given (content), or is cut with an ellipsis (static labels).
    """
    text = text.upper()
    if font == "small" and measure(text, "small") > w:
        font = "tiny"
        y += 1  # keep the optical centre of the 7 px row
    c = to_rgb(color)
    tw = measure(text, font)
    if tw <= w:
        f.text(x + (w - tw) // 2, y, text, c, font)
    elif t is not None:
        draw_marquee(f, text, t, x, y, w, c, font)
    else:
        f.text(x, y, fit(text, w, font), c, font)
    return font


def hero(
    f: Frame, y: int, text: str, color: ColorLike, t: float | None = None, x: int = LEFT, w: int = INNER_W
) -> str:
    """The primary value in the biggest font that fits the box: `big` (digits only), then `small`, then tiny.

    `y` is the top of a 10 px band; smaller fonts are centred in it. Returns the font used.
    """
    digits_only = all(ch in "0123456789:.- " for ch in text)
    if digits_only and measure(text, "big") <= w:
        tw = measure(text, "big")
        f.text(x + (w - tw) // 2, y, text, color, "big")
        return "big"
    if measure(text.upper(), "small") <= w:
        label(f, y + 2, text, color, font="small", x=x, w=w)
        return "small"
    label(f, y + 3, text, color, t, x=x, w=w)
    return "tiny"


# ------------------------------------------------------------------ layouts
def header(
    f: Frame,
    text: str,
    color: ColorLike,
    right: str = "",
    right_color: ColorLike = MUTE,
    y: int = 1,
    t: float | None = None,
    rule: ColorLike | None = None,
) -> None:
    """Tiny title row at the top: title left, optional status right, optional 1 px rule underneath (y+6)."""
    rw = measure(right.upper()) if right else 0
    if right:
        f.text_right(RIGHT, y, right.upper(), right_color)
    w = INNER_W - (rw + 2 if right else 0)
    tw = measure(text.upper())
    if tw <= w:
        f.text(LEFT, y, text.upper(), color)
    elif t is not None:
        draw_marquee(f, text.upper(), t, LEFT, y, w, to_rgb(color))
    else:
        f.text(LEFT, y, fit(text.upper(), w), color)
    if rule is not None:
        f.hline(0, y + 6, 32, rule)


def icon_value(
    f: Frame,
    icon: str,
    value: str,
    color: ColorLike,
    caption: str = "",
    t: float | None = None,
    value_color: ColorLike = TEXT,
    caption_color: ColorLike = MUTE,
) -> None:
    """The "icon + one number" screen: 2× icon centred on top, hero value in the middle, caption below.

    Layout (y): icon 1–14 · value 16–25 · caption 26–30. Unknown icon names fall back to no icon (value
    moves up to the centre).
    """
    rows = ICONS.get(icon)
    if rows:
        iw = len(rows[0]) * 2
        draw_icon(f, icon, (32 - iw) // 2, 1, color, k=2)
        hero(f, 16, value, value_color, t)
        if caption:
            label(f, 26, caption, caption_color, t)
    else:
        hero(f, 9, value, value_color, t)
        if caption:
            label(f, 22, caption, caption_color, t)


# ------------------------------------------------------------------ state screens
def _glyph_top(f: Frame, icon: str | None, color: RGB) -> bool:
    """Draw a state-screen glyph centred on rows 3–13: a DotDeck icon name (2× scale) or a `Sprite`."""
    if icon is None:
        return False
    if isinstance(icon, str):
        rows = ICONS.get(icon)
        if not rows:
            return False
        iw, ih = len(rows[0]), len(rows)
        k = 2 if ih * 2 <= 12 else 1
        draw_icon(f, icon, (32 - iw * k) // 2, 2 + (12 - ih * k) // 2, color, k=k)
        return True
    f.sprite(icon, (32 - icon.w) // 2, max(1, 8 - icon.h // 2))  # type: ignore[attr-defined]
    return True


def loading(f: Frame, t: float, label_text: str = "LOADING", color: ColorLike = INFO) -> None:
    """Standard placeholder while a provider has no data yet: label + three pulsing dots."""
    c = to_rgb(color)
    label(f, 10, label_text, scale(c, 0.7), t)
    for i in range(3):
        k = 0.5 + 0.5 * math.sin(t * 5 - i * 0.9)
        f.rect(11 + i * 4, 19, 2, 2, scale(c, 0.25 + 0.75 * k))


def offline(f: Frame, label_text: str, detail: str = "", icon: str | None = None) -> None:
    """Configured but unreachable / errored: amber label, grey one-word detail, short amber-dim rule."""
    has = _glyph_top(f, icon, scale(WARN, 0.8))
    y = 16 if has else 9
    label(f, y, label_text, WARN)
    if detail:
        label(f, y + 8, detail, MUTE)
    if not has:
        f.hline(12, 25, 8, (60, 20, 0))


def setup(f: Frame, label_text: str, hint: str, color: ColorLike = INFO, icon: str | None = None) -> None:
    """Not configured yet: app glyph, label in the app colour, grey hint ("SET HOST", "ADD URL"). No red."""
    c = to_rgb(color)
    has = _glyph_top(f, icon, scale(c, 0.85))
    y = 16 if has else 9
    label(f, y, label_text, c)
    label(f, y + 8, hint, MUTE)


def empty(f: Frame, message: str, detail: str = "", color: ColorLike = MUTE, icon: str | None = None) -> None:
    """Nothing to show right now (no games, no music): calm grey message, never a blank panel."""
    has = _glyph_top(f, icon, scale(to_rgb(color), 0.6))
    y = 16 if has else 12
    label(f, y, message, color)
    if detail:
        label(f, y + 8, detail, DIM)
