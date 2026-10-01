"""Action games: Invaders, Maze Chase, Asteroids, Infinity. Original code and art.

Each game builds its match in `new_game()` from the menu's mode / map / roster (see `games_core.GameApp`).
With an empty roster (attract mode) every game plays its classic solo round with the AI in seat 1.
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, Sprite, hsv, measure, mix, scale
from .games_core import WHITE, GameApp, GameSettings, Mode, Theme, approach, clamp, shadow_text, tint


class _ActionGame(GameApp):
    """Small helpers shared by the action games (not registered itself)."""

    def _tid(self) -> str:
        """The theme id in effect (the home menu's choice wins over the stored setting)."""
        return str(self.sel.get("theme", self.settings.theme))

    def _gm(self) -> str:
        """The mode being played: the menu's mode during a match, the classic solo game in attract mode."""
        return self.play_mode.id if self.roster else "solo"

    def _seat_list(self) -> list[int]:
        return sorted(self.roster) if self.roster else [1]

    def _map_key(self) -> str:
        return self.map_id if self.map_id in self.maps else next(iter(self.maps))

    def _banner(self, f: Frame, text: str, color: RGB, y: int = 13) -> None:
        shadow_text(f, (32 - measure(text, "tiny")) // 2, y, text, color)

    def _end_by_score(self, scores: dict[int, int], shown: dict[int, int] | None = None) -> None:
        """Finish a versus/ffa match: the highest score wins, a shared top score is a draw. `shown` is what
        the results screen lists when it differs from the ranking score."""
        if self.over or not scores:
            return
        top = max(scores.values())
        best = [s for s, v in scores.items() if v == top]
        card = {s: int(v) for s, v in (shown or scores).items()}
        if len(best) == 1:
            self.result(winner_seat=best[0], scores=card)
        else:
            self.result(text="DRAW", scores=card)


# =====================================================================================================
# Invaders
# =====================================================================================================
class InvadersSettings(GameSettings):
    rows: int = Field(3, ge=2, le=4, title="Alien rows", json_schema_extra={"group": "Game"})
    shields: bool = Field(True, title="Shields", json_schema_extra={"group": "Game"})
    lives: int = Field(3, ge=1, le=5, title="Lives", json_schema_extra={"group": "Game"})
    fire: int = Field(
        3,
        ge=1,
        le=5,
        title="Alien fire",
        description="How often the fleet shoots back",
        json_schema_extra={"group": "Game"},
    )
    duel_waves: int = Field(
        2,
        ge=1,
        le=5,
        title="Duel waves",
        description="Waves in a Duel match",
        json_schema_extra={"group": "Game"},
    )


ALIENS = [
    ([".#.#.", "#####", "#.#.#", ".#.#."], [".#.#.", "#####", "#.#.#", "#...#"]),
    (["#...#", ".###.", "##.##", "#.#.#"], ["#...#", ".###.", "##.##", ".#.#."]),
    ([".###.", "#.#.#", "#####", ".#.#."], [".###.", "#.#.#", "#####", "#.#.#"]),
    (["..#..", ".###.", "#.#.#", "#...#"], ["..#..", ".###.", "#.#.#", ".#.#."]),
]
SHIP = ["..#..", ".###.", "#####"]
A_COLS, A_PITCH_X, A_PITCH_Y = 4, 7, 5
SHIELD_Y = 23


def invader_shields(map_id: str) -> np.ndarray:
    """Hit points per x column of the shield row (0 = open)."""
    hp = np.zeros(32, dtype=np.int8)
    if map_id == "classic":
        for x0 in (3, 13, 23):
            hp[x0 : x0 + 6] = 2
    elif map_id == "bunkers":
        for x0 in (2, 8, 14, 20, 26):
            hp[x0 : x0 + 4] = 3
    elif map_id == "wall":
        hp[1:31] = 1
        for g in (6, 15, 24):
            hp[g : g + 2] = 0
    return hp


@register
class Invaders(_ActionGame):
    id = "invaders"
    name = "Invaders"
    description = "Hold the line against a marching alien fleet behind crumbling shields. ←/→ move, A fires."
    icon = "rocket"
    Settings = InvadersSettings
    step_hz = 30.0
    max_players = 4
    controls = ("dpad", "joystick", "gamepad", "keyboard")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("coop", "Co-op", 2, 4, "coop", "Cannons share the lives"),
        Mode("duel", "Duel", 2, 4, "ffa", "Most points when the waves are done"),
    )
    maps: ClassVar[dict[str, str]] = {
        "classic": "Classic",
        "bunkers": "Bunkers",
        "wall": "Long Wall",
        "open": "Open Sky",
    }
    game_themes: ClassVar[dict[str, Theme]] = {
        "deep": Theme(
            p=(60, 255, 120),
            e=(255, 70, 200),
            x=(255, 230, 60),
            w=(70, 150, 255),
            hud=(220, 230, 255),
            bg=(0, 0, 8),
            r=(
                (255, 70, 200),
                (255, 230, 60),
                (90, 220, 255),
                (255, 120, 60),
                (60, 255, 120),
                (190, 110, 255),
                (255, 255, 255),
            ),
        ),
        "sunset": Theme(
            p=(0, 230, 255),
            e=(255, 140, 30),
            x=(255, 255, 120),
            w=(200, 70, 160),
            hud=(255, 210, 160),
            bg=(10, 6, 8),
            r=(
                (255, 140, 30),
                (255, 90, 90),
                (255, 200, 60),
                (255, 255, 120),
                (0, 230, 255),
                (200, 110, 255),
                (255, 170, 200),
            ),
        ),
    }
    game_theme_labels: ClassVar[dict[str, str]] = {"deep": "Deep Space", "sunset": "Sunset"}

    def new_game(self) -> None:
        self.wave = 1
        self.gm = self._gm()
        self.lives = int(self.settings.lives)
        self.cleared = 0
        self._cache: dict[Any, Any] = {}
        seats = self._seat_list()
        n = len(seats)
        self.cannons: list[dict[str, Any]] = []
        for i, seat in enumerate(seats):
            x = 13.5 if n == 1 else 3 + (i + 0.5) * 26 / n
            self.cannons.append(
                {
                    "seat": seat,
                    "x": x,
                    "tx": x,
                    "bullet": None,
                    "respawn": 0.6,
                    "lives": int(self.settings.lives),
                    "score": 0,
                    "aim": 0.0,
                    "out": False,
                }
            )
        self._wave()

    def _wave(self) -> None:
        rows = self.settings.rows
        self.alive = [[True] * A_COLS for _ in range(rows)]
        self.ax = 2.0
        self.ay = 6.0 + min(3, (self.wave - 1) // 2)
        self.adir = 1
        self.bounces = 0
        self.march_t = 0.0
        self.frame = 0
        self.shots: list[list[float]] = []  # alien bullets [x, y]
        for c in self.cannons:
            c["bullet"] = None
            c["respawn"] = max(c["respawn"], 0.6)
        self.shield = invader_shields(self._map_key()) if self.settings.shields else np.zeros(32, np.int8)

    def _sprites(self) -> dict[str, Any]:
        key = self._tid()
        if key not in self._cache:
            th = self.theme
            cols = [th.r[4], th.r[3], th.r[6], th.r[0]] if key == "classic" else [th.e, th.x, th.p, th.e]
            if key in self.game_themes:
                cols = [th.e, th.r[1], th.r[2], th.r[3]]
            self._cache[key] = [
                [Sprite.parse(fr, {"#": cols[i]}) for fr in pair] for i, pair in enumerate(ALIENS)
            ]
        return {"aliens": self._cache[key]}

    def _ship_col(self, c: dict[str, Any]) -> RGB:
        if self.gm != "solo":
            return self.colour_of(c["seat"])
        return (60, 255, 90) if self._tid() == "classic" else self.theme.p

    def _ship_sprite(self, col: RGB) -> Sprite:
        spr = self._cache.get(("ship", col))
        if spr is None:
            spr = self._cache[("ship", col)] = Sprite.parse(SHIP, {"#": col})
        return spr

    def _alien_pos(self, r: int, c: int) -> tuple[float, float]:
        return self.ax + c * A_PITCH_X, self.ay + r * A_PITCH_Y

    def _count(self) -> int:
        return sum(v for row in self.alive for v in row)

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        c = next((c for c in self.cannons if c["seat"] == player and not c["out"]), None)
        if c is None:
            return
        if k in ("left", "right"):
            if abs(c["tx"] - c["x"]) > 6:
                c["tx"] = c["x"]
            c["tx"] = clamp(c["tx"] + (-3 if k == "left" else 3), 2, 29)
        elif k == "a":
            self._fire(c)

    def _fire(self, c: dict[str, Any]) -> None:
        if c["bullet"] is None and c["respawn"] <= 0:
            c["bullet"] = [c["x"], 27.0]

    def _ai(self, c: dict[str, Any]) -> None:
        # dodge the nearest threatening bullet, otherwise line up under the lowest alien of the nearest column
        x = c["x"]
        danger = [s for s in self.shots if s[1] > 13 and abs(s[0] - x) < 3.5]
        if danger and self.rng.random() < 0.5 + 0.5 * self.skill:
            s = max(danger, key=lambda s: s[1])
            away = 1 if s[0] <= x else -1
            if x > 26:
                away = -1
            elif x < 5:
                away = 1
            c["tx"] = clamp(x + away * 5, 2, 29)
            return
        best: tuple[float, float] | None = None
        for col in range(A_COLS):
            rows = [r for r in range(len(self.alive)) if self.alive[r][col]]
            if not rows:
                continue
            ax, _ay = self._alien_pos(rows[-1], col)
            cx = ax + 2 + self.adir * 1.2
            d = abs(cx - x)
            if best is None or d < best[0]:
                best = (d, cx)
        if best:
            c["tx"] = clamp(best[1] + c["aim"], 2, 29)
            if abs(best[1] + c["aim"] - x) < 1.2:
                self._fire(c)
                c["aim"] = self.rng.uniform(-1, 1) * (1 - self.skill) * 4

    def update(self, dt: float) -> None:
        th = self.theme
        active = [c for c in self.cannons if not c["out"]]
        for c in active:
            c["respawn"] = max(0.0, c["respawn"] - dt)
            if not self.is_human(c["seat"]):
                self._ai(c)
            c["x"] = clamp(approach(c["x"], c["tx"], 22 * dt), 2, 29)
        # march
        n = self._count()
        interval = (0.12 + 0.5 * n / (A_COLS * len(self.alive))) / (1 + 0.12 * (self.wave - 1))
        if self._map_key() == "open":
            interval *= 1.25  # no cover, so the fleet is a little slower
        self.march_t += dt
        if self.march_t >= interval:
            self.march_t = 0.0
            self.frame ^= 1
            cols = [c for c in range(A_COLS) if any(self.alive[r][c] for r in range(len(self.alive)))]
            if cols:
                left = self.ax + min(cols) * A_PITCH_X
                right = self.ax + max(cols) * A_PITCH_X + 5
                if (self.adir > 0 and right >= 32) or (self.adir < 0 and left <= 0):
                    self.adir = -self.adir
                    self.bounces += 1
                    if self.bounces % 2 == 0:
                        self.ay += 1
                else:
                    self.ax += self.adir
            # alien fire
            shooters = []
            for c in range(A_COLS):
                rows = [r for r in range(len(self.alive)) if self.alive[r][c]]
                if rows:
                    shooters.append(self._alien_pos(rows[-1], c))
            fire = int(self.settings.fire)
            cap = 2 + self.wave // 2 + (len(active) - 1) + (1 if fire >= 4 else 0)
            if shooters and len(self.shots) < cap and self.rng.random() < 0.12 * fire:
                sx, sy = self.rng.choice(shooters)
                self.shots.append([sx + 2, sy + 4])
        # player bullets
        wave = self.wave
        for c in active:
            b = c["bullet"]
            if b:
                b[1] -= 56 * dt
                if b[1] < 0:
                    c["bullet"] = None
                else:
                    self._bullet_hits(c, b[0], b[1])
            if self.over or self.wave != wave:
                return
        # alien bullets
        keep = []
        for s in self.shots:
            s[1] += (14 + 2 * self.wave) * dt
            if s[1] > 32:
                continue
            if self._shield_hit(s[0], s[1] + 1):
                continue
            hit = next(
                (c for c in active if c["respawn"] <= 0 and s[1] + 1 >= 29 and abs(s[0] - c["x"]) < 2.6),
                None,
            )
            if hit is not None:
                self._hit_player(hit)
                if self.over:
                    return
                if self.gm == "solo":
                    keep = []
                    break
                continue
            keep.append(s)
        self.shots = keep
        # invasion
        rows_alive = [r for r in range(len(self.alive)) if any(self.alive[r])]
        if rows_alive and self._alien_pos(rows_alive[-1], 0)[1] + 4 >= 28:
            self.fx.burst(self.rng, 16, 28, th.e, 20, 18, 0.8)
            for c in active:
                if self.is_human(c["seat"]):
                    self.damage(1.5)
                    break
            self._finish()

    def _finish(self) -> None:
        if self.gm == "duel":
            self._end_by_score({c["seat"]: c["score"] for c in self.cannons})
        else:
            self.game_over()

    def _bullet_hits(self, c: dict[str, Any], bx: float, by: float) -> None:
        for r in range(len(self.alive)):
            for col in range(A_COLS):
                if not self.alive[r][col]:
                    continue
                ax, ay = self._alien_pos(r, col)
                if ax - 0.5 <= bx <= ax + 5 and ay <= by <= ay + 4:
                    self.alive[r][col] = False
                    c["bullet"] = None
                    pts = (len(self.alive) - r) * 10
                    c["score"] += pts
                    if self.gm == "duel":
                        self.score = self.cannons[0]["score"]
                    else:
                        self.score += pts
                    px = self._sprites()["aliens"][r % 4][0].px[1, 0]
                    col_rgb = tuple(int(v) for v in px) if any(px) else self.theme.e
                    self.fx.burst(self.rng, ax + 2.5, ay + 2, col_rgb, 8, 14, 0.45)  # type: ignore[arg-type]
                    if self._count() == 0:
                        self.cleared += 1
                        if self.gm == "duel" and self.cleared >= int(self.settings.duel_waves):
                            self._finish()
                            return
                        self.wave += 1
                        self.flash = 1.2
                        self.fx.burst(self.rng, 16, 12, WHITE, 14, 16, 0.7)
                        self._wave()
                    return
        if self._shield_hit(bx, by):
            c["bullet"] = None

    def _shield_hit(self, x: float, y: float) -> bool:
        if not SHIELD_Y <= y < SHIELD_Y + 2:
            return False
        xi = int(x)
        if 0 <= xi < 32 and self.shield[xi] > 0:
            self.shield[xi] -= 1
            self.fx.burst(self.rng, x, y, self.theme.w, 2, 5, 0.3)
            return True
        return False

    def _hit_player(self, c: dict[str, Any]) -> None:
        col = self._ship_col(c)
        self.fx.burst(self.rng, c["x"], 29, col, 16, 16, 0.8)
        self.fx.burst(self.rng, c["x"], 29, WHITE, 5, 8, 0.4)
        if self.is_human(c["seat"]):
            self.damage()
        c["respawn"] = 1.4
        c["bullet"] = None
        if self.gm == "duel":
            c["lives"] -= 1
            if c["lives"] <= 0:
                c["out"] = True
                if all(x["out"] for x in self.cannons):
                    self._finish()
            return
        if self.gm == "solo":
            self.shots = []
        self.lives -= 1
        if self.lives <= 0:
            self.game_over()

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        sp = self._sprites()
        for r, row in enumerate(self.alive):
            for c, alive in enumerate(row):
                if alive:
                    ax, ay = self._alien_pos(r, c)
                    f.sprite(sp["aliens"][r % 4][self.frame], round(ax), round(ay))
        for x in np.nonzero(self.shield)[0]:
            hp = int(self.shield[x])
            h = min(2, hp)
            f.rect(int(x), SHIELD_Y + 2 - h, 1, h, scale(th.w, min(1.0, 0.45 + 0.2 * hp)))
        for sx, sy in self.shots:
            f.vline(int(sx), int(sy), 2, th.x if int(now * 10) % 2 else th.e)
        for c in self.cannons:
            if c["out"]:
                continue
            if c["bullet"]:
                f.vline(int(c["bullet"][0]), int(c["bullet"][1]), 2, WHITE)
            if c["respawn"] <= 0 or int(now * 8) % 2:
                f.sprite(self._ship_sprite(self._ship_col(c)), round(c["x"]) - 2, 29)
        if self.gm == "duel":
            # one score bar per cannon along the top row (the results screen has the numbers)
            lead = max(1, max(c["score"] for c in self.cannons))
            for i, c in enumerate(self.cannons[:4]):
                col = self.colour_of(c["seat"])
                x0 = 1 + i * 8
                f.hline(x0, 0, 7, scale(col, 0.25))
                w = round(7 * c["score"] / lead)
                if w:
                    f.hline(x0, 0, w, col if not c["out"] else scale(col, 0.5))
        else:
            self.hud(f, str(self.score), x=1, y=0)
            ship = self._ship_col(self.cannons[0])
            for i in range(min(5, self.lives - 1)):
                f.rect(30 - 3 * i, 1, 2, 2, ship)
        if self.flash > 0 and int(now * 6) % 3:
            self._banner(f, f"WAVE {self.wave}", th.x, 14)


# =====================================================================================================
# Maze Chase — 8×8 maze of 3×3 rooms with 1 px walls (fills the whole panel)
# =====================================================================================================
M = 8
DXY = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPP = {"up": "down", "down": "up", "left": "right", "right": "left"}
FLIP = {"up": "up", "down": "down", "left": "right", "right": "left"}
PAC = {
    "right": ["###", "#..", "###"],
    "left": ["###", "..#", "###"],
    "up": ["#.#", "#.#", "###"],
    "down": ["###", "#.#", "#.#"],
}
PAC_SHUT = ["###", "###", "###"]
PILL = ["#.#", ".#.", "#.#"]
GHOST = ["###", "W#W", "#.#"]


class MazeSettings(GameSettings):
    ghosts: int = Field(3, ge=1, le=4, title="Ghosts", json_schema_extra={"group": "Game"})
    lives: int = Field(3, ge=1, le=5, title="Lives", json_schema_extra={"group": "Game"})
    hunt_time: int = Field(
        40,
        ge=15,
        le=90,
        title="Hunt round (s)",
        description="Seconds the runner must survive in Hunt mode",
        json_schema_extra={"group": "Game"},
    )
    fright: float = Field(6.0, ge=2.0, le=10.0, title="Power pill (s)", json_schema_extra={"group": "Game"})


@register
class Maze(_ActionGame):
    id = "maze"
    name = "Maze Chase"
    description = (
        "Eat every dot in a fresh wrap-around maze while ghosts give chase; power pills turn the tables."
    )
    icon = "ghost"
    Settings = MazeSettings
    step_hz = 30.0
    over_hold = 2.0
    max_players = 4
    controls = ("dpad", "swipe", "joystick", "gamepad")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("coop", "Co-op", 2, 2, "coop", "Two runners, shared lives"),
        Mode("hunt", "Hunt", 2, 4, "ffa", "The others are the ghosts; everyone runs once"),
    )
    maps: ClassVar[dict[str, str]] = {
        "random": "Random",
        "mirror": "Mirror",
        "open": "Open",
        "boxed": "Boxed",
    }
    game_themes: ClassVar[dict[str, Theme]] = {
        "haunted": Theme(
            p=(255, 230, 60),
            e=(255, 90, 60),
            x=(120, 255, 200),
            w=(120, 50, 210),
            hud=(230, 220, 255),
            bg=(4, 2, 8),
            r=(
                (255, 90, 60),
                (255, 120, 220),
                (90, 220, 255),
                (255, 170, 40),
                (120, 255, 200),
                (200, 140, 255),
                (255, 255, 255),
            ),
        ),
        "hedge": Theme(
            p=(255, 200, 40),
            e=(255, 90, 160),
            x=(140, 220, 255),
            w=(40, 170, 70),
            hud=(220, 255, 220),
            bg=(0, 6, 2),
            r=(
                (255, 90, 160),
                (255, 140, 60),
                (140, 220, 255),
                (200, 120, 255),
                (255, 255, 160),
                (255, 90, 90),
                (255, 255, 255),
            ),
        ),
    }
    game_theme_labels: ClassVar[dict[str, str]] = {"haunted": "Haunted", "hedge": "Hedge Maze"}

    def new_game(self) -> None:
        self.level = 1
        self.gm = self._gm()
        self.lives = int(self.settings.lives)
        self.order = self._seat_list()
        self.round = 0
        self.pts: dict[int, int] = dict.fromkeys(self.order, 0)
        self.between = 1.6 if self.gm == "hunt" else 0.0
        self._cache: dict[str, Any] = {}
        self._build()

    # --------------------------------------------------------------- maze
    def _nbr(self, cell: tuple[int, int], d: str) -> tuple[int, int] | None:
        dx, dy = DXY[d]
        nx, ny = cell[0] + dx, cell[1] + dy
        if self.wrap:
            return nx % M, ny % M
        if 0 <= nx < M and 0 <= ny < M:
            return nx, ny
        return None

    def _build(self) -> None:
        mid = self._map_key()
        rng = random.Random(4242 + self.level) if mid == "mirror" else self.rng
        self.wrap = mid != "boxed"
        width = M // 2 if mid == "mirror" else M
        self.open: dict[tuple[int, int], set[str]] = {(x, y): set() for x in range(M) for y in range(M)}
        seen = {(0, 0)}
        stack = [(0, 0)]
        while stack:
            cell = stack[-1]
            opts = []
            for d in DXY:
                n = self._nbr(cell, d)
                if n is None or n in seen or n[0] >= width:
                    continue
                if mid == "mirror" and abs(n[0] - cell[0]) > 1:
                    continue  # no horizontal wrap while carving one half
                opts.append((d, n))
            if not opts:
                stack.pop()
                continue
            d, n = rng.choice(opts)
            self._link(cell, d)
            seen.add(n)
            stack.append(n)
        if mid == "mirror":
            for x in range(width):
                for y in range(M):
                    self.open[(M - 1 - x, y)] = {FLIP[d] for d in self.open[(x, y)]}
            for y in rng.sample(range(M), 3):
                self._link((width - 1, y), "right")
            for y in rng.sample(range(M), 2):
                self._link((0, y), "left")
        # braid: no dead ends, plus a few extra loops
        for cell in sorted(self.open):
            if len(self.open[cell]) == 1:
                cands = [d for d in DXY if d not in self.open[cell] and self._nbr(cell, d)]
                self._link(cell, rng.choice(cands), mid == "mirror")
        extra = {"random": 6, "mirror": 3, "open": 18, "boxed": 4}.get(mid, 6)
        for _ in range(extra):
            cell = (rng.randrange(M), rng.randrange(M))
            d = rng.choice(tuple(DXY))
            if self._nbr(cell, d):
                self._link(cell, d, mid == "mirror")
        self.dots = set(self.open)
        self.pills = {(0, 0), (M - 1, 0), (0, M - 1), (M - 1, M - 1)}
        self.home = (M // 2, M // 2)
        self.spawn = (M // 2, 0) if self.gm == "hunt" else (M // 2, M - 2)
        self.dots.discard(self.spawn)
        self._wall_mask()
        self._place()

    def _link(self, cell: tuple[int, int], d: str, mirror: bool = False) -> None:
        n = self._nbr(cell, d)
        if n is None:
            return
        self.open[cell].add(d)
        self.open[n].add(OPP[d])
        if mirror:
            m = (M - 1 - cell[0], cell[1])
            mn = self._nbr(m, FLIP[d])
            if mn is not None:
                self.open[m].add(FLIP[d])
                self.open[mn].add(OPP[FLIP[d]])

    def _wall_mask(self) -> None:
        mask = np.zeros((32, 32), dtype=bool)
        for (x, y), dirs in self.open.items():
            if "right" not in dirs:
                mask[4 * y + 1 : 4 * y + 4, (4 * x + 4) % 32] = True
            if "down" not in dirs:
                mask[(4 * y + 4) % 32, 4 * x + 1 : 4 * x + 4] = True
        for y in range(0, 32, 4):
            for x in range(0, 32, 4):
                neigh = (
                    mask[(y - 1) % 32, x]
                    or mask[(y + 1) % 32, x]
                    or mask[y, (x - 1) % 32]
                    or mask[y, (x + 1) % 32]
                )
                mask[y, x] = bool(neigh)
        self.walls = mask

    def _place(self) -> None:
        """Put runners and ghosts at their starts (a new life in Solo, a new round in Hunt)."""
        gm = self.gm
        self.runners: list[dict[str, Any]] = []
        ghost_seats: list[int | None]
        if gm == "hunt":
            runner = self.order[self.round % len(self.order)]
            run_seats = [runner]
            others = [s for s in self.order if s != runner]
            ghost_seats = [*others, *([None] * max(0, 2 - len(others)))]
            self.clock = float(self.settings.hunt_time)
        elif gm == "coop":
            run_seats = self.order
            ghost_seats = [None] * int(self.settings.ghosts)
        else:
            run_seats = [1]
            ghost_seats = [None] * int(self.settings.ghosts)
        for i, seat in enumerate(run_seats):
            pos = self.spawn if i == 0 else ((self.spawn[0] - 1) % M, self.spawn[1])
            self.runners.append(
                {
                    "seat": seat,
                    "pos": pos,
                    "dir": "left" if i == 0 else "right",
                    "want": "left" if i == 0 else "right",
                    "t": 0.0,
                    "dead": 0.0,
                    "out": False,
                }
            )
        self.ghosts: list[dict[str, Any]] = []
        for i, seat in enumerate(ghost_seats):
            self.ghosts.append(
                {
                    "seat": seat,
                    "pos": self.home,
                    "dir": ("up", "left", "right", "down")[i % 4],
                    "want": ("up", "left", "right", "down")[i % 4],
                    "t": 0.0,
                    "eaten": 0.0,
                    "wait": 1.5 if seat is not None else 1.0 + i * 1.2,
                }
            )
        self.fright = 0.0
        self.mode_t = 0.0
        self.dying = 0.0

    @property
    def p(self) -> dict[str, Any]:
        """The first runner (seat 1's in Solo)."""
        return self.runners[0]

    # ---------------------------------------------------------- movement
    def _next(self, pos: tuple[int, int], d: str) -> tuple[int, int]:
        dx, dy = DXY[d]
        return (pos[0] + dx) % M, (pos[1] + dy) % M

    def _bfs(
        self, src: tuple[int, int], block: set[tuple[int, int]] | None = None
    ) -> dict[tuple[int, int], tuple[int, str]]:
        """Distance and first step from `src` to every reachable room."""
        out: dict[tuple[int, int], tuple[int, str]] = {src: (0, "")}
        q = deque([src])
        while q:
            cur = q.popleft()
            dist, first = out[cur]
            for d in self.open[cur]:
                n = self._next(cur, d)
                if n in out or (block and n in block):
                    continue
                out[n] = (dist + 1, first or d)
                q.append(n)
        return out

    def _ghost_dist(self) -> dict[tuple[int, int], int]:
        dist: dict[tuple[int, int], int] = {}
        q: deque[tuple[int, int]] = deque()
        for g in self.ghosts:
            if g["eaten"] > 0 or g["wait"] > 0 or self.fright > 1.5:
                continue
            for c in (g["pos"], self._next(g["pos"], g["dir"])):
                if c not in dist:
                    dist[c] = 0
                    q.append(c)
        while q:
            cur = q.popleft()
            for d in self.open[cur]:
                n = self._next(cur, d)
                if n not in dist:
                    dist[n] = dist[cur] + 1
                    q.append(n)
        return dist

    def _live_runners(self) -> list[dict[str, Any]]:
        return [r for r in self.runners if not r["out"] and r["dead"] <= 0]

    def _ai_dir(self, r: dict[str, Any]) -> str:
        pos = r["pos"]
        if self.rng.random() < 0.03 * (1 - self.skill):
            return self.rng.choice(tuple(self.open[pos]))
        gd = self._ghost_dist()
        radius = 1 + round(2 * self.skill)
        danger = {c for c, d in gd.items() if d <= radius}
        danger.discard(pos)
        # chase frightened ghosts
        if self.fright > 1.5:
            bfs = self._bfs(pos)
            prey = [
                bfs[g["pos"]] for g in self.ghosts if g["eaten"] <= 0 and g["pos"] in bfs and g["wait"] <= 0
            ]
            prey = [p for p in prey if p[0] <= 5 and p[1]]
            if prey:
                return min(prey)[1]
        bfs = self._bfs(pos, danger)
        targets = [bfs[c] for c in (self.dots | self.pills) if c in bfs and bfs[c][1]]
        if targets:
            return min(targets)[1]
        # nowhere safe: step to the neighbour farthest from ghosts
        return max(self.open[pos], key=lambda d: gd.get(self._next(pos, d), 99))

    def _ghost_dir(self, g: dict[str, Any], i: int) -> str:
        pos = g["pos"]
        opts = [d for d in self.open[pos] if d != OPP[g["dir"]]] or list(self.open[pos])
        runners = self._live_runners()
        if g["eaten"] > 0:
            target = self.home
        elif self.fright > 0 or not runners:
            return self.rng.choice(opts)
        else:
            prey = min(
                runners,
                key=lambda r: abs(_wrapi(r["pos"][0] - pos[0])) + abs(_wrapi(r["pos"][1] - pos[1])),
            )
            px, py = prey["pos"]
            scatter = (self.mode_t % 20) < 5 and self.gm != "hunt"
            if scatter:
                target = ((0, 0), (M - 1, 0), (0, M - 1), (M - 1, M - 1))[i % 4]
            elif i == 1:
                dx, dy = DXY[prey["dir"]]
                target = ((px + 2 * dx) % M, (py + 2 * dy) % M)
            elif i == 2 and self.rng.random() < 0.4:
                return self.rng.choice(opts)
            else:
                target = (px, py)
        bfs = self._bfs(target)
        return min(opts, key=lambda d: bfs.get(self._next(pos, d), (99, ""))[0])

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        if k not in DXY:
            return
        ents = [r for r in self.runners if r["seat"] == player] + [
            g for g in self.ghosts if g["seat"] == player
        ]
        for e in ents:
            e["want"] = k
            if k == OPP[e["dir"]] and e["t"] > 0:
                # reverse mid-corridor
                e["pos"] = self._next(e["pos"], e["dir"])
                e["t"] = 1.0 - e["t"]
                e["dir"] = k

    def _step_entity(self, e: dict[str, Any], speed: float, dt: float, choose: Any) -> None:
        if e["t"] == 0.0:
            d = choose()
            if d and d in self.open[e["pos"]]:
                e["dir"] = d
            elif e["dir"] not in self.open[e["pos"]]:
                return
        e["t"] += speed * dt
        if e["t"] >= 1.0:
            e["pos"] = self._next(e["pos"], e["dir"])
            e["t"] = 0.0

    def _human_dir(self, e: dict[str, Any]) -> str:
        w = e["want"]
        return w if w in self.open[e["pos"]] else e["dir"]

    def update(self, dt: float) -> None:
        if self.between > 0:  # Hunt: the role banner between rounds
            self.between -= dt
            return
        if self.dying > 0:
            self.dying -= dt
            if self.dying <= 0:
                if self.lives <= 0:
                    self.game_over()
                else:
                    self._place()
            return
        self.mode_t += dt
        self.fright = max(0.0, self.fright - dt)
        if self.gm == "hunt":
            self.clock -= dt
            if self.clock <= 0:
                self.pts[self.runners[0]["seat"]] += 10  # survived the round
                self._next_round()
                return
        pspeed = 4.2 + 0.2 * self.level
        for r in self.runners:
            if r["out"]:
                continue
            if r["dead"] > 0:
                r["dead"] -= dt
                if r["dead"] <= 0:
                    r.update(pos=self.spawn, t=0.0, dir="left", want="left")
                continue
            human = self.is_human(r["seat"])
            self._step_entity(
                r, pspeed, dt, (lambda r=r: self._human_dir(r)) if human else (lambda r=r: self._ai_dir(r))
            )
            if r["t"] == 0.0:
                pos = r["pos"]
                if pos in self.dots:
                    self.dots.discard(pos)
                    self._points(r["seat"], 1)
                if pos in self.pills:
                    self.pills.discard(pos)
                    self._points(r["seat"], 5)
                    self.fright = float(self.settings.fright)
                    self.flash = 0.2
        for i, g in enumerate(self.ghosts):
            if g["wait"] > 0:
                g["wait"] -= dt
                continue
            if g["eaten"] > 0:
                g["eaten"] -= dt
                if g["eaten"] <= 0:
                    g["pos"], g["t"] = self.home, 0.0
                continue
            if g["seat"] is not None:
                gs = 2.4 if self.fright > 0 else pspeed * 0.97
            else:
                gs = (2.4 if self.fright > 0 else 3.4 + 0.25 * self.level) * (0.85 + 0.15 * self.skill)
            if g["seat"] is not None and self.is_human(g["seat"]):
                self._step_entity(g, gs, dt, lambda g=g: self._human_dir(g))
            else:
                self._step_entity(g, gs, dt, lambda g=g, i=i: self._ghost_dir(g, i))
        # collisions (room-level, including passing through each other)
        for r in self._live_runners():
            pp = self._xy(r)
            for g in self.ghosts:
                if g["eaten"] > 0 or g["wait"] > 0:
                    continue
                gp = self._xy(g)
                dx = (pp[0] - gp[0] + 16) % 32 - 16
                dy = (pp[1] - gp[1] + 16) % 32 - 16
                if abs(dx) < 2.5 and abs(dy) < 2.5:
                    if self.fright > 0:
                        g["eaten"] = 3.0
                        self._points(r["seat"], 20 if self.gm != "hunt" else 10)
                        self.fx.burst(self.rng, gp[0] + 1, gp[1] + 1, WHITE, 8, 12, 0.5)
                    else:
                        self._caught(r, g, pp)
                        return
        if not self.dots and not self.pills:
            if self.gm == "hunt":
                self.pts[self.runners[0]["seat"]] += 20
                self._next_round()
                return
            self.level += 1
            self.flash = 0.8
            self.score += 50
            self._build()

    def _points(self, seat: int, n: int) -> None:
        self.pts[seat] = self.pts.get(seat, 0) + n
        if self.gm == "hunt":
            self.score = self.pts.get(1, 0)
        else:
            self.score += n

    def _caught(self, r: dict[str, Any], g: dict[str, Any], pp: tuple[float, float]) -> None:
        col = self._runner_color(r)
        self.fx.burst(self.rng, pp[0] + 1, pp[1] + 1, col, 16, 12, 0.9)
        if self.is_human(r["seat"]):
            self.damage()
        if self.gm == "hunt":
            if g["seat"] is not None:
                self.pts[g["seat"]] = self.pts.get(g["seat"], 0) + 15
            self._next_round()
        elif self.gm == "coop":
            if self.lives > 0:
                self.lives -= 1
                r["dead"] = 2.0
            else:
                r["out"] = True
            if all(x["out"] for x in self.runners):
                self.game_over()
        else:
            self.lives -= 1
            self.dying = 1.4

    def _next_round(self) -> None:
        self.round += 1
        if self.round >= len(self.order):
            self._end_by_score(dict(self.pts))
            return
        self.between = 1.6
        self._build()

    def _xy(self, e: dict[str, Any]) -> tuple[float, float]:
        x, y = e["pos"]
        dx, dy = DXY[e["dir"]]
        return 4 * x + 1 + dx * 4 * e["t"], 4 * y + 1 + dy * 4 * e["t"]

    def _pac_color(self) -> RGB:
        return (
            (255, 220, 0)
            if self._tid() == "classic"
            else self.theme.p
            if self._tid() in self.game_themes
            else self.theme.x
        )

    def _runner_color(self, r: dict[str, Any]) -> RGB:
        return self._pac_color() if self.gm == "solo" else self.colour_of(r["seat"])

    def _ghost_colors(self) -> list[RGB]:
        th = self.theme
        if self._tid() == "classic":
            return [(255, 20, 30), (255, 110, 200), (0, 220, 255), (255, 150, 0)]
        return [th.e, th.r[1], th.r[2], th.r[5]]

    def _sprite(self, rows: list[str], color: RGB, eye: RGB = WHITE) -> Sprite:
        key = f"{''.join(rows)}{color}{eye}"
        spr = self._cache.get(key)
        if spr is None:
            spr = Sprite.parse(rows, {"#": color, "W": eye})
            self._cache[key] = spr
        return spr

    def _blit_wrap(self, f: Frame, spr: Sprite, x: float, y: float) -> None:
        ix, iy = round(x) % 32, round(y) % 32
        for ox in (0, -32):
            for oy in (0, -32):
                f.sprite(spr, ix + ox, iy + oy)

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        wall = (40, 70, 255) if self._tid() == "classic" else th.w
        if self.flash > 0 and int(now * 10) % 2:
            wall = WHITE
        f.px[self.walls] = scale(wall, 0.7)
        dot = scale(th.hud, 0.55)
        for x, y in self.dots:
            if (x, y) not in self.pills:
                f.set(4 * x + 2, 4 * y + 2, dot)
        if int(now * 4) % 2:
            pill = self._sprite(PILL, (255, 140, 200) if self._tid() == "classic" else th.x)
            for x, y in self.pills:
                f.sprite(pill, 4 * x + 1, 4 * y + 1)
        cols = self._ghost_colors()
        for i, g in enumerate(self.ghosts):
            gx, gy = self._xy(g)
            if g["eaten"] > 0:
                f.set(round(gx) % 32, round(gy + 1) % 32, WHITE)
                f.set((round(gx) + 2) % 32, round(gy + 1) % 32, WHITE)
                continue
            if g["wait"] > 0 and int(now * 6) % 2:
                continue
            c = cols[i % len(cols)] if g["seat"] is None else self.colour_of(g["seat"])
            if self.fright > 0:
                c = (90, 120, 255) if self.fright > 1.5 or int(now * 8) % 2 else WHITE
            self._blit_wrap(f, self._sprite(GHOST, c, WHITE if self.fright <= 0 else (255, 150, 150)), gx, gy)
        for r in self.runners:
            if r["out"] or r["dead"] > 0:
                continue
            if self.dying > 0 and int(now * 8) % 2:
                continue
            px, py = self._xy(r)
            chomp = int(now * 8) % 2 == 0 and self.dying <= 0
            rows = PAC_SHUT if chomp else PAC[r["dir"]]
            self._blit_wrap(f, self._sprite(rows, self._runner_color(r)), px, py)
        if self.gm == "hunt":
            runner = self.runners[0]
            col = self.colour_of(runner["seat"])
            left = round(30 * max(0.0, self.clock) / max(1, int(self.settings.hunt_time)))
            if left:
                f.hline(1, 0, left, col)
            if self.between > 0 and not self.over:
                self._banner(f, f"P{runner['seat']} RUNS", col)
        elif self.gm == "coop":
            for i in range(min(5, self.lives)):
                f.set(30 - 2 * i, 0, th.hud)


def _wrapi(d: int) -> int:
    return (d + M // 2) % M - M // 2


# =====================================================================================================
# Asteroids
# =====================================================================================================
class AsteroidsSettings(GameSettings):
    rocks: int = Field(3, ge=1, le=6, title="Rocks per wave", json_schema_extra={"group": "Game"})
    filled: bool = Field(True, title="Solid rocks", json_schema_extra={"group": "Graphics"})
    lives: int = Field(3, ge=1, le=5, title="Lives", json_schema_extra={"group": "Game"})
    time_limit: int = Field(
        120,
        ge=30,
        le=300,
        title="Battle time (s)",
        description="Dogfights end after this; most lives left wins",
        json_schema_extra={"group": "Game"},
    )


ROCK_R = {3: 5.0, 2: 3.0, 1: 1.6}
WELL = (16.0, 16.0)


def _wrapd(a: float, b: float) -> float:
    return (a - b + 16) % 32 - 16


@register
class Asteroids(_ActionGame):
    id = "asteroids"
    name = "Asteroids"
    description = (
        "Pilot a tiny ship through a field of splitting space rocks. ←/→ turn, ↑ thrust, A fire, B warp."
    )
    icon = "orbit"
    Settings = AsteroidsSettings
    step_hz = 30.0
    max_players = 4
    controls = ("gamepad", "dpad", "joystick", "keyboard")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("coop", "Co-op", 2, 4, "coop", "Clear the field together, shared lives"),
        Mode("battle", "Dogfight", 2, 4, "ffa", "Shoot each other; last ship flying wins"),
        Mode("teams", "Squads", 2, 4, "versus", "Team dogfight"),
    )
    maps: ClassVar[dict[str, str]] = {
        "field": "Rock Field",
        "dense": "Dense Belt",
        "well": "Gravity Well",
        "open": "Open Space",
    }
    game_themes: ClassVar[dict[str, Theme]] = {
        "nebula": Theme(
            p=(80, 220, 255),
            e=(255, 120, 60),
            x=(255, 240, 120),
            w=(190, 150, 255),
            hud=(230, 230, 255),
            bg=(6, 2, 10),
            r=(
                (255, 120, 60),
                (190, 150, 255),
                (255, 240, 120),
                (80, 220, 255),
                (255, 90, 180),
                (120, 255, 160),
                (255, 255, 255),
            ),
        ),
        "mars": Theme(
            p=(90, 255, 160),
            e=(255, 150, 60),
            x=(255, 255, 160),
            w=(220, 110, 70),
            hud=(255, 220, 190),
            bg=(8, 4, 2),
            r=(
                (255, 150, 60),
                (220, 110, 70),
                (255, 255, 160),
                (90, 255, 160),
                (120, 200, 255),
                (255, 100, 120),
                (255, 255, 255),
            ),
        ),
    }
    game_theme_labels: ClassVar[dict[str, str]] = {"nebula": "Nebula", "mars": "Red Planet"}

    def new_game(self) -> None:
        self.wave = 0
        self.gm = self._gm()
        self.lives = int(self.settings.lives)
        self.elapsed = 0.0
        mid = self._map_key()
        seats = self._seat_list()
        if mid == "well":
            spawns = [(8.0, 8.0), (24.0, 24.0), (24.0, 8.0), (8.0, 24.0)]
        elif len(seats) == 1:
            spawns = [(16.0, 16.0)]
        else:
            spawns = [(9.0, 9.0), (23.0, 23.0), (23.0, 9.0), (9.0, 23.0)]
        self.ships: list[dict[str, Any]] = []
        for i, seat in enumerate(seats):
            s: dict[str, Any] = {
                "seat": seat,
                "home": spawns[i % len(spawns)],
                "lives": int(self.settings.lives),
                "score": 0,
                "out": False,
                "dead": 0.0,
            }
            self._ship_reset(s)
            self.ships.append(s)
        self.rocks: list[dict[str, Any]] = []
        self.bullets: list[list[float]] = []  # x, y, vx, vy, life, owner seat
        self.next_wave()

    def _ship_reset(self, s: dict[str, Any]) -> None:
        s["x"], s["y"] = s["home"]
        s["vx"] = s["vy"] = 0.0
        # point towards the middle (up for the solo ship in the centre)
        dx, dy = 16 - s["x"], 16 - s["y"]
        s["ang"] = math.atan2(dy, dx) if abs(dx) + abs(dy) > 1 else -math.pi / 2
        if self._map_key() == "well" and abs(dx) + abs(dy) > 1:
            s["ang"] += math.pi / 2  # orbit the well instead of diving in
        s["inv"] = 2.0
        s["cool"] = 0.0
        s["thrust"] = 0.0

    # solo compatibility (the ship of seat 1)
    @property
    def sx(self) -> float:
        return float(self.ships[0]["x"])

    @property
    def sy(self) -> float:
        return float(self.ships[0]["y"])

    def next_wave(self) -> None:
        self.wave += 1
        mid = self._map_key()
        n = int(self.settings.rocks) + self.wave - 1
        size = 3
        if mid == "dense":
            n, size = 2 * int(self.settings.rocks) + self.wave, 2
        elif mid == "open":
            n = max(1, int(self.settings.rocks) // 2) + (self.wave - 1) // 2
        for _ in range(n):
            for _try in range(40):
                x, y = self.rng.uniform(0, 32), self.rng.uniform(0, 32)
                far = all(
                    math.hypot(_wrapd(x, s["x"]), _wrapd(y, s["y"])) > 11 for s in self.ships if not s["out"]
                )
                if far and (mid != "well" or math.hypot(x - 16, y - 16) > 7):
                    break
            self._rock(x, y, size)

    def _rock(self, x: float, y: float, size: int) -> None:
        a = self.rng.uniform(0, 2 * math.pi)
        sp = (
            self.rng.uniform(2.5, 5.0)
            * (1.6 if size == 1 else 1.2 if size == 2 else 1.0)
            * (1 + 0.08 * self.wave)
        )
        n = 8 if size == 3 else 6 if size == 2 else 5
        shape = [ROCK_R[size] * self.rng.uniform(0.72, 1.12) for _ in range(n)]
        self.rocks.append(
            {
                "x": x,
                "y": y,
                "vx": math.cos(a) * sp,
                "vy": math.sin(a) * sp,
                "size": size,
                "shape": shape,
                "rot": self.rng.uniform(0, 6.3),
                "spin": self.rng.uniform(-1.5, 1.5),
            }
        )

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        s = next((s for s in self.ships if s["seat"] == player), None)
        if s is None or s["out"] or s["dead"] > 0:
            return
        if k == "left":
            s["ang"] -= 0.4
        elif k == "right":
            s["ang"] += 0.4
        elif k == "up":
            s["vx"] += math.cos(s["ang"]) * 5
            s["vy"] += math.sin(s["ang"]) * 5
            s["thrust"] = 0.25
        elif k == "down":
            s["vx"] *= 0.5
            s["vy"] *= 0.5
        elif k == "a":
            self._fire(s)
        elif k == "b":
            self.fx.burst(self.rng, s["x"], s["y"], self._ship_col(s), 8, 10, 0.4)
            for _try in range(20):
                s["x"], s["y"] = self.rng.uniform(0, 32), self.rng.uniform(0, 32)
                if self._map_key() != "well" or math.hypot(s["x"] - 16, s["y"] - 16) > 6:
                    break
            s["vx"] = s["vy"] = 0.0
            s["inv"] = max(s["inv"], 0.5)

    def _fire(self, s: dict[str, Any]) -> None:
        if s["cool"] > 0 or sum(1 for b in self.bullets if b[5] == s["seat"]) >= 4:
            return
        s["cool"] = 0.22
        c, sn = math.cos(s["ang"]), math.sin(s["ang"])
        self.bullets.append(
            [s["x"] + c * 3, s["y"] + sn * 3, c * 32 + s["vx"], sn * 32 + s["vy"], 0.75, s["seat"]]
        )

    def _combat(self) -> bool:
        return self.gm in ("battle", "teams")

    def _foe(self, a: dict[str, Any], b: dict[str, Any]) -> bool:
        if a is b or not self._combat():
            return False
        if self.gm == "teams":
            return self.team_of(a["seat"]) != self.team_of(b["seat"])
        return True

    def _ai(self, s: dict[str, Any], dt: float) -> None:
        sx, sy = s["x"], s["y"]
        # threat: rock on a collision course soon → turn away and burn
        threat: tuple[float, float] | None = None
        best_tc = 9.0
        for r in self.rocks:
            dx, dy = _wrapd(r["x"], sx), _wrapd(r["y"], sy)
            rvx, rvy = r["vx"] - s["vx"], r["vy"] - s["vy"]
            dist = math.hypot(dx, dy) - ROCK_R[r["size"]] - 1.5
            closing = -(dx * rvx + dy * rvy) / max(0.1, math.hypot(dx, dy))
            tc = dist / closing if closing > 0 else 9.0
            if dist < 2.5:
                tc = min(tc, 0.3)
            if tc < best_tc:
                best_tc, threat = tc, (dx, dy)
        if self._map_key() == "well":
            dw = math.hypot(16 - sx, 16 - sy)
            if dw < 8 and best_tc > 0.4:
                best_tc, threat = 0.4, (16 - sx, 16 - sy)
        # aim: the nearest enemy ship in a dogfight, else the nearest rock (leading its motion)
        targets: list[tuple[float, float, float, float]] = [
            (r["x"], r["y"], r["vx"], r["vy"]) for r in self.rocks
        ]
        foes = [o for o in self.ships if self._foe(s, o) and not o["out"] and o["dead"] <= 0]
        if foes:
            near = min(foes, key=lambda o: math.hypot(_wrapd(o["x"], sx), _wrapd(o["y"], sy)))
            if math.hypot(_wrapd(near["x"], sx), _wrapd(near["y"], sy)) < 16 or not targets:
                targets = [(near["x"], near["y"], near["vx"], near["vy"])]
        if not targets:
            return
        tx, ty, tvx, tvy = min(targets, key=lambda t: math.hypot(_wrapd(t[0], sx), _wrapd(t[1], sy)))
        dx, dy = _wrapd(tx, sx), _wrapd(ty, sy)
        tlead = math.hypot(dx, dy) / 32
        dx += (tvx - s["vx"]) * tlead
        dy += (tvy - s["vy"]) * tlead
        want = math.atan2(dy, dx)
        evade = threat is not None and best_tc < 0.9 + 0.8 * self.skill
        if evade and threat is not None:
            want = math.atan2(-threat[1], -threat[0])
        diff = (want - s["ang"] + math.pi) % (2 * math.pi) - math.pi
        turn = (3.2 + 3.5 * self.skill) * dt
        s["ang"] += clamp(diff, -turn, turn)
        if evade and abs(diff) < 0.8:
            s["vx"] += math.cos(s["ang"]) * 26 * dt
            s["vy"] += math.sin(s["ang"]) * 26 * dt
            s["thrust"] = 0.1
        elif not evade and abs(diff) < 0.12 + 0.15 * (1 - self.skill):
            self._fire(s)
        # gentle drift back towards the middle (never into the well)
        if not evade and math.hypot(s["vx"], s["vy"]) < 2 and self._map_key() != "well":
            cx, cy = _wrapd(16, sx), _wrapd(16, sy)
            if math.hypot(cx, cy) > 8 and abs(diff) < 0.3:
                s["vx"] += math.cos(s["ang"]) * 6 * dt
                s["vy"] += math.sin(s["ang"]) * 6 * dt

    def update(self, dt: float) -> None:
        well = self._map_key() == "well"
        self.elapsed += dt
        for s in self.ships:
            if s["out"]:
                continue
            if s["dead"] > 0:
                s["dead"] -= dt
                if s["dead"] <= 0:
                    self._ship_reset(s)
                continue
            s["cool"] = max(0.0, s["cool"] - dt)
            s["inv"] = max(0.0, s["inv"] - dt)
            s["thrust"] = max(0.0, s["thrust"] - dt)
            if not self.is_human(s["seat"]):
                self._ai(s, dt)
            if s["thrust"] > 0:
                bx, by = s["x"] - math.cos(s["ang"]) * 2.5, s["y"] - math.sin(s["ang"]) * 2.5
                self.fx.emit(bx, by, -math.cos(s["ang"]) * 8, -math.sin(s["ang"]) * 8, self.theme.x, 0.25)
            if well:
                gx, gy = self._pull(s["x"], s["y"])
                s["vx"] += gx * dt
                s["vy"] += gy * dt
            damp = 0.55**dt
            sp = math.hypot(s["vx"], s["vy"])
            if sp > 16:
                s["vx"], s["vy"] = s["vx"] * 16 / sp, s["vy"] * 16 / sp
            s["vx"] *= damp
            s["vy"] *= damp
            s["x"] = (s["x"] + s["vx"] * dt) % 32
            s["y"] = (s["y"] + s["vy"] * dt) % 32
        for r in self.rocks:
            r["x"] = (r["x"] + r["vx"] * dt) % 32
            r["y"] = (r["y"] + r["vy"] * dt) % 32
            r["rot"] += r["spin"] * dt
        keep = []
        for b in self.bullets:
            if well:
                gx, gy = self._pull(b[0], b[1])
                b[2] += gx * dt
                b[3] += gy * dt
                if math.hypot(b[0] - 16, b[1] - 16) < 1.6:
                    continue
            b[0] = (b[0] + b[2] * dt) % 32
            b[1] = (b[1] + b[3] * dt) % 32
            b[4] -= dt
            if b[4] <= 0:
                continue
            hit = None
            for r in self.rocks:
                if math.hypot(_wrapd(b[0], r["x"]), _wrapd(b[1], r["y"])) < ROCK_R[r["size"]] + 0.5:
                    hit = r
                    break
            if hit:
                self._split(hit, int(b[5]))
                continue
            owner = next((s for s in self.ships if s["seat"] == b[5]), None)
            victim = None
            if owner is not None and self._combat():
                for s in self.ships:
                    if s["out"] or s["dead"] > 0 or s["inv"] > 0 or not self._foe(owner, s):
                        continue
                    if math.hypot(_wrapd(b[0], s["x"]), _wrapd(b[1], s["y"])) < 1.8:
                        victim = s
                        break
            if victim is not None and owner is not None:
                owner["score"] += 1
                if owner is self.ships[0]:
                    self.score += 1
                self._crash(victim)
                if self.over:
                    return
                continue
            keep.append(b)
        self.bullets = keep
        for s in self.ships:
            if s["out"] or s["dead"] > 0 or s["inv"] > 0:
                continue
            crash = well and math.hypot(s["x"] - 16, s["y"] - 16) < 2.2
            if not crash:
                for r in self.rocks:
                    if math.hypot(_wrapd(s["x"], r["x"]), _wrapd(s["y"], r["y"])) < ROCK_R[r["size"]] + 1.2:
                        crash = True
                        break
            if crash:
                self._crash(s)
                if self.over:
                    return
        if self._combat() and self.elapsed >= int(self.settings.time_limit):
            self._battle_end(timeout=True)
            return
        if not self.rocks:
            self.flash = 0.5
            self.next_wave()

    def _pull(self, x: float, y: float) -> tuple[float, float]:
        dx, dy = 16 - x, 16 - y
        d2 = max(9.0, dx * dx + dy * dy)
        k = 90.0 / d2 / math.sqrt(d2)
        return dx * k, dy * k

    def _split(self, r: dict[str, Any], seat: int) -> None:
        self.rocks.remove(r)
        pts = {3: 2, 2: 5, 1: 10}[r["size"]]
        if not self._combat():
            self.score += pts
            for s in self.ships:
                if s["seat"] == seat:
                    s["score"] += pts
        col = self._rock_color(r["size"])
        self.fx.burst(self.rng, r["x"], r["y"], col, 4 + 2 * r["size"], 10, 0.5)
        if r["size"] > 1:
            for _ in range(2):
                self._rock(r["x"], r["y"], r["size"] - 1)

    def _crash(self, s: dict[str, Any]) -> None:
        col = self._ship_col(s)
        self.fx.burst(self.rng, s["x"], s["y"], col, 18, 14, 0.9)
        self.fx.burst(self.rng, s["x"], s["y"], WHITE, 6, 8, 0.5)
        if self.is_human(s["seat"]):
            self.damage()
        if self._combat():
            s["lives"] -= 1
            if s["lives"] <= 0:
                s["out"] = True
                self._battle_end()
            else:
                s["dead"] = 1.2
            return
        if self.gm == "coop":
            if self.lives > 0:
                self.lives -= 1
                s["dead"] = 1.2
            else:
                s["out"] = True
                if all(x["out"] for x in self.ships):
                    self.game_over()
            return
        self.lives -= 1
        if self.lives <= 0:
            self.game_over()
        else:
            self._ship_reset(s)
            # clear the spawn point
            hx, hy = s["home"]
            for r in self.rocks:
                if math.hypot(_wrapd(r["x"], hx), _wrapd(r["y"], hy)) < 8:
                    r["x"] = (r["x"] + 16) % 32

    def _battle_end(self, timeout: bool = False) -> None:
        if self.over:
            return
        alive = [s for s in self.ships if not s["out"]]
        scores = {s["seat"]: s["score"] for s in self.ships}
        if self.gm == "teams":
            teams = {self.team_of(s["seat"]) for s in alive}
            if len(teams) <= 1 and not timeout:
                self.result(winner_team=next(iter(teams), None), scores=scores)
            elif timeout:
                lives = {t: sum(s["lives"] for s in alive if self.team_of(s["seat"]) == t) for t in (0, 1)}
                if lives[0] == lives[1]:
                    self.result(text="DRAW", scores=scores)
                else:
                    self.result(winner_team=0 if lives[0] > lives[1] else 1, scores=scores)
            return
        if len(alive) <= 1 and not timeout:
            if alive:
                self.result(winner_seat=alive[0]["seat"], scores=scores)
            else:
                self._end_by_score(scores)
        elif timeout:
            self._end_by_score({s["seat"]: s["lives"] * 100 + s["score"] for s in self.ships}, scores)

    def _ship_col(self, s: dict[str, Any]) -> RGB:
        return self.theme.p if self.gm == "solo" else self.colour_of(s["seat"])

    def _rock_color(self, size: int) -> RGB:
        th = self.theme
        if self._tid() == "classic":
            return {3: (200, 170, 140), 2: (230, 190, 150), 1: (255, 220, 180)}[size]
        return {3: th.w, 2: th.e, 1: th.x}[size]

    def _poly(self, f: Frame, r: dict[str, Any], ox: float, oy: float) -> None:
        n = len(r["shape"])
        pts = []
        for i, rad in enumerate(r["shape"]):
            a = r["rot"] + i * 2 * math.pi / n
            pts.append((round(r["x"] + ox + math.cos(a) * rad), round(r["y"] + oy + math.sin(a) * rad)))
        col = self._rock_color(r["size"])
        if r["size"] == 1:
            f.rect(round(r["x"] + ox) - 1, round(r["y"] + oy) - 1, 2, 2, col)
            return
        if self.settings.filled:
            f.circle(
                round(r["x"] + ox),
                round(r["y"] + oy),
                max(1, round(ROCK_R[r["size"]] * 0.65)),
                scale(col, 0.28),
            )
        f.polyline([*pts, pts[0]], col)

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        f.clear(th.bg)
        if self._map_key() == "well":
            for k in range(8):  # the well's swirl: 8 dots circling the core
                a = now * 1.8 + k * math.pi / 4
                rad = 3.5 + (k % 2)
                f.set(
                    round(16 + math.cos(a) * rad), round(16 + math.sin(a) * rad), scale(th.x, 0.3 + 0.05 * k)
                )
            f.rect(15, 15, 2, 2, scale(th.x, 0.85))
        for r in self.rocks:
            rad = ROCK_R[r["size"]] + 1
            xs = [0.0] + ([-32.0] if r["x"] + rad > 32 else []) + ([32.0] if r["x"] - rad < 0 else [])
            ys = [0.0] + ([-32.0] if r["y"] + rad > 32 else []) + ([32.0] if r["y"] - rad < 0 else [])
            for ox in xs:
                for oy in ys:
                    self._poly(f, r, ox, oy)
        for b in self.bullets:
            owner = next((s for s in self.ships if s["seat"] == b[5]), None)
            col = WHITE if owner is None or not self._combat() else tint(self._ship_col(owner), 0.5)
            f.set(int(b[0]), int(b[1]), col)
        for s in self.ships:
            if s["out"] or s["dead"] > 0 or self.over or (s["inv"] > 0 and int(now * 10) % 2):
                continue
            c, sn = math.cos(s["ang"]), math.sin(s["ang"])
            nose = (s["x"] + c * 3, s["y"] + sn * 3)
            lw = (s["x"] + math.cos(s["ang"] + 2.5) * 2.4, s["y"] + math.sin(s["ang"] + 2.5) * 2.4)
            rw = (s["x"] + math.cos(s["ang"] - 2.5) * 2.4, s["y"] + math.sin(s["ang"] - 2.5) * 2.4)
            pts = [(round(p[0]), round(p[1])) for p in (nose, lw, rw)]
            col = self._ship_col(s)
            f.line(*pts[0], *pts[1], col)
            f.line(*pts[0], *pts[2], col)
            f.line(*pts[1], *pts[2], scale(col, 0.6))
            f.set(*pts[0], WHITE)
        if self._combat():
            for i, s in enumerate(self.ships[:4]):  # lives per ship, in its colour, along the top
                col = self._ship_col(s)
                for j in range(s["lives"]):
                    f.set(1 + i * 8 + 2 * j, 0, col)
        else:
            self.hud(f, str(self.score), x=1, y=1)
            for i in range(min(6, self.lives - (1 if self.gm == "solo" else 0))):
                f.set(30 - 2 * i, 1, th.p)
        if self.flash > 0 and int(now * 6) % 3:
            self._banner(f, f"WAVE {self.wave}", th.x, 14)


# =====================================================================================================
# Infinity — endless neon cave flight
# =====================================================================================================
class InfinitySettings(GameSettings):
    trail: bool = Field(True, title="Rainbow trail", json_schema_extra={"group": "Graphics"})
    stars: bool = Field(True, title="Star field", json_schema_extra={"group": "Graphics"})
    spikes: bool = Field(True, title="Stalactites", json_schema_extra={"group": "Game"})
    accel: float = Field(
        0.25,
        ge=0.0,
        le=1.0,
        title="Speed-up",
        description="How fast the flight accelerates",
        json_schema_extra={"group": "Game"},
    )
    lives: int = Field(
        3,
        ge=0,
        le=9,
        title="Convoy respawns",
        description="Shared respawns in Convoy mode",
        json_schema_extra={"group": "Game"},
    )


SHIP_ROWS = ["##..", ".###", "##.."]
#: cave generators: start gap, narrowest gap, wobble, stalactite spacing, floating-rock spacing (0 = none)
INF_MAPS: dict[str, dict[str, Any]] = {
    "cave": {"gap0": 19.0, "gapmin": 9.5, "wob": 0.25, "spike": (12, 24), "rock": None},
    "tunnel": {"gap0": 14.0, "gapmin": 9.0, "wob": 0.12, "spike": (6, 12), "rock": None},
    "canyon": {"gap0": 24.0, "gapmin": 13.0, "wob": 0.45, "spike": (20, 34), "rock": (9, 16)},
}
SHIP_XS = {1: (7,), 2: (5, 11), 3: (3, 9, 15), 4: (3, 8, 13, 18)}


@register
class Infinity(_ActionGame):
    id = "infinity"
    name = "Infinity"
    description = "A tiny ship flying forever through a procedurally generated neon cave. Up/down to steer."
    icon = "infinity"
    Settings = InfinitySettings
    step_hz = 40.0
    over_hold = 1.2
    fx_on_top = False
    max_players = 4
    controls = ("tap", "dpad", "tilt", "joystick")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("survive", "Survival", 2, 4, "ffa", "Same cave; last ship flying wins"),
        Mode("coop", "Convoy", 2, 4, "coop", "Shared respawns while a wingmate flies"),
    )
    maps: ClassVar[dict[str, str]] = {"cave": "Cave", "tunnel": "Tunnel", "canyon": "Canyon"}
    game_themes: ClassVar[dict[str, Theme]] = {
        "lava": Theme(
            p=(80, 230, 255),
            e=(255, 90, 20),
            x=(255, 230, 80),
            w=(255, 60, 10),
            hud=(255, 230, 200),
            bg=(6, 3, 2),
            r=(
                (255, 90, 20),
                (255, 60, 10),
                (255, 230, 80),
                (80, 230, 255),
                (255, 150, 60),
                (255, 200, 150),
                (255, 255, 255),
            ),
        ),
        "ice": Theme(
            p=(255, 180, 40),
            e=(120, 220, 255),
            x=(255, 90, 200),
            w=(180, 240, 255),
            hud=(220, 245, 255),
            bg=(2, 4, 10),
            r=(
                (120, 220, 255),
                (180, 240, 255),
                (255, 90, 200),
                (255, 180, 40),
                (140, 255, 220),
                (200, 200, 255),
                (255, 255, 255),
            ),
        ),
    }
    game_theme_labels: ClassVar[dict[str, str]] = {"lava": "Lava Cave", "ice": "Ice Cave"}

    SHIP_X = 7

    def new_game(self) -> None:
        self.gm = self._gm()
        self.lives = int(self.settings.lives)
        self.cfg = INF_MAPS.get(self._map_key(), INF_MAPS["cave"])
        self.speed = 14.0
        self.dist = 0.0
        self.cols: deque[tuple[int, int, int, int, int]] = deque()  # top, bottom, spike side, rock top/bottom
        self.col0 = 0  # world index of cols[0]
        self.center = 15.5
        self.drift = 0.0
        self.gap = float(self.cfg["gap0"])
        self.obs_in = 30
        self.rock_in = 40
        self.spike: list[int] | None = None
        self.rock: list[int] | None = None
        seats = self._seat_list()
        xs = SHIP_XS[min(4, len(seats))]
        self.ships: list[dict[str, Any]] = [
            {
                "seat": seat,
                "x": xs[i],
                "y": 15.0,
                "vy": 0.0,
                "ty": 15.0,
                "lapse": 0.0,
                "out": False,
                "dead": 0.0,
                "inv": 0.0,
                "dist": 0,
            }
            for i, seat in enumerate(seats)
        ]
        self.stars = [
            [self.rng.uniform(0, 32), self.rng.uniform(0, 32), self.rng.uniform(0.2, 0.6)] for _ in range(18)
        ]
        self.hue = self.rng.random()
        while len(self.cols) < 40:
            self._gen()

    # solo compatibility
    @property
    def y(self) -> float:
        return float(self.ships[0]["y"])

    def _gen(self) -> None:
        rng = self.rng
        cfg = self.cfg
        # slope limit keeps every cave flyable at the current speed
        maxslope = clamp(18.0 / max(1.0, self.speed), 0.3, 1.0) * (0.3 if self.spike or self.rock else 1.0)
        wob = float(cfg["wob"])
        self.drift = clamp(self.drift + rng.uniform(-wob, wob), -maxslope, maxslope)
        self.center += self.drift
        half = self.gap / 2
        if self.center - half < 1:
            self.center, self.drift = 1 + half, abs(self.drift) * 0.5
        if self.center + half > 30:
            self.center, self.drift = 30 - half, -abs(self.drift) * 0.5
        self.gap = max(float(cfg["gapmin"]), float(cfg["gap0"]) - self.dist / 300)
        top = round(self.center - half)
        bot = round(self.center + half)
        flag = 0
        self.obs_in -= 1
        if self.obs_in <= 0 and not self.spike and not self.rock and self.settings.spikes:
            # start a 2–3 column stalactite / stalagmite that leaves a 10 px passage
            span = bot - top
            depth = min(max(0, span - 10), 2 + round(rng.random() * (span - 10)))
            if depth >= 3:
                self.spike = [rng.choice((1, 2)), depth, rng.randrange(2, 4)]
            lo, hi = cfg["spike"]
            self.obs_in = rng.randrange(lo, hi)
        if self.spike:
            side, depth, left = self.spike
            if side == 1:
                top += depth
            else:
                bot -= depth
            flag = side
            self.spike = [side, depth, left - 1] if left > 1 else None
        m0 = m1 = -1
        if cfg["rock"]:
            self.rock_in -= 1
            if self.rock_in <= 0 and not self.spike and not self.rock and bot - top >= 13:
                # a floating boulder: 3 px tall, with at least an 8 px passage on one side
                up = rng.random() < 0.5
                r0 = top + 8 if up else bot - 11
                self.rock = [r0, rng.randrange(2, 4)]
                lo, hi = cfg["rock"]
                self.rock_in = rng.randrange(lo, hi)
            if self.rock:
                r0, left = self.rock
                m0, m1 = r0, r0 + 3
                if not (top + 2 < m0 and m1 < bot - 2):
                    m0 = m1 = -1
                self.rock = [r0, left - 1] if left > 1 else None
        self.cols.append((top, bot, flag, m0, m1))

    def _col(self, x: int) -> tuple[int, int, int, int, int]:
        i = int(self.scroll_x()) + x - self.col0
        if 0 <= i < len(self.cols):
            return self.cols[i]
        return (0, 31, 0, -1, -1)

    def scroll_x(self) -> float:
        return self.dist

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        s = next((s for s in self.ships if s["seat"] == player), None)
        if s is None or s["out"] or s["dead"] > 0:
            return
        if k in ("up", "down", "a", "b"):
            if abs(s["ty"] - s["y"]) > 6:
                s["ty"] = s["y"]
            s["ty"] = clamp(s["ty"] + (-3 if k in ("up", "a") else 3), 1, 30)

    def _ai_target(self, s: dict[str, Any]) -> float:
        """Backward pass over upcoming columns: the band of heights from which the cave stays flyable."""
        vmax = 22.0
        per_col = vmax / max(1.0, self.speed)
        look = 26
        lo, hi = 0.0, 31.0
        base = int(self.dist) - self.col0 + int(s["x"])
        n = len(self.cols)
        bands: list[tuple[float, float]] = []
        for k in range(look, -1, -1):
            i = base + k
            if not 0 <= i < n:
                continue
            ts, bs = [], []
            for j in range(i, min(n, i + 4)):
                t, b, _f, m0, m1 = self.cols[j]
                if m0 >= 0:  # a boulder: plan for the wider passage
                    if m0 - t >= b - m1:
                        b = m0
                    else:
                        t = m1
                ts.append(t)
                bs.append(b)
            flo, fhi = max(ts) + 2.3, min(bs) - 2.3
            lo, hi = max(flo, lo - per_col), min(fhi, hi + per_col)
            if lo > hi:
                lo = hi = (flo + fhi) / 2
            bands.append((lo, hi))
        if not bands:
            return float(s["y"])
        bands.reverse()  # bands[0] = the columns under the ship now
        ahead = bands[min(len(bands) - 1, 3)]
        now_lo, now_hi = bands[0]
        return clamp((ahead[0] + ahead[1]) / 2, now_lo, now_hi)

    def _flying(self) -> list[dict[str, Any]]:
        return [s for s in self.ships if not s["out"] and s["dead"] <= 0]

    def update(self, dt: float) -> None:
        self.speed = min(44.0, self.speed + float(self.settings.accel) * dt)
        self.dist += self.speed * dt
        self.score = int(self.dist / 8)
        self.hue = (self.hue + dt * 0.02) % 1.0
        while int(self.dist) - self.col0 > 4:
            self.cols.popleft()
            self.col0 += 1
        while len(self.cols) < 64:
            self._gen()
        for st in self.stars:
            st[0] -= self.speed * st[2] * dt
            if st[0] < 0:
                st[0] += 32
                st[1] = self.rng.uniform(0, 32)
        for s in self.ships:
            if s["out"]:
                continue
            if s["dead"] > 0:
                s["dead"] -= dt
                if s["dead"] <= 0:  # convoy respawn in the middle of the passage, briefly shielded
                    t, b, _f, _m0, _m1 = self._col(int(s["x"]) + 1)
                    s.update(y=(t + b) / 2, ty=(t + b) / 2, vy=0.0, inv=1.5)
                continue
            s["inv"] = max(0.0, s["inv"] - dt)
            if not self.is_human(s["seat"]):
                if s["lapse"] > 0:
                    s["lapse"] -= dt  # a lapse of concentration: keep drifting towards a stale target
                else:
                    s["ty"] = self._ai_target(s) + self.rng.gauss(0, (1 - self.skill) * 1.2)
                    if self.rng.random() < dt * (0.03 + 0.25 * (1 - self.skill)):
                        s["lapse"] = self.rng.uniform(0.25, 0.6)
            vmax = 26.0
            want = clamp((s["ty"] - s["y"]) * 10, -vmax, vmax)
            s["vy"] = approach(s["vy"], want, 300 * dt)
            s["y"] = clamp(s["y"] + s["vy"] * dt, 0, 31)
            if self.settings.trail:
                c = (
                    hsv(self.hue + self.dist * 0.004, 0.9, 1.0)
                    if self.gm == "solo"
                    else self.colour_of(s["seat"])
                )
                self.fx.emit(s["x"], s["y"] + self.rng.uniform(-0.5, 0.5), -self.speed, 0, c, 0.5)
            if s["inv"] <= 0 and self._hits(s):
                self._crash(s)
                if self.over:
                    return

    def _hits(self, s: dict[str, Any]) -> bool:
        yi0, yi1 = s["y"] - 1.2, s["y"] + 1.2
        for dx in range(4):
            t, b, _f, m0, m1 = self._col(int(s["x"]) + dx)
            if yi0 <= t or yi1 >= b:
                return True
            if m0 >= 0 and yi1 > m0 - 0.5 and yi0 < m1 + 0.5:
                return True
        return False

    def _crash(self, s: dict[str, Any]) -> None:
        x = s["x"] + 2
        self.fx.burst(self.rng, x, s["y"], WHITE, 8, 14, 0.6)
        col = hsv(self.hue, 0.9, 1) if self.gm == "solo" else self.colour_of(s["seat"])
        self.fx.burst(self.rng, x, s["y"], col, 18, 20, 1.0)
        if self.is_human(s["seat"]):
            self.damage()
        s["dist"] = self.score
        if self.gm == "coop":
            others = [o for o in self.ships if o is not s and not o["out"]]
            if others and self.lives > 0:
                self.lives -= 1
                s["dead"] = 3.0
                return
            s["out"] = True
            if all(o["out"] for o in self.ships):
                self.game_over()
            return
        s["out"] = True
        if self.gm == "survive":
            flying = self._flying()
            if len(flying) <= 1:
                for o in flying:
                    o["dist"] = self.score + 1  # the last one flying outlasts everyone
                self._end_by_score({x["seat"]: int(x["dist"]) for x in self.ships})
            return
        self.game_over()

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        tid = self._tid()
        f.clear(th.bg)
        if self.settings.stars:
            for sx, sy, depth in self.stars:
                f.set(int(sx), int(sy), scale(WHITE, depth * 0.55))
        for x in range(32):
            t, b, flag, m0, m1 = self._col(x)
            w = int(self.dist) + x
            if tid in ("classic", "neon"):
                edge = hsv(self.hue + w * 0.006, 0.85, 1.0)
            elif tid in self.game_themes:
                edge = mix(th.w, th.e, 0.5 + 0.5 * math.sin(w * 0.05))
            else:
                edge = mix(th.p, th.e, 0.5 + 0.5 * math.sin(w * 0.05))
            fill = scale(edge, 0.16)
            deep = scale(edge, 0.07)
            if t >= 0:
                f.vline(x, 0, t + 1, fill)
                f.vline(x, 0, max(0, t - 4), deep)
                f.set(x, t, edge if flag != 1 else th.x)
            if b <= 31:
                f.vline(x, b, 32 - b, fill)
                f.vline(x, b + 5, 32, deep)
                f.set(x, b, edge if flag != 2 else th.x)
            if flag == 1:
                f.vline(x, max(0, t - 6), 6, scale(th.x, 0.45))
            elif flag == 2:
                f.vline(x, b + 1, 6, scale(th.x, 0.45))
            if m0 >= 0:
                f.vline(x, m0, m1 - m0 + 1, scale(th.x, 0.5))
                f.set(x, m0, th.x)
                f.set(x, m1, th.x)
        self.fx.draw(f)
        for s in self.ships:
            if s["out"] or s["dead"] > 0 or self.over:
                continue
            if s["inv"] > 0 and int(now * 10) % 2:
                continue
            if self.gm == "solo":
                ship = tint(th.p, 0.2) if tid != "classic" else WHITE
            else:
                ship = self.colour_of(s["seat"])
            y = round(s["y"])
            x0 = int(s["x"])
            for j, row in enumerate(SHIP_ROWS):
                for i, ch in enumerate(row):
                    if ch == "#":
                        f.set(x0 + i, y - 1 + j, ship)
            f.set(x0 + 3, y, hsv(self.hue + 0.5, 0.6, 1.0) if self.gm == "solo" else WHITE)
        self.hud(f, str(self.score), y=1)
