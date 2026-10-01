"""New apps: Day & Night, Progress, Five O'Clock, Planets, What to Wear, Tides & Surf, QR Code, Habits, Calendar
and Loops — plus their providers (planets, wear, tides, calendar) and the tz fallback table.

Maths is checked against published vectors (QR Reed–Solomon and format bits, known 2026 planet events, DST
dates); parsers run on real captures in tests/fixtures/newapps (Open-Meteo forecast/marine, 2026-09-25) and a
hand-written ICS; providers run against httpx.MockTransport; every app renders every Choice option with and
without data, fast, and every clip bakes within the frame and GIF budgets.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from dotdeck.apps import calendar as calendar_app
from dotdeck.apps import daynight, fiveoclock, habits, loops, planets, progress, qr, tides, wear
from dotdeck.gfx import Frame
from dotdeck.gfx.image import GIF_BUDGET, encode_gif_budget
from dotdeck.providers import calendar as calendar_p
from dotdeck.providers import planets as planets_p
from dotdeck.providers import tides as tides_p
from dotdeck.providers import tzlite
from dotdeck.providers import wear as wear_p
from dotdeck.providers.base import Hub

FIX = Path(__file__).parent / "fixtures" / "newapps"
UTCd = UTC


def ts(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> float:
    return datetime(y, m, d, h, mi, tzinfo=UTC).timestamp()


# ------------------------------------------------------------------------------------------ fakes
class Prov:
    def __init__(self, value: Any = None, error: str | None = None) -> None:
        self.value, self.error, self.wanted = value, error, None

    def want(self, *a: Any) -> None:
        self.wanted = a


class Ctx:
    def __init__(self, providers: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> None:
        self.providers = providers or {}
        self.data: dict[str, Any] = data if data is not None else {}
        self.saved = 0
        self.key = self.app_id = "test"
        self.library = None

    def provider(self, name: str) -> Any:
        if name not in self.providers:
            raise KeyError(name)
        return self.providers[name]

    def save(self) -> None:
        self.saved += 1

    def invalidate(self) -> None: ...
    def notify(self, **_: Any) -> None: ...


class Store:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or {}

    def get(self, k: str, default: Any = None) -> Any:
        return self.data.get(k, default)


def make(
    cls: type, settings: dict[str, Any] | None = None, providers: dict[str, Any] | None = None, data=None
):  # type: ignore[no-untyped-def]
    app = cls(Ctx(providers, data), cls.Settings.model_validate(settings or {}))
    app.on_settings()
    app.on_start()
    return app


def mock_hub(handler, store: dict[str, Any] | None = None, loc=(19.2, 72.97)) -> Hub:  # type: ignore[no-untyped-def]
    hub = Hub(Store(store), lambda _n: None)
    hub.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def location() -> dict[str, Any]:
        return {"city": "Mumbai", "lat": loc[0], "lon": loc[1], "country": "IN"}

    hub.location = location  # type: ignore[method-assign]
    return hub


# ------------------------------------------------------------------------------------------ data
def marine_now() -> dict[str, Any]:
    """The marine capture, shifted so its middle day is today."""
    d = tides_p.parse_marine(json.loads((FIX / "open_meteo_marine.json").read_text()))
    shift = time.time() - d["ts"][30]
    d["ts"] = [t + shift for t in d["ts"]]
    for e in d["extrema"]:
        e["ts"] += shift
    d.update(place="Mumbai", unit="m")
    return d


def wear_data() -> dict[str, Any]:
    d = wear_p.summarise(json.loads((FIX / "open_meteo_forecast.json").read_text()), 6)
    d["unit"] = "C"
    return d


def calendar_data() -> dict[str, Any]:
    now = time.time()

    def ev(a: float, b: float, title: str, cal: int = 0) -> dict[str, Any]:
        return {"start": now + a * 60, "end": now + b * 60, "title": title, "cal": cal, "all_day": False}

    return {
        "events": [
            ev(-30, 15, "Planning"),
            ev(12, 42, "Design review with the platform team", 1),
            ev(200, 230, "1:1"),
        ],
        "errors": [],
        "configured": True,
    }


def sky_data() -> dict[str, Any]:
    now = time.time()
    return {
        "city": "Mumbai",
        "lat": 19.2,
        "lon": 72.97,
        "tz_offset": 19800.0,
        "days": {"x": {"sunrise": now + 3600, "sunset": now + 13 * 3600}},
    }


APPS: dict[str, tuple[type, str | None, Any]] = {  # id -> (class, provider name, data factory)
    "daynight": (daynight.DayNight, "sky", sky_data),
    "progress": (progress.Progress, None, None),
    "fiveoclock": (fiveoclock.FiveOClock, None, None),
    "planets": (
        planets.Planets,
        "planets",
        lambda: planets_p.compute(time.time(), 19.2, 72.97) | {"tz_offset": 19800},
    ),
    "wear": (wear.Wear, "wear", wear_data),
    "tides": (tides.Tides, "tides", marine_now),
    "qr": (qr.QRCode, None, None),
    "habits": (habits.Habits, None, None),
    "calendar": (calendar_app.Calendar, "calendar", calendar_data),
    "loops": (loops.Loops, None, None),
}


def variants(cls: type) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{}]
    for name, field in cls.Settings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            out += [{name: v} for v in extra["enum"]]
    return out


CASES = [(aid, v) for aid, (cls, _, _) in APPS.items() for v in variants(cls)]


@pytest.mark.parametrize(("app_id", "settings"), CASES, ids=[f"{a}-{list(s.values())}" for a, s in CASES])
@pytest.mark.parametrize("state", ["none", "error", "data"])
def test_every_variant_renders_fast(app_id: str, settings: dict[str, Any], state: str) -> None:
    cls, prov, factory = APPS[app_id]
    if app_id == "calendar":
        settings = {"urls": "https://example.com/secret.ics", **settings}
    providers = {}
    if prov:
        value = factory() if (state == "data" and factory) else None
        providers[prov] = Prov(value, "boom" if state == "error" else None)
    app = make(cls, settings, providers)
    worst = 0.0
    for t in (0.0, 0.37, 1.9, 7.3):
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, t)
        if t:  # the first call may warm caches (map projections)
            worst = max(worst, time.perf_counter() - t0)
        assert f.px.shape == (32, 32, 3)
    assert worst < 0.05, f"{app_id} render took {worst * 1000:.1f} ms"
    assert app.kind() in ("stream", "clip")
    json.dumps(app.status(), default=str)


CLIP_CASES = [(a, v) for a, v in CASES if a in ("fiveoclock", "loops", "wear", "daynight", "habits")]


@pytest.mark.parametrize(
    ("app_id", "settings"), CLIP_CASES, ids=[f"{a}-{list(s.values())}" for a, s in CLIP_CASES]
)
def test_clips_bake_within_budget(app_id: str, settings: dict[str, Any]) -> None:
    cls, prov, factory = APPS[app_id]
    providers = {prov: Prov(factory())} if prov else {}
    app = make(cls, settings, providers)
    if app.kind() != "clip":
        pytest.skip("streams in this state")
    clip = app.clip_frames()
    assert 1 <= len(clip.frames) <= 240
    assert len(clip.durations_ms) == len(clip.frames)
    gif = encode_gif_budget(clip.frames, clip.durations_ms, app.clip_colors)
    assert len(gif) <= GIF_BUDGET
    json.loads(app.clip_key())  # keys are JSON


def test_loops_are_seamless_and_deterministic() -> None:
    for eff in ("cat", "rain", "warp", "dvd"):
        a = make(loops.Loops, {"effect": eff})
        secs, _ = loops.LOOP_SPEC[eff]
        f0, f1 = Frame(), Frame()
        a.render(f0, 0.0)
        a.render(f1, secs)  # one loop later: identical frame
        assert np.array_equal(f0.px, f1.px), eff
        b = make(loops.Loops, {"effect": eff})
        f2 = Frame()
        b.render(f2, 0.0)
        assert np.array_equal(f0.px, f2.px), eff


def test_life_restarts_and_fades() -> None:
    run = loops.life_run(240)
    assert len(run) == 240
    assert run[-1][2] < run[-4][2]  # the seam fades to black
    alive = [int(g.sum()) for g, _, _ in run]
    assert max(alive) > 20 and min(alive) >= 0
    assert loops.life_step(loops.life_seed(0)).sum() == 6  # R-pentomino, generation 1


def test_dvd_hits_corners() -> None:
    app = make(loops.Loops, {"effect": "dvd"})
    f = Frame()
    app.render(f, 0.0)
    assert f.px[0:8, 0:8].any()  # starts in the top-left corner


# ------------------------------------------------------------------------------------------ QR
def test_qr_reed_solomon_vector() -> None:
    # "HELLO WORLD" 1-M data codewords and their published EC codewords (ISO 18004 annex / thonky.com)
    data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    assert qr.rs_ecc(data, 10) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]


def test_qr_format_bits() -> None:
    assert format(qr.format_bits("L", 0), "015b") == "111011111000100"
    assert format(qr.format_bits("M", 0), "015b") == "101010000010010"
    assert format(qr.format_bits("L", 4), "015b") == "110011000101111"
    assert format(qr.format_bits("M", 5), "015b") == "100000011001110"


def test_qr_capacity_and_versions() -> None:
    assert [qr.max_bytes(v, "L") for v in (1, 2, 3)] == [17, 32, 53]
    assert [qr.max_bytes(v, "M") for v in (1, 2, 3)] == [14, 26, 42]
    assert len(qr.encode(b"x" * 17, "L")) == 21
    assert len(qr.encode(b"x" * 18, "L")) == 25
    assert len(qr.encode(b"x" * 53, "L")) == 29
    with pytest.raises(ValueError):
        qr.encode(b"x" * 54, "L")


def test_wifi_payload_escapes() -> None:
    assert qr.wifi_payload("My;Net", 'p:a"ss', "WPA", True) == 'WIFI:T:WPA;S:My\\;Net;P:p\\:a\\"ss;H:true;;'
    assert qr.wifi_payload("Cafe", "", "nopass", False) == "WIFI:T:nopass;S:Cafe;;"


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"mode": "wifi", "ssid": "DotDeck", "password": "hunter2hunter2"},
        {"mode": "text", "text": "hi", "ecc": "L"},
        {"mode": "text", "text": "Hello, DotDeck! 0123456789 abcdefghijklmnopqrstuvw", "ecc": "L"},
    ],
)
def test_qr_panel_decodes_with_opencv(settings: dict[str, Any]) -> None:
    cv2 = pytest.importorskip("cv2")
    app = make(qr.QRCode, settings)
    f = Frame()
    app.render(f, 0)
    gray = f.px.mean(axis=2).astype(np.uint8)
    img = np.full((48, 48), 255, np.uint8)  # extend the light quiet zone like a wall around the panel
    img[8:40, 8:40] = gray
    img = cv2.resize(img, None, fx=10, fy=10, interpolation=cv2.INTER_NEAREST)
    text, _pts, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert text == app.payload()


def test_qr_too_long_message() -> None:
    app = make(qr.QRCode, {"mode": "text", "text": "é" * 30})
    f = Frame()
    app.render(f, 0)
    assert app.matrix() is None and app.status()["error"] == "too long"
    assert f.px.any()


# ------------------------------------------------------------------------------------------ time zones
def test_tz_dst_rules_2026() -> None:
    assert tzlite.rule_offset(60, "EU", ts(2026, 3, 29, 0, 59)) == 3600
    assert tzlite.rule_offset(60, "EU", ts(2026, 3, 29, 1, 0)) == 7200
    assert tzlite.rule_offset(60, "EU", ts(2026, 10, 25, 1, 0)) == 3600
    assert tzlite.rule_offset(-300, "US", ts(2026, 3, 8, 6, 59)) == -5 * 3600
    assert tzlite.rule_offset(-300, "US", ts(2026, 3, 8, 7, 0)) == -4 * 3600
    assert tzlite.rule_offset(-300, "US", ts(2026, 11, 1, 6, 0)) == -5 * 3600
    assert tzlite.rule_offset(600, "AU", ts(2026, 1, 15)) == 11 * 3600  # southern summer
    assert tzlite.rule_offset(600, "AU", ts(2026, 7, 15)) == 10 * 3600
    assert tzlite.rule_offset(720, "NZ", ts(2026, 9, 26, 14, 0)) == 13 * 3600


def test_tz_resolve_names() -> None:
    now = ts(2026, 7, 1)
    assert tzlite.utc_offset("Asia/Kolkata", now) == 19800
    assert tzlite.utc_offset("India Standard Time", now) == 19800
    assert tzlite.utc_offset("W. Europe Standard Time", now) == 7200
    assert tzlite.utc_offset("Nowhere/Atlantis", now) is None
    naive = datetime(2026, 7, 1, 9, 0)
    assert tzlite.local_to_utc(naive, tzlite.resolve("Europe/Berlin")) == ts(2026, 7, 1, 7, 0)  # type: ignore[arg-type]


def test_always_five_oclock_somewhere() -> None:
    start = ts(2026, 1, 1)
    for i in range(0, 366 * 24 * 4, 7):  # every 15 minutes-ish through the year
        t = start + i * 900
        cities = fiveoclock.five_oclock_cities(t)
        assert cities, datetime.fromtimestamp(t, UTC)
        assert all(tzlite.local_time(c, t).hour == 17 for c, _ in cities)
    cities = fiveoclock.five_oclock_cities(ts(2026, 9, 25, 11, 30))  # 17:00 IST
    assert "MUMBAI" in {c.name for c, _ in cities}


def test_fiveoclock_clip_key_tracks_cities() -> None:
    app = make(fiveoclock.FiveOClock, {"count": 2})
    k1 = app.clip_key()
    app._cache = (time.time(), fiveoclock.five_oclock_cities(time.time() + 3600))
    assert app.clip_key() != k1


# ------------------------------------------------------------------------------------------ progress
def test_progress_periods() -> None:
    s = progress.ProgressSettings(birth_date=date(1990, 7, 2), life_years=80, week_start="mon")
    now = datetime(2026, 7, 2, 12, 0)  # a Thursday, midday
    ps = progress.periods(now, s)
    assert ps["day"].frac == pytest.approx(0.5)
    assert ps["week"].frac == pytest.approx(3.5 / 7)
    assert ps["month"].frac == pytest.approx(1.5 / 31)
    assert ps["year"].frac == pytest.approx((182 + 0.5) / 365)
    assert ps["life"].frac == pytest.approx(36 / 80, abs=1e-3)
    assert progress.pct_text(0.7349, 1) == "73.4%"
    assert progress.pct_text(1.0, 2) == "100%"
    assert progress.left_text(ps["day"], now) == "12H"
    sun = progress.periods(now, progress.ProgressSettings(week_start="sun"))
    assert sun["week"].frac == pytest.approx(4.5 / 7)


# ------------------------------------------------------------------------------------------ habits
def test_habits_tick_streak_undo_persist() -> None:
    app = make(habits.Habits, {"day_starts": 0})
    today = app.today()
    for k in (1, 2, 3):
        app.set_done(1, True, today - timedelta(days=k))
    assert habits.streak(app.days(1), today) == (3, False)
    res = asyncio.run(app.action("tick", {"habit": "water"}))
    assert res["habits"]["1"]["streak"] == 4 and res["habits"]["1"]["done_today"]
    assert app.kind() == "stream"  # the tick burst plays live
    assert app.ctx.saved >= 4
    assert app.ctx.data["log"]["1"][-1] == today.isoformat()
    asyncio.run(app.action("undo", {}))
    assert habits.streak(app.days(1), today) == (3, False)
    asyncio.run(app.action("tick2", {}))
    asyncio.run(app.action("untick", {"habit": 2}))
    assert today.isoformat() not in app.days(2)
    with pytest.raises(ValueError):
        asyncio.run(app.action("tick", {"habit": "nope"}))
    app._fx = None
    assert app.kind() == "clip"
    # a fresh instance reads the same persisted data
    again = habits.Habits(app.ctx, app.settings)
    assert again.days(1) == app.days(1)


# ------------------------------------------------------------------------------------------ planets
def test_planet_ephemeris_known_events() -> None:
    def peak(name: str, start: float, days: int, fn: Any = max) -> tuple[float, date]:
        vals = [(planets_p.geocentric(name, start + i * 86400)["elong"], i) for i in range(days)]
        e, i = fn(vals)
        return e, (datetime.fromtimestamp(start, UTC) + timedelta(days=i)).date()

    e, d = peak("jupiter", ts(2025, 12, 1), 90)
    assert abs((d - date(2026, 1, 10)).days) <= 1 and e > 178  # opposition 2026-01-10
    e, d = peak("venus", ts(2026, 6, 1), 120)
    assert abs((d - date(2026, 8, 15)).days) <= 2 and 45 < e < 47  # greatest elongation 45.9°
    _, d = peak("venus", ts(2026, 9, 1), 90, min)
    assert abs((d - date(2026, 10, 24)).days) <= 2  # inferior conjunction
    _, d = peak("mars", ts(2026, 12, 1), 150)
    assert abs((d - date(2027, 2, 19)).days) <= 2  # opposition


def test_planets_compute_rise_set() -> None:
    d = planets_p.compute(ts(2026, 10, 20, 10), -33.87, 151.2)  # Sydney, 21:00 local
    sat = next(p for p in d["planets"] if p["id"] == "saturn")
    assert sat["alt"] > 20 and sat["visible_now"]
    for p in d["planets"]:
        for k in ("rise", "set"):
            assert p[k] is None or ts(2026, 10, 20, 10) < p[k] < ts(2026, 10, 21, 12)
    alt, _ = planets_p.altaz(sat["ra"], sat["dec"], sat["set"], -33.87, 151.2)
    assert abs(float(alt)) < 1.0  # at its set time the planet is on the horizon


def test_planets_provider_fetch() -> None:
    hub = mock_hub(lambda r: httpx.Response(404))
    p = planets_p.PlanetsProvider(hub)
    d = asyncio.run(p.fetch())
    assert d["city"] == "Mumbai" and len(d["planets"]) == 5
    asyncio.run(hub.http.aclose())


# ------------------------------------------------------------------------------------------ day & night
def test_subsolar_and_terminator() -> None:
    lat, lon = daynight.subsolar_point(ts(2026, 9, 23, 12))  # near the equinox, noon UTC
    assert abs(lat) < 0.6 and abs(lon) < 3
    alt = daynight.solar_altitude(np.array([0.0, 0.0]), np.array([lon, lon + 180]), lat, lon)
    assert alt[0] > 89 and alt[1] < -89
    mlat, _ = daynight.sublunar_point(ts(2026, 9, 25))
    assert abs(mlat) < 29  # the moon never strays further than ~28.6° from the equator


def test_daynight_home_and_caption() -> None:
    app = make(daynight.DayNight, {"layout": "world"}, {"sky": Prov(sky_data())})
    top, _, bottom, _ = app._caption(time.time())
    assert top in ("DAY", "NIGHT", "DUSK", "DAWN") and bottom.startswith("▲")
    for layout in ("world", "half", "globe"):
        a = make(daynight.DayNight, {"layout": layout}, {"sky": Prov(sky_data())})
        assert a._static(time.time())["home"] is not None


# ------------------------------------------------------------------------------------------ wear
def test_wear_summary_and_choice() -> None:
    d = wear_data()
    assert d["hours"] == 6 and d["rain_prob"] == 71 and d["uv_max"] > 4
    s = wear.WearSettings()
    assert wear.choose(d, s) == "umbrella"
    assert wear.choose(d | {"rain_prob": 10, "rain_mm": 0}, s) == "tshirt"
    assert wear.choose(d | {"rain_prob": 10, "rain_mm": 0, "uv_max": 8}, s) == "sunglasses"
    assert wear.choose(d | {"rain_prob": 10, "rain_mm": 0, "feels_min": 9}, s) == "jacket"
    assert wear.choose(d | {"rain_prob": 10, "rain_mm": 0, "feels_min": 1}, s) == "scarf"
    assert wear.choose(d | {"snow_cm": 2.0}, s) == "boots"
    assert wear.choose(d, wear.WearSettings(rain_chance=80)) == "tshirt"


def test_wear_provider_fetch_units() -> None:
    raw = (FIX / "open_meteo_forecast.json").read_text()
    seen: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(r.url.params)
        return httpx.Response(200, text=raw)

    hub = mock_hub(handler, {"units": "imperial"})
    p = wear_p.WearProvider(hub)
    p.want(4)
    d = asyncio.run(p.fetch())
    assert d["unit"] == "F" and d["hours"] == 4 and "uv_index" in seen["hourly"]
    asyncio.run(hub.http.aclose())


# ------------------------------------------------------------------------------------------ tides
def test_marine_parse_and_extrema() -> None:
    d = tides_p.parse_marine(json.loads((FIX / "open_meteo_marine.json").read_text()))
    assert d["has_tide"] and d["has_waves"] and d["tz_offset"] == 19800
    kinds = [e["kind"] for e in d["extrema"]]
    assert all(a != b for a, b in itertools.pairwise(kinds))  # highs and lows alternate
    assert 3 <= kinds.count("high") <= 6  # semidiurnal: ~2 highs a day over 3 days
    first = d["extrema"][0]
    i = min(range(len(d["ts"])), key=lambda k: abs(d["ts"][k] - first["ts"]))
    assert abs(d["sea"][i] - first["h"]) < 0.2
    assert tides_p.compass(268) == "W" and tides_p.compass(10) == "N"
    inland = tides_p.parse_marine({"hourly": {"time": ["2026-09-25T00:00"], "sea_level_height_msl": [None]}})
    assert not inland["has_tide"] and not inland["has_waves"]


def test_tides_provider_coast_target() -> None:
    raw = (FIX / "open_meteo_marine.json").read_text()
    seen: dict[str, Any] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen.update(r.url.params)
        return httpx.Response(200, text=raw)

    hub = mock_hub(handler)
    p = tides_p.TidesProvider(hub)
    p.want(18.95, 72.8)
    d = asyncio.run(p.fetch())
    assert seen["latitude"] == "18.95" and d["place"] == "18.95,72.80" and d["unit"] == "m"
    p.want(0, 0)
    assert p.target is None
    asyncio.run(hub.http.aclose())


# ------------------------------------------------------------------------------------------ calendar
ICS = (FIX / "calendar.ics").read_text()


def _events() -> list[tuple[str, str, float]]:
    evs = calendar_p.events_between(ICS, ts(2026, 10, 18), ts(2026, 11, 5))
    return [
        (datetime.fromtimestamp(e["start"], UTC).strftime("%m-%d %H:%M"), e["title"], e["end"] - e["start"])
        for e in evs
    ]


def test_ics_expansion() -> None:
    evs = _events()
    standups = [s for s, title, _ in evs if title.startswith("Daily stand-up")]
    # WEEKLY MO,WE,FR COUNT=8 from Mon 19 Oct: Wed 21 is an EXDATE, Fri 23 moved by RECURRENCE-ID;
    # 09:30 Berlin is 07:30 UTC in CEST and 08:30 UTC after the 25 Oct DST change.
    assert standups == [
        "10-19 07:30",
        "10-26 08:30",
        "10-28 08:30",
        "10-30 08:30",
        "11-02 08:30",
        "11-04 08:30",
    ]
    assert ("10-23 09:00", "Stand-up (moved)", 900.0) in evs
    reviews = [s for s, title, _ in evs if title == "Design review"]
    assert reviews == ["10-20 14:00", "10-22 14:00", "10-24 14:00", "10-26 14:00"]  # DAILY;INTERVAL=2;UNTIL
    assert not any(title == "Cancelled sync" for _, title, _ in evs)
    long = next(e for e in evs if e[1].startswith("1:1"))
    assert long[0] == "10-22 11:30" and long[1].endswith("across the panel")  # Windows TZID + unfolding
    loc = calendar_p.events_between(ICS, ts(2026, 10, 20), ts(2026, 10, 21))
    assert any(e["location"] == "Room 4; 2nd floor" for e in loc)


def test_vtimezone_fallback_matches_rules() -> None:
    comps = calendar_p.components(calendar_p.unfold(ICS))
    vtz = next(c for c in comps[0]["children"] if c["type"] == "VTIMEZONE")
    fn = calendar_p.vtimezone_offset(vtz)
    assert fn(ts(2026, 7, 1)) == 7200 and fn(ts(2026, 12, 1)) == 3600
    assert fn(ts(2026, 3, 29, 0, 59)) == 3600 and fn(ts(2026, 3, 29, 1, 0)) == 7200


def test_ics_lexing() -> None:
    assert calendar_p.parse_line('DTSTART;TZID="A: B":20260101T000000') == (
        "DTSTART",
        {"TZID": "A: B"},
        "20260101T000000",
    )
    assert calendar_p.unescape("a\\, b\\; c\\nd\\\\") == "a, b; c\nd\\"
    assert calendar_p.parse_duration("P1DT2H30M").total_seconds() == 95400
    assert calendar_p.parse_duration("-PT15M").total_seconds() == -900
    assert calendar_p.split_urls("webcal://x/a.ics\n https://y/b.ics , junk") == [
        "webcal://x/a.ics",
        "https://y/b.ics",
    ]


def test_calendar_provider_hides_urls() -> None:
    secret = "https://calendar.example.com/private-SECRET123/basic.ics"

    def handler(r: httpx.Request) -> httpx.Response:
        if "bad" in str(r.url):
            return httpx.Response(500)
        return httpx.Response(200, text=ICS)

    hub = mock_hub(handler)
    p = calendar_p.CalendarProvider(hub)
    p.want([secret, "webcal://bad.example.com/private-OTHER/x.ics"], 12)
    d = asyncio.run(p.fetch())
    assert d["calendars"] == 2 and len(d["errors"]) == 1
    assert "SECRET" not in json.dumps(d) and "OTHER" not in json.dumps(d)
    p.want(["https://bad.example.com/private-OTHER/y.ics"], 12)
    with pytest.raises(RuntimeError) as err:
        asyncio.run(p.fetch())
    assert "OTHER" not in str(err.value)
    asyncio.run(hub.http.aclose())


def test_calendar_focus_and_status() -> None:
    soon = copy.deepcopy(calendar_data())
    soon["events"] = [e for e in soon["events"] if e["start"] > time.time()]
    soon["events"][0]["start"] = time.time() + 120
    app = make(
        calendar_app.Calendar, {"urls": "https://x/s.ics", "take_over_minutes": 5}, {"calendar": Prov(soon)}
    )
    assert app.watches_focus() and app.wants_focus()
    st = app.status()
    assert st["next"]["title"].startswith("Design") and "x/s.ics" not in json.dumps(st)
    assert app.ctx.providers["calendar"].wanted == (["https://x/s.ics"], 12)
    off = make(
        calendar_app.Calendar, {"urls": "https://x/s.ics", "take_over": False}, {"calendar": Prov(soon)}
    )
    assert not off.wants_focus()
    assert calendar_app.countdown(59) == "0M" and calendar_app.countdown(3900) == "1H05"
    assert calendar_app.countdown(30 * 3600) == "30H" and calendar_app.countdown(3 * 86400) == "3D"
