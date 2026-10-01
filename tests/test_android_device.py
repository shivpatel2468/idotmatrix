"""The Android BLE backend (device/android.py) against a fake Kotlin bridge.

The fake answers from its own thread, like Android's binder threads, so the thread → event-loop hand-off is
exercised. It also enforces Android's GATT rule: one operation in flight at a time.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from dotdeck.config import Config
from dotdeck.device import protocol as P
from dotdeck.device.android import AndroidBleDevice
from dotdeck.server import build_device


class FakeBridge:
    def __init__(self, write_size: int = 180, find: bool = True) -> None:
        self.write_size = write_size
        self.find = find
        self.listener: Any = None
        self.connects = 0
        self.disconnects = 0
        self.packets: list[tuple[bytes, bool]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.fail_next_write = False
        self._lock = threading.Lock()

    def _later(self, fn: Any, *args: Any, delay: float = 0.002) -> None:
        threading.Timer(delay, fn, args).start()

    # ------------------------------------------------ the Kotlin API
    def connect(self, address: str | None, prefix: str, listener: Any) -> None:
        self.listener = listener
        self.connects += 1
        if self.find:
            self._later(
                listener.onConnected, address or "AA:BB:CC:DD:EE:FF", f"{prefix}XXXXXX", self.write_size
            )
        else:
            self._later(listener.onConnectFailed, "panel not found")

    def write(self, data: bytes, with_response: bool, token: int) -> None:
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        assert len(data) <= self.write_size, "a packet larger than the negotiated write size"
        self.packets.append((bytes(data), with_response))
        ok = not self.fail_next_write
        self.fail_next_write = False

        def done() -> None:
            with self._lock:
                self.in_flight -= 1
            self.listener.onWriteDone(token, ok, "" if ok else "GATT_ERROR 133")
            if ok and data[:1] and len(self.packets) % 3 == 0:
                self.listener.onNotify([5, 0, 0, 0, 1])  # a Java byte[] arrives as a list of signed bytes

        self._later(done)

    def disconnect(self) -> None:
        self.disconnects += 1

    # ------------------------------------------------ test helpers
    def drop_link(self) -> None:
        self._later(self.listener.onDisconnected, "GATT status 8 (link supervision timeout)")


async def _until(cond: Any, within: float = 3.0) -> None:
    end = time.monotonic() + within
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


async def _started(bridge: FakeBridge) -> AndroidBleDevice:
    dev = AndroidBleDevice("AA:BB:CC:DD:EE:01", bridge=bridge, min_frame_interval=0.0, packet_gap=0.001)
    await dev.start()
    await _until(lambda: dev.connected)
    return dev


async def test_connects_and_reports_the_panel() -> None:
    bridge = FakeBridge(write_size=180)
    dev = await _started(bridge)
    try:
        assert dev.info.kind == "android"
        assert dev.info.address == "AA:BB:CC:DD:EE:01"
        assert dev.info.name and dev.info.name.startswith(P.NAME_PREFIX)
        assert dev.packet_size == 180 and dev.info.mtu == 180
    finally:
        await dev.stop()


async def test_frames_are_split_into_paced_packets_one_at_a_time() -> None:
    bridge = FakeBridge(write_size=100)
    dev = await _started(bridge)
    try:
        png = bytes(range(256)) * 3  # 768 B: several packets
        dev.show_frame(png)
        payload = P.image_upload(png)
        await _until(lambda: b"".join(p for p, _ in bridge.packets).endswith(payload))
        assert bridge.max_in_flight == 1, "Android allows one GATT operation in flight"
        assert all(len(p) <= 100 for p, _ in bridge.packets)
        await _until(lambda: dev.info.frames_sent >= 1)  # counted once the last packet lands
        await _until(lambda: dev.info.last_ack == "05 00 00 00 01")
    finally:
        await dev.stop()


async def test_link_loss_reconnects_and_replays_the_screen() -> None:
    bridge = FakeBridge()
    dev = await _started(bridge)
    try:
        png = b"\x89PNG" + bytes(200)
        dev.show_frame(png)
        await _until(lambda: b"".join(p for p, _ in bridge.packets).endswith(P.image_upload(png)))
        sent = len(bridge.packets)
        bridge.drop_link()
        await _until(lambda: bridge.connects >= 2 and dev.connected, within=5.0)
        # after reconnecting, the engine restores power/brightness and then whatever was on screen
        await _until(lambda: P.image_upload(png) in b"".join(p for p, _ in bridge.packets[sent:]), within=5.0)
        assert bridge.disconnects == 0, "the engine never disconnects voluntarily (pairing screen)"
    finally:
        await dev.stop()


async def test_panel_not_found_retries_with_an_error() -> None:
    bridge = FakeBridge(find=False)
    dev = AndroidBleDevice(None, bridge=bridge, min_frame_interval=0.0)
    await dev.start()
    try:
        await _until(lambda: dev.info.status == "error")
        assert "not found" in (dev.info.last_error or "")
        bridge.find = True
        await _until(lambda: dev.connected, within=5.0)
    finally:
        await dev.stop()


async def test_a_failed_write_marks_the_link_down_and_recovers() -> None:
    bridge = FakeBridge()
    dev = await _started(bridge)
    try:
        bridge.fail_next_write = True
        dev.command(P.brightness(50))
        await _until(lambda: bridge.connects >= 2 and dev.connected, within=5.0)
    finally:
        await dev.stop()


@pytest.mark.parametrize("kind", ["android"])
def test_config_builds_the_android_device(kind: str) -> None:
    dev = build_device(Config(device=kind))  # type: ignore[arg-type]
    assert isinstance(dev, AndroidBleDevice)
