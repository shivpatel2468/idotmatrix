"""Firmware — the panel's built-in modes. Zero Bluetooth traffic once set."""

from __future__ import annotations

from pydantic import Field

from ..device import protocol as P
from ..engine.app import App, AppSettings, Choice, Color, Kind, register
from ..gfx import Frame, hsv, to_rgb


class NativeSettings(AppSettings):
    feature: str = Choice(
        "clock",
        {
            "clock": "Clock",
            "effect": "Effect",
            "color": "Solid colour",
            "scoreboard": "Scoreboard",
            "countdown": "Countdown",
            "stopwatch": "Stopwatch",
        },
    )
    clock_style: int = Field(0, ge=0, le=7, title="Clock design (0-7)")
    show_date: bool = Field(True, title="Show date")
    hour24: bool = Field(True, title="24-hour")
    color: Color = Field("#ff4818", title="Colour")
    effect: int = Field(0, ge=0, le=6, title="Effect (0-6)")
    score_left: int = Field(0, ge=0, le=999, title="Left score")
    score_right: int = Field(0, ge=0, le=999, title="Right score")
    minutes: int = Field(5, ge=0, le=255, title="Countdown minutes")
    seconds: int = Field(0, ge=0, le=59, title="Countdown seconds")


@register
class Native(App):
    id = "native"
    name = "Firmware Modes"
    description = "The panel's own clock designs, effects, scoreboard and timers — no streaming."
    icon = "microchip"
    category = "device"
    Settings = NativeSettings

    def kind(self) -> Kind:
        return "native"

    def native_command(self) -> bytes | list[bytes]:
        s = self.settings
        rgb = to_rgb(s.color)
        match s.feature:
            case "clock":
                return [P.set_time(), P.clock(s.clock_style, s.show_date, s.hour24, rgb)]
            case "effect":
                return P.effect(s.effect, [rgb, hsv(0.33), hsv(0.66)])
            case "color":
                return P.fullscreen_color(*rgb)
            case "scoreboard":
                return P.scoreboard(s.score_left, s.score_right)
            case "countdown":
                return [P.countdown(0, 0, 0), P.countdown(1, s.minutes, s.seconds)]
            case "stopwatch":
                return [P.chronograph(0), P.chronograph(1)]
        raise ValueError(s.feature)

    def render(self, f: Frame, t: float) -> None:
        # the studio preview can't see firmware output; show what was requested instead
        s = self.settings
        if s.feature == "color":
            f.clear(s.color)
            return
        f.rect(0, 0, 32, 32, (30, 30, 44), fill=False)
        f.text_center(6, "PANEL", (90, 90, 110))
        short = {"scoreboard": "SCORE", "countdown": "TIMER", "stopwatch": "WATCH"}
        f.text_center(14, short.get(s.feature, s.feature.upper()), s.color)
        if s.feature == "scoreboard":
            f.text_center(22, f"{s.score_left}-{s.score_right}", (255, 255, 255))
