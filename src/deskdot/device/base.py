"""Device abstraction and the latest-frame-wins scheduler shared by every backend.

Why a scheduler: BLE is slow (~5-25 KB/s in practice) and the render loop is not.
If frames were queued FIFO, the panel would fall seconds behind the studio —
the "laggy" behaviour of the old build. Instead each kind of work has a slot:

* commands (brightness, power, native modes) — FIFO, always first
* gif      — single slot, newest wins
* pixels   — merged dict {(x, y): rgb}, newest colour per LED wins
* frame    — single slot, newest wins

One writer task drains the slots in that priority order, so the panel is at
most one frame behind the engine no matter how fast frames are produced.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from . import protocol as P
from .diagnose import diagnose

log = logging.getLogger("deskdot.device")
GIF_COOLDOWN = 3.0  # s between GIF uploads; back-to-back uploads make the panel stop acking
#: s to wait after the link dropped (or was released) before the next connect attempt. The panel needs a moment to
#: start advertising again and WinRT / Android need it to tear the old GATT session down; connecting sooner is what
#: produced the "link lost -> panel not found" streaks in the logs (docs/HARDWARE_PROTOCOL.md finding 18).
REARM_DELAY = 2.5
#: consecutive failed attempts after which the supervisor runs a recovery pass (dispose the stack, wait for the
#: panel's advertisement, connect cleanly, replay a safe state) instead of retrying blindly
RECOVER_AFTER = 4
#: how long a recovery pass waits for the panel to advertise
RECOVER_SCAN = 30.0
#: how long a release waits for the item in flight (a GIF upload waits for each chunk's ack: 3 s x up to ~10)
RELEASE_DRAIN = 35.0

Status = Literal["disconnected", "scanning", "connecting", "connected", "error"]
PanelMode = Literal["unknown", "diy", "gif", "native"]


class DeviceInfo(BaseModel):
    kind: Literal["ble", "sim", "android", "web"]
    status: Status = "disconnected"
    address: str | None = None
    name: str | None = None
    mtu: int | None = None
    mode: PanelMode = "unknown"
    last_error: str | None = None
    connected_since: float | None = None
    frames_sent: int = 0
    frames_dropped: int = 0
    bytes_sent: int = 0
    last_write_ms: float = 0.0
    link_fps: float = 0.0
    last_ack: str | None = None
    power: bool = True
    link_enabled: bool = True  # False = the user released the panel from the studio (ADR 0013)
    # Connection health (docs/STUDIO_UI.md "Connection"): what went wrong and what to do about it.
    attempts: int = 0  # failed connect attempts since the last success
    retry_at: float | None = None  # epoch s of the next automatic attempt (None: not waiting)
    last_seen: float | None = None  # epoch s the panel last took a write or sent an ack
    rssi: int | None = (
        None  # signal strength (dBm) seen when the panel was last found, if the backend knows it
    )
    reason: str | None = None  # device/diagnose.py reason code for the last failure
    hint: str | None = None  # one human next step for `reason`
    recoveries: int = 0  # recovery passes run since start (stack reset + wait for the panel's advertisement)


class Device(ABC):
    """Base class: owns the work slots and the writer task. Backends implement I/O."""

    kind: Literal["ble", "sim", "android", "web"]

    #: bytes per ATT write; backends set this after connecting
    packet_size: int = 20
    #: a connect attempt (scan + GATT connect + setup) that takes longer than this is abandoned and retried
    connect_timeout: float = 45.0
    #: pause after a drop / release before the next attempt (REARM_DELAY; tests shorten it)
    rearm_delay: float = REARM_DELAY

    def __init__(
        self,
        min_frame_interval: float = 0.08,
        on_change: Callable[[], None] | None = None,
        packet_gap: float = 0.018,
    ) -> None:
        self.info = DeviceInfo(kind=self.kind)
        self.min_frame_interval = min_frame_interval
        # Verified on hardware 2026-09-24: back-to-back write-without-response packets are silently
        # dropped by the panel, so any payload larger than one packet (every photo-like frame) never
        # showed. A short gap between packets fixes it (see docs/HARDWARE_PROTOCOL.md).
        self.packet_gap = packet_gap
        self._acks: asyncio.Queue[bytes] = asyncio.Queue()
        self._frames_unacked = 0
        self._on_change = on_change or (lambda: None)
        self._commands: deque[tuple[bytes, PanelMode | None]] = deque()
        self._gif: bytes | None = None
        self._gif_ready_at = 0.0  # no GIF upload starts before this (cool-down after the previous one)
        self._frame: bytes | None = None
        self._pixels: dict[tuple[int, int], tuple[int, int, int]] = {}
        self._wake = asyncio.Event()
        self._writer: asyncio.Task[None] | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._retry = asyncio.Event()  # "Reconnect now": cuts the supervisor's back-off short
        self._stopping = False
        self._paused = (
            False  # pause_writes(): nothing more goes out (the web app hands the panel to another tab)
        )
        self._busy = False  # a write item (command, GIF upload, frame) is going out right now
        self._idle = asyncio.Event()  # set while no write item is going out
        self._idle.set()
        # what the panel should be showing, replayed after a reconnect
        self._last_visual: tuple[str, bytes] | None = None
        self._last_brightness: int | None = None
        self._last_frame_at = 0.0
        self._fps_t = 0.0
        self._dropped_at = (
            0.0  # monotonic time the link last dropped / was released (REARM_DELAY counts from it)
        )
        self._safe_replay = False  # the next connect follows a recovery: replay gently (no GIF right away)
        #: Optional coordination hook (handover.py): returns a plain-words message while another DeskDot holds the
        #: panel or holds the connect lease, so this supervisor waits instead of adding connect attempts to the air.
        self.gate: Callable[[], str | None] | None = None

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._stopping = False
        self._writer = asyncio.create_task(self._write_loop(), name="device-writer")
        self._supervisor = asyncio.create_task(self._supervise(), name="device-supervisor")

    async def stop(self) -> None:
        self._stopping = True
        for t in (self._writer, self._supervisor):
            if t:
                t.cancel()
        for t in (self._writer, self._supervisor):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        await self._disconnect()
        self._set(status="disconnected")

    async def set_link(self, enabled: bool, reason: str = "disconnected from the studio") -> bool:
        """Release / take back the panel on the user's explicit request (ADR 0013). Released, the supervisor stays
        idle — nothing reconnects until the user presses Connect, so another app can hold the panel meanwhile.

        Releasing is graceful (ADR 0015): the item in flight finishes first — a GIF upload keeps waiting for each
        chunk's ack — so the panel is never left mid-transfer for the next app; then the GATT session is closed and
        disposed. Returns False when the drain timed out (the link is closed anyway)."""
        self.info.link_enabled = enabled
        drained = True
        if not enabled:
            drained = await self._close_gracefully(reason)
        else:
            self._set(attempts=0, reason=None, hint=None, last_error=None)
            self.retry_now()
        self._on_change()
        return drained

    async def _close_gracefully(self, reason: str) -> bool:
        """Finish the write in flight, close the link, and keep queued work for the next connect."""
        drained = True
        if self.connected:
            drained = await self.pause_writes(RELEASE_DRAIN)
            if not drained:
                log.warning(
                    "release: the write in flight did not finish within %.0fs; closing anyway", RELEASE_DRAIN
                )
        await self._disconnect()
        self._mark_disconnected(reason)
        self.resume_writes()  # the writer now waits for the next connect (it checks `connected` first)
        return drained

    async def reconnect(self, only_if_down: bool = False) -> str:
        """The user's "Reconnect". Not connected: try again right now (skips the back-off wait) — never a
        disconnect. Connected: drop the link and connect again (an explicit user action, e.g. to apply a new packet
        size), unless `only_if_down`. Returns "connected", "retrying" or "reconnecting"."""
        if not self.info.link_enabled:
            await self.set_link(True)
            return "retrying"
        if self.connected:
            if only_if_down:
                return "connected"
            await self._close_gracefully("manual reconnect")
            self.retry_now()
            return "reconnecting"
        self._set(attempts=0)
        self.retry_now()
        return "retrying"

    async def pause_writes(self, limit: float = 6.0) -> bool:
        """Send nothing more after the item in flight finishes (a GIF upload always completes: rule 13), without
        touching the link. True when the writer went quiet within `limit` s. `resume_writes()` undoes it."""
        self._paused = True
        try:
            await asyncio.wait_for(self._idle.wait(), limit)
        except TimeoutError:
            return False
        return True

    def resume_writes(self) -> None:
        self._paused = False
        self._wake.set()

    def retry_now(self) -> None:
        """Wake the supervisor: the next connect attempt starts now instead of after the back-off."""
        self._retry.set()

    async def wait_connected(self, limit: float) -> bool:
        """True once the link is up (within `limit` s)."""
        if self.connected:
            return True
        try:
            await asyncio.wait_for(self._connected.wait(), limit)
        except TimeoutError:
            return False
        return self.connected

    async def wait_for_panel(self, limit: float) -> bool:
        """Wait until the panel advertises (its previous central let go). Backends that can't listen for
        advertisements return True at once and let the connect attempt find out."""
        try:
            return await self._wait_for_panel(limit)
        except Exception as e:  # a scan error is not fatal: the connect attempt reports the real problem
            log.info("waiting for the panel: %s", e)
            return False

    # ------------------------------------------------------------ public API
    @property
    def connected(self) -> bool:
        return self.info.status == "connected"

    async def flush(self, limit: float = 10.0) -> bool:
        """Wait until every queued command, GIF and frame has been written (e.g. before disconnecting)."""
        end = time.monotonic() + limit
        while time.monotonic() < end:
            if not (self._commands or self._gif is not None or self._frame is not None or self._pixels):
                await asyncio.sleep(0.4)  # the last write was popped before it finished: let it land
                return True
            await asyncio.sleep(0.05)
        return False

    def show_frame(self, png: bytes) -> None:
        """Queue a PNG frame for DIY mode. Replaces any frame not yet sent."""
        if self._frame is not None:
            self.info.frames_dropped += 1
        self._frame = png
        self._gif = None  # latest visual wins: a newer frame supersedes a queued/in-flight GIF
        self._last_visual = ("frame", png)
        self._wake.set()

    def show_gif(self, gif: bytes) -> None:
        """Upload an animation the panel will loop by itself."""
        self._gif = gif
        self._frame = None
        self._pixels.clear()
        self._last_visual = ("gif", gif)
        self._wake.set()

    def set_pixels(self, pixels: dict[tuple[int, int], tuple[int, int, int]]) -> None:
        """Paint individual LEDs (DIY mode). Cheap for small edits like brush strokes."""
        self._pixels.update(pixels)
        self._wake.set()

    def command(self, payload: bytes | list[bytes], mode: PanelMode | None = None) -> None:
        """Queue raw protocol packets. `mode` records the panel mode they leave behind."""
        packets = payload if isinstance(payload, list) else [payload]
        for i, p in enumerate(packets):
            self._commands.append((p, mode if i == len(packets) - 1 else None))
        if mode == "native":
            self._frame = None
            self._gif = None
            self._last_visual = ("cmd", b"".join(packets))
        self._wake.set()

    def set_power(self, on: bool) -> None:
        """Screen on/off. While off nothing visual is sent, so the panel stays dark."""
        self.info.power = on
        self.command(P.screen_on() if on else P.screen_off())
        if on:
            self._replay_visual()

    def set_brightness(self, percent: int) -> None:
        self._last_brightness = max(5, min(100, int(percent)))
        self.command(P.brightness(self._last_brightness))

    # ------------------------------------------------------------ backend I/O
    @abstractmethod
    async def _connect(self) -> None:
        """Open the link; set info.address/name/mtu. Raise on failure."""

    @abstractmethod
    async def _disconnect(self) -> None: ...

    @abstractmethod
    async def _write_packet(self, packet: bytes, response: bool) -> None:
        """Write one ATT packet (<= packet_size bytes)."""

    async def _wait_for_panel(self, limit: float) -> bool:
        """Backend hook: wait for the panel's advertisement. Default: can't tell, go ahead."""
        return True

    async def _reset_stack(self) -> None:
        """Backend hook (recovery, failed attempts): drop every GATT object this process may still hold. A leaked
        session keeps the panel connected to us at the OS level, so it stops advertising for everyone."""
        await self._disconnect()

    async def _write(self, data: bytes, response: bool = False) -> None:
        """Write a logical message, split into packets with a pacing gap between them."""
        n = max(20, self.packet_size)
        for i in range(0, len(data), n):
            if i and self.packet_gap:
                await asyncio.sleep(self.packet_gap)
            await self._write_packet(data[i : i + n], response)

    def _on_ack(self, data: bytes) -> None:
        """Backends call this for every notification on fa03."""
        self.info.last_ack = data.hex(" ")
        self.info.last_seen = time.time()
        self._acks.put_nowait(bytes(data))

    async def _await_ack(self, wait: float) -> bytes | None:
        try:
            return await asyncio.wait_for(self._acks.get(), wait)
        except TimeoutError:
            return None

    def _drain_acks(self) -> None:
        while not self._acks.empty():
            self._acks.get_nowait()

    # ------------------------------------------------------------- internals
    def _set(self, **kw: object) -> None:
        changed = False
        for k, v in kw.items():
            if getattr(self.info, k) != v:
                setattr(self.info, k, v)
                changed = True
        if changed:
            self._on_change()

    def _mark_disconnected(self, reason: str | None) -> None:
        if self.connected:
            self._dropped_at = time.monotonic()
        self._connected.clear()
        code, tip = (None, None) if reason in (None, "manual reconnect") else diagnose(reason, self.kind)
        self._set(
            status="disconnected",
            mode="unknown",
            connected_since=None,
            last_error=reason,
            reason=code,
            hint=tip,
        )

    def _note_failure(self, message: str, retry_in: float | None = None, status: Status = "error") -> None:
        """Publish a failed connect attempt: the raw error, its reason code, the next step and when we retry."""
        attempts = self.info.attempts + (1 if status == "error" else 0)
        code, tip = diagnose(message, self.kind, attempts)
        self._set(
            status=status,
            last_error=message,
            attempts=attempts,
            reason=code,
            hint=tip,
            retry_at=round(time.time() + retry_in, 1) if retry_in else None,
        )

    async def _wait_retry(self, delay: float) -> bool:
        """Sleep the back-off, or less if the user pressed Reconnect now. True when woken by the user."""
        if not self._retry.is_set():
            try:
                await asyncio.wait_for(self._retry.wait(), delay)
            except TimeoutError:
                return False
        self._retry.clear()
        return True

    async def _supervise(self) -> None:
        delay = 1.0
        while not self._stopping:
            if self.connected or not self.info.link_enabled:
                await asyncio.sleep(0.5 if not self.info.link_enabled else 1.0)
                continue
            held = self.gate() if self.gate else None
            if held:
                # Another DeskDot holds the panel (or is connecting to it under the lease): don't add connect
                # attempts to the air. "Use the panel here" or the holder letting go wakes us (retry_now).
                self._set(status="disconnected", reason="elsewhere", hint=held, retry_at=None)
                await self._wait_retry(3.0)
                continue
            rearm = self._dropped_at + self.rearm_delay - time.monotonic()
            if rearm > 0:  # let the panel re-advertise and the OS finish tearing the old session down
                await asyncio.sleep(rearm)
                continue
            try:
                if self.info.attempts and self.info.attempts % RECOVER_AFTER == 0:
                    await self._recover()
                self._set(status="connecting")
                try:
                    # Verified 2026-10-01: after Windows sleeps, a WinRT connect can hang forever, which left the
                    # supervisor stuck and the panel never reconnected. Abandon a hung attempt and retry.
                    await asyncio.wait_for(self._connect(), self.connect_timeout)
                except TimeoutError:
                    # bleak raises TimeoutError for its own (shorter) GATT timeout too, so don't claim a duration
                    await self._reset_stack()  # never leave a half-open session behind: it holds the panel
                    raise ConnectionError("connect timed out (the panel didn't answer)") from None
                except Exception:
                    await self._reset_stack()
                    raise
                delay = 1.0
                now = time.time()
                self._set(
                    status="connected",
                    connected_since=now,
                    last_seen=now,
                    last_error=None,
                    mode="unknown",
                    attempts=0,
                    retry_at=None,
                    reason=None,
                    hint=None,
                )
                self._connected.set()
                self._replay()
                log.info("panel connected: %s (%s), mtu=%s", self.info.name, self.info.address, self.info.mtu)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # jitter: two DeskDots that lost the panel at the same moment must not retry in lockstep
                wait = delay * random.uniform(0.8, 1.25)
                log.warning("connect failed: %s — retrying in %.0fs", e, wait)
                self._note_failure(str(e) or type(e).__name__, retry_in=wait)
                # "Reconnect now" starts the back-off over
                delay = 1.0 if await self._wait_retry(wait) else min(delay * 2, 20.0)
                self._set(retry_at=None)

    async def _recover(self) -> None:
        """Several attempts failed in a row: instead of retrying blindly (and the user power-cycling the panel),
        reset this process's Bluetooth objects, wait for the panel to advertise, then connect cleanly and replay a
        safe state."""
        n = self.info.recoveries + 1
        log.info("recovery %d: resetting the Bluetooth session and waiting for the panel to advertise", n)
        self._set(
            status="scanning",
            reason="recovering",
            recoveries=n,
            hint="Recovering the link: clearing old Bluetooth sessions and waiting for the panel to show up.",
        )
        await self._reset_stack()
        await asyncio.sleep(self.rearm_delay)
        seen = await self.wait_for_panel(RECOVER_SCAN)
        log.info("recovery %d: the panel %s", n, "is advertising" if seen else "is still not advertising")
        self._safe_replay = True

    def _replay(self) -> None:
        """After (re)connecting, restore power, brightness and whatever was on screen.

        After a recovery the panel may still be digesting an interrupted transfer, so the replay is gentle: power
        and brightness first, a GIF only after the usual cool-down (finding 16)."""
        if self._safe_replay:
            self._safe_replay = False
            self._gif_ready_at = time.monotonic() + GIF_COOLDOWN
        if self._last_brightness is not None:
            self._commands.appendleft((P.brightness(self._last_brightness), None))
        self._commands.appendleft((P.screen_on() if self.info.power else P.screen_off(), None))
        self._replay_visual()

    def _replay_visual(self) -> None:
        if self._last_visual and not (self._frame or self._gif):
            kind, data = self._last_visual
            if kind == "frame":
                self._frame = data
            elif kind == "gif":
                self._gif = data
        self._wake.set()

    async def _ensure_diy(self) -> None:
        if self.info.mode != "diy":
            await self._write(P.diy_mode(1))
            self._set(mode="diy")
            await asyncio.sleep(0.05)

    async def _write_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while not self._stopping and not self._paused:
                if not self.connected:
                    await self._connected.wait()
                    if self._paused:
                        break
                self._busy = True
                self._idle.clear()
                try:
                    if not await self._write_next():
                        break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("write failed: %s", e)
                    self._mark_disconnected(f"write failed: {e}")
                    await self._disconnect()
                finally:
                    self._busy = False
                    self._idle.set()

    async def _write_next(self) -> bool:
        """Send the highest-priority pending item. Returns False when idle."""
        t0 = time.perf_counter()
        if self._commands:
            payload, mode = self._commands.popleft()  # pop first: a bad packet must not loop forever
            await self._write(payload)
            if mode:
                self._set(mode=mode)
            self._account(len(payload), t0, frame=False)
            return True
        if not self.info.power:
            # screen is off: keep only the latest visual (in _last_visual) for when it comes back on
            self._frame = None
            self._gif = None
            self._pixels.clear()
            return False
        if self._gif is not None:
            wait = self._gif_ready_at - time.monotonic()
            if wait > 0:  # give the firmware a breather between GIF uploads (it stores each one)
                await asyncio.sleep(min(wait, 0.25))
                return True
            gif = self._gif
            # flow control: the panel acks every 4 KiB chunk (05 00 01 00 01) and the last one (... 03)
            self._drain_acks()
            self._frames_unacked = 0
            # Never abandon a GIF mid-upload: a half-sent GIF leaves the firmware ignoring the next one (verified
            # on hardware 2026-09-27 — blank panel). Finish it, then the newest visual goes out next (latest wins).
            for chunk in P.gif_upload(gif):
                await self._write(chunk)
                if await self._await_ack(3.0) is None:
                    log.warning("no ack for a GIF chunk; continuing")
            if self._gif is gif:
                self._gif = None
            self._gif_ready_at = time.monotonic() + GIF_COOLDOWN
            self._set(mode="gif")
            self._account(len(gif), t0, frame=True)
            return True
        if self._pixels:
            await self._ensure_diy()
            batch, self._pixels = self._pixels, {}
            for (x, y), (r, g, b) in batch.items():
                await self._write(P.pixel(x, y, r, g, b))
            self._account(10 * len(batch), t0, frame=False)
            return True
        if self._frame is not None:
            wait = self.min_frame_interval - (time.monotonic() - self._last_frame_at)
            if wait > 0:
                await asyncio.sleep(wait)
                return True  # re-evaluate: a command may have arrived meanwhile
            png, self._frame = self._frame, None
            await self._ensure_diy()
            payload = P.image_upload(png)
            # Flow control: drain incoming ACKs non-blockingly to maintain a steady cadence
            while not self._acks.empty():
                self._acks.get_nowait()
                self._frames_unacked = max(0, self._frames_unacked - 1)

            # Only throttle if the panel is more than 1 frame behind
            if self._frames_unacked >= 2:
                if await self._await_ack(0.12) is not None:
                    self._frames_unacked = max(0, self._frames_unacked - 1)
                else:
                    self._frames_unacked = 0  # ack lost; don't stall forever
            await self._write(payload)
            self._frames_unacked += 1
            self._last_frame_at = time.monotonic()
            self._account(len(payload), t0, frame=True)
            return True
        return False

    def _account(self, nbytes: int, t0: float, frame: bool) -> None:
        dt = time.perf_counter() - t0
        self.info.bytes_sent += nbytes
        self.info.last_seen = time.time()
        self.info.last_write_ms = round(dt * 1000, 1)
        if frame:
            self.info.frames_sent += 1
            now = time.monotonic()
            inst = 1.0 / max(1e-3, now - self._fps_t) if self._fps_t else 0.0
            self._fps_t = now
            self.info.link_fps = round(0.8 * self.info.link_fps + 0.2 * min(inst, 60), 2)
