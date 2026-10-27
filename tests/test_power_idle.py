"""Power: the engine idles when nobody consumes its frames, and the panel link backs off (docs/adr/0014).

Measured on the Fossil Gen 6 (Wear OS, 32-bit, Python 3.11): with no panel in range the engine kept rendering and
PNG-encoding every frame for nobody, retried the panel every 20 s forever, and the host held a wake lock 24/7 —
~10 % of the watch's CPU nonstop and a warm wrist. These tests pin the event-driven behaviour that replaced it.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import deskdot.apps  # noqa: F401 — registers built-in apps
from deskdot.config import Config, Store
from deskdot.device import SimDevice
from deskdot.device.android import LOW_POWER_RETRY_CAP, AndroidBleDevice
from deskdot.engine import Engine
from deskdot.gfx import Frame
from deskdot.providers import build_hub
from deskdot.server import _LanClients, build_device, create_app


async def _until(cond: Any, within: float = 3.0) -> None:
    end = time.monotonic() + within
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


class GatedDevice(SimDevice):
    """A simulated panel that is out of range until `present` is set (then 'Reconnect' / the back-off finds it)."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.present = False
        self.connect_attempts = 0

    async def _connect(self) -> None:
        self.connect_attempts += 1
        await asyncio.sleep(0.01)
        if not self.present:
            raise ConnectionError("panel not found")

    def drop(self) -> None:
        self.present = False
        self._mark_disconnected("link lost")


@pytest.fixture
async def no_panel(tmp_path: Path):  # type: ignore[no-untyped-def]
    cfg = Config(device="sim", data_dir=tmp_path)
    store = Store(tmp_path / "state.json")
    hub = build_hub(store, lambda _n: None)
    dev = GatedDevice(bytes_per_second=1e7, min_frame_interval=0.0)
    eng = Engine(cfg, store, dev, hub)
    await eng.start()
    yield eng, dev
    await eng.stop()
    await hub.http.aclose()


# ------------------------------------------------------------------------------------------------ engine idling
async def test_engine_idles_without_panel_or_viewers(no_panel) -> None:  # type: ignore[no-untyped-def]
    eng, dev = no_panel
    await _until(lambda: eng.idle)
    ticks = eng.ticks
    await asyncio.sleep(0.5)
    assert eng.ticks == ticks, "an idle engine must not tick at all"
    assert eng.current is None or not eng.current.holding, "the app's providers are released while idle"
    assert eng._bg == set()
    assert dev._frame is None and dev._last_visual is None, (
        "nothing is rendered or encoded for a missing panel"
    )


async def test_viewer_wakes_the_engine_and_leaving_idles_it_again(no_panel) -> None:  # type: ignore[no-untyped-def]
    eng, _dev = no_panel
    await _until(lambda: eng.idle)
    got: list[Frame] = []
    eng.frame_listeners.add(got.append)  # the studio / the watch UI opens its socket
    await _until(lambda: not eng.idle)
    await _until(lambda: len(got) > 0 or eng.ticks > 2)
    assert eng.current is not None and eng.current.visible and eng.current.holding
    eng.frame_listeners.discard(got.append)
    await _until(lambda: eng.idle)
    assert eng.idle_count >= 2


async def test_panel_coming_back_resumes_at_once_and_gets_the_current_visual(no_panel) -> None:  # type: ignore[no-untyped-def]
    eng, dev = no_panel
    eng.activate("clock")  # a stream app
    await _until(lambda: eng.idle)
    dev.present = True
    dev.retry_now()  # what the Android standby link does when the panel reappears
    await _until(lambda: dev.connected)
    await _until(lambda: dev.info.frames_sent >= 1)
    assert not eng.idle
    dev.drop()
    await _until(lambda: eng.idle)


async def test_studio_without_panel_renders_but_never_encodes_png(no_panel) -> None:  # type: ignore[no-untyped-def]
    eng, dev = no_panel
    eng.activate("clock")
    got: list[Frame] = []
    eng.frame_listeners.add(got.append)
    await _until(lambda: eng.ticks > 3)
    assert dev._frame is None and dev._last_visual is None
    eng.frame_listeners.discard(got.append)


