"""TV view (docs/TV_VIEW.md): the TV link routes, the LAN gate, the socket's messages and its privacy."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot.config import Config
from deskdot.multiplayer import LanGate
from deskdot.server import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def _until(ws: Any, pred: Any, timeout: float = 4.0) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        m = ws.receive()
        if m.get("bytes") is not None:
            if pred(m["bytes"]):
                return m["bytes"]
            continue
        if m.get("text") is not None:
            msg = json.loads(m["text"])
            if pred(msg):
                return msg
    raise AssertionError("message never arrived")


def test_tv_link_routes_and_page(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.get("/api/tv").json() == {"tv": None}
        r = c.post("/api/tv").json()
        code, url = r["code"], r["url"]
        assert r["ok"] and len(code) == 4 and url.endswith(f"/tv/{code}") and url.startswith("http://")
        assert c.post("/api/tv").json()["code"] == code, "reopening the sheet keeps the code"
        assert c.get("/api/tv").json()["tv"]["code"] == code

        page = c.get(f"/tv/{code}")
        assert page.status_code == 200 and "DeskDotTV" in page.text
        assert "<script>" not in page.text, "no inline script (the web app's CSP)"
        for name in ("tv.js", "tv-games.js", "tv-casino.js"):
            assert f"/tv/static/{name}" in page.text
            js = c.get(f"/tv/static/{name}")
            assert js.status_code == 200 and "javascript" in js.headers["content-type"]
        assert "registerScene" in c.get("/tv/static/tv.js").text
        assert c.get("/tv/static/nope.js").status_code == 404
        assert c.get("/tv/static/..%2Fserver.py").status_code == 404
        assert c.get("/tv/ZZZZ").status_code == 404  # still the page: it says the link has closed

        lobby = c.post("/api/play/lobby", json={"app": "tictactoe"}).json()
        assert lobby["code"] != code

        renewed = c.post("/api/tv", json={"renew": True}).json()["code"]
        assert renewed != code
        assert c.get(f"/tv/{code}").status_code == 404
        assert c.delete("/api/tv").json()["ok"]
        assert c.get("/api/tv").json() == {"tv": None}


def test_tv_socket_hello_state_frames(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        c.post("/api/apps/clock/activate", json={})
        code = c.post("/api/tv").json()["code"]
        with c.websocket_connect(f"/ws/tv/{code}") as ws:
            hello = _until(ws, lambda m: isinstance(m, dict) and m["type"] == "hello")
            assert hello["app"] == "clock" and hello["meta"]["name"] and "server_time" in hello
            assert set(hello["meta"]) == {"id", "name", "category", "icon", "max_players"}
            assert "bot" in hello["avatars"]
            st = _until(ws, lambda m: isinstance(m, dict) and m["type"] == "state")
            assert st["app"] == "clock" and isinstance(st["status"], dict) and st["lobby"] is None
            frame = _until(ws, lambda m: isinstance(m, bytes))
            assert len(frame) == 32 * 32 * 3
            assert c.get("/api/tv").json()["tv"]["viewers"] == 1

            ws.send_text(json.dumps({"type": "ping", "t": 5}))
            pong = _until(ws, lambda m: isinstance(m, dict) and m["type"] == "pong")
            assert pong["t"] == 5 and pong["server_time"] > 0

            c.post("/api/apps/tictactoe/activate", json={})
            hello2 = _until(ws, lambda m: isinstance(m, dict) and m["type"] == "hello")
            assert hello2["app"] == "tictactoe" and hello2["meta"]["max_players"] == 2

            c.post("/api/play/lobby", json={"app": "tictactoe"})
            st = _until(ws, lambda m: isinstance(m, dict) and m["type"] == "state" and m["lobby"])
            assert st["lobby"]["code"] and st["lobby"]["url"]

            c.delete("/api/tv")
            assert _until(ws, lambda m: isinstance(m, dict) and m["type"] == "closed")

        with c.websocket_connect("/ws/tv/ZZZZ") as ws:
            assert ws.receive_json()["type"] == "closed"


def test_tv_never_gets_private_data(tmp_path: Path) -> None:
    """A TV gets the public casino status phones get as `status` — never a seat's private view."""
    with _client(tmp_path) as c:
        lob = c.post("/api/play/lobby", json={"app": "casino_roulette"}).json()
        code = c.post("/api/tv").json()["code"]
        with (
            c.websocket_connect(f"/ws/p/{lob['code']}?cid=phoneTVTV01") as phone,
            c.websocket_connect(f"/ws/tv/{code}") as tv,
        ):
            phone.receive_json()
            phone.send_text(json.dumps({"type": "casino", "op": "seed", "client_seed": "secret-seed-xyz"}))
            phone.send_text(json.dumps({"type": "casino", "op": "bet", "spot": "n:17", "amount": 25}))
            st = _until(
                tv,
                lambda m: isinstance(m, dict) and m["type"] == "state" and m["status"].get("totals"),
            )
            assert st["app"] == "casino_roulette" and st["status"]["totals"] == {"n:17": 25}
            assert "table_theme" in st["status"]
            text = json.dumps(st)
            assert "secret-seed-xyz" not in text and "phoneTVTV01" not in text
            assert "private" not in st
            # the same public dict the phone gets as `status`
            app = c.app.state.engine._slot("casino_roulette").app
            assert set(st["status"]) == set(app.status())


