"""Build every HTML page of idotmatrix.com from site/apps.json, plus the sitemap, robots.txt and icons.

    uv run python scripts/build_site_pages.py            # write the pages, then check every internal link
    uv run python scripts/build_site_pages.py --check    # only check links (exit 1 on a broken one)

Run after scripts/build_site_media.py (previews) and scripts/build_site_data.py (apps.json).

Two kinds of page:
  * hand-written pages (index, setup, guide, apps, features, studio, specs, faq, 404): edit the HTML between
    `<!-- page:start -->` and `<!-- page:end -->` in site/<page>.html. This script rewrites everything around it
    (head, meta tags, header, footer) so the chrome is identical everywhere, fills the `<!-- gen:NAME -->` regions
    (app cards, preview reels) and refreshes `data-count` numbers.
  * one generated page per app: site/apps/<id>.html (preview, settings, game modes, try-it commands).

URLs are root-relative (/apps.html), so every page, the 404 page included, works at any depth. The site is
plain static files: no framework, no bundler; Google Fonts is the only third-party request.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SITE_URL = "https://idotmatrix.com"
REPO = "https://github.com/shivpatel2468/idotmatrix"
BRAND = "DeskDot"

START, END = "<!-- page:start -->", "<!-- page:end -->"
# The one inline script, run before first paint: marks the document as JS-enabled (scroll-reveal styles key off
# it) and as supporting cross-document View Transitions (`vt`: the CSS fade-in fallback then stays off).
# netlify.toml's Content-Security-Policy allows exactly this script by its hash (see csp_hash()).
INLINE_JS = 'document.documentElement.className+=" js"+("onpagereveal" in window?" vt":"")'

NAV = [
    ("setup", "/setup.html", "AI setup"),
    ("guide", "/guide.html", "Run it"),
    ("apps", "/apps.html", "Apps"),
    ("features", "/features.html", "Features"),
    ("studio", "/studio.html", "Studio"),
    ("specs", "/specs.html", "Specs"),
    ("faq", "/faq.html", "FAQ"),
]

PAGES: dict[str, dict[str, Any]] = {
    "index.html": {
        "nav": "home",
        "title": "DeskDot: the all-in-one app for your iDotMatrix 32×32 panel",
        "description": "Turn your iDotMatrix 32×32 LED panel into a live desktop companion: {apps} apps, "
        "multiplayer games, live data, a studio for browser and phone, and an MCP server so AI agents can "
        "drive it. Free, open source, local.",
    },
    "setup.html": {
        "nav": "setup",
        "title": "Set up DeskDot with your AI agent",
        "description": "One prompt for Claude Code, Gemini CLI, Codex or Cursor installs DeskDot, starts the "
        "simulator, then connects your iDotMatrix panel and its MCP server.",
    },
    "guide.html": {
        "nav": "guide",
        "title": "Run DeskDot yourself: step-by-step guide",
        "description": "From nothing to a live iDotMatrix panel in about ten minutes: install uv, clone, build the "
        "studio, try the simulator, pair over Bluetooth, and keep it on with a Raspberry Pi.",
    },
    "apps.html": {
        "nav": "apps",
        "title": "All {apps} DeskDot apps for the iDotMatrix panel",
        "description": "Browse every DeskDot app with its real animated preview: clocks, live data, media, "
        "pets, ambient loops and {games} games. Search apps, settings and options.",
    },
    "features.html": {
        "nav": "features",
        "title": "DeskDot features: games, AI agents, live data",
        "description": "Multiplayer games with phone controllers, an MCP server for AI agents, baked loops that "
        "play smoothly on the panel, live data from 45+ free sources, and a fruit-fly brain that plays games.",
    },
    "studio.html": {
        "nav": "studio",
        "title": "The DeskDot studio: browser, phone and 3D views",
        "description": "Library, live LED-accurate preview, settings generated from each app's schema, Play mode "
        "for games, the phone controller and the 3D Fly Brain view.",
    },
    "specs.html": {
        "nav": "specs",
        "title": "DeskDot compatibility and iDotMatrix panel specs",
        "description": "Which computers run DeskDot (Windows, Raspberry Pi, Linux, macOS, Android beta) and the "
        "measured limits of the iDotMatrix 32×32 panel it drives.",
    },
    "faq.html": {
        "nav": "faq",
        "title": "DeskDot FAQ",
        "description": "Is DeskDot official? Which panels work? Does it cost anything? Answers about the "
        "iDotMatrix app, MCP and AI agents, smooth animation and writing your own app.",
    },
    "404.html": {
        "nav": None,
        "title": "Page not found",
        "description": "This page wandered off the 32×32 grid.",
        "noindex": True,
    },
}

CAT_COLOR = {
    "time": "#ffcc33",
    "data": "#45d9ff",
    "media": "#ff3f78",
    "creative": "#c39bff",
    "pets": "#5cf2a0",
    "games": "#ff7419",
    "ambient": "#4fe3c8",
    "productivity": "#ffe27a",
    "device": "#a6adff",
}
KIND = {
    "clip": (
        "Baked loop",
        "#5cf2a0",
        "Rendered once into a GIF that the panel loops with its own firmware: perfectly smooth, no Bluetooth traffic.",
    ),
    "stream": (
        "Live",
        "#45d9ff",
        "Rendered by the engine and streamed over Bluetooth as its data changes (about 5–9 frames a second).",
    ),
    "native": (
        "Firmware",
        "#ffcc33",
        "Uses one of the panel's own built-in modes, so it keeps running even with the computer off.",
    ),
}
CONTROL = {
    "dpad": "D-pad",
    "joystick": "Analog stick",
    "swipe": "Swipe",
    "tap": "Tap zones",
    "gamepad": "Gamepad",
    "keyboard": "Keyboard",
    "tilt": "Tilt",
}
TEAMS = {"solo": "Solo", "coop": "Co-op", "ffa": "Free-for-all", "versus": "Teams"}
TYPE = {
    "choice": "choice",
    "toggle": "on/off",
    "integer": "whole number",
    "number": "number",
    "color": "colour",
    "text": "text",
}
FEATURED = ["synthwave", "petworld", "cycles", "weather", "nowplaying", "radar", "wireframe", "flybrain"]


def e(s: str) -> str:
    """Escape text for HTML content and double-quoted attributes (apostrophes stay readable)."""
    return html.escape(s, quote=False).replace('"', "&quot;")


def csp_hash() -> str:
    """The CSP source for INLINE_JS (netlify.toml must carry it)."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(INLINE_JS.encode()).digest()).decode() + "'"


