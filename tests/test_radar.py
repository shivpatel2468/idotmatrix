"""Flight radar: source parsing (fixtures, no network), geometry, blip coordinates, rendering and actions."""

from __future__ import annotations

import itertools
import math
import time
from typing import Any

import pytest

from dotdeck.apps.radar import Radar, RadarSettings, alt_label, beam, scope_xy, to_pixel
from dotdeck.gfx import Frame
from dotdeck.providers.flights import (
    FlightsProvider,
    bearing_deg,
    distance_nm,
    parse_opensky,
    parse_readsb,
    parse_route,
)

HOME = (19.0748, 72.8856)

READSB = {
    "now": 1790201277.0,
    "ac": [
        {
            "hex": "781666",
            "flight": "CSN633  ",
            "r": "B-209X",
            "t": "B789",
            "alt_baro": 34000,
            "gs": 515.4,
            "track": 239.7,
            "baro_rate": 32,
            "squawk": "0440",
            "lat": 18.999132,
            "lon": 72.716059,
            "seen_pos": 0.1,
        },
        {"hex": "80158a", "flight": "IGO536M ", "alt_baro": "ground", "gs": 12, "lat": 19.09, "lon": 72.87},
        {
            "hex": "~abc123",
            "alt_geom": 15800,
            "geom_rate": -640,
            "lat": 19.3,
            "lon": 73.1,
            "true_heading": 90,
        },
        {"hex": "nopos", "flight": "GHOST1", "alt_baro": 30000},  # no position: dropped
        {"hex": "stale", "flight": "OLD1", "alt_baro": 30000, "lat": 19.0, "lon": 72.0, "seen_pos": 300},
    ],
}

OPENSKY = {
    "time": 1790201277,
    "states": [
        [
            "801672",
            "AIC1SK  ",
            "India",
            1790201276,
            1790201276,
            73.175,
            18.6298,
            4724.4,
            False,
            139.9,
            336.83,
            -4.55,
            None,
            4914.9,
            "2703",
            False,
            0,
        ],
        [
            "800001",
            "",
            "India",
            1790201270,
            1790201276,
            72.88,
            19.08,
            None,
            True,
            3.0,
            90.0,
            None,
            None,
            None,
            None,
            False,
            0,
        ],
        [
            "800002",
            "NOPOS",
            "India",
            None,
            1790201276,
            None,
            None,
            1000.0,
            False,
            100.0,
            0.0,
            0.0,
            None,
            None,
            None,
            False,
            0,
        ],
    ],
}

ADSBDB = {
    "response": {
        "flightroute": {
            "callsign": "UAE500",
            "callsign_iata": "EK500",
            "airline": {"name": "Emirates", "icao": "UAE", "iata": "EK"},
            "origin": {
                "iata_code": "DXB",
                "icao_code": "OMDB",
                "name": "Dubai International Airport",
                "municipality": "Dubai",
                "country_iso_name": "AE",
            },
            "destination": {
                "iata_code": "BOM",
                "icao_code": "VABB",
                "name": "Chhatrapati Shivaji International",
                "municipality": "Mumbai",
                "country_iso_name": "IN",
            },
        }
    }
}

KEYS = {
    "id",
    "callsign",
    "lat",
    "lon",
    "alt_ft",
    "speed_kt",
    "track",
    "vrate",
    "type",
    "reg",
    "squawk",
    "dist_nm",
    "bearing_deg",
    "ground",
}


# ------------------------------------------------------------------ geometry
def test_distance_and_bearing() -> None:
    assert distance_nm(0, 0, 1, 0) == pytest.approx(60.04, abs=0.1)  # one degree of latitude ~ 60 nm
    assert distance_nm(*HOME, *HOME) == 0
    assert bearing_deg(0, 0, 1, 0) == pytest.approx(0, abs=1e-6)
    assert bearing_deg(0, 0, 0, 1) == pytest.approx(90, abs=1e-6)
    assert bearing_deg(0, 0, -1, 0) == pytest.approx(180, abs=1e-6)
    assert bearing_deg(0, 0, 0, -1) == pytest.approx(270, abs=1e-6)
    # Mumbai -> Delhi: ~610 nm, a little east of north
    assert distance_nm(*HOME, 28.5665, 77.1031) == pytest.approx(610, abs=15)
    assert 15 < bearing_deg(*HOME, 28.5665, 77.1031) < 30


