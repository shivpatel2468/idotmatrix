"""Apps and providers in the browser app (platform "web", docs/WEB_APP.md "App support in the browser").

* every data host a provider calls is either CORS-friendly (checked with `curl -H "Origin: https://idotmatrix.com"`)
  or on the CORS proxy's allowlist (netlify/functions/cors-proxy.mjs), and the proxy stays a strict allowlist;
* apps that can't work in a tab say so (`platforms` without "web" + a `web_reason`) and render "NOT ON WEB";
* the web-only code paths (ntfy polling, uptime without sockets, the fetch transport's LAN detection) behave.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from deskdot import platforms, web_main
from deskdot.config import Store
from deskdot.engine import REGISTRY
from deskdot.gfx import Frame
from deskdot.providers import build_hub, ntfy, uptime

ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "netlify" / "functions" / "cors-proxy.mjs"

# Hosts that answer a browser from https://idotmatrix.com directly (Access-Control-Allow-Origin "*" or the
# origin echoed), verified with curl on 2026-10-04. A host that loses CORS moves to the proxy allowlist.
CORS_OK = {
    "geocoding-api.open-meteo.com",
    "api.open-meteo.com",
    "air-quality-api.open-meteo.com",
    "marine-api.open-meteo.com",
    "mc-heads.net",
    "crafatar.com",
    "api.dicebear.com",
    "api.chess.com",
    "api.github.com",
    "api.frankfurter.dev",
    "cdn.jsdelivr.net",
    "icanhazdadjoke.com",
    "uselessfacts.jsph.pl",
    "api.adviceslip.com",
    "catfact.ninja",
    "v2.jokeapi.dev",
    "api.chucknorris.io",
    "api.kanye.rest",
    "api.adsbdb.com",
    "www.gamerpower.com",
    "api.spaceflightnewsapi.net",
    "dev.to",
    "date.nager.at",
    "caldays.com",
    "lrclib.net",
    "itunes.apple.com",
    "dog.ceo",
    "images.dog.ceo",
    "cataas.com",
    "randomfox.ca",
    "collectionapi.metmuseum.org",
    "picsum.photos",
    "fastly.picsum.photos",
    "pokeapi.co",
    "raw.githubusercontent.com",
    "api.rainviewer.com",
    "api.sunrise-sunset.org",
    "ll.thespacedevs.com",
    "corquaid.github.io",
    "api.wheretheiss.at",
    "opentdb.com",
    "hn.algolia.com",  # verified 2026-10-08 (echoes the origin)
    "data-api.binance.vision",
    "services.swpc.noaa.gov",
    "mempool.space",
    "api.coingecko.com",
    "api.alternative.me",
    "api.jolpi.ca",
    "api.citybik.es",
    "eonet.gsfc.nasa.gov",
    "flagcdn.com",
    "api.mcsrvstat.us",
    "api.tvmaze.com",
    "upload.wikimedia.org",
    "thumb.wikimedia.org",  # picture of the day (Photo Frame), verified 2026-10-08
    "latest.currency-api.pages.dev",  # the currency-api mirror (sample URL in CurrencyProvider.endpoints)
    # Now Playing in the browser (providers/media_web.py), verified 2026-10-29
    "api.listenbrainz.org",
    "ws.audioscrobbler.com",  # Last.fm's API (CORS even on errors)
    "lastfm.freetls.fastly.net",  # Last.fm cover images
    "coverartarchive.org",  # redirects to archive.org, then a numbered archive.org node: all with CORS
    "archive.org",
}
# hosts that only appear at run time (image URLs inside API answers), with the provider that fetches them
DYNAMIC = {
    "images.metmuseum.org": "photos (Met)",
    "openaccess-cdn.clevelandart.org": "photos (Cleveland)",
    "fastly.picsum.photos": "photos (Picsum redirect)",
    "images.dog.ceo": "photos (dogs)",
    "randomfox.ca": "photos (foxes)",
    "raw.githubusercontent.com": "pokedex sprites",
    "query2.finance.yahoo.com": "stocks",
    "lastfm.freetls.fastly.net": "media (Last.fm covers)",
    "archive.org": "media (Cover Art Archive redirect)",
}
# user-configured services (no fixed host) and documentation placeholders
NOT_FIXED = {"example.com", "homeassistant.local", "octopi.local", "nas.local", "host"}

_URL = re.compile(r"https?://([A-Za-z0-9.-]+)")


def _hosts_in(path: Path) -> set[str]:
    """Hosts of every URL in a module's string literals (docstrings left out)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant):
                docs.add(id(b.value))
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            out |= {h.lower() for h in _URL.findall(n.value)}
    return out


