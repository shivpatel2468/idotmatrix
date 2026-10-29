"""Legal copy and notices shared by every page of idotmatrix.com (used by scripts/build_site_pages.py).

One place for: the owner line, the contact address, the "unofficial" wording, the casino banner, the licence line,
and the open-source licence inventory behind /licenses.html (read at build time from web/node_modules, the
Python environment and the fonts this site self-hosts).
"""

from __future__ import annotations

import html
import importlib.metadata as md
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# The real address replaces this token before a deploy (never a work address).
CONTACT_EMAIL = "shiv.patel1.3.2003@gmail.com"
OWNER = "Shiv Patel"
COUNTRY = "India"
YEAR = 2026
UPDATED = "29 October 2026"

UNOFFICIAL = (
    "Unofficial: DeskDot is not made, endorsed or supported by Shenzhen Heaton Technology or the iDotMatrix brand. "
    "Official app: iDotMatrix on Google Play / App Store."
)
FOOTER_TEXT = (
    f"<b>DeskDot™</b> is an independent product by {OWNER}, {COUNTRY}. <b>Unofficial:</b> not made, endorsed or "
    "supported by Shenzhen Heaton Technology Co., Ltd. or the iDotMatrix brand. “iDotMatrix” is a trademark of its "
    "owner and is used only to describe compatible panels. All other trademarks belong to their owners."
)
LICENCE_LINE = (
    "DeskDot versions up to v3.2 were published under the MIT licence and remain so. Future versions will be "
    "proprietary software licensed under the DeskDot EULA."
)
CASINO_BANNER = (
    "<b>Play money only.</b> No purchases, no cash-out, no prizes, no real-money betting. 18+. "
    "Credits reset with the session."
)
CASINO_FREE = "Casino games are free in every plan. Paid plans never add, refill or change casino chips."
CASINO_EDGE = "House-edge and RTP figures are shown as educational statistics (play chips; for learning how house edge works)."
VERIFIABLE = (
    "<b>Verifiable shuffle:</b> each round's seed hash is shown before chips are placed and revealed afterwards, so "
    "anyone can check the result wasn't changed. The host can still reset or adjust play chips."
)


def e(s: str) -> str:
    return html.escape(s, quote=False).replace('"', "&quot;")


# =============================================================================================== licences (L28)
WEB = ROOT / "web"
NODE = WEB / "node_modules"
PYODIDE_VERSION = "0.29.5"  # keep in step with scripts/build_webapp.py
# Python packages the browser engine loads from Pyodide (scripts/build_webapp.py PACKAGES + their dependencies)
# plus the vendored python-multipart wheel.
PY_PACKAGES = [
    "numpy",
    "pillow",
    "pydantic",
    "pydantic-core",
    "annotated-types",
    "typing-extensions",
    "typing-inspection",
    "fastapi",
    "starlette",
    "anyio",
    "httpx",
    "httpcore",
    "h11",
    "certifi",
    "idna",
    "tzdata",
    "python-multipart",
]
# Reference texts for licence families (the full text ships once; per-package notices are listed with each package).
TEXT_SOURCES = {
    "MPL-2.0": [
        ".venv/Lib/site-packages/pathspec-*.dist-info/licenses/LICENSE",
        ".venv/lib/python*/site-packages/pathspec-*.dist-info/licenses/LICENSE",
    ],
}
UPSTREAM = {
    "pyodide": "https://github.com/pyodide/pyodide",
    "certifi": "https://github.com/certifi/python-certifi",
}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace").strip()


def _npm_packages() -> list[dict[str, Any]]:
    """The web app's runtime dependencies (web/package.json `dependencies`, plus react-dom's scheduler)."""
    deps = list(json.loads((WEB / "package.json").read_text(encoding="utf-8"))["dependencies"])
    if "react-dom" in deps:
        deps.append("scheduler")
    out = []
    for name in deps:
        if name.startswith("@fontsource"):
            continue  # listed as fonts
        d = NODE / name
        pkg = json.loads((d / "package.json").read_text(encoding="utf-8"))
        lic = next(
            (f for f in sorted(d.iterdir()) if f.name.lower().startswith(("license", "licence", "copying"))),
            None,
        )
        repo = pkg.get("repository")
        url = repo.get("url") if isinstance(repo, dict) else repo
        url = (url or pkg.get("homepage") or f"https://www.npmjs.com/package/{name}").removeprefix("git+")
        url = url.removesuffix(".git").replace("git://", "https://").replace("ssh://git@", "https://")
        if not url.startswith("http"):
            url = f"https://www.npmjs.com/package/{name}"
        out.append(
            {
                "name": name,
                "version": pkg.get("version", ""),
                "license": pkg.get("license", "see text"),
                "url": url,
                "text": _read(lic) if lic else "",
                "where": "web app (/app/)",
            }
        )
    return out