def test_scope_mapping_north_up() -> None:
    assert scope_xy(0, 0, 30) == (16.0, 16.0)
    x, y = scope_xy(30, 0, 30)  # at range, due north: top edge
    assert to_pixel(x, y) == (16, 1)
    assert to_pixel(*scope_xy(30, 90, 30))[0] == 31  # east: right edge
    assert to_pixel(*scope_xy(30, 180, 30))[1] == 31
    assert to_pixel(*scope_xy(30, 270, 30))[0] == 1
    for d, b in itertools.product((0, 1, 7.5, 15, 29.9, 30), range(0, 360, 7)):
        px, py = to_pixel(*scope_xy(d, b, 30))
        assert 0 <= px <= 31 and 0 <= py <= 31
    assert to_pixel(-5, 99) == (0, 31)  # clamped


def test_beam_stays_on_panel() -> None:
    for th in (0, 0.3, math.pi / 2, 2, math.pi, 5.9):
        b = beam(th)
        assert b.shape == (32, 32) and b.max() <= 1.0 and b.max() > 0.5


def test_alt_label() -> None:
    assert alt_label({"alt_ft": 34000}) == "FL340"
    assert alt_label({"alt_ft": 6850}) == "6850FT"
    assert alt_label({"ground": True, "alt_ft": 0}) == "GND"
    assert alt_label({"alt_ft": None}) == "---"


# ------------------------------------------------------------------- parsing
def test_parse_readsb() -> None:
    ac = parse_readsb(READSB, HOME)
    assert [a["id"] for a in ac] == ["80158a", "781666", "abc123"]  # nearest first, bad rows dropped
    for a in ac:
        assert set(a) == KEYS
    gnd, csn, anon = ac
    assert gnd["ground"] is True and gnd["alt_ft"] == 0
    assert csn["callsign"] == "CSN633" and csn["alt_ft"] == 34000 and csn["type"] == "B789"
    assert csn["reg"] == "B-209X" and csn["squawk"] == "0440" and csn["speed_kt"] == 515
    assert 200 < csn["bearing_deg"] < 250 and 8 < csn["dist_nm"] < 12
    assert anon["alt_ft"] == 15800 and anon["vrate"] == -640 and anon["track"] == 90
    assert anon["callsign"] == "ABC123"  # falls back to the hex id
    assert parse_readsb({}, HOME) == [] and parse_readsb({"ac": None}, HOME) == []


def test_parse_opensky() -> None:
    ac = parse_opensky(OPENSKY, HOME)
    assert [a["id"] for a in ac] == ["800001", "801672"]
    gnd, aic = ac
    assert gnd["ground"] and gnd["alt_ft"] == 0
    assert aic["callsign"] == "AIC1SK" and aic["squawk"] == "2703"
    assert aic["alt_ft"] == round(4724.4 * 3.28084)
    assert aic["speed_kt"] == round(139.9 * 1.943844)
    assert aic["vrate"] == round(-4.55 * 196.8504)
    assert set(aic) == KEYS
    assert parse_opensky({"states": None}, HOME) == []


def test_parse_route() -> None:
    r = parse_route(ADSBDB)
    assert r is not None
    assert (
        r["airline"] == "Emirates" and r["origin"]["iata"] == "DXB" and r["destination"]["city"] == "Mumbai"
    )
    assert parse_route({"response": "unknown callsign"}) is None
    assert parse_route({}) is None


# ------------------------------------------------------------------ provider
class _Resp:
    def __init__(self, status: int, data: Any) -> None:
        self.status_code, self._data = status, data

    def json(self) -> Any:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            req = httpx.Request("GET", "http://x")
            raise httpx.HTTPStatusError(
                "boom", request=req, response=httpx.Response(self.status_code, request=req)
            )


class _Http:
    def __init__(self, routes: dict[str, _Resp]) -> None:
        self.routes, self.calls = routes, []

    async def get(self, url: str, params: Any = None) -> _Resp:
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise AssertionError(f"unexpected request {url}")


