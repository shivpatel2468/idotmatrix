"""Themes for idotmatrix.com: the casino's 21 table themes (src/deskdot/apps/_casino.py TABLE_THEMES), the way each
one looks in the dark casino (web/src/components/casino/casino.css, state.ts themeVars), mapped onto the website's own
token names (site/styles.css).

Dark is the primary look: the page is the casino's room (`bg`), cards and panels its surfaces, lines tinted by the
accent like `--cz-line`, text the casino's felt-tinted inks, the accent (and its AA text tone `accent_text`) on
buttons, links, highlights and glows, and the felt's `pattern` motif as the page's background texture. Light is the
casino's porcelain salon (casino.css `:root[data-theme="light"] .cz`): the room washed in the table's colour, the
accent deepened to bronze where it is text, primary keys in the accent (or, for a pale accent, the table's felt).
Every text tone is pushed until it is AA (4.5:1) on every surface it sits on; tests/test_site_data.py checks it.

build_site_pages.py writes css() between the `/* gen:themes */` markers in site/styles.css and the theme menu from
menu_html(). The pick is stored in localStorage `deskdot.siteTheme` (the studio's own page themes are a different set,
in `deskdot.pageTheme`; a visitor whose old pick there is also a table id keeps it). Nothing stored: DEFAULT, dark.
"""

from __future__ import annotations

import html
import re
from typing import Any

DEFAULT = "cyber"  # first-time visitors: Cyber grid, dark
STORE_KEY = "deskdot.siteTheme"

_INK_LIGHT = ("#1c1a22", "#3a3642", "#4f4a57")  # the salon's inks (casino.css --cz-ink-1 … --cz-mute)


# ------------------------------------------------------------------ colour maths (sRGB)
def _rgb(h: str) -> tuple[int, int, int]:
    x = h.lstrip("#")
    return int(x[0:2], 16), int(x[2:4], 16), int(x[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    """`a` moved `t` of the way to `b` (CSS color-mix(in srgb, a, b t))."""
    x, y = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x[i] + (y[i] - x[i]) * t):02x}" for i in range(3))


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


def until(c: str, to: str, bgs: tuple[str, ...], ratio: float = 4.5) -> str:
    """Move `c` toward `to` in 4 % steps until it reaches `ratio` against every colour in `bgs`."""
    for k in range(26):
        x = mix(c, to, k * 0.04)
        if all(contrast(x, bg) >= ratio for bg in bgs):
            return x
    return mix(c, to, 1)


def _ink_pattern(p: str, ink: str, cap: float = 0.08) -> str:
    """The felt's motif re-inked for porcelain: every rgba() colour becomes `ink` at a light alpha."""
    return re.sub(
        r"rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*([0-9.]+)\s*\)",
        lambda mm: rgba(ink, round(min(cap, float(mm.group(1)) * 1.2), 4)),
        p,
    )


def _lift_pattern(p: str, k: float = 1.7, cap: float = 0.3) -> str:
    """The felt's motif for the page: the casino draws it on a mid-tone felt, the page is the darker room, so every
    rgba() alpha is lifted `k` times (at most `cap`) to read as the same subtle texture."""
    return re.sub(
        r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)",
        lambda mm: f"rgba({mm[1]}, {mm[2]}, {mm[3]}, {round(min(cap, float(mm[4]) * k), 4):g})",
        p,
    )


# ------------------------------------------------------------------ the themes
def themes() -> list[dict[str, Any]]:
    """The table themes in the casino's order: id, name, description and its CSS tokens (felt, accent, surfaces …)."""
    from deskdot.apps._casino import TABLE_THEMES

    return [
        {"id": t.id, "name": t.name, "description": t.description, **t.css} for t in TABLE_THEMES.values()
    ]


def ids() -> list[str]:
    return [t["id"] for t in themes()]


def _pale(accent: str) -> bool:
    """A pale accent (ivory, champagne, ice) can't be a key on porcelain (state.ts lightSwitches)."""
    a = _rgb(accent)
    return (max(a) - min(a)) / max(max(a), 1) < 0.36


def _tint(c: dict[str, str]) -> str:
    """The colour the light room is washed with: the felt, or the accent when the felt is a graphite / black."""
    f = _rgb(c["felt"])
    return c["accent"] if max(f) - min(f) < 40 else c["felt"]