def test_tv_display_settings_validate_and_reach_every_tv(tmp_path: Path) -> None:
    """The studio's look / quality (POST /api/tv/settings) goes live to every TV of the link, in hello and state."""
    with _client(tmp_path) as c:
        code = c.post("/api/tv").json()["code"]
        assert c.get("/api/tv").json()["tv"]["display"] == {"look": None, "quality": None, "rev": None}
        with c.websocket_connect(f"/ws/tv/{code}") as tv1, c.websocket_connect(f"/ws/tv/{code}") as tv2:
            for tv in (tv1, tv2):
                hello = _until(tv, lambda m: isinstance(m, dict) and m["type"] == "hello")
                assert hello["display"] == {"look": None, "quality": None, "rev": None}

            r = c.post("/api/tv/settings", json={"look": "glow"}).json()
            assert r["ok"] and r["display"]["look"] == "glow" and r["display"]["quality"] is None
            rev1 = r["display"]["rev"]
            assert isinstance(rev1, float)
            for tv in (tv1, tv2):
                st = _until(
                    tv,
                    lambda m: isinstance(m, dict) and m["type"] == "state" and m["display"]["look"] == "glow",
                )
                assert st["display"] == {"look": "glow", "quality": None, "rev": rev1}

            # a key left out keeps its value; every change gets a new revision (even the same value again)
            r = c.post("/api/tv/settings", json={"quality": "lite"}).json()
            assert (
                r["display"]["look"] == "glow"
                and r["display"]["quality"] == "lite"
                and r["display"]["rev"] > rev1
            )
            st = _until(
                tv1,
                lambda m: isinstance(m, dict) and m["type"] == "state" and m["display"]["quality"] == "lite",
            )
            assert st["display"]["look"] == "glow"
            again = c.post("/api/tv/settings", json={"quality": "lite"}).json()["display"]
            assert again["rev"] > r["display"]["rev"]

            # validation: only the studio's looks and the three qualities (null hands the choice back to each TV)
            for bad in ({"look": "hd"}, {"look": "LED"}, {"quality": "ultra"}, {"look": 3}):
                assert c.post("/api/tv/settings", json=bad).status_code == 422
            assert c.get("/api/tv").json()["tv"]["display"]["look"] == "glow", (
                "a rejected change changes nothing"
            )
            r = c.post("/api/tv/settings", json={"look": None}).json()
            assert r["display"]["look"] is None and r["display"]["quality"] == "lite"
            assert c.get("/api/tv").json()["tv"]["display"] == r["display"]

        # a TV that connects later starts with the studio's choice
        with c.websocket_connect(f"/ws/tv/{code}") as tv3:
            hello = _until(tv3, lambda m: isinstance(m, dict) and m["type"] == "hello")
            assert hello["display"]["quality"] == "lite" and hello["display"]["look"] is None
            st = _until(tv3, lambda m: isinstance(m, dict) and m["type"] == "state")
            assert st["display"]["quality"] == "lite"


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/tv/AB12", True),
        ("/ws/tv/AB12", True),
        ("/tv/static/tv.js", True),
        ("/tv/../api/state", False),
        ("/api/tv", False),
        ("/api/tv/settings", False),
        ("/tv/../api/tv/settings", False),
        ("/tvx", False),
    ],
)
def test_lan_gate_tv(path: str, allowed: bool) -> None:
    reached: list[str] = []
    sent: list[dict[str, Any]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        reached.append(scope["path"])

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    asyncio.run(LanGate(inner)({"type": "http", "path": path, "client": ("192.168.1.40", 5000)}, None, send))
    assert bool(reached) == allowed


def test_tv_page_built_for_the_join_page() -> None:
    """The web app (docs/TV_VIEW.md §8): tv.html's scripts move to /app/join/tv/, and /tv/* reaches the join page."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("build_webapp", root / "scripts" / "build_webapp.py")
    assert spec and spec.loader
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    page = b.tv_page_for_join(b.TV_PAGE.read_text(encoding="utf-8"), "abc123")
    for name in ("tv.js", "tv-games.js", "tv-casino.js"):
        assert f'src="/app/join/tv/{name}?v=abc123"' in page
        assert (b.TV_SCRIPTS / name).is_file()
    assert "/tv/static/" not in page
    toml = (root / "netlify.toml").read_text(encoding="utf-8")
    assert 'from = "/tv/*"' in toml and 'for = "/tv/*"' in toml
    join = (root / "web" / "webapp" / "join" / "join.js").read_text(encoding="utf-8")
    assert "/tv/${code}" in join and '"tv"' in join
    rtc = (root / "web" / "webapp" / "host-rtc.js").read_text(encoding="utf-8")
    assert '"/api/tv"' in rtc
