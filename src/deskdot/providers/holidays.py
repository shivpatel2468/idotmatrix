"""Upcoming public holidays for a country, from three keyless sources (tried in order).

1. Nager.Date ``/api/v3/NextPublicHolidays/{CC}`` — clean JSON for ~120 countries, the next 365 days. It answers
   HTTP 204 (no body) for countries it doesn't cover, India among them.
2. Google Calendar's public holiday ICS feeds (``{lang}.{name}#holiday@group.v.calendar.google.com``) — every
   country, several years, each event tagged "Public holiday" or "Observance". Parsed here (no dependency).
3. caldays.com ``/api/holidays/{cc}`` (CC BY 4.0) — the current calendar year only; last resort.

``value = {CC: {"country", "source", "holidays": [{"date": "YYYY-MM-DD", "name", "public": bool}], "fetched"}}``;
holidays are sorted by date and start at today (observances are included, flagged ``public = False``).
Apps call ``want(cc)``; an empty code means "the panel's location country".
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import time
from typing import Any
from urllib.parse import quote

from .base import Provider

NAGER = "https://date.nager.at/api/v3/NextPublicHolidays/{cc}"
GOOGLE = (
    "https://calendar.google.com/calendar/ical/{cid}%23holiday%40group.v.calendar.google.com/public/basic.ics"
)
CALDAYS = "https://caldays.com/api/holidays/{cc}"

#: Google's older calendar ids; any other country uses ``en.{cc}`` (verified live for the ones below).
GOOGLE_IDS: dict[str, str] = {
    "AU": "australian",
    "AT": "austrian",
    "BR": "brazilian",
    "BG": "bulgarian",
    "CA": "canadian",
    "CN": "china",
    "HR": "croatian",
    "CZ": "czech",
    "DK": "danish",
    "NL": "dutch",
    "FI": "finnish",
    "FR": "french",
    "DE": "german",
    "GR": "greek",
    "HK": "hong_kong",
    "HU": "hungarian",
    "IN": "indian",
    "ID": "indonesian",
    "IE": "irish",
    "IL": "jewish",
    "IT": "italian",
    "JP": "japanese",
    "LT": "lithuanian",
    "LV": "latvian",
    "MY": "malaysia",
    "MX": "mexican",
    "NZ": "new_zealand",
    "NO": "norwegian",
    "PH": "philippines",
    "PL": "polish",
    "PT": "portuguese",
    "RO": "romanian",
    "RU": "russian",
    "SA": "saudiarabian",
    "SG": "singapore",
    "SK": "slovak",
    "SI": "slovenian",
    "ZA": "sa",
    "KR": "south_korea",
    "ES": "spain",
    "SE": "swedish",
    "TW": "taiwan",
    "TR": "turkish",
    "GB": "uk",
    "UA": "ukrainian",
    "US": "usa",
    "VN": "vietnamese",
}
CC_RE = re.compile(r"^[A-Z]{2}$")
MAX_COUNTRIES = 4
HORIZON_DAYS = 400


def normalize_cc(raw: str) -> str:
    s = (raw or "").strip().upper()
    return s if CC_RE.match(s) else ""


def google_calendar_id(cc: str) -> str:
    return f"en.{GOOGLE_IDS.get(cc, cc.lower())}"


def _clean(items: list[dict[str, Any]], today: dt.date) -> list[dict[str, Any]]:
    """Sort, drop the past and far future, merge same-day duplicates (public wins)."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    end = today + dt.timedelta(days=HORIZON_DAYS)
    for h in items:
        try:
            d = dt.date.fromisoformat(h["date"])
        except (KeyError, ValueError):
            continue
        name = " ".join(str(h.get("name") or "").split())
        if not name or d < today or d > end:
            continue
        k = (h["date"], name.lower())
        if k in seen:
            seen[k]["public"] = seen[k]["public"] or bool(h.get("public", True))
            continue
        seen[k] = {"date": h["date"], "name": name, "public": bool(h.get("public", True))}
    return sorted(seen.values(), key=lambda h: (h["date"], not h["public"], h["name"]))


# ---------------------------------------------------------------------------- parsers
def parse_nager(payload: Any, today: dt.date) -> list[dict[str, Any]]:
    """Nager.Date NextPublicHolidays JSON -> holidays (English name; regional-only days flagged non-public)."""
    items = []
    for h in payload or []:
        if not isinstance(h, dict):
            continue
        types = h.get("types") or ["Public"]
        items.append(
            {
                "date": str(h.get("date") or ""),
                "name": str(h.get("name") or h.get("localName") or ""),
                "public": "Public" in types and h.get("global", True) is not False,
            }
        )
    return _clean(items, today)