def _proxy_allowlist() -> set[str]:
    src = PROXY.read_text(encoding="utf-8")
    block = re.search(r"const ALLOW = new Set\(\[(.*?)\]\);", src, re.S)
    assert block, "cors-proxy.mjs must keep `const ALLOW = new Set([...])`"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def test_every_provider_host_works_from_the_browser() -> None:
    allow = _proxy_allowlist()
    missing = {}
    for path in sorted((ROOT / "src" / "deskdot" / "providers").glob("*.py")):
        for host in _hosts_in(path) - NOT_FIXED:
            if host not in CORS_OK and host not in allow:
                missing[host] = path.name
    for host, who in DYNAMIC.items():
        if host not in CORS_OK and host not in allow:
            missing[host] = who
    assert not missing, (
        f"no CORS and not on the proxy allowlist (netlify/functions/cors-proxy.mjs): {missing}"
    )


def test_the_proxy_is_a_strict_get_only_allowlist() -> None:
    src = PROXY.read_text(encoding="utf-8")
    allow = _proxy_allowlist()
    assert allow and all(re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", h) for h in allow), "exact host names only"
    assert 'req.method !== "GET"' in src
    assert 'redirect: "manual"' in src and 'redirect: "follow"' not in src, "redirects must be re-checked"
    for pattern in re.findall(r"/\^(.*?)\$/", src):  # anchored patterns only (no open suffix matches)
        assert ".*" not in pattern and not pattern.startswith(".")
    assert "cookie" not in re.sub(r"//.*", "", src).lower(), "never forward cookies"


# ------------------------------------------------------------------------------------------- apps
def _off_web() -> list[str]:
    return [a for a, c in REGISTRY.items() if not c.hidden and c.platforms and "web" not in c.platforms]


def test_apps_that_cant_run_in_a_tab_say_why() -> None:
    off = _off_web()
    assert set(off) == {"activeapp", "obs", "printer", "anki"}, "a new off-web app: add it to docs/WEB_APP.md"
    assert not {"sysmon", "nowplaying"} & set(off)  # the browser's own stats; a listening service / typed in
    for app_id in off:
        cls = REGISTRY[app_id]
        assert len(cls.web_reason) > 20, f"{app_id}: set web_reason (why it can't run in a browser tab)"
        assert cls.meta().settings_schema["webReason"] == cls.web_reason
    for app_id, cls in REGISTRY.items():  # a reason only where it applies
        if app_id not in off:
            assert "webReason" not in cls.meta().settings_schema, app_id


def test_lan_apps_only_lose_the_browser() -> None:
    for app_id in ("obs", "printer", "anki"):
        plats = REGISTRY[app_id].platforms
        assert set(plats) == set(platforms.NATIVE), app_id
    assert platforms.supported("lan", "android") and not platforms.supported("lan", "web")


@pytest.mark.parametrize("app_id", ["obs", "printer", "anki", "activeapp"])
async def test_off_web_apps_say_not_on_web(engine, monkeypatch, app_id: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(platforms, "current", lambda: "web")
    if app_id in ("obs", "printer"):
        engine.store.section("apps")[app_id] = {"host": "192.168.1.20"}
    slot = engine._slot(app_id)
    assert not slot.app.supported_here()
    assert not slot.app.relevant()  # the playlist skips it
    f = Frame()
    slot.app.render(f, 0.5)
    assert f.px.any(), "draws the NOT ON WEB card"


async def test_lan_providers_never_poll_in_the_browser(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(platforms, "current", lambda: "web")
    hub = build_hub(Store(tmp_path / "s.json"), lambda _n: None)
    try:
        for name in ("obs", "printer", "anki"):
            p = hub.get(name)
            p.acquire()
            assert p._task is None and p.error and "Browser" in p.error
            p.release()
    finally:
        await hub.http.aclose()


# ------------------------------------------------------------------------------------------- ntfy
async def test_ntfy_polls_in_the_browser(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(ntfy, "current", lambda: "web")
    seen: list[httpx.Request] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        line = {"id": f"m{len(seen)}", "event": "message", "topic": "t1", "message": "hi", "priority": 4}
        return httpx.Response(200, text=json.dumps(line) + "\n")

    store = Store(tmp_path / "s.json")
    store.set("ntfy", {"enabled": True, "topics": "t1", "token": "tk_secret"})
    hub = build_hub(store, lambda _n: None)
    await hub.http.aclose()
    hub.http = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    events: list[tuple[str, dict[str, Any]]] = []
    hub.listeners.append(lambda e, d: events.append((e, d)))
    p = hub.get("ntfy")
    try:
        v = await p.fetch()
        assert v["connected"] is True
        q = seen[0].url.params
        assert seen[0].url.path == "/t1/json" and q["poll"] == "1" and q["since"].isdigit()
        assert q["auth"] == ntfy.auth_param("tk_secret") and "authorization" not in seen[0].headers
        assert events and events[0][1]["message"] == "hi"
        await p.fetch()
        assert seen[1].url.params["since"] == "m1"  # resumes after the last message
        assert p.next_interval() == ntfy.WEB_POLL
    finally:
        await hub.http.aclose()


def test_ntfy_auth_param_is_base64url_without_padding() -> None:
    import base64

    v = ntfy.auth_param("tk_abc")
    assert "=" not in v
    assert base64.urlsafe_b64decode(v + "=" * (-len(v) % 4)) == b"Bearer tk_abc"


# ----------------------------------------------------------------------------------------- uptime
async def test_uptime_in_the_browser(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(uptime, "current", lambda: "web")

    def answer(req: httpx.Request) -> httpx.Response:
        if req.url.host == "cors.example":
            return httpx.Response(204)
        raise httpx.ConnectError("blocked by the browser", request=req)

    async def probe(url: str, wait: float = 5.0) -> float:
        if "down.example" in url:
            raise OSError("unreachable: TypeError: Failed to fetch")
        return 42.0

    monkeypatch.setattr(web_main, "probe", probe)
    hub = build_hub(Store(tmp_path / "s.json"), lambda _n: None)
    await hub.http.aclose()
    hub.http = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    p = hub.get("uptime")
    p.configure(uptime.parse_targets("cors.example, nocors.example, down.example, db.local:5432"), confirm=1)
    try:
        v = (await p.fetch())["targets"]
        by = {s["label"]: s for s in v.values()}
        assert by["CORS"]["up"] is True and by["CORS"]["status"] == 204
        assert (
            by["NOCORS"]["up"] is True and by["NOCORS"]["status"] is None and by["NOCORS"]["latency"] == 42.0
        )
        assert by["DOWN"]["up"] is False and by["DOWN"]["error"] == "UNREACHABLE"
        assert by["DB"]["up"] is None and by["DB"]["error"] == "NO TCP IN BROWSER"  # never alerts
    finally:
        await hub.http.aclose()


# ------------------------------------------------------------------------------ fetch transport
@pytest.mark.parametrize(
    ("host", "local"),
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("192.168.1.20", True),
        ("172.20.0.5", True),
        ("10.0.0.2", True),
        ("[::1]", True),
        ("169.254.10.1", True),
        ("homeassistant.local", True),
        ("octopi", True),
        ("nas.lan", True),
        ("api.open-meteo.com", False),
        ("8.8.8.8", False),
        ("172.32.0.1", False),
    ],
)
def test_lan_hosts_are_recognised(host: str, local: bool) -> None:
    assert web_main.is_local_host(host) is local


def test_blocked_messages_say_why() -> None:
    lan = web_main.blocked_message("homeassistant.local", "http://homeassistant.local:8123/api/", True)
    assert "plain-http" in lan and "desktop app" in lan
    assert "CORS" in web_main.blocked_message("example.org", "https://example.org/", False)


async def test_flights_poll_slower_through_the_proxy(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    hub = build_hub(Store(tmp_path / "s.json"), lambda _n: None)
    try:
        p = hub.get("flights")
        assert p.next_interval() == p.interval  # desktop: unchanged
        monkeypatch.setattr(platforms, "current", lambda: "web")
        assert p.next_interval() == p.WEB_INTERVAL > p.interval
    finally:
        await hub.http.aclose()


async def test_uptime_skips_lan_http_in_the_browser(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(uptime, "current", lambda: "web")
    hub = build_hub(Store(tmp_path / "s.json"), lambda _n: None)
    p = hub.get("uptime")
    p.configure(uptime.parse_targets("NAS=http://192.168.1.10:8080/health"))
    try:
        st = next(iter((await p.fetch())["targets"].values()))
        assert st["up"] is None and st["error"] == "LAN HTTP: NOT IN BROWSER"
    finally:
        await hub.http.aclose()
    monkeypatch.setattr(uptime, "current", lambda: "windows")
    assert uptime.web_unsupported({"kind": "tcp", "host": "db", "port": 1}) is None  # desktop: unchanged


async def test_uptime_focus_view_explains_browser_limits(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    engine.store.section("apps")["uptime"] = {"targets": "db.local:5432", "layout": "focus"}
    app = engine._slot("uptime").app
    st = {
        "key": "tcp:db.local:5432",
        "label": "DB",
        "kind": "tcp",
        "up": None,
        "error": "NO TCP IN BROWSER",
        "history": [],
        "latency": None,
        "status": None,
    }
    monkeypatch.setattr(app, "_data", lambda: (None, [({"label": "DB", "kind": "tcp"}, st)]))
    f = Frame()
    app._focus(f, 0.0, [({"label": "DB", "kind": "tcp"}, st)])
    assert f.px.any()


# ------------------------------------------------------------------------------------ Now Playing
def _np_hub(tmp_path: Path, settings: dict[str, Any], answer: Any) -> Any:
    store = Store(tmp_path / "s.json")
    store.section("apps")["nowplaying"] = settings
    hub = build_hub(store, lambda _n: None)
    hub.http = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    return hub


LB_NOW = {
    "payload": {
        "count": 1,
        "playing_now": True,
        "listens": [
            {
                "track_metadata": {
                    "artist_name": "Daft Punk",
                    "track_name": "One More Time",
                    "release_name": "Discovery",
                    "additional_info": {"duration_ms": 320000, "release_mbid": "abc-123"},
                }
            }
        ],
    }
}


async def test_now_playing_from_listenbrainz_in_the_browser(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from deskdot.providers import media_web

    monkeypatch.setattr(platforms, "current", lambda: "web")
    seen: list[str] = []

    def answer(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.host == "api.listenbrainz.org":
            return httpx.Response(200, json=LB_NOW)
        return httpx.Response(404)

    hub = _np_hub(tmp_path, {"web_source": "listenbrainz", "web_user": "rob"}, answer)
    p = hub.get("media")
    try:
        assert p.supported and isinstance(p.backend, media_web.WebBackend) and not p.can_control
        v = await p.fetch()
        assert v["active"] and v["title"] == "One More Time" and v["artist"] == "Daft Punk"
        assert v["playing"] and v["duration"] == 320 and v["controls"] is False
        assert seen[0] == "https://api.listenbrainz.org/1/user/rob/playing-now"
        await p.fetch()  # cached for POLL_S: the 1 s tick doesn't ask again
        assert sum("listenbrainz" in u for u in seen) == 1
        snap = media_web.parse_listenbrainz(LB_NOW)
        assert snap is not None and snap.art_url == "https://coverartarchive.org/release/abc-123/front-250"
        assert media_web.parse_listenbrainz({"payload": {"listens": []}}) is None
    finally:
        await hub.http.aclose()


async def test_now_playing_from_lastfm_and_typed_in(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from deskdot.providers import media_web

    monkeypatch.setattr(platforms, "current", lambda: "web")
    track = {
        "name": "Midnight City",
        "artist": {"#text": "M83"},
        "album": {"#text": "Hurry Up"},
        "image": [{"#text": "https://lastfm.freetls.fastly.net/i/u/300x300/cover.png", "size": "extralarge"}],
        "@attr": {"nowplaying": "true"},
    }

    def answer(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "ws.audioscrobbler.com" and req.url.params["api_key"] == "k1"
        return httpx.Response(200, json={"recenttracks": {"track": [track]}})

    hub = _np_hub(tmp_path, {"web_source": "lastfm", "web_user": "u", "web_api_key": "k1"}, answer)
    try:
        v = await hub.get("media").fetch()
        assert v["title"] == "Midnight City" and v["artist"] == "M83" and v["album"] == "Hurry Up"
        snap = media_web.parse_lastfm({"recenttracks": {"track": [track]}})
        assert snap is not None and snap.art_url and snap.art_url.endswith("cover.png")
        done = {**track, "@attr": {}}  # the newest scrobble, finished: nothing is playing now
        assert media_web.parse_lastfm({"recenttracks": {"track": done}}) is None
        with pytest.raises(RuntimeError, match="Invalid API key"):
            media_web.parse_lastfm({"error": 10, "message": "Invalid API key"})
        # typed in: no network at all; clearing the song stops it
        hub.store.section("apps")["nowplaying"] = {
            "web_source": "manual",
            "web_title": "Song",
            "web_artist": "Me",
        }
        v = await hub.get("media").fetch()
        assert v["active"] and v["title"] == "Song" and v["artist"] == "Me"
        hub.store.section("apps")["nowplaying"] = {"web_source": "manual", "web_title": ""}
        assert (await hub.get("media").fetch()) == {"active": False}
        hub.store.section("apps")["nowplaying"] = {"web_source": "lastfm", "web_user": "u"}
        with pytest.raises(RuntimeError, match="API key"):
            await hub.get("media").fetch()
    finally:
        await hub.http.aclose()


async def test_now_playing_renders_in_the_browser(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(platforms, "current", lambda: "web")
    app = engine._slot("nowplaying").app
    assert app.supported_here()
    schema = app.meta().settings_schema
    for key in ("web_source", "web_user", "web_api_key", "web_title", "web_artist"):
        assert schema["properties"][key]["platforms"] == ["web"], key  # "Browser only" on the desktop
    assert schema["properties"]["web_api_key"]["format"] == "password"
    f = Frame()
    app.render(f, 0.5)
    assert f.px.any()


# --------------------------------------------------------------------------------- System Monitor
async def test_system_monitor_uses_the_browsers_own_stats(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from deskdot.providers import system

    monkeypatch.setattr(platforms, "current", lambda: "web")
    monkeypatch.setattr(system, "current", lambda: "web")
    monkeypatch.setattr(system, "_browser", None)
    p = engine.hub.get("system")
    assert p.supported
    assert await p.fetch() is None  # the page hasn't reported yet: loading, not an error
    b = system.browser_stats(
        {
            "pressure": "serious",
            "heap_used": 50e6,
            "heap_limit": 200e6,
            "battery": 0.42,
            "charging": False,
            "downlink_mbps": 8,
            "fps": 60,
            "cores": 8,
            "device_memory_gb": 8,
            "rtt_ms": "nonsense",
        }
    )
    assert b["cpu"] == 75 and b["ram"] == 25 and b["battery"] == 42 and b["plugged"] is False
    assert b["net_down"] == 1_000_000 and b["fps"] == 60 and b["rtt_ms"] is None
    v = await p.fetch()
    assert v["browser"] is True and v["disk"] is None and v["cpu_hist"] == [75]
    assert system.browser_stats({})["cpu"] is None  # a browser without Compute Pressure: "--"
    app = engine._slot("sysmon").app
    assert app.supported_here() and "webReason" not in app.meta().settings_schema
    p.value = v
    for layout in ("bars", "graph"):
        engine.store.section("apps")["sysmon"] = {"layout": layout}
        engine.slots.pop("sysmon", None)
        f = Frame()
        engine._slot("sysmon").app.render(f, 0.0)
        assert f.px.any(), layout


def test_web_main_forwards_browser_stats(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from deskdot.providers import system

    monkeypatch.setattr(system, "_browser", None)
    web_main.sys_stats({"pressure": "nominal"})
    assert system._browser is not None and system._browser["cpu"] == 25


# ------------------------------------------------------------------------------------ the web build
def _build_script() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_webapp", ROOT / "scripts" / "build_webapp.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_web_build_writes_version_json_with_the_newest_notes() -> None:
    b = _build_script()
    notes = b.whats_new_notes(
        "# What's new\n<!-- ## x — format -->\n## 3.9.0 — a\n### New\n- **A**\n\n## 3.8.0 — b\n"
    )
    assert notes == "## 3.9.0 — a\n### New\n- **A**\n"
    real = b.whats_new_notes((ROOT / "WHATS_NEW.md").read_text(encoding="utf-8"))
    assert real.startswith("## ") and "\n## " not in real
    j = json.loads(b.version_json("3.9.0", "abc123", notes))
    assert j == {"version": "3.9.0", "build": "abc123", "notes": notes}  # deterministic: no timestamps
    sw = (ROOT / "web" / "webapp" / "sw.js").read_text(encoding="utf-8")
    assert 'SCOPE.pathname + "version.json") return;' in sw, "version.json must never come from a cache"


def test_web_build_drops_the_inline_prepaint_script(tmp_path: Path) -> None:
    b = _build_script()
    index = tmp_path / "index.html"
    index.write_text((ROOT / "web" / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
    b.inject_host(index, "b1")
    html = index.read_text(encoding="utf-8")
    assert "<script>" not in html, (
        "the web app's CSP forbids inline script (host.js paints the theme instead)"
    )
    assert '<script src="/app/host/host.js?v=b1"></script>' in html
    host = (ROOT / "web" / "webapp" / "host.js").read_text(encoding="utf-8")
    for key in ("deskdot.theme", "deskdot.glass", "deskdot.pageTheme"):  # the same pre-paint work, in host.js
        assert key in host, key


def test_web_engine_archive_leaves_out_desktop_only_modules() -> None:
    b = _build_script()
    assert {"desktop.py", "launcher.py", "mcp_server.py", "cli.py", "device/ble.py"} <= b.EXCLUDE
    for rel in b.EXCLUDE:  # every exclusion still names a real module (a rename would ship it silently)
        assert (ROOT / "src" / "deskdot" / rel).exists(), rel
    # the new browser-side modules ship (they are imported by the engine in a tab)
    for rel in ("providers/media_web.py", "updates.py", "tvlink.py", "gfx/themes.py", "casino/chips.py"):
        assert rel not in b.EXCLUDE and (ROOT / "src" / "deskdot" / rel).exists(), rel
