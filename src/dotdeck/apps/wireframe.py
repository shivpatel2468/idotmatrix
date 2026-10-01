"""Wireframe 3D — retro 80s vector graphics and 4D tesseract holo-display on 32x32.

Renders real-time 3D and 4D perspective wireframe models with yaw/pitch/roll rotation,
Bresenham line rasterization, and luminous depth-faded line intensity.
Seamless loops are baked into native hardware GIFs.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame

TAU = math.tau

THEMES = {
    "cyber_cyan": {
        "near": (0, 245, 255),
        "mid": (0, 140, 210),
        "far": (20, 60, 130),
        "bg": (6, 8, 16),
        "vertex": (255, 255, 255),
    },
    "laser_green": {
        "near": (60, 255, 80),
        "mid": (30, 180, 50),
        "far": (16, 80, 30),
        "bg": (4, 12, 6),
        "vertex": (220, 255, 220),
    },
    "neon_magenta": {
        "near": (255, 30, 180),
        "mid": (180, 0, 140),
        "far": (90, 16, 75),
        "bg": (12, 4, 14),
        "vertex": (255, 220, 245),
    },
    "solar_gold": {
        "near": (255, 215, 40),
        "mid": (230, 120, 20),
        "far": (100, 45, 12),
        "bg": (14, 8, 4),
        "vertex": (255, 255, 220),
    },
}


# --- 3D / 4D Geometric Models ---
def _build_tesseract() -> tuple[np.ndarray, list[tuple[int, int]]]:
    """16 vertices and 32 edges of a 4D hypercube."""
    verts = np.array(
        [[x, y, z, w] for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0) for w in (-1.0, 1.0)],
        dtype=np.float32,
    )
    edges: list[tuple[int, int]] = []
    n = len(verts)
    for i in range(n):
        for j in range(i + 1, n):
            # Connected if they differ in exactly one coordinate
            if np.sum(np.abs(verts[i] - verts[j]) > 1e-3) == 1:
                edges.append((i, j))
    return verts, edges


def _build_icosahedron() -> tuple[np.ndarray, list[tuple[int, int]]]:
    """12 vertices and 30 edges of a regular icosahedron."""
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    v = [
        (-1.0, phi, 0.0),
        (1.0, phi, 0.0),
        (-1.0, -phi, 0.0),
        (1.0, -phi, 0.0),
        (0.0, -1.0, phi),
        (0.0, 1.0, phi),
        (0.0, -1.0, -phi),
        (0.0, 1.0, -phi),
        (phi, 0.0, -1.0),
        (phi, 0.0, 1.0),
        (-phi, 0.0, -1.0),
        (-phi, 0.0, 1.0),
    ]
    verts = np.array(v, dtype=np.float32)
    # Normalize radius
    verts /= np.linalg.norm(verts[0])
    edges: list[tuple[int, int]] = []
    # Distance between adjacent vertices in normalized icosahedron is ~1.05
    for i in range(12):
        for j in range(i + 1, 12):
            d = np.linalg.norm(verts[i] - verts[j])
            if 0.9 < d < 1.2:
                edges.append((i, j))
    return verts, edges


def _build_torus(rings: int = 8, sides: int = 6) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Wireframe torus (donut) mesh."""
    r_major = 1.0
    r_minor = 0.4
    verts: list[list[float]] = []
    edges: list[tuple[int, int]] = []

    for i in range(rings):
        u = i / rings * TAU
        for j in range(sides):
            v = j / sides * TAU
            x = (r_major + r_minor * math.cos(v)) * math.cos(u)
            y = (r_major + r_minor * math.cos(v)) * math.sin(u)
            z = r_minor * math.sin(v)
            verts.append([x, y, z])

    for i in range(rings):
        next_i = (i + 1) % rings
        for j in range(sides):
            next_j = (j + 1) % sides
            idx = i * sides + j
            # Ring edge
            edges.append((idx, next_i * sides + j))
            # Cross edge
            edges.append((idx, i * sides + next_j))

    return np.array(verts, dtype=np.float32), edges


def _build_diamond() -> tuple[np.ndarray, list[tuple[int, int]]]:
    """10-vertex faceted brilliant gemstone."""
    top = [0.0, 1.3, 0.0]
    bot = [0.0, -1.3, 0.0]
    crown = [[math.cos(i / 8.0 * TAU) * 0.9, 0.4, math.sin(i / 8.0 * TAU) * 0.9] for i in range(8)]
    verts = np.array([top, *crown, bot], dtype=np.float32)
    edges: list[tuple[int, int]] = []
    # Connect top to crown
    for i in range(1, 9):
        edges.append((0, i))
    # Connect crown ring
    for i in range(1, 9):
        next_i = 1 if i == 8 else i + 1
        edges.append((i, next_i))
    # Connect crown to bottom
    for i in range(1, 9):
        edges.append((i, 9))
    return verts, edges


