"""Providers fetch data in the background so apps never wait on I/O.

A provider only polls while something holds a reference to it (an app that
is on screen, or a studio request). Values are cached; `value` is None until
the first successful fetch and keeps the last good value after an error.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

import httpx

if TYPE_CHECKING:
    from ..config import Store

log = logging.getLogger("dotdeck.providers")
T = TypeVar("T")


class Hub:
    """Shared services handed to providers."""

    def __init__(self, store: Store, on_change: Callable[[str], None]) -> None:
        self.store = store
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(6.0, connect=4.0),
            headers={"User-Agent": "DotDeck/3 (+https://github.com/)"},
            follow_redirects=True,
        )
        self.on_change = on_change
        self.providers: dict[str, Provider[Any]] = {}
        self.listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._geo: tuple[str, float, dict[str, Any]] | None = None  # (settings key, time, result)
        self._geo_lock = asyncio.Lock()

    async def location(self) -> dict[str, Any]:
        """Where the panel is: `{"city", "lat", "lon", "country"}` (ISO-2 country code, may be "").

        Order: explicit lat/lon in settings → the settings city geocoded (Open-Meteo) → IP geolocation.
        Cached for 6 h (and re-resolved whenever the location setting changes). Every location-aware
        provider (weather, flights, air quality, earthquakes, holidays…) must use this.
        """
        loc = self.store.get("location") or {}
        key = repr(sorted(loc.items()))
        async with self._geo_lock:
            if self._geo and self._geo[0] == key and time.time() - self._geo[1] < 6 * 3600:
                return self._geo[2]
            res = await self._resolve_location(loc)
            self._geo = (key, time.time(), res)
            return res

    async def _resolve_location(self, loc: dict[str, Any]) -> dict[str, Any]:
        if loc.get("lat") is not None and loc.get("lon") is not None:
            return {
                "city": loc.get("city") or "HOME",
                "lat": float(loc["lat"]),
                "lon": float(loc["lon"]),
                "country": str(loc.get("country") or ""),
            }
        if loc.get("city"):
            r = await self.http.get(
                "https://geocoding-api.open-meteo.com/v1/search", params={"name": loc["city"], "count": 1}
            )
            r.raise_for_status()
            hits = r.json().get("results") or []
            if hits:
                h = hits[0]
                return {
                    "city": h["name"],
                    "lat": float(h["latitude"]),
                    "lon": float(h["longitude"]),
                    "country": str(h.get("country_code") or "").upper(),
                }
        r = await self.http.get("http://ip-api.com/json/?fields=status,city,lat,lon,countryCode")
        r.raise_for_status()
        d = r.json()
        if d.get("status") != "success":
            raise RuntimeError("IP geolocation failed; set a city in Settings")
        return {
            "city": d["city"],
            "lat": float(d["lat"]),
            "lon": float(d["lon"]),
            "country": d.get("countryCode") or "",
        }

    def emit(self, event: str, data: dict[str, Any]) -> None:
        """Broadcast a discrete event (e.g. a goal) to the engine."""
        for cb in list(self.listeners):
            try:
                cb(event, data)
            except Exception:
                log.exception("event listener failed for %s", event)

    def get(self, name: str) -> Provider[Any]:
        return self.providers[name]

    async def close(self) -> None:
        for p in self.providers.values():
            await p.stop()
        await self.http.aclose()


class Provider(Generic[T]):
    name: ClassVar[str]
    interval: ClassVar[float] = 60.0  # seconds between fetches
    retry: ClassVar[float] = 15.0  # seconds after a failure

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.value: T | None = None
        self.updated: float = 0.0
        self.error: str | None = None
        self._refs = 0
        self._task: asyncio.Task[None] | None = None
        self._kick = asyncio.Event()

    # --------------------------------------------------------------- usage
    def acquire(self) -> None:
        self._refs += 1
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name=f"provider-{self.name}")

    def release(self) -> None:
        self._refs = max(0, self._refs - 1)

    def refresh(self) -> None:
        """Fetch as soon as possible (e.g. after its settings changed)."""
        self._kick.set()

    @property
    def age(self) -> float:
        return time.time() - self.updated if self.updated else float("inf")

    def next_interval(self) -> float:
        return self.interval

    def announce(self, old: T | None, new: T) -> bool:
        """Whether a fetch result should push a studio state update (high-rate sources say no)."""
        return True

    async def fetch(self) -> T:
        raise NotImplementedError

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def snapshot(self) -> dict[str, Any]:
        return {"updated": self.updated or None, "error": self.error, "active": self._refs > 0}

    # ------------------------------------------------------------ internals
    async def _loop(self) -> None:
        # linger a little after the last release so fast app switches don't refetch
        idle_since: float | None = None
        while True:
            if self._refs == 0:
                idle_since = idle_since or time.monotonic()
                if time.monotonic() - idle_since > 30:
                    return
            else:
                idle_since = None
            wait = self.retry
            try:
                if self._refs or self.value is None:
                    old, new = self.value, await self.fetch()
                    self.value = new
                    self.updated = time.time()
                    had_error, self.error = self.error, None
                    if had_error or self.announce(old, new):
                        self.hub.on_change(self.name)
                wait = self.next_interval()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"[:200]
                log.info("provider %s: %s", self.name, self.error)
                self.hub.on_change(self.name)
            self._kick.clear()
            try:
                await asyncio.wait_for(self._kick.wait(), timeout=wait)
            except TimeoutError:
                pass
