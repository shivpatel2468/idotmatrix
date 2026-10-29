"""idotmatrix.com is generated from the code: apps.json, one page and one real preview per app, a sitemap, no broken
links, and the DeskDot name everywhere (scripts/build_site_media.py, build_site_data.py, build_site_pages.py)."""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import deskdot.apps  # noqa: F401 — registers built-in apps
from deskdot.engine import REGISTRY

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
VISIBLE = {aid for aid, cls in REGISTRY.items() if not cls.hidden}


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _committed() -> dict[str, Any]:
    return json.loads((SITE / "apps.json").read_text(encoding="utf-8"))


def test_generator_writes_valid_json_for_every_app(tmp_path: Path) -> None:
    out = tmp_path / "apps.json"
    assert _load("build_site_data").main(["--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))

    ids = [a["id"] for a in data["apps"]]
    assert set(ids) == VISIBLE and len(ids) == len(set(ids)) == data["count"]
    assert sum(c["count"] for c in data["categories"]) == data["count"]

    for app in data["apps"]:
        assert app["name"] and app["category"] and app["kind"] in ("clip", "stream", "native")
        assert app["kind"] in app["kinds"]
        assert app["page"] == f"apps/{app['id']}.html"
        for key in ("preview", "poster", "og_image"):
            if app[key]:
                assert (SITE / app[key]).exists()
        schema_keys = set(REGISTRY[app["id"]].Settings.model_json_schema().get("properties", {}))
        assert {s["key"] for s in app["settings"]} == schema_keys
        for s in app["settings"]:
            assert s["title"] and s["type"]
            if s["type"] == "choice":
                assert s["options"] and all("label" in o for o in s["options"])
        if app["category"] == "games":
            assert app["game"]["max_players"] >= 1


def test_committed_site_data_is_current() -> None:
    """site/apps.json is what the generator makes today (re-run the scripts after adding or removing an app)."""
    assert {a["id"] for a in _committed()["apps"]} == VISIBLE


def test_every_app_has_a_real_preview_and_a_page() -> None:
    for app in _committed()["apps"]:
        aid = app["id"]
        gif = SITE / "media" / "apps" / f"{aid}.gif"
        assert gif.exists() and gif.read_bytes()[:6] in (b"GIF87a", b"GIF89a"), f"no preview for {aid}"
        assert gif.stat().st_size <= 200_000, f"{aid} preview is {gif.stat().st_size} bytes"
        assert (SITE / "media" / "apps" / f"{aid}.png").exists()
        assert (SITE / "media" / "apps" / "og" / f"{aid}.png").exists()
        page = (SITE / "apps" / f"{aid}.html").read_text(encoding="utf-8")
        assert f"/media/apps/{aid}.gif" in page
        assert f'<link rel="canonical" href="https://idotmatrix.com/apps/{aid}.html" />' in page
    explorer = (SITE / "apps.html").read_text(encoding="utf-8")
    assert all(f'href="/apps/{a}.html"' in explorer for a in VISIBLE)


PAGES = [
    "index", "setup", "guide", "apps", "features", "studio", "specs", "faq", "whats-new",
    "download", "privacy", "terms", "license", "licenses",
]  # fmt: skip
LEGAL = ("download", "privacy", "terms", "license", "licenses")  # not in the main nav


def test_pages_have_standard_head_and_chrome() -> None:
    for name in [*PAGES, "404"]:
        html = (SITE / f"{name}.html").read_text(encoding="utf-8")
        assert html.startswith("<!doctype html>") and '<html lang="en">' in html
        for needle in (
            "<title>",
            'name="description"',
            'property="og:title"',
            'property="og:image"',
            'name="twitter:card"',
            'rel="icon"',
            'class="skip" href="#main"',
            '<main id="main"',
            'class="mini-logo"',
            "/main.js",
        ):
            assert needle in html, f"{name}.html lacks {needle}"
        assert html.count("<h1") == 1, f"{name}.html needs exactly one <h1>"
        if name != "404":
            assert '<link rel="canonical"' in html
            nav = re.search(r'<nav id="nav".*?</nav>', html, re.S)
            assert nav and (name in ("index", *LEGAL) or 'aria-current="page"' in nav.group(0))
        for img in re.findall(r"<img\b[^>]*>", html):
            assert 'alt="' in img and 'width="' in img and 'height="' in img, f"{name}.html: {img}"


def test_sitemap_lists_every_page() -> None:
    xml = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    locs = set(re.findall(r"<loc>(.*?)</loc>", xml))
    expected = {"https://idotmatrix.com/"} | {
        f"https://idotmatrix.com/{p}.html" for p in PAGES if p != "index"
    }
    expected |= {f"https://idotmatrix.com/apps/{a}.html" for a in VISIBLE}
    assert locs == expected
    assert "Sitemap: https://idotmatrix.com/sitemap.xml" in (SITE / "robots.txt").read_text(encoding="utf-8")


def test_no_broken_internal_links() -> None:
    assert _load("build_site_pages").check_links(SITE) == []


def test_site_makes_no_third_party_requests_and_carries_the_legal_chrome() -> None:
    for name in [*PAGES, "404"]:
        html = (SITE / f"{name}.html").read_text(encoding="utf-8")
        assert "fonts.googleapis" not in html and "fonts.gstatic" not in html, name
        assert 'id="notice"' in html and 'href="/privacy.html"' in html and 'href="/terms.html"' in html, name
        title = re.search(r"<title>(.*?)</title>", html).group(1)
        assert not title.startswith("iDotMatrix") and "for your iDotMatrix" not in title, name
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S).group(1)
        assert "iDotMatrix" not in h1, name
    assert "api.github.com" not in (SITE / "main.js").read_text(encoding="utf-8")
    assert (SITE / "fonts" / "OFL.txt").exists()
    for app in _committed()["apps"]:
        if app["category"] == "casino":
            page = (SITE / "apps" / f"{app['id']}.html").read_text(encoding="utf-8")
            assert 'class="casino-note"' in page and "Play money only" in page, app["id"]


def test_site_says_deskdot_not_dotdeck() -> None:
    for f in SITE.rglob("*"):
        if f.is_relative_to(SITE / "app"):
            continue  # the web app's studio bundle still reads the old `dotdeck.*` localStorage keys (migration)
        if f.name == "whats-new.html":
            continue  # the 3.3.0 notes tell the story of the rename ("it was called DotDeck")
        if f.suffix in (".html", ".js", ".css", ".json", ".xml", ".txt", ".webmanifest", ".svg"):
            assert "dotdeck" not in f.read_text(encoding="utf-8").lower(), f


def test_netlify_config_matches_the_site() -> None:
    cfg = tomllib.loads((ROOT / "netlify.toml").read_text(encoding="utf-8"))
    assert cfg["build"]["publish"] == "site"
    csps = {
        h["for"]: h["values"]["Content-Security-Policy"]
        for h in cfg["headers"]
        if "Content-Security-Policy" in h["values"]
    }
    # The website's pages share one policy; the web app (/app/*) has its own (Pyodide from the CDN, wasm, a
    # worker, live data APIs). No rule may match both, or Netlify would send two policies and both would apply.
    assert "/*" not in csps
    site = csps["/:page"]
    for pattern in ("/", "/apps/*", "/media/*"):
        assert csps[pattern] == site, pattern
    assert _load("build_site_pages").csp_hash() in site  # the inline <script> is allowed by its hash
    # No third-party requests from the website: fonts are self-hosted, the GitHub star count is baked at build time.
    assert "font-src 'self'" in site and "connect-src 'self';" in site
    assert "googleapis" not in site and "gstatic" not in site and "api.github.com" not in site
    app = csps["/app/*"]
    assert "'wasm-unsafe-eval'" in app and "https://cdn.jsdelivr.net" in app and "worker-src 'self'" in app
    assert (SITE / "404.html").exists() and (SITE / "CNAME").read_text().strip() == "idotmatrix.com"


def test_site_themes_mirror_the_studio() -> None:
    """Light / dark / auto and all 21 page themes: applied before first paint, styled, and offered in the menu."""
    pages = _load("build_site_pages")
    assert "deskdot.theme" in pages.INLINE_JS and "deskdot.pageTheme" in pages.INLINE_JS
    from deskdot.gfx.themes import PAGE_THEMES

    css = (SITE / "styles.css").read_text(encoding="utf-8")
    index = (SITE / "index.html").read_text(encoding="utf-8")
    for tid in PAGE_THEMES:
        assert f'data-page-theme-pick="{tid}"' in index, tid
        if tid != "ember":
            assert f':root[data-page-theme="{tid}"][data-theme="light"]' in css, tid
    assert ':root[data-theme="light"]' in css and "prefers-reduced-transparency" in css
