"""Page themes: the casino's 21 table themes, worn by the studio, the phone shell, the launcher, the web app — and
by the panel's apps.

A page theme is chosen once (Settings → Display & colour → Page theme, ``POST /api/theme``) and stored on the
engine, so every device shows the same one. Every page theme *is* a casino table (``gfx/tables.py`` ``TABLE_THEMES``:
same ids, names and descriptions), so the studio, the casino and the website (scripts/site_theme.py) can't drift:

* **screen** — `screen_tokens()`: the studio's CSS tokens in dark (the table as the dark casino shows it: the room
  and its surfaces, lines lit by the accent, the casino's felt-tinted inks, the accent on keys and selections, the
  felt's motif as the page texture) and in light (the casino's porcelain salon, washed in the table's colour, the
  accent deepened until it reads AA). ``scripts/gen_page_themes.py`` writes them into the studio
  (``web/src/lib/pageThemes.gen.ts``); a test keeps the generated file current.
* **panel** — a `PanelPalette`: LED colours for apps that follow the theme (docs/APP_SDK.md § Page theme). The hero
  ``accent`` is the table's own LED accent (the colour the casino draws its chrome in); saturated, never near-white
  for accents, and every dark tone still lit on the panel (DISPLAY_DESIGN.md §3: ≥ 45 per channel at its brightest
  channel; the panel calibration's gamma crushes anything darker).

``cyber`` (Cyber grid) is the default. Ids from before 3.9 (the studio's own themes) map to the nearest table
(`LEGACY`), so a stored pick keeps working.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .color import RGB, mix, scale, to_hex
from .tables import TABLE_THEMES, TableTheme, contrast, mix_hex

Role = Literal["accent", "accent2", "accent3", "text", "mute", "soft", "track"]
ROLES: tuple[Role, ...] = ("accent", "accent2", "accent3", "text", "mute", "soft", "track")
DEFAULT_THEME = "cyber"


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


# ------------------------------------------------------------------ the panel: LED palettes per table
# accent = the table's own LED accent (what the casino draws its chrome in); accent2 / accent3 = the table's other
# colours (its chips, its felt) tuned to read as separate series on the LEDs
_LED: dict[str, tuple[RGB, RGB, RGB]] = {
    "classic": ((255, 200, 30), (230, 18, 36), (0, 200, 100)),
    "royal": ((255, 205, 50), (60, 120, 255), (140, 180, 255)),
    "crimson": ((235, 175, 60), (255, 30, 60), (255, 120, 140)),
    "midnight": ((190, 90, 255), (0, 220, 255), (255, 80, 200)),
    "strip": ((255, 50, 170), (0, 230, 255), (255, 200, 40)),
    "emerald": ((250, 215, 140), (0, 220, 130), (0, 200, 255)),
    "burgundy": ((245, 225, 185), (220, 30, 80), (255, 150, 60)),
    "noir": ((232, 214, 168), (170, 185, 215), (255, 140, 60)),
    "jade": ((255, 190, 40), (0, 210, 160), (255, 60, 50)),
    "deco": ((255, 195, 60), (255, 120, 40), (120, 200, 255)),
    "marigold": ((255, 150, 20), (255, 30, 140), (255, 220, 60)),
    "diwali": ((255, 180, 40), (255, 60, 40), (255, 90, 170)),
    "cyber": ((40, 240, 220), (255, 40, 200), (140, 255, 60)),
    "arcade": ((40, 255, 90), (255, 220, 0), (255, 60, 180)),
    "sakura": ((255, 120, 170), (120, 140, 255), (190, 120, 255)),
    "arctic": ((110, 210, 255), (60, 140, 255), (150, 255, 235)),
    "oasis": ((255, 200, 110), (0, 220, 210), (255, 120, 60)),
    "abyss": ((60, 240, 255), (0, 140, 255), (120, 255, 180)),
    "volcano": ((255, 100, 20), (255, 30, 20), (255, 200, 40)),
    "galaxy": ((80, 220, 255), (190, 90, 255), (255, 210, 120)),
    "riverboat": ((240, 170, 50), (230, 90, 40), (230, 220, 190)),
}

#: page-theme ids from before 3.9 (the studio's own set) → the nearest table
LEGACY: dict[str, str] = {
    "ember": "cyber",
    "graphite": "noir",
    "sunset": "volcano",
    "citrus": "arcade",
    "glacier": "arctic",
}


# ------------------------------------------------------------------ the screen: CSS tokens per mode
def _rgba(h: str, a: float) -> str:
    x = h.lstrip("#")
    return f"rgba({int(x[0:2], 16)}, {int(x[2:4], 16)}, {int(x[4:6], 16)}, {a:g})"


def _until(c: str, to: str, bgs: tuple[str, ...], ratio: float = 4.5) -> str:
    """Move ``c`` toward ``to`` in 4 % steps until it reaches ``ratio`` against every colour in ``bgs``."""
    for k in range(26):
        x = mix_hex(c, to, k * 0.04)
        if all(contrast(x, bg) >= ratio for bg in bgs):
            return x
    return mix_hex(c, to, 1)


def _alphas(p: str, f: Callable[[int, int, int, float], str]) -> str:
    """Every ``rgba()`` colour in a gradient motif, rewritten by ``f(r, g, b, a)``."""
    return re.sub(
        r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)",
        lambda m: f(int(m[1]), int(m[2]), int(m[3]), float(m[4])),
        p,
    )


def _channels(h: str) -> list[int]:
    x = h.lstrip("#")
    return [int(x[i : i + 2], 16) for i in (0, 2, 4)]


def _pale(accent: str) -> bool:
    """A pale accent (ivory, champagne, ice) can't be a key on porcelain (casino state.ts lightSwitches)."""
    a = _channels(accent)
    return (max(a) - min(a)) / max(max(a), 1) < 0.36


