"""Party games for 1–4 players on one panel: friends join from their phones over local Wi-Fi.

Light Cycles — original take on the classic trail game. Up to four bikes leave glowing walls; turn to box the
others in, don't crash. Last bike (or team) riding wins the round, first to `first_to` wins the match. Seats
without a person are ridden by an AI that picks the turn leaving it the most open space (a short flood fill).

Modes: Solo (you against AI riders), Party (free for all, 2–4 people) and Teams (2v2 / 2v1 / 1v1 picked on the
side-select screen; a team scores while any of its bikes is riding). Arenas: Open, Pillars (four blocks), Core (a
walled box in the middle with four gates, so everyone meets in the centre) and Wrap (no outer wall: ride off one
edge, come back on the other).

Designed for the panel's link (docs/HARDWARE_PROTOCOL.md): a dark arena where only the four bike heads change
each step, so streamed frames stay tiny (one BLE packet) and a phone's turn shows up on the very next frame.
"""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, mix, scale
from .games_core import TEAM_RGB, WHITE, GameApp, GameSettings, Mode, Theme

SEAT_RGB: dict[int, RGB] = {1: (0, 200, 255), 2: (255, 60, 90), 3: (80, 255, 120), 4: (255, 200, 0)}
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
FIRST_TO = 5
ARENA = (1, 1, 30, 30)  # x0, y0, w, h inside the border
STARTS = {1: (4, 15, "right"), 2: (27, 16, "left"), 3: (16, 4, "down"), 4: (15, 27, "up")}
Cell = tuple[int, int]


def _arena_walls(map_id: str) -> frozenset[Cell]:
    """Static obstacles for each arena. Every start position and its first run stay clear."""
    cells: set[Cell] = set()
    if map_id == "pillars":
        for x0, y0 in ((8, 8), (21, 8), (8, 21), (21, 21)):
            cells.update((x0 + dx, y0 + dy) for dx in range(3) for dy in range(3))
    elif map_id == "core":
        lo, hi = 10, 21
        for i in range(lo, hi + 1):
            for c in ((i, lo), (i, hi), (lo, i), (hi, i)):
                if not ({c[0], c[1]} & {15, 16}):  # four 2-wide gates in the middle of each side
                    cells.add(c)
    return frozenset(cells)


WALLS = {m: _arena_walls(m) for m in ("open", "pillars", "core", "wrap")}


class CycleSettings(GameSettings):
    riders: int = Field(
        4, ge=2, le=4, title="Bikes in the arena", description="Empty seats are ridden by the AI"
    )
    pace: float = Field(9.0, ge=5.0, le=14.0, title="Steps per second")
    first_to: int = Field(
        FIRST_TO,
        ge=1,
        le=9,
        title="Match: first to",
        description="Round wins needed to take the match",
        json_schema_extra={"group": "Game"},
    )


CYCLE_THEMES: dict[str, Theme] = {
    "grid": Theme(
        p=(120, 220, 255),
        e=(255, 140, 180),
        x=(255, 240, 120),
        w=(90, 96, 140),  # arena walls: neutral steel, textured so they never read as a trail
        hud=(230, 235, 255),
        bg=(0, 0, 3),
        r=(
            (0, 200, 255),
            (255, 60, 90),
            (80, 255, 120),
            (255, 200, 0),
            (200, 150, 255),
            (255, 160, 60),
            (255, 255, 255),
        ),
    ),
    "sunset": Theme(
        p=(255, 190, 90),
        e=(255, 140, 210),
        x=(255, 250, 190),
        w=(150, 90, 110),
        hud=(255, 225, 205),
        bg=(5, 1, 4),
        r=(
            (0, 200, 255),
            (255, 60, 90),
            (80, 255, 120),
            (255, 200, 0),
            (200, 150, 255),
            (255, 160, 60),
            (255, 255, 255),
        ),
    ),
}


