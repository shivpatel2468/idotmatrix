"""Coordinated panel hand-over between DeskDot instances (ADR 0015).

The panel accepts one Bluetooth central at a time. People drive it from several places — DeskDot on a laptop, the
DeskDot Android app, the web app in a browser tab — and moving it used to mean finding the app that held it, pressing
Release there, then Reconnect here, with a fair chance of a stuck panel in between. This module makes it one button:
**Use the panel here**.

Pieces (all pure asyncio, no new dependencies):

* **Discovery** — a small UDP broadcast beacon on the LAN (port 8767, every 4 s): who I am, whether I hold the panel,
  and whether I hold the *connect lease*. Only sent and accepted on private networks (RFC 1918 / link-local), and
  only while the user's "Find other DeskDots on this network" setting is on (`handover.enabled`).
* **Lease** — at most one instance may be connecting at a time. An instance taking the panel claims the lease (in its
  beacon, and the holder grants it when it lets go); others' supervisors stay quiet while it is held
  (`Device.gate`). Leases expire (30 s), so a crashed instance never blocks the panel.
* **Pairing** — once per pair of installs. B asks A to pair; both show the same 6-digit code; the user allows it on A;
  A hands B a random 256-bit key (the only moment a secret crosses the LAN). After that every hand-over request is
  signed (HMAC-SHA256 over method, path, timestamp, nonce and body hash), fresh (±120 s), never replayed (nonce
  cache) and rate-limited.
* **Hand-over** — B: claim the lease → ask A to let go (`POST /lan/handover/release`, signed) → A finishes the write in
  flight (a GIF upload waits for its chunk acks), disconnects and disposes its GATT session, marks itself released
  ("Panel moved to B", no auto-reconnect) and acks → B waits for the panel to advertise → connects (the device
  supervisor, jittered back-off) → announces it holds the panel. If A can't be reached, B says who probably has the
  panel and offers a safe force path (wait for the advertisement, try once, explain).
* **The browser tab on this computer** can't use UDP. It talks to this engine over loopback (the web app is already
  allowed to probe `/api/health` with Private-Network-Access headers): it reports whether it holds the panel
  (`POST /api/handover/tab`, which answers "please let go" when someone wants it) and asks this engine to free the
  panel for it (`POST /api/handover/free`) — including relaying the request to a phone on the LAN, which an https
  page can't reach itself.

HTTP routes live in `handover_api.py`; the device layer's part (graceful release, stack reset, recovery) in
`device/base.py`. Tests: tests/test_handover.py (three contending instances on a fake panel, auth, lease).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import time
import uuid
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .device.base import Device

log = logging.getLogger("deskdot.handover")

BEACON_PORT = 8767
BEACON_EVERY = 4.0  # s between beacons (and right away on every change)
PEER_FRESH = 15.0  # s: a peer heard from within this is "nearby"
PEER_FORGET = 600.0  # s: unpaired peers not heard from in this long drop off the list
LEASE_TTL = 30.0  # s: a connect lease nobody renews expires
TAB_FRESH = 10.0  # s: the browser tab on this computer reports every ~3 s
CLOCK_SKEW = 120.0  # s: signed requests older / newer than this are refused
PAIR_TTL = 180.0  # s: a pairing request expires
RELEASE_WAIT_TAB = 15.0  # s: how long a release waits for the browser tab to let go
ADVERT_WAIT = 20.0  # s: how long the taker waits for the panel to advertise
CONNECT_WAIT = 50.0  # s: how long the taker waits for its supervisor to connect

TAB_ID = "tab"  # the browser tab on this computer, as a pseudo-peer

#: signed request headers
H_PEER, H_TS, H_NONCE, H_SIG = "x-deskdot-peer", "x-deskdot-ts", "x-deskdot-nonce", "x-deskdot-sig"


# ====================================================================== small, pure parts (unit-tested)
def is_private(addr: str | None) -> bool:
    """A LAN address we talk to: RFC 1918, link-local or loopback — never a public one."""
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return (
        (ip.is_private or ip.is_link_local or ip.is_loopback)
        and not ip.is_multicast
        and not ip.is_unspecified
    )


def signature(key: bytes, method: str, path: str, ts: str, nonce: str, body: bytes) -> str:
    msg = "\n".join([method.upper(), path, ts, nonce, hashlib.sha256(body).hexdigest()]).encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def pair_code(id_a: str, nonce_a: str, id_b: str, nonce_b: str) -> str:
    """The 6-digit code both sides show while pairing (order-independent)."""
    (i1, n1), (i2, n2) = sorted([(id_a, nonce_a), (id_b, nonce_b)])
    digest = hashlib.sha256(f"deskdot-pair|{i1}|{n1}|{i2}|{n2}".encode()).hexdigest()
    n = int(digest[:12], 16) % 1_000_000
    return f"{n // 1000:03d} {n % 1000:03d}"


@dataclass
class Lease:
    owner: str
    name: str
    until: float
    via: str | None = None  # the instance whose beacon told us about it (None: granted here)


class LeaseTable:
    """Who may connect to the panel right now. One owner at a time; a lease nobody renews expires."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self._lease: Lease | None = None

    def current(self) -> Lease | None:
        if self._lease and self._lease.until <= self.clock():
            self._lease = None
        return self._lease

    def grant(self, owner: str, name: str, ttl: float = LEASE_TTL) -> bool:
        """Grant (or renew) the lease. False when someone else holds an unexpired one."""
        cur = self.current()
        if cur and cur.owner != owner:
            return False
        self._lease = Lease(owner, name, self.clock() + ttl)
        return True

    def note(self, owner: str, name: str, until: float, via: str | None = None) -> None:
        """Record a lease another instance announced (its beacon). Never overrides one we granted to someone else."""
        cur = self.current()
        if (cur is None or cur.owner == owner or (via and cur.via == via)) and until > self.clock():
            self._lease = Lease(owner, name, until, via)

    def forget_via(self, via: str) -> None:
        """That instance's beacon no longer carries a lease: drop the one we learned from it."""
        if self._lease and self._lease.via == via:
            self._lease = None

    def release(self, owner: str) -> None:
        if self._lease and self._lease.owner == owner:
            self._lease = None

    def held_by_other(self, me: str) -> Lease | None:
        cur = self.current()
        return cur if cur and cur.owner != me else None


