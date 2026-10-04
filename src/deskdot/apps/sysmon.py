"""System monitor — CPU / RAM / disk / network from the host PC."""

from __future__ import annotations

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import PALETTE, Frame, mix, scale
from ..platforms import FEATURES
from ._kit import loading, offline, unsupported

#: bar tracks and the graph baseline: dim but still lit through the panel's gamma (see DISPLAY_DESIGN §3)
TRACK_K = 0.3


def heat(base: tuple[int, int, int] | str, pct: float) -> tuple[int, int, int]:
    """A metric's own colour, amber from 75 %, red from 90 % — distinct steps, never a muddy blend
    (magenta RAM mixed toward amber read as red, the same as a full disk)."""
    if pct >= 90:
        return PALETTE["bad"]
    if pct >= 75:
        return PALETTE["warn"]
    return mix(base, base, 0)


class SysmonSettings(AppSettings):
    layout: str = Choice("bars", {"bars": "Bars", "graph": "CPU graph"})
    cpu_color: Color = Field("#00ff8c", title="CPU")
    ram_color: Color = Field("#ff00be", title="RAM")
    disk_color: Color = Field("#ffaa00", title="Disk")


@register
class Sysmon(App):
    id = "sysmon"
    name = "System Monitor"
    description = "Live CPU, memory, storage and network from this PC."
    icon = "cpu"
    category = "data"
    Settings = SysmonSettings
    fps = 1.0
    uses = ("system",)
    platforms = FEATURES["system"]  # psutil: every native host, not the browser app
    web_reason = "A browser tab can't read the computer's CPU, memory, disk or network counters (no psutil)."

    def render(self, f: Frame, t: float) -> None:
        if not self.supported_here():
            unsupported(f, "SYSTEM")
            return
        p = self.ctx.provider("system")
        d = p.value
        if not d:
            (offline(f, "SYSTEM", "N/A") if p.error else loading(f, t, "SYSTEM"))
            return
        (self._graph if self.settings.layout == "graph" else self._bars)(f, d)

    def _bars(self, f: Frame, d: dict) -> None:  # type: ignore[type-arg]
        s = self.settings
        rows = (
            ("CPU", d["cpu"], s.cpu_color),
            ("RAM", d["ram"], s.ram_color),
            ("DSK", d["disk"], s.disk_color),
        )
        for i, (label, v, c) in enumerate(rows):
            y = 1 + i * 11
            f.text(1, y, label, scale(c, 0.75))
            if v is None:  # this host hides the metric (CPU on Android, disks in some containers)
                f.text_right(30, y, "--", scale(c, 0.5))
                f.bar(1, y + 6, 30, 2, 0.0, c, track=scale(c, TRACK_K))
                continue
            f.text_right(30, y, f"{v}%", (255, 255, 255))
            f.bar(1, y + 6, 30, 2, v / 100, heat(c, v), track=scale(c, TRACK_K))

    def _graph(self, f: Frame, d: dict) -> None:  # type: ignore[type-arg]
        s = self.settings
        f.text(1, 1, "CPU", scale(s.cpu_color, 0.75))
        cpu = d.get("cpu")
        if cpu is None:
            f.text_right(30, 1, "--", scale(s.cpu_color, 0.5), font="small")
        else:
            f.text_right(30, 1, f"{cpu}%", heat(s.cpu_color, cpu), font="small")
        hist = d.get("cpu_hist") or [0, 0]
        hist = ([0.0] * 32 + list(hist))[-32:]
        top, h = 10, 14
        f.hline(0, top + h, 32, scale(s.cpu_color, TRACK_K))
        for x, v in enumerate(hist):
            bh = round(h * v / 100)
            for k in range(bh):
                f.set(x, top + h - 1 - k, scale(s.cpu_color, 0.45 + 0.55 * (k + 1) / max(1, bh)))
        f.text(1, 26, "RAM", scale(s.ram_color, 0.75))
        ram = d.get("ram")
        f.bar(16, 27, 15, 3, (ram or 0) / 100, heat(s.ram_color, ram or 0), track=scale(s.ram_color, TRACK_K))

    def status(self) -> dict:  # type: ignore[type-arg]
        d = self.ctx.provider("system").value or {}
        return {k: d.get(k) for k in ("cpu", "ram", "disk")}
