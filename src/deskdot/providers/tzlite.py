"""Time zones without a tz database: `zoneinfo` first, then a small built-in table of cities and DST rules.

Windows Python ships no IANA database (``zoneinfo.available_timezones()`` is empty unless the ``tzdata`` wheel is
installed), so the Five O'Clock app and the calendar's TZID handling fall back to this table. It covers every
UTC offset in use (-11 … +14, plus the half/quarter-hour zones) with the current (2026) DST rules of the zones
it lists. `utc_offset()` answers for any IANA name in the table, and `resolve()` also knows the Windows zone
names Outlook writes into ICS files ("India Standard Time", "W. Europe Standard Time", …).
"""

from __future__ import annotations

import calendar
import zoneinfo
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import NamedTuple


class City(NamedTuple):
    name: str  # ASCII caps, as drawn on the panel
    country: str  # ISO-2
    zone: str  # IANA name
    std: int  # standard offset, minutes east of UTC
    rule: str  # DST rule id (see _dst_window), "" = none


# fmt: off
CITIES: tuple[City, ...] = (
    City("PAGO PAGO", "AS", "Pacific/Pago_Pago", -660, ""),
    City("HONOLULU", "US", "Pacific/Honolulu", -600, ""),
    City("PAPEETE", "PF", "Pacific/Tahiti", -600, ""),
    City("MARQUESAS", "PF", "Pacific/Marquesas", -570, ""),
    City("ANCHORAGE", "US", "America/Anchorage", -540, "US"),
    City("GAMBIER", "PF", "Pacific/Gambier", -540, ""),
    City("LOS ANGELES", "US", "America/Los_Angeles", -480, "US"),
    City("VANCOUVER", "CA", "America/Vancouver", -480, "US"),
    City("PITCAIRN", "PN", "Pacific/Pitcairn", -480, ""),
    City("PHOENIX", "US", "America/Phoenix", -420, ""),
    City("DENVER", "US", "America/Denver", -420, "US"),
    City("MEXICO CITY", "MX", "America/Mexico_City", -360, ""),
    City("CHICAGO", "US", "America/Chicago", -360, "US"),
    City("SAN JOSE", "CR", "America/Costa_Rica", -360, ""),
    City("NEW YORK", "US", "America/New_York", -300, "US"),
    City("TORONTO", "CA", "America/Toronto", -300, "US"),
    City("HAVANA", "CU", "America/Havana", -300, "CU"),
    City("BOGOTA", "CO", "America/Bogota", -300, ""),
    City("LIMA", "PE", "America/Lima", -300, ""),
    City("PANAMA", "PA", "America/Panama", -300, ""),
    City("KINGSTON", "JM", "America/Jamaica", -300, ""),
    City("CARACAS", "VE", "America/Caracas", -240, ""),
    City("LA PAZ", "BO", "America/La_Paz", -240, ""),
    City("SAN JUAN", "PR", "America/Puerto_Rico", -240, ""),
    City("HALIFAX", "CA", "America/Halifax", -240, "US"),
    City("SANTIAGO", "CL", "America/Santiago", -240, "CL"),
    City("ST JOHN'S", "CA", "America/St_Johns", -210, "US"),
    City("BUENOS AIRES", "AR", "America/Argentina/Buenos_Aires", -180, ""),
    City("SAO PAULO", "BR", "America/Sao_Paulo", -180, ""),
    City("RIO", "BR", "America/Sao_Paulo", -180, ""),
    City("MONTEVIDEO", "UY", "America/Montevideo", -180, ""),
    City("NORONHA", "BR", "America/Noronha", -120, ""),
    City("S GEORGIA", "GS", "Atlantic/South_Georgia", -120, ""),
    City("PRAIA", "CV", "Atlantic/Cape_Verde", -60, ""),
    City("AZORES", "PT", "Atlantic/Azores", -60, "EU"),
    City("REYKJAVIK", "IS", "Atlantic/Reykjavik", 0, ""),
    City("DAKAR", "SN", "Africa/Dakar", 0, ""),
    City("ACCRA", "GH", "Africa/Accra", 0, ""),
    City("LONDON", "GB", "Europe/London", 0, "EU"),
    City("DUBLIN", "IE", "Europe/Dublin", 0, "EU"),
    City("LISBON", "PT", "Europe/Lisbon", 0, "EU"),
    City("LAGOS", "NG", "Africa/Lagos", 60, ""),
    City("ALGIERS", "DZ", "Africa/Algiers", 60, ""),
    City("PARIS", "FR", "Europe/Paris", 60, "EU"),
    City("BERLIN", "DE", "Europe/Berlin", 60, "EU"),
    City("MADRID", "ES", "Europe/Madrid", 60, "EU"),
    City("ROME", "IT", "Europe/Rome", 60, "EU"),
    City("AMSTERDAM", "NL", "Europe/Amsterdam", 60, "EU"),
    City("PRAGUE", "CZ", "Europe/Prague", 60, "EU"),
    City("CAIRO", "EG", "Africa/Cairo", 120, "EG"),
    City("JOHANNESBURG", "ZA", "Africa/Johannesburg", 120, ""),
    City("ATHENS", "GR", "Europe/Athens", 120, "EU"),
    City("HELSINKI", "FI", "Europe/Helsinki", 120, "EU"),
    City("KYIV", "UA", "Europe/Kyiv", 120, "EU"),
    City("NAIROBI", "KE", "Africa/Nairobi", 180, ""),
    City("ISTANBUL", "TR", "Europe/Istanbul", 180, ""),
    City("MOSCOW", "RU", "Europe/Moscow", 180, ""),
    City("RIYADH", "SA", "Asia/Riyadh", 180, ""),
    City("DOHA", "QA", "Asia/Qatar", 180, ""),
    City("TEHRAN", "IR", "Asia/Tehran", 210, ""),
    City("DUBAI", "AE", "Asia/Dubai", 240, ""),
    City("BAKU", "AZ", "Asia/Baku", 240, ""),
    City("MAURITIUS", "MU", "Indian/Mauritius", 240, ""),
    City("KABUL", "AF", "Asia/Kabul", 270, ""),
    City("KARACHI", "PK", "Asia/Karachi", 300, ""),
    City("TASHKENT", "UZ", "Asia/Tashkent", 300, ""),
    City("MALDIVES", "MV", "Indian/Maldives", 300, ""),
    City("MUMBAI", "IN", "Asia/Kolkata", 330, ""),
    City("DELHI", "IN", "Asia/Kolkata", 330, ""),
    City("COLOMBO", "LK", "Asia/Colombo", 330, ""),
    City("KATHMANDU", "NP", "Asia/Kathmandu", 345, ""),
    City("DHAKA", "BD", "Asia/Dhaka", 360, ""),
    City("THIMPHU", "BT", "Asia/Thimphu", 360, ""),
    City("YANGON", "MM", "Asia/Yangon", 390, ""),
    City("BANGKOK", "TH", "Asia/Bangkok", 420, ""),
    City("JAKARTA", "ID", "Asia/Jakarta", 420, ""),
    City("HANOI", "VN", "Asia/Ho_Chi_Minh", 420, ""),
    City("SINGAPORE", "SG", "Asia/Singapore", 480, ""),
    City("HONG KONG", "HK", "Asia/Hong_Kong", 480, ""),
    City("SHANGHAI", "CN", "Asia/Shanghai", 480, ""),
    City("MANILA", "PH", "Asia/Manila", 480, ""),
    City("PERTH", "AU", "Australia/Perth", 480, ""),
    City("TAIPEI", "TW", "Asia/Taipei", 480, ""),
    City("TOKYO", "JP", "Asia/Tokyo", 540, ""),
    City("SEOUL", "KR", "Asia/Seoul", 540, ""),
    City("DARWIN", "AU", "Australia/Darwin", 570, ""),
    City("ADELAIDE", "AU", "Australia/Adelaide", 570, "AU"),
    City("BRISBANE", "AU", "Australia/Brisbane", 600, ""),
    City("SYDNEY", "AU", "Australia/Sydney", 600, "AU"),
    City("MELBOURNE", "AU", "Australia/Melbourne", 600, "AU"),
    City("GUAM", "GU", "Pacific/Guam", 600, ""),
    City("NOUMEA", "NC", "Pacific/Noumea", 660, ""),
    City("HONIARA", "SB", "Pacific/Guadalcanal", 660, ""),
    City("SUVA", "FJ", "Pacific/Fiji", 720, ""),
    City("AUCKLAND", "NZ", "Pacific/Auckland", 720, "NZ"),
    City("TARAWA", "KI", "Pacific/Tarawa", 720, ""),
    City("NUKU'ALOFA", "TO", "Pacific/Tongatapu", 780, ""),
    City("APIA", "WS", "Pacific/Apia", 780, ""),
    City("KIRITIMATI", "KI", "Pacific/Kiritimati", 840, ""),
)