class RateLimiter:
    """At most `n` events per `per` seconds for each key (sliding window)."""

    def __init__(self, n: int, per: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.n, self.per, self.clock = n, per, clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = self.clock()
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= now - self.per:
            q.popleft()
        if len(q) >= self.n:
            return False
        q.append(now)
        if len(self._hits) > 512:  # bounded memory under a flood of keys
            for k in [k for k, v in self._hits.items() if not v][:256]:
                del self._hits[k]
        return True


class NonceCache:
    def __init__(self, ttl: float = 2 * CLOCK_SKEW, clock: Callable[[], float] = time.time) -> None:
        self.ttl, self.clock = ttl, clock
        self._seen: dict[str, float] = {}

    def fresh(self, nonce: str) -> bool:
        now = self.clock()
        if len(self._seen) > 2048:
            self._seen = {k: t for k, t in self._seen.items() if t > now - self.ttl}
        if nonce in self._seen and self._seen[nonce] > now - self.ttl:
            return False
        self._seen[nonce] = now
        return True


@dataclass
class Peer:
    id: str
    name: str
    kind: str  # "ble" (a computer), "android", "web" (the browser tab on this computer)
    addr: str | None = None
    port: int = 8765
    holding: bool = False
    panel: str | None = None
    since: float | None = None  # epoch s it has held the panel
    last_seen: float = 0.0
    last_holding_at: float | None = None  # the last time it said it held the panel (for "probably held by")
    lease_until: float | None = None
    paired: bool = False

    def public(self, now: float) -> dict[str, Any]:
        d = asdict(self)
        d["online"] = now - self.last_seen < PEER_FRESH
        d["ago"] = round(now - self.last_seen, 1) if self.last_seen else None
        return d


class Transport(Protocol):
    async def post(
        self, peer: Peer, path: str, body: dict[str, Any], headers: dict[str, str]
    ) -> tuple[int, dict[str, Any]]: ...


class HttpTransport:
    """Talks to a peer's LAN endpoint over plain HTTP (the payloads are signed, not secret)."""

    def __init__(self, timeout: float = 6.0) -> None:
        self.timeout = timeout

    async def post(
        self, peer: Peer, path: str, body: dict[str, Any], headers: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        import httpx

        if not peer.addr or not is_private(peer.addr):
            raise ConnectionError(f"{peer.name} has no LAN address")
        host = f"[{peer.addr}]" if ":" in peer.addr else peer.addr
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(
                f"http://{host}:{peer.port}{path}",
                content=json.dumps(body).encode(),
                headers={**headers, "content-type": "application/json"},
            )
        try:
            data = r.json()
        except ValueError:
            data = {"detail": r.text[:200]}
        return r.status_code, data if isinstance(data, dict) else {"detail": data}


class AuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


# ====================================================================== the coordinator
class Handover:
    """One per engine. Owns the peer table, the lease, pairing and the hand-over flow."""

    def __init__(
        self,
        device: Device,
        data_dir: Path,
        *,
        kind: str,
        name: str | None = None,
        port: int = 8765,
        enabled: bool = True,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.time,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.device = device
        self.path = data_dir / "handover.json"
        self.kind = kind
        self.port = port
        self.enabled = enabled
        self.transport: Transport = transport or HttpTransport()
        self.clock = clock
        self.on_change = on_change or (lambda: None)
        saved = self._load()
        self.id: str = saved.get("id") or uuid.uuid4().hex[:16]
        self.name: str = name or saved.get("name") or default_name(kind)
        self.keys: dict[str, bytes] = {}
        self.peers: dict[str, Peer] = {}
        for pid, p in (saved.get("peers") or {}).items():
            try:
                self.keys[pid] = bytes.fromhex(p["key"])
                self.peers[pid] = Peer(
                    id=pid,
                    name=str(p.get("name") or pid),
                    kind=str(p.get("kind") or "ble"),
                    addr=p.get("addr"),
                    port=int(p.get("port") or 8765),
                    paired=True,
                )
            except (KeyError, ValueError, TypeError):
                continue
        self.lease = LeaseTable(clock)
        self.nonces = NonceCache(clock=clock)
        self.limit_peer = RateLimiter(10, 60.0)
        self.limit_addr = RateLimiter(30, 60.0)
        self.limit_pair = RateLimiter(5, 60.0)
        self.progress: dict[str, Any] | None = None
        self.moved_to: dict[str, Any] | None = (
            None  # {id, name, at}: we let go of the panel for this instance
        )
        self.tab: dict[str, Any] | None = None  # the browser tab on this computer: {holding, panel, at, want}
        self.pair_in: dict[str, dict[str, Any]] = {}  # requests to pair with us, waiting for the user
        self.pair_out: dict[str, dict[str, Any]] = {}  # our requests, waiting for the other side's user
        self._task: asyncio.Task[None] | None = None
        self._tab_changed = asyncio.Event()
        self._beacon: _Beacon | None = None
        self._holding_since: float | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        #: our own hand-over's phase: while it asks the holder and waits for the advertisement, our supervisor must
        #: not connect (it would scan alongside us, and a panel we already hold never advertises)
        self._phase: str | None = None
        device.gate = self.gate if enabled else None
        if not saved.get("id"):
            self._save()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        peers = {
            pid: {"name": p.name, "kind": p.kind, "addr": p.addr, "port": p.port, "key": self.keys[pid].hex()}
            for pid, p in self.peers.items()
            if pid in self.keys
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"id": self.id, "name": self.name, "peers": peers}, indent=1), "utf-8")
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
            tmp.replace(self.path)
        except OSError as e:  # pragma: no cover — disk trouble: pairing just won't survive a restart
            log.warning("handover: can't save %s: %s", self.path, e)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.enabled and self._beacon is None:
            self._beacon = _Beacon(self)
            await self._beacon.start()

    async def stop(self) -> None:
        for t in [self._task, *self._tasks]:
            if t and not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        if self._beacon:
            await self._beacon.stop()
            self._beacon = None

    async def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self.device.gate = self.gate if on else None
        if on:
            await self.start()
        elif self._beacon:
            await self._beacon.stop()
            self._beacon = None
        self.changed()

    def _bg(self, coro: Coroutine[Any, Any, Any]) -> None:
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    def changed(self) -> None:
        if self._beacon:
            self._beacon.kick()
        self.on_change()

    # ------------------------------------------------------------------ who holds the panel
    def _tab_fresh(self) -> dict[str, Any] | None:
        t = self.tab
        return t if t and self.clock() - t["at"] < TAB_FRESH else None

    def holding(self) -> bool:
        """This engine (or the browser tab it speaks for) holds the panel."""
        tab = self._tab_fresh()
        return self.device.connected or bool(tab and tab["holding"])

    def holder_peer(self) -> Peer | None:
        """The nearby instance that says it holds the panel (fresh beacon), if any."""
        now = self.clock()
        for p in self.peers.values():
            if p.holding and now - p.last_seen < PEER_FRESH:
                return p
        return None

    def probable_holder(self) -> Peer | None:
        """Who most likely has it when nobody nearby says so: the peer that last claimed it."""
        cands = [p for p in self.peers.values() if p.last_holding_at]
        return max(cands, key=lambda p: p.last_holding_at or 0) if cands else None

    def gate(self) -> str | None:
        """Device.gate: a reason to hold automatic connect attempts back (another instance has or is taking it)."""
        if not self.enabled:
            return None
        if self._task and not self._task.done():
            return "Moving the panel here…" if self._phase in ("ask", "waiting") else None
        if self.device.connected:
            return None
        lease = self.lease.held_by_other(self.id)
        if lease:
            return (
                f"{lease.name} is connecting to the panel. Press Use the panel here to bring it here instead."
            )
        tab = self._tab_fresh()
        if tab and tab["holding"]:
            return "A DeskDot browser tab on this computer has the panel. Press Use the panel here to move it here."
        p = self.holder_peer()
        if p:
            return f"{p.name} has the panel. Press Use the panel here to move it here."
        return None

    # ------------------------------------------------------------------ beacons
    def beacon(self) -> dict[str, Any]:
        lease = self.lease.current()
        holding = self.holding()
        if holding and self._holding_since is None:
            self._holding_since = self.clock()
        elif not holding:
            self._holding_since = None
        tab = self._tab_fresh()
        return {
            "app": "deskdot",
            "v": 1,
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "port": self.port,
            "holding": holding,
            "via": "tab" if holding and not self.device.connected else None,
            "panel": self.device.info.name or (tab or {}).get("panel"),
            "since": self._holding_since,
            "lease": {"owner": lease.owner, "name": lease.name, "until": lease.until} if lease else None,
        }

    def on_beacon(self, msg: dict[str, Any], addr: str | None) -> None:
        """A beacon from the LAN (or a fake one in tests)."""
        if not self.enabled or not isinstance(msg, dict) or msg.get("app") != "deskdot":
            return
        pid = str(msg.get("id") or "")[:32]
        if not pid or pid == self.id or (addr is not None and not is_private(addr)):
            return
        now = self.clock()
        p = self.peers.get(pid)
        if p is None:
            if len(self.peers) >= 32:
                return
            p = self.peers[pid] = Peer(id=pid, name="", kind="ble")
        was_holding = p.holding and now - p.last_seen < PEER_FRESH
        p.name = str(msg.get("name") or pid)[:48]
        p.kind = str(msg.get("kind") or "ble")[:12]
        p.addr = addr or p.addr
        with contextlib.suppress(TypeError, ValueError):
            p.port = int(msg.get("port") or 8765)
        p.holding = bool(msg.get("holding"))
        p.panel = str(msg["panel"])[:32] if msg.get("panel") else None
        p.since = msg.get("since") if isinstance(msg.get("since"), int | float) else None
        p.last_seen = now
        if p.holding:
            p.last_holding_at = now
        lease = msg.get("lease")
        if p.holding:
            self.lease.release(pid)  # it got the panel: its lease has done its job
        if isinstance(lease, dict) and isinstance(lease.get("until"), int | float):
            owner = str(lease.get("owner") or "")[:32]
            if owner and owner != self.id:
                # their clock may differ: keep the remaining time, capped
                sent = (
                    msg.get("now") if isinstance(msg.get("now"), int | float) else lease["until"] - LEASE_TTL
                )
                remaining = min(LEASE_TTL, float(lease["until"]) - float(sent))
                self.lease.note(
                    owner, str(lease.get("name") or p.name)[:48], now + max(0.0, remaining), via=pid
                )
        else:
            self.lease.forget_via(pid)
        if was_holding and not p.holding:
            self.device.retry_now()  # the holder let go: an instance waiting at the gate may try now
        self._forget_old(now)
        self.on_change()

    def _forget_old(self, now: float) -> None:
        for pid in [pid for pid, p in self.peers.items() if not p.paired and now - p.last_seen > PEER_FORGET]:
            del self.peers[pid]

    # ------------------------------------------------------------------ signing
    def _signed_headers(self, peer: Peer, path: str, body: dict[str, Any]) -> dict[str, str]:
        key = self.keys[peer.id]
        ts, nonce = str(int(self.clock())), secrets.token_hex(12)
        raw = json.dumps(body).encode()
        return {
            H_PEER: self.id,
            H_TS: ts,
            H_NONCE: nonce,
            H_SIG: signature(key, "POST", path, ts, nonce, raw),
        }

    def verify(self, method: str, path: str, headers: dict[str, str], body: bytes, addr: str | None) -> Peer:
        """Authenticate a signed LAN request. Raises AuthError(status, message)."""
        if not self.enabled:
            raise AuthError(404, "hand-over is off on this DeskDot")
        if addr is not None and not is_private(addr):
            raise AuthError(403, "only from the local network")
        if not self.limit_addr.allow(addr or "?"):
            raise AuthError(429, "too many requests")
        pid = headers.get(H_PEER, "")
        key = self.keys.get(pid)
        if key is None:
            raise AuthError(401, "not paired")
        ts, nonce, sig = headers.get(H_TS, ""), headers.get(H_NONCE, ""), headers.get(H_SIG, "")
        try:
            skew = abs(self.clock() - int(ts))
        except ValueError:
            raise AuthError(401, "bad timestamp") from None
        if skew > CLOCK_SKEW:
            raise AuthError(401, "request expired (are both clocks right?)")
        if not hmac.compare_digest(sig, signature(key, method, path, ts, nonce, body)):
            raise AuthError(401, "bad signature")
        if not self.nonces.fresh(nonce):
            raise AuthError(401, "replayed request")
        if not self.limit_peer.allow(pid):
            raise AuthError(429, "too many requests")
        peer = self.peers[pid]
        if addr:
            peer.addr = addr
        return peer

    async def _call(self, peer: Peer, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return await self.transport.post(peer, path, body, self._signed_headers(peer, path, body))

    # ------------------------------------------------------------------ pairing
    async def pair(self, peer_id: str) -> dict[str, Any]:
        """Start pairing with a nearby instance; the user confirms the code on that instance."""
        peer = self.peers.get(peer_id)
        if peer is None or peer_id == TAB_ID:
            raise KeyError(peer_id)
        nonce = secrets.token_hex(16)
        status, resp = await self.transport.post(
            peer,
            "/lan/handover/pair",
            {"id": self.id, "name": self.name, "kind": self.kind, "port": self.port, "nonce": nonce},
            {},
        )
        if status != 200 or not resp.get("nonce"):
            raise ConnectionError(str(resp.get("detail") or f"{peer.name} refused to pair ({status})"))
        code = pair_code(self.id, nonce, peer.id, str(resp["nonce"]))
        self.pair_out[peer_id] = {"nonce": nonce, "code": code, "status": "pending", "at": self.clock()}
        self.changed()
        self._bg(self._poll_pair(peer, nonce))
        return {"code": code, "status": "pending"}

    async def _poll_pair(self, peer: Peer, nonce: str) -> None:
        end = self.clock() + PAIR_TTL
        while self.clock() < end:
            await asyncio.sleep(1.5)
            out = self.pair_out.get(peer.id)
            if not out or out["nonce"] != nonce:
                return
            try:
                _status, resp = await self.transport.post(
                    peer, "/lan/handover/pair/poll", {"id": self.id, "nonce": nonce}, {}
                )
            except Exception as e:
                log.debug("pair poll: %s", e)
                continue
            st = resp.get("status")
            if st == "allowed" and resp.get("key"):
                try:
                    self.keys[peer.id] = bytes.fromhex(str(resp["key"]))
                except ValueError:
                    st = "denied"
                else:
                    peer.paired = True
                    self._save()
            if st in ("allowed", "denied"):
                out["status"] = st
                self.changed()
                return
        if peer.id in self.pair_out:
            self.pair_out[peer.id]["status"] = "expired"
            self.changed()

    def on_pair_request(self, body: dict[str, Any], addr: str | None) -> dict[str, Any]:
        if not self.enabled:
            raise AuthError(404, "hand-over is off on this DeskDot")
        if addr is not None and not is_private(addr):
            raise AuthError(403, "only from the local network")
        if not self.limit_pair.allow(addr or "?"):
            raise AuthError(429, "too many requests")
        pid = str(body.get("id") or "")[:32]
        nonce = str(body.get("nonce") or "")[:64]
        if not pid or len(nonce) < 16 or pid == self.id:
            raise AuthError(400, "bad request")
        self._expire_pairs()
        if pid not in self.pair_in and len(self.pair_in) >= 4:
            raise AuthError(429, "too many pairing requests")
        peer = self.peers.get(pid)
        if peer is None:
            peer = self.peers[pid] = Peer(id=pid, name="", kind="ble")
        peer.name = str(body.get("name") or pid)[:48]
        peer.kind = str(body.get("kind") or "ble")[:12]
        peer.addr = addr or peer.addr
        with contextlib.suppress(TypeError, ValueError):
            peer.port = int(body.get("port") or 8765)
        mine = secrets.token_hex(16)
        self.pair_in[pid] = {
            "nonce": nonce,
            "mine": mine,
            "code": pair_code(self.id, mine, pid, nonce),
            "status": "pending",
            "at": self.clock(),
            "name": peer.name,
            "kind": peer.kind,
        }
        self.changed()
        return {"id": self.id, "name": self.name, "kind": self.kind, "nonce": mine}

    def answer_pair(self, peer_id: str, allow: bool) -> dict[str, Any]:
        req = self.pair_in.get(peer_id)
        if req is None or req["status"] != "pending":
            raise KeyError(peer_id)
        if allow:
            key = secrets.token_bytes(32)
            self.keys[peer_id] = key
            req["key"] = key.hex()
            self.peers[peer_id].paired = True
            self._save()
        req["status"] = "allowed" if allow else "denied"
        req["at"] = self.clock()
        self.changed()
        return {"ok": True, "status": req["status"]}

    def on_pair_poll(self, body: dict[str, Any], addr: str | None) -> dict[str, Any]:
        if addr is not None and not is_private(addr):
            raise AuthError(403, "only from the local network")
        if not self.limit_addr.allow(addr or "?"):
            raise AuthError(429, "too many requests")
        self._expire_pairs()
        req = self.pair_in.get(str(body.get("id") or ""))
        if req is None or not hmac.compare_digest(str(body.get("nonce") or ""), req["nonce"]):
            return {"status": "unknown"}
        if req["status"] == "allowed":
            key = req.pop("key", None)
            req["status"] = "done"
            return {"status": "allowed", "key": key} if key else {"status": "unknown"}
        return {"status": req["status"]}

    def _expire_pairs(self) -> None:
        now = self.clock()
        for d in (self.pair_in, self.pair_out):
            for pid in [k for k, v in d.items() if now - v["at"] > PAIR_TTL]:
                del d[pid]

    def forget(self, peer_id: str) -> None:
        self.keys.pop(peer_id, None)
        p = self.peers.get(peer_id)
        if p:
            p.paired = False
        self._save()
        self.changed()

    # ------------------------------------------------------------------ the holder's side
    async def on_release_request(self, peer: Peer, body: dict[str, Any]) -> dict[str, Any]:
        """A paired instance asks us to let go of the panel (it wants it)."""
        lease = self.lease.held_by_other(peer.id)
        if lease and lease.owner != self.id:
            return {"ok": False, "busy": lease.name, "detail": f"{lease.name} is taking the panel right now"}
        to_name = str(body.get("for") or peer.name)[:64]
        self.lease.grant(peer.id, to_name)
        released = await self._let_go(peer.id, to_name)
        return {
            "ok": released,
            "released": released,
            "panel": self.device.info.name,
            "detail": None if released else "the browser tab on this computer didn't let go",
        }

    async def _let_go(self, to_id: str, to_name: str) -> bool:
        """Release the panel (gracefully) for another instance, or ask our browser tab to. True once it's free."""
        if self._task and not self._task.done():
            self._task.cancel()  # we were taking it ourselves: they asked later, they win (the user is there)
        tab = self._tab_fresh()
        if tab and tab["holding"] and to_id != TAB_ID:
            tab["want"] = to_name
            self._tab_changed.clear()
            end = self.clock() + RELEASE_WAIT_TAB
            while self.clock() < end:
                cur = self._tab_fresh()
                if not cur or not cur["holding"]:
                    break
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._tab_changed.wait(), 1.0)
                self._tab_changed.clear()
            else:
                return False
        if self.device.connected or self.device.info.link_enabled:
            await self.device.set_link(False, reason=f"moved to {to_name}")
        self.moved_to = {"id": to_id, "name": to_name, "at": self.clock()}
        log.info("handover: let go of the panel for %s", to_name)
        self.changed()
        return True

    def on_announce(self, peer: Peer, body: dict[str, Any]) -> dict[str, Any]:
        """A paired instance tells us it holds the panel now (faster than its next beacon)."""
        peer.holding = bool(body.get("holding"))
        peer.panel = str(body["panel"])[:32] if body.get("panel") else peer.panel
        peer.last_seen = self.clock()
        if peer.holding:
            peer.last_holding_at = peer.last_seen
            peer.since = peer.since or peer.last_seen
            self.lease.release(peer.id)
        self.changed()
        return {"ok": True}

    # ------------------------------------------------------------------ the browser tab on this computer
    def on_tab_report(self, holding: bool, panel: str | None) -> dict[str, Any]:
        prev = self._tab_fresh()
        want = prev.get("want") if prev else None
        self.tab = {
            "holding": bool(holding),
            "panel": (panel or None) and str(panel)[:32],
            "at": self.clock(),
            "want": want if holding else None,
        }
        if holding:
            self.lease.release(TAB_ID)  # the tab connected: its lease has done its job
        elif prev and prev["holding"]:
            self.device.retry_now()
        self._tab_changed.set()
        if bool(prev and prev["holding"]) != bool(holding):
            self.changed()
        return {"want": self.tab["want"], **self.brief()}

    async def free_for_tab(self) -> dict[str, Any]:
        """The browser tab on this computer wants the panel: let go of it, or ask the instance that has it."""
        if not self.lease.grant(TAB_ID, f"a browser tab on {self.name}"):
            lease = self.lease.current()
            return {
                "ok": False,
                "detail": f"{lease.name if lease else 'another DeskDot'} is taking the panel right now",
            }
        if self.device.connected or self.device.info.link_enabled:
            await self.device.set_link(False, reason="moved to a browser tab on this computer")
            self.moved_to = {"id": TAB_ID, "name": "a browser tab on this computer", "at": self.clock()}
            self.changed()
            return {"ok": True, "released_by": self.name}
        holder = self.holder_peer()
        if holder is None:
            return {"ok": True, "released_by": None}
        res = await self._ask_release(holder, for_name=f"a browser tab on {self.name}")
        if res is not None:
            self.lease.release(TAB_ID)
        return {"ok": res is None, "released_by": holder.name if res is None else None, "detail": res}

    # ------------------------------------------------------------------ the taker's side
    def take(self, force: bool = False) -> dict[str, Any]:
        """ "Use the panel here": start the hand-over in the background (progress in `brief()["progress"]`)."""
        if self._task and not self._task.done():
            return {"ok": True, "started": False}
        self._task = asyncio.get_running_loop().create_task(self._take(force), name="handover-take")
        return {"ok": True, "started": True}

    def _steps(self, who: str | None) -> list[dict[str, Any]]:
        ask = f"Asking {who} to let go" if who else "Checking nobody else has it"
        return [
            {"id": "ask", "label": ask, "state": "active"},
            {"id": "released", "label": "Released", "state": "todo"},
            {"id": "waiting", "label": "Waiting for the panel", "state": "todo"},
            {"id": "connected", "label": "Connected", "state": "todo"},
        ]

    def _step(self, sid: str, state: str, label: str | None = None) -> None:
        if not self.progress:
            return
        for i, s in enumerate(self.progress["steps"]):
            if s["id"] == sid:
                s["state"] = state
                if label:
                    s["label"] = label
                if state == "done" and i + 1 < len(self.progress["steps"]):
                    nxt = self.progress["steps"][i + 1]
                    if nxt["state"] == "todo":
                        nxt["state"] = "active"
        self.changed()

    def _fail(self, message: str, can_force: bool = False) -> None:
        if self.progress:
            for s in self.progress["steps"]:
                if s["state"] == "active":
                    s["state"] = "failed"
            self.progress.update(error=message, can_force=can_force, done=True)
        self.lease.release(self.id)
        self.changed()

    async def _ask_release(self, peer: Peer, for_name: str | None = None) -> str | None:
        """Ask a paired peer to let go. None on success, else a plain-words reason."""
        if peer.id not in self.keys:
            return f"{peer.name} isn't paired with this DeskDot yet. Pair them once (press Pair next to it), or press Release the panel on {peer.name}."
        try:
            body = {"want": "panel", "name": self.name, "for": for_name or self.name}
            status, resp = await self._call(peer, "/lan/handover/release", body)
        except Exception as e:
            log.info("handover: %s unreachable: %s", peer.name, e)
            return f"Couldn't reach {peer.name} on the network."
        if status == 200 and resp.get("released"):
            return None
        if resp.get("busy"):
            return f"{resp['busy']} is taking the panel right now. Try again in a moment."
        if status == 401:
            return f"{peer.name} doesn't recognise this DeskDot any more ({resp.get('detail')}). Pair them again."
        return f"{peer.name} didn't let go ({resp.get('detail') or status})."

    async def _take(self, force: bool) -> None:
        holder = None if force else self.holder_peer()
        tab = self._tab_fresh()
        tab_holds = bool(tab and tab["holding"])
        who = holder.name if holder else ("the browser tab on this computer" if tab_holds else None)
        self.progress = {
            "steps": self._steps(who),
            "error": None,
            "can_force": False,
            "done": False,
            "force": force,
            "target": who,
            "started": self.clock(),
        }
        self.moved_to = None
        if not self.lease.grant(self.id, self.name):
            lease = self.lease.current()
            return self._fail(
                f"{lease.name if lease else 'Another DeskDot'} is taking the panel right now. Try again in a moment."
            )
        self.changed()
        self._phase = "ask"
        try:
            # 1. ask whoever has it to let go
            if holder is not None:
                why = await self._ask_release(holder)
                if why:
                    return self._fail(
                        why + " You can also try anyway: DeskDot waits for the panel to be free.",
                        can_force=True,
                    )
                holder.holding = False
            elif tab_holds and tab is not None:
                tab["want"] = self.name
                self._tab_changed.clear()
                end = self.clock() + RELEASE_WAIT_TAB
                while (cur := self._tab_fresh()) and cur["holding"] and self.clock() < end:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._tab_changed.wait(), 1.0)
                    self._tab_changed.clear()
                cur = self._tab_fresh()
                if cur and cur["holding"]:
                    return self._fail(
                        "The browser tab on this computer didn't let go. Open it and press Release the "
                        "panel there.",
                        can_force=True,
                    )
            self._step("ask", "done")
            self._step("released", "done", None if (holder or tab_holds) else "Nobody else had it")
            # 2. wait for the panel to advertise (it does only once its previous central is gone)
            self.lease.grant(self.id, self.name)
            self._phase = "waiting"
            seen = self.device.connected or await self.device.wait_for_panel(ADVERT_WAIT)
            if not seen:
                probable = holder or self.probable_holder()
                hint = (
                    f"most likely {probable.name}"
                    if probable
                    else "the iDotMatrix phone app, another DeskDot or a browser tab"
                )
                self._step("waiting", "active", "Panel not showing up yet — trying anyway")
                log.info("handover: the panel isn't advertising; still held by %s?", hint)
            self._step("waiting", "done")
            # 3. connect (the supervisor does it: one attempt at a time, jittered back-off)
            self.lease.grant(self.id, self.name, CONNECT_WAIT + 5)
            self._phase = "connect"
            await self.device.set_link(True)
            self.device.retry_now()
            if not await self.device.wait_connected(CONNECT_WAIT):
                probable = holder or self.probable_holder()
                who_has = (
                    (
                        f"It's probably still held by {probable.name}: open DeskDot there and press Release the "
                        "panel."
                    )
                    if probable
                    else (
                        "Something else may still hold it — the iDotMatrix phone app, "
                        "another DeskDot or a browser tab. Close it there."
                    )
                )
                return self._fail(
                    f"The panel didn't connect. {who_has} If nothing holds it, unplug the panel for 5 "
                    "seconds; DeskDot keeps trying by itself."
                )
            self._step("connected", "done")
            self.progress["done"] = True
            self.lease.release(self.id)
            self.changed()
            await self._announce()
        except asyncio.CancelledError:
            self._fail("Another DeskDot asked for the panel at the same time and got it.")
            raise
        except Exception as e:  # pragma: no cover — defensive
            log.warning("handover failed: %s", e)
            self._fail(f"Hand-over failed: {e}")
        finally:
            self._phase = None
            self.device.retry_now()  # leave the gate promptly whatever happened

    async def _announce(self) -> None:
        """Tell paired peers we hold the panel (their "Panel moved to …" updates at once)."""
        body = {"holding": True, "panel": self.device.info.name}
        for p in list(self.peers.values()):
            if p.id in self.keys and p.addr and self.clock() - p.last_seen < PEER_FRESH:
                with contextlib.suppress(Exception):
                    await self._call(p, "/lan/handover/announce", body)
        self.changed()

    # ------------------------------------------------------------------ state for the studio
    def brief(self) -> dict[str, Any]:
        now = self.clock()
        self._expire_pairs()
        holder: dict[str, Any] | None = None
        tab = self._tab_fresh()
        if self.device.connected:
            holder = {
                "id": self.id,
                "name": self.name,
                "kind": self.kind,
                "me": True,
                "since": self.device.info.connected_since,
            }
        elif tab and tab["holding"]:
            holder = {"id": TAB_ID, "name": "Browser tab on this computer", "kind": "web", "me": False}
        elif (p := self.holder_peer()) is not None:
            holder = {"id": p.id, "name": p.name, "kind": p.kind, "me": False, "since": p.since}
        probable = None
        if holder is None and (pp := self.probable_holder()) is not None:
            probable = {"id": pp.id, "name": pp.name, "ago": round(now - (pp.last_holding_at or now), 1)}
        peers = [p.public(now) for p in self.peers.values() if p.paired or now - p.last_seen < PEER_FORGET]
        if tab:
            peers.append(
                {
                    "id": TAB_ID,
                    "name": "Browser tab on this computer",
                    "kind": "web",
                    "holding": tab["holding"],
                    "panel": tab["panel"],
                    "online": True,
                    "paired": True,
                    "ago": round(now - tab["at"], 1),
                }
            )
        lease = self.lease.current()
        return {
            "enabled": self.enabled,
            "me": {"id": self.id, "name": self.name, "kind": self.kind},
            "holder": holder,
            "probable": probable,
            "peers": sorted(peers, key=lambda d: (not d.get("online"), d["name"])),
            "lease": {"owner": lease.owner, "name": lease.name, "in": round(lease.until - now, 1)}
            if lease
            else None,
            "progress": self.progress,
            "moved_to": self.moved_to if not self.device.info.link_enabled else None,
            "pair_requests": [
                {"id": pid, "name": r["name"], "kind": r["kind"], "code": r["code"]}
                for pid, r in self.pair_in.items()
                if r["status"] == "pending"
            ],
            "pairing": [
                {
                    "id": pid,
                    "name": self.peers[pid].name if pid in self.peers else pid,
                    "code": r["code"],
                    "status": r["status"],
                }
                for pid, r in self.pair_out.items()
            ],
        }


