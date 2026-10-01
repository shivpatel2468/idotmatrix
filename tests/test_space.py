"""Space & Sky: parsers on trimmed real captures, the orbit/astronomy maths, providers over a mock transport,
and every screen of the Space and Sun & Moon apps (with data, loading and offline)."""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from dotdeck.apps.sky import Sky, SkySettings, dur_text, moon_disc, sky_colors
from dotdeck.apps.space import (
    Space,
    SpaceSettings,
    countdown_text,
    hyphen_wrap,
    page_len,
    pick_page,
)
from dotdeck.config import Store
from dotdeck.gfx import Frame, measure
from dotdeck.providers.base import Hub
from dotdeck.providers.sky import (
    SkyProvider,
    moon_phase,
    moon_phase_time,
    next_phase,
    parse_open_meteo,
    parse_sunrise_sunset,
    phase_name,
    subsolar_point,
    sun_events,
    sun_position,
)
from dotdeck.providers.space import (
    IssProvider,
    Orbit,
    SpaceProvider,
    ascii_text,
    fit_rate,
    haversine_km,
    next_pass,
    parse_iss,
    parse_launches,
    parse_news,
    parse_people_corquaid,
    parse_people_open_notify,
    provider_abbr,
    throttle_seconds,
)

FIX = Path(__file__).parent / "fixtures" / "space"
MUMBAI = {"city": "Mumbai", "lat": 19.0760, "lon": 72.8777, "country": "IN"}


