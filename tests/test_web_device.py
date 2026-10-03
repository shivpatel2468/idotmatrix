"""The Web Bluetooth backend (device/web.py) against a fake page bridge.

In the browser everything runs on one thread (the worker's event loop) and the page answers asynchronously, so
the fake answers through `loop.call_later`. It enforces one GATT operation in flight (Chrome rejects a second
write while one is pending) and records when each packet went out, so the pacing gap is checked too.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any

from deskdot import platforms
from deskdot.config import Config
from deskdot.device import protocol as P
from deskdot.device.web import NEEDS_USER, WebBleDevice, _to_bytes
from deskdot.server import build_device


class FakePage:
    def __init__(self, write_size: int = 180, picked: bool = True, reachable: bool = True) -> None:
        self.write_size = write_size
        self.picked = picked  # the user already chose a panel (or the browser remembers one)
        self.reachable = reachable
        self.listener: Any = None
        self.connects = 0
        self.disconnects = 0
        self.packets: list[tuple[bytes, bool, float]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.fail_next_write = False
        self.ack_every_write = False  # GIF chunks: the panel acks each 4 KiB chunk

    def _later(self, fn: Any, *args: Any, delay: float = 0.002) -> None:
        asyncio.get_running_loop().call_later(delay, fn, *args)

    # ------------------------------------------------ the deskdotBle API
    def connect(self, prefix: str, listener: Any) -> None:
        self.listener = listener
        self.connects += 1
        if not self.picked:
            self._later(listener.onNeedsUser, NEEDS_USER)
        elif self.reachable:
            self._later(listener.onConnected, "web:panel-id", f"{prefix}XXXXXX", self.write_size)
        else:
            self._later(listener.onConnectFailed, "NetworkError: Bluetooth Device is no longer in range.")

    def write(self, data: bytes, with_response: bool, token: int) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        assert len(data) <= self.write_size, "a packet larger than the write size"
        self.packets.append((bytes(data), with_response, time.monotonic()))
        ok = not self.fail_next_write
        self.fail_next_write = False

        def done() -> None:
            self.in_flight -= 1
            self.listener.onWriteDone(token, ok, "" if ok else "NetworkError: GATT operation failed")
            if ok and self.ack_every_write:
                self.listener.onNotify(bytes([5, 0, 1, 0, 1]))

        self._later(done)

    def disconnect(self) -> None:
        self.disconnects += 1

    # ------------------------------------------------ test helpers
    def user_picks(self) -> None:
        self.picked = True
        self.listener.onUserPicked()

    def drop_link(self) -> None:
        self._later(self.listener.onDisconnected, "gattserverdisconnected")

    def stream(self) -> bytes:
        return b"".join(p for p, _, _ in self.packets)


async def _until(cond: Any, within: float = 3.0) -> None:
    end = time.monotonic() + within
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


async def _started(page: FakePage, gap: float = 0.001) -> WebBleDevice:
    dev = WebBleDevice(bridge=page, min_frame_interval=0.0, packet_gap=gap)
    await dev.start()
    await _until(lambda: dev.connected)
    return dev


async def test_connects_and_reports_the_panel() -> None:
    page = FakePage(write_size=244)
    dev = await _started(page)
    try:
        assert dev.info.kind == "web"
        assert dev.info.name and dev.info.name.startswith(P.NAME_PREFIX)
        assert dev.packet_size == 244 and dev.info.mtu == 244
    finally:
        await dev.stop()


async def test_waits_for_the_user_gesture_without_retrying() -> None:
    page = FakePage(picked=False)
    dev = WebBleDevice(bridge=page, min_frame_interval=0.0)
    await dev.start()
    try:
        await _until(lambda: dev.needs_user)
        await asyncio.sleep(0.3)
        assert page.connects == 1, "no retry loop while nobody has picked a panel"
        assert dev.info.status == "disconnected" and "Connect panel" in (dev.info.last_error or "")
        page.user_picks()
        await _until(lambda: dev.connected)
        assert not dev.needs_user
    finally:
        await dev.stop()


async def test_frames_are_split_into_paced_packets_one_at_a_time() -> None:
    page = FakePage(write_size=100)
    dev = await _started(page, gap=0.02)
    try:
        png = bytes(range(256)) * 3  # 768 B: several packets
        dev.show_frame(png)
        payload = P.image_upload(png)
        await _until(lambda: page.stream().endswith(payload))
        assert page.max_in_flight == 1, "one GATT operation in flight"
        assert all(len(p) <= 100 for p, _, _ in page.packets)
        frame = [t for p, _, t in page.packets[-len(range(0, len(payload), 100)) :]]
        gaps = [b - a for a, b in itertools.pairwise(frame)]
        assert gaps and min(gaps) >= 0.018, f"packets of one message must be paced: {gaps}"
        await _until(lambda: dev.info.frames_sent >= 1)
    finally:
        await dev.stop()


async def test_latest_frame_wins() -> None:
    page = FakePage(write_size=20)
    dev = await _started(page)
    try:
        frames = [bytes([i]) * 300 for i in range(1, 6)]
        for f in frames:
            dev.show_frame(f)  # faster than the link: only the newest may go out after the first
        await _until(lambda: page.stream().endswith(P.image_upload(frames[-1])))
        sent = page.stream()
        for f in frames[1:-1]:
            assert P.image_upload(f) not in sent, "a superseded frame was sent (FIFO queue)"
        assert dev.info.frames_dropped >= 3
    finally:
        await dev.stop()


async def test_gif_chunks_wait_for_their_ack() -> None:
    page = FakePage(write_size=244)
    page.ack_every_write = True
    dev = await _started(page)
    try:
        gif = b"GIF89a" + bytes(9000)  # three 4 KiB chunks
        dev.show_gif(gif)
        chunks = P.gif_upload(gif)
        await _until(lambda: page.stream().endswith(chunks[-1]), within=10.0)
        await _until(lambda: dev.info.mode == "gif")  # set once the final chunk is acked
        assert page.max_in_flight == 1
    finally:
        await dev.stop()


async def test_link_loss_reconnects_and_replays_the_screen() -> None:
    page = FakePage()
    dev = await _started(page)
    try:
        png = b"\x89PNG" + bytes(200)
        dev.show_frame(png)
        await _until(lambda: page.stream().endswith(P.image_upload(png)))
        sent = len(page.packets)
        page.drop_link()
        await _until(lambda: page.connects >= 2 and dev.connected, within=5.0)
        await _until(
            lambda: P.image_upload(png) in b"".join(p for p, _, _ in page.packets[sent:]), within=5.0
        )
        assert page.disconnects == 0, "the engine never disconnects voluntarily (pairing screen)"
    finally:
        await dev.stop()


async def test_unreachable_panel_retries_and_a_new_pick_cuts_the_wait_short() -> None:
    page = FakePage(reachable=False)
    dev = WebBleDevice(bridge=page, min_frame_interval=0.0)
    await dev.start()
    try:
        await _until(lambda: dev.info.status == "error")
        assert "range" in (dev.info.last_error or "")
        await _until(lambda: page.connects >= 3, within=5.0)  # back-off 1 s, 2 s …
        page.reachable = True
        page.user_picks()  # the user clicks "Connect panel" again: no waiting out the back-off
        await _until(lambda: dev.connected, within=1.0)
    finally:
        await dev.stop()


async def test_a_failed_write_marks_the_link_down_and_recovers() -> None:
    page = FakePage()
    dev = await _started(page)
    try:
        page.fail_next_write = True
        dev.command(P.brightness(50))
        await _until(lambda: page.connects >= 2 and dev.connected, within=5.0)
    finally:
        await dev.stop()


def test_bytes_from_the_page() -> None:
    class JsArray:  # a Pyodide JsProxy of a Uint8Array
        def to_bytes(self) -> bytes:
            return b"\x05\x00\x00\x00\x01"

    assert _to_bytes(JsArray()) == b"\x05\x00\x00\x00\x01"
    assert _to_bytes([5, 0, 1]) == b"\x05\x00\x01"


def test_config_builds_the_web_device() -> None:
    dev = build_device(Config(device="web"))
    assert isinstance(dev, WebBleDevice)
    assert dev.packet_gap > 0, "the web link is paced like every real link"


def test_web_platform_has_no_host_features() -> None:
    assert platforms.LABELS["web"] == "Browser"
    assert not any(platforms.supported(f, "web") for f in platforms.FEATURES)
    assert platforms.supported("system", "android")
