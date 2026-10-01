"""Bonus games: Minesweeper auto-solver and a vertical space shooter. Original code and art."""

from __future__ import annotations

import math
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, Sprite, scale
from .games_core import WHITE, GameApp, GameSettings, Mode, Theme, approach, clamp, tint

# =====================================================================================================
# Mines — 10×10 board of 3×3 px cells; numbers drawn as dice pips in the number's colour
# =====================================================================================================
MN = 10
PIPS = {
    1: [(1, 1)],
    2: [(0, 0), (2, 2)],
    3: [(0, 0), (1, 1), (2, 2)],
    4: [(0, 0), (2, 0), (0, 2), (2, 2)],
    5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)],
    6: [(0, 0), (0, 1), (0, 2), (2, 0), (2, 1), (2, 2)],
    7: [(0, 0), (0, 1), (0, 2), (2, 0), (2, 1), (2, 2), (1, 1)],
    8: [(0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2)],
}
NUM_COLORS: dict[int, RGB] = {
    1: (40, 120, 255),
    2: (40, 220, 60),
    3: (255, 40, 40),
    4: (190, 60, 255),
    5: (255, 140, 0),
    6: (0, 220, 220),
    7: (255, 255, 255),
    8: (255, 90, 180),
}

Cell = tuple[int, int]


def _field(map_id: str) -> frozenset[Cell]:
    """The cells of each field shape (the 10 × 10 square minus holes)."""
    cells = {(x, y) for x in range(MN) for y in range(MN)}
    if map_id == "donut":
        cells -= {(x, y) for x in range(3, 7) for y in range(3, 7)}
    elif map_id == "cross":
        cells -= {(x, y) for x in range(MN) for y in range(MN) if (x < 3 or x > 6) and (y < 3 or y > 6)}
    return frozenset(cells)


FIELDS = {m: _field(m) for m in ("square", "donut", "cross")}


class MinesSettings(GameSettings):
    mines: int = Field(14, ge=6, le=25, title="Mines")
    lives: int = Field(
        3,
        ge=1,
        le=5,
        title="Co-op lives",
        description="Mines the team can survive in co-op",
        json_schema_extra={"group": "Game"},
    )
    stun: float = Field(
        2.5,
        ge=1.0,
        le=6.0,
        title="Race: stun after a mine (s)",
        json_schema_extra={"group": "Game"},
    )


MINES_THEMES: dict[str, Theme] = {
    "field": Theme(
        p=(130, 255, 210),
        e=(255, 160, 50),  # flags
        x=(255, 240, 130),
        w=(100, 130, 80),  # turf over hidden cells
        hud=(230, 255, 220),
        bg=(1, 4, 1),
        r=(
            (120, 200, 255),
            (150, 255, 120),
            (255, 130, 120),
            (230, 160, 255),
            (255, 200, 90),
            (100, 255, 240),
            (255, 255, 255),
        ),
    ),
    "frost": Theme(
        p=(150, 255, 230),
        e=(255, 130, 170),
        x=(255, 250, 170),
        w=(110, 140, 185),  # snow over hidden cells
        hud=(220, 240, 255),
        bg=(1, 2, 8),
        r=(
            (120, 210, 255),
            (150, 255, 150),
            (255, 140, 140),
            (230, 170, 255),
            (255, 200, 100),
            (120, 255, 240),
            (255, 255, 255),
        ),
    ),
}


