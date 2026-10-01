"""Falling Sand — Powder Toy style cellular automaton physics sandbox on 32x32.

Simulates granular and fluid dynamics: falling sand dunes, flowing water, rising fire
and smoke, combustible plants, corrosive acid, and molten lava solidifying on contact.
Seamless loops are precomputed and baked into native hardware GIFs.
"""

from __future__ import annotations

import random
from functools import lru_cache

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame
from ._kit import loading

# Element IDs
EMPTY = 0
SAND = 1
WATER = 2
FIRE = 3
PLANT = 4
STONE = 5
ACID = 6
LAVA = 7
SMOKE = 8

# Color definitions (RGB)
PALETTES: dict[str, dict[int, tuple[int, int, int]]] = {
    "vibrant": {
        EMPTY: (8, 10, 16),
        SAND: (215, 155, 45),
        WATER: (45, 140, 255),
        FIRE: (255, 80, 20),
        PLANT: (45, 200, 75),
        STONE: (110, 116, 136),  # stone/glass lifted: darker greys vanish at the panel's gamma 1.5
        ACID: (60, 255, 30),
        LAVA: (255, 45, 10),
        SMOKE: (90, 95, 110),
    },
    "retro": {
        EMPTY: (0, 0, 0),
        SAND: (218, 165, 32),
        WATER: (30, 100, 200),
        FIRE: (230, 60, 30),
        PLANT: (34, 139, 34),
        STONE: (128, 128, 128),
        ACID: (50, 205, 50),
        LAVA: (220, 20, 60),
        SMOKE: (80, 80, 80),
    },
    "neon": {
        EMPTY: (12, 6, 20),
        SAND: (255, 230, 90),
        WATER: (0, 240, 255),
        FIRE: (255, 0, 120),
        PLANT: (0, 255, 160),
        STONE: (120, 100, 165),
        ACID: (180, 255, 0),
        LAVA: (255, 50, 0),
        SMOKE: (120, 80, 140),
    },
    "pastel": {
        EMPTY: (18, 20, 28),
        SAND: (240, 210, 140),
        WATER: (120, 180, 240),
        FIRE: (255, 140, 100),
        PLANT: (140, 220, 150),
        STONE: (140, 145, 160),
        ACID: (160, 245, 120),
        LAVA: (255, 120, 90),
        SMOKE: (120, 125, 140),
    },
}


