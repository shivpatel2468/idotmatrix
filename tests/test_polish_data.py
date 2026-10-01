"""Polish of the live-data apps: seamless loops, even 1 px motion at <= 10 fps, GIFs within budget without the
encoder dropping frames, and the clarity rules (tones that stay lit through the panel gamma, no collisions).

Clarity threshold: the user's panel runs gamma calibration that crushes dark tones, so anything meant to be seen
needs >= ~45 in its brightest channel (docs/DISPLAY_DESIGN.md §3).
"""

from __future__ import annotations

import base64
import io
import itertools
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PIL import Image

from dotdeck.apps import currency as fx_app
from dotdeck.apps import gamedeals as deals_app
from dotdeck.apps import headlines as hl_app
from dotdeck.apps import quakes as qk_app
from dotdeck.apps import radar as radar_app
from dotdeck.apps import rainradar as rr_app
from dotdeck.apps import stocks as stocks_app
from dotdeck.apps import tides as tides_app
from dotdeck.apps import wear as wear_app
from dotdeck.apps import weather as wx
from dotdeck.gfx import Frame, measure
from dotdeck.gfx.image import GIF_BUDGET, encode_gif_budget
from dotdeck.providers import gamedeals as deals_p
from dotdeck.providers import headlines as hl_p
from dotdeck.providers import quakes as qk_p
from dotdeck.providers import rainradar as rr_p

FIX = Path(__file__).parent / "fixtures"
HOME = {"city": "Mumbai", "lat": 19.0760, "lon": 72.8777, "country": "IN"}
VISIBLE = 45


def fx(*parts: str) -> Any:
    return json.loads((FIX.joinpath(*parts)).read_text(encoding="utf-8"))


class Ctx:
    def __init__(self, **providers: Any) -> None:
        self.providers = providers
        self.data: dict[str, Any] = {}

    def provider(self, name: str) -> Any:
        if name not in self.providers:
            raise KeyError(name)
        return self.providers[name]

    def save(self) -> None: ...
    def invalidate(self) -> None: ...
    def notify(self, **_: Any) -> None: ...


def prov(value: Any = None, error: str | None = None, **kw: Any) -> SimpleNamespace:
    ns = SimpleNamespace(value=value, error=error, updated=1.0, **kw)
    for m in ("want", "unwant", "configure", "refresh"):
        if not hasattr(ns, m):
            setattr(ns, m, lambda *a, **k: None)
    return ns


def frame_at(app: Any, t: float) -> Frame:
    f = Frame()
    app.render(f, t)
    return f


def gif_frames(app: Any, clip: Any) -> tuple[int, int]:
    gif = encode_gif_budget(clip.frames, clip.durations_ms, app.clip_colors)
    return Image.open(io.BytesIO(gif)).n_frames, len(gif)


def assert_budget(app: Any) -> None:
    """Under 40 KB with every frame kept (identical neighbours are merged by the GIF writer, not dropped)."""
    clip = app.clip_frames()
    n, size = gif_frames(app, clip)
    assert size <= GIF_BUDGET
    distinct = 1 + sum(a != b for a, b in zip(clip.frames, clip.frames[1:], strict=False))
    assert n == distinct, f"the encoder dropped frames ({n} of {distinct})"


def h_shift(a: np.ndarray, b: np.ndarray) -> int | None:
    """How many px the content of band `a` moved left to become `b` (None: not a pure shift)."""
    w = a.shape[1]
    for s in range(0, 8):
        if np.array_equal(b[:, : w - s], a[:, s:]):
            return s
    return None


# ------------------------------------------------------------------------------------------- weather
def weather_value(cond: str, day: bool = True) -> dict[str, Any]:
    return {
        "city": "Mumbai",
        "temp": 28,
        "condition": cond,
        "label": cond.upper(),
        "is_day": day,
        "hi": 31,
        "lo": 24,
        "hourly": [26 + 4 * math.sin(i / 24 * math.tau) for i in range(24)],
        "unit": "C",
    }


