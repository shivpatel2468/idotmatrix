"""Web Bluetooth backend: the engine running in a browser tab under Pyodide (docs/WEB_APP.md, ADR 0012).

The engine runs in a Web Worker, but `navigator.bluetooth` only exists on the page, so the page owns the GATT
session and the worker drives it through a small message bridge (`site/app/engine/ble.js` + `worker.js`). The
shape mirrors the Android bridge (device/android.py): one GATT session, writes acknowledged one at a time by
token, fa03 notifications forwarded as acks, and the link loss reported back.

Everything that matters for the panel (pacing, ack flow control, latest-frame-wins, GIF rules) stays in `Device`,
shared with the desktop, so the hardware findings in HARDWARE_PROTOCOL.md apply unchanged. The bridge is
injectable so this module is tested on the desktop against a fake (tests/test_web_device.py).

Bridge contract (JS object `deskdotBle` in the worker's global scope):

- `connect(namePrefix, listener)` — connect to the panel the user picked (or one the browser remembers from an
  earlier visit). Reports `onConnected(address, name, writeSize)`, `onConnectFailed(msg)`, or — when the user
  hasn't picked a panel yet — `onNeedsUser(msg)`; the page then shows its "Connect panel" button, and a click
  (the user gesture Web Bluetooth requires) calls `listener.onUserPicked()`.
- `write(data: Uint8Array, withResponse: bool, token: int)` — reports `onWriteDone(token, ok, msg)`. Browsers don't
  expose the negotiated MTU, so `writeSize` is the page's guess; if the stack refuses a packet that long, the page
  re-sends it in smaller pieces and reports the size that works with `onWriteSize(n)`.
- `disconnect()` — close the GATT session (only when the user unlinks the panel; never voluntarily).
- unsolicited: `onNotify(data)` for every fa03 notification, `onDisconnected(msg)` when the link drops.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any

from . import protocol as P
from .base import Device

log = logging.getLogger("deskdot.web")

CONNECT_TIMEOUT = 30.0  # GATT connect + service discovery + notifications (the chooser is not counted)
WRITE_TIMEOUT = 5.0
NEEDS_USER = "Click “Connect panel” and pick your IDM-… panel"


def _to_bytes(data: Any) -> bytes:
    """A JS Uint8Array arrives as a Pyodide JsProxy (`to_bytes()`); a fake bridge passes bytes."""
    if isinstance(data, bytes | bytearray | memoryview):
        return bytes(data)
    to_bytes = getattr(data, "to_bytes", None)
    if to_bytes is not None:
        return bytes(to_bytes())
    return bytes(b & 0xFF for b in data)


class _Listener:
    """Bridge callbacks. The browser is single-threaded, so they already run on the engine's event loop."""

    def __init__(self, device: WebBleDevice) -> None:
        self.device = device

    def onConnected(self, address: str, name: str, write_size: int) -> None:
        self.device._connected_cb(str(address), str(name), int(write_size))

    def onConnectFailed(self, message: str) -> None:
        self.device._connect_failed_cb(str(message))

    def onNeedsUser(self, message: str) -> None:
        self.device._needs_user_cb(str(message or NEEDS_USER))

    def onUserPicked(self) -> None:
        self.device._user_picked_cb()

    def onDisconnected(self, message: str) -> None:
        self.device._disconnected_cb(str(message or "link lost"))

    def onWriteSize(self, write_size: int) -> None:
        self.device._write_size_cb(int(write_size))

    def onNotify(self, data: Any) -> None:
        self.device._on_ack(_to_bytes(data))

    def onWriteDone(self, token: int, ok: bool, message: str) -> None:
        self.device._write_done_cb(int(token), bool(ok), str(message or ""))


class _JsBridge:  # pragma: no cover — browser only
    """Adapts the worker's `deskdotBle` object: Python bytes -> Uint8Array, listener -> a persistent proxy."""

    def __init__(self) -> None:
        import js  # type: ignore[import-not-found]

        self._js = js.deskdotBle
        self._proxy: Any = None

    def connect(self, name_prefix: str, listener: _Listener) -> None:
        from pyodide.ffi import create_proxy  # type: ignore[import-not-found]

        if self._proxy is None:
            self._proxy = create_proxy(listener)
        self._js.connect(name_prefix, self._proxy)

    def write(self, data: bytes, with_response: bool, token: int) -> None:
        from pyodide.ffi import to_js  # type: ignore[import-not-found]

        self._js.write(to_js(memoryview(data)), with_response, token)

    def disconnect(self) -> None:
        self._js.disconnect()