# =============================================================================================== shared chrome
SPRITE = """<svg width="0" height="0" class="sprite" aria-hidden="true" focusable="false">
  <symbol id="i-gh" viewBox="0 0 24 24"><path fill="currentColor" d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.26 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z"/></symbol>
  <symbol id="i-star" viewBox="0 0 24 24"><path fill="currentColor" d="m12 2.6 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.4l-5.8 3.1 1.1-6.5L2.6 9.4l6.5-.9L12 2.6Z"/></symbol>
  <symbol id="i-copy" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></g></symbol>
  <symbol id="i-check" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" d="m4 12 5 5L20 6"/></symbol>
  <symbol id="i-search" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></g></symbol>
  <symbol id="i-arrow" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M5 12h14m-6-6 6 6-6 6"/></symbol>
  <symbol id="i-back" viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M19 12H5m6 6-6-6 6-6"/></symbol>
</svg>"""


def _url(path: str) -> str:
    """The canonical absolute URL of a site path ("index.html" → https://idotmatrix.com/)."""
    path = path.lstrip("/")
    return f"{SITE_URL}/" if path in ("", "index.html") else f"{SITE_URL}/{path}"


def head(
    path: str,
    title: str,
    description: str,
    *,
    og_image: str = "/media/og.png",
    og_size: tuple[int, int] = (1200, 630),
    og_alt: str = "DeskDot apps rendered on simulated 32×32 LED panels",
    noindex: bool = False,
    jsonld: list[dict[str, Any]] | None = None,
    og_type: str = "website",
) -> str:
    full_title = title if BRAND in title else f"{title} · {BRAND}"
    card = "summary_large_image" if og_size[0] > og_size[1] else "summary"
    tags = [
        '<meta charset="utf-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />',
        f"<title>{e(full_title)}</title>",
        f'<meta name="description" content="{e(description)}" />',
    ]
    if noindex:
        tags.append('<meta name="robots" content="noindex" />')
    else:
        tags.append(f'<link rel="canonical" href="{_url(path)}" />')
    img = SITE_URL + og_image
    tags += [
        '<meta name="theme-color" content="#08070a" />',
        '<meta name="color-scheme" content="dark" />',
        '<meta name="author" content="Shiv Patel" />',
        f'<meta property="og:type" content="{og_type}" />',
        f'<meta property="og:site_name" content="{BRAND}" />',
        f'<meta property="og:url" content="{_url(path)}" />',
        f'<meta property="og:title" content="{e(full_title)}" />',
        f'<meta property="og:description" content="{e(description)}" />',
        f'<meta property="og:image" content="{img}" />',
        f'<meta property="og:image:width" content="{og_size[0]}" />',
        f'<meta property="og:image:height" content="{og_size[1]}" />',
        f'<meta property="og:image:alt" content="{e(og_alt)}" />',
        f'<meta name="twitter:card" content="{card}" />',
        f'<meta name="twitter:title" content="{e(full_title)}" />',
        f'<meta name="twitter:description" content="{e(description)}" />',
        f'<meta name="twitter:image" content="{img}" />',
        f'<meta name="twitter:image:alt" content="{e(og_alt)}" />',
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml" />',
        '<link rel="icon" href="/favicon.ico" sizes="32x32" />',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png" />',
        '<link rel="manifest" href="/site.webmanifest" />',
        '<link rel="preconnect" href="https://fonts.googleapis.com" />',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />',
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,'
        '400..800&amp;family=Martian+Mono:wght@400..700&amp;display=swap" />',
        '<link rel="stylesheet" href="/styles.css" />',
        f"<script>{INLINE_JS}</script>",
        '<script src="/main.js" defer></script>',
    ]
    for block in jsonld or []:
        tags.append(
            '<script type="application/ld+json">'
            + json.dumps(block, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
            + "</script>"
        )
    return "<head>\n" + "\n".join(tags) + "\n</head>"


def header(active: str | None) -> str:
    links = []
    for key, href, label in NAV:
        cur = ' aria-current="page"' if key == active else ""
        links.append(f'<a href="{href}"{cur}>{label}</a>')
    home_cur = ' aria-current="page"' if active == "home" else ""
    return f"""<a class="skip" href="#main">Skip to content</a>
{SPRITE}
<header class="bar" id="bar">
  <div class="wrap">
    <a class="brand" href="/"{home_cur} aria-label="{BRAND} home"><canvas class="mini-logo" width="86" height="14" aria-hidden="true"></canvas><span class="word">{BRAND}</span></a>
    <nav id="nav" aria-label="Main">
      {chr(10).join("      " + link for link in links).strip()}
    </nav>
    <button class="menu-btn" id="menu-btn" type="button" aria-expanded="false" aria-controls="nav" aria-label="Menu"><span></span><span></span><span></span></button>
    <a class="btn small gh" href="{REPO}" aria-label="{BRAND} on GitHub"><svg aria-hidden="true"><use href="#i-gh"/></svg><span class="hide-sm">GitHub</span><span class="count" data-stars></span></a>
  </div>
</header>"""


def footer() -> str:
    return f"""<footer>
  <div class="wrap">
    <div class="foot-grid">
      <div>
        <canvas class="footer-logo" width="150" height="24" role="img" aria-label="idotmatrix"></canvas>
        <p>{BRAND} turns an iDotMatrix 32×32 RGB LED panel into a live desktop companion. Built by
          <a href="https://github.com/shivpatel2468">Shiv Patel</a>. Free and open source under the MIT licence.</p>
      </div>
      <div>
        <h2>Get started</h2>
        <ul>
          <li><a href="/setup.html">Set up with an AI agent</a></li>
          <li><a href="/guide.html">Step-by-step guide</a></li>
          <li><a href="/apps.html">Apps explorer</a></li>
          <li><a href="/specs.html">Compatibility</a></li>
          <li><a href="/faq.html">FAQ</a></li>
        </ul>
      </div>
      <div>
        <h2>Docs</h2>
        <ul>
          <li><a href="{REPO}/blob/main/README.md">README</a></li>
          <li><a href="{REPO}/blob/main/docs/MCP.md">MCP server</a></li>
          <li><a href="{REPO}/blob/main/docs/APP_SDK.md">App SDK</a></li>
          <li><a href="{REPO}/blob/main/docs/API.md">HTTP API</a></li>
          <li><a href="{REPO}/blob/main/docs/DEPLOY.md">Raspberry Pi &amp; hosts</a></li>
        </ul>
      </div>
      <div>
        <h2>Project</h2>
        <ul>
          <li><a href="{REPO}">GitHub repository</a></li>
          <li><a href="{REPO}/issues">Issues</a></li>
          <li><a href="{REPO}/blob/main/CHANGELOG.md">Changelog</a></li>
          <li><a href="{REPO}/blob/main/LICENSE">MIT licence</a></li>
          <li><a href="{REPO}/blob/main/SECURITY.md">Security</a></li>
        </ul>
      </div>
    </div>
    <div class="fine">
      <span>© Shiv Patel · MIT licence · Unofficial, not affiliated with iDotMatrix</span>
      <span>1,024 pixels. Zero subscriptions.</span>
    </div>
  </div>
</footer>
<div class="toast" id="toast" role="status" aria-live="polite"></div>"""


def document(path: str, head_html: str, active: str | None, body: str, body_class: str = "") -> str:
    cls = f' class="{body_class}"' if body_class else ""
    return (
        f'<!doctype html>\n<html lang="en">\n{head_html}\n<body{cls}>\n{header(active)}\n\n'
        f'<main id="main" tabindex="-1">\n{START}\n{body.strip()}\n{END}\n</main>\n\n{footer()}\n</body>\n</html>\n'
    )


# =============================================================================================== app bits
def panel(app: dict[str, Any], *, eager: bool = False, cls: str = "panel") -> str:
    """The app's real preview as an LED panel: the animated GIF, or its still for reduced-motion visitors."""
    alt = f"{app['name']} running on a 32×32 LED panel"
    if not app.get("preview"):
        return f'<div class="{cls} empty" role="img" aria-label="{e(alt)}"></div>'
    load = 'fetchpriority="high"' if eager else 'loading="lazy"'
    still = (
        f'<source media="(prefers-reduced-motion: reduce)" srcset="/{app["poster"]}" />'
        if app.get("poster")
        else ""
    )
    return (
        f'<div class="{cls}"><picture>{still}<img src="/{app["preview"]}" width="32" height="32" {load} '
        f'decoding="async" alt="{e(alt)}" /></picture></div>'
    )


def badge(label: str, color: str) -> str:
    return f'<span class="badge" style="--c:{color}"><i></i>{e(label)}</span>'


def search_text(app: dict[str, Any], cat_label: str) -> str:
    parts = [app["name"], app["id"], app["description"], cat_label, *[KIND[k][0] for k in app["kinds"]]]
    for s in app["settings"]:
        parts += [s["title"], s["key"].replace("_", " "), s.get("group", "")]
        parts += [str(o["label"]) for o in s.get("options", [])]
    g = app.get("game")
    if g:
        parts += [f"{g['max_players']} players", "game"]
        parts += [m["name"] for m in g["modes"]] + [TEAMS.get(m["teams"], m["teams"]) for m in g["modes"]]
        parts += [m["label"] for m in g["maps"]] + [CONTROL.get(c, c) for c in g["controls"]]
    seen: dict[str, None] = {}
    for word in " ".join(parts).lower().split():
        seen.setdefault(word, None)
    return " ".join(seen)


def app_card(app: dict[str, Any], cat_label: str, *, i: int = 0, searchable: bool = True) -> str:
    k_label, k_color, _ = KIND[app["kind"]]
    g = app.get("game") or {}
    mp = g.get("max_players", 1) > 1
    foot = [f"<span>{len(app['settings'])} settings</span>"]
    if mp:
        foot.append(f"<span>{g['max_players']} players</span>")
    if g.get("maps"):
        foot.append(f"<span>{len(g['maps'])} maps</span>")
    attrs = ""
    if searchable:
        flags = " ".join(f for f, on in (("multiplayer", mp), ("clip", "clip" in app["kinds"])) if on)
        attrs = f' data-cat="{app["category"]}" data-flags="{flags}" data-search="{e(search_text(app, cat_label))}"'
    return f"""<a class="card app-card" href="/{app["page"]}" style="--glow:{CAT_COLOR[app["category"]]};--i:{min(i, 12)}"{attrs}>
  <div class="thumb">{panel(app)}{badge(k_label, k_color)}</div>
  <div class="body">
    <span class="tag" style="color:{CAT_COLOR[app["category"]]}">{e(cat_label)}</span>
    <h3>{e(app["name"])}</h3>
    <p>{e(app["description"])}</p>
    <div class="foot">{"".join(foot)}</div>
  </div>
</a>"""


def _fmt(s: dict[str, Any], v: Any, missing: bool = False) -> str:
    if missing:
        return '<span class="range">—</span>'
    if v is None:
        return '<span class="range">none</span>'
    if isinstance(v, bool):
        return "On" if v else "Off"
    if s.get("options"):
        label = next((o["label"] for o in s["options"] if o["value"] == v), v)
        return e(str(label))
    if s["type"] == "color" and isinstance(v, str):
        return f'<span class="swatch" style="background:{e(v)}"></span>{e(v)}'
    if isinstance(v, str):
        return '<span class="range">empty</span>' if v == "" else e(v if len(v) <= 60 else v[:57] + "…")
    if isinstance(v, int | float):
        return e(str(v))
    j = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return f"<code>{e(j if len(j) <= 60 else j[:57] + '…')}</code>"


def _options_cell(s: dict[str, Any]) -> str:
    if s.get("options"):
        pills = "".join(
            f'<span class="pill{" def" if o["value"] == s.get("default") else ""}">{e(str(o["label"]))}</span>'
            for o in s["options"]
        )
        return f'<div class="opts">{pills}</div>'
    lo, hi = s.get("min"), s.get("max")
    if lo is not None or hi is not None:
        bar = ""
        d = s.get("default")
        nums = all(isinstance(x, int | float) and not isinstance(x, bool) for x in (lo, hi, d))
        if nums and hi > lo:
            pct = max(0.0, min(100.0, (d - lo) / (hi - lo) * 100))
            bar = f'<span class="range-bar" aria-hidden="true"><i style="left:{pct:.1f}%"></i></span>'
        return f'<span class="range">{e(str(lo if lo is not None else ""))} – {e(str(hi if hi is not None else ""))}</span>{bar}'
    if s.get("max_length") is not None:
        return f'<span class="range">up to {s["max_length"]} characters</span>'
    return {
        "color": '<span class="range">any colour (#rrggbb)</span>',
        "toggle": '<span class="range">on / off</span>',
        "text": '<span class="range">free text</span>',
    }.get(s["type"], '<span class="range">—</span>')


def settings_table(settings: list[dict[str, Any]]) -> str:
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in settings:
        groups.setdefault(s.get("group", ""), []).append(s)
    order = sorted(groups, key=lambda g: g != "")
    many = len(order) > 1
    rows = []
    for g in order:
        if many:
            rows.append(
                f'<tr class="group-row"><th colspan="4" scope="colgroup">{e(g or "General")}</th></tr>'
            )
        for s in groups[g]:
            desc = f'<span class="d">{e(s["description"])}</span>' if s.get("description") else ""
            rows.append(
                f'<tr><th scope="row" class="k">{e(s["title"])}<code>{e(s["key"])}</code>{desc}</th>'
                f'<td><span class="t">{e(TYPE.get(s["type"], s["type"]))}</span></td>'
                f'<td class="def-cell"><span class="v">{_fmt(s, s.get("default"), "default" not in s)}</span></td>'
                f'<td class="opt-cell">{_options_cell(s)}</td></tr>'
            )
    return (
        '<div class="table-scroll"><table class="settings-table"><caption class="sr-only">Settings</caption>'
        '<thead><tr><th scope="col">Setting</th><th scope="col">Type</th><th scope="col">Default</th>'
        f'<th scope="col">Options / range</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def code_block(label: str, cmd: str) -> str:
    return f'<div class="code"><span class="label">{e(label)}</span><pre><span class="p">$ </span>{e(cmd)}</pre></div>'


def app_page(app: dict[str, Any], data: dict[str, Any], prev: dict[str, Any], nxt: dict[str, Any]) -> str:
    cats = {c["id"]: c["label"] for c in data["categories"]}
    cat = cats[app["category"]]
    color = CAT_COLOR[app["category"]]
    k_label, _k_color, k_text = KIND[app["kind"]]
    g = app.get("game")
    badges = badge(cat, color) + "".join(badge(KIND[k][0], KIND[k][1]) for k in app["kinds"])
    if g and g["max_players"] > 1:
        badges += badge(f"{g['max_players']} players", "#ff7419")
    note = k_text
    if len(app["kinds"]) > 1:
        others = " / ".join(KIND[k][0].lower() for k in app["kinds"] if k != app["kind"])
        note = f"{k_text} Some options switch it to {others}."
    facts = [
        f'<div class="fact"><span>Output</span><b>{k_label}</b><small>{e(note)}</small></div>',
        f'<div class="fact"><span>Settings</span><b>{len(app["settings"])}</b><small>every one editable live in the '
        "studio, or by an agent with <code>update_app_settings</code></small></div>",
    ]
    if app["actions"]:
        labels = " · ".join(e(a["label"]) for a in app["actions"])
        facts.append(
            f'<div class="fact"><span>Buttons</span><b>{labels}</b><small>studio buttons, or <code>app_action</code> '
            "over MCP</small></div>"
        )
    if app.get("source"):
        facts.append(
            f'<div class="fact"><span>Source</span><b><a href="{REPO}/blob/main/{e(app["source"])}">'
            f"{e(app['source'].rsplit('/', 1)[-1])}</a></b><small>{e(app['source'])}</small></div>"
        )

    sections = [
        f'<section class="app-sec" aria-labelledby="s-glance"><h2 id="s-glance">At a glance</h2><div class="facts">{"".join(facts)}</div></section>'
    ]
    if g:
        rows = [
            f'<div class="fact"><span>Players</span><b>{f"1–{g['max_players']}" if g["max_players"] > 1 else "1"}</b>'
            + (
                "<small>seat 1 on the keyboard or studio, the rest on phones over your Wi-Fi; empty seats are "
                "played by the AI</small>"
                if g["max_players"] > 1
                else "<small>single player</small>"
            )
            + "</div>"
        ]
        if g["controls"]:
            pills = "".join(
                f'<span class="pill{" def" if i == 0 else ""}">{e(CONTROL.get(c, c))}</span>'
                for i, c in enumerate(g["controls"])
            )
            rows.append(f'<div class="fact"><span>Controllers</span><div class="pills">{pills}</div></div>')
        body = f'<div class="facts">{"".join(rows)}</div>'
        if g["modes"]:
            trs = "".join(
                f'<tr><th scope="row" class="k">{e(m["name"])}'
                f"{' <span class="tag">default</span>' if i == 0 else ''}</th>"
                f'<td class="v">{m["min_players"] if m["min_players"] == m["max_players"] else f"{m['min_players']}–{m['max_players']}"}</td>'
                f"<td>{e(TEAMS.get(m['teams'], m['teams']))}</td></tr>"
                for i, m in enumerate(g["modes"])
            )
            body += (
                '<h3>Modes</h3><div class="table-scroll"><table class="settings-table compact"><thead><tr>'
                '<th scope="col">Mode</th><th scope="col">Players</th><th scope="col">Play</th></tr></thead>'
                f"<tbody>{trs}</tbody></table></div>"
            )
        if g["maps"]:
            body += (
                '<h3>Maps</h3><div class="pills">'
                + "".join(
                    f'<span class="pill{" def" if i == 0 else ""}">{e(m["label"])}</span>'
                    for i, m in enumerate(g["maps"])
                )
                + "</div>"
            )
        if g["themes"]:
            d = next((s.get("default") for s in app["settings"] if s["key"] == "theme"), None)
            body += (
                '<h3>Themes</h3><div class="pills">'
                + "".join(
                    f'<span class="pill{" def" if t["value"] == d else ""}">{e(str(t["label"]))}</span>'
                    for t in g["themes"]
                )
                + "</div>"
            )
        sections.append(
            f'<section class="app-sec" aria-labelledby="s-game"><h2 id="s-game">Game</h2>{body}</section>'
        )

    st = (
        settings_table(app["settings"])
        if app["settings"]
        else '<p class="range">This app has no settings.</p>'
    )
    sections.append(
        f'<section class="app-sec" aria-labelledby="s-settings"><h2 id="s-settings">Settings</h2>{st}</section>'
    )

    choice = next((s for s in app["settings"] if len(s.get("options", [])) > 1), None)
    example = ""
    if choice:
        alt = next(
            (o["value"] for o in choice["options"] if o["value"] != choice.get("default")),
            choice.get("default"),
        )
        example = (
            f" --settings '{json.dumps({choice['key']: alt}, ensure_ascii=False, separators=(',', ':'))}'"
        )
    sections.append(
        '<section class="app-sec" aria-labelledby="s-try"><h2 id="s-try">Try it</h2>'
        + code_block(
            "render a frame to PNG (no panel needed)",
            f"uv run deskdot preview {app['id']}{example} --out {app['id']}.png",
        )
        + code_block(
            "show it on your panel (engine running)",
            f"curl -X POST http://127.0.0.1:8765/api/apps/{app['id']}/activate",
        )
        + f'<p class="range">Or ask your agent: “Show {e(app["name"])} on my panel”. It calls <code>show_app</code> with '
        f'<code>"{e(app["id"])}"</code>. New here? <a href="/setup.html">Set up DeskDot</a> first.</p></section>'
    )

    same = [a for a in data["apps"] if a["category"] == app["category"] and a["id"] != app["id"]]
    if same:
        start = next((i for i, a in enumerate(data["apps"]) if a["id"] == app["id"]), 0)
        same.sort(key=lambda a: (data["apps"].index(a) - start) % len(data["apps"]))
        more = "".join(app_card(a, cat, searchable=False) for a in same[:4])
        sections.append(
            f'<section class="app-sec" aria-labelledby="s-more"><h2 id="s-more">More {e(cat.lower())} apps</h2>'
            f'<div class="app-grid small">{more}</div></section>'
        )

    pager = (
        '<nav class="pager" aria-label="Previous and next app">'
        f'<a class="btn" href="/{prev["page"]}" rel="prev"><svg aria-hidden="true"><use href="#i-back"/></svg>'
        f"<span><small>Previous</small>{e(prev['name'])}</span></a>"
        '<a class="btn" href="/apps.html">All apps</a>'
        f'<a class="btn next" href="/{nxt["page"]}" rel="next"><span><small>Next</small>{e(nxt["name"])}</span>'
        '<svg aria-hidden="true"><use href="#i-arrow"/></svg></a></nav>'
    )
    src_btn = (
        f'<a class="btn" href="{REPO}/blob/main/{e(app["source"])}"><svg aria-hidden="true"><use href="#i-gh"/></svg>View source</a>'
        if app.get("source")
        else ""
    )
    body = f"""<div class="wrap page app-page">
<nav class="crumbs" aria-label="Breadcrumb"><ol><li><a href="/apps.html">Apps</a></li><li><a href="/apps.html#cat={app["category"]}">{e(cat)}</a></li><li><span aria-current="page">{e(app["name"])}</span></li></ol></nav>
<div class="app-hero">
  <div class="device small">{panel(app, eager=True, cls="panel big")}<div class="device-label"><span>32×32 · {e(k_label)}</span><span>real render</span></div></div>
  <div>
    <div class="badges">{badges}</div>
    <h1>{e(app["name"])}</h1>
    <p class="lede">{e(app["description"])}</p>
    <div class="cta"><a class="btn primary" href="/setup.html">Put it on your panel <svg aria-hidden="true"><use href="#i-arrow"/></svg></a>{src_btn}</div>
  </div>
</div>
{"".join(sections)}
{pager}
</div>"""
    desc = f"{app['description']} A {cat.lower()} app for the iDotMatrix 32×32 LED panel, with {len(app['settings'])} settings."
    crumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Apps", "item": _url("apps.html")},
            {"@type": "ListItem", "position": 2, "name": app["name"], "item": _url(app["page"])},
        ],
    }
    og = f"/{app['og_image']}" if app.get("og_image") else "/media/og.png"
    head_html = head(
        app["page"],
        f"{app['name']}: {cat} app for iDotMatrix",
        desc,
        og_image=og,
        og_size=(480, 480) if app.get("og_image") else (1200, 630),
        og_alt=f"{app['name']} on a 32×32 LED panel",
        jsonld=[crumbs],
        og_type="article",
    )
    return document(app["page"], head_html, "apps", body)


