"""The casino's table themes: one look per table, for the panel (LED colours) and for every screen (CSS tokens).

The data lives here, in ``gfx`` (no app imports), so the page themes (``gfx/themes.py``) are built from it: the
studio, the web app and the website all wear these 21 tables (docs/STUDIO_UI.md § Page themes). ``apps/_casino.py``
re-exports everything for the casino apps; docs/CASINO.md §11 describes the themes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

GOLD = (255, 200, 30)
GOLD_DIM = (120, 90, 14)
FELT = (0, 120, 60)
RED = (230, 18, 36)
WHITE = (240, 240, 240)
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