class WebBleDevice(Device):
    kind = "web"
    # The supervisor's own timeout would also count the time the user takes to click "Connect panel" (which may
    # be never). `_connect` enforces CONNECT_TIMEOUT on the GATT part itself. (A week, not "forever": the browser's
    # setTimeout overflows past 2^31 ms and would fire at once.)
    connect_timeout = 7 * 24 * 3600.0

    def __init__(self, address: str | None = None, bridge: Any = None, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.info.address = address
        self._bridge = bridge  # None → the page's Web Bluetooth bridge, resolved on first connect
        self._listener = _Listener(self)
        self._connect_future: asyncio.Future[tuple[str, str, int]] | None = None
        self._picked = asyncio.Event()
        self._writes: dict[int, asyncio.Future[None]] = {}
        self._tokens = itertools.count(1)
        self._link_up = False
        #: True while the engine waits for the user to pick a panel in the browser's chooser
        self.needs_user = False

    # ------------------------------------------------------------------ Device hooks
    async def _connect(self) -> None:
        if self._bridge is None:  # pragma: no cover — browser only
            self._bridge = _JsBridge()
        delay = 1.0
        while True:
            if not self.info.link_enabled:
                raise ConnectionError("panel unlinked in the studio")
            self._set(status="connecting")
            loop = asyncio.get_running_loop()
            self._connect_future = loop.create_future()
            self._picked.clear()
            self._bridge.connect(P.NAME_PREFIX, self._listener)
            try:
                result = await asyncio.wait_for(self._connect_future, CONNECT_TIMEOUT)
            except _NeedsUser as e:
                # nothing to connect to until the user clicks: idle (no retries, no error spam) until they do
                self.needs_user = True
                self._set(status="disconnected", last_error=str(e))
                await self._picked.wait()
                self.needs_user = False
                continue
            except (ConnectionError, TimeoutError) as e:
                # Retry with back-off like the supervisor does, but a click on "Connect panel" (a new pick) cuts
                # the wait short — the supervisor's own back-off sleep couldn't be woken.
                msg = (
                    str(e)
                    if isinstance(e, ConnectionError)
                    else "panel didn't answer — is it powered, in range, and not connected to the phone app "
                    "or the desktop app?"
                )
                log.warning("connect failed: %s — retrying in %.0fs", msg, delay)
                self._set(status="error", last_error=msg)
                try:
                    await asyncio.wait_for(self._picked.wait(), delay)
                except TimeoutError:
                    pass
                delay = min(delay * 2, 20.0)
                continue
            finally:
                self._connect_future = None
            break
        address, name, write_size = result
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
            except Exception as e:  # pragma: no cover — defensive: the page may already be gone
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

    # ------------------------------------------------------------------ bridge callbacks
    def _connected_cb(self, address: str, name: str, write_size: int) -> None:
        if self._connect_future is not None and not self._connect_future.done():
            self._connect_future.set_result((address, name, write_size))

    def _connect_failed_cb(self, message: str) -> None:
        if self._connect_future is not None and not self._connect_future.done():
            self._connect_future.set_exception(ConnectionError(message))

    def _needs_user_cb(self, message: str) -> None:
        if self._connect_future is not None and not self._connect_future.done():
            self._connect_future.set_exception(_NeedsUser(message))

    def _user_picked_cb(self) -> None:
        """The user picked a panel in the chooser: connect now (also cuts a reconnect back-off short)."""
        self._picked.set()
        if not self.info.link_enabled:
            self.info.link_enabled = True
            self._on_change()

    def _write_size_cb(self, write_size: int) -> None:
        """The page found the link takes smaller packets than it first guessed (a write was refused)."""
        size = max(20, write_size)
        if size != self.packet_size:
            log.info("packet size %d -> %d bytes", self.packet_size, size)
            self.packet_size = size
            self._set(mtu=size)

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


class _NeedsUser(Exception):
    """The browser has no panel to connect to until the user picks one (a user gesture)."""
