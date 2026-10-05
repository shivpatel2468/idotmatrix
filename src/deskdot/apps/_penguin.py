"""Penguin Escape — the puzzle rules, the levels and the BFS solver (pure Python, no drawing).

Original game design, levels and code. The board is 8 × 7 tiles; anything off the board is a wall.
Everything is turn-based and deterministic, so the same rules drive the game, the demo AI and the tests:

* **Snow** (`.`): one step per press. **Ice** (`_`): you keep sliding until something stops you (a wall, a
  block, a closed door, the edge, or a snow tile you slide onto). Fish and keys are picked up on the way.
* **Water** (`~`): sliding or stepping in is a splash (retry). An ice **block** pushed into water fills the hole
  (it becomes solid slush you can walk on).
* **Blocks** (`B`/`b`): walk into one to shove it; it slides over ice like you do and stops one tile into snow.
  Blocks never enter a keeper's walkway, fish, keys, doors or the exit, and they block a keeper's view.
* **Keys** (`K`/`k`) open **doors** (`D`); each key opens one door and you stop in the doorway.
* **Keepers** (`G`/`g`) follow a fixed script, one step per move of yours. Each sees 3 tiles ahead of itself
  (walls, doors and blocks block the view). End a move in view — or bump into a keeper — and you're caught.
  Sliding *past* a keeper's gaze is fine: you're too quick to spot.
* **Exit** (`E`): reach it to escape. Every level has three fish; each fish is a star.

Keeper scripts are strings run in a loop, one character per turn: `U D L R` move (and face that way),
`u d l r` only turn, `.` waits. The puzzle state carries the turn number modulo the scripts' common period.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

COLS, ROWS = 8, 7
VISION = 3
DIRS: dict[str, tuple[int, int]] = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_SCRIPT_DIR = {"U": "up", "D": "down", "L": "left", "R": "right"}
_TURN_DIR = {"u": "up", "d": "down", "l": "left", "r": "right"}

WALL, SNOW, ICE, WATER, EXIT, DOOR = "#", ".", "_", "~", "E", "D"
# grid character → (floor, object)
_CELL: dict[str, tuple[str, str | None]] = {
    "#": (WALL, None),
    ".": (SNOW, None),
    "_": (ICE, None),
    "~": (WATER, None),
    "E": (EXIT, None),
    "D": (DOOR, None),
    "S": (SNOW, "start"),
    "s": (ICE, "start"),
    "F": (SNOW, "fish"),
    "f": (ICE, "fish"),
    "K": (SNOW, "key"),
    "k": (ICE, "key"),
    "B": (SNOW, "block"),
    "b": (ICE, "block"),
    "G": (SNOW, "guard"),
    "g": (ICE, "guard"),
}


@dataclass(frozen=True)
class Level:
    name: str
    rows: tuple[str, ...]
    guards: tuple[str, ...] = ()  # one script per G/g, in reading order
    par: int = 30  # move budget: the 3-star solution fits in this many moves (tests check it)
    demo: str = ""  # the shortest 3-star solution (u/d/l/r), found by `solve` — the demo AI plays it


# State: (pos, fish_mask, keys_mask, doors_mask, blocks, filled_mask, turn)
State = tuple[int, int, int, int, frozenset[int], int, int]


@dataclass
class Result:
    """What one move did (for animation): outcome, the tiles the penguin crossed, and a shoved block."""

    state: State
    outcome: str  # "bump" | "move" | "push" | "fall" | "caught" | "win"
    path: tuple[int, ...]
    block: tuple[int, ...] = ()  # tiles the block crossed (first = where it was)
    sank: bool = False  # the block filled a water hole
    caught_by: int = -1  # keeper index


def _pop(n: int) -> int:
    return bin(n).count("1")


class Puzzle:
    """A compiled level: static floor, item positions and the keepers' timeline."""

    def __init__(self, level: Level) -> None:
        self.level = level
        if len(level.rows) != ROWS or any(len(r) != COLS for r in level.rows):
            raise ValueError(f"level {level.name!r} must be {COLS}×{ROWS}")
        floor: list[str] = []
        self.fish: list[int] = []
        self.keys: list[int] = []
        self.doors: list[int] = []
        blocks: list[int] = []
        guards: list[int] = []
        start = -1
        for y, row in enumerate(level.rows):
            for x, ch in enumerate(row):
                i = y * COLS + x
                fl, obj = _CELL[ch]
                floor.append(fl)
                if fl == DOOR:
                    self.doors.append(i)
                if obj == "start":
                    start = i
                elif obj == "fish":
                    self.fish.append(i)
                elif obj == "key":
                    self.keys.append(i)
                elif obj == "block":
                    blocks.append(i)
                elif obj == "guard":
                    guards.append(i)
        if start < 0:
            raise ValueError(f"level {level.name!r} has no start")
        if len(guards) != len(level.guards):
            raise ValueError(f"level {level.name!r}: {len(guards)} keepers, {len(level.guards)} scripts")
        self.floor = tuple(floor)
        self.exit = floor.index(EXIT)
        self.water = tuple(i for i, c in enumerate(floor) if c == WATER)
        self.fish_idx = {p: n for n, p in enumerate(self.fish)}
        self.key_idx = {p: n for n, p in enumerate(self.keys)}
        self.door_idx = {p: n for n, p in enumerate(self.doors)}
        self.water_idx = {p: n for n, p in enumerate(self.water)}
        self.all_fish = (1 << len(self.fish)) - 1
        self.period = 1
        for s in level.guards:
            self.period = self.period * len(s) // math.gcd(self.period, len(s))
        # timeline[t] = ((pos, facing), ...) per keeper, for t in 0..period-1 (the position *at* turn t)
        tracks: list[list[tuple[int, str]]] = []
        self.route: set[int] = set()
        for g, script in zip(guards, level.guards, strict=True):
            face = next(
                (
                    _SCRIPT_DIR.get(c) or _TURN_DIR.get(c)
                    for c in script
                    if c in _SCRIPT_DIR or c in _TURN_DIR
                ),
                "down",
            )
            pos, track = g, []
            for t in range(self.period):
                track.append((pos, face))
                self.route.add(pos)
                c = script[t % len(script)]
                if c in _SCRIPT_DIR:
                    face = _SCRIPT_DIR[c]
                    nxt = self.nb(pos, face)
                    if nxt < 0 or self.floor[nxt] == WALL:
                        raise ValueError(f"level {level.name!r}: keeper walks into a wall")
                    pos = nxt
                elif c in _TURN_DIR:
                    face = _TURN_DIR[c]
            if pos != g:
                raise ValueError(f"level {level.name!r}: keeper script does not loop")
            tracks.append(track)
        self.timeline: tuple[tuple[tuple[int, str], ...], ...] = tuple(
            tuple(tr[t] for tr in tracks) for t in range(self.period)
        )
        self.start: State = (start, 0, 0, 0, frozenset(blocks), 0, 0)

    # ------------------------------------------------------------- geometry
    @staticmethod
    def nb(i: int, d: str) -> int:
        """The neighbour of tile `i` in direction `d`, or -1 off the board."""
        dx, dy = DIRS[d]
        x, y = i % COLS + dx, i // COLS + dy
        if 0 <= x < COLS and 0 <= y < ROWS:
            return y * COLS + x
        return -1

    def keepers(self, t: int) -> tuple[tuple[int, str], ...]:
        return self.timeline[t % self.period] if self.timeline else ()

    def _opaque(self, i: int, doors: int, blocks: frozenset[int]) -> bool:
        fl = self.floor[i]
        if fl == WALL or i in blocks:
            return True
        return fl == DOOR and not doors >> self.door_idx[i] & 1

    def sight(self, t: int, doors: int, blocks: frozenset[int]) -> list[list[int]]:
        """Per keeper: the tiles it watches at turn `t` (its own tile first)."""
        out = []
        for pos, face in self.keepers(t):
            seen = [pos]
            cur = pos
            for _ in range(VISION):
                cur = self.nb(cur, face)
                if cur < 0 or self._opaque(cur, doors, blocks):
                    break
                seen.append(cur)
            out.append(seen)
        return out

    def _spotted(self, pos: int, t: int, doors: int, blocks: frozenset[int]) -> int:
        for n, seen in enumerate(self.sight(t, doors, blocks)):
            if pos in seen:
                return n
        return -1

    def held_keys(self, st: State) -> int:
        return _pop(st[2]) - _pop(st[3])

    # ------------------------------------------------------------- rules
    def _block_free(self, i: int, st: State) -> bool:
        if i < 0:
            return False
        fl = self.floor[i]
        if fl in (WALL, DOOR, EXIT) or i in st[4] or i in self.route:
            return False
        if i in self.fish_idx and not st[1] >> self.fish_idx[i] & 1:
            return False
        return not (i in self.key_idx and not st[2] >> self.key_idx[i] & 1)

    def _wet(self, i: int, filled: int) -> bool:
        return self.floor[i] == WATER and not filled >> self.water_idx[i] & 1

    def step(self, st: State, d: str) -> Result:
        """Apply one move. A bump (nothing moves) returns the same state."""
        pos, fish, keys, doors, blocks, filled, t = st
        guards_now = {p: n for n, (p, _f) in enumerate(self.keepers(t))}
        first = self.nb(pos, d)
        if first < 0:
            return Result(st, "bump", (pos,))
        if first in blocks:  # shove the block
            if not self._block_free(self.nb(first, d), st) or self.nb(first, d) in guards_now:
                return Result(st, "bump", (pos,))
            trail = [first]
            cur = first
            sank = False
            while True:
                n = self.nb(cur, d)
                if not self._block_free(n, st) or n in guards_now:
                    break
                cur = n
                trail.append(cur)
                if self._wet(cur, filled):
                    sank = True
                    break
                if self.floor[cur] != ICE:
                    break
            nb_ = set(blocks)
            nb_.discard(first)
            if sank:
                filled |= 1 << self.water_idx[cur]
            else:
                nb_.add(cur)
            new: State = (pos, fish, keys, doors, frozenset(nb_), filled, t)
            return self._after(new, "push", (pos,), tuple(trail), sank)
        path = [pos]
        cur = pos
        while True:
            n = self.nb(cur, d)
            if n < 0 or self.floor[n] == WALL or n in blocks:
                break
            if self.floor[n] == DOOR and not doors >> self.door_idx[n] & 1:
                if _pop(keys) - _pop(doors) <= 0:
                    break
                doors |= 1 << self.door_idx[n]
                cur = n
                path.append(cur)
                break
            if n in guards_now:
                path.append(n)
                new = (pos, fish, keys, doors, blocks, filled, t)
                return Result(new, "caught", tuple(path), caught_by=guards_now[n])
            cur = n
            path.append(cur)
            if self._wet(cur, filled):
                return Result((cur, fish, keys, doors, blocks, filled, t), "fall", tuple(path))
            if cur in self.fish_idx:
                fish |= 1 << self.fish_idx[cur]
            if cur in self.key_idx:
                keys |= 1 << self.key_idx[cur]
            if cur == self.exit:
                return Result((cur, fish, keys, doors, blocks, filled, t), "win", tuple(path))
            if self.floor[cur] != ICE:
                break
        if cur == pos:
            return Result(st, "bump", (pos,))
        return self._after((cur, fish, keys, doors, blocks, filled, t), "move", tuple(path))

    def _after(
        self, st: State, outcome: str, path: tuple[int, ...], block: tuple[int, ...] = (), sank: bool = False
    ) -> Result:
        """End of a move: spotted where you stopped? Then the keepers take their step and look again."""
        pos, fish, keys, doors, blocks, filled, t = st
        n = self._spotted(pos, t, doors, blocks)
        if n >= 0:
            return Result(st, "caught", path, block, sank, n)
        t2 = (t + 1) % self.period
        st2: State = (pos, fish, keys, doors, blocks, filled, t2)
        n = self._spotted(pos, t2, doors, blocks)
        if n >= 0:
            return Result(st2, "caught", path, block, sank, n)
        return Result(st2, outcome, path, block, sank)

    def stars(self, st: State) -> int:
        return _pop(st[1])


