"""Boids — Craig Reynolds flocking swarm simulation and bioluminescent particle life on 32x32.

Simulates emergent flocking behaviors (separation, alignment, cohesion, predator avoidance)
with glowing bioluminescent trails and atmospheric environmental lighting.
Loops are precomputed and baked into native hardware GIFs.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame
from ._kit import loading

TAU = math.tau

THEMES = {
    "deep_sea": {
        "bg_top": (2, 6, 16),
        "bg_bot": (0, 2, 8),
        "boid_head": (0, 240, 255),
        "boid_body": (0, 150, 220),
        "boid_trail": (0, 60, 130),
        "predator": (255, 60, 100),
    },
    "starlings": {
        "bg_top": (35, 20, 50),
        "bg_bot": (210, 100, 50),
        "boid_head": (25, 18, 30),
        "boid_body": (40, 30, 50),
        "boid_trail": (80, 50, 70),
        "predator": (255, 220, 80),
    },
    "fireflies": {
        "bg_top": (4, 10, 8),
        "bg_bot": (8, 20, 12),
        "boid_head": (255, 255, 180),
        "boid_body": (190, 240, 60),
        "boid_trail": (70, 140, 20),
        "predator": (255, 100, 30),
    },
    "cyber": {
        "bg_top": (10, 4, 20),
        "bg_bot": (4, 2, 10),
        "boid_head": (255, 0, 180),
        "boid_body": (160, 0, 220),
        "boid_trail": (70, 0, 120),
        "predator": (0, 255, 180),
    },
}


def _step_boids(
    pos: np.ndarray,
    vel: np.ndarray,
    pred_pos: np.ndarray,
    pred_vel: np.ndarray,
    has_predator: bool,
) -> None:
    """Vectorized flocking update with Reynolds' three rules + predator avoidance."""
    diff = pos[None, :, :] - pos[:, None, :]  # shape (n, n, 2)
    # Toroidal distance correction
    diff = (diff + 16.0) % 32.0 - 16.0
    dist = np.linalg.norm(diff, axis=-1) + 1e-5  # shape (n, n)

    # 1. Separation (< 3.0 px)
    close = (dist < 3.2) & (dist > 0.05)
    sep = np.sum(-diff * (close / (dist**1.5))[..., None], axis=1)

    # 2. Alignment (< 7.5 px)
    nbr = (dist < 7.5) & (dist > 0.05)
    nbr_count = np.sum(nbr, axis=1, keepdims=True) + 1e-5
    avg_vel = np.sum(vel[None, :, :] * nbr[..., None], axis=1) / nbr_count
    align = avg_vel - vel

    # 3. Cohesion (< 7.5 px)
    avg_pos_diff = np.sum(diff * nbr[..., None], axis=1) / nbr_count
    cohesion = avg_pos_diff

    # Combine flocking forces
    acc = 1.4 * sep + 0.8 * align + 0.5 * cohesion

    # Predator avoidance
    if has_predator:
        p_diff = pos - pred_pos  # shape (n, 2)
        p_diff = (p_diff + 16.0) % 32.0 - 16.0
        p_dist = np.linalg.norm(p_diff, axis=-1, keepdims=True) + 1e-5
        flee = (p_diff / (p_dist**1.8)) * (p_dist < 9.0)
        acc += 2.5 * flee

        # Update predator (circles and pursues flock center of mass)
        flock_center = np.mean(pos, axis=0)
        pred_dir = (flock_center - pred_pos + 16.0) % 32.0 - 16.0
        pred_dist = np.linalg.norm(pred_dir) + 1e-5
        pred_acc = (pred_dir / pred_dist) * 0.4
        pred_vel += pred_acc
        p_speed = np.linalg.norm(pred_vel) + 1e-5
        if p_speed > 1.2:
            pred_vel[:] = (pred_vel / p_speed) * 1.2
        pred_pos[:] = (pred_pos + pred_vel) % 32.0

    # Integrate velocities
    vel += acc * 0.25
    speeds = np.linalg.norm(vel, axis=-1, keepdims=True) + 1e-5
    # Clamp speed: min 0.6, max 1.5 px/tick
    max_speed = 1.4
    min_speed = 0.5
    vel[:] = np.where(
        speeds > max_speed,
        (vel / speeds) * max_speed,
        np.where(speeds < min_speed, (vel / speeds) * min_speed, vel),
    )

    # Move boids with wrap
    pos[:] = (pos + vel) % 32.0


