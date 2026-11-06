"""Battery: the phone sleeps when there is nothing to drive (ADR 0016).

Covers the pure decision (`keepawake.decide`), the reporter that talks to the app's PowerGate (a fake host here), the
engine's "do I need the CPU" signal, the device's long back-off when the panel stays missing, and the hand-over's
beacon pace / peer freshness / quiet-holder ask.
"""

from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot import keepawake as ka
from deskdot.config import Config
from deskdot.device import base as device_base
from deskdot.device.base import LONG_BACKOFF, LONG_FAIL, SHORT_BACKOFF, Device, next_backoff
from deskdot.engine import Engine
from deskdot.handover import (
    BEACON_EVERY,
    BEACON_HOLDING_QUIET,
    BEACON_QUIET,
    PEER_FRESH,
    PEER_FRESH_MAX,
    Handover,
    beacon_interval,
    fresh_window,
)
from deskdot.keepawake import Inputs, KeepAwake, decide
from deskdot.server import create_app


# ====================================================================== the decision
@pytest.mark.parametrize(
    ("inputs", "awake", "reason"),
    [
        (Inputs(app_visible=True, link_enabled=False), True, "app open"),
        (Inputs(handover_busy=True, link_enabled=False), True, "hand-over"),
        (Inputs(request_age=10.0, link_enabled=False), True, "lan request"),
        (Inputs(connected=True, writing=True), True, "writing"),
        (Inputs(link_enabled=False), False, "released"),
        (Inputs(connected=True, engine="streaming"), True, "streaming"),
        (Inputs(connected=True, engine="playlist"), True, "playlist"),
        (Inputs(connected=True, engine=None), False, "static"),
        (Inputs(gated=True), False, "elsewhere"),
        (Inputs(attempting=True, failing_for=3600.0), True, "connecting"),
        (Inputs(failing_for=30.0), True, "reconnecting"),
        (Inputs(failing_for=ka.MISSING_GRACE + 1), False, "panel missing"),
    ],
)
def test_decide_awake_only_when_there_is_something_to_drive(inputs: Inputs, awake: bool, reason: str) -> None:
    assert decide(inputs) == (awake, reason)


def test_lan_requests_keep_it_awake_only_for_a_while() -> None:
    assert decide(Inputs(link_enabled=False, request_age=ka.REQUEST_GRACE - 1))[0] is True
    assert decide(Inputs(link_enabled=False, request_age=ka.REQUEST_GRACE + 1))[0] is False
    assert decide(Inputs(link_enabled=False, request_age=math.inf))[0] is False


# ====================================================================== the reporter
class FakeHost:
    def __init__(self) -> None:
        self.reports: list[tuple[bool, bool, bool, int, str]] = []
        self.screen = True
        self.visible = False

    def report(self, awake: bool, multicast: bool, lan: bool, wake_in: int, reason: str) -> None:
        self.reports.append((awake, multicast, lan, wake_in, reason))

    def screen_on(self) -> bool:
        return self.screen

    def app_visible(self) -> bool:
        return self.visible


class StubDevice(Device):
    kind = "android"

    def __init__(self) -> None:
        super().__init__(min_frame_interval=0.0, packet_gap=0.0)
        self.retries = 0
        self.fail_for = 0.0

    async def _connect(self) -> None:  # pragma: no cover — the supervisor is not started here
        raise ConnectionError("x")

    async def _disconnect(self) -> None:  # pragma: no cover
        pass

    async def _write_packet(self, packet: bytes, response: bool) -> None:  # pragma: no cover
        pass

    def retry_now(self) -> None:
        self.retries += 1

    def failing_for(self) -> float:
        return self.fail_for


class StubEngine:
    def __init__(self) -> None:
        self.reason: str | None = None
        self.refresh: float | None = None

    def cpu_reason(self) -> str | None:
        return self.reason

    def wake_in(self) -> float | None:
        return self.refresh


class StubHandover:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.taking = False

    def busy(self) -> bool:
        return self.taking


def _reporter(
    clock: list[float], **kw: Any
) -> tuple[KeepAwake, FakeHost, StubDevice, StubEngine, StubHandover]:
    host, dev, eng, ho = FakeHost(), StubDevice(), StubEngine(), StubHandover(**kw)
    keep = KeepAwake(host, device=dev, engine=eng, handover=ho, clock=lambda: clock[0])
    return keep, host, dev, eng, ho


