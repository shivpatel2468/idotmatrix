"""Paddle, runner and racing games: Pong, Breakout, Flappy, Dino Runner, Racer. Original code and art.

Every game here keeps its classic solo self-play in attract mode (empty roster) and adds multiplayer modes, maps
and genre themes on top of the shared game flow in `games_core`:

- Pong: 1 v 1, Doubles (front + back paddle per side, 2 v 2) and 4 Way (a paddle per wall, last one standing);
  maps Open / Block (centre bumper) / Portals.
- Breakout: Solo, Co-op (two paddles, two balls, one wall) and Versus (split field, mirrored walls);
  maps Classic / Fortress (steel bricks) / Descend (the wall creeps down).
- Flappy: Solo and Race (up to 4 birds through the same pipes, gaps shrink); maps Pipes / Moving / Cave.
- Dino Runner: Solo and Race (up to 4 runners on one track); maps Desert / Canyon (pits) / Rush.
- Racer: Solo and Race (2-4 cars on one road); maps Highway / Roadworks (lane closures) / Rush hour.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, Sprite, mix, scale
from .games_core import THEMES, WHITE, GameApp, GameSettings, Mode, Theme, approach, clamp, tint

GAME = {"group": "Game"}
CLASSIC_R = THEMES["classic"].r


def _tid(app: GameApp) -> str:
    """The theme id in use (the home menu may override the stored setting)."""
    return str(app.sel.get("theme", app.settings.theme))


def _far(c: RGB, others: list[RGB], d: int = 150) -> bool:
    return all(sum(abs(a - b) for a, b in zip(c, o, strict=True)) > d for o in others)


def _race_finished(app: GameApp, racers: list[dict[str, Any]]) -> bool:
    """Race modes end when one racer is left, or when every person is out (the AI needn't race on alone)."""
    alive = [r for r in racers if r["alive"]]
    humans = [r for r in racers if app.roster.get(r["seat"], {}).get("human")]
    if len(alive) <= 1 or (humans and not any(r["alive"] for r in humans)):
        if alive:
            win = max(alive, key=lambda r: (r["score"], -r["seat"]))
        else:
            win = max(racers, key=lambda r: (r["score"], -r["seat"]))
        app.result(winner_seat=win["seat"], scores={r["seat"]: int(r["score"]) for r in racers})
        return True
    return False


def _pips(f: Frame, racers: list[dict[str, Any]], app: GameApp, y: int = 1) -> None:
    """One pip per racer, in the seat colour (dim when out)."""
    for i, r in enumerate(racers):
        c = app.colour_of(r["seat"])
        f.rect(1 + i * 3, y, 2, 2, c if r["alive"] else scale(c, 0.25))


# =====================================================================================================
# Pong
# =====================================================================================================
PONG_THEMES = {
    "arcade": Theme(
        p=(0, 220, 255), e=(255, 70, 110), x=(255, 214, 0), w=(90, 90, 150), hud=(255, 255, 255),
        bg=(3, 3, 10), r=CLASSIC_R,
    ),
    "court": Theme(
        p=(255, 236, 110), e=(120, 200, 255), x=(220, 255, 90), w=(60, 150, 80), hud=(225, 255, 225),
        bg=(2, 12, 4), r=CLASSIC_R,
    ),
    "ice": Theme(
        p=(140, 230, 255), e=(255, 110, 170), x=(255, 255, 255), w=(70, 120, 180), hud=(200, 240, 255),
        bg=(2, 6, 14), r=CLASSIC_R,
    ),
}  # fmt: skip


class PongSettings(GameSettings):
    paddle: int = Field(7, ge=4, le=12, title="Paddle size")
    points: int = Field(7, ge=3, le=21, title="Points to win")
    lives: int = Field(3, ge=1, le=9, title="Lives (4 Way)", json_schema_extra=GAME)


SIDES = ("L", "R", "T", "B")
PORTALS = ((10, 17), (20, 11))  # a linked pair of 2 × 4 portals
SERVE_FROM = {"L": (10.0, 15.0), "R": (20.0, 15.0), "T": (15.0, 10.0), "B": (15.0, 20.0)}


@register
class Pong(GameApp):
    id = "pong"
    name = "Pong"
    description = (
        "Two paddles, one ball that speeds up every hit. Plays itself; up/down steers the left paddle. "
        "Modes: 1 v 1, Doubles (2 v 2, front and back paddles) and 4 Way (a paddle on every wall). "
        "Friends join from their phones (local Wi-Fi)."
    )
    icon = "circle-dot"
    Settings = PongSettings
    max_players = 4  # seat 1 = host (left paddle in attract), seat 2 = right paddle; 3-4 in Doubles / 4 Way
    controls = ("joystick", "dpad", "gamepad")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("classic", "1 v 1", 1, 2, "versus", "Left against right"),
        Mode("doubles", "Doubles", 4, 4, "versus", "2 v 2: a back and a front paddle per side"),
        Mode("fourway", "4 Way", 2, 4, "ffa", "A paddle on every wall; last one standing"),
    )
    maps: ClassVar[dict[str, str]] = {"open": "Open", "block": "Block", "portals": "Portals"}
    game_themes: ClassVar[dict[str, Theme]] = PONG_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"arcade": "Arcade", "court": "Court", "ice": "Ice"}

    # ------------------------------------------------------------ setup
    def pilot_anchor(self) -> tuple[float, float] | None:
        """The fruit-fly pilot's eye follows seat 1's paddle."""
        pad = next((p for p in self.pads if p["seat"] == 1), None)
        if pad is None:
            return None
        mid = pad["pos"] + self.settings.paddle / 2
        return (pad["plane"], mid) if pad["side"] in ("L", "R") else (mid, pad["plane"])

    def new_game(self) -> None:
        self.mode = self.play_mode.id if self.roster else "classic"
        self.ls = self.rs = 0
        self.rally = 0
        self.max_rally = 0
        self.trail: deque[tuple[float, float]] = deque(maxlen=5)
        self.portal_cd = 0.0
        self.pads: list[dict[str, Any]] = []
        self.lives: dict[str, int] = {}
        if self.mode == "fourway":
            for seat, side in zip(sorted(self.roster), SIDES, strict=False):
                self.pads.append(self._pad(seat, side, 0))
                self.lives[side] = self.settings.lives
            self.open = set(self.lives)
        else:
            depths = (0, 6) if self.mode == "doubles" else (0,)
            for team, side in ((0, "L"), (1, "R")):
                seats = self._side_seats(team)
                for j, d in enumerate(depths):
                    self.pads.append(self._pad(seats[j % len(seats)], side, d))
            self.open = {"L", "R"}
        self.err = [0.0] * len(self.pads)
        self._serve(self.rng.choice(sorted(self.open)))

    def _team(self, seat: int) -> int:
        t = self.team_of(seat)
        return (0 if seat % 2 else 1) if t is None else t

    def _side_seats(self, team: int) -> list[int]:
        seats = [s for s in sorted(self.roster) if self._team(s) == team]
        return seats or [2 if team else 1]  # attract / 1-player: seat 2 (a phone or the AI) on the right

    def _pad(self, seat: int, side: str, depth: int) -> dict[str, Any]:
        p = self.settings.paddle
        plane = {"L": depth + 2.0, "R": 28.0 - depth, "T": 2.0, "B": 28.0}[side]
        mid = 16 - p / 2
        return {"seat": seat, "side": side, "d": depth, "plane": plane, "pos": mid, "tgt": mid}

    def best_candidate(self) -> int:
        return self.max_rally

    def _serve(self, side: str) -> None:
        sp = 17.0
        a = self.rng.uniform(-0.6, 0.6)
        if self.mode == "fourway":
            self.bx, self.by = SERVE_FROM[side]
        else:
            self.bx = 15.0
            if self.map_id == "block":
                self.by = self.rng.choice((self.rng.uniform(3, 9), self.rng.uniform(21, 27)))
            else:
                self.by = self.rng.uniform(8, 22)
        out = -1 if side in ("L", "T") else 1
        if side in ("L", "R"):
            self.vx, self.vy = out * sp * math.cos(a), sp * math.sin(a)
        else:
            self.vx, self.vy = sp * math.sin(a), out * sp * math.cos(a)
        self.wait = 0.9
        self.trail.clear()
        self._new_err()

    def _new_err(self) -> None:
        p = self.settings.paddle
        spread = (1.0 - self.skill) * p * 0.6 + 0.6
        miss = 0.15 + 0.3 * (1.0 - self.skill)
        self.err = []
        for pad in self.pads:
            e = self.rng.uniform(-spread, spread)
            if self.rng.random() < miss * (
                1.6 if pad["d"] else 1.0
            ):  # a whiff now and then keeps score moving
                e = self.rng.choice((-1, 1)) * (p / 2 + self.rng.uniform(2.5, 5))
            self.err.append(e)

    # ------------------------------------------------------------ input
    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        p = self.settings.paddle
        for pad in self.pads:
            if pad["seat"] != player:
                continue
            if pad["side"] in ("L", "R"):
                if k not in ("up", "down"):
                    continue
                d = -5 if k == "up" else 5
            else:
                if k not in ("left", "right"):
                    continue
                d = -5 if k == "left" else 5
            if abs(pad["tgt"] - pad["pos"]) > 8:
                pad["tgt"] = pad["pos"]
            pad["tgt"] = clamp(pad["tgt"] + d, 0, 32 - p)

    # ------------------------------------------------------------ AI
    def _toward(self, side: str) -> bool:
        return {"L": self.vx < 0, "R": self.vx > 0, "T": self.vy < 0, "B": self.vy > 0}[side]

    def _predict(self, pad: dict[str, Any]) -> float:
        vert = pad["side"] in ("L", "R")
        v, pos, other, vo = (
            (self.vx, self.bx, self.by, self.vy) if vert else (self.vy, self.by, self.bx, self.vx)
        )
        if v == 0:
            return other
        t = (pad["plane"] - pos) / v
        y = (other + vo * t) % 60.0
        return 60.0 - y if y > 30 else y

    def _ai(self, i: int, pad: dict[str, Any], dt: float) -> None:
        p = self.settings.paddle
        if self._toward(pad["side"]) and self.wait <= 0:
            target = self._predict(pad) + 1 - p / 2 + self.err[i]
        else:
            target = 16 - p / 2 + 3 * math.sin(self._last * 0.7 + i)
        sp = (14 + 22 * self.skill) * dt
        pad["pos"] = pad["tgt"] = clamp(approach(pad["pos"], target, sp), 0, 32 - p)

    # ------------------------------------------------------------ simulation
    def update(self, dt: float) -> None:
        p = self.settings.paddle
        for i, pad in enumerate(self.pads):
            if self.is_human(pad["seat"]):
                pad["pos"] = clamp(approach(pad["pos"], pad["tgt"], 34 * dt), 0, 32 - p)
            else:
                self._ai(i, pad, dt)
        if self.wait > 0:
            self.wait -= dt
            return
        self.portal_cd = max(0.0, self.portal_cd - dt)
        self.trail.append((self.bx, self.by))
        ox, oy = self.bx, self.by
        self.bx += self.vx * dt
        self.by += self.vy * dt
        # closed sides are walls
        if "T" not in self.open and self.by < 0:
            self.by, self.vy = -self.by, abs(self.vy)
        elif "B" not in self.open and self.by > 30:
            self.by, self.vy = 60 - self.by, -abs(self.vy)
        if "L" not in self.open and self.bx < 0:
            self.bx, self.vx = -self.bx, abs(self.vx)
        elif "R" not in self.open and self.bx > 30:
            self.bx, self.vx = 60 - self.bx, -abs(self.vx)
        self._obstacles(ox, oy)
        self._paddles(p)
        for side, out in (
            ("L", self.bx < -3),
            ("R", self.bx > 33),
            ("T", self.by < -3),
            ("B", self.by > 33),
        ):
            if out and side in self.open:
                self._goal(side)
                return

    def _block(self) -> tuple[int, int, int, int]:
        return (14, 14, 4, 4) if self.mode == "fourway" else (15, 12, 2, 8)

    def _obstacles(self, ox: float, oy: float) -> None:
        if self.map_id == "block":
            x, y, w, h = self._block()
            if self.bx + 2 > x and self.bx < x + w and self.by + 2 > y and self.by < y + h:
                if not (ox + 2 > x and ox < x + w):
                    self.vx, self.bx = -self.vx, ox
                else:
                    self.vy, self.by = -self.vy, oy
                self.fx.burst(self.rng, self.bx + 1, self.by + 1, self.theme.w, 4, 8, 0.3)
        elif self.map_id == "portals" and self.portal_cd <= 0:
            for (ax, ay), (bx, by) in (PORTALS, PORTALS[::-1]):
                if self.bx + 2 > ax and self.bx < ax + 2 and self.by + 2 > ay and self.by < ay + 4:
                    self.fx.burst(self.rng, ax + 1, ay + 2, tint(self.theme.w, 0.4), 5, 8, 0.4)
                    self.bx, self.by = bx + (self.bx - ax), by + (self.by - ay)
                    self.fx.burst(self.rng, bx + 1, by + 2, tint(self.theme.w, 0.4), 5, 8, 0.4)
                    self.trail.clear()
                    self.portal_cd = 0.5
                    break

    def _paddles(self, p: int) -> None:
        for pad in self.pads:
            side, pl, pos = pad["side"], pad["plane"], pad["pos"]
            vert = side in ("L", "R")
            along, cross = (self.by, self.bx) if vert else (self.bx, self.by)
            crossed = cross <= pl if side in ("L", "T") else cross >= pl
            if not (self._toward(side) and crossed and along + 2 > pos and along < pos + p):
                continue
            if abs(cross - pl) >= 2.5:
                continue
            off = ((along + 1) - (pos + p / 2)) / (p / 2)
            sp = min(38.0, math.hypot(self.vx, self.vy) * 1.06)
            ang = clamp(off, -1, 1) * 0.9
            out = 1 if side in ("L", "T") else -1
            if vert:
                self.bx = pl
                self.vx, self.vy = out * sp * math.cos(ang), sp * math.sin(ang)
            else:
                self.by = pl
                self.vx, self.vy = sp * math.sin(ang), out * sp * math.cos(ang)
            self.rally += 1
            self.max_rally = max(self.max_rally, self.rally)
            self.fx.burst(self.rng, self.bx + 1, self.by + 1, self.theme.x, 5, 10, 0.35)
            self._new_err()
            return

    def _goal(self, side: str) -> None:
        """The ball left through `side`: that side concedes."""
        self.rally = 0
        self.flash = 0.4
        conceders = {pad["seat"] for pad in self.pads if pad["side"] == side}
        if any(self.is_human(s) for s in conceders):
            self.damage(0.7)
        ex, ey = clamp(self.bx, 0, 31), clamp(self.by, 0, 31)
        self.fx.burst(self.rng, ex, ey, self._side_colour(side), 14, 18)
        if self.mode == "fourway":
            self.lives[side] -= 1
            if self.lives[side] <= 0:
                self.open.discard(side)
                self.pads = [pad for pad in self.pads if pad["side"] != side]
                self.fx.burst(self.rng, ex, ey, WHITE, 10, 14, 0.8)
            if len(self.open) <= 1:
                win = next((pad["seat"] for pad in self.pads), None)
                scores = {s: self.lives.get(sd, 0) for s, sd in zip(sorted(self.roster), SIDES, strict=False)}
                self.result(winner_seat=win, scores=scores)
                return
            self.score = self.lives.get("L", 0)
            self._serve(side if side in self.open else self.rng.choice(sorted(self.open)))
            return
        if side == "R":
            self.ls += 1
        else:
            self.rs += 1
        self.score = self.rs if self._team(1) == 1 and self.roster else self.ls
        if max(self.ls, self.rs) >= self.settings.points:
            self._finish()
            return
        self._serve("L" if side == "R" else "R")  # serve toward the side that scored

    def _finish(self) -> None:
        if not self.roster:
            self.game_over()
            return
        team = 0 if self.ls > self.rs else 1
        seats = {pad["seat"] for pad in self.pads}
        scores = {s: (self.ls if self._team(s) == 0 else self.rs) for s in sorted(seats)}
        sides = [self._side_seats(0), self._side_seats(1)]
        if all(len(set(s)) == 1 for s in sides):
            self.result(winner_seat=sides[team][0], scores=scores)
        else:
            self.result(winner_team=team, scores=scores)

    # ------------------------------------------------------------ drawing
    def _side_colour(self, side: str) -> RGB:
        pad = next((pad for pad in self.pads if pad["side"] == side), None)
        if pad is None:
            return self.theme.w
        return self._pad_colour(pad)

    def _pad_colour(self, pad: dict[str, Any]) -> RGB:
        if self.roster:
            return self.colour_of(pad["seat"])
        return self.theme.p if pad["side"] == "L" else self.theme.e

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        p = self.settings.paddle
        if self.mode == "fourway":
            for side in SIDES:
                if side in self.open:
                    continue
                wc = scale(th.w, 0.7)
                if side == "L":
                    f.rect(0, 0, 1, 32, wc)
                elif side == "R":
                    f.rect(31, 0, 1, 32, wc)
                elif side == "T":
                    f.rect(0, 0, 32, 1, wc)
                else:
                    f.rect(0, 31, 32, 1, wc)
            if self.settings.show_score:
                spots = {"L": (4, 13), "R": (25, 13), "T": (15, 4), "B": (15, 23)}
                for side in self.open:
                    x, y = spots[side]
                    f.text(x, y, str(self.lives[side]), scale(self._side_colour(side), 0.7))
        else:
            for y in range(0, 32, 4):
                f.rect(15, y + 1, 2, 2, scale(th.w, 0.45))
            if self.settings.show_score:
                c = scale(th.hud, 0.8 if self.flash <= 0 else 1.0)
                f.text_right(13, 2, str(self.ls), c, "small")
                f.text(19, 2, str(self.rs), c, "small")
        if self.map_id == "block":
            x, y, w, h = self._block()
            f.rect(x, y, w, h, th.w)
            f.hline(x, y, w, tint(th.w, 0.45))
        elif self.map_id == "portals":
            pc = tint(th.w, 0.3)
            for ax, ay in PORTALS:
                k = 0.55 + 0.45 * math.sin(now * 5 + ax)
                f.rect(ax - 1, ay - 1, 4, 6, scale(pc, k), fill=False)
                f.rect(ax, ay, 2, 4, scale(pc, 0.18))
        for pad in self.pads:
            col = self._pad_colour(pad)
            pos = round(pad["pos"])
            side, d = pad["side"], pad["d"]
            if side == "L":
                f.rect(d, pos, 2, p, col)
                f.rect(d, pos, 1, p, tint(col, 0.45))
            elif side == "R":
                f.rect(30 - d, pos, 2, p, col)
                f.rect(31 - d, pos, 1, p, tint(col, 0.45))
            elif side == "T":
                f.rect(pos, 0, p, 2, col)
                f.rect(pos, 0, p, 1, tint(col, 0.45))
            else:
                f.rect(pos, 30, p, 2, col)
                f.rect(pos, 31, p, 1, tint(col, 0.45))
        if self.wait > 0 and int(now * 6) % 2:
            return
        n = len(self.trail)
        for i, (x, y) in enumerate(self.trail):
            f.rect(round(x), round(y), 2, 2, scale(th.x, 0.12 + 0.4 * i / max(1, n)))
        f.rect(round(self.bx), round(self.by), 2, 2, WHITE)


