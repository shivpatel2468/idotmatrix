"""The studio's casino mode: the host `view` op and moving a lobby between casino tables (docs/CASINO.md §6)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _client(tmp_path: Path) -> Any:
    from fastapi.testclient import TestClient

    from deskdot.config import Config
    from deskdot.server import create_app

    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def _state(ws: Any, pred: Any, timeout: float = 3.0) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        m = ws.receive_json()
        if m["type"] == "state" and pred(m):
            return m  # type: ignore[no-any-return]
    raise AssertionError("state never arrived")


def _op(c: Any, app: str, **payload: Any) -> Any:
    r = c.post(f"/api/apps/{app}/actions/casino", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_host_view_is_read_only_until_the_host_plays(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        c.post("/api/apps/casino_roulette/activate", json={})
        v = _op(c, "casino_roulette", op="view", spots=True)
        assert v["private"] == {"seated": False}  # looking never seats the host
        assert v["status"]["game"] == "roulette" and v["status"]["phase"] == "betting"
        ids = {s["id"] for s in v["spots"]}
        assert {"n:17", "red", "dz:2"} <= ids
        assert next(s for s in v["spots"] if s["id"] == "n:17")["pays"] == "35:1"
        assert "cat" in v["avatars"] and len(v["avatars"]["cat"]["px"]) == 8
        assert v["players"] == []
        assert "spots" not in _op(c, "casino_roulette", op="view")

        _op(c, "casino_roulette", op="bet", spot="red", amount=25)
        v = _op(c, "casino_roulette", op="view")
        me = v["private"]
        assert me["seated"] and me["bets"] == {"red": 25} and me["credits"] == 975 and "bet" in me["ops"]
        (host,) = v["players"]
        assert host["pid"] == "host" and host["seat"] == "host" and host["kicked"] is False


def test_lobby_switch_moves_phones_to_the_next_table(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "casino_roulette"}).json()["code"]
        with c.websocket_connect(f"/ws/p/{code}?cid=switchCID1") as a:
            seat = a.receive_json()["seat"]
            a.send_text(json.dumps({"type": "casino", "op": "bet", "spot": "red", "amount": 40}))
            _state(a, lambda m: m.get("private", {}).get("credits") == 960)

            r = c.post("/api/play/lobby/switch", json={"app": "casino_sevens"})
            assert r.status_code == 200 and r.json()["app"] == "casino_sevens" and r.json()["code"] == code
            assert c.get("/api/state").json()["engine"]["current"]["app"] == "casino_sevens"
            # the open roulette bet was refunded when its table closed; the phone sits at the dice table now
            m = _state(
                a, lambda m: m["status"].get("game") == "sevens" and m.get("private", {}).get("seated")
            )
            assert m["private"]["credits"] == 1000 and m["private"]["seat"] == seat
            a.send_text(json.dumps({"type": "casino", "op": "bet", "spot": "up", "amount": 10}))
            m = _state(a, lambda m: m.get("private", {}).get("bets") == {"up": 10})
            assert m["private"]["credits"] == 990

        # only casino rooms switch, and only to casino tables
        assert c.post("/api/play/lobby/switch", json={"app": "snake"}).status_code in (404, 422)


def test_lobby_switch_needs_an_open_room(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.post("/api/play/lobby/switch", json={"app": "casino_sevens"}).status_code == 404


def test_host_and_phones_bet_on_one_table(tmp_path: Path) -> None:
    """The host seat ("host") and phone seats (2…) share the bettors / done lists without breaking the status."""
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "casino_roulette"}).json()["code"]
        with c.websocket_connect(f"/ws/p/{code}?cid=mixedCID01") as a:
            seat = a.receive_json()["seat"]
            a.send_text(json.dumps({"type": "casino", "op": "bet", "spot": "n:17", "amount": 25}))
            _state(a, lambda m: m.get("private", {}).get("bets"))
            _op(c, "casino_roulette", op="bet", spot="red", amount=100)
            _op(c, "casino_roulette", op="done")
            st = _op(c, "casino_roulette", op="view")["status"]
            assert st["bettors"] == ["host", seat] and st["done"] == ["host"]
            assert c.get("/api/state").json()["engine"]["current"]["status"]["bettors"] == ["host", seat]