def test_static_clip_lets_the_phone_sleep_after_the_grace_and_live_content_wakes_it() -> None:
    clock = [1000.0]
    keep, host, dev, eng, _ = _reporter(clock)
    dev.info.status = "connected"
    eng.reason = "streaming"
    keep.evaluate()
    assert host.reports[-1][0] is True and keep.reason == "streaming"
    eng.reason = None  # a baked clip / the firmware clock: nothing live
    keep.evaluate()
    assert keep.awake is True  # not at once: a GIF upload or a studio reopening gets IDLE_GRACE
    clock[0] += ka.IDLE_GRACE + 1
    keep.evaluate()
    awake, multicast, lan, wake_in, reason = host.reports[-1]
    assert (awake, multicast, lan) == (False, False, True)
    assert reason == "asleep: static" and wake_in == ka.NUDGE_EVERY
    eng.reason = "streaming"
    keep.evaluate()
    assert host.reports[-1][0] is True  # live content is back: awake at once, exactly as before


def test_a_clip_that_rebakes_with_time_asks_for_an_alarm() -> None:
    clock = [0.0]
    keep, host, dev, eng, _ = _reporter(clock)
    dev.info.status = "connected"
    eng.refresh = 90.0
    keep.evaluate()
    clock[0] += ka.IDLE_GRACE + 1
    keep.evaluate()
    assert host.reports[-1][3] == 90


def test_released_panel_sleeps_and_reports_only_changes() -> None:
    clock = [0.0]
    keep, host, dev, _, _ = _reporter(clock)
    dev.info.link_enabled = False
    for _ in range(3):
        keep.evaluate()
    clock[0] += ka.IDLE_GRACE + 1
    for _ in range(3):
        keep.evaluate()
    assert [r[0] for r in host.reports] == [True, False]
    assert host.reports[-1][4] == "asleep: released"


def test_missing_panel_sleeps_between_attempts_with_an_alarm_for_the_next() -> None:
    clock = [0.0]
    keep, host, dev, _, _ = _reporter(clock)
    dev.info.status = "error"
    dev.fail_for = 20.0
    keep.evaluate()
    assert keep.awake and keep.reason == "reconnecting"
    dev.fail_for = ka.MISSING_GRACE + 5
    dev.info.retry_at = time.time() + 170
    keep.evaluate()  # no grace between scheduled attempts
    awake, _, _, wake_in, reason = host.reports[-1]
    assert awake is False and reason == "asleep: panel missing"
    assert 160 <= wake_in <= 170
    dev.info.status = "connecting"  # the alarm fired and the attempt runs: awake for it
    keep.evaluate()
    assert host.reports[-1][0] is True


def test_handover_holds_multicast_and_the_setting_off_never_does() -> None:
    clock = [0.0]
    keep, host, dev, _, ho = _reporter(clock)
    dev.info.link_enabled = False
    ho.taking = True
    keep.evaluate()
    assert host.reports[-1][:3] == (True, True, True)
    ho.taking = False
    keep.evaluate()
    assert (
        host.reports[-1][1] is False
    )  # multicast only while a hand-over or pairing runs (the app adds "screen on")
    keep2, host2, _dev2, _, ho2 = _reporter(clock, enabled=False)
    ho2.taking = True
    keep2.evaluate()
    assert host2.reports[-1][1:3] == (False, False)


def test_opening_the_app_wakes_and_retries_the_panel_now() -> None:
    clock = [0.0]
    keep, host, dev, _, _ = _reporter(clock)
    dev.info.status = "error"
    dev.fail_for = 3600.0
    keep.evaluate()
    assert dev.retries == 0
    host.visible = True
    keep.evaluate()
    assert dev.retries == 1 and keep.reason == "app open"
    keep.evaluate()
    assert dev.retries == 1  # only on the edge


def test_lan_request_middleware_keeps_it_awake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = FakeHost()
    monkeypatch.setattr(ka, "HOST", host)
    cfg = Config(device="android", data_dir=tmp_path, plugins_dir=tmp_path / "plugins", lan_handover=False)
    from deskdot.device import android as android_dev

    monkeypatch.setattr(android_dev.AndroidBleDevice, "_connect", _never_connect)
    app = create_app(cfg)
    with TestClient(app, client=("192.168.1.50", 5555)) as c:
        c.get("/p/")  # a phone controller on the LAN
        keep = next(m.kwargs["keepawake"] for m in app.user_middleware if m.cls is ka.LanActivity)
        assert keep._last_request > -math.inf  # noted, with the loop's clock
        assert c.app.state.engine is not None
    with TestClient(app) as c:
        assert "power" in c.get("/api/state").json()