async def test_holds_keep_it_running_and_map_to_locks(no_panel) -> None:  # type: ignore[no-untyped-def]
    eng, _dev = no_panel
    seen: list[dict[str, Any]] = []
    eng.power_listeners.append(seen.append)
    await _until(lambda: eng.idle)
    d = eng.demand()
    assert (d["run"], d["wake_lock"], d["wifi"]) == (False, False, False)

    eng.hold("lobby")  # a lobby with nobody in it yet: Wi-Fi up so phones can join, the CPU may sleep
    await _until(lambda: not eng.idle)
    d = eng.demand()
    assert (d["run"], d["wake_lock"], d["wifi"], d["hosting"]) == (True, False, True, True)

    eng.hold("lan")  # a phone joined from another device
    await _until(lambda: eng._power_key == (True, True, True))
    eng.unhold("lan")
    eng.unhold("lobby")
    await _until(lambda: eng.idle)
    assert eng.demand()["holds"] == {}
    verdicts = [(x["run"], x["wake_lock"], x["wifi"]) for x in seen]
    assert verdicts[-1] == (False, False, False)
    assert all(a != b for a, b in itertools.pairwise(verdicts)), "reported on change only"


async def test_connected_panel_holds_the_wake_lock(no_panel) -> None:  # type: ignore[no-untyped-def]
    eng, dev = no_panel
    dev.present = True
    dev.retry_now()
    await _until(lambda: dev.connected)
    await _until(lambda: eng._power_key == (True, True, False))


async def test_fresh_frame_renders_on_demand_while_idle(no_panel) -> None:  # type: ignore[no-untyped-def]
    eng, _dev = no_panel
    await _until(lambda: eng.idle)
    eng.frame = Frame()  # pretend the last tick showed a black screen
    fr = eng.fresh_frame()
    assert fr.px.any(), "the clock draws something"
    assert eng.idle, "an on-demand render doesn't wake the loop"


async def test_background_providers_come_back_after_idle(no_panel) -> None:  # type: ignore[no-untyped-def]
    eng, _dev = no_panel
    eng.store.set("os_notifications", {"enabled": True})
    eng._refresh_background()
    await _until(lambda: eng.idle)
    assert eng._bg == set()
    got: list[Frame] = []
    eng.frame_listeners.add(got.append)
    await _until(lambda: "notifications" in eng._bg)
    eng.frame_listeners.discard(got.append)


# --------------------------------------------------------------------------------------------- panel back-off
def test_backoff_doubles_up_to_the_cap() -> None:
    dev = SimDevice()
    assert (dev.retry_base, dev.retry_cap) == (1.0, 20.0), "phone / desktop keep their 20 s cap"
    seq, d = [], dev.retry_base
    for _ in range(8):
        d = dev._next_delay(d)
        seq.append(d)
    assert seq == [2, 4, 8, 16, 20, 20, 20, 20]

    watch = AndroidBleDevice("AA:BB:CC:DD:EE:01", bridge=object(), low_power=True)
    assert watch.retry_cap == LOW_POWER_RETRY_CAP == 600.0
    seq, d = [], watch.retry_base
    for _ in range(12):
        d = watch._next_delay(d)
        seq.append(d)
    assert seq[:9] == [2, 4, 8, 16, 32, 64, 128, 256, 512] and seq[9:] == [600, 600, 600]


def test_low_power_reaches_the_android_device() -> None:
    dev = build_device(Config(device="android", low_power=True))
    assert isinstance(dev, AndroidBleDevice) and dev.low_power and dev.retry_cap == 600.0
    phone = build_device(Config(device="android"))
    assert isinstance(phone, AndroidBleDevice) and not phone.low_power and phone.retry_cap == 20.0


class StandbyBridge:
    """A Kotlin bridge with no panel in range; `standby()` is recorded, `come_back()` completes it."""

    def __init__(self, with_standby: bool = True) -> None:
        self.listener: Any = None
        self.connects = 0
        self.disconnects = 0
        self.standbys: list[str] = []
        if not with_standby:
            self.standby = None  # type: ignore[assignment]

    def _later(self, fn: Any, *args: Any) -> None:
        threading.Timer(0.002, fn, args).start()

    def connect(self, address: str | None, prefix: str, listener: Any) -> None:
        self.listener = listener
        self.connects += 1
        self._later(listener.onConnectFailed, "panel not found")

    def standby(self, address: str) -> None:  # type: ignore[no-redef]
        self.standbys.append(address)

    def write(self, data: bytes, with_response: bool, token: int) -> None:
        self._later(self.listener.onWriteDone, token, True, "")

    def disconnect(self) -> None:
        self.disconnects += 1

    def come_back(self) -> None:
        self._later(self.listener.onConnected, "AA:BB:CC:DD:EE:01", "IDM-039C09", 180)


