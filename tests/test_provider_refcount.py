"""R-PROV-8: a provider polls only while held. `acquire()` starts polling, the last `release()` stops it once the
30 s linger has passed, and a new `acquire()` inside the linger keeps the same poll going.

The provider's clock (`time.monotonic`) is faked and its waits are short, so the 30 s linger takes milliseconds.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deskdot.providers import base
from deskdot.providers.base import Hub, Provider


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return 1_700_000_000.0 + self.t


class Counter(Provider[int]):
    name = "counter"
    interval = 0.01  # real seconds between polls (the linger is measured on the fake clock)
    retry = 0.01

    def __init__(self, hub: Hub) -> None:
        super().__init__(hub)
        self.fetches = 0

    async def fetch(self) -> int:
        self.fetches += 1
        return self.fetches


class _Hub:
    def on_change(self, _name: str) -> None:
        pass


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    clk = FakeClock()
    monkeypatch.setattr(base, "time", clk)
    return clk


async def _polls(p: Counter, n: int = 3) -> None:
    """Wait until the provider has fetched `n` more times."""
    start = p.fetches
    for _ in range(500):
        if p.fetches >= start + n:
            return
        await asyncio.sleep(0.002)
    raise AssertionError(f"provider stopped polling at {p.fetches} fetches")


async def _settle() -> None:
    await asyncio.sleep(0.05)


async def test_polling_starts_on_first_acquire_and_stops_after_the_linger(clock: FakeClock) -> None:
    p = Counter(_Hub())  # type: ignore[arg-type]
    await _settle()
    assert p.fetches == 0 and p._task is None, "nothing polls before anyone holds the provider"

    p.acquire()
    await _polls(p)
    assert p.snapshot()["active"] is True
    first_task = p._task

    p.acquire()  # a second holder shares the same poll
    assert p._task is first_task
    p.release()
    await _polls(p)  # one holder left: still polling

    p.release()  # last holder gone: the linger starts
    assert p.snapshot()["active"] is False
    await _settle()
    clock.t += 29  # inside the linger the task is still alive (a fast app switch doesn't refetch)
    await _settle()
    assert p._task is not None and not p._task.done()

    clock.t += 2  # past 30 s: the loop ends and polling stops
    await _settle()
    assert p._task.done()
    stopped_at = p.fetches
    await _settle()
    assert p.fetches == stopped_at, "a released provider kept fetching after the linger"
    assert p.value == stopped_at, "the last good value is kept after polling stops"


async def test_acquire_inside_the_linger_keeps_the_same_poll(clock: FakeClock) -> None:
    p = Counter(_Hub())  # type: ignore[arg-type]
    p.acquire()
    await _polls(p)
    task = p._task
    p.release()
    await _settle()
    clock.t += 20
    await _settle()
    p.acquire()  # back within the linger: no new task, polling continues and the idle timer resets
    assert p._task is task
    await _polls(p)
    clock.t += 40
    await _polls(p)
    assert not task.done()
    p.release()
    await _settle()
    clock.t += 31
    await _settle()
    assert task.done()


async def test_acquire_after_the_linger_starts_polling_again(clock: FakeClock) -> None:
    p = Counter(_Hub())  # type: ignore[arg-type]
    p.acquire()
    await _polls(p)
    p.release()
    await _settle()
    clock.t += 31
    await _settle()
    assert p._task is not None and p._task.done()
    old: Any = p._task
    p.acquire()
    assert p._task is not old
    await _polls(p)
    p.release()
    await p.stop()