# =====================================================================================================
# Breakout
# =====================================================================================================
BREAKOUT_THEMES = {
    "arcade": Theme(
        p=(0, 220, 255), e=(255, 70, 110), x=(255, 214, 0), w=(120, 120, 170), hud=(255, 255, 255),
        bg=(3, 3, 10), r=CLASSIC_R,
    ),
    "candy": Theme(
        p=(255, 150, 220), e=(255, 90, 120), x=(255, 255, 160), w=(150, 110, 150), hud=(255, 220, 245),
        bg=(10, 4, 10),
        r=((255, 110, 160), (255, 170, 90), (255, 230, 110), (140, 255, 160), (110, 220, 255), (170, 150, 255),
           (255, 140, 255)),
    ),
    "lava": Theme(
        p=(255, 200, 60), e=(255, 80, 40), x=(255, 255, 200), w=(120, 80, 60), hud=(255, 210, 150),
        bg=(10, 3, 0),
        r=((255, 60, 20), (255, 110, 0), (255, 160, 0), (255, 210, 60), (255, 120, 80), (230, 90, 40),
           (255, 180, 120)),
    ),
}  # fmt: skip


class BreakoutSettings(GameSettings):
    lives: int = Field(3, ge=1, le=5, title="Lives")
    rows: int = Field(6, ge=3, le=6, title="Brick rows")
    paddle: int = Field(6, ge=4, le=8, title="Paddle width", json_schema_extra=GAME)
    drop: int = Field(
        12, ge=4, le=30, title="Wall drop every (s)", description="Descend map", json_schema_extra=GAME
    )