# =============================================================================================== hand pages
def fill(body: str, name: str, content: str) -> str:
    pat = re.compile(rf"(<!-- gen:{name} -->)(.*?)(<!-- /gen:{name} -->)", re.S)
    if not pat.search(body):
        return body
    return pat.sub(lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", body)


def counts(data: dict[str, Any]) -> dict[str, str]:
    return {
        "apps": str(data["count"]),
        "games": str(data["games"]),
        "multiplayer": str(data["multiplayer"]),
        "settings": f"{sum(len(a['settings']) for a in data['apps']):,}",
        "categories": str(len(data["categories"])),
    }


def refresh_counts(body: str, nums: dict[str, str]) -> str:
    pat = re.compile(r'(<(\w+)\b[^>]*\bdata-count="(\w+)"[^>]*>)([^<]*)(</\2>)')
    return pat.sub(lambda m: m.group(1) + nums.get(m.group(3), m.group(4)) + m.group(5), body)


def faq_jsonld(body: str) -> dict[str, Any] | None:
    items = []
    for q, a in re.findall(r"<summary>(.*?)</summary>\s*<div class=\"a\">(.*?)</div>", body, re.S):
        text = re.sub(r"<[^>]+>", "", a)
        items.append(
            {
                "@type": "Question",
                "name": html.unescape(re.sub(r"<[^>]+>", "", q)).strip(),
                "acceptedAnswer": {"@type": "Answer", "text": " ".join(html.unescape(text).split())},
            }
        )
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": items} if items else None


SOFTWARE_LD = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": BRAND,
    "url": f"{SITE_URL}/",
    "applicationCategory": "UtilitiesApplication",
    "operatingSystem": "Windows, Linux, macOS, Android (beta)",
    "description": "An engine, studio and MCP server that turns an iDotMatrix 32×32 LED panel into a live desktop companion.",
    "license": "https://opensource.org/licenses/MIT",
    "author": {"@type": "Person", "name": "Shiv Patel", "url": "https://github.com/shivpatel2468"},
    "codeRepository": REPO,
    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
}


