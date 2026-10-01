"""Local-Wi-Fi multiplayer: lobby, phone controller, seats, and the LAN gate."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dotdeck.config import Config
from dotdeck.multiplayer import LanGate, is_local
from dotdeck.server import create_app


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def _ttt(c: TestClient) -> Any:
    eng = c.app.state.engine
    return eng._slot("tictactoe").app


def test_lobby_controller_and_seats(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        games = c.get("/api/play/lobby").json()["games"]
        assert any(g["id"] == "tictactoe" and g["max_players"] == 2 for g in games)
        assert c.post("/api/play/lobby", json={"app": "clock"}).status_code == 422  # not a multiplayer game

        r = c.post("/api/play/lobby", json={"app": "tictactoe"}).json()
        code, url = r["code"], r["url"]
        assert url.endswith(f"/p/{code}") and url.startswith("http://")
        assert len(url) <= 53, (
            "the join URL must fit a version-3 QR code (29 px: fits the panel at 1 px/module)"
        )
        assert _ttt(c).lobby_waiting()

        assert c.get(f"/p/{code}").status_code == 200
        assert "DotDeck controller" in c.get(f"/p/{code}").text
        assert c.get("/p/ZZZZ").status_code == 404

        with c.websocket_connect(f"/ws/p/{code}") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello" and hello["seat"] == 2
            game = _ttt(c)
            assert game.is_human(2) and not game.lobby_waiting()  # 2-player game full: the QR goes away
            before = game.curs[2]
            ws.send_text(json.dumps({"k": "right"}))
            ws.send_text(json.dumps({"type": "ping", "t": 1}))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                m = ws.receive_json()
                if m["type"] == "pong":
                    break
            assert game.curs[2] == (before // 3) * 3 + (before % 3 + 1) % 3, "seat 2's own cursor moved"
            assert game.curs[1] == 4, "seat 1's cursor is untouched"

            with c.websocket_connect(f"/ws/p/{code}") as ws2:  # a third phone: the game is full
                assert ws2.receive_json()["type"] == "full"

        for _ in range(50):  # the phone left: its seat is freed and the AI takes over again
            if not _ttt(c).is_human(2):
                break
            time.sleep(0.02)
        assert not _ttt(c).is_human(2)
        assert c.delete("/api/play/lobby").json()["ok"]
        assert _ttt(c).lobby_url is None


async def test_tictactoe_two_players_take_turns() -> None:
    from dotdeck.apps.games_board import TicTacToe
    from dotdeck.engine.app import AppSettings  # noqa: F401 — registry import side effect

    class Ctx:
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}

        def save(self) -> None: ...

    game = TicTacToe(Ctx(), TicTacToe.Settings())  # type: ignore[arg-type]
    await game.action("seat", {"player": 2, "joined": True})
    await game.action("input", {"key": "left", "player": 1})  # host takes over (fresh round, X to move)
    assert game.versus and game.turn == 1
    await game.action("input", {"key": "a", "player": 2})  # not O's turn: ignored
    assert game.board == (0,) * 9
    await game.action("input", {"key": "a", "player": 1})
    assert game.board.count(1) == 1 and game.turn == 2
    game.update(5.0)  # O is a person now: the AI must not move for them
    assert game.board.count(2) == 0
    await game.action("input", {"key": "up", "player": 2})
    await game.action("input", {"key": "a", "player": 2})
    assert game.board.count(2) == 1 and game.turn == 1
    assert game.status()["turn"] == 1 and game.status()["seats"][1]["human"]
    await game.action("input", {"key": "a", "player": 3})  # no such seat in a 2-player game: ignored
    assert game.board.count(1) == 1


@pytest.mark.parametrize(
    ("client", "path", "allowed"),
    [
        ("127.0.0.1", "/api/state", True),
        ("::1", "/", True),
        ("192.168.1.40", "/api/state", False),
        ("192.168.1.40", "/", False),
        ("192.168.1.40", "/p/AB12", True),
        ("192.168.1.40", "/ws/p/AB12", True),
    ],
)
def test_lan_gate(client: str, path: str, allowed: bool) -> None:
    reached: list[str] = []
    sent: list[dict[str, Any]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        reached.append(scope["path"])

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    gate = LanGate(inner)
    asyncio.run(gate({"type": "http", "path": path, "client": (client, 5000)}, None, send))
    assert bool(reached) == allowed
    if not allowed:
        assert sent[0]["status"] == 403
    assert is_local("127.0.0.1") and not is_local("10.0.0.2")


async def test_light_cycles_four_players_and_frame_size() -> None:
    from dotdeck.apps.games_party import LightCycles
    from dotdeck.gfx import Frame

    class Ctx:
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}

        def save(self) -> None: ...

    game = LightCycles(Ctx(), LightCycles.Settings())  # type: ignore[arg-type]
    for seat in (2, 3):
        await game.action("seat", {"player": seat, "joined": True})
    assert game.is_human(2) and game.is_human(3) and not game.is_human(4)
    game.countdown = 0
    await game.action("input", {"key": "up", "player": 2})  # seat 2 starts heading left; turns up
    game._step()
    assert game.bikes[2]["d"] == "up"
    await game.action(
        "input", {"key": "right", "player": 2}
    )  # can't reverse... but right is not a reverse of up
    game._step()
    assert game.bikes[2]["d"] == "right"
    # the AI keeps seat 4 alive for a while, and frames stay small (fits one BLE packet)
    sizes = []
    for _ in range(40):
        game._step()
        f = Frame()
        game.draw(f, 0.0)
        sizes.append(len(f.to_png()))
    assert game.bikes[4]["alive"] or game.result_t > 0
    assert sum(sizes) / len(sizes) < 500, f"mean frame {sum(sizes) / len(sizes):.0f} B"
    assert game.status()["max_players"] == 4


def test_local_second_player_and_controller_hints(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        meta = {a["id"]: a for a in c.get("/api/meta").json()["apps"]}
        assert meta["cycles"]["max_players"] == 4 and meta["cycles"]["controls"][0] == "swipe"
        assert meta["clock"]["max_players"] == 1
        with c.websocket_connect(
            "/ws"
        ) as ws:  # the studio's socket: a 2nd local player (other keyboard half)
            ws.send_text(json.dumps({"type": "input", "app": "pong", "key": "up", "player": 2}))
            ws.send_text(json.dumps({"type": "ping"}))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                m = ws.receive()
                if m.get("text") and '"pong"' in m["text"]:
                    break
        pong = c.app.state.engine._slot("pong").app
        assert pong.is_human(2) and pong.seats[2]["local"], "the 2nd local player took seat 2"
        pong.seats[2]["at"] -= 60  # idle for a minute: the AI takes the seat back
        assert not pong.is_human(2)
