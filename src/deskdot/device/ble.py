"""Bluetooth LE backend (bleak). One persistent GATT session for the app's lifetime.

The panel shows its blinking pairing icon whenever the link drops, so this
backend never disconnects voluntarily; it reconnects with backoff when the
link is lost (see Device._supervise).

Session hygiene (ADR 0015, docs/HARDWARE_PROTOCOL.md finding 18). On Windows a GATT connection stays up as long as
*any* WinRT object of it is alive — the `GattSession`, the `BluetoothLEDevice` or a single `GattDeviceService`.
bleak closes the session and device when the link drops, but the services only in `disconnect()`. So:

* every `BleakClient` this backend creates is disposed with `disconnect()` — after a link loss, a failed or
  timed-out attempt, and a release — whether or not it still reports `is_connected`;
* the client is remembered *before* `connect()` starts, so a timed-out attempt can still be disposed;
* disconnect callbacks are bound to their own client: a late callback from an old session never marks a newer,
  healthy link as lost;
* services are always read from the panel (`use_cached_services=False`): the firmware sends "services changed"
  and a stale Windows cache made start_notify fail on a link that was already going away.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from . import protocol as P
from .base import Device

log = logging.getLogger("deskdot.ble")
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


async def scan(seconds: float = 6.0) -> list[dict[str, object]]:
    """Discover nearby iDotMatrix panels (advertised name starts with 'IDM-')."""
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    out = []
    for dev, adv in found.values():
        name = adv.local_name or dev.name or ""
        if name.startswith(P.NAME_PREFIX):
            out.append({"address": dev.address, "name": name, "rssi": adv.rssi})
    return sorted(out, key=lambda d: -int(d["rssi"] or -999))  # type: ignore[call-overload]


class BleDevice(Device):
    kind = "ble"

    def __init__(self, address: str | None, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.info.address = address
        self._client: BleakClient | None = None
        self._stale: set[BleakClient] = set()  # clients whose link dropped, waiting to be disposed

    async def _find(self) -> BLEDevice:
        self._set(status="scanning")
        if self.info.address and sys.platform == "darwin" and MAC_RE.match(self.info.address):
            # CoreBluetooth never exposes MAC addresses (devices get per-host UUIDs), so on macOS a
            # configured MAC can't be used: find the panel by its advertised IDM- name instead.
            log.info(
                "macOS: ignoring MAC %s, scanning for an %s* panel by name", self.info.address, P.NAME_PREFIX
            )
            self.info.address = None
        want = (self.info.address or "").lower()
        rssi: list[int] = []

        def match(d: BLEDevice, adv: AdvertisementData) -> bool:
            # same test as BleakScanner.find_device_by_address (case-insensitive), but we also keep the signal
            ok = (
                d.address.lower() == want
                if want
                else (adv.local_name or d.name or "").startswith(P.NAME_PREFIX)
            )
            if ok:
                rssi.append(adv.rssi)
            return ok

        dev = await BleakScanner.find_device_by_filter(match, timeout=10.0)
        if dev is None:
            if want and sys.platform == "win32" and await asyncio.to_thread(_windows_holds, want):
                raise ConnectionError(
                    f"panel not found ({self.info.address}) — this computer is still connected to it (a browser tab, "
                    "another app, or an old session DeskDot is clearing): held by another session"
                )
            target = self.info.address or f"any {P.NAME_PREFIX}* panel"
            raise ConnectionError(
                f"panel not found ({target}) — is it powered and not connected to the phone app?"
            )
        if rssi:
            self._set(rssi=rssi[-1])
        return dev

    async def _connect(self) -> None:
        await self._dispose_stale()
        dev = await self._find()
        self._set(status="connecting")
        client = BleakClient(
            dev,
            disconnected_callback=self._on_disconnect,
            timeout=15.0,
            winrt={"use_cached_services": False},
        )
        # remember it before connecting: if the attempt times out (the supervisor cancels us), _reset_stack() must
        # still find and dispose it — a leaked WinRT session keeps the panel connected to Windows, invisible to all
        self._client = client
        await client.connect()
        char = client.services.get_characteristic(P.UUID_WRITE)
        if char is None:
            raise ConnectionError("write characteristic fa02 missing — not an iDotMatrix panel?")
        size = char.max_write_without_response_size
        if size <= 20 and sys.platform.startswith("linux"):
            # BlueZ < 5.62 (and some adapters) report the 23-byte default until asked: without this a Pi would
            # send ~25x more packets per frame. AcquireWrite reveals the negotiated MTU (bleak's own advice).
            try:
                await client._backend._acquire_mtu()  # type: ignore[attr-defined]
                size = max(size, int(client.mtu_size) - 3)
            except Exception as e:
                log.info("BlueZ MTU unknown, using %d-byte packets: %s", size, e)
        self.packet_size = max(20, size)
        try:
            await client.start_notify(P.UUID_NOTIFY, lambda _c, data: self._on_ack(bytes(data)))
        except Exception as e:  # acks are an optimisation; timeouts cover their absence
            log.info("ack notifications unavailable: %s", e)
        if not client.is_connected or self._client is not client:
            # the link dropped while we were setting it up (seen in the logs: "connected" and "write failed: not
            # connected" in the same second) — fail this attempt instead of reporting a dead link as up
            raise ConnectionError("link lost while connecting")
        self.info.address = dev.address
        self.info.name = dev.name
        self.info.mtu = self.packet_size

    def _on_disconnect(self, client: BleakClient) -> None:
        if client is not self._client:
            return  # an old session (or one we are closing on purpose): not this link's loss
        self._client = None
        self._stale.add(client)  # its GATT services are still open: dispose them before the next attempt
        if not self._stopping and self.connected:
            log.warning("panel link lost")
            self._mark_disconnected("link lost")

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            self._stale.add(client)
        await self._dispose_stale()

    async def _reset_stack(self) -> None:
        await self._disconnect()

    async def _dispose_stale(self) -> None:
        """Dispose every client we no longer use. `disconnect()` closes the services, session and device objects
        even when the link is already gone (bleak returns early only if it never connected)."""
        while self._stale:
            client = self._stale.pop()
            try:
                await asyncio.wait_for(client.disconnect(), 5.0)
            except Exception as e:
                log.debug("dispose: %s", e)

    async def _wait_for_panel(self, limit: float) -> bool:
        """Scan until the panel advertises (it does only while no central holds it)."""
        await self._dispose_stale()
        want = (self.info.address or "").lower()

        def match(d: BLEDevice, adv: AdvertisementData) -> bool:
            if want and not (sys.platform == "darwin" and MAC_RE.match(want)):
                return d.address.lower() == want
            return (adv.local_name or d.name or "").startswith(P.NAME_PREFIX)

        return await BleakScanner.find_device_by_filter(match, timeout=limit) is not None

    async def _write_packet(self, packet: bytes, response: bool) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise ConnectionError("not connected")
        await client.write_gatt_char(P.UUID_WRITE, packet, response=response)


def _windows_holds(address: str) -> bool:  # pragma: no cover — Windows only, best effort
    """Is Windows itself still connected to this panel (a zombie session)? The panel doesn't advertise then, which
    looks exactly like "off or out of range". Asks WinRT for the device's connection status (runs in a worker
    thread with its own loop); any error means "can't tell" (False)."""
    try:
        from winrt.windows.devices.bluetooth import BluetoothConnectionStatus, BluetoothLEDevice

        async def check() -> bool:
            dev = await BluetoothLEDevice.from_bluetooth_address_async(int(address.replace(":", ""), 16))
            if dev is None:
                return False
            try:
                return dev.connection_status == BluetoothConnectionStatus.CONNECTED
            finally:
                dev.close()

        return asyncio.run(check())
    except Exception:
        return False
