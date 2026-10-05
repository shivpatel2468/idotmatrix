"""Penguin Escape — a sliding-ice puzzle: waddle a penguin out of the zoo, one single-screen level at a time.

Original game, levels and pixel art. The rules, the levels and the BFS solver live in `_penguin.py`; this module
draws them on the 32 × 32 panel and plays them.

Layout: a 4-row HUD (three fish pips, the key you carry, sixteen level dots) over an 8 × 7 board of 4 × 4 px tiles.
Moves are turn-based: the keepers take one step per move of yours, so every level is a deterministic puzzle.

Keys: arrows waddle (and slide on ice), A undoes the last move (also after a splash or getting caught), B restarts
the level and opens the level card, where ←/→ pick any level you've reached and A starts it.

The demo AI plays the stored shortest 3-star solution of each level (found by the solver; the tests re-solve every
level), and when it takes over from a person mid-level it re-plans with a time-sliced BFS from where the penguin
stands — or restarts the level if the puzzle has been painted into a corner.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, Sprite, scale
from . import _kit
from ._penguin import COLS, DIRS, DOOR, EXIT, ICE, LEVELS, WALL, WATER, Puzzle, Result, State, puzzle
from ._penguin import solve_iter as _solve_iter
from .games_core import WHITE, GameApp, GameSettings, Theme

_LETTER = {"u": "up", "d": "down", "l": "left", "r": "right"}
TILE = 4
OY = 4  # board top (rows 0..3 are the HUD)
N_LEVELS = len(LEVELS)
WALK_T, SLIDE_T, PUSH_T = 0.2, 0.075, 0.07
CARD_AI = 1.4  # seconds the level card shows while the AI plays
BFS_CHUNK = 40  # solver expansions per sim step when re-planning (keeps every render well under 2 ms)
BFS_BUDGET = 300  # chunks before the AI gives up re-planning and restarts the level


# ----------------------------------------------------------------------------- looks
class Look:
    """Tile colours for one theme. Dark tones stay above ~45 per channel (the panel's gamma crushes them)."""

    def __init__(self, **kw: RGB) -> None:
        self.__dict__.update(kw)

    snow: RGB
    snow2: RGB
    ice: RGB
    glint: RGB
    water: RGB
    ripple: RGB
    wall: RGB
    wall2: RGB
    block: RGB
    block2: RGB
    beam: RGB
    hud: RGB
    sky: RGB


LOOKS: dict[str, Look] = {
    "ice": Look(
        snow=(128, 138, 165),
        snow2=(104, 114, 146),
        ice=(30, 112, 215),
        glint=(160, 215, 255),
        water=(6, 26, 112),
        ripple=(40, 90, 200),
        wall=(78, 66, 104),
        wall2=(112, 98, 146),
        block=(170, 238, 255),
        block2=(70, 150, 205),
        beam=(255, 222, 90),
        hud=(10, 14, 30),
        sky=(0, 0, 0),
    ),
    "night": Look(
        snow=(76, 84, 128),
        snow2=(60, 66, 108),
        ice=(26, 72, 176),
        glint=(120, 170, 255),
        water=(4, 12, 64),
        ripple=(30, 60, 150),
        wall=(56, 48, 84),
        wall2=(86, 74, 120),
        block=(130, 205, 255),
        block2=(50, 110, 180),
        beam=(255, 236, 140),
        hud=(4, 4, 16),
        sky=(0, 0, 0),
    ),
    "aurora": Look(
        snow=(116, 146, 156),
        snow2=(92, 122, 136),
        ice=(0, 140, 168),
        glint=(130, 255, 220),
        water=(8, 24, 90),
        ripple=(60, 80, 200),
        wall=(84, 54, 120),
        wall2=(124, 84, 168),
        block=(170, 255, 236),
        block2=(60, 170, 170),
        beam=(255, 210, 110),
        hud=(6, 10, 22),
        sky=(0, 0, 0),
    ),
}
LOOK_LABELS = {"ice": "Ice", "night": "Night", "aurora": "Aurora"}

FISH: RGB = (255, 200, 0)
FISH_DIM: RGB = (70, 60, 40)
KEY: RGB = (255, 70, 200)
GATE: RGB = (0, 235, 120)
BODY: RGB = (12, 12, 26)
BELLY: RGB = (235, 242, 255)
BEAK: RGB = (255, 130, 0)
STAR: RGB = (255, 214, 0)


def _theme(look: Look) -> Theme:
    return Theme(
        p=BELLY,
        e=(60, 190, 80),
        x=FISH,
        w=look.wall2,
        hud=(200, 225, 255),
        bg=look.hud,
        r=(look.ice, look.snow, look.block, FISH, KEY, GATE, look.water),
    )


# ----------------------------------------------------------------------------- sprites (4 × 4, original)
_PAL = {"K": BODY, "W": BELLY, "O": BEAK}
_FRAMES: dict[str, tuple[str, ...]] = {
    "down0": (".KK.", "KWOK", "KWWK", "O..O"),
    "down1": (".KK.", "KWOK", "KWWK", ".OO."),
    "up0": (".KK.", "KKKK", "KKKK", "O..O"),
    "up1": (".KK.", "KKKK", "KKKK", ".OO."),
    "right0": (".KK.", "KKWO", "KWW.", ".O.."),
    "right1": (".KK.", "KKWO", "KWW.", "..O."),
    "slide_right": ("....", "KKKO", "WWW.", "O..."),
    "slide_down": ("O...", ".KW.", ".KW.", "..O."),
    "slide_up": ("..O.", ".KW.", ".KW.", "O..."),
    "cheer": ("K..K", "KWOK", "KWWK", ".OO."),
}


def _sprites() -> dict[str, Sprite]:
    out = {k: Sprite.parse(v, _PAL) for k, v in _FRAMES.items()}
    for k in ("right0", "right1", "slide_right"):
        out[k.replace("right", "left")] = out[k].flipped()
    return out


SPRITES = _sprites()
KEEPER = {
    "0": Sprite.parse(
        ("HHHH", ".SS.", "GGGG", ".N.N"),
        {"H": (196, 156, 60), "S": (255, 176, 120), "G": (40, 170, 70), "N": (50, 70, 160)},
    ),
    "1": Sprite.parse(
        ("HHHH", ".SS.", "GGGG", "N.N."),
        {"H": (196, 156, 60), "S": (255, 176, 120), "G": (40, 170, 70), "N": (50, 70, 160)},
    ),
}
FISH_TAIL: RGB = (255, 120, 0)
FISH_SPR = Sprite.parse(("....", ".##T", "###.", ".##T"), {"#": FISH, "T": FISH_TAIL})
KEY_SPR = Sprite.parse(("....", ".#..", "#.##", ".#.#"), {"#": KEY})
HUD_FISH = Sprite.parse((".##T", "###.", ".##T"), {"#": FISH, "T": FISH_TAIL})
HUD_FISH_OFF = Sprite.parse((".##T", "###.", ".##T"), {"#": FISH_DIM, "T": FISH_DIM})
HUD_KEY = Sprite.parse(("##.", "#.#", "##."), {"#": KEY})


def _star(f: Frame, x: int, y: int, c: RGB) -> None:
    """A 5 × 5 star."""
    f.set(x + 2, y, c)
    f.hline(x, y + 1, 5, c)
    f.hline(x + 1, y + 2, 3, c)
    f.set(x + 1, y + 3, c)
    f.set(x + 3, y + 3, c)
    f.set(x, y + 4, c)
    f.set(x + 4, y + 4, c)


def _xy(i: int) -> tuple[int, int]:
    """Top-left panel pixel of tile `i`."""
    return (i % COLS) * TILE, OY + (i // COLS) * TILE


class PenguinSettings(GameSettings):
    start_level: int = Field(
        1,
        ge=1,
        le=N_LEVELS,
        title="Starting level",
        description="Where the demo starts, and the lowest level you can always pick",
        json_schema_extra={"group": "Game"},
    )


@register
class PenguinEscape(GameApp):
    id = "penguin"
    name = "Penguin Escape"
    description = (
        "A sliding-ice puzzle: guide a penguin out of the zoo through 16 levels. Ice slides you until something "
        "stops you; shove ice blocks (into water to bridge it), grab keys for doors and three fish for stars, and "
        "stay out of the keepers' torch beams. Arrows move, A undoes, B restarts / picks a level."
    )
    icon = "snowflake"
    Settings = PenguinSettings
    step_hz = 30.0
    over_hold = 2.5
    controls = ("dpad", "swipe", "gamepad", "joystick")
    game_themes: ClassVar[dict[str, Theme]] = {k: _theme(v) for k, v in LOOKS.items()}
    game_theme_labels: ClassVar[dict[str, str]] = LOOK_LABELS

    # ------------------------------------------------------------------ setup
    def new_game(self) -> None:
        self.stars_best: dict[str, int] = {}
        self.reached = 0
        try:
            raw = self.ctx.data.get("stars") or {}
            self.stars_best = {str(k): int(v) for k, v in dict(raw).items()}
            self.reached = int(self.ctx.data.get("reached", 0))
        except Exception:
            self.stars_best, self.reached = {}, 0
        lo = int(self.settings.start_level) - 1
        first = max(lo, min(self.reached, N_LEVELS - 1)) if self.flow == "play" else lo
        self.cleared_run = 0
        self.load(first)

    def load(self, n: int) -> None:
        """Start level `n` (0-based) with its level card."""
        self.level = max(0, min(N_LEVELS - 1, n))
        self.pz: Puzzle = puzzle(self.level)
        self.state: State = self.pz.start
        self.prev: State = self.state
        self.history: list[State] = []
        self.face = "down"
        self.anim: Result | None = None
        self.anim_t = 0.0
        self.anim_len = 0.0
        self.end: str | None = None  # "win" | "fall" | "caught" once the move animation finishes
        self.end_t = 0.0
        self.card = "level"  # "level" | "clear" | "fail" | "escaped" | None
        self.card_t = 0.0
        self.queued: str | None = None
        self.human_moved = False
        self.ai_moved = False
        self.ai_t = 0.0
        self.ai_oops = False
        self.plan: list[str] = list(self._demo())
        self.plan_from: State | None = self.state
        self.solver: Any = None
        self.solver_n = 0

    def _demo(self) -> list[str]:
        return [_LETTER[c] for c in LEVELS[self.level].demo]

    @property
    def look(self) -> Look:
        return LOOKS.get(str(self.sel.get("theme", self.settings.theme)), LOOKS["ice"])

    def allowed_max(self) -> int:
        return max(int(self.settings.start_level) - 1, min(self.reached, N_LEVELS - 1))

    # ------------------------------------------------------------------ input
    def fly_key(self, k: str) -> str | None:
        return k if k in DIRS else None  # the fly only walks; undo / restart stay with people

    def key(self, k: str) -> None:
        if self.card is None and not self._fly_driving(self._clock()):
            self.human_moved = True
        if self.card == "level":
            if k in ("left", "right"):
                lim = self.allowed_max()
                n = self.level + (1 if k == "right" else -1)
                if 0 <= n <= lim:
                    self.load(n)
                self.card_t = 0.0
            elif k != "b":
                self.card = None
            return
        if self.card in ("clear", "escaped"):
            if self.card_t > 0.5:
                self._next_level()
            return
        if self.card == "fail":
            if k == "a":
                self.undo()
            elif k == "b" or self.card_t > 0.4:
                self.load(self.level)
            return
        if k == "b":
            self.load(self.level)
            return
        if k == "a":
            self.undo()
            return
        if k in DIRS:
            if self.anim is not None or self.end is not None:
                self.queued = k
            else:
                self.move(k)

    def undo(self, keep_plan: bool = False) -> None:
        if not self.history:
            return
        self.state = self.prev = self.history.pop()
        self.anim, self.end, self.card, self.queued = None, None, None, None
        if not keep_plan:
            self.plan, self.plan_from, self.solver = [], None, None

    def move(self, d: str) -> bool:
        """Play one move; False when nothing happened (a bump)."""
        r = self.pz.step(self.state, d)
        self.face = d
        if r.outcome == "bump":
            return False
        self.history.append(self.state)
        del self.history[:-300]
        self.prev, self.state = self.state, r.state
        self.anim = r
        steps = max(1, len(r.path) - 1)
        self.anim_len = (
            WALK_T + SLIDE_T * (steps - 1) if r.outcome != "push" else WALK_T + PUSH_T * len(r.block)
        )
        self.anim_t = 0.0
        got = self.pz.stars(r.state) - self.pz.stars(self.prev)
        if got > 0:
            x, y = _xy(r.path[-1])
            self.fx.burst(self.rng, x + 2, y + 2, FISH, 6, 9, 0.45)
        if r.sank and r.block:
            x, y = _xy(r.block[-1])
            self.fx.burst(self.rng, x + 2, y + 2, self.look.glint, 8, 10, 0.5)
        if r.outcome in ("win", "fall", "caught"):
            self.end = r.outcome
        return True

    # ------------------------------------------------------------------ simulation
    def update(self, dt: float) -> None:
        if self.card is not None:
            self.card_t += dt
            if self.card == "level" and ((not self.human and self.card_t > CARD_AI) or self.card_t > 6.0):
                self.card = None
            elif self.card in ("clear", "escaped") and self.card_t > (2.0 if not self.human else 6.0):
                self._next_level()
            elif self.card == "fail" and self.card_t > (1.2 if not self.human else 4.0):
                self.load(self.level)
            return
        if self.anim is not None:
            self.anim_t += dt
            if self.anim_t >= self.anim_len:
                self.anim = None
                self.end_t = 0.0
            return
        if self.end is not None:
            self.end_t += dt
            if self.end_t > (0.9 if self.end == "win" else 0.7):
                self._finish(self.end)
            return
        if self.queued:
            k, self.queued = self.queued, None
            self.move(k)
            return
        if not self.human:
            self._ai(dt)

    def _finish(self, outcome: str) -> None:
        self.end = None
        if outcome != "win":
            self.card, self.card_t = "fail", 0.0
            if self.human_moved and not self.ai_moved:
                self.damage(0.6)
            return
        stars = self.pz.stars(self.state)
        self.score += stars
        self.cleared_run += 1
        if self.human_moved and not self.ai_moved:  # only people's escapes count towards progress
            key = str(self.level + 1)
            if stars > self.stars_best.get(key, -1):
                self.stars_best[key] = stars
            self.reached = max(self.reached, min(N_LEVELS - 1, self.level + 1))
            try:
                self.ctx.data["stars"] = dict(self.stars_best)
                self.ctx.data["reached"] = self.reached
                self.ctx.save()
            except Exception:
                pass
        self.card, self.card_t = ("escaped" if self.level == N_LEVELS - 1 else "clear"), 0.0
        self.flash = 0.3

    def _next_level(self) -> None:
        if self.level == N_LEVELS - 1:
            if self.flow == "play" and self.card == "escaped":
                self.result(text="ESCAPED")
                return
            self.load(int(self.settings.start_level) - 1 if not self.human else 0)
            return
        self.load(self.level + 1)

    def _ai(self, dt: float) -> None:
        self.ai_t -= dt
        if self.ai_t > 0:
            return
        if self.ai_oops:  # take back the deliberate slip
            self.ai_oops = False
            self.undo(keep_plan=True)
            self.ai_t = 0.35
            return
        if not self.plan or self.plan_from != self.state:
            self._replan()
            return
        d = self.plan[0]
        self.ai_moved = True
        if self.rng.random() < (1.0 - self.skill) * 0.25:  # a slip: a harmless wrong move, then undo
            wrong = [x for x in DIRS if x != d and self.pz.step(self.state, x).outcome in ("move", "push")]
            if wrong:
                self.move(self.rng.choice(wrong))
                self.ai_oops = True
                self.ai_t = 0.45
                return
        self.plan.pop(0)
        self.move(d)
        self.plan_from = self.state
        self.ai_t = 0.3

    def _replan(self) -> None:
        """Plan from wherever the penguin stands: the stored solution at the start, otherwise (a person played
        before) a time-sliced BFS; a puzzle that can't be won any more starts over."""
        if self.state == self.pz.start:
            self.plan, self.plan_from, self.solver = self._demo(), self.state, None
            return
        if self.solver is None:
            self.solver = _solve_iter(self.pz, self.state, all_fish=False, chunk=BFS_CHUNK)
            self.solver_n = 0
        plan = next(self.solver, [])
        self.solver_n += 1
        if plan is None and self.solver_n <= BFS_BUDGET:
            return
        self.solver = None
        if plan:
            self.plan, self.plan_from = list(plan), self.state
        else:
            self.load(self.level)  # stuck (or too far to think): start the level again
            self.card = None

    # ------------------------------------------------------------------ the fruit-fly pilot
    def _penguin_px(self) -> tuple[float, float]:
        x, y = _xy(self.state[0])
        if self.anim is not None and self.anim.path:
            x, y = self._along(self.anim.path, self._anim_k())
        return x + 2.0, y + 2.0

    def pilot_anchor(self) -> tuple[float, float] | None:
        return self._penguin_px()

    def fly_lure(self) -> list[tuple[float, float, float]]:
        """The next move of the solution (smelled one tile that way), and the exit gate."""
        px, py = self._penguin_px()
        out: list[tuple[float, float, float]] = []
        if self.plan and self.plan_from == self.state:
            dx, dy = DIRS[self.plan[0]]
            out.append((px + dx * 6, py + dy * 6, 1.0))
        ex, ey = _xy(self.pz.exit)
        out.append((ex + 2.0, ey + 2.0, 0.4))
        return out

    # ------------------------------------------------------------------ drawing
    def _anim_k(self) -> float:
        if self.anim is None or self.anim_len <= 0:
            return 1.0
        return min(1.0, self.anim_t / self.anim_len)

    @staticmethod
    def _along(path: tuple[int, ...], k: float) -> tuple[float, float]:
        """Pixel position along a tile path at progress k (the first step walks, the rest slide evenly)."""
        if len(path) < 2:
            x, y = _xy(path[0])
            return float(x), float(y)
        seg = (len(path) - 1) * k
        i = min(len(path) - 2, int(seg))
        u = seg - i
        ax, ay = _xy(path[i])
        bx, by = _xy(path[i + 1])
        return ax + (bx - ax) * u, ay + (by - ay) * u

    def _floor(self, look: Look) -> np.ndarray:
        """The static board (floor, walls, doors, filled holes) for the current state, cached."""
        st = self.state
        key = (self.level, st[3], st[5], id(look))
        cache = getattr(self, "_floor_cache", None)
        if cache is not None and cache[0] == key:
            return cache[1]
        fr = Frame()
        pz = self.pz
        for i, fl in enumerate(pz.floor):
            x, y = _xy(i)
            if fl == WALL:
                fr.rect(x, y, TILE, TILE, look.wall)
                fr.hline(x, y, TILE, look.wall2)
                fr.set(x + 1 + (i % 2), y + 2, look.wall2)
            elif fl == ICE:
                fr.rect(x, y, TILE, TILE, look.ice)
            elif fl == WATER:
                if st[5] >> pz.water_idx[i] & 1:
                    fr.rect(x, y, TILE, TILE, scale(look.block, 0.75))  # a sunk block: slush
                    fr.set(x + 1, y + 1, look.block)
                else:
                    fr.rect(x, y, TILE, TILE, look.water)
            elif fl == DOOR:
                fr.rect(x, y, TILE, TILE, look.snow)
                if not st[3] >> pz.door_idx[i] & 1:
                    fr.rect(x, y, TILE, TILE, scale(KEY, 0.35))
                    fr.vline(x, y, TILE, KEY)
                    fr.vline(x + 2, y, TILE, KEY)
                    fr.hline(x, y, TILE, KEY)
            elif fl == EXIT:
                fr.rect(x, y, TILE, TILE, look.snow)
            else:  # snow (with a speckle so it reads as a different surface from ice)
                fr.rect(x, y, TILE, TILE, look.snow)
                if (i * 7) % 3 == 0:
                    fr.set(x + (i % 3), y + 1 + (i % 2) * 2, look.snow2)
        arr = fr.px[OY:].copy()
        self._floor_cache = (key, arr)
        return arr

    def draw(self, f: Frame, now: float) -> None:
        look = self.look
        if self.card in ("level", "clear", "escaped"):
            self._draw_card(f, now, look)
            return
        f.clear(look.sky)
        f.px[OY:] = self._floor(look)
        pz, st = self.pz, self.state
        k = self._anim_k()
        # water ripples and ice glints (slow, few pixels)
        ph = int(now * 3)
        for n, i in enumerate(pz.water):
            if not st[5] >> n & 1:
                x, y = _xy(i)
                f.set(x + (ph + n) % 3, y + 1 + (n + ph // 3) % 2, look.ripple)
        for i, fl in enumerate(pz.floor):
            if fl == ICE and (i * 5 + ph // 2) % 9 == 0:
                x, y = _xy(i)
                f.set(x + 1, y + 1, look.glint)
                f.set(x + 2, y + 2, scale(look.glint, 0.6))
        # exit gate: a pulsing green arch
        ex, ey = _xy(pz.exit)
        g = scale(GATE, 0.65 + 0.35 * math.sin(now * 5))
        f.vline(ex, ey, TILE, g)
        f.vline(ex + 3, ey, TILE, g)
        f.hline(ex, ey, TILE, g)
        f.rect(ex + 1, ey + 1, 2, 3, scale(GATE, 0.25))
        # items
        for n, i in enumerate(pz.fish):
            if not st[1] >> n & 1:
                x, y = _xy(i)
                f.sprite(FISH_SPR, x, y - (1 if int(now * 2 + n) % 4 == 0 else 0))
        for n, i in enumerate(pz.keys):
            if not st[2] >> n & 1:
                x, y = _xy(i)
                f.sprite(KEY_SPR, x, y)
        # blocks (the shoved one glides along its trail)
        moving = self.anim.block if self.anim is not None and self.anim.block else ()
        for i in st[4]:
            if moving and i == moving[-1]:
                continue
            self._block(f, *_xy(i), look)
        if moving:
            kb = min(1.0, max(0.0, (self.anim_t - WALK_T * 0.5) / max(0.01, self.anim_len - WALK_T * 0.5)))
            bx, by = self._along(moving, kb)
            if not (self.anim is not None and self.anim.sank and kb >= 1.0):
                self._block(f, round(bx), round(by), look)
        # keepers: beams first, then bodies (gliding from their previous tile)
        if pz.timeline:
            caught_by = self.anim.caught_by if self.anim is not None else -1
            beam_on = self.anim is None or k >= 1.0
            if beam_on:
                for n, seen in enumerate(pz.sight(st[6], st[3], st[4])):
                    a = 0.55 if n == caught_by or self.end == "caught" else 0.32
                    for j in seen[1:]:
                        x, y = _xy(j)
                        sub = f.px[y : y + TILE, x : x + TILE].astype(np.float32)
                        f.px[y : y + TILE, x : x + TILE] = (sub + (np.array(look.beam) - sub) * a).astype(
                            np.uint8
                        )
            before = pz.keepers(self.prev[6])
            for n, (pos, _face) in enumerate(pz.keepers(st[6])):
                ax, ay = _xy(before[n][0])
                bx, by = _xy(pos)
                kk = k if self.anim is not None else 1.0
                x, y = round(ax + (bx - ax) * kk), round(ay + (by - ay) * kk)
                f.sprite(KEEPER[str((pos + int(now * 4)) % 2) if kk < 1.0 else "0"], x, y)
                if self.end == "caught" and (caught_by < 0 or caught_by == n) and int(now * 6) % 2:
                    f.vline(x + 1, y - 4, 2, (255, 40, 40))
                    f.set(x + 1, y - 1, (255, 40, 40))
        self._draw_penguin(f, now, look)
        self._hud(f, now, look)
        if self.card == "fail":
            self._draw_fail(f, now)

    def _block(self, f: Frame, x: int, y: int, look: Look) -> None:
        f.rect(x, y, TILE, TILE, look.block)
        f.hline(x, y + 3, TILE, look.block2)
        f.vline(x + 3, y, TILE, look.block2)
        f.set(x, y, WHITE)

    def _draw_penguin(self, f: Frame, now: float, look: Look) -> None:
        a = self.anim
        x, y = _xy(self.state[0])
        name = f"{self.face}0"
        if a is not None and a.path:
            fx, fy = self._along(a.path, self._anim_k())
            x, y = round(fx), round(fy)
            sliding = len(a.path) > 2 and self.anim_t > WALK_T * 0.6
            if sliding:
                name = "slide_" + self.face if self.face != "left" else "slide_left"
            else:
                name = f"{self.face}{int(self.anim_t * 14) % 2}"
        if self.end == "win" or self.card in ("clear", "escaped"):
            name = "cheer"
            y -= 1 if int(now * 6) % 2 else 0
        if self.end == "fall" and a is None:
            # sinking: the top of the penguin above a ring of ripples
            spr = SPRITES["down0"]
            sink = min(3, int(self.end_t * 6))
            if sink < 3:
                f.blit(spr.px[: 4 - sink], x, y + sink, spr.mask[: 4 - sink])
            f.hline(x - 1, y + 3, 6, look.glint)
            return
        if self.card == "fail" and a is None and self.end is None and self._fell():
            return
        spr = SPRITES.get(name) or SPRITES["down0"]
        f.sprite(spr, x, y)

    def _fell(self) -> bool:
        st = self.state
        pz = self.pz
        return pz.floor[st[0]] == WATER and not (st[5] >> pz.water_idx[st[0]] & 1)

    def _hud(self, f: Frame, now: float, look: Look) -> None:
        f.rect(0, 0, 32, OY, look.hud)
        got = self.state[1]
        for n in range(3):
            f.sprite(HUD_FISH if got >> n & 1 else HUD_FISH_OFF, 1 + n * 5, 0)
        if self.pz.held_keys(self.state) > 0:
            f.sprite(HUD_KEY, 16, 0)
        # sixteen level dots in two rows: cleared = gold, current = white (blinking), ahead = dim
        for n in range(N_LEVELS):
            x, y = 23 + n % 8, 0 if n < 8 else 2
            if n == self.level:
                c = WHITE if int(now * 3) % 3 else scale(WHITE, 0.4)
            elif str(n + 1) in self.stars_best:
                c = scale(STAR, 0.8)
            else:
                c = (46, 50, 70)
            f.set(x, y, c)

    def _draw_fail(self, f: Frame, now: float) -> None:
        f.dim(0.35)
        f.rect(0, 11, 32, 15, (0, 0, 0))
        fell = self._fell()
        _kit.label(
            f, 12, "SPLASH" if fell else "CAUGHT", (90, 170, 255) if fell else (255, 70, 60), font="small"
        )
        if int(now * 2) % 2:
            _kit.label(f, 20, "A UNDO", (150, 150, 170))
        else:
            _kit.label(f, 20, "B RETRY", (150, 150, 170))

    def _draw_card(self, f: Frame, now: float, look: Look) -> None:
        th = self.theme
        f.clear(look.hud)
        key = str(self.level + 1)
        if self.card == "level":
            f.text_center(2, "LEVEL", scale(th.hud, 0.75))
            _kit.hero(f, 9, key, WHITE)
            best = self.stars_best.get(key, 0)
            for n in range(3):
                _star(f, 6 + n * 8, 21, STAR if n < best else (54, 54, 74))
            lim = self.allowed_max()
            blink = int(now * 2) % 2 == 0
            if self.level > 0 and blink:
                f.text(1, 11, "<", scale(th.hud, 0.6))
            if self.level < lim and blink:
                f.text(28, 11, ">", scale(th.hud, 0.6))
            name = LEVELS[self.level].name.upper()
            _kit.label(f, 27, name, scale(th.hud, 0.55), t=self.card_t)
            return
        # clear / escaped: a cheering penguin (2×) over the stars it earned
        spr = SPRITES["cheer"]
        hop = 1 if int(now * 5) % 2 else 0
        f.rect(10, 1, 12, 10, look.snow)  # an ice floe to stand on (a dark penguin vanishes on black)
        for cx, cy in ((10, 1), (21, 1), (10, 10), (21, 10)):
            f.set(cx, cy, look.hud)
        big = np.repeat(np.repeat(spr.px, 2, axis=0), 2, axis=1)
        mask = np.repeat(np.repeat(spr.mask, 2, axis=0), 2, axis=1)
        f.blit(big, 12, 2 - hop, mask)
        txt = "ESCAPED" if self.card == "escaped" else "CLEAR"
        _kit.label(f, 12, txt, GATE, font="small")
        got = self.pz.stars(self.state)
        for n in range(3):
            lit = n < got and self.card_t > 0.25 * (n + 1)
            _star(f, 6 + n * 8, 22, STAR if lit else (54, 54, 74))

    def status(self) -> dict[str, Any]:
        st = super().status()
        st["level"] = self.level + 1
        st["levels"] = N_LEVELS
        st["fish"] = self.pz.stars(self.state)
        st["moves"] = len(self.history)
        st["stage"] = self.card or ("moving" if self.anim is not None else "puzzle")
        st["stars_total"] = sum(self.stars_best.values())
        return st
