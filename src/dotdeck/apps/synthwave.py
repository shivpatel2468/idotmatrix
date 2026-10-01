"""Synthwave — 80s cyberpunk outrun horizon with 3D perspective grid, blazing sun, and sports car.

A rolling neon grid in true perspective, a banded retrowave sun behind two layers of mountains, and a
cruising car on the road. Everything moves in whole cycles of one 48-frame loop, so the baked GIF plays
seamlessly on the panel.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame

RGB = tuple[int, int, int]

THEMES: dict[str, dict[str, RGB]] = {
    "outrun": {
        "sky_top": (10, 4, 25),
        "sky_mid": (45, 10, 60),
        "sun_top": (255, 235, 60),
        "sun_mid": (255, 100, 30),
        "sun_bot": (255, 0, 120),
        "mountain": (25, 12, 40),
        "mountain_edge": (255, 0, 140),
        "grid_ground": (8, 4, 18),
        "grid_lines": (0, 240, 255),
        "car_body": (30, 32, 45),
        "car_lights": (255, 30, 60),
        "car_underglow": (0, 220, 255),
    },
    "miami": {
        "sky_top": (15, 25, 45),
        "sky_mid": (60, 30, 80),
        "sun_top": (255, 245, 140),
        "sun_mid": (255, 140, 100),
        "sun_bot": (255, 80, 150),
        "mountain": (20, 25, 45),
        "mountain_edge": (255, 100, 180),
        "grid_ground": (10, 18, 30),
        "grid_lines": (40, 240, 200),
        "car_body": (220, 230, 245),
        "car_lights": (255, 60, 120),
        "car_underglow": (255, 120, 200),
    },
    "cyber_red": {
        "sky_top": (16, 4, 8),
        "sky_mid": (55, 12, 18),
        "sun_top": (255, 200, 50),
        "sun_mid": (255, 60, 20),
        "sun_bot": (180, 0, 40),
        "mountain": (30, 8, 12),
        "mountain_edge": (255, 40, 60),
        "grid_ground": (14, 4, 8),
        "grid_lines": (255, 50, 40),
        "car_body": (20, 20, 25),
        "car_lights": (255, 220, 40),
        "car_underglow": (255, 30, 20),
    },
    "emerald": {
        "sky_top": (4, 16, 12),
        "sky_mid": (10, 45, 30),
        "sun_top": (200, 255, 120),
        "sun_mid": (60, 230, 100),
        "sun_bot": (10, 160, 80),
        "mountain": (6, 25, 18),
        "mountain_edge": (40, 255, 140),
        "grid_ground": (4, 14, 10),
        "grid_lines": (0, 255, 180),
        "car_body": (25, 35, 30),
        "car_lights": (255, 220, 60),
        "car_underglow": (0, 255, 160),
    },
}

HORIZON = 17  # the horizon row: sky above, ground below
VP_X = 15.5  # vanishing point: the road meets the horizon under the sun
N_FRAMES = 60  # the whole loop (6 s at 10 fps); every motion repeats a whole number of times in it
# Two smooth ridges (heights above the horizon). The near ridge dips in the middle so the sun sits in the valley.
FAR = (3, 4, 5, 6, 6, 5, 4, 4, 5, 6, 7, 7, 6, 4, 2, 1, 1, 2, 4, 6, 7, 8, 8, 7, 6, 5, 5, 6, 6, 5, 4, 3)
NEAR = (5, 6, 7, 6, 5, 4, 3, 3, 4, 4, 3, 2, 1, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 4, 3, 4, 5, 6, 7, 7, 6, 5)
STARS = ((3, 2, 0), (9, 5, 5), (23, 1, 10), (29, 4, 3), (6, 9, 12), (26, 8, 7), (13, 1, 9), (19, 1, 14))
SLAT_ROWS = (12, 14, 16)  # static blind gaps across the lower sun (moving slats judder at 8 fps)
GRID_DEPTH = 14.0  # a cross line at depth z sits at y = HORIZON + GRID_DEPTH / z
ROAD_HALF = 11.0  # half the road's width at the bottom edge (leaves a gap either side of the car)
# rear views, 12 px wide (see _vehicle for the palette)
CAR = (
    "...hhhhhh...",
    "..hgrggggh..",
    ".bbbbbbbbbb.",
    "LLbbbbbbbbLL",
    "LLdddppdddLL",
    ".tt.e..e.tt.",
    ".uuuuuuuuuu.",
)
SHIP = (
    "....hhhh....",
    "...hgrggh...",
    ".bbbbbbbbbb.",
    "LbbbbbbbbbbL",
    ".dddeeeeddd.",
    "............",
    "..uuuuuuuu..",
)


def _dashes(z: float) -> float:
    """Integral of the centre-dash pattern (on for the first half of every unit of depth) from 0 to z."""
    whole = math.floor(z)
    return whole * 0.5 + min(z - whole, 0.5)


def _mix(a: RGB, b: RGB, k: float) -> RGB:
    return (
        round(a[0] + (b[0] - a[0]) * k),
        round(a[1] + (b[1] - a[1]) * k),
        round(a[2] + (b[2] - a[2]) * k),
    )


def _lift(c: RGB, floor: int) -> RGB:
    """Raise a dark colour until its brightest channel reaches `floor` (darker tones vanish on the LEDs)."""
    m = max(c)
    if m >= floor:
        return c
    if m == 0:
        return (floor, floor, floor)
    k = floor / m
    return (round(c[0] * k), round(c[1] * k), round(c[2] * k))


def grid_frames(speed: float) -> int:
    """Frames for the ground to scroll one grid square: a divisor of N_FRAMES, so the loop stays seamless."""
    want = 20 / speed
    return min((10, 12, 15, 20, 30, 60), key=lambda g: abs(g - want))


class SynthwaveSettings(AppSettings):
    theme: str = Choice(
        "outrun",
        {
            "outrun": "Neon Outrun",
            "miami": "Miami Sunset",
            "cyber_red": "Blood Cyber",
            "emerald": "Matrix Emerald",
        },
        title="Visual Theme",
    )
    vehicle: str = Choice(
        "car",
        {
            "car": "Retro Sports Car",
            "ship": "Hover Cruiser",
            "none": "Empty Highway",
        },
        title="Cruiser Vehicle",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, title="Highway Speed")
    brightness: float = Field(default=1.0, ge=0.2, le=1.0, title="LED Brightness")


@register
class Synthwave(App):
    id = "synthwave"
    name = "Synthwave Horizon"
    category = "creative"
    description = "80s cyberpunk outrun horizon with 3D perspective grid, blazing sun, and sports car."
    Settings = SynthwaveSettings

    clip_seconds = N_FRAMES / 10.0
    clip_fps = 10.0  # the fastest GIF rate verified on the panel
    clip_colors = 64
    fps = 10.0

    def kind(self) -> Kind:
        return "clip"

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        th = THEMES.get(s.theme, THEMES["outrun"])
        k = t * self.clip_fps  # frame clock
        i = int(k) % N_FRAMES
        self._sky(f, th, i)
        self._sun(f, th)
        self._mountains(f, th)
        self._ground(f, th, (k / grid_frames(s.speed)) % 1.0)
        if s.vehicle != "none":
            self._vehicle(f, th, s.vehicle, i)
        if s.brightness < 1.0:
            f.px[:] = (f.px.astype(np.float32) * s.brightness).astype(np.uint8)

    # ---------------------------------------------------------------- layers
    def _sky(self, f: Frame, th: dict[str, RGB], i: int) -> None:
        # three flat bands: gradients bloat the GIF and band on the panel anyway
        top, mid = th["sky_top"], th["sky_mid"]
        f.rect(0, 0, 32, 6, top)
        f.rect(0, 6, 32, 6, _mix(top, mid, 0.5))
        f.rect(0, 12, 32, HORIZON - 12, mid)
        for x, y, ph in STARS:
            on = (i + ph * 3) % 20 < 15  # twinkle period 20 divides the loop
            f.set(x, y, (255, 255, 255) if on else (120, 120, 170))

    def _sun(self, f: Frame, th: dict[str, RGB]) -> None:
        cx, cy, r = VP_X, 10.0, 7.5
        top, mid, bot = th["sun_top"], th["sun_mid"], th["sun_bot"]
        bands = (top, _mix(top, mid, 0.5), mid, _mix(mid, bot, 0.5), bot)  # flat bands, top to bottom
        halo = _mix(th["sky_mid"], mid, 0.35)
        for y in range(int(cy - r) - 1, HORIZON):
            dy = y + 0.5 - cy
            if abs(dy) > r + 1:
                continue
            hw_halo = math.sqrt(max(0.0, (r + 1) ** 2 - dy * dy))
            f.hline(round(cx - hw_halo), y, round(2 * hw_halo), halo)
            if abs(dy) > r or y in SLAT_ROWS:
                continue
            hw = math.sqrt(r * r - dy * dy)
            band = bands[min(4, int((y - (cy - r)) / (2 * r) * 5))]
            f.hline(round(cx - hw), y, round(2 * hw), band)

    def _mountains(self, f: Frame, th: dict[str, RGB]) -> None:
        edge = th["mountain_edge"]
        far_fill = _lift(_mix(th["mountain"], th["sky_mid"], 0.4), 48)
        far_edge = _mix(far_fill, edge, 0.45)
        near_fill = _lift(th["mountain"], 46)
        for layer, fill, ridge in ((FAR, far_fill, far_edge), (NEAR, near_fill, edge)):
            for x, h in enumerate(layer):
                if h <= 0:
                    continue
                y0 = HORIZON - h
                f.rect(x, y0, 1, h, fill)
                # edge the whole step down to the lower neighbour, so the ridge reads as one unbroken line
                lo = min(layer[x - 1] if x > 0 else h, layer[x + 1] if x < 31 else h)
                f.vline(x, y0, max(1, h - lo), ridge)

    def _ground(self, f: Frame, th: dict[str, RGB], phase: float) -> None:
        grid, ground = th["grid_lines"], th["grid_ground"]
        road = _mix(ground, (70, 66, 84), 0.5)  # asphalt: a flat surface of its own, no grid on it
        dash = _mix(road, (255, 240, 200), 0.9)
        f.rect(0, HORIZON + 1, 32, 31 - HORIZON, ground)

        def half_width(row: int) -> float:
            return ROAD_HALF * (row + 0.5 - HORIZON) / (31.5 - HORIZON)

        # cross lines in true perspective, drawn with sub-pixel coverage: a line between two rows lights both
        # in proportion, so it glides instead of snapping a whole row at an uneven rhythm. Far lines fade in at
        # the horizon instead of popping into view.
        glow = [0.0] * 32
        for n in range(7):
            z = n + 1 - phase
            if z <= 0.2:
                continue
            level = 1.0 if z < 1.5 else max(0.0, (5.5 - z) / 4.0)
            if level <= 0:
                continue
            y = HORIZON + GRID_DEPTH / z
            y0 = int(y)
            fr = y - y0
            for row, cover in ((y0, 1.0 - fr), (y0 + 1, fr)):
                if HORIZON < row < 32:
                    glow[row] = max(glow[row], level * cover)
        for row in range(HORIZON + 1, 32):
            hw = half_width(row)
            xl, xr = round(VP_X - hw), round(VP_X + hw)
            q = round(glow[row] * 8) / 8  # 8 steps keeps the GIF palette small
            if q > 0:  # grid squares only on the ground either side of the road
                c = _mix(ground, grid, q)
                f.hline(0, row, xl, c)
                f.hline(xr, row, 32 - xr, c)
            f.hline(xl, row, xr - xl, road)
            # centre dashes: half of every grid square in depth, with the same sub-pixel coverage
            z_far, z_near = GRID_DEPTH / (row - HORIZON), GRID_DEPTH / (row + 1 - HORIZON)
            cover = (_dashes(z_far + phase) - _dashes(z_near + phase)) / (z_far - z_near)
            fade = min(1.0, (row - HORIZON) / 5)
            k = round(cover * fade * 6) / 6
            if k > 0:
                w = 2 if row > 25 else 1
                f.hline(round(VP_X - w / 2), row, w, _mix(road, dash, k))
        # lines running to the vanishing point: the two road edges, then the grid either side
        for bx in (VP_X - ROAD_HALF, VP_X + ROAD_HALF, *(VP_X + d for d in (-23, -16, 16, 23))):
            edge = abs(bx - VP_X) == ROAD_HALF

            def at(p: float, bx: float = bx) -> tuple[int, int]:
                return round(VP_X + (bx - VP_X) * p - 0.5), round(HORIZON + (31 - HORIZON) * p)

            # connected segments (one pixel per row breaks the steep outer lines into dashes)
            for p0, p1, c in (
                (0.07 if edge else 0.15, 0.35, _mix(ground, grid, 0.35)),
                (0.35, 0.6, _mix(ground, grid, 0.65)),
                (0.6, 1.0, grid),
            ):
                (xa, ya), (xb, yb) = at(p0), at(p1)
                f.line(xa, ya, xb, yb, c)
        f.hline(0, HORIZON, 32, grid)  # glowing horizon

    def _vehicle(self, f: Frame, th: dict[str, RGB], kind: str, i: int) -> None:
        # the hero of the scene: a light silver body in every theme, so it stands out from the dark road
        pal: dict[str, RGB] = {
            "h": (235, 238, 250),  # roof / top highlight
            "b": (190, 196, 215),  # upper body
            "d": (118, 124, 150),  # lower body
            "g": (26, 26, 40),  # rear window
            "r": (95, 100, 130),  # window reflection
            "L": th["car_lights"],
            "p": (255, 255, 255),  # plate
            "t": (58, 58, 70),  # tyres
            "e": (255, 190, 70) if i % 4 < 2 else (255, 120, 40),  # exhaust flicker, period 4
            "u": _mix(th["grid_ground"], th["car_underglow"], 0.6),  # underglow on the road
        }
        sprite = SHIP if kind == "ship" else CAR
        x0, y0 = 10, 24  # 12 px wide, centred on the vanishing point
        for dy, line in enumerate(sprite):
            for dx, ch in enumerate(line):
                if ch != ".":
                    f.set(x0 + dx, y0 + dy, pal[ch])

    def clip_frames(self) -> Clip:
        frames = []
        for i in range(N_FRAMES):
            fr = Frame()
            self.render(fr, i / self.clip_fps)
            frames.append(fr)
        return Clip(frames, [round(1000 / self.clip_fps)] * N_FRAMES)