def fx(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ parsers
def test_parse_launches() -> None:
    ls = parse_launches(fx("ll2_upcoming.json"))
    assert len(ls) == 5
    assert [x["net"] for x in ls] == sorted(x["net"] for x in ls)
    first = ls[0]
    assert first["rocket"] == "Long March 8A" and first["mission"] == "SatNet LEO Group 26"
    assert first["provider_abbr"] == "CASC" and first["status"] == "SUCCESS" and first["precision"] == "MIN"
    electron = next(x for x in ls if x["rocket"] == "Electron")
    assert electron["provider_abbr"] == "ROCKETLAB" and electron["status"] == "GO"
    assert electron["location"].startswith("Rocket Lab Launch Complex 1")
    assert parse_launches({"results": [{"name": "x"}, "junk"]}) == []  # no NET: dropped


def test_ascii_and_abbr() -> None:
    assert (
        ascii_text("ESA Awards RFA €2.7 Million — Ångström “ok”")
        == 'ESA Awards RFA EUR2.7 Million - Angstrom "ok"'
    )
    assert ascii_text(None) == ""
    assert provider_abbr("SpaceX") == "SPACEX"
    assert provider_abbr("HyImpulse") == "HYIMPULSE"
    assert provider_abbr("Some Very Long Space Agency") == "SVLSA"


def test_parse_people() -> None:
    p = parse_people_corquaid(fx("people_corquaid.json"))
    assert p["number"] == 10 and p["source"] == "corquaid"
    stations = [x["station"] for x in p["people"]]
    assert stations.count("ISS") == 7 and stations.count("TIANGONG") == 3
    o = parse_people_open_notify(fx("astros_open_notify.json"))
    assert o["number"] == len(o["people"]) == 12
    assert {x["station"] for x in o["people"]} == {"ISS", "TIANGONG"}
    with pytest.raises(ValueError):
        parse_people_corquaid({"people": []})


def test_parse_news_and_iss() -> None:
    n = parse_news(fx("snapi_articles.json"))
    assert len(n) == 4 and all(a["title"] and a["site"] and a["published"] for a in n)
    assert "EUR2.7" in n[0]["title"]
    i = parse_iss(fx("iss_now.json"))
    assert -52 < i["lat"] < 52 and 380 < i["alt_km"] < 450 and 27000 < i["vel_kmh"] < 28000


def test_throttle_seconds() -> None:
    r = httpx.Response(429, json={"detail": "Request was throttled. Expected available in 1234 seconds."})
    assert throttle_seconds(r) == 1234
    assert throttle_seconds(httpx.Response(429, headers={"Retry-After": "90"})) == 90
    assert throttle_seconds(httpx.Response(429, text="nope")) == 900


# ------------------------------------------------------------------- orbit
def test_orbit_model_matches_wheretheiss() -> None:
    pos = fx("iss_positions.json")
    track = [(p["timestamp"], p["latitude"], p["longitude"]) for p in pos]
    asc, _ = fit_rate(track[:2])
    a = pos[0]
    orb = Orbit(a["timestamp"], a["latitude"], a["longitude"], asc, a["altitude"], None)
    la, lo = orb.at([p["timestamp"] for p in pos[1:]])
    err = haversine_km([p["latitude"] for p in pos[1:]], [p["longitude"] for p in pos[1:]], la, lo)
    assert float(np.max(err)) < 150.0  # km, over 15 minutes


def test_fit_rate_recovers_period_and_pass() -> None:
    truth = Orbit(1_790_000_000.0, 10.0, 20.0, True, 420.0, 2 * math.pi / (92.9 * 60))
    ts = [1_790_000_000.0 - 3000 + 60 * i for i in range(51)]
    la, lo = truth.at(ts)
    asc, rate = fit_rate(list(zip(ts, la.tolist(), lo.tolist(), strict=True)))
    assert asc is True or asc is False
    assert rate is not None and abs(2 * math.pi / rate / 60 - 92.9) < 0.3
    # an observer right under the track in 20 minutes sees a pass then
    la2, lo2 = truth.at([1_790_000_000.0 + 1200])
    np_ = next_pass(truth, 1_790_000_000.0, float(la2[0]), float(lo2[0]))
    assert np_ is not None and abs(np_["peak"] - (1_790_000_000.0 + 1200)) < 90 and np_["max_elev"] > 80


# --------------------------------------------------------------- astronomy
def test_sun_events_match_sunrise_sunset_org() -> None:
    api = parse_sunrise_sunset(fx("sunrise_sunset.json"))
    ev = sun_events(date(2026, 9, 24), MUMBAI["lat"], MUMBAI["lon"], 19800)
    for k in ("sunrise", "sunset", "noon", "civil_begin", "civil_end"):
        assert abs(ev[k] - api[k]) < 120, k
    assert abs(ev["day_length"] - api["day_length"]) < 240
    g0, g1 = ev["golden_pm"]
    b0, b1 = ev["blue_pm"]
    assert g0 < ev["sunset"] < g1 == b0 < b1 == ev["civil_end"]
    # polar night / day
    assert sun_events(date(2026, 12, 21), 80.0, 0.0, 0)["polar"] == "night"
    assert sun_events(date(2026, 6, 21), 80.0, 0.0, 0)["polar"] == "day"


def test_sun_position_and_subsolar() -> None:
    iss = fx("iss_now.json")  # wheretheiss reports the subsolar point too
    lat, lon = subsolar_point(iss["timestamp"])
    assert abs(lat - iss["solar_lat"]) < 0.1 and abs(lon - iss["solar_lon"]) < 0.3
    alt, _ = sun_position(iss["timestamp"], iss["solar_lat"], iss["solar_lon"])
    assert alt > 89.5


def test_moon_phases_known_dates() -> None:
    def ts(*a: int) -> float:
        return datetime(*a, tzinfo=UTC).timestamp()

    # 2024-04-08 18:21 UTC total eclipse new moon, 2024-04-23 23:49 UTC full moon
    assert abs(next_phase(ts(2024, 4, 1), full=False) - ts(2024, 4, 8, 18, 21)) < 180
    assert abs(next_phase(ts(2024, 4, 15), full=True) - ts(2024, 4, 23, 23, 49)) < 180
    assert abs(moon_phase_time(0) - ts(2000, 1, 6, 18, 14)) < 180
    m = moon_phase(ts(2024, 4, 23, 23, 49))
    assert m["illumination"] > 0.99 and m["name"] == "FULL MOON"
    m = moon_phase(ts(2024, 4, 12))
    assert m["waxing"] and m["name"] == "WAXING CRESCENT" and 0.05 < m["illumination"] < 0.3
    assert phase_name(0.5) == "FULL MOON" and phase_name(0.8) == "WANING CRESCENT"


def test_parse_open_meteo() -> None:
    om = parse_open_meteo(fx("open_meteo_sun.json"))
    assert om["tz_offset"] == 19800 and om["tz"] == "Asia/Kolkata"
    day = om["days"]["2026-09-24"]
    assert abs(day["sunrise"] - parse_sunrise_sunset(fx("sunrise_sunset.json"))["sunrise"]) < 120
    bad = {"status": "OK", "results": {"sunrise": "1970-01-01T00:00:01+00:00", "day_length": 0}}
    assert parse_sunrise_sunset(bad)["sunrise"] is None


# ---------------------------------------------------------------- providers
def _hub(tmp_path: Path, handler: Any) -> Hub:
    hub = Hub(Store(tmp_path / "state.json"), lambda _n: None)
    hub.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def location() -> dict[str, Any]:
        return dict(MUMBAI)

    hub.location = location  # type: ignore[method-assign]
    return hub


async def test_space_provider_fetch_and_rate_limit(tmp_path: Path) -> None:
    calls: list[str] = []
    limited = {"on": False}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if "thespacedevs" in req.url.host:
            if limited["on"]:
                return httpx.Response(429, json={"detail": "Expected available in 2000 seconds."})
            return httpx.Response(200, json=fx("ll2_upcoming.json"))
        if "corquaid" in req.url.host:
            return httpx.Response(500)
        if "open-notify" in req.url.host:
            return httpx.Response(200, json=fx("astros_open_notify.json"))
        return httpx.Response(200, json=fx("snapi_articles.json"))

    hub = _hub(tmp_path, handler)
    p = SpaceProvider(hub)
    p.want(("launch", "people", "news"), "rocketlab")
    v = await p.fetch()
    p.value = v
    assert set(v["launches"]) == {"any", "rocketlab"}
    assert v["people"]["data"]["source"] == "open-notify"  # corquaid failed -> fallback
    assert len(v["news"]["items"]) == 4
    n = len(calls)
    assert await p.fetch() == v and len(calls) == n  # nothing due: no requests
    # a 429 benches every launch list for at least 15 min and keeps the cached lists
    for k in list(p._due):
        p._due[k] = 0.0
    limited["on"] = True
    v2 = await p.fetch()
    assert v2["launches"] == v["launches"] and "launch:any" in v2["errors"]
    assert p._due["launch:spacex"] >= time.time() + 1900
    await hub.http.aclose()


async def test_iss_provider(tmp_path: Path) -> None:
    now = fx("iss_now.json")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/positions"):
            stamps = [int(x) for x in req.url.params["timestamps"].split(",")]
            orb = Orbit(now["timestamp"], now["latitude"], now["longitude"], False, 420.0, None)
            la, lo = orb.at(stamps)
            return httpx.Response(
                200,
                json=[
                    {"timestamp": s, "latitude": float(a), "longitude": float(b)}
                    for s, a, b in zip(stamps, la, lo, strict=True)
                ],
            )
        return httpx.Response(200, json={**now, "timestamp": time.time()})

    hub = _hub(tmp_path, handler)
    p = IssProvider(hub)
    v = await p.fetch()
    assert len(v["track"]) >= 5 and len(v["ahead"]) > 60
    assert v["user"]["city"] == "Mumbai" and v["dist_km"] > 0
    assert p.announce(None, v) and not p.announce(v, {**v, "ts": v["ts"] + 1 - v["ts"] % 60 + 5})
    p.fast = False
    assert p.next_interval() == 60.0
    await hub.http.aclose()


async def test_sky_provider_and_fallback(tmp_path: Path) -> None:
    ok = {"on": True}

    def handler(req: httpx.Request) -> httpx.Response:
        if not ok["on"]:
            raise httpx.ConnectError("down")
        if "open-meteo" in req.url.host:
            return httpx.Response(200, json=fx("open_meteo_sun.json"))
        return httpx.Response(200, json=fx("sunrise_sunset.json"))

    hub = _hub(tmp_path, handler)
    p = SkyProvider(hub)
    v = await p.fetch()
    assert v["tz_offset"] == 19800 and v["sources"]
    assert len(v["days"]) == 2 and v["today"] in v["days"]
    ok["on"] = False  # offline: local maths only, still a full value
    p2 = SkyProvider(hub)
    v2 = await p2.fetch()
    assert v2["sources"] == ["local"] and v2["days"][v2["today"]]["sunrise"] is not None
    await hub.http.aclose()


# --------------------------------------------------------------------- apps
class FakeProvider:
    def __init__(self, name: str, value: Any = None, error: str | None = None) -> None:
        self.name, self.value, self.error = name, value, error
        self.wanted: list[Any] = []
        self.fast = True

    def want(self, *a: Any) -> None:
        self.wanted.append(a)


class Ctx:
    def __init__(self, provs: dict[str, Any]) -> None:
        self.provs = provs

    def provider(self, name: str) -> Any:
        if name not in self.provs:
            raise KeyError(name)
        return self.provs[name]

    def invalidate(self) -> None: ...


def _space_value(net_shift: float | None = None, **kw: Any) -> dict[str, Any]:
    now = time.time()
    items = parse_launches(fx("ll2_upcoming.json"))
    if net_shift is not None:
        items[0].update({"net": now + net_shift, "precision": "MIN", **kw})
        items = [items[0]] + [dict(x, net=now + 86400 * (i + 2)) for i, x in enumerate(items[1:])]
    else:
        for i, x in enumerate(items):
            x["net"] = now + 3600 * (i + 1) * 13
    return {
        "launches": {"any": {"items": items, "updated": now}},
        "people": {"data": parse_people_corquaid(fx("people_corquaid.json")), "updated": now},
        "news": {"items": parse_news(fx("snapi_articles.json")), "updated": now},
        "errors": {},
    }


def _iss_value() -> dict[str, Any]:
    now = time.time()
    fix = parse_iss(fx("iss_now.json"))
    fix["ts"] = now
    orb = Orbit(now, fix["lat"], fix["lon"], False, fix["alt_km"], None)
    back = [now - 60 * i for i in range(40, 0, -1)]
    la, lo = orb.at(back)
    ah = [now + 60 * i for i in range(1, 90)]
    la2, lo2 = orb.at(ah)
    return {
        **fix,
        "track": list(zip(back, la.tolist(), lo.tolist(), strict=True)),
        "ahead": list(zip(ah, la2.tolist(), lo2.tolist(), strict=True)),
        "user": {"city": "Mumbai", "lat": MUMBAI["lat"], "lon": MUMBAI["lon"]},
        "dist_km": 5000.0,
        "elev_deg": -20.0,
        "next_pass": {
            "start": now + 1800,
            "end": now + 2100,
            "max_elev": 40.0,
            "peak": now + 1950,
            "now": False,
        },
    }


def _render(app: Any, ts: tuple[float, ...] = (0.0, 1.3, 2.7, 5.5, 9.1)) -> list[Frame]:
    out = []
    for t in ts:
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, t)
        assert time.perf_counter() - t0 < 0.05
        out.append(f)
    return out