def build_hand_page(name: str, data: dict[str, Any]) -> str:
    path = SITE / name
    src = path.read_text(encoding="utf-8")
    if START not in src or END not in src:
        raise SystemExit(f"{path}: missing {START} / {END} markers")
    body = src.split(START, 1)[1].split(END, 1)[0]
    meta = PAGES[name]
    nums = counts(data)
    cats = {c["id"]: c["label"] for c in data["categories"]}
    by_id = {a["id"]: a for a in data["apps"]}

    cards = "\n".join(app_card(a, cats[a["category"]], i=i) for i, a in enumerate(data["apps"]))
    body = fill(body, "cards", cards)
    chips = [
        f'<button type="button" class="chip" data-cat="all" aria-pressed="true" style="--c:#f3f1ec"><i></i>All <small>{data["count"]}</small></button>'
    ]
    chips += [
        f'<button type="button" class="chip" data-cat="{c["id"]}" aria-pressed="false" style="--c:{CAT_COLOR[c["id"]]}"><i></i>{e(c["label"])} <small>{c["count"]}</small></button>'
        for c in data["categories"]
    ]
    chips.append('<span class="sep" aria-hidden="true"></span>')
    chips += [
        '<button type="button" class="chip" data-flag="multiplayer" aria-pressed="false" style="--c:#ff7419"><i></i>Multiplayer</button>',
        '<button type="button" class="chip" data-flag="clip" aria-pressed="false" style="--c:#5cf2a0"><i></i>Baked loops</button>',
    ]
    body = fill(body, "chips", "\n".join(chips))
    featured = [by_id[i] for i in FEATURED if i in by_id]
    body = fill(
        body,
        "featured",
        "\n".join(app_card(a, cats[a["category"]], i=i, searchable=False) for i, a in enumerate(featured)),
    )
    games = sorted(
        (a for a in data["apps"] if a.get("game", {}).get("max_players", 1) > 1),
        key=lambda a: -a["game"]["max_players"],
    )
    body = fill(
        body,
        "games",
        "\n".join(app_card(a, cats[a["category"]], i=i, searchable=False) for i, a in enumerate(games[:8])),
    )
    body = refresh_counts(body, nums)

    desc = meta["description"].format(**nums)
    title = meta["title"].format(**nums)
    ld: list[dict[str, Any]] = []
    if name == "index.html":
        ld.append(SOFTWARE_LD)
    if name == "faq.html":
        fq = faq_jsonld(body)
        if fq:
            ld.append(fq)
    head_html = head(name, title, desc, noindex=meta.get("noindex", False), jsonld=ld)
    return document(name, head_html, meta["nav"], body, body_class=f"page-{name.removesuffix('.html')}")


