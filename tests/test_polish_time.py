"""Polish checks for the time/productivity group (docs/DISPLAY_DESIGN.md, the "Synthwave treatment").

Smoothness: baked loops wrap without a jump, clips run at <= 10 fps with even frame times, marquees move at
most 1 px per frame, rings and bars glide with a sub-LED leading edge, GIFs fit the budget without the encoder
dropping frames. Clarity: meaningful dark tones survive the panel's gamma, heroes contrast with what's behind
them, text never collides with other text or leaves the 1 px margin.
"""

from __future__ import annotations

import io
import itertools
import time
from datetime import date, timedelta
from typing import Any

import numpy as np
import pytest
from PIL import Image

from dotdeck.apps import (
    activeapp,
    agent,
    anki,
    calendar,
    custom,
    daily,
    daynight,
    extras,
    habits,
    holidays,
    onair,
    progress,
    sky,
    timer,
)
from dotdeck.gfx import Frame, measure
from dotdeck.gfx.image import GIF_BUDGET, encode_gif, encode_gif_budget

VISIBLE = 45  # the brightest channel a meaningful dark tone needs through the panel's gamma-1.5 calibration


# ------------------------------------------------------------------------------------------ fakes
class Prov:
    def __init__(self, value: Any = None, error: str | None = None) -> None:
        self.value, self.error = value, error

    def want(self, *a: Any) -> None: ...
    def configure(self, *a: Any, **k: Any) -> None: ...
    def icon(self, exe: str) -> None:
        return None