def _build_starfighter() -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Retro vector arcade starfighter."""
    v = [
        [0.0, 0.0, 1.4],  # 0: nose
        [-0.4, 0.2, 0.2],  # 1: cockpit left
        [0.4, 0.2, 0.2],  # 2: cockpit right
        [0.0, 0.5, -0.2],  # 3: canopy top
        [-1.4, -0.2, -0.9],  # 4: left wingtip
        [1.4, -0.2, -0.9],  # 5: right wingtip
        [-0.5, -0.2, -1.1],  # 6: left engine
        [0.5, -0.2, -1.1],  # 7: right engine
        [0.0, 0.6, -1.0],  # 8: vertical fin top
    ]
    verts = np.array(v, dtype=np.float32)
    edges = [
        (0, 1),
        (0, 2),
        (1, 2),
        (1, 3),
        (2, 3),
        (1, 4),
        (2, 5),
        (4, 6),
        (5, 7),
        (6, 7),
        (3, 8),
        (6, 8),
        (7, 8),
        (0, 6),
        (0, 7),
    ]
    return verts, edges


# Pre-built models
MODELS = {
    "tesseract": _build_tesseract(),
    "icosahedron": _build_icosahedron(),
    "torus": _build_torus(),
    "diamond": _build_diamond(),
    "starfighter": _build_starfighter(),
}


TESSERACT_W = 2.4  # 4D camera distance for the stereographic 4D -> 3D projection
N_BASE = 64  # frames per loop at speed 1 (8 s at 8 fps): one full turn of every rotation


def loop_frames(speed: float) -> int:
    """Frames per loop: speed picks the loop length (a multiple of 8), never the frame duration."""
    return max(32, min(80, round(N_BASE / speed / 8) * 8))  # <= 80: the busiest shapes stay < 40 KB


def _tesseract_3d(verts: np.ndarray, ang: float) -> np.ndarray:
    """Rotate in the XW plane and project 4D -> 3D."""
    c, s_ = math.cos(ang), math.sin(ang)
    x = verts[:, 0] * c - verts[:, 3] * s_
    w = verts[:, 0] * s_ + verts[:, 3] * c
    k = TESSERACT_W / (TESSERACT_W - w)
    return np.stack([x * k, verts[:, 1] * k, verts[:, 2] * k], axis=-1)


def _project(name: str, a: float, scale: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Model `name` at loop angle `a` (0..2pi): rotated vertices and their screen x, y."""
    verts_raw, _ = MODELS[name]
    # the tesseract also makes one full 4D turn per loop
    v = _tesseract_3d(verts_raw, a) if name == "tesseract" else verts_raw
    v = v * scale
    ang_x = 0.35 + 0.45 * math.sin(a)  # a nodding tilt, so the top and bottom show
    ang_z = 0.25 * math.sin(a + 1.3)  # a gentle roll
    cy, sy = math.cos(a), math.sin(a)  # one full yaw turn per loop
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float32)
    cx, sx = math.cos(ang_x), math.sin(ang_x)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float32)
    cz, sz = math.cos(ang_z), math.sin(ang_z)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float32)
    rot = v @ (rz @ rx @ ry).T
    denom = np.maximum(CAMERA_Z - rot[:, 2], 0.2)
    return rot, 15.5 + rot[:, 0] * FOV / denom, 15.5 - rot[:, 1] * FOV / denom


def _fit(name: str, reach: float = 14.5) -> float:
    """Model scale whose furthest vertex over the whole loop lands `reach` px from the centre: each model
    fills the panel and none runs off it."""
    scale = 1.0 / float(np.linalg.norm(MODELS[name][0], axis=1).max())
    for _ in range(6):
        r = max(
            float(np.abs(np.concatenate([sx, sy]) - 15.5).max())
            for _, sx, sy in (_project(name, a, scale) for a in np.linspace(0, TAU, 48, endpoint=False))
        )
        scale *= (reach / r) ** 0.8
    return scale


CAMERA_Z, FOV = 3.2, 26.0
SCALE = {name: _fit(name) for name in MODELS}


def _depth_color(z: float, theme: dict[str, Any]) -> np.ndarray:
    """Depth cue: near edges bright, far edges dim (but still lit on the LEDs)."""
    c_near = np.array(theme["near"], dtype=np.float32)
    c_mid = np.array(theme["mid"], dtype=np.float32)
    c_far = np.array(theme["far"], dtype=np.float32)
    depth = max(0.0, min(1.0, (1.0 - z) / 2.0))  # z in [-1, 1] after normalising: 0 = close, 1 = far
    if depth < 0.4:
        return c_near * (1.0 - depth * 2.5) + c_mid * (depth * 2.5)
    d2 = (depth - 0.4) / 0.6
    return c_mid * (1.0 - d2) + c_far * d2


