"""Calendar: upcoming events from secret iCalendar (ICS) URLs — Google, Outlook/Office 365, iCloud, Fastmail…

The iCalendar parser is written here (RFC 5545 subset, no library):

* line unfolding, property parameters (quoted values too), TEXT unescaping (``\\n \\, \\; \\\\``);
* ``DTSTART``/``DTEND``/``DURATION`` as UTC (``Z``), ``TZID=`` local time, floating local time or ``VALUE=DATE``;
* time zones: ``zoneinfo`` when the machine has tz data, else the file's own ``VTIMEZONE`` (STANDARD/DAYLIGHT
  with yearly ``BYMONTH``/``BYDAY`` rules), else the built-in table in `providers.tzlite` (IANA and Windows
  names), else this machine's local time;
* ``RRULE``: ``FREQ=DAILY|WEEKLY|MONTHLY|YEARLY`` with ``INTERVAL``, ``BYDAY`` (daily/weekly), ``COUNT`` and
  ``UNTIL``; ``EXDATE`` (lists, TZID, dates); ``RECURRENCE-ID`` overrides; ``STATUS:CANCELLED`` is dropped.

Occurrences are expanded in the event's own wall-clock time and converted to UTC one by one, so a weekly 09:00
meeting stays at 09:00 across DST changes. URLs are secrets: they never appear in values or errors.
"""

from __future__ import annotations

import asyncio
import calendar as cal
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from . import tzlite
from .base import Provider

Offset = Callable[[float], int]
DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
MAX_INSTANCES = 5000


# ------------------------------------------------------------------------------------------ lexing
def unfold(text: str) -> list[str]:
    """RFC 5545 §3.1: a CRLF followed by a space or tab continues the previous line."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw.strip():
            lines.append(raw)
    return lines


def parse_line(line: str) -> tuple[str, dict[str, str], str]:
    """'DTSTART;TZID="Europe/Paris":2026…' -> ('DTSTART', {'TZID': 'Europe/Paris'}, '2026…')."""
    in_q = False
    split = len(line)
    for i, ch in enumerate(line):
        if ch == '"':
            in_q = not in_q
        elif ch == ":" and not in_q:
            split = i
            break
    head, value = line[:split], line[split + 1 :]
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', head)
    name = parts[0].upper() if parts else ""
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return name, params, value


def unescape(v: str) -> str:
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def components(lines: list[str]) -> list[dict[str, Any]]:
    """Nested BEGIN/END blocks -> [{'type', 'props': [(name, params, value)], 'children': [...]}]."""
    root: dict[str, Any] = {"type": "ROOT", "props": [], "children": []}
    stack = [root]
    for line in lines:
        name, params, value = parse_line(line)
        if name == "BEGIN":
            node = {"type": value.upper(), "props": [], "children": []}
            stack[-1]["children"].append(node)
            stack.append(node)
        elif name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1]["props"].append((name, params, value))
    return root["children"]


def _prop(c: dict[str, Any], name: str) -> tuple[dict[str, str], str] | None:
    for n, p, v in c["props"]:
        if n == name:
            return p, v
    return None


def _props(c: dict[str, Any], name: str) -> list[tuple[dict[str, str], str]]:
    return [(p, v) for n, p, v in c["props"] if n == name]


# ------------------------------------------------------------------------------------------ values
def parse_offset(s: str) -> int:
    """'+0530' / '-0800' / '+013000' -> seconds east of UTC."""
    sign = -1 if s.startswith("-") else 1
    s = s.lstrip("+-")
    h, m, sec = int(s[0:2]), int(s[2:4] or 0), int(s[4:6] or 0)
    return sign * (h * 3600 + m * 60 + sec)


def parse_duration(s: str) -> timedelta:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", s.strip())
    if not m:
        raise ValueError(f"bad duration {s!r}")
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, se = (int(g or 0) for g in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=se)


def parse_wall(v: str) -> tuple[datetime, bool, bool]:
    """(naive wall datetime, is_date, is_utc)."""
    v = v.strip()
    if len(v) == 8:
        return datetime.strptime(v, "%Y%m%d"), True, False
    utc = v.endswith("Z")
    return datetime.strptime(v.rstrip("Z")[:15], "%Y%m%dT%H%M%S"), False, utc


def _nth_weekday(year: int, month: int, wd: int, n: int) -> int:
    days = cal.monthrange(year, month)[1]
    hits = [d for d in range(1, days + 1) if cal.weekday(year, month, d) == wd]
    if not hits:
        return 1
    if n < 0:
        return hits[max(-len(hits), n)]
    return hits[min(len(hits), max(1, n)) - 1]


def vtimezone_offset(tz: dict[str, Any]) -> Offset:
    """An offset function from a VTIMEZONE's STANDARD/DAYLIGHT sub-components (yearly BYMONTH/BYDAY rules)."""
    rules = []
    for sub in tz["children"]:
        if sub["type"] not in ("STANDARD", "DAYLIGHT"):
            continue
        start = _prop(sub, "DTSTART")
        to = _prop(sub, "TZOFFSETTO")
        frm = _prop(sub, "TZOFFSETFROM")
        if not start or not to:
            continue
        wall, _, _ = parse_wall(start[1])
        rr = _prop(sub, "RRULE")
        rule = dict(kv.split("=", 1) for kv in rr[1].split(";") if "=" in kv) if rr else {}
        rules.append((wall, parse_offset(to[1]), parse_offset(frm[1]) if frm else parse_offset(to[1]), rule))

    def onsets(year: int) -> list[tuple[float, int]]:
        out = []
        for wall, to, frm, rule in rules:
            if rule.get("FREQ") == "YEARLY" and "BYMONTH" in rule and "BYDAY" in rule:
                m = re.fullmatch(r"([+-]?\d*)([A-Z]{2})", rule["BYDAY"].split(",")[0])
                if not m:
                    continue
                n = int(m.group(1) or 1)
                month = int(rule["BYMONTH"].split(",")[0])
                day = _nth_weekday(year, month, DAYS.index(m.group(2)), n)
                local = datetime(year, month, day, wall.hour, wall.minute, wall.second)
            elif year == wall.year:
                local = wall
            else:
                continue
            out.append((local.replace(tzinfo=UTC).timestamp() - frm, to))
        return out

    def offset(ts: float) -> int:
        y = datetime.fromtimestamp(ts, tz=UTC).year
        cands = [o for yy in (y - 1, y) for o in onsets(yy) if o[0] <= ts]
        if cands:
            return max(cands)[1]
        return rules[0][1] if rules else 0

    return offset