# Windows zone ids (as Outlook/Exchange write them in ICS TZID) -> IANA
WINDOWS_ZONES: dict[str, str] = {
    "Dateline Standard Time": "Etc/GMT+12", "UTC-11": "Pacific/Pago_Pago",
    "Hawaiian Standard Time": "Pacific/Honolulu", "Alaskan Standard Time": "America/Anchorage",
    "Pacific Standard Time": "America/Los_Angeles", "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time": "America/Denver", "Central Standard Time": "America/Chicago",
    "Central Standard Time (Mexico)": "America/Mexico_City", "Central America Standard Time": "America/Costa_Rica",
    "Eastern Standard Time": "America/New_York", "SA Pacific Standard Time": "America/Bogota",
    "Cuba Standard Time": "America/Havana", "Venezuela Standard Time": "America/Caracas",
    "Atlantic Standard Time": "America/Halifax", "SA Western Standard Time": "America/La_Paz",
    "Pacific SA Standard Time": "America/Santiago", "Newfoundland Standard Time": "America/St_Johns",
    "E. South America Standard Time": "America/Sao_Paulo", "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "Montevideo Standard Time": "America/Montevideo", "UTC-02": "America/Noronha",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde", "Azores Standard Time": "Atlantic/Azores",
    "UTC": "UTC", "Coordinated Universal Time": "UTC", "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik", "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris", "Central Europe Standard Time": "Europe/Prague",
    "Central European Standard Time": "Europe/Warsaw", "W. Central Africa Standard Time": "Africa/Lagos",
    "GTB Standard Time": "Europe/Athens", "FLE Standard Time": "Europe/Kyiv", "Egypt Standard Time": "Africa/Cairo",
    "South Africa Standard Time": "Africa/Johannesburg", "Israel Standard Time": "Asia/Jerusalem",
    "Turkey Standard Time": "Europe/Istanbul", "Russian Standard Time": "Europe/Moscow",
    "Arab Standard Time": "Asia/Riyadh", "E. Africa Standard Time": "Africa/Nairobi",
    "Iran Standard Time": "Asia/Tehran", "Arabian Standard Time": "Asia/Dubai",
    "Azerbaijan Standard Time": "Asia/Baku", "Afghanistan Standard Time": "Asia/Kabul",
    "Pakistan Standard Time": "Asia/Karachi", "West Asia Standard Time": "Asia/Tashkent",
    "India Standard Time": "Asia/Kolkata", "Sri Lanka Standard Time": "Asia/Colombo",
    "Nepal Standard Time": "Asia/Kathmandu", "Bangladesh Standard Time": "Asia/Dhaka",
    "Myanmar Standard Time": "Asia/Yangon", "SE Asia Standard Time": "Asia/Bangkok",
    "China Standard Time": "Asia/Shanghai", "Singapore Standard Time": "Asia/Singapore",
    "W. Australia Standard Time": "Australia/Perth", "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo", "Korea Standard Time": "Asia/Seoul",
    "AUS Central Standard Time": "Australia/Darwin", "Cen. Australia Standard Time": "Australia/Adelaide",
    "E. Australia Standard Time": "Australia/Brisbane", "AUS Eastern Standard Time": "Australia/Sydney",
    "West Pacific Standard Time": "Pacific/Guam", "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Fiji Standard Time": "Pacific/Fiji", "New Zealand Standard Time": "Pacific/Auckland",
    "Tonga Standard Time": "Pacific/Tongatapu", "Samoa Standard Time": "Pacific/Apia",
    "Line Islands Standard Time": "Pacific/Kiritimati",
}
# fmt: on

