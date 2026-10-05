"""Local-Wi-Fi multiplayer: lobby, phone controller, seats, and the LAN gate."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot.config import Config
from deskdot.multiplayer import LanGate, is_local
from deskdot.server import create_app


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
        assert "DeskDot controller" in c.get(f"/p/{code}").text
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
    from deskdot.apps.games_board import TicTacToe
    from deskdot.engine.app import AppSettings  # noqa: F401 — registry import side effect

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
    from deskdot.apps.games_party import LightCycles
    from deskdot.gfx import Frame

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


# ---------------------------------------------------------------- join flow: profiles, roster, reconnect


def _recv(ws: Any, kind: str, timeout: float = 2.0) -> dict[str, Any]:
    """The next message of `kind` (state pushes and other messages in between are skipped)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        m = ws.receive_json()
        if m["type"] == kind:
            return m
    raise AssertionError(f"no {kind!r} message")


def _cycles(c: TestClient) -> Any:
    return c.app.state.engine._slot("cycles").app


def _roster_until(ws: Any, ok: Any) -> dict[str, Any]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        r = _recv(ws, "roster")
        if ok(r["players"]):
            return r
    raise AssertionError("roster never matched")


def test_profile_sets_seat_data_and_broadcasts_roster(tmp_path: Path) -> None:
    from deskdot.gfx.avatars import AVATAR_IDS

    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "cycles"}).json()["code"]
        with (
            c.websocket_connect(f"/ws/p/{code}?cid=phone-aaaa-1111") as a,
            c.websocket_connect(f"/ws/p/{code}?cid=phone-bbbb-2222") as b,
        ):
            ha = _recv(a, "hello")
            assert ha["seat"] == 2 and ha["cid"] == "phone-aaaa-1111"
            assert ha["profile"]["name"] == "P2" and not ha["resumed"]
            assert {p["color"] for p in ha["palette"]} >= {"#ff2d78", "#ffc800"}
            assert [x["id"] for x in ha["avatars"]] == list(AVATAR_IDS)
            assert all(len(r) == 8 for x in ha["avatars"] for r in x["px"])
            assert any(m["teams"] == "versus" for m in ha["modes"])
            hb = _recv(b, "hello")
            assert hb["seat"] == 3 and hb["color"] != ha["color"]

            a.send_text(
                json.dumps(
                    {"type": "profile", "name": "Ana", "color": "#FF2D78", "avatar": "ghost", "team": 1}
                )
            )
            roster = _roster_until(b, lambda ps: any(p["name"] == "Ana" for p in ps))
            me = next(p for p in roster["players"] if p["seat"] == 2)
            assert me == {
                "seat": 2,
                "name": "Ana",
                "color": "#ff2d78",
                "avatar": "ghost",
                "team": 1,
                "ready": False,
                "host": False,
            }
            assert roster["players"][0]["host"] and roster["players"][0]["seat"] == 1

            game = _cycles(c)
            assert game.seats[2]["name"] == "Ana" and game.seats[2]["avatar"] == "ghost"
            assert game.seat_colour(2) == (255, 45, 120) and game.colour_of(2) == (255, 45, 120)
            assert game.seats[2]["team"] == 1
            assert "cid" not in game.seats[2], "the client id stays on the server"

            # b can't take a's colour (nor the host's): the pick is refused and b keeps its own
            b.send_text(json.dumps({"type": "profile", "color": "#ff2d78"}))
            b.send_text(json.dumps({"type": "profile", "color": "#00c8ff", "ready": True}))
            r = _roster_until(b, lambda ps: any(p["seat"] == 3 and p["ready"] for p in ps))
            pb = next(p for p in r["players"] if p["seat"] == 3)
            assert pb["color"] == hb["color"]
            assert game.seats[3]["ready"] and game.join_card is not None and game.join_card[2] == "READY"
            st = game.status()
            assert st["seats"][1]["name"] == "Ana" and st["seats"][1]["color"] == "#ff2d78"


def test_profile_input_is_sanitised() -> None:
    from deskdot.multiplayer import NAME_MAX, Room, clean_cid, clean_name

    assert clean_name("  <b>Zo\u00eb</b>  the\n\tgreat ") == "bZob thegr"
    assert clean_name("x" * 50) == "x" * NAME_MAX
    assert clean_name("<script>") == "script"
    assert clean_name(123) == "" and clean_name(None) == ""
    assert clean_cid("short") is None and clean_cid("ok_client-id-1") == "ok_client-id-1"
    assert clean_cid("bad id with spaces!") is None and clean_cid(["x"]) is None

    room = Room("ABCD", "cycles", 4)
    got = room.join(None)
    assert got is not None
    seat, prof, _ = got
    before = dict(prof)
    room.apply_profile(
        seat,
        {
            "name": "\u200b\u202e",  # only invisible / control characters: falls back to the seat name
            "color": "#123456",  # not in the palette
            "avatar": "../../etc/passwd",
            "team": True,  # bools are not teams
            "ready": "yes",  # only real booleans
        },
    )
    assert room.seats[seat] == {**before, "name": f"P{seat}"}
    room.apply_profile(seat, {"team": 7})
    assert room.seats[seat]["team"] is None
    room.apply_profile(seat, {"team": 0, "ready": True, "avatar": "frog", "name": "A" * 99})
    p = room.seats[seat]
    assert p["team"] == 0 and p["ready"] is True and p["avatar"] == "frog" and p["name"] == "A" * NAME_MAX
    assert room.colour_of(1) not in {room.colour_of(s) for s in room.seats}, "nobody wears the host's colour"
    room.apply_profile(seat, {"color": "#50ff78"})  # seat 3's default while the AI plays it: taken
    assert room.seats[seat]["color"] != "#50ff78"


