"""Let the phone sleep when there is nothing to drive (ADR 0016).

The Android app used to hold a partial wake lock, a Wi-Fi lock and a multicast lock for as long as the engine ran. A
14-hour screen-off battery check on the owner's phone showed the cost: the CPU never deep-slept (`DeskDot::engine`
held 13 h 58 m of 14 h 06 m), 73,000 mDNS packets woke it through the disabled multicast filter, and most of that time
the engine wasn't even driving the panel (released, held by the laptop, or not found).

This module decides, every couple of seconds, whether the engine needs the CPU, and tells the app's `PowerGate`
(Kotlin) through a small `Host`:

* **awake** — hold the wake lock (and the Wi-Fi lock): the app is open, a hand-over or pairing is running, a LAN
  device spoke to us lately, the panel is connected and the engine streams live content, something is being written,
  or the panel was lost a short while ago and we are reconnecting.
* **asleep** — the panel is released or held elsewhere, has been missing for minutes, or runs a baked clip / its
  firmware clock with nothing live to stream. The BLE link stays up (Android keeps a GATT connection while the CPU
  sleeps); the engine wakes on Bluetooth and network events, and on an alarm `wake_in` seconds later (the next
  reconnect attempt, a clip re-bake, or a periodic look around).
* **multicast** — the hand-over setting is on and a hand-over or pairing is running. The app adds "the screen is on".

On Android the event loop's clock is CLOCK_BOOTTIME (`BootClockLoop`), so timers count the time the phone slept: a
back-off of 3 minutes is 3 wall-clock minutes, and an alarm that wakes the CPU finds the overdue timers ready to run.
Desktop and tests use the plain asyncio loop and no host (nothing changes there).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger("deskdot.keepawake")

#: s the panel may be missing before the phone stops staying awake for it (then: an alarm per retry)
MISSING_GRACE = 180.0
#: s after the last request from another device on the LAN (a hand-over, a phone controller) that we stay awake
REQUEST_GRACE = 120.0
#: s an "asleep" verdict must hold before the wake lock goes (a GIF upload finishing, a studio closing and reopening)
IDLE_GRACE = 30.0
#: s between looks around while asleep with nothing scheduled (night mode, schedules, the beacon)
NUDGE_EVERY = 900.0
#: s between evaluations (loop time)
EVERY = 2.0


@dataclass(frozen=True)
class Inputs:
    """What the decision looks at, gathered from the device, the engine and the hand-over."""

    link_enabled: bool = True
    connected: bool = False
    attempting: bool = False  # a connect attempt is running (status connecting / scanning)
    writing: bool = False  # the device is writing or has work queued
    gated: bool = False  # another DeskDot holds the panel or is taking it
    failing_for: float = 0.0  # s the current streak of failed attempts has lasted
    engine: str | None = None  # Engine.cpu_reason(): why the engine needs the CPU, or None
    handover_busy: bool = False  # a hand-over or a pairing is running
    request_age: float = math.inf  # s since another device on the LAN last called us
    app_visible: bool = False  # the DeskDot app is on screen


def decide(i: Inputs) -> tuple[bool, str]:
    """(awake, reason). Pure: tests/test_keepawake.py covers every branch."""
    if i.app_visible:
        return True, "app open"
    if i.handover_busy:
        return True, "hand-over"
    if i.request_age < REQUEST_GRACE:
        return True, "lan request"
    if i.writing:
        return True, "writing"
    if not i.link_enabled:
        return False, "released"
    if i.connected:
        return (True, i.engine) if i.engine else (False, "static")
    if i.gated:
        return False, "elsewhere"
    if i.attempting:
        return True, "connecting"
    if i.failing_for < MISSING_GRACE:
        return True, "reconnecting"
    return False, "panel missing"


class Host(Protocol):
    """The app's side (Kotlin `PowerGate`; a fake in tests)."""

    def report(self, awake: bool, multicast: bool, lan: bool, wake_in: int, reason: str) -> None: ...

    def screen_on(self) -> bool: ...

    def app_visible(self) -> bool: ...


class JavaHost:  # pragma: no cover — Android only
    """`com.deskdot.app.PowerGate` through Chaquopy."""

    def __init__(self) -> None:
        from java import jclass  # type: ignore[import-not-found]

        self._gate = jclass("com.deskdot.app.PowerGate")

    def report(self, awake: bool, multicast: bool, lan: bool, wake_in: int, reason: str) -> None:
        self._gate.report(awake, multicast, lan, wake_in, reason)

    def screen_on(self) -> bool:
        return bool(self._gate.isScreenOn())

    def app_visible(self) -> bool:
        return bool(self._gate.isAppVisible())


class BootClockLoop(asyncio.SelectorEventLoop):
    """An event loop whose clock counts deep sleep (CLOCK_BOOTTIME), so timers fire on wall-clock schedules on a phone
    that sleeps between events. uvicorn takes it as `loop="deskdot.keepawake:BootClockLoop"`."""

    _clock = getattr(time, "CLOCK_BOOTTIME", None)

    def time(self) -> float:
        if self._clock is None:  # pragma: no cover — not Linux: the monotonic clock
            return time.monotonic()
        return time.clock_gettime(self._clock)


