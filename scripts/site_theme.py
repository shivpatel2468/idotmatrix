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

DEFAULT = "ember"

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


def css() -> str:
    """The stylesheet for every non-default theme, light and dark, plus the swatch colours of all of them."""
    parts = ["/* generated by scripts/site_theme.py from src/deskdot/gfx/themes.py: do not edit by hand */"]
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
    sw = "".join(
        f'<button type="button" class="sw sw-{t["id"]}" data-page-theme-pick="{t["id"]}" aria-pressed="false" '
        f'title="{html.escape(t["name"])}"><i aria-hidden="true"></i><span>{html.escape(t["name"])}</span></button>'
        for t in themes()
    )
    return f"""<div class="theme-menu" id="theme-menu" role="dialog" aria-modal="false" aria-labelledby="theme-menu-h" hidden>
  <div class="theme-menu-head"><h2 id="theme-menu-h">Appearance</h2><button type="button" class="theme-close" aria-label="Close">×</button></div>
  <div class="seg" role="group" aria-label="Light or dark">{modes}</div>
  <h3>Page theme <small id="theme-name"></small></h3>
  <div class="swatches" role="group" aria-label="Page theme">{sw}</div>
  <p class="theme-note">The same 21 themes as the DeskDot studio. Saved in this browser; the web app opens in it too.</p>
</div>"""
