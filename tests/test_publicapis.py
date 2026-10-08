"""The 3.6.0 public-API apps: providers fetch through a mock transport serving recorded payloads
(tests/fixtures/publicapis/, captured 2026-10-08), and every app renders every layout with that data.

No live network. `run_provider(name)` is also used by the preview script in the docs workflow.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from deskdot.engine import REGISTRY
from deskdot.gfx import Frame
from deskdot.providers import (
    asteroids,
    bikeshare,
    bitcoin,
    cryptomarket,
    earthevents,
    flags,
    gameserver,
    hourly,
    longweekend,
    racing,
    spaceweather,
    tvguide,
    wiki,
)

FIX = Path(__file__).parent / "fixtures" / "publicapis"
HOME = {"city": "London", "lat": 51.5074, "lon": -0.1278, "country": "GB"}


def fx(name: str) -> Any:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def route(req: httpx.Request) -> httpx.Response:
    """Recorded answers by host + path."""
    h, p = req.url.host, req.url.path
    table: dict[tuple[str, str], Any] = {
        ("services.swpc.noaa.gov", "/products/noaa-planetary-k-index.json"): "swpc_kp.json",
        ("services.swpc.noaa.gov", "/products/noaa-planetary-k-index-forecast.json"): "swpc_kp_forecast.json",
        ("services.swpc.noaa.gov", "/json/ovation_aurora_latest.json"): "swpc_ovation.json",
        ("mempool.space", "/api/v1/fees/recommended"): "mempool_fees.json",
        ("mempool.space", "/api/v1/blocks"): "mempool_blocks.json",
        ("mempool.space", "/api/mempool"): "mempool_mempool.json",
        ("mempool.space", "/api/v1/difficulty-adjustment"): "mempool_difficulty.json",
        ("api.coingecko.com", "/api/v3/global"): "coingecko_global.json",
        ("api.coingecko.com", "/api/v3/coins/markets"): "coingecko_markets.json",
        ("api.alternative.me", "/fng/"): "fng.json",
        ("api.jolpi.ca", "/ergast/f1/current/next.json"): "jolpica_next.json",
        ("api.jolpi.ca", "/ergast/f1/current/last/results.json"): "jolpica_last.json",
        ("api.citybik.es", "/v2/networks"): "citybikes_networks.json",
        ("api.citybik.es", "/v2/networks/santander-cycles"): "citybikes_network.json",
        ("eonet.gsfc.nasa.gov", "/api/v3/events"): "eonet.json",
        ("flagcdn.com", "/en/codes.json"): "flagcdn_codes.json",
        ("api.open-meteo.com", "/v1/forecast"): "openmeteo_hourly.json",
        ("ssd-api.jpl.nasa.gov", "/cad.api"): "jpl_cad.json",
        ("api.tvmaze.com", "/schedule"): "tvmaze_schedule.json",
    }
    if h == "date.nager.at":
        return (
            httpx.Response(200, json=fx("nager_longweekend.json"))
            if p.endswith("/GB")
            else httpx.Response(204)
        )
    if h == "api.wikimedia.org":
        return httpx.Response(200, json=fx("wiki_featured.json"))
    if h == "flagcdn.com" and p.endswith(".png"):
        name = "flag_in.png" if "/in." in p else "flag_jp.png"
        return httpx.Response(200, content=(FIX / name).read_bytes(), headers={"content-type": "image/png"})
    if h == "api.mcsrvstat.us":
        name = "mcsrvstat_offline.json" if "offline" in p else "mcsrvstat.json"
        return httpx.Response(200, json=fx(name))
    name = table.get((h, p))
    if name is None:
        return httpx.Response(404, text=f"no fixture for {h}{p}")
    return httpx.Response(200, json=fx(name))


class Store:
    def __init__(self, units: str = "metric") -> None:
        self.units = units

    def get(self, key: str, default: Any = None) -> Any:
        return self.units if key == "units" else default


class Hub:
    def __init__(self, handler: Any = route, units: str = "metric") -> None:
        self.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.store = Store(units)
        self.changes: list[str] = []

    async def location(self) -> dict[str, Any]:
        return dict(HOME)

    def on_change(self, name: str) -> None:
        self.changes.append(name)


PROVIDERS = {
    "spaceweather": spaceweather.SpaceWeatherProvider,
    "bitcoin": bitcoin.BitcoinProvider,
    "cryptomarket": cryptomarket.CryptoMarketProvider,
    "racing": racing.RacingProvider,
    "longweekend": longweekend.LongWeekendProvider,
    "bikeshare": bikeshare.BikeShareProvider,
    "earthevents": earthevents.EarthEventsProvider,
    "flags": flags.FlagsProvider,
    "hourly": hourly.HourlyProvider,
    "wiki": wiki.WikiProvider,
    "asteroids": asteroids.AsteroidsProvider,
    "gameserver": gameserver.GameServerProvider,
    "tvguide": tvguide.TvGuideProvider,
}


async def run_provider(name: str, **want: Any) -> Any:
    """A provider with its value fetched from the fixtures (wants applied first)."""
    hub = Hub()
    p = PROVIDERS[name](hub)  # type: ignore[arg-type]
    if name == "gameserver":
        p.want("demo.mcstatus.io")
    if name == "flags":
        p.value = await p.fetch()
        p.want("jp", "in")
    if name == "bikeshare":
        p.want("santander-cycles")
    p.value = await p.fetch()
    await hub.http.aclose()
    return p


# ------------------------------------------------------------------------------------------- parsers
def test_space_weather_parsers() -> None:
    kp = spaceweather.parse_kp(fx("swpc_kp.json"))
    assert len(kp) == 24 and all(0 <= k <= 9 for _t, k in kp) and kp == sorted(kp)
    legacy = [["time_tag", "Kp", "a_running", "station_count"], ["2026-10-08 09:00:00.000", "2.33", "7", "8"]]
    assert spaceweather.parse_kp(legacy)[0][1] == pytest.approx(2.33)  # the pre-2026 table shape still parses
    fc = spaceweather.parse_kp_forecast(fx("swpc_kp_forecast.json"))
    assert {kind for _t, _k, kind in fc} >= {"predicted"}
    ov = spaceweather.parse_ovation(fx("swpc_ovation.json"), 64.8, -147.7)
    assert len(ov["oval"]) == 16 and len(ov["oval"][0]) == 32 and 0 <= ov["chance"] <= 100
    assert spaceweather.activity(2.0) == "QUIET" and spaceweather.activity(5.0) == "STORM G1"
    assert spaceweather.storm_level(8.67) == "G5" and spaceweather.storm_level(4.67) == "G1"


def test_bitcoin_parsers_and_halving() -> None:
    fees = bitcoin.parse_fees(fx("mempool_fees.json"))
    assert set(fees) == {"fastest", "half_hour", "hour", "economy", "minimum"}
    blocks = bitcoin.parse_blocks(fx("mempool_blocks.json"))
    assert blocks[0]["height"] > blocks[-1]["height"] and blocks[0]["tx_count"] > 0
    h = bitcoin.halving(970_510, now=0)
    assert h["height"] == 1_050_000 and h["remaining"] == 79_490 and h["subsidy"] == 3.125
    assert h["eta"] == 79_490 * 600 and 0.6 < h["progress"] < 0.63
    with pytest.raises(ValueError):
        bitcoin.parse_fees({"fees": 1})


def test_crypto_market_parsers() -> None:
    g = cryptomarket.parse_global(fx("coingecko_global.json"))
    assert g["cap"] > 1e12 and 0 < g["btc_dom"] < 100
    coins = cryptomarket.parse_markets(fx("coingecko_markets.json"))
    up, down = cryptomarket.movers(coins)
    assert all(not c["stable"] for c in up + down)
    assert up == sorted(up, key=lambda c: -c["change"]) and down == sorted(down, key=lambda c: c["change"])
    f = cryptomarket.parse_fng(fx("fng.json"))
    assert (
        0 <= f["value"] <= 100
        and len(f["history"]) == 30
        and f["label"] == cryptomarket.fng_label(f["value"])
    )


def test_racing_parsers() -> None:
    n = racing.parse_next(fx("jolpica_next.json"))
    assert n and n["name"].endswith("GP") and n["sessions"][-1][0] == "RACE" and n["start"]
    assert [s[1] for s in n["sessions"]] == sorted(s[1] for s in n["sessions"])
    last = racing.parse_last(fx("jolpica_last.json"))
    assert (
        last
        and [r["pos"] for r in last["podium"]] == [1, 2, 3]
        and all(len(r["code"]) == 3 for r in last["podium"])
    )
    empty = {"MRData": {"RaceTable": {"Races": []}}}
    assert racing.parse_next(empty) is None
    with pytest.raises(ValueError):
        racing.parse_next({"oops": 1})


def test_long_weekend_parsers() -> None:
    import datetime as dt

    ws = longweekend.parse_weekends(fx("nager_longweekend.json"))
    assert ws and all(w["days"] >= 3 for w in ws)
    up = longweekend.upcoming(ws, dt.date(2026, 10, 8))
    assert all(w["end"] >= "2026-10-08" for w in up)
    assert all(not w["bridge"] for w in longweekend.upcoming(ws, dt.date(2026, 1, 1), bridges=False))


def test_bikeshare_parsers() -> None:
    nets = bikeshare.parse_networks(fx("citybikes_networks.json"))
    best, dist = bikeshare.nearest_network(nets, HOME["lat"], HOME["lon"])  # type: ignore[misc]
    assert best["city"] and dist >= 0
    st = bikeshare.parse_stations(fx("citybikes_network.json"), HOME["lat"], HOME["lon"])
    assert st == sorted(st, key=lambda s: s["dist_m"]) and all(not s["name"][0].isdigit() for s in st)
    assert (
        bikeshare.short_station("300073 - Prince of Wales Drive, Battersea Park") == "PRINCE OF WALES DRIVE"
    )
    only = bikeshare.parse_stations(
        fx("citybikes_network.json"), HOME["lat"], HOME["lon"], match=st[0]["name"][:6]
    )
    assert only and all(st[0]["name"][:6] in s["name"] for s in only)


def test_earth_events_parser() -> None:
    ev = earthevents.parse_events(fx("eonet.json"))
    assert ev and ev == sorted(ev, key=lambda e: -e["date"])
    assert all(-90 <= e["lat"] <= 90 and -180 <= e["lon"] <= 180 for e in ev)
    assert earthevents.short_title("Wildfire - Big Creek Fire, Idaho", "wildfires") == "BIG CREEK FIRE, IDAHO"
    poly = {"events": [{"id": "x", "title": "Ice", "categories": [{"id": "seaLakeIce"}],
                        "geometry": [{"type": "Polygon", "date": "2026-10-01T00:00:00Z",
                                      "coordinates": [[[0, 60], [10, 60], [10, 70], [0, 70]]]}]}]}  # fmt: skip
    e = earthevents.parse_events(poly)[0]
    assert e["lat"] == 65 and e["lon"] == 5 and e["label"] == "ICE"


def test_flags_parsers() -> None:
    names = flags.parse_codes(fx("flagcdn_codes.json"))
    assert names["jp"] == "JAPAN" and all(len(k) == 2 for k in names)
    img = flags.decode_flag((FIX / "flag_jp.png").read_bytes())
    assert img.shape[1] <= 30 and img.shape[0] <= 20 and img.dtype == np.uint8
    assert img[img.shape[0] // 2, img.shape[1] // 2, 0] > 150  # the red sun in the middle


def test_hourly_parser() -> None:
    d = hourly.parse_hourly(fx("openmeteo_hourly.json"))
    assert len(d["hours"]) >= 12 and d["hours"][0]["h"] in range(24)
    assert d["now"]["wind"] is not None and all(0 <= (h["prob"] or 0) <= 100 for h in d["hours"])


def test_wiki_parsers() -> None:
    feed = fx("wiki_featured.json")
    tr = wiki.parse_trending(feed)
    assert tr and all(t["views"] > 0 and t["title"] == t["title"].upper() for t in tr)
    assert not any(wiki.BORING.match(t["title"]) for t in tr)
    pic = wiki.parse_picture(feed)
    assert pic and pic["url"].startswith("https://")


def test_asteroid_parser() -> None:
    a = asteroids.parse_cad(fx("jpl_cad.json"))
    assert a and a == sorted(a, key=lambda r: r["time"]) and all(r["dist_ld"] <= 10.01 for r in a)
    lo, hi = asteroids.size_m(27.8)
    assert 4 < lo < hi < 25  # a ~10 m rock
    assert asteroids.parse_cad({"signature": {}, "count": 0, "fields": ["des"]}) == []


def test_game_server_parser() -> None:
    s = gameserver.parse_status(fx("mcsrvstat.json"))
    assert s["online"] and s["players"] > 0 and s["max"] >= 0
    assert s["icon"] is not None and s["icon"].shape == (16, 16, 3)
    off = gameserver.parse_status(fx("mcsrvstat_offline.json"))
    assert off["online"] is False and off["players"] == 0
    assert gameserver.clean_address("https://Play.Example.net/") == "play.example.net"
    assert gameserver.clean_address("bad host!") == ""


def test_tv_parser() -> None:
    shows = tvguide.parse_schedule(fx("tvmaze_schedule.json"))
    assert shows and shows == sorted(shows, key=lambda s: s["start"]) and all(s["show"] for s in shows)
    late = tvguide.on_air(shows, shows[0]["start"] - 1)
    assert late[0] == shows[0]


# -------------------------------------------------------------------------------------- providers
@pytest.mark.parametrize("name", sorted(PROVIDERS))
async def test_provider_fetches_from_recorded_answers(name: str) -> None:
    p = await run_provider(name)
    assert p.value, name
    assert PROVIDERS[name].endpoints, f"{name}: declare endpoints for scripts/api_health.py"


async def test_long_weekend_unsupported_country() -> None:
    hub = Hub()
    p = longweekend.LongWeekendProvider(hub)  # type: ignore[arg-type]
    p.want("IN")
    v = await p.fetch()
    assert v["supported"] is False and v["country"] == "IN"


async def test_hourly_uses_imperial_units() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return route(req)

    hub = Hub(handler, units="imperial")
    v = await hourly.HourlyProvider(hub).fetch()  # type: ignore[arg-type]
    assert v["unit_speed"] == "MPH" and seen[0].url.params["wind_speed_unit"] == "mph"


async def test_binance_geo_block_switches_to_the_mirror() -> None:
    from deskdot.providers.markets import HOSTS, MarketsProvider

    hosts: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        if req.url.host == "api.binance.com":
            return httpx.Response(451, json={"msg": "Service unavailable from a restricted location"})
        if req.url.path.endswith("/ticker/24hr"):
            t = {
                "symbol": "BTCUSDT",
                "lastPrice": "1",
                "priceChangePercent": "2",
                "highPrice": "3",
                "lowPrice": "0.5",
            }
            return httpx.Response(200, json=[t])
        return httpx.Response(200, json=[[0, "1", "1", "1", "1.5"]] * 3)

    hub = Hub(handler)
    p = MarketsProvider(hub)  # type: ignore[arg-type]
    v = await p.fetch()
    assert v["BTC"]["price"] == 1.0 and p.host == HOSTS[1]
    assert hosts[0] == "api.binance.com" and set(hosts[1:]) == {"data-api.binance.vision"}


async def test_photo_frame_picture_of_the_day() -> None:
    from deskdot.providers.photos import PhotosProvider

    p = PhotosProvider(Hub())  # type: ignore[arg-type]
    url, title, _artist, key = await p._pick("potd")
    assert url.startswith("https://") and key.startswith("potd:") and title


# -------------------------------------------------------------------------------------------- apps
NEW_APPS = {
    "aurora": "spaceweather",
    "btcnet": "bitcoin",
    "cryptomarket": "cryptomarket",
    "racecountdown": "racing",
    "longweekend": "longweekend",
    "bikeshare": "bikeshare",
    "earthevents": "earthevents",
    "worldflags": "flags",
    "rainchance": "hourly",
    "windcompass": "hourly",
    "wikitrending": "wiki",
    "asteroidflyby": "asteroids",
    "gameserver": "gameserver",
    "tvtonight": "tvguide",
}


class Ctx:
    def __init__(self, **providers: Any) -> None:
        self.providers = providers
        self.data: dict[str, Any] = {}
        self.notes: list[dict[str, Any]] = []

    def provider(self, name: str) -> Any:
        return self.providers[name]

    def notify(self, **kw: Any) -> None:
        self.notes.append(kw)

    def save(self) -> None: ...

    def invalidate(self) -> None: ...


def variants(cls: type) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{}]
    for name, field in cls.Settings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            out += [{name: v} for v in extra["enum"]]
    return out


def make_app(app_id: str, provider: Any, **settings: Any) -> Any:
    cls = REGISTRY[app_id]
    if app_id == "gameserver":
        settings.setdefault("address", "demo.mcstatus.io")
    return cls(Ctx(**{NEW_APPS[app_id]: provider}), cls.Settings(**settings))  # type: ignore[arg-type]


@pytest.mark.parametrize("app_id", sorted(NEW_APPS))
async def test_new_apps_render_with_data(app_id: str) -> None:
    p = await run_provider(NEW_APPS[app_id])
    for s in variants(REGISTRY[app_id]):
        app = make_app(app_id, p, **s)
        app.on_start()
        for t in (0.0, 3.3, 9.1, 17.7, 26.0):
            f = Frame()
            t0 = time.perf_counter()
            app.render(f, t)
            assert time.perf_counter() - t0 < 0.05
            assert f.px.any(), (app_id, s, t)
        assert isinstance(app.status(), dict)


@pytest.mark.parametrize("app_id", sorted(NEW_APPS))
def test_new_apps_have_states_without_data(app_id: str) -> None:
    class Empty:
        value = None
        error = None

        def want(self, *a: Any, **k: Any) -> None: ...

    class Broken(Empty):
        error = "ConnectError: offline"

    for p in (Empty(), Broken()):
        f = Frame()
        make_app(app_id, p).render(f, 0.5)
        assert f.px.any(), app_id


def test_aurora_alerts_once_per_crossing() -> None:
    class P:
        def __init__(self) -> None:
            self.value: Any = {"kp": 3.0, "history": [3.0], "forecast": [], "kp_max_24h": None, "chance": 1}
            self.error = None
            self.updated = 1.0

    p = P()
    app = make_app("aurora", p, alert_kp=5)
    app.render(Frame(), 0)
    p.value = {**p.value, "kp": 5.33}
    p.updated = 2.0
    app.render(Frame(), 1)
    app.render(Frame(), 2)
    assert len(app.ctx.notes) == 1 and "KP 5" in app.ctx.notes[0]["title"]


def test_game_server_needs_an_address() -> None:
    class P:
        value = None
        error = None

    f = Frame()
    REGISTRY["gameserver"](Ctx(gameserver=P()), REGISTRY["gameserver"].Settings()).render(f, 0)  # type: ignore[arg-type]
    assert f.px.any()  # the SET ADDRESS screen
