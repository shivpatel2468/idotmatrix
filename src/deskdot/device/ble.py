"""Bluetooth LE backend (bleak). One persistent GATT session for the app's lifetime.

The panel shows its blinking pairing icon whenever the link drops, so this
backend never disconnects voluntarily; it reconnects with backoff when the
link is lost (see Device._supervise).
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

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

    async def _find(self) -> BLEDevice:
        self._set(status="scanning")
        if self.info.address and sys.platform == "darwin" and MAC_RE.match(self.info.address):
            # CoreBluetooth never exposes MAC addresses (devices get per-host UUIDs), so on macOS a
            # configured MAC can't be used: find the panel by its advertised IDM- name instead.
            log.info(
                "macOS: ignoring MAC %s, scanning for an %s* panel by name", self.info.address, P.NAME_PREFIX
            )
            self.info.address = None
        if self.info.address:
            dev = await BleakScanner.find_device_by_address(self.info.address, timeout=10.0)
        else:
            dev = await BleakScanner.find_device_by_filter(
                lambda d, adv: (adv.local_name or d.name or "").startswith(P.NAME_PREFIX), timeout=10.0
            )
        if dev is None:
            target = self.info.address or f"any {P.NAME_PREFIX}* panel"
            raise ConnectionError(
                f"panel not found ({target}) — is it powered and not connected to the phone app?"
            )
        return dev

    async def _connect(self) -> None:
        dev = await self._find()
        self._set(status="connecting")
        client = BleakClient(dev, disconnected_callback=self._on_disconnect, timeout=15.0)
        await client.connect()
        char = client.services.get_characteristic(P.UUID_WRITE)
        if char is None:
            await client.disconnect()
            raise ConnectionError("write characteristic fa02 missing — not an iDotMatrix panel?")
        self._client = client
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
        self.info.address = dev.address
        self.info.name = dev.name
        self.info.mtu = self.packet_size

    def _on_disconnect(self, _client: BleakClient) -> None:
        if not self._stopping:
            log.warning("panel link lost")
            self._mark_disconnected("link lost")

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None and client.is_connected:
            try:
                await asyncio.wait_for(client.disconnect(), 5.0)
            except Exception as e:
                log.debug("disconnect: %s", e)

    async def _write_packet(self, packet: bytes, response: bool) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise ConnectionError("not connected")
        await client.write_gatt_char(P.UUID_WRITE, packet, response=response)