def _ics_unfold(text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", text)


def _ics_unescape(v: str) -> str:
    return (
        v.replace("\\n", " ")
        .replace("\\N", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def parse_ics(text: str, today: dt.date) -> list[dict[str, Any]]:
    """An iCalendar (RFC 5545) holiday feed -> holidays. Handles line folding, DATE and DATE-TIME starts.

    Google tags each event's DESCRIPTION "Public holiday" or "Observance"; other feeds count as public.
    """
    items = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", _ics_unfold(text), re.S):
        props: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            props.setdefault(key.split(";", 1)[0].upper(), val.strip())
        m = re.match(r"(\d{4})(\d{2})(\d{2})", props.get("DTSTART", ""))
        if not m or props.get("STATUS", "CONFIRMED").upper() == "CANCELLED":
            continue
        desc = _ics_unescape(props.get("DESCRIPTION", "")).lower()
        items.append(
            {
                "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                "name": _ics_unescape(props.get("SUMMARY", "")),
                "public": not desc.startswith("observance"),
            }
        )
    return _clean(items, today)


def parse_caldays(payload: dict[str, Any], today: dt.date) -> list[dict[str, Any]]:
    items = [
        {"date": str(h.get("date") or ""), "name": str(h.get("name") or ""), "public": True}
        for h in payload.get("holidays") or []
        if isinstance(h, dict)
    ]
    return _clean(items, today)


# ---------------------------------------------------------------------------- provider
class HolidaysProvider(Provider[dict[str, Any]]):
    name = "holidays"
    interval = 6 * 3600.0
    retry = 120.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.countries: list[str] = []  # "" = the location's country

    def want(self, cc: str = "") -> None:
        cc = normalize_cc(cc)
        new = cc not in self.countries
        if not new:
            self.countries.remove(cc)
        self.countries.append(cc)
        del self.countries[:-MAX_COUNTRIES]
        if new:
            self.refresh()

    def announce(self, old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
        def key(d: dict[str, Any] | None) -> Any:
            return {k: (v["source"], [h["date"] for h in v["holidays"][:10]]) for k, v in (d or {}).items()}

        return key(old) != key(new)

    async def _nager(self, cc: str, today: dt.date) -> list[dict[str, Any]]:
        r = await self.hub.http.get(NAGER.format(cc=cc))
        if r.status_code == 204 or not r.content:
            return []
        r.raise_for_status()
        return parse_nager(r.json(), today)

    async def _google(self, cc: str, today: dt.date) -> list[dict[str, Any]]:
        url = GOOGLE.format(cid=quote(google_calendar_id(cc), safe="._"))
        r = await self.hub.http.get(url, timeout=15.0)
        r.raise_for_status()
        if "BEGIN:VCALENDAR" not in r.text[:200]:
            return []
        return await asyncio.to_thread(parse_ics, r.text, today)

    async def _caldays(self, cc: str, today: dt.date) -> list[dict[str, Any]]:
        r = await self.hub.http.get(CALDAYS.format(cc=cc.lower()))
        if r.status_code == 404:
            return []
        r.raise_for_status()
        return parse_caldays(r.json(), today)

    async def lookup(self, cc: str) -> dict[str, Any]:
        today = dt.date.today()
        errors: list[str] = []
        for source, fn in (("nager", self._nager), ("google", self._google), ("caldays", self._caldays)):
            try:
                hols = await fn(cc, today)
            except Exception as e:  # the next source may still answer
                errors.append(f"{source}: {type(e).__name__}")
                continue
            if hols:
                return {"country": cc, "source": source, "holidays": hols, "fetched": time.time()}
        raise RuntimeError(f"no holidays for {cc}" + (f" ({'; '.join(errors)})" if errors else ""))

    async def fetch(self) -> dict[str, Any]:
        wanted = list(self.countries) or [""]
        loc_cc = ""
        if "" in wanted:
            try:
                loc_cc = normalize_cc(str((await self.hub.location()).get("country") or ""))
            except Exception:
                loc_cc = ""
        codes = {w: (w or loc_cc) for w in wanted}
        todo = sorted({c for c in codes.values() if c})
        if not todo:
            raise RuntimeError("no country: set one in the app or a location in Settings")
        results = await asyncio.gather(*(self.lookup(c) for c in todo), return_exceptions=True)
        out: dict[str, Any] = {}
        errors = []
        for c, res in zip(todo, results, strict=True):
            if isinstance(res, BaseException):
                errors.append(str(res))
                old = (self.value or {}).get(c)
                if old:
                    out[c] = old
            else:
                out[c] = res
        if not out:
            raise RuntimeError("; ".join(errors)[:200])
        if "" in codes and loc_cc in out:
            out[""] = out[loc_cc]  # apps asking for "the location's country" read key ""
        return out