# ------------------------------------------------------------------------------ solver
def solve_iter(
    pz: Puzzle, start: State, all_fish: bool = True, limit: int = 400_000, chunk: int = 200
) -> Iterator[list[str] | None]:
    """Breadth-first search for the shortest winning move list. A generator so callers can time-slice it:
    it yields None every `chunk` expansions and finally yields the plan (or [] when there is none)."""
    want = pz.all_fish if all_fish else 0
    parent: dict[State, tuple[State, str] | None] = {start: None}
    q: deque[State] = deque([start])
    n = 0
    while q:
        st = q.popleft()
        for d in DIRS:
            r = pz.step(st, d)
            if r.outcome == "win":
                if r.state[1] & want != want:
                    continue
                plan = [d]
                cur = st
                while parent[cur] is not None:
                    prev, dd = parent[cur]  # type: ignore[misc]
                    plan.append(dd)
                    cur = prev
                plan.reverse()
                yield plan
                return
            if r.outcome not in ("move", "push") or r.state in parent:
                continue
            parent[r.state] = (st, d)
            q.append(r.state)
        n += 1
        if n >= limit:
            break
        if n % chunk == 0:
            yield None
    yield []


def solve(pz: Puzzle, start: State | None = None, all_fish: bool = True) -> list[str]:
    plan: list[str] | None = None
    for plan in solve_iter(pz, pz.start if start is None else start, all_fish):
        if plan is not None:
            break
    return plan or []