def _tint(c: dict[str, str]) -> str:
    """The colour the light room is washed with: the felt, or the accent when the felt is a graphite / black."""
    f = _channels(c["felt"])
    return c["accent"] if max(f) - min(f) < 40 else c["felt"]


DOTS_DARK = "radial-gradient(circle at 1px 1px, rgba(255, 255, 255, 0.035) 1px, transparent 0)"

#: tokens that must read as text (AA, 4.5:1) on every page surface, per mode (tests/test_page_themes.py)
TEXT_TOKENS = ("color-ink-1", "color-ink-2", "color-ink-3", "color-ember", "color-gold-text")
SURFACES = ("color-chassis-0", "color-chassis-1", "color-chassis-2", "color-chassis-3")


def _metal(m: str, m2: str, light: bool) -> dict[str, str]:
    shade = mix_hex(m, "#000000", 0.25 if light else 0.32)
    a, b = (0.5, 0.85) if light else (0.32, 0.32)
    return {
        "m-gold-leaf": f"linear-gradient(135deg, {mix_hex(m2, '#ffffff', 0.45)} 0%, {m} 34%, {shade} 58%, "
        f"{m2} 80%, {m} 100%)",
        "m-brass": f"linear-gradient(180deg, {m2}, {mix_hex(m, '#000000', 0.2)})",
        "m-rule-gold": f"linear-gradient(90deg, transparent, {_rgba(m, a)} 22%, {_rgba(m2, b)} 50%, "
        f"{_rgba(m, a)} 78%, transparent)",
    }


