"""Local-Wi-Fi multiplayer: friends join a game from their phones by scanning a QR code on the panel.

Flow: the studio opens a lobby for a game (`POST /api/play/lobby`). The engine shows the game with a full-screen
join QR code for `http://<this computer's LAN IP>:<port>/p/<code>`. A friend scans it, the phone opens a tiny
controller page (`CONTROLLER_HTML`, no install), and its WebSocket (`/ws/p/<code>`) is given the next free seat.
Every button press goes straight to `engine.action(app, "input", {"key", "player"})` — the same in-process path
as the host's keyboard, which wakes the engine at once, so a phone move lands on the next rendered frame.

Security: the engine listens on the LAN so phones can reach it, but `LanGate` only lets non-local clients reach
the controller page and its socket, and only with a valid room code. The studio and API stay local-only unless
`lan_studio = true` is set in dotdeck.toml.
"""

from __future__ import annotations

import ipaddress
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEAT_COLORS = {1: "#00c8ff", 2: "#ff3c5a", 3: "#50ff78", 4: "#ffc800"}
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O/1/I: easy to read aloud


def lan_ip() -> str:
    """This computer's address on the local network (no traffic is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def is_local(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "testclient")


@dataclass
class Room:
    code: str
    app: str
    max_players: int
    created: float = field(default_factory=time.monotonic)
    seats: dict[int, dict[str, Any]] = field(default_factory=dict)  # seat -> {"name", "sockets"}

    def free_seat(self) -> int | None:
        for n in range(2, self.max_players + 1):
            if n not in self.seats:
                return n
        return None


class Lobby:
    """One room at a time (one panel). Opening a new lobby replaces the old one."""

    def __init__(self, host: str, port: int) -> None:
        self.bind_host = host
        self.port = port
        self.room: Room | None = None

    @property
    def lan_ready(self) -> bool:
        """Can phones reach us? Only if the server listens beyond loopback."""
        return not is_local(self.bind_host)

    def open(self, app: str, max_players: int) -> Room:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        self.room = Room(code=code, app=app, max_players=max_players)
        return self.room

    def close(self) -> None:
        self.room = None

    def url(self) -> str | None:
        if self.room is None:
            return None
        return f"http://{lan_ip()}:{self.port}/p/{self.room.code}"

    def valid(self, code: str) -> bool:
        return self.room is not None and secrets.compare_digest(code.upper(), self.room.code)

    def snapshot(self) -> dict[str, Any] | None:
        r = self.room
        if r is None:
            return None
        return {
            "code": r.code,
            "app": r.app,
            "url": self.url(),
            "max_players": r.max_players,
            "lan_ready": self.lan_ready,
            "seats": [
                {"seat": n, "name": s["name"], "color": SEAT_COLORS.get(n)}
                for n, s in sorted(r.seats.items())
            ],
        }


class LanGate:
    """ASGI middleware: clients that aren't on this computer may only use the phone controller (/p/, /ws/p/)."""

    ALLOWED = ("/p/", "/ws/p/")

    def __init__(self, app: Any, allow_all: bool = False) -> None:
        self.app = app
        self.allow_all = allow_all

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket") and not self.allow_all:
            client = (scope.get("client") or (None, None))[0]
            path = scope.get("path", "")
            if not is_local(client) and not path.startswith(self.ALLOWED):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"DotDeck: the studio is only available on this computer.",
                    }
                )
                return
        await self.app(scope, receive, send)


# The phone controller page: one self-contained file (inline CSS/JS, no CDNs; phones on the LAN may be offline).
# Read once at import, so edits go live when the engine restarts.
CONTROLLER_HTML = Path(__file__).with_name("controller.html").read_text(encoding="utf-8")
