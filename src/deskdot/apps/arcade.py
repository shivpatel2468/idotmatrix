"""Arcade — Snake that plays itself (a demo AI) until you take over with the arrow keys in the studio.

Fun modes for 2–4 snakes in one arena: Battle (last snake alive, or the most apples when the clock runs out),
Teams (2 v 2 / 2 v 1 / 1 v 1) and Co-op (a shared apple count and shared lives; teammates pass through each
other). Maps change the arena: open field, pillars, a maze and wrap-around tunnels. Original code and art.
"""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import Color, register
from ..gfx import RGB, Frame, mix, scale
from .games_core import WHITE, GameApp, GameSettings, Mode, Theme, shadow_text, tint

N = 16  # 16x16 board, each cell drawn 2x2
DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
Cell = tuple[int, int]

# where each seat's snake starts (head, heading); the body trails behind the head
STARTS: dict[int, tuple[Cell, Cell]] = {
    1: ((4, 4), (1, 0)),
    2: ((11, 11), (-1, 0)),
    3: ((11, 4), (0, 1)),
    4: ((4, 11), (0, -1)),
}
SOLO_START: tuple[Cell, Cell] = ((8, 8), (1, 0))


def _border(gaps: range | None = None) -> set[Cell]:
    out: set[Cell] = set()
    for i in range(N):
        if gaps is not None and i in gaps:
            continue
        out |= {(i, 0), (i, N - 1), (0, i), (N - 1, i)}
    return out


def _block(x: int, y: int, w: int = 2, h: int = 2) -> set[Cell]:
    return {(x + i, y + j) for i in range(w) for j in range(h)}


MAPS: dict[str, str] = {"classic": "Open", "pillars": "Pillars", "maze": "Maze", "tunnels": "Tunnels"}
WALLS: dict[str, frozenset[Cell]] = {
    "classic": frozenset(),
    "pillars": frozenset(_block(7, 2) | _block(7, 12) | _block(2, 7) | _block(12, 7) | _block(7, 7)),
    "maze": frozenset(
        _border()
        | {(x, 5) for x in range(5, 11)}
        | {(x, 10) for x in range(5, 11)}
        | _block(7, 1, 2, 2)
        | _block(7, 13, 2, 2)
    ),
    "tunnels": frozenset(_border(range(6, 10)) | _block(7, 7)),
}
WRAPS = {"classic": True, "pillars": True, "maze": False, "tunnels": True}

SNAKE_THEMES: dict[str, Theme] = {
    "night": Theme(
        p=(0, 255, 140),
        e=(255, 70, 110),
        x=(255, 220, 60),
        w=(70, 80, 150),
        hud=(255, 255, 255),
        bg=(0, 0, 0),
        r=(
            (0, 255, 140),
            (255, 70, 110),
            (255, 220, 60),
            (0, 200, 255),
            (255, 140, 0),
            (180, 90, 255),
            (255, 255, 255),
        ),
    ),
    "jungle": Theme(
        p=(150, 255, 60),
        e=(255, 120, 40),
        x=(255, 235, 90),
        w=(50, 130, 55),
        hud=(210, 255, 180),
        bg=(2, 10, 4),
        r=(
            (150, 255, 60),
            (255, 120, 40),
            (255, 235, 90),
            (90, 220, 255),
            (255, 80, 80),
            (200, 150, 255),
            (255, 255, 255),
        ),
    ),
    "circuit": Theme(
        p=(0, 235, 255),
        e=(255, 80, 200),
        x=(255, 255, 120),
        w=(0, 110, 150),
        hud=(150, 240, 255),
        bg=(0, 4, 12),
        r=(
            (0, 235, 255),
            (255, 80, 200),
            (255, 255, 120),
            (120, 255, 120),
            (255, 150, 60),
            (160, 120, 255),
            (255, 255, 255),
        ),
    ),
    "desert": Theme(
        p=(255, 215, 80),
        e=(255, 90, 60),
        x=(255, 255, 210),
        w=(170, 110, 50),
        hud=(255, 225, 160),
        bg=(10, 6, 2),
        r=(
            (255, 215, 80),
            (255, 90, 60),
            (255, 255, 210),
            (80, 220, 255),
            (140, 255, 90),
            (255, 130, 220),
            (255, 255, 255),
        ),
    ),
}


