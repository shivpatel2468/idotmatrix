"""Planet apps: Earthquakes (USGS), Rain Radar (RainViewer), Air Quality (Open-Meteo), Holidays (Nager/Google/caldays).

Provider parsing runs on trimmed real captures in tests/fixtures/planet; provider fetches run against an
httpx.MockTransport; every app layout renders with and without data, bakes under the GIF budget and alerts once.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import io
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import numpy as np
import pytest
from pydantic import ValidationError

from deskdot.apps.airquality import US_BANDS, AirQuality, band, band_frac
from deskdot.apps.holidays import Holidays, auto_icon, clean_name
from deskdot.apps.quakes import Quakes, ago, fmt_km
from deskdot.apps.rainradar import RainRadar
from deskdot.gfx import Frame, measure
from deskdot.gfx.image import GIF_BUDGET, encode_gif_budget
from deskdot.providers import airquality as aq
from deskdot.providers import holidays as hol
from deskdot.providers import quakes as qk
from deskdot.providers import rainradar as rr

FIX = Path(__file__).parent / "fixtures" / "planet"
HOME = {"city": "Mumbai", "lat": 19.0760, "lon": 72.8777, "country": "IN"}
TODAY = dt.date(2026, 9, 24)


def load(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- fakes
class FakeHub:
    def __init__(self, handler: Any, loc: dict[str, Any] | None = None) -> None:
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.loc = loc or HOME

    async def location(self) -> dict[str, Any]:
        return dict(self.loc)


class Ctx:
    def __init__(self, **providers: Any) -> None:
        self.providers = providers
        self.notices: list[dict[str, Any]] = []

    def provider(self, name: str) -> Any:
        if name not in self.providers:
            raise KeyError(name)
        return self.providers[name]

    def notify(self, **kw: Any) -> None:
        self.notices.append(kw)


def fake_provider(value: Any, error: str | None = None, updated: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(value=value, error=error, updated=updated, want=lambda *a, **k: None)


def render_all(app: Any, ts: tuple[float, ...] = (0.0, 0.4, 1.3, 2.6, 7.7)) -> list[Frame]:
    out = []
    for t in ts:
        f = Frame()
        t0 = time.perf_counter()
        app.render(f, t)
        assert time.perf_counter() - t0 < 0.05
        assert f.px.shape == (32, 32, 3)
        out.append(f)
    return out


def choices(cls: type) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{}]
    for name, field in cls.Settings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            out += [{name: v} for v in extra["enum"]]
    return out


def bake_ok(app: Any) -> None:
    clip = app.clip_frames()
    assert 1 <= len(clip.frames) <= 260
    assert len(clip.durations_ms) == len(clip.frames)
    gif = encode_gif_budget(clip.frames, clip.durations_ms, app.clip_colors)
    assert len(gif) <= GIF_BUDGET


# =========================================================================== earthquakes
def quake_value() -> dict[str, Any]:
    feed = qk.parse_feed(load("usgs_2.5_day.json"), HOME)
    return {"home": HOME, "feeds": {"2.5_day": feed}}


def test_parse_usgs_feed() -> None:
    feed = qk.parse_feed(load("usgs_2.5_day.json"), HOME)
    qs = feed["quakes"]
    assert len(qs) == 14 and feed["title"].startswith("USGS")
    assert [q["time"] for q in qs] == sorted((q["time"] for q in qs), reverse=True)
    q = qs[0]
    assert {"id", "mag", "region", "area", "lat", "lon", "depth_km", "dist_km", "bearing"} <= set(q)
    assert q["time"] > 1.7e9  # seconds, not ms
    assert all(0 <= x["dist_km"] <= 20100 for x in qs)


def test_quake_helpers() -> None:
    assert qk.region_of("16 km SE of Karluk, Alaska") == "KARLUK, ALASKA"
    assert qk.area_of("10 km NE of Aguanga, CA") == "CALIF"
    assert qk.area_of("south of the Fiji Islands") == "SOUTH OF THE FIJI ISLANDS"
    assert qk.compass(44) == "NE" and qk.compass(359) == "N"
    assert abs(qk.distance_km(19.07, 72.88, 28.61, 77.21) - 1150) < 20  # Mumbai -> Delhi
    assert [ago(s) for s in (10, 300, 1700, 7300, 3 * 86400)] == ["NOW", "5M", "25M", "2H", "3D"]
    for km in (4.2, 620, 9911, 12345):
        assert measure(fmt_km(km, 20)) <= 20


def test_quake_feed_skips_events_without_magnitude() -> None:
    doc = load("usgs_2.5_day.json")
    doc["features"][0]["properties"]["mag"] = None
    assert len(qk.parse_feed(doc)["quakes"]) == 13


async def test_quakes_provider_fetch() -> None:
    doc = load("usgs_2.5_day.json")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/4.5_week.geojson") or req.url.path.endswith("/2.5_day.geojson")
        return httpx.Response(200, json=doc)

    p = qk.QuakesProvider(FakeHub(handler))
    p.want("2.5_day")
    p.want("4.5_week")
    p.want("bogus")
    v = await p.fetch()
    assert set(v["feeds"]) == {"2.5_day", "4.5_week"} and v["home"]["city"] == "Mumbai"
    assert p.announce(None, v) and not p.announce(v, v)
    await p.hub.http.aclose()


@pytest.mark.parametrize("settings", choices(Quakes), ids=str)
def test_quakes_renders_every_option(settings: dict[str, Any]) -> None:
    app = Quakes(Ctx(quakes=fake_provider(quake_value())), Quakes.Settings(**settings))
    render_all(app)
    assert app.kind() == ("clip" if app.settings.feed == "2.5_day" else "stream")  # fixture has one feed
    render_all(Quakes(Ctx(quakes=fake_provider(None)), Quakes.Settings(**settings)))
    render_all(Quakes(Ctx(quakes=fake_provider(None, "boom")), Quakes.Settings(**settings)))
    render_all(Quakes(Ctx(), Quakes.Settings(**settings)))  # provider not registered


@pytest.mark.parametrize("layout", ["world", "region", "card", "list"])
def test_quakes_clips_fit_budget(layout: str) -> None:
    app = Quakes(Ctx(quakes=fake_provider(quake_value())), Quakes.Settings(layout=layout))
    bake_ok(app)
    key = app.clip_key()
    assert key == app.clip_key()


def test_quakes_empty_feed_and_filter() -> None:
    app = Quakes(Ctx(quakes=fake_provider(quake_value())), Quakes.Settings(min_mag=9.0))
    for lay in ("world", "region", "card", "list"):
        app.settings = Quakes.Settings(min_mag=9.0, layout=lay)
        render_all(app)
    assert not app.relevant()


def test_quake_alert_arms_then_fires_once() -> None:
    v = quake_value()
    prov = fake_provider(v, updated=1.0)
    ctx = Ctx(quakes=prov)
    app = Quakes(ctx, Quakes.Settings(radius_km=5000, alert_mag=2.5))
    app.kind()  # first fetch arms: existing quakes never alert
    assert ctx.notices == []
    new = copy.deepcopy(v)
    q = dict(new["feeds"]["2.5_day"]["quakes"][0], id="new1", mag=5.8, dist_km=120.0, bearing=90.0)
    new["feeds"]["2.5_day"]["quakes"].insert(0, q)
    prov.value, prov.updated = new, 2.0
    app.kind()
    app.kind()  # same fetch: no duplicate
    prov.updated = 3.0
    app.kind()  # same event on the next fetch: still once
    assert len(ctx.notices) == 1 and "5.8" in ctx.notices[0]["title"]
    far = dict(q, id="far", dist_km=9000.0)
    new["feeds"]["2.5_day"]["quakes"].insert(0, far)
    prov.updated = 4.0
    app.kind()
    assert len(ctx.notices) == 1


# =========================================================================== air quality
def test_parse_air_mumbai_has_no_pollen() -> None:
    d = aq.parse_air(load("openmeteo_air_mumbai.json"), "Mumbai")
    assert d["us_aqi"] == 104 and d["pollen"] == {} and d["uv"] > 0
    assert len(d["hourly"]["us_aqi"]) == 24
    assert d["hour0"] == int(d["time"][11:13])


def test_parse_air_berlin_has_pollen() -> None:
    d = aq.parse_air(load("openmeteo_air_berlin.json"), "Berlin")
    assert set(d["pollen"]) == {"grass", "birch", "alder", "ragweed", "mugwort", "olive"}
    assert d["eu_aqi"] is not None


def test_parse_air_rejects_empty() -> None:
    with pytest.raises(ValueError):
        aq.parse_air({"current": {}})
    with pytest.raises(ValueError):
        aq.parse_air({"current": {"time": "2026-09-24T12:00", "us_aqi": None, "european_aqi": None}})


async def test_air_provider_fetch() -> None:
    doc = load("openmeteo_air_mumbai.json")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["latitude"] == str(HOME["lat"])
        assert "grass_pollen" in req.url.params["current"]
        return httpx.Response(200, json=doc)

    p = aq.AirQualityProvider(FakeHub(handler))
    v = await p.fetch()
    assert v["city"] == "Mumbai" and v["pm2_5"] == pytest.approx(30.4)
    await p.hub.http.aclose()


def test_aqi_bands() -> None:
    assert band(42, US_BANDS)[1] == "GOOD" and band(104, US_BANDS)[1] == "POOR"
    assert band(999, US_BANDS)[1] == "HAZARD"
    assert band_frac(0, US_BANDS) == 0 and band_frac(50, US_BANDS) == pytest.approx(1 / 6)
    assert band_frac(1000, US_BANDS) == 1.0
    for _hi, label, _c in US_BANDS:
        assert measure(label) <= 30


@pytest.mark.parametrize("settings", choices(AirQuality), ids=str)
@pytest.mark.parametrize("fixture", ["openmeteo_air_mumbai.json", "openmeteo_air_berlin.json"])
def test_air_renders_every_option(settings: dict[str, Any], fixture: str) -> None:
    d = aq.parse_air(load(fixture), "X")
    render_all(AirQuality(Ctx(airquality=fake_provider(d)), AirQuality.Settings(**settings)))
    render_all(AirQuality(Ctx(airquality=fake_provider(None)), AirQuality.Settings(**settings)))
    render_all(AirQuality(Ctx(airquality=fake_provider(None, "x")), AirQuality.Settings(**settings)))
    render_all(AirQuality(Ctx(), AirQuality.Settings(**settings)))


def test_air_renders_missing_values() -> None:
    d = aq.parse_air(load("openmeteo_air_mumbai.json"))
    d.update(uv=None, pm2_5=None, hourly={"us_aqi": [None] * 24, "eu_aqi": [], "pm2_5": [], "uv": []})
    for lay in ("gauge", "pollutants", "uv", "forecast", "cycle"):
        render_all(AirQuality(Ctx(airquality=fake_provider(d)), AirQuality.Settings(layout=lay)))
    d["us_aqi"] = None
    render_all(AirQuality(Ctx(airquality=fake_provider(d)), AirQuality.Settings()))


def test_air_alert_once_per_crossing() -> None:
    d = aq.parse_air(load("openmeteo_air_mumbai.json"))
    prov = fake_provider(d, updated=1.0)
    ctx = Ctx(airquality=prov)
    app = AirQuality(ctx, AirQuality.Settings(alert_aqi=150))
    f = Frame()
    app.render(f, 0)  # 104: below, arms
    for upd, v in ((2.0, 160.0), (3.0, 170.0), (4.0, 120.0), (5.0, 155.0)):
        prov.value, prov.updated = {**d, "us_aqi": v}, upd
        app.render(f, 0)
        app.render(f, 0.5)
    assert len(ctx.notices) == 2  # 104 -> 160 and 120 -> 155
    ctx2 = Ctx(airquality=fake_provider({**d, "us_aqi": 200.0}))
    AirQuality(ctx2, AirQuality.Settings(alert_aqi=150)).render(Frame(), 0)
    assert ctx2.notices == []  # already above at start: no alert


# =========================================================================== holidays
def test_parse_nager() -> None:
    hs = hol.parse_nager(load("nager_de.json"), TODAY)
    assert hs[0] == {"date": "2026-10-03", "name": "German Unity Day", "public": True}
    assert any(not h["public"] for h in hs)  # regional days are flagged


def test_parse_google_ics_india() -> None:
    hs = hol.parse_ics((FIX / "google_in.ics").read_text(encoding="utf-8"), TODAY)
    names = {h["name"]: h["public"] for h in hs}
    assert names["Mahatma Gandhi Jayanti"] is True
    assert names["Diwali/Deepavali"] is True
    assert names["First Day of Sharad Navratri"] is False  # observance
    assert all(h["date"] >= TODAY.isoformat() for h in hs)
    assert hs == sorted(hs, key=lambda h: (h["date"], not h["public"], h["name"]))


def test_parse_ics_folding_and_datetime() -> None:
    ics = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20261225T000000Z\r\nSUMMARY:Christ\r\n mas\r\n"
        "END:VEVENT\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261001\r\nSUMMARY:Gone\r\nSTATUS:CANCELLED\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    assert hol.parse_ics(ics, TODAY) == [{"date": "2026-12-25", "name": "Christmas", "public": True}]


def test_parse_caldays() -> None:
    hs = hol.parse_caldays(load("caldays_in.json"), TODAY)
    assert hs[0]["date"] >= "2026-09-24" and any(h["name"] == "Diwali" for h in hs)


def test_google_ids_and_cc() -> None:
    assert hol.google_calendar_id("IN") == "en.indian"
    assert hol.google_calendar_id("PK") == "en.pk"
    assert hol.normalize_cc(" in ") == "IN" and hol.normalize_cc("IND") == ""


def _hol_handler(nager: Any, google_ok: bool = True) -> Any:
    ics = (FIX / "google_in.ics").read_text(encoding="utf-8")

    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if host == "date.nager.at":
            return httpx.Response(204) if nager is None else httpx.Response(200, json=nager)
        if host == "calendar.google.com":
            assert "en.indian" in str(req.url)
            return httpx.Response(200, text=ics) if google_ok else httpx.Response(500)
        if host == "caldays.com":
            return httpx.Response(200, json=load("caldays_in.json"))
        return httpx.Response(404)

    return handler


async def test_holidays_india_falls_back_from_nager_204_to_google() -> None:
    p = hol.HolidaysProvider(FakeHub(_hol_handler(None)))
    p.want("")
    v = await p.fetch()
    assert v["IN"]["source"] == "google" and v[""] is v["IN"]
    assert v["IN"]["holidays"][0]["date"] >= dt.date.today().isoformat()
    await p.hub.http.aclose()


async def test_holidays_last_resort_caldays() -> None:
    p = hol.HolidaysProvider(FakeHub(_hol_handler(None, google_ok=False)))
    v = await p.lookup("IN")
    assert v["source"] == "caldays"
    await p.hub.http.aclose()


async def test_holidays_nager_first() -> None:
    doc = load("nager_de.json")
    for h in doc:  # move the capture into the future so it survives "today"
        h["date"] = str(dt.date.today().year + 1) + h["date"][4:]
    p = hol.HolidaysProvider(FakeHub(_hol_handler(doc)))
    p.want("de")
    v = await p.fetch()
    assert v["DE"]["source"] == "nager"
    await p.hub.http.aclose()


def hol_value(first: str | None = None, days: int = 0, cc: str = "IN") -> dict[str, Any]:
    today = dt.date.today()
    hs = [
        {"date": (today + dt.timedelta(days=d)).isoformat(), "name": n, "public": pub}
        for d, n, pub in (
            (8, "Mahatma Gandhi Jayanti", True),
            (17, "First Day of Sharad Navratri", False),
            (26, "Dussehra", True),
            (45, "Diwali/Deepavali", True),
            (61, "Guru Nanak Jayanti", True),
            (92, "Christmas", True),
            (123, "Republic Day", True),
        )
    ]
    if first:
        hs.insert(0, {"date": (today + dt.timedelta(days=days)).isoformat(), "name": first, "public": True})
    e = {"country": cc, "source": "google", "holidays": hs, "fetched": 1.0}
    return {"": e, cc: e}


@pytest.mark.parametrize("settings", choices(Holidays), ids=str)
@pytest.mark.parametrize("first", [None, "Diwali/Deepavali", "Eid al-Fitr"])
def test_holidays_render_every_option(settings: dict[str, Any], first: str | None) -> None:
    app = Holidays(Ctx(holidays=fake_provider(hol_value(first))), Holidays.Settings(**settings))
    render_all(app)
    assert app.kind() == "clip"
    render_all(Holidays(Ctx(holidays=fake_provider(None)), Holidays.Settings(**settings)))
    render_all(Holidays(Ctx(holidays=fake_provider(None, "x")), Holidays.Settings(**settings)))
    render_all(Holidays(Ctx(), Holidays.Settings(**settings)))


@pytest.mark.parametrize("layout", ["countdown", "list", "calendar"])
@pytest.mark.parametrize("first", [None, "Republic Day"])
def test_holidays_clips_fit_budget(layout: str, first: str | None) -> None:
    app = Holidays(
        Ctx(holidays=fake_provider(hol_value(first))),
        Holidays.Settings(layout=layout, count=8, observances=True),
    )
    bake_ok(app)


def test_holidays_countdown_and_celebration() -> None:
    app = Holidays(Ctx(holidays=fake_provider(hol_value())), Holidays.Settings())
    ups = app.upcoming()
    assert ups[0]["days"] == 8 and all(h["public"] for h in ups)  # observances hidden by default
    assert app.status()["next"]["days"] == 8
    party = Holidays(Ctx(holidays=fake_provider(hol_value("Diwali/Deepavali"))), Holidays.Settings())
    assert party._plan()["screen"] == "celebrate" and party.wants_focus()
    quiet = Holidays(Ctx(holidays=fake_provider(hol_value("Diwali"))), Holidays.Settings(celebrate=False))
    assert quiet._plan()["screen"] == "countdown"
    obs = Holidays(Ctx(holidays=fake_provider(hol_value())), Holidays.Settings(observances=True))
    assert any(not h["public"] for h in obs.upcoming())
    empty = {"": {"country": "IN", "source": "google", "holidays": [], "fetched": 1.0}}
    render_all(Holidays(Ctx(holidays=fake_provider(empty)), Holidays.Settings()))


def test_holiday_names_and_icons() -> None:
    assert clean_name("Chhat Puja (Pratihar Sashthi/Surya Sashthi)") == "CHHAT PUJA"
    assert auto_icon("Diwali/Deepavali") == "diya"
    assert auto_icon("Christmas Day") == "tree"
    assert auto_icon("Independence Day") == "flag"
    assert auto_icon("Eid al-Adha") == "crescent"
    assert auto_icon("Mahatma Gandhi Jayanti") == "wheel"
    assert auto_icon("Labour Day") == "star"
    with pytest.raises(ValidationError):
        Holidays.Settings(country="IND")
    assert Holidays.Settings(country="de").country == "DE"


# =========================================================================== rain radar
def tile_png() -> bytes:
    return base64.b64decode(load("rainviewer_tile.json")["png_b64"])


def test_decode_real_tile() -> None:
    dbz, snow = rr.decode_tile(tile_png())
    assert dbz.shape == (32, 32) and snow.shape == (32, 32)
    echo = dbz != rr.NONE
    assert echo.any() and dbz[echo].min() >= -10 and dbz[echo].max() <= 80


def test_decode_table_colours_roundtrip() -> None:
    cols = rr._COLS.astype(np.uint8)
    img = np.zeros((1, len(cols) + 1, 4), dtype=np.uint8)
    img[0, : len(cols)] = cols  # last pixel stays transparent
    dbz, snow = rr.decode_rgba(img)
    assert dbz[0, -1] == rr.NONE and not snow[0, -1]
    # every table colour decodes to a dBZ that renders the same colour (duplicate whites map to any of them)
    assert (np.abs(rr._COLS[rr._DBZ.tolist().index(int(dbz[0, 30]))] - rr._COLS[30]) < 1).all()
    assert snow[0, len(cols) - 1]


def test_downsample_needs_coverage() -> None:
    dbz = np.full((256, 256), rr.NONE, dtype=np.int16)
    dbz[0:8, 0:8] = 30  # a full cell
    dbz[0:2, 8:9] = 40  # 2 of 64 pixels: noise
    cell, snow = rr.downsample(dbz, np.zeros_like(dbz, dtype=bool))
    assert cell[0, 0] == 30 and cell[0, 1] == rr.NONE and not snow.any()


def test_mercator_roundtrip_and_window() -> None:
    x, y = rr.world_px(19.0760, 72.8777, 6)
    la, lo = rr.world_latlon(x, y, 6)
    assert abs(la - 19.0760) < 1e-6 and abs(lo - 72.8777) < 1e-6
    lats, lons = rr.cell_latlon(19.0760, 72.8777, 6)
    assert abs(lats[15, 15] - 19.0760) < 0.01 and abs(lons[15, 15] - 72.8777) < 0.01  # home = LED (15, 15)
    assert 15 < rr.km_per_led(19.2, 6) < 20


def test_upsample_elevation() -> None:
    e = np.zeros((16, 16), dtype=np.float32)
    e[:, 8:] = 300.0
    elev, land = rr.upsample_elevation(e)
    assert elev.shape == land.shape == (32, 32)
    assert land[:, 20:].all() and not land[:, :12].any()


def test_parse_maps() -> None:
    host, frames = rr.parse_maps(load("rainviewer_maps.json"))
    assert host.startswith("https://") and len(frames) >= 10
    assert all(f["kind"] == "past" for f in frames) and frames == sorted(frames, key=lambda f: f["time"])


def _radar_handler(calls: dict[str, int], elev_ok: bool = True) -> Any:
    maps = load("rainviewer_maps.json")
    png = tile_png()
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(buf, "PNG")
    empty = buf.getvalue()

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        key = (
            "maps"
            if "weather-maps" in u
            else "elev"
            if "elevation" in u
            else "cov"
            if "coverage" in u
            else "tile"
        )
        calls[key] = calls.get(key, 0) + 1
        if key == "maps":
            return httpx.Response(200, json=maps)
        if key == "elev":
            if not elev_ok:
                return httpx.Response(429, json={"error": True})
            n = len(req.url.params["latitude"].split(","))
            return httpx.Response(200, json={"elevation": [0.0 if i % 3 else 120.0 for i in range(n)]})
        if key == "cov":
            return httpx.Response(200, content=empty)
        return httpx.Response(200, content=png)

    return handler


async def test_radar_provider_fetch_caches_tiles_and_basemap() -> None:
    calls: dict[str, int] = {}
    p = rr.RainRadarProvider(FakeHub(_radar_handler(calls)))
    p.want(5)
    v = await p.fetch()
    n = len(load("rainviewer_maps.json")["radar"]["past"])
    assert v["zoom"] == 5 and len(v["frames"]) == n
    assert v["frames"][0]["dbz"].shape == (32, 32) and v["land"].shape == (32, 32)
    assert v["elev"] is not None and v["nocov"] is not None and not v["nocov"].any()
    assert calls["elev"] == 3  # 256 samples in chunks of 100
    await p.fetch()
    assert calls["tile"] == n and calls["elev"] == 3  # tiles and basemap cached
    await p.hub.http.aclose()


async def test_radar_basemap_falls_back_to_world_mask() -> None:
    calls: dict[str, int] = {}
    p = rr.RainRadarProvider(FakeHub(_radar_handler(calls, elev_ok=False)))
    v = await p.fetch()
    assert v["elev"] is None and v["land"].dtype == bool
    await p.fetch()
    assert calls["elev"] == 1  # the fallback is not retried on every fetch
    await p.hub.http.aclose()


def radar_value() -> dict[str, Any]:
    dbz, snow = rr.decode_tile(tile_png())
    frames = []
    for i in range(13):
        d = np.roll(dbz, i, axis=1)
        frames.append(
            {"time": 1790227200.0 + 600 * i, "kind": "past" if i < 11 else "nowcast", "dbz": d, "snow": snow}
        )
    land = np.zeros((32, 32), dtype=bool)
    land[:, 16:] = True
    elev = np.where(land, 400.0, 0.0).astype(np.float32)
    nocov = np.zeros((32, 32), dtype=bool)
    nocov[:, :4] = True
    return {
        "home": HOME,
        "zoom": 6,
        "frames": frames,
        "land": land,
        "elev": elev,
        "nocov": nocov,
        "km_per_led": 18.5,
    }


@pytest.mark.parametrize("settings", choices(RainRadar), ids=str)
def test_radar_renders_every_option(settings: dict[str, Any]) -> None:
    s = {"zoom": "6", **settings}
    app = RainRadar(Ctx(rainradar=fake_provider(radar_value())), RainRadar.Settings(**s))
    frames = render_all(app)
    if s["zoom"] == "6":
        assert app.kind() == "clip"
        assert frames[0].get(15, 15) != (0, 0, 0)  # home marker
    else:
        assert app.kind() == "stream"  # data for another zoom: loading until the provider catches up
    render_all(RainRadar(Ctx(rainradar=fake_provider(None)), RainRadar.Settings(**settings)))
    render_all(RainRadar(Ctx(rainradar=fake_provider(None, "x")), RainRadar.Settings(**settings)))
    render_all(RainRadar(Ctx(), RainRadar.Settings(**settings)))


@pytest.mark.parametrize("smooth", [True, False])
def test_radar_clip_fits_budget_and_rebakes(smooth: bool) -> None:
    prov = fake_provider(radar_value())
    app = RainRadar(Ctx(rainradar=prov), RainRadar.Settings(smooth=smooth))
    bake_ok(app)
    k1 = app.clip_key()
    v2 = radar_value()
    v2["frames"] = [*v2["frames"][1:], dict(v2["frames"][-1], time=v2["frames"][-1]["time"] + 600)]
    prov.value = v2
    assert app.clip_key() != k1  # a new radar frame re-bakes the loop


def test_radar_dry_and_basemap_without_elevation() -> None:
    v = radar_value()
    for fr in v["frames"]:
        fr["dbz"] = np.full((32, 32), rr.NONE, dtype=np.int16)
    v["elev"] = None
    for bm in ("outline", "terrain", "land", "none"):
        app = RainRadar(Ctx(rainradar=fake_provider(v)), RainRadar.Settings(basemap=bm))
        f = render_all(app)[0]
        assert app.dry(v)
        assert f.get(30, 1) != (0, 0, 0) or f.get(29, 1) != (0, 0, 0)  # "DRY" label
    assert app.status()["rain_cells"] == 0
