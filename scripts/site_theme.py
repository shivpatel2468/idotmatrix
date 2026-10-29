"""Page themes for idotmatrix.com: the studio's 21 page themes (src/deskdot/gfx/themes.py, mirrored by
web/src/lib/pageTheme.ts) re-derived for the website's own token names (site/styles.css).

The colour maths is a port of `derive()` in web/src/lib/pageTheme.ts: a theme is only seeds (an accent for dark, an
optional accent for ivory, a metal, a tint, a texture); every other colour is derived and AA-checked here, in light
and dark. The default theme ("ember") emits nothing: site/styles.css is its look.

build_site_pages.py writes the result between the `/* gen:themes */` markers in site/styles.css, and the theme menu's
swatches from `menu_html()`. The pick is stored like the studio stores it (localStorage `deskdot.theme`,
`deskdot.pageTheme`), so the web app at /app/ opens in the same theme.
"""

from __future__ import annotations

import html
from typing import Any

DEFAULT = "ember"  # the studio's default: site/styles.css's :root is its look, so it emits no block
# The website's own default for first-time visitors (the studio and the web app keep "ember"): a calm, retro look —
# a deep teal-navy night or a warm paper day, softer layers, the logo's LED rose and gold as the accents with a
# sunset orange and a teal as their only companions, gentle glows. Hand-tuned (not derived from seeds) and AA-checked
# by retro_contrast() / tests/test_site_data.py. Visitors who picked a theme keep it (localStorage deskdot.pageTheme).
SITE_DEFAULT = "retro"
RETRO_NAME = "Retro calm"
RETRO_DESCRIPTION = "The website's default: a teal-navy night or a warm paper day, lit in LED rose and gold."
RETRO = {
    "dark": {
        "bg": "#111a22",
        "bg-2": "#15202a",
        "chassis": "#1a2632",
        "chassis-2": "#213040",
        "line": "#263543",
        "line-2": "#354757",
        "ink": "#f1e9da",
        "ink-2": "#c6beb0",
        "ink-3": "#9c968a",
        "rose": "#ff7396",
        "tangerine": "#ff9a62",
        "gold": "#f6c453",
        "gold-metal": "#f6c453",
        "ember": "#ff8a65",
        "ember-2": "#ffab8a",
        "cyan": "#5fd4c4",
        "green": "#8fdcaa",
        "violet": "#b9a3ff",
        "link": "#ff9ab2",
        "link-hover": "#ffc4d2",
        "well": "rgba(241, 233, 218, 0.03)",
        "well-2": "rgba(241, 233, 218, 0.055)",
        "well-3": "rgba(241, 233, 218, 0.085)",
        "code-bg": "#0e161d",
        "code-head": "#15202a",
        "code-ink": "#e6dfd2",
        "code-dim": "#948e84",
        "code-inline": "#1f2c38",
        "dot-grid": "rgba(241, 233, 218, 0.05)",
        "divider-dot": "#f6c453",
        "wash-1": "rgba(255, 115, 150, 0.07)",
        "wash-2": "rgba(95, 212, 196, 0.05)",
        "wash-3": "rgba(246, 196, 83, 0.05)",
        "selection": "rgba(255, 115, 150, 0.35)",
        "primary-a": "#ff8fab",
        "primary-b": "#ff7396",
        "primary-c": "#f25f86",
        "primary-line": "#ffa3ba",
        "on-primary": "#2a0d17",
        "primary-glow": "rgba(255, 115, 150, 0.18)",
        "accent-line": "#4a3442",
        "accent-wash": "rgba(255, 115, 150, 0.05)",
        "gold-line": "#4f4428",
        "gold-wash": "rgba(246, 196, 83, 0.06)",
        "rose-line": "#4a3442",
        "rose-wash": "rgba(255, 115, 150, 0.05)",
        "notice-bg": "#162029",
        "shadow": "rgba(4, 10, 16, 0.45)",
        "shadow-strong": "rgba(4, 10, 16, 0.65)",
        "theme-color": "#111a22",
        "btn-fill": "linear-gradient(180deg, #223140, #1a2632)",
    },
    "light": {
        "bg": "#f3ead8",
        "bg-2": "#f8f2e5",
        "chassis": "#fdf9f0",
        "chassis-2": "#eee3cd",
        "line": "#e2d5bb",
        "line-2": "#d1c1a2",
        "ink": "#1f2430",
        "ink-2": "#464954",
        "ink-3": "#5f5c60",
        "rose": "#b52a55",
        "tangerine": "#a8460f",
        "gold": "#7f5b0c",
        "gold-metal": "#c99a2e",
        "ember": "#a63e16",
        "ember-2": "#b52a55",
        "cyan": "#0f6e66",
        "green": "#2a7346",
        "violet": "#6247a8",
        "link": "#b02a52",
        "link-hover": "#861c3c",
        "well": "rgba(80, 60, 30, 0.035)",
        "well-2": "rgba(80, 60, 30, 0.06)",
        "well-3": "rgba(80, 60, 30, 0.09)",
        "code-bg": "#f8f2e5",
        "code-head": "#eee3cd",
        "code-ink": "#2a2c36",
        "code-dim": "#5f5c60",
        "code-inline": "#eee3cd",
        "dot-grid": "rgba(80, 60, 30, 0.085)",
        "divider-dot": "#b52a55",
        "wash-1": "rgba(181, 42, 85, 0.05)",
        "wash-2": "rgba(15, 110, 102, 0.04)",
        "wash-3": "rgba(201, 154, 46, 0.07)",
        "selection": "rgba(181, 42, 85, 0.2)",
        "primary-a": "#c9416a",
        "primary-b": "#b52a55",
        "primary-c": "#9c2148",
        "primary-line": "#c9416a",
        "on-primary": "#ffffff",
        "primary-glow": "rgba(181, 42, 85, 0.16)",
        "accent-line": "#e7bcc6",
        "accent-wash": "rgba(181, 42, 85, 0.04)",
        "gold-line": "#e2c98a",
        "gold-wash": "rgba(201, 154, 46, 0.08)",
        "rose-line": "#e7bcc6",
        "rose-wash": "rgba(181, 42, 85, 0.045)",
        "notice-bg": "#f6e4dc",
        "shadow": "rgba(80, 60, 30, 0.16)",
        "shadow-strong": "rgba(60, 44, 20, 0.3)",
        "theme-color": "#f3ead8",
        "btn-fill": "linear-gradient(180deg, rgba(255, 252, 245, 0.92), rgba(253, 249, 240, 0.7))",
    },
}
# text tokens that must stay AA (4.5:1) on every surface they sit on
_RETRO_TEXT = (
    "ink",
    "ink-2",
    "ink-3",
    "rose",
    "tangerine",
    "gold",
    "ember",
    "ember-2",
    "cyan",
    "green",
    "violet",
    "link",
)
_RETRO_SURFACES = ("bg", "bg-2", "chassis", "chassis-2")