# IANA names that aren't cities above but show up in calendars
_EXTRA: dict[str, tuple[int, str]] = {
    "UTC": (0, ""),
    "Etc/UTC": (0, ""),
    "GMT": (0, ""),
    "Etc/GMT": (0, ""),
    "Etc/GMT+12": (-720, ""),
    "Europe/Warsaw": (60, "EU"),
    "Europe/Vienna": (60, "EU"),
    "Europe/Brussels": (60, "EU"),
    "Europe/Zurich": (60, "EU"),
    "Europe/Stockholm": (60, "EU"),
    "Europe/Oslo": (60, "EU"),
    "Europe/Copenhagen": (60, "EU"),
    "Europe/Budapest": (60, "EU"),
    "Europe/Bucharest": (120, "EU"),
    "Europe/Sofia": (120, "EU"),
    "Europe/Kiev": (120, "EU"),
    "Asia/Calcutta": (330, ""),
    "Asia/Jerusalem": (120, "IL"),
    "Asia/Kuala_Lumpur": (480, ""),
    "Asia/Saigon": (420, ""),
    "America/Detroit": (-300, "US"),
    "America/Boise": (-420, "US"),
    "America/Edmonton": (-420, "US"),
    "America/Winnipeg": (-360, "US"),
    "America/Montreal": (-300, "US"),
}


def _nth_sunday(year: int, month: int, n: int) -> int:
    """Day of month of the n-th Sunday (n = -1: last)."""
    days = calendar.monthrange(year, month)[1]
    sundays = [d for d in range(1, days + 1) if calendar.weekday(year, month, d) == 6]
    return sundays[n - 1] if n > 0 else sundays[n]


def _last_weekday(year: int, month: int, weekday: int) -> int:
    days = calendar.monthrange(year, month)[1]
    return max(d for d in range(1, days + 1) if calendar.weekday(year, month, d) == weekday)


