"""Panel hand-over between DeskDots (ADR 0015) and the device layer's release / recovery hygiene.

A fake panel accepts exactly one central (like the real one: it stops advertising while held). Fake devices for a
laptop, a phone and a browser tab talk to it; a fake LAN carries beacons and the signed hand-over requests between
the laptop's and the phone's `Handover`, and the tab speaks to the laptop over its loopback API like host.js does.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot.config import Config
from deskdot.device import base as device_base
from deskdot.device.base import Device
from deskdot.handover import (
    TAB_ID,
    AuthError,
    Handover,
    LeaseTable,
    NonceCache,
    Peer,
    RateLimiter,
    is_private,
    pair_code,
    signature,
)
from deskdot.server import create_app


# ====================================================================== fakes
class FakePanel:
    """One central at a time; after a disconnect it takes a moment to advertise again."""

    def __init__(self, readvertise: float = 0.05) -> None:
        self.central: str | None = None
        self.readvertise = readvertise
        self.free_at = 0.0
        self.refused: dict[str, int] = {}  # connect attempts while someone else held it (connect storms)
        self.log: list[tuple[str, str]] = []

    def advertising(self) -> bool:
        return self.central is None and time.monotonic() >= self.free_at

    def connect(self, who: str) -> None:
        if not self.advertising():
            self.refused[who] = self.refused.get(who, 0) + 1
            raise ConnectionError("panel not found (AA:BB:CC:DD:EE:01)")
        self.central = who
        self.log.append(("connect", who))

    def disconnect(self, who: str) -> None:
        if self.central == who:
            self.central = None
            self.free_at = time.monotonic() + self.readvertise
            self.log.append(("disconnect", who))


class PanelDevice(Device):
    """A backend on the fake panel. `ghost`: the next disconnect leaks the session (the WinRT / Android bug)."""

    kind = "ble"
    rearm_delay = 0.05

    def __init__(self, panel: FakePanel, who: str, ack_delay: float = 0.0) -> None:
        super().__init__(min_frame_interval=0.0, packet_gap=0.0)
        self.panel = panel
        self.who = who
        self.ack_delay = ack_delay
        self.ghost = False
        self.attempts = 0
        self.events: list[tuple[str, float]] = []

    async def _connect(self) -> None:
        self.attempts += 1
        await asyncio.sleep(0.01)
        self.panel.connect(self.who)
        self.info.name = "IDM-TEST"

    async def _disconnect(self) -> None:
        self.events.append(("disconnect", time.monotonic()))
        if self.ghost:
            return  # the OS keeps the link: the panel stays held by us, invisible
        self.panel.disconnect(self.who)

    async def _reset_stack(self) -> None:
        self.ghost = False
        self.events.append(("reset", time.monotonic()))
        self.panel.disconnect(self.who)

    async def _wait_for_panel(self, limit: float) -> bool:
        end = time.monotonic() + limit
        while not self.panel.advertising():
            if time.monotonic() > end:
                return False
            await asyncio.sleep(0.02)
        return True

    async def _write(self, data: bytes, response: bool = False) -> None:
        if self.panel.central != self.who:
            raise ConnectionError("not connected")
        await asyncio.sleep(0.002)
        is_gif_chunk = len(data) > 16 and data[2:4] == b"\x01\x00" and data[13:16] == b"\x05\x00\x0d"
        self.events.append(("gif-chunk" if is_gif_chunk else "write", time.monotonic()))
        if is_gif_chunk:
            asyncio.get_running_loop().call_later(self.ack_delay, self._ack_chunk)

    def _ack_chunk(self) -> None:
        self.events.append(("ack", time.monotonic()))
        self._on_ack(b"\x05\x00\x01\x00\x01")

    async def _write_packet(
        self, packet: bytes, response: bool
    ) -> None:  # pragma: no cover — _write is overridden
        raise AssertionError


ADDR = {"laptop": "192.168.1.10", "phone": "192.168.1.20"}


class FakeLan:
    """Carries beacons and HTTP requests between Handover instances; `down` makes one unreachable."""

    def __init__(self) -> None:
        self.nodes: dict[str, Handover] = {}
        self.addr: dict[str, str] = {}
        self.down: set[str] = set()

    def add(self, label: str, ho: Handover) -> None:
        self.nodes[ho.id] = ho
        self.addr[ho.id] = ADDR[label]

    def pump(self) -> None:
        for a in self.nodes.values():
            if a.id in self.down:
                continue
            msg = {**a.beacon(), "now": time.time()}
            for b in self.nodes.values():
                if b is not a:
                    b.on_beacon(json.loads(json.dumps(msg)), self.addr[a.id])

    def transport_for(self, sender: str) -> Any:
        lan = self

        class T:
            async def post(self, peer: Peer, path: str, body: dict[str, Any], headers: dict[str, str]) -> Any:
                if peer.id in lan.down:
                    raise ConnectionError("unreachable")
                target = lan.nodes[peer.id]
                raw = json.dumps(body).encode()
                addr = lan.addr[sender]
                try:
                    if path == "/lan/handover/pair":
                        return 200, target.on_pair_request(body, addr)
                    if path == "/lan/handover/pair/poll":
                        return 200, target.on_pair_poll(body, addr)
                    p = target.verify("POST", path, headers, raw, addr)
                    if path == "/lan/handover/release":
                        res = await target.on_release_request(p, body)
                        return (200 if res.get("ok") or res.get("busy") else 409), res
                    if path == "/lan/handover/announce":
                        return 200, target.on_announce(p, body)
                except AuthError as e:
                    return e.status, {"detail": str(e)}
                return 404, {}

        return T()


class TabClient:
    """What host.js does for a browser tab on the laptop: report holding, let go when asked, ask to be freed."""

    def __init__(self, dev: PanelDevice, laptop: Handover) -> None:
        self.dev, self.laptop = dev, laptop
        self.task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        while True:
            res = self.laptop.on_tab_report(self.dev.connected, self.dev.info.name)
            if res.get("want") and self.dev.connected:
                await self.dev.set_link(False, reason=f"moved to {res['want']}")
                self.laptop.on_tab_report(False, None)
            await asyncio.sleep(0.05)

    async def use_here(self) -> dict[str, Any]:
        res = await self.laptop.free_for_tab()
        if res.get("ok"):
            await self.dev.set_link(True)
        return res


async def _until(cond: Any, limit: float = 8.0) -> None:
    end = time.monotonic() + limit
    while not cond():
        assert time.monotonic() < end, "timed out"
        await asyncio.sleep(0.02)


async def _pair(lan: FakeLan, a: Handover, b: Handover) -> None:
    lan.pump()
    out = await a.pair(b.id)
    req = b.brief()["pair_requests"]
    assert req and req[0]["code"] == out["code"], "both sides show the same code"
    b.answer_pair(a.id, True)
    await _until(lambda: a.pair_out[b.id]["status"] == "allowed", 5.0)
    assert a.keys[b.id] == b.keys[a.id]


@pytest.fixture
def world(tmp_path: Path) -> Any:
    panel = FakePanel()
    lan = FakeLan()
    devs = {k: PanelDevice(panel, k) for k in ("laptop", "phone", "tab")}
    laptop = Handover(devs["laptop"], tmp_path / "l", kind="ble", name="Laptop", transport=None)
    phone = Handover(devs["phone"], tmp_path / "p", kind="android", name="Pixel", transport=None)
    laptop.transport = lan.transport_for(laptop.id)
    phone.transport = lan.transport_for(phone.id)
    lan.add("laptop", laptop)
    lan.add("phone", phone)
    return panel, lan, devs, laptop, phone


# ====================================================================== three instances contending
async def test_three_instances_hand_the_panel_around_one_holder_at_a_time(world: Any) -> None:
    panel, lan, devs, laptop, phone = world
    tab = TabClient(devs["tab"], laptop)
    devs["tab"].info.link_enabled = False  # the tab connects only when its user asks
    holders: list[int] = []

    async def watch() -> None:
        while True:
            lan.pump()
            holders.append(sum(d.connected for d in devs.values()))
            await asyncio.sleep(0.02)

    for d in devs.values():
        await d.start()
    # beacons are pumped by `watch`: no real sockets (Handover.start() would open the UDP beacon)
    tasks = [asyncio.create_task(watch()), asyncio.create_task(tab.run())]
    try:
        await _until(lambda: panel.central is not None)
        first = panel.central
        await _pair(lan, phone, laptop)
        # whoever lost the race at start-up now waits at the gate instead of hammering the panel
        await asyncio.sleep(1.0)
        loser = "phone" if first == "laptop" else "laptop"
        refused_before = panel.refused.get(loser, 0)
        await asyncio.sleep(1.5)
        assert panel.refused.get(loser, 0) == refused_before, (
            "no connect storm while another DeskDot holds it"
        )
        assert devs[loser].info.reason == "elsewhere"

        # 1. the phone takes it from the laptop (or the laptop from the phone)
        taker, giver = (phone, laptop) if first == "laptop" else (laptop, phone)
        taker.take()
        t0 = time.monotonic()
        await _until(lambda: panel.central == ("phone" if taker is phone else "laptop"))
        await _until(lambda: bool(taker.progress and taker.progress["done"]))
        # the taker's own supervisor (link enabled, waiting at the gate) must not connect while the hand-over still
        # waits for the advertisement: a held panel never advertises, and the wait would run its full 20 s
        assert time.monotonic() - t0 < 5.0
        assert [s["state"] for s in taker.progress["steps"]] == ["done"] * 4
        assert giver.brief()["moved_to"]["name"] == taker.name
        assert not giver.device.info.link_enabled, "released means no auto-reconnect"

        # 2. the browser tab on the laptop takes it; the laptop relays the request to the phone if needed
        res = await tab.use_here()
        assert res["ok"], res
        await _until(lambda: panel.central == "tab")
        await asyncio.sleep(0.3)
        assert laptop.brief()["holder"]["id"] == TAB_ID
        lan.pump()
        assert phone.brief()["holder"]["name"] == "Laptop", (
            "the phone sees the laptop (speaking for its tab) hold it"
        )

        # 3. the laptop takes it back from its own tab
        laptop.take()
        await _until(lambda: panel.central == "laptop")
        await _until(lambda: bool(laptop.progress and laptop.progress["done"]))
        assert laptop.progress["error"] is None

        # 4. and the phone takes it once more
        phone.take()
        await _until(lambda: panel.central == "phone")
        await asyncio.sleep(0.3)
        assert max(holders) == 1, "never two instances connected at once"
        assert sum(panel.refused.values()) <= 6, panel.refused
    finally:
        for t in tasks:
            t.cancel()
        await laptop.stop()
        await phone.stop()
        for d in devs.values():
            await d.stop()


async def test_two_takers_at_once_only_one_gets_the_lease(world: Any, tmp_path: Path) -> None:
    panel, lan, devs, laptop, phone = world
    third_dev = PanelDevice(panel, "third")
    third = Handover(third_dev, tmp_path / "t", kind="ble", name="Desktop", transport=None)
    third.transport = lan.transport_for(third.id)
    ADDR["third"] = "192.168.1.30"
    lan.add("third", third)
    devs["phone"].info.link_enabled = False
    third_dev.info.link_enabled = False
    for d in (*devs.values(), third_dev):
        await d.start()
    try:
        await _until(lambda: panel.central == "laptop")
        await _pair(lan, phone, laptop)
        await _pair(lan, third, laptop)
        await _pair(lan, third, phone)
        lan.pump()
        phone.take()
        third.take()
        for _ in range(200):
            lan.pump()
            await asyncio.sleep(0.02)
            if phone.progress and third.progress and phone.progress["done"] and third.progress["done"]:
                break
        winners = [h for h in (phone, third) if h.progress and h.progress["error"] is None]
        assert len(winners) == 1, (phone.progress, third.progress)
        assert panel.central == ("phone" if winners[0] is phone else "third")
        loser = third if winners[0] is phone else phone
        assert "taking the panel" in (loser.progress["error"] or "") or "has" in (
            loser.progress["error"] or ""
        )
    finally:
        ADDR.pop("third", None)
        for h in (laptop, phone, third):
            await h.stop()
        for d in (*devs.values(), third_dev):
            await d.stop()


async def test_unreachable_holder_explains_and_offers_a_safe_force_path(world: Any) -> None:
    panel, lan, devs, laptop, phone = world
    devs["phone"].info.link_enabled = False
    for d in devs.values():
        await d.start()
    try:
        await _until(lambda: panel.central == "laptop")
        await _pair(lan, phone, laptop)
        lan.pump()
        lan.down.add(laptop.id)  # the laptop's DeskDot froze / the Wi-Fi blocks it
        phone.take()
        await _until(lambda: bool(phone.progress and phone.progress["done"]))
        assert phone.progress["can_force"] and "Couldn't reach Laptop" in phone.progress["error"]
        assert panel.central == "laptop", "nothing was forced without the user saying so"
        # the user frees it on the laptop by hand, then presses "Try anyway"
        await devs["laptop"].set_link(False)
        phone.take(force=True)
        await _until(lambda: panel.central == "phone")
    finally:
        await laptop.stop()
        await phone.stop()
        for d in devs.values():
            await d.stop()


async def test_holder_side_rejects_a_second_taker_while_the_lease_is_out(world: Any) -> None:
    _panel, lan, devs, laptop, phone = world
    await devs["laptop"].start()
    try:
        await _until(lambda: devs["laptop"].connected)
        await _pair(lan, phone, laptop)
        laptop.lease.grant("someone-else", "Desktop")
        res = await laptop.on_release_request(laptop.peers[phone.id], {})
        assert res["busy"] == "Desktop" and devs["laptop"].connected
    finally:
        await devs["laptop"].stop()


# ====================================================================== device hygiene
async def test_release_during_a_gif_upload_waits_for_the_chunk_acks() -> None:
    panel = FakePanel()
    dev = PanelDevice(panel, "laptop", ack_delay=0.15)
    await dev.start()
    try:
        await _until(lambda: dev.connected)
        dev.show_gif(bytes(range(256)) * 40)  # ~10 KB: three 4 KiB chunks, each waiting for its ack
        await _until(lambda: any(e == "gif-chunk" for e, _ in dev.events))
        assert await dev.set_link(False), "drained before closing"
        kinds = [e for e, _ in dev.events]
        cut = kinds.index("disconnect")
        assert kinds[:cut].count("gif-chunk") == 3 and kinds[:cut].count("ack") == 3, kinds
        assert dev.info.reason == "released" and panel.central is None
    finally:
        await dev.stop()


async def test_a_failed_attempt_disposes_a_ghost_session() -> None:
    # the WinRT / Android bug: the link "dropped" but the OS kept the session, so the panel stays held by us and
    # stops advertising. Every failed attempt now disposes our leftovers, so the next one connects.
    panel = FakePanel()
    dev = PanelDevice(panel, "laptop")
    await dev.start()
    try:
        await _until(lambda: dev.connected)
        dev.ghost = True
        dev._mark_disconnected("link lost")
        await dev._disconnect()
        assert panel.central == "laptop" and not dev.connected
        dev.retry_now()
        await _until(lambda: dev.connected, 6.0)
        assert any(e == "reset" for e, _ in dev.events)
        assert panel.log[-2:] == [("disconnect", "laptop"), ("connect", "laptop")]
    finally:
        await dev.stop()


async def test_recovery_waits_for_the_panel_instead_of_retrying_blindly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(device_base, "RECOVER_AFTER", 3)
    panel = FakePanel()
    dev = PanelDevice(panel, "laptop")
    await dev.start()
    try:
        await _until(lambda: dev.connected)
        dev.show_gif(b"GIF89a" + bytes(200))
        await asyncio.sleep(0.2)
        dev._mark_disconnected("link lost")
        await dev._disconnect()
        panel.free_at = time.monotonic() + 1.2  # stuck: not advertising for a while

        async def nudge() -> None:  # skip the back-off waits: attempts come quickly and keep failing
            while not dev.connected:
                dev.retry_now()
                await asyncio.sleep(0.05)

        t = asyncio.create_task(nudge())
        try:
            await _until(lambda: dev.connected, 10.0)
        finally:
            t.cancel()
        assert dev.info.recoveries >= 1
        assert panel.refused["laptop"] <= 4, "the recovery waited for the advertisement instead of hammering"
        since = time.monotonic()
        await asyncio.sleep(0.4)
        assert not any(e == "gif-chunk" and t0 >= since for e, t0 in dev.events), (
            "after a recovery the GIF waits for the cool-down (gentle replay)"
        )
    finally:
        await dev.stop()


async def test_after_a_drop_the_next_attempt_waits_for_the_panel_to_re_advertise() -> None:
    panel = FakePanel(readvertise=0.0)
    dev = PanelDevice(panel, "laptop")
    dev.rearm_delay = 0.4
    await dev.start()
    try:
        await _until(lambda: dev.connected)
        n = dev.attempts
        dev._mark_disconnected("link lost")
        await dev._disconnect()
        t0 = time.monotonic()
        dev.retry_now()
        await _until(lambda: dev.connected)
        assert time.monotonic() - t0 >= 0.35 and dev.attempts == n + 1
    finally:
        await dev.stop()


# ====================================================================== lease, auth, rate limits
def test_lease_one_owner_expiry_and_renewal() -> None:
    now = [1000.0]
    lt = LeaseTable(clock=lambda: now[0])
    assert lt.grant("a", "A", ttl=30)
    assert not lt.grant("b", "B"), "one owner at a time"
    assert lt.grant("a", "A", ttl=30), "the owner renews"
    assert lt.held_by_other("b").owner == "a" and lt.held_by_other("a") is None
    now[0] += 31
    assert lt.current() is None and lt.grant("b", "B"), "a lease nobody renews expires"
    lt.note("c", "C", now[0] + 10)
    assert lt.current().owner == "b", "a beacon never overrides a lease we granted"
    lt.release("b")
    lt.note("c", "C", now[0] + 10)
    assert lt.current().owner == "c"


def test_rate_limiter_and_nonces() -> None:
    t = [0.0]
    rl = RateLimiter(3, 60.0, clock=lambda: t[0])
    assert [rl.allow("x") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("y")
    t[0] = 61.0
    assert rl.allow("x")
    nc = NonceCache(ttl=10, clock=lambda: t[0])
    assert nc.fresh("n1") and not nc.fresh("n1")


def test_private_networks_only() -> None:
    assert all(
        is_private(a)
        for a in ("192.168.1.2", "10.0.0.5", "172.16.3.4", "169.254.1.1", "127.0.0.1", "fe80::1")
    )
    assert not any(is_private(a) for a in ("8.8.8.8", "1.1.1.1", "224.0.0.1", "", None, "x"))


def test_pair_code_is_symmetric() -> None:
    assert pair_code("a", "n1", "b", "n2") == pair_code("b", "n2", "a", "n1")
    assert len(pair_code("a", "n1", "b", "n2").replace(" ", "")) == 6


async def test_signed_requests_auth(tmp_path: Path) -> None:
    dev = PanelDevice(FakePanel(), "x")
    ho = Handover(dev, tmp_path, kind="ble", name="Laptop")
    key = b"k" * 32
    ho.keys["peer1"] = key
    ho.peers["peer1"] = Peer(id="peer1", name="Pixel", kind="android", paired=True)
    body = b'{"want":"panel"}'

    def headers(
        ts: int | None = None, nonce: str = "n-1", k: bytes = key, path: str = "/lan/handover/release"
    ) -> dict:
        ts_s = str(int(time.time()) if ts is None else ts)
        return {
            "x-deskdot-peer": "peer1",
            "x-deskdot-ts": ts_s,
            "x-deskdot-nonce": nonce,
            "x-deskdot-sig": signature(k, "POST", path, ts_s, nonce, body),
        }

    assert ho.verify("POST", "/lan/handover/release", headers(), body, "192.168.1.20").id == "peer1"
    cases = [
        (headers(), "192.168.1.20", "replayed"),  # same nonce again
        (headers(nonce="n-2", k=b"z" * 32), "192.168.1.20", "bad signature"),
        (headers(nonce="n-3", ts=int(time.time()) - 600), "192.168.1.20", "expired"),
        (headers(nonce="n-4", path="/lan/handover/announce"), "192.168.1.20", "bad signature"),
        ({**headers(nonce="n-5"), "x-deskdot-peer": "stranger"}, "192.168.1.20", "not paired"),
        (headers(nonce="n-6"), "8.8.8.8", "local network"),
    ]
    for h, addr, why in cases:
        with pytest.raises(AuthError, match=why):
            ho.verify("POST", "/lan/handover/release", h, body, addr)
    ok = 0
    for i in range(20):
        try:
            ho.verify("POST", "/lan/handover/release", headers(nonce=f"r-{i}"), body, "192.168.1.21")
            ok += 1
        except AuthError as e:
            assert e.status == 429
    assert ok < 20, "rate-limited per peer"
    ho.enabled = False
    with pytest.raises(AuthError):
        ho.verify("POST", "/lan/handover/release", headers(nonce="off"), body, "192.168.1.22")


async def test_pairing_needs_the_users_allow(tmp_path: Path) -> None:
    lan = FakeLan()
    panel = FakePanel()
    a = Handover(PanelDevice(panel, "laptop"), tmp_path / "a", kind="ble", name="Laptop")
    b = Handover(PanelDevice(panel, "phone"), tmp_path / "b", kind="android", name="Pixel")
    a.transport, b.transport = lan.transport_for(a.id), lan.transport_for(b.id)
    lan.add("laptop", a)
    lan.add("phone", b)
    lan.pump()
    await a.pair(b.id)
    await asyncio.sleep(1.7)
    assert b.id not in a.keys, "no key before the user allows it"
    b.answer_pair(a.id, False)
    await _until(lambda: a.pair_out[b.id]["status"] == "denied", 5.0)
    assert b.id not in a.keys and a.id not in b.keys
    await a.stop()
    # a paired key survives a restart
    await _pair(lan, a, b)
    again = Handover(PanelDevice(panel, "laptop2"), tmp_path / "a", kind="ble")
    assert again.id == a.id and again.keys[b.id] == a.keys[b.id] and again.peers[b.id].paired
    await a.stop()


# ====================================================================== HTTP surface
def test_lan_gate_lets_only_the_handover_endpoints_through(tmp_path: Path) -> None:
    app = create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins"))
    with TestClient(app, client=("192.168.1.20", 50000)) as lan:
        assert lan.get("/api/handover").status_code == 403, "the studio API stays on this computer"
        assert lan.post("/api/device/link", json={"enabled": False}).status_code == 403
        r = lan.post("/lan/handover/release", json={"want": "panel"})
        assert r.status_code in (401, 404), "reachable, but refused without a signature"
        assert lan.post("/lan/handover/pair", content=b"[]").status_code == 400


def test_tab_and_free_endpoints_allow_the_web_app_only(tmp_path: Path) -> None:
    app = create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins"))
    with TestClient(app) as c:
        web = {"Origin": "https://idotmatrix.com"}
        r = c.post("/api/handover/tab", json={"holding": True, "panel": "IDM-1"}, headers=web)
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "https://idotmatrix.com"
        assert r.json()["want"] is None and any(p["id"] == TAB_ID and p["holding"] for p in r.json()["peers"])
        pre = c.options(
            "/api/handover/free",
            headers={
                **web,
                "Access-Control-Request-Private-Network": "true",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert pre.status_code == 204 and pre.headers["access-control-allow-private-network"] == "true"
        evil = {"Origin": "https://evil.example"}
        assert c.post("/api/handover/free", headers=evil).status_code == 403, "no cross-site release"
        assert c.post("/api/handover/take", json={}, headers=evil).status_code == 403
        assert c.post("/api/handover/take", json={}).json()["ok"]
        state = c.get("/api/state").json()
        assert "handover" in state and state["handover"]["me"]["name"]
        assert c.get("/api/health").json()["handover"] is True
