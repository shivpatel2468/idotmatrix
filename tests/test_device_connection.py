"""Connection health: failure diagnosis, "Reconnect now", releasing the panel (ADR 0013) and the health probe.

A fake backend fails on demand, so the supervisor's back-off, the published reason / hint and the rule that a
reconnect never drops a link it doesn't have are checked without Bluetooth.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deskdot.config import Config
from deskdot.device.base import Device
from deskdot.device.diagnose import BUSY_AFTER, classify, diagnose
from deskdot.server import create_app


class FlakyDevice(Device):
    kind = "ble"

    def __init__(self, failures: list[str] | None = None) -> None:
        super().__init__(min_frame_interval=0.0, packet_gap=0.0)
        self.failures = list(failures or [])
        self.attempt_times: list[float] = []
        self.disconnects = 0
        self.packets = 0

    async def _connect(self) -> None:
        self.attempt_times.append(time.monotonic())
        if self.failures:
            raise ConnectionError(self.failures.pop(0))
        self.info.name = "IDM-TEST"

    async def _disconnect(self) -> None:
        self.disconnects += 1

    async def _write_packet(self, packet: bytes, response: bool) -> None:
        await asyncio.sleep(0.005)
        self.packets += 1


async def _until(cond, limit: float = 3.0) -> None:  # type: ignore[no-untyped-def]
    end = time.monotonic() + limit
    while not cond():
        assert time.monotonic() < end, "timed out"
        await asyncio.sleep(0.01)


# ------------------------------------------------------------------ diagnosis
@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (
            "panel not found (AA:BB:CC:DD:EE:01) — is it powered and not connected to the phone app?",
            "not_found",
        ),
        ("Bluetooth device is turned off", "bluetooth_off"),
        ("No Bluetooth adapters found.", "bluetooth_off"),
        ("connect timed out after 45s", "no_answer"),
        (
            "The panel didn't answer. Is it powered and close by? (NetworkError: GATT Server is disconnected.)",
            "no_answer",
        ),
        ("Bluetooth permission was blocked for this site. Allow it, then click Connect panel.", "permission"),
        ("Click “Connect panel” and pick your IDM-… panel", "needs_user"),
        ("Your panel (IDM-1) is connected to DeskDot on this computer. Open it there…", "busy"),
        ("link lost", "link_lost"),
        ("write failed: not connected", "link_lost"),
        ("disconnected from the studio", "released"),
        ("something odd", "error"),
    ],
)
def test_classify(message: str, reason: str) -> None:
    assert classify(message) == reason


def test_repeated_not_found_means_busy_with_the_other_apps_named() -> None:
    assert diagnose("panel not found", "ble", attempts=1)[0] == "not_found"
    reason, hint = diagnose("panel not found", "ble", attempts=BUSY_AFTER)
    assert reason == "busy"
    assert "phone app" in hint and "browser tab" in hint
    assert "DeskDot on this computer" in diagnose("panel not found", "web", attempts=BUSY_AFTER)[1]


# ------------------------------------------------------------------ supervisor
async def test_failure_is_published_with_reason_hint_and_retry_time() -> None:
    dev = FlakyDevice(["panel not found (any IDM-* panel)"] * 5)
    await dev.start()
    try:
        await _until(lambda: dev.info.attempts >= 1)
        info = dev.info
        assert info.status == "error" and info.reason == "not_found"
        assert info.hint and "one app at a time" in info.hint
        assert info.retry_at is not None and info.retry_at > time.time()
    finally:
        await dev.stop()


async def test_reconnect_now_cuts_the_back_off_short_without_disconnecting() -> None:
    dev = FlakyDevice(["panel not found"] * 4)  # back-off after these: 1 s, 2 s, 4 s, 8 s
    await dev.start()
    try:
        await _until(lambda: len(dev.attempt_times) >= 1)
        await asyncio.sleep(0.05)
        disconnects = dev.disconnects
        assert await dev.reconnect() == "retrying"
        await _until(lambda: len(dev.attempt_times) >= 2, limit=0.5)  # long before the 1 s back-off
        assert dev.disconnects == disconnects, "a retry never drops a link (rule 5)"
    finally:
        await dev.stop()


async def test_success_clears_the_diagnosis() -> None:
    dev = FlakyDevice(["connect timed out after 45s"])
    await dev.start()
    try:
        await _until(lambda: dev.info.attempts == 1)
        dev.retry_now()
        await _until(lambda: dev.connected)
        info = dev.info
        assert (info.attempts, info.reason, info.hint, info.last_error, info.retry_at) == (
            0,
            None,
            None,
            None,
            None,
        )
        assert info.last_seen is not None
    finally:
        await dev.stop()


async def test_reconnect_if_down_leaves_a_good_link_alone() -> None:
    dev = FlakyDevice()
    await dev.start()
    try:
        await _until(lambda: dev.connected)
        assert await dev.reconnect(only_if_down=True) == "connected"
        assert dev.connected and dev.disconnects == 0
    finally:
        await dev.stop()


async def test_release_stops_reconnecting_until_connect() -> None:
    dev = FlakyDevice()
    await dev.start()
    try:
        await _until(lambda: dev.connected)
        await dev.set_link(False)  # the user's "Release the panel"
        assert dev.info.reason == "released" and not dev.connected
        attempts = len(dev.attempt_times)
        await asyncio.sleep(1.2)
        assert len(dev.attempt_times) == attempts, "a released panel stays free for other apps"
        await dev.set_link(True)
        await _until(lambda: dev.connected)
        assert dev.info.reason is None
    finally:
        await dev.stop()


async def test_reconnect_takes_a_released_panel_back() -> None:
    dev = FlakyDevice()
    await dev.start()
    try:
        await _until(lambda: dev.connected)
        await dev.set_link(False)
        assert await dev.reconnect() == "retrying"
        await _until(lambda: dev.connected)
        assert dev.info.link_enabled
    finally:
        await dev.stop()


async def test_pause_writes_finishes_the_item_in_flight_then_sends_nothing() -> None:
    # the web app's tab hand-off: the old tab goes quiet (never mid-message), the link itself stays up
    dev = FlakyDevice()
    await dev.start()
    try:
        await _until(lambda: dev.connected)
        dev.command([bytes(20)] * 30)  # one long message in flight
        await _until(lambda: dev.packets > 0)
        assert await dev.pause_writes(3.0)
        sent = dev.packets
        dev.command(bytes(20))
        dev.show_frame(b"png" * 10)
        await asyncio.sleep(0.2)
        assert dev.packets == sent and dev.connected and dev.disconnects == 0
        dev.resume_writes()
        await _until(lambda: dev.packets > sent)
    finally:
        await dev.stop()


# ------------------------------------------------------------------ HTTP
def test_health_probe_for_the_web_app(tmp_path: Path) -> None:
    app = create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins"))
    with TestClient(app) as c:
        r = c.get("/api/health", headers={"Origin": "https://idotmatrix.com"})
        assert r.headers["access-control-allow-origin"] == "https://idotmatrix.com"
        body = r.json()
        assert {"device", "kind", "panel", "link_enabled"} <= body.keys()
        assert (
            "access-control-allow-origin"
            not in c.get("/api/health", headers={"Origin": "https://evil.example"}).headers
        )
        pre = c.options(
            "/api/health",
            headers={"Origin": "https://idotmatrix.com", "Access-Control-Request-Private-Network": "true"},
        )
        assert pre.status_code == 204 and pre.headers["access-control-allow-private-network"] == "true"


def test_reconnect_endpoint(tmp_path: Path) -> None:
    app = create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins"))
    with TestClient(app) as c:
        assert c.post("/api/device/reconnect", json={"only_if_down": True}).json()["result"] in (
            "connected",
            "retrying",
        )
        assert c.post("/api/device/reconnect").json()["ok"]
        assert "reason" in c.get("/api/state").json()["device"]