def local_offset_fn(ts: float) -> int:
    off = datetime.fromtimestamp(ts).astimezone().utcoffset()
    return int(off.total_seconds()) if off else 0


class Resolver:
    """TZID -> offset function, preferring zoneinfo, then the file's VTIMEZONEs, then the built-in table."""

    def __init__(self, vtimezones: dict[str, dict[str, Any]]) -> None:
        self.vtz = vtimezones
        self.cache: dict[str, Offset] = {}

    def __call__(self, tzid: str | None) -> Offset:
        if not tzid:
            return local_offset_fn
        if tzid in self.cache:
            return self.cache[tzid]
        fn: Offset | None = None
        name = tzid.strip('"')
        if tzlite.has_tzdata():
            fn = tzlite.resolve(name)
        if fn is None and name in self.vtz:
            fn = vtimezone_offset(self.vtz[name])
        if fn is None:
            fn = tzlite.resolve(name)
        self.cache[tzid] = fn or local_offset_fn
        return self.cache[tzid]


def to_ts(wall: datetime, is_date: bool, is_utc: bool, tzfn: Offset) -> float:
    if is_utc:
        return wall.replace(tzinfo=UTC).timestamp()
    if is_date:
        return tzlite.local_to_utc(wall, local_offset_fn)
    return tzlite.local_to_utc(wall, tzfn)