@register
class Mines(GameApp):
    id = "mines"
    name = "Mines"
    description = (
        "Minesweeper that solves itself with logic (and the odd guess). Arrows move the cursor, "
        "A reveals, B flags. Up to four players sweep one field together (co-op) or race for cells."
    )
    icon = "bomb"
    Settings = MinesSettings
    over_hold = 2.5
    max_players = 4
    controls = ("dpad", "gamepad", "keyboard")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("coop", "Co-op", 2, 4, "coop"),
        Mode("race", "Race", 2, 4, "ffa"),
    )
    maps: ClassVar[dict[str, str]] = {"square": "Square", "donut": "Donut", "cross": "Cross"}
    game_themes: ClassVar[dict[str, Theme]] = MINES_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"field": "Field", "frost": "Frost"}

    def new_game(self) -> None:
        self.wins = 0
        self.rules = self.play_mode.id if self.roster else "classic"
        self.cells = FIELDS.get(self.map_id, FIELDS["square"])
        self.lives = self.settings.lives
        self._board()

    def _board(self) -> None:
        self.mines: set[Cell] = set()
        self.shown: set[Cell] = set()
        self.flags: set[Cell] = set()
        self.blown: set[Cell] = set()  # co-op / race: mines that went off (they stay on the field, flagged)
        self.ver = 0  # bumps on every change: the shared solver result is cached per version
        self._solved: tuple[int, list[tuple[str, Cell]]] = (-1, [])
        seats = sorted(self.roster) if self.rules != "classic" else [1]
        start = [
            (MN // 2, MN // 2),
            (MN // 2 - 1, MN // 2 - 1),
            (MN // 2, MN // 2 - 1),
            (MN // 2 - 1, MN // 2),
        ]
        self.cur: dict[int, dict[str, Any]] = {}
        for i, seat in enumerate(seats):
            x, y = start[i % 4]
            self.cur[seat] = {
                "x": x,
                "y": y,
                "fx": float(x),
                "fy": float(y),
                "act": 0.4 + 0.2 * i,
                "op": None,
                "stun": 0.0,
            }
        self.pts = dict.fromkeys(seats, 0)
        self.won_t = 0.0
        self.boom: Cell | None = None

    # the host's cursor (seat 1), kept as attributes for the single-player code paths
    @property
    def cx(self) -> int:
        return int(self.cur[1]["x"])

    @property
    def cy(self) -> int:
        return int(self.cur[1]["y"])

    def _nb(self, c: Cell) -> list[Cell]:
        x, y = c
        return [
            (x + dx, y + dy)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if (dx or dy) and (x + dx, y + dy) in self.cells
        ]

    def _count(self, c: Cell) -> int:
        return sum(1 for n in self._nb(c) if n in self.mines)

    def _lay(self, safe: Cell) -> None:
        keep_out = {safe, *self._nb(safe)}
        cells = sorted(c for c in self.cells if c not in keep_out)
        self.mines = set(self.rng.sample(cells, min(self.settings.mines, len(cells) // 3)))

    def _reveal(self, c: Cell, seat: int = 1) -> None:
        if c in self.shown or c in self.flags or c not in self.cells:
            return
        if not self.mines:
            self._lay(c)
        self.ver += 1
        if c in self.mines:
            self._mine(c, seat)
            return
        stack = [c]
        got = 0
        while stack:
            cur = stack.pop()
            if cur in self.shown:
                continue
            self.shown.add(cur)
            self.flags.discard(cur)
            got += 1
            if self._count(cur) == 0:
                stack.extend(n for n in self._nb(cur) if n not in self.shown)
        self.score += got
        if seat in self.pts:
            self.pts[seat] += got
        if got >= 6:  # a big opening: a little shimmer where it started
            self.fx.burst(self.rng, c[0] * 3 + 2.5, c[1] * 3 + 2.5, self.theme.x, 4, 7, 0.4)
        if len(self.shown) == len(self.cells) - len(self.mines):
            self._cleared()

    def _mine(self, c: Cell, seat: int) -> None:
        self.boom = c
        self.fx.burst(self.rng, c[0] * 3 + 2.5, c[1] * 3 + 2.5, (255, 120, 0), 20, 16, 0.9)
        self.fx.burst(self.rng, c[0] * 3 + 2.5, c[1] * 3 + 2.5, WHITE, 6, 8, 0.5)
        if self.is_human(seat):
            self.damage()
        if self.rules == "classic" or self.rules == "solo":
            self.game_over()
            return
        self.blown.add(c)  # the field survives: the mine is marked and play goes on
        self.flags.add(c)
        self.flash = 0.2
        if self.rules == "coop":
            self.lives -= 1
            if self.lives <= 0:
                self.result(text="BOOM", scores=dict(self.pts))
        else:
            self.cur[seat]["stun"] = float(self.settings.stun)
            self.pts[seat] = max(0, self.pts[seat] - 5)
        if len(self.shown) == len(self.cells) - len(self.mines) and not self.over:
            self._cleared()

    def _cleared(self) -> None:
        for _ in range(4):
            self.fx.burst(
                self.rng, self.rng.uniform(4, 28), self.rng.uniform(4, 28), self.theme.x, 6, 10, 0.8
            )
        self.flags = set(self.mines)
        if self.rules == "coop":
            self.score += 50
            self.result(text="CLEARED", scores=dict(self.pts))
        elif self.rules == "race":
            self.result(winner_seat=max(self.pts, key=lambda s: self.pts[s]), scores=dict(self.pts))
        else:
            self.wins += 1
            self.score += 50
            self.won_t = 1.6

    def _toggle_flag(self, c: Cell) -> None:
        if c in self.shown or c in self.blown or c not in self.cells:
            return
        self.ver += 1
        if c in self.flags:
            self.flags.discard(c)
        else:
            self.flags.add(c)

    # ------------------------------------------------------------------ AI
    def _solve(self) -> list[tuple[str, Cell]]:
        if not self.shown:
            mid = sorted(c for c in self.cells if 2 <= c[0] < MN - 2 and 2 <= c[1] < MN - 2)
            return [("open", self.rng.choice(mid or sorted(self.cells)))]
        flag: set[Cell] = set()
        safe: set[Cell] = set()
        constraints: list[tuple[frozenset[Cell], int]] = []
        for c in self.shown:
            n = self._count(c)
            if n == 0:
                continue
            hidden = [x for x in self._nb(c) if x not in self.shown and x not in self.flags]
            need = n - sum(1 for x in self._nb(c) if x in self.flags)
            if not hidden:
                continue
            if need == len(hidden):
                flag.update(hidden)
            elif need == 0:
                safe.update(hidden)
            constraints.append((frozenset(hidden), need))
        if not flag and not safe:
            # subset rule: A ⊂ B → B \ A holds need(B) - need(A) mines
            for a, na in constraints:
                for b, nb in constraints:
                    if a is b or not a < b:
                        continue
                    rest = b - a
                    if nb - na == 0:
                        safe.update(rest)
                    elif nb - na == len(rest):
                        flag.update(rest)
                if flag or safe:
                    break
        if self.rng.random() < (1 - self.skill) * 0.15 and not flag:
            safe = set()  # a lapse: guess even though logic had an answer
        if flag or safe:
            return [("flag", c) for c in sorted(flag)] + [("open", c) for c in sorted(safe)]
        # guess: the hidden cell with the lowest local mine estimate
        hidden_all = sorted(c for c in self.cells if c not in self.shown and c not in self.flags)
        if not hidden_all:
            return []
        remaining = max(0, len(self.mines) - len(self.flags))
        base = remaining / max(1, len(hidden_all))
        risk = dict.fromkeys(hidden_all, base)
        for cells, need in constraints:
            p = need / len(cells)
            for c in cells:
                risk[c] = max(risk[c], p) if risk[c] != base else p
        best = min(risk.values())
        choices = [c for c, r in risk.items() if r <= best + 1e-9]
        return [("open", self.rng.choice(choices))]

    def _plan(self) -> list[tuple[str, Cell]]:
        """The shared solver's answer for the current board (every AI seat reads the same cached plan)."""
        if self._solved[0] != self.ver:
            self._solved = (self.ver, self._solve())
        return self._solved[1]

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        cur = self.cur.get(player)
        if cur is None or self.won_t > 0 or cur["stun"] > 0:
            return
        d = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}.get(k)
        c = (cur["x"], cur["y"])
        if d:
            cur["x"] = int(clamp(cur["x"] + d[0], 0, MN - 1))
            cur["y"] = int(clamp(cur["y"] + d[1], 0, MN - 1))
        elif k == "a":
            self._reveal(c, player)
        elif k == "b":
            self._toggle_flag(c)

    def update(self, dt: float) -> None:
        for cur in self.cur.values():
            cur["fx"] = approach(cur["fx"], cur["x"], 14 * dt)
            cur["fy"] = approach(cur["fy"], cur["y"], 14 * dt)
            cur["stun"] = max(0.0, cur["stun"] - dt)
        if self.won_t > 0:
            self.won_t -= dt
            if self.won_t <= 0:
                self._board()
            return
        for seat, cur in self.cur.items():
            if self.over:
                return
            if not self.is_human(seat):
                self._ai(seat, cur, dt)

    def _ai(self, seat: int, cur: dict[str, Any], dt: float) -> None:
        if cur["stun"] > 0:
            return
        cur["act"] -= dt
        if cur["act"] > 0:
            return
        op = cur["op"]
        if op is None or (op[1] in self.shown) or (op[0] == "flag" and op[1] in self.flags):
            plan = [
                p
                for p in self._plan()
                if p[1] not in self.shown and not (p[0] == "flag" and p[1] in self.flags)
            ]
            if not plan:
                return
            if len(self.cur) > 1:  # several sweepers: each takes the job nearest to its own cursor
                plan.sort(key=lambda p: abs(p[1][0] - cur["x"]) + abs(p[1][1] - cur["y"]))
            op = cur["op"] = plan[0]
        kind, c = op
        if (cur["x"], cur["y"]) != c:
            # walk the cursor one cell towards the target
            cur["x"] += (c[0] > cur["x"]) - (c[0] < cur["x"])
            cur["y"] += (c[1] > cur["y"]) - (c[1] < cur["y"])
            cur["act"] = 0.05 if len(self.cur) == 1 else 0.05 + 0.1 * (1 - self.skill)
            return
        cur["op"] = None
        if kind == "open":
            self._reveal(c, seat)
            cur["act"] = 0.25
        else:
            if c not in self.flags:
                self._toggle_flag(c)
            cur["act"] = 0.15

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        classic = str(self.sel.get("theme", self.settings.theme)) == "classic"
        f.clear(th.bg)
        hidden_c = (70, 80, 110) if classic else scale(th.w, 0.9)
        hidden_hi = tint(hidden_c, 0.35)
        open_c = (14, 14, 22) if classic else scale(th.w, 0.12)
        show_mines = self.over or self.won_t > 0
        for x, y in self.cells:
            px, py = 1 + x * 3, 1 + y * 3
            c = (x, y)
            if c in self.shown:
                f.rect(px, py, 3, 3, open_c)
                n = self._count(c)
                if n:
                    col = NUM_COLORS[n] if classic else th.r[(n - 1) % len(th.r)]
                    for ox, oy in PIPS[n]:
                        f.set(px + ox, py + oy, col)
            elif (show_mines and c in self.mines) or c in self.blown:
                col = (255, 60, 0) if c == self.boom else (th.e if self.over or c in self.blown else th.x)
                f.rect(px, py, 3, 3, scale(col, 0.25))
                f.set(px + 1, py + 1, col)
                f.set(px + 1, py, col)
                f.set(px, py + 1, col)
                f.set(px + 2, py + 1, col)
                f.set(px + 1, py + 2, col)
            else:
                f.rect(px, py, 2, 2, hidden_c)
                f.set(px, py, hidden_hi)
                if c in self.flags:
                    f.rect(px, py, 2, 2, (255, 30, 40) if classic else th.e)
        # cursors: a blinking frame around each player's cell (seat colours when several sweep together)
        if not self.over and int(now * 5) % 3:
            for seat, cur in self.cur.items():
                if cur["stun"] > 0 and int(now * 8) % 2:
                    continue
                gx, gy = round(cur["fx"]), round(cur["fy"])
                solo_col = th.p if self.is_human(seat) else th.x
                col = self.colour_of(seat) if len(self.cur) > 1 else solo_col
                f.rect(gx * 3, gy * 3, 5, 5, col, fill=False)
        if self.rules == "coop":  # team lives down the right edge
            for i in range(self.lives):
                f.rect(31, 1 + i * 3, 1, 2, th.e)

    def status(self) -> dict[str, Any]:
        st = super().status()
        if self.rules != "classic":
            st["cells"] = {str(k): v for k, v in self.pts.items()}
        return st


# =====================================================================================================
# Starship — vertical shooter with swooping enemy waves
# =====================================================================================================
class StarshipSettings(GameSettings):
    lives: int = Field(3, ge=1, le=5, title="Lives")
    ace_time: int = Field(
        90,
        ge=30,
        le=240,
        title="Ace duel length (s)",
        description="Dogfight mode: most points when the clock runs out wins",
        json_schema_extra={"group": "Game"},
    )


SHIP5 = ["..#..", "..#..", ".###.", "##W##", "#.#.#"]
FOES = [
    ["#...#", "#####", ".#.#.", "..#.."],
    [".###.", "##.##", "#####", "#.#.#"],
    ["#.#.#", ".###.", "##.##", ".#.#."],
]
SHIP_Y = 26

STARSHIP_THEMES: dict[str, Theme] = {
    "void": Theme(
        p=(90, 230, 255),
        e=(255, 120, 200),
        x=(255, 230, 90),
        w=(120, 110, 150),  # rocks, canyon walls
        hud=(220, 230, 255),
        bg=(0, 0, 5),
        r=(
            (255, 120, 200),
            (255, 170, 80),
            (170, 255, 110),
            (130, 200, 255),
            (220, 160, 255),
            (255, 230, 90),
            (255, 255, 255),
        ),
    ),
    "solar": Theme(
        p=(120, 255, 160),
        e=(255, 150, 60),
        x=(255, 250, 170),
        w=(150, 95, 60),
        hud=(255, 225, 160),
        bg=(6, 2, 0),
        r=(
            (255, 150, 60),
            (255, 120, 170),
            (255, 230, 90),
            (150, 220, 255),
            (200, 255, 120),
            (255, 250, 170),
            (255, 255, 255),
        ),
    ),
}


@register
class Starship(GameApp):
    id = "starship"
    name = "Starship"
    description = (
        "A vertical space shooter: weave through swooping enemy waves. ←/→ move, auto-fire, A bomb. "
        "Fly with up to three wingmen (co-op, a downed ship is revived when the wave is cleared) or dogfight "
        "for points (Ace). Arenas: deep space, an asteroid belt and a narrow canyon."
    )
    icon = "plane"
    Settings = StarshipSettings
    step_hz = 30.0
    max_players = 4
    controls = ("joystick", "dpad", "tilt", "gamepad")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("coop", "Wingmen", 2, 4, "coop"),
        Mode("ace", "Ace", 2, 4, "ffa"),
    )
    maps: ClassVar[dict[str, str]] = {"deep": "Deep space", "rocks": "Asteroids", "canyon": "Canyon"}
    game_themes: ClassVar[dict[str, Theme]] = STARSHIP_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"void": "Void", "solar": "Solar"}

    def new_game(self) -> None:
        self.rules = self.play_mode.id if self.roster else "classic"
        self.arena = self.map_id if self.map_id in self.maps else "deep"
        seats = sorted(self.roster) if self.rules != "classic" else [1]
        n = len(seats)
        self.ships: dict[int, dict[str, Any]] = {}
        for i, seat in enumerate(seats):
            x = 13.5 if n == 1 else 3 + (i + 0.5) * 26 / n
            self.ships[seat] = {
                "x": x,
                "tx": x,
                "lives": self.settings.lives,
                "inv": 1.5,
                "cool": 0.1 * i,
                "alive": True,
                "pts": 0,
            }
        self.foes: list[dict[str, Any]] = []
        self.shots: list[list[float]] = []  # [x, y, seat]
        self.bolts: list[list[float]] = []
        self.rocks: list[list[float]] = []  # [x, y, hp]
        self.rock_t = 1.5
        self.scroll = 0.0
        self.wave = 0
        self.wave_t = 1.0
        self.bombs = 1
        self.clock = float(self.settings.ace_time)
        self.stars = [
            [self.rng.uniform(0, 32), self.rng.uniform(0, 32), self.rng.uniform(0.3, 1.0)] for _ in range(20)
        ]
        self._cache: dict[Any, Any] = {}

    # the host's ship, for the single-player code paths
    @property
    def x(self) -> float:
        return float(self.ships[min(self.ships)]["x"])

    @property
    def lives(self) -> int:
        return int(sum(s["lives"] for s in self.ships.values()))

    def _tid(self) -> str:
        return str(self.sel.get("theme", self.settings.theme))

    def _art(self) -> dict[str, Any]:
        key = self._tid()
        if key not in self._cache:
            th = self.theme
            if key == "classic":
                cols = [th.e, th.r[1], th.r[5]]
            elif key in self.game_themes:
                cols = [th.e, th.r[1], th.r[3]]  # never the rock colour: foes must not hide among the rocks
            else:
                cols = [th.e, th.x, th.w]
            self._cache[key] = {
                "foes": [Sprite.parse(rows, {"#": cols[i]}) for i, rows in enumerate(FOES)],
                "cols": cols,
            }
        return self._cache[key]

    def _ship_col(self, seat: int) -> RGB:
        return self.theme.p if len(self.ships) == 1 else self.colour_of(seat)

    def _ship_art(self, col: RGB) -> Sprite:
        key = ("ship", col)
        if key not in self._cache:
            self._cache[key] = Sprite.parse(SHIP5, {"#": col, "W": WHITE})
        return self._cache[key]

    def _gap(self, y: float) -> tuple[float, float]:
        """Canyon walls at row y: the open span (left, right)."""
        if self.arena != "canyon":
            return 0.0, 31.0
        ph = (y - self.scroll) * 0.3
        left = 2 + round(2.5 + 2.5 * math.sin(ph))
        right = 2 + round(2.5 + 2.5 * math.sin(ph + 2.1))
        return float(left), float(31 - right)

    def _spawn_wave(self) -> None:
        self.wave += 1
        kind = self.rng.randrange(3)
        n = 5 + min(4, self.wave // 2) + (len(self.ships) - 1) * 2
        pattern = self.rng.choice(("sine", "dive", "zig"))
        side = self.rng.random() < 0.5
        for i in range(n):
            self.foes.append(
                {
                    "kind": kind,
                    "pat": pattern,
                    "t": -i * 0.45,
                    "x0": self.rng.uniform(4, 22) if pattern == "dive" else (6.0 if side else 21.0),
                    "x": -10.0,
                    "y": -10.0,
                    "hp": 2 + (kind == 1) + self.wave // 4,
                    "fire": self.rng.uniform(0.6, 2.0),
                }
            )

    def _path(self, e: dict[str, Any]) -> tuple[float, float]:
        t = e["t"]
        sp = 7.0 + 0.6 * self.wave
        y = -5 + t * sp
        if e["pat"] == "sine":
            x = 13.5 + 11 * math.sin(t * 1.6 + (0 if e["x0"] < 13 else math.pi))
        elif e["pat"] == "zig":
            ph = (t * 0.8) % 2
            x = e["x0"] + (ph if ph < 1 else 2 - ph) * (13 if e["x0"] < 13 else -13)
        else:
            x = e["x0"] + 4 * math.sin(t * 3)
            y = -5 + t * sp * (0.6 if y < 10 else 1.4)
        return x, y

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        s = self.ships.get(player)
        if s is None or not s["alive"]:
            return
        if k in ("left", "right"):
            if abs(s["tx"] - s["x"]) > 6:
                s["tx"] = s["x"]
            s["tx"] = clamp(s["tx"] + (-3 if k == "left" else 3), 2, 29)
        elif k == "a":
            self._bomb(player)

    def _bomb(self, seat: int = 1) -> None:
        if self.bombs <= 0:
            return
        self.bombs -= 1
        self.flash = 0.4
        for e in list(self.foes):
            if e["y"] > -3:
                self._kill(e, seat)
        self.bolts = []

    def _kill(self, e: dict[str, Any], seat: int = 1) -> None:
        if e in self.foes:
            self.foes.remove(e)
        pts = 10 * (e["kind"] + 1)
        self.score += pts
        if seat in self.ships:
            self.ships[seat]["pts"] += pts
        self.fx.burst(self.rng, e["x"] + 2.5, e["y"] + 2, self._art()["cols"][e["kind"]], 9, 13, 0.5)
        if self.rng.random() < 0.04:
            self.bombs = min(3, self.bombs + 1)

    def _ai(self, seat: int, s: dict[str, Any]) -> None:
        # dodge bolts, rocks and foes heading for the ship; otherwise sit under a foe (wingmen spread out)
        x = s["x"]
        threats = [b[0] for b in self.bolts if b[1] > 16 and abs(b[0] - x) < 3.5]
        threats += [e["x"] + 2.5 for e in self.foes if e["y"] > 14 and abs(e["x"] + 2.5 - x) < 5]
        threats += [r[0] + 1 for r in self.rocks if r[1] > 13 and abs(r[0] + 1 - x) < 4.5]
        lo, hi = self._gap(SHIP_Y + 2)
        if threats and self.rng.random() < 0.55 + 0.45 * self.skill:
            tx = min(threats, key=lambda v: abs(v - x))
            away = 1 if tx <= x else -1
            if x > hi - 6:
                away = -1
            elif x < lo + 6:
                away = 1
            s["tx"] = clamp(x + away * 6, 2, 29)
            return
        live = [e for e in self.foes if -4 < e["y"] < 20]
        if live:
            if len(self.ships) == 1:
                e = max(live, key=lambda e: e["y"])
            else:
                lane = 3 + (sorted(self.ships).index(seat) + 0.5) * 26 / len(self.ships)
                e = min(live, key=lambda e: abs(e["x"] + 2.5 - lane) - 0.3 * e["y"])
            s["tx"] = clamp(e["x"] + 2.5, 2, 29)
        if len([e for e in self.foes if e["y"] > 12]) >= 4 and self.bombs:
            self._bomb(seat)

    def _hit(self, seat: int, s: dict[str, Any]) -> None:
        th = self.theme
        self.fx.burst(self.rng, s["x"], 28, self._ship_col(seat), 18, 15, 0.8)
        self.fx.burst(self.rng, s["x"], 28, WHITE, 6, 8, 0.4)
        s["inv"] = 2.0
        if self.is_human(seat):
            self.damage()
        if self.rules == "ace":  # dogfight: a hit costs points, never the ship
            s["pts"] = max(0, s["pts"] - 25)
            return
        self.bolts = [b for b in self.bolts if abs(b[0] - s["x"]) > 4]
        s["lives"] -= 1
        if s["lives"] <= 0:
            s["alive"] = False
            self.fx.burst(self.rng, s["x"], 28, th.x, 12, 18, 1.0)
            if not any(o["alive"] for o in self.ships.values()):
                if self.rules == "coop":
                    self.result(text=f"WAVE {self.wave}", scores={k: v["pts"] for k, v in self.ships.items()})
                else:
                    self.game_over()

    def update(self, dt: float) -> None:
        th = self.theme
        for st in self.stars:
            st[1] += 18 * st[2] * dt
            if st[1] > 32:
                st[1] -= 32
                st[0] = self.rng.uniform(0, 32)
        self.scroll += 8 * dt
        if self.rules == "ace":
            self.clock -= dt
            if self.clock <= 0:
                pts = {k: v["pts"] for k, v in self.ships.items()}
                self.result(winner_seat=max(pts, key=lambda k: pts[k]), scores=pts)
                return
        lo, hi = self._gap(SHIP_Y + 2)
        for seat, s in self.ships.items():
            if not s["alive"]:
                continue
            s["inv"] = max(0.0, s["inv"] - dt)
            if not self.is_human(seat):
                self._ai(seat, s)
            s["x"] = clamp(
                approach(s["x"], s["tx"], (20 + 8 * self.skill) * dt), max(2, lo + 2), min(29, hi - 2)
            )
            # auto-fire
            s["cool"] -= dt
            if s["cool"] <= 0:
                s["cool"] = 0.3
                self.shots.append([s["x"], 25.0, float(seat)])
        for sh in self.shots:
            sh[1] -= 40 * dt
        self.shots = [sh for sh in self.shots if sh[1] > -2]
        # waves
        if not self.foes:
            self.wave_t -= dt
            if self.wave_t <= 0:
                self._revive()
                self._spawn_wave()
                self.wave_t = 1.2
        for e in list(self.foes):
            e["t"] += dt
            if e["t"] < 0:
                continue
            e["x"], e["y"] = self._path(e)
            e["x"] -= 2.5
            e["fire"] -= dt
            if e["fire"] <= 0 and 0 < e["y"] < 20:
                e["fire"] = self.rng.uniform(1.4, 3.0) / (1 + 0.1 * self.wave)
                self.bolts.append([e["x"] + 2.5, e["y"] + 4])
            if e["y"] > 34:
                self.foes.remove(e)
                continue
            for sh in self.shots:
                if e["x"] - 0.5 <= sh[0] <= e["x"] + 5 and e["y"] <= sh[1] <= e["y"] + 4:
                    sh[1] = -10
                    e["hp"] -= 1
                    if e["hp"] <= 0:
                        self._kill(e, int(sh[2]))
                    else:
                        self.fx.burst(self.rng, sh[0], e["y"] + 3, WHITE, 2, 5, 0.2)
                    break
        for b in self.bolts:
            b[1] += (15 + self.wave) * dt
        self.bolts = [b for b in self.bolts if b[1] < 33]
        if self.arena == "rocks":
            self._rocks(dt)
        # hits on the ships
        for seat, s in self.ships.items():
            if not s["alive"] or s["inv"] > 0 or self.over:
                continue
            x = s["x"]
            hit = any(abs(b[0] - x) < 2 and 26 <= b[1] <= 31 for b in self.bolts)
            hit = hit or any(abs(e["x"] + 2.5 - x) < 3.5 and 23 < e["y"] < 31 for e in self.foes)
            for r in self.rocks:
                if abs(r[0] + 1 - x) < 3 and 23 < r[1] < 30:
                    r[2] = 0
                    hit = True
            if hit:
                self._hit(seat, s)
        for s in self.ships.values():
            if s["alive"] and (s["inv"] <= 0 or int(self._last * 8) % 2):
                self.fx.emit(s["x"] + self.rng.uniform(-0.6, 0.6), 31, 0, 10, th.x, 0.15)

    def _rocks(self, dt: float) -> None:
        self.rock_t -= dt
        if self.rock_t <= 0:
            self.rock_t = self.rng.uniform(1.6, 3.2)
            self.rocks.append([self.rng.uniform(2, 27), -3.0, 3.0])
        for r in self.rocks:
            r[1] += (5 + 0.3 * self.wave) * dt
            for sh in self.shots:
                if r[0] - 0.5 <= sh[0] <= r[0] + 3 and r[1] <= sh[1] <= r[1] + 3:
                    sh[1] = -10
                    r[2] -= 1
                    self.fx.burst(self.rng, sh[0], r[1] + 2, tint(self.theme.w, 0.4), 2, 5, 0.25)
                    if r[2] <= 0:
                        seat = int(sh[2])
                        self.score += 5
                        if seat in self.ships:
                            self.ships[seat]["pts"] += 5
                    break
        for r in self.rocks:
            if r[2] <= 0:
                self.fx.burst(self.rng, r[0] + 1.5, r[1] + 1.5, tint(self.theme.w, 0.3), 8, 10, 0.5)
        self.rocks = [r for r in self.rocks if r[2] > 0 and r[1] < 33]

    def _revive(self) -> None:
        """Co-op: a wave cleared brings downed wingmen back with one life."""
        if self.rules != "coop":
            return
        for s in self.ships.values():
            if not s["alive"]:
                s["alive"], s["lives"], s["inv"] = True, 1, 2.0
                self.fx.burst(self.rng, s["x"], 28, self.theme.x, 10, 10, 0.6)

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        art = self._art()
        if self._tid() in self.game_themes:
            f.clear(th.bg)
        for sx, sy, depth in self.stars:
            f.set(int(sx), int(sy), scale(WHITE, 0.15 + 0.45 * depth))
        if self.arena == "canyon":
            wall, edge = scale(th.w, 0.35), th.w
            for y in range(32):
                lo, hi = self._gap(y)
                f.hline(0, y, int(lo), wall)
                f.set(int(lo), y, edge)
                f.hline(int(hi) + 1, y, 31 - int(hi), wall)
                f.set(int(hi), y, edge)
        if self.flash > 0:
            f.dim(1.0)
            f.rect(0, 0, 32, 32, scale(th.x, self.flash))
        for r in self.rocks:  # 3 × 3 rocks with a lit corner; they crack (dim) as they take hits
            x, y = round(r[0]), round(r[1])
            c = scale(th.w, 0.6 + 0.4 * r[2] / 3)
            f.rect(x, y, 3, 3, c)
            f.set(x, y, tint(c, 0.4))
            f.set(x + 2, y + 2, scale(c, 0.6))
        for e in self.foes:
            if e["t"] >= 0:
                f.sprite(art["foes"][e["kind"]], round(e["x"]), round(e["y"]))
        for sh in self.shots:
            col = th.p if len(self.ships) == 1 else self._ship_col(int(sh[2]))
            f.vline(int(sh[0]), int(sh[1]), 2, tint(col, 0.5))
        for b in self.bolts:
            f.rect(int(b[0]), int(b[1]), 1, 2, th.e if int(now * 10) % 2 else th.x)
        for seat, s in self.ships.items():
            if not self.over and s["alive"] and (s["inv"] <= 0 or int(now * 10) % 2):
                f.sprite(self._ship_art(self._ship_col(seat)), round(s["x"]) - 2, SHIP_Y)
        if self.rules == "ace":
            self.hud(f, str(max(0, int(self.clock))), x=1, y=1)
            left = int(30 * max(0.0, self.clock) / max(1, self.settings.ace_time))
            f.hline(1, 31, left, scale(th.hud, 0.5))
            for i, seat in enumerate(sorted(self.ships)):  # points race: one bar per ship, top right
                w = min(8, self.ships[seat]["pts"] // 40)
                f.hline(30 - w, 1 + 2 * i, w + 1, self._ship_col(seat))
            return
        self.hud(f, str(self.score), x=1, y=1)
        if len(self.ships) == 1:
            s = self.ships[min(self.ships)]
            for i in range(s["lives"] - 1):
                f.rect(30 - 3 * i, 1, 2, 2, th.p)
        else:
            for i, seat in enumerate(sorted(self.ships)):  # each wingman's lives, one row per ship
                for j in range(self.ships[seat]["lives"]):
                    f.set(30 - 2 * j, 1 + 2 * i, self._ship_col(seat))
        for i in range(self.bombs):
            f.rect(30 - 3 * i, 9 if len(self.ships) > 1 else 4, 2, 1, th.x)