class _Store:
    def get(self, key: str, default: Any = None) -> Any:
        return {"location": {"lat": HOME[0], "lon": HOME[1], "city": "Mumbai"}}.get(key, default)


class _Hub:
    def __init__(self, http: _Http) -> None:
        self.http, self.store, self.providers, self.changes = http, _Store(), {}, []

    def on_change(self, name: str) -> None:
        self.changes.append(name)


async def test_provider_fallback_and_bench() -> None:
    http = _Http(
        {"adsb.lol": _Resp(403, {}), "airplanes.live": _Resp(429, {}), "opensky": _Resp(200, OPENSKY)}
    )
    p = FlightsProvider(_Hub(http))  # type: ignore[arg-type]
    v = await p.fetch()
    assert v["source"] == "opensky" and len(v["aircraft"]) == 2
    assert v["center"] == {"lat": HOME[0], "lon": HOME[1], "city": "Mumbai"}
    assert set(v) == {"center", "radius_nm", "aircraft", "source", "updated"}
    n = len(http.calls)
    await p.fetch()  # benched sources are skipped
    assert len(http.calls) == n + 1 and "opensky" in http.calls[-1]


async def test_provider_readsb_and_all_down() -> None:
    http = _Http({"adsb.lol": _Resp(200, READSB)})
    p = FlightsProvider(_Hub(http))  # type: ignore[arg-type]
    p.configure(60)
    v = await p.fetch()
    assert v["source"] == "adsb.lol" and "/v2/point/19.0748/72.8856/71" in http.calls[0]
    down = FlightsProvider(_Hub(_Http({"": _Resp(500, {})})))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="no ADS-B source"):
        await down.fetch()


def test_announce_only_on_set_change() -> None:
    p = FlightsProvider(_Hub(_Http({})))  # type: ignore[arg-type]
    a = {"aircraft": [{"id": "a"}, {"id": "b"}], "source": "adsb.lol"}
    moved = {"aircraft": [{"id": "b"}, {"id": "a"}], "source": "adsb.lol"}
    assert p.announce(None, a)
    assert not p.announce(a, moved)
    assert p.announce(a, {"aircraft": [{"id": "a"}], "source": "adsb.lol"})


async def test_route_cached_including_misses() -> None:
    http = _Http({"UAE500": _Resp(200, ADSBDB), "IGO6E": _Resp(404, {"response": "unknown callsign"})})
    p = FlightsProvider(_Hub(http))  # type: ignore[arg-type]
    p.ROUTE_GAP = 0.0
    r = await p.route("uae500 ")
    assert r and r["destination"]["iata"] == "BOM"
    assert await p.route("UAE500") == r
    assert await p.route("IGO6E") is None
    assert await p.route("IGO6E") is None
    assert len(http.calls) == 2  # one per callsign, misses cached
    assert p.cached_route("UAE500") == r and p.route_known("IGO6E")
    assert await p.route("") is None and await p.route("BAD/../X") is None


# ------------------------------------------------------------------------ app
class _Prov:
    name = "flights"

    def __init__(self, value: Any = None, error: str | None = None) -> None:
        self.value, self.error, self.configured = value, error, None
        self.hub = _Hub(_Http({}))
        self.looked_up: list[str] = []

    def configure(self, r: float) -> None:
        self.configured = r

    def cached_route(self, cs: str) -> Any:
        return {"origin": {"iata": "DEL"}, "destination": {"iata": "JFK"}} if cs == "AIC101" else None

    def route_known(self, cs: str) -> bool:
        return False

    async def route(self, cs: str) -> Any:
        self.looked_up.append(cs)
        return self.cached_route(cs)


class _Ctx:
    def __init__(self, prov: Any) -> None:
        self.p = prov

    def provider(self, name: str) -> Any:
        if self.p is None:
            raise KeyError(name)
        return self.p


def _value(n: int = 8) -> dict[str, Any]:
    ac = []
    for i in range(n):
        ac.append(
            {
                "id": f"a{i}",
                "callsign": "AIC101" if i == 0 else f"TST{i}",
                "lat": 0,
                "lon": 0,
                "alt_ft": 1000 + i * 5000,
                "speed_kt": 200 + i * 30,
                "track": i * 45.0,
                "vrate": (-1) ** i * 800,
                "type": "A320",
                "reg": "",
                "squawk": "",
                "dist_nm": 2.0 + i * 3.5,
                "bearing_deg": i * 47.0 % 360,
                "ground": i == 7,
            }
        )
    return {
        "center": {"lat": 0, "lon": 0, "city": "X"},
        "radius_nm": 40,
        "aircraft": ac,
        "source": "t",
        "updated": time.time(),
    }