@register
class LightCycles(GameApp):
    id = "cycles"
    name = "Light Cycles"
    description = (
        "Up to four glowing bikes, walls behind them — box the others in, don't crash. Plays itself; arrows steer "
        "the blue bike, and up to three friends can join from their phones on your Wi-Fi. Party, 2v2 teams and "
        "four arenas."
    )
    icon = "zap"
    Settings = CycleSettings
    max_players = 4
    controls = (
        "swipe",
        "dpad",
        "joystick",
        "gamepad",
    )  # best controllers first (phone + Play mode default to the first)
    over_hold = 3.0
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo", 1, 1, "solo"),
        Mode("party", "Party", 2, 4, "ffa"),
        Mode("teams", "Teams", 2, 4, "versus"),
    )
    maps: ClassVar[dict[str, str]] = {"open": "Open", "pillars": "Pillars", "core": "Core", "wrap": "Wrap"}
    game_themes: ClassVar[dict[str, Theme]] = CYCLE_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"grid": "Grid", "sunset": "Sunset"}

    def pilot_anchor(self) -> tuple[float, float] | None:
        """The fruit-fly pilot's eye follows seat 1's bike."""
        b = self.bikes.get(1)
        return None if not b or not b["alive"] else (b["x"], b["y"])

    def new_game(self) -> None:
        self.wins = dict.fromkeys(range(1, 5), 0)
        self.team_wins = {0: 0, 1: 0}
        self.arena = self.map_id if self.map_id in WALLS else "open"
        self.walls = WALLS[self.arena]
        self.wrap = self.arena == "wrap"
        self.teams = bool(self.roster) and self.play_mode.teams == "versus"
        self._round()

    def _seats(self) -> list[int]:
        if self.roster and self.play_mode.id != "solo":
            return sorted(self.roster)[:4]
        return list(range(1, self.settings.riders + 1))

    def _round(self) -> None:
        self.grid: dict[Cell, int] = {}  # cell -> seat that painted it
        self.bikes: dict[int, dict[str, Any]] = {}
        for seat in self._seats():
            x, y, d = STARTS[seat]
            self.bikes[seat] = {"x": x, "y": y, "d": d, "next": d, "alive": True}
            self.grid[(x, y)] = seat
        self.acc = 0.0
        self.countdown = 1.4
        self.result_t = 0.0
        self.round_winner = 0
        self.round_team: int | None = None

    def rgb(self, seat: int) -> RGB:
        """A bike's colour: its seat colour, or its team's (tinted per rider) in team play."""
        return self.colour_of(seat) if self.teams else self.seat_colour(seat)

    # ------------------------------------------------------------------ input
    def key_p(self, k: str, player: int) -> None:
        b = self.bikes.get(player)
        if b is None or not b["alive"] or k not in DIRS:
            return
        dx, dy = DIRS[k]
        cx, cy = DIRS[b["d"]]
        if (dx, dy) != (-cx, -cy):  # no instant reverse into your own wall
            b["next"] = k

    # ------------------------------------------------------------------ rules
    def _nxt(self, x: int, y: int, dx: int, dy: int) -> Cell:
        x, y = x + dx, y + dy
        if self.wrap:
            x0, y0, w, h = ARENA
            x, y = x0 + (x - x0) % w, y0 + (y - y0) % h
        return x, y

    def _free(self, x: int, y: int) -> bool:
        x0, y0, w, h = ARENA
        return x0 <= x < x0 + w and y0 <= y < y0 + h and (x, y) not in self.grid and (x, y) not in self.walls

    def _space(self, x: int, y: int, limit: int = 80) -> int:
        """How much room is reachable from (x, y) — a bounded flood fill."""
        if not self._free(x, y):
            return 0
        seen = {(x, y)}
        q = deque([(x, y)])
        while q and len(seen) < limit:
            cx, cy = q.popleft()
            for dx, dy in DIRS.values():
                n = self._nxt(cx, cy, dx, dy)
                if n not in seen and self._free(*n):
                    seen.add(n)
                    q.append(n)
        return len(seen)

    def _ai_turn(self, seat: int) -> None:
        b = self.bikes[seat]
        cx, cy = DIRS[b["d"]]
        best, choice = -1.0, b["d"]
        for name, (dx, dy) in DIRS.items():
            if (dx, dy) == (-cx, -cy):
                continue
            room = self._space(*self._nxt(b["x"], b["y"], dx, dy))
            if room == 0:
                continue
            # prefer going straight a little (less jittery), plus a pinch of skill-scaled randomness
            score = room + (6 if name == b["d"] else 0) + self.rng.random() * (1 - self.skill) * 25
            if score > best:
                best, choice = score, name
        b["next"] = choice

    def fly_lure(self) -> list[tuple[float, float, float]]:
        """Open space: a few pixels down the way with the most room left (a bounded flood fill) and the longest
        clear run, so the turn is smelled early enough for a fly to make it."""
        b = self.bikes.get(1)
        if not b or not b["alive"]:
            return []
        key = (b["x"], b["y"], b["d"], len(self.grid))
        cached = getattr(self, "_fly_way", None)
        if cached is None or cached[0] != key:
            cx, cy = DIRS[b["d"]]
            ahead: set[Cell] = set()  # where the other bikes are about to be
            for s, o in self.bikes.items():
                if s != 1 and o["alive"]:
                    ox, oy = o["x"], o["y"]
                    for _ in range(5):
                        ox, oy = self._nxt(ox, oy, *DIRS[o["d"]])
                        ahead.add((ox, oy))
            best, way = -1.0, b["d"]
            for name, (dx, dy) in DIRS.items():
                if (dx, dy) == (-cx, -cy):
                    continue
                x, y = b["x"], b["y"]
                run = 0
                while run < 10:
                    x, y = self._nxt(x, y, dx, dy)
                    if not self._free(x, y) or (x, y) in ahead:
                        break
                    run += 1
                if run == 0:
                    continue
                room = (
                    self._space(*self._nxt(b["x"], b["y"], dx, dy), 40)
                    + 3 * run
                    + (2 if name == b["d"] else 0)
                )
                if room > best:
                    best, way = room, name
            cached = self._fly_way = (key, way)
        dx, dy = DIRS[cached[1]]
        return [(b["x"] + dx * 5, b["y"] + dy * 5, 1.0)]

    def update(self, dt: float) -> None:
        if self.result_t > 0:
            self.result_t -= dt
            if self.result_t <= 0:
                self._after_round()
            return
        if self.countdown > 0:
            self.countdown -= dt
            return
        self.acc += dt
        step = 1.0 / self.settings.pace
        while self.acc >= step:
            self.acc -= step
            self._step()
            if self.result_t > 0:
                break

    def _after_round(self) -> None:
        n = self.settings.first_to
        if not self.roster:  # self-play / classic: the match card shows your round wins
            if max(self.wins.values()) >= n:
                self.score = self.wins[1]
                self.game_over()
            else:
                self._round()
            return
        scores = {s: self.wins[s] for s in self.bikes}
        if self.teams:
            if max(self.team_wins.values()) >= n:
                self.score = self.wins[1]
                best = max(self.team_wins, key=lambda t: self.team_wins[t])
                self.result(winner_team=best, scores=scores)
                return
        elif max(scores.values(), default=0) >= n:
            self.score = self.wins[1]
            self.result(winner_seat=max(scores, key=lambda s: scores[s]), scores=scores)
            return
        self._round()

    def _step(self) -> None:
        for seat, b in self.bikes.items():
            if b["alive"] and not self.is_human(seat):
                self._ai_turn(seat)
        moves: dict[int, Cell] = {}
        for seat, b in self.bikes.items():
            if b["alive"]:
                b["d"] = b["next"]
                moves[seat] = self._nxt(b["x"], b["y"], *DIRS[b["d"]])
        targets = list(moves.values())
        for seat, (nx, ny) in moves.items():
            b = self.bikes[seat]
            if not self._free(nx, ny) or targets.count((nx, ny)) > 1:  # wall, trail, or head-on
                b["alive"] = False
                self.fx.burst(self.rng, b["x"], b["y"], self.rgb(seat), 12, 14, 0.5)
                self.fx.burst(self.rng, b["x"], b["y"], WHITE, 4, 7, 0.3)
                self.flash = 0.25
                if self.is_human(seat):
                    self.damage()
        for seat, (nx, ny) in moves.items():
            b = self.bikes[seat]
            if b["alive"]:
                b["x"], b["y"] = nx, ny
                self.grid[(nx, ny)] = seat
        alive = [s for s, b in self.bikes.items() if b["alive"]]
        if self.teams:
            sides = {self.team_of(s) for s in alive}
            if len(sides) <= 1:
                self.round_team = next(iter(sides)) if sides else None
                if self.round_team is not None:
                    self.team_wins[self.round_team] += 1
                    for s in self.bikes:
                        if self.team_of(s) == self.round_team:
                            self.wins[s] += 1
                self.round_winner = alive[0] if len(alive) == 1 else 0
                self.score = self.wins[1]
                self.result_t = 1.6
            return
        if len(alive) <= 1:
            self.round_winner = alive[0] if alive else 0
            if self.round_winner:
                self.wins[self.round_winner] += 1
            self.score = self.wins[1]
            self.result_t = 1.6

    # ------------------------------------------------------------------ draw
    def _tid(self) -> str:
        return str(self.sel.get("theme", self.settings.theme))

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        own = self._tid() in self.game_themes
        if own:
            f.clear(th.bg)
        wall = th.w if own else (100, 100, 120)
        edge = scale(wall, 0.45) if own else (26, 26, 36)
        if self.flash > 0:
            edge = mix(edge, WHITE, 0.25)
        if self.wrap:  # no outer wall: a dashed rim marks the portals
            for i in range(0, 32, 4):
                for x, y in ((i, 0), (i, 31), (0, i), (31, i)):
                    f.set(x, y, edge)
        else:
            f.rect(0, 0, 32, 32, edge, fill=False)
        dark = scale(wall, 0.55)
        for x, y in self.walls:  # checkered, so arena walls never read as a bike's trail
            f.set(x, y, wall if (x + y) % 2 else dark)
        for (x, y), seat in self.grid.items():
            b = self.bikes.get(seat)
            f.set(x, y, scale(self.rgb(seat), 0.5 if b and b["alive"] else 0.18))
        for seat, b in self.bikes.items():
            if b["alive"]:
                f.set(b["x"], b["y"], mix(self.rgb(seat), WHITE, 0.45))
        if self.countdown > 0 and int(now * 4) % 2 == 0:
            for seat, b in self.bikes.items():  # the start positions pulse so everyone finds their bike
                f.rect(b["x"] - 1, b["y"] - 1, 3, 3, scale(self.rgb(seat), 0.6), fill=False)
        if self.result_t > 0:
            if self.teams:
                t = self.round_team
                col = TEAM_RGB[t] if t is not None else (160, 160, 170)
                label = "DRAW" if t is None else ("TEAM A" if t == 0 else "TEAM B")
            else:
                col = self.rgb(self.round_winner) if self.round_winner else (160, 160, 170)
                label = (
                    "DRAW"
                    if not self.round_winner
                    else ("YOU" if self.round_winner == 1 and self.human else f"P{self.round_winner}")
                )
            f.rect(3, 12, 26, 9, (0, 0, 0))
            f.rect(3, 12, 26, 9, col, fill=False)
            f.text_center(14, label, col)
        if self.settings.show_score:  # wins as dots along the top border
            if self.teams:
                for t in (0, 1):
                    for i in range(self.team_wins[t]):
                        f.set(2 + i if t == 0 else 29 - i, 0, TEAM_RGB[t])
            else:
                for seat in self.bikes:
                    for i in range(self.wins[seat]):
                        f.set(2 + (seat - 1) * 7 + i, 0, self.rgb(seat))

    def best_candidate(self) -> int:
        return self.wins[1] if self.human else 0

    def status(self) -> dict[str, Any]:
        st = super().status()
        st["wins"] = {str(s): w for s, w in self.wins.items() if s in self.bikes}
        st["alive"] = [s for s, b in self.bikes.items() if b["alive"]]
        return st