def _render_boids_frame(
    pos: np.ndarray,
    vel: np.ndarray,
    trails: list[np.ndarray],
    pred_pos: np.ndarray,
    theme_name: str,
    has_predator: bool,
    t: float,
) -> np.ndarray:
    """Render background gradient, fading trails, and boid sprites."""
    theme = THEMES.get(theme_name, THEMES["deep_sea"])
    frame = np.zeros((32, 32, 3), dtype=np.uint8)

    # Background gradient
    c_top = np.array(theme["bg_top"], dtype=np.float32)
    c_bot = np.array(theme["bg_bot"], dtype=np.float32)
    for y in range(32):
        fr = y / 31.0
        frame[y, :] = (c_top * (1.0 - fr) + c_bot * fr).astype(np.uint8)

    # Fading trails
    n_trails = len(trails)
    c_trail = np.array(theme["boid_trail"], dtype=np.float32)
    for i, t_pos in enumerate(trails):
        alpha = (i + 1.0) / (n_trails + 1.0) * 0.6
        for p in t_pos:
            x, y = int(p[0]) % 32, int(p[1]) % 32
            curr = frame[y, x].astype(np.float32)
            frame[y, x] = np.clip(curr * (1.0 - alpha) + c_trail * alpha, 0, 255).astype(np.uint8)

    # Draw Boids
    c_head = theme["boid_head"]
    c_body = theme["boid_body"]
    is_firefly = theme_name == "fireflies"

    for i in range(len(pos)):
        px, py = int(pos[i, 0]) % 32, int(pos[i, 1]) % 32
        vx, vy = vel[i, 0], vel[i, 1]

        if is_firefly:
            # Pulsing bioluminescence: 4 pulses per loop (t is the loop phase), phase set by position so it
            # stays continuous when boids are re-labelled at the loop seam
            pulse = math.sin(t * TAU * 4 + pos[i, 0] * 0.45 + pos[i, 1] * 0.3) * 0.5 + 0.5
            col = tuple(int(c * (0.4 + 0.6 * pulse)) for c in c_head)
            frame[py, px] = col  # type: ignore[assignment]
            # 1-pixel soft glow halo
            if pulse > 0.7:
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = (py + dy) % 32, (px + dx) % 32
                    halo = tuple(int(c * 0.3) for c in c_body)
                    frame[ny, nx] = halo  # type: ignore[assignment]
        else:
            # Head pixel
            frame[py, px] = c_head
            # Tail pixel pointing opposite to velocity
            tx = round(px - vx * 0.8) % 32
            ty = round(py - vy * 0.8) % 32
            frame[ty, tx] = c_body

    # Draw Predator
    if has_predator:
        ppx, ppy = int(pred_pos[0]) % 32, int(pred_pos[1]) % 32
        c_pred = theme["predator"]
        # Predator is larger: 2x2 diamond
        frame[ppy, ppx] = (255, 255, 255)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            frame[(ppy + dy) % 32, (ppx + dx) % 32] = c_pred

    return frame


_READY: dict[tuple[str, str, float], list[np.ndarray]] = {}  # finished loops, filled by clip_frames()
N_FRAMES = 64  # 8 s at 8 fps
BLEND = 16  # frames over which the end of the flight morphs back into its start (the loop seam)


def _wrap(d: np.ndarray) -> np.ndarray:
    """Shortest signed distance on the 32 px torus."""
    return (d + 16.0) % 32.0 - 16.0


