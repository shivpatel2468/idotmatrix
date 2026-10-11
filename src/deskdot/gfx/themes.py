"""Page themes: one look for the studio, the phone shell, the launcher and the web app — and the panel's apps.

A page theme is chosen once (Settings → Display & colour → Page theme, ``POST /api/theme``) and stored on the
engine, so every device shows the same one. It has two halves:

* **screen** — the seeds the studio derives its CSS from (``web/src/lib/pageTheme.ts`` mirrors this table; a test
  keeps them in sync): ``accent`` (the accent on dark surfaces), ``accent_light`` (the accent on ivory, AA as text;
  empty = derived), ``metal`` (the second, "metal" accent: gold, silver, brass…), ``tint`` (the hue the chassis and
  the washes lean to; empty = untinted) and ``pattern`` / ``pattern_size`` (the page's texture motif: gradients only).
* **panel** — a `PanelPalette`: LED colours for apps that follow the theme (docs/APP_SDK.md § Page theme). Saturated,
  never near-white for accents, and every dark tone still lit on the panel (DISPLAY_DESIGN.md §3: ≥ 45 per channel
  at its brightest channel; the panel calibration's gamma crushes anything darker).

``ember`` (DeskDot) is the default and is *exactly* the original look: apps that follow the theme keep their own
colours under it. The casino has its own per-table themes (apps/_casino.py ``TABLE_THEMES``); page themes never touch
a casino table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .color import RGB, mix, scale, to_hex

Role = Literal["accent", "accent2", "accent3", "text", "mute", "soft", "track"]
ROLES: tuple[Role, ...] = ("accent", "accent2", "accent3", "text", "mute", "soft", "track")
DEFAULT_THEME = "ember"


@dataclass(frozen=True)
class PanelPalette:
    """LED colours of a page theme, by role. Apps ask for a role (`App.themed`) or map a colour setting to one
    (`App.theme_colors`).

    accent   the hero colour (rings, highlights, the primary value's accent)
    accent2  a second accent (second series, secondary highlights)
    accent3  a third accent (third series, small details)
    text     primary text (white, faintly tinted by the theme)
    mute     secondary text / labels (a tinted grey that still reads)
    soft     the accent dimmed: captions, inactive marks, lit tracks
    track    dark structure: bar tracks, dividers (the darkest tone that stays lit on the panel)
    """

    accent: RGB
    accent2: RGB
    accent3: RGB
    text: RGB
    mute: RGB
    soft: RGB
    track: RGB

    def role(self, name: str) -> RGB:
        return getattr(self, name) if name in ROLES else self.accent  # type: ignore[no-any-return]

    def public(self) -> dict[str, str]:
        return {r: to_hex(getattr(self, r)) for r in ROLES}


def _lift(c: RGB, floor: int) -> RGB:
    """Scale ``c`` up until its brightest channel reaches ``floor`` (keeps the hue; DISPLAY_DESIGN §3)."""
    m = max(c)
    return c if m >= floor or m == 0 else scale(c, floor / m)


def palette(
    accent: RGB, accent2: RGB, accent3: RGB, *, text: RGB | None = None, mute: RGB | None = None
) -> PanelPalette:
    """Derive the quiet roles from the accent so every theme follows the same LED rules."""
    return PanelPalette(
        accent=accent,
        accent2=accent2,
        accent3=accent3,
        text=text or mix((255, 255, 255), accent, 0.12),
        mute=mute or mix((140, 140, 160), accent, 0.3),
        soft=_lift(scale(accent, 0.45), 100),
        track=_lift(scale(accent, 0.2), 52),
    )


@dataclass(frozen=True)
class PageTheme:
    id: str
    name: str
    description: str
    panel: PanelPalette
    accent: str  # the accent on dark surfaces
    metal: str  # the second ("metal") accent on dark surfaces
    tint: str = ""  # the chassis / wash hue ("" = untinted, the original graphite and porcelain)
    accent_light: str = ""  # the accent on ivory ("" = derived: deepened until it reads AA)
    pattern: str = ""  # the page texture: gradients only, low alpha ("" = the dot grid)
    pattern_size: str = ""
    origin: Literal["studio", "table"] = "studio"  # a studio original, or adapted from a casino table concept

    def screen(self) -> dict[str, str]:
        return {
            "accent": self.accent,
            "accent_light": self.accent_light,
            "metal": self.metal,
            "tint": self.tint,
            "pattern": self.pattern,
            "pattern_size": self.pattern_size,
        }

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "origin": self.origin,
            "screen": self.screen(),
            "panel": self.panel.public(),
        }


_T: list[PageTheme] = [
    PageTheme(
        "ember",
        "DeskDot",
        "The original: graphite and ember in the dark, porcelain and rose in the light, gold for metal.",
        PanelPalette(
            accent=(255, 72, 24),
            accent2=(255, 170, 0),
            accent3=(0, 220, 255),
            text=(255, 255, 255),
            mute=(140, 140, 160),
            soft=(140, 40, 13),
            track=(56, 16, 5),
        ),
        accent="#ff4818",
        accent_light="#b81f4b",
        metal="#ffcc33",
    ),
    PageTheme(
        "graphite",
        "Graphite & ice",
        "Brushed steel and ice blue: a calm, almost monochrome instrument.",
        palette((110, 190, 255), (60, 110, 255), (255, 190, 110)),
        accent="#8ab8ff",
        accent_light="#2c5a96",
        metal="#c3ccd8",
        tint="#56657a",
        pattern="repeating-linear-gradient(0deg, rgba(160, 180, 210, 0.035) 0 1px, transparent 1px 4px)",
        pattern_size="auto",
    ),
    PageTheme(
        "sunset",
        "Sunset coral",
        "Coral light sliding into violet dusk, with a warm amber rim.",
        palette((255, 90, 60), (190, 60, 255), (255, 190, 40)),
        accent="#ff7a59",
        metal="#c58bff",
        tint="#5a2a48",
        pattern="radial-gradient(circle at 1px 1px, rgba(255, 140, 110, 0.05) 1px, transparent 0)",
        pattern_size="18px 18px",
    ),
    PageTheme(
        "citrus",
        "Citrus",
        "Lime zest and lemon on a dark leaf: bright, fresh and loud.",
        palette((150, 255, 0), (255, 214, 0), (0, 220, 255)),
        accent="#b6f23a",
        metal="#ffd84a",
        tint="#34461a",
        pattern="repeating-linear-gradient(60deg, rgba(182, 242, 58, 0.03) 0 1px, transparent 1px 12px)",
        pattern_size="auto",
    ),
    PageTheme(
        "royal",
        "Royal blue",
        "Deep palace blue under a fine gold lattice.",
        palette((60, 120, 255), (255, 205, 50), (140, 180, 255)),
        accent="#6b97ff",
        metal="#ffcc33",
        tint="#1b4aa8",
        pattern="repeating-linear-gradient(45deg, rgba(255, 204, 51, 0.045) 0 1px, transparent 1px 22px), "
        "repeating-linear-gradient(-45deg, rgba(255, 204, 51, 0.045) 0 1px, transparent 1px 22px)",
        pattern_size="auto, auto",
        origin="table",
    ),
    PageTheme(
        "crimson",
        "Crimson velvet",
        "Red velvet and brass: an old-world salon.",
        palette((255, 30, 60), (235, 175, 60), (255, 120, 140)),
        accent="#ff4d6d",
        metal="#e8b04a",
        tint="#8c1a2e",
        pattern="radial-gradient(circle at 50% 50%, rgba(232, 176, 74, 0.05) 0 2px, transparent 3px)",
        pattern_size="26px 26px",
        origin="table",
    ),
    PageTheme(
        "midnight",
        "Midnight neon",
        "After-hours violet with faint neon scan lines and a cyan glint.",
        palette((190, 90, 255), (0, 220, 255), (255, 80, 200)),
        accent="#c77dff",
        metal="#59e3ff",
        tint="#3a1d72",
        pattern="repeating-linear-gradient(0deg, rgba(199, 125, 255, 0.035) 0 1px, transparent 1px 5px)",
        pattern_size="auto",
        origin="table",
    ),
    PageTheme(
        "strip",
        "Neon strip",
        "Hot-pink boulevard neon with cyan sparks.",
        palette((255, 50, 170), (0, 230, 255), (255, 200, 40)),
        accent="#ff4fb8",
        metal="#3fe0ff",
        tint="#5a1260",
        pattern="repeating-linear-gradient(135deg, rgba(255, 63, 176, 0.035) 0 2px, transparent 2px 16px)",
        pattern_size="auto",
        origin="table",
    ),
    PageTheme(
        "emerald",
        "Emerald & champagne",
        "Dark emerald with champagne trim: the high-limit room.",
        palette((0, 220, 130), (250, 215, 140), (0, 200, 255)),
        accent="#2fd59a",
        metal="#f1dca0",
        tint="#0b5a43",
        pattern="repeating-linear-gradient(45deg, rgba(241, 220, 160, 0.03) 0 10px, transparent 10px 20px)",
        pattern_size="auto",
        origin="table",
    ),
    PageTheme(
        "noir",
        "Riviera noir",
        "Black lacquer, silver rails and champagne pinstripes.",
        palette((232, 214, 168), (170, 185, 215), (255, 140, 60)),
        accent="#e8d7a8",
        accent_light="#6e5a2a",
        metal="#c0c6d0",
        tint="#3a3c44",
        pattern="repeating-linear-gradient(90deg, rgba(232, 215, 168, 0.03) 0 1px, transparent 1px 18px)",
        pattern_size="auto",
        origin="table",
    ),
    PageTheme(
        "jade",
        "Imperial jade",
        "Deep jade with red-gold trim and rolling clouds.",
        palette((0, 210, 160), (255, 190, 40), (255, 60, 50)),
        accent="#2fd3b0",
        metal="#f2c14e",
        tint="#0c6655",
        pattern="radial-gradient(circle at 50% 100%, transparent 9px, rgba(242, 193, 78, 0.045) 10px, transparent 11px)",
        pattern_size="24px 14px",
        origin="table",
    ),
    PageTheme(
        "deco",
        "Gilded deco",
        "Jazz-age black lacquer with gold sunburst fans.",
        palette((255, 195, 60), (255, 120, 40), (120, 200, 255)),
        accent="#e9c46a",
        metal="#e9c46a",
        tint="#4a3f2a",
        pattern="repeating-conic-gradient(from 0deg at 50% 100%, rgba(233, 196, 106, 0.04) 0 6deg, transparent 6deg 18deg)",
        pattern_size="48px 24px",
        origin="table",
    ),
    PageTheme(
        "marigold",
        "Marigold masala",
        "Saffron gold on magenta silk with a scatter of paisley buds.",
        palette((255, 150, 20), (255, 30, 140), (255, 220, 60)),
        accent="#ffa21f",
        metal="#ff5fae",
        tint="#7c1452",
        pattern="radial-gradient(ellipse 3px 5px at 50% 50%, rgba(255, 162, 31, 0.06) 0 100%, transparent 100%)",
        pattern_size="20px 20px",
        origin="table",
    ),
    PageTheme(
        "cyber",
        "Cyber grid",
        "Graphite traced with a teal circuit grid and magenta nodes.",
        palette((40, 240, 220), (255, 40, 200), (140, 255, 60)),
        accent="#2ff3e0",
        metal="#ff4fd8",
        tint="#1f3a44",
        pattern="linear-gradient(rgba(47, 243, 224, 0.035) 1px, transparent 1px), "
        "linear-gradient(90deg, rgba(47, 243, 224, 0.035) 1px, transparent 1px)",
        pattern_size="24px 24px, 24px 24px",
        origin="table",
    ),
    PageTheme(
        "arcade",
        "Pixel arcade",
        "Cabinet black on a neon-green pixel grid with coin-yellow trim.",
        palette((40, 255, 90), (255, 220, 0), (255, 60, 180)),
        accent="#39ff6a",
        metal="#ffd60a",
        tint="#1e3a26",
        pattern="linear-gradient(rgba(57, 255, 106, 0.03) 1px, transparent 1px), "
        "linear-gradient(90deg, rgba(57, 255, 106, 0.03) 1px, transparent 1px)",
        pattern_size="8px 8px, 8px 8px",
        origin="table",
    ),
    PageTheme(
        "sakura",
        "Sakura night",
        "Indigo dusk under drifting blossom-pink petals.",
        palette((255, 110, 170), (120, 140, 255), (190, 120, 255)),
        accent="#ffa3c7",
        metal="#b9c3ff",
        tint="#26306e",
        pattern="radial-gradient(ellipse 2px 3px at 50% 50%, rgba(255, 163, 199, 0.07) 0 100%, transparent 100%)",
        pattern_size="28px 28px",
        origin="table",
    ),
    PageTheme(
        "glacier",
        "Glacier",
        "Glacier blue and silver frost, like a desk carved in ice.",
        palette((110, 210, 255), (60, 140, 255), (150, 255, 235)),
        accent="#8fd8ff",
        metal="#d8ecf6",
        tint="#164e6c",
        pattern="repeating-linear-gradient(60deg, rgba(216, 236, 246, 0.03) 0 1px, transparent 1px 14px), "
        "repeating-linear-gradient(-60deg, rgba(216, 236, 246, 0.03) 0 1px, transparent 1px 14px)",
        pattern_size="auto, auto",
        origin="table",
    ),
    PageTheme(
        "oasis",
        "Desert oasis",
        "Turquoise pool framed in sand gold and star tiles.",
        palette((0, 220, 210), (255, 200, 110), (255, 120, 60)),
        accent="#3fe0d6",
        metal="#f0cf8e",
        tint="#0d5c63",
        pattern="repeating-linear-gradient(45deg, rgba(240, 207, 142, 0.035) 0 1px, transparent 1px 16px), "
        "repeating-linear-gradient(-45deg, rgba(240, 207, 142, 0.035) 0 1px, transparent 1px 16px)",
        pattern_size="auto, auto",
        origin="table",
    ),
    PageTheme(
        "abyss",
        "Ocean abyss",
        "Deep-sea teal with bioluminescent aqua sparks.",
        palette((60, 240, 255), (0, 140, 255), (120, 255, 180)),
        accent="#5cf2ff",
        metal="#8af5d0",
        tint="#08424f",
        pattern="radial-gradient(circle at 50% 50%, rgba(92, 242, 255, 0.07) 0 1px, transparent 2px)",
        pattern_size="30px 30px",
        origin="table",
    ),
    PageTheme(
        "volcano",
        "Volcano",
        "Charcoal basalt split by glowing lava seams.",
        palette((255, 100, 20), (255, 30, 20), (255, 200, 40)),
        accent="#ff6a1f",
        metal="#ffb347",
        tint="#4a2a1c",
        pattern="repeating-linear-gradient(120deg, rgba(255, 106, 31, 0.035) 0 1px, transparent 1px 26px)",
        pattern_size="auto",
        origin="table",
    ),
    PageTheme(
        "galaxy",
        "Galaxy",
        "Deep-space purple scattered with a cyan starfield.",
        palette((80, 220, 255), (190, 90, 255), (255, 210, 120)),
        accent="#59e3ff",
        metal="#c9a7ff",
        tint="#2a1a55",
        pattern="radial-gradient(circle at 30% 40%, rgba(89, 227, 255, 0.12) 0 1px, transparent 1.5px), "
        "radial-gradient(circle at 70% 80%, rgba(201, 167, 255, 0.09) 0 1px, transparent 1.5px)",
        pattern_size="37px 37px, 53px 53px",
        origin="table",
    ),
]

PAGE_THEMES: dict[str, PageTheme] = {t.id: t for t in _T}
DEFAULT = PAGE_THEMES[DEFAULT_THEME]


def page_theme(tid: object) -> PageTheme:
    """The theme with this id, else the default (stored ids may be stale)."""
    return PAGE_THEMES.get(str(tid), DEFAULT)