class KeepAwake:
    """Evaluates `decide()` and reports changes to the host. One per engine, Android only."""

    def __init__(
        self,
        host: Host,
        *,
        device: Any,
        engine: Any,
        handover: Any = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.host = host
        self.device = device
        self.engine = engine
        self.handover = handover
        self._clock = clock
        self.awake = True  # the app starts awake (EngineService acquires before the engine reports)
        self.reason = "starting"
        self.multicast = False
        self._idle_since: float | None = None
        self._last_request = -math.inf
        self._sent: tuple[bool, bool, bool, str] | None = None
        self._target = 0.0  # time.time() the last reported alarm was for
        self._visible = False
        self._kick = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def now(self) -> float:
        if self._clock is not None:
            return self._clock()
        return asyncio.get_running_loop().time()

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        global _instance
        self._loop = asyncio.get_running_loop()
        self._kick = asyncio.Event()  # bound to this loop (a restarted server runs a new one)
        # A device change (the link dropping while the phone sleeps, an attempt starting) is evaluated at once: the
        # CPU may be awake only for the moment that delivered the event.
        prev = self.device._on_change

        def changed() -> None:
            prev()
            self._kick.set()

        self.device._on_change = changed
        _instance = self
        self._task = asyncio.create_task(self._run(), name="keepawake")

    async def stop(self) -> None:
        global _instance
        if _instance is self:
            _instance = None
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def kick(self) -> None:
        """Evaluate now (from any thread: the app's alarm, the screen turning on, the app opening)."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._kick.set)

    def note_request(self) -> None:
        """Another device on the LAN called us (a hand-over, a phone controller): stay awake for a while."""
        self._last_request = self.now()
        if not self.awake:
            self._kick.set()

    async def _run(self) -> None:
        while True:
            try:
                self.evaluate()
            except Exception:  # pragma: no cover — defensive: never take the engine down over power hints
                log.exception("keep-awake evaluation failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._kick.wait(), EVERY)
            self._kick.clear()

    # ------------------------------------------------------------------ the decision
    def inputs(self) -> Inputs:
        d = self.device
        info = d.info
        ho = self.handover
        gate = d.gate() if d.gate else None
        try:
            visible = bool(self.host.app_visible())
        except Exception:  # pragma: no cover — the app side is gone (shutting down)
            visible = False
        return Inputs(
            link_enabled=info.link_enabled,
            connected=d.connected,
            attempting=info.status in ("connecting", "scanning"),
            writing=d.connected and d.has_work(),
            gated=bool(gate),
            failing_for=d.failing_for(),
            engine=self.engine.cpu_reason(),
            handover_busy=bool(ho is not None and ho.busy()),
            request_age=self.now() - self._last_request,
            app_visible=visible,
        )

    def evaluate(self) -> None:
        i = self.inputs()
        if (
            i.app_visible
            and not self._visible
            and not self.device.connected
            and self.device.info.link_enabled
        ):
            # Opening the app is the user looking: the long back-off starts over (fix 4)
            self.device.retry_now()
        self._visible = i.app_visible
        want, reason = decide(i)
        now = self.now()
        if want:
            self._idle_since = None
            self.awake = True
        else:
            if self._idle_since is None:
                self._idle_since = now
            # between scheduled reconnect attempts the phone may sleep at once; otherwise let things settle first
            grace = 0.0 if reason == "panel missing" else IDLE_GRACE
            if now - self._idle_since >= grace:
                self.awake = False
        self.reason = reason
        ho = self.handover
        lan = bool(ho is not None and ho.enabled)
        self.multicast = lan and i.handover_busy
        # The alarm matters only while asleep; re-send it only when its target moves (not as it counts down).
        wake_in = 0 if self.awake else int(self.wake_in(reason))
        target = time.time() + wake_in
        key = (self.awake, self.multicast, lan, reason)
        if key != self._sent or (not self.awake and abs(target - self._target) > 10):
            self._sent = key
            self._target = target
            log.info(
                "power: %s (%s)%s",
                "awake" if self.awake else "asleep",
                reason,
                "" if self.awake else f", next look in {wake_in}s",
            )
            self.host.report(
                self.awake, self.multicast, lan, wake_in, reason if self.awake else f"asleep: {reason}"
            )

    def wake_in(self, reason: str) -> float:
        """While asleep: seconds until the app's alarm should wake the engine."""
        if reason in ("panel missing", "reconnecting", "connecting"):
            retry_at = self.device.info.retry_at
            if retry_at:
                return max(5.0, min(NUDGE_EVERY, retry_at - time.time()))
            return 60.0
        if reason == "static":
            refresh = self.engine.wake_in()
            if refresh:
                return max(30.0, min(NUDGE_EVERY, refresh))
        return NUDGE_EVERY

    def brief(self) -> dict[str, Any]:
        return {"awake": self.awake, "reason": self.reason, "multicast": self.multicast}


_instance: KeepAwake | None = None
#: the app's power host, set by android_main before the server is built (None: desktop, browser, tests)
HOST: Host | None = None


def nudge() -> None:
    """Called by the app (any thread): its alarm fired, the screen or the app's visibility changed."""
    ka = _instance
    if ka is not None:
        ka.kick()


class LanActivity:
    """ASGI middleware: a request from another device on the LAN keeps the phone awake for REQUEST_GRACE."""

    def __init__(self, app: Any, keepawake: KeepAwake) -> None:
        self.app = app
        self.keepawake = keepawake

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            from .multiplayer import is_local

            client = (scope.get("client") or (None, None))[0]
            if not is_local(client):
                self.keepawake.note_request()
        await self.app(scope, receive, send)
