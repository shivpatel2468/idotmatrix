"""Timer — Pomodoro, countdown and stopwatch with an edge progress ring."""

from __future__ import annotations

import time
from typing import Any

from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Color, register
from ..gfx import Frame, mix, scale
from ..gfx.color import ColorLike, to_rgb
from ._kit import PERIMETER


def smooth_ring(
    f: Frame,
    progress: float,
    color: ColorLike,
    track: ColorLike | None = None,
    tail: float = 0.4,
    head: bool = True,
) -> None:
    """The edge progress ring with a sub-LED leading edge: the next LED fades in with the remainder
    (quantised to 8 levels, so the baked/streamed palette stays small), so a slow drain or fill glides
    instead of stepping one LED every few seconds. Clockwise from 12 o'clock, like `_kit.ring`."""
    n = len(PERIMETER)
    exact = n * max(0.0, min(1.0, progress))
    full = int(exact + 1e-9)
    rem = round((exact - full) * 8) / 8
    if rem >= 1.0:
        full, rem = full + 1, 0.0
    c = to_rgb(color)
    tr = to_rgb(track) if track is not None else (0, 0, 0)
    if track is not None:
        for x, y in PERIMETER[full:]:
            f.set(x, y, tr)
    for i, (x, y) in enumerate(PERIMETER[:full]):
        k = tail + (1 - tail) * (i / max(1.0, exact - 1)) if full > 1 else 1.0
        f.set(x, y, scale(c, min(1.0, k)))
    if head and full > 0:
        f.set(*PERIMETER[full - 1], mix(c, (255, 255, 255), 0.45))
    if rem > 0 and full < n:
        f.set(*PERIMETER[full], mix(tr, c, rem))


def smooth_bar(
    f: Frame, x: int, y: int, w: int, h: int, value: float, color: ColorLike, track: ColorLike = (24, 24, 32)
) -> None:
    """`Frame.bar` with a sub-pixel end: the next column lights in proportion (8 levels), so a slowly
    growing bar creeps instead of jumping a whole column at a time."""
    c, tr = to_rgb(color), to_rgb(track)
    f.rect(x, y, w, h, tr)
    exact = w * max(0.0, min(1.0, value))
    full = int(exact + 1e-9)
    f.rect(x, y, full, h, c)
    rem = round((exact - full) * 8) / 8
    if 0 < rem < 1 and full < w:
        f.rect(x + full, y, 1, h, mix(tr, c, rem))


class TimerSettings(AppSettings):
    mode: str = Choice(
        "pomodoro", {"pomodoro": "Pomodoro", "countdown": "Countdown", "stopwatch": "Stopwatch"}
    )
    focus: int = Field(25, ge=1, le=180, title="Focus (min)")
    short_break: int = Field(5, ge=1, le=60, title="Break (min)")
    long_break: int = Field(15, ge=1, le=90, title="Long break (min)")
    rounds: int = Field(4, ge=1, le=12, title="Rounds before long break")
    countdown: int = Field(10, ge=1, le=999, title="Countdown (min)")
    focus_color: Color = Field("#ff1e5a", title="Focus colour")
    break_color: Color = Field("#00ff8c", title="Break colour")


@register
class Timer(App):
    id = "timer"
    name = "Focus Timer"
    description = "Pomodoro cycles, countdowns and a stopwatch. Notifies when a phase ends."
    icon = "timer"
    category = "productivity"
    Settings = TimerSettings
    fps = 2.0
    actions = (
        Action("toggle", "Start/Pause", "play"),
        Action("reset", "Reset", "rotate-ccw"),
        Action("skip", "Skip", "skip-forward"),
    )

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.running = False
        self.phase = "focus"  # focus | break | long
        self.round = 1
        self.elapsed = 0.0  # seconds accumulated while paused
        self.since: float | None = None

    # ----------------------------------------------------------------- model
    def _length(self) -> float:
        s = self.settings
        if s.mode == "countdown":
            return s.countdown * 60.0
        if s.mode == "stopwatch":
            return 0.0
        return {"focus": s.focus, "break": s.short_break, "long": s.long_break}[self.phase] * 60.0

    def _spent(self) -> float:
        return self.elapsed + (time.monotonic() - self.since if self.running and self.since else 0.0)

    def on_settings(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self.running, self.elapsed, self.since = False, 0.0, None

    def _next_phase(self, notify: bool) -> None:
        s = self.settings
        if s.mode == "pomodoro":
            if self.phase == "focus":
                self.phase = "long" if self.round % s.rounds == 0 else "break"
            else:
                self.phase = "focus"
                self.round += 1
            msg = {"focus": "BACK TO FOCUS", "break": "TAKE A BREAK", "long": "LONG BREAK"}[self.phase]
        else:
            msg = "TIME IS UP"
        if notify:
            self.ctx.notify(
                title="TIMER", message=msg, icon="bell", color=self._color(), style="full", duration=6
            )
        keep = s.mode == "pomodoro" and self.running
        self.elapsed, self.since = 0.0, time.monotonic() if keep else None
        self.running = keep

    def _color(self) -> str:
        return self.settings.break_color if self.phase != "focus" else self.settings.focus_color

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name == "toggle":
            if self.running:
                self.elapsed, self.running, self.since = self._spent(), False, None
            else:
                self.running, self.since = True, time.monotonic()
        elif name == "reset":
            self._reset()
            self.phase, self.round = "focus", 1
        elif name == "skip":
            self._next_phase(notify=False)
        else:
            raise KeyError(name)
        return self.status()

    # ---------------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        length = self._length()
        spent = self._spent()
        if length and spent >= length:
            self._next_phase(notify=True)
            spent, length = self._spent(), self._length()
        color = self._color()
        if s.mode == "stopwatch":
            secs = int(spent)
            label = "WATCH"
            prog = (spent % 60) / 60
        else:
            secs = max(0, int(length - spent + 0.999))
            label = (
                {"focus": "FOCUS", "break": "BREAK", "long": "REST"}[self.phase]
                if s.mode == "pomodoro"
                else "TIMER"
            )
            prog = 1 - spent / length if length else 0
        mm, ss = divmod(secs, 60)
        txt = f"{mm:02d}:{ss:02d}" if mm < 100 else f"{mm}M"
        dim = not self.running and int(t * 2) % 2 == 1 and spent > 0
        f.text_center(5, label, scale(color, 0.85))
        f.text(1, 12, txt, scale((255, 255, 255), 0.35 if dim else 1.0), font="big")
        if s.mode == "pomodoro":
            n = s.rounds
            x0 = 16 - (n * 3 - 1) // 2
            done = (self.round - 1) % n
            for i in range(n):
                f.rect(x0 + i * 3, 25, 2, 2, color if i < done else scale(color, 0.3))
        smooth_ring(f, prog, color, track=scale(color, 0.1))  # full, unbroken ring (gaps read as "cut")

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "phase": self.phase,
            "round": self.round,
            "remaining": max(0.0, self._length() - self._spent()) if self._length() else self._spent(),
        }
