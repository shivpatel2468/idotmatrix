"""The shared base of every casino panel app (docs/CASINO.md §3–4): one thin `App` per game.

A casino app owns one `CasinoGame` (the rules + round machine in ``deskdot.casino``) and joins the engine-wide
`CasinoSession` (credits follow players across games). It

* speaks the lobby protocol (``lobby`` / ``seat`` actions, the join QR) like a `GameApp`, so phones join with
  the same QR code; the server serves ``casino.html`` to them because ``category == "casino"``;
* forwards every ``casino`` action — phone ops (player = lobby seat) and host ops (player = "host") — to the
  session and the table;
* publishes ``status()`` (public, every phone + the studio) and ``private_status(seat)`` (that phone only);
* draws through a `View` — a snapshot of the table — so the live table and the preview/demo modes share one
  drawing path (``view`` setting: live, a self-playing demo loop, or one frozen phase for previews).

A new game subclasses `CasinoApp`, sets ``Game`` and ``Settings`` (its rules fields + ``view``), and implements
``draw_table(f, v, now)`` for the phases it animates (spinning / dealing / result); the betting board, the "no
more bets" card, the join QR, the paused card and the history strip come from here.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..casino import HOST, CasinoGame, CasinoSession, fair
from ..casino.rulebook import guide
from ..casino.table import LOCK_SECONDS
from ..engine import App, AppSettings, Choice
from ..gfx import Frame, measure, mix, scale
from ._kit import PERIMETER

# ------------------------------------------------------------------ palette (LED-tuned, dark tones ≥ 45)
GOLD = (255, 200, 30)
GOLD_DIM = (120, 90, 14)
FELT = (0, 120, 60)
RED = (230, 18, 36)
BLACKP = (66, 66, 76)  # a "black" pocket / tile: lit, or it vanishes on the panel
GREEN = (0, 190, 80)
WHITE = (240, 240, 240)
MUTE = (140, 140, 160)
DIM = (70, 70, 90)
INK = (0, 0, 0)
TONES: dict[str, tuple[int, int, int]] = {
    "red": RED,
    "black": BLACKP,
    "green": GREEN,
    "white": (90, 90, 104),
    "down": (30, 110, 255),
    "seven": (220, 160, 0),
    "up": (230, 30, 60),
    "gold": (200, 150, 0),
}


# ------------------------------------------------------------------ table themes (docs/CASINO.md §11)
RGB3 = tuple[int, int, int]


@dataclass(frozen=True)
class TableTheme:
    """One table look, for the panel (LED colours: saturated, dark tones still lit) and the phones / studio (CSS).

    The panel draws on black; a theme recolours the table's own chrome — headers, highlights, the waiting chip,
    the timer bar, wheel rims, the paused and "no more bets" cards, the win bulbs. Semantic colours (roulette
    red / black pockets, card suits, under / over tones, players' colours) never change. ``classic`` is exactly
    the original look.
    """

    id: str
    name: str
    accent: RGB3  # headers, highlights, win bulbs (classic: gold)
    accent_dim: RGB3
    text: RGB3  # the countdown digits
    alert: RGB3  # NO MORE BETS, the last seconds of the countdown
    chip: RGB3  # the waiting chip's body
    chip_dark: RGB3
    rim: RGB3  # wheel rims (roulette)
    wood: RGB3  # the roulette ball track
    felt: RGB3  # table felt (mid tone)
    felt_dark: RGB3  # dark felt: the timer bar's track, the paused band
    css: dict[str, str] = field(
        default_factory=dict
    )  # phone + studio: felt, felt2, felt3, accent, accent_hi, …, pattern
    description: str = ""  # one line: the table's concept (the studio's theme picker, the docs)

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description, "css": dict(self.css)}


def _css(felt: str, felt2: str, felt3: str, accent: str, hi: str, lo: str, deep: str, wing: str, wing2: str,
         wing3: str, ink: str = "#1a1200", *, pattern: str = "none", size: str = "auto") -> dict[str, str]:  # fmt: skip
    """A theme's CSS tokens. ``pattern`` is the felt's motif: a CSS ``background-image`` of pure gradients (no
    ``url()``), drawn over the felt at low contrast; ``size`` is its ``background-size``, one entry per layer."""
    a = accent.lstrip("#")
    rgb = ", ".join(str(int(a[i : i + 2], 16)) for i in (0, 2, 4))
    s4 = mix_hex(wing, "#ffffff", 0.11)
    text = (
        next(  # the accent as text: nudged toward accent_hi until it reads (WCAG AA) on the lightest surface
            c for c in (mix_hex(accent, hi, k / 10) for k in range(11)) if contrast(c, s4) >= 4.5 or c == hi
        )
    )
    return {
        "felt": felt, "felt2": felt2, "felt3": felt3, "accent": accent, "accent_hi": hi, "accent_lo": lo,
        "accent_deep": deep, "accent_rgb": rgb, "ink": ink, "wing": wing, "wing2": wing2, "wing3": wing3,
        # derived page palette (phones + studio): every surface is tinted by the theme's wings, text on felt by the felt
        "bg": mix_hex(wing3, "#000000", 0.45), "surface": mix_hex(wing3, "#ffffff", 0.02),
        "surface2": mix_hex(wing2, "#ffffff", 0.05), "surface3": mix_hex(wing, "#ffffff", 0.05),
        "surface4": s4, "felt_ink": mix_hex("#ffffff", felt, 0.1), "accent_text": text,
        "pattern": pattern, "pattern_size": size,
    }  # fmt: skip


def mix_hex(a: str, b: str, t: float) -> str:
    """CSS ``color-mix(in srgb, a, b t)``: ``a`` moved ``t`` of the way to ``b`` (sRGB channels, rounded)."""
    x, y = a.lstrip("#"), b.lstrip("#")
    ch = (round(int(x[i : i + 2], 16) * (1 - t) + int(y[i : i + 2], 16) * t) for i in (0, 2, 4))
    return "#" + "".join(f"{c:02x}" for c in ch)


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio of two ``#rrggbb`` colours (1 … 21)."""

    def lum(h: str) -> float:
        h = h.lstrip("#")
        c = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


TABLE_THEMES: dict[str, TableTheme] = {
    t.id: t
    for t in (
        TableTheme(
            "classic",
            "Classic green",
            description="The original: green baize with a fine twill and gold trim.",
            accent=GOLD,
            accent_dim=GOLD_DIM,
            text=WHITE,
            alert=RED,
            chip=RED,
            chip_dark=(150, 8, 20),
            rim=(150, 108, 20),
            wood=(70, 42, 22),
            felt=FELT,
            felt_dark=(40, 34, 10),
            css=_css(
                "#0d6b45",
                "#0a5236",
                "#063823",
                "#ffcc33",
                "#ffe08a",
                "#e2a400",
                "#3a2c08",
                "#102a20",
                "#0b1c16",
                "#0a1512",
                pattern="repeating-linear-gradient(45deg, rgba(255, 255, 255, 0.035) 0 1px, transparent 1px 5px)",
            ),
        ),
        TableTheme(
            "royal",
            "Royal blue",
            description="Deep blue baize under a gold diamond lattice, like a palace card room.",
            accent=(255, 205, 50),
            accent_dim=(110, 88, 18),
            text=WHITE,
            alert=RED,
            chip=(40, 100, 255),
            chip_dark=(18, 46, 160),
            rim=(70, 110, 230),
            wood=(34, 44, 100),
            felt=(20, 60, 170),
            felt_dark=(18, 30, 80),
            css=_css(
                "#1b4aa8",
                "#123680",
                "#0a1f4d",
                "#ffcc33",
                "#ffe08a",
                "#e2a400",
                "#3a2c08",
                "#13214a",
                "#0d1734",
                "#0a1128",
                pattern="repeating-linear-gradient(45deg, rgba(255, 204, 51, 0.06) 0 1px, transparent 1px 22px), "
                "repeating-linear-gradient(-45deg, rgba(255, 204, 51, 0.06) 0 1px, transparent 1px 22px)",
                size="auto, auto",
            ),
        ),
        TableTheme(
            "crimson",
            "Crimson velvet",
            description="Red velvet with brass medallions: an old-world salon.",
            accent=(235, 175, 60),
            accent_dim=(112, 78, 22),
            text=WHITE,
            alert=(255, 90, 30),
            chip=(240, 200, 70),
            chip_dark=(130, 92, 14),
            rim=(200, 140, 50),
            wood=(96, 22, 34),
            felt=(150, 20, 40),
            felt_dark=(64, 14, 22),
            css=_css(
                "#8c1a2e",
                "#691322",
                "#3d0a14",
                "#e8b04a",
                "#f6d38a",
                "#c48a24",
                "#3a2508",
                "#2c1016",
                "#200b10",
                "#170809",
                pattern="radial-gradient(circle, rgba(232, 176, 74, 0.1) 0 2px, transparent 2.5px), "
                "repeating-radial-gradient(circle, transparent 0 8px, rgba(232, 176, 74, 0.05) 8px 9px, "
                "transparent 9px 16px)",
                size="36px 36px, 36px 36px",
            ),
        ),
        TableTheme(
            "midnight",
            "Midnight neon",
            description="Violet after-hours felt with faint neon scan lines.",
            accent=(190, 90, 255),
            accent_dim=(84, 40, 128),
            text=(235, 225, 255),
            alert=(255, 40, 150),
            chip=(150, 60, 255),
            chip_dark=(72, 24, 140),
            rim=(130, 70, 235),
            wood=(46, 26, 80),
            felt=(60, 30, 120),
            felt_dark=(36, 18, 70),
            css=_css(
                "#3a1d72",
                "#29145a",
                "#140a33",
                "#c77dff",
                "#e2bcff",
                "#9a4ae0",
                "#2a1145",
                "#1a1230",
                "#120c22",
                "#0c0818",
                "#12001f",
                pattern="repeating-linear-gradient(135deg, rgba(199, 125, 255, 0.07) 0 1px, transparent 1px 12px)",
            ),
        ),
        TableTheme(
            "strip",
            "Neon strip",
            description="Hot-pink boulevard felt with a neon chevron and cyan sparks.",
            accent=(255, 50, 170),
            accent_dim=(120, 22, 80),
            text=(225, 255, 255),
            alert=(0, 220, 255),
            chip=(0, 210, 255),
            chip_dark=(0, 96, 140),
            rim=(0, 200, 255),
            wood=(90, 14, 80),
            felt=(110, 20, 110),
            felt_dark=(60, 10, 56),
            css=_css(
                "#5a1260",
                "#410c47",
                "#22052a",
                "#ff3fb0",
                "#ff9ad6",
                "#d81f8a",
                "#3d0a2a",
                "#22102e",
                "#170b22",
                "#100717",
                "#1f0013",
                pattern="linear-gradient(135deg, rgba(255, 63, 176, 0.08) 25%, transparent 25%), "
                "linear-gradient(225deg, rgba(255, 63, 176, 0.08) 25%, transparent 25%)",
                size="24px 24px, 24px 24px",
            ),
        ),
        TableTheme(
            "emerald",
            "Emerald & champagne",
            description="Dark emerald with a champagne harlequin check: the high-limit room.",
            accent=(250, 215, 140),
            accent_dim=(118, 100, 60),
            text=WHITE,
            alert=RED,
            chip=(0, 200, 130),
            chip_dark=(0, 100, 64),
            rim=(210, 180, 110),
            wood=(24, 66, 48),
            felt=(0, 110, 76),
            felt_dark=(16, 56, 40),
            css=_css(
                "#0b5a43",
                "#084431",
                "#03241a",
                "#f1dca0",
                "#fbefcc",
                "#cdb26a",
                "#352c12",
                "#0d2a22",
                "#091e18",
                "#071612",
                pattern="repeating-conic-gradient(from 45deg, rgba(241, 220, 160, 0.05) 0 25%, transparent 0 50%)",
                size="22px 22px",
            ),
        ),
        TableTheme(
            "burgundy",
            "Burgundy & ivory",
            description="Burgundy felt quilted in ivory thread, like a members' club.",
            accent=(245, 232, 200),
            accent_dim=(112, 104, 84),
            text=WHITE,
            alert=(255, 50, 50),
            chip=(210, 30, 74),
            chip_dark=(112, 14, 40),
            rim=(230, 214, 180),
            wood=(84, 22, 42),
            felt=(120, 26, 56),
            felt_dark=(62, 16, 30),
            css=_css(
                "#6b1f36",
                "#521729",
                "#2c0b16",
                "#f4ead2",
                "#fffaf0",
                "#d6c8a4",
                "#3a3020",
                "#2a121a",
                "#1e0d13",
                "#16090e",
                pattern="repeating-linear-gradient(60deg, rgba(244, 234, 210, 0.05) 0 1px, transparent 1px 18px), "
                "repeating-linear-gradient(-60deg, rgba(244, 234, 210, 0.05) 0 1px, transparent 1px 18px)",
                size="auto, auto",
            ),
        ),
        # ---- the grand tour (docs/CASINO.md §11): each a whole look — felt, metal, and a motif woven in the felt
        TableTheme(
            "noir",
            "Riviera noir",
            description="Black baize, silver rails and champagne pinstripes: a seaside salon after midnight.",
            accent=(232, 214, 168),
            accent_dim=(104, 94, 70),
            text=WHITE,
            alert=RED,
            chip=(200, 202, 216),
            chip_dark=(90, 90, 104),
            rim=(190, 192, 206),
            wood=(60, 60, 70),
            felt=(58, 60, 68),
            felt_dark=(46, 46, 52),
            css=_css(
                "#26282e",
                "#1c1d22",
                "#0f1013",
                "#e8d7a8",
                "#f7eed6",
                "#b9a97e",
                "#2e2a1e",
                "#18191d",
                "#111215",
                "#0c0c0e",
                pattern="repeating-linear-gradient(90deg, rgba(232, 215, 168, 0.07) 0 1px, transparent 1px 14px), "
                "repeating-linear-gradient(90deg, rgba(200, 204, 216, 0.04) 0 1px, transparent 1px 7px)",
                size="auto, auto",
            ),
        ),
        TableTheme(
            "jade",
            "Imperial jade",
            description="Deep jade felt, red-gold trim and rolling auspicious clouds.",
            accent=(255, 190, 40),
            accent_dim=(116, 84, 14),
            text=WHITE,
            alert=(255, 50, 40),
            chip=(225, 30, 40),
            chip_dark=(120, 14, 20),
            rim=(230, 170, 50),
            wood=(20, 80, 64),
            felt=(0, 120, 96),
            felt_dark=(10, 60, 48),
            css=_css(
                "#0c6655",
                "#084e41",
                "#032a23",
                "#f2c14e",
                "#fbe3a0",
                "#d39a22",
                "#3d2a08",
                "#0e2a26",
                "#0a1f1c",
                "#071614",
                pattern="radial-gradient(circle at 50% 100%, transparent 0 7px, rgba(242, 193, 78, 0.09) 7px 8px, "
                "transparent 8.5px 11px, rgba(242, 193, 78, 0.06) 11px 12px, transparent 12.5px), "
                "radial-gradient(circle at 0 50%, transparent 0 7px, rgba(242, 193, 78, 0.09) 7px 8px, "
                "transparent 8.5px 11px, rgba(242, 193, 78, 0.06) 11px 12px, transparent 12.5px), "
                "radial-gradient(circle at 100% 50%, transparent 0 7px, rgba(242, 193, 78, 0.09) 7px 8px, "
                "transparent 8.5px 11px, rgba(242, 193, 78, 0.06) 11px 12px, transparent 12.5px)",
                size="28px 28px, 28px 28px, 28px 28px",
            ),
        ),
        TableTheme(
            "deco",
            "Gilded deco",
            description="Jazz-age black lacquer with gold sunburst fans.",
            accent=(255, 195, 60),
            accent_dim=(112, 84, 24),
            text=WHITE,
            alert=RED,
            chip=(240, 200, 90),
            chip_dark=(110, 86, 30),
            rim=(220, 170, 60),
            wood=(70, 56, 30),
            felt=(62, 56, 42),
            felt_dark=(48, 42, 30),
            css=_css(
                "#24211b",
                "#1a1814",
                "#0e0d0b",
                "#e9c46a",
                "#f6e2a8",
                "#c49a3c",
                "#33270c",
                "#1b1914",
                "#13110e",
                "#0d0c0a",
                pattern="repeating-conic-gradient(from -90deg at 50% 100%, rgba(233, 196, 106, 0.1) 0 3deg, "
                "transparent 3deg 15deg), "
                "radial-gradient(circle at 50% 100%, transparent 0 19px, rgba(233, 196, 106, 0.1) 19px 20px, "
                "transparent 20.5px)",
                size="48px 24px, 48px 24px",
            ),
        ),
        TableTheme(
            "marigold",
            "Marigold masala",
            description="Magenta silk felt, saffron gold and a scatter of paisley buds — the big-screen wedding table.",
            accent=(255, 150, 20),
            accent_dim=(120, 66, 8),
            text=(255, 240, 220),
            alert=(255, 40, 40),
            chip=(230, 30, 140),
            chip_dark=(110, 14, 66),
            rim=(255, 160, 40),
            wood=(90, 20, 56),
            felt=(140, 20, 90),
            felt_dark=(66, 10, 44),
            css=_css(
                "#7c1452",
                "#5e0f3e",
                "#320822",
                "#ffa21f",
                "#ffd08a",
                "#e07b00",
                "#3d2306",
                "#2b0c1f",
                "#1f0816",
                "#160610",
                "#1f0f00",
                pattern="radial-gradient(5px 8px at 30% 38%, rgba(255, 162, 31, 0.12) 98%, transparent 100%), "
                "radial-gradient(circle at 36% 22%, rgba(255, 162, 31, 0.1) 0 2px, transparent 2.5px), "
                "radial-gradient(4px 6px at 78% 80%, rgba(255, 208, 138, 0.09) 98%, transparent 100%), "
                "radial-gradient(circle at 74% 66%, rgba(255, 208, 138, 0.08) 0 1.5px, transparent 2px)",
                size="40px 40px, 40px 40px, 40px 40px, 40px 40px",
            ),
        ),
        TableTheme(
            "diwali",
            "Festival of lights",
            description="Deep maroon felt, diya-gold flames and a rangoli of dots.",
            accent=(255, 180, 40),
            accent_dim=(118, 80, 14),
            text=(255, 240, 210),
            alert=(255, 70, 40),
            chip=(255, 120, 30),
            chip_dark=(130, 50, 10),
            rim=(240, 170, 50),
            wood=(90, 24, 30),
            felt=(130, 20, 40),
            felt_dark=(60, 12, 20),
            css=_css(
                "#6a1424",
                "#510f1b",
                "#2b070e",
                "#ffbf3c",
                "#ffe39a",
                "#e09612",
                "#3d2808",
                "#260b10",
                "#1b080c",
                "#130508",
                pattern="radial-gradient(circle at 25% 25%, rgba(255, 191, 60, 0.16) 0 1.5px, transparent 2px), "
                "radial-gradient(circle at 75% 75%, rgba(255, 191, 60, 0.16) 0 1.5px, transparent 2px), "
                "radial-gradient(circle at 75% 25%, rgba(255, 120, 160, 0.1) 0 1px, transparent 1.5px), "
                "radial-gradient(circle at 25% 75%, rgba(255, 120, 160, 0.1) 0 1px, transparent 1.5px), "
                "repeating-linear-gradient(45deg, rgba(255, 191, 60, 0.04) 0 1px, transparent 1px 13px)",
                size="18px 18px, 18px 18px, 18px 18px, 18px 18px, auto",
            ),
        ),
        TableTheme(
            "cyber",
            "Cyber grid",
            description="Graphite felt traced with a teal circuit grid and magenta nodes.",
            accent=(40, 240, 220),
            accent_dim=(10, 96, 90),
            text=(220, 255, 250),
            alert=(255, 40, 200),
            chip=(255, 40, 200),
            chip_dark=(120, 16, 96),
            rim=(40, 220, 210),
            wood=(40, 52, 64),
            felt=(50, 64, 80),
            felt_dark=(30, 40, 52),
            css=_css(
                "#1f2a33",
                "#172029",
                "#0c1116",
                "#2ff3e0",
                "#a6fff6",
                "#12bfae",
                "#0a3330",
                "#141b22",
                "#0f141a",
                "#0a0e12",
                "#00201d",
                pattern="linear-gradient(rgba(47, 243, 224, 0.07) 1px, transparent 1px), "
                "linear-gradient(90deg, rgba(47, 243, 224, 0.07) 1px, transparent 1px), "
                "radial-gradient(circle at 1px 1px, rgba(255, 60, 200, 0.28) 0 1.5px, transparent 2px)",
                size="22px 22px, 22px 22px, 44px 44px",
            ),
        ),
        TableTheme(
            "arcade",
            "Pixel arcade",
            description="Cabinet-black felt on a neon-green pixel grid, coin-yellow chips.",
            accent=(40, 255, 90),
            accent_dim=(14, 100, 36),
            text=(220, 255, 230),
            alert=(255, 40, 180),
            chip=(255, 220, 0),
            chip_dark=(120, 100, 0),
            rim=(40, 230, 90),
            wood=(40, 50, 44),
            felt=(30, 60, 36),
            felt_dark=(20, 46, 26),
            css=_css(
                "#14201a",
                "#0f1813",
                "#070b09",
                "#39ff6a",
                "#b3ffc6",
                "#12d14a",
                "#0b3315",
                "#111a15",
                "#0c130f",
                "#080d0a",
                "#002a0c",
                pattern="linear-gradient(rgba(57, 255, 106, 0.07) 1px, transparent 1px), "
                "linear-gradient(90deg, rgba(57, 255, 106, 0.07) 1px, transparent 1px), "
                "repeating-conic-gradient(rgba(57, 255, 106, 0.05) 0 25%, transparent 0 50%)",
                size="8px 8px, 8px 8px, 32px 32px",
            ),
        ),
        TableTheme(
            "sakura",
            "Sakura night",
            description="Indigo felt under drifting blossom-pink petals.",
            accent=(255, 120, 170),
            accent_dim=(110, 50, 74),
            text=(255, 230, 240),
            alert=(255, 60, 60),
            chip=(255, 140, 190),
            chip_dark=(120, 50, 84),
            rim=(230, 130, 180),
            wood=(40, 44, 100),
            felt=(40, 50, 140),
            felt_dark=(24, 28, 80),
            css=_css(
                "#26306e",
                "#1c2455",
                "#0f1433",
                "#ffa3c7",
                "#ffd6e6",
                "#e8749f",
                "#3d1828",
                "#161a38",
                "#10132a",
                "#0b0d1e",
                "#2a0614",
                pattern="radial-gradient(4px 7px at 22% 30%, rgba(255, 163, 199, 0.16) 98%, transparent 100%), "
                "radial-gradient(7px 4px at 68% 72%, rgba(255, 214, 230, 0.12) 98%, transparent 100%), "
                "radial-gradient(circle at 86% 18%, rgba(255, 163, 199, 0.12) 0 1.5px, transparent 2px), "
                "radial-gradient(circle at 40% 88%, rgba(255, 163, 199, 0.09) 0 1px, transparent 1.5px)",
                size="52px 52px, 52px 52px, 52px 52px, 52px 52px",
            ),
        ),
        TableTheme(
            "arctic",
            "Glacier",
            description="Glacier-blue felt with silver frost crystals, like a table carved in ice.",
            accent=(190, 235, 255),
            accent_dim=(70, 96, 110),
            text=WHITE,
            alert=(255, 60, 80),
            chip=(80, 200, 255),
            chip_dark=(20, 90, 140),
            rim=(170, 220, 245),
            wood=(30, 70, 100),
            felt=(20, 90, 140),
            felt_dark=(14, 44, 70),
            css=_css(
                "#164e6c",
                "#103c54",
                "#082233",
                "#d8ecf6",
                "#f4fbff",
                "#a9c6d6",
                "#1d2c35",
                "#0f2433",
                "#0b1a25",
                "#08131b",
                "#0a1a24",
                pattern="repeating-linear-gradient(60deg, rgba(216, 236, 246, 0.06) 0 1px, transparent 1px 16px), "
                "repeating-linear-gradient(-60deg, rgba(216, 236, 246, 0.06) 0 1px, transparent 1px 16px), "
                "repeating-linear-gradient(0deg, rgba(216, 236, 246, 0.04) 0 1px, transparent 1px 14px)",
                size="auto, auto, auto",
            ),
        ),
        TableTheme(
            "oasis",
            "Desert oasis",
            description="Turquoise pool felt framed in sand gold, laid with star-and-diamond tiles.",
            accent=(255, 200, 110),
            accent_dim=(110, 86, 44),
            text=WHITE,
            alert=RED,
            chip=(20, 210, 200),
            chip_dark=(6, 100, 96),
            rim=(230, 190, 110),
            wood=(90, 64, 30),
            felt=(0, 130, 130),
            felt_dark=(10, 60, 62),
            css=_css(
                "#0d5c63",
                "#09464c",
                "#04262a",
                "#f0cf8e",
                "#faeacb",
                "#cfa75a",
                "#3a2b10",
                "#2a2117",
                "#1f1811",
                "#16110c",
                pattern="repeating-conic-gradient(from 45deg, rgba(240, 207, 142, 0.07) 0 25%, transparent 0 50%), "
                "radial-gradient(circle, transparent 0 5px, rgba(240, 207, 142, 0.1) 5px 6px, transparent 6.5px)",
                size="24px 24px, 24px 24px",
            ),
        ),
        TableTheme(
            "abyss",
            "Ocean abyss",
            description="Deep-sea teal with bioluminescent aqua sparks and rising bubbles.",
            accent=(60, 240, 255),
            accent_dim=(20, 96, 110),
            text=(220, 255, 255),
            alert=(255, 90, 60),
            chip=(120, 255, 200),
            chip_dark=(30, 110, 90),
            rim=(40, 200, 230),
            wood=(10, 60, 76),
            felt=(0, 90, 110),
            felt_dark=(4, 46, 56),
            css=_css(
                "#08424f",
                "#063440",
                "#021c24",
                "#5cf2ff",
                "#b9faff",
                "#22c3d6",
                "#08323a",
                "#0a2128",
                "#07181d",
                "#051115",
                "#00222a",
                pattern="radial-gradient(circle at 30% 30%, rgba(92, 242, 255, 0.16) 0 1.5px, transparent 2px), "
                "radial-gradient(circle at 75% 62%, rgba(92, 242, 255, 0.1) 0 1px, transparent 1.5px), "
                "radial-gradient(circle at 55% 88%, transparent 0 4px, rgba(92, 242, 255, 0.08) 4px 5px, "
                "transparent 5.5px)",
                size="40px 40px, 40px 40px, 40px 40px",
            ),
        ),
        TableTheme(
            "volcano",
            "Volcano",
            description="Charcoal basalt felt split by glowing lava seams.",
            accent=(255, 100, 20),
            accent_dim=(120, 44, 8),
            text=(255, 236, 220),
            alert=(255, 210, 40),
            chip=(255, 60, 20),
            chip_dark=(130, 24, 6),
            rim=(230, 90, 30),
            wood=(70, 50, 44),
            felt=(70, 56, 50),
            felt_dark=(48, 38, 34),
            css=_css(
                "#2e2420",
                "#221b18",
                "#120e0c",
                "#ff6a1f",
                "#ffb07a",
                "#e04a00",
                "#3d1806",
                "#211b18",
                "#181311",
                "#110d0c",
                "#1f0800",
                pattern="repeating-linear-gradient(115deg, transparent 0 18px, rgba(255, 106, 31, 0.1) 18px 19px, "
                "transparent 19px 31px), "
                "repeating-linear-gradient(35deg, transparent 0 23px, rgba(255, 106, 31, 0.07) 23px 24px, "
                "transparent 24px 41px)",
                size="auto, auto",
            ),
        ),
        TableTheme(
            "galaxy",
            "Galaxy",
            description="Deep-space purple felt scattered with a cyan starfield.",
            accent=(80, 220, 255),
            accent_dim=(30, 86, 110),
            text=(230, 240, 255),
            alert=(255, 60, 180),
            chip=(170, 90, 255),
            chip_dark=(76, 36, 130),
            rim=(90, 200, 255),
            wood=(40, 30, 90),
            felt=(50, 30, 110),
            felt_dark=(30, 18, 66),
            css=_css(
                "#2a1a55",
                "#1e1240",
                "#0d0823",
                "#59e3ff",
                "#b5f3ff",
                "#1fb5db",
                "#0d3340",
                "#171230",
                "#100c22",
                "#0b0818",
                "#001d26",
                pattern="radial-gradient(circle at 12% 18%, rgba(255, 255, 255, 0.34) 0 1px, transparent 1.5px), "
                "radial-gradient(circle at 68% 42%, rgba(89, 227, 255, 0.3) 0 1px, transparent 1.5px), "
                "radial-gradient(circle at 38% 78%, rgba(255, 255, 255, 0.2) 0 0.8px, transparent 1.3px), "
                "radial-gradient(circle at 88% 86%, rgba(200, 160, 255, 0.24) 0 1.2px, transparent 1.8px)",
                size="64px 64px, 64px 64px, 64px 64px, 64px 64px",
            ),
        ),
        TableTheme(
            "riverboat",
            "Riverboat mahogany",
            description="Paddle-steamer mahogany grain with polished brass and ivory chips.",
            accent=(240, 170, 50),
            accent_dim=(110, 76, 22),
            text=WHITE,
            alert=RED,
            chip=(230, 220, 190),
            chip_dark=(110, 100, 80),
            rim=(220, 160, 60),
            wood=(100, 50, 24),
            felt=(110, 54, 30),
            felt_dark=(56, 28, 16),
            css=_css(
                "#5a2e1c",
                "#45230f",
                "#26130a",
                "#d9a648",
                "#f0d08c",
                "#b0802a",
                "#33230a",
                "#24150e",
                "#1a0f0a",
                "#120a07",
                pattern="repeating-linear-gradient(92deg, rgba(0, 0, 0, 0.12) 0 2px, transparent 2px 9px, "
                "rgba(217, 166, 72, 0.06) 9px 10px, transparent 10px 17px)",
            ),
        ),
    )
}
CLASSIC = TABLE_THEMES["classic"]


def table_theme(tid: object) -> TableTheme:
    return TABLE_THEMES.get(str(tid), CLASSIC)


VIEWS = {
    "live": "Live table",
    "demo": "Demo loop",
    "betting": "Preview: betting",
    "locked": "Preview: no more bets",
    "spinning": "Preview: spin / roll",
    "result": "Preview: result",
    "board": "Preview: result board",
    "lobby": "Preview: join QR",
    "paused": "Preview: paused",
}


class CasinoSettings(AppSettings):
    view: str = Choice(
        "live",
        VIEWS,
        title="Panel view",
        group="Preview",
        description="Live plays the real table. The others are a self-playing demo or one frozen phase, "
        "to check the art (no credits move).",
    )
    table_theme: str = Choice(
        "classic",
        {t.id: t.name for t in TABLE_THEMES.values()},
        title="Table theme",
        group="Look",
        description="The table's colours on the panel, every phone and the studio. Card suits, roulette "
        "pockets and players' colours never change.",
    )


def _session(ctx: Any) -> CasinoSession:
    """The engine's casino session (shared by every casino app); a private one in bare previews."""
    shared = getattr(ctx, "shared", None)
    if callable(shared):
        return shared("casino", lambda section, save: CasinoSession(section, save))  # type: ignore[no-any-return]
    return CasinoSession()


def player_key(seat: int, payload: dict[str, Any]) -> str:
    """The wallet id for a phone: the server's `pid` (derived from its client id), else the seat."""
    pid = payload.get("pid")
    if isinstance(pid, str) and 4 <= len(pid) <= 40 and pid != HOST:
        return pid
    return f"seat{seat}"


@dataclass
class View:
    """What the panel draws: the table's public state plus the (still secret) outcome while it animates."""

    phase: str
    since: float = 0.0  # seconds in this phase
    since_lock: float | None = None  # seconds since betting closed (drives the spin / roll)
    ends_in: float | None = None  # betting countdown (None = waiting for the first chip)
    bet_span: float = 20.0
    result_span: float = 7.0
    outcome: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)  # summaries, newest last
    bettors: list[tuple[int, int, int]] = field(default_factory=list)  # colours of players with chips down
    #: everyone at the table while bets are open: (colour, 0 = no chips yet, 1 = chips down, 2 = pressed done)
    seats: list[tuple[tuple[int, int, int], int]] = field(default_factory=list)
    winners: list[tuple[int, int, int]] = field(default_factory=list)  # colours of this round's winners
    paused: bool = False
    nonce: int = 0
    lobby: bool = False


