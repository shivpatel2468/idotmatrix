"""Neon Heat — a top-down night-city getaway for 1–4 players. Original code, maps and pixel art.

A 3 × 3-screen neon grid city (96 × 78 px) under a permanent sunset band. Cars drive in right-hand lanes and
turn at intersections Pac-Man style: an arrow key is remembered and taken at the next junction, the opposite
arrow U-turns at once. Pick up a package (green), deliver it (gold) while police cars with flashing red/blue light
bars hunt the carrier. With more couriers everyone races for the same package and can steal it by ramming
(Package Rush), or one team drives the getaway cars while the other team drives the police (Cops & Robbers).
City maps change the street grid: dense Downtown, the tight lanes of Old Town, and the long roads of the Suburbs.

Hardware-friendly (docs/HARDWARE_PROTOCOL.md #9, #13): the camera never scrolls. It shows one whole screen of the
city and switches screens when the followed car crosses an edge; the roads are placed so no road runs along a
screen seam. Cars move ≤ ~1 px per streamed frame; off-screen police, packages and rivals show as blinking edge
pointers.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, measure, mix, scale
from .games_core import BLACK, WHITE, GameApp, GameSettings, Mode, Theme, shadow_text

SEAT_COLORS: tuple[RGB, ...] = ((0, 200, 255), (255, 60, 90), (80, 255, 120), (255, 200, 0))

VX = (8, 24, 40, 56, 72, 88)  # vertical road centre lines (Downtown, the default map)
HY = (6, 20, 38, 58, 72)  # horizontal road centre lines
#: city maps: id -> (label, vertical roads, horizontal roads). No road may run within HALF of a screen seam.
CITY_MAPS: dict[str, tuple[str, tuple[int, ...], tuple[int, ...]]] = {
    "downtown": ("Downtown", VX, HY),
    "oldtown": ("Old Town", (8, 20, 42, 54, 76, 88), (6, 20, 34, 46, 60, 72)),
    "suburbs": ("Suburbs", (8, 40, 56, 88), (6, 20, 38, 72)),
}
MW, MH = 96, 78  # map size in px
TOP = 6  # playfield starts below the sunset band
SW, SH = 32, 26  # one screen of city
DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))  # N E S W
N, E, S, W = range(4)
HALF = 3  # road half-width (7 px roads, lanes at ±2)

# a car pointing north, 3 × 4: headlights, windscreen, body, tail lights
CAR_N = ("hbh", "bwb", "bbb", "tbt")

#: the hand-tuned default look (also used for the shared "classic" theme)
SYNTHWAVE: dict[str, Any] = {
    "roof": (10, 4, 20),
    "edge": ((200, 0, 120), (0, 150, 200)),
    "park": (0, 14, 8),
    "window": (120, 100, 40),
    "frond": (0, 190, 90),
    "bands": ((40, 0, 60), (80, 0, 80), (150, 10, 90), (230, 60, 60), (255, 120, 20)),
    "sun": (255, 210, 60),
}
LOOKS: dict[str, dict[str, Any]] = {
    "synthwave": SYNTHWAVE,
    "noir": {
        "roof": (8, 8, 10),
        "edge": ((150, 120, 70), (110, 110, 125)),
        "park": (10, 16, 10),
        "window": (200, 170, 90),
        "frond": (90, 120, 90),
        "bands": ((14, 14, 16), (34, 34, 38), (70, 66, 62), (150, 120, 80), (230, 190, 120)),
        "sun": (255, 230, 170),
    },
    "toxic": {
        "roof": (4, 10, 6),
        "edge": ((170, 40, 220), (60, 210, 40)),
        "park": (6, 20, 6),
        "window": (180, 255, 80),
        "frond": (120, 255, 60),
        "bands": ((6, 16, 8), (20, 50, 14), (60, 110, 20), (150, 200, 30), (220, 255, 80)),
        "sun": (240, 255, 120),
    },
}
PICKUP: RGB = (60, 255, 120)
DROP: RGB = (255, 200, 40)
POLICE: RGB = (190, 190, 210)


def _theme(look: dict[str, Any]) -> Theme:
    return Theme(
        p=SEAT_COLORS[0],
        e=POLICE,
        x=DROP,
        w=look["edge"][0],
        hud=WHITE,
        bg=look["roof"],
        r=(*look["bands"], look["edge"][1], look["window"]),
    )


def _rot(rows: tuple[str, ...], d: int) -> list[str]:
    g = [list(r) for r in rows]
    for _ in range(d):
        g = [list(r) for r in zip(*g[::-1], strict=True)]  # rotate clockwise
    return ["".join(r) for r in g]


CAR_SHAPES = [_rot(CAR_N, d) for d in range(4)]


def _nodes_exits(i: int, j: int, nx: int = len(VX), ny: int = len(HY)) -> list[int]:
    out = []
    if j > 0:
        out.append(N)
    if i < nx - 1:
        out.append(E)
    if j < ny - 1:
        out.append(S)
    if i > 0:
        out.append(W)
    return out


class Car:
    __slots__ = ("acc", "col", "dir", "kind", "plan", "seat", "speed", "stun", "want", "x", "y")

    def __init__(self, kind: str, x: int, y: int, d: int, speed: float, col: RGB, seat: int = 0) -> None:
        self.kind = kind  # player | police | traffic
        self.x, self.y, self.dir = x, y, d
        self.speed = speed
        self.acc = 0.0
        self.plan: int | None = None
        self.want: int | None = None
        self.col = col
        self.seat = seat
        self.stun = 0.0


class Courier:
    """One player's state (a seat)."""

    __slots__ = ("car", "carry", "cash", "cop", "lives", "safe", "think")

    def __init__(self, car: Car, lives: int = 3, cop: bool = False) -> None:
        self.car = car
        self.cash = 0
        self.lives = lives
        self.carry = False
        self.safe = 2.0  # seconds of invulnerability
        self.think = 0.0
        self.cop = cop  # Cops & Robbers: this seat drives a police car