class Ctx:
    def __init__(self, providers: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> None:
        self.providers = providers or {}
        self.data: dict[str, Any] = data if data is not None else {}
        self.key = self.app_id = "test"
        self.library = None

    def provider(self, name: str) -> Any:
        if name not in self.providers:
            raise KeyError(name)
        return self.providers[name]

    def save(self) -> None: ...
    def invalidate(self) -> None: ...
    def notify(self, **_: Any) -> None: ...


def make(cls: type, settings: dict[str, Any] | None = None, providers=None, data=None):  # type: ignore[no-untyped-def]
    app = cls(Ctx(providers, data), cls.Settings.model_validate(settings or {}))
    app.on_settings()
    app.on_start()
    return app


def render(app: Any, t: float) -> Frame:
    f = Frame()
    app.render(f, t)
    return f


def gif_frames(data: bytes) -> int:
    return int(getattr(Image.open(io.BytesIO(data)), "n_frames", 1))


def assert_gif_keeps_every_frame(frames: list[Frame], durations: list[int], colors: int) -> None:
    """Fits the 40 KB budget without `encode_gif_budget` halving the frame rate. (Pillow itself folds frames
    that are identical after palette mapping into their neighbour; that keeps timing and is not a drop.)"""
    gif = encode_gif_budget(frames, durations, colors)
    assert len(gif) <= GIF_BUDGET
    full = gif_frames(encode_gif(frames, durations, max_colors=16))
    assert gif_frames(gif) >= full, "the encoder dropped frames to fit the budget"


def row_shift(a: Frame, b: Frame, y0: int, y1: int) -> int:
    """How far the lit pattern in rows y0..y1 moved left from `a` to `b` (best match over -4..4 px)."""
    pa = a.px[y0 : y1 + 1, 1:31].astype(int).sum(axis=2) > 0
    pb = b.px[y0 : y1 + 1, 1:31].astype(int).sum(axis=2) > 0
    best, err = 0, None
    for dx in range(-4, 5):
        sa = pa[:, max(0, dx) : 30 + min(0, dx)]
        sb = pb[:, max(0, -dx) : 30 + min(0, -dx)]
        e = int((sa != sb).sum())
        if err is None or e < err:
            best, err = dx, e
    return best


def max_marquee_step(frames: list[Frame], y0: int, y1: int) -> int:
    return max(abs(row_shift(a, b, y0, y1)) for a, b in itertools.pairwise(frames))


# ------------------------------------------------------------------------------------------ data
def holidays_value(days_ahead: int, name: str) -> dict[str, Any]:
    today = date.today()
    hol = [
        {"date": (today + timedelta(days=days_ahead)).isoformat(), "name": name, "public": True},
        {
            "date": (today + timedelta(days=days_ahead + 20)).isoformat(),
            "name": "Guru Nanak Jayanti",
            "public": True,
        },
        {
            "date": (today + timedelta(days=days_ahead + 40)).isoformat(),
            "name": "Christmas Day",
            "public": True,
        },
    ]
    return {"": {"country": "IN", "source": "t", "holidays": hol, "fetched": 1}}


# ============================================================================= rings and bars
def test_smooth_ring_glides_and_stays_unbroken() -> None:
    """A slow drain changes the panel a little every step instead of one whole LED every few seconds."""
    energy = []
    for i in range(0, 41):
        f = Frame()
        timer.smooth_ring(f, 0.5 + i / (124 * 8), (255, 0, 0), head=False, tail=1.0)
        energy.append(int(f.px[..., 0].astype(int).sum()))
    assert all(b > a for a, b in itertools.pairwise(energy)), "every 1/8 LED of progress shows"
    f = Frame()
    timer.smooth_ring(f, 1.0, (255, 0, 0), track=None)
    edge = [f.get(x, y) for x, y in timer.PERIMETER]
    assert all(max(c) > 0 for c in edge), "a full ring has no gap"


def test_smooth_bar_has_a_partial_end_column() -> None:
    f = Frame()
    timer.smooth_bar(f, 1, 10, 30, 2, 10.5 / 30, (0, 200, 0), track=(0, 0, 0))
    assert f.get(10, 10) == (0, 200, 0) and 0 < f.get(11, 10)[1] < 200 and f.get(12, 10) == (0, 0, 0)


def test_countdown_last_day_ring_counts_the_seconds() -> None:
    from datetime import datetime

    app = make(extras.Countdown, {"target": (datetime.now() + timedelta(hours=3, seconds=30)).isoformat()})
    lit = sum(1 for x, y in timer.PERIMETER if max(render(app, 0).get(x, y)) > 60)
    assert 20 < lit < 110, "the ring shows the draining minute, not a year-scale 100 %"


# ============================================================================= seamless baked loops
@pytest.mark.parametrize("state", list(agent.STATES))
def test_agent_loop_is_seamless_and_props_stay_off_the_label(state: str) -> None:
    app = make(agent.Agent, {"state": state})
    assert render(app, 0.0) == render(app, app.clip_seconds)
    clip = app.clip_frames()
    assert len(set(clip.durations_ms)) == 1 and 1000 / clip.durations_ms[0] <= 10
    for f in clip.frames:
        assert f.px[6].max() == 0, f"{state}: a prop touches the label row"
    assert str(agent.AgentSettings().color).lower() == "#f94a18"  # the user's Claude colour, flat
    assert_gif_keeps_every_frame(clip.frames, clip.durations_ms, app.clip_colors)


@pytest.mark.parametrize("glyph", ["mic", "cam", "both"])
@pytest.mark.parametrize("look", ["sign", "outline"])
def test_onair_loop_is_seamless(glyph: str, look: str) -> None:
    app = make(onair.OnAir, {"glyph": glyph, "look": look})
    assert render(app, 0.0) == render(app, app.clip_seconds)
    clip = app.clip_frames()
    assert_gif_keeps_every_frame(clip.frames, clip.durations_ms, app.clip_colors)


def test_habits_loop_is_seamless_and_missed_days_are_visible() -> None:
    today = date.today()
    log = {"1": [(today - timedelta(days=i)).isoformat() for i in range(4)], "2": [], "3": []}
    app = make(habits.Habits, {}, data={"log": log})
    assert render(app, 0.0) == render(app, app.clip_seconds)
    clip = app.clip_frames()
    assert_gif_keeps_every_frame(clip.frames, clip.durations_ms, app.clip_colors)
    assert max(habits.MISS) >= VISIBLE


@pytest.mark.parametrize("layout", ["world", "half", "globe"])
def test_daynight_clip_fits_and_night_land_is_visible(layout: str) -> None:
    now = time.time()
    value = {"lat": 19.2, "lon": 72.97, "tz_offset": 19800.0, "days": {"x": {"sunrise": now + 3600}}}
    app = make(daynight.DayNight, {"layout": layout}, {"sky": Prov(value)})
    assert render(app, 0.0) == render(app, app.clip_seconds)
    clip = app.clip_frames()
    assert len(set(clip.durations_ms)) == 1 and 1000 / clip.durations_ms[0] <= 10
    assert_gif_keeps_every_frame(clip.frames, clip.durations_ms, app.clip_colors)
    from dotdeck.gfx import to_rgb

    assert max(to_rgb(daynight.DayNightSettings().night_land)) >= VISIBLE


# ============================================================================= holidays
HOLIDAY_CASES = [
    ({"layout": "countdown"}, 12, "Diwali"),
    ({"layout": "countdown", "icon": "confetti"}, 3, "Mahatma Gandhi Jayanti Celebrations"),
    ({"layout": "list"}, 12, "Diwali"),
    ({"layout": "calendar"}, 12, "Diwali"),
    ({"icon": "confetti"}, 0, "Independence Day of the Republic"),
    ({"icon": "fireworks"}, 0, "Diwali"),
    ({}, 0, "Christmas"),
]


@pytest.mark.parametrize(("settings", "days", "name"), HOLIDAY_CASES)
def test_holidays_loops_are_seamless_even_and_within_budget(
    settings: dict[str, Any], days: int, name: str
) -> None:
    app = make(holidays.Holidays, settings, {"holidays": Prov(holidays_value(days, name))})
    plan = app._plan()
    assert render(app, 0.0) == render(app, plan["loop"])
    clip = app.clip_frames()
    assert len(set(clip.durations_ms)) == 1 and 1000 / clip.durations_ms[0] <= 10
    assert len(clip.frames) == round(plan["loop"] * plan["fps"])
    assert_gif_keeps_every_frame(clip.frames, clip.durations_ms, app.clip_colors)
    if plan["screen"] in ("countdown", "celebrate"):
        y = 26 if plan["screen"] == "countdown" else 27
        assert max_marquee_step(clip.frames, y, y + 4) <= 1, "the name marquee steps 1 px per frame"


def test_holidays_confetti_falls_at_an_even_cadence() -> None:
    """11 confetti rows per UNIT-long loop at 10 fps: a row every 4 frames, never 3-then-4."""
    f_prev, moves = None, []
    for i in range(44):
        f = Frame()
        holidays.icon_confetti(f, 0, 0, i / 44, (255, 170, 0))
        if f_prev is not None:
            moves.append(f != f_prev)
        f_prev = f
    changed = [i for i, m in enumerate(moves) if m]
    gaps = {b - a for a, b in itertools.pairwise(changed)}
    assert gaps <= {1, 2}, gaps  # the slow pieces move every 4th frame, the fast every 2nd: always a change


def test_holidays_calendar_cells_are_visible() -> None:
    app = make(holidays.Holidays, {"layout": "calendar"}, {"holidays": Prov(holidays_value(12, "Diwali"))})
    f = render(app, 0.0)
    cells = f.px[7:31, 1:31].reshape(-1, 3)
    lit = cells[cells.max(axis=1) > 0]
    assert len(lit) > 200 and np.percentile(lit.max(axis=1), 10) >= VISIBLE


# ============================================================================= marquees
def test_daily_marquee_clip_is_ten_fps_one_px_per_frame() -> None:
    class DP(Prov):
        def has(self, s: str) -> bool:
            return s == "quote"

        def take(self, s: str) -> dict[str, Any]:
            return {
                "id": "q",
                "source": "quote",
                "text": "THE BEST WAY TO PREDICT THE FUTURE IS TO INVENT IT",
            }

    app = make(daily.Daily, {"style": "marquee", "speed": 12, "show_author": False}, {"daily": DP({"x": 1})})
    app.render(Frame(), 0)
    clip = app.clip_frames()
    moving = [d for d in clip.durations_ms if d < 1000]
    assert moving and max(1000 / d for d in moving) <= 10.5
    assert max_marquee_step(clip.frames, 13, 19) <= 1
    assert len(clip.frames) <= daily.Daily.MAX_CLIP_FRAMES
    assert_gif_keeps_every_frame(clip.frames, clip.durations_ms, app.clip_colors)


def test_custom_scroll_clip_is_ten_fps_one_px_per_frame() -> None:
    push = {"a": {"text": "The washing machine has finished its cycle", "icon": "bolt"}}
    app = make(custom.Custom, {}, {"custom": Prov(push)})
    assert app.kind() == "clip"
    clip = app.clip_frames()
    assert set(clip.durations_ms) == {100}
    assert max_marquee_step(clip.frames, 21, 27) <= 1
    assert_gif_keeps_every_frame(clip.frames, clip.durations_ms, app.clip_colors)


@pytest.mark.parametrize("module", ["calendar", "uptime", "anki", "ci", "obs", "printer"])
def test_streamed_marquees_step_one_px_per_frame(module: str) -> None:
    import importlib

    mod = importlib.import_module(f"dotdeck.apps.{module}")
    cls = next(
        v
        for v in vars(mod).values()
        if isinstance(v, type)
        and getattr(v, "__module__", "") == mod.__name__
        and hasattr(v, "fps")
        and hasattr(v, "Settings")
        and v.__name__ not in ("App",)
    )
    assert mod.SPEED / cls.fps == 1.0


# ============================================================================= clarity
def test_github_name_never_runs_into_the_total() -> None:
    days = [((date.today() - timedelta(days=i)).isoformat(), i % 5) for i in range(120)][::-1]
    value = {"user": "averylongusername", "days": days, "total": 12345, "streak": 3}
    app = make(extras.GitHub, {"user": "averylongusername"}, {"github": Prov(value)})
    f = render(app, 0.0)
    tot = "12.3K"
    x = 31 - measure(tot)
    assert f.px[1:6, x - 1].max() == 0 and f.px[1:6, x - 2].max() == 0


def test_calendar_timeline_shows_todays_events() -> None:
    now = time.time()
    events = [{"start": now - 1800, "end": now + 900, "title": "PLAN", "cal": 0, "all_day": False}]
    app = make(calendar.Calendar, {"urls": "https://x/y.ics"}, {"calendar": Prov({"events": events})})
    f = render(app, 0.0)
    strip = f.px[25:27, 2:30]
    cyan = (strip[..., 2] > 150) & (strip[..., 0] < 60)
    assert cyan.sum() >= 2, "the current event is on the timeline"


def test_sky_sun_is_visible_on_the_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    from dotdeck.providers.sky import local_date, sun_events

    tz = 19800.0
    d0 = local_date(time.time(), tz)
    days = {d.isoformat(): sun_events(d, 19.2, 72.97, tz) for d in (d0, d0 + timedelta(days=1))}
    value = {"lat": 19.2, "lon": 72.97, "tz_offset": tz, "days": days}
    ev = days[d0.isoformat()]
    for ts in (ev["sunrise"] + 300, ev["sunset"] - 120):
        monkeypatch.setattr(sky.time, "time", lambda ts=ts: ts)
        for layout, horizon in (("arc", 19), ("combined", 15)):
            f = render(make(sky.Sky, {"layout": layout}, {"sky": Prov(value)}), 1.0)
            above = f.px[: horizon + 1].reshape(-1, 3).astype(int)
            pale = (above[:, 0] > 230) & (above[:, 1] > 190) & (above[:, 2] > 110)
            assert pale.any(), f"{layout}: the low sun must stand out from the orange horizon"


def test_progress_future_units_are_visible() -> None:
    assert max(progress.FUTURE) >= VISIBLE
    for focus in ("day", "week", "month", "life", "event1"):
        f = render(make(progress.Progress, {"layout": "dots", "focus": focus, "event1_on": True}), 0.0)
        body = f.px[8:31].reshape(-1, 3)
        lit = body[body.max(axis=1) > 0]
        assert lit.max(axis=1).min() >= VISIBLE * 0.9, focus


def test_activeapp_focus_bars_stop_before_the_times() -> None:
    w = {
        "proc": "code.exe", "exe": "", "name": "Code", "title": "x", "category": "code", "since": time.time() - 60,
        "top": [{"exe": "", "name": "A", "seconds": 5400}, {"exe": "", "name": "B", "seconds": 3000}],
    }  # fmt: skip
    f = render(make(activeapp.ActiveApp, {"layout": "focus"}, {"window": Prov(w)}), 0.0)
    for i, secs in enumerate((5400, 3000)):
        y = 8 + i * 6
        txt = activeapp.fmt_short(secs)
        x = 31 - measure(txt)
        assert f.px[y + 1 : y + 4, x - 2 : x].max() == 0, "a gap between bar and time"
    assert activeapp.fmt_short(5400) == "90M" and activeapp.fmt_short(4 * 3600) == "4H"


def test_anki_done_keeps_the_margin() -> None:
    v = {"state": "ok", "due": 0, "new": 0, "learn": 0, "review": 0, "reviewed": 12}
    f = render(make(anki.Anki, {}, {"anki": Prov(v)}), 0.0)
    assert f.px[18:23, 0].max() == 0 and f.px[18:23, 31].max() == 0
