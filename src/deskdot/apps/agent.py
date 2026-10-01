"""Agent — a pixel Claude mascot that mirrors what your AI agent is doing.

Drive it from Claude Code hooks (see docs/MCP.md), the MCP `agent_state` tool,
or `POST /api/agent/{state}`.
"""

from __future__ import annotations

import math

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, Kind, register
from ..gfx import Frame, scale

STATES = {
    "idle": "Idle",
    "thinking": "Thinking",
    "working": "Working",
    "waiting": "Needs input",
    "done": "Done",
    "error": "Error",
    "sleeping": "Sleeping",
}
LABELS = {
    "idle": "READY",
    "thinking": "THINK",
    "working": "WORKING",
    "waiting": "WAITING",
    "done": "DONE!",
    "error": "ERROR",
    "sleeping": "ZZZ",
}
LABEL_COLOR = {
    "idle": (140, 140, 160),
    "thinking": (80, 170, 255),
    "working": (0, 220, 255),
    "waiting": (255, 214, 0),
    "done": (0, 255, 120),
    "error": (255, 20, 60),
    "sleeping": (110, 90, 200),
}


class AgentSettings(AppSettings):
    state: str = Choice("idle", STATES, title="State")
    label: bool = Field(True, title="Show label")
    color: Color = Field("#f94a18", title="Body colour")  # Claude orange as it reads on the LEDs


@register
class Agent(App):
    id = "agent"
    name = "Claude Mascot"
    description = "Animated Claude sprite for agent status: thinking, working, waiting, done."
    icon = "bot"
    category = "productivity"
    Settings = AgentSettings
    clip_seconds = 2.4
    clip_fps = 10.0

    def kind(self) -> Kind:
        return "clip"

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        st = s.state
        period = self.clip_seconds
        ph = (t % period) / period  # 0..1, loops seamlessly
        body = s.color
        eye = (0, 0, 0)

        dx = dy = 0
        if st == "idle":
            dy = 1 if ph > 0.5 else 0
        elif st == "thinking":
            dy = round(math.sin(ph * math.tau))
        elif st == "done":
            dy = -round(3 * abs(math.sin(ph * math.tau * 2)))
        elif st == "error":
            dx = [0, -1, 1, -1, 1, 0, 0, 0, 0, 0][int(ph * 10)]
        elif st == "sleeping":
            dy = 1 if ph > 0.5 else 0
        oy = 3 if s.label else 0

        x0, y0 = 8 + dx, 9 + oy + dy
        # legs stay planted while the body bobs down onto them, but leave the floor with it on a jump —
        # a body floating above its own feet reads as broken
        for lx in (9, 13, 17, 21):
            f.rect(lx + dx, 21 + oy + min(0, dy), 2, 4, body)
        # arms
        arm_l = arm_r = 0
        if st == "working":
            arm_l = -1 if int(ph * 8) % 2 else 1
            arm_r = -arm_l
        elif st == "done":
            arm_l = arm_r = -3
        elif st == "waiting":
            arm_r = -3 if ph < 0.5 else -2
        f.rect(x0 - 3, y0 + 4 + arm_l, 3, 4, body)
        f.rect(x0 + 16, y0 + 4 + arm_r, 3, 4, body)
        # body: one flat colour, like the real Clawd
        f.rect(x0, y0, 16, 12, body)
        # eyes
        ex1, ex2, ey = x0 + 3, x0 + 11, y0 + 3
        blink = st in ("idle", "waiting") and 0.62 < ph < 0.68
        if st == "sleeping" or blink:
            f.hline(ex1, ey + 2, 2, eye)
            f.hline(ex2, ey + 2, 2, eye)
        elif st == "done":  # happy ^ ^
            for ex in (ex1, ex2):
                f.set(ex, ey + 1, eye)
                f.set(ex + 1, ey, eye)
                f.set(ex + 2, ey + 1, eye)
        elif st == "error":  # x x
            for ex in (ex1, ex2):
                f.line(ex, ey, ex + 2, ey + 2, eye)
                f.line(ex + 2, ey, ex, ey + 2, eye)
        else:
            look = 1 if st == "thinking" else 0
            f.rect(ex1 + look, ey - look, 2, 3, eye)
            f.rect(ex2 + look, ey - look, 2, 3, eye)

        # props sit on a fixed row under the label (not on the bobbing body), so they never merge into it
        top = 9 + oy - 5
        accent = LABEL_COLOR[st]
        if st == "thinking":
            for i in range(3):
                on = int(ph * 6) % 3 == i
                f.rect(x0 + 4 + i * 4, top, 2, 2, accent if on else scale(accent, 0.3))
        elif st == "working":
            ky = min(31, y0 + 17)
            f.hline(4, ky, 24, (50, 50, 64))
            k = int(ph * 12)
            f.set(5 + (k * 7) % 22, ky, (0, 255, 200))
            f.set(5 + (k * 11 + 5) % 22, ky, (0, 220, 255))
        elif st == "waiting":
            if s.label:  # a smaller ? that hops with the waving hand, clear of the label row and of the hand
                by = 7 if ph < 0.5 else 8
                f.text(x0 + 16, by, "?", accent)
            else:
                by = top - round(abs(math.sin(ph * math.tau)) * 2)
                f.text(x0 + 14, by, "?", accent, font="small")
        elif st == "done":
            for i, (sx, sy) in enumerate(((3, 8), (28, 10), (5, 20), (27, 22))):
                if (int(ph * 8) + i) % 2 == 0:
                    f.set(sx, sy + oy, (255, 255, 255))
                    f.set(sx, sy + oy - 1, scale(accent, 0.6))
        elif st == "error":
            f.text(x0 + 17, top, "!", accent, font="small")
        elif st == "sleeping":
            # a Z drifts up beside the head, fading in and out so the loop wraps without a pop
            zy = top + 3 - int(ph * 4)
            f.text(x0 + 17, zy, "Z", scale(accent, 0.3 + 0.7 * math.sin(math.pi * ph)))

        if s.label:
            f.text_center(1, LABELS[st], accent)

    def status(self) -> dict:  # type: ignore[type-arg]
        return {"state": self.settings.state}
