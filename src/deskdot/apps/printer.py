"""3D printer — progress ring with %, ETA, nozzle/bed temperatures and the file name (OctoPrint or Moonraker).

Layouts: ``ring`` (the panel edge is the progress bar; hero % inside) and ``rows`` (%, bar, ETA, both
temperatures as rows). A finished print gets a confetti celebration and a notification; a failed or
cancelled one gets a red card and a notification.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import PALETTE, Frame, draw_marquee, measure, mix, scale
from ..gfx.color import RGB
from ..platforms import FEATURES
from ..providers.radiator import panel_text
from ._kit import loading, unsupported
from ._radiator import (
    WHITE,
    Alerts,
    badge,
    celebrate,
    fmt_clock,
    fmt_eta,
    glyph,
    offline_screen,
    provider,
    pulse,
    setup_screen,
)
from .timer import smooth_bar, smooth_ring

ACCENT: RGB = PALETTE["ember"]
NOZZLE: RGB = PALETTE["amber"]
BED: RGB = PALETTE["magenta"]
DONE: RGB = PALETTE["ok"]
FAIL: RGB = PALETTE["bad"]
SPEED = 8.0  # marquee px/s: 1 px per streamed frame at fps 8


class PrinterSettings(AppSettings):
    kind: str = Choice(
        "octoprint",
        {"octoprint": "OctoPrint", "moonraker": "Moonraker / Klipper"},
        title="Server",
        group="Connection",
    )
    host: str = Field(
        "",
        max_length=120,
        title="Host",
        description="e.g. octopi.local or 192.168.1.50 (blank = not set up)",
        json_schema_extra={"group": "Connection"},
    )
    port: int = Field(
        0,
        ge=0,
        le=65535,
        title="Port",
        description="0 = default (OctoPrint 80, Moonraker 7125)",
        json_schema_extra={"group": "Connection"},
    )
    api_key: str = Field(
        "",
        max_length=120,
        title="API key",
        description="OctoPrint: Settings → Application Keys. Moonraker: only if required. Never logged.",
        json_schema_extra={"group": "Connection", "format": "password", "writeOnly": True},
    )
    layout: str = Choice("ring", {"ring": "Progress ring", "rows": "Rows"}, title="Layout", group="Display")
    celebrate_min: int = Field(
        10,
        ge=0,
        le=120,
        title="Celebrate for (min)",
        description="Confetti after a finished print",
        json_schema_extra={"group": "Display"},
    )
    alerts: bool = Field(True, title="Notify when done or failed", json_schema_extra={"group": "Display"})
    takeover: bool = Field(
        False, title="Take over the playlist while printing", json_schema_extra={"group": "Display"}
    )


def fmt_temp(pair: list[float | None] | None, deg: bool = True) -> str:
    a = (pair or [None, None])[0]
    return "--" if a is None else f"{a:.0f}°" if deg else f"{a:.0f}"


def heating(pair: list[float | None] | None) -> bool:
    a, tgt = (pair or [None, None])[:2]
    return a is not None and tgt is not None and tgt > 0 and tgt - a > 3


@register
class Printer(App):
    id = "printer"
    name = "3D Printer"
    description = "Print progress ring, ETA, nozzle and bed temperatures from OctoPrint or Moonraker."
    icon = "printer"
    category = "device"
    Settings = PrinterSettings
    fps = 8.0  # marquees move 1 px per frame; static screens are deduped, so rest costs nothing
    uses = ("printer",)
    platforms = FEATURES["lan"]  # OctoPrint / Moonraker answer plain http on the LAN
    web_reason = (
        "OctoPrint and Moonraker answer plain http on your network, which an https page may not call; "
        "use the desktop, Raspberry Pi or Android app."
    )

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._alerts = Alerts(ctx, provider(ctx, "printer"))
        self.on_settings()

    def on_start(self) -> None:
        p = provider(self.ctx, "printer")
        if p is not None and hasattr(p, "configure"):
            s = self.settings
            p.configure(s.kind, s.host, s.port, s.api_key)

    def on_settings(self) -> None:
        self.on_start()

    def _value(self) -> tuple[Any, dict[str, Any] | None]:
        p = provider(self.ctx, "printer")
        return p, (p.value if p is not None else None)

    def _check_events(self, p: Any) -> None:
        for ev in self._alerts.drain(p):
            if not self.settings.alerts:
                continue
            ok = ev["kind"] == "done"
            self.ctx.notify(
                title="PRINT DONE" if ok else "PRINT FAILED",
                message=str(ev.get("file") or "")[:280],
                icon="ok" if ok else "error",
                color="#00ff78" if ok else "#ff143c",
                style="celebrate" if ok else "full",
                duration=10,
            )

    def watches_focus(self) -> bool:
        return self.settings.alerts or self.settings.takeover

    def wants_focus(self) -> bool:
        p, v = self._value()
        self._check_events(p)
        return bool(self.settings.takeover and v and v.get("state") in ("printing", "paused"))

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        p, v = self._value()
        self._check_events(p)
        s = self.settings
        if not self.supported_here():
            unsupported(f, "PRINTER")
            return
        if not s.host.strip():
            setup_screen(f, t, "printer", "PRINTER", "SET HOST", ACCENT)
            return
        if v is None:
            loading(f, t, "PRINTER", ACCENT)
            return
        state = v.get("state")
        if state == "offline":
            offline_screen(f, "printer", "PRINTER", "OFFLINE")
            return
        if state == "auth":
            offline_screen(f, "printer", "PRINTER", "API KEY")
            return
        fin = v.get("finished_at")
        recent = fin is not None and time.time() - fin < max(1, s.celebrate_min) * 60
        if state in ("printing", "paused"):
            (self._ring if s.layout == "ring" else self._rows)(f, t, v)
        elif (recent and v.get("result") == "failed") or state == "failed":
            self._result(f, t, v, ok=False)
        elif state == "done" or (recent and v.get("result") == "done"):
            self._result(f, t, v, ok=True, party=recent and s.celebrate_min > 0)
        elif state == "error":
            self._error(f, t, v)
        else:
            self._idle(f, t, v)

    def _temps(
        self, f: Frame, y: int, v: dict[str, Any], t: float, x0: int = 1, x1: int = 30, deg: bool = True
    ) -> None:
        """Nozzle left, bed right; a heater still warming up pulses."""
        noz, bed = v.get("nozzle"), v.get("bed")
        nc = scale(NOZZLE, pulse(t, 0.4, 5.0)) if heating(noz) else NOZZLE
        bc = scale(BED, pulse(t, 0.4, 5.0)) if heating(bed) else BED
        f.text(x0, y, fmt_temp(noz, deg), nc)
        f.text_right(x1, y, fmt_temp(bed, deg), bc)

    def _progress(self, v: dict[str, Any]) -> float:
        return max(0.0, min(1.0, float(v.get("progress") or 0.0)))

    # ring: the edge is the progress bar -------------------------------------------------------
    def _ring(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        prog = self._progress(v)
        paused = v.get("state") == "paused"
        c = PALETTE["amber"] if paused else ACCENT
        smooth_ring(f, prog, c, track=scale(c, 0.12))
        name = panel_text(v.get("file") or "", 80).removesuffix(".GCODE") or "PRINTING"
        draw_marquee(f, name, t, 2, 3, 28, PALETTE["mute"], speed=SPEED)
        pct = f"{int(prog * 100)}"
        w = measure(pct, "big") + 1 + measure("%")
        x = (32 - w) // 2
        x = f.text(x, 9, pct, WHITE if not paused else PALETTE["amber"], font="big")
        f.text(x + 1, 14, "%", c)
        if paused:
            f.text_center(20, "PAUSED", PALETTE["amber"])
        else:
            f.text_center(20, fmt_eta(v.get("left")), PALETTE["mute"])
        self._temps(f, 26, v, t, 3, 28, deg=False)

    # rows: %, bar, ETA, temps -----------------------------------------------------------------
    def _rows(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        prog = self._progress(v)
        paused = v.get("state") == "paused"
        c = PALETTE["amber"] if paused else ACCENT
        name = panel_text(v.get("file") or "", 80).removesuffix(".GCODE") or "PRINTING"
        draw_marquee(f, name, t, 1, 1, 30, PALETTE["mute"], speed=SPEED)
        f.text(1, 8, f"{int(prog * 100)}%", WHITE, font="small")
        smooth_bar(f, 1, 16, 30, 2, prog, c, track=scale(c, 0.15))
        if paused:
            f.text_center(20, "PAUSED", c)
        else:
            f.text(1, 20, "ETA", PALETTE["dim"])
            f.text_right(30, 20, fmt_eta(v.get("left")), PALETTE["mute"])
        self._temps(f, 26, v, t)

    @staticmethod
    def _pair(pair: list[float | None] | None) -> str:
        a, tgt = (pair or [None, None])[:2]
        if a is None:
            return "--"
        return f"{a:.0f}/{tgt:.0f}" if tgt else f"{a:.0f}°"

    # results ----------------------------------------------------------------------------------
    def _result(self, f: Frame, t: float, v: dict[str, Any], ok: bool, party: bool = False) -> None:
        c = DONE if ok else FAIL
        if party:
            celebrate(f, t, c)
            # a calm, full edge that breathes (a 2 s sweep that snapped back to empty read as a glitch)
            smooth_ring(f, 1.0, scale(c, pulse(t, 0.55, 2.0)), tail=1.0, head=False)
            f.rect(1, 18, 30, 7, (0, 0, 0))  # confetti never runs through the word
        badge(f, 15, 11, 6, "pass" if ok else "fail", t)
        f.text_center(19, "DONE" if ok else "FAILED", c)
        name = panel_text(v.get("file") or "", 80).removesuffix(".GCODE")
        if party:
            return
        if name:
            draw_marquee(f, name, t, 1, 26, 30, PALETTE["mute"], speed=SPEED)
        elif v.get("elapsed"):
            f.text_center(26, fmt_clock(v.get("elapsed")), PALETTE["mute"])

    def _error(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        offline_screen(f, "printer", "ERROR", "")
        msg = panel_text(v.get("message") or "PRINTER ERROR", 80)
        draw_marquee(f, msg, t, 1, 24, 30, FAIL, speed=SPEED)

    def _idle(self, f: Frame, t: float, v: dict[str, Any]) -> None:
        g = glyph("printer", scale(ACCENT, 0.8))
        f.sprite(g, 1, 1)
        f.text(12, 3, "IDLE", mix(ACCENT, WHITE, 0.2))
        f.text(1, 14, "NOZ", PALETTE["dim"])
        f.text_right(30, 14, fmt_temp(v.get("nozzle")), NOZZLE)
        f.text(1, 22, "BED", PALETTE["dim"])
        f.text_right(30, 22, fmt_temp(v.get("bed")), BED)

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        _p, v = self._value()
        v = v or {}
        return {
            "server": self.settings.kind,
            "state": v.get("state", "unset"),
            "progress": round(float(v["progress"]) * 100, 1) if v.get("progress") is not None else None,
            "eta_s": round(v["left"]) if v.get("left") is not None else None,
            "file": v.get("file") or None,
            "nozzle": (v.get("nozzle") or [None])[0],
            "bed": (v.get("bed") or [None])[0],
            "api_key": "set" if self.settings.api_key else "",
        }