def _variants() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{}]
    for name, field in RadarSettings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            out += [{name: v} for v in extra["enum"]]
    out += [
        {"show_labels": False},
        {"trails": False},
        {"rotate_labels": True},
        {"hide_ground": False},
        {"min_altitude_ft": 20000},
        {"range_nm": 5},
        {"range_nm": 150, "sweep_speed": 30},
    ]
    out += [{"layout": "list", "theme": th} for th in ("amber", "military")]
    return out


@pytest.mark.parametrize("settings", _variants(), ids=str)
@pytest.mark.parametrize("state", ["none", "missing", "error", "empty", "data"])
def test_render_variants(settings: dict[str, Any], state: str) -> None:
    prov = {
        "none": _Prov(),
        "missing": None,
        "error": _Prov(error="boom"),
        "empty": _Prov({**_value(), "aircraft": []}),
        "data": _Prov(_value()),
    }[state]
    app = Radar(_Ctx(prov), RadarSettings(**settings))  # type: ignore[arg-type]
    worst = 0.0
    for t in (0.0, 0.37, 1.9, 7.3, 13.1):
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, t)
        worst = max(worst, time.perf_counter() - t0)
        assert f.px.shape == (32, 32, 3)
        assert f.px.any()  # never a blank panel
    assert worst < 0.05


def test_status_blips_on_panel_and_filters() -> None:
    app = Radar(_Ctx(_Prov(_value())), RadarSettings(range_nm=30))  # type: ignore[arg-type]
    st = app.status()
    ids = [b["id"] for b in st["blips"]]
    assert "a7" not in ids  # on the ground, hidden by default
    assert st["count"] == len(ids) > 0 and st["selected"] is None
    for b in st["blips"]:
        assert 0 <= b["x"] <= 31 and 0 <= b["y"] <= 31
        assert set(b) == {"id", "callsign", "x", "y", "alt_ft", "speed_kt", "type"}
    assert app.contacts()[0]["id"] == "a0"
    app.settings = RadarSettings(range_nm=30, min_altitude_ft=20000)
    assert all(b["alt_ft"] >= 20000 for b in app.status()["blips"])
    app.settings = RadarSettings(range_nm=5)
    assert all(c["dist_now"] <= 5 for c in app.contacts())


def test_configure_on_start() -> None:
    prov = _Prov()
    app = Radar(_Ctx(prov), RadarSettings(range_nm=80))  # type: ignore[arg-type]
    app.on_start()
    assert prov.configured == 80


async def test_select_clear_next() -> None:
    prov = _Prov(_value())
    app = Radar(_Ctx(prov), RadarSettings())  # type: ignore[arg-type]
    sel = await app.action("select", {"id": "a0"})
    assert sel["id"] == "a0" and sel["route"]["origin"]["iata"] == "DEL"
    assert 0 <= sel["x"] <= 31 and 0 <= sel["y"] <= 31
    import asyncio

    await asyncio.sleep(0)  # let the fire-and-forget lookup run
    await asyncio.sleep(0)
    assert prov.looked_up == ["AIC101"]
    f = Frame()
    app.render(f, 1.0)  # selected blink + brackets render
    assert app.status()["selected"]["callsign"] == "AIC101"
    nxt = await app.action("next", {})
    assert nxt["id"] != "a0"
    await app.action("select", {"id": "gone"})
    assert app.status()["selected"] == {"id": "gone", "lost": True}
    assert await app.action("clear", {}) is None
    assert app.status()["selected"] is None
    with pytest.raises(KeyError):
        await app.action("nope", {})


def test_meta() -> None:
    m = Radar.meta()
    assert m.id == "radar" and m.category == "data" and m.icon == "radar"
    assert Radar.uses == ("flights",) and Radar.fps == 10.0
    RadarSettings()
    with pytest.raises(ValueError):
        RadarSettings(theme="nope")
