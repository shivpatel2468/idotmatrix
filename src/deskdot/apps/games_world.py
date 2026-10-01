"""Dig World — a side-view block sandbox. Original code, world generator and pixel art.

The world is 96 × 40 blocks of 2 × 2 px: grass, dirt, stone, four ores, caves, trees, lakes and bedrock. A tiny
miner (1 × 2 blocks, 2 × 4 px) digs, collects, places blocks and builds. Underground is dark until the miner's
lamp has lit it, which keeps most of the panel black (small PNG frames) and makes every tunnel a discovery.

Hardware-friendly motion (docs/HARDWARE_PROTOCOL.md #9, #13): the camera never scrolls smoothly; it jumps in
half-screen steps (8 blocks = 16 px) when the miner nears an edge, and the miner walks at ~1 px per streamed frame.

The demo AI plans with a bounded Dijkstra over standing positions (walk, step up, drop, dig through, pillar up):
by day it tunnels towards the most valuable ore it has seen (or explores downwards), at dusk it climbs to open sky
and builds a little house with a pitched roof and a window, sleeps through the night while creatures prowl
outside, and digs its way out at dawn.

Up to four miners share one world: in Co-op two miners pool their ore and a knocked-out miner is revived by a
partner (or at dawn); in Ore Rush every miner digs for their own score until the days run out. Biomes (maps)
change the generator: rolling meadows, deep caverns rich in ore, steep peaks, and lake country. The camera follows
seat 1; other miners off screen show as edge pointers in their colours.
"""

from __future__ import annotations

import heapq
import math
from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, scale
from .games_core import WHITE, GameApp, GameSettings, Mode, Theme, tint

# ----------------------------------------------------------------------------- blocks
(AIR, GRASS, DIRT, STONE, COAL, COPPER, GOLD, GEM, WOOD, LEAF, WATER, PLANK, ROOF, GLASS, TORCH, BEDROCK) = (
    range(16)
)
N_BLOCKS = 16
SOLID = frozenset({GRASS, DIRT, STONE, COAL, COPPER, GOLD, GEM, PLANK, ROOF, GLASS, BEDROCK})
ORES = {COAL: 1, COPPER: 3, GOLD: 6, GEM: 10}  # block → points
HARD = {GRASS: 0.22, DIRT: 0.22, STONE: 0.42, COAL: 0.5, COPPER: 0.5, GOLD: 0.55, GEM: 0.6}
HARD.update({PLANK: 0.3, ROOF: 0.3, GLASS: 0.2})
WW, WH = 96, 40  # world size in blocks
VW = 16  # viewport, blocks (2 px each)
DUSK, NIGHT, DAWN = 0.55, 0.64, 0.97

WALK_T, FALL_T, CLIMB_T, PLACE_T = 0.27, 0.13, 0.32, 0.17


def _q(c: RGB) -> tuple[RGB, RGB, RGB, RGB]:
    return (c, c, c, c)


def _palette(theme: str) -> dict[int, tuple[RGB, RGB, RGB, RGB]]:
    # bright enough to survive the panel's gamma calibration (dark tones crush on the LEDs)
    grass = (50, 200, 50)
    dirt = (140, 78, 32)
    stone = (92, 92, 108)
    wood, leaf, water = (96, 58, 22), (18, 104, 30), (12, 42, 150)
    if theme == "neon":
        grass, dirt, stone = (0, 220, 150), (70, 20, 80), (36, 30, 70)
        leaf = (0, 120, 90)
    elif theme == "retro":
        grass, dirt, stone = (170, 150, 20), (90, 40, 10), (60, 40, 30)
    elif theme == "mono":
        grass, dirt, stone = (80, 230, 90), (20, 70, 30), (16, 50, 24)
    elif theme == "frost":  # snow on top, cold blue-grey rock (as bright as the meadow's, for the LEDs)
        grass, dirt, stone = (225, 235, 250), (120, 112, 140), (96, 110, 136)
        wood, leaf, water = (96, 70, 50), (40, 110, 96), (40, 110, 200)
    elif theme == "dune":  # sand over sandstone, an oasis for the lakes
        grass, dirt, stone = (235, 200, 110), (190, 140, 70), (140, 100, 70)
        wood, leaf, water = (120, 80, 40), (60, 150, 50), (20, 120, 170)
    ore = {COAL: (14, 14, 18), COPPER: (230, 120, 60), GOLD: (255, 205, 0), GEM: (0, 230, 235)}
    if theme == "mono":
        ore = {COAL: (0, 20, 0), COPPER: (120, 220, 120), GOLD: (190, 255, 190), GEM: (240, 255, 240)}
    elif theme == "frost":  # no cyan gems in blue rock: they turn magenta
        ore = {COAL: (14, 14, 18), COPPER: (230, 120, 60), GOLD: (255, 205, 0), GEM: (255, 70, 190)}
    elif theme == "dune":  # copper-coloured ore would vanish in sandstone: turquoise instead
        ore = {COAL: (14, 14, 18), COPPER: (80, 220, 230), GOLD: (255, 215, 0), GEM: (255, 70, 190)}
    pal = {
        GRASS: (grass, grass, dirt, dirt),
        DIRT: _q(dirt),
        STONE: _q(stone),
        WOOD: _q(wood),
        LEAF: _q(leaf),
        WATER: _q(water),
        PLANK: ((170, 110, 50), (170, 110, 50), (120, 72, 30), (120, 72, 30)),
        ROOF: ((200, 40, 40), (200, 40, 40), (140, 24, 24), (140, 24, 24)),
        GLASS: ((120, 200, 255), (40, 90, 150), (40, 90, 150), (40, 90, 150)),
        TORCH: ((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)),  # drawn by hand
        BEDROCK: ((30, 30, 34), (16, 16, 18), (16, 16, 18), (30, 30, 34)),
        AIR: _q((0, 0, 0)),
    }
    for b, c in ore.items():
        pal[b] = (c, stone, c, c)  # a nugget: three ore pixels, one rock
    return pal


def _luts(theme: str) -> np.ndarray:
    """(4, N_BLOCKS, 3) colour table: one per pixel of the block."""
    pal = _palette(theme)
    out = np.zeros((4, N_BLOCKS, 3), dtype=np.uint8)
    for b, quad in pal.items():
        for k in range(4):
            out[k, b] = quad[k]
    return out


# sky colours (flat, stepped — no gradients): day, dusk, night
SKY = {"day": (40, 100, 210), "dusk": (120, 44, 84), "night": (4, 4, 22)}
CAVE = (46, 34, 28)  # explored tunnels: clearly lighter than unexplored (black) rock
DARK = (0, 0, 0)  # unexplored rock


#: per-theme look of the sky, tunnels, miner and creatures. `classic` = the meadow look; the shared themes derive
#: theirs from the Theme roles.
LOOKS: dict[str, dict[str, Any]] = {
    "overworld": {
        "sky": SKY,
        "cave": CAVE,
        "helmet": (255, 200, 0),
        "shirt": (255, 125, 95),  # warm: never lost against the blue day sky
        "mob": (215, 125, 255),
        "eye": (255, 50, 40),
    },
    "frost": {
        "sky": {"day": (70, 120, 190), "dusk": (90, 60, 110), "night": (4, 6, 20)},
        "cave": (34, 40, 56),
        "helmet": (255, 200, 0),
        "shirt": (255, 125, 95),
        "mob": (150, 255, 140),
        "eye": (40, 0, 60),
    },
    "dune": {
        "sky": {"day": (90, 150, 220), "dusk": (150, 70, 50), "night": (8, 4, 14)},
        "cave": (56, 40, 26),
        "helmet": (255, 220, 40),
        "shirt": (255, 120, 180),
        "mob": (120, 255, 120),
        "eye": (255, 40, 40),
    },
}