# =============================================================================================== static extras
FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#08070a"/><g fill="#ff3f78"><circle cx="8" cy="7" r="2.4"/><circle cx="8" cy="15" r="2.4"/><circle cx="8" cy="21" r="2.4"/><circle cx="8" cy="27" r="2.4"/></g><g fill="#ff7419"><circle cx="16" cy="15" r="2.4"/><circle cx="16" cy="21" r="2.4"/><circle cx="16" cy="27" r="2.4"/></g><g fill="#ffcc33"><circle cx="24" cy="15" r="2.4"/><circle cx="24" cy="21" r="2.4"/><circle cx="24" cy="27" r="2.4"/></g></svg>
"""


def write_icons() -> None:
    from PIL import Image, ImageDraw

    (SITE / "favicon.svg").write_text(FAVICON, encoding="utf-8")
    dots = [(8, 7, "#ff3f78"), (8, 15, "#ff3f78"), (8, 21, "#ff3f78"), (8, 27, "#ff3f78")]
    dots += [(16, y, "#ff7419") for y in (15, 21, 27)] + [(24, y, "#ffcc33") for y in (15, 21, 27)]

    def icon(size: int, radius: float) -> Image.Image:
        k = size / 32
        im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius * k, fill="#08070a")
        for x, y, c in dots:
            d.ellipse([(x - 2.4) * k, (y - 2.4) * k, (x + 2.4) * k, (y + 2.4) * k], fill=c)
        return im

    icon(180, 0).convert("RGB").save(SITE / "apple-touch-icon.png", optimize=True)
    icon(512, 7).save(SITE / "icon-512.png", optimize=True)
    icon(192, 7).save(SITE / "icon-192.png", optimize=True)
    icon(64, 7).save(SITE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    manifest = {
        "name": f"{BRAND} for iDotMatrix",
        "short_name": BRAND,
        "start_url": "/",
        "display": "browser",
        "background_color": "#08070a",
        "theme_color": "#08070a",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (SITE / "site.webmanifest").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")


def write_sitemap(paths: list[str]) -> None:
    today = date.today().isoformat()
    urls = "".join(
        f"  <url><loc>{_url(p)}</loc><lastmod>{today}</lastmod>"
        f"<priority>{'1.0' if p == 'index.html' else '0.8' if '/' not in p else '0.6'}</priority></url>\n"
        for p in paths
    )
    (SITE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n",
        encoding="utf-8",
    )
    (SITE / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8"
    )


# =============================================================================================== link checker
class _Links(HTMLParser):
    ATTRS: ClassVar[set[str]] = {"href", "src", "srcset", "poster"}

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for k, v in attrs:
            if v is None:
                continue
            if k == "id":
                self.ids.add(v)
            elif k in self.ATTRS:
                if k == "srcset":
                    self.links += [part.strip().split(" ")[0] for part in v.split(",") if part.strip()]
                elif not (tag == "link" and k == "href" and v.startswith("https://fonts.")):
                    self.links.append(v)


def _parse(path: Path) -> _Links:
    p = _Links()
    p.feed(path.read_text(encoding="utf-8"))
    return p


def check_links(site: Path = SITE) -> list[str]:
    """Every internal href/src in every page must resolve to a file in site/ (and #fragments to an id)."""
    errors: list[str] = []
    parsed = {f: _parse(f) for f in sorted(site.rglob("*.html"))}
    for page, p in parsed.items():
        rel = page.relative_to(site).as_posix()
        for link in p.links:
            u = urlsplit(link)
            if u.scheme or link.startswith("//"):
                if u.scheme not in ("http", "https", "mailto", "data"):
                    errors.append(f"{rel}: unexpected scheme in {link}")
                continue
            if not u.path:  # same-page fragment
                frag = unquote(u.fragment)
                if frag and "=" not in frag and frag not in p.ids:
                    errors.append(f"{rel}: #{frag} has no target")
                continue
            target = (site / u.path.lstrip("/")) if u.path.startswith("/") else (page.parent / u.path)
            target = Path(unquote(str(target)))
            if u.path.endswith("/"):
                target = target / "index.html"
            if not target.exists():
                errors.append(f"{rel}: broken link {link}")
                continue
            frag = unquote(u.fragment)
            if frag and "=" not in frag and target.suffix == ".html":
                ids = parsed.get(target.resolve()) or _parse(target)
                if frag not in ids.ids:
                    errors.append(f"{rel}: {link} — no #{frag} there")
    return errors


# =============================================================================================== main
def build() -> list[str]:
    data = json.loads((SITE / "apps.json").read_text(encoding="utf-8"))
    written: list[str] = []
    for name in PAGES:
        (SITE / name).write_text(build_hand_page(name, data), encoding="utf-8", newline="\n")
        written.append(name)
    out = SITE / "apps"
    out.mkdir(exist_ok=True)
    keep = set()
    apps = data["apps"]
    for i, a in enumerate(apps):
        page = app_page(a, data, apps[i - 1], apps[(i + 1) % len(apps)])
        (SITE / a["page"]).write_text(page, encoding="utf-8", newline="\n")
        keep.add((SITE / a["page"]).name)
        written.append(a["page"])
    for stale in out.glob("*.html"):
        if stale.name not in keep:
            stale.unlink()
    write_icons()
    write_sitemap([p for p in written if p != "404.html"])
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="only check internal links")
    args = ap.parse_args(argv)
    if not args.check:
        written = build()
        print(f"wrote {len(written)} pages, sitemap.xml, robots.txt, icons", file=sys.stderr)
    errors = check_links()
    for err in errors:
        print("LINK", err, file=sys.stderr)
    print(f"link check: {len(errors)} problem(s)", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
