"""Simulated panel for development without hardware.

Behaves like the BLE backend — same scheduler, same mode switches — and models
link throughput so the studio's link stats and frame dropping look realistic.
"""

from __future__ import annotations

import asyncio

from .base import Device


class SimDevice(Device):
    kind = "sim"

    def __init__(self, bytes_per_second: float = 12_000, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self.bps = bytes_per_second
        self.writes: list[bytes] = []  # last packets, for tests
        self.info.name = "Simulator"
        self.info.address = "SIM:00:00:00:00:00"
        self.info.mtu = 244
        self.packet_size = 244
        self.packet_gap = 0.0

    async def _connect(self) -> None:
        await asyncio.sleep(0.05)

    async def _disconnect(self) -> None:
        return None

    async def _write(self, data: bytes, response: bool = False) -> None:
        # record whole logical messages (tests inspect them), timed as if packetised
        self.writes.append(data)
        del self.writes[:-64]
        await asyncio.sleep(len(data) / self.bps + (0.008 if response else 0.0))

    async def _write_packet(self, packet: bytes, response: bool) -> None:  # pragma: no cover
        await self._write(packet, response)

    async def _await_ack(self, wait: float) -> bytes | None:
        return bytes([5, 0, 0, 0, 1])  # the simulator always accepts