CONDITIONS = [("clear", True), ("clear", False), ("partly", True), ("partly", False)] + [
    (c, True) for c in ("cloudy", "fog", "rain", "drizzle", "storm", "snow")
]


@pytest.mark.parametrize(("cond", "day"), CONDITIONS)
@pytest.mark.parametrize("layout", ["icon", "forecast"])
def test_weather_is_a_seamless_clip(cond: str, day: bool, layout: str) -> None:
    app = wx.Weather(Ctx(weather=prov(weather_value(cond, day))), wx.WeatherSettings(layout=layout))
    assert app.kind() == "clip"
    first, wrapped = frame_at(app, 0.0), frame_at(app, wx.N_FRAMES / wx.FPS)
    assert first == wrapped, "the loop jumps"
    clip = app.clip_frames()
    assert len(clip.frames) == wx.N_FRAMES and len(set(clip.durations_ms)) == 1
    assert clip.durations_ms[0] >= 100  # <= 10 fps
    assert_budget(app)
    for fr in clip.frames:  # the icon never reaches the temperature column
        assert not fr.px[:10, 16:18].any() or cond == "clear"


def test_weather_rain_falls_one_pixel_per_frame() -> None:
    app = wx.Weather(Ctx(weather=prov(weather_value("rain"))), wx.WeatherSettings())
    frames = app.clip_frames().frames
    col = 2  # the first drop column
    heads = [max(y for y in range(9, 17) if tuple(fr.px[y, col]) == wx.RAIN) for fr in frames]
    steps = {(b - a) % wx.RAIN_FALL for a, b in zip(heads, heads[1:] + heads[:1], strict=True)}
    assert steps == {1}


def test_weather_loading_streams() -> None:
    app = wx.Weather(Ctx(weather=prov(None)), wx.WeatherSettings())
    assert app.kind() == "stream"
    assert frame_at(app, 0.3).px.any()
    assert frame_at(wx.Weather(Ctx(weather=prov(None, "x")), wx.WeatherSettings()), 0.3).px.any()


# --------------------------------------------------------------------------------------- flight radar
def radar_value(n: int = 8) -> dict[str, Any]:
    ac = [
        {
            "id": f"a{i}",
            "callsign": f"TST{i}",
            "lat": 0,
            "lon": 0,
            "alt_ft": 1000 + i * 4000,
            "speed_kt": 200 + i * 20,
            "track": i * 40.0,
            "vrate": 0,
            "type": "A320",
            "dist_nm": 1.0 + (i * 2.7) % 28,
            "bearing_deg": i * 47.0 % 360,
            "ground": False,
        }
        for i in range(n)
    ]
    return {
        "center": {"lat": 0, "lon": 0},
        "radius_nm": 30,
        "aircraft": ac,
        "source": "t",
        "updated": time.time() - 3600,  # an hour old: dead reckoning clamps at 30 s, contacts cannot creep
    }


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"theme": "amber"},
        {"theme": "military"},
        {"sweep_speed": 2},
        {"sweep_speed": 7.3},
        {"sweep_speed": 30},
        {"rotate_labels": True},
        {"show_labels": False},
    ],
    ids=str,
)
def test_radar_scope_is_a_seamless_clip_within_budget(settings: dict[str, Any]) -> None:
    for value in (radar_value(8), radar_value(40), None):
        app = radar_app.Radar(Ctx(flights=prov(value)), radar_app.RadarSettings(**settings))
        assert app.kind() == "clip"
        clip = app.clip_frames()
        assert len(clip.frames) <= radar_app.MAX_FRAMES
        assert len(set(clip.durations_ms)) == 1 and clip.durations_ms[0] >= 100
        loop = sum(clip.durations_ms) / 1000
        assert frame_at(app, 0.0) == frame_at(app, loop), "the sweep jumps at the wrap"
        assert_budget(app)