def _dark(c: dict[str, str]) -> dict[str, str]:
    """The studio in the table's dark casino (casino.css html[data-cz] and the wings): the room and its surfaces, the
    felt-tinted inks, lines lit by the accent, the felt's glow and motif on the page, the accent on the glass's rim."""
    acc, hi, deep, felt, text = c["accent"], c["accent_hi"], c["accent_deep"], c["felt"], c["felt_ink"]
    bg, s1, s2, s3, s4 = c["bg"], c["surface"], c["surface2"], c["surface3"], c["surface4"]
    surf = (bg, s1, s2, s3)
    ember = acc if all(contrast(acc, s) >= 4.5 for s in surf) else _until(c["accent_text"], hi, surf)
    ink = c["ink"]
    on = ink if contrast(ink, acc) >= 4.5 else ("#000000" if contrast("#000000", acc) >= 4.5 else "#ffffff")
    pat = c.get("pattern") or ""
    has_pat = pat not in ("", "none")
    # the felt's motif on the page, a touch stronger than on the felt (the page is the darker room)
    motif = _alphas(pat, lambda r, g, b, a: f"rgba({r}, {g}, {b}, {round(min(0.3, a * 1.25), 4):g})")
    size = c.get("pattern_size") or "auto"
    line, line2 = mix_hex(s2, acc, 0.14), mix_hex(s3, acc, 0.24)
    return {
        "color-chassis-0": bg,
        "color-chassis-1": s1,
        "color-chassis-2": s2,
        "color-chassis-3": s3,
        "color-chassis-4": s4,
        "color-line": line,
        "color-line-2": line2,
        "color-ink-1": _until(mix_hex(text, hi, 0.2), "#ffffff", surf, 7),
        "color-ink-2": _until(mix_hex(text, s3, 0.2), "#ffffff", surf),
        "color-ink-3": _until(mix_hex(text, s3, 0.36), "#ffffff", surf),
        "color-ink-4": mix_hex(text, s3, 0.6),
        "color-ember": ember,
        "color-ember-2": hi,
        "color-ember-deep": deep,
        "color-ember-line": mix_hex(s2, acc, 0.34),
        "color-on-ember": on,
        "color-gold": acc,
        "color-gold-2": hi,
        "color-gold-text": _until(c["accent_text"], "#ffffff", surf),
        "m-glass": mix_hex(bg, s1, 0.6),
        "m-glass-line": _rgba(acc, 0.1),
        "m-key-floor": mix_hex(bg, "#000000", 0.4),
        "m-key-hover": mix_hex(s4, text, 0.12),
        "m-page-glow": _rgba(felt, 0.24),
        "m-wash-a": _rgba(felt, 0.24),
        "m-wash-b": _rgba(acc, 0.03),
        "m-texture": f"{motif}, {DOTS_DARK}" if has_pat else DOTS_DARK,
        "m-texture-size": f"{size}, 22px 22px" if has_pat else "22px 22px",
        "m-champagne": mix_hex(acc, bg, 0.84),
        **_metal(acc, hi, False),
        "lg-edge": _rgba(acc, 0.12),
        "lg-edge-strong": _rgba(acc, 0.24),
        "lg-rim-a": _rgba(mix_hex("#ffffff", hi, 0.35), 0.36),
        # the casino's wings (casino.css .cz-wing) for the studio's panels: their gradient, the accent for lit edges
        # and glows, and the felt's motif faint inside (index.css § TABLE ROOM)
        "pt-wing": c["wing"],
        "pt-wing-2": c["wing2"],
        "pt-wing-3": c["wing3"],
        "pt-felt": felt,
        "pt-acc-rgb": c["accent_rgb"],
        "pt-motif": _alphas(pat, lambda r, g, b, a: f"rgba({r}, {g}, {b}, {round(a * 0.5, 4):g})")
        if has_pat
        else "none",
        "pt-motif-size": size if has_pat else "auto",
        # the plain pages' short names (launcher, controller, the web app's landing card)
        "ember": ember,
        "ember2": hi,
        "on-ember": on,
        "rose": ember,
        "tangerine": hi,
        "gold": acc,
        "c0": bg,
        "c1": s1,
        "c2": s2,
        "c3": s3,
        "c4": s4,
        "line": line,
        "line2": line2,
        "landing-bg": f"radial-gradient(70% 60% at 50% 0%, {_rgba(felt, 0.5)}, transparent 70%), {_rgba(bg, 0.95)}",
        "card-wash": _rgba(deep, 0.33),
        "tan-line": _rgba(hi, 0.27),
        "tan-fill": _rgba(hi, 0.06),
        "tan-sel": _rgba(hi, 0.33),
    }


