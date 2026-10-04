"""Build the DeskDot web app into site/app/ (served at https://idotmatrix.com/app/ by Netlify).

    uv run python scripts/build_webapp.py              # studio + engine + host → site/app/
    uv run python scripts/build_webapp.py --skip-studio  # reuse the last studio build (engine/host changes only)

What it produces (docs/WEB_APP.md):

    site/app/index.html            the studio (Vite build with base /app/), plus host/host.js injected first
    site/app/assets/…              the studio's hashed JS/CSS/fonts
    site/app/host/host.{js,css}    page host: fetch/WebSocket shims, Web Bluetooth bridge, landing card
    site/app/engine/worker.js      the engine worker (Pyodide)
    site/app/engine/deskdot-<hash>.zip   the deskdot package (desktop-only modules left out)
    site/app/engine/*.whl          pure-Python wheels Pyodide doesn't ship (python-multipart)
    site/app/engine/manifest.json  what the worker loads: Pyodide version/CDN, packages, archive names
    site/app/sw.js                 service worker (API routing for <img>, offline cache)
    site/app/join/…                the phone join page served at /p/<code> (online play with friends, WebRTC):
                                   index.html + join.{js,css}, and the engine's phone pages (controller.html,
                                   casino.html) with their inline script moved to <kind>.js (the page's CSP)

Pyodide itself and its packages (numpy, Pillow, pydantic, FastAPI…) load from the official CDN, pinned below.
The normal desktop build (web/dist) is not touched.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "deskdot"
WEB = ROOT / "web"
HOST_SRC = WEB / "webapp"
OUT = ROOT / "site" / "app"
CACHE = ROOT / "tmp" / "webapp-cache"

# Pinned: Pyodide 0.29.5 = CPython 3.13.2 (the engine's tested version), numpy 2.2.5, Pillow 11.3, pydantic 2.12.5
# (pydantic-core 2.41.5), FastAPI 0.116.1 / Starlette 0.47.2, httpx 0.28.1. Changing it: re-run the checks in
# docs/WEB_APP.md ("Upgrading Pyodide").
PYODIDE_VERSION = "0.29.5"
PYODIDE_PYTHON = "3.13"
PYODIDE_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
# Pyodide distribution packages the engine imports (their dependencies load automatically, except httpx's:
# Pyodide's lock lists none for httpx, so httpcore & co. are named explicitly).
PACKAGES = [
    "numpy",
    "pillow",
    "pydantic",
    "fastapi",
    "httpx",
    "httpcore",
    "h11",
    "certifi",
    "idna",
    "tzdata",
]
# pure-Python wheels from PyPI that Pyodide doesn't ship: vendored next to the engine (same version as uv.lock)
PYPI_WHEELS = ["python-multipart"]

# Desktop-only modules: never imported in the browser (entry points, the tray launcher, the MCP server, bleak).
EXCLUDE = {
    "launcher.py",
    "mcp_server.py",
    "cli.py",
    "__main__.py",
    "android_main.py",
    "device/ble.py",
}


def log(msg: str) -> None:
    print(f"[webapp] {msg}", flush=True)


def locked_version(name: str) -> str:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    for pkg in lock.get("package", []):
        if pkg.get("name") == name:
            return str(pkg["version"])
    raise SystemExit(f"{name} isn't in uv.lock")


def pypi_wheel(name: str, dest: Path) -> str:
    """Download the pure-Python wheel of `name` at the uv.lock version; returns its file name."""
    version = locked_version(name)
    CACHE.mkdir(parents=True, exist_ok=True)
    info = json.loads(
        urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30).read()
    )
    wheel = next(
        (
            u
            for u in info["urls"]
            if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("-none-any.whl")
        ),
        None,
    )
    if wheel is None:
        raise SystemExit(f"{name} {version} has no pure-Python wheel")
    cached = CACHE / wheel["filename"]
    if not cached.exists():
        log(f"downloading {wheel['filename']}")
        cached.write_bytes(urllib.request.urlopen(wheel["url"], timeout=60).read())
    if hashlib.sha256(cached.read_bytes()).hexdigest() != wheel["digests"]["sha256"]:
        cached.unlink()
        raise SystemExit(f"{wheel['filename']}: checksum mismatch")
    shutil.copy2(cached, dest / wheel["filename"])
    return str(wheel["filename"])


def engine_zip(sources: bool = False) -> bytes:
    """src/deskdot as a zip of byte-code (deterministic order and timestamps).

    Compiling ~2.6 MB of source inside WebAssembly took most of the start-up (~6 s of ~10 s), so the package ships
    as sourceless .pyc (legacy layout: foo.pyc next to where foo.py was). Pyodide 0.29 is CPython 3.13, the same
    byte-code as this interpreter (checked in main()). `sources=True` ships the .py files instead (debugging).
    """
    import importlib.util
    import marshal

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(SRC.rglob("*")):
            rel = path.relative_to(SRC).as_posix()
            if path.is_dir() or "__pycache__" in rel or rel.endswith((".pyc", ".pyo")) or rel in EXCLUDE:
                continue
            data = path.read_bytes()
            name = f"deskdot/{rel}"
            if rel.endswith(".py") and not sources:
                code = compile(data, f"/deskdot/{rel}", "exec", dont_inherit=True, optimize=0)
                # PEP 552 header: magic, flags=0b01 (hash-based, unchecked), 8-byte source hash, then the code
                header = importlib.util.MAGIC_NUMBER + (1).to_bytes(4, "little")
                data = header + importlib.util.source_hash(data) + marshal.dumps(code)
                name = name[:-3] + ".pyc"
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


def build_studio(dest: Path) -> None:
    env = {**os.environ, "DESKDOT_WEBAPP": "1"}
    with tempfile.TemporaryDirectory(prefix="deskdot-webapp-") as tmp:
        out = Path(tmp) / "dist"
        cmd = ["npx", "vite", "build", "--outDir", str(out), "--emptyOutDir", "--logLevel", "warn"]
        log("building the studio (vite, base /app/)")
        subprocess.run(cmd, cwd=WEB, env=env, check=True, shell=sys.platform == "win32")
        for item in out.iterdir():
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)


def inject_host(index: Path, build: str) -> None:
    html = index.read_text(encoding="utf-8")
    # --skip-studio keeps the previous (already injected) page: drop the old injection first
    html = re.sub(
        r'\s*<meta name="description"[^>]*>|\s*<link rel="manifest"[^>]*>|\s*<script src="/app/host/host\.js[^>]*></script>',
        "",
        html,
    )
    tag = f'<script src="/app/host/host.js?v={build}"></script>'
    html = re.sub(
        r"<title>.*?</title>", "<title>DeskDot in your browser — iDotMatrix studio</title>", html, count=1
    )
    head_extra = (
        '<meta name="description" content="Drive your iDotMatrix 32×32 LED panel from the browser over Web '
        'Bluetooth: the full DeskDot studio and engine, no install." />\n    '
        '<link rel="manifest" href="/app/manifest.webmanifest" />\n    '
        f"{tag}\n    "
    )
    # the host must run before the studio's module script (it installs the fetch / WebSocket shims)
    html = html.replace('<script type="module"', head_extra + '<script type="module"', 1)
    if tag not in html:
        raise SystemExit("couldn't inject the host script into index.html")
    index.write_text(html, encoding="utf-8")


#: the engine's phone pages, rebuilt for the join page (/p/<code> on the website): the script moves to a file
#: because the website's CSP allows no inline script
PHONE_PAGES = {"controller": SRC / "controller.html", "casino": SRC / "casino.html"}


def split_phone_page(html: str, kind: str, build: str) -> tuple[str, str]:
    """(page with `<script src=/app/join/<kind>.js>`, the script) from one engine phone page."""
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    if len(scripts) != 1:
        raise SystemExit(f"{kind}.html: expected exactly one inline <script>")
    tag = f'<script src="/app/join/{kind}.js?v={build}"></script>'
    page = html.replace(f"<script>{scripts[0]}</script>", tag, 1)
    if re.search(r"<[^>]*\son[a-z]+\s*=", page.replace(tag, "")) or "javascript:" in page:
        raise SystemExit(f"{kind}.html: inline event handlers can't run under the join page's CSP")
    return page, scripts[0].strip("\n") + "\n"


def build_join(dest: Path, build: str) -> None:
    """The phone join page (web/webapp/join/) + the engine's phone pages, into site/app/join/."""
    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted((HOST_SRC / "join").iterdir()):
        if src.is_file():
            data = src.read_text(encoding="utf-8")
            (dest / src.name).write_text(data.replace("__BUILD__", build), encoding="utf-8")
    for kind, src in PHONE_PAGES.items():
        page, script = split_phone_page(src.read_text(encoding="utf-8"), kind, build)
        (dest / f"{kind}.html").write_text(page, encoding="utf-8")
        (dest / f"{kind}.js").write_text(script, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-studio", action="store_true", help="keep the studio files already in site/app/")
    ap.add_argument(
        "--sources", action="store_true", help="ship .py sources instead of byte-code (debugging)"
    )
    a = ap.parse_args()
    if sys.version_info[:2] != tuple(int(x) for x in PYODIDE_PYTHON.split(".")):
        raise SystemExit(
            f"run with Python {PYODIDE_PYTHON} (Pyodide's byte-code version), not {sys.version.split()[0]}"
        )
    t0 = time.time()

    studio_keep: dict[str, bytes] = {}
    if a.skip_studio:
        if not (OUT / "index.html").exists():
            raise SystemExit("no previous studio build in site/app/; run without --skip-studio")
        for p in OUT.rglob("*"):
            rel = p.relative_to(OUT).as_posix()
            if p.is_file() and (rel == "index.html" or rel.startswith("assets/") or rel == "favicon.svg"):
                studio_keep[rel] = p.read_bytes()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "engine").mkdir(parents=True)
    (OUT / "host").mkdir()

    if a.skip_studio:
        for rel, data in studio_keep.items():
            (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
            (OUT / rel).write_bytes(data)
    else:
        build_studio(OUT)

    engine = engine_zip(sources=a.sources)
    digest = hashlib.sha256(engine).hexdigest()[:12]
    engine_name = f"deskdot-{digest}.zip"
    (OUT / "engine" / engine_name).write_bytes(engine)
    wheels = [pypi_wheel(name, OUT / "engine") for name in PYPI_WHEELS]

    host_files = {
        "host/host.js": HOST_SRC / "host.js",
        "host/host.css": HOST_SRC / "host.css",
        "engine/worker.js": HOST_SRC / "worker.js",
        # add-ons host.js loads itself: online play (WebRTC), camera / screen / mic capture
        **{f"host/{f.name}": f for f in sorted(HOST_SRC.glob("host-*.js"))},
    }
    h = hashlib.sha256(engine)
    for rel, src in host_files.items():
        data = src.read_bytes()
        h.update(data)
        (OUT / rel).write_bytes(data)
    for src in [*sorted((HOST_SRC / "join").iterdir()), *PHONE_PAGES.values()]:
        if src.is_file():
            h.update(src.read_bytes())
    build = h.hexdigest()[:12]
    build_join(OUT / "join", build)

    sw = (HOST_SRC / "sw.js").read_text(encoding="utf-8")
    sw = sw.replace("__BUILD__", build).replace("__PYODIDE_URL__", PYODIDE_URL)
    (OUT / "sw.js").write_text(sw, encoding="utf-8")

    sys.path.insert(0, str(ROOT / "src"))
    from deskdot import __version__

    manifest = {
        "version": __version__,
        "build": build,
        "engine": engine_name,
        "wheels": wheels,
        "packages": PACKAGES,
        "pyodide": {"version": PYODIDE_VERSION, "python": PYODIDE_PYTHON, "indexURL": PYODIDE_URL},
        "proxy": "/app/proxy",
    }
    (OUT / "engine" / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(
        json.dumps(
            {
                "name": "DeskDot",
                "short_name": "DeskDot",
                "description": "The iDotMatrix 32×32 panel studio, in your browser",
                "start_url": "/app/",
                "scope": "/app/",
                "display": "standalone",
                "background_color": "#08080a",
                "theme_color": "#0c0c0f",
                "icons": [
                    {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    inject_host(OUT / "index.html", build)

    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    log(f"engine archive {engine_name}: {len(engine) / 1024:.0f} KB; wheels: {', '.join(wheels)}")
    log(f"site/app: {total / 1024 / 1024:.2f} MB in {sum(1 for p in OUT.rglob('*') if p.is_file())} files")
    log(f"Pyodide {PYODIDE_VERSION} from {PYODIDE_URL} (packages: {', '.join(PACKAGES)})")
    log(f"done in {time.time() - t0:.1f}s, build {build}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