def test_radar_contacts_rebake_through_the_rate_limited_chunk() -> None:
    p = prov(radar_value())
    app = radar_app.Radar(Ctx(flights=p), radar_app.RadarSettings())
    key, chunk = app.clip_key(), app.clip_chunk()
    p.value = radar_value(5)
    assert app.clip_key() == key and app.clip_chunk() != chunk
    assert app.clip_refresh >= 90
    assert radar_app.Radar(Ctx(flights=p), radar_app.RadarSettings(layout="list")).kind() == "stream"


def test_radar_rings_stay_lit() -> None:
    app = radar_app.Radar(Ctx(flights=prov(radar_value())), radar_app.RadarSettings())
    grid = app._lut[np.clip(app._base * 255, 0, 255).astype(np.uint8)]
    assert grid.max(axis=2).max() >= 60 and (grid.max(axis=2) >= VISIBLE).sum() > 60


# ---------------------------------------------------------------------------------------- earthquakes
def quake_value() -> dict[str, Any]:
    return {"home": HOME, "feeds": {"2.5_day": qk_p.parse_feed(fx("planet", "usgs_2.5_day.json"), HOME)}}


@pytest.mark.parametrize("layout", ["world", "region", "card", "list"])
def test_quakes_loops_are_seamless_at_10fps(layout: str) -> None:
    app = qk_app.Quakes(Ctx(quakes=prov(quake_value())), qk_app.QuakesSettings(layout=layout))
    clip = app.clip_frames()
    loop = sum(clip.durations_ms) / 1000
    assert min(clip.durations_ms) >= 100
    assert frame_at(app, 0.0) == frame_at(app, loop)
    assert_budget(app)


def test_quakes_card_marquee_moves_one_pixel_per_frame() -> None:
    app = qk_app.Quakes(Ctx(quakes=prov(quake_value())), qk_app.QuakesSettings(layout="card"))
    frames = app.clip_frames().frames
    band = [fr.px[26:31, 1:31] for fr in frames]
    shifts = [h_shift(a, b) for a, b in itertools.pairwise(band)]
    assert set(s for s in shifts if s is not None) <= {0, 1}
    assert shifts.count(1) > 10


def test_quakes_time_ago_lives_in_the_chunk() -> None:
    app = qk_app.Quakes(Ctx(quakes=prov(quake_value())), qk_app.QuakesSettings())
    assert '"M"' not in app.clip_key() and "D" in app.clip_chunk()
    assert app.clip_refresh >= 90


def test_quakes_land_is_visible_but_neutral() -> None:
    land = qk_app.QuakesSettings().land.lstrip("#")
    rgb = tuple(int(land[i : i + 2], 16) for i in (0, 2, 4))
    assert max(rgb) >= VISIBLE and max(rgb) - min(rgb) < 40  # no green that reads as a quake dot


# ----------------------------------------------------------------------------------------- rain radar
def rain_value() -> dict[str, Any]:
    dbz, snow = rr_p.decode_tile(base64.b64decode(fx("planet", "rainviewer_tile.json")["png_b64"]))
    frames = [
        {"time": 1790227200.0 + 600 * i, "kind": "past" if i < 11 else "nowcast", "dbz": np.roll(dbz, i, 1),
         "snow": snow}
        for i in range(13)
    ]  # fmt: skip
    land = np.zeros((32, 32), dtype=bool)
    land[:, 16:] = True
    return {"home": HOME, "zoom": 6, "frames": frames, "land": land, "elev": np.where(land, 400.0, 0.0),
            "nocov": np.zeros((32, 32), dtype=bool), "km_per_led": 18.5}  # fmt: skip


@pytest.mark.parametrize("basemap", ["outline", "terrain", "land", "none"])
def test_rainradar_basemap_visible_and_budget(basemap: str) -> None:
    app = rr_app.RainRadar(Ctx(rainradar=prov(rain_value())), rr_app.RainRadarSettings(basemap=basemap))
    img = app.basemap(app._data()[1])
    if basemap != "none":
        assert img[:, 16:].max() >= VISIBLE  # the land/coast still reads on the LEDs
        assert (
            np.abs(img[:, 16:].astype(int)[..., 1] - img[:, 16:].astype(int)[..., 2]) < 40
        ).all()  # neutral
    assert_budget(app)
    steps = app.schedule(app._data()[1])
    assert len([s for s in steps if s[0] == 0]) == 1 + len(rr_app.BLEND_STEPS)  # hold + two cross-fades