async def _never_connect(self: Any) -> None:
    await asyncio.sleep(3600)


def test_boot_clock_loop_runs_timers() -> None:
    loop = ka.BootClockLoop()
    try:
        t0 = loop.time()
        loop.run_until_complete(asyncio.sleep(0.01))
        assert loop.time() >= t0
    finally:
        loop.close()


# ====================================================================== the engine's signal
async def test_engine_needs_the_cpu_only_for_live_content(engine: Engine) -> None:
    engine.activate("clock")
    engine._tick()
    assert engine.cpu_reason() == "streaming"
    engine.activate("native")
    engine._tick()
    assert engine.cpu_reason() is None  # the firmware clock runs by itself
    engine.released = True
    assert engine.cpu_reason() is None


async def test_engine_ticks_slowly_when_nobody_can_see_a_frame(engine: Engine) -> None:
    engine.activate("clock")
    engine._tick()
    assert engine.device.connected is False  # the fixture's device was never started
    assert engine._delay() >= 1.0
    engine.frame_listeners.add(lambda _f: None)  # the studio watches: full rate again
    assert engine._delay() == engine._base_delay()


# ====================================================================== the device's long back-off
def test_next_backoff_grows_long_after_ten_minutes() -> None:
    assert next_backoff(1.0, 0.0) == 2.0
    assert next_backoff(16.0, 100.0) == SHORT_BACKOFF
    assert next_backoff(SHORT_BACKOFF, LONG_FAIL - 1) == SHORT_BACKOFF
    assert next_backoff(SHORT_BACKOFF, LONG_FAIL) == LONG_BACKOFF
    assert LONG_BACKOFF * 0.8 >= 120 and LONG_BACKOFF * 1.25 <= 300  # 2-5 minutes with the jitter


class MissingDevice(Device):
    kind = "ble"
    rearm_delay = 0.01

    def __init__(self) -> None:
        super().__init__(min_frame_interval=0.0, packet_gap=0.0)
        self.attempts_at: list[float] = []

    async def _connect(self) -> None:
        self.attempts_at.append(time.monotonic())
        raise ConnectionError("panel not found (AA:BB:CC:DD:EE:01)")

    async def _disconnect(self) -> None:
        pass

    async def _write_packet(self, packet: bytes, response: bool) -> None:  # pragma: no cover
        pass


async def test_supervisor_backs_off_long_and_reconnect_now_starts_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(device_base, "LONG_FAIL", 0.3)
    monkeypatch.setattr(device_base, "SHORT_BACKOFF", 0.05)
    monkeypatch.setattr(device_base, "LONG_BACKOFF", 30.0)
    monkeypatch.setattr(device_base, "RECOVER_AFTER", 10_000)
    dev = MissingDevice()
    await dev.start()
    try:
        end = time.monotonic() + 5
        while dev.failing_for() < 0.3 or dev.info.retry_at is None or dev.info.retry_at - time.time() < 10:
            assert time.monotonic() < end, "never reached the long back-off"
            await asyncio.sleep(0.02)
        n = len(dev.attempts_at)
        assert dev.info.retry_at - time.time() > 20  # ~30 s (jittered) until the next attempt
        await asyncio.sleep(0.3)
        assert len(dev.attempts_at) == n  # waiting, not hammering the air
        dev.retry_now()  # "Reconnect now" / opening the app
        await asyncio.sleep(0.2)
        assert len(dev.attempts_at) > n
        assert dev.failing_for() < 0.3  # the streak started over
    finally:
        await dev.stop()


# ====================================================================== the hand-over's beacons
def test_beacon_pace() -> None:
    assert beacon_interval(screen_on=True, heard_ago=1e9, holding=False) == BEACON_EVERY
    assert (
        beacon_interval(screen_on=False, heard_ago=5.0, holding=False) == BEACON_EVERY
    )  # someone is listening
    assert beacon_interval(screen_on=False, heard_ago=1e9, holding=True) == BEACON_HOLDING_QUIET
    assert beacon_interval(screen_on=False, heard_ago=1e9, holding=False) == BEACON_QUIET
    assert 15 <= BEACON_QUIET <= 30
    assert BEACON_HOLDING_QUIET < PEER_FRESH  # a 3.10 laptop still sees a quiet holder as nearby


