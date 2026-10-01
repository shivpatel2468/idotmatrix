from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from dotdeck.config import Config
from dotdeck.server import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def test_meta_state_and_frame(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        meta = c.get("/api/meta").json()
        assert {a["id"] for a in meta["apps"]} >= {"clock", "weather", "canvas", "agent"}
        pong = next(a for a in meta["apps"] if a["id"] == "pong")
        doubles = next(m for m in pong["modes"] if m["id"] == "doubles")
        assert doubles["min_players"] == doubles["max_players"] == 4 and doubles["teams"] == "versus"
        assert c.get("/api/state").json()["device"]["kind"] == "sim"
        png = c.get("/api/frame.png?scale=4")
        assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


def test_settings_validation(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.patch("/api/apps/clock/settings", json={"style": "analog"}).json()["style"] == "analog"
        assert c.patch("/api/apps/clock/settings", json={"style": "nope"}).status_code == 422
        assert c.patch("/api/apps/clock/settings", json={"color": "red"}).status_code == 422
        assert c.post("/api/apps/nope/activate", json={}).status_code == 404


def test_pixels_and_canvas(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.post("/api/pixels", json={"rows": ["#"], "palette": {"#": "#ff0000"}})
        assert r.status_code == 200
        assert c.get("/api/state").json()["engine"]["mode"] == "manual"
        got = c.post("/api/apps/canvas/actions/get", json={}).json()["result"]["rgb"]
        import base64

        assert base64.b64decode(got)[:3] == b"\xff\x00\x00"


def test_media_upload_roundtrip(tmp_path: Path) -> None:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 128, 255)).save(buf, "PNG")
    with _client(tmp_path) as c:
        item = c.post("/api/media", files={"file": ("x.png", buf.getvalue(), "image/png")}).json()
        assert item["width"] == 64
        assert c.get(f"/api/media/{item['id']}/preview.png").status_code == 200
        assert len(c.get("/api/media").json()) == 1
        assert c.post("/api/media", files={"file": ("x.png", b"nope", "image/png")}).status_code == 400
        assert c.delete(f"/api/media/{item['id']}").status_code == 200


def test_playlist_put_validates(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        ok = c.put("/api/playlist", json={"enabled": False, "items": [{"app": "clock", "duration": 10}]})
        assert ok.status_code == 200
        bad = c.put("/api/playlist", json={"items": [{"app": "clock", "settings": {"style": "x"}}]})
        assert bad.status_code == 422


def test_websocket_streams_state_and_frames(tmp_path: Path) -> None:
    with _client(tmp_path) as c, c.websocket_connect("/ws") as ws:
        got_state = got_frame = False
        for _ in range(6):
            msg = ws.receive()
            if msg.get("bytes"):
                assert len(msg["bytes"]) == 3072
                got_frame = True
            elif msg.get("text") and '"state"' in msg["text"]:
                got_state = True
            if got_state and got_frame:
                break
        assert got_state and got_frame


def test_stale_stored_settings_do_not_block_updates(tmp_path: Path) -> None:
    import json

    (tmp_path / "state.json").write_text(
        json.dumps({"apps": {"clock": {"style": "gone", "color": "#ffffff"}}})
    )
    with _client(tmp_path) as c:
        r = c.patch("/api/apps/clock/settings", json={"accent": "#00ff00"})
        assert r.status_code == 200 and r.json()["style"] == "hero" and r.json()["accent"] == "#00ff00"
        assert c.patch("/api/apps/clock/settings", json={"style": "nope"}).status_code == 422


def test_handoff_api(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        cfg = c.get("/api/handoff").json()
        assert cfg["mode"] == "clock" and cfg["released"] is False
        assert (
            c.put("/api/handoff", json={"mode": "app", "app": "weather", "seconds": 5}).json()["app"]
            == "weather"
        )
        assert c.put("/api/handoff", json={"mode": "nope"}).status_code == 422
        for _ in range(50):  # the simulated panel connects in the background
            if c.get("/api/state").json()["device"]["status"] == "connected":
                break
            time.sleep(0.05)
        r = c.post("/api/handoff/now", json={"mode": "clock"}).json()
        assert r["ok"] and r["released"] is True
        assert c.post("/api/handoff/take-back").json()["released"] is False


def test_secrets_never_leave_the_engine(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.patch("/api/apps/ci/settings", json={"token": "ghp_supersecret123"}).json()
        assert r["token"] == "••••••"
        assert "ghp_supersecret123" not in c.get("/api/state").text
        c.patch("/api/apps/ci/settings", json={"token": "••••••", "rotate": 9})  # mask sent back = keep
        eng = c.app.state.engine
        assert eng.base_settings("ci")["token"] == "ghp_supersecret123"
        assert c.patch("/api/apps/ci/settings", json={"token": ""}).json()["token"] == ""  # "" clears


def test_presets(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        ps = c.get("/api/presets").json()
        ids = {p["id"] for p in ps}
        assert {"cat-games", "cat-pets", "everything", "dashboard"} <= ids
        games = next(p for p in ps if p["id"] == "cat-games")
        assert len(games["items"]) >= 11 and all(i["app"] not in ("ci", "obs") for i in games["items"])
        r = c.post("/api/presets/cat-games/play", json={"shuffle": True}).json()
        assert r["ok"] and r["items"] == len(games["items"])
        st = c.get("/api/state").json()["engine"]
        assert st["mode"] == "playlist" and st["active_preset"] == "cat-games"
        assert st["preset"] == {"id": "cat-games", "name": "All games", "shuffle": True}
        mine = c.post("/api/presets", json={"name": "My Games"}).json()
        assert mine["id"].startswith("my-") and not mine["builtin"]
        assert any(p["id"] == mine["id"] for p in c.get("/api/presets").json())
        assert c.delete("/api/presets/cat-games").status_code == 404  # built-ins can't be deleted
        assert c.delete(f"/api/presets/{mine['id']}").json()["ok"]
        assert c.post("/api/presets/nope/play", json={}).status_code == 404