async def test_watch_parks_a_standby_link_and_adopts_it_without_scanning() -> None:
    bridge = StandbyBridge()
    dev = AndroidBleDevice("AA:BB:CC:DD:EE:01", bridge=bridge, low_power=True, min_frame_interval=0.0)
    await dev.start()
    try:
        await _until(lambda: bridge.standbys == ["AA:BB:CC:DD:EE:01"])
        connects = bridge.connects
        bridge.come_back()  # the controller re-linked the panel on its own
        await _until(lambda: dev.connected, within=1.0)  # at once, not after the back-off
        assert bridge.connects == connects, "adopting the standby link needs no new active connect / scan"
        assert dev.info.name == "IDM-039C09" and dev.packet_size == 180
    finally:
        await dev.stop()


async def test_phone_never_parks_a_standby_link() -> None:
    bridge = StandbyBridge()
    dev = AndroidBleDevice("AA:BB:CC:DD:EE:01", bridge=bridge, low_power=False)
    await dev.start()
    try:
        await _until(lambda: bridge.connects >= 2, within=4.0)
        assert bridge.standbys == []
    finally:
        await dev.stop()


async def test_releasing_the_panel_cancels_the_standby_and_stops_retrying() -> None:
    bridge = StandbyBridge()
    dev = AndroidBleDevice("AA:BB:CC:DD:EE:01", bridge=bridge, low_power=True)
    await dev.start()
    try:
        await _until(lambda: bridge.standbys)
        await dev.set_link(False)  # the user releases / forgets the panel
        assert bridge.disconnects >= 1, "the parked autoConnect is cancelled"
        connects = bridge.connects
        bridge.come_back()  # a late controller callback must not re-take a released panel
        await asyncio.sleep(0.3)
        assert not dev.connected and bridge.connects == connects
        await dev.set_link(True)  # Connect again: an active attempt right away
        await _until(lambda: bridge.connects > connects)
    finally:
        await dev.stop()


async def test_supervisor_waits_on_events_while_released() -> None:
    bridge = StandbyBridge()
    dev = AndroidBleDevice("AA:BB:CC:DD:EE:01", bridge=bridge, low_power=True)
    dev.info.link_enabled = False
    await dev.start()
    try:
        await asyncio.sleep(0.3)
        assert bridge.connects == 0
        assert dev._supervisor is not None and not dev._supervisor.done()
    finally:
        await dev.stop()


# ------------------------------------------------------------------------------------------ server-side holds
def test_lobby_and_tv_hold_the_engine_until_closed(tmp_path: Path) -> None:
    app = create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins"))
    with TestClient(app) as c:
        eng = app.state.engine
        assert eng.holds == {}
        c.post("/api/play/lobby", json={"app": "tictactoe"})
        assert eng.holds == {"lobby": 1}
        assert eng.demand()["wifi"] is True
        c.post("/api/play/lobby", json={"app": "tictactoe"})  # re-open: still one hold
        assert eng.holds == {"lobby": 1}
        c.post("/api/tv")
        assert eng.holds == {"lobby": 1, "tv": 1}
        c.delete("/api/play/lobby")
        c.delete("/api/tv")
        assert eng.holds == {}
        assert c.get("/api/state").json()["engine"]["power"]["holds"] == {}


async def test_lan_websocket_holds_the_engine_but_a_local_one_does_not() -> None:
    class Eng:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def hold(self, r: str) -> None:
            self.calls.append("+" + r)

        def unhold(self, r: str) -> None:
            self.calls.append("-" + r)

    seen: list[list[str]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(list(eng.calls))

    eng = Eng()
    mw = _LanClients(inner, eng)  # type: ignore[arg-type]
    await mw({"type": "websocket", "client": ("192.168.1.50", 5000)}, None, None)
    assert seen[-1] == ["+lan"] and eng.calls == ["+lan", "-lan"]
    await mw({"type": "websocket", "client": ("127.0.0.1", 5000)}, None, None)  # the watch's own UI
    await mw({"type": "http", "client": ("192.168.1.50", 5000)}, None, None)  # plain REST
    assert eng.calls == ["+lan", "-lan"]
