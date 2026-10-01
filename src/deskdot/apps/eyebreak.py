"""Eye break (20-20-20): every N minutes of continuous computer use, look 20 ft away for 20 s.

A hidden app the engine shows for ~24 s when the break is due (Settings → Integrations → Eye break), then it
hands the panel back. Calm by design: dim mint/teal, a slow breathing orb, no blinking. It never fires while
you are On Air or a full-screen app / game is up; a natural break (2 min without input) resets the timer.
"""

from __future__ import annotations

import math

import numpy as np

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import Frame, mix, scale
from ..gfx.icons import draw_icon
from .timer import smooth_ring

INTRO = 2.5  # "LOOK AWAY 20S" title card
SECONDS = 20
OUTRO = 1.5
TOTAL = INTRO + SECONDS + OUTRO

MINT = (0, 255, 170)
TEAL = (0, 150, 190)
SOFT = (200, 255, 235)

_YY, _XX = np.mgrid[0:32, 0:32].astype(np.float32)


def breath(t: float, period: float = 6.0) -> float:
    """0..1..0, slow and smooth: in for 3 s, out for 3 s."""
    return 0.5 - 0.5 * math.cos((t % period) / period * math.tau)


def orb(f: Frame, cx: float, cy: float, radius: float, color: tuple[int, int, int], peak: float) -> None:
    """A soft radial glow (additive-looking falloff), kept dim so text stays readable on top."""
    d = np.sqrt((_XX - cx) ** 2 + (_YY - cy) ** 2)
    a = np.clip(1.0 - d / max(1.0, radius), 0.0, 1.0) ** 1.25 * peak
    glow = a[..., None] * np.array(color, dtype=np.float32)
    f.px[:] = np.maximum(f.px.astype(np.float32), glow).astype(np.uint8)


class EyeBreakSettings(AppSettings):
    style: str = Choice("breathe", {"breathe": "Breathing orb", "ring": "Countdown ring"}, title="Style")


@register
class EyeBreak(App):
    id = "eyebreak"
    name = "Eye Break"
    description = "The 20-20-20 nudge: look 20 ft away for 20 seconds."
    icon = "eye"
    category = "productivity"
    Settings = EyeBreakSettings
    hidden = True
    fps = 8.0

    def render(self, f: Frame, t: float) -> None:
        if t < INTRO:
            self._intro(f, t)
        elif t < INTRO + SECONDS:
            left = SECONDS - (t - INTRO)
            (self._ring if self.settings.style == "ring" else self._breathe)(f, t, left)
        else:
            self._done(f, t - INTRO - SECONDS)

    def _intro(self, f: Frame, t: float) -> None:
        k = min(1.0, 0.35 + 0.65 * t / 0.6)  # never a black first frame
        orb(f, 15.5, 15.5, 16 + 4 * breath(t), TEAL, 0.30 * k)
        f.text_center(5, "LOOK", scale(SOFT, k), font="small")
        f.text_center(14, "AWAY", scale(SOFT, k), font="small")
        f.text_center(25, "20S", scale(MINT, k))

    def _breathe(self, f: Frame, t: float, left: float) -> None:
        b = breath(t - INTRO)
        orb(f, 15.5, 15.5, 10 + 8 * b, mix(TEAL, MINT, b), 0.38 + 0.27 * b)
        f.text_center(1, "LOOK", scale(SOFT, 0.75))
        f.text_center(11, f"{math.ceil(left)}", (255, 255, 255), font="big")
        f.text_center(26, "AWAY", scale(SOFT, 0.75))

    def _ring(self, f: Frame, t: float, left: float) -> None:
        # drains smoothly: the leading LED fades out with the remainder instead of stepping (8 fps, 6 LEDs/s)
        smooth_ring(f, left / SECONDS, scale(MINT, 0.55), track=(0, 22, 18), tail=1.0, head=False)
        b = breath(t - INTRO)
        draw_icon(f, "eye", 9, 2, scale(mix(TEAL, MINT, b), 0.6 + 0.4 * b), 2)  # 14 x 10 lit area
        f.text_center(16, f"{math.ceil(left)}", (255, 255, 255), font="small")
        f.text_center(25, "AWAY", scale(SOFT, 0.6))

    def _done(self, f: Frame, t: float) -> None:
        k = max(0.0, 1.0 - t / OUTRO)
        draw_icon(f, "ok", 11, 6, scale(MINT, k), 2)
        f.text_center(22, "DONE", scale(SOFT, k), font="small")

    def status(self) -> dict:  # type: ignore[type-arg]
        return {"break": f"{SECONDS}s", "rule": "20-20-20"}
