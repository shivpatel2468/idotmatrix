"""Loops — a pack of novelty animations, every one a baked clip that the panel plays natively.

* ``rain``  — glyph rain: columns of invented 3×5 glyphs stream down, heads white-hot, tails fading green.
* ``warp``  — hyperspace: stars stretch into streaks as they fly past, with a soft blue core.
* ``life``  — Conway's Game of Life from hand-picked seeds (R-pentomino, acorn, glider fleets, oscillators,
  a soup); a seed that dies or settles into a short cycle fades out and the next one starts.
* ``cat``   — Pip, an original ginger tabby in a red scarf, flying through space on a rainbow comet trail.
* ``dvd``   — the DESKDOT logo bouncing around the screen, changing colour on every wall, celebrating corners.

(Fire and lava lamp live in Ambient and aren't repeated here; Ambient's rain and starfield are the plain
line/dot versions, these are the glyph and streak ones.) Every effect is a function of the loop phase or a
fixed-seed simulation, so the GIF is deterministic and loops seamlessly.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import Frame, Sprite, hsv, mix, scale, to_rgb
from ..gfx.color import RGB

TAU = math.tau

# ------------------------------------------------------------------------------------------ rain glyphs
# sixteen invented 3×5 glyphs (not any real script) so the columns read as "code"
_GLYPH_ROWS = (
    ["###", "..#", ".##", "..#", "..#"],
    ["#.#", "###", "..#", ".#.", "#.."],
    ["##.", "..#", "###", "#..", ".##"],
    [".#.", "###", ".#.", "#.#", "#.#"],
    ["###", "#..", "###", "..#", "#.."],
    ["#..", "###", "#.#", "..#", ".#."],
    [".##", "#..", "#.#", ".##", "..#"],
    ["###", ".#.", "###", ".#.", "#.."],
    ["#.#", "#.#", ".##", "..#", "##."],
    ["..#", ".##", "#.#", "..#", "..#"],
    ["###", "#.#", "#.#", "..#", ".#."],
    [".#.", "#.#", "..#", ".#.", "###"],
    ["#..", "#.#", "###", "..#", "..#"],
    ["##.", ".##", "..#", ".#.", ".#."],
    ["#.#", ".#.", "###", ".#.", "#.#"],
    [".##", ".#.", "##.", ".#.", ".##"],
)
GLYPHS = [np.array([[c == "#" for c in r[::-1]] for r in g], bool) for g in _GLYPH_ROWS]  # mirrored

# ------------------------------------------------------------------------------------------ Pip the cat
# 16×9, facing right: pointed ears, green eyes, pink nose, white muzzle and belly, tabby stripes, tail up.
_CAT_BODY = [
    "..........O....O",
    "..T.......OO..OO",
    ".T........OOOOOO",
    ".T...ODODOOGOOGO",
    "..T.OODODOOOWPWO",
    "...OOOOOOOOOWWW.",
    "...OWWWWWWO.....",
]
_CAT_LEGS = (
    ["...OO...OO......", "..OO.....OO....."],
    ["....OO..OO......", "....O....O......"],
    [".....OOOO.......", ".....O..O......."],
    ["....OO..OO......", "...O......O....."],
)
_CAT_PAL = {
    "O": (255, 140, 20),
    "D": (190, 70, 0),
    "W": (255, 236, 210),
    "G": (60, 255, 90),
    "P": (255, 110, 160),
    "T": (230, 110, 10),
}
CAT_FRAMES = [Sprite.parse(_CAT_BODY + legs, _CAT_PAL) for legs in _CAT_LEGS]
SCARF: RGB = (255, 30, 60)

# ------------------------------------------------------------------------------------------ Life seeds
LIFE_SEEDS: list[tuple[str, list[str]]] = [
    ("r-pentomino", [".##", "##.", ".#."]),
    ("acorn", [".#.....", "...#...", "##..###"]),
    ("gliders", []),  # generated: a fleet
    ("pulsar+penta", []),  # generated: two oscillators side by side
    ("diehard", ["......#.", "##......", ".#...###"]),
    ("soup", []),  # generated: fixed-seed random soup
    ("lwss", []),  # generated: spaceship convoy
]


PULSAR = [
    "..###...###..",
    ".............",
    "#....#.#....#",
    "#....#.#....#",
    "#....#.#....#",
    "..###...###..",
    ".............",
    "..###...###..",
    "#....#.#....#",
    "#....#.#....#",
    "#....#.#....#",
    ".............",
    "..###...###..",
]
PENTADECATHLON = [".#.", ".#.", "#.#", ".#.", ".#.", ".#.", ".#.", "#.#", ".#.", ".#."]


def _stamp(g: np.ndarray, rows: list[str], x: int, y: int, flip: bool = False) -> None:
    for j, r in enumerate(rows):
        for i, c in enumerate(r[::-1] if flip else r):
            if c == "#":
                g[(y + j) % 32, (x + i) % 32] = True


def life_seed(k: int) -> np.ndarray:
    name, rows = LIFE_SEEDS[k % len(LIFE_SEEDS)]
    g = np.zeros((32, 32), bool)
    if name == "gliders":
        glider = [".#.", "..#", "###"]
        for i, (x, y) in enumerate(((2, 2), (12, 5), (22, 1), (6, 16), (18, 20), (26, 12))):
            _stamp(g, glider, x, y, flip=i % 2 == 1)
    elif name == "pulsar+penta":
        _stamp(g, PULSAR, 2, 9)
        _stamp(g, PENTADECATHLON, 23, 11)
    elif name == "soup":
        rng = np.random.default_rng(7)
        g[8:24, 8:24] = rng.random((16, 16)) < 0.38
    elif name == "lwss":
        ship = [".#..#", "#....", "#...#", "####."]
        for y in (3, 13, 23):
            _stamp(g, ship, 4 + (y % 7), y)
    else:
        h, w = len(rows), len(rows[0])
        _stamp(g, rows, 16 - w // 2, 16 - h // 2)
    return g


def life_step(g: np.ndarray) -> np.ndarray:
    n = sum(np.roll(np.roll(g, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)
    return (n == 3) | (g & (n == 2))


@lru_cache(maxsize=2)
def life_run(n_frames: int, max_gens: int = 110) -> list[tuple[np.ndarray, np.ndarray, float]]:
    """(grid, age, brightness) for each frame: seeds run until they die, cycle or hit max_gens, then fade out."""
    out: list[tuple[np.ndarray, np.ndarray, float]] = []
    seed = 0
    while len(out) < n_frames:
        g = life_seed(seed)
        age = np.zeros((32, 32), np.int16)
        history: list[bytes] = []
        for gen in range(max_gens):
            fade_in = min(1.0, (gen + 1) / 3)
            out.append((g.copy(), age.copy(), fade_in))
            key = np.packbits(g).tobytes()
            if gen > 12 and (key in history[-16:] or g.sum() < 3):
                break
            history.append(key)
            nxt = life_step(g)
            age = np.where(nxt, np.where(g, age + 1, 0), 0).astype(np.int16)
            g = nxt
        for k in range(4):  # fade out
            out.append((g.copy(), age.copy(), 1 - (k + 1) / 5))
        seed += 1
    out = out[:n_frames]
    # make the loop seam a fade: the last frames dim towards black (the first frame fades in)
    for i in range(1, 4):
        grid, ag, b = out[-i]
        out[-i] = (grid, ag, b * i / 4)
    return out


class LoopsSettings(AppSettings):
    effect: str = Choice(
        "cat",
        {
            "cat": "Pixel cat",
            "rain": "Glyph rain",
            "warp": "Warp speed",
            "life": "Game of Life",
            "dvd": "Bouncing logo",
        },
        title="Loop",
    )
    speed: float = Field(1.0, ge=0.5, le=2.0, title="Speed")
    tint: Color = Field("#00ff5a", title="Rain colour")
    warp_color: Color = Field("#3c8cff", title="Warp colour")
    brightness: float = Field(1.0, ge=0.2, le=1.0, title="Brightness")


# effect -> (seconds, fps) of the baked loop. On the panel, motion reads as smooth only in small steps per frame
# at ~8 fps (verified: the cat was choppy at 12 fps, and at 8 fps with bigger steps; smooth at 8 fps with the
# original small steps). So loops play at 8 fps and are long enough that each frame moves only a little.
LOOP_SPEC: dict[str, tuple[float, float]] = {
    "cat": (12.0, 8.0),  # 96 frames: half-pixel-ish steps read smoother than 48 on the panel
    "rain": (7.5, 8.0),
    "warp": (5.6, 8.0),
    "life": (30.0, 8.0),
    "dvd": (30.0, 8.0),  # 240 frames, one pixel per frame
}


@register
class Loops(App):
    id = "loops"
    name = "Loops"
    description = (
        "Novelty loops: pixel cat on a rainbow trail, glyph rain, warp speed, Game of Life, bouncing logo."
    )
    icon = "infinity"
    category = "ambient"
    Settings = LoopsSettings
    fps = 12.0
    clip_colors = 64

    def __init__(self, *a: object, **kw: object) -> None:
        super().__init__(*a, **kw)  # type: ignore[arg-type]
        self._life: list[tuple[np.ndarray, np.ndarray, float]] | None = None
        self.on_settings()

    def on_settings(self) -> None:
        if self.settings.effect == "life":  # simulate the whole run up front, not inside render()
            secs, fps = LOOP_SPEC["life"]
            self._life = life_run(round(secs * fps))

    def kind(self) -> Kind:
        return "clip"

    def spec(self) -> tuple[float, float]:
        return LOOP_SPEC[self.settings.effect]

    def clip_frames(self) -> Clip:
        secs, fps = self.spec()
        n = round(secs * fps)
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / fps)
            frames.append(f)
        ms = max(20, round(1000 / (fps * self.settings.speed)))
        return Clip(frames, [ms] * n)

    def render(self, f: Frame, t: float) -> None:
        secs, fps = self.spec()
        ph = (t / secs) % 1.0
        frame_no = round(ph * secs * fps) % round(secs * fps)
        getattr(self, f"fx_{self.settings.effect}")(f, ph, frame_no)
        if self.settings.brightness < 1:
            f.dim(self.settings.brightness)

    # ------------------------------------------------------------------------------------------ rain
    def fx_rain(self, f: Frame, ph: float, n: int) -> None:
        tint = to_rgb(self.settings.tint)
        head = mix(tint, (255, 255, 255), 0.75)
        rows = 6  # glyph rows at a 6 px pitch (the last one is cut by the edge)
        rnd = random.Random(42)
        for col in range(8):
            x = col * 4
            for stream in range(2):
                laps = rnd.choice((1, 2, 2, 3))
                length = rnd.randint(3, 6)
                off = rnd.random()
                span = rows + length
                pos = int(((ph * laps + off) % 1.0) * span)  # head cell, whole cells only (discrete steps)
                if stream == 1 and rnd.random() < 0.5:
                    continue
                for k in range(length):
                    cell = pos - k
                    if not 0 <= cell < rows:
                        continue
                    # glyphs mutate now and then: index depends on the cell and a slow frame bucket
                    bucket = (n // (3 + (col + cell) % 4)) if k else n
                    gi = (col * 7 + cell * 13 + bucket * (5 if k == 0 else 1) + stream * 3) % len(GLYPHS)
                    c = head if k == 0 else scale(tint, (1 - k / length) ** 1.3 * 0.95 + 0.05)
                    y = cell * 6
                    g = GLYPHS[gi]
                    sub = f.px[y : y + 5, x : x + 3]
                    sub[g[: sub.shape[0], : sub.shape[1]]] = c

    # ------------------------------------------------------------------------------------------ warp
    def fx_warp(self, f: Frame, ph: float, n: int) -> None:
        tint = to_rgb(self.settings.warp_color)
        star_c = mix(tint, (255, 255, 255), 0.2)
        head_c = mix(tint, (255, 255, 255), 0.8)
        # soft core
        yy, xx = np.mgrid[0:32, 0:32]
        d = np.hypot(xx - 15.5, yy - 15.5)
        glow = np.clip(1 - d / 9, 0, 1) ** 2 * (0.25 + 0.05 * math.sin(ph * TAU * 3))
        f.px[:] = (np.array(scale(tint, 0.35), np.float32) * glow[..., None]).astype(np.uint8)
        rnd = random.Random(9)
        for _ in range(70):
            a = rnd.uniform(0, TAU)
            r0 = rnd.uniform(0.15, 1.0)
            off = rnd.random()
            laps = rnd.choice((1, 2))
            z = 1.0 - ((ph * laps + off) % 1.0)  # 1 far -> 0 near
            z = max(0.05, z)
            z_prev = min(1.0, z + 0.09 * laps)
            k = 7.0
            x1, y1 = 15.5 + math.cos(a) * r0 / z * k, 15.5 + math.sin(a) * r0 / z * k
            x0, y0 = 15.5 + math.cos(a) * r0 / z_prev * k, 15.5 + math.sin(a) * r0 / z_prev * k
            bright = min(1.0, (1 - z) * 1.5)
            steps = max(1, int(math.hypot(x1 - x0, y1 - y0)))
            for s in range(steps + 1):
                u = s / steps
                c = head_c if s == steps else star_c
                f.blend(round(x0 + (x1 - x0) * u), round(y0 + (y1 - y0) * u), c, bright * (0.25 + 0.75 * u))

    # ------------------------------------------------------------------------------------------ life
    def fx_life(self, f: Frame, ph: float, n: int) -> None:
        if self._life is None:
            self.on_settings()
        assert self._life is not None
        grid, age, bright = self._life[n % len(self._life)]
        young = np.array((180, 255, 255), np.float32)
        old = np.array((110, 40, 255), np.float32)
        k = np.clip(age / 12.0, 0, 1)[..., None]
        col = young * (1 - k) + old * k
        f.px[:] = np.where(grid[..., None], col * bright, 0).astype(np.uint8)

    # ------------------------------------------------------------------------------------------ cat
    def fx_cat(self, f: Frame, ph: float, n: int) -> None:
        # stars: three parallax layers, whole screen widths per loop so the loop is seamless
        rnd = random.Random(3)
        for layer, (count, laps, b) in enumerate(((14, 1, 0.35), (8, 2, 0.6), (5, 3, 1.0))):
            for _ in range(count):
                x0, y = rnd.randrange(32), rnd.randrange(32)
                x = (x0 - round(ph * laps * 32)) % 32
                tw = 1.0 if layer < 2 else (0.6 + 0.4 * math.sin(ph * TAU * 4 + x0))
                f.set(x, y, scale((200, 210, 255), b * tw))
                if layer == 2:  # the near stars are little crosses
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        f.set(x + dx, y + dy, scale((120, 130, 200), 0.5 * tw))
        bob = round(1.2 * math.sin(ph * TAU * 2))
        cx, cy = 13, 11 + bob
        # rainbow comet trail: a tapering ribbon from the tail to the left edge, hues sliding along it
        tail_x = cx + 1
        for x in range(tail_x, -1, -1):
            dist = tail_x - x
            half = max(0.6, 2.4 - dist * 0.12)
            wob = math.sin(dist * 0.45 - ph * TAU * 2) * min(1.5, dist * 0.12)
            mid = cy + 5.5 + wob
            fade = max(0.0, 1 - dist / 16)
            for y in range(math.floor(mid - half), math.ceil(mid + half) + 1):
                inside = 1 - abs(y - mid) / (half + 0.5)
                if inside <= 0:
                    continue
                hue = (y - mid) / 7 + 0.5 + dist * 0.02 - ph
                f.blend(x, y, hsv(hue, 0.9, 1.0), fade * min(1.0, inside * 1.6))
        # sparkles shed by the trail
        for i in range(6):
            life = (ph * 3 + i / 6) % 1.0
            sx = round(tail_x - life * 14)
            sy = round(cy + 5 + math.sin(i * 2.1) * (1 + life * 5))
            f.set(sx, sy, scale((255, 255, 220), (1 - life) * 0.9))
        f.sprite(CAT_FRAMES[(n // 2) % len(CAT_FRAMES)], cx, cy)
        # red scarf: a collar at the neck and a streamer fluttering back over the shoulders
        for dy in (3, 4, 5):
            f.set(cx + 10, cy + dy, SCARF)
        for i in range(5):
            wave = round(math.sin(ph * TAU * 4 - i * 1.2) * min(1.0, i * 0.45))
            f.set(cx + 9 - i, cy + 2 + wave, SCARF if i < 3 else scale(SCARF, 0.65))

    # ------------------------------------------------------------------------------------------ dvd
    LOGO_W, LOGO_H = 17, 13

    def fx_dvd(self, f: Frame, ph: float, n: int) -> None:
        secs, fps = LOOP_SPEC["dvd"]
        total = round(secs * fps)  # 240 frames
        rx, ry = 32 - self.LOGO_W, 32 - self.LOGO_H  # 15, 19
        px, py = 30, 48  # frames per round trip: corners meet every lcm(15, 24) = 120 frames
        tx, ty = (n % px) / px, (n % py) / py
        x = round(rx * (1 - abs(1 - 2 * tx)))
        y = round(ry * (1 - abs(1 - 2 * ty)))
        bounces = n // (px // 2) + n // (py // 2)
        col = hsv((bounces * 0.37) % 1.0, 0.9, 1.0)
        since_x, since_y = n % (px // 2), n % (py // 2)
        corner_age = n % 120  # both walls at once
        if corner_age < 10:
            k = 1 - corner_age / 10
            cxp, cyp = 0, (0 if (n // 120) % 2 == 0 else 31)
            for i in range(12):
                a = i / 12 * TAU
                r = 2 + corner_age * 1.6
                f.set(round(cxp + math.cos(a) * r), round(cyp + math.sin(a) * r), hsv(i / 12, 0.7, k))
            if corner_age < 4:
                col = mix(col, (255, 255, 255), 0.7)
        elif min(since_x, since_y) < 2:
            col = mix(col, (255, 255, 255), 0.35)  # a little flash on every wall hit
        self._logo(f, x, y, col)
        _ = total

    def _logo(self, f: Frame, x: int, y: int, col: RGB) -> None:
        f.text(x, y, "DOT", col, font="small")
        f.text(x + 1, y + 8, "DECK", scale(col, 0.8))