def test_controller_ignores_bad_messages_and_keys(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "cycles"}).json()["code"]
        with c.websocket_connect(f"/ws/p/{code}?cid=bad%20id%21") as ws:
            hello = _recv(ws, "hello")
            assert hello["cid"] is None  # an invalid cid is dropped: still playable, just no reclaim
            junk = ["not json", "[1,2]", json.dumps({"k": "rm -rf"}), "x" * 5000, json.dumps({"k": None})]
            for bad in junk:
                ws.send_text(bad)
            ws.send_text(json.dumps({"type": "ping", "t": "<img>"}))
            assert _recv(ws, "pong")["t"] is None, "only numbers are echoed"
            ws.send_text(json.dumps({"type": "ping", "t": 5}))
            assert _recv(ws, "pong")["t"] == 5, "the socket survived the junk"


def test_reconnect_reclaims_seat_by_cid(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "cycles"}).json()["code"]
        with c.websocket_connect(f"/ws/p/{code}?cid=phone-keep-0001") as ws:
            assert _recv(ws, "hello")["seat"] == 2
            ws.send_text(json.dumps({"type": "profile", "name": "Keeper", "color": "#9650ff", "ready": True}))
            _roster_until(ws, lambda ps: any(p["name"] == "Keeper" for p in ps))
        for _ in range(50):  # the phone dropped: the AI plays its seat meanwhile
            if 2 not in _cycles(c).seats:
                break
            time.sleep(0.02)
        assert 2 not in _cycles(c).seats
        with c.websocket_connect(f"/ws/p/{code}?cid=phone-new-9999") as other:
            assert _recv(other, "hello")["seat"] == 3, "a newcomer doesn't take the reserved seat"
            with c.websocket_connect(f"/ws/p/{code}?cid=phone-keep-0001") as again:
                h = _recv(again, "hello")
                assert h["seat"] == 2 and h["resumed"]
                assert h["profile"]["name"] == "Keeper" and h["color"] == "#9650ff"
                assert not h["profile"]["ready"], "a reconnect confirms Ready again"
                assert _cycles(c).seats[2]["name"] == "Keeper"
                # the same phone opening the page twice takes over its seat; the old tab is told so
                with c.websocket_connect(f"/ws/p/{code}?cid=phone-keep-0001") as third:
                    assert _recv(third, "hello")["seat"] == 2
                    assert _recv(again, "replaced")["type"] == "replaced"


async def test_panel_uses_picked_name_colour_and_team() -> None:
    from deskdot.apps.games_party import LightCycles
    from deskdot.gfx import Frame

    class Ctx:
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}

        def save(self) -> None: ...

    game = LightCycles(Ctx(), LightCycles.Settings())  # type: ignore[arg-type]
    game.lobby_url = "http://192.168.1.2:8765/p/ABCD"
    await game.action(
        "seat", {"player": 2, "joined": True, "name": "Ana", "color": "#9650ff", "avatar": "cat", "team": 0}
    )
    assert game.seat_colour(2) == (150, 80, 255) and game.rgb(2) == (150, 80, 255)
    f = Frame()
    game.render(f, 0.0)  # the join card: avatar + name in the picked colour
    assert (f.px == (150, 80, 255)).all(axis=2).any()
    await game.action("seat", {"player": 2, "joined": True, "color": "javascript:x", "avatar": "nope"})
    assert game.seat_colour(2) == (255, 60, 90) and game.seats[2]["avatar"] is None, "bad values fall back"
    await game.action("seat", {"player": 2, "joined": True, "name": "Ana", "team": 0})
    game.lobby_url = None
    await game.action("start", {"mode": "teams", "players": 2})
    assert game.flow == "teams" and game.team_of(2) == 0, "the side picked on the phone is used"
    await game.action("seat", {"player": 2, "joined": True, "name": "Ana", "team": 1})
    assert game.team_of(2) == 1, "changing side on the phone moves the player on the side-select screen"
    game.draw_teams(Frame(), 0.0)
    game.result(winner_seat=2)
    game.draw_outro(Frame(), 0.0)


@pytest.mark.parametrize("app_id", ["leafleap", "digworld"])
async def test_phone_can_take_a_seat_in_world_games(engine, app_id: str) -> None:  # type: ignore[no-untyped-def]
    """Leaf Leap and Dig World once shadowed GameApp._seat() with an int, so a phone joining crashed."""
    game = engine._slot(app_id).app
    await game.action("seat", {"player": 2, "joined": True, "name": "PHONE"})
    assert game.seats[2]["name"] == "PHONE"
