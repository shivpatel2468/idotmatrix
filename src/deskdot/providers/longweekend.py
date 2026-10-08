"""Long weekends from Nager.Date (``/api/v3/LongWeekend/{year}/{country}``, keyless, CORS).

A long weekend is 3+ days off in a row, built from public holidays next to a weekend; Nager also says when one
"bridge day" of leave would join a holiday to the weekend. The country is the setting or the panel's location
(``hub.location()``). Nager answers 204 / 404 for countries it doesn't cover (India, for example): the value then
says ``supported: False`` and the app explains it.

``value = {"country", "supported", "weekends": [{start, end (ISO dates), days, bridge: bool, bridge_days: [ISO]}],
"updated"}`` — this year's and next year's, oldest first.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any

from .base import Endpoint, Provider

API = "https://date.nager.at/api/v3/LongWeekend/{year}/{cc}"


def parse_weekends(d: Any) -> list[dict[str, Any]]:
    out = []
    for w in d if isinstance(d, list) else []:
        if not isinstance(w, dict) or not w.get("startDate") or not w.get("endDate"):
            continue
        out.append(
            {
                "start": str(w["startDate"])[:10],
                "end": str(w["endDate"])[:10],
                "days": int(w.get("dayCount") or 0),
                "bridge": bool(w.get("needBridgeDay")),
                "bridge_days": [str(b)[:10] for b in w.get("bridgeDays") or []],
            }
        )
    return out


def upcoming(weekends: list[dict[str, Any]], today: dt.date, bridges: bool = True) -> list[dict[str, Any]]:
    """Weekends that haven't ended yet (an ongoing one first), optionally without the ones that need leave."""
    iso = today.isoformat()
    return sorted(
        (w for w in weekends if w["end"] >= iso and (bridges or not w["bridge"])), key=lambda w: w["start"]
    )


class LongWeekendProvider(Provider[dict[str, Any]]):
    name = "longweekend"
    endpoints = (Endpoint("Nager.Date long weekends", API.format(year=2026, cc="GB"), check=parse_weekends),)
    interval = 6 * 3600.0
    retry = 300.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.country = ""  # "" = from the location

    def want(self, country: str) -> None:
        cc = country.strip().upper()[:2]
        if cc != self.country:
            self.country = cc
            self.refresh()

    async def _year(self, year: int, cc: str) -> list[dict[str, Any]] | None:
        r = await self.hub.http.get(API.format(year=year, cc=cc))
        if r.status_code in (204, 404) or not r.content:
            return None
        r.raise_for_status()
        return parse_weekends(r.json())

    async def fetch(self) -> dict[str, Any]:
        cc = self.country
        if not cc:
            cc = str((await self.hub.location()).get("country") or "").upper()
        if not cc:
            raise RuntimeError("set a country")
        year = dt.date.today().year
        this, nxt = await asyncio.gather(self._year(year, cc), self._year(year + 1, cc))
        supported = this is not None or nxt is not None
        return {
            "country": cc,
            "supported": supported,
            "weekends": (this or []) + (nxt or []),
            "updated": time.time(),
        }