# text tokens, and the surfaces they must stay AA on
TEXT = ("ink", "ink-2", "ink-3", "rose", "tangerine", "ember", "ember-2", "gold", "link", "link-hover")
SURFACES = ("bg", "bg-2", "chassis", "chassis-2")


def dark(c: dict[str, str]) -> dict[str, str]:
    """The website's tokens for a table theme, as the casino looks in dark mode."""
    acc, hi, lo = c["accent"], c["accent_hi"], c["accent_lo"]
    bg, s1, s2, s3 = c["bg"], c["surface"], c["surface2"], c["surface3"]
    surf = (bg, s1, s2, s3)
    # the casino's inks (casino.css --cz-ink-1 / -2 / --cz-dim), pushed until AA on every surface
    ink = until(mix("#ffffff", hi, 0.18), "#ffffff", surf, 7)
    ink2 = until(mix(c["felt_ink"], hi, 0.16), "#ffffff", surf)
    ink3 = until(mix(c["felt_ink"], c["wing"], 0.3), "#ffffff", surf)
    text = until(c["accent_text"], hi, surf)
    hi_text = until(hi, "#ffffff", surf)
    on = (
        c["ink"]
        if contrast(c["ink"], acc) >= 4.5
        else ("#000000" if contrast("#000000", acc) >= 4.5 else "#ffffff")
    )
    edge = mix(s2, acc, 0.34)
    return {
        "bg": bg,
        "bg-2": s1,
        "chassis": s2,
        "chassis-2": s3,
        "line": mix(s2, acc, 0.14),
        "line-2": mix(s3, acc, 0.24),
        "ink": ink,
        "ink-2": ink2,
        "ink-3": ink3,
        "rose": text,
        "tangerine": text,
        "ember": text,
        "ember-2": hi_text,
        "gold": hi_text,
        "gold-metal": acc,
        "link": text,
        "link-hover": hi_text,
        "well": rgba(hi, 0.03),
        "well-2": rgba(hi, 0.055),
        "well-3": rgba(hi, 0.085),
        "code-bg": mix(bg, "#000000", 0.25),
        "code-head": s1,
        "code-ink": ink2,
        "code-dim": ink3,
        "code-inline": s3,
        "dot-grid": rgba(acc, 0.06),
        "divider-dot": acc,
        "wash-1": rgba(c["felt"], 0.42),
        "wash-2": rgba(acc, 0.07),
        "wash-3": rgba(c["felt"], 0.3),
        "selection": rgba(acc, 0.4),
        "primary-a": hi,
        "primary-b": acc,
        "primary-c": lo,
        "primary-line": hi,
        "on-primary": on,
        "primary-glow": rgba(acc, 0.32),
        "accent-line": edge,
        "accent-wash": rgba(acc, 0.05),
        "gold-line": edge,
        "gold-wash": rgba(acc, 0.06),
        "rose-line": edge,
        "rose-wash": rgba(acc, 0.05),
        "notice-bg": s1,
        "shadow": "rgba(0, 0, 0, 0.5)",
        "shadow-strong": "rgba(0, 0, 0, 0.72)",
        "theme-color": bg,
        "btn-fill": f"linear-gradient(180deg, {s3}, {s2})",
        "lg-edge-strong": rgba(acc, 0.22),
        "felt": c["felt"],
        "felt-2": c["felt2"],
        "texture": _lift_pattern(c["pattern"]) if c.get("pattern") not in (None, "", "none") else "none",
        "texture-size": c.get("pattern_size") or "auto",
    }