def _plot(buf: np.ndarray, x: int, y: int, col: np.ndarray, k: float) -> None:
    if 0 <= x < 32 and 0 <= y < 32 and k > 0:
        np.maximum(buf[y, x], col * k, out=buf[y, x])


def _draw_line_aa(buf: np.ndarray, x0: float, y0: float, x1: float, y1: float, col: np.ndarray) -> None:
    """Xiaolin Wu line at sub-pixel endpoints: each step lights the two pixels the line passes between in
    proportion (the nearer one at full strength, 8 levels), so edges glide as the model turns instead of
    crawling in whole-pixel jaggies. Vectorised: one numpy pass per edge."""
    steep = abs(y1 - y0) > abs(x1 - x0)
    if steep:
        x0, y0, x1, y1 = y0, x0, y1, x1
    if x0 > x1:
        x0, y0, x1, y1 = x1, y1, x0, y0
    dx = x1 - x0
    g = (y1 - y0) / dx if dx > 1e-6 else 0.0
    xs = np.arange(round(x0), round(x1) + 1)
    y = y0 + g * (xs - x0)
    yi = np.floor(y).astype(int)
    fr = y - yi
    peak = np.maximum(fr, 1.0 - fr)
    wa = np.round((1.0 - fr) / peak * 8) / 8
    wb = np.round(fr / peak * 8) / 8
    main = np.concatenate([xs, xs])
    minor = np.concatenate([yi, yi + 1])
    w = np.concatenate([wa, wb])
    px, py = (minor, main) if steep else (main, minor)
    ok = (px >= 0) & (px < 32) & (py >= 0) & (py < 32) & (w > 0)
    np.maximum.at(buf, (py[ok], px[ok]), col[None, :] * w[ok, None])


class WireframeSettings(AppSettings):
    shape: str = Choice(
        "tesseract",
        {
            "tesseract": "4D Hypercube Tesseract",
            "icosahedron": "3D Geodesic Icosahedron",
            "torus": "3D Wireframe Torus",
            "diamond": "Faceted Diamond Gem",
            "starfighter": "Vector Starfighter",
        },
        title="Geometric Shape",
    )
    palette: str = Choice(
        "cyber_cyan",
        {
            "cyber_cyan": "Electric Cyan",
            "laser_green": "Laser Vector Green",
            "neon_magenta": "Neon Magenta",
            "solar_gold": "Solar Amber Gold",
        },
        title="Holo Palette",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, title="Rotation Speed")
    brightness: float = Field(default=1.0, ge=0.2, le=1.0, title="LED Brightness")


@register
class Wireframe(App):
    id = "wireframe"
    name = "3D Wireframe Vector"
    category = "creative"
    description = "Retro 80s 3D vector graphics and 4D tesseract holo-display with depth cueing."
    Settings = WireframeSettings

    clip_seconds = N_BASE / 8.0  # 64 frames at 8 fps
    clip_fps = 8.0
    clip_colors = 32
    fps = 8.0

    def kind(self) -> Kind:
        return "clip"

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        theme = THEMES.get(s.palette, THEMES["cyber_cyan"])
        shape_name = s.shape if s.shape in MODELS else "tesseract"
        _, edges = MODELS[shape_name]
        # loop phase: every rotation turns a whole number of times per loop, so the GIF wraps seamlessly
        ph = (t * self.clip_fps / loop_frames(s.speed)) % 1.0
        rot_v, screen_x, screen_y = _project(shape_name, ph * TAU, SCALE[shape_name])
        # depth cue relative to the model's own size
        zr = float(np.abs(rot_v[:, 2]).max()) or 1.0

        buf = np.zeros((32, 32, 3), np.float32)
        buf[:] = theme["bg"]
        depths = [(rot_v[i, 2] + rot_v[j, 2]) / 2.0 / zr for i, j in edges]
        for idx in np.argsort(depths):  # far edges first
            i, j = edges[idx]
            col = _depth_color(float(depths[idx]), theme)
            _draw_line_aa(buf, screen_x[i], screen_y[i], screen_x[j], screen_y[j], col)
        c_vert = np.array(theme["vertex"], np.float32)
        for i in range(len(rot_v)):  # glowing vertices on the near side
            if rot_v[i, 2] > 0.0:
                _plot(buf, round(screen_x[i]), round(screen_y[i]), c_vert, 1.0)
        if s.brightness < 1.0:
            buf *= s.brightness
        f.px[:] = np.clip(buf, 0, 255).astype(np.uint8)

    def clip_frames(self) -> Clip:
        n = loop_frames(self.settings.speed)
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / self.clip_fps)
            frames.append(f)
        return Clip(frames, [round(1000 / self.clip_fps)] * n)