DARK = {
    "c0": "#08080a",
    "c1": "#0f0f13",
    "c2": "#16161b",
    "c3": "#1e1e25",
    "line": "#25252d",
    "line2": "#33333d",
}
LIGHT = {
    "c0": "#f4f0e8",
    "c1": "#fbf9f5",
    "c2": "#ffffff",
    "c3": "#f0ebe2",
    "line": "#e7e1d6",
    "line2": "#d8d0c2",
}


# ------------------------------------------------------------------ colour maths (sRGB, as lib/pageTheme.ts)
def _rgb(h: str) -> tuple[int, int, int]:
    x = h.lstrip("#")
    return int(x[0:2], 16), int(x[2:4], 16), int(x[4:6], 16)


def _hex(c: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{int(max(0.0, min(255.0, v)) + 0.5):02x}" for v in c)


def mix(a: str, b: str, t: float) -> str:
    x, y = _rgb(a), _rgb(b)
    return _hex(tuple(x[i] + (y[i] - x[i]) * t for i in range(3)))  # type: ignore[arg-type]


def rgba(h: str, a: float) -> str:
    r, g, b = _rgb(h)
    return f"rgba({r}, {g}, {b}, {a:g})"


def _lum(h: str) -> float:
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def until(c: str, to: str, bg: str, ratio: float) -> str:
    """Move `c` toward `to` in 4 % steps until it reaches `ratio` against `bg`."""
    for k in range(26):
        x = mix(c, to, k * 0.04)
        if contrast(x, bg) >= ratio:
            return x
    return mix(c, to, 1)


def derive(t: dict[str, str]) -> dict[str, dict[str, str]]:
    """Every colour a theme paints with on the website, per mode."""
    tint = t.get("tint") or ""

    def tinted(base: str, k: float) -> str:
        return mix(base, tint, k) if tint else base

    a = until(t["accent"], "#ffffff", DARK["c1"], 4.5)
    m = t["metal"]
    dark = {
        "accent": a,
        "accent2": mix(a, "#ffffff", 0.28),
        "on": mix(a, "#000000", 0.9) if contrast(a, "#111111") >= 4.5 else "#ffffff",
        "metal": m,
        "metal_text": until(m, "#ffffff", DARK["c1"], 7),
        **{k: tinted(DARK[k], 0.07) for k in ("c0", "c1", "c2")},
        "c3": tinted(DARK["c3"], 0.08),
        "line": tinted(DARK["line"], 0.12),
        "line2": tinted(DARK["line2"], 0.14),
    }
    al = t.get("accent_light") or until(t["accent"], "#16101a", LIGHT["c0"], 4.8)
    light = {
        "accent": al,
        "accent2": mix(al, "#ffffff", 0.18),
        "on": "#ffffff",
        "metal": until(m, "#3a2a10", LIGHT["c1"], 2.6),
        "metal_text": until(m, "#2a1c08", LIGHT["c1"], 4.8),
        "c0": tinted(LIGHT["c0"], 0.06),
        "c1": LIGHT["c1"],
        "c2": LIGHT["c2"],
        "c3": tinted(LIGHT["c3"], 0.06),
        "line": tinted(LIGHT["line"], 0.08),
        "line2": tinted(LIGHT["line2"], 0.1),
    }
    return {"dark": dark, "light": light}


def _ink_pattern(p: str, ink: str) -> str:
    """The motif re-inked for porcelain (as lib/pageTheme.ts inkPattern)."""
    import re

    return re.sub(
        r"rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([0-9.]+)\s*\)",
        lambda mm: rgba(ink, round(min(0.12, float(mm.group(1)) * 1.5), 4)),
        p,
    )


# ------------------------------------------------------------------ the seeds
def themes() -> list[dict[str, Any]]:
    """The page themes in the studio's order: id, name, description and the screen seeds."""
    from deskdot.gfx.themes import PAGE_THEMES

    out = []
    for th in PAGE_THEMES.values():
        pub = th.public()
        out.append({"id": pub["id"], "name": pub["name"], "description": pub["description"], **pub["screen"]})
    return out


def _block(d: dict[str, str], *, light: bool, tinted: bool, texture: str, size: str) -> str:
    a, a2, m = d["accent"], d["accent2"], d["metal"]
    text_amber = a if light else a2
    lines = [
        f"--rose: {a}; --tangerine: {text_amber}; --ember: {a}; --ember-2: {a if light else a2};",
        f"--gold: {d['metal_text'] if light else m}; --gold-metal: {m};",
        f"--link: {a if light else a2}; --link-hover: {mix(a, '#000000', 0.25) if light else mix(a2, '#ffffff', 0.35)};",
        f"--primary-a: {mix(a, '#ffffff', 0.14) if light else mix(a2, '#ffffff', 0.12)}; --primary-b: {a};"
        f" --primary-c: {mix(a, '#000000', 0.14)}; --primary-line: {mix(a, '#ffffff', 0.3)}; --on-primary: {d['on']};",
        f"--primary-glow: {rgba(a, 0.22 if light else 0.35)}; --selection: {rgba(a, 0.25 if light else 0.45)};",
        f"--wash-1: {rgba(a, 0.07 if light else 0.1)}; --wash-2: {rgba(a2, 0.05 if light else 0.07)};"
        f" --wash-3: {rgba(m, 0.08 if light else 0.06)};",
        f"--accent-line: {mix(a, d['c0'], 0.55)}; --accent-wash: {rgba(a, 0.06)};",
    ]
    if tinted:
        lines.append(
            f"--bg: {d['c0']}; --bg-2: {d['c1']}; --chassis: {d['c2']}; --chassis-2: {d['c3']};"
            f" --line: {d['line']}; --line-2: {d['line2']}; --theme-color: {d['c0']};"
        )
    if texture:
        lines.append(f"--texture: {texture}; --texture-size: {size or 'auto'};")
    return "\n  ".join(lines)


def retro_contrast() -> dict[str, float]:
    """The lowest contrast of each Retro calm text colour over its surfaces, per mode ("dark.ink-3": 4.57, …)."""
    return {
        f"{mode}.{k}": min(contrast(tok[k], tok[bg]) for bg in _RETRO_SURFACES)
        for mode, tok in RETRO.items()
        for k in _RETRO_TEXT
    } | {f"{mode}.on-primary": contrast(tok["on-primary"], tok["primary-b"]) for mode, tok in RETRO.items()}


def retro_css() -> str:
    """Retro calm's swatch and its light and dark token blocks (hand-tuned, see RETRO)."""

    def block(tok: dict[str, str]) -> str:
        return "\n  ".join(f"--{k}: {v};" for k, v in tok.items())

    d, lt = RETRO["dark"], RETRO["light"]
    sel = f':root[data-page-theme="{SITE_DEFAULT}"]'
    return (
        f".sw-{SITE_DEFAULT} {{ --sw-a: {d['rose']}; --sw-m: {d['gold']}; --sw-t: {d['chassis']}; }}\n"
        f':root[data-theme="light"] .sw-{SITE_DEFAULT} {{ --sw-a: {lt["rose"]}; --sw-m: {lt["gold-metal"]};'
        f" --sw-t: {lt['chassis-2']}; }}\n"
        f'{sel} {{\n  {block(d)}\n}}\n{sel}[data-theme="light"] {{\n  {block(lt)}\n}}'
    )


def css() -> str:
    """The stylesheet for every non-default theme, light and dark, plus the swatch colours of all of them."""
    parts = ["/* generated by scripts/site_theme.py from src/deskdot/gfx/themes.py: do not edit by hand */"]
    parts.append(retro_css())
    for t in themes():
        dv = derive(t)
        d, lt = dv["dark"], dv["light"]
        parts.append(
            f".sw-{t['id']} {{ --sw-a: {d['accent']}; --sw-m: {d['metal']}; --sw-t: {d['c2']}; }}\n"
            f':root[data-theme="light"] .sw-{t["id"]} {{ --sw-a: {lt["accent"]}; --sw-m: {lt["metal"]};'
            f" --sw-t: {lt['c3']}; }}"
        )
        if t["id"] == DEFAULT:
            continue
        sel = f':root[data-page-theme="{t["id"]}"]'
        pat = t.get("pattern") or ""
        size = t.get("pattern_size") or ""
        dark_block = _block(d, light=False, tinted=bool(t.get("tint")), texture=pat, size=size)
        light_tex = _ink_pattern(pat, lt["accent"]) if pat else ""
        light_block = _block(lt, light=True, tinted=bool(t.get("tint")), texture=light_tex, size=size)
        parts.append(f'{sel} {{\n  {dark_block}\n}}\n{sel}[data-theme="light"] {{\n  {light_block}\n}}')
    return "\n".join(parts)


def menu_html() -> str:
    """The theme menu (outside the header so its glass can blur the page): appearance + page theme swatches."""
    modes = "".join(
        f'<button type="button" data-theme-pick="{mid}" aria-pressed="false">{label}</button>'
        for mid, label in (("light", "Light"), ("dark", "Dark"), ("system", "Auto"))
    )
    picks = [{"id": SITE_DEFAULT, "name": RETRO_NAME}, *themes()]
    sw = "".join(
        f'<button type="button" class="sw sw-{t["id"]}" data-page-theme-pick="{t["id"]}" aria-pressed="false" '
        f'title="{html.escape(t["name"])}"><i aria-hidden="true"></i><span>{html.escape(t["name"])}</span></button>'
        for t in picks
    )
    return f"""<div class="theme-menu" id="theme-menu" role="dialog" aria-modal="false" aria-labelledby="theme-menu-h" hidden>
  <div class="theme-menu-head"><h2 id="theme-menu-h">Appearance</h2><button type="button" class="theme-close" aria-label="Close">×</button></div>
  <div class="seg" role="group" aria-label="Light or dark">{modes}</div>
  <h3>Page theme <small id="theme-name"></small></h3>
  <div class="swatches" role="group" aria-label="Page theme">{sw}</div>
  <p class="theme-note">Retro calm is the website's own; the other 21 are the DeskDot studio's (the web app opens in those too). Saved in this browser.</p>
</div>"""
