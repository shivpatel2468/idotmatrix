"""Pixabots — animated 32x32 pixel art robot avatars with idle bounce, blinking, and accessories.

Inspired by Pablo Stanley's Pixabots (MIT) and Adafruit's 32x32 sprite animations.
"""

from __future__ import annotations

import math

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame

TAU = math.tau

PALETTES: dict[str, dict[str, tuple[int, int, int]]] = {
    "default": {
        "metal": (160, 175, 195),
        "metal_dark": (95, 110, 130),
        "screen": (22, 28, 40),
        "eye": (0, 230, 255),
        "eye_dim": (0, 120, 150),
        "accent": (255, 65, 95),
        "glow": (255, 220, 50),
        "bg": (6, 8, 14),
    },
    "cyberpunk": {  # metal lifted: (45, 50, 70) vanished against the background at the panel's gamma
        "metal": (95, 105, 150),
        "metal_dark": (55, 60, 95),
        "screen": (12, 12, 22),
        "eye": (255, 0, 180),
        "eye_dim": (140, 0, 95),
        "accent": (0, 240, 255),
        "glow": (0, 255, 160),
        "bg": (8, 6, 16),
    },
    "pico8": {
        "metal": (194, 195, 199),
        "metal_dark": (126, 37, 83),
        "screen": (0, 0, 0),
        "eye": (41, 173, 255),
        "eye_dim": (29, 43, 83),
        "accent": (255, 0, 77),
        "glow": (255, 236, 39),
        "bg": (0, 0, 0),
    },
    "gameboy": {
        "metal": (139, 172, 15),
        "metal_dark": (48, 98, 48),
        "screen": (15, 56, 15),
        "eye": (155, 188, 15),
        "eye_dim": (48, 98, 48),
        "accent": (155, 188, 15),
        "glow": (139, 172, 15),
        "bg": (15, 56, 15),
    },
    "neon": {  # lifted like cyberpunk: the body has to read as a silhouette
        "metal": (80, 80, 125),
        "metal_dark": (48, 48, 80),
        "screen": (6, 6, 14),
        "eye": (0, 255, 140),
        "eye_dim": (0, 130, 70),
        "accent": (255, 20, 147),
        "glow": (0, 220, 255),
        "bg": (4, 4, 10),
    },
}


class PixabotsSettings(AppSettings):
    character: str = Choice(
        "sparky",
        {
            "sparky": "Sparky (Retro Bot)",
            "visor": "Visor (Cyberpunk)",
            "crt": "CRT Monitor (Smiley)",
            "nyan": "Nyan Cat (Cosmic)",
            "parrot": "Party Parrot (Dance)",
            "astro": "Astro Bot (Explorer)",
        },
        title="Character",
    )
    color_scheme: str = Choice("default", list(PALETTES), title="Color Palette")
    accessory: str = Choice(
        "none",
        {
            "none": "None",
            "antenna": "Beacon Antenna",
            "headphones": "DJ Headphones",
            "crown": "Royal Crown",
            "party_hat": "Party Hat",
        },
        title="Accessory",
    )
    speed: float = Field(1.0, ge=0.5, le=2.0, title="Speed")
    sparkles: bool = Field(True, title="Sparkles & Effects")