def test_peer_freshness_follows_the_announced_pace() -> None:
    assert fresh_window(None) == PEER_FRESH  # a 3.10 beacon
    assert fresh_window(4.0) == PEER_FRESH
    assert fresh_window(20.0) == 50.0
    assert fresh_window(1e6) == PEER_FRESH_MAX
    assert fresh_window("x") == PEER_FRESH
    assert fresh_window(float("nan")) == PEER_FRESH


class _Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def test_a_slow_holder_stays_nearby_and_the_screen_sets_the_pace(tmp_path: Path) -> None:
    clock = _Clock()
    screen = [False]
    ho = Handover(StubDevice(), tmp_path, kind="android", clock=clock, screen_on=lambda: screen[0])
    assert ho.beacon_every() == BEACON_QUIET  # screen off, nobody heard, not holding
    screen[0] = True
    assert ho.beacon_every() == BEACON_EVERY
    screen[0] = False
    beacon = {"app": "deskdot", "id": "phone2", "name": "Phone", "holding": True, "every": BEACON_QUIET}
    ho.on_beacon(beacon, "192.168.1.20")
    assert ho.beacon_every() == BEACON_EVERY  # we just heard someone: keep the fast pace
    clock.t += 40  # past PEER_FRESH, within 2.5 x its 20 s pace
    holder = ho.holder_peer()
    assert holder is not None and holder.id == "phone2"
    assert ho.gate() is not None
    clock.t += 30
    assert ho.holder_peer() is None


async def test_busy_while_taking_or_pairing(tmp_path: Path) -> None:
    ho = Handover(StubDevice(), tmp_path, kind="android")
    assert ho.busy() is False
    ho.pair_out["x"] = {"status": "pending", "at": ho.clock(), "code": "123 456"}
    assert ho.busy() is True
    ho.pair_out.clear()
    ho.enabled = False
    assert ho.busy() is False


async def test_take_asks_the_quiet_last_holder_to_let_go(tmp_path: Path) -> None:
    """A phone whose screen is off sleeps between beacons, so nobody *says* they hold the panel: the taker asks the
    paired instance that last did, over signed HTTP, instead of failing with "probably held by"."""

    class Transport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def post(
            self, peer: Any, path: str, body: dict[str, Any], headers: dict[str, str]
        ) -> tuple[int, dict[str, Any]]:
            self.calls.append(path)
            return 200, {"released": True}

    class Connects(StubDevice):
        def retry_now(self) -> None:
            self.info.status = "connected"
            self._connected.set()

    t = Transport()
    dev = Connects()
    ho = Handover(dev, tmp_path, kind="ble", transport=t)
    ho.keys["phone"] = b"k" * 32
    from deskdot.handover import Peer

    ho.peers["phone"] = Peer(
        id="phone",
        name="Phone",
        kind="android",
        addr="192.168.1.20",
        paired=True,
        last_holding_at=ho.clock() - 600,
    )
    assert ho.holder_peer() is None  # its beacons stopped long ago
    ho.take()
    assert ho._task is not None
    await asyncio.wait_for(ho._task, 10)
    assert t.calls and t.calls[0].endswith("/lan/handover/release")
    assert ho.progress is not None and ho.progress["error"] is None


def test_reports_do_not_repeat_as_the_next_attempt_counts_down() -> None:
    clock = [0.0]
    keep, host, dev, _, _ = _reporter(clock)
    dev.info.status = "error"
    dev.fail_for = 20.0
    for left in (20, 15, 10):
        dev.info.retry_at = time.time() + left
        keep.evaluate()
    assert len(host.reports) == 1  # awake, reconnecting: once
    dev.fail_for = ka.MISSING_GRACE + 5
    dev.info.retry_at = time.time() + 170
    keep.evaluate()
    dev.info.retry_at = time.time() + 168  # same target, counting down
    keep.evaluate()
    assert len(host.reports) == 2
    dev.info.retry_at = time.time() + 400  # a new attempt was scheduled: a new alarm
    keep.evaluate()
    assert len(host.reports) == 3


async def test_a_device_change_is_evaluated_at_once() -> None:
    host, dev, eng = FakeHost(), StubDevice(), StubEngine()
    keep = KeepAwake(host, device=dev, engine=eng)
    await keep.start()
    try:
        await asyncio.sleep(0.05)
        n = len(host.reports)
        dev._set(link_enabled=False)  # the user released the panel: on_change fires
        keep._idle_since = -1e9  # past the grace
        dev._set(status="disconnected")
        await asyncio.sleep(0.05)  # well under the 2 s evaluation period
        assert len(host.reports) > n and host.reports[-1][0] is False
    finally:
        await keep.stop()