class HeatSettings(GameSettings):
    traffic: int = Field(5, ge=0, le=10, title="Traffic", json_schema_extra={"group": "Game"})
    police: int = Field(
        2,
        ge=1,
        le=4,
        title="Police cars",
        description="How many chase you with a package",
        json_schema_extra={"group": "Game"},
    )
    lives: int = Field(3, ge=1, le=5, title="Lives", json_schema_extra={"group": "Game"})
    match_time: int = Field(
        150,
        ge=60,
        le=300,
        title="Match length (s)",
        description="Package Rush and Cops & Robbers end when the clock runs out",
        json_schema_extra={"group": "Game"},
    )


@register
class NeonHeat(GameApp):
    id = "neonheat"
    name = "Neon Heat"
    description = (
        "Top-down neon city getaway: grab packages, deliver them and shake the police. Arrows turn at the next "
        "junction, the opposite arrow U-turns. Up to four couriers race for the package and steal it by ramming, "
        "or play Cops & Robbers."
    )
    icon = "siren"
    Settings = HeatSettings
    max_players: ClassVar[int] = 4
    controls = (
        "swipe",
        "dpad",
        "joystick",
        "gamepad",
    )  # best controllers first (phone + Play mode default to the first)
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("rush", "Package Rush", 2, 4, "ffa", "Everyone races for the package; ram to steal it"),
        Mode("cops", "Cops & Robbers", 2, 4, "versus", "Team A delivers, team B drives the police"),
    )
    maps: ClassVar[dict[str, str]] = {k: v[0] for k, v in CITY_MAPS.items()}
    game_themes: ClassVar[dict[str, Theme]] = {k: _theme(v) for k, v in LOOKS.items()}
    game_theme_labels: ClassVar[dict[str, str]] = {"synthwave": "Synthwave", "noir": "Noir", "toxic": "Toxic"}
    step_hz = 30.0
    over_hold = 2.5

    # ----------------------------------------------------------------- setup
    def new_game(self) -> None:
        self._map_key: tuple[str, str] | None = None
        _label, self.VX, self.HY = CITY_MAPS.get(self.map_id, CITY_MAPS["downtown"])
        self.cars: list[Car] = []
        self.players: dict[int, Courier] = {}
        nx, ny = len(self.VX), len(self.HY)
        starts = ((1, 1, E), (nx - 2, ny - 2, W), (1, ny - 2, E), (nx - 2, 1, W))
        cops = self.play_mode.id == "cops" and bool(self.roster)
        for seat in sorted(self.roster) if self.roster else (1, 2):
            i, j, d = starts[(seat - 1) % 4]
            x, y = self._lane_pos(self.VX[i] + (6 if d == E else -6), self.HY[j], d)
            col = self.colour_of(seat) if self.roster else self.seat_colour(seat)
            cop = cops and self.team_of(seat) == 1
            car = Car("player", x, y, d, 11.5 if cop else 11.0, col, seat)
            self.cars.append(car)
            self.players[seat] = Courier(car, int(self.settings.lives), cop)
        for _ in range(self.settings.traffic):
            self._spawn_traffic()
        self.pickup: tuple[int, int] | None = None
        self.drop: tuple[int, int] | None = None
        self.job_t = 1.0
        self.banner = ""
        self.banner_t = 0.0
        self.follow = 1
        self.sx, self.sy = self._screen_of(self.players[min(self.players)].car)
        self.level = 1
        self.multi = bool(self.roster) and len(self.players) > 1
        self.time_left = float(self.settings.match_time)
        self.tick = 0

    @property
    def active_seats(self) -> list[int]:
        """Solo: seat 1 always plays; seat 2 joins the city when a phone is seated (or the AI plays it in the demo).
        A match: every seat in the roster that still has lives."""
        if self.roster:
            return [s for s in sorted(self.players) if self.players[s].lives > 0]
        if self.max_players > 1 and (2 in self.seats or not self.human):
            return [1, 2]
        return [1]

    def _lane_pos(self, x: int, y: int, d: int) -> tuple[int, int]:
        """Snap a point on a road centre line onto the lane for direction d."""
        if d == N:
            return x + 2, y
        if d == S:
            return x - 2, y
        if d == E:
            return x, y + 2
        return x, y - 2

    def _exits(self, i: int, j: int) -> list[int]:
        return _nodes_exits(i, j, len(self.VX), len(self.HY))

    def _spawn_traffic(self) -> None:
        rng = self.rng
        pal = [(90, 50, 140), (120, 70, 40), (60, 60, 90), (40, 90, 90), (110, 40, 70)]  # dim: scenery
        VX, HY = self.VX, self.HY
        for _ in range(20):
            if rng.random() < 0.5:
                i = rng.randrange(len(VX))
                y = rng.randrange(HY[0] + 4, HY[-1] - 4)
                d = rng.choice((N, S))
                x, y = self._lane_pos(VX[i], y, d)
            else:
                j = rng.randrange(len(HY))
                x = rng.randrange(VX[0] + 4, VX[-1] - 4)
                d = rng.choice((E, W))
                x, y = self._lane_pos(x, HY[j], d)
            if all(abs(c.x - x) + abs(c.y - y) > 10 for c in self.cars):
                self.cars.append(Car("traffic", x, y, d, 5.0, rng.choice(pal)))
                return

    def _spawn_police(self, target: Car) -> None:
        rng = self.rng
        VX, HY = self.VX, self.HY
        best = None
        for _ in range(30):
            i, j = rng.randrange(len(VX)), rng.randrange(len(HY))
            dist = abs(VX[i] - target.x) + abs(HY[j] - target.y)
            if dist >= 48 and (best is None or rng.random() < 0.5):
                best = (i, j)
        if best is None:
            best = (0, 0) if target.x > MW / 2 else (len(VX) - 1, len(HY) - 1)
        i, j = best
        d = rng.choice(self._exits(i, j))
        x, y = self._lane_pos(VX[i], HY[j], d)
        x += DIRS[d][0] * 4
        y += DIRS[d][1] * 4
        self.cars.append(Car("police", x, y, d, 8.6, POLICE))

    def _new_job(self) -> None:
        rng = self.rng
        cars = [self.players[s].car for s in self.active_seats]
        for _ in range(40):
            p = (rng.randrange(len(self.VX)), rng.randrange(len(self.HY)))
            if all(abs(self.VX[p[0]] - c.x) + abs(self.HY[p[1]] - c.y) > 30 for c in cars):
                self.pickup = p
                return
        self.pickup = (0, 0)

    # --------------------------------------------------------------- driving
    def _step_car(self, car: Car) -> None:
        """Advance one pixel along the lane; decide at a junction's entry line, turn on the target lane's line."""
        VX, HY = self.VX, self.HY
        dx, dy = DIRS[car.dir]
        car.x += dx
        car.y += dy
        entry = None
        if car.dir == N and car.y - 2 in HY and car.x - 2 in VX:
            entry = (VX.index(car.x - 2), HY.index(car.y - 2))
        elif car.dir == S and car.y + 2 in HY and car.x + 2 in VX:
            entry = (VX.index(car.x + 2), HY.index(car.y + 2))
        elif car.dir == E and car.x + 2 in VX and car.y - 2 in HY:
            entry = (VX.index(car.x + 2), HY.index(car.y - 2))
        elif car.dir == W and car.x - 2 in VX and car.y + 2 in HY:
            entry = (VX.index(car.x - 2), HY.index(car.y + 2))
        if entry is not None:
            exits = [d for d in self._exits(*entry) if (d - car.dir) % 4 != 2]
            car.plan = self._choose(car, entry, exits)
            if car.plan == car.dir:
                car.plan = None
        p = car.plan
        if p is not None and (p - car.dir) % 4 != 2:
            ok = (
                (p == E and car.y - 2 in HY)
                or (p == W and car.y + 2 in HY)
                or (p == N and car.x - 2 in VX)
                or (p == S and car.x + 2 in VX)
            )
            if ok:
                car.dir = p
                car.plan = None

    def _uturn(self, car: Car) -> None:
        d = (car.dir + 2) % 4
        if car.dir in (N, S):
            car.x += -4 if car.dir == N else 4
        else:
            car.y += -4 if car.dir == E else 4
        car.dir = d
        car.plan = None

    def _choose(self, car: Car, node: tuple[int, int], exits: list[int]) -> int:
        if car.kind == "traffic":
            if car.dir in exits and self.rng.random() < 0.55:
                return car.dir
            return self.rng.choice(exits)
        nx, ny = self.VX[node[0]], self.HY[node[1]]
        if car.kind == "police":
            tgt = self._police_target(car)
            if tgt is None or self.rng.random() < 0.12:
                return self.rng.choice(exits)
            return min(exits, key=lambda d: self._dist_after(node, d, tgt.x, tgt.y) + self.rng.random() * 6)
        seat = car.seat
        if self.is_human(seat):
            w = car.want
            car.want = None
            if w in exits:
                return w
            return car.dir if car.dir in exits else self.rng.choice(exits)
        if self.players[seat].cop:
            return self._cop_choose(car, node, exits)
        return self._ai_choose(car, node, exits, nx, ny)

    def _dist_after(self, node: tuple[int, int], d: int, tx: float, ty: float) -> float:
        i, j = node
        i2, j2 = i + DIRS[d][0], j + DIRS[d][1]
        x2, y2 = self.VX[i2], self.HY[j2]
        leg = abs(x2 - self.VX[i]) + abs(y2 - self.HY[j])
        return leg + abs(x2 - tx) + abs(y2 - ty)

    def _teammates(self, a: int, b: int) -> bool:
        return self.play_mode.id == "cops" and bool(self.roster) and self.team_of(a) == self.team_of(b)

    def _goal_of(self, seat: int) -> tuple[float, float] | None:
        me = self.players[seat]
        if me.carry and self.drop is not None:
            return self.VX[self.drop[0]], self.HY[self.drop[1]]
        if self.pickup is not None:
            return self.VX[self.pickup[0]], self.HY[self.pickup[1]]
        for s, other in self.players.items():  # someone else has it: chase them to steal it
            if s != seat and other.carry and s in self.active_seats and not self._teammates(s, seat):
                return other.car.x, other.car.y
        return None

    def _cop_choose(self, car: Car, node: tuple[int, int], exits: list[int]) -> int:
        """A police seat's AI: hunt the carrier, else stake out the package, else the nearest robber."""
        robbers = [self.players[s] for s in self.active_seats if not self.players[s].cop]
        tgt: tuple[float, float] | None = None
        carriers = [r for r in robbers if r.carry]
        if carriers:
            c = min(carriers, key=lambda r: abs(r.car.x - car.x) + abs(r.car.y - car.y)).car
            tgt = (c.x, c.y)
        elif self.pickup is not None:
            tgt = (self.VX[self.pickup[0]], self.HY[self.pickup[1]])
        elif robbers:
            c = min(robbers, key=lambda r: abs(r.car.x - car.x) + abs(r.car.y - car.y)).car
            tgt = (c.x, c.y)
        if tgt is None:
            return self.rng.choice(exits)
        noise = (1.0 - self.skill) * 30
        return min(exits, key=lambda d: self._dist_after(node, d, *tgt) + self.rng.random() * noise)

    def _ai_choose(self, car: Car, node: tuple[int, int], exits: list[int], nx: int, ny: int) -> int:
        goal = self._goal_of(car.seat)
        cops = [c for c in self.cars if c.kind == "police"]
        cops += [self.players[s].car for s in self.active_seats if self.players[s].cop]
        noise = (1.0 - self.skill) * 40
        best, best_s = exits[0], 1e9
        for d in exits:
            i2, j2 = node[0] + DIRS[d][0], node[1] + DIRS[d][1]
            x2, y2 = self.VX[i2], self.HY[j2]
            s = 0.0 if goal is None else self._dist_after(node, d, *goal)
            if goal is None:
                s = self.rng.random() * 30
            me = self.players[car.seat]
            for c in cops:
                if not me.carry and c.kind == "police" and self._police_target(c) is not car:
                    continue
                # a road that leads towards a police car is a road to avoid
                dc = abs(c.x - x2) + abs(c.y - y2)
                if dc < 30:
                    s += (30 - dc) * 2.2 * self.skill
                if (c.x - nx) * DIRS[d][0] + (c.y - ny) * DIRS[d][1] > 0 and dc < 20:
                    s += 25 * self.skill
            s += self.rng.random() * noise
            if s < best_s:
                best, best_s = d, s
        return best

    def _police_target(self, cop: Car) -> Car | None:
        best, bd = None, 1e9
        for s in self.active_seats:
            p = self.players[s]
            if not p.carry:
                continue
            d = abs(p.car.x - cop.x) + abs(p.car.y - cop.y)
            if d < bd:
                best, bd = p.car, d
        return best

    def _blocked(self, car: Car) -> bool:
        """Something directly ahead in the same lane."""
        dx, dy = DIRS[car.dir]
        for o in self.cars:
            if o is car or o.dir != car.dir:
                continue
            if car.kind == "police" and o.kind == "player":
                continue  # the police don't queue behind their suspect
            if o.kind == "player" and o.seat not in self.active_seats:
                continue
            ax = (o.x - car.x) * dx + (o.y - car.y) * dy
            lat = abs((o.x - car.x) * dy) + abs((o.y - car.y) * dx)
            if lat == 0 and 0 < ax <= 5:
                return True
        return False

    # ------------------------------------------------------------------ input
    def pilot_anchor(self) -> tuple[float, float] | None:
        """The fruit-fly pilot's eye follows seat 1's car (on screen coordinates)."""
        p = self.players.get(1)
        return None if p is None else self._scr(p.car.x, p.car.y)

    def fly_lure(self) -> list[tuple[float, float, float]]:
        """The job: the pickup, the drop-off while carrying, or a rival carrying the parcel (may be off-screen)."""
        p = self.players.get(1)
        if p is None or 1 not in self.active_seats:
            return []
        goal = self._goal_of(1)
        return [] if goal is None else [(*self._scr(*goal), 1.0)]

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        p = self.players.get(player)
        if p is None or player not in self.active_seats:
            return
        d = {"up": N, "right": E, "down": S, "left": W}.get(k)
        car = p.car
        if d is None:
            return
        if (d - car.dir) % 4 == 2:
            self._uturn(car)
        elif d != car.dir:
            car.want = d
            car.plan = None if car.plan is None else car.plan
            # already inside a junction: take the turn if its line is still ahead
            if self._in_junction(car):
                car.plan = d

    def _in_junction(self, car: Car) -> bool:
        return any(abs(car.x - x) <= HALF for x in self.VX) and any(abs(car.y - y) <= HALF for y in self.HY)

    # ------------------------------------------------------------------- loop
    def update(self, dt: float) -> None:
        self.banner_t = max(0.0, self.banner_t - dt)
        seats = self.active_seats
        if not self.roster and 2 in self.players:
            if 2 not in seats:
                self.players[2].car.x = -99  # parked out of the city
            elif self.players[2].car.x < 0:
                x, y = self._lane_pos(self.VX[-2] - 6, self.HY[-2], W)
                self.players[2].car.x, self.players[2].car.y, self.players[2].car.dir = x, y, W
        if self.pickup is None and self.drop is None and not any(self.players[s].carry for s in seats):
            self.job_t -= dt
            if self.job_t <= 0:
                self._new_job()
        n_traffic = sum(1 for c in self.cars if c.kind == "traffic")
        if n_traffic < self.settings.traffic:
            self._spawn_traffic()
        for car in self.cars:
            if car.kind == "player" and car.seat not in seats:
                continue
            if car.stun > 0:
                car.stun -= dt
                continue
            sp = car.speed
            if car.kind == "police":
                sp = min(10.6, 8.0 + 0.4 * self.level)  # the heat rises with every delivery
            car.acc += sp * dt
            while car.acc >= 1.0:
                car.acc -= 1.0
                if self._blocked(car):
                    car.acc = 0.0
                    break
                self._step_car(car)
        for s in seats:
            self.players[s].safe = max(0.0, self.players[s].safe - dt)
        self._collide(seats)
        # the police give up on nobody
        if not any(self.players[s].carry for s in seats):
            for c in [c for c in self.cars if c.kind == "police"]:
                if not self._on_screen(c.x, c.y) and self.rng.random() < dt * 0.5:
                    self.cars.remove(c)
        # camera: follow a human seat if there is one, else seat 1
        seats = self.active_seats
        humans = [s for s in seats if self.is_human(s)]
        self.follow = humans[0] if humans else (seats[0] if seats else self.follow)
        fc = self.players[self.follow].car
        if fc.x >= 0:
            self.sx, self.sy = self._screen_of(fc)
        self.score = self.players[1].cash if 1 in self.players else 0
        if self.multi and not self.over:
            self.time_left -= dt
            self._check_end()

    def _check_end(self) -> None:
        seats = self.active_seats
        cash = {s: self.players[s].cash for s in self.players}
        if self.play_mode.id == "cops":
            robbers = [s for s in seats if not self.players[s].cop]
            team = {0: 0, 1: 0}
            for p in self.players.values():
                team[1 if p.cop else 0] += p.cash
            if not robbers:  # every getaway car is out of lives
                self.result(winner_team=1, scores=cash)
            elif self.time_left <= 0:
                win = 0 if team[0] >= team[1] else 1
                self.result(winner_team=win, scores=cash)
            return
        if len(seats) <= 1 or self.time_left <= 0:
            pool = seats if len(seats) == 1 and self.time_left > 0 else list(self.players)
            win = max(pool, key=lambda s: (cash[s], self.players[s].lives))
            self.result(winner_seat=win, scores=cash)

    def _collide(self, seats: list[int]) -> None:
        for s in seats:
            me = self.players[s]
            car = me.car
            if me.cop:
                self._cop_collide(s, seats)
                continue
            # pickup / delivery
            if self.pickup is not None:
                px, py = self.VX[self.pickup[0]], self.HY[self.pickup[1]]
                if abs(car.x - px) <= 3 and abs(car.y - py) <= 3:
                    me.carry = True
                    self.pickup = None
                    self._pick_drop(car)
                    n = min(4, self.settings.police + self.level // 3)
                    if self.multi and self.play_mode.id == "cops":
                        n = max(0, n - 1)  # people drive the police too
                    for _ in range(n):
                        self._spawn_police(car)
                    self._say("GO!", 0.8)
                    self.fx.burst(self.rng, *self._scr(car.x, car.y), PICKUP, 10, 10, 0.5)
            if me.carry and self.drop is not None:
                dx, dy = self.VX[self.drop[0]], self.HY[self.drop[1]]
                if abs(car.x - dx) <= 3 and abs(car.y - dy) <= 3:
                    cops = sum(1 for c in self.cars if c.kind == "police")
                    me.cash += 10 + 5 * cops
                    me.carry = False
                    self.drop = None
                    self.job_t = 1.2
                    self.level += 1
                    self.flash = 0.3
                    self._say(f"+{10 + 5 * cops}", 1.0)
                    self.fx.burst(self.rng, *self._scr(car.x, car.y), (255, 210, 60), 14, 12, 0.7)
                    self.fx.burst(self.rng, *self._scr(car.x, car.y), WHITE, 5, 6, 0.4)
            for o in self.cars:
                if o is car or abs(o.x - car.x) > 3 or abs(o.y - car.y) > 3:
                    continue
                if o.kind == "police" and me.carry and me.safe <= 0:
                    self._busted(s, o)
                    break
                if o.kind == "traffic" and car.stun <= 0 and o.stun <= 0:
                    car.stun = 0.5
                    o.stun = 0.8
                    self.fx.burst(self.rng, *self._scr(car.x, car.y), (255, 170, 40), 6, 8, 0.4)
                    if self.is_human(s):
                        self.damage(0.4)  # a fender-bender: a light red fade
                if o.kind == "player" and o.seat in seats and o.seat != s and not self._teammates(s, o.seat):
                    other = self.players[o.seat]
                    if other.cop:
                        continue
                    if other.carry and other.safe <= 0 and car.stun <= 0:  # rammed: the package changes hands
                        other.carry, me.carry = False, True
                        other.safe = me.safe = 3.0
                        o.stun = 1.2
                        self._say("STEAL", 0.9)
                        if self.is_human(o.seat):
                            self.damage(0.6)
                        self.fx.burst(self.rng, *self._scr(o.x, o.y), PICKUP, 8, 9, 0.5)

    def _cop_collide(self, s: int, seats: list[int]) -> None:
        """A police seat touching the carrier busts them: the cops' team scores."""
        cop = self.players[s]
        for r in seats:
            rob = self.players[r]
            if rob.cop or not rob.carry or rob.safe > 0:
                continue
            if abs(rob.car.x - cop.car.x) <= 3 and abs(rob.car.y - cop.car.y) <= 3:
                cop.cash += 15
                self._busted(r, None)
                return

    def _busted(self, seat: int, cop: Car | None) -> None:
        me = self.players[seat]
        me.carry = False
        me.lives -= 1
        me.safe = 2.5
        me.car.stun = 1.0
        if cop is not None:
            self.cars.remove(cop)
        if self.is_human(seat):
            self.damage()
        self.fx.burst(self.rng, *self._scr(me.car.x, me.car.y), (255, 40, 40), 8, 10, 0.6)
        self.fx.burst(self.rng, *self._scr(me.car.x, me.car.y), (40, 90, 255), 8, 10, 0.6)
        # the package goes back on the street somewhere else
        self.drop = None
        self._new_job()
        self._say("BUSTED", 1.4)
        if me.lives <= 0:
            if self.multi:
                me.car.x = -99  # out of the match: parked out of the city
                self._say(f"P{seat} OUT", 1.6)
            else:
                self.game_over()

    def _pick_drop(self, car: Car) -> None:
        rng = self.rng
        VX, HY = self.VX, self.HY
        best = None
        for _ in range(40):
            p = (rng.randrange(len(VX)), rng.randrange(len(HY)))
            if 40 <= abs(VX[p[0]] - car.x) + abs(HY[p[1]] - car.y) <= 70:
                best = p
                break
        self.drop = best or (0 if car.x > MW / 2 else len(VX) - 1, 0 if car.y > MH / 2 else len(HY) - 1)

    def _say(self, text: str, t: float) -> None:
        self.banner, self.banner_t = text, t

    # ----------------------------------------------------------------- camera
    def _screen_of(self, car: Car) -> tuple[int, int]:
        return min(2, max(0, car.x // SW)), min(2, max(0, car.y // SH))

    def _scr(self, x: float, y: float) -> tuple[float, float]:
        return x - self.sx * SW, y - self.sy * SH + TOP

    def _on_screen(self, x: float, y: float) -> bool:
        sx, sy = self._scr(x, y)
        return 0 <= sx < 32 and TOP <= sy < 32

    # ------------------------------------------------------------------- draw
    @property
    def theme_id(self) -> str:
        return str(self.sel.get("theme", self.settings.theme))

    def _look(self) -> dict[str, Any]:
        tid = self.theme_id
        if tid == "classic":
            return SYNTHWAVE
        if tid in LOOKS:
            return LOOKS[tid]
        th = self.theme
        return {
            "roof": scale(th.bg, 1.5),
            "edge": (scale(th.e, 0.8), scale(th.p, 0.8)),
            "park": scale(th.w, 0.15),
            "window": scale(th.x, 0.5),
            "frond": (255, 0, 190),
            "bands": (scale(th.bg, 3.0), scale(th.w, 0.4), scale(th.w, 0.7), th.e, th.x),
            "sun": th.x,
        }

    def _map(self) -> np.ndarray:
        key = (self.theme_id, self.map_id)
        if self._map_key == key:
            return self._map_img
        self._map_key = key
        look = self._look()
        VX, HY = self.VX, self.HY
        pink, cyan = look["edge"]
        road = (0, 0, 0)
        img = np.zeros((MH, MW, 3), dtype=np.uint8)
        img[:] = look["roof"]
        for x in VX:
            img[HY[0] - HALF : HY[-1] + HALF + 1, x - HALF : x + HALF + 1] = road
        for y in HY:
            img[y - HALF : y + HALF + 1, VX[0] - HALF : VX[-1] + HALF + 1] = road
        # blocks: neon edge on the kerb side facing the road, parks with palms, lit windows
        xs = [0, *[x + HALF + 1 for x in VX]]
        xe = [*[x - HALF for x in VX], MW]
        ys = [0, *[y + HALF + 1 for y in HY]]
        ye = [*[y - HALF for y in HY], MH]
        k = 0
        rng = np.random.default_rng(7)
        for bi in range(len(xs)):
            for bj in range(len(ys)):
                x0, x1, y0, y1 = xs[bi], xe[bi], ys[bj], ye[bj]
                if x1 - x0 < 3 or y1 - y0 < 3:
                    continue
                k += 1
                park = (bi * 3 + bj * 5) % 7 == 2
                if park:
                    img[y0:y1, x0:x1] = look["park"]
                    for px in range(x0 + 2, x1 - 2, 5):
                        self._palm(img, px, y0 + (y1 - y0) // 2 - 2, look["frond"])
                    continue
                edge = pink if k % 2 else cyan
                img[y0, x0:x1] = edge
                img[y1 - 1, x0:x1] = edge
                img[y0:y1, x0] = edge
                img[y0:y1, x1 - 1] = edge
                for _ in range(max(1, (x1 - x0) * (y1 - y0) // 40)):
                    wx = int(rng.integers(x0 + 2, max(x0 + 3, x1 - 2)))
                    wy = int(rng.integers(y0 + 2, max(y0 + 3, y1 - 2)))
                    img[wy, wx] = look["window"]
        self._map_img = img
        return img

    def _palm(self, img: np.ndarray, x: int, y: int, frond: RGB) -> None:
        trunk = (110, 60, 20)
        pts = [(-2, 0), (0, 0), (2, 0), (-1, 1), (0, 1), (1, 1)]
        for dx, dy in pts:
            if 0 <= y + dy < MH and 0 <= x + dx < MW:
                img[y + dy, x + dx] = frond
        for dy in (2, 3, 4):
            if 0 <= y + dy < MH and 0 <= x < MW:
                img[y + dy, x] = trunk

    def _sunset(self, f: Frame) -> None:
        look = self._look()
        for y, c in enumerate(look["bands"]):
            f.hline(0, y, 32, c)
        # a striped sun sinking into the band
        for y, half in ((1, 2), (2, 3), (4, 3)):
            f.hline(16 - half, y, half * 2, look["sun"])
        f.hline(0, 5, 32, BLACK)

    def draw(self, f: Frame, now: float) -> None:
        img = self._map()
        ox, oy = self.sx * SW, self.sy * SH
        f.px[TOP:32, :] = img[oy : oy + SH, ox : ox + SW]
        self._sunset(f)
        blink = int(now * 4) % 2
        # markers
        for node, col in ((self.pickup, PICKUP), (self.drop, DROP)):
            if node is None:
                continue
            x, y = self._scr(self.VX[node[0]], self.HY[node[1]])
            if self._on_screen(self.VX[node[0]], self.HY[node[1]]):
                c = col if blink else scale(col, 0.45)
                f.rect(int(x) - 1, int(y) - 1, 3, 3, c, fill=False)
                f.set(int(x), int(y), WHITE if blink else col)
            else:
                self._pointer(f, x, y, col if blink else scale(col, 0.4))
        # cars: traffic, police, players (players on top)
        order = sorted(self.cars, key=lambda c: {"traffic": 0, "police": 1, "player": 2}[c.kind])
        seats = self.active_seats
        for car in order:
            if car.kind == "player" and car.seat not in seats:
                continue
            x, y = self._scr(car.x, car.y)
            if not self._on_screen(car.x, car.y):
                if car.kind == "police":
                    self._pointer(f, x, y, (255, 30, 30) if blink else (40, 80, 255))
                elif car.kind == "player":
                    self._pointer(f, x, y, car.col)
                continue
            self._car(f, car, int(x), int(y), now)
        self.fx.draw(f)
        self._hud(f, now)

    def _car(self, f: Frame, car: Car, x: int, y: int, now: float) -> None:
        shape = CAR_SHAPES[car.dir]
        h, w = len(shape), len(shape[0])
        # anchor: the car's lane point is the centre of its footprint
        x0 = x - w // 2
        y0 = y - h // 2
        body = car.col
        lights = car.kind == "police"
        if car.kind == "player":
            me = self.players[car.seat]
            lights = me.cop
            if me.safe > 0 and int(now * 8) % 2:
                return
            if car.stun > 0:
                body = mix(body, WHITE, 0.4)
        siren = int(now * 6) % 2
        for yy, row in enumerate(shape):
            for xx, ch in enumerate(row):
                if ch == "b":
                    c = body
                elif ch == "w":
                    if lights:
                        c = (255, 20, 20) if (xx + yy + siren) % 2 else (30, 70, 255)
                    else:
                        c = scale(body, 0.35)
                elif ch == "h":
                    c = (255, 240, 170)
                else:
                    c = (200, 0, 0)
                f.set(x0 + xx, y0 + yy, c)
        if car.kind == "player":  # headlight beam: makes the couriers pop out of the traffic
            dx, dy = DIRS[car.dir]
            fx = x0 + (w if dx > 0 else -1 if dx < 0 else w // 2)
            fy = y0 + (h if dy > 0 else -1 if dy < 0 else h // 2)
            for k in (0, 1):
                f.set(fx + dx * k, fy + dy * k, scale((255, 240, 170), 0.45 / (k + 1)))
        if car.kind == "player" and self.players[car.seat].carry:
            f.set(x0 + w // 2, y0 + h // 2, PICKUP if int(now * 3) % 2 else WHITE)

    def _pointer(self, f: Frame, x: float, y: float, col: RGB) -> None:
        px = int(min(31, max(0, x)))
        py = int(min(31, max(TOP, y)))
        f.set(px, py, col)
        # a second pixel along the edge makes it read as a marker, not a stray LED
        if px in (0, 31):
            f.set(px, min(31, py + 1), col)
        else:
            f.set(min(31, px + 1), py, col)

    def _hud(self, f: Frame, now: float) -> None:
        if not self.settings.show_score:
            return
        seats = self.active_seats
        if self.multi:
            me = self.players[self.follow]
            shadow_text(f, 1, 0, str(me.cash), me.car.col)
            t = str(max(0, int(self.time_left + 0.99)))
            shadow_text(
                f, 31 - measure(t), 0, t, WHITE if self.time_left > 10 or int(now * 4) % 2 else (255, 60, 60)
            )
        else:
            p1 = self.players[1]
            c1 = SEAT_COLORS[0] if len(seats) > 1 else WHITE
            shadow_text(f, 1, 0, str(p1.cash), c1)
            if len(seats) > 1:
                p2 = self.players[2]
                t = str(p2.cash)
                shadow_text(f, 31 - measure(t), 0, t, SEAT_COLORS[1])
            else:
                for i in range(p1.lives):
                    f.set(30 - i * 2, 1, (255, 60, 90))
                    f.set(30 - i * 2, 2, (255, 60, 90))
        if self.banner_t > 0:
            w = measure(self.banner)
            y = 17
            f.rect((32 - w) // 2 - 1, y - 1, w + 2, 7, BLACK)
            col = (255, 40, 40) if self.banner == "BUSTED" and int(now * 6) % 2 else (255, 230, 120)
            f.text_center(y, self.banner, col)

    def status(self) -> dict[str, Any]:
        st = super().status()
        if "seats" in st:  # only the seats that have a car in this city (the demo city has two couriers)
            st["seats"] = [x for x in st["seats"] if x["seat"] in self.players]
        st["cash"] = {s: self.players[s].cash for s in self.active_seats}
        st["lives"] = {s: self.players[s].lives for s in self.active_seats}
        if self.multi:
            st["time_left"] = max(0, int(self.time_left))
        return st