def light(c: dict[str, str]) -> dict[str, str]:
    """The porcelain salon lit by the table (casino.css light mode), in the website's tokens."""
    acc, hi, lo, felt = c["accent"], c["accent_hi"], c["accent_lo"], c["felt"]
    tint = _tint(c)
    room = mix(felt, tint, 0.3)
    pale = _pale(acc)
    bg, s1 = mix("#f2ede4", room, 0.12), mix("#fcfbf8", room, 0.06)
    s2, s3 = mix("#ffffff", room, 0.025), mix("#f1ede5", room, 0.1)
    surf = (bg, s1, s2, s3)
    metal = mix(acc, "#4a4438", 0.26)
    bronze = mix(felt, "#000000", 0.28) if pale else mix("#1a1206", acc, 0.3)
    text = until(bronze, "#000000", surf)
    text2 = until(mix(text, "#000000", 0.2), "#000000", surf)
    ink, ink2, ink3 = (until(i, "#000000", surf) for i in _INK_LIGHT)
    # primary keys: gold leaf in the accent, or (pale accent) the table's felt with accent lettering
    key_a, key_b, key_c = (mix(felt, "#ffffff", 0.12), felt, c["felt2"]) if pale else (hi, acc, lo)
    on = hi if pale else c["ink"]
    if contrast(on, key_b) < 4.5:
        on = "#ffffff" if contrast("#ffffff", key_b) >= contrast("#000000", key_b) else "#000000"
    line_base = mix("#e4ddd1", room, 0.1)
    edge = mix(line_base, metal, 0.5)
    pat = c.get("pattern") or ""
    return {
        "bg": bg,
        "bg-2": s1,
        "chassis": s2,
        "chassis-2": s3,
        "line": mix(line_base, metal, 0.26),
        "line-2": mix(mix("#d6cdbf", room, 0.12), metal, 0.4),
        "ink": ink,
        "ink-2": ink2,
        "ink-3": ink3,
        "rose": text,
        "tangerine": text,
        "ember": text,
        "ember-2": text,
        "gold": text2,
        "gold-metal": metal,
        "link": text,
        "link-hover": text2,
        "well": rgba(room, 0.035),
        "well-2": rgba(room, 0.06),
        "well-3": rgba(room, 0.09),
        "code-bg": s1,
        "code-head": s3,
        "code-ink": ink,
        "code-dim": ink3,
        "code-inline": s3,
        "dot-grid": rgba(room, 0.1),
        "divider-dot": metal,
        "wash-1": rgba(tint, 0.1),
        "wash-2": rgba(acc, 0.08),
        "wash-3": rgba(tint, 0.06),
        "selection": rgba(tint, 0.22),
        "primary-a": key_a,
        "primary-b": key_b,
        "primary-c": key_c,
        "primary-line": mix(key_b, "#000000", 0.12),
        "on-primary": on,
        "primary-glow": rgba(tint, 0.24),
        "accent-line": edge,
        "accent-wash": rgba(tint, 0.05),
        "gold-line": edge,
        "gold-wash": rgba(acc, 0.08),
        "rose-line": edge,
        "rose-wash": rgba(tint, 0.05),
        "notice-bg": mix("#ffffff", tint, 0.08),
        "shadow": rgba(mix(room, "#3a2e1c", 0.6), 0.18),
        "shadow-strong": rgba(mix(room, "#281e10", 0.6), 0.34),
        "theme-color": bg,
        "btn-fill": "linear-gradient(180deg, rgba(255, 255, 255, 0.88), rgba(255, 255, 255, 0.62))",
        "lg-edge-strong": rgba(mix(metal, "#000000", 0.2), 0.3),
        "felt": felt,
        "felt-2": c["felt2"],
        "texture": _ink_pattern(pat, mix(tint, "#000000", 0.2)) if pat and pat != "none" else "none",
        "texture-size": c.get("pattern_size") or "auto",
    }


def tokens(t: dict[str, Any]) -> dict[str, dict[str, str]]:
    d, lt = dark(t), light(t)
    assert (
        d.keys() == lt.keys()
    )  # the light block overrides every dark token (the two share a selector prefix)
    return {"dark": d, "light": lt}


def contrast_report() -> dict[str, float]:
    """The lowest contrast of every text token over the surfaces it sits on, per theme and mode, plus the primary
    key's lettering ("cyber.dark.ink-3": 5.1, …)."""
    out: dict[str, float] = {}
    for t in themes():
        for mode, tok in tokens(t).items():
            for k in TEXT:
                out[f"{t['id']}.{mode}.{k}"] = min(contrast(tok[k], tok[s]) for s in SURFACES)
            out[f"{t['id']}.{mode}.on-primary"] = contrast(tok["on-primary"], tok["primary-b"])
    return out


def _block(tok: dict[str, str]) -> str:
    return "\n  ".join(f"--{k}: {v};" for k, v in tok.items())


