"""Uptime monitor — HTTP status + latency and TCP connect checks, with sparklines and outage alerts.

Layouts: ``list`` (three rows: status dot, name, latency and a sparkline each), ``grid`` (a status tile per
target) and ``focus`` (one target per screen: hero latency, big sparkline). An outage flashes the panel
edge and sends a notification; recovery sends another. ICMP ping is not supported (raw sockets need admin
rights) — use a TCP port instead (``host:22``, ``host:443`` …).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale
from ..gfx.color import RGB
from ..providers.uptime import parse_targets
from ._kit import PERIMETER, loading
from ._radiator import (
    WHITE,
    Alerts,
    dot,
    fit_chars,
    offline_screen,
    page_dots,
    provider,
    pulse,
    setup_screen,
)

ACCENT = PALETTE["mint"]
SPEED = 8.0  # marquee px/s: 1 px per streamed frame at fps 8
UP, DOWN, SLOW, UNKNOWN = PALETTE["ok"], PALETTE["bad"], PALETTE["amber"], PALETTE["dim"]


class UptimeSettings(AppSettings):
    targets: str = Field(
        "google.com, github.com, 1.1.1.1:53",
        max_length=600,
        title="Targets",
        description=(
            "Comma-separated. example.com (HTTPS), http://host:8080/health, host:port or tcp://host:port "
            "(TCP connect), NAME=target to label. ICMP ping needs admin rights, so it isn't supported: "
            "use a TCP port instead."
        ),
        json_schema_extra={"group": "Targets"},
    )
    every: int = Field(30, ge=10, le=600, title="Check every (s)", json_schema_extra={"group": "Targets"})
    timeout: int = Field(5, ge=1, le=20, title="Timeout (s)", json_schema_extra={"group": "Targets"})
    expect: str = Choice(
        "ok",
        {"ok": "Status < 400", "2xx": "2xx only", "any": "Any reply < 500"},
        title="HTTP counts as up when",
        group="Targets",
    )
    layout: str = Choice(
        "list", {"list": "List", "grid": "Grid", "focus": "Focus"}, title="Layout", group="Layout"
    )
    rotate: int = Field(6, ge=2, le=60, title="Seconds per page", json_schema_extra={"group": "Layout"})
    slow_ms: int = Field(
        800,
        ge=50,
        le=5000,
        title="Slow above (ms)",
        description="Latency shown amber above this",
        json_schema_extra={"group": "Layout"},
    )
    confirm: int = Field(
        2,
        ge=1,
        le=5,
        title="Failures before DOWN",
        description="Consecutive failed checks",
        json_schema_extra={"group": "Alerts"},
    )
    alerts: bool = Field(True, title="Notify on down / up", json_schema_extra={"group": "Alerts"})
    flash: bool = Field(True, title="Flash on outage", json_schema_extra={"group": "Alerts"})
    takeover: bool = Field(
        False, title="Take over the playlist while down", json_schema_extra={"group": "Alerts"}
    )

    @field_validator("targets")
    @classmethod
    def _clean(cls, v: str) -> str:
        return v.strip()


def fmt_ms(ms: float | None) -> str:
    if ms is None:
        return "--"
    if ms >= 10000:
        return f"{ms / 1000:.0f}S"
    if ms >= 1000:
        return f"{ms / 1000:.1f}S"
    return f"{ms:.0f}"


@register
class Uptime(App):
    id = "uptime"
    name = "Uptime Monitor"
    description = "HTTP and TCP checks with latency sparklines, a status grid and outage alerts."
    icon = "activity"
    category = "productivity"
    Settings = UptimeSettings
    fps = 8.0  # smooth marquees; static screens are deduped, so this costs nothing at rest
    uses = ("uptime",)

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._alerts = Alerts(ctx, provider(ctx, "uptime"))
        self._flash_at: float | None = None
        self._flash_pending = False
        self._last_t = 0.0
        self.on_settings()

    def on_start(self) -> None:
        p = provider(self.ctx, "uptime")
        if p is not None and hasattr(p, "configure"):
            s = self.settings
            p.configure(self.targets, every=s.every, timeout=s.timeout, confirm=s.confirm, expect=s.expect)

    def on_settings(self) -> None:
        self.targets = parse_targets(self.settings.targets)
        self.on_start()

    # ------------------------------------------------------------ data / alerts
    def _data(self) -> tuple[Any, list[tuple[dict[str, Any], dict[str, Any] | None]]]:
        p = provider(self.ctx, "uptime")
        states = ((p.value if p is not None else None) or {}).get("targets") or {}
        return p, [(t, states.get(t["key"])) for t in self.targets]

    def _check_events(self, p: Any) -> None:
        for ev in self._alerts.drain(p):
            down = ev["kind"] == "down"
            if down:
                self._flash_pending = True
            if self.settings.alerts:
                self.ctx.notify(
                    title=str(ev.get("label") or "TARGET")[:40],
                    message=("DOWN " + str(ev.get("error") or ""))[:280] if down else "BACK UP",
                    icon="error" if down else "ok",
                    color="#ff143c" if down else "#00ff78",
                    style="full" if down else "banner",
                    duration=8 if down else 5,
                )

    def watches_focus(self) -> bool:
        return self.settings.alerts or self.settings.takeover

    def wants_focus(self) -> bool:
        p, rows = self._data()
        self._check_events(p)
        return self.settings.takeover and any(st and st.get("up") is False for _t, st in rows)

    # ------------------------------------------------------------ helpers
    def _state_color(self, st: dict[str, Any] | None, t: float) -> RGB:
        if not st or st.get("up") is None:
            return UNKNOWN
        if st["up"] is False:
            return scale(DOWN, pulse(t, 0.4, 6.0))
        lat = st.get("latency")
        return SLOW if lat is not None and lat > self.settings.slow_ms else UP

    def _lat_color(self, ms: float | None) -> RGB:
        if ms is None:
            return DOWN
        return SLOW if ms > self.settings.slow_ms else UP

    def spark(
        self,
        f: Frame,
        x: int,
        y: int,
        w: int,
        h: int,
        hist: list[float | None],
        color: RGB,
        fill: bool,
        absolute: bool = False,
    ) -> None:
        """One column per check (newest right); failed checks are red ticks on the baseline.

        `absolute` scales from 0 to the slow threshold instead of min..max: a 3 px row would otherwise turn
        normal ±15 ms jitter into a full-height zigzag; this way a healthy target is a calm flat line and
        only real slowdowns rise."""
        vals = hist[-w:]
        if not vals:
            f.hline(x, y + h - 1, w, PALETTE["shade"])
            return
        nums = [v for v in vals if v is not None]
        lo, hi = (min(nums), max(nums)) if nums else (0.0, 1.0)
        span = max(hi - lo, max(5.0, hi * 0.15))  # keep jitter from looking dramatic
        if absolute:
            lo, span = 0.0, max(hi, float(self.settings.slow_ms))
        x0 = x + w - len(vals)
        f.hline(x, y + h - 1, x0 - x, PALETTE["ink"])
        prev: tuple[int, int] | None = None
        for i, v in enumerate(vals):
            cx = x0 + i
            if v is None:
                f.vline(cx, y + h - 2, 2, DOWN)
                prev = None
                continue
            cy = y + h - 1 - round((v - lo) / span * (h - 1))
            c = self._lat_color(v) if color == UP else color
            if fill:
                f.vline(cx, cy + 1, y + h - cy - 1, scale(c, 0.22))
            if prev is not None:
                f.line(prev[0], prev[1], cx, cy, scale(c, 0.85))
            f.set(cx, cy, c)
            prev = (cx, cy)

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        p, rows = self._data()
        self._check_events(p)
        if t < self._last_t:  # app restarted: t is relative to on_start
            self._flash_at = None
        self._last_t = t
        if self._flash_pending:
            self._flash_pending, self._flash_at = False, t
        if not self.targets:
            setup_screen(f, t, "uptime", "UPTIME", "ADD URL", ACCENT)
            return
        if not any(st for _t, st in rows):
            if p is not None and p.error:
                offline_screen(f, "uptime", "UPTIME", "ERROR")
            else:
                loading(f, t, "UPTIME", ACCENT)
            return
        {"list": self._list, "grid": self._grid, "focus": self._focus}[self.settings.layout](f, t, rows)
        self._outage_edge(f, t, rows)

    def _outage_edge(self, f: Frame, t: float, rows: list[Any]) -> None:
        if not self.settings.flash:
            return
        if self._flash_at is not None and t - self._flash_at < 4.0:
            on = int((t - self._flash_at) * 6) % 2 == 0
            if on:
                for x, y in PERIMETER:
                    f.set(x, y, DOWN)
            return
        if any(st and st.get("up") is False for _t, st in rows):
            # a slow red breath in the corners while anything is down
            c = scale(DOWN, pulse(t, 0.15, 2.0))
            for x, y in ((0, 0), (1, 0), (0, 1), (31, 0), (30, 0), (31, 1)):
                f.set(x, y, c)

    # list: three rows per page ------------------------------------------------------------------
    def _list(self, f: Frame, t: float, rows: list[Any]) -> None:
        per = 3
        pages = -(-len(rows) // per)
        pg = int(t // self.settings.rotate) % pages
        for i, (tg, st) in enumerate(rows[pg * per : pg * per + per]):
            y = 1 + i * 10
            c = self._state_color(st, t)
            f.vline(0, y, 9, c)  # status bar on the edge: colour at a glance, frees width for the name
            if st and st.get("up") is False:
                val, vc = ("DOWN" if st.get("status") is None else str(st["status"])), DOWN
            elif st and st.get("up") is None and tg["kind"] == "ping":
                val, vc = "N/A", UNKNOWN
            else:
                lat = (st or {}).get("latency")
                val, vc = fmt_ms(lat), self._lat_color(lat) if st else UNKNOWN
            vw = measure(val)
            f.text_right(30, y, val, vc)
            down = bool(st and st.get("up") is False)
            f.text(2, y, fit_chars(tg["label"], 30 - vw - 3), WHITE if down else PALETTE["mute"])
            if tg["kind"] != "ping":
                self.spark(f, 2, y + 6, 29, 3, (st or {}).get("history") or [], UP, fill=False, absolute=True)
        page_dots(f, pages, pg)

    # grid: a tile per target --------------------------------------------------------------------
    def _grid(self, f: Frame, t: float, rows: list[Any]) -> None:
        n = len(rows)
        up = sum(1 for _t, st in rows if st and st.get("up"))
        down = sum(1 for _t, st in rows if st and st.get("up") is False)
        f.text(1, 1, "UP", ACCENT)
        f.text_right(30, 1, f"{up}/{n}", DOWN if down else UP if up == n else SLOW)
        cols = 1 if n == 1 else 2 if n <= 4 else 3 if n <= 9 else 4
        nrows = -(-n // cols)
        gap = 2 if cols <= 2 else 1
        tw = (30 - gap * (cols - 1)) // cols
        th = (23 - gap * (nrows - 1)) // nrows
        for i, (tg, st) in enumerate(rows):
            x = 1 + (i % cols) * (tw + gap)
            y = 8 + (i // cols) * (th + gap)
            c = self._state_color(st, t)
            f.rect(x, y, tw, th, scale(c, 0.2))
            f.rect(x, y, tw, th, c, fill=False)
            if tw >= 13 and th >= 10:
                lab = fit_chars(tg["label"], tw - 2)
                ly = y + (th - 5) // 2 if th < 14 else y + 2
                f.text(x + (tw - measure(lab)) // 2, ly, lab, WHITE)
                if th >= 14:
                    lat = (st or {}).get("latency")
                    val = ("DOWN" if tw >= 18 else "OFF") if st and st.get("up") is False else fmt_ms(lat)
                    f.text(x + (tw - measure(val)) // 2, y + th - 7, val, mix(c, WHITE, 0.3))
            elif tw >= 5 and th >= 5:
                f.rect(x + 2, y + 2, tw - 4, th - 4, c)

    # focus: one target per screen ---------------------------------------------------------------
    def _focus(self, f: Frame, t: float, rows: list[Any]) -> None:
        i = int(t // self.settings.rotate) % len(rows)
        tg, st = rows[i]
        tr = t % self.settings.rotate
        c = self._state_color(st, t)
        draw_marquee(f, tg["label"], tr, 1, 1, 25, PALETTE["mute"], speed=SPEED)
        dot(f, 28, 2, c)
        if st and st.get("up") is False:
            f.text_center(8, "DOWN", DOWN, font="small")
            detail = (
                f"HTTP {st['status']}" if st.get("status") else str(st.get("error") or "NO REPLY").upper()
            )
            draw_marquee(f, detail, tr, 1, 17, 30, PALETTE["mute"], speed=SPEED)
        elif st and st.get("up") is None and tg["kind"] == "ping":
            f.text_center(8, "N/A", UNKNOWN, font="small")
            draw_marquee(f, "ICMP NEEDS ADMIN - USE HOST:PORT", tr, 1, 17, 30, PALETTE["mute"], speed=SPEED)
        else:
            lat = (st or {}).get("latency")
            val = fmt_ms(lat)
            unit = "" if val.endswith("S") or val == "--" else "MS"
            w = measure(val, "small") + (measure(unit) + 1 if unit else 0)
            x = (32 - w) // 2
            x = f.text(x, 8, val, WHITE, font="small")
            if unit:
                f.text(x + 2, 10, unit, self._lat_color(lat) if st else UNKNOWN)
        hist = (st or {}).get("history") or []
        if tg["kind"] == "ping":
            pass
        elif st and st.get("up") is False:
            self.spark(f, 1, 24, 30, 5, hist, UP, fill=False)
        else:
            self.spark(f, 1, 17, 30, 11, hist, UP, fill=True)
        page_dots(f, len(rows), i)

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        _p, rows = self._data()
        return {
            tg["label"]: (
                "unknown" if not st or st.get("up") is None else "up" if st["up"] else "down",
                st.get("latency") if st else None,
            )
            for tg, st in rows
        }
