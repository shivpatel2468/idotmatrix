"""Focus Pet — cute animated productivity companion and desk Tamagotchi for 32x32.

Accompanies deep work sessions with Pomodoro cycles: typing at a laptop with steaming coffee
during focus, stretching and drinking boba during breaks, and sleeping under a starry window.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame

TAU = math.tau

# Color palettes
THEMES = {
    "cozy": {
        "bg": (18, 16, 24),
        "wall": (28, 24, 36),
        "wood": (140, 85, 45),
        "wood_dark": (100, 55, 30),
        "laptop": (180, 185, 200),
        "screen": (80, 180, 255),
        "text": (255, 240, 200),
        "accent": (255, 120, 150),
    },
    "nordic": {
        "bg": (20, 24, 30),
        "wall": (32, 38, 48),
        "wood": (170, 140, 100),
        "wood_dark": (120, 95, 65),
        "laptop": (200, 210, 220),
        "screen": (100, 220, 200),
        "text": (230, 240, 250),
        "accent": (255, 160, 90),
    },
    "cyber": {
        "bg": (8, 6, 16),
        "wall": (18, 14, 32),
        "wood": (80, 90, 140),  # lifted: (40, 45, 70) furniture vanished on the LEDs
        "wood_dark": (52, 58, 95),
        "laptop": (90, 100, 130),
        "screen": (0, 240, 255),
        "text": (255, 0, 180),
        "accent": (0, 255, 160),
    },
    "warm": {
        "bg": (24, 18, 16),
        "wall": (38, 28, 24),
        "wood": (160, 90, 50),
        "wood_dark": (115, 60, 32),
        "laptop": (190, 180, 170),
        "screen": (255, 190, 90),
        "text": (255, 245, 220),
        "accent": (255, 90, 70),
    },
}

SPECIES_COLORS = {
    "bunny": {"fur": (245, 240, 235), "inner": (255, 180, 190), "eye": (40, 35, 45)},
    "cat": {"fur": (240, 150, 60), "inner": (255, 200, 160), "eye": (30, 160, 80)},
    "dog": {"fur": (180, 120, 70), "inner": (220, 170, 130), "eye": (35, 25, 20)},
    "fox": {"fur": (235, 85, 35), "inner": (250, 230, 210), "eye": (40, 25, 15)},
    "robot": {"fur": (130, 160, 190), "inner": (0, 220, 255), "eye": (0, 240, 255)},
}


class FocusPetSettings(AppSettings):
    activity: str = Choice(
        "focus",
        {
            "focus": "Focus / Deep Work",
            "break": "Coffee / Stretch Break",
            "sleep": "Night / Cozy Rest",
        },
        title="Companion State",
    )
    species: str = Choice(
        "bunny",
        {
            "bunny": "Mochi Bunny",
            "cat": "Ginger Cat",
            "dog": "Shiba Dog",
            "fox": "Kitsune Fox",
            "robot": "Byte Bot",
        },
        title="Pet Character",
    )
    accessory: str = Choice(
        "glasses",
        {
            "none": "No Accessory",
            "glasses": "Study Glasses",
            "headphones": "Lofi Headphones",
            "crown": "Focus Crown",
        },
        title="Head Accessory",
    )
    theme: str = Choice(
        "cozy",
        {
            "cozy": "Cozy Warm",
            "nordic": "Nordic Minimal",
            "cyber": "Cyberpunk Neon",
            "warm": "Autumn Hearth",
        },
        title="Room Style",
    )
    timer_bar: str = Choice(
        "on",
        {
            "on": "Show Progress HUD",
            "off": "Hide Progress HUD",
        },
        title="Top Progress HUD",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, title="Animation Speed")
    brightness: float = Field(default=1.0, ge=0.2, le=1.0, title="LED Brightness")


@register
class FocusPet(App):
    id = "focuspet"
    name = "Focus Companion"
    category = "productivity"
    description = "Lofi animated productivity pet that studies, takes breaks, and rests with you."
    Settings = FocusPetSettings

    clip_seconds = 6.0  # 48 frames at 8.0 fps
    clip_fps = 8.0
    clip_colors = 32
    fps = 8.0
    _p = 0.0  # loop phase of the frame being drawn (set by render)

    def kind(self) -> Kind:
        return "clip"

    def n_frames(self) -> int:
        """Frames per loop: speed picks the loop length (48 at speed 1), never the frame duration."""
        return min((24, 32, 48, 64, 96), key=lambda n: abs(n - 48 / self.settings.speed))

    def _ph(self, t: float) -> float:
        return (t * self.clip_fps / self.n_frames()) % 1.0

    def render(self, f: Frame, t: float) -> None:
        # Every animation below is a function of the loop phase with a whole number of cycles per loop
        # (`_cyc`), so render(0) == render(n_frames / fps): the baked GIF wraps without a jump.
        s = self.settings
        self._p = self._ph(t)
        theme = THEMES.get(s.theme, THEMES["cozy"])
        spec = SPECIES_COLORS.get(s.species, SPECIES_COLORS["bunny"])

        # Base background
        f.rect(0, 0, 32, 22, theme["bg"])
        f.rect(0, 22, 32, 10, theme["wall"])

        # Render Activity Scene
        if s.activity == "sleep":
            self._render_sleep(f, t, theme, spec, s)
        elif s.activity == "break":
            self._render_break(f, t, theme, spec, s)
        else:  # "focus"
            self._render_focus(f, t, theme, spec, s)

        # Top Progress HUD
        if s.timer_bar == "on":
            self._render_hud(f, t, theme, s)

        # Brightness adjustment
        if s.brightness < 1.0:
            import numpy as np

            f.px[:] = (f.px.astype(np.float32) * s.brightness).astype(np.uint8)

    def _cyc(self, cycles: int) -> float:
        """Phase (0..1) of something that repeats `cycles` times per loop."""
        return (self._p * cycles) % 1.0

    def _tick(self, n: int) -> int:
        """Which of n even steps of the loop we are in."""
        return int(self._p * n) % n

    def _render_hud(self, f: Frame, t: float, theme: dict[str, Any], s: FocusPetSettings) -> None:
        """Four Pomodoro pips along the top edge: two done, the current one breathing, one to go."""
        accent = theme["accent"] if s.activity != "break" else (100, 240, 140)
        breathe = 0.55 + 0.45 * math.sin(self._cyc(1) * TAU)
        for k in range(4):
            if k < 2:
                col = accent
            elif k == 2:
                col = tuple(round(c * (round(breathe * 4) / 4)) for c in accent)
            else:
                col = (46, 46, 64)
            f.hline(1 + k * 8, 0, 6, col)  # type: ignore[arg-type]

    def _render_focus(
        self, f: Frame, t: float, theme: dict[str, Any], spec: dict[str, Any], s: FocusPetSettings
    ) -> None:
        """Pet sitting at desk with open glowing laptop and steaming mug."""
        bounce = -(self._tick(8) % 2)  # a small typing bob, 1 px, on an even beat

        # Window with calm night stars
        f.rect(2, 3, 7, 7, (8, 10, 18))
        f.rect(2, 3, 7, 1, theme["wood_dark"])
        f.rect(2, 9, 7, 1, theme["wood_dark"])
        f.rect(2, 3, 1, 7, theme["wood_dark"])
        f.rect(8, 3, 1, 7, theme["wood_dark"])
        # Star twinkle
        if self._tick(12) % 2 == 0:
            f.set(4, 5, (220, 240, 255))
        f.set(6, 7, (200, 220, 240))

        # Wooden Desk
        desk_y = 20
        f.hline(0, desk_y, 32, theme["wood"])
        f.hline(0, desk_y + 1, 32, theme["wood_dark"])
        f.vline(3, desk_y + 2, 10, theme["wood_dark"])
        f.vline(28, desk_y + 2, 10, theme["wood_dark"])

        # Steaming Mug
        f.rect(26, 17, 4, 3, (240, 240, 240))
        f.set(25, 18, (240, 240, 240))  # handle
        f.hline(26, 17, 4, (120, 70, 40))  # coffee
        # Animated steam: two wisps rising 3 px and fading, half a cycle apart
        for off in (0.0, 0.5):
            q = (self._cyc(4) + off) % 1.0
            k = 1.0 - q * 0.7
            f.set(
                27 + (1 if q > 0.5 else 0), 16 - int(q * 3), (round(190 * k), round(190 * k), round(200 * k))
            )

        # Bonsai / Small Plant on desk
        f.rect(1, 17, 3, 3, (160, 100, 60))  # pot
        f.set(2, 16, (40, 180, 70))
        f.set(1, 15, (50, 210, 80))
        f.set(3, 15, (30, 160, 60))

        # Pet Body & Head
        py = 14 + bounce
        px = 8
        self._draw_pet(f, px, py, spec, s, state="focus", t=t)

        # Open Laptop
        # Screen
        f.vline(19, 13, 7, theme["laptop"])
        f.rect(20, 13, 5, 7, theme["screen"])
        # Screen code lines
        code_blink = self._tick(24) % 3
        f.hline(21, 15, 3, (255, 255, 255) if code_blink == 0 else (180, 230, 255))
        f.hline(21, 17, 2, (255, 255, 255) if code_blink == 1 else (180, 230, 255))
        # Base keyboard
        f.hline(18, 20, 7, theme["laptop"])

        # Animated Typing Hands
        hand_toggle = self._tick(24) % 2
        f.set(17, 19 + hand_toggle, spec["fur"])
        f.set(18, 19 + (1 - hand_toggle), spec["fur"])

    def _render_break(
        self, f: Frame, t: float, theme: dict[str, Any], spec: dict[str, Any], s: FocusPetSettings
    ) -> None:
        """Pet stretching, drinking boba tea with bubbles and smiling."""
        # four hops per loop: up 1, 2, down again, then a rest on the floor
        hop = round(2 * max(0.0, math.sin(self._cyc(4) * TAU)))

        # Sunny outdoor / window background
        f.rect(3, 4, 10, 10, (120, 200, 255))
        f.rect(3, 4, 10, 1, theme["wood_dark"])
        f.rect(3, 13, 10, 1, theme["wood_dark"])
        f.rect(3, 4, 1, 10, theme["wood_dark"])
        f.rect(12, 4, 1, 10, theme["wood_dark"])
        # Bright sun
        f.rect(8, 6, 3, 3, (255, 220, 50))

        # Potted floor plant
        f.rect(25, 23, 5, 5, (180, 110, 60))
        f.rect(24, 17, 7, 6, (40, 190, 70))
        f.set(27, 15, (60, 230, 90))

        # Floor line
        f.hline(0, 26, 32, theme["wood_dark"])

        # Pet standing in center
        px = 12
        py = 15 - hop
        self._draw_pet(f, px, py, spec, s, state="break", t=t)

        # Boba Cup in hands
        cup_y = py + 5
        f.rect(px + 7, cup_y, 4, 5, (230, 235, 245))  # cup
        f.hline(px + 7, cup_y + 1, 4, (210, 160, 110))  # milk tea
        f.hline(px + 7, cup_y + 4, 4, (40, 25, 20))  # tapioca pearls
        f.vline(px + 9, cup_y - 2, 3, (255, 100, 150))  # straw

        # Floating happy musical note or heart
        if self._tick(12) % 2 == 0:
            f.set(px + 10, py - 2, (255, 120, 160))
            f.set(px + 11, py - 3, (255, 120, 160))
            f.set(px + 12, py - 2, (255, 120, 160))

    def _render_sleep(
        self, f: Frame, t: float, theme: dict[str, Any], spec: dict[str, Any], s: FocusPetSettings
    ) -> None:
        """Pet curled under cozy quilt in bed with floating z Z Z."""
        breath = 1 if self._cyc(2) >= 0.5 else 0  # slow breathing: two breaths per loop

        # Starry window with crescent moon
        f.rect(20, 3, 9, 9, (6, 8, 20))
        frame_c = (72, 64, 90)  # lifted: the old (40, 35, 50) frame vanished
        f.rect(20, 3, 9, 1, frame_c)
        f.rect(20, 11, 9, 1, frame_c)
        f.rect(20, 3, 1, 9, frame_c)
        f.rect(28, 3, 1, 9, frame_c)
        # Golden crescent moon (a C shape, not a bar)
        moon = (255, 220, 80)
        for x, y in ((24, 5), (25, 5), (23, 6), (23, 7), (23, 8), (24, 9), (25, 9), (26, 5), (26, 9)):
            f.set(x, y, moon)

        # Wooden bed frame
        f.rect(4, 21, 24, 7, theme["wood_dark"])
        f.rect(2, 16, 3, 12, theme["wood"])  # headboard
        f.rect(27, 19, 3, 9, theme["wood"])  # footboard

        # Pillow
        f.rect(5, 18, 6, 4, (240, 240, 245))

        # Pet head sleeping on pillow
        px = 8
        py = 17 + breath
        self._draw_pet(f, px, py, spec, s, state="sleep", t=t)

        # Patchwork Quilt
        quilt_c1 = theme["accent"]
        quilt_c2 = (quilt_c1[0] // 2, quilt_c1[1] // 2, quilt_c1[2] // 2)
        f.rect(13, 20, 14, 6, quilt_c1)
        for qx in range(13, 27, 4):
            f.rect(qx, 20, 2, 6, quilt_c2)

        # Floating Snoring 'z' 'Z' 'Z'
        z_cycle = self._cyc(3) * 3.0
        if z_cycle < 1.0:
            f.set(11, 13, (180, 200, 240))
        elif z_cycle < 2.0:
            f.set(13, 11, (200, 220, 255))
            f.set(14, 11, (200, 220, 255))
        else:
            f.set(15, 9, (230, 240, 255))
            f.set(16, 9, (230, 240, 255))
            f.set(16, 8, (230, 240, 255))

    def _draw_pet(
        self,
        f: Frame,
        x: int,
        y: int,
        spec: dict[str, Any],
        s: FocusPetSettings,
        state: str,
        t: float,
    ) -> None:
        """Render species body, head, face, and accessory."""
        fur = spec["fur"]
        inner = spec["inner"]
        eye = spec["eye"]
        species = s.species

        # Body
        if state != "sleep":
            f.rect(x + 1, y + 4, 6, 5, fur)

        # Ears based on species
        if species == "bunny":
            f.rect(x + 1, y - 5, 2, 5, fur)
            f.rect(x + 5, y - 5, 2, 5, fur)
            f.set(x + 1, y - 3, inner)
            f.set(x + 5, y - 3, inner)
        elif species in ("cat", "fox"):
            f.set(x + 1, y - 2, fur)
            f.set(x + 2, y - 1, fur)
            f.set(x + 5, y - 1, fur)
            f.set(x + 6, y - 2, fur)
            f.set(x + 1, y - 1, inner)
            f.set(x + 6, y - 1, inner)
        elif species == "dog":
            # Floppy ears
            f.rect(x, y - 1, 2, 4, inner)
            f.rect(x + 6, y - 1, 2, 4, inner)
        elif species == "robot":
            # Antenna
            f.vline(x + 3, y - 4, 4, (100, 120, 140))
            f.set(x + 3, y - 5, (255, 60, 60))

        # Head
        f.rect(x + 1, y - 1, 6, 6, fur)

        # Face
        if state == "sleep":
            # Closed happy sleeping eyes (- -)
            f.hline(x + 2, y + 1, 2, eye)
            f.hline(x + 5, y + 1, 2, eye)
        else:
            # Blink logic
            blink = self._tick(24) % 12 == 0  # two short blinks per loop
            if blink:
                f.hline(x + 2, y + 1, 2, eye)
                f.hline(x + 5, y + 1, 2, eye)
            else:
                f.set(x + 2, y + 1, eye)
                f.set(x + 5, y + 1, eye)
            # Nose / Smile
            f.set(x + 3, y + 2, inner)
            f.set(x + 4, y + 2, inner)
            # Cheeks
            f.set(x + 1, y + 2, (255, 140, 160))
            f.set(x + 6, y + 2, (255, 140, 160))

        # Accessories
        if s.accessory == "glasses" and state != "sleep":
            rim = (220, 180, 50)  # gold rims round each eye (at 6 px a bridge would join them into a mask)
            f.rect(x + 1, y, 3, 3, rim, fill=False)
            f.rect(x + 4, y, 3, 3, rim, fill=False)
            f.set(x + 2, y + 1, eye)
            f.set(x + 5, y + 1, eye)
        elif s.accessory == "headphones":
            f.rect(x, y, 1, 4, (255, 80, 80))
            f.rect(x + 7, y, 1, 4, (255, 80, 80))
            f.hline(x + 1, y - 2, 6, (60, 60, 70))
        elif s.accessory == "crown":
            f.hline(x + 2, y - 3, 4, (255, 215, 0))
            f.set(x + 2, y - 4, (255, 215, 0))
            f.set(x + 4, y - 4, (255, 215, 0))
            f.set(x + 5, y - 4, (255, 215, 0))

    def clip_frames(self) -> Clip:
        n = self.n_frames()
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / self.clip_fps)
            frames.append(f)
        return Clip(frames, [round(1000 / self.clip_fps)] * n)
