"""Puzzle games: Tetris (falling blocks) and 2048. Original code and art.

Tetris: Solo (10-wide well), Versus (two 7-wide wells side by side; clearing lines sends garbage rows to the
opponent) and Co-op (one 13-wide well, two falling pieces at once). Maps: an empty well, a garbage mound, or a
rising floor.

2048: Solo, Race (2–4 small boards, first to the target tile wins; big merges drop junk tiles on rivals) and
Relay (one board, players take turns). Maps: the classic board, or one with two immovable stones.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from ..engine.app import Choice, register
from ..gfx import RGB, Frame, scale
from .games_core import BLACK, THEMES, WHITE, GameApp, GameSettings, Mode, Theme, tint

# =====================================================================================================
# Tetris — wells of 2×2 px cells, 16 rows tall
# =====================================================================================================
WW, WH = 10, 16
_SHAPES = {
    "I": [(0, 1), (1, 1), (2, 1), (3, 1)],
    "O": [(1, 0), (2, 0), (1, 1), (2, 1)],
    "T": [(0, 1), (1, 1), (2, 1), (1, 0)],
    "S": [(1, 0), (2, 0), (0, 1), (1, 1)],
    "Z": [(0, 0), (1, 0), (1, 1), (2, 1)],
    "J": [(0, 0), (0, 1), (1, 1), (2, 1)],
    "L": [(2, 0), (0, 1), (1, 1), (2, 1)],
}
KINDS = tuple(_SHAPES)
GARBAGE = 8  # grid value of a garbage block
GHOST = 8  # ghost cell = kind + GHOST (9..15)
FLASH = 16  # a clearing row
SEAT_IDX = 16  # an active co-op piece = SEAT_IDX + seat (17..20)
ATTACK = (0, 0, 1, 2, 4)  # garbage rows sent for 0..4 cleared lines
ATTACK_MIRROR = (0, 1, 2, 3, 4)


def _rotations(cells: list[tuple[int, int]]) -> list[tuple[tuple[int, int], ...]]:
    out: list[tuple[tuple[int, int], ...]] = []
    cur = cells
    for _ in range(4):
        mx, my = min(x for x, _ in cur), min(y for _, y in cur)
        norm = tuple(sorted((x - mx, y - my) for x, y in cur))
        if norm not in out:
            out.append(norm)
        cur = [(3 - y, x) for x, y in cur]  # rotate clockwise in a 4x4 box
    return out


ROTS = {k: _rotations(v) for k, v in _SHAPES.items()}


def _rowmasks(cells: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
    rows: dict[int, int] = {}
    for x, y in cells:
        rows[y] = rows.get(y, 0) | (1 << x)
    return sorted(rows.items())


MASKS = {k: [_rowmasks(r) for r in rots] for k, rots in ROTS.items()}

TETRIS_THEMES: dict[str, Theme] = {
    "prism": Theme(
        p=(0, 220, 255),
        e=(255, 70, 90),
        x=(255, 220, 40),
        w=(60, 90, 255),
        hud=(255, 255, 255),
        bg=(0, 0, 0),
        r=(
            (0, 220, 255),
            (255, 214, 0),
            (190, 60, 255),
            (40, 230, 60),
            (255, 30, 30),
            (40, 80, 255),
            (255, 130, 0),
        ),
    ),
    "candy": Theme(
        p=(255, 120, 220),
        e=(255, 90, 90),
        x=(255, 255, 150),
        w=(200, 80, 170),
        hud=(255, 210, 240),
        bg=(8, 2, 8),
        r=(
            (120, 240, 255),
            (255, 240, 120),
            (230, 130, 255),
            (140, 255, 150),
            (255, 110, 140),
            (130, 150, 255),
            (255, 170, 90),
        ),
    ),
    "deep": Theme(
        p=(0, 255, 210),
        e=(255, 110, 70),
        x=(210, 255, 255),
        w=(0, 120, 160),
        hud=(170, 245, 255),
        bg=(0, 3, 10),
        r=(
            (0, 255, 230),
            (255, 220, 90),
            (150, 110, 255),
            (60, 255, 120),
            (255, 90, 110),
            (40, 150, 255),
            (255, 150, 60),
        ),
    ),
}


class Pilot:
    """One falling piece and whoever steers it."""

    __slots__ = (
        "act_t",
        "bag",
        "drop_fast",
        "fall_t",
        "idx",
        "kind",
        "lines",
        "next",
        "px",
        "py",
        "rot",
        "seat",
        "target",
        "waiting",
    )

    def __init__(self, seat: int, idx: int) -> None:
        self.seat, self.idx = seat, idx
        self.bag: list[str] = []
        self.kind = self.next = "T"
        self.rot = self.px = self.py = 0
        self.target = (0, 0)
        self.act_t = self.fall_t = 0.0
        self.drop_fast = False
        self.waiting = True
        self.lines = 0


class Well:
    """A playfield: grid, clearing animation, pending garbage and the pilots dropping pieces into it."""

    def __init__(self, w: int, x0: int, team: int) -> None:
        self.w, self.x0, self.team = w, x0, team
        self.full = (1 << w) - 1
        self.grid = [[0] * w for _ in range(WH)]
        self.lines = 0
        self.clearing: list[int] = []
        self.clear_t = 0.0
        self.pending = 0
        self.alive = True
        self.hurt = 0.0
        self.pilots: list[Pilot] = []


class TetrisSettings(GameSettings):
    ghost: bool = Field(True, title="Landing shadow")
    start_level: int = Field(1, ge=1, le=10, title="Start level")
    attack: str = Choice(
        "classic",
        {"classic": "Classic (2 lines → 1)", "mirror": "Mirror (every line)"},
        title="Garbage sent",
        group="Game",
    )
    rise_every: int = Field(
        15, ge=5, le=60, title="Rising floor every (s)", json_schema_extra={"group": "Game"}
    )


@register
class Tetris(GameApp):
    id = "tetris"
    name = "Tetris"
    description = (
        "Falling blocks with a next-piece preview. The AI stacks by holes, height and bumpiness. "
        "←/→ move, ↑ rotate, ↓ soft drop, A hard drop, B rotate back. B in the demo opens the menu: Versus "
        "(clear lines to send garbage) and Co-op (one wide well)."
    )
    icon = "blocks"
    Settings = TetrisSettings
    step_hz = 30.0
    max_players = 2
    controls = ("dpad", "gamepad", "keyboard", "joystick")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("versus", "Versus", 2, 2, "versus", "Clear lines to send garbage"),
        Mode("coop", "Co-op", 2, 2, "coop", "One wide well, two pieces"),
    )
    maps: ClassVar[dict[str, str]] = {"classic": "Empty", "mound": "Mound", "rising": "Rising"}
    game_themes: ClassVar[dict[str, Theme]] = TETRIS_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"prism": "Prism", "candy": "Candy", "deep": "Deep sea"}

    def new_game(self) -> None:
        teams = self.play_mode.teams
        self.layout = teams if teams in ("versus", "coop") and self.n_players > 1 else "solo"
        if self.layout == "versus":
            self.wells = [Well(7, 0, 0), Well(7, 18, 1)]
            for seat in range(1, 3):
                t = self.team_of(seat)
                w = self.wells[(seat - 1) if t is None else t]
                if w.pilots:  # both seats on one side can't happen after side select; be safe anyway
                    w = next(x for x in self.wells if not x.pilots)
                w.pilots.append(Pilot(seat, 0))
        elif self.layout == "coop":
            well = Well(13, 0, 0)
            well.pilots = [Pilot(1, 0), Pilot(2, 1)]
            self.wells = [well]
        else:
            well = Well(WW, 0, 0)
            well.pilots = [Pilot(1, 0)]
            self.wells = [well]
        self.rise_t = float(self.settings.rise_every)
        if self.map_id == "mound":
            holes = [self.rng.randrange(7) for _ in range(5)]  # the same mound in every well (fair)
            for w in self.wells:
                for i, h in enumerate(holes):
                    row = [GARBAGE] * w.w
                    row[h % w.w] = 0
                    row[(h * 3 + 2) % w.w] = 0
                    w.grid[WH - 5 + i] = row
        for w in self.wells:
            for p in w.pilots:
                p.next = self._draw_bag(p)
                self._spawn(w, p)

    # -------------------------------------------------------------- compat (solo = the first well)
    @property
    def grid(self) -> list[list[int]]:
        return self.wells[0].grid

    @property
    def lines(self) -> int:
        return self.wells[0].lines

    @property
    def piece(self) -> str:
        return self.wells[0].pilots[0].kind

    def level_of(self, w: Well) -> int:
        return self.settings.start_level + w.lines // 8

    @property
    def level(self) -> int:
        return self.level_of(self.wells[0])

    # --------------------------------------------------------------- logic
    def _draw_bag(self, p: Pilot) -> str:
        if not p.bag:
            p.bag = list(KINDS)
            self.rng.shuffle(p.bag)
        return p.bag.pop()

    @staticmethod
    def _cells(kind: str, rot: int, px: int, py: int) -> list[tuple[int, int]]:
        return [(px + x, py + y) for x, y in ROTS[kind][rot % len(ROTS[kind])]]

    def _others(self, w: Well, p: Pilot) -> set[tuple[int, int]]:
        out: set[tuple[int, int]] = set()
        for o in w.pilots:
            if o is not p and not o.waiting:
                out.update(self._cells(o.kind, o.rot, o.px, o.py))
        return out

    def _fits(self, w: Well, p: Pilot, rot: int, px: int, py: int, others: bool = True) -> bool:
        block = self._others(w, p) if others and len(w.pilots) > 1 else ()
        for x, y in self._cells(p.kind, rot, px, py):
            if x < 0 or x >= w.w or y >= WH or (y >= 0 and w.grid[y][x]) or (x, y) in block:
                return False
        return True

    def _spawn(self, w: Well, p: Pilot) -> None:
        p.kind = p.next  # `next` is only replaced once the piece is really in the well
        p.rot = 0
        pw = max(x for x, _ in ROTS[p.kind][0]) + 1
        half = (w.w + 1) // 2 if len(w.pilots) > 1 else w.w
        lo, hi = (0, half) if p.idx == 0 else (half, w.w)
        p.px, p.py = lo + (hi - lo - pw) // 2, 0
        p.drop_fast = False
        p.fall_t = 0.0
        if len(w.pilots) > 1 and not self._fits(w, p, 0, p.px, 0, others=False):
            # co-op: your half is full to the top, but the piece may still enter elsewhere in the wide well
            spots = sorted(range(w.w - pw + 1), key=lambda x: abs(x - p.px))
            p.px = next((x for x in spots if self._fits(w, p, 0, x, 0, others=False)), p.px)
        if not self._fits(w, p, 0, p.px, p.py, others=False):
            p.waiting = True
            self._top_out(w)
            return
        if not self._fits(w, p, 0, p.px, p.py):
            p.waiting = True  # the partner's piece is in the way: try again next tick
            return
        p.next = self._draw_bag(p)
        p.waiting = False
        p.target = self._plan(w, p)

    def _top_out(self, w: Well) -> None:
        if not w.alive:
            return
        w.alive = False
        if self.over:
            return
        self.fx.burst(self.rng, w.x0 + w.w, 4, self.theme.e, 16, 14, 0.8)
        if any(self.is_human(p.seat) for p in w.pilots):
            self.damage(1.0)
        if self.layout == "versus":
            win = next((x for x in self.wells if x is not w), None)
            seat = win.pilots[0].seat if win and win.pilots else None
            self.result(winner_seat=seat, scores={p.seat: x.lines for x in self.wells for p in x.pilots})
        elif self.layout == "coop":
            self.result(
                scores={p.seat: p.lines for p in w.pilots},
                text=f"{w.lines} LINE" + ("" if w.lines == 1 else "S"),
            )
        else:
            self.game_over()

    def _lock(self, w: Well, p: Pilot) -> None:
        idx = KINDS.index(p.kind) + 1
        for x, y in self._cells(p.kind, p.rot, p.px, p.py):
            if 0 <= y < WH:
                w.grid[y][x] = idx
        p.waiting = True
        for o in w.pilots:  # co-op: the partner re-plans around the new blocks
            if o is not p and not o.waiting:
                o.target = self._plan(w, o, near=True)
                o.drop_fast = False
        full = [y for y in range(WH) if all(w.grid[y])]
        if full:
            w.clearing = full
            w.clear_t = 0.32
            p.lines += len(full)
            for y in full:
                for x in range(0, w.w, 2):
                    self.fx.burst(self.rng, w.x0 + x * 2 + 1, y * 2 + 1, WHITE, 1, 10, 0.4)
        else:
            if w.pending:
                self._add_garbage(w, min(4, w.pending))
                w.pending = max(0, w.pending - 4)
                if not w.alive:
                    return
            self._spawn(w, p)

    def _finish_clear(self, w: Well) -> None:
        n = len(w.clearing)
        keep = [row for y, row in enumerate(w.grid) if y not in w.clearing]
        w.grid = [[0] * w.w for _ in range(n)] + keep
        w.lines += n
        w.clearing = []
        if n >= 4:
            self.flash = 0.5
        if self.layout == "versus":
            table = ATTACK_MIRROR if self.settings.attack == "mirror" else ATTACK
            send = table[min(4, n)]
            cancel = min(w.pending, send)
            w.pending -= cancel
            send -= cancel
            for o in self.wells:
                if o is not w and o.alive and send:
                    o.pending += send
        self._unstick(w)
        for p in w.pilots:
            if p.waiting:
                self._spawn(w, p)
                if not w.alive:
                    return
        self._score()

    def _unstick(self, w: Well) -> None:
        """After the grid moved, lift any floating piece that now overlaps blocks."""
        for p in w.pilots:
            if p.waiting:
                continue
            for _ in range(6):
                if self._fits(w, p, p.rot, p.px, p.py, others=False):
                    break
                p.py -= 1

    def _add_garbage(self, w: Well, n: int) -> None:
        hole = self.rng.randrange(w.w)
        if any(any(row) for row in w.grid[:n]):
            w.grid = w.grid[n:] + [[GARBAGE] * w.w for _ in range(n)]
            self._top_out(w)
            return
        rows = []
        for _ in range(n):
            row = [GARBAGE] * w.w
            row[hole] = 0
            rows.append(row)
        w.grid = w.grid[n:] + rows
        w.hurt = 0.6
        self._unstick(w)
        for p in w.pilots:
            if not p.waiting:
                p.target = self._plan(w, p, near=True)
        for x in range(0, w.w, 2):
            self.fx.burst(self.rng, w.x0 + x * 2 + 1, 31, self.theme.e, 1, 8, 0.3, vy=-8)
        if any(self.is_human(p.seat) for p in w.pilots):
            self.damage(0.5)

    def _score(self) -> None:
        if self.layout == "versus":
            mine = next((w for w in self.wells for p in w.pilots if p.seat == 1), self.wells[0])
            self.score = mine.lines
        else:
            self.score = self.wells[0].lines

    def _move(self, w: Well, p: Pilot, dx: int, dy: int) -> bool:
        if self._fits(w, p, p.rot, p.px + dx, p.py + dy):
            p.px += dx
            p.py += dy
            return True
        return False

    def _rotate(self, w: Well, p: Pilot, d: int) -> None:
        n = len(ROTS[p.kind])
        r = (p.rot + d) % n
        for kick in (0, -1, 1, -2, 2):
            if self._fits(w, p, r, p.px + kick, p.py):
                p.rot, p.px = r, p.px + kick
                return

    def _hard_drop(self, w: Well, p: Pilot) -> None:
        start = p.py
        while self._move(w, p, 0, 1):
            pass
        c = self.theme.r[KINDS.index(p.kind)]
        for x, _y in self._cells(p.kind, p.rot, p.px, p.py):
            for yy in range(start, p.py, 3):
                self.fx.emit(w.x0 + x * 2 + 1, yy * 2 + 1, 0, 0, scale(c, 0.5), 0.25)
        self._settle(w, p)

    def _settle(self, w: Well, p: Pilot) -> None:
        """The piece can't fall: lock it, unless only the partner's piece is holding it up (co-op)."""
        if self._fits(w, p, p.rot, p.px, p.py + 1, others=False):
            return
        self._lock(w, p)

    def _ghost_y(self, w: Well, p: Pilot) -> int:
        y = p.py
        while self._fits(w, p, p.rot, p.px, y + 1):
            y += 1
        return y

    # ------------------------------------------------------------------ AI
    def _plan(self, w: Well, p: Pilot, near: bool = False) -> tuple[int, int]:
        """Score every (rotation, column) drop with the classic holes/height/bumpiness heuristic.
        Co-op: the partner's piece is treated as already landed where it is heading, and the columns it is
        travelling through are left to it. `near`: re-plan a piece that is already falling — only drops it
        can still reach from where it is."""
        rows = [sum(1 << x for x in range(w.w) if r[x]) for r in w.grid]
        reserved = 0
        for o in w.pilots:
            if o is p or o.waiting:
                continue
            tr, tx = o.target
            y = o.py
            while self._fits(w, o, tr, tx, y + 1, others=False):
                y += 1
            if self._fits(w, o, tr, tx, y, others=False):
                for cx, cy in self._cells(o.kind, tr, tx, y):
                    if 0 <= cy < WH:
                        rows[cy] |= 1 << cx
            for cx, _cy in self._cells(o.kind, tr, tx, y) + self._cells(o.kind, o.rot, o.px, o.py):
                reserved |= 1 << cx
        results: list[tuple[float, int, int]] = []
        crossing: list[tuple[float, int, int]] = []
        for ri, masks in enumerate(MASKS[p.kind]):
            pw = max(x for x, _ in ROTS[p.kind][ri]) + 1
            for px in range(w.w - pw + 1):
                if near and abs(px - p.px) > 3:
                    continue
                shifted = [(dy, m << px) for dy, m in masks]
                cols = 0
                for _dy, m in shifted:
                    cols |= m
                y0 = max(-1, p.py - 1) if near else -1
                y = y0
                while all(y + 1 + dy < WH and not rows[y + 1 + dy] & m for dy, m in shifted):
                    y += 1
                if y <= y0 or y < 0:
                    continue
                new = rows[:]
                for dy, m in shifted:
                    new[y + dy] |= m
                cleared = sum(1 for r in new if r == w.full)
                if cleared:
                    new = [0] * cleared + [r for r in new if r != w.full]
                (crossing if cols & reserved else results).append((self._eval(new, cleared, w.w), ri, px))
        results = results or crossing
        if not results:
            return p.rot, p.px
        results.sort(reverse=True)
        pick = 0
        if len(results) > 2 and self.rng.random() < (1 - self.skill) * 0.7:
            pick = self.rng.randrange(1, min(4, len(results)))
        _, ri, px = results[pick]
        return ri, px

    @staticmethod
    def _eval(rows: list[int], cleared: int, ww: int = WW) -> float:
        full = (1 << ww) - 1
        heights = [0] * ww
        covered = 0
        holes = 0
        for y, r in enumerate(rows):
            holes += bin(covered & ~r & full).count("1")
            new = r & ~covered
            if new:
                for x in range(ww):
                    if new >> x & 1:
                        heights[x] = WH - y
            covered |= r
        agg = sum(heights)
        bump = sum(abs(heights[i] - heights[i + 1]) for i in range(ww - 1))
        tall = max(heights)
        return (
            -0.51 * agg
            + 0.76 * cleared
            - 0.36 * holes * 2
            - 0.18 * bump
            - (0.8 * (tall - 11) if tall > 11 else 0)
        )

    def _ai_step(self, w: Well, p: Pilot) -> None:
        tr, tx = p.target
        if p.rot != tr:
            before = p.rot
            self._rotate(w, p, 1)
            if p.rot == before:
                self._blocked(w, p)
        elif p.px != tx:
            dx = 1 if tx > p.px else -1
            if not self._move(w, p, dx, 0):
                if self._fits(w, p, p.rot, p.px + dx, p.py, others=False):
                    self._blocked(w, p)
                else:
                    p.drop_fast = True
        else:
            p.drop_fast = True

    def _blocked(self, w: Well, p: Pilot) -> None:
        """The partner's piece is in the way: pick a drop on this side of it (or just drop if none)."""
        if len(w.pilots) < 2:
            p.drop_fast = True
            return
        new = self._plan(w, p, near=True)
        if new == p.target:
            p.drop_fast = True
        p.target = new

    # --------------------------------------------------------------- input
    def key_p(self, k: str, player: int) -> None:
        for w in self.wells:
            for p in w.pilots:
                if p.seat == player and w.alive and not w.clearing and not p.waiting:
                    self._key(w, p, k)
                    return

    def _key(self, w: Well, p: Pilot, k: str) -> None:
        if k == "left":
            self._move(w, p, -1, 0)
        elif k == "right":
            self._move(w, p, 1, 0)
        elif k == "up":
            self._rotate(w, p, 1)
        elif k == "b":
            self._rotate(w, p, -1)
        elif k == "down":
            if not self._move(w, p, 0, 1):
                self._settle(w, p)
            p.fall_t = 0.0
        elif k == "a":
            self._hard_drop(w, p)

    def update(self, dt: float) -> None:
        for w in self.wells:
            w.hurt = max(0.0, w.hurt - dt)
        if self.map_id == "rising":
            self.rise_t -= dt
            if self.rise_t <= 0:
                self.rise_t = float(self.settings.rise_every)
                for w in self.wells:
                    if w.alive and not w.clearing and not self.over:
                        self._add_garbage(w, 1)
        for w in self.wells:
            if self.over:
                return
            if not w.alive:
                continue
            if w.clearing:
                w.clear_t -= dt
                if w.clear_t <= 0:
                    self._finish_clear(w)
                continue
            for p in w.pilots:
                if self.over or not w.alive or w.clearing:
                    break
                if p.waiting:
                    self._spawn(w, p)
                    continue
                self._tick_pilot(w, p, dt)

    def _tick_pilot(self, w: Well, p: Pilot, dt: float) -> None:
        ai = not self.is_human(p.seat)
        if ai:
            p.act_t -= dt
            if p.act_t <= 0 and not p.drop_fast:
                p.act_t = 0.11 - 0.05 * self.skill
                self._ai_step(w, p)
        gravity = max(0.06, 0.8 * 0.84 ** (self.level_of(w) - 1))
        if ai and p.drop_fast:
            gravity = min(gravity, 0.035)
        p.fall_t += dt
        if p.fall_t >= gravity:
            p.fall_t = 0.0
            if not self._move(w, p, 0, 1):
                self._settle(w, p)

    # ---------------------------------------------------------------- draw
    def _luts(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        th = self.theme
        g = (125, 125, 140)
        seats = [self.colour_of(s) for s in (1, 2, 3, 4)]
        base = [th.bg, *th.r, g, *(scale(c, 0.22) for c in th.r), WHITE, *seats]
        hi = [th.bg, *(tint(c, 0.45) for c in th.r), tint(g, 0.3), *(scale(c, 0.3) for c in th.r), WHITE]
        hi += [tint(c, 0.45) for c in seats]
        lo = [th.bg, *(scale(c, 0.55) for c in th.r), scale(g, 0.6), *(scale(c, 0.16) for c in th.r), WHITE]
        lo += [scale(c, 0.55) for c in seats]
        return (np.array(base, np.uint8), np.array(hi, np.uint8), np.array(lo, np.uint8))

    def _draw_well(self, f: Frame, w: Well, luts: tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
        cells = np.array(w.grid, dtype=np.int16)
        if w.alive and not w.clearing and not self.over:
            for p in w.pilots:
                if p.waiting:
                    continue
                idx = KINDS.index(p.kind) + 1
                if self.settings.ghost:
                    gy = self._ghost_y(w, p)
                    for x, y in self._cells(p.kind, p.rot, p.px, gy):
                        if 0 <= y < WH and cells[y, x] == 0:
                            cells[y, x] = idx + GHOST
                own = SEAT_IDX + p.seat if self.layout == "coop" else idx
                for x, y in self._cells(p.kind, p.rot, p.px, p.py):
                    if 0 <= y < WH:
                        cells[y, x] = own
        if w.clearing and int(w.clear_t * 20) % 2 == 0:
            for y in w.clearing:
                cells[y, :] = FLASH
        base, hi, lo = luts
        img = np.repeat(np.repeat(base[cells], 2, axis=0), 2, axis=1)
        img[0::2, 0::2] = hi[cells]
        img[1::2, 1::2] = lo[cells]
        if not w.alive:
            img = (img * 0.35).astype(np.uint8)
        f.px[:, w.x0 : w.x0 + w.w * 2] = img

    def _mini(self, f: Frame, kind: str, x0: int, y0: int, col: RGB) -> None:
        for x, y in ROTS[kind][0]:
            f.set(x0 + x, y0 + y, col)

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        luts = self._luts()
        f.clear(th.bg)
        for w in self.wells:
            self._draw_well(f, w, luts)
        hot = (255, 40, 40)
        if self.layout == "versus":
            a, b = self.wells
            for x, w in ((14, a), (17, b)):
                side = self.colour_of(w.pilots[0].seat) if w.pilots else th.w
                col = hot if w.hurt > 0 and int(w.hurt * 10) % 2 else scale(side, 0.6)
                f.vline(x, 0, 32, col)
            for x, w in ((15, a), (16, b)):  # incoming garbage meters
                h = min(32, w.pending * 2)
                if h:
                    f.vline(x, 32 - h, h, th.e)
            return
        if self.layout == "coop":
            w = self.wells[0]
            f.vline(26, 0, 32, hot if w.hurt > 0 and int(w.hurt * 10) % 2 else scale(th.w, 0.8))
            for i, p in enumerate(w.pilots):
                pw = max(x for x, _ in ROTS[p.next][0]) + 1
                self._mini(f, p.next, 27 + (5 - pw) // 2, 1 + i * 5, self.colour_of(p.seat))
            if self.settings.show_score:
                for i, ch in enumerate(str(w.lines)[-3:]):
                    f.text(28, 13 + i * 6, ch, th.hud)
            return
        w = self.wells[0]
        p = w.pilots[0]
        wall = hot if w.hurt > 0 and int(w.hurt * 10) % 2 else scale(th.w, 0.8 if self.flash <= 0 else 1.0)
        f.vline(20, 0, 32, wall)
        # next piece
        nidx = KINDS.index(p.next)
        cells_n = ROTS[p.next][0]
        pw = max(x for x, _ in cells_n) + 1
        ox = 21 + (11 - pw * 2) // 2
        c = th.r[nidx]
        for x, y in cells_n:
            f.rect(ox + x * 2, 2 + y * 2, 2, 2, c)
            f.set(ox + x * 2, 2 + y * 2, tint(c, 0.45))
        if self.settings.show_score:
            f.text_right(30, 9, str(w.lines), th.hud)
            f.text(22, 16, "L", scale(th.hud, 0.5))
            f.text_right(30, 16, str(self.level), scale(th.hud, 0.8))
        who = "YOU" if self.is_human(1) else "AI"
        f.text(21 + (11 - (len(who) * 4 - 1)) // 2 + (1 if who == "YOU" else 0), 26, who, scale(th.p, 0.55))

    def status(self) -> dict[str, Any]:
        st = super().status()
        if self.layout != "solo":
            st["lines"] = {str(p.seat): w.lines for w in self.wells for p in w.pilots}
        return st


# =====================================================================================================
# 2048 — 4×4 grid of 7×7 tiles, colour encodes value; small 3×3-px boards for races
# =====================================================================================================
LINES = {
    "left": [[r * 4 + c for c in range(4)] for r in range(4)],
    "right": [[r * 4 + c for c in range(3, -1, -1)] for r in range(4)],
    "up": [[r * 4 + c for r in range(4)] for c in range(4)],
    "down": [[r * 4 + c for r in range(3, -1, -1)] for c in range(4)],
}
DIRS = tuple(LINES)
SNAKE = (
    15, 14, 13, 12,
    8, 9, 10, 11,
    7, 6, 5, 4,
    0, 1, 2, 3,
)  # fmt: skip
WEIGHT = tuple(4.0**w for w in SNAKE)
STONE = 15  # an immovable block (the Stones map)
STONE_CELLS = (5, 10)


@lru_cache(maxsize=65536)
def _slide(row: tuple[int, ...]) -> tuple[tuple[int, ...], int]:
    """Slide one line towards index 0; stones split it into independent segments."""
    if STONE in row:
        out: list[int] = []
        gain = 0
        i = 0
        while i < len(row):
            if row[i] == STONE:
                out.append(STONE)
                i += 1
                continue
            j = i
            while j < len(row) and row[j] != STONE:
                j += 1
            seg, g = _slide(row[i:j])
            out += seg
            gain += g
            i = j
        return tuple(out), gain
    tiles = [v for v in row if v]
    res: list[int] = []
    gain = 0
    i = 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            res.append(tiles[i] + 1)
            gain += 1 << (tiles[i] + 1)
            i += 2
        else:
            res.append(tiles[i])
            i += 1
    return tuple(res + [0] * (len(row) - len(res))), gain


def _apply(b: tuple[int, ...], d: str) -> tuple[tuple[int, ...], int, bool]:
    nb = list(b)
    gain = 0
    for idxs in LINES[d]:
        row = tuple(b[i] for i in idxs)
        new, g = _slide(row)
        gain += g
        for i, v in zip(idxs, new, strict=True):
            nb[i] = v
    t = tuple(nb)
    return t, gain, t != b


def _heur(b: tuple[int, ...]) -> float:
    s = 0.0
    empty = 0
    for i, v in enumerate(b):
        if v == STONE:
            continue
        if v:
            s += (1 << v) * WEIGHT[i]
        else:
            empty += 1
    return s * (1.0 + 0.06 * empty)


CLASSIC_RAMP: list[RGB] = [
    (0, 0, 0),
    (70, 60, 50),
    (140, 115, 80),
    (255, 140, 40),
    (255, 90, 20),
    (255, 40, 40),
    (255, 0, 90),
    (255, 210, 40),
    (170, 255, 0),
    (0, 255, 120),
    (0, 200, 255),
    (170, 80, 255),
    (255, 255, 255),
]


def _ramp_from(th: Theme) -> list[RGB]:
    out: list[RGB] = [(0, 0, 0)]
    for i in range(1, 13):
        c = th.r[(i - 1) % len(th.r)]
        out.append(scale(c, 0.35 + 0.65 * min(1.0, (i - 1) / 3)) if i < 12 else WHITE)
    return out


# per theme: colour ramp by exponent (1 = "2")
def _ramp(theme: str) -> list[RGB]:
    if theme in ("classic", "tiles"):
        return CLASSIC_RAMP
    th = G2048_THEMES.get(theme) or THEMES.get(theme) or THEMES["classic"]
    return _ramp_from(th)


G2048_THEMES: dict[str, Theme] = {
    "tiles": Theme(
        p=(255, 200, 90),
        e=(255, 80, 60),
        x=(255, 230, 120),
        w=(150, 120, 90),
        hud=(255, 235, 200),
        bg=(6, 4, 2),
        r=THEMES["classic"].r,
    ),
    "ice": Theme(
        p=(120, 230, 255),
        e=(255, 110, 150),
        x=(230, 255, 255),
        w=(80, 140, 200),
        hud=(200, 240, 255),
        bg=(0, 3, 10),
        r=(
            (90, 130, 200),
            (60, 170, 255),
            (0, 220, 255),
            (100, 255, 230),
            (180, 160, 255),
            (230, 120, 255),
            (255, 150, 200),
        ),
    ),
    "ember": Theme(
        p=(255, 170, 40),
        e=(255, 60, 60),
        x=(255, 240, 150),
        w=(160, 70, 30),
        hud=(255, 210, 150),
        bg=(10, 3, 0),
        r=(
            (150, 70, 40),
            (255, 110, 30),
            (255, 60, 30),
            (255, 170, 0),
            (255, 220, 60),
            (255, 90, 120),
            (255, 250, 200),
        ),
    ),
}


class Board:
    """One 2048 board and its animation state."""

    __slots__ = ("alive", "anim", "anim_t", "board", "move_t", "pending", "pop", "score", "seat")

    def __init__(self, seat: int) -> None:
        self.seat = seat
        self.board: tuple[int, ...] = (0,) * 16
        self.score = 0
        self.anim: list[tuple[int, int, int]] = []  # (exponent, from, to)
        self.anim_t = 0.0
        self.pop: dict[int, float] = {}
        self.pending: list[str] = []
        self.move_t = 0.0
        self.alive = True

    @property
    def top(self) -> int:
        return max((v for v in self.board if v != STONE), default=0)


class G2048Settings(GameSettings):
    numbers: bool = Field(True, title="Show numbers")
    race_target: str = Choice(
        "256", {"128": "128", "256": "256", "512": "512", "1024": "1024"}, title="Race to tile", group="Game"
    )
    junk: bool = Field(
        True,
        title="Junk attacks",
        description="Race: merging 64 or more drops a junk tile on every rival",
        json_schema_extra={"group": "Game"},
    )


@register
class G2048(GameApp):
    id = "g2048"
    name = "2048"
    description = (
        "Slide and merge tiles towards 2048; colour tells the value. The AI hugs a corner. Arrows slide. "
        "B in the demo opens the menu: Race on 2–4 small boards, or Relay (take turns on one board)."
    )
    icon = "grid-2x2"
    Settings = G2048Settings
    step_hz = 30.0
    over_hold = 2.5
    max_players = 4
    controls = ("swipe", "dpad", "keyboard", "gamepad")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("race", "Race", 2, 4, "ffa", "First to the target tile"),
        Mode("relay", "Relay", 2, 4, "coop", "Take turns on one board"),
    )
    maps: ClassVar[dict[str, str]] = {"classic": "Classic", "stones": "Stones"}
    game_themes: ClassVar[dict[str, Theme]] = G2048_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"tiles": "Tiles", "ice": "Ice", "ember": "Ember"}

    def new_game(self) -> None:
        teams = self.play_mode.teams
        n = self.n_players
        self.layout = teams if teams in ("ffa", "coop") and n > 1 else "solo"
        seats = range(1, n + 1) if self.layout == "ffa" else [1]
        self.boards = [Board(s) for s in seats]
        self.turn = 1
        self.turn_t = 0.0
        self.turn_seats = list(range(1, n + 1)) if self.layout == "coop" else [1]
        for b in self.boards:
            if self.map_id == "stones":
                cells = list(b.board)
                for i in STONE_CELLS:
                    cells[i] = STONE
                b.board = tuple(cells)
            self._spawn(b)
            self._spawn(b)
            b.anim_t = 0.0

    # ---- compat: the solo board
    @property
    def board(self) -> tuple[int, ...]:
        return self.boards[0].board

    @property
    def pending(self) -> list[str]:
        return self.boards[0].pending

    def _spawn(self, b: Board) -> None:
        empty = [i for i, v in enumerate(b.board) if not v]
        if not empty:
            return
        i = self.rng.choice(empty)
        cells = list(b.board)
        cells[i] = 2 if self.rng.random() < 0.1 else 1
        b.board = tuple(cells)
        b.pop[i] = 0.14

    def _do(self, b: Board, d: str) -> bool:
        old = b.board
        nb = list(old)
        for idxs in LINES[d]:
            for i in idxs:
                nb[i] = 0
        moves: list[tuple[int, int, int]] = []
        merged: set[int] = set()
        gain = 0
        for idxs in LINES[d]:
            pos = 0
            for k, i in enumerate(idxs):
                v = old[i]
                if v == STONE:
                    nb[i] = STONE
                    pos = k + 1
                    continue
                if not v:
                    continue
                if pos > 0 and nb[idxs[pos - 1]] == v and idxs[pos - 1] not in merged:
                    dest = idxs[pos - 1]
                    nb[dest] = v + 1
                    merged.add(dest)
                    gain += 1 << (v + 1)
                else:
                    dest = idxs[pos]
                    nb[dest] = v
                    pos += 1
                moves.append((v, i, dest))
        new = tuple(nb)
        if new == old:
            return False
        b.board = new
        b.score += gain
        b.anim = moves
        b.anim_t = 0.1
        ramp = _ramp(self.sel.get("theme", self.settings.theme))
        ox, oy, cell = self._origin(b)
        for m in merged:
            b.pop[m] = 0.2
            r, c = divmod(m, 4)
            if new[m] >= 7:
                self.fx.burst(
                    self.rng,
                    ox + c * cell + cell // 2,
                    oy + r * cell + cell // 2,
                    ramp[min(12, new[m])],
                    8,
                    12,
                )
        big = max((new[m] for m in merged), default=0)
        self._spawn(b)
        if self.layout == "ffa":
            self._race_events(b, big)
        if not any(_apply(b.board, dd)[2] for dd in DIRS):
            self._stuck(b)
        self._score()
        return True

    def _race_events(self, b: Board, big: int) -> None:
        if b.top >= int(self.settings.race_target).bit_length() - 1:
            self.flash = 0.4
            self.result(winner_seat=b.seat, scores={x.seat: x.top for x in self.boards})
            return
        if big >= 6 and self.settings.junk:
            for o in self.boards:
                if o is not b and o.alive:
                    self._spawn(o)
                    if self.is_human(o.seat):
                        self.damage(0.4)
                    if not any(_apply(o.board, dd)[2] for dd in DIRS):
                        self._stuck(o)

    def _stuck(self, b: Board) -> None:
        if not b.alive or self.over:
            return
        b.alive = False
        if self.is_human(b.seat):
            self.damage(1.0)
        if self.layout == "solo":
            self.game_over()
            return
        if self.layout == "coop":
            self._score()
            self.result(text=f"{b.score}", scores={})
            return
        ox, oy, _cell = self._origin(b)
        self.fx.burst(self.rng, ox + 8, oy + 8, self.theme.e, 12, 12, 0.6)
        alive = [x for x in self.boards if x.alive]
        if len(alive) == 1:
            self.result(winner_seat=alive[0].seat, scores={x.seat: x.top for x in self.boards})
        elif not alive:
            best = max(self.boards, key=lambda x: (x.top, x.score))
            self.result(winner_seat=best.seat, scores={x.seat: x.top for x in self.boards})

    def _score(self) -> None:
        self.score = self.boards[0].score

    def _ai(self, b: Board) -> str | None:
        valid = [(d, *_apply(b.board, d)) for d in DIRS]
        valid = [v for v in valid if v[3]]
        if not valid:
            return None
        if self.rng.random() < (1 - self.skill) * 0.3:
            return self.rng.choice(valid)[0]
        samples_n = 4 if len(self.boards) == 1 else 2
        best_d, best_v = valid[0][0], -1.0
        for d, nb, gain, _moved in valid:
            empty = [i for i, v in enumerate(nb) if not v]
            samples = empty if len(empty) <= samples_n else self.rng.sample(empty, samples_n)
            tot = 0.0
            for i in samples:
                sb = list(nb)
                sb[i] = 1
                sbt = tuple(sb)
                best2 = 0.0
                for d2 in DIRS:
                    b2, _g, mv = _apply(sbt, d2)
                    if mv:
                        best2 = max(best2, _heur(b2))
                tot += best2
            val = tot / max(1, len(samples)) + gain
            if val > best_v:
                best_d, best_v = d, val
        return best_d

    # ---- input
    def key_p(self, k: str, player: int) -> None:
        if k not in LINES:
            return
        if self.layout == "coop":
            if player != self.turn:
                return
            b = self.boards[0]
        else:
            b = next((x for x in self.boards if x.seat == player), None)
            if b is None:
                return
        if b.alive and len(b.pending) < 3:
            b.pending.append(k)

    def update(self, dt: float) -> None:
        for b in self.boards:
            if self.over:
                return
            self._tick_board(b, dt)

    def _tick_board(self, b: Board, dt: float) -> None:
        b.anim_t = max(0.0, b.anim_t - dt)
        for k in list(b.pop):
            b.pop[k] -= dt
            if b.pop[k] <= 0:
                del b.pop[k]
        if b.anim_t > 0 or not b.alive:
            return
        seat = self.turn if self.layout == "coop" else b.seat
        if b.pending:
            if self._do(b, b.pending.pop(0)):
                self._next_turn()
            return
        human = self.is_human(seat)
        if self.layout == "coop":
            self.turn_t += dt
            if human and self.turn_t < 8.0:  # a person gets 8 s for their move, then the AI helps out
                return
        elif human:
            return
        b.move_t -= dt
        if b.move_t <= 0:
            b.move_t = 0.32 if self.layout == "solo" else 0.45
            d = self._ai(b)
            if d is None:
                self._stuck(b)
            elif self._do(b, d):
                self._next_turn()

    def _next_turn(self) -> None:
        if self.layout != "coop":
            return
        i = self.turn_seats.index(self.turn) if self.turn in self.turn_seats else 0
        self.turn = self.turn_seats[(i + 1) % len(self.turn_seats)]
        self.turn_t = 0.0

    # ---- draw
    def _origin(self, b: Board) -> tuple[int, int, int]:
        """(x, y, cell pitch) of a board on the panel."""
        if len(self.boards) == 1:
            return 0, 0, 8
        i = self.boards.index(b)
        if len(self.boards) == 2:
            return i * 16, 8, 4
        return (i % 2) * 16, (i // 2) * 16, 4

    def _tile(self, f: Frame, x: int, y: int, v: int, ramp: list[RGB], glow: float = 0.0) -> None:
        if v == STONE:
            self._stone(f, x, y, 7)
            return
        c = ramp[min(12, v)]
        if glow > 0:
            c = tint(c, min(0.6, glow * 3))
        f.rect(x, y, 7, 7, c)
        f.hline(x, y, 7, tint(c, 0.3))
        if not self.settings.numbers:
            return
        ink = WHITE if v <= 2 else BLACK
        n = 1 << v
        if n < 100:
            txt = str(n)
            w = 3 if n < 10 else 7
            f.text(x + (7 - w) // 2, y + 1, txt, ink)
        elif n >= 1024:
            f.text(x, y + 1, f"{n // 1024}K", ink)
        else:  # 128 / 256 / 512 → 1–3 cut-out pips
            k = v - 6
            for i in range(k):
                f.rect(x + 1 + i * 2 + (3 - k), y + 3, 1, 1, ink)

    def _stone(self, f: Frame, x: int, y: int, s: int) -> None:
        g = (150, 150, 165)
        f.rect(x, y, s, s, scale(g, 0.55))
        f.hline(x, y, s, g)
        f.vline(x, y, s, g)
        if s >= 7:
            f.set(x + 3, y + 3, scale(g, 0.3))
            f.set(x + 4, y + 2, scale(g, 0.3))

    def draw(self, f: Frame, now: float) -> None:
        tid = self.sel.get("theme", self.settings.theme)
        ramp = _ramp(tid)
        th = self.theme
        f.clear(th.bg)
        if len(self.boards) == 1:
            self._draw_big(f, self.boards[0], ramp, th)
            if self.layout == "coop":  # whose turn: an L of their colour along the bottom and right gaps
                col = self.colour_of(self.turn)
                if not self.is_human(self.turn):
                    col = scale(col, 0.5)
                f.hline(0, 31, 32, col)
                f.vline(31, 0, 32, col)
            return
        for b in self.boards:
            self._draw_small(f, b, ramp, th)
        if len(self.boards) == 2 and self.settings.show_score:
            goal = max(1, int(self.settings.race_target).bit_length() - 1)
            for b in self.boards:
                ox, _oy, _ = self._origin(b)
                col = self.colour_of(b.seat)
                w = max(1, round(14 * min(1.0, b.top / goal)))
                f.hline(ox + 1, 3, 14, scale(col, 0.2))
                f.hline(ox + 1, 3, w, col)
                f.hline(ox + 1, 4, w, scale(col, 0.6))
                txt = str(1 << b.top) if b.top else "0"
                f.text(ox + (15 - len(txt) * 4) // 2 + 1, 26, txt, scale(th.hud, 0.8 if b.alive else 0.35))

    def _draw_big(self, f: Frame, b: Board, ramp: list[RGB], th: Theme) -> None:
        for i in range(16):
            r, c = divmod(i, 4)
            f.rect(c * 8, r * 8, 7, 7, scale(th.w, 0.16))
        if b.anim_t > 0 and b.anim:
            k = 1 - b.anim_t / 0.1
            for i in STONE_CELLS if STONE in b.board else ():
                r, c = divmod(i, 4)
                self._stone(f, c * 8, r * 8, 7)
            for v, a, dst in b.anim:
                ar, ac = divmod(a, 4)
                br, bc = divmod(dst, 4)
                x = round((ac + (bc - ac) * k) * 8)
                y = round((ar + (br - ar) * k) * 8)
                self._tile(f, x, y, v, ramp)
            return
        for i, v in enumerate(b.board):
            if not v:
                continue
            r, c = divmod(i, 4)
            p = b.pop.get(i, 0.0)
            if v == STONE:
                self._stone(f, c * 8, r * 8, 7)
            elif p > 0.14:  # merge pop
                self._tile(f, c * 8, r * 8, v, ramp, glow=p)
            elif p > 0:  # spawn grows in
                s = 7 - round(p / 0.14 * 5)
                o = (7 - s) // 2
                f.rect(c * 8 + o, r * 8 + o, s, s, ramp[min(12, v)])
            else:
                self._tile(f, c * 8, r * 8, v, ramp)

    def _draw_small(self, f: Frame, b: Board, ramp: list[RGB], th: Theme) -> None:
        ox, oy, cell = self._origin(b)
        seat_col = self.colour_of(b.seat)
        empty = scale(seat_col, 0.18)
        k = 1.0 if b.alive else 0.35
        for i, v in enumerate(b.board):
            r, c = divmod(i, 4)
            x, y = ox + c * cell, oy + r * cell
            if v == STONE:
                self._stone(f, x, y, 3)
            elif v:
                col = ramp[min(12, v)]
                if b.pop.get(i, 0.0) > 0.14:
                    col = tint(col, 0.5)
                f.rect(x, y, 3, 3, scale(col, k))
            else:
                f.rect(x, y, 3, 3, scale(empty, k))

    def status(self) -> dict[str, Any]:
        st = super().status()
        if self.layout == "ffa":
            st["tops"] = {str(b.seat): 1 << b.top if b.top else 0 for b in self.boards}
        elif self.layout == "coop":
            st["turn"] = self.turn
        return st