# ------------------------------------------------------------------------------------------ stocks
def stock(price: float, pct: float) -> dict[str, Any]:
    return {"price": price, "change_pct": pct, "change": price * pct / 100, "currency": "USD", "decimals": 2,
            "market_state": "REGULAR", "history": [price * (1 + 0.002 * math.sin(i / 3)) for i in range(40)],
            "range_ref": price, "name": "X"}  # fmt: skip


@pytest.mark.parametrize("symbols", ["AAPL,NVDA", "AAPL,NVDA,MSFT,TSLA", "AAPL,NVDA,MSFT,TSLA,AMZN,META"])
@pytest.mark.parametrize("speed", [4, 12, 30])
def test_stocks_ticker_moves_in_even_steps(symbols: str, speed: int) -> None:
    data = {s: stock(100 + i * 37.5, (-1) ** i * 1.2) for i, s in enumerate(symbols.split(","))}
    app = stocks_app.Stocks(Ctx(stocks=prov(data)), stocks_app.StocksSettings(layout="ticker", symbols=symbols,
                                                                              speed=speed))  # fmt: skip
    clip = app.clip_frames()
    assert len(set(clip.durations_ms)) == 1 and clip.durations_ms[0] >= stocks_app.TAPE_MIN_MS
    band = [fr.px[1:30] for fr in clip.frames]
    shifts = {h_shift(a, b) for a, b in zip(band, band[1:] + band[:1], strict=True)}
    assert len(shifts) == 1 and None not in shifts, f"uneven tape steps {shifts}"
    assert_budget(app)


def test_stocks_mono_down_stays_readable() -> None:
    app = stocks_app.Stocks(Ctx(stocks=prov({})), stocks_app.StocksSettings(theme="mono"))
    assert max(app.down) >= 150


# ---------------------------------------------------------------------------------------- headlines
class HeadlinesProv(SimpleNamespace):
    key = staticmethod(hl_p.HeadlinesProvider.key)


def hn_value() -> dict[str, Any]:
    item = hl_p.parse_hn_item(fx("daily", "hn_item.json")) or {}
    return {"hn:top": [dict(item, id=str(i), rank=i, score=500 - i * 40) for i in range(1, 7)]}


def headlines(**kw: Any) -> hl_app.Headlines:
    p = HeadlinesProv(value=hn_value(), error=None, want=lambda *a: None)
    return hl_app.Headlines(Ctx(headlines=p), hl_app.HeadlinesSettings(**kw))


@pytest.mark.parametrize("layout", ["card", "big"])
@pytest.mark.parametrize("speed", [4, 12, 24])
def test_headlines_marquee_even_steps(layout: str, speed: int) -> None:
    app = headlines(layout=layout, speed=speed)
    clip = app.clip_frames()
    assert len(clip.frames) <= 200 and len(set(clip.durations_ms)) == 1 and clip.durations_ms[0] >= 100
    y = 21 if layout == "card" else 26
    band = [fr.px[y : y + 7, 1:31] for fr in clip.frames]
    shifts = [h_shift(a, b) for a, b in itertools.pairwise(band)]
    moving = {s for s in shifts if s}
    assert len(moving) == 1 and None not in shifts, f"uneven marquee {set(shifts)}"


def test_headlines_ticker_lines_fit_and_frame_rate() -> None:
    app = headlines(layout="ticker")
    lines, _total, _stops = app._tape_lines()
    assert all(measure(text) <= 30 for _y, text, _c, align in lines if align != "rule")
    clip = app.clip_frames()
    assert len(clip.frames) <= 200 and min(clip.durations_ms) >= 100
    assert hl_app.hyphenate("SNAPDRAGONNNNN X2") .startswith("SNAPDR")  # fmt: skip


