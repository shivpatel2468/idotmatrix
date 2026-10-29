"""Build site/apps.json: every app in the library with its settings, for the Apps explorer on idotmatrix.com.

    uv run python scripts/build_site_data.py            # writes site/apps.json
    uv run python scripts/build_site_data.py --out x.json

The whole site, in order: build_site_media.py (app previews, slow) → build_site_data.py (this) →
build_site_pages.py (every HTML page, sitemap, link check).

The shape mirrors what the studio gets from /api/meta (src/deskdot/server.py), flattened into a list of settings
per app so a static page can render it without a JSON-schema walker. Apps are instantiated once with default
settings (against a simulated panel, no network) only to ask them which output kind they use.

It also records the latest GitHub release (`release`: version, date, page, and one entry per installer with its size)
for the download page. The asset names carry the version (DeskDot-Setup-3.8.0-x64.exe), so the page can't use
stable `releases/latest/download/<name>` links: they are baked in here, at build time (no request from the page).
Offline, the release already in site/apps.json is kept.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PREVIEWS = SITE / "media" / "apps"  # rendered by scripts/build_site_media.py
DEFAULT_OUT = SITE / "apps.json"
REPO = "shivpatel2468/idotmatrix"

# The installers on a release, by file name: (pattern, key, platform, note). Anything else (checksums.txt) is not a download.
ASSETS = [
    (re.compile(r"^DeskDot-Setup-[\d.]+-x64\.exe$"), "windows", "windows", "Windows 10/11 (64-bit)"),
    (re.compile(r"^DeskDot-[\d.]+-macOS-arm64\.dmg$"), "mac_arm", "mac", "Apple silicon (M1 and newer)"),
    (re.compile(r"^DeskDot-[\d.]+-macOS-x64\.dmg$"), "mac_intel", "mac", "Intel Mac"),
    (re.compile(r"^DeskDot-[\d.]+\.apk$"), "android", "android", "Android 8 or newer"),
]

CATEGORY_LABELS = {
    "time": "Time",
    "data": "Live data",
    "media": "Media",
    "creative": "Creative",
    "pets": "Pets",
    "games": "Games",
    "casino": "Casino",
    "ambient": "Ambient",
    "productivity": "Productivity",
    "device": "Device",
}


def _type_of(prop: dict[str, Any], defs: dict[str, Any]) -> str:
    """A short, human type name for one JSON-schema property."""
    if "$ref" in prop:
        prop = defs.get(prop["$ref"].rsplit("/", 1)[-1], {})
    if "enum" in prop:
        return "choice"
    if prop.get("format") == "color":
        return "color"
    if "anyOf" in prop:
        kinds = [_type_of(p, defs) for p in prop["anyOf"] if p.get("type") != "null"]
        return (kinds[0] if len(kinds) == 1 else " | ".join(kinds)) + "?" if kinds else "any"
    t = prop.get("type", "any")
    if t == "array":
        return f"list of {_type_of(prop.get('items', {}), defs)}"
    return {
        "integer": "integer",
        "number": "number",
        "boolean": "toggle",
        "string": "text",
        "object": "object",
    }.get(t, str(t))


def settings_from_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a pydantic JSON schema into [{key, title, type, default, options, min, max, group, ...}]."""
    defs = schema.get("$defs", {})
    out = []
    for key, prop in schema.get("properties", {}).items():
        s: dict[str, Any] = {
            "key": key,
            "title": prop.get("title") or key.replace("_", " ").title(),
            "type": _type_of(prop, defs),
        }
        if prop.get("description"):
            s["description"] = prop["description"]
        if "default" in prop:
            s["default"] = prop["default"]
        if "enum" in prop:
            labels = prop.get("enumLabels") or {}
            s["options"] = [{"value": v, "label": labels.get(str(v), str(v))} for v in prop["enum"]]
        for src, dst in (
            ("minimum", "min"),
            ("maximum", "max"),
            ("exclusiveMinimum", "min"),
            ("exclusiveMaximum", "max"),
            ("minLength", "min_length"),
            ("maxLength", "max_length"),
        ):
            if src in prop:
                s[dst] = prop[src]
        if prop.get("group"):
            s["group"] = prop["group"]
        out.append(s)
    return out