def css() -> str:
    """Every table theme's dark and light token blocks plus its swatch (felt, motif, accent). The default (Cyber
    grid) also styles a page whose inline script never ran (no JS: no data-page-theme, dark)."""
    parts = [
        "/* generated by scripts/site_theme.py from src/deskdot/apps/_casino.py TABLE_THEMES: do not edit by hand */"
    ]
    for t in themes():
        tok = tokens(t)
        parts.append(
            f".sw-{t['id']} {{ --sw-t: {t['felt']}; --sw-a: {t['accent']}; --sw-m: {t['accent_hi']};"
            f" --sw-p: {t.get('pattern') or 'none'}; --sw-ps: {t.get('pattern_size') or 'auto'}; }}"
        )
        sel = f':root[data-page-theme="{t["id"]}"]'
        dark_sel = f"{sel}, :root:not([data-page-theme])" if t["id"] == DEFAULT else sel
        parts.append(
            f'{dark_sel} {{\n  {_block(tok["dark"])}\n}}\n{sel}[data-theme="light"] {{\n  {_block(tok["light"])}\n}}'
        )
    return "\n".join(parts)


def menu_html() -> str:
    """The theme menu (outside the header so its glass can blur the page): appearance + the table theme swatches."""
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
  <h3>Table theme <small id="theme-name"></small></h3>
  <div class="swatches" role="group" aria-label="Table theme">{sw}</div>
  <p class="theme-note">The 21 table themes of the DeskDot casino, felt and all. Saved in this browser.</p>
</div>"""


# ------------------------------------------------------------------ the web app's landing card (/app/, web/webapp)
def host_css() -> str:
    """The landing card and connection pill of the web app at /app/ (web/webapp/host.css, a shadow root) in the same
    table theme as the website: host.js sets :host([data-table-theme]) from the website's pick (STORE_KEY)."""
    parts = [
        "/* generated by scripts/site_theme.py from src/deskdot/apps/_casino.py TABLE_THEMES: do not edit by hand */"
    ]
    parts.append(
        ':host([data-table-theme]) .landing, :host([data-table-theme][data-theme="light"]) .landing'
        " { background: var(--landing-bg); }\n"
        ':host([data-table-theme]) .bar i, :host([data-table-theme][data-theme="light"]) .bar i'
        " { background: linear-gradient(90deg, var(--ember), color-mix(in srgb, var(--ember) 65%, #fff)); }"
    )
    for t in themes():
        tok = tokens(t)
        for mode in ("dark", "light"):
            d = tok[mode]
            pat, size = d["texture"], d["texture-size"]
            veil = rgba(d["bg"], 0.95 if mode == "dark" else 0.94)
            glow = rgba(t["felt"], 0.5) if mode == "dark" else rgba(_tint(t), 0.12)
            landing = f"radial-gradient(70% 60% at 50% 0%, {glow}, transparent 70%)"
            if pat != "none":
                landing += f", {pat}"
            v = {
                "c0": d["bg"], "c1": d["bg-2"], "c2": d["chassis"], "c3": d["chassis-2"],
                "c4": t["surface4"] if mode == "dark" else d["chassis"],
                "line": d["line"], "line2": d["line-2"], "ink1": d["ink"], "ink2": d["ink-2"], "ink3": d["ink-3"],
                "ember": d["primary-b"], "ember2": d["ember-2"] if mode == "dark" else d["link"],
                "on-ember": d["on-primary"],
                "landing-bg": f"{landing}, {veil}",
                "landing-size": f"auto, {size}" if pat != "none" else "auto",
                "pill-bg": rgba(d["chassis"], 0.94),
                "lg-tint": rgba(d["chassis"], 0.55 if mode == "dark" else 0.6),
                "lg-tint-thick": rgba(d["chassis"], 0.8 if mode == "dark" else 0.82),
                "lg-frost": rgba(d["chassis"], 0.96),
                "lg-solid": d["chassis"],
                "lg-edge-strong": d["lg-edge-strong"],
            }  # fmt: skip
            sel = (
                f':host([data-table-theme="{t["id"]}"])'
                if mode == "dark"
                else (f':host([data-table-theme="{t["id"]}"][data-theme="light"])')
            )
            parts.append(f"{sel} {{ " + " ".join(f"--{k}: {x};" for k, x in v.items()) + " }")
    parts.append(":host([data-table-theme]) .landing { background-size: var(--landing-size); }")
    return "\n".join(parts)
