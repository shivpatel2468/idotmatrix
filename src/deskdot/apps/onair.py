"""On Air (full screen): shown by the engine while the webcam or microphone is in use.

A hidden app: the engine selects it instead of the playlist while a call is live (Settings → Integrations →
On Air, style "Full screen") and hands the playlist back when the call ends. It is a clip — a 2 s breathing
loop baked once — so an hour-long call costs one GIF upload and zero Bluetooth traffic after that.
"""

from __future__ import annotations

import math

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import Frame, mix, scale

RED = (255, 16, 24)
WHITE = (255, 236, 230)

# '#' body, '+' highlight / grille (drawn dimmer)
MIC = [
    "...###...",
    "..#+#+#..",
    "..#####..",
    "..#+#+#..",
    "#.#####.#",
    "#.#+#+#.#",
    "#..###..#",
    ".#.....#.",
    "..#####..",
    "....#....",
    "....#....",
    "..#####..",
]
CAM = [
    ".#########...",
    "###...####..#",
    "##.+++.###.##",
    "##.+.+.######",
    "##.+++.######",
    "###...####.##",
    "##########..#",
    ".#########...",
]


def _glyph(f: Frame, rows: list[str], x: int, y: int, color: tuple[int, int, int]) -> None:
    hi = mix(color, (255, 255, 255), 0.55)
    for yy, row in enumerate(rows):
        for xx, ch in enumerate(row):
            if ch == "#":
                f.set(x + xx, y + yy, color)
            elif ch == "+":
                f.set(x + xx, y + yy, hi)


def draw_glyphs(f: Frame, glyph: str, bottom: int, color: tuple[int, int, int]) -> None:
    """The mic / cam / both glyph, bottom-aligned at `bottom`, centred."""
    if glyph == "both":
        w = len(CAM[0]) + 3 + len(MIC[0])
        x = (32 - w) // 2
        _glyph(f, CAM, x, bottom - len(CAM) + 1, color)
        _glyph(f, MIC, x + len(CAM[0]) + 3, bottom - len(MIC) + 1, color)
        return
    rows = CAM if glyph == "cam" else MIC
    _glyph(f, rows, (32 - len(rows[0])) // 2, bottom - len(rows) + 1, color)


class OnAirSettings(AppSettings):
    glyph: str = Choice("mic", {"mic": "Microphone", "cam": "Camera", "both": "Both"}, title="Device")
    look: str = Choice("sign", {"sign": "Lit sign", "outline": "Outline"}, title="Look")


@register
class OnAir(App):
    id = "onair"
    name = "On Air"
    description = "Full-screen ON AIR sign while your camera or microphone is live."
    icon = "radio"
    category = "productivity"
    Settings = OnAirSettings
    hidden = True
    clip_seconds = 2.4
    clip_fps = 10.0
    clip_colors = 32

    def kind(self) -> str:  # type: ignore[override]
        return "clip"

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        ph = (t / self.clip_seconds) % 1.0
        k = 0.5 - 0.5 * math.cos(ph * math.tau)  # 0 -> 1 -> 0 over one loop
        draw_glyphs(f, s.glyph, 13, scale(RED, 0.85 + 0.15 * k))
        if s.look == "outline":
            f.rect(0, 17, 32, 15, scale(RED, 0.55 + 0.45 * k), fill=False)
            self._words(f, 21, scale(RED, 0.8 + 0.2 * k))
        else:  # a lit sign: glowing red box, bright letters
            f.rect(0, 17, 32, 15, scale(RED, 0.30 + 0.12 * k))
            f.rect(0, 17, 32, 15, scale(RED, 0.75 + 0.25 * k), fill=False)
            for x, y in ((0, 17), (31, 17), (0, 31), (31, 31)):
                f.set(x, y, (0, 0, 0))
            self._words(f, 21, mix(WHITE, RED, 0.12 * (1 - k)))

    @staticmethod
    def _words(f: Frame, y: int, color: tuple[int, int, int]) -> None:
        # "ON AIR" in small type with a 2 px word gap = 28 px (a normal space would need 31)
        f.text(2, y, "ON", color, font="small")
        f.text(15, y, "AIR", color, font="small")