def _py_packages() -> list[dict[str, Any]]:
    out = []
    for name in PY_PACKAGES:
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        meta = dist.metadata
        lic = meta.get("License-Expression") or (meta.get("License") or "").split("\n")[0] or "see text"
        files = [f for f in dist.files or [] if "licenses/" in str(f).replace("\\", "/")]
        main = sorted(files, key=lambda f: (str(f).count("/"), str(f)))
        text = _read(Path(dist.locate_file(main[0]))) if main else ""
        url = next(
            (
                v.split(",", 1)[1].strip()
                for v in meta.get_all("Project-URL") or []
                if "source" in v.split(",", 1)[0].lower()
            ),
            meta.get("Home-page") or f"https://pypi.org/project/{name}/",
        )
        out.append(
            {
                "name": name,
                "version": "",
                "license": lic,
                "url": url,
                "text": text,
                "where": f"browser engine (as distributed by Pyodide {PYODIDE_VERSION})",
            }
        )
    return out


def _cpython_licence() -> str:
    base = Path(sys.base_prefix)
    ver = f"python{sys.version_info[0]}.{sys.version_info[1]}"
    for p in (base / "LICENSE.txt", base / "lib" / ver / "LICENSE.txt"):
        if p.exists():
            return _read(p)
    return ""


def _glob_text(patterns: list[str]) -> str:
    for pat in patterns:
        for p in sorted(ROOT.glob(pat)):
            return _read(p)
    return ""


def licence_inventory() -> list[dict[str, Any]] | None:
    """Every third-party component the public website and the web app ship or load, with its licence text.
    None when the build inputs (web/node_modules) are missing: the committed page is then left as it is."""
    if not NODE.exists():
        return None
    fonts = [
        {
            "name": "Bricolage Grotesque (font)",
            "version": "",
            "license": "OFL-1.1",
            "url": "https://github.com/ateliertriay/bricolage",
            "text": _read(NODE / "@fontsource-variable" / "bricolage-grotesque" / "LICENSE"),
            "where": "website and web app (self-hosted; OFL.txt ships next to the font files)",
        },
        {
            "name": "Martian Mono (font)",
            "version": "",
            "license": "OFL-1.1",
            "url": "https://github.com/evilmartians/mono",
            "text": _read(NODE / "@fontsource" / "martian-mono" / "LICENSE"),
            "where": "website and web app (self-hosted; OFL.txt ships next to the font files)",
        },
    ]
    runtime = [
        {
            "name": "Pyodide",
            "version": PYODIDE_VERSION,
            "license": "MPL-2.0",
            "url": UPSTREAM["pyodide"],
            "text": "",
            "where": "web app: loaded unmodified from cdn.jsdelivr.net. Source code: "
            f"{UPSTREAM['pyodide']} (tag {PYODIDE_VERSION}).",
        },
        {
            "name": "CPython 3.13 (inside Pyodide)",
            "version": "",
            "license": "PSF-2.0",
            "url": "https://github.com/python/cpython",
            "text": _cpython_licence(),
            "where": "browser engine (as distributed by Pyodide)",
        },
    ]
    return [*fonts, *_npm_packages(), *runtime, *_py_packages()]


def licences_html() -> str | None:
    items = licence_inventory()
    if items is None:
        return None
    rows = "".join(
        f'<tr><th scope="row"><a href="#lic-{i}">{e(p["name"])}</a></th><td>{e(p["version"]) or "—"}</td>'
        f"<td><code>{e(p['license'])}</code></td><td>{e(p['where'])}</td></tr>"
        for i, p in enumerate(items)
    )
    table = (
        '<div class="table-scroll"><table class="data-table lic-table"><caption>Components</caption><thead><tr>'
        '<th scope="col">Component</th><th scope="col">Version</th><th scope="col">Licence</th>'
        f'<th scope="col">Where</th></tr></thead><tbody>{rows}</tbody></table></div>'
    )
    mpl = _glob_text(TEXT_SOURCES["MPL-2.0"])
    blocks = []
    for i, p in enumerate(items):
        body = (
            f"<pre>{e(p['text'])}</pre>"
            if p["text"]
            else '<p>Licence text: <a href="#text-MPL-2.0">MPL-2.0, below</a>.</p>'
            if mpl
            else '<p>Licence text: <a href="https://www.mozilla.org/en-US/MPL/2.0/">MPL-2.0</a>.</p>'
        )
        blocks.append(
            f'<details class="lic" id="lic-{i}"><summary>{e(p["name"])} <code>{e(p["license"])}</code></summary>'
            f'<div class="a"><p><a href="{e(p["url"])}">{e(p["url"])}</a></p>{body}</div></details>'
        )
    full = ""
    if mpl:
        full = (
            '<h2 id="text-MPL-2.0">Mozilla Public License 2.0 (full text)</h2>'
            "<p>Pyodide and certifi are used unmodified; their source code is available upstream "
            f'(<a href="{UPSTREAM["pyodide"]}">Pyodide</a>, <a href="{UPSTREAM["certifi"]}">certifi</a>).</p>'
            f'<details class="lic"><summary>Show the MPL-2.0 text</summary><div class="a"><pre>{e(mpl)}</pre></div></details>'
        )
    return (
        table
        + '<h2 id="texts">Licence texts</h2><div class="faq lic-list">'
        + "".join(blocks)
        + "</div>"
        + full
    )
