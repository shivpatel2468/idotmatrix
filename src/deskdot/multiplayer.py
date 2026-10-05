"""Local-Wi-Fi multiplayer: friends join a game from their phones by scanning a QR code on the panel.

Flow: the studio opens a lobby for a game (`POST /api/play/lobby`). The engine shows the game with a full-screen
join QR code for `http://<this computer's LAN IP>:<port>/p/<code>`. A friend scans it, the phone opens a tiny
controller page (`CONTROLLER_HTML`, no install), and its WebSocket (`/ws/p/<code>`) is given the next free seat.
Every button press goes straight to `engine.action(app, "input", {"key", "player"})` — the same in-process path
as the host's keyboard, which wakes the engine at once, so a phone move lands on the next rendered frame.

Joining is a short flow on the phone: the socket gets a seat (`hello`), the player picks a name, colour, avatar
and (in team games) a side, then marks Ready; every change is a `profile` message the server sanitises
(`Room.apply_profile`) and forwards to the game, and every phone gets the live lobby list (`roster`). A phone keeps
a client id (`cid`) in localStorage and connects with `?cid=...`: a reconnect within `RESERVE_S` gets its seat and
profile back.

Security: the engine listens on the LAN so phones can reach it, but `LanGate` only lets non-local clients reach
the controller page and its socket, and only with a valid room code (plus the read-only TV view, docs/TV_VIEW.md).
The studio and API stay local-only unless `lan_studio = true` is set in deskdot.toml.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .gfx.avatars import AVATAR_IDS, AVATARS

SEAT_COLORS = {1: "#00c8ff", 2: "#ff3c5a", 3: "#50ff78", 4: "#ffc800"}
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O/1/I: easy to read aloud
#: colours a phone player may pick (LED-friendly, far apart on the panel). The seat defaults come first.
PLAYER_COLORS: dict[str, str] = {
    "#00c8ff": "Sky",
    "#ff3c5a": "Red",
    "#50ff78": "Lime",
    "#ffc800": "Gold",
    "#ff2d78": "Pink",
    "#ff7814": "Orange",
    "#9650ff": "Violet",
    "#1fe0ff": "Cyan",
    "#3264ff": "Blue",
    "#f0f0f0": "White",
}
NAME_MAX = 10
RESERVE_S = (
    20.0  # a phone that drops keeps its seat (and profile) this long for a reconnect with the same cid
)
_NAME_BAD = re.compile(r"[^A-Za-z0-9 !?.'_+&#*-]")  # only what the panel's bitmap fonts can draw
_CID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")


def clean_name(value: Any) -> str:
    """A display name the panel can draw: printable font characters only, single spaces, at most NAME_MAX."""
    if not isinstance(value, str):
        return ""
    return " ".join(_NAME_BAD.sub("", value[:64]).split())[:NAME_MAX].strip()


def clean_cid(value: Any) -> str | None:
    return value if isinstance(value, str) and _CID.match(value) else None


def clean_team(value: Any) -> tuple[bool, int | None]:
    """(valid, team): None = no preference, 0 = team A, 1 = team B."""
    if value is None:
        return True, None
    if type(value) is int and value in (0, 1):
        return True, value
    return False, None


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
    seats: dict[int, dict[str, Any]] = field(default_factory=dict)  # seat -> profile (see `join`)
    reserved: dict[int, tuple[float, dict[str, Any]]] = field(
        default_factory=dict
    )  # seat -> (until, profile)

    def _live_reservations(self) -> dict[int, dict[str, Any]]:
        t = time.monotonic()
        self.reserved = {n: r for n, r in self.reserved.items() if r[0] > t and n not in self.seats}
        return {n: r[1] for n, r in self.reserved.items()}

    def free_seat(self) -> int | None:
        held = self._live_reservations()
        for n in range(2, self.max_players + 1):
            if n not in self.seats and n not in held:
                return n
        return None

    def colour_of(self, seat: int) -> str:
        if seat in self.seats:
            return str(self.seats[seat]["color"])
        held = self._live_reservations().get(seat)
        return str(held["color"]) if held else SEAT_COLORS.get(seat, "#f0f0f0")

    def taken_colors(self, seat: int) -> set[str]:
        """Colours other seats show on the panel (the host's, phones', and the AI seats' defaults)."""
        return {self.colour_of(n) for n in range(1, self.max_players + 1) if n != seat}

    def join(self, cid: str | None) -> tuple[int, dict[str, Any], bool] | None:
        """Seat a phone: (seat, profile, resumed). A known `cid` gets its old seat and profile back if it is
        still connected (a page reload) or reserved; otherwise the next free seat with fresh defaults."""
        if cid:
            for n, p in self.seats.items():
                if p.get("cid") == cid:
                    return n, p, True
            for n, p in self._live_reservations().items():
                if p.get("cid") == cid:
                    del self.reserved[n]
                    self.seats[n] = p
                    return n, p, True
        seat = self.free_seat()
        if seat is None:
            return None
        taken = self.taken_colors(seat)
        color = SEAT_COLORS.get(seat, "")
        if color in taken or color not in PLAYER_COLORS:
            color = next((c for c in PLAYER_COLORS if c not in taken), "#f0f0f0")
        prof = {
            "name": f"P{seat}",
            "color": color,
            "avatar": AVATAR_IDS[(seat - 2) % len(AVATAR_IDS)],
            "team": None,
            "ready": False,
            "cid": cid,
        }
        self.seats[seat] = prof
        return seat, prof, False

    def leave(self, seat: int) -> None:
        """The phone's socket closed: free the seat, but hold it for a reconnect with the same cid."""
        prof = self.seats.pop(seat, None)
        if prof is not None and prof.get("cid"):
            prof["ready"] = False
            self.reserved[seat] = (time.monotonic() + RESERVE_S, prof)

    def apply_profile(self, seat: int, msg: dict[str, Any]) -> bool:
        """Apply a phone's `profile` message to its seat, keeping only valid values. True if anything changed.
        Never trusts the phone: names are filtered to drawable characters, colours must come from
        PLAYER_COLORS and be free, avatars must exist, teams are 0/1/None, ready is a real boolean."""
        p = self.seats.get(seat)
        if p is None:
            return False
        before = dict(p)
        if "name" in msg:
            p["name"] = clean_name(msg["name"]) or f"P{seat}"
        c = msg.get("color")
        if isinstance(c, str) and c.lower() in PLAYER_COLORS and c.lower() not in self.taken_colors(seat):
            p["color"] = c.lower()
        a = msg.get("avatar")
        if isinstance(a, str) and a in AVATARS:
            p["avatar"] = a
        if "team" in msg:
            ok, team = clean_team(msg["team"])
            if ok:
                p["team"] = team
        if isinstance(msg.get("ready"), bool):
            p["ready"] = msg["ready"]
        if not p.get("cid"):
            p["cid"] = clean_cid(msg.get("cid"))
        return p != before

    def roster(self) -> list[dict[str, Any]]:
        """Everyone in the lobby, for the phones: the host (seat 1) and every seated phone."""
        out: list[dict[str, Any]] = [
            {
                "seat": 1,
                "name": "HOST",
                "color": SEAT_COLORS[1],
                "avatar": None,
                "team": None,
                "ready": True,
                "host": True,
            }
        ]
        for n, p in sorted(self.seats.items()):
            out.append(
                {
                    "seat": n,
                    "name": p["name"],
                    "color": p["color"],
                    "avatar": p["avatar"],
                    "team": p["team"],
                    "ready": bool(p["ready"]),
                    "host": False,
                }
            )
        return out


class Lobby:
    """One room at a time (one panel). Opening a new lobby replaces the old one."""

    def __init__(self, host: str, port: int, public_url: str | None = None) -> None:
        self.bind_host = host
        self.port = port
        #: the web app: phones join over the internet (idotmatrix.com/p/<code>, a WebRTC tunnel to the tab)
        self.public_url = public_url.rstrip("/") if public_url else None
        self.room: Room | None = None

    @property
    def lan_ready(self) -> bool:
        """Can phones reach us? Only if the server listens beyond loopback (or the web app's relay is on)."""
        return self.public_url is not None or not is_local(self.bind_host)

    def open(self, app: str, max_players: int, avoid: str | None = None) -> Room:
        """`avoid`: a code that must not be reused (the open TV link's, docs/TV_VIEW.md)."""
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if code != (avoid or "").upper():
                break
        self.room = Room(code=code, app=app, max_players=max_players)
        return self.room

    def close(self) -> None:
        self.room = None

    def url(self) -> str | None:
        if self.room is None:
            return None
        if self.public_url:
            return f"{self.public_url}/p/{self.room.code}"
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
                {
                    "seat": n,
                    "name": s["name"],
                    "color": s.get("color") or SEAT_COLORS.get(n),
                    "avatar": s.get("avatar"),
                    "ready": bool(s.get("ready")),
                }
                for n, s in sorted(r.seats.items())
            ],
        }