class ArcadeSettings(GameSettings):
    speed: int = Field(8, ge=3, le=15, title="Speed (moves/s)")
    color: Color = Field("#00ff8c", title="Snake colour")
    food: Color = Field("#ff1e5a", title="Food colour")
    walls: bool = Field(
        False, title="Solid walls", description="On the open map the edges kill instead of wrapping around"
    )
    grow: int = Field(1, ge=1, le=3, title="Growth per apple", json_schema_extra={"group": "Game"})
    match_time: int = Field(
        90,
        ge=30,
        le=300,
        title="Match time (s)",
        description="Battle and Teams",
        json_schema_extra={"group": "Game"},
    )
    lives: int = Field(3, ge=0, le=9, title="Co-op lives", json_schema_extra={"group": "Game"})


class Snake:
    __slots__ = ("alive", "apples", "body", "dir", "grow", "queue", "respawn", "seat")

    def __init__(self, seat: int, head: Cell, d: Cell) -> None:
        self.seat = seat
        self.body: deque[Cell] = deque((head[0] - d[0] * i, head[1] - d[1] * i) for i in range(3))
        self.dir = d
        self.queue: deque[Cell] = deque()
        self.alive = True
        self.apples = 0
        self.grow = 0
        self.respawn = 0.0


@register
class Arcade(GameApp):
    id = "arcade"
    name = "Snake"
    description = (
        "Snake on the LEDs. Plays itself as a screensaver; press the arrow keys to play. B opens the menu: "
        "Battle and Teams for 2–4 snakes, Co-op with shared apples, and four arenas."
    )
    icon = "gamepad-2"
    Settings = ArcadeSettings
    fps = 10.0
    step_hz = 30.0
    over_hold = 1.2
    max_players = 4
    controls = ("swipe", "dpad", "joystick", "gamepad", "keyboard")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("battle", "Battle", 2, 4, "ffa", "Last snake alive wins"),
        Mode("teams", "Teams", 2, 4, "versus", "Most apples or last team alive"),
        Mode("coop", "Co-op", 2, 4, "coop", "Shared apples and lives"),
    )
    maps: ClassVar[dict[str, str]] = MAPS
    game_themes: ClassVar[dict[str, Theme]] = SNAKE_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {
        "night": "Night",
        "jungle": "Jungle",
        "circuit": "Circuit",
        "desert": "Desert",
    }

    def pilot_anchor(self) -> tuple[float, float] | None:
        """The fruit-fly pilot's eye follows seat 1's snake head (grid cells are 2 px)."""
        snake = next((s for s in self.snakes if s.seat == 1 and s.alive and s.body), None)
        return None if snake is None else (snake.body[0][0] * 2 + 1, snake.body[0][1] * 2 + 1)

    @property
    def mul(self) -> float:
        return 1.0  # `speed` is moves per second here, not a multiplier

    # ---------------------------------------------------------------- setup
    def new_game(self) -> None:
        m = self.play_mode
        self.multi = m.teams != "solo" and self.n_players > 1
        n = self.n_players if self.multi else 1
        mid = self.map_id if self.map_id in WALLS else "classic"
        self.walls = WALLS[mid]
        self.wrap = WRAPS[mid] and not (mid == "classic" and self.settings.walls)
        self.snakes: list[Snake] = []
        for seat in range(1, n + 1):
            head, d = SOLO_START if (n == 1 and mid == "classic") else STARTS[seat]
            self.snakes.append(Snake(seat, head, d))
        self.foods: list[Cell] = []
        self.base_food = 1 if n == 1 else n
        for _ in range(self.base_food):
            self._spawn_food()
        self.clock_left = (
            float(self.settings.match_time) if m.teams in ("ffa", "versus") and self.multi else 0.0
        )
        self.lives = int(self.settings.lives)
        self.acc = 0.0
        self._dist: dict[Cell, int] = {}

    def _occupied(self) -> set[Cell]:
        occ = set(self.walls)
        for s in self.snakes:
            if s.alive:
                occ.update(s.body)
        return occ

    def _spawn_food(self) -> None:
        occ = self._occupied() | set(self.foods)
        free = [(x, y) for x in range(N) for y in range(N) if (x, y) not in occ]
        if free:
            self.foods.append(self.rng.choice(free))

    def _team(self, seat: int) -> int:
        t = self.team_of(seat)
        return (seat - 1) % 2 if t is None else t

    def _allied(self, a: int, b: int) -> bool:
        m = self.play_mode.teams
        return m == "coop" or (m == "versus" and self._team(a) == self._team(b))

    def _wrap(self, x: int, y: int) -> Cell | None:
        if 0 <= x < N and 0 <= y < N:
            return x, y
        return (x % N, y % N) if self.wrap else None

    # ------------------------------------------------------------------ AI
    def _food_distances(self, blocked: set[Cell]) -> dict[Cell, int]:
        """One multi-source BFS from every apple, shared by every AI snake this step."""
        dist = {c: 0 for c in self.foods}
        q = deque(self.foods)
        while q:
            cur = q.popleft()
            dd = dist[cur] + 1
            for d in DIRS.values():
                nxt = self._wrap(cur[0] + d[0], cur[1] + d[1])
                if nxt is not None and nxt not in dist and nxt not in blocked:
                    dist[nxt] = dd
                    q.append(nxt)
        return dist

    def _room(self, start: Cell, blocked: set[Cell], cap: int) -> int:
        seen = {start}
        q = deque([start])
        while q and len(seen) < cap:
            cur = q.popleft()
            for d in DIRS.values():
                nxt = self._wrap(cur[0] + d[0], cur[1] + d[1])
                if nxt is not None and nxt not in seen and nxt not in blocked:
                    seen.add(nxt)
                    q.append(nxt)
        return len(seen)

    def _ai_dir(self, s: Snake, blocked: set[Cell]) -> Cell:
        head = s.body[0]
        own = blocked | {head}
        rivals = [
            o.body[0] for o in self.snakes if o is not s and o.alive and not self._allied(o.seat, s.seat)
        ]
        best: tuple[float, Cell] | None = None
        cap = min(len(s.body) + 3, 48)
        for d in DIRS.values():
            if d == (-s.dir[0], -s.dir[1]):
                continue
            nxt = self._wrap(head[0] + d[0], head[1] + d[1])
            if nxt is None or nxt in blocked:
                continue
            score = float(self._dist.get(nxt, 400))
            if self._room(nxt, own, cap) < cap:
                score += 600
            if any(abs(nxt[0] - rx) + abs(nxt[1] - ry) == 1 for rx, ry in rivals):
                score += 30 * self.skill  # don't race a rival head into the same cell
            if self.rng.random() < (1 - self.skill) * 0.15:
                score -= self.rng.uniform(0, 8)
            if best is None or score < best[0]:
                best = (score, d)
        return best[1] if best else s.dir

    # ---------------------------------------------------------------- rules
    def _step(self) -> None:
        alive = [s for s in self.snakes if s.alive]
        blocked = set(self.walls)
        for s in alive:
            body = list(s.body)
            blocked.update(body[:-1] if s.grow == 0 else body)
        self._dist = self._food_distances(blocked)
        for s in alive:
            if s.queue:
                s.dir = s.queue.popleft()
            elif not self.is_human(s.seat):
                s.dir = self._ai_dir(s, blocked)
        nexts = {s.seat: self._wrap(s.body[0][0] + s.dir[0], s.body[0][1] + s.dir[1]) for s in alive}
        dying: list[Snake] = []
        for s in alive:
            nxt = nexts[s.seat]
            if nxt is None or nxt in self.walls:
                dying.append(s)
                continue
            hit = False
            for o in alive:
                if o is not s and self._allied(o.seat, s.seat):
                    continue  # teammates pass through each other
                body = list(o.body)
                eff = body if (o.grow or nexts[o.seat] in self.foods) else body[:-1]
                if nxt in eff or (o is not s and nexts[o.seat] == nxt):
                    hit = True
                    break
            if hit:
                dying.append(s)
        for s in alive:
            if s in dying:
                continue
            nxt = nexts[s.seat]
            assert nxt is not None
            s.body.appendleft(nxt)
            if nxt in self.foods:
                self.foods.remove(nxt)
                s.apples += 1
                s.grow += int(self.settings.grow)
                self.fx.burst(self.rng, nxt[0] * 2 + 1, nxt[1] * 2 + 1, self._food_rgb(), 5, 8, 0.35)
            if s.grow:
                s.grow -= 1
            else:
                s.body.pop()
        for s in dying:
            self._die(s)
        while len(self.foods) < self.base_food:
            before = len(self.foods)
            self._spawn_food()
            if len(self.foods) == before:
                break
        self._score()
        if self.multi and not self.over:
            self._check_end()

    def _die(self, s: Snake) -> None:
        s.alive = False
        hx, hy = s.body[0]
        self.fx.burst(self.rng, hx * 2 + 1, hy * 2 + 1, self._snake_rgb(s.seat), 14, 14, 0.7)
        if self.is_human(s.seat):
            self.damage(1.0)
        teams = self.play_mode.teams
        if not self.multi:
            self.game_over()
            return
        if teams in ("ffa", "versus"):
            # the fallen snake turns into a trail of apples for the survivors
            for i, c in enumerate(list(s.body)[1:]):
                if i % 2 == 0 and c not in self.walls and c not in self.foods and len(self.foods) < 12:
                    self.foods.append(c)
            s.body.clear()
        elif teams == "coop":
            s.body.clear()
            if self.lives > 0:
                self.lives -= 1
                s.respawn = 2.0
            else:
                total = sum(x.apples for x in self.snakes)
                self.result(scores={x.seat: x.apples for x in self.snakes}, text=f"{total} FOOD")

    def _respawn(self, s: Snake) -> None:
        head, d = STARTS[s.seat]
        fresh = Snake(s.seat, head, d)
        if any(c in self._occupied() for c in fresh.body):
            s.respawn = 0.3  # the start is blocked: try again shortly
            return
        s.body, s.dir, s.alive, s.queue = fresh.body, d, True, deque()

    def _score(self) -> None:
        if self.play_mode.teams == "coop" and self.multi:
            self.score = sum(s.apples for s in self.snakes)
        else:
            self.score = self.snakes[0].apples

    def _check_end(self, timeout: bool = False) -> None:
        scores = {s.seat: s.apples for s in self.snakes}
        alive = [s for s in self.snakes if s.alive]
        teams = self.play_mode.teams
        if teams == "ffa":
            if len(alive) == 1 and not timeout:
                self.result(winner_seat=alive[0].seat, scores=scores)
            elif not alive or timeout:
                pool = alive or self.snakes
                top = max(s.apples for s in pool)
                lead = [s for s in pool if s.apples == top]
                if len(lead) == 1:
                    self.result(winner_seat=lead[0].seat, scores=scores)
                else:
                    self.result(scores=scores, text="DRAW")
        elif teams == "versus":
            left = {self._team(s.seat) for s in alive}
            if len(left) == 1 and not timeout:
                self.result(winner_team=left.pop(), scores=scores)
            elif not left or timeout:
                tot = {0: 0, 1: 0}
                for s in self.snakes:
                    tot[self._team(s.seat)] = tot.get(self._team(s.seat), 0) + s.apples
                if tot[0] == tot[1]:
                    self.result(scores=scores, text="DRAW")
                else:
                    self.result(winner_team=0 if tot[0] > tot[1] else 1, scores=scores)

    def update(self, dt: float) -> None:
        if self.multi:
            for s in self.snakes:
                if not s.alive and s.respawn > 0:
                    s.respawn -= dt
                    if s.respawn <= 0:
                        self._respawn(s)
            if self.clock_left > 0:
                self.clock_left -= dt
                if self.clock_left <= 0:
                    self._check_end(timeout=True)
                    return
        self.acc += dt
        step = 1.0 / self.settings.speed
        if self.acc > 3 * step:
            self.acc = 3 * step
        while self.acc >= step and not self.over:
            self.acc -= step
            self._step()

    # ---------------------------------------------------------------- input
    def key_p(self, k: str, player: int) -> None:
        d = DIRS.get(k)
        s = next((x for x in self.snakes if x.seat == player), None)
        if d is None or s is None or not s.alive:
            return
        last = s.queue[-1] if s.queue else s.dir
        if d != (-last[0], -last[1]) and d != last and len(s.queue) < 3:
            s.queue.append(d)

    # ----------------------------------------------------------------- draw
    def _food_rgb(self) -> RGB:
        return scale(self.settings.food, 1.0)

    def _snake_rgb(self, seat: int) -> RGB:
        if not self.multi:
            return scale(self.settings.color, 1.0)
        return self.colour_of(seat)

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        wall = th.w
        hi = tint(wall, 0.35)
        for x, y in self.walls:
            f.rect(x * 2, y * 2, 2, 2, wall)
            f.set(x * 2, y * 2, hi)
        if not self.walls and not self.wrap:
            f.rect(0, 0, 32, 32, scale(wall, 0.5), fill=False)
        pulse = 0.6 + 0.4 * abs(((now * 3) % 2) - 1)
        food = scale(self._food_rgb(), pulse)
        spark = scale(WHITE, pulse)
        for fx, fy in self.foods:
            f.rect(fx * 2, fy * 2, 2, 2, food)
            if self.multi:  # a white sparkle so apples never look like a (red) rival snake
                f.set(fx * 2, fy * 2, spark)
                f.set(fx * 2 + 1, fy * 2 + 1, spark)
        blink = int(now * 8) % 2 == 0
        for s in self.snakes:
            col = self._snake_rgb(s.seat)
            if not s.alive:
                if not self.multi and blink:
                    for x, y in s.body:
                        f.rect(x * 2, y * 2, 2, 2, (255, 30, 60))
                elif s.respawn > 0 and blink:
                    hx, hy = STARTS[s.seat][0]
                    f.rect(hx * 2, hy * 2, 2, 2, scale(col, 0.7))
                continue
            n = len(s.body)
            head = WHITE if not self.multi else tint(col, 0.55)
            for i, (x, y) in enumerate(s.body):
                c = head if i == 0 else mix(col, scale(col, 0.35), i / max(1, n))
                f.rect(x * 2, y * 2, 2, 2, c)
        if self.multi and self.settings.show_score:
            if 0 < self.clock_left <= 10:
                shadow_text(
                    f, 15 - (len(str(int(self.clock_left) + 1)) * 2), 1, str(int(self.clock_left) + 1), th.x
                )
            elif self.play_mode.teams == "coop" and any(s.respawn > 0 for s in self.snakes):
                shadow_text(f, 12, 1, f"x{self.lives}", th.hud)

    def status(self) -> dict[str, Any]:
        st = super().status()
        if self.multi:
            st["apples"] = {str(s.seat): s.apples for s in self.snakes}
            if self.clock_left > 0:
                st["time_left"] = round(self.clock_left)
        return st