@register
class Pixabots(App):
    id = "pixabots"
    name = "Pixabots"
    description = "Animated 32x32 pixel art robot avatars with idle bounce, blinking, and accessories."
    icon = "bot"
    category = "creative"
    Settings = PixabotsSettings
    clip_seconds = 2.0
    clip_fps = 8.0
    clip_colors = 32

    def kind(self) -> Kind:
        return "clip"

    def n_frames(self) -> int:
        """Frames per loop: speed picks the loop length (16 at speed 1), never the frame duration."""
        return min((8, 12, 16, 24, 32), key=lambda n: abs(n - 16 / self.settings.speed))

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        pal = PALETTES.get(s.color_scheme, PALETTES["default"])
        ph = (t * self.clip_fps / self.n_frames()) % 1.0

        # Background
        f.px[:] = pal["bg"]

        # idle bounce 0, +1, 0, -1 px, each held for an even quarter of the loop (a steady rhythm)
        by = (0, 1, 0, -1)[int(ph * 4) % 4]

        # Draw selected character
        if s.character == "sparky":
            self._draw_sparky(f, ph, by, pal)
        elif s.character == "visor":
            self._draw_visor(f, ph, by, pal)
        elif s.character == "crt":
            self._draw_crt(f, ph, by, pal)
        elif s.character == "nyan":
            self._draw_nyan(f, ph, by)
        elif s.character == "parrot":
            self._draw_parrot(f, ph, by)
        elif s.character == "astro":
            self._draw_astro(f, ph, by, pal)

        # Draw accessory if enabled and applicable
        if s.character in ("sparky", "visor", "crt", "astro"):
            self._draw_accessory(f, by, pal, s.accessory)

        # Floating ambient sparkles
        if s.sparkles and s.character not in ("nyan", "parrot"):
            self._draw_sparkles(f, ph, pal)

    def clip_frames(self) -> Clip:
        n = self.n_frames()
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / self.clip_fps)
            frames.append(f)
        return Clip(frames, [round(1000 / self.clip_fps)] * n)

    # ------------------------------------------------------------- character renderers
    def _draw_sparky(self, f: Frame, ph: float, by: int, pal: dict[str, tuple[int, int, int]]) -> None:
        """Retro metallic box robot with antenna beacon, blinking eyes, and chest gauge."""
        metal, dark, screen = pal["metal"], pal["metal_dark"], pal["screen"]
        eye, eye_dim, accent = pal["eye"], pal["eye_dim"], pal["accent"]

        # Caterpillar treads / feet
        f.rect(7, 26, 18, 4, dark)
        f.hline(8, 27, 16, (20, 20, 25))
        # Tread tread dots
        td_offset = int((ph * 8) % 4)
        for tx in range(9 + td_offset, 24, 4):
            f.set(tx, 27, metal)

        # Body chassis
        f.rect(8, 17 + by, 16, 9, metal)
        f.rect(9, 18 + by, 14, 7, dark)
        # Chest meter / status core (pulsing heart)
        pulse = 0.5 + 0.5 * math.sin(ph * TAU * 2)
        core_c = (int(accent[0] * pulse), int(accent[1] * pulse), int(accent[2] * pulse))
        f.rect(13, 20 + by, 6, 4, (10, 10, 15))
        f.rect(14, 21 + by, 4, 2, core_c)

        # Arms with claw hands
        arm_wobble = round(math.sin(ph * TAU) * 0.6)
        f.rect(5, 18 + by + arm_wobble, 3, 6, metal)
        f.rect(4, 23 + by + arm_wobble, 2, 2, dark)
        f.rect(24, 18 + by - arm_wobble, 3, 6, metal)
        f.rect(26, 23 + by - arm_wobble, 2, 2, dark)

        # Neck
        f.rect(14, 15 + by, 4, 2, dark)

        # Head casing (16x11)
        f.rect(8, 5 + by, 16, 11, metal)
        f.rect(9, 6 + by, 14, 9, dark)
        f.rect(10, 7 + by, 12, 7, screen)

        # Ear bolts
        f.rect(6, 8 + by, 2, 4, dark)
        f.rect(24, 8 + by, 2, 4, dark)

        # Blinking eyes: closed when 0.75 <= ph <= 0.88
        blinking = 0.72 <= ph <= 0.86
        if blinking:
            f.hline(11, 10 + by, 3, eye_dim)
            f.hline(18, 10 + by, 3, eye_dim)
        else:
            f.rect(11, 9 + by, 3, 3, eye)
            f.rect(18, 9 + by, 3, 3, eye)
            f.set(11, 9 + by, (255, 255, 255))
            f.set(18, 9 + by, (255, 255, 255))

        # Smile
        f.hline(13, 13 + by, 6, dark)
        f.set(14, 13 + by, metal)
        f.set(17, 13 + by, metal)

    def _draw_visor(self, f: Frame, ph: float, by: int, pal: dict[str, tuple[int, int, int]]) -> None:
        """Cyberpunk synthwave bot with animated graphic equalizer visor and hover jets."""
        metal, dark, screen = pal["metal"], pal["metal_dark"], pal["screen"]
        accent, eye, glow = pal["accent"], pal["eye"], pal["glow"]

        # Hover thruster jets with particle exhaust
        f.rect(10, 27, 4, 3, dark)
        f.rect(18, 27, 4, 3, dark)
        flame_len = round(1 + math.sin(ph * TAU * 3) * 1.5)
        f.rect(11, 29, 2, flame_len, glow)
        f.rect(19, 29, 2, flame_len, glow)

        # Angular body armor
        f.rect(9, 18 + by, 14, 8, dark)
        f.rect(10, 19 + by, 12, 6, metal)
        # Power line
        f.hline(11, 21 + by, 10, accent)

        # Neck collar
        f.rect(12, 16 + by, 8, 2, dark)

        # Helmet
        f.rect(7, 5 + by, 18, 11, metal)
        f.rect(8, 6 + by, 16, 9, dark)

        # Cyber Visor (equalizer bars)
        f.rect(9, 8 + by, 14, 6, screen)
        # 5 animated EQ bars
        eq_heights = [
            round(2 + math.sin(ph * TAU * 2 + 0) * 1.5),
            round(3 + math.sin(ph * TAU * 3 + 1) * 1.8),
            round(4 + math.sin(ph * TAU * 2 + 2) * 1.8),
            round(3 + math.sin(ph * TAU * 3 + 3) * 1.5),
            round(2 + math.sin(ph * TAU * 2 + 4) * 1.5),
        ]
        for idx, h in enumerate(eq_heights):
            vx = 10 + idx * 2 + (1 if idx > 2 else 0)
            f.vline(vx, 13 + by - max(1, min(5, h)), max(1, min(5, h)), eye)

        # Horn antennas
        f.rect(6, 4 + by, 2, 4, accent)
        f.rect(24, 4 + by, 2, 4, accent)

    def _draw_crt(self, f: Frame, ph: float, by: int, pal: dict[str, tuple[int, int, int]]) -> None:
        """Retro beige CRT computer monitor bot with expressive smiling face."""
        metal, dark, screen = pal["metal"], pal["metal_dark"], pal["screen"]
        eye = pal["eye"]

        # Pedestal stand
        f.rect(13, 26, 6, 2, dark)
        f.rect(10, 28, 12, 3, metal)

        # Monitor bezel (rounded box 20x16)
        f.rect(6, 7 + by, 20, 18, metal)
        f.rect(7, 8 + by, 18, 16, dark)

        # Green phosphorescent curved screen
        f.rect(8, 9 + by, 16, 12, screen)

        # Scanline effect
        for sy in range(9 + by, 21 + by, 2):
            f.hline(8, sy, 16, (screen[0] + 8, screen[1] + 8, screen[2] + 8))

        # Pixel face: winks at 0.7 <= ph <= 0.85
        winking = 0.70 <= ph <= 0.85
        # Left eye: chevron ^
        f.set(11, 13 + by, eye)
        f.set(12, 12 + by, eye)
        f.set(13, 13 + by, eye)

        # Right eye: chevron or wink dash
        if winking:
            f.hline(19, 13 + by, 3, eye)
        else:
            f.set(19, 13 + by, eye)
            f.set(20, 12 + by, eye)
            f.set(21, 13 + by, eye)

        # Smile `\_/`
        f.set(14, 16 + by, eye)
        f.hline(15, 17 + by, 3, eye)
        f.set(18, 16 + by, eye)

        # Floppy drive & power LED
        f.hline(8, 22 + by, 8, (15, 15, 18))
        blink_led = (0, 255, 60) if int(ph * 8) % 2 == 0 else (0, 90, 20)
        f.set(23, 22 + by, blink_led)

    def _draw_nyan(self, f: Frame, ph: float, by: int) -> None:
        """The iconic cosmic space cat with animated rainbow trail (from Adafruit guide)."""
        # Deep starfield background
        f.px[:] = (4, 4, 18)
        # Twinkling stars
        rnd_stars = [(3, 5), (8, 26), (28, 7), (29, 24), (16, 2)]
        for idx, (sx, sy) in enumerate(rnd_stars):
            if int(ph * 8 + idx) % 3 != 0:
                f.set(sx, sy, (255, 255, 255))

        # Trailing rainbow beam (6 bands)
        rainbow_colors = [
            (255, 0, 0),  # Red
            (255, 140, 0),  # Orange
            (255, 230, 0),  # Yellow
            (0, 255, 60),  # Green
            (0, 170, 255),  # Blue
            (160, 32, 240),  # Purple
        ]
        wave = round(math.sin(ph * TAU * 2) * 1.0)
        for band_idx, col in enumerate(rainbow_colors):
            y_base = 11 + band_idx * 2 + by
            for rx in range(0, 13):
                ry = y_base + (wave if rx % 4 < 2 else -wave)
                f.set(rx, ry, col)

        # Toast pastry body (11x11)
        f.rect(12, 10 + by, 12, 11, (215, 160, 90))
        f.rect(13, 11 + by, 10, 9, (255, 192, 203))  # Pink frosting
        # Sprinkles
        f.set(15, 13 + by, (255, 60, 120))
        f.set(19, 14 + by, (255, 60, 120))
        f.set(16, 17 + by, (255, 60, 120))
        f.set(21, 16 + by, (255, 60, 120))

        # Gray Cat Head (8x7)
        hx, hy = 20, 12 + by
        f.rect(hx, hy, 8, 7, (140, 140, 150))
        # Ears
        f.rect(hx, hy - 2, 2, 2, (140, 140, 150))
        f.rect(hx + 6, hy - 2, 2, 2, (140, 140, 150))
        # Cheeks & Eyes
        f.set(hx + 2, hy + 2, (0, 0, 0))
        f.set(hx + 5, hy + 2, (0, 0, 0))
        f.set(hx + 1, hy + 4, (255, 105, 180))  # pink cheek
        f.set(hx + 6, hy + 4, (255, 105, 180))

        # Tail (waving)
        tail_wave = round(math.sin(ph * TAU * 2) * 1.2)
        f.rect(10, 16 + by + tail_wave, 3, 2, (140, 140, 150))
        # Feet
        f.rect(13, 21 + by, 2, 2, (140, 140, 150))
        f.rect(21, 21 + by, 2, 2, (140, 140, 150))

    def _draw_parrot(self, f: Frame, ph: float, by: int) -> None:
        """The cult-classic Party Parrot dancing in vibrant rainbow colors (from Adafruit guide)."""
        # Circular bobbing motion
        dx = round(math.cos(ph * TAU) * 1.6)
        dy = round(math.sin(ph * TAU) * 1.6)

        # Vibrant party color ramp cycling with phase
        party_hues = [
            (255, 0, 80),
            (255, 140, 0),
            (255, 230, 0),
            (0, 255, 100),
            (0, 220, 255),
            (180, 0, 255),
        ]
        col_idx = int((ph * 6) % 6)
        body_color = party_hues[col_idx]
        beak_color = (255, 200, 30)

        cx, cy = 13 + dx, 12 + dy

        # Parrot Body & Wing
        f.rect(cx - 3, cy + 4, 10, 11, body_color)
        f.rect(
            cx - 5,
            cy + 8,
            4,
            8,
            (int(body_color[0] * 0.7), int(body_color[1] * 0.7), int(body_color[2] * 0.7)),
        )

        # Head & Crest
        f.rect(cx, cy - 4, 10, 10, body_color)
        f.rect(cx - 2, cy - 6, 6, 4, body_color)

        # Huge Beak
        f.rect(cx + 8, cy, 6, 6, beak_color)
        f.set(cx + 14, cy + 3, beak_color)
        f.set(cx + 13, cy + 4, beak_color)
        f.hline(cx + 9, cy + 3, 4, (140, 90, 10))

        # Eye
        f.rect(cx + 4, cy - 1, 3, 3, (255, 255, 255))
        f.set(cx + 5, cy, (0, 0, 0))

        # Party confetti
        for i in range(10):
            c_angle = i * 0.628 + ph * TAU
            c_dist = 11 + (i % 3) * 3
            px = round(16 + math.cos(c_angle) * c_dist)
            py = round(16 + math.sin(c_angle) * c_dist)
            f.set(px, py, party_hues[(col_idx + i) % 6])

    def _draw_astro(self, f: Frame, ph: float, by: int, pal: dict[str, tuple[int, int, int]]) -> None:
        """Space explorer astronaut robot hovering with golden reflective visor."""
        suit = (225, 230, 240)
        suit_dark = (120, 130, 150)
        gold_visor = (255, 190, 40)
        accent = pal["accent"]

        # Nitrogen hover thrusters
        f.rect(9, 26 + by, 3, 3, suit_dark)
        f.rect(19, 26 + by, 3, 3, suit_dark)
        puff = 0.5 + 0.5 * math.sin(ph * TAU * 3)
        if puff > 0.4:
            f.set(10, 29 + by, (200, 240, 255))
            f.set(20, 29 + by, (200, 240, 255))

        # Spacesuit body
        f.rect(8, 17 + by, 15, 9, suit)
        f.rect(9, 18 + by, 13, 7, suit_dark)
        # Chest control panel
        f.rect(12, 19 + by, 7, 4, (30, 35, 45))
        f.set(13, 20 + by, (0, 255, 100))
        f.set(15, 20 + by, (255, 0, 80))
        f.set(17, 20 + by, (0, 200, 255))

        # Arms
        f.rect(5, 18 + by, 3, 7, suit)
        f.rect(23, 18 + by, 3, 7, suit)

        # Bubble Helmet (rounded 18x12)
        f.rect(7, 4 + by, 17, 13, suit)
        f.rect(8, 5 + by, 15, 11, (10, 15, 25))

        # Golden Curved Visor
        f.rect(9, 6 + by, 13, 8, gold_visor)
        # White highlight glare reflection
        f.hline(11, 7 + by, 4, (255, 255, 255))
        f.set(10, 8 + by, (255, 255, 255))

        # Red mission shoulder patches
        f.set(5, 18 + by, accent)
        f.set(25, 18 + by, accent)

    # ------------------------------------------------------------- accessories
    def _draw_accessory(self, f: Frame, by: int, pal: dict[str, tuple[int, int, int]], acc: str) -> None:
        metal_dark = pal["metal_dark"]
        glow = pal["glow"]
        accent = pal["accent"]

        if acc == "antenna":
            # Classic antenna rod with glowing beacon
            f.vline(15, 1 + by, 4, metal_dark)
            f.rect(14, by, 3, 2, glow)
        elif acc == "headphones":
            # Over-ear DJ headphones
            f.hline(9, 4 + by, 13, (40, 40, 50))  # Headband
            f.rect(5, 7 + by, 3, 6, accent)  # Left ear cup
            f.rect(23, 7 + by, 3, 6, accent)  # Right ear cup
        elif acc == "crown":
            # 3-point golden royal crown
            f.hline(10, 4 + by, 11, (255, 215, 0))
            f.set(10, 2 + by, (255, 215, 0))
            f.set(15, 1 + by, (255, 215, 0))
            f.set(20, 2 + by, (255, 215, 0))
            # Ruby jewel in center
            f.set(15, 3 + by, (255, 0, 50))
        elif acc == "party_hat":
            # Striped cone party hat
            f.set(15, 0 + by, (255, 255, 255))  # pompom
            f.rect(14, 1 + by, 3, 2, (255, 50, 80))
            f.rect(13, 3 + by, 5, 2, (255, 220, 30))

    def _draw_sparkles(self, f: Frame, ph: float, pal: dict[str, tuple[int, int, int]]) -> None:
        glow = pal["glow"]
        sparkle_coords = [(3, 4), (28, 5), (2, 25), (29, 23)]
        for idx, (sx, sy) in enumerate(sparkle_coords):
            brightness = 0.5 + 0.5 * math.sin(ph * TAU * 2 + idx * 1.57)
            if brightness > 0.4:
                col = (int(glow[0] * brightness), int(glow[1] * brightness), int(glow[2] * brightness))
                f.set(sx, sy, col)
