"""Raycaster 3D — first-person Wolfenstein 3D style dungeon crawler engine on 32x32.

Renders real-time 3D raycasting with textured walls, depth fog shading, dynamic
torchlight/crystal illumination, and an interactive minimap radar HUD.
Loops are precomputed and baked into native hardware GIFs.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame

# 12x12 Dungeon Map layout
# 0: Empty, 1: Solid Brick, 2: Mossy Wall, 3: Rune/Crystal Pillar
MAP_DATA = np.array(
    [
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 0, 3, 1, 0, 1, 1, 0, 1],
        [1, 0, 1, 3, 0, 0, 0, 0, 3, 1, 0, 1],
        [1, 0, 0, 0, 0, 2, 2, 0, 0, 0, 0, 1],
        [1, 0, 1, 0, 2, 1, 1, 2, 0, 1, 0, 1],
        [1, 0, 1, 0, 2, 1, 1, 2, 0, 1, 0, 1],
        [1, 0, 0, 0, 0, 2, 2, 0, 0, 0, 0, 1],
        [1, 0, 1, 3, 0, 0, 0, 0, 3, 1, 0, 1],
        [1, 0, 1, 1, 0, 3, 1, 0, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    ],
    dtype=np.int32,
)

# The walk: once round the outer corridor, corner to corner (cell centres), heading east, south, west, north.
CORNERS = ((1.5, 1.5), (10.5, 1.5), (10.5, 10.5), (1.5, 10.5))
HEADINGS = (0.0, math.pi / 2, math.pi, -math.pi / 2)
TURN = 0.25  # share of each side spent turning the corner (a quarter circle, radius CORNER_R)
CORNER_R = 0.5
N_BASE = 160  # frames per lap at speed 1 (20 s at 8 fps: ~0.3 cells and <= 9 degrees per frame)


def loop_frames(speed: float) -> int:
    """Frames per lap: speed picks the loop length (a multiple of 16), never the frame duration."""
    return max(96, min(160, round(N_BASE / speed / 16) * 16))  # <= 160 frames: < 40 KB


THEME_COLORS = {
    "dungeon": {
        "ceiling": (16, 12, 24),
        "floor": (54, 44, 58),
        "wall_1": (165, 145, 118),  # lifted: the old stone read as mud on the LEDs
        "wall_2": (95, 155, 85),
        "wall_3": (215, 155, 45),
        "fog": (8, 6, 10),
    },
    "cyberpunk": {
        "ceiling": (16, 8, 36),
        "floor": (34, 22, 70),
        "wall_1": (0, 210, 255),
        "wall_2": (255, 0, 140),
        "wall_3": (0, 255, 160),
        "fog": (6, 4, 12),
    },
    "inferno": {
        "ceiling": (34, 8, 6),
        "floor": (78, 24, 12),
        "wall_1": (220, 80, 20),
        "wall_2": (160, 40, 10),
        "wall_3": (255, 200, 40),
        "fog": (18, 4, 2),
    },
}


def _get_player_pose(progress: float) -> tuple[float, float, float]:
    """Camera (x, y, angle) at `progress` (0..1) round the lap. Walks the straights (easing a little into
    the corners) and turns on a quarter circle at an even rate: no stop-and-go at every waypoint."""
    side = int(progress * 4) % 4
    local = progress * 4 - int(progress * 4)
    (x0, y0), (x1, y1) = CORNERS[side], CORNERS[(side + 1) % 4]
    h0, h1 = HEADINGS[side], HEADINGS[(side + 1) % 4]
    d0 = (math.cos(h0), math.sin(h0))
    d1 = (math.cos(h1), math.sin(h1))
    if local < 1 - TURN:  # the straight, from the end of the last arc to the start of the next
        u = local / (1 - TURN)
        u = 0.5 * u + 0.5 * u * u * (3 - 2 * u)  # half linear, half eased: a gentle slow-down at the ends
        sx, sy = x0 + d0[0] * CORNER_R, y0 + d0[1] * CORNER_R
        ex, ey = x1 - d0[0] * CORNER_R, y1 - d0[1] * CORNER_R
        return sx + (ex - sx) * u, sy + (ey - sy) * u, h0
    u = (local - (1 - TURN)) / TURN  # the corner: a quarter circle about (corner - r*d0 + r*d1)
    cx = x1 - d0[0] * CORNER_R + d1[0] * CORNER_R
    cy = y1 - d0[1] * CORNER_R + d1[1] * CORNER_R
    a = u * math.pi / 2
    # start point relative to centre is -r*d1; rotate it by `a` in the turning direction
    rx, ry = -d1[0] * CORNER_R, -d1[1] * CORNER_R
    ca, sa = math.cos(a), math.sin(a)
    return cx + rx * ca - ry * sa, cy + rx * sa + ry * ca, h0 + a


def _cast_ray(px: float, py: float, ray_ang: float) -> tuple[float, int, int, float]:
    """DDA Raycasting. Returns (distance, wall_type, side, hit_pos)."""
    cos_a = math.cos(ray_ang)
    sin_a = math.sin(ray_ang)

    map_x = int(px)
    map_y = int(py)

    delta_dist_x = abs(1.0 / cos_a) if abs(cos_a) > 1e-6 else 1e30
    delta_dist_y = abs(1.0 / sin_a) if abs(sin_a) > 1e-6 else 1e30

    if cos_a < 0:
        step_x = -1
        side_dist_x = (px - map_x) * delta_dist_x
    else:
        step_x = 1
        side_dist_x = (map_x + 1.0 - px) * delta_dist_x

    if sin_a < 0:
        step_y = -1
        side_dist_y = (py - map_y) * delta_dist_y
    else:
        step_y = 1
        side_dist_y = (map_y + 1.0 - py) * delta_dist_y

    hit = False
    side = 0
    wall_type = 1

    # DDA loop (max 20 steps)
    for _ in range(20):
        if side_dist_x < side_dist_y:
            side_dist_x += delta_dist_x
            map_x += step_x
            side = 0
        else:
            side_dist_y += delta_dist_y
            map_y += step_y
            side = 1

        if 0 <= map_x < 12 and 0 <= map_y < 12:
            cell = MAP_DATA[map_y, map_x]
            if cell > 0:
                hit = True
                wall_type = cell
                break
        else:
            break

    if not hit:
        return 16.0, 1, 0, 0.0

    if side == 0:
        dist = (map_x - px + (1 - step_x) / 2) / cos_a
        hit_pos = py + dist * sin_a
    else:
        dist = (map_y - py + (1 - step_y) / 2) / sin_a
        hit_pos = px + dist * cos_a

    hit_pos -= math.floor(hit_pos)
    return max(0.2, dist), wall_type, side, hit_pos


def _render_3d_frame(
    px: float,
    py: float,
    ang: float,
    theme_name: str,
    show_radar: bool,
    flicker: float,
) -> np.ndarray:
    """Render one 32x32 3D raycast frame."""
    theme = THEME_COLORS.get(theme_name, THEME_COLORS["dungeon"])
    frame = np.zeros((32, 32, 3), dtype=np.uint8)

    # Sky & Floor gradients
    c_ceil = np.array(theme["ceiling"], dtype=np.float32)
    c_floor = np.array(theme["floor"], dtype=np.float32)
    c_fog = np.array(theme["fog"], dtype=np.float32)

    # Ceiling & floor in flat bands (smooth gradients bloat the GIF and band on the LEDs anyway); the floor is
    # lifted so the corridor reads as a space, not a void, at the panel's gamma
    frame[:8, :] = (c_ceil * 0.6).astype(np.uint8)
    frame[8:16, :] = c_ceil.astype(np.uint8)
    frame[16:22, :] = (c_floor * 0.75).astype(np.uint8)
    frame[22:, :] = c_floor.astype(np.uint8)

    # Cast 32 rays (one per pixel column)
    fov = math.pi / 3.0  # 60 degrees
    tan_half_fov = math.tan(fov / 2.0)

    for col in range(32):
        camera_x = 2.0 * col / 32.0 - 1.0  # -1 to 1
        ray_ang = ang + math.atan(camera_x * tan_half_fov)

        dist, wall_type, side, hit_pos = _cast_ray(px, py, ray_ang)

        # Fisheye correction
        dist_corr = dist * math.cos(ray_ang - ang)

        # Projected wall height on 32-pixel screen
        proj_h = int(min(32.0, 24.0 / dist_corr))
        y0 = max(0, 16 - proj_h // 2)
        y1 = min(31, 16 + proj_h // 2)

        # Base wall color
        wall_key = f"wall_{wall_type}"
        base_c = np.array(theme.get(wall_key, theme["wall_1"]), dtype=np.float32)

        # Shading: Side 1 is slightly darker (classic Wolfenstein 3D directional light)
        if side == 1:
            base_c *= 0.75

        # Distance fog attenuation
        fog_factor = round(max(0.0, min(1.0, 1.0 - (dist_corr / 10.0))) * 8) / 8  # 8 levels: a small palette

        # Brick texture pattern / mortar lines
        tex_x = int(hit_pos * 8) % 8
        is_mortar = tex_x == 0

        # Torchlight flicker effect on rune/crystal walls
        if wall_type == 3:
            glow = 0.8 + 0.3 * flicker
            base_c = np.clip(base_c * glow, 0, 255)

        h = y1 - y0 + 1
        ys = np.arange(h)
        tex_y = (ys * 8 // max(1, y1 - y0)) % 8
        is_m = is_mortar | (tex_y == 0)
        c = base_c * np.where(is_m[:, None], 0.45, 1.0)
        final_c = c * fog_factor + c_fog * (1.0 - fog_factor)
        frame[y0 : y1 + 1, col] = np.clip(final_c, 0, 255).astype(np.uint8)

    # Optional Mini-map Radar in top-right corner (6x6)
    if show_radar:
        # Semi-transparent dark background
        frame[1:8, 24:31] = (10, 12, 16)
        # Radar border
        frame[1, 24:31] = (60, 70, 80)
        frame[7, 24:31] = (60, 70, 80)
        frame[1:8, 24] = (60, 70, 80)
        frame[1:8, 30] = (60, 70, 80)

        # Render visible blocks around player
        ipx, ipy = int(px), int(py)
        for ry in range(-2, 3):
            for rx in range(-2, 3):
                mx, my = ipx + rx, ipy + ry
                if 0 <= mx < 12 and 0 <= my < 12 and MAP_DATA[my, mx] > 0:
                    frame[4 + ry, 27 + rx] = (120, 130, 145)

        # Player icon (yellow) with directional nose pixel
        frame[4, 27] = (255, 230, 40)
        dx = round(math.cos(ang))
        dy = round(math.sin(ang))
        frame[4 + dy, 27 + dx] = (255, 100, 30)

    return frame


def _flicker(i: int, n: int) -> float:
    """Torch flicker: n // 8 cycles per lap (about one a second), so it repeats seamlessly."""
    return math.sin(i / n * math.tau * (n // 8)) * 0.5 + 0.5


@lru_cache(maxsize=8)
def _generate_raycaster_loop(theme: str, show_radar: bool, n_frames: int = N_BASE) -> list[np.ndarray]:
    """One lap of the corridor as `n_frames` frames (frame n would equal frame 0)."""
    frames: list[np.ndarray] = []
    for i in range(n_frames):
        px, py, ang = _get_player_pose(i / n_frames)
        frames.append(_render_3d_frame(px, py, ang, theme, show_radar, _flicker(i, n_frames)))
    return frames


class RaycasterSettings(AppSettings):
    theme: str = Choice(
        "dungeon",
        {
            "dungeon": "Medieval Dungeon",
            "cyberpunk": "Cyber Grid",
            "inferno": "Infernal Basalt",
        },
        title="Visual Theme",
    )
    radar: str = Choice(
        "on",
        {
            "on": "Radar HUD On",
            "off": "Radar HUD Off",
        },
        title="Minimap Radar HUD",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, title="Exploration Speed")
    brightness: float = Field(default=1.0, ge=0.2, le=1.0, title="LED Brightness")


@register
class Raycaster(App):
    id = "raycaster"
    name = "3D Dungeon Raycaster"
    category = "games"
    description = "First-person 3D raycasting dungeon crawler with textured walls and radar."
    Settings = RaycasterSettings

    clip_seconds = N_BASE / 8.0  # one lap: 160 frames at 8 fps
    clip_fps = 8.0
    clip_colors = 32
    fps = 8.0

    def kind(self) -> Kind:
        return "clip"

    def render(self, f: Frame, t: float) -> None:
        n = loop_frames(self.settings.speed)
        i = int(round(t * self.clip_fps, 6))
        k = t * self.clip_fps / n % 1.0
        px, py, ang = _get_player_pose(k)
        show_radar = self.settings.radar == "on"
        img = _render_3d_frame(px, py, ang, self.settings.theme, show_radar, _flicker(i % n, n))
        if self.settings.brightness < 1.0:
            f.px[:] = (img.astype(np.float32) * self.settings.brightness).astype(np.uint8)
        else:
            f.px[:] = img

    def clip_frames(self) -> Clip:
        n = loop_frames(self.settings.speed)
        frames = _generate_raycaster_loop(self.settings.theme, self.settings.radar == "on", n)
        out: list[Frame] = []
        for img in frames:
            f = Frame()
            if self.settings.brightness < 1.0:
                f.px[:] = (img.astype(np.float32) * self.settings.brightness).astype(np.uint8)
            else:
                f.px[:] = img
            out.append(f)
        return Clip(out, [round(1000 / self.clip_fps)] * len(out))
