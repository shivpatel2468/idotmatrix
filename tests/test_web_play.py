"""Online play with friends in the web app (docs/WEB_APP.md, "Play with friends over the internet").

The engine runs in a browser tab; phones reach it over WebRTC (web/webapp/host-rtc.js ↔ web/webapp/join/join.js).
What the engine side must guarantee: the join QR points at the website (`public_url`), the desktop is unchanged,
and a tunnelled phone (a non-loopback `client` through web_main) is treated exactly like a phone on the Wi-Fi.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from deskdot import web_main
from deskdot.config import Config
from deskdot.multiplayer import CASINO_HTML, CONTROLLER_HTML, LanGate, Lobby
from deskdot.server import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_lobby_url_points_at_the_website_with_public_url() -> None:
    web = Lobby("127.0.0.1", 8765, "https://idotmatrix.com/")
    assert web.lan_ready, "the web app's phones come over the internet: no LAN warning"
    assert web.url() is None
    room = web.open("tictactoe", 2)
    assert web.url() == f"https://idotmatrix.com/p/{room.code}"
    assert len(web.url() or "") <= 53, "must fit a version-3 QR code"
    assert (web.snapshot() or {})["url"] == web.url()


def test_desktop_lobby_is_unchanged() -> None:
    local = Lobby("127.0.0.1", 8765)
    assert local.public_url is None and not local.lan_ready
    room = local.open("tictactoe", 2)
    url = local.url() or ""
    assert url.startswith("http://") and url.endswith(f":8765/p/{room.code}")
    assert Lobby("0.0.0.0", 8765).lan_ready


def test_web_lobby_over_the_api_has_no_warning(tmp_path: Path) -> None:
    cfg = Config(
        device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins", public_url="https://idotmatrix.com"
    )
    with TestClient(create_app(cfg)) as c:
        r = c.post("/api/play/lobby", json={"app": "tictactoe"}).json()
        assert r["url"] == f"https://idotmatrix.com/p/{r['code']}"
        assert "warning" not in r
        assert c.get("/api/play/lobby").json()["lan_ready"] is True


# ----------------------------------------------------------------------------- web_main: the phone's address
async def _echo(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """A tiny ASGI app that answers with the client address it saw."""
    who = (scope.get("client") or ("?", 0))[0]
    if scope["type"] == "http":
        await receive()
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]}
        )
        await send(
            {
                "type": "http.response.body",
                "body": f"{who} {scope['path']}?{scope['query_string'].decode()}".encode(),
            }
        )
    elif scope["type"] == "websocket":
        await receive()  # websocket.connect
        await send({"type": "websocket.accept"})
        await send(
            {"type": "websocket.send", "text": f"{who} {scope['path']}?{scope['query_string'].decode()}"}
        )
        await send({"type": "websocket.close", "code": 1000})


async def test_http_client_passthrough(monkeypatch: Any) -> None:
    monkeypatch.setattr(web_main, "_app", LanGate(_echo))
    # the studio (this tab) is local
    status, _, body = await web_main.http("GET", "/api/state", [])
    assert status == 200 and body.startswith(b"127.0.0.1 ")
    # a tunnelled phone is not: it may only use the phone routes, like a phone on the Wi-Fi
    status, _, body = await web_main.http("GET", "/api/state", [], client="10.88.0.2")
    assert status == 403
    status, _, body = await web_main.http("GET", "/p/AB12", [], client="10.88.0.2")
    assert status == 200 and body == b"10.88.0.2 /p/AB12?"


async def test_ws_client_and_query_passthrough(monkeypatch: Any) -> None:
    monkeypatch.setattr(web_main, "_app", LanGate(_echo))
    events: list[tuple[str, Any]] = []
    web_main.ws_open(901, "/ws/p/AB12?cid=pabcdefgh1", lambda ev, d: events.append((ev, d)), "10.88.0.7")
    for _ in range(50):
        await asyncio.sleep(0)
        if events and events[-1][0] == "close":
            break
    assert ("open", None) in events
    assert ("text", "10.88.0.7 /ws/p/AB12?cid=pabcdefgh1") in events, "the seat comes back by ?cid="

    events.clear()
    web_main.ws_open(902, "/ws", lambda ev, d: events.append((ev, d)), "10.88.0.7")
    for _ in range(50):
        await asyncio.sleep(0)
        if events and events[-1][0] == "close":
            break
    assert events and events[0] == ("close", 1008), "the studio socket is closed to phones"


# ----------------------------------------------------------------------------- the join page's phone pages
def test_join_page_tells_casino_from_controller() -> None:
    # web/webapp/join/join.js picks /app/join/casino.html when the engine's /p/<code> page has this marker
    assert "DeskDotCasino" in CASINO_HTML
    assert "DeskDotCasino" not in CONTROLLER_HTML


def _build_webapp() -> Any:
    spec = importlib.util.spec_from_file_location("build_webapp", ROOT / "scripts" / "build_webapp.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_phone_pages_split_for_the_join_page_csp() -> None:
    b = _build_webapp()
    for kind, src in b.PHONE_PAGES.items():
        html = src.read_text(encoding="utf-8")
        page, script = b.split_phone_page(html, kind, "abc123")
        assert "<script>" not in page, "the join page's CSP allows no inline script"
        assert f'<script src="/app/join/{kind}.js?v=abc123"></script>' in page
        assert script.strip() and script.strip() in html
        # the controller connects to wss://<location.host>/ws/p/<code>: join.js's WebSocket shim routes that
        assert "location.host}/ws/p/${code}" in script


def test_join_sources_exist_and_signal_route() -> None:
    join = ROOT / "web" / "webapp" / "join"
    html = (join / "index.html").read_text(encoding="utf-8")
    assert "/app/join/join.js" in html and "/app/host/host-rtc-wire.js" in html
    assert "<script>" not in html, "no inline script under the /p/* CSP"
    assert (join / "join.css").exists()
    fn = (ROOT / "netlify" / "functions" / "signal.mjs").read_text(encoding="utf-8")
    assert 'path: "/app/signal"' in fn
    toml = (ROOT / "netlify.toml").read_text(encoding="utf-8")
    assert 'from = "/p/*"' in toml and 'to = "/app/join/index.html"' in toml
    assert json.loads((ROOT / "netlify" / "package.json").read_text(encoding="utf-8"))["dependencies"][
        "@netlify/blobs"
    ]