def _theme(look: dict[str, Any]) -> Theme:
    return Theme(
        p=look["shirt"],
        e=look["mob"],
        x=look["helmet"],
        w=(92, 92, 108),
        hud=WHITE,
        bg=look["sky"]["night"],
        r=(
            (230, 120, 60),
            (255, 205, 0),
            (0, 230, 235),
            (170, 110, 50),
            (200, 40, 40),
            (120, 200, 255),
            WHITE,
        ),
    )


#: biomes: generator parameters (base height, hill amplitude, caves, cave length, cave top, ore amount, lakes)
BIOMES: dict[str, tuple[str, float, float, int, tuple[int, int], int, float, int]] = {
    "meadow": ("Meadow", 14.0, 1.0, 7, (18, 40), 22, 1.0, 1),
    "caverns": ("Caverns", 11.0, 0.8, 16, (30, 60), 16, 1.4, 1),
    "peaks": ("Peaks", 17.0, 2.2, 4, (18, 40), 24, 1.0, 1),
    "lakes": ("Lakes", 14.0, 1.0, 6, (18, 40), 22, 1.0, 3),
}

# per-miner state: one miner at a time is "loaded" onto the app (seat 1 while idle) so the planner, actions and
# drawing helpers keep working on plain attributes
MINER_ATTRS = (
    "mc",
    "mr",
    "face",
    "task",
    "anim",
    "inv",
    "hearts",
    "hurt",
    "mode",
    "plan",
    "goal",
    "skip",
    "explore",
    "fails",
    "blueprint",
    "house",
    "build_mode",
    "aim",
    "pending",
    "jump_hang",
    "swing",
    "swing_at",
    "idle",
    "pts",
    "down_t",
)


class DigSettings(GameSettings):
    creatures: bool = Field(True, title="Night creatures", json_schema_extra={"group": "Game"})
    day_length: int = Field(50, ge=20, le=180, title="Day length (s)", json_schema_extra={"group": "Game"})
    hearts: int = Field(3, ge=1, le=5, title="Hearts", json_schema_extra={"group": "Game"})
    match_days: int = Field(
        2,
        ge=1,
        le=5,
        title="Match length (days)",
        description="Co-op and Ore Rush end after this many days",
        json_schema_extra={"group": "Game"},
    )


