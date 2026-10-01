"""Android BLE backend: the engine running inside the DeskDot Android app (see docs/adr/0011).

Android's Bluetooth stack is only reachable from Java/Kotlin, so the app ships a small `BleBridge` class (one GATT
session, MTU request, ack notifications, one GATT operation in flight). This backend drives it through Chaquopy's
Java interop and turns its callbacks — which arrive on Android binder threads — into asyncio futures.

Everything that matters for the panel (pacing, ack flow control, latest-frame-wins, GIF rules) stays in
`Device`, shared with the desktop backend. The bridge is injectable so this module is tested on the desktop
against a fake (tests/test_android_device.py).

Bridge contract (Kotlin `com.deskdot.app.BleBridge`, listener interface `com.deskdot.app.BleListener`):

- `connect(address: String?, namePrefix: String, listener)` — scan (by MAC, or by advertised name prefix), connect,
  request MTU, enable notifications; reports `onConnected(address, name, writeSize)` or `onConnectFailed(msg)`.
- `write(data: byte[], withResponse: boolean, token: int)` — reports `onWriteDone(token, ok, msg)`.
- `disconnect()` — close the GATT session (only on shutdown; the engine never disconnects voluntarily).
- unsolicited: `onNotify(data)` for every fa03 notification, `onDisconnected(msg)` when the link drops.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any

from . import protocol as P
from .base import Device

log = logging.getLogger("deskdot.android")

CONNECT_TIMEOUT = 25.0  # scan (≤10 s) + connect + MTU + service discovery
WRITE_TIMEOUT = 5.0


class _Events:
    """Receives bridge callbacks (on any thread) and hands them to the device on its event loop."""

    def __init__(self, device: AndroidBleDevice, loop: asyncio.AbstractEventLoop) -> None:
        self.device = device
        self.loop = loop

    def _call(self, fn: Any, *args: Any) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    def onConnected(self, address: str, name: str, write_size: int) -> None:
        self._call(self.device._connected_cb, str(address), str(name), int(write_size))

    def onConnectFailed(self, message: str) -> None:
        self._call(self.device._connect_failed_cb, str(message))

    def onDisconnected(self, message: str) -> None:
        self._call(self.device._disconnected_cb, str(message))

    def onNotify(self, data: Any) -> None:
        self._call(self.device._on_ack, _to_bytes(data))

    def onWriteDone(self, token: int, ok: bool, message: str) -> None:
        self._call(self.device._write_done_cb, int(token), bool(ok), str(message or ""))


def _to_bytes(data: Any) -> bytes:
    """Java byte[] arrives as a Chaquopy jarray of signed bytes; a fake bridge passes bytes."""
    if isinstance(data, bytes | bytearray):
        return bytes(data)
    return bytes(b & 0xFF for b in data)


def _java_bridge_and_listener(events: _Events) -> tuple[Any, Any]:  # pragma: no cover — Android only
    from java import dynamic_proxy, jclass  # type: ignore[import-not-found]

    listener_iface = jclass("com.deskdot.app.BleListener")

    class Listener(dynamic_proxy(listener_iface)):  # type: ignore[misc]
        def onConnected(self, address: str, name: str, write_size: int) -> None:
            events.onConnected(address, name, write_size)

        def onConnectFailed(self, message: str) -> None:
            events.onConnectFailed(message)

        def onDisconnected(self, message: str) -> None:
            events.onDisconnected(message)

        def onNotify(self, data: Any) -> None:
            events.onNotify(data)

        def onWriteDone(self, token: int, ok: bool, message: str) -> None:
            events.onWriteDone(token, ok, message)

    return jclass("com.deskdot.app.BleBridge").getInstance(), Listener()


class AndroidBleDevice(Device):
    kind = "android"

    def __init__(self, address: str | None, bridge: Any = None, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.info.address = address
        self._bridge = bridge  # None → the real Kotlin bridge, resolved on first connect
        self._listener: Any = None
        self._connect_future: asyncio.Future[tuple[str, str, int]] | None = None
        self._writes: dict[int, asyncio.Future[None]] = {}
        self._tokens = itertools.count(1)
        self._link_up = False

    def _ensure_bridge(self) -> None:
        if self._listener is not None:
            return
        events = _Events(self, asyncio.get_running_loop())
        if self._bridge is None:  # pragma: no cover — Android only
            self._bridge, self._listener = _java_bridge_and_listener(events)
        else:
            self._listener = events

    # ------------------------------------------------------------------ Device hooks
    async def _connect(self) -> None:
        self._ensure_bridge()
        self._set(status="scanning")
        loop = asyncio.get_running_loop()
        self._connect_future = loop.create_future()
        self._bridge.connect(self.info.address, P.NAME_PREFIX, self._listener)
        try:
            address, name, write_size = await asyncio.wait_for(self._connect_future, CONNECT_TIMEOUT)
        except TimeoutError:
            raise ConnectionError(
                "panel not found — is it powered, and not connected to the iDotMatrix phone app?"
            ) from None
        finally:
            self._connect_future = None
        self._link_up = True
        self.packet_size = max(20, write_size)
        self.info.address = address
        self.info.name = name
        self.info.mtu = self.packet_size

    async def _disconnect(self) -> None:
        was_up, self._link_up = self._link_up, False
        self._fail_writes("disconnected")
        if was_up and self._bridge is not None:
            try:
                self._bridge.disconnect()
            except Exception as e:  # pragma: no cover — defensive: the Java side may already be gone
                log.debug("disconnect: %s", e)

    async def _write_packet(self, packet: bytes, response: bool) -> None:
        if not self._link_up or self._bridge is None:
            raise ConnectionError("not connected")
        token = next(self._tokens)
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._writes[token] = fut
        try:
            self._bridge.write(packet, response, token)
            await asyncio.wait_for(fut, WRITE_TIMEOUT)
        except TimeoutError:
            raise ConnectionError("write timed out") from None
        finally:
            self._writes.pop(token, None)

    # ------------------------------------------------------------------ bridge callbacks (event loop)
    def _connected_cb(self, address: str, name: str, write_size: int) -> None:
        if self._connect_future is not None and not self._connect_future.done():
            self._connect_future.set_result((address, name, write_size))

    def _connect_failed_cb(self, message: str) -> None:
        if self._connect_future is not None and not self._connect_future.done():
            self._connect_future.set_exception(ConnectionError(message))

    def _disconnected_cb(self, message: str) -> None:
        if self._connect_future is not None and not self._connect_future.done():
            self._connect_future.set_exception(ConnectionError(message))
            return
        if self._link_up:
            self._link_up = False
            self._fail_writes(message)
            if not self._stopping:
                log.warning("panel link lost: %s", message)
                self._mark_disconnected(message or "link lost")

    def _write_done_cb(self, token: int, ok: bool, message: str) -> None:
        fut = self._writes.get(token)
        if fut is None or fut.done():
            return
        if ok:
            fut.set_result(None)
        else:
            fut.set_exception(ConnectionError(message or "write failed"))

    def _fail_writes(self, reason: str) -> None:
        for fut in self._writes.values():
            if not fut.done():
                fut.set_exception(ConnectionError(reason))
        self._writes.clear()