def _match(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Greedy pairing of boids in `a` to boids in `b` (shortest toroidal hops first): perm[i] is a's partner."""
    d = np.linalg.norm(_wrap(b[None, :, :] - a[:, None, :]), axis=-1)
    perm = np.full(len(a), -1)
    used: set[int] = set()
    for flat in np.argsort(d, axis=None):
        i, j = divmod(int(flat), len(b))
        if perm[i] < 0 and j not in used:
            perm[i] = j
            used.add(j)
    return perm


@lru_cache(maxsize=16)
def _generate_boids_loop(
    theme: str, predator_mode: str, rate: float, n_frames: int = N_FRAMES
) -> list[np.ndarray]:
    """A seamless flocking loop. The flock is simulated for the loop plus BLEND frames; over the first BLEND
    frames each boid glides from where it is after the loop to where it is at the start (partners matched by
    distance), so the last frame flows into the first. `rate` is simulation steps per frame (the speed)."""
    rng = np.random.RandomState(42)
    n = 22
    pos = rng.uniform(4, 28, (n, 2)).astype(np.float32)
    vel = rng.uniform(-1, 1, (n, 2)).astype(np.float32)
    pred_pos = np.array([16.0, 16.0], dtype=np.float32)
    pred_vel = np.array([0.8, 0.4], dtype=np.float32)
    has_pred = predator_mode == "on"

    for _ in range(50):  # warmup
        _step_boids(pos, vel, pred_pos, pred_vel, has_pred)
    steps = math.ceil((n_frames + BLEND) * rate) + 2
    hist_p, hist_v, hist_q = [pos.copy()], [vel.copy()], [pred_pos.copy()]
    for _ in range(steps):
        _step_boids(pos, vel, pred_pos, pred_vel, has_pred)
        hist_p.append(pos.copy())
        hist_v.append(vel.copy())
        hist_q.append(pred_pos.copy())

    def at(hist: list[np.ndarray], tau: float, wrap: bool = True) -> np.ndarray:
        """State at fractional step `tau` (positions interpolate along the shortest wrap-around hop)."""
        k = int(tau)
        fr = tau - k
        if not wrap:
            return hist[k] + (hist[k + 1] - hist[k]) * fr
        return (hist[k] + _wrap(hist[k + 1] - hist[k]) * fr) % 32.0

    m = n_frames + BLEND
    ps = [at(hist_p, i * rate) for i in range(m)]
    vs = [at(hist_v, i * rate, wrap=False) for i in range(m)]
    qs = [at(hist_q, i * rate) for i in range(m)]
    perm = _match(ps[n_frames], ps[0])
    frames: list[np.ndarray] = []
    for i in range(n_frames):
        p, v, q = ps[i], vs[i], qs[i]
        if i < BLEND:  # glide from the end of the flight (frame n + i) into its start (frame i)
            w = i / (BLEND - 1)
            w = w * w * (3 - 2 * w)
            a, b = ps[n_frames + i], ps[i][perm]
            p = (a + _wrap(b - a) * w) % 32.0
            v = vs[n_frames + i] * (1 - w) + vs[i][perm] * w
            qa = qs[n_frames + i]
            q = (qa + _wrap(qs[i] - qa) * w) % 32.0
        # each frame is drawn from its own positions + headings (rows are re-labelled across the seam)
        trails = [(p - v * rate * k) % 32.0 for k in (3, 2, 1)]
        frames.append(_render_boids_frame(p, v, trails, q, theme, has_pred, t=i / n_frames))
    return frames


class BoidsSettings(AppSettings):
    theme: str = Choice(
        "deep_sea",
        {
            "deep_sea": "Bioluminescent Abyss",
            "starlings": "Twilight Murmuration",
            "fireflies": "Summer Fireflies",
            "cyber": "Cyberpunk Nanobots",
        },
        title="Visual Theme",
    )
    predator: str = Choice(
        "off",
        {
            "off": "Peaceful Flock",
            "on": "Apex Predator Chasing",
        },
        title="Predator Mode",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, title="Swarm Speed")
    brightness: float = Field(default=1.0, ge=0.2, le=1.0, title="LED Brightness")


@register
class Boids(App):
    id = "boids"
    name = "Flocking Boids"
    category = "creative"
    description = "Craig Reynolds flocking swarm simulation and bioluminescent particle life."
    Settings = BoidsSettings

    clip_seconds = N_FRAMES / 8.0  # 64 frames at 8 fps
    clip_fps = 8.0
    clip_colors = 32
    fps = 8.0

    def kind(self) -> Kind:
        return "clip"

    def _key(self) -> tuple[str, str, float]:
        # speed = simulation steps per frame (0.7 at speed 1: <= ~1 px/frame), never the frame duration
        return (self.settings.theme, self.settings.predator, round(0.7 * self.settings.speed, 2))

    def render(self, f: Frame, t: float) -> None:
        # The simulation takes ~60-100 ms, far over the 2 ms render budget, so it runs in clip_frames() (on the
        # engine's bake thread); render() only reads the finished loop, and shows a calm placeholder meanwhile.
        frames = _READY.get(self._key())
        if frames is None:
            loading(f, t, "FLOCK")
            return
        img = frames[int(round(t * self.clip_fps, 6)) % len(frames)]
        if self.settings.brightness < 1.0:
            f.px[:] = (img.astype(np.float32) * self.settings.brightness).astype(np.uint8)
        else:
            f.px[:] = img

    def clip_frames(self) -> Clip:
        key = self._key()
        frames = _READY.get(key) or _generate_boids_loop(*key)
        _READY[key] = frames
        out: list[Frame] = []
        for i in range(len(frames)):
            f = Frame()
            self.render(f, i / self.clip_fps)
            out.append(f)
        return Clip(out, [round(1000 / self.clip_fps)] * len(out))