def _kinds(engine: Any, cls: type, settings: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """The output kind with default settings, plus every kind any single Choice option switches it to."""
    from deskdot.engine.runtime import AppContext

    def kind_with(patch: dict[str, Any]) -> str | None:
        try:
            app = cls(AppContext(engine, cls.id, cls.id), cls.Settings(**patch))
            return str(app.kind())
        except Exception:  # an option that needs live data to decide; the default still counts
            return None

    default = kind_with({}) or "stream"
    seen = {default}
    for s in settings:
        for opt in s.get("options", []):
            k = kind_with({s["key"]: opt["value"]})
            if k:
                seen.add(k)
    order = ["clip", "stream", "native"]
    return default, sorted(seen, key=order.index)


def _source(cls: type) -> str | None:
    """The app's file relative to the repo (for a "view source" link), if it lives in the repo."""
    try:
        path = Path(inspect.getsourcefile(cls) or "").resolve()
        return path.relative_to(ROOT).as_posix()
    except (TypeError, ValueError):
        return None


def _media(name: str) -> str | None:
    """A rendered preview's path relative to site/, if scripts/build_site_media.py has made it."""
    return f"media/apps/{name}" if (PREVIEWS / name).exists() else None


async def build() -> dict[str, Any]:
    import deskdot
    import deskdot.apps  # registers every built-in app
    from deskdot.config import Config, Store
    from deskdot.device import SimDevice
    from deskdot.engine import Engine
    from deskdot.engine.app import REGISTRY
    from deskdot.providers import build_hub

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(device="sim", data_dir=Path(tmp))
        store = Store(Path(tmp) / "state.json")
        hub = build_hub(store, lambda _n: None)
        engine = Engine(cfg, store, SimDevice(bytes_per_second=1e7, min_frame_interval=0.0), hub)
        apps = []
        try:
            for cls in sorted(REGISTRY.values(), key=lambda c: (c.category, c.name.lower())):
                if cls.hidden:
                    continue
                m = cls.meta()
                settings = settings_from_schema(m.settings_schema)
                kind, kinds = _kinds(engine, cls, settings)
                entry: dict[str, Any] = {
                    "id": m.id,
                    "name": m.name,
                    "category": m.category,
                    "icon": m.icon,
                    "description": m.description,
                    "kind": kind,
                    "kinds": kinds,
                    "page": f"apps/{m.id}.html",
                    "preview": _media(f"{m.id}.gif"),
                    "poster": _media(f"{m.id}.png"),
                    "og_image": _media(f"og/{m.id}.png"),
                    "source": _source(cls),
                    "actions": [{"id": a.id, "label": a.label} for a in m.actions],
                    "settings": settings,
                }
                if m.category == "games" or getattr(cls, "max_players", 1) > 1:
                    entry["game"] = {
                        "max_players": int(getattr(cls, "max_players", 1)),
                        "controls": list(getattr(cls, "controls", ())),
                        "modes": [
                            {
                                "id": md.id,
                                "name": md.name,
                                "min_players": md.min_players,
                                "max_players": md.max_players,
                                "teams": md.teams,
                            }
                            for md in getattr(cls, "modes", ())
                        ],
                        "maps": [{"id": k, "label": v} for k, v in getattr(cls, "maps", {}).items()],
                        "themes": next(
                            (s["options"] for s in settings if s["key"] == "theme" and "options" in s), []
                        ),
                    }
                apps.append(entry)
        finally:
            await hub.http.aclose()

    cats = sorted({a["category"] for a in apps}, key=list(CATEGORY_LABELS).index)
    return {
        "version": deskdot.__version__,
        "count": len(apps),
        "games": sum(1 for a in apps if a["category"] == "games"),
        "multiplayer": sum(1 for a in apps if a.get("game", {}).get("max_players", 1) > 1),
        "categories": [
            {"id": c, "label": CATEGORY_LABELS[c], "count": sum(a["category"] == c for a in apps)}
            for c in cats
        ],
        "apps": apps,
    }


def _fetch_release() -> dict[str, Any]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "deskdot-site-build"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def release(previous: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The latest GitHub release as the download page shows it, or `previous` when GitHub can't be reached."""
    try:
        rel = _fetch_release()
    except Exception as exc:  # offline, rate-limited: keep what the site already has
        print(f"latest release: {exc}; keeping the committed one", file=sys.stderr)
        return previous
    assets: list[dict[str, Any]] = []
    checksums = None
    for a in rel.get("assets", []):
        name, url = a.get("name", ""), a.get("browser_download_url", "")
        if not url.startswith(f"https://github.com/{REPO}/releases/download/"):
            continue
        if name == "checksums.txt":
            checksums = url
            continue
        for pat, key, platform, note in ASSETS:
            if pat.match(name):
                assets.append(
                    {
                        "key": key,
                        "platform": platform,
                        "name": name,
                        "url": url,
                        "size": int(a.get("size") or 0),
                        "note": note,
                    }
                )
    if not assets:
        return previous
    published = rel.get("published_at") or ""
    try:
        when = datetime.fromisoformat(published.replace("Z", "+00:00"))
        date = f"{when.day} {when:%B %Y}"
    except ValueError:
        date = ""
    order = [k for _p, k, _pl, _n in ASSETS]
    return {
        "version": str(rel.get("tag_name", "")).removeprefix("v"),
        "tag": rel.get("tag_name", ""),
        "date": date,
        "page": rel.get("html_url", f"https://github.com/{REPO}/releases/latest"),
        "checksums": checksums,
        "assets": sorted(assets, key=lambda x: order.index(x["key"])),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    data = asyncio.run(build())
    try:
        previous = json.loads(DEFAULT_OUT.read_text(encoding="utf-8")).get("release")
    except (OSError, ValueError):
        previous = None
    rel = release(previous)
    if rel:
        data["release"] = rel
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {data['count']} apps, {data['games']} games", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