# ------------------------------------------------------------------------------------------ recurrence
def expand_rrule(
    dtstart: datetime, rule: dict[str, str], until_ts: float | None, window_end: datetime
) -> list[datetime]:
    """Wall-clock occurrence starts (including dtstart) up to `window_end` (wall), honouring COUNT."""
    freq = rule.get("FREQ", "")
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT") else None
    byday = [re.sub(r"^[+-]?\d+", "", d) for d in rule.get("BYDAY", "").split(",") if d]
    bydays = sorted(DAYS.index(d) for d in byday if d in DAYS)
    out: list[datetime] = []
    n = 0

    def emit(dt: datetime) -> bool:
        """False = stop."""
        nonlocal n
        if dt < dtstart:
            return True
        if count is not None and n >= count:
            return False
        if until_ts is not None and dt.replace(tzinfo=UTC).timestamp() > until_ts + 86400 * 2:
            return False  # rough wall-time guard; exact UNTIL check happens after conversion
        n += 1
        if dt > window_end:
            return False
        out.append(dt)
        return True

    if freq == "DAILY":
        d = dtstart
        for _ in range(MAX_INSTANCES):
            if (not bydays or d.weekday() in bydays) and not emit(d):
                break
            d += timedelta(days=interval)
    elif freq == "WEEKLY":
        days = bydays or [dtstart.weekday()]
        week0 = dtstart - timedelta(days=dtstart.weekday())
        stop = False
        for k in range(MAX_INSTANCES):
            base = week0 + timedelta(weeks=k * interval)
            for wd in days:
                if not emit(base + timedelta(days=wd)):
                    stop = True
                    break
            if stop:
                break
    elif freq == "MONTHLY":
        for k in range(MAX_INSTANCES // 10):
            y, m = divmod(dtstart.month - 1 + k * interval, 12)
            y += dtstart.year
            if dtstart.day > cal.monthrange(y, m + 1)[1]:
                continue
            if not emit(dtstart.replace(year=y, month=m + 1)):
                break
    elif freq == "YEARLY":
        for k in range(200):
            try:
                d = dtstart.replace(year=dtstart.year + k * interval)
            except ValueError:
                continue
            if not emit(d):
                break
    else:
        emit(dtstart)
    return out


def events_between(text: str, start_ts: float, end_ts: float, cal_index: int = 0) -> list[dict[str, Any]]:
    """Every event instance overlapping [start_ts, end_ts] in one ICS document."""
    comps = components(unfold(text))
    vcal = next((c for c in comps if c["type"] == "VCALENDAR"), {"children": comps})
    vtz = {}
    for c in vcal["children"]:
        if c["type"] == "VTIMEZONE" and _prop(c, "TZID"):
            vtz[_prop(c, "TZID")[1]] = c  # type: ignore[index]
    resolve = Resolver(vtz)
    vevents = [c for c in vcal["children"] if c["type"] == "VEVENT"]
    overrides: dict[tuple[str, float], dict[str, Any]] = {}
    for ev in vevents:
        rid = _prop(ev, "RECURRENCE-ID")
        uid = _prop(ev, "UID")
        if rid and uid:
            w, is_date, utc = parse_wall(rid[1])
            overrides[(uid[1], to_ts(w, is_date, utc, resolve(rid[0].get("TZID"))))] = ev
    out = []
    for ev in vevents:
        st = _prop(ev, "DTSTART")
        if not st:
            continue
        status = _prop(ev, "STATUS")
        if status and status[1].upper() == "CANCELLED":
            continue
        tzfn = resolve(st[0].get("TZID"))
        wall0, is_date, utc = parse_wall(st[1])
        if st[0].get("VALUE") == "DATE":
            is_date = True
        en = _prop(ev, "DTEND")
        du = _prop(ev, "DURATION")
        if en:
            wend, _, eutc = parse_wall(en[1])
            end_tzfn = resolve(en[0].get("TZID")) if en[0].get("TZID") else tzfn
            length = to_ts(wend, is_date, eutc, end_tzfn) - to_ts(wall0, is_date, utc, tzfn)
        elif du:
            length = parse_duration(du[1]).total_seconds()
        else:
            length = 86400.0 if is_date else 0.0
        summary = _prop(ev, "SUMMARY")
        loc = _prop(ev, "LOCATION")
        uid = _prop(ev, "UID")
        title = unescape(summary[1]).strip() if summary else "(no title)"
        exdates: set[int] = set()
        for p, v in _props(ev, "EXDATE"):
            for item in v.split(","):
                if item.strip():
                    w, dd, u = parse_wall(item)
                    exdates.add(
                        round(to_ts(w, dd or is_date, u, resolve(p.get("TZID")) if p.get("TZID") else tzfn))
                    )
        rr = _prop(ev, "RRULE")
        if rr and not _prop(ev, "RECURRENCE-ID"):
            rule = dict(kv.split("=", 1) for kv in rr[1].split(";") if "=" in kv)
            until_ts = None
            if rule.get("UNTIL"):
                w, dd, u = parse_wall(rule["UNTIL"])
                until_ts = to_ts(
                    w + (timedelta(days=1) - timedelta(seconds=1) if dd else timedelta()), dd, u, tzfn
                )
            off_now = tzfn(end_ts)
            window_wall = datetime.fromtimestamp(end_ts + off_now + 3600, tz=UTC).replace(tzinfo=None)
            walls = expand_rrule(wall0, rule, until_ts, window_wall)
        else:
            walls = [wall0]
        for w in walls:
            s = to_ts(w, is_date, utc, tzfn)  # a UTC DTSTART recurs in UTC, a TZID one in its wall time
            if rr and not _prop(ev, "RECURRENCE-ID"):
                if rule.get("UNTIL") and until_ts is not None and s > until_ts:
                    continue
                if round(s) in exdates:
                    continue
                if uid and (uid[1], s) in overrides:
                    continue  # replaced by its RECURRENCE-ID override
            e = s + length
            if e < start_ts or s > end_ts:
                continue
            out.append(
                {
                    "start": s,
                    "end": e,
                    "title": title,
                    "location": unescape(loc[1]).strip() if loc else "",
                    "all_day": is_date,
                    "cal": cal_index,
                }
            )
    out.sort(key=lambda e: (e["start"], e["end"]))
    return out


# ------------------------------------------------------------------------------------------ provider
def split_urls(s: str) -> list[str]:
    return [
        u.strip() for u in re.split(r"[\s,]+", s or "") if u.strip().lower().startswith(("http", "webcal"))
    ]


class CalendarProvider(Provider[dict[str, Any]]):
    name = "calendar"
    interval = 600.0
    retry = 90.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.urls: list[str] = []
        self.lookahead = 24.0

    def want(self, urls: list[str], lookahead_hours: float = 24.0) -> None:
        urls = [u.strip() for u in urls if u.strip()]
        if urls != self.urls or lookahead_hours != self.lookahead:
            self.urls, self.lookahead = urls, float(lookahead_hours)
            self.refresh()

    async def _get(self, url: str) -> str:
        if url.lower().startswith("webcal://"):
            url = "https://" + url[9:]
        r = await self.hub.http.get(url, timeout=15.0)
        r.raise_for_status()
        return r.text

    async def fetch(self) -> dict[str, Any]:
        now = time.time()
        if not self.urls:
            return {"events": [], "calendars": 0, "errors": [], "fetched": now, "configured": False}
        texts = await asyncio.gather(*(self._get(u) for u in self.urls), return_exceptions=True)
        events: list[dict[str, Any]] = []
        errors = []
        start, end = now - 18 * 3600, now + max(self.lookahead, 24.0) * 3600
        for i, tx in enumerate(texts):
            if isinstance(tx, BaseException):
                errors.append(f"calendar {i + 1}: {type(tx).__name__}")  # never echo the secret URL
                continue
            try:
                events += await asyncio.to_thread(events_between, tx, start, end, i)
            except Exception as e:
                errors.append(f"calendar {i + 1}: parse error {type(e).__name__}")
        if errors and len(errors) == len(self.urls):
            raise RuntimeError("; ".join(errors))
        events.sort(key=lambda e: (e["start"], e["end"]))
        return {
            "events": events,
            "calendars": len(self.urls),
            "errors": errors,
            "fetched": now,
            "configured": True,
        }


def day_bounds(ts: float) -> tuple[float, float]:
    d = datetime.fromtimestamp(ts).date()
    start = datetime(d.year, d.month, d.day).timestamp()
    return start, start + 86400