def default_name(kind: str) -> str:
    if kind == "android":
        try:
            from java import jclass  # type: ignore[import-not-found]

            build = jclass("android.os.Build")
            return f"{build.MANUFACTURER.capitalize()} {build.MODEL}"[:48]
        except Exception:
            return "Android phone"
    host = socket.gethostname() or "this computer"
    return host.split(".")[0][:48]


# ====================================================================== UDP beacon
class _Beacon(asyncio.DatagramProtocol):
    """Broadcast our beacon on the LAN and feed the ones we hear to the coordinator. Private networks only."""

    def __init__(self, ho: Handover) -> None:
        self.ho = ho
        self.transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task[None] | None = None
        self._kick = asyncio.Event()

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("0.0.0.0", BEACON_PORT))
            sock.setblocking(False)
            self.transport, _ = await loop.create_datagram_endpoint(lambda: self, sock=sock)
        except OSError as e:
            sock.close()
            log.info("handover: LAN discovery unavailable (%s); hand-over still works from this computer", e)
            return
        self._task = loop.create_task(self._loop(), name="handover-beacon")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self.transport:
            self.transport.close()
            self.transport = None

    def kick(self) -> None:
        self._kick.set()

    async def _loop(self) -> None:
        from .multiplayer import lan_ip

        while True:
            ip = await asyncio.to_thread(lan_ip)
            if self.transport and is_private(ip) and not ipaddress.ip_address(ip).is_loopback:
                msg = {**self.ho.beacon(), "now": self.ho.clock()}
                with contextlib.suppress(OSError):
                    self.transport.sendto(json.dumps(msg).encode(), ("255.255.255.255", BEACON_PORT))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._kick.wait(), BEACON_EVERY)
            self._kick.clear()
            await asyncio.sleep(0.2)  # coalesce bursts of changes

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        if len(data) > 2048:
            return
        try:
            msg = json.loads(data)
        except ValueError:
            return
        self.ho.on_beacon(msg, str(addr[0]))