def _utc(year: int, month: int, day: int, hour: float, offset_min: int = 0) -> float:
    """Unix time of a wall-clock instant at `offset_min` east of UTC."""
    return datetime(year, month, day, tzinfo=UTC).timestamp() + hour * 3600 - offset_min * 60


def _dst_window(rule: str, year: int, std: int) -> tuple[float, float] | None:
    """(start, end) unix times of DST in `year`; start > end for southern-hemisphere rules."""
    if rule == "EU":
        return _utc(year, 3, _nth_sunday(year, 3, -1), 1), _utc(year, 10, _nth_sunday(year, 10, -1), 1)
    if rule == "US":
        return (
            _utc(year, 3, _nth_sunday(year, 3, 2), 2, std),
            _utc(year, 11, _nth_sunday(year, 11, 1), 2, std + 60),
        )
    if rule == "CU":
        return (
            _utc(year, 3, _nth_sunday(year, 3, 2), 0, std),
            _utc(year, 11, _nth_sunday(year, 11, 1), 1, std + 60),
        )
    if rule == "AU":
        return (
            _utc(year, 10, _nth_sunday(year, 10, 1), 2, std),
            _utc(year, 4, _nth_sunday(year, 4, 1), 3, std + 60),
        )
    if rule == "NZ":
        return (
            _utc(year, 9, _nth_sunday(year, 9, -1), 2, std),
            _utc(year, 4, _nth_sunday(year, 4, 1), 3, std + 60),
        )
    if rule == "CL":  # Saturday 24:00 local = Sunday 00:00
        return (
            _utc(year, 9, _nth_sunday(year, 9, 1), 0, std),
            _utc(year, 4, _nth_sunday(year, 4, 1), 0, std + 60),
        )
    if rule == "EG":  # last Friday of April 00:00 -> last Thursday of October 24:00
        return (
            _utc(year, 4, _last_weekday(year, 4, 4), 0, std),
            _utc(year, 10, _last_weekday(year, 10, 3), 24, std + 60),
        )
    if rule == "IL":  # Friday before the last Sunday of March 02:00 -> last Sunday of October 02:00
        return (
            _utc(year, 3, _nth_sunday(year, 3, -1) - 2, 2, std),
            _utc(year, 10, _nth_sunday(year, 10, -1), 2, std + 60),
        )
    return None


def rule_offset(std: int, rule: str, ts: float) -> int:
    """UTC offset in seconds at `ts` for a standard offset (minutes) and DST rule."""
    if not rule:
        return std * 60
    year = datetime.fromtimestamp(ts, tz=UTC).year
    win = _dst_window(rule, year, std)
    if win is None:
        return std * 60
    a, b = win
    dst = (a <= ts < b) if a < b else (ts >= a or ts < b)
    return (std + (60 if dst else 0)) * 60


_TABLE: dict[str, tuple[int, str]] = {**_EXTRA, **{c.zone: (c.std, c.rule) for c in CITIES}}


@lru_cache(maxsize=256)
def _zoneinfo(name: str) -> zoneinfo.ZoneInfo | None:
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return None


def has_tzdata() -> bool:
    return _zoneinfo("Europe/London") is not None


def resolve(name: str) -> Callable[[float], int] | None:
    """A function ts -> UTC offset (seconds) for an IANA or Windows zone name, or None if unknown."""
    name = name.strip().strip('"')
    iana = WINDOWS_ZONES.get(name, name)
    zi = _zoneinfo(iana)
    if zi is not None:

        def via_zoneinfo(ts: float, zi: zoneinfo.ZoneInfo = zi) -> int:
            off = datetime.fromtimestamp(ts, tz=zi).utcoffset()
            return int(off.total_seconds()) if off else 0

        return via_zoneinfo
    entry = _TABLE.get(iana)
    if entry is None:
        return None
    std, rule = entry
    return lambda ts: rule_offset(std, rule, ts)


def utc_offset(name: str, ts: float) -> int | None:
    fn = resolve(name)
    return fn(ts) if fn else None


def local_to_utc(wall: datetime, offset_fn: Callable[[float], int]) -> float:
    """Unix time of a naive wall-clock datetime in the zone described by `offset_fn`."""
    naive = wall.replace(tzinfo=UTC).timestamp()
    guess = naive - offset_fn(naive)
    return naive - offset_fn(guess)


def city_offset(c: City, ts: float) -> int:
    """UTC offset (seconds) of a table city at `ts`; zoneinfo wins when the machine has tz data."""
    zi = _zoneinfo(c.zone)
    if zi is not None:
        off = datetime.fromtimestamp(ts, tz=zi).utcoffset()
        if off is not None:
            return int(off.total_seconds())
    return rule_offset(c.std, c.rule, ts)


def local_time(c: City, ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC).replace(tzinfo=None) + timedelta(seconds=city_offset(c, ts))