class CasinoApp(App):
    category = "casino"
    Game: ClassVar[type[CasinoGame]]
    Settings: ClassVar[type[AppSettings]] = CasinoSettings
    fps = 10.0
    #: seats: 1 = the host (studio), 2..9 = phones from the lobby QR
    max_players: ClassVar[int] = 9
    controls: ClassVar[tuple[str, ...]] = ("casino",)
    #: the result phase first shows the table (wheel / dice) for this long, then the results board
    table_seconds: ClassVar[float] = 3.4
    #: previews play the self-running demo: the last chips, no more bets, the spin / deal and the result
    preview_patch: ClassVar[dict[str, Any]] = {"view": "demo"}

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        game = cls.__dict__.get("Game")
        if game is not None and "preview_span" not in cls.__dict__:
            # demo_view(): 6 s of betting, LOCK_SECONDS + spin_seconds of spin / deal, 7 s of result
            cls.preview_span = (4.0, 2.0 + LOCK_SECONDS + game.spin_seconds + 5.5, 6.0)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self.session = _session(ctx)
        self.game = self.Game(self.session, self._rules())
        self.lobby_url: str | None = None
        self.seats: dict[int, dict[str, Any]] = {}  # lobby seats -> profile (QR corner dots)
        self._edges: tuple[str, dict[str, float]] | None = None

    # ------------------------------------------------------------- lifecycle
    def _rules(self) -> Any:
        return self.Game.Rules.model_validate(self.settings.model_dump())

    def on_settings(self) -> None:
        self.game.set_rules(self._rules())
        self._edges = None

    def on_start(self) -> None:
        self._live()

    def on_stop(self) -> None:
        self.session.release(self.game)

    def clock(self) -> float:
        return self.session.clock()

    @property
    def th(self) -> TableTheme:
        """The table theme (``table_theme`` setting): the panel chrome, the phones' and the studio's felt."""
        return table_theme(getattr(self.settings, "table_theme", "classic"))

    def _live(self) -> None:
        """This table is the one in play; a fresh table opens betting at once."""
        if self.session.game is not self.game:
            self.session.use(self.game)
        if self.game.phase == "idle" and self.game.round is None:
            self.game.open_betting()

    def lobby_waiting(self) -> bool:
        """The join QR shows while the lobby is open and nobody has sat down yet; once someone has, the panel shows
        the table and who has bet (the studio and the phones keep the QR for latecomers)."""
        g = self.game
        return (
            self.lobby_url is not None
            and not self.seats
            and g.phase in ("idle", "betting")
            and g.deadline is None
            and not self.session.paused
        )

    # --------------------------------------------------------------- actions
    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "casino":
            return self.casino(payload)
        if name == "seat":
            seat = int(payload.get("player", 0) or 0)
            if 2 <= seat <= self.max_players:
                if payload.get("joined", True):
                    self.seats[seat] = {k: payload.get(k) for k in ("name", "color", "avatar")}
                    self.session.join(
                        player_key(seat, payload),
                        seat,
                        name=str(payload.get("name") or f"P{seat}"),
                        color=str(payload.get("color") or ""),
                        avatar=str(payload.get("avatar") or ""),
                    )
                else:
                    self.seats.pop(seat, None)
                    self.session.leave(seat)
            return self.status()
        if name == "lobby":
            self.lobby_url = payload.get("url") or None
            if not self.lobby_url and not payload.get("keep_seats"):
                for seat in list(self.seats):
                    self.session.leave(seat)
                self.seats.clear()
            return self.status()
        if name == "input":  # the studio keyboard: A = start a round / spin now, B = pause
            k = str(payload.get("key", "")).lower()
            if int(payload.get("player", 1) or 1) == 1:
                self._live()
                g = self.game
                if k == "a":
                    if g.phase == "betting" and g.bets:
                        g.lock()
                    elif g.phase in ("idle", "result"):
                        g.open_betting()
                elif k == "b":
                    self.session.host_op("pause", {})
            return self.status()
        raise KeyError(name)

    def casino(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One casino op. ``player`` is the lobby seat for phones (set by the server, never trusted from the
        phone) or ``"host"`` (the studio, local only). Host ops raise on bad input (HTTP 400); player ops
        return ``{"ok": False, "error": ...}`` and the phone also gets the message as its private notice."""
        self._live()
        op = str(payload.get("op", ""))
        player = payload.get("player", "host")
        now = self.clock()
        self.game.tick(now)
        if player == "host" and op == "view":
            return self.host_view(bool(payload.get("spots")))
        if player == "host" and op in _host_ops():
            return {"ok": True, **self.session.host_op(op, payload)}
        if player == "host" and op in self.game.host_ops:
            return {"ok": True, **self.game.host_op(op, payload, now)}
        if player == "host":
            pid = self.session.ensure_host().pid
        elif type(player) is int:
            pid = self.session.pid_at(player) or ""
            if not pid:
                return {"ok": False, "error": "Take a seat first"}
        else:
            raise ValueError("player must be a seat number or 'host'")
        p = self.session.players[pid]
        if p.kicked:
            return {"ok": False, "error": "The host has taken you off the table"}
        if op == "seed":
            err = self.session.set_seed(pid, payload.get("client_seed"))
        elif op in ("start_round", "lock", "settings", "credits", "kick", "pause", "reset_session"):
            err = self.game._note(pid, "Only the host can do that")
        else:
            err = self.game.handle(pid, op, payload, now)
        return {"ok": err is None, "error": err}

    # ----------------------------------------------------------------- state
    def edges(self) -> dict[str, float]:
        key = repr(self.game.rules)
        if self._edges is None or self._edges[0] != key:
            self._edges = (key, {k: round(v, 5) for k, v in self.game.edges().items()})
        return self._edges[1]

    def status(self) -> dict[str, Any]:
        if self.settings.view != "live":
            return {
                "casino": True,
                "game": self.Game.id,
                "view": self.settings.view,
                "table_theme": self.th.public(),
            }
        self._live()
        now = self.clock()
        self.game.tick(now)
        st = {
            **self.session.public_state(),
            **self.game.public_state(now),
            "name": self.name,
            "edges": self.edges(),
            "lobby": self.lobby_waiting(),
            "max_players": self.max_players,
            "table_theme": self.th.public(),
        }
        st["history"] = [h for h in st["history"] if h.get("game") == self.Game.id][-10:]
        # the session's change counter: the studio gets this status from two feeds (the engine stream and the
        # host-view poll) and keeps the newest, so a late reply can never roll the chips on the table back
        st["rev"] = self.session.version
        st["clock"] = self.clock_anchors()
        return st

    def host_view(self, spots: bool = False) -> dict[str, Any]:
        """The studio's casino mode (host op ``view``, read-only): the fresh public status, the host seat's own
        private view (what a phone gets as ``private``; ``seated: False`` until the host first plays) and, on
        request, the table's spots and the avatar art. Never seats the host."""
        pid = HOST if HOST in self.session.players else None
        now = self.clock()
        out: dict[str, Any] = {
            "ok": True,
            "status": self.status(),
            "private": {
                "seated": True,
                **self.session.private_state(pid),
                **self.game.private_state(pid, now),
            }
            if pid
            else {"seated": False},
            # the leaderboard with each wallet's pid (credits for a player who left) and who is kicked
            "players": [
                {**row, "pid": w["pid"], "kicked": self.session.players[w["pid"]].kicked}
                for row, w in zip(
                    self.session.leaderboard(),
                    self.session.bank.leaderboard(list(self.session.players)),
                    strict=True,
                )
            ],
        }
        if spots:
            from ..gfx.avatars import AVATARS

            out["spots"] = self.game.spot_table()
            out["guide"] = guide(self.Game.id)  # the rulebook (casino/rulebook.py), read once per table
            out["themes"] = [t.public() for t in TABLE_THEMES.values()]  # the studio's theme swatches
            out["avatars"] = {k: {"name": v[0], "px": list(v[1])} for k, v in AVATARS.items()}
        return out

    # ------------------------------------------------------------------ the shared clock
    #: game timers published as wall-clock anchors (name in `clock` → attribute of the game)
    CLOCK_ANCHORS: ClassVar[dict[str, str]] = {
        "phase_at": "phase_at",
        "lock_at": "locked_at",
        "ends_at": "deadline",
        "reveal_at": "reveal_at",
        "next_at": "result_until",
        "turn_at": "turn_deadline",
        "stage_at": "stage_deadline",
        "call_at": "next_call_at",
    }

    def clock_anchors(self) -> dict[str, float | None]:
        """The round's timers as the engine's wall-clock times (``time.time()`` seconds): when this phase began,
        when betting closed / closes, when the outcome is revealed, when the next round opens, the turn deadline.
        Public (no outcome in them) and constant within a phase, so every device — panel, TV, phones, studio —
        counts down and flips at the same moment from one synced clock (docs/TV_VIEW.md §3). ``ends_in`` & co.
        stay for older pages."""
        off = time.time() - self.clock()
        cur = getattr(self, "_wall_off", None)
        if (
            cur is None or abs(off - cur) > 0.05
        ):  # one offset per run, so the anchors don't jitter between polls
            self._wall_off = cur = off
        g = self.game
        out: dict[str, float | None] = {}
        for key, attr in self.CLOCK_ANCHORS.items():
            v = getattr(g, attr, None)
            if isinstance(v, (int, float)):
                out[key] = round(v + cur, 3)
            elif key in ("lock_at", "ends_at", "reveal_at", "next_at"):
                out[key] = None
        return out

    # ------------------------------------------------------------------ TV
    #: the TV view may see the round's drawn outcome from the lock on (docs/TV_VIEW.md §3, "tv"): bets are frozen
    #: then, so it gives nobody an edge, and the commit–reveal proof is untouched (the seed is revealed at the
    #: result as before). Only for games where nobody decides anything after the lock — never turn games
    #: (blackjack, poker tables) or housie, and never in `status()` (phones).
    tv_reveal: ClassVar[bool] = False

    def tv_extra(self) -> dict[str, Any] | None:
        """TV-only data next to the public status: ``{"reveal": {...}}`` while a locked round plays out — the
        outcome the panel animates and its clock (``since_lock`` at server time ``at``), so a TV reproduces the
        panel's animation exactly. None while betting (and for previews)."""
        if self.settings.view != "live" or not self.tv_reveal:
            return None
        g = self.game
        if (
            g.locked_at is None
            or g.outcome is None
            or g.phase not in ("locked", "spinning", "dealing", "result")
        ):
            return None
        now = self.clock()
        return {
            "reveal": {
                "game": self.Game.id,
                "round": g.nonce,
                "outcome": g.outcome,
                "since_lock": round(max(0.0, now - g.locked_at), 4),
                "at": round(time.time(), 4),
                "paused": self.session.paused,
                "lock_s": LOCK_SECONDS,
                "spin_s": self.Game.spin_seconds,
                **self.tv_reveal_extra(g.outcome, g.nonce or 0),
            }
        }

    def tv_reveal_extra(self, outcome: dict[str, Any], nonce: int) -> dict[str, Any]:
        """Per game: the panel animation's cosmetic constants for this round (they come from a hash the TV
        can't recompute cheaply)."""
        return {}

    def private_status(self, seat: int) -> dict[str, Any] | None:
        pid = self.session.pid_at(seat)
        if pid is None:
            return {"seated": False}
        now = self.clock()
        return {"seated": True, **self.session.private_state(pid), **self.game.private_state(pid, now)}

    # ------------------------------------------------------------------ view
    def live_view(self, now: float) -> View:
        g, s = self.game, self.session
        hist = [h for h in s.history if h.get("game") == self.Game.id][-10:]
        res = g.result if g.phase == "result" else None
        colours = {p.pid: _rgb(p.color) for p in s.players.values()}
        return View(
            phase=g.phase,
            since=max(0.0, now - g.phase_at),
            since_lock=(now - g.locked_at) if g.locked_at is not None else None,
            ends_in=(g.deadline - now) if g.deadline is not None else None,
            bet_span=float(s.house.bet_seconds),
            result_span=float(s.house.result_seconds),
            outcome=g.outcome if g.phase in ("spinning", "dealing", "action", "result") else None,
            history=hist,
            bettors=[colours.get(p, WHITE) for p, b in g.bets.items() if b],
            seats=[
                (colours.get(pid, WHITE), 2 if pid in g.done else 1 if g.bets.get(pid) else 0)
                for pid, pl in sorted(s.players.items(), key=lambda kv: str(kv[1].seat))
                if pl.online and not pl.kicked
            ]
            if g.phase in ("idle", "betting")
            else [],
            winners=[colours.get(p, WHITE) for p, v in res.payouts.items() if v["net"] > 0] if res else [],
            paused=s.paused,
            nonce=g.nonce or 0,
            lobby=self.lobby_waiting(),
        )

    def demo_outcome(self, k: int) -> dict[str, Any]:
        """A real-looking outcome for demo round `k` (fixed seed: previews are deterministic)."""
        return self.game.draw(fair.Rng(b"deskdot-casino-demo", "demo", k))

    def demo_view(self, view: str, t: float) -> View:
        """A self-playing table (`demo`) or one frozen phase, as a pure function of t."""
        spin = LOCK_SECONDS + self.Game.spin_seconds
        res_s = 7.0
        bet_s = 6.0
        cycle = bet_s + spin + res_s
        k = int(t // cycle) if view == "demo" else 3
        hist = [self.game.summary(self.demo_outcome(i)) for i in range(k - 8, k)]
        colours = [(0, 200, 255), (255, 60, 90), (80, 255, 120), (255, 200, 0)]
        v = View(phase="betting", history=hist, bettors=colours, nonce=k, bet_span=10.0, result_span=res_s)
        v.seats = [(c, min(2, int(t * 0.8 + i) % 3)) for i, c in enumerate(colours)]
        if view == "demo":
            ph = t % cycle
            if ph < bet_s:
                v.phase, v.since, v.ends_in = "betting", ph, bet_s + 4 - ph
            elif ph < bet_s + spin:
                ls = ph - bet_s
                v.since_lock = ls
                v.phase = "locked" if ls < LOCK_SECONDS else self.Game.reveal_phase
                v.since = ls if ls < LOCK_SECONDS else ls - LOCK_SECONDS
            else:
                v.phase, v.since, v.since_lock = "result", ph - bet_s - spin, ph - bet_s
        elif view in ("betting", "paused", "lobby"):
            v.phase, v.since, v.ends_in = "betting", t, max(0.0, 9.6 - t % 10)
            v.paused = view == "paused"
            v.lobby = view == "lobby"
        elif view == "locked":
            v.phase, v.since, v.since_lock = "locked", t % LOCK_SECONDS, t % LOCK_SECONDS
        elif view == "spinning":
            ls = LOCK_SECONDS + (t % self.Game.spin_seconds)
            v.phase, v.since, v.since_lock = self.Game.reveal_phase, ls - LOCK_SECONDS, ls
        else:  # result / board
            base = 0.0 if view == "result" else self.table_seconds + 0.5
            v.phase, v.since = "result", base + (t % 3.0)
            v.since_lock = spin + v.since
        if v.phase in ("spinning", "dealing", "result"):
            v.outcome = self.demo_outcome(k)
        if v.phase == "result":
            v.winners = colours[:2]
            v.history = [*v.history[1:], self.game.summary(v.outcome)] if v.outcome else v.history
        if view == "lobby":
            self.lobby_url = self.lobby_url or "http://192.168.1.20:8765/p/K7QX"
        return v

    # ------------------------------------------------------------------ draw
    def render(self, f: Frame, t: float) -> None:
        view = self.settings.view
        if view == "live":
            self._live()
            now = self.clock()
            self.game.tick(now)
            v = self.live_view(now)
        else:
            now = t
            v = self.demo_view(view, t)
        self.on_frame(v, now)
        if v.lobby and self.lobby_url:
            draw_qr(f, self.lobby_url, self.seats, now)
            return
        if v.phase in ("idle", "betting"):
            self.draw_betting(f, v, now)
        elif v.phase == "locked":
            draw_no_more_bets(f, v.since, self.th)
        elif v.phase == "result" and v.since >= self.table_seconds:
            self.draw_board(f, v, now)
        else:
            self.draw_table(f, v, now)
        if v.paused:
            draw_paused(f, self.th)

    def on_frame(self, v: View, now: float) -> None:
        """Called every frame whatever is drawn (lobby QR, NO MORE BETS card…): keep continuous motion running."""

    def draw_table(self, f: Frame, v: View, now: float) -> None:
        """The game's own animation: spinning / dealing / action and the first part of the result."""
        raise NotImplementedError

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        """(label, background) of one history tile."""
        return str(summary.get("label", "?")), TONES.get(str(summary.get("tone")), TONES["white"])

    def hero_result(self, f: Frame, v: View, now: float) -> None:
        """The results board's hero (top half): the outcome as a big tile. Override for richer heroes."""
        if v.outcome is None:
            return
        lbl, bg = self.tile(self.game.summary(v.outcome))
        big_tile(f, lbl, bg, y=2)

    def draw_betting(self, f: Frame, v: View, now: float) -> None:
        """The betting board: header, countdown hero, timer bar, chips-down pips and the history strip."""
        th = self.th
        f.clear(INK)
        waiting = v.ends_in is None
        head = "BET NOW" if not waiting else "BETS"
        pulse = 0.5 + 0.5 * math.sin(now * 4)
        f.text_center(1, head, mix(th.accent_dim, th.accent, pulse) if waiting else th.accent)
        if waiting:
            draw_chip(f, 16, 13, now, th)
        else:
            left = max(0, math.ceil((v.ends_in or 0) - 1e-6))
            hurry = left <= 5
            col = th.alert if hurry and int(now * 4) % 2 == 0 else th.text
            f.text_center(8, str(left), col, font="big")
            frac = max(0.0, min(1.0, (v.ends_in or 0) / max(1.0, v.bet_span)))
            f.rect(1, 20, 30, 1, th.felt_dark)
            f.rect(1, 20, round(30 * frac), 1, th.alert if hurry else th.accent)
        if v.seats:
            seat_row(f, 22, v.seats, now)
        else:
            pips(f, 22, v.bettors)
        self.history_strip(f, 25, v.history)

    def draw_board(self, f: Frame, v: View, now: float) -> None:
        """Second half of the result: the outcome tile, who won, and the history strip."""
        f.clear(INK)
        self.hero_result(f, v, now)
        n = len(v.winners)
        if n:
            txt = "WIN" if n == 1 else f"{n} WIN"
            f.text_center(18, txt, self.th.accent)
            win_flash(f, now, v.winners, self.th)
        else:
            f.text_center(18, "HOUSE", MUTE)
        self.history_strip(f, 25, v.history)

    def history_strip(self, f: Frame, y: int, history: list[dict[str, Any]]) -> None:
        """Recent results as coloured tiles, newest on the left (outlined in gold)."""
        x = 1
        for i, h in enumerate(reversed(history)):
            lbl, bg = self.tile(h)
            w = measure(lbl) + 4
            if x + w - 1 > 30:
                break
            f.rect(x, y, w, 7, bg if i == 0 else tuple(max(46, round(c * 0.72)) for c in bg))
            f.text(x + 2, y + 1, lbl, WHITE if i == 0 else (205, 205, 205))
            if i == 0:
                f.rect(x, y - 1, w, 1, self.th.accent)
            x += w + 1


def _host_ops() -> tuple[str, ...]:
    from ..casino.session import HOST_OPS

    return HOST_OPS


def _rgb(c: str) -> tuple[int, int, int]:
    try:
        h = c.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError, AttributeError):
        return WHITE


# =========================================================================== shared art
def big_tile(f: Frame, label: str, bg: tuple[int, int, int], y: int = 2) -> None:
    """A result as a bold tile: big white digits on the outcome's colour (reads from across the room)."""
    w = measure(label, "big") + 8
    x = (32 - w) // 2
    f.rect(x, y, w, 14, bg)
    f.rect(x + 1, y + 14, w - 1, 1, scale(bg, 0.45))  # a 1 px drop shadow gives the tile weight
    f.text(x + 4, y + 2, label, WHITE, font="big")


def draw_chip(f: Frame, cx: int, cy: int, now: float, th: TableTheme = CLASSIC) -> None:
    """A casino chip (waiting for the first bet), bobbing gently."""
    dy = round(math.sin(now * 2.2) * 1.2)
    cy += dy
    f.circle(cx, cy, 6, th.chip)
    for k in range(8):  # edge spots
        a = k * math.pi / 4 + now * 0.8
        f.set(round(cx + 5 * math.cos(a)), round(cy + 5 * math.sin(a)), WHITE)
    f.circle(cx, cy, 3, th.chip_dark)
    f.circle(cx, cy, 2, th.accent)


def pips(f: Frame, y: int, colours: list[tuple[int, int, int]]) -> None:
    """One 2 px pip per player with chips down, in their colour, centred."""
    if not colours:
        return
    n = min(len(colours), 10)
    w = n * 3 - 1
    x = (32 - w) // 2
    for i, c in enumerate(colours[:n]):
        f.rect(x + 3 * i, y, 2, 1, c)


def seat_row(f: Frame, y: int, seats: list[tuple[tuple[int, int, int], int]], now: float) -> None:
    """Everyone at the table, centred, one 2 px pip each in their colour: dim = no chips yet, lit = chips down,
    a 2×2 block with a white cap = pressed done (ready). Waiting pips breathe so the row reads as "waiting on you"."""
    n = min(len(seats), 10)
    w = n * 3 - 1
    x = (32 - w) // 2
    breathe = 0.18 + 0.12 * (0.5 + 0.5 * math.sin(now * 3))
    for i, (c, state) in enumerate(seats[:n]):
        px = x + 3 * i
        if state == 0:
            f.rect(px, y, 2, 1, scale(c, breathe))
        elif state == 1:
            f.rect(px, y, 2, 1, c)
        else:
            f.rect(px, y, 2, 2, c)
            f.rect(px, y, 2, 1, WHITE)


def draw_no_more_bets(f: Frame, since: float, th: TableTheme = CLASSIC) -> None:
    """The lock beat: NO MORE BETS, in the theme's alert colour (classic: red), with a quick wipe in."""
    f.clear(INK)
    k = min(1.0, since / 0.25)
    col = scale(th.alert, 0.4 + 0.6 * k)
    f.rect(0, 7, 32, 1, scale(th.alert, 0.35 * k))
    f.rect(0, 24, 32, 1, scale(th.alert, 0.35 * k))
    f.text_center(10, "NO MORE", col)
    f.text_center(17, "BETS", col)


def draw_paused(f: Frame, th: TableTheme = CLASSIC) -> None:
    """The paused card: the table dimmed, PAUSED on a band (a felt band edged in the accent, for a theme)."""
    f.dim(0.3)
    if th is CLASSIC:
        f.rect(0, 12, 32, 9, (20, 20, 28))
    else:
        f.rect(0, 12, 32, 9, th.felt_dark)
        f.rect(0, 12, 32, 1, th.accent_dim)
        f.rect(0, 20, 32, 1, th.accent_dim)
    f.text_center(14, "PAUSED", th.accent)


def win_flash(f: Frame, now: float, colours: list[tuple[int, int, int]], th: TableTheme = CLASSIC) -> None:
    """Chasing bulbs around the edge: the theme's accent (classic: gold), every third bulb a winner's colour."""
    off = int(now * 14)
    for i, (x, y) in enumerate(PERIMETER):
        if (i + off) % 4 == 0:
            c = colours[(i // 4) % len(colours)] if colours and (i // 4) % 3 == 0 else th.accent
            f.set(x, y, c)
        elif (i + off) % 4 == 1:
            f.set(x, y, th.accent_dim)


def draw_qr(f: Frame, url: str, seats: dict[int, dict[str, Any]], now: float) -> None:
    """Full-screen join QR (dark modules on white), the joined players blinking in the corners."""
    from .qr import encode

    try:
        m = encode(url.encode(), "L")
    except ValueError:
        f.text_center(12, "URL TOO", WHITE)
        f.text_center(19, "LONG", WHITE)
        return
    n = len(m)
    off = (32 - n) // 2
    f.rect(0, 0, 32, 32, (235, 235, 235))
    for y, row in enumerate(m):
        for x, dark in enumerate(row):
            if dark:
                f.set(off + x, off + y, (0, 0, 0))
    if int(now * 2) % 2 == 0:
        corners = ((31, 0), (0, 31), (31, 31), (0, 0))
        for i, s in enumerate(sorted(seats)[:4]):
            f.set(*corners[i], _rgb(str(seats[s].get("color") or "#ffffff")))


def cosmetic(nonce: int, *parts: object) -> float:
    """A stable pseudo-random number in [0, 1) for animation flourishes (never for outcomes)."""
    h = hashlib.blake2b(f"{nonce}:{parts}".encode(), digest_size=4).digest()
    return int.from_bytes(h, "big") / 2**32