@register
class DigWorld(GameApp):
    id = "digworld"
    name = "Dig World"
    description = (
        "A block-world sandbox: the miner digs for ore, builds a house at dusk and hides from night creatures. "
        "Arrows walk/dig, A jumps (or places in build mode), B toggles dig/build. Two miners play co-op, "
        "up to four race for ore."
    )
    icon = "pickaxe"
    Settings = DigSettings
    step_hz = 30.0
    over_hold = 2.5
    max_players: ClassVar[int] = 4
    controls = ("dpad", "gamepad", "joystick", "keyboard")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("coop", "Co-op", 2, 2, "coop", "Pool your ore; revive a knocked-out partner by touching them"),
        Mode("rush", "Ore Rush", 2, 4, "ffa", "Most ore when the days run out wins"),
    )
    maps: ClassVar[dict[str, str]] = {k: v[0] for k, v in BIOMES.items()}
    game_themes: ClassVar[dict[str, Theme]] = {k: _theme(v) for k, v in LOOKS.items()}
    game_theme_labels: ClassVar[dict[str, str]] = {"overworld": "Overworld", "frost": "Frost", "dune": "Dune"}

    # ------------------------------------------------------------------ world
    def new_game(self) -> None:
        self._lut_theme = ""
        self._gen()
        self.tod = 0.26  # time of day, 0 = dawn
        self.day = 0
        self.mobs: list[list[float]] = []  # [c, r, hp, move_timer, anim_dx, anim_dy, anim_t]
        self.spawn_t = 2.0
        self.last_score_t = 0.0
        self.seat_order = sorted(self.roster) if self.roster else [1]
        self.miners: dict[int, dict[str, Any]] = {}
        dry = [c for c in range(4, WW - 4) if self.g[self._top(c)][c] != WATER]
        c0 = min(dry, key=lambda c: abs(c - WW // 2)) if dry else WW // 2
        for i, seat in enumerate(self.seat_order):
            want = c0 + (0, 3, -3, 6)[i % 4]
            self._init_miner(min(dry, key=lambda c, w=want: abs(c - w)) if dry else want)
            self._save(seat)
        self._seat = self.seat_order[0]
        self._load(self._seat)
        self.cam_c = max(0, min(WW - VW, self.mc - VW // 2))
        self.cam_r = max(0, min(WH - VW, self.mr - 9))
        for m in self.miners.values():
            self._reveal(m["mc"], m["mr"], 4)

    def _init_miner(self, c: int) -> None:
        self.mc = c
        self.mr = self._top(self.mc) - 1
        self.face = 1
        self.task: list[Any] | None = None  # [kind, args, t_left, total]
        self.anim = (0.0, 0.0)  # draw offset while moving, px
        self.inv = 14  # building blocks carried
        self.hearts = int(self.settings.hearts)
        self.hurt = 0.0
        self.mode = "work"  # work | home | build | sleep
        self.plan: list[tuple[str, int, int, int]] = []  # (kind, dc, feet c, feet r) steps
        self.goal: tuple[int, int] | None = None
        self.skip: set[tuple[int, int]] = set()
        self.explore: tuple[int, int] | None = None
        self.fails = 0
        self.blueprint: list[tuple[int, int, int]] = []
        self.house: tuple[int, int] | None = None
        self.build_mode = False  # human: dig (False) or place (True)
        self.aim = (1, 0)
        self.pending: str | None = None
        self.jump_hang = 0.0
        self.swing = 0.0
        self.swing_at: tuple[int, int] = (0, 0)
        self.idle = 0.0
        self.pts = 0
        self.down_t = 0.0  # knocked out: > 0 (Ore Rush: seconds until the miner respawns)

    def _save(self, seat: int) -> None:
        self.miners[seat] = {a: getattr(self, a) for a in MINER_ATTRS}

    def _load(self, seat: int) -> None:
        for a, v in self.miners[seat].items():
            setattr(self, a, v)
        self._seat = seat

    @property
    def multi(self) -> bool:
        return len(self.seat_order) > 1

    def _controlled(self, seat: int | None = None) -> bool:
        """Is this miner (default: the loaded one) driven by a person right now?"""
        return self.is_human(self._seat if seat is None else seat)

    def _gen(self) -> None:
        rng = self.rng
        biome = self.map_id if self.map_id in BIOMES else "meadow"
        _label, base, amp, n_caves, cave_len, cave_top, ore_mul, lakes = BIOMES[biome]
        # heightmap: sum of a few smooth random waves, plus one valley that becomes a lake
        waves = [
            (rng.uniform(0.05, 0.12), rng.uniform(0, 6.3), rng.uniform(1.2, 2.6) * amp) for _ in range(3)
        ]
        valley = rng.randrange(12, WW - 12)
        if abs(valley - WW // 2) < 10:
            valley = (valley + 30) % (WW - 24) + 12
        valleys = [valley]
        for _ in range(lakes - 1):  # lake country: more valleys, away from the start and each other
            v = rng.randrange(8, WW - 8)
            if abs(v - WW // 2) > 9 and all(abs(v - o) > 14 for o in valleys):
                valleys.append(v)
        h = []
        for c in range(WW):
            y = base + sum(a * math.sin(c * f + p) for f, p, a in waves)
            y += sum(4.5 * max(0.0, 1 - abs(c - v) / 6.0) for v in valleys)
            h.append(max(6, min(27, round(y))))
        g = [bytearray(WW) for _ in range(WH)]
        self.surface = h[:]  # original surface row per column (sky above, cave backdrop below)
        for c in range(WW):
            for r in range(h[c], WH):
                d = r - h[c]
                g[r][c] = GRASS if d == 0 else DIRT if d < 3 + (c * 7 % 3 == 0) else STONE
            g[WH - 1][c] = BEDROCK
            if rng.random() < 0.5:
                g[WH - 2][c] = BEDROCK
        # caves: random walkers carving 1–2 block tunnels
        for _ in range(n_caves):
            c, r = rng.uniform(4, WW - 4), rng.uniform(cave_top, WH - 5)
            a = rng.uniform(0, 6.3)
            for _ in range(rng.randrange(*cave_len)):
                a += rng.uniform(-0.6, 0.6)
                c = min(WW - 3, max(2, c + math.cos(a)))
                r = min(WH - 4, max(h[int(c)] + 5, r + math.sin(a) * 0.6))
                for dc, dr in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    if g[int(r) + dr][int(c) + dc] != BEDROCK:
                        g[int(r) + dr][int(c) + dc] = AIR
        # ore veins, rarer and richer with depth
        for ore, n, lo, size in ((COAL, 60, 2, 4), (COPPER, 42, 5, 3), (GOLD, 26, 10, 3), (GEM, 16, 15, 2)):
            for _ in range(round(n * ore_mul)):
                c = rng.randrange(1, WW - 1)
                r = rng.randrange(min(WH - 3, h[c] + lo), WH - 2)
                for _ in range(rng.randrange(1, size + 1)):
                    if g[r][c] == STONE:
                        g[r][c] = ore
                    c = min(WW - 2, max(1, c + rng.choice((-1, 0, 1))))
                    r = min(WH - 3, max(1, r + rng.choice((-1, 0, 1))))
        # a surface nugget near the start so the first minute has something shiny
        c0 = WW // 2 + rng.choice((-5, 5))
        g[h[c0] + 4][c0] = COPPER
        # lake: fill the valley below the water line
        for valley in valleys:
            wl = max(h[max(0, valley - 7)], h[min(WW - 1, valley + 7)])
            basin = [valley]
            for step in (-1, 1):  # only the valley's own basin floods, not every low column in the world
                c = valley + step
                while 0 < c < WW - 1 and h[c] > wl:
                    basin.append(c)
                    c += step
            for c in basin:
                if h[c] > wl:
                    for r in range(wl, h[c]):
                        g[r][c] = WATER
                    g[h[c]][c] = DIRT
        # trees (walk-through scenery)
        c = rng.randrange(2, 6)
        while c < WW - 3:
            if g[h[c]][c] == GRASS and abs(c - WW // 2) > 1 and rng.random() < 0.55:
                top = h[c] - rng.randrange(3, 5)
                for r in range(top, h[c]):
                    g[r][c] = WOOD
                for dc, dr in ((-1, 0), (0, -1), (1, 0), (-1, -1), (1, -1), (0, -2), (-1, 1), (1, 1)):
                    if g[top + dr][c + dc] == AIR:
                        g[top + dr][c + dc] = LEAF
                c += rng.randrange(5, 9)
            else:
                c += rng.randrange(2, 4)
        self.g = g
        self.seen = [bytearray(WW) for _ in range(WH)]
        for c in range(WW):
            for r in range(0, min(WH, h[c] + 4)):
                self.seen[r][c] = 1
        self.stars = [(self.rng.randrange(32), self.rng.randrange(1, 14)) for _ in range(9)]

    # ---------------------------------------------------------------- queries
    def _solid(self, c: int, r: int) -> bool:
        if not (0 <= c < WW) or r >= WH:
            return True
        if r < 0:
            return False
        return self.g[r][c] in SOLID

    def _clear(self, c: int, r: int) -> bool:
        return 0 <= c < WW and r < WH and (r < 0 or self.g[r][c] not in SOLID)

    def _supported(self, c: int, r: int) -> bool:
        return self._solid(c, r + 1)

    def _top(self, c: int) -> int:
        """Row of the highest solid block (or water) in column c."""
        for r in range(WH):
            b = self.g[r][c]
            if b in SOLID or b == WATER:
                return r
        return WH - 1

    def _wet(self, c: int, r: int) -> bool:
        return 0 <= c < WW and 0 <= r < WH and self.g[r][c] == WATER

    def _reveal(self, c: int, r: int, rad: int) -> None:
        # ores glint from a little further away than the lamp lights plain rock
        for dr in range(-6, 7):
            rr = r + dr
            if 0 <= rr < WH:
                row = self.g[rr]
                for cc in range(max(0, c - 6), min(WW, c + 7)):
                    if row[cc] in ORES:
                        self.seen[rr][cc] = 1
        for dr in range(-rad, rad + 1):
            for dc in range(-rad, rad + 1):
                if dc * dc + dr * dr <= rad * rad + 1:
                    cc, rr = c + dc, r + dr
                    if 0 <= cc < WW and 0 <= rr < WH:
                        self.seen[rr][cc] = 1

    def _mob_at(self, c: int, r: int) -> list[float] | None:
        for m in self.mobs:
            if int(m[0]) == c and int(m[1]) in (r, r + 1):
                return m
        return None

    # --------------------------------------------------------------- actions
    def _start(self, kind: str, args: tuple[int, ...], dur: float) -> None:
        self.task = [kind, args, dur, dur]

    def _try_dig(self, c: int, r: int) -> bool:
        if not (0 <= c < WW and 0 <= r < WH):
            return False
        b = self.g[r][c]
        if b not in HARD:
            return False
        self._start("dig", (c, r), HARD[b])
        return True

    def _try_move(self, dc: int, dr: int) -> bool:
        c, r = self.mc + dc, self.mr + dr
        if not (self._clear(c, r) and self._clear(c, r - 1)):
            return False
        if dr < 0 and not self._clear(self.mc, self.mr - 2):
            return False
        wet = self._wet(self.mc, self.mr) or self._wet(c, r)
        dur = CLIMB_T if dr < 0 and dc else WALK_T if dr == 0 else FALL_T
        self._start("move", (dc, dr), dur * (1.6 if wet else 1.0))
        if dc:
            self.face = dc
        return True

    def _finish(self) -> None:
        assert self.task is not None
        kind, args, _t, _total = self.task
        self.task = None
        self.anim = (0.0, 0.0)
        th = self.theme
        if kind == "move":
            dc, dr = args
            self.mc += dc
            self.mr += dr
            self._reveal(self.mc, self.mr - 1, 4)
        elif kind == "dig":
            c, r = args
            b = self.g[r][c]
            if b in HARD:
                self.g[r][c] = AIR
                col = self._lut[0, b]
                self.fx.burst(
                    self.rng, c * 2 + 1 - self.cam_c * 2, r * 2 + 1 - self.cam_r * 2, tuple(col), 5, 7, 0.4
                )
                if b in ORES:
                    self._award(ORES[b])
                    self.last_score_t = 0.0
                    self.flash = 0.25
                    self.fx.burst(self.rng, (c - self.cam_c) * 2 + 1, (r - self.cam_r) * 2, th.x, 4, 9, 0.5)
                elif b not in (GLASS,):
                    self.inv = min(99, self.inv + 1)
                self._reveal(c, r, 2)
        elif kind == "place":
            c, r, b = args
            ok = self._clear(c, r) and self.inv > 0 and not self._mob_at(c, r) and not self._miner_at(c, r)
            if ok and not (c == self.mc and r in (self.mr, self.mr - 1)):
                self.g[r][c] = b
                self.inv -= 1
        elif kind == "pillar":
            b = args[0]
            self.mr -= 1
            if self.inv > 0 and self._clear(self.mc, self.mr + 1):
                self.g[self.mr + 1][self.mc] = b
                self.inv -= 1
        elif kind == "hit":
            m = self._mob_at(*args)
            if m is not None:
                m[2] -= 1
                if m[2] <= 0:
                    self.mobs.remove(m)
                    self._award(5)
                    self.fx.burst(
                        self.rng,
                        (m[0] - self.cam_c) * 2 + 1,
                        (m[1] - self.cam_r) * 2,
                        self._look()["mob"],
                        10,
                        10,
                        0.6,
                    )
                else:  # a hit knocks sparks off it
                    self.fx.burst(
                        self.rng, (m[0] - self.cam_c) * 2 + 1, (m[1] - self.cam_r) * 2, WHITE, 3, 6, 0.3
                    )

    def _award(self, n: int) -> None:
        """Points for the loaded miner. Co-op pools them; in Ore Rush the panel score is seat 1's own."""
        self.pts += n
        if self.play_mode.id != "rush" or not self.multi or self._seat == 1:
            self.score += n

    def _miner_at(self, c: int, r: int) -> bool:
        """Another miner (not the loaded one) stands in cell (c, r)."""
        for seat, m in self.miners.items():
            if seat != self._seat and m["mc"] == c and r in (m["mr"], m["mr"] - 1):
                return True
        return False

    # ------------------------------------------------------------------ human
    def key(self, k: str) -> None:
        if k == "b":
            self.build_mode = not self.build_mode
            return
        self.pending = k
        if k in ("left", "right", "up", "down"):
            self.aim = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[k]

    def key_p(self, k: str, player: int) -> None:
        if player == self._seat:
            self.key(k)
            return
        m = self.miners.get(player)
        if m is None:
            return
        if k == "b":
            m["build_mode"] = not m["build_mode"]
            return
        m["pending"] = k
        if k in ("left", "right", "up", "down"):
            m["aim"] = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[k]

    def _human(self) -> None:
        k, self.pending = self.pending, None
        if k is None:
            return
        c, r = self.mc, self.mr
        if k in ("left", "right"):
            d = -1 if k == "left" else 1
            self.face = d
            if self._try_move(d, 0):
                return
            room = self._clear(c + d, r - 1) and self._clear(c + d, r - 2) and self._clear(c, r - 2)
            if room and self._try_move(d, -1):
                return
            if self.build_mode:
                return
            m = self._mob_at(c + d, r) or self._mob_at(c + d, r - 1)
            if m is not None:
                self._start("hit", (c + d, int(m[1])), 0.25)
            elif not self._try_dig(c + d, r - 1):
                self._try_dig(c + d, r)
        elif k == "up":
            if not self.build_mode and self._solid(c, r - 2):
                self._try_dig(c, r - 2)
            elif not self.build_mode:
                self._jump()
        elif k == "down":
            if not self.build_mode:
                self._try_dig(c, r + 1)
        elif k == "a":
            if not self.build_mode:
                self._jump()
                return
            dc, dr = self.aim
            if (dc, dr) == (0, 1):
                if self._supported(c, r) and self._clear(c, r - 2) and self.inv > 0:
                    self._start("pillar", (PLANK,), CLIMB_T)
                return
            side = (c + dc, r) if self._clear(c + dc, r) else (c + dc, r - 1)
            tgt = (c, r - 2) if dr < 0 else side
            if self._clear(*tgt) and self.inv > 0:
                self._start("place", (*tgt, PLANK), PLACE_T)

    def _jump(self) -> None:
        if self._supported(self.mc, self.mr) or self._wet(self.mc, self.mr):
            self._try_move(0, -1)
            self.jump_hang = 0.3

    # --------------------------------------------------------------------- AI
    def _neighbours(self, c: int, r: int) -> list[tuple[float, int, int, str, int]]:
        """Moves from standing position (c, r): (cost, c2, r2, kind, dc)."""
        out = []
        solid, clear = self._solid, self._clear
        inv = self.inv

        def dig(cc: int, rr: int) -> float:
            if clear(cc, rr):
                return 0.0
            b = self.g[rr][cc] if 0 <= cc < WW and 0 <= rr < WH else BEDROCK
            h = HARD.get(b)
            return 99.0 if h is None else 1.0 + h * 5

        for d in (-1, 1):
            c2 = c + d
            if not 0 <= c2 < WW:
                continue
            # walk / tunnel sideways, then drop
            k = dig(c2, r) + dig(c2, r - 1)
            if k < 50:
                r2 = r
                wet = False
                while r2 + 1 < WH and not solid(c2, r2 + 1):
                    r2 += 1
                    if self._wet(c2, r2):
                        wet = True
                        break
                if not wet and not self._wet(c2, r) and not self._wet(c2, r - 1):
                    out.append((1.0 + k + (r2 - r) * 0.3, c2, r2, "side", d))
            # step up
            if solid(c2, r):
                k = dig(c, r - 2) + dig(c2, r - 1) + dig(c2, r - 2)
                if (
                    k < 50
                    and not self._wet(c2, r - 1)
                    and not self._wet(c2, r - 2)
                    and not self._wet(c, r - 2)
                ):
                    out.append((1.6 + k, c2, r - 1, "up", d))
        # dig down
        if r + 2 < WH and self.g[r + 1][c] in HARD:
            k = dig(c, r + 1)
            r2 = r + 1
            while r2 + 1 < WH and not solid(c, r2 + 1) and not self._wet(c, r2 + 1):
                r2 += 1
            if solid(c, r2 + 1):
                out.append((1.5 + k + (r2 - r - 1) * 0.3, c, r2, "down", 0))
        # pillar up
        if inv > 3 and r > 3:
            k = dig(c, r - 2)
            if k < 50 and not self._wet(c, r - 2):
                out.append((7.0 + k, c, r - 1, "pillar", 0))  # costs a block: stairs are better
        return out

    def _search(self, score_fn: Any, limit: int = 420) -> list[tuple[str, int, int, int]]:
        """Bounded Dijkstra from the miner; returns the step list to the visited node with the lowest score."""
        start = (self.mc, self.mr)
        dist = {start: 0.0}
        prev: dict[tuple[int, int], tuple[tuple[int, int], str, int]] = {}
        pq = [(0.0, start)]
        best, best_s = None, math.inf
        n = 0
        c0, r0 = start
        while pq and n < limit:
            d, node = heapq.heappop(pq)
            if d > dist.get(node, math.inf):
                continue
            n += 1
            s = score_fn(node[0], node[1], d)
            if s < best_s:
                best, best_s = node, s
            for cost, c2, r2, kind, dc in self._neighbours(*node):
                if abs(c2 - c0) > 15 or abs(r2 - r0) > 14:
                    continue
                nd = d + cost
                if nd < dist.get((c2, r2), math.inf):
                    dist[(c2, r2)] = nd
                    prev[(c2, r2)] = (node, kind, dc)
                    heapq.heappush(pq, (nd, (c2, r2)))
        if best is None or best == start:
            return []
        steps = []
        node = best
        while node != start:
            p, kind, dc = prev[node]
            steps.append((kind, dc, node[0], node[1]))
            node = p
        steps.reverse()
        return steps

    def _adjacent_cells(self, c: int, r: int) -> tuple[tuple[int, int], ...]:
        return ((c - 1, r), (c + 1, r), (c - 1, r - 1), (c + 1, r - 1), (c, r + 1), (c, r - 2))

    def _ore_near(self, c: int, r: int) -> tuple[int, int] | None:
        best = None
        for cc, rr in self._adjacent_cells(c, r):
            if not (0 <= cc < WW and 0 <= rr < WH and self.g[rr][cc] in ORES and self.seen[rr][cc]):
                continue
            if best is None or ORES[self.g[rr][cc]] > ORES[self.g[best[1]][best[0]]]:
                best = (cc, rr)
        return best

    def _plan_work(self) -> None:
        seen, g = self.seen, self.g
        # commit to one ore at a time (re-choosing every step makes the miner dither)
        if self.goal is not None:
            gc, gr = self.goal
            if g[gr][gc] not in ORES:
                self.goal = None
        if self.goal is None:
            greed = 1.0 + 3.0 * self.skill  # skill: chase the richest ore rather than the nearest
            best, best_s = None, -math.inf
            for rr in range(max(0, self.mr - 12), min(WH, self.mr + 13)):
                row, srow = g[rr], seen[rr]
                for cc in range(max(0, self.mc - 13), min(WW, self.mc + 14)):
                    b = row[cc]
                    if b in ORES and srow[cc] and (cc, rr) not in self.skip:
                        sc = ORES[b] * greed - abs(cc - self.mc) - abs(rr - self.mr) * 1.3
                        if sc > best_s:
                            best, best_s = (cc, rr), sc
            self.goal = best
        if self.goal is not None:
            oc, orr = self.goal

            def score(c: int, r: int, d: float) -> float:
                dd = abs(oc - c) + abs(orr - (r - 0.5))
                return d + (0.0 if dd <= 1.6 else dd * 8.0)

            steps = self._search(score, 500)
            if steps:
                self.plan = steps
                return
            if self._ore_near(self.mc, self.mr) is None:
                self.skip.add(self.goal)  # unreachable from here: forget it
                self.goal = None
        # explore: head for a random point, mostly downwards and sideways
        if self.explore is None or (abs(self.explore[0] - self.mc) + abs(self.explore[1] - self.mr)) < 3:
            tc = min(WW - 3, max(2, self.mc + self.rng.choice((-1, 1)) * self.rng.randrange(6, 14)))
            depth = self.surface[tc] + self.rng.randrange(3, 22)
            self.explore = (tc, min(WH - 4, depth))
        tc, tr = self.explore

        def escore(c: int, r: int, d: float) -> float:
            return d * 0.35 + abs(c - tc) + abs(r - tr) * 1.2

        self.plan = self._search(escore)
        if not self.plan:
            self.explore = None
            self.fails += 1

    def _plan_home(self) -> bool:
        """Climb towards open sky. True when standing somewhere a house fits."""
        if self._house_ok(self.mc, self.mr):
            return True

        def score(c: int, r: int, d: float) -> float:
            ok = self._house_ok(c, r)
            return d * 0.4 + (0 if ok else 12 + max(0, r - self.surface[c] + 1) * 8.0)  # height beats effort

        self.plan = self._search(score, 700)
        if not self.plan:
            self.fails += 1
            if self.fails > 4:
                return True  # build wherever we are
        return False

    def _house_ok(self, c: int, r: int) -> bool:
        if not (4 <= c < WW - 4) or r < 6:
            return False
        if self._top(c) < r or r >= self.surface[c]:  # under a roof or down a shaft: not open sky
            return False
        for dc in (-1, 0, 1):
            if self._wet(c + dc, r) or self._wet(c + dc, r + 1) or self._wet(c + dc, r - 1):
                return False
        return True

    def _make_blueprint(self) -> None:
        c, r = self.mc, self.mr
        bp: list[tuple[int, int, int]] = []
        for dc in (-1, 1):  # floor
            bp.append((c + dc, r + 1, PLANK))
        for dr in (0, 1, 2):  # interior air (dig out anything in the way)
            for dc in (-1, 0, 1):
                if not (dc == 0 and dr < 2):
                    bp.append((c + dc, r - dr, AIR))
        for dr in (0, 1, 2):  # walls, bottom-up, with a window in the right wall
            bp.append((c - 2, r - dr, PLANK))
            bp.append((c + 2, r - dr, GLASS if dr == 1 else PLANK))
        for dc in range(-3, 4):  # roof and ridge
            bp.append((c + dc, r - 3, ROOF))
        for dc in (-1, 0, 1):
            bp.append((c + dc, r - 4, ROOF))
        bp.append((c - 1, r - 1, TORCH))
        self.blueprint = bp
        self.house = (c, r)

    def _build_step(self) -> bool:
        """Do the next blueprint job; False when the house is finished."""
        while self.blueprint:
            c, r, want = self.blueprint[0]
            if not (0 <= c < WW and 0 <= r < WH):
                self.blueprint.pop(0)
                continue
            b = self.g[r][c]
            if want == AIR:
                self.blueprint.pop(0)
                if b in HARD:
                    self._start("dig", (c, r), HARD[b] * 0.8)
                    return True
                if b in (LEAF, WOOD):
                    self.g[r][c] = AIR
                continue
            if want == TORCH:
                self.blueprint.pop(0)
                if b in (AIR, LEAF, WOOD):
                    self.g[r][c] = TORCH
                continue
            self.blueprint.pop(0)
            if b in SOLID or self.inv <= 0:
                continue
            if b in (LEAF, WOOD):
                self.g[r][c] = AIR
            self._start("place", (c, r, want), PLACE_T)
            return True
        return False

    def _ai(self) -> None:
        c, r = self.mc, self.mr
        # fight anything touching us
        for m in self.mobs:
            if abs(int(m[0]) - c) == 1 and abs(int(m[1]) - r) <= 1:
                self.face = 1 if m[0] > c else -1
                self._start("hit", (int(m[0]), int(m[1])), 0.28 + (1 - self.skill) * 0.3)
                return
        tod = self.tod
        if self.mode == "sleep":
            if DAWN - 1 < tod < DUSK - 0.1 and tod > 0.02:
                self.mode = "work"
                self.plan = []
                self.explore = (min(WW - 3, max(2, c + self.rng.choice((-12, 12)))), self.surface[c] + 8)
            return
        depth = max(0, r - self.surface[c])
        if self.mode == "work" and DUSK - 0.06 - 0.006 * depth <= tod < DAWN:  # deep: leave early
            self.mode = "home"
            self.plan = []
            self.fails = 0
        if self.mode == "home":
            if not self.plan and self._plan_home():
                self.mode = "build"
                self._make_blueprint()
                return
            if not self.plan:
                return
        if self.mode == "build":
            if not self._build_step():
                self.mode = "sleep"
            return
        if self.mode == "work":
            ore = self._ore_near(c, r)
            if ore is not None:
                self.face = 1 if ore[0] > c else -1 if ore[0] < c else self.face
                self._try_dig(*ore)
                self.plan = []
                return
            if not self.plan:
                self._plan_work()
                if not self.plan:
                    return
        self._exec_step()

    def _exec_step(self) -> None:
        kind, dc, _tc, _tr = self.plan[0]
        c, r = self.mc, self.mr
        if kind == "side":
            for cc, rr in ((c + dc, r - 1), (c + dc, r)):
                if self._solid(cc, rr):
                    if not self._try_dig(cc, rr):
                        self.plan = []
                    return
            self.plan.pop(0)
            self._try_move(dc, 0)
        elif kind == "up":
            for cc, rr in ((c, r - 2), (c + dc, r - 2), (c + dc, r - 1)):
                if self._solid(cc, rr):
                    if not self._try_dig(cc, rr):
                        self.plan = []
                    return
            self.plan.pop(0)
            if not self._try_move(dc, -1):
                self.plan = []
        elif kind == "down":
            self.plan.pop(0)
            if self._solid(c, r + 1) and not self._try_dig(c, r + 1):
                self.plan = []
        elif kind == "pillar":
            if self._solid(c, r - 2):
                if not self._try_dig(c, r - 2):
                    self.plan = []
                return
            self.plan.pop(0)
            if self.inv > 0:
                self._start("pillar", (DIRT,), CLIMB_T)
            else:
                self.plan = []

    # ------------------------------------------------------------------ mobs
    def _update_mobs(self, dt: float) -> None:
        """Night creatures hunt the nearest standing miner. Works on the saved miner states (self.miners)."""
        night = NIGHT <= self.tod < DAWN
        if not night:
            for m in self.mobs:
                self.fx.burst(
                    self.rng, (m[0] - self.cam_c) * 2 + 1, (m[1] - self.cam_r) * 2, (255, 140, 40), 6, 6
                )
            self.mobs.clear()
            return
        if not self.settings.creatures:
            return
        alive = [(s, mm) for s, mm in self.miners.items() if mm["down_t"] <= 0 and mm["hearts"] > 0]
        if not alive:
            return
        self.spawn_t -= dt
        if self.spawn_t <= 0 and len(self.mobs) < 2 + len(self.miners):
            self.spawn_t = self.rng.uniform(3.0, 6.0)
            side = self.rng.choice((-1, 1))
            tm = alive[0][1] if len(alive) == 1 else self.rng.choice(alive)[1]
            c = tm["mc"] + side * self.rng.randrange(6, 8)
            if 1 <= c < WW - 1 and tm["mr"] <= self.surface[tm["mc"]] + 3:
                r = self._top(c) - 1
                if not self._wet(c, r + 1) and r > 2:
                    self.mobs.append([float(c), float(r), 2.0, 0.6, 0.0, 0.0, 0.0])
        for m in self.mobs:
            c, r = int(m[0]), int(m[1])
            m[6] = max(0.0, m[6] - dt)
            m[3] -= dt
            if m[3] > 0:
                continue
            m[3] = 0.55
            if not self._solid(c, r + 1):
                m[1] += 1
                m[4], m[5], m[6] = 0.0, -1.0, 0.2
                continue
            tm = min((mm for _s, mm in alive), key=lambda mm: abs(mm["mc"] - c) + abs(mm["mr"] - r))
            mc, mr = tm["mc"], tm["mr"]
            d = 1 if mc > c else -1 if mc < c else 0
            if d == 0 or (abs(mc - c) == 1 and abs(mr - r) <= 1):
                continue
            if self._clear(c + d, r) and self._clear(c + d, r - 1) and not self._mob_at(c + d, r):
                m[0] += d
                m[4], m[5], m[6] = -d, 0.0, 0.3
            elif (
                self._clear(c + d, r - 1)
                and self._clear(c + d, r - 2)
                and self._clear(c, r - 2)
                and not self._mob_at(c + d, r - 1)
            ):
                m[0] += d
                m[1] -= 1
                m[4], m[5], m[6] = -d, 1.0, 0.3
        # contact damage
        for seat, mm in alive:
            mm["hurt"] = max(0.0, mm["hurt"] - dt)
            mc, mr = mm["mc"], mm["mr"]
            for m in self.mobs:
                if abs(int(m[0]) - mc) <= 1 and abs(int(m[1]) - mr) <= 1 and mm["hurt"] <= 0:
                    between_ok = int(m[0]) == mc or self._clear((int(m[0]) + mc) // 2 + 0, mr)
                    if between_ok:
                        mm["hearts"] -= 1
                        mm["hurt"] = 1.2
                        self.fx.burst(
                            self.rng,
                            (mc - self.cam_c) * 2 + 1,
                            (mr - self.cam_r) * 2,
                            (255, 40, 40),
                            6,
                            8,
                        )
                        if self._controlled(seat):
                            self.damage()  # the red fade: a person got hit (never the demo AI)
                        if mm["hearts"] <= 0:
                            self._knocked_out(seat, mm)
                        break
            if self.over:
                return

    def _knocked_out(self, seat: int, mm: dict[str, Any]) -> None:
        if not self.multi:
            self.game_over()
            return
        mm["task"], mm["plan"], mm["anim"] = None, [], (0.0, 0.0)
        self.fx.burst(
            self.rng, (mm["mc"] - self.cam_c) * 2 + 1, (mm["mr"] - self.cam_r) * 2, WHITE, 10, 9, 0.7
        )
        if self.play_mode.id == "rush":
            mm["down_t"] = 4.0  # back on the surface in a moment, minus a quarter of the ore
            return
        mm["down_t"] = 1.0  # co-op: lies there until a partner touches them (or dawn)
        if all(m["down_t"] > 0 for m in self.miners.values()):
            self.result(scores={s: int(m["pts"]) for s, m in self.miners.items()}, text="ALL DOWN")

    def _revive_partners(self) -> None:
        """Co-op: a standing miner next to a knocked-out partner gets them back up with one heart."""
        for seat, mm in self.miners.items():
            if mm["down_t"] <= 0:
                continue
            for s2, other in self.miners.items():
                near = abs(other["mc"] - mm["mc"]) <= 1 and abs(other["mr"] - mm["mr"]) <= 1
                if s2 != seat and other["down_t"] <= 0 and near:
                    mm["down_t"], mm["hearts"], mm["hurt"] = 0.0, 1, 1.2
                    x, y = (mm["mc"] - self.cam_c) * 2 + 1, (mm["mr"] - self.cam_r) * 2
                    self.fx.burst(self.rng, x, y, (120, 255, 150), 10, 8, 0.6)
                    break

    def _respawn(self) -> None:
        """Ore Rush: the loaded miner climbs out on top of its column with full hearts."""
        self.mr = self._top(self.mc) - 1
        while self._wet(self.mc, self.mr + 1) and self.mc < WW - 5:
            self.mc += 1
            self.mr = self._top(self.mc) - 1
        self.hearts = int(self.settings.hearts)
        self.pts -= self.pts // 4
        self.down_t = 0.0
        self.hurt = 1.2
        self.mode, self.plan, self.task, self.explore = "work", [], None, None
        self._reveal(self.mc, self.mr, 4)
        self._camera()

    def _match_end(self) -> None:
        scores = {s: int(m["pts"]) for s, m in self.miners.items()}
        if self.play_mode.id == "rush":
            self.result(winner_seat=max(scores, key=lambda s: scores[s]), scores=scores)
        else:
            self.result(scores=scores, text=f"{self.score} ORE")

    # ------------------------------------------------------------------ loop
    def update(self, dt: float) -> None:
        length = float(self.settings.day_length)
        self.tod += dt / length
        self._save(self._seat)
        if self.tod >= 1.0:
            self.tod -= 1.0
            self.day += 1
            top = int(self.settings.hearts)
            for mm in self.miners.values():
                if mm["down_t"] > 0 and self.play_mode.id == "coop":
                    mm["down_t"], mm["hearts"] = 0.0, 1  # dawn gets everyone back up
                else:
                    mm["hearts"] = min(top, mm["hearts"] + 1)
            self._load(self._seat)
            if self.multi:
                if self.day >= int(self.settings.match_days):
                    self._match_end()
                    return
            elif self.day >= 3 and not self.human:
                self.game_over()  # a fresh world every few days in demo mode
                return
        self.last_score_t += dt
        self._update_mobs(dt)
        if self.multi and self.play_mode.id == "coop":
            self._revive_partners()
        if self.over:
            self._load(self._seat)
            return
        for seat in self.seat_order:
            self._load(seat)
            self._miner_step(dt)
            self._save(seat)
        self._load(self.seat_order[0])

    def _miner_step(self, dt: float) -> None:
        """Advance the loaded miner: its current action, gravity, then the human's keys or the AI."""
        if self.down_t > 0:
            if self.play_mode.id == "rush":
                self.down_t -= dt
                if self.down_t <= 0:
                    self._respawn()
            return
        self.swing = max(0.0, self.swing - dt)
        if self.task is not None:
            self.task[2] -= dt
            kind, args, t_left, total = self.task
            if kind == "move":
                k = 1 - max(0.0, t_left) / total
                self.anim = (args[0] * 2 * k, args[1] * 2 * k)
            elif kind in ("dig", "hit"):
                self.swing = 0.1
                self.swing_at = (args[0], args[1])
            elif kind == "pillar":
                k = 1 - max(0.0, t_left) / total
                self.anim = (0.0, -2 * k)
            if self.task[2] <= 0:
                self._finish()
                self._camera()
            return
        human = self._controlled()
        # gravity (water: sink slowly); a jump hangs for a moment so a sideways press can land on a ledge
        if not self._supported(self.mc, self.mr):
            if self.jump_hang > 0:
                self.jump_hang = max(0.0, self.jump_hang - dt)
                if human and self.pending in ("left", "right"):
                    self._human()
                return
            self._start("move", (0, 1), FALL_T * (2.5 if self._wet(self.mc, self.mr + 1) else 1.0))
            return
        self.jump_hang = 0.0
        if human:
            self._human()
            return
        self._ai()
        if self.task is None:
            self.idle += dt
            if self.idle > 1.5:  # stuck: forget the plan and pick somewhere else
                self.idle = 0.0
                self.plan = []
                self.explore = None
        else:
            self.idle = 0.0

    def _camera(self) -> None:
        if self._seat != self.seat_order[0]:
            return  # the camera follows seat 1 (the host)
        c, r = self.mc, self.mr
        if c - self.cam_c < 3:
            self.cam_c -= 8
        elif c - self.cam_c > VW - 4:
            self.cam_c += 8
        if r - self.cam_r > VW - 3:
            self.cam_r += 8
        elif r - 1 - self.cam_r < 2:
            self.cam_r -= 8
        self.cam_c = max(0, min(WW - VW, self.cam_c))
        self.cam_r = max(0, min(WH - VW, self.cam_r))

    # ------------------------------------------------------------------ draw
    @property
    def theme_id(self) -> str:
        return str(self.sel.get("theme", self.settings.theme))

    def _look(self) -> dict[str, Any]:
        tid = self.theme_id
        if tid in ("classic", "overworld"):
            return LOOKS["overworld"]
        if tid in LOOKS:
            return LOOKS[tid]
        th = self.theme
        return {"sky": SKY, "cave": CAVE, "helmet": th.x, "shirt": th.p, "mob": scale(th.e, 0.7), "eye": th.e}

    @property
    def _lut(self) -> np.ndarray:
        if self._lut_theme != self.theme_id:
            self._lut_theme = self.theme_id
            self._lut_cache = _luts(self.theme_id)
        return self._lut_cache

    def _phase(self) -> str:
        t = self.tod
        if DUSK <= t < NIGHT:
            return "dusk"
        if NIGHT <= t < DAWN:
            return "night"
        return "day" if t >= 0.02 else "dusk"

    def draw(self, f: Frame, now: float) -> None:
        self._save(self._seat)
        look = self._look()
        cc, cr = self.cam_c, self.cam_r
        lut = self._lut
        view = np.array([self.g[r][cc : cc + VW] for r in range(cr, cr + VW)], dtype=np.uint8)
        seen = np.array([self.seen[r][cc : cc + VW] for r in range(cr, cr + VW)], dtype=bool)
        phase = self._phase()
        img = np.empty((32, 32, 3), dtype=np.uint8)
        img[0::2, 0::2] = lut[0][view]
        img[0::2, 1::2] = lut[1][view]
        img[1::2, 0::2] = lut[2][view]
        img[1::2, 1::2] = lut[3][view]
        air = (view == AIR) | (view == TORCH)
        surf = np.array(self.surface[cc : cc + VW])
        rows = np.arange(cr, cr + VW)[:, None]
        under = rows > surf[None, :]
        # sky vs cave backdrop; unexplored rock stays dark
        sky = air & ~under
        cave = air & under
        hidden = ~seen & ~air
        big = np.ones((2, 2), dtype=bool)
        img[np.kron(sky, big)] = look["sky"][phase]
        img[np.kron(cave, big)] = look["cave"]
        img[np.kron(hidden, big)] = DARK
        visible = [
            (s, m) for s, m in self.miners.items() if cc <= m["mc"] < cc + VW and cr <= m["mr"] < cr + VW + 1
        ]
        if phase != "day":
            k = 0.8 if phase == "dusk" else 0.5
            lit = np.kron(~(sky | cave | hidden), big)
            # every miner's lamp keeps a small circle at full brightness
            yy, xx = np.ogrid[:32, :32]
            near = np.zeros((32, 32), dtype=bool)
            for _s, m in visible:
                mx, my = (m["mc"] - cc) * 2 + 1, (m["mr"] - cr) * 2 - 1
                near |= (xx - mx) ** 2 + (yy - my) ** 2 <= 30
            dimmed = lit & ~near
            img[dimmed] = (img[dimmed].astype(np.uint16) * int(k * 256) >> 8).astype(np.uint8)
        f.px[:] = img
        # celestial: sun by day, moon + stars by night, drawn only onto open sky
        if phase == "night":
            for sx, sy in self.stars:
                if sky[sy // 2, sx // 2]:
                    f.set(sx, sy, (70, 70, 100))
        a = (self.tod - 0.0) / DUSK if self.tod < DUSK else (self.tod - NIGHT) / (DAWN - NIGHT)
        a = min(1.0, max(0.0, a))
        bx = round(2 + a * 26)
        by = round(8 - 6 * math.sin(math.pi * a))
        body = (255, 210, 60) if phase != "night" else (210, 210, 190)
        for dx in (0, 1):
            for dy in (0, 1):
                x, y = bx + dx, by + dy
                if sky[y // 2, x // 2]:
                    f.set(x, y, body)
        self._draw_details(f, view, cc, cr, now)
        self._draw_mobs(f, cc, cr, now, look)
        for _s, m in visible:
            self._lamp_glow(f, cave, cc, cr, m)
        seen_seats = {s for s, _m in visible}
        for s in reversed(self.seat_order):  # seat 1 on top
            m = self.miners[s]
            if s in seen_seats:
                self._draw_miner(f, s, m, cc, cr, now, look)
            else:
                self._pointer(f, s, m, cc, cr, now)
        self._draw_hud(f, now)

    def _draw_details(self, f: Frame, view: np.ndarray, cc: int, cr: int, now: float) -> None:
        # torches flicker; water gets a glinting surface row
        ys, xs = np.nonzero(view == TORCH)
        for y, x in zip(ys.tolist(), xs.tolist(), strict=True):
            f.set(x * 2, y * 2 + 1, (110, 70, 30))
            f.set(x * 2, y * 2, (255, 170, 40) if int(now * 6 + x) % 3 else (255, 230, 120))
        ys, xs = np.nonzero(view == WATER)
        for y, x in zip(ys.tolist(), xs.tolist(), strict=True):
            r = y + cr
            if r > 0 and self.g[r - 1][x + cc] == AIR:
                f.set(x * 2 + (int(now * 2 + x) % 2), y * 2, (60, 110, 220))

    def _lamp_glow(self, f: Frame, cave: np.ndarray, cc: int, cr: int, m: dict[str, Any]) -> None:
        """A warm pool of light around a miner in tunnels, so you can always find them on the panel."""
        ox, oy = m["anim"]
        mx, my = (m["mc"] - cc) * 2 + 1 + ox, (m["mr"] - 1 - cr) * 2 + 2 + oy
        for y in range(max(0, int(my) - 5), min(32, int(my) + 6)):
            for x in range(max(0, int(mx) - 5), min(32, int(mx) + 6)):
                d2 = (x - mx) ** 2 + (y - my) ** 2
                if d2 <= 25 and cave[y // 2, x // 2]:
                    f.blend(x, y, (255, 170, 80), 0.35 * (1 - d2 / 25))

    def _shirt(self, seat: int, look: dict[str, Any]) -> RGB:
        return self.colour_of(seat) if self.multi else look["shirt"]

    def _pointer(self, f: Frame, seat: int, m: dict[str, Any], cc: int, cr: int, now: float) -> None:
        """A partner or rival off screen: a blinking 2-px marker on the edge nearest them, in their colour."""
        if int(now * 3) % 3 == 0:
            return
        x = min(31, max(0, (m["mc"] - cc) * 2))
        y = min(31, max(0, (m["mr"] - 1 - cr) * 2))
        col = self._shirt(seat, self._look())
        f.set(x, y, col)
        if x in (0, 31):
            f.set(x, min(31, y + 1), col)
        else:
            f.set(min(31, x + 1), y, col)

    def _draw_miner(
        self, f: Frame, seat: int, m: dict[str, Any], cc: int, cr: int, now: float, look: dict[str, Any]
    ) -> None:
        if self.over and int(now * 4) % 2:
            return
        ox, oy = m["anim"]
        x = round((m["mc"] - cc) * 2 + ox)
        y = round((m["mr"] - 1 - cr) * 2 + oy)
        helmet = look["helmet"]
        skin = (240, 170, 120)
        shirt = self._shirt(seat, look)
        legs = (40, 50, 150)
        if m["down_t"] > 0:  # knocked out: lying on the floor, blinking so a partner can find them
            if int(now * 3) % 2:
                f.set(x - 1, y + 3, helmet)
                f.set(x, y + 3, skin)
                f.set(x + 1, y + 3, shirt)
                f.set(x + 2, y + 3, legs)
            return
        if m["hurt"] > 0.8 and int(now * 12) % 2:
            shirt = skin = (255, 60, 60)
        human = self._controlled(seat)
        sleeping = m["mode"] == "sleep" and not human
        f.set(x, y, helmet)
        f.set(x + 1, y, helmet)
        f.set(x, y + 1, skin)
        f.set(x + 1, y + 1, skin)
        f.set(x, y + 2, shirt)
        f.set(x + 1, y + 2, shirt)
        task = m["task"]
        walking = task is not None and task[0] == "move" and task[1][1] == 0
        step = walking and int(now * 8) % 2
        if step:
            f.set(x + (1 if m["face"] > 0 else 0), y + 3, legs)
        else:
            f.set(x, y + 3, legs)
            f.set(x + 1, y + 3, legs)
        # headlamp in the facing direction (brighter at night)
        if self._phase() != "day" or m["mr"] > self.surface[m["mc"]] + 1:
            f.set(x + (2 if m["face"] > 0 else -1), y, (255, 250, 170))
        # pickaxe swing at the target block
        if m["swing"] > 0:
            tc, tr = m["swing_at"]
            px = (tc - cc) * 2 + (0 if tc > m["mc"] else 1)
            py = (tr - cr) * 2 + (int(now * 10) % 2)
            f.set(px, py, (230, 230, 240))
        if sleeping and m["house"] is not None:
            z = int(now * 1.5) % 3
            f.set(x + 2 + z // 2, y - 1 - z, (140, 160, 255))

    def _draw_mobs(self, f: Frame, cc: int, cr: int, now: float, look: dict[str, Any]) -> None:
        body = look["mob"]
        eye = look["eye"]
        for m in self.mobs:
            k = m[6] / 0.3 if m[6] > 0 else 0.0
            x = round((m[0] - cc) * 2 + m[4] * 2 * k)
            y = round((m[1] - 1 - cr) * 2 + m[5] * 2 * k)
            f.rect(x, y, 2, 1, body)
            f.rect(x, y + 1, 2, 1, eye if int(now * 3 + m[0]) % 5 else body)
            f.rect(x, y + 2, 2, 1, body)
            if int(now * 5 + m[0]) % 2:
                f.set(x, y + 3, body)
            else:
                f.set(x + 1, y + 3, body)

    def _draw_hud(self, f: Frame, now: float) -> None:
        if not self.settings.show_score:
            return
        for i in range(int(self.settings.hearts)):
            c = (230, 30, 40) if i < self.hearts else (50, 10, 14)
            f.rect(1 + i * 3, 1, 2, 2, c)
        if self._controlled():
            # mode chip: pickaxe (grey) or a plank block, plus blocks carried
            if self.build_mode:
                f.rect(1, 4, 2, 2, (170, 110, 50))
            else:
                f.set(1, 4, (200, 200, 210))
                f.set(2, 5, (120, 80, 40))
        col = WHITE if self.flash else tint(self.theme.hud, 0.0)
        if self.multi and self.play_mode.id == "rush":
            col = WHITE if self.flash else self.colour_of(self._seat)
        self.hud(f, str(self.score), color=col)

    def status(self) -> dict[str, Any]:
        st = super().status()
        st.update({"day": self.day + 1, "time": self._phase(), "blocks": self.inv, "hearts": self.hearts})
        # "mode" stays Dig World's own (dig/build for a person, the AI's work/home/build/sleep); the menu's mode
        # is reported as play_mode
        st["play_mode"] = self.play_mode.id
        st["mode"] = ("build" if self.build_mode else "dig") if self._controlled() else self.mode
        if self.multi:
            st["ore"] = {s: int(m["pts"]) for s, m in self.miners.items()}
        return st