def test_headlines_comment_count_never_covers_the_score() -> None:
    app = headlines()
    f = Frame()
    app.comments(f, {"comments": 147}, 30, 10, left=20)
    assert not f.px[:, :20].any()
    f2 = Frame()
    app.comments(f2, {"comments": 147}, 30, 10, left=25)
    assert not f2.px.any()


# ---------------------------------------------------------------------------------------- game deals
def test_gamedeals_marquee_one_pixel_per_frame_at_10fps() -> None:
    stores = {s["storeID"]: s["storeName"] for s in fx("visuals", "cheapshark_stores.json")}
    p = prov({"giveaways": deals_p.parse_giveaways(fx("visuals", "gamerpower.json")),
              "deals": deals_p.parse_deals(fx("visuals", "cheapshark_deals.json"), stores), "updated": 1.0})  # fmt: skip
    for source in ("giveaways", "deals"):
        app = deals_app.GameDeals(Ctx(gamedeals=p), deals_app.GameDealsSettings(source=source))
        app._clock = lambda: 1790200000.0
        clip = app.clip_frames()
        assert min(clip.durations_ms) >= 100
        band = [fr.px[26:31, 1:31] for fr in clip.frames]
        shifts = {h_shift(a, b) for a, b in itertools.pairwise(band)}
        assert shifts <= {0, 1}, f"uneven marquee {shifts}"


# --------------------------------------------------------------------------------------- what to wear
@pytest.mark.parametrize("icon", ["umbrella", "jacket", "sunglasses", "tshirt", "scarf", "boots"])
def test_wear_loops_are_seamless(icon: str) -> None:
    d = {"temp": 23, "rain_prob": 71, "uv_max": 5, "unit": "C"}
    app = wear_app.Wear(Ctx(wear=prov(d)), wear_app.WearSettings(icon=icon))
    assert frame_at(app, 0.0) == frame_at(app, app.clip_seconds)
    assert_budget(app)


# ---------------------------------------------------------------------------------------- tides
def test_tide_crest_is_one_unbroken_line() -> None:
    now = time.time()
    ts = [now + (i - 48) * 1800 for i in range(120)]
    d = {"ts": ts, "sea": [1.2 * math.sin(i / 12.4 * math.tau * 0.5) for i in range(120)], "has_tide": True,
         "has_waves": False, "extrema": [], "tz_offset": 0.0, "unit": "m"}  # fmt: skip
    app = tides_app.Tides(Ctx(tides=prov(d)), tides_app.TidesSettings())
    f = frame_at(app, 0.0)
    crest = {tides_app.CREST, tides_app.CREST_PAST, (255, 255, 255), (127, 127, 127)}  # + the "now" dot
    rows = [{y for y in range(8, 26) if tuple(f.px[y, x]) in crest} for x in range(1, 31)]
    assert all(rows), "a column lost its crest pixel"
    for a, b in itertools.pairwise(rows):  # neighbouring columns touch (8-connected)
        assert min(abs(ya - yb) for ya in a for yb in b) <= 1


# ------------------------------------------------------------------------------------ small clarity rules
def test_currency_converter_result_clears_the_caption() -> None:
    v = {"base": "INR", "range": "30d", "date": "x",
         "pairs": {"USD": {"code": "USD", "rate": 95.74, "change_pct": 0.15, "range_pct": 0.2, "history": [95, 96]}}}  # fmt: skip
    app = fx_app.Currency(Ctx(currency=prov(v)), fx_app.CurrencySettings(layout="converter", quotes="USD"))
    f = frame_at(app, 0.0)
    assert not f.px[24:26].any(), "the big result runs into the currency caption"
    assert f.px[26:31].any()


def test_dim_structure_stays_lit() -> None:
    from dotdeck.apps import airquality, planets, sysmon

    assert max(airquality.TRACK) >= VISIBLE and airquality.UNLIT_K >= 0.35
    assert max(planets.HORIZON) >= 100
    assert sysmon.TRACK_K >= 0.25
    assert max(stocks_app.TRACK) >= VISIBLE and max(rr_app.COAST) >= 80