# ------------------------------------------------------------------------------ levels
# Every level: 8 columns × 7 rows, one start (S/s), one exit (E), three fish (F/f).
LEVELS: tuple[Level, ...] = (
    Level(
        "First Steps",
        (
            "S..#..F.",
            ".#.#.##.",
            ".#.....#",
            ".##F##..",
            "......#.",
            "#F###...",
            "......#E",
        ),
        par=33,
        demo="ddddrdurruuruurrllddrrdrddd",
    ),
    Level(
        "Thin Ice",
        (
            "S____._F",
            "_####_#_",
            "_#..._#.",
            "_#.##_#_",
            "_.f__.#_",
            "#_####._",
            "F______E",
        ),
        par=12,
        demo="rrldldlr",
    ),
    Level(
        "Skating Rink",
        (
            ".#_____#",
            "_._##___",
            "__#S#_._",
            "_F#____#",
            "____.__.",
            "___.____",
            "__F_.f_E",
        ),
        par=20,
        demo="ddruuruuldlddrrr",
    ),
    Level(
        "Holes in the Ice",
        (
            "f#___...",
            "__~##~#_",
            "__E.#~._",
            "..___#_.",
            ".._____~",
            "_____F.#",
            "._.S#._F",
        ),
        par=22,
        demo="lluuudrrdrdrluldru",
    ),
    Level(
        "Ice Cubes",
        (
            "_.._#._#",
            "#_S__B_F",
            "...#_.#.",
            "##.___.#",
            "_..#__.#",
            "#__#_._.",
            "._f.BFE.",
        ),
        par=25,
        demo="dddduuuurdruuurldddr",
    ),
    Level(
        "Bridge Builder",
        (
            "_~__B.FS",
            "f#~~#_~#",
            ".~~__B.~",
            ".#~_~.~#",
            "__#___.~",
            "##_F..~E",
            "_~._#~~~",
        ),
        par=30,
        demo="lllllldurrrddddddldrrrrr",
    ),
    Level(
        "Lock and Key",
        (
            "#_F_#._#",
            "....#.#.",
            "_##D_#_.",
            "#..#K#.#",
            "._.S_#_f",
            "#..__._.",
            "_._E##f.",
        ),
        par=30,
        demo="ruuluuldrdrddrruldrulldr",
    ),
    Level(
        "Night Shift",
        (
            ".###...f",
            ".#.....#",
            "...#....",
            "..E#S...",
            "##.....F",
            "..G..#..",
            "..#F...#",
        ),
        guards=("drul",),
        par=32,
        demo="uuudurrrlddddrdldllluurllu",
    ),
    Level(
        "Quick Skater",
        (
            "#__.__S.",
            "_____.#_",
            "__F#.__.",
            "#.#__f._",
            "_#__.#._",
            "...#._E.",
            "FG__.#__",
        ),
        guards=("RRRLLL",),
        par=32,
        demo="ldudldrurdrdldldlldurrurdr",
    ),
    Level(
        "Blind Spot",
        (
            "_..__#.#",
            "...#.f..",
            ".#......",
            "_#..G.#.",
            "#_S..#F.",
            "fB..#...",
            "_.E..._.",
        ),
        guards=("uudd",),
        par=37,
        demo="lddlrrrdrrururuulludrrddddllll",
    ),
    Level(
        "Two Keepers",
        (
            "#_..##._",
            "__#._.._",
            "_#.F__#f",
            "__G..._#",
            "___.__S_",
            ".F_..##_",
            "G___.E__",
        ),
        guards=("RLRL", "ludr"),
        par=40,
        demo="ldulururrddurrurduldllulldldrdrr",
    ),
    Level(
        "Cold Storage",
        (
            "_#~~~#E_",
            "K_~_.~~.",
            "D_.#_.~~",
            "__#.Fb__",
            "_B_~~_~_",
            "_F~~_.#.",
            "_F____S_",
        ),
        par=42,
        demo="llurulddruuluurrrdruldldrrruuuuuul",
    ),
    Level(
        "Feeding Time",
        (
            "___....F",
            "_###E_S#",
            "__.#_.G#",
            "#.___._#",
            "_#G...#f",
            "_._.D.._",
            ".K_#f...",
        ),
        guards=("rrll", "RRLL"),
        par=45,
        demo="urllddlurddlurrdrrrudlulllldruulurrd",
    ),
    Level(
        "The Big Melt",
        (
            "._____f#",
            "#_f~F~b_",
            "._.#..B_",
            "___~~._.",
            "~~.#_~._",
            "E.S#_~._",
            "~_B_.~.#",
        ),
        par=45,
        demo="uuudddldrrrrrrruruulllurdrddldlllull",
    ),
    Level(
        "Searchlights",
        (
            "_.._#f._",
            ".___#f._",
            "#..._#_.",
            "_..#SEb.",
            "_#.G..._",
            "F..___G_",
            "..___._#",
        ),
        guards=("rrll", "UUUDDD"),
        par=50,
        demo="ududulldlldrrrruuulldudurrdudddlluuurrdr",
    ),
    Level(
        "Great Escape",
        (
            "~G#.~___",
            "_B.E#.#.",
            "#~__#_..",
            "~._..~k.",
            "_.____._",
            "BD_~FS#_",
            "~F#._F.G",
        ),
        guards=("DDDUUU", "uudd"),
        par=55,
        demo="duldlrululldruluurddldlldddruuruluurddldluru",
    ),
)

_PUZZLES: dict[int, Puzzle] = {}


def puzzle(n: int) -> Puzzle:
    """The compiled level `n` (0-based), cached."""
    pz = _PUZZLES.get(n)
    if pz is None:
        pz = _PUZZLES[n] = Puzzle(LEVELS[n])
    return pz