@pytest.mark.parametrize("mode", ["launch", "iss", "people", "news", "rotate"])
@pytest.mark.parametrize("state", ["data", "loading", "offline", "missing"])
def test_space_screens(mode: str, state: str) -> None:
    provs: dict[str, Any] = {}
    if state == "data":
        provs = {"space": FakeProvider("space", _space_value()), "iss": FakeProvider("iss", _iss_value())}
    elif state != "missing":
        err = "ConnectError" if state == "offline" else None
        provs = {"space": FakeProvider("space", None, err), "iss": FakeProvider("iss", None, err)}
    app = Space(Ctx(provs), SpaceSettings(mode=mode))
    frames = _render(app)
    assert any(f.px.any() for f in frames)
    json.dumps(app.status())


@pytest.mark.parametrize(
    ("shift", "kw", "fast"),
    [
        (42.0, {}, True),
        (-3.0, {}, True),
        (-400.0, {}, True),
        (3 * 86400.0, {"status": "HOLD"}, False),
        (5000.0, {"precision": "HR"}, False),
        (9 * 86400.0, {"precision": "DAY", "status": "TBD"}, False),
    ],
)
def test_launch_phases(shift: float, kw: dict[str, Any], fast: bool) -> None:
    sp = FakeProvider("space", _space_value(shift, **kw))
    app = Space(Ctx({"space": sp}), SpaceSettings(mode="launch", take_over=True))
    frames = _render(app, (0.0, 0.4))
    assert frames[0].px.any()
    st = app.status()["next_launch"]
    assert st["t_minus_s"] == pytest.approx(shift, abs=2)
    if shift < 0:
        assert st["t_minus"].startswith("T+")
    assert app.wants_focus() == (-120 < shift <= 60)
    assert sp.wanted and sp.wanted[-1][1] == "any"