BRICK_W, BRICK_H, BRICK_TOP, COLS = 4, 3, 6, 8
STEEL = 9  # unbreakable brick


@register
class Breakout(GameApp):
    id = "breakout"
    name = "Breakout"
    description = (
        "Smash a colourful brick wall; new patterns every level. Left/right moves the paddle. "
        "Co-op: two paddles and two balls on one wall. Versus: a split field, first to clear their half wins."
    )
    icon = "brick-wall"
    Settings = BreakoutSettings
    max_players = 2
    controls = ("joystick", "dpad", "tilt", "gamepad")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("coop", "Co-op", 2, 2, "coop", "Two paddles, two balls, one wall"),
        Mode("versus", "Versus", 2, 2, "versus", "Split field: clear your half first"),
    )
    maps: ClassVar[dict[str, str]] = {"classic": "Classic", "fortress": "Fortress", "descend": "Descend"}
    game_themes: ClassVar[dict[str, Theme]] = BREAKOUT_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"arcade": "Arcade", "candy": "Candy", "lava": "Lava"}

    def new_game(self) -> None:
        self.mode = self.play_mode.id if self.roster else "solo"
        self.level = 1
        self.lives = self.settings.lives
        self.top = BRICK_TOP
        self.drop_t = float(self.settings.drop)
        w = self.settings.paddle
        seats = sorted(self.roster) or [1]
        if self.mode == "versus":
            left = [s for s in seats if self.team_of(s) == 0] or [seats[0]]
            right = [s for s in seats if self.team_of(s) == 1 and s != left[0]] or [seats[-1]]
            spec = [(left[0], 0, 15), (right[0], 16, 31)]
        elif self.mode == "coop":
            spec = [(seats[0], 0, 31), (seats[-1], 0, 31)]
        else:
            spec = [(1, 0, 31)]
        starts = [13.0] if len(spec) == 1 else [16 * i + 8 - w / 2 for i in range(len(spec))]
        self.pads: list[dict[str, Any]] = [
            {"seat": s, "lo": lo, "hi": hi, "x": x, "t": x, "err": 0.0, "score": 0, "lives": self.lives}
            for (s, lo, hi), x in zip(spec, starts, strict=True)
        ]
        self.balls: list[dict[str, Any]] = [{} for _ in self.pads]
        self._build()
        for i in range(len(self.pads)):
            self._serve(i)

    # ------------------------------------------------------------ wall
    def _build(self) -> None:
        rows = self.settings.rows
        kind = (self.level - 1) % 4
        g: list[list[int]] = []
        for r in range(rows):
            row = []
            for c in range(COLS):
                on = True
                if kind == 1:
                    on = (r + c) % 2 == 0 or r == 0
                elif kind == 2:
                    on = abs(c - 3.5) <= r * 0.8 + 0.5
                elif kind == 3:
                    on = self.rng.random() < 0.75
                hp = (
                    2 if (self.level >= 2 and r == 0) or (self.level >= 3 and self.rng.random() < 0.12) else 1
                )
                if self.map_id == "fortress" and r == rows - 1 and c in (1, 2, 5, 6):
                    row.append(STEEL)  # a steel shelf with gaps: aim through them
                    continue
                if self.map_id == "fortress" and r == 0:
                    hp = 2
                row.append(hp if on else 0)
            if self.mode == "versus":
                row = row[:4] + row[:4][::-1]  # mirrored halves: a fair race
            g.append(row)
        self.bricks = g
        self.top = BRICK_TOP
        self.drop_t = float(self.settings.drop)

    def _left(self, cols: range = range(COLS)) -> int:
        return sum(1 for row in self.bricks for c in cols if 0 < row[c] < STEEL)

    def _cols(self, i: int) -> range:
        if self.mode != "versus":
            return range(COLS)
        return range(0, 4) if i == 0 else range(4, 8)

    # ------------------------------------------------------------ ball
    def _serve(self, i: int) -> None:
        pad = self.pads[i]
        w = self.settings.paddle
        sp = self._speed()
        a = self.rng.uniform(-0.5, 0.5)
        self.balls[i] = {
            "x": pad["x"] + w / 2,
            "y": 27.0,
            "vx": sp * math.sin(a),
            "vy": -sp * math.cos(a),
            "wait": 0.8,
            "trail": deque(maxlen=4),
        }
        pad["err"] = 0.0

    def _speed(self) -> float:
        return min(34.0, 20.0 + 2.2 * (self.level - 1))

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        if k not in ("left", "right"):
            return
        w = self.settings.paddle
        for pad in self.pads:
            if pad["seat"] != player:
                continue
            if abs(pad["t"] - pad["x"]) > 8:
                pad["t"] = pad["x"]
            pad["t"] = clamp(pad["t"] + (-4 if k == "left" else 4), pad["lo"], pad["hi"] + 1 - w)

    def _landing_x(self, b: dict[str, Any], lo: float, hi: float) -> float:
        t = (28.0 - b["y"]) / b["vy"] if b["vy"] > 0 else 0.0
        span = hi - lo
        x = (b["x"] - lo + b["vx"] * t) % (2 * span)
        return lo + (2 * span - x if x > span else x)

    def _brick_at(self, x: float, y: float) -> tuple[int, int] | None:
        r = int((y - self.top) // BRICK_H)
        c = int(x // BRICK_W)
        if 0 <= r < len(self.bricks) and 0 <= c < COLS and y >= self.top and self.bricks[r][c]:
            return r, c
        return None

    def _ai(self, i: int, dt: float) -> None:
        pad = self.pads[i]
        w = self.settings.paddle
        b = self.balls[i]
        if self.mode == "coop":  # cover the partner's ball when it lands nearer to us
            o = self.balls[1 - i]
            other = self.pads[1 - i]
            if not (b["vy"] > 0 and b["wait"] <= 0) and o["vy"] > 0 and o["wait"] <= 0:
                lx = self._landing_x(o, pad["lo"], pad["hi"])
                if abs(lx - pad["x"] - w / 2) < abs(lx - other["x"] - w / 2):
                    b = o
        if b["vy"] > 0 and b["wait"] <= 0:
            target = self._landing_x(b, pad["lo"], pad["hi"]) - w / 2 + pad["err"]
        else:
            target = b["x"] - w / 2 + 2 * math.sin(self._last + i)
        pad["x"] = approach(pad["x"], target, (18 + 30 * self.skill) * dt)
        pad["t"] = pad["x"]

    def update(self, dt: float) -> None:
        w = self.settings.paddle
        for i, pad in enumerate(self.pads):
            if self.is_human(pad["seat"]):
                pad["x"] = approach(pad["x"], pad["t"], 40 * dt)
            else:
                self._ai(i, dt)
            pad["x"] = clamp(pad["x"], pad["lo"], pad["hi"] + 1 - w)
        if self.map_id == "descend":
            self.drop_t -= dt
            if self.drop_t <= 0:
                self.drop_t = float(self.settings.drop)
                self.top += 1
                bottom = max((r for r, row in enumerate(self.bricks) if any(row)), default=0)
                if self.top + (bottom + 1) * BRICK_H >= 26:  # the wall reached the danger line
                    self.top = BRICK_TOP
                    self.flash = 0.6
                    for i in range(len(self.pads)) if self.mode == "versus" else (0,):
                        if self._lose(i):
                            return
        for i in range(len(self.pads)):
            self._step(i, dt, w)
            if self.over:
                return

    def _step(self, i: int, dt: float, w: int) -> None:
        pad, b = self.pads[i], self.balls[i]
        lo, hi = pad["lo"], pad["hi"]
        if b["wait"] > 0:
            b["wait"] -= dt
            b["x"], b["y"] = pad["x"] + w / 2, 27.0
            return
        b["trail"].append((b["x"], b["y"]))
        ox, oy = b["x"], b["y"]
        nx, ny = ox + b["vx"] * dt, oy + b["vy"] * dt
        if nx < lo:
            nx, b["vx"] = 2 * lo - nx, abs(b["vx"])
        elif nx > hi:
            nx, b["vx"] = 2 * hi - nx, -abs(b["vx"])
        if ny < 0:
            ny, b["vy"] = -ny, abs(b["vy"])
        hit = self._brick_at(nx, ny)
        if hit:
            if self._brick_at(nx, oy):
                b["vx"] = -b["vx"]
                nx = ox
            else:
                b["vy"] = -b["vy"]
                ny = oy
            self._hit(*hit, i)
            if self.over or b is not self.balls[i]:
                return
        # paddles: your own; in co-op either paddle returns either ball
        for j in range(len(self.pads)) if self.mode == "coop" else (i,):
            px = self.pads[j]["x"]
            if b["vy"] > 0 and oy < 28 <= ny and px - 1 <= nx <= px + w + 1:
                off = clamp((nx - (px + w / 2)) / (w / 2 + 0.5), -1, 1)
                sp = self._speed()
                b["vx"], b["vy"] = sp * math.sin(off), -sp * math.cos(off)
                ny = 28 - (ny - 28)
                spread = (1 - self.skill) * 5.5
                if self.rng.random() < 0.03 + 0.1 * (1 - self.skill):
                    spread = 7.0  # misjudged bounce
                cols = self._cols(i)
                half = cols.start + len(cols) // 2
                fuller = sum(1 for row in self.bricks for c in range(cols.start, half) if 0 < row[c] < STEEL)
                other = self._left(cols) - fuller
                bias = 1.4 if fuller > other else -1.4
                self.pads[j]["err"] = bias + self.rng.uniform(-spread, spread)
                self.fx.burst(self.rng, nx, 28, scale(self._pad_colour(j), 0.8), 2, 5, 0.25)
                break
        b["x"], b["y"] = nx, ny
        if b["y"] > 33:
            self.fx.burst(self.rng, b["x"], 31, self.theme.e, 12, 14, 0.6)
            self._lose(i)

    def _lose(self, i: int) -> bool:
        """Ball `i` was lost (or the wall came down). Returns True when the match ended."""
        pad = self.pads[i]
        self.flash = 0.5
        hurt = (
            any(self.is_human(p["seat"]) for p in self.pads)
            if self.mode == "coop"
            else self.is_human(pad["seat"])
        )
        if hurt:
            self.damage(0.8)
        if self.mode == "versus":
            pad["lives"] -= 1
            if pad["lives"] <= 0:
                win = self.pads[1 - i]
                self.result(winner_seat=win["seat"], scores={p["seat"]: p["score"] for p in self.pads})
                return True
        else:
            self.lives -= 1
            if self.lives <= 0:
                if self.mode == "coop":
                    self.result(scores={p["seat"]: p["score"] for p in self.pads}, text=f"LEVEL {self.level}")
                else:
                    self.game_over()
                return True
        self._serve(i)
        return False

    def _hit(self, r: int, c: int, i: int) -> None:
        v = self.bricks[r][c]
        x, y = c * BRICK_W + 2, self.top + r * BRICK_H + 1
        if v >= STEEL:
            self.fx.burst(self.rng, x, y, WHITE, 2, 6, 0.2)
            return
        self.bricks[r][c] -= 1
        if self.bricks[r][c] > 0:
            return
        pad = self.pads[i]
        pad["score"] += len(self.bricks) - r
        self.score = sum(p["score"] for p in self.pads) if self.mode == "coop" else self._seat1_score()
        self.fx.burst(self.rng, x, y, self._row_color(r), 5, 9, 0.5, gravity=30)
        if self.mode == "versus":
            if self._left(self._cols(i)) <= 0:
                self.flash = 0.6
                self.result(winner_seat=pad["seat"], scores={p["seat"]: p["score"] for p in self.pads})
            return
        if self._left() <= 0:
            self.level += 1
            self.flash = 0.6
            self._build()
            for j in range(len(self.pads)):
                self._serve(j)

    def _seat1_score(self) -> int:
        return next((p["score"] for p in self.pads if p["seat"] == 1), self.pads[0]["score"])

    def _row_color(self, r: int) -> RGB:
        pal = self.theme.r
        return pal[r % len(pal)]

    def _pad_colour(self, i: int) -> RGB:
        return self.colour_of(self.pads[i]["seat"]) if len(self.pads) > 1 else self.theme.p

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        w = self.settings.paddle
        for r, row in enumerate(self.bricks):
            base = self._row_color(r)
            y = self.top + r * BRICK_H
            for c, hp in enumerate(row):
                if not hp:
                    continue
                x = c * BRICK_W
                if hp >= STEEL:
                    f.rect(x, y, 3, 2, th.w)
                    f.hline(x, y, 3, tint(th.w, 0.5))
                    f.set(x + 1, y + 1, scale(th.w, 0.55))
                    continue
                col = tint(base, 0.55) if hp > 1 else base
                f.rect(x, y, 3, 2, col)
                f.hline(x, y, 3, tint(col, 0.35))
                f.rect(x + 3, y, 1, 2, scale(col, 0.3))
        if self.map_id == "descend":
            for x in range(0, 32, 3):
                f.set(x, 25, scale(th.e, 0.35))
        if self.mode == "versus":
            y0 = self.top + len(self.bricks) * BRICK_H
            for y in range(y0, 29, 2):
                f.set(15 + (y // 2) % 2, y, scale(th.w, 0.4))
        if self.flash > 0 and int(now * 10) % 2:
            f.rect(0, 31, 32, 1, scale(th.e, 0.5))
        for i, pad in enumerate(self.pads):
            col = self._pad_colour(i)
            px = round(pad["x"])
            f.rect(px, 29, w, 1, tint(col, 0.5))
            f.rect(px, 30, w, 1, col)
            f.set(px, 30, scale(col, 0.5))
            f.set(px + w - 1, 30, scale(col, 0.5))
        for i, b in enumerate(self.balls):
            tc = th.x if len(self.pads) == 1 else self._pad_colour(i)
            for k, (x, y) in enumerate(b["trail"]):
                f.set(int(x), int(y), scale(tc, 0.15 + 0.15 * k))
            f.set(int(b["x"]), int(b["y"]), WHITE)
        if self.mode == "versus":
            for i, pad in enumerate(self.pads):
                col = self._pad_colour(i)
                for k in range(pad["lives"]):
                    f.rect(1 + 3 * k if i == 0 else 29 - 3 * k, 1, 2, 2, col)
            return
        self.hud(f, str(self.score), x=1, y=0)
        for k in range(self.lives):
            f.rect(30 - 3 * k, 1, 2, 2, th.e)


# =====================================================================================================
# Flappy
# =====================================================================================================
FLAPPY_THEMES = {
    "meadow": Theme(
        p=(255, 214, 0), e=(40, 220, 60), x=(255, 255, 255), w=(200, 120, 40), hud=(255, 255, 255),
        bg=(4, 6, 16), r=CLASSIC_R,
    ),
    "dusk": Theme(
        p=(255, 170, 60), e=(120, 220, 255), x=(255, 240, 200), w=(110, 70, 140), hud=(255, 220, 190),
        bg=(10, 4, 14), r=CLASSIC_R,
    ),
    "abyss": Theme(
        p=(255, 230, 90), e=(80, 255, 200), x=(255, 255, 255), w=(40, 110, 120), hud=(180, 255, 240),
        bg=(0, 6, 10), r=CLASSIC_R,
    ),
}  # fmt: skip


class FlappySettings(GameSettings):
    gap: int = Field(11, ge=8, le=15, title="Gap size")
    gravity: int = Field(5, ge=1, le=10, title="Gravity", json_schema_extra=GAME)
    shrink: bool = Field(True, title="Race: gaps shrink (sudden death)", json_schema_extra=GAME)


BIRD_ROWS_A = [".YYW.", "YYYWK", "wwYYO", ".YYY."]
BIRD_ROWS_B = [".YYW.", "wwYWK", "YYYYO", ".YYY."]
BIRD_X = {1: [6], 2: [4, 12], 3: [3, 10, 17], 4: [3, 9, 15, 21]}
FLAP_SPEED = 11.0


@register
class Flappy(GameApp):
    id = "flappy"
    name = "Flappy"
    description = (
        "A little bird threading between pipes. Plays itself; up or A flaps. "
        "Race: up to four birds through the same pipes, last one flying wins."
    )
    icon = "bird"
    Settings = FlappySettings
    step_hz = 40.0
    max_players = 4
    controls = ("tap", "dpad", "gamepad")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("race", "Race", 2, 4, "ffa", "Same pipes for everyone; last bird flying wins"),
    )
    maps: ClassVar[dict[str, str]] = {"pipes": "Pipes", "moving": "Moving", "cave": "Cave"}
    game_themes: ClassVar[dict[str, Theme]] = FLAPPY_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {"meadow": "Meadow", "dusk": "Dusk", "abyss": "Abyss"}

    def pilot_anchor(self) -> tuple[float, float] | None:
        """The fruit-fly pilot's eye follows seat 1's bird."""
        bird = next((b for b in self.birds if b["seat"] == 1), None)
        return None if bird is None else (bird["x"], bird["y"])

    def new_game(self) -> None:
        self.race = bool(self.roster) and self.play_mode.id == "race"
        seats = sorted(self.roster) if self.race else [1]
        xs = BIRD_X[max(1, min(4, len(seats)))]
        self.birds: list[dict[str, Any]] = [
            {"seat": s, "x": x, "y": 14.0, "vy": 0.0, "alive": True, "cd": 0.0, "score": 0}
            for s, x in zip(seats, xs, strict=False)
        ]
        self.t = 0.0
        self.pipes: list[dict[str, Any]] = []
        self.scroll = 0.0
        self.next_x = 34.0
        self.last_gap = 14.0
        self.spawned = 0
        self.ph = (self.rng.uniform(0, 6.28), self.rng.uniform(0, 6.28))
        if self.map_id != "cave":
            while self.next_x < 60:
                self._spawn()
        self._sprites: dict[tuple[str, RGB], tuple[Sprite, Sprite]] = {}

    # ------------------------------------------------------------ world
    def _gap(self) -> int:
        g = self.settings.gap
        if self.race and self.settings.shrink:
            g -= self.spawned // 8
        return max(7, g)

    def _spawn(self) -> None:
        g = self._gap()
        moving = self.map_id == "moving"
        lo, hi = (6, 25 - g) if moving else (3, 28 - g)
        top = clamp(self.last_gap + self.rng.uniform(-7, 7), lo, max(lo, hi))
        self.last_gap = top
        self.pipes.append(
            {"x": self.next_x, "top": top, "gap": g, "ph": self.rng.uniform(0, 6.28), "scored": set()}
        )
        self.next_x += 17
        self.spawned += 1

    def _top(self, p: dict[str, Any], ahead: float = 0.0) -> float:
        if self.map_id != "moving":
            return float(p["top"])
        return p["top"] + 3 * math.sin(p["ph"] + (self.t + ahead) * 1.7)

    def _cave(self, wx: float) -> tuple[float, float]:
        """Ceiling and floor of the cave at world column `wx` (a pure function of x: no storage)."""
        c = 15 + 5 * math.sin(wx * 0.05 + self.ph[0]) + 2 * math.sin(wx * 0.13 + self.ph[1])
        if wx < 40:
            c = 15 + (c - 15) * wx / 40  # a gentle start
        g = self.settings.gap + 3
        if self.race and self.settings.shrink:
            g -= int(self.t / 12)
        half = max(9, g) / 2
        return max(1.0, c - half), min(29.0, c + half)

    def _birds(self, body: RGB) -> tuple[Sprite, Sprite]:
        key = (_tid(self), body)
        if key not in self._sprites:
            th = self.theme
            pal = {
                "Y": body,
                "W": WHITE,
                "K": (40, 40, 60),
                "O": (255, 90, 0) if _tid(self) != "mono" else th.x,
            }
            pal["w"] = tint(body, 0.55)
            self._sprites[key] = (Sprite.parse(BIRD_ROWS_A, pal), Sprite.parse(BIRD_ROWS_B, pal))
        return self._sprites[key]

    def _body(self, b: dict[str, Any]) -> RGB:
        if self.race:
            return self.colour_of(b["seat"])
        return (255, 214, 0) if _tid(self) == "classic" else self.theme.p

    # ------------------------------------------------------------ input
    def _flap(self, b: dict[str, Any]) -> None:
        b["vy"] = -19.0
        self.fx.burst(self.rng, b["x"], b["y"] + 2, scale(WHITE, 0.6), 2, 5, 0.3, vx=-8)

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        if k in ("up", "a"):
            for b in self.birds:
                if b["seat"] == player and b["alive"]:
                    self._flap(b)

    # ------------------------------------------------------------ simulation
    def update(self, dt: float) -> None:
        self.t += dt
        mv = FLAP_SPEED * dt
        self.scroll += mv
        for p in self.pipes:
            p["x"] -= mv
        self.next_x -= mv
        self.pipes = [p for p in self.pipes if p["x"] > -7]
        if self.map_id != "cave":
            while self.next_x < 40:
                self._spawn()
        grav = 70.0 * (0.6 + 0.08 * self.settings.gravity)
        for b in self.birds:
            if not b["alive"]:
                if b["y"] < 34:
                    b["vy"] = min(30.0, b["vy"] + grav * dt)
                    b["y"] += b["vy"] * dt
                continue
            if not self.is_human(b["seat"]):
                self._ai(b, dt)
            b["vy"] = min(30.0, b["vy"] + grav * dt)
            b["y"] += b["vy"] * dt
            if b["y"] < 0:
                b["y"], b["vy"] = 0.0, 0.0
            if self._collides(b):
                self._die(b)
                continue
            if self.map_id == "cave":
                b["score"] = int(self.scroll / 8)
            else:
                for p in self.pipes:
                    if b["seat"] not in p["scored"] and p["x"] + 5 < b["x"]:
                        p["scored"].add(b["seat"])
                        b["score"] += 1
                        self.fx.burst(self.rng, b["x"] + 2, b["y"], self.theme.x, 4, 8, 0.4)
        self.score = self.birds[0]["score"]
        if self.race:
            _race_finished(self, self.birds)
        elif not self.birds[0]["alive"]:
            self.game_over()

    def _ai(self, b: dict[str, Any], dt: float) -> None:
        b["cd"] -= dt
        if self.map_id == "cave":
            # aim for the middle of the narrowest part just ahead
            cols = [self._cave(self.scroll + b["x"] + dx) for dx in range(-1, 10, 2)]
            target = (max(c[0] for c in cols) + min(c[1] for c in cols)) / 2 + 1.3
        else:
            nxt = next((p for p in self.pipes if p["x"] + 6 > b["x"]), None)
            if nxt:
                ahead = max(0.0, (nxt["x"] - b["x"]) / FLAP_SPEED)
                target = self._top(nxt, ahead) + nxt["gap"] / 2 + 1.2
            else:
                target = 16.0
        if b["y"] + 2 > target and b["vy"] >= 0 and b["cd"] <= 0:
            if self.rng.random() < 0.04 * (1.0 - self.skill) + 0.002:
                b["cd"] = 0.28  # a moment of hesitation: sometimes fatal
            else:
                self._flap(b)
                b["cd"] = 0.1

    def _collides(self, b: dict[str, Any]) -> bool:
        bx0, bx1 = b["x"], b["x"] + 4
        by0, by1 = b["y"] + 0.5, b["y"] + 3.5
        if b["y"] + 4 > 30:
            return True
        if self.map_id == "cave":
            for cx in range(int(bx0), int(bx1) + 1):
                ceil, floor = self._cave(self.scroll + cx)
                if by0 < ceil or by1 > floor:
                    return True
            return False
        for p in self.pipes:
            x = p["x"]
            top = self._top(p)
            if x - 0.5 < bx1 and x + 5.5 > bx0 and (by0 < top or by1 > top + p["gap"]):
                return True
        return False

    def _die(self, b: dict[str, Any]) -> None:
        b["alive"] = False
        b["vy"] = -6.0
        self.fx.burst(self.rng, b["x"] + 2, b["y"] + 2, self._body(b), 14, 16, 0.7, gravity=40)
        if self.is_human(b["seat"]):
            self.damage()

    # ------------------------------------------------------------ drawing
    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        classic = _tid(self) == "classic"
        hill = scale(th.w, 0.18)
        off = self.scroll * 0.3
        for x in range(32):
            h = 3 + round(2.2 * math.sin((x + off) * 0.35) + 1.5 * math.sin((x + off) * 0.13))
            f.vline(x, 30 - h, h, hill)
        rock = (40, 220, 60) if classic else th.e
        if self.map_id == "cave":
            edge = tint(rock, 0.35)
            dark = scale(rock, 0.45)
            for x in range(32):
                ceil, floor = self._cave(self.scroll + x)
                c, fl = round(ceil), round(floor)
                f.vline(x, 0, c, dark)
                f.set(x, c - 1, edge)
                f.vline(x, fl, 30 - fl, dark)
                f.set(x, fl, edge)
        for p in self.pipes:
            x = round(p["x"])
            gt = round(self._top(p))
            bottom = round(self._top(p) + p["gap"])
            f.rect(x, 0, 5, gt, rock)
            f.rect(x, bottom, 5, 30 - bottom, rock)
            f.vline(x + 1, 0, gt, tint(rock, 0.45))
            f.vline(x + 1, bottom, 30 - bottom, tint(rock, 0.45))
            f.vline(x + 4, 0, gt, scale(rock, 0.45))
            f.vline(x + 4, bottom, 30 - bottom, scale(rock, 0.45))
            lip = tint(rock, 0.2)
            f.rect(x - 1, gt - 2, 7, 2, lip)
            f.rect(x - 1, bottom, 7, 2, lip)
        ground = (200, 120, 40) if classic else th.w
        f.rect(0, 30, 32, 2, scale(ground, 0.6))
        s = int(self.scroll) % 4
        for x in range(-s, 32, 4):
            f.rect(x, 30, 2, 1, ground)
        for b in sorted(self.birds, key=lambda b: b["alive"]):
            if b["y"] >= 32:
                continue
            a, bb = self._birds(self._body(b) if b["alive"] else scale(self._body(b), 0.4))
            flap = b["alive"] and b["vy"] < 0 and int(now * 12) % 2 == 0
            f.sprite(bb if flap else a, round(b["x"]), round(b["y"]))
        txt = str(self.score)
        self.hud(f, txt, x=16 - len(txt) * 2, y=1)
        if self.race:
            _pips(f, self.birds, self)


# =====================================================================================================
# Dino Runner
# =====================================================================================================
DINO_THEMES = {
    "desert": Theme(
        p=(110, 230, 90), e=(40, 200, 70), x=(255, 110, 70), w=(200, 150, 90), hud=(255, 255, 255),
        bg=(40, 28, 56), r=CLASSIC_R,
    ),
    "tundra": Theme(
        p=(255, 160, 80), e=(170, 240, 255), x=(255, 110, 200), w=(190, 220, 240), hud=(255, 255, 255),
        bg=(14, 24, 40), r=CLASSIC_R,
    ),
    "volcano": Theme(
        p=(120, 255, 120), e=(255, 140, 40), x=(255, 240, 120), w=(160, 70, 40), hud=(255, 220, 180),
        bg=(36, 10, 6), r=CLASSIC_R,
    ),
}  # fmt: skip


class DinoSettings(GameSettings):
    birds: bool = Field(True, title="Birds")
    cycle: int = Field(40, ge=10, le=120, title="Day length (s)")
    start_speed: int = Field(24, ge=16, le=40, title="Start speed", json_schema_extra=GAME)


DINO_RUN = [
    ["....####", "....#.##", "....####", "#..###..", "######..", ".#####..", "..#..#..", "..##...."],
    ["....####", "....#.##", "....####", "#..###..", "######..", ".#####..", "..#..#..", ".....##."],
]
DINO_JUMP = ["....####", "....#.##", "....####", "#..###..", "######..", ".#####..", "..#..#..", "..##.##."]
DINO_DUCK = ["..........", "#....#####", "#####.#.##", ".#########", "..#..#....", "..##.##..."]
CACTI = [
    [".##.", ".###", "###.", ".##.", ".##."],
    ["..##..", "..##.#", "#.##.#", "#.####", "####..", "..##..", "..##.."],
    [".##.", ".##.", ".###", "###.", ".##.", ".##.", ".##.", ".##."],
    [".##..", ".##.#", "###.#", ".####", ".##..", ".##.."],
]
BIRD_UP = ["#...#", ".#.#.", "..###", "....."]
BIRD_DN = [".....", "..###", ".#.#.", "#...#"]
GROUND_Y = 27
JUMP_V, GRAVITY = 66.0, 190.0
DINO_X = {1: [2], 2: [2, 12], 3: [1, 8, 15], 4: [1, 7, 13, 19]}


@register
class Dino(GameApp):
    id = "dino"
    name = "Dino Runner"
    description = (
        "An endless desert run: jump cacti, duck birds, day turns to night. Up/A jumps, down ducks. "
        "Race: up to four runners on one track, last one running wins."
    )
    icon = "footprints"
    Settings = DinoSettings
    step_hz = 40.0
    max_players = 4
    controls = ("tap", "dpad", "gamepad")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("race", "Race", 2, 4, "ffa", "One track, last one running wins"),
    )
    maps: ClassVar[dict[str, str]] = {"desert": "Desert", "canyon": "Canyon", "rush": "Rush"}
    game_themes: ClassVar[dict[str, Theme]] = DINO_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {
        "desert": "Desert",
        "tundra": "Tundra",
        "volcano": "Volcano",
    }

    def new_game(self) -> None:
        rush = self.map_id == "rush"
        self.race = bool(self.roster) and self.play_mode.id == "race"
        seats = sorted(self.roster) if self.race else [1]
        xs = DINO_X[max(1, min(4, len(seats)))]
        self.dinos: list[dict[str, Any]] = [
            {
                "seat": s,
                "x": float(x),
                "y": 0.0,
                "vy": 0.0,
                "duck": 0.0,
                "alive": True,
                "jitter": 0.0,
                "score": 0,
            }
            for s, x in zip(seats, xs, strict=False)
        ]
        self.spawn_x = 33.0 + max(0, xs[-1] - 8)  # obstacles appear early enough for the front runner
        self.speed = float(self.settings.start_speed) + (8 if rush else 0)
        self.top_speed = 48.0 if rush else 42.0
        self.accel = (0.8 if rush else 0.35) * (1.5 if self.race else 1.0)
        self.dist = 0.0
        self.obs: list[dict[str, Any]] = []
        self.next_gap = 30.0
        self.stars = [(self.rng.randrange(32), self.rng.randrange(1, 18)) for _ in range(14)]
        self._cache: dict[Any, Any] = {}

    def _art(self) -> dict[str, Any]:
        key = _tid(self)
        if key not in self._cache:
            th = self.theme
            cactus = (40, 200, 70) if key == "classic" else th.e
            bird = (255, 90, 60) if key == "classic" else th.x
            self._cache[key] = {
                "cacti": [Sprite.parse(r, {"#": cactus}) for r in CACTI],
                "bird": [Sprite.parse(BIRD_UP, {"#": bird}), Sprite.parse(BIRD_DN, {"#": bird})],
            }
        return self._cache[key]

    def _runner(self, colour: RGB) -> dict[str, Any]:
        key = ("dino", colour)
        if key not in self._cache:
            self._cache[key] = {
                "run": [Sprite.parse(r, {"#": colour}) for r in DINO_RUN],
                "jump": Sprite.parse(DINO_JUMP, {"#": colour}),
                "duck": Sprite.parse(DINO_DUCK, {"#": colour}),
            }
        return self._cache[key]

    def _colour(self, d: dict[str, Any]) -> RGB:
        if self.race:
            return self.colour_of(d["seat"])
        return (110, 230, 90) if _tid(self) == "classic" else self.theme.p

    def _spawn(self) -> None:
        x0 = self.spawn_x
        bird_from = 40 if self.map_id == "rush" else 120
        bird_p = 0.45 if self.map_id == "rush" else 0.3
        if self.settings.birds and self.dist > bird_from and self.rng.random() < bird_p:
            h = self.rng.choice((1, 4, 9))  # low → jump, mid → duck, high → run under
            self.obs.append({"x": x0, "kind": "bird", "h": h, "w": 5, "hgt": 4})
        elif self.map_id == "canyon" and self.dist > 40 and self.rng.random() < 0.4:
            self.obs.append({"x": x0, "kind": "pit", "w": self.rng.randint(5, 7), "hgt": 1})
        else:
            i = self.rng.randrange(len(CACTI))
            w = len(CACTI[i][0])
            self.obs.append({"x": x0, "kind": "cactus", "i": i, "w": w, "hgt": len(CACTI[i])})
            if self.rng.random() < 0.3:
                j = self.rng.randrange(len(CACTI))
                w2, h2 = len(CACTI[j][0]), len(CACTI[j])
                h = max(h2, len(CACTI[i]))
                # only pair cacti when a perfect jump can still clear both at this speed
                window = 2 * math.sqrt(max(0.0, JUMP_V**2 - 2 * GRAVITY * h)) / GRAVITY
                if (w + w2 + 2) / self.speed < window * 0.8:
                    self.obs.append({"x": x0 + w, "kind": "cactus", "i": j, "w": w2, "hgt": h2})
        self.next_gap = self.rng.uniform(0.9, 1.9) * (14 + self.speed * 0.9)

    def _jump(self, d: dict[str, Any]) -> None:
        if d["y"] <= 0 and d["duck"] <= 0:
            d["vy"] = JUMP_V

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        for d in self.dinos:
            if d["seat"] != player or not d["alive"]:
                continue
            if k in ("up", "a"):
                self._jump(d)
            elif k == "down":
                if d["y"] > 0:
                    d["vy"] = min(d["vy"], -40.0)
                d["duck"] = 0.45

    def _hitbox(self, d: dict[str, Any]) -> tuple[float, float, float, float]:
        dx = d["x"] - 2
        if d["duck"] > 0 and d["y"] <= 0:
            return dx + 3.5, GROUND_Y - 4, dx + 12.0, GROUND_Y
        top = GROUND_Y - 8 - d["y"]
        return dx + 5.5, top + 0.5, dx + 8.5, top + 8

    def _ai(self, d: dict[str, Any]) -> None:
        """Jump so the apex of the arc sits over the middle of the next obstacle cluster."""
        s = self.speed
        dx = d["x"] - 2
        span: list[float] | None = None
        for o in sorted(self.obs, key=lambda o: o["x"]):
            if o["x"] + o["w"] < 4 + dx:
                continue
            if o["kind"] == "bird" and o["h"] >= 9:
                continue
            if o["kind"] == "bird" and o["h"] == 4:
                if span is None:
                    if o["x"] - dx - 12 < 4 + s * 0.1:
                        d["duck"] = 0.2
                    return
                break
            sp = s * (1.15 if o["kind"] == "bird" else 1.0)
            t_in = (o["x"] + 0.5 - (8.5 + dx)) / sp
            t_out = (o["x"] + o["w"] - 0.5 - (5.5 + dx)) / sp
            if span is None:
                span = [t_in, t_out]
            elif t_in < span[1] + 0.12:
                span[1] = max(span[1], t_out)
            else:
                break
        if span is None or d["y"] > 0:
            return
        t_jump = (span[0] + span[1]) / 2 - JUMP_V / GRAVITY + d["jitter"]
        if t_jump <= 0:
            self._jump(d)
            d["jitter"] = self.rng.gauss(0, 0.01 + (1 - self.skill) * 0.15)

    def _hits(self, d: dict[str, Any]) -> bool:
        x0, y0, x1, y1 = self._hitbox(d)
        for o in self.obs:
            if o["kind"] == "pit":
                mid = (x0 + x1) / 2
                if d["y"] <= 0 and o["x"] + 0.5 < mid < o["x"] + o["w"] - 0.5:
                    return True
                continue
            if o["kind"] == "bird":
                oy1 = GROUND_Y - o["h"]
                oy0 = oy1 - 3
            else:
                oy1 = GROUND_Y
                oy0 = GROUND_Y - o["hgt"] + 0.5
            if o["x"] + 0.5 < x1 and o["x"] + o["w"] - 0.5 > x0 and oy0 < y1 and oy1 > y0:
                return True
        return False

    def update(self, dt: float) -> None:
        self.speed = min(self.top_speed, self.speed + self.accel * dt)
        mv = self.speed * dt
        self.dist += mv
        for o in self.obs:
            o["x"] -= mv * (1.15 if o["kind"] == "bird" else 1.0)
        self.obs = [o for o in self.obs if o["x"] > -12]
        self.next_gap -= mv
        if self.next_gap <= 0:
            self._spawn()
        for d in self.dinos:
            if not d["alive"]:
                d["x"] -= mv  # the fallen runner drifts back with the ground
                continue
            if not self.is_human(d["seat"]):
                self._ai(d)
            d["duck"] = max(0.0, d["duck"] - dt)
            if d["y"] > 0 or d["vy"] > 0:
                d["vy"] -= GRAVITY * dt
                d["y"] += d["vy"] * dt
                if d["y"] <= 0:
                    d["y"], d["vy"] = 0.0, 0.0
                    self.fx.burst(self.rng, d["x"] + 4, GROUND_Y, scale(self.theme.w, 0.9), 3, 6, 0.3, vy=-3)
            d["score"] = int(self.dist / 4)
            if self._hits(d):
                d["alive"] = False
                self.fx.burst(
                    self.rng, d["x"] + 6, GROUND_Y - 5 - d["y"], self.theme.e, 14, 15, 0.7, gravity=40
                )
                if self.is_human(d["seat"]):
                    self.damage()
        self.score = self.dinos[0]["score"]
        if self.race:
            _race_finished(self, self.dinos)
        elif not self.dinos[0]["alive"]:
            self.game_over()

    def _sky(self, day: float) -> tuple[RGB, RGB]:
        tid = _tid(self)
        if tid in self.game_themes:
            bg = self.theme.bg
            return mix((0, 0, 0), scale(bg, 0.35), day), mix((4, 2, 14), bg, day)
        mono = tid == "mono"
        top = mix((0, 0, 0), (10, 30, 70) if not mono else (0, 25, 0), day)
        bot = mix((4, 2, 14), (60, 40, 70) if not mono else (10, 40, 10), day)
        return top, bot

    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        art = self._art()
        cyc = self.settings.cycle
        ph = (self.dist / 16 / cyc) % 1.0  # 0..1 day→night→day
        day = 0.5 + 0.5 * math.cos(ph * 2 * math.pi)
        sky_top, sky_bot = self._sky(day)
        for i in range(3):  # flat bands (cheaper on the link than a smooth gradient)
            f.rect(0, i * 9, 32, 9, mix(sky_top, sky_bot, i / 2))
        night = 1 - day
        if night > 0.3:
            for sx, sy in self.stars:
                x = int(sx - self.dist * 0.05) % 32
                tw = 0.5 + 0.5 * math.sin(now * 2 + sx)
                f.set(x, sy, scale(WHITE, (night - 0.3) * (0.4 + 0.5 * tw)))
        a = (ph * 2) % 1.0
        cx = round(30 - a * 28)
        cy = round(12 - 8 * math.sin(a * math.pi))
        if ph < 0.25 or ph >= 0.75:
            f.circle(cx, cy, 2, (255, 200, 40))
        else:
            f.circle(cx, cy, 2, (220, 220, 240))
            f.circle(cx + 1, cy - 1, 1, sky_top)
        ground = (200, 150, 90) if _tid(self) == "classic" else th.w
        f.hline(0, GROUND_Y, 32, ground)
        f.rect(0, GROUND_Y + 1, 32, 32 - GROUND_Y - 1, scale(ground, 0.2))
        dd = int(self.dist)
        for i in range(10):
            x = (i * 7 + 3 * (i % 3) - dd) % 36 - 2
            f.set(x, GROUND_Y + 2 + (i % 3), scale(ground, 0.6))
        for o in self.obs:
            x = round(o["x"])
            if o["kind"] == "bird":
                f.sprite(art["bird"][int(now * 6) % 2], x, GROUND_Y - o["h"] - 4)
            elif o["kind"] == "pit":
                f.rect(x, GROUND_Y, o["w"], 32 - GROUND_Y, (0, 0, 0))
                f.hline(x, 31, o["w"], scale(th.e, 0.5))
                f.vline(x - 1, GROUND_Y, 3, ground)
                f.vline(x + o["w"], GROUND_Y, 3, ground)
            else:
                f.sprite(art["cacti"][o["i"]], x, GROUND_Y - o["hgt"])
        for d in sorted(self.dinos, key=lambda d: d["alive"]):
            if d["x"] < -10:
                continue
            col = self._colour(d) if d["alive"] else scale(self._colour(d), 0.35)
            spr = self._runner(col)
            x = round(d["x"])
            if d["duck"] > 0 and d["y"] <= 0:
                f.sprite(spr["duck"], x, GROUND_Y - 6)
            elif d["y"] > 0:
                f.sprite(spr["jump"], x, round(GROUND_Y - 8 - d["y"]))
            else:
                frame = int(self.dist / 3) % 2 if d["alive"] else 0
                f.sprite(spr["run"][frame], x, GROUND_Y - 8)
        self.hud(f, str(self.score), y=1)
        if self.race:
            _pips(f, self.dinos, self)


# =====================================================================================================
# Racer
# =====================================================================================================
RACER_THEMES = {
    "asphalt": Theme(
        p=(0, 220, 255), e=(255, 80, 80), x=(255, 214, 0), w=(30, 110, 40), hud=(255, 255, 255),
        bg=(22, 22, 30), r=CLASSIC_R,
    ),
    "midnight": Theme(
        p=(255, 230, 90), e=(255, 70, 150), x=(120, 255, 255), w=(60, 70, 150), hud=(230, 230, 255),
        bg=(10, 10, 20),
        r=((255, 70, 150), (120, 255, 255), (170, 110, 255), (255, 150, 60), (90, 255, 140), (255, 255, 255),
           (0, 160, 255)),
    ),
    "dunes": Theme(
        p=(80, 220, 255), e=(255, 120, 60), x=(255, 240, 120), w=(170, 120, 60), hud=(255, 230, 190),
        bg=(30, 22, 16),
        r=((255, 70, 40), (255, 200, 60), (120, 255, 120), (255, 255, 255), (200, 120, 255), (255, 140, 180),
           (60, 160, 255)),
    ),
}  # fmt: skip


class RacerSettings(GameSettings):
    traffic: int = Field(5, ge=1, le=10, title="Traffic")
    lives: int = Field(1, ge=1, le=5, title="Lives", json_schema_extra=GAME)


CAR = [".BBB.", "KBBBK", ".WWW.", ".BBB.", ".BBB.", "KBBBK", ".BBB.", ".LBL."]
LANE_X = (5, 13, 21)  # left pixel of a car in each lane
PLAYER_Y = 22
RACE_SLOTS = {
    1: [(1, PLAYER_Y)],
    2: [(0, PLAYER_Y), (2, PLAYER_Y)],
    3: [(0, PLAYER_Y), (2, PLAYER_Y), (1, 11)],
    4: [(0, PLAYER_Y), (2, PLAYER_Y), (0, 11), (2, 11)],
}
CAR_H, CONE_H = 8, 3


@register
class Racer(GameApp):
    id = "racer"
    name = "Racer"
    description = (
        "Top-down three-lane highway dash through traffic. Left/right changes lanes. "
        "Race: 2-4 cars on one road, last car running wins."
    )
    icon = "car"
    Settings = RacerSettings
    step_hz = 40.0
    max_players = 4
    controls = ("tilt", "swipe", "dpad", "gamepad")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("race", "Race", 2, 4, "ffa", "One road, last car running wins"),
    )
    maps: ClassVar[dict[str, str]] = {"highway": "Highway", "roadworks": "Roadworks", "rush": "Rush hour"}
    game_themes: ClassVar[dict[str, Theme]] = RACER_THEMES
    game_theme_labels: ClassVar[dict[str, str]] = {
        "asphalt": "Asphalt",
        "midnight": "Midnight",
        "dunes": "Dunes",
    }

    def new_game(self) -> None:
        rush = self.map_id == "rush"
        self.race = bool(self.roster) and self.play_mode.id == "race"
        seats = sorted(self.roster) if self.race else [1]
        slots = RACE_SLOTS[max(1, min(4, len(seats)))]
        self.players: list[dict[str, Any]] = [
            {
                "seat": s, "lane": lane, "x": float(LANE_X[lane]), "y": y, "alive": True, "think": 0.0,
                "lives": self.settings.lives, "inv": 0.0, "score": 0,
            }
            for s, (lane, y) in zip(seats, slots, strict=False)
        ]  # fmt: skip
        self.speed = 30.0 if rush else 22.0
        self.dens = min(10, self.settings.traffic + (3 if rush else 0))
        self.dist = 0.0
        self.cars: list[list[float]] = []  # [lane, y, own_speed, colour index, kind (0 car, 1 cone)]
        self.gap = 10.0
        self.closure: dict[str, Any] = {"lane": None, "t": self.rng.uniform(5, 9), "warn": 0.0, "cone": 0.0}
        self._cache: dict[Any, Sprite] = {}
        self._traffic: dict[Any, list[Sprite]] = {}

    # ------------------------------------------------------------ art
    def _car(self, body: RGB) -> Sprite:
        if body not in self._cache:
            glass = (
                (210, 230, 255) if self.race else tint(body, 0.7)
            )  # one shared glass tint keeps frames small
            pal = {"B": body, "K": (50, 50, 60), "W": glass, "L": (255, 20, 20)}
            self._cache[body] = Sprite.parse(CAR, pal)
        return self._cache[body]

    def _traffic_sprites(self) -> list[Sprite]:
        key = (_tid(self), self.race)
        if key not in self._traffic:
            avoid = [self._colour(p) for p in self.players]
            bodies = [c for c in self.theme.r if _far(c, avoid)] or [(200, 200, 200)]
            if self.race:
                bodies = bodies[:2]  # races already bring up to four car colours
            self._traffic[key] = [self._car(b) for b in bodies]
        return self._traffic[key]

    def _colour(self, pl: dict[str, Any]) -> RGB:
        return self.colour_of(pl["seat"]) if self.race else self.theme.p

    # ------------------------------------------------------------ input
    def _lane_taken(self, pl: dict[str, Any], lane: int) -> bool:
        return any(
            q is not pl and q["alive"] and q["lane"] == lane and abs(q["y"] - pl["y"]) < 8.6
            for q in self.players
        )

    def _steer(self, pl: dict[str, Any], lane: int) -> None:
        lane = max(0, min(2, lane))
        if lane != pl["lane"] and not self._lane_taken(pl, lane):
            pl["lane"] = lane

    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        for pl in self.players:
            if pl["seat"] == player and pl["alive"]:
                if k == "left":
                    self._steer(pl, pl["lane"] - 1)
                elif k == "right":
                    self._steer(pl, pl["lane"] + 1)

    # ------------------------------------------------------------ traffic
    def _spawn(self) -> None:
        # traffic keeps formation (same relative speed), so spacing rules at spawn guarantee a way through
        closed = self.closure["lane"]
        soon = closed is None and self.map_id == "roadworks" and self.closure["t"] < 3
        lanes = [la for la in (0, 1, 2) if la != closed]
        self.rng.shuffle(lanes)
        pair = closed is None and not soon and self.rng.random() < 0.08 * self.dens
        for lane in lanes[: 2 if pair else 1]:
            self.cars.append([float(lane), -9.0, 0.5, float(self.rng.randrange(1, 8)), 0.0])
        rel = self.speed * 0.5
        self.gap = (21 + rel * 0.35 + self.rng.uniform(0, 14)) * (1.4 - self.dens * 0.08)

    def _roadworks(self, dt: float, mv: float) -> None:
        cl = self.closure
        cl["t"] -= dt
        if cl["lane"] is None:
            if cl["t"] <= 0:
                cl.update(lane=self.rng.choice((0, 2)), t=self.rng.uniform(5, 8), warn=1.4, cone=0.0)
            return
        if cl["warn"] > 0:
            cl["warn"] -= dt
        else:
            cl["cone"] -= mv
            if cl["cone"] <= 0:
                self.cars.append([float(cl["lane"]), -4.0, 1.0, 0.0, 1.0])  # cones sit still on the road
                cl["cone"] = 5.0
        if cl["t"] <= 0:
            cl.update(lane=None, t=self.rng.uniform(6, 12))

    @staticmethod
    def _h(c: list[float]) -> float:
        return CONE_H if c[4] else CAR_H

    def _free(self, pl: dict[str, Any], lane: int, t: float) -> bool:
        py = pl["y"]
        for c in self.cars:
            if int(c[0]) != lane:
                continue
            cy = c[1] + self.speed * c[2] * t
            if cy < py + 8.6 and cy + self._h(c) > py - 0.6:
                return False
        return not self._lane_taken(pl, lane)

    def _survive(self, pl: dict[str, Any], lane: int, t: float, depth: int, step: float) -> int:
        """How many look-ahead steps we can survive from `lane` at time `t` (small DFS)."""
        if depth == 0:
            return 0
        best = 0
        for nl in (lane, lane - 1, lane + 1):
            if not 0 <= nl <= 2:
                continue
            ok = self._free(pl, nl, t + step) and (
                nl == lane or (self._free(pl, nl, t) and self._free(pl, lane, t + step))
            )
            if ok:
                best = max(best, 1 + self._survive(pl, nl, t + step, depth - 1, step))
                if best == depth:
                    break
        return best

    def _ai(self, pl: dict[str, Any], dt: float) -> None:
        pl["think"] -= dt
        if pl["think"] > 0 or abs(pl["x"] - LANE_X[pl["lane"]]) > 1:
            return
        pl["think"] = 0.06 + (1 - self.skill) * 0.3
        step = 0.28
        depth = 3 + round(3 * self.skill)
        cur = pl["lane"]
        scores = []
        for nl in (cur, cur - 1, cur + 1):
            if not 0 <= nl <= 2:
                continue
            if nl != cur and not (self._free(pl, nl, 0) and self._free(pl, nl, step)):
                continue
            if nl == cur and not self._free(pl, cur, step):
                scores.append((0, 0, nl))
                continue
            sv = 1 + self._survive(pl, nl, step, depth - 1, step)
            scores.append((sv, 1 if nl == cur else 0, nl))
        if scores:
            self._steer(pl, max(scores)[2])

    # ------------------------------------------------------------ simulation
    def update(self, dt: float) -> None:
        self.speed = min(60.0, self.speed + 0.5 * dt)
        mv = self.speed * dt
        self.dist += mv
        for c in self.cars:
            c[1] += self.speed * c[2] * dt
        self.cars = [c for c in self.cars if c[1] < 34]
        if self.map_id == "roadworks":
            self._roadworks(dt, mv)
        self.gap -= mv * 0.5
        if self.gap <= 0:
            self._spawn()
        for pl in self.players:
            if not pl["alive"]:
                pl["y"] += mv * 0.8  # the wreck falls behind
                continue
            if not self.is_human(pl["seat"]):
                self._ai(pl, dt)
            pl["x"] = approach(pl["x"], LANE_X[pl["lane"]], (30 + self.speed * 0.6) * dt)
            pl["score"] = int(self.dist / 10)
            if pl["inv"] > 0:
                pl["inv"] -= dt
                continue
            for c in self.cars:
                cx = LANE_X[int(c[0])]
                if abs(cx - pl["x"]) < 4.5 and c[1] < pl["y"] + 7.5 and c[1] + self._h(c) > pl["y"] + 0.5:
                    self._crash(pl)
                    break
            if not self.race and int(self.dist) % 3 == 0 and self.rng.random() < 0.5:
                self.fx.emit(
                    pl["x"] + 1 + self.rng.randrange(3), pl["y"] + 8, 0, self.speed * 0.3, (90, 90, 110), 0.2
                )
        self.score = self.players[0]["score"]
        if self.race:
            _race_finished(self, self.players)
        elif not self.players[0]["alive"]:
            self.game_over()

    def _crash(self, pl: dict[str, Any]) -> None:
        x, y = pl["x"] + 2, pl["y"] + 2
        self.fx.burst(self.rng, x, y, (255, 150, 0), 18, 18, 0.8)
        self.fx.burst(self.rng, x, y, WHITE, 6, 10, 0.5)
        if self.is_human(pl["seat"]):
            self.damage()
        pl["lives"] -= 1
        if pl["lives"] > 0:
            pl["inv"] = 1.6  # blink through the traffic for a moment
        else:
            pl["alive"] = False

    # ------------------------------------------------------------ drawing
    def draw(self, f: Frame, now: float) -> None:
        th = self.theme
        tid = _tid(self)
        classic = tid == "classic"
        grass = (20, 90, 30) if classic else th.w if tid in self.game_themes else scale(th.w, 0.5)
        road = th.bg if tid in self.game_themes else (22, 22, 30)
        f.rect(0, 0, 32, 32, road)
        f.rect(0, 0, 3, 32, grass)
        f.rect(29, 0, 3, 32, grass)
        s = int(self.dist)
        for y in range(-(s % 8), 32, 8) if not self.race else ():  # races carry more cars: plain verges
            f.rect(0, y, 3, 2, scale(grass, 0.55))
            f.rect(29, y + 4, 3, 2, scale(grass, 0.55))
        kerb = (230, 30, 30) if classic else th.e
        for y in range(-(s % 4), 32, 4):
            f.vline(3, y, 2, kerb)
            f.vline(3, y + 2, 2, WHITE)
            f.vline(28, y, 2, WHITE)
            f.vline(28, y + 2, 2, kerb)
        lane_c = scale(th.hud, 0.55)
        for y in range(-(s % 6), 32, 6):
            f.vline(11, y, 3, lane_c)
            f.vline(19, y, 3, lane_c)
        cl = self.closure
        if cl["lane"] is not None and cl["warn"] > 0 and int(now * 4) % 2:
            x = LANE_X[cl["lane"]] + 2  # flashing chevrons: this lane is about to close
            for y in (2, 6):
                f.set(x, y + 2, th.x)
                f.set(x - 1, y + 1, th.x)
                f.set(x + 1, y + 1, th.x)
                f.set(x - 2, y, th.x)
                f.set(x + 2, y, th.x)
        traffic = self._traffic_sprites()
        for lane, y, _own, ci, kind in self.cars:
            x = LANE_X[int(lane)]
            if kind:
                cy = round(y)
                f.set(x + 2, cy, WHITE)
                f.rect(x + 1, cy + 1, 3, 1, th.x)
                f.rect(x, cy + 2, 5, 1, scale(th.x, 0.7))
            else:
                f.sprite(traffic[int(ci) % len(traffic)], x, round(y))
        for pl in self.players:
            if pl["y"] > 32:
                continue
            col = self._colour(pl)
            if not pl["alive"]:
                f.sprite(self._car(scale(col, 0.35)), round(pl["x"]), round(pl["y"]))
                continue
            if pl["inv"] > 0 and int(now * 8) % 2:
                continue
            if self.over and not self.race:
                continue
            f.sprite(self._car(col), round(pl["x"]), round(pl["y"]))
        self.hud(f, str(self.score), y=1)
        if self.race:
            _pips(f, self.players, self)
        elif self.settings.lives > 1:
            for k in range(self.players[0]["lives"]):
                f.rect(1 + 3 * k, 1, 2, 2, th.e)
