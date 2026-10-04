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
    assert {"sysmon", "activeapp", "nowplaying", "obs", "printer", "anki"} <= set(off)
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


@pytest.mark.parametrize("app_id", ["sysmon", "obs", "printer", "anki", "activeapp", "nowplaying"])
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