def test_rotate_pins_the_final_minute_and_status() -> None:
    provs = {"space": FakeProvider("space", _space_value(30.0)), "iss": FakeProvider("iss", _iss_value())}
    app = Space(Ctx(provs), SpaceSettings(mode="rotate", rotate_seconds=5))
    assert {app.screen(t) for t in (0, 5, 10, 15)} == {"launch"}
    s = app.status()
    assert s["iss"]["next_pass_in_min"] == 30 and s["people"]["count"] == 10 and s["latest_headline"]["title"]


def test_launch_filter_falls_back_to_any_list() -> None:
    sp = FakeProvider("space", _space_value())
    app = Space(Ctx({"space": sp}), SpaceSettings(mode="launch", launch_filter="rocketlab"))
    nl = app.next_launch()
    assert nl is not None and nl["provider"] == "Rocket Lab"


def test_space_helpers() -> None:
    assert countdown_text(3 * 86400 + 3723) == "3D 01:02:03"
    assert countdown_text(-95) == "T+01:35"
    lines = hyphen_wrap("RECORD PARTICIPATION IN ESA'S INDUSTRY SPACE DAYS")
    assert all(measure(x) <= 30 for x in lines) and lines[1].endswith("-")
    items = [("SHORT", (1, 1, 1)), ("A MUCH LONGER CAPTION THAT SCROLLS", (1, 1, 1))]
    assert pick_page(items, 0.1)[0] == 0 and pick_page(items, page_len("SHORT") + 0.1)[0] == 1