def _light(c: dict[str, str]) -> dict[str, str]:
    """The casino's porcelain salon (casino.css :root[data-theme="light"][data-cz]): porcelain washed in the table's
    colour, the accent deepened to bronze where it is text, gold leaf in the accent, the motif inked faintly."""
    acc, hi, felt = c["accent"], c["accent_hi"], c["felt"]
    tint = _tint(c)
    room = mix_hex(felt, tint, 0.3)
    bg, s1, s2 = mix_hex("#f2ede4", room, 0.13), mix_hex("#fcfbf8", room, 0.05), "#ffffff"
    s3, s4 = mix_hex("#f1ede5", room, 0.08), mix_hex("#e7e2d8", room, 0.08)
    surf = (bg, s1, s2, s3)
    base = mix_hex(felt, "#000000", 0.28) if _pale(acc) else mix_hex("#1a1206", acc, 0.4)
    ember = _until(base, "#000000", (*surf, "#ffffff"), 4.6)  # text on porcelain, and white lettering on it
    ember2 = mix_hex(ember, acc, 0.3)
    metal = mix_hex(acc, "#4a4438", 0.26)
    pat = c.get("pattern") or ""
    has_pat = pat not in ("", "none")
    ink = mix_hex(tint, "#000000", 0.2)
    motif = _alphas(pat, lambda r, g, b, a: _rgba(ink, round(min(0.08, a * 1.2), 4)))
    dots = f"radial-gradient(circle at 1px 1px, {_rgba(room, 0.3)} 1px, transparent 0)"
    size = c.get("pattern_size") or "auto"
    line = mix_hex(mix_hex("#e7e1d6", room, 0.08), acc, 0.18)
    line2 = mix_hex(mix_hex("#d8d0c2", room, 0.1), acc, 0.26)
    return {
        "color-chassis-0": bg,
        "color-chassis-1": s1,
        "color-chassis-2": s2,
        "color-chassis-3": s3,
        "color-chassis-4": s4,
        "color-line": line,
        "color-line-2": line2,
        "color-ink-1": _until("#1c1a22", "#000000", surf, 7),
        "color-ink-2": _until("#4a4652", "#000000", surf),
        "color-ink-3": _until("#6b6673", "#000000", surf),
        "color-ink-4": "#a49ea8",
        "color-ember": ember,
        "color-ember-2": ember2,
        "color-ember-deep": mix_hex("#ffffff", acc, 0.14),
        "color-ember-line": mix_hex("#e7e1d6", ember, 0.45),
        "color-on-ember": "#ffffff",
        "color-gold": metal,
        "color-gold-2": mix_hex(acc, "#ffffff", 0.4),
        "color-gold-text": _until(acc, "#2a1c08", surf),
        "m-glass": s1,
        "m-glass-line": _rgba(mix_hex(room, "#40301a", 0.5), 0.1),
        "m-key-floor": mix_hex("#ddd5c8", room, 0.1),
        "m-key-hover": mix_hex("#c5bcad", room, 0.1),
        "m-page-glow": _rgba(tint, 0.05),
        "m-wash-a": _rgba(tint, 0.24),
        "m-wash-b": _rgba(acc, 0.2),
        "m-texture": f"{motif}, {dots}" if has_pat else dots,
        "m-texture-size": f"{size}, 22px 22px" if has_pat else "22px 22px",
        "m-champagne": mix_hex(hi, "#ffffff", 0.7),
        **_metal(metal, mix_hex(acc, "#ffffff", 0.4), True),
        "lg-edge": _rgba(mix_hex(room, "#40301a", 0.6), 0.14),
        "lg-edge-strong": _rgba(mix_hex(metal, "#000000", 0.2), 0.3),
        "lg-rim-a": "#ffffff",
        "pt-wing": s1,
        "pt-wing-2": s1,
        "pt-wing-3": s1,
        "pt-felt": tint,
        "pt-acc-rgb": ", ".join(str(v) for v in _channels(ember)),
        "pt-motif": motif if has_pat else "none",
        "pt-motif-size": size if has_pat else "auto",
        "ember": ember,
        "ember2": ember2,
        "on-ember": "#ffffff",
        "rose": ember,
        "tangerine": ember2,
        "gold": metal,
        "c0": bg,
        "c1": s1,
        "c2": s2,
        "c3": s3,
        "c4": s4,
        "line": line,
        "line2": line2,
        "landing-bg": f"radial-gradient(70% 60% at 50% 0%, {_rgba(tint, 0.12)}, transparent 70%), {_rgba(bg, 0.94)}",
        "card-wash": _rgba(mix_hex(ember, "#ffffff", 0.9), 0.6),
        "tan-line": _rgba(ember, 0.2),
        "tan-fill": _rgba(ember, 0.05),
        "tan-sel": _rgba(ember, 0.27),
    }


def screen_tokens(table: TableTheme) -> dict[str, dict[str, str]]:
    """The studio's CSS custom properties (names without the leading ``--``) for one table, in dark and in light."""
    return {"dark": _dark(table.css), "light": _light(table.css)}


# ------------------------------------------------------------------ the themes
@dataclass(frozen=True)
class PageTheme:
    id: str
    name: str
    description: str
    panel: PanelPalette
    table: TableTheme
    origin: Literal["table"] = "table"

    def screen(self) -> dict[str, str]:
        """The swatch seeds: the felt, the accent, the room and the motif (the theme picker, the API)."""
        c = self.table.css
        return {
            "felt": c["felt"],
            "accent": c["accent"],
            "accent_hi": c["accent_hi"],
            "bg": c["bg"],
            "pattern": c.get("pattern") or "",
            "pattern_size": c.get("pattern_size") or "",
        }

    def tokens(self) -> dict[str, dict[str, str]]:
        return screen_tokens(self.table)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "origin": self.origin,
            "screen": self.screen(),
            "panel": self.panel.public(),
        }


PAGE_THEMES: dict[str, PageTheme] = {
    t.id: PageTheme(t.id, t.name, t.description, palette(*_LED[t.id]), t) for t in TABLE_THEMES.values()
}
DEFAULT = PAGE_THEMES[DEFAULT_THEME]


def theme_id(tid: object) -> str:
    """A stored id as a current theme id: a table id as is, a pre-3.9 page-theme id mapped (`LEGACY`), else the
    default (stored ids may be stale)."""
    s = str(tid)
    s = LEGACY.get(s, s)
    return s if s in PAGE_THEMES else DEFAULT_THEME


def page_theme(tid: object) -> PageTheme:
    """The theme with this id (old ids mapped to their table), else the default."""
    return PAGE_THEMES[theme_id(tid)]