def _step_ca(grid: np.ndarray, ages: np.ndarray, rng: random.Random) -> None:
    """Run one tick of granular/fluid cellular automaton physics."""
    # Bottom to top for falling matter
    for y in range(30, -1, -1):
        # Alternate sweep direction to avoid directional bias
        xs = list(range(32))
        if rng.random() < 0.5:
            xs.reverse()

        for x in xs:
            elem = grid[y, x]
            if elem in (EMPTY, STONE):
                continue

            # --- FIRE & SMOKE (rises) ---
            if elem in (FIRE, SMOKE):
                ages[y, x] += 1
                if ages[y, x] > (4 if elem == FIRE else 6):
                    grid[y, x] = EMPTY
                    continue
                # Rise upwards
                ny = y - 1
                nx = x + rng.choice((-1, 0, 1))
                if 0 <= ny < 32 and 0 <= nx < 32:
                    target = grid[ny, nx]
                    if target == EMPTY:
                        grid[ny, nx] = elem
                        ages[ny, nx] = ages[y, x]
                        grid[y, x] = EMPTY
                    elif target == PLANT and elem == FIRE:
                        grid[ny, nx] = FIRE
                        ages[ny, nx] = 0
                    elif target == WATER and elem == FIRE:
                        grid[ny, nx] = SMOKE
                        ages[ny, nx] = 0
                        grid[y, x] = EMPTY
                continue

            # --- PLANT (growth when hydrated) ---
            if elem == PLANT:
                # Check adjacent water
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < 32 and 0 <= nx < 32 and grid[ny, nx] == WATER:
                        grid[ny, nx] = EMPTY  # drink water
                        # Sprout upwards or sideways
                        sy = y - 1
                        sx = x + rng.choice((-1, 0, 1))
                        if 0 <= sy < 32 and 0 <= sx < 32 and grid[sy, sx] == EMPTY:
                            grid[sy, sx] = PLANT
                            ages[sy, sx] = 0
                        break
                continue

            # --- LAVA ---
            if elem == LAVA:
                # Check for water reaction -> Stone + Steam
                quenched = False
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < 32 and 0 <= nx < 32 and grid[ny, nx] == WATER:
                        grid[y, x] = STONE
                        grid[ny, nx] = SMOKE
                        ages[ny, nx] = 0
                        quenched = True
                        break
                if quenched:
                    continue

                # Burn adjacent plant
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < 32 and 0 <= nx < 32 and grid[ny, nx] == PLANT:
                        grid[ny, nx] = FIRE
                        ages[ny, nx] = 0

                # Lava flows down slowly
                if y < 31 and grid[y + 1, x] == EMPTY:
                    grid[y + 1, x] = LAVA
                    grid[y, x] = EMPTY
                elif rng.random() < 0.4:
                    dirs = [-1, 1]
                    rng.shuffle(dirs)
                    for dx in dirs:
                        nx = x + dx
                        if 0 <= nx < 32 and y < 31 and grid[y + 1, nx] == EMPTY:
                            grid[y + 1, nx] = LAVA
                            grid[y, x] = EMPTY
                            break
                        elif 0 <= nx < 32 and grid[y, nx] == EMPTY:
                            grid[y, nx] = LAVA
                            grid[y, x] = EMPTY
                            break
                continue

            # --- ACID ---
            if elem == ACID:
                # Dissolves organic/solid matter
                dissolved = False
                for dy, dx in ((1, 0), (0, -1), (0, 1), (-1, 0)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < 32 and 0 <= nx < 32 and grid[ny, nx] in (SAND, PLANT, STONE):
                        grid[ny, nx] = SMOKE
                        ages[ny, nx] = 2
                        grid[y, x] = EMPTY
                        dissolved = True
                        break
                if dissolved:
                    continue

                # Liquid flow
                if y < 31 and grid[y + 1, x] == EMPTY:
                    grid[y + 1, x] = ACID
                    grid[y, x] = EMPTY
                else:
                    dirs = [-1, 1]
                    rng.shuffle(dirs)
                    moved = False
                    for dx in dirs:
                        nx = x + dx
                        if 0 <= nx < 32 and y < 31 and grid[y + 1, nx] == EMPTY:
                            grid[y + 1, nx] = ACID
                            grid[y, x] = EMPTY
                            moved = True
                            break
                    if not moved:
                        for dx in dirs:
                            nx = x + dx
                            if 0 <= nx < 32 and grid[y, nx] == EMPTY:
                                grid[y, nx] = ACID
                                grid[y, x] = EMPTY
                                break
                continue

            # --- SAND ---
            if elem == SAND and y < 31:
                below = grid[y + 1, x]
                if below == EMPTY:
                    grid[y + 1, x] = SAND
                    grid[y, x] = EMPTY
                    continue
                elif below in (WATER, ACID):  # Sand sinks in water
                    grid[y + 1, x] = SAND
                    grid[y, x] = below
                    continue

                # Check diagonals down-left and down-right
                dirs = [-1, 1]
                rng.shuffle(dirs)
                moved = False
                for dx in dirs:
                    nx = x + dx
                    if 0 <= nx < 32:
                        diag = grid[y + 1, nx]
                        if diag == EMPTY:
                            grid[y + 1, nx] = SAND
                            grid[y, x] = EMPTY
                            moved = True
                            break
                        elif diag in (WATER, ACID):
                            grid[y + 1, nx] = SAND
                            grid[y, x] = diag
                            moved = True
                            break
                if moved:
                    continue

            # --- WATER ---
            if elem == WATER:
                # Check straight down
                if y < 31 and grid[y + 1, x] == EMPTY:
                    grid[y + 1, x] = WATER
                    grid[y, x] = EMPTY
                    continue

                # Check down-diagonals
                dirs = [-1, 1]
                rng.shuffle(dirs)
                moved = False
                for dx in dirs:
                    nx = x + dx
                    if 0 <= nx < 32 and y < 31 and grid[y + 1, nx] == EMPTY:
                        grid[y + 1, nx] = WATER
                        grid[y, x] = EMPTY
                        moved = True
                        break
                if moved:
                    continue

                # Horizontal flow
                for dx in dirs:
                    nx = x + dx
                    if 0 <= nx < 32 and grid[y, nx] == EMPTY:
                        grid[y, nx] = WATER
                        grid[y, x] = EMPTY
                        break


def _render_grid_to_rgb(grid: np.ndarray, ages: np.ndarray, palette_name: str) -> np.ndarray:
    """Render 32x32 simulation grid to RGB array with dynamic shading."""
    pal = PALETTES.get(palette_name, PALETTES["vibrant"])
    img = np.zeros((32, 32, 3), dtype=np.uint8)

    for elem, base_color in pal.items():
        mask = grid == elem
        if not np.any(mask):
            continue

        if elem == EMPTY:
            img[mask] = base_color
        elif elem == SAND:
            # Subtle grain noise
            noise = ((np.arange(32 * 32).reshape(32, 32) * 17) % 25 - 12)[..., None]
            c = np.clip(np.array(base_color, dtype=np.int16) + noise, 0, 255).astype(np.uint8)
            img[mask] = c[mask]
        elif elem == WATER:
            # Subtle wave shimmer
            shimmer = ((grid == WATER) & (np.roll(grid == WATER, -1, axis=0) == 0))[..., None]
            c = np.where(
                shimmer, (min(255, base_color[0] + 50), min(255, base_color[1] + 50), 255), base_color
            )
            img[mask] = c[mask]
        elif elem == FIRE:
            # Flicker from age
            age_f = (ages[mask] / 4.0)[..., None]
            yellow = np.array([255, 230, 40], dtype=np.float32)
            red = np.array(base_color, dtype=np.float32)
            c = (yellow * (1.0 - age_f) + red * age_f).clip(0, 255).astype(np.uint8)
            img[mask] = c
        elif elem == LAVA:
            # Glowing core
            img[mask] = base_color
        elif elem == PLANT:
            img[mask] = base_color
        elif elem == STONE:
            # Brick texture
            stone_arr = np.full((32, 32, 3), base_color, dtype=np.uint8)
            # Mortar lines
            for y in range(32):
                if y % 4 == 3:  # (not 0: the shelves sit on rows 12/20/28 and would all be mortar)
                    stone_arr[y, :] = (base_color[0] - 25, base_color[1] - 25, base_color[2] - 25)
            img[mask] = stone_arr[mask]
        elif elem == ACID:
            img[mask] = base_color
        elif elem == SMOKE:
            fade = np.clip(1.0 - ages[mask] / 6.0, 0.2, 1.0)[..., None]
            img[mask] = (np.array(base_color, dtype=np.float32) * fade).astype(np.uint8)

    return img


_READY: dict[tuple[str, str, int], list[np.ndarray]] = {}  # finished loops, filled by clip_frames()
N_FRAMES = 48
DISSOLVE = 12  # frames over which the end of the run dissolves, grain by grain, back into its start
FRAME_MS = 125  # busy full-screen motion reads smoothly at <= 8 fps (HARDWARE_PROTOCOL #13)


def pacing(speed: float) -> tuple[int, int]:
    """(CA steps per frame, frame ms). A cellular automaton moves in whole ticks: faster runs more ticks per
    frame, slower holds each tick longer — the loop is the same frames either way, so it stays seamless."""
    steps = max(1, round(speed))
    return steps, max(FRAME_MS, round(FRAME_MS * steps / speed))


@lru_cache(maxsize=16)
def _simulate_scenario(
    scenario: str, palette: str, steps: int = 1, n_frames: int = N_FRAMES
) -> list[np.ndarray]:
    """Deterministic frames for a preset scenario. The automaton never repeats exactly, so the run goes
    DISSOLVE frames past the loop and those frames dissolve pixel by pixel (a fixed random order) into the
    first ones: the last frame flows into the first without a jump."""
    rng = random.Random(42)
    grid = np.zeros((32, 32), dtype=np.uint8)
    ages = np.zeros((32, 32), dtype=np.uint8)

    # Setup initial boundary & geometry
    if scenario == "hourglass":
        # A closed glass: caps top and bottom, two bulbs meeting at a 2 px neck (rows 15-16, columns 15-16)
        grid[3, 3:29] = STONE
        grid[28, 3:29] = STONE
        for i in range(11):  # staircase walls: a 1-px diagonal would let grains slip through its corners
            for dy in (0, 1):
                grid[4 + i + dy, 4 + i] = STONE
                grid[4 + i + dy, 27 - i] = STONE
                grid[27 - i - dy, 4 + i] = STONE
                grid[27 - i - dy, 27 - i] = STONE
        grid[15:17, 14] = STONE
        grid[15:17, 17] = STONE
        # the upper bulb full of sand
        for y in range(5, 13):
            for x in range(y + 1, 31 - y):
                grid[y, x] = SAND

    elif scenario == "volcano":
        # Mountain slopes
        for x in range(32):
            h = max(0, int(20 - abs(x - 16) * 1.3))
            for y in range(31 - h, 32):
                grid[y, x] = STONE
        # Crater cavity
        for y in range(12, 18):
            for x in range(14, 18):
                grid[y, x] = LAVA
        # Water pool on the sides
        for y in range(26, 32):
            for x in range(0, 7):
                grid[y, x] = WATER
            for x in range(25, 32):
                grid[y, x] = WATER

    elif scenario == "oasis":
        # Terraced stone cliffs
        grid[12, 0:14] = STONE
        grid[20, 10:24] = STONE
        grid[28, 0:32] = STONE
        # Initial plant seeds
        grid[19, 12] = PLANT
        grid[19, 13] = PLANT
        grid[27, 22] = PLANT
        grid[27, 23] = PLANT

    elif scenario == "acid_lab":
        # Suspended stone shelves
        grid[10, 8:24] = STONE
        grid[18, 4:18] = STONE
        grid[18, 20:28] = STONE
        grid[26, 6:26] = STONE
        # Sand deposits on shelves
        grid[9, 10:22] = SAND
        grid[17, 6:16] = SAND

    elif scenario == "elemental":
        # Partitioned container
        grid[15, 0:13] = STONE
        grid[15, 19:32] = STONE
        grid[22, 12:20] = STONE
        # Initial deposits
        grid[14, 2:8] = PLANT
        grid[21, 14:18] = LAVA

    # Run warmup to reach dynamic equilibrium (the hourglass only until the stream is flowing)
    for _ in range(12 if scenario == "hourglass" else 60):
        _emit_sources(grid, ages, scenario, rng)
        _step_ca(grid, ages, rng)

    if scenario == "hourglass":
        return _hourglass_loop(grid, ages, palette, steps, rng)
    frames: list[np.ndarray] = []
    for _ in range(n_frames + DISSOLVE):
        for _ in range(steps):
            _emit_sources(grid, ages, scenario, rng)
            _step_ca(grid, ages, rng)
        frames.append(_render_grid_to_rgb(grid, ages, palette))
    order = np.random.default_rng(7).random((32, 32))  # when each pixel switches over
    for k in range(DISSOLVE):
        late = (order >= (k + 1) / (DISSOLVE + 1))[..., None]  # still showing the end of the run
        frames[k] = np.where(late, frames[n_frames + k], frames[k])
    return frames[:n_frames]


def _squash(img: np.ndarray, k: float, bg: tuple[int, int, int]) -> np.ndarray:
    """The frame squeezed vertically about its centre to `k` of its height (a turning glass, seen edge-on)."""
    out = np.empty_like(img)
    out[:] = bg
    for y in range(32):
        src = 15.5 + (y + 0.5 - 16.0) / max(k, 1e-3)
        if 0 <= src < 32:
            out[y] = img[int(src)]
    return out


def _hourglass_loop(
    grid: np.ndarray, ages: np.ndarray, palette: str, steps: int, rng: random.Random
) -> list[np.ndarray]:
    """The sand runs down, rests, then the glass turns over (a vertical squeeze through its edge) and the loop
    starts again from the turned glass — the swap happens while it is a single line, so the loop never jumps.
    The glass is symmetric top to bottom, so turning it is a flip of the grid."""

    def run(g: np.ndarray, a: np.ndarray, record: bool) -> tuple[list[np.ndarray], np.ndarray]:
        shots: list[np.ndarray] = []
        still = 0
        for _ in range(400):
            before = g.copy()
            for _ in range(steps):
                _step_ca(g, a, rng)
            if record:
                shots.append(_render_grid_to_rgb(g, a, palette))
            still = still + 1 if np.array_equal(before, g) else 0
            if still >= 2:
                break
        return shots, g

    _, settled = run(grid, ages, record=False)  # a first run only to learn how the sand comes to rest
    start = np.flipud(settled).copy()
    start_rgb = _render_grid_to_rgb(start, ages, palette)
    frames, _end = run(start.copy(), np.zeros_like(ages), record=True)
    frames = [start_rgb, *frames]
    frames += [frames[-1]] * 6  # rest a moment before turning
    bg = PALETTES.get(palette, PALETTES["vibrant"])[EMPTY]
    last = frames[-1]
    frames += [_squash(last, k, bg) for k in (0.7, 0.4, 0.12)]
    frames += [_squash(start_rgb, k, bg) for k in (0.12, 0.4, 0.7)]
    return frames


def _emit_sources(grid: np.ndarray, ages: np.ndarray, scenario: str, rng: random.Random) -> None:
    """Continuously supply particles according to scenario themes."""
    if scenario == "hourglass":
        return  # a closed glass: the sand just runs through (the loop's dissolve turns it back over)
    if scenario == "volcano":
        # Lava eruption from crater
        if rng.random() < 0.6:
            x = rng.randint(14, 17)
            grid[11, x] = LAVA
            # Fiery spark
            if rng.random() < 0.4:
                grid[9, rng.randint(13, 18)] = FIRE
                ages[9, :] = 0

    elif scenario == "oasis":
        # Water spring pouring from top-left
        if rng.random() < 0.8:
            grid[2, rng.choice((4, 5, 6))] = WATER

    elif scenario == "acid_lab":
        # Acid dropper from ceiling
        if rng.random() < 0.35:
            grid[1, rng.choice((15, 16))] = ACID

    elif scenario == "elemental":
        # Multi-element dripper
        r = rng.random()
        if r < 0.25:
            grid[2, 6] = WATER
        elif r < 0.45:
            grid[2, 16] = SAND
        elif r < 0.65:
            grid[2, 25] = ACID


class SandSettings(AppSettings):
    scenario: str = Choice(
        "hourglass",
        {
            "hourglass": "Hourglass",
            "volcano": "Lava Volcano",
            "oasis": "Waterfall Oasis",
            "acid_lab": "Acid Laboratory",
            "elemental": "Elemental Crucible",
        },
        title="Simulation Scenario",
    )
    palette: str = Choice(
        "vibrant",
        {
            "vibrant": "Vibrant",
            "retro": "Retro 8-Bit",
            "neon": "Cyber Neon",
            "pastel": "Soft Pastel",
        },
        title="Color Palette",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0, title="Simulation Speed")
    brightness: float = Field(default=1.0, ge=0.2, le=1.0, title="LED Brightness")


@register
class Sand(App):
    id = "sand"
    name = "Falling Sand"
    category = "creative"
    description = "Powder Toy cellular automaton with sand, water, fire, lava, plants, and acid."
    Settings = SandSettings

    clip_seconds = 6.0  # 48 frames at 8 fps = 6.0 s seamless loop
    clip_fps = 8.0
    clip_colors = 32
    fps = 8.0

    def kind(self) -> Kind:
        return "clip"

    def _key(self) -> tuple[str, str, int]:
        return (self.settings.scenario, self.settings.palette, pacing(self.settings.speed)[0])

    def render(self, f: Frame, t: float) -> None:
        # The simulation takes ~60-100 ms, far over the 2 ms render budget, so it runs in clip_frames() (on the
        # engine's bake thread); render() only reads the finished loop, and shows a calm placeholder meanwhile.
        frames = _READY.get(self._key())
        if frames is None:
            loading(f, t, "SAND")
            return
        ms = pacing(self.settings.speed)[1]
        img = frames[int(round(t * 1000 / ms, 6)) % len(frames)]
        if self.settings.brightness < 1.0:
            f.px[:] = (img.astype(np.float32) * self.settings.brightness).astype(np.uint8)
        else:
            f.px[:] = img

    def clip_frames(self) -> Clip:
        key = self._key()
        frames = _READY.get(key) or _simulate_scenario(*key)
        _READY[key] = frames
        ms = pacing(self.settings.speed)[1]
        out: list[Frame] = []
        for i in range(len(frames)):
            f = Frame()
            self.render(f, i * ms / 1000)
            out.append(f)
        return Clip(out, [ms] * len(out))