@pytest.mark.parametrize("layout", ["arc", "moon", "times", "combined"])
@pytest.mark.parametrize("hour", [3.0, 6.3, 12.0, 18.4, 18.7, 22.0])
def test_sky_layouts_through_the_day(layout: str, hour: float, monkeypatch: pytest.MonkeyPatch) -> None:
    ev = {
        "2026-09-24": sun_events(date(2026, 9, 24), MUMBAI["lat"], MUMBAI["lon"], 19800),
        "2026-09-25": sun_events(date(2026, 9, 25), MUMBAI["lat"], MUMBAI["lon"], 19800),
    }
    value = {
        **MUMBAI,
        "tz_offset": 19800.0,
        "tz": "Asia/Kolkata",
        "today": "2026-09-24",
        "days": ev,
        "sources": ["local"],
    }
    at = datetime(2026, 9, 24, tzinfo=UTC).timestamp() - 19800 + hour * 3600
    import dotdeck.apps.sky as sky_mod

    monkeypatch.setattr(sky_mod.time, "time", lambda: at)
    app = Sky(Ctx({"sky": FakeProvider("sky", value)}), SkySettings(layout=layout, hour24=hour < 12))
    for f in _render(app):
        assert f.px.any()
    st = app.status()
    assert st["sunrise"] in ("06:26", "06:27") and st["moon"]["phase"]


@pytest.mark.parametrize("state", ["loading", "offline", "missing"])
@pytest.mark.parametrize("layout", ["arc", "moon", "times", "combined"])
def test_sky_without_data(layout: str, state: str) -> None:
    provs = (
        {} if state == "missing" else {"sky": FakeProvider("sky", None, "x" if state == "offline" else None)}
    )
    app = Sky(Ctx(provs), SkySettings(layout=layout))
    assert all(f.px.any() for f in _render(app))
    assert "moon" in app.status()


def test_sky_helpers() -> None:
    assert dur_text(12 * 3600 + 7 * 60) == "12H07" and dur_text(42 * 60) == "42M"
    top, hor = sky_colors(-30)
    assert max(top + hor) < 12
    rgb, a = moon_disc(9.3, 500, False, 19)  # full moon: lit and symmetric in coverage
    assert a[9, 9] == 1.0 and a[0, 0] == 0.0 and rgb[9, 9].max() > 150
    rgb_new, _ = moon_disc(9.3, 0, False, 19)
    assert rgb_new.max() < 30
    wax, _ = moon_disc(9.3, 200, False, 19)  # waxing crescent: right side lit in the north
    assert wax[9, 15].max() > wax[9, 3].max()
    south, _ = moon_disc(9.3, 200, True, 19)
    assert south[9, 3].max() > south[9, 15].max()