class LanGate:
    """ASGI middleware: clients that aren't on this computer may only use the phone controller (/p/, /ws/p/) and
    the read-only TV view (/tv/, /ws/tv/ — docs/TV_VIEW.md); both check their code."""

    ALLOWED = ("/p/", "/ws/p/", "/tv/", "/ws/tv/")

    def __init__(self, app: Any, allow_all: bool = False) -> None:
        self.app = app
        self.allow_all = allow_all

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket") and not self.allow_all:
            client = (scope.get("client") or (None, None))[0]
            path = scope.get("path", "")
            if not is_local(client) and (not path.startswith(self.ALLOWED) or ".." in path or "\\" in path):
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
                        "body": b"DeskDot: the studio is only available on this computer.",
                    }
                )
                return
        await self.app(scope, receive, send)


def game_profile(prof: dict[str, Any]) -> dict[str, Any]:
    """The part of a phone's profile the game draws (never the cid)."""
    return {k: prof.get(k) for k in ("name", "color", "avatar", "team", "ready")}


def player_pid(cid: Any) -> str | None:
    """A stable player id derived from a phone's client id: casino wallets follow it across reconnects and seat
    changes. One-way, so the game (and the studio) never see the cid itself."""
    c = clean_cid(cid)
    if c is None:
        return None
    return "p" + hashlib.sha256(f"deskdot-player:{c}".encode()).hexdigest()[:15]


def avatar_table() -> list[dict[str, Any]]:
    return [{"id": k, "name": v[0], "px": list(v[1])} for k, v in AVATARS.items()]


# The phone controller page: one self-contained file (inline CSS/JS, no CDNs; phones on the LAN may be offline).
# Read once at import, so edits go live when the engine restarts.
CONTROLLER_HTML = Path(__file__).with_name("controller.html").read_text(encoding="utf-8")
# The phone casino page (docs/CASINO.md §5), served instead when the lobby's app is in category "casino".
CASINO_HTML = Path(__file__).with_name("casino.html").read_text(encoding="utf-8")
