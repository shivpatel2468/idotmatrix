"""Leaf Leap — a flip-screen side-scrolling platformer for 1–2 players. Original code, level generator and pixel art.

Sprig, a small sprout with a leaf on its head, runs through procedurally built levels of five screens: grass and
dirt, brick ledges, pits, coins and shell-backed beetles to stomp, and a goal flag on the last screen. Each level
is harder than the one before. Level sets (maps) change the generator: open meadows, low-ceilinged caves, sky isles
full of pits, and a beetle-crowded castle.

Two players: in co-op both sprouts share a pool of lives and a fallen partner pops back in next to the other; in a
race the first to the flag wins the level. The camera shows the leader's screen and pulls a straggler along.

Hardware-friendly (docs/HARDWARE_PROTOCOL.md #9, #13): the camera never scrolls. The level is shown one whole
screen (8 × 8 tiles of 4 px) at a time and flips when the leader crosses a screen edge; the generator keeps the
tiles next to every screen seam solid, so no jump is ever blind. Sprig runs at ~1 px per streamed frame.

The demo AI simulates its options (keep running, jump now, wait, back off) a second into the future with the real
physics and takes the one that survives, gains the most ground and collects the most.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, scale
from .games_core import WHITE, GameApp, GameSettings, Mode, Theme, clamp, tint

T = 4  # tile size, px
SCREENS = 5
LW, LH = SCREENS * 8, 8  # level size in tiles
RUN = 9.0  # px/s
JUMP_V, GRAV = 31.0, 55.0
HW, HH = 3, 3  # hero hitbox (the leaf is decoration)
DT_AI = 1 / 30

EMPTY, GROUND, BRICK, ROCK = 0, 1, 2, 3

# per-hero state; one hero at a time is "loaded" onto the app (seat 1 while idle), so the physics and the
# rollout AI keep working on plain attributes
HERO_ATTRS = (
    "x",
    "y",
    "vx",
    "vy",
    "ground",
    "face",
    "safe",
    "dead_t",
    "move_t",
    "move_dir",
    "jump_q",
    "ai_t",
    "plan_run",
    "hold",
    "pts",
    "wins",
)

#: the hand-tuned default look (also used for the shared "classic" theme)
MEADOW_LOOK: dict[str, RGB] = {
    "sky": (3, 5, 18),
    "grass": (40, 190, 60),
    "dirt": (70, 38, 16),
    "brick": (170, 80, 30),
    "brick2": (110, 48, 16),
    "hero": (90, 235, 160),
    "leaf": (150, 255, 60),
    "beetle": (200, 130, 255),
    "coin": (255, 205, 30),
    "star": (60, 60, 90),
    "rock": (70, 60, 76),
}
LOOKS: dict[str, dict[str, RGB]] = {
    "meadow": MEADOW_LOOK,
    "autumn": {
        "sky": (12, 6, 10),
        "grass": (240, 130, 30),
        "dirt": (100, 56, 30),
        "brick": (160, 60, 40),
        "brick2": (105, 38, 24),
        "hero": (120, 240, 200),
        "leaf": (255, 90, 40),
        "beetle": (130, 190, 255),
        "coin": (255, 230, 80),
        "star": (70, 50, 60),
        "rock": (90, 64, 50),
    },
    "crystal": {
        "sky": (4, 4, 10),
        "grass": (70, 210, 160),
        "dirt": (64, 58, 88),
        "brick": (130, 90, 235),
        "brick2": (82, 54, 160),
        "hero": (180, 255, 120),
        "leaf": (90, 255, 170),
        "beetle": (255, 120, 100),
        "coin": (255, 215, 60),
        "star": (40, 64, 76),
        "rock": (60, 56, 84),
    },
}


def _theme(look: dict[str, RGB], hud: RGB) -> Theme:
    return Theme(
        p=look["hero"],
        e=look["beetle"],
        x=look["coin"],
        w=look["brick"],
        hud=hud,
        bg=look["sky"],
        r=(
            look["grass"],
            look["brick"],
            look["coin"],
            look["hero"],
            look["beetle"],
            look["leaf"],
            look["dirt"],
        ),
    )


class LeapSettings(GameSettings):
    enemies: bool = Field(True, title="Beetles", json_schema_extra={"group": "Game"})
    lives: int = Field(3, ge=1, le=5, title="Lives", json_schema_extra={"group": "Game"})
    race_levels: int = Field(3, ge=1, le=5, title="Race length (levels)", json_schema_extra={"group": "Game"})


#: level sets: generator weights for (gap, step, ledge, beetle, pitledge) and the chance of a wide pit
MAP_KINDS = {"meadow": "Meadow", "caves": "Caves", "sky": "Sky Isles", "castle": "Castle"}


@register
class LeafLeap(GameApp):
    id = "leafleap"
    name = "Leaf Leap"
    description = (
        "A flip-screen platformer: Sprig runs, jumps pits, stomps beetles and grabs coins on the way to the flag. "
        "Left/right run, up/A jumps. Two sprouts play co-op (shared lives) or race to the flag."
    )
    icon = "sprout"
    Settings = LeapSettings
    step_hz = 30.0
    over_hold = 2.5
    max_players: ClassVar[int] = 2
    controls = ("dpad", "gamepad", "joystick", "keyboard")
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Solo"),
        Mode("coop", "Co-op", 2, 2, "coop", "Shared lives; a fallen sprout pops back next to its partner"),
        Mode("race", "Race", 2, 2, "ffa", "First to the flag wins the level"),
    )
    maps: ClassVar[dict[str, str]] = MAP_KINDS
    game_themes: ClassVar[dict[str, Theme]] = {
        "meadow": _theme(MEADOW_LOOK, (255, 255, 255)),
        "autumn": _theme(LOOKS["autumn"], (255, 236, 200)),
        "crystal": _theme(LOOKS["crystal"], (220, 240, 255)),
    }
    game_theme_labels: ClassVar[dict[str, str]] = {
        "meadow": "Meadow",
        "autumn": "Autumn",
        "crystal": "Crystal cave",
    }

    # ------------------------------------------------------------------ level
    def new_game(self) -> None:
        self.level = 1
        self.lives = int(self.settings.lives)
        self.levels_done = 0
        self.seat_order = sorted(self.roster) if self.roster else [1]
        self.heroes: dict[int, dict[str, Any]] = {}
        self._seat = 1
        self._build()

    @property
    def multi(self) -> bool:
        return len(self.seat_order) > 1

    def _build(self) -> None:
        rng = self.rng
        lvl = self.level
        m = self.map_id if self.map_id in MAP_KINDS else "meadow"
        g = [[EMPTY] * LW for _ in range(LH)]
        h = [6] * LW  # ground top row per column (8 = pit)
        coins: list[list[float]] = []
        beetles: list[list[float]] = []
        weights_for = {
            "meadow": [3, 2, 2, 2 + min(3, lvl), 1 + min(2, lvl // 2)],
            "caves": [1, 2, 4, 3 + min(3, lvl), 2 + min(2, lvl // 2)],
            "sky": [5, 1, 3, 1 + min(2, lvl), 3 + min(2, lvl // 2)],
            "castle": [2, 3, 1, 4 + min(3, lvl), 1],
        }
        wide = {"meadow": min(0.6, 0.15 * lvl), "sky": min(0.85, 0.3 + 0.15 * lvl)}.get(
            m, min(0.5, 0.1 * lvl)
        )
        castle = m == "castle"
        for sc in range(SCREENS):
            x0 = sc * 8
            if sc == 0:
                for c in (3, 4, 5):
                    coins.append([float((x0 + c) * T + 1), 18.0])
                continue
            if sc == SCREENS - 1:
                if rng.random() < 0.5:
                    for c in (2, 3):
                        h[x0 + c] = 5
                continue
            kinds = ["gap", "step", "ledge", "beetle", "pitledge"]
            weights = weights_for[m]
            if not self.settings.enemies:
                weights[3] = 0
            kind = rng.choices(kinds, weights)[0]
            if kind == "gap":
                w = 2 if rng.random() < wide else 1
                c = rng.randrange(2, 6 - w + 1)
                for k in range(w):
                    h[x0 + c + k] = 8
                coins.append([float((x0 + c) * T + (w * T) // 2 - 1), 13.0])
            elif kind == "step":
                up = rng.choice((5, 4))
                for c in range(2, 6):
                    h[x0 + c] = up if c in (3, 4) else 5
                coins.append([float((x0 + 3) * T + 3), float((up - 2) * T + 1)])
                if self.settings.enemies and (castle or (lvl > 1 and rng.random() < 0.5)):
                    beetles.append([float((x0 + 6) * T), 6 * T - 3.0, -1.0, 1.0])
            elif kind == "ledge":
                r = rng.choice((3, 4))
                for c in range(2, 5):
                    g[r][x0 + c] = BRICK
                for c in range(2, 5):
                    coins.append([float((x0 + c) * T + 1), float((r - 1) * T + 1)])
            elif kind == "beetle":
                beetles.append([float((x0 + 5) * T), 6 * T - 3.0, -1.0, 1.0])
                if castle or (lvl > 2 and rng.random() < 0.5):
                    beetles.append([float((x0 + 2) * T), 6 * T - 3.0, 1.0, 1.0])
                coins.append([float((x0 + 4) * T + 1), 14.0])
            else:  # a pit with a brick stepping stone above it
                for c in (2, 3, 4, 5):
                    h[x0 + c] = 8
                g[4][x0 + 3] = BRICK
                g[4][x0 + 4] = BRICK
                coins.append([float((x0 + 3) * T + 3), 10.0])
        for c in range(LW):
            for r in range(h[c], LH):
                g[r][c] = GROUND
        if m == "caves":  # a low rock ceiling with stalactites: ledges leave little headroom
            for c in range(LW):
                g[0][c] = ROCK
                if c % 8 in (2, 5) and g[1][c] == EMPTY and g[2][c] == EMPTY:
                    g[1][c] = ROCK
        self.g = g
        self.coins = coins
        self.beetles = beetles  # [x, y, dir, alive]
        self.flag_x = (LW - 2) * T + 1
        self.screen = 0
        prev = self.heroes
        self.heroes = {}
        for i, seat in enumerate(self.seat_order):
            self._spawn(0, lane=i)
            self.pts = prev.get(seat, {}).get("pts", 0)
            self.wins = prev.get(seat, {}).get("wins", 0)
            self.dead_t = 0.0
            self.move_t = 0.0
            self.move_dir = 0
            self.jump_q = 0.0
            self.ai_t = 0.0
            self.plan_run = 1
            self.hold = 0.0
            self._save(seat)
        self._load(1 if 1 in self.heroes else self.seat_order[0])
        self.win_t = 0.0
        self.stars = [(self.rng.randrange(32), self.rng.randrange(1, 14)) for _ in range(7)]

    def _save(self, seat: int) -> None:
        self.heroes[seat] = {a: getattr(self, a) for a in HERO_ATTRS}

    def _load(self, seat: int) -> None:
        for a, v in self.heroes[seat].items():
            setattr(self, a, v)
        self._seat = seat

    def _spawn(self, screen: int, lane: int = 0) -> None:
        self.x = float(screen * 32 + 2 + 4 * lane)
        self.y = float(6 * T - HH)
        while self._solid_box(self.x, self.y) and self.y > 0:
            self.y -= 1
        self.vx = 0.0
        self.vy = 0.0
        self.ground = True
        self.face = 1
        self.safe = 1.5

    # ---------------------------------------------------------------- physics
    def _tile(self, px: float, py: float) -> int:
        c, r = int(px // T), int(py // T)
        if c < 0 or c >= LW:
            return GROUND
        if r < 0 or r >= LH:
            return EMPTY
        return self.g[r][c]

    def _solid_box(self, x: float, y: float) -> bool:
        for px in (x, x + HW - 0.01):
            for py in (y, y + HH - 0.01):
                if self._tile(px, py) != EMPTY:
                    return True
        return False

    def _move(self, st: list[float], dt: float, run: int, jump: bool) -> str:
        """Advance a physics state [x, y, vx, vy, ground] by dt. Returns '' or 'pit'."""
        x, y, _vx, vy, ground = st
        if jump and ground:
            vy = -JUMP_V
            ground = 0.0
        vx = run * RUN
        vy = min(60.0, vy + GRAV * dt)
        # horizontal, pixel by pixel
        nx = x + vx * dt
        if not self._solid_box(nx, y):
            x = nx
        else:
            step = 1 if vx > 0 else -1
            while not self._solid_box(x + step * 0.5, y) and abs(x - nx) > 0.5:
                x += step * 0.5
        ny = y + vy * dt
        if not self._solid_box(x, ny):
            y = ny
            ground = 0.0
        else:
            if vy > 0:
                y = float(int((ny + HH) // T) * T - HH)
                while self._solid_box(x, y):
                    y -= 1
                ground = 1.0
            else:
                y = float(int(ny // T + 1) * T)
                if self._solid_box(x, y):
                    y = st[1]
            vy = 0.0
        st[:] = [x, y, vx, vy, ground]
        return "pit" if y > 32 else ""

    # ------------------------------------------------------------------ input
    def key(self, k: str) -> None:
        if k in ("left", "right"):
            self.move_dir = -1 if k == "left" else 1
            self.move_t = 0.45
            self.face = self.move_dir
        elif k in ("up", "a", "b"):
            self.jump_q = 0.2
            if self.move_t <= 0:
                self.move_dir = 0

    def key_p(self, k: str, player: int) -> None:
        if player == self._seat:
            self.key(k)
            return
        h = self.heroes.get(player)
        if h is None:
            return
        if k in ("left", "right"):
            h["move_dir"] = -1 if k == "left" else 1
            h["move_t"] = 0.45
            h["face"] = h["move_dir"]
        elif k in ("up", "a", "b"):
            h["jump_q"] = 0.2
            if h["move_t"] <= 0:
                h["move_dir"] = 0

    # --------------------------------------------------------------------- AI
    HOLD = 0.4  # a pause or back-step lasts this long, then Sprig runs on

    def _ai(self) -> tuple[int, bool]:
        """Try a handful of plans ~1.1 s ahead with the real physics; keep the best."""
        best, best_s = (1, False), -1e9
        # (run, jump at step): jumping a few frames later is how the edge of a wide pit gets used
        plans = ((1, -1), (1, 0), (1, 3), (1, 6), (1, 9), (1, 12), (0, -1), (-1, -1), (-1, 0))
        for run, jump_at in plans:
            s = self._rollout(run, jump_at)
            if s > best_s:
                best, best_s = (run, jump_at == 0), s
        return best

    def _rollout(self, run: int, jump_at: int) -> float:
        jump = jump_at >= 0
        st = [self.x, self.y, 0.0, self.vy, 1.0 if self.ground else 0.0]
        beetles = [b[:] for b in self.beetles if b[3] > 0]
        coins = set(range(len(self.coins)))
        got = stomps = 0
        for i in range(42):
            r = run if i * DT_AI < self.HOLD else 1
            if self._move(st, DT_AI, r, i == jump_at):
                return -1000.0 + i
            for b in beetles:
                self._beetle_step(b, DT_AI)
                if b[3] <= 0:
                    continue
                if abs(st[0] + 1.5 - (b[0] + 2)) < 3.2 and abs(st[1] + HH - (b[1] + 3)) < 3.5:
                    if st[3] > 0 and st[1] + HH <= b[1] + 2.0:
                        b[3] = 0
                        stomps += 1
                        st[3] = -20.0
                    else:
                        return -800.0 + i
            for ci in list(coins):
                cx, cy = self.coins[ci]
                if abs(st[0] + 1 - cx - 0.5) < 2.5 and abs(st[1] + 1 - cy - 0.5) < 2.5:
                    coins.discard(ci)
                    got += 1
        # progress, loot, and ending on solid ground
        score = st[0] + got * 12 * self.skill + stomps * 8 + (2 if st[4] else 0)
        if jump:
            score -= 1.5 + jump_at * 0.05
        if run <= 0:
            score -= 12  # waiting or backing off is only worth it to dodge something
        return score

    # ------------------------------------------------------------------- loop
    def _beetle_step(self, b: list[float], dt: float) -> None:
        if b[3] <= 0:
            return
        nx = b[0] + b[2] * 3.5 * dt
        front = nx + (4 if b[2] > 0 else 0)
        wall = self._tile(front, b[1] + 1) != EMPTY
        floor = self._tile(front, b[1] + 4) != EMPTY
        if wall or not floor:
            b[2] = -b[2]
        else:
            b[0] = nx

    def _controlled(self) -> bool:
        """Is the loaded hero driven by a person?"""
        if not self.roster:
            return self.human
        return self.is_human(self._seat)

    def update(self, dt: float) -> None:
        if self.win_t > 0:
            self.win_t -= dt
            if self.win_t <= 0:
                self.levels_done += 1
                if self.play_mode.id == "race" and self.levels_done >= int(self.settings.race_levels):
                    self._race_result()
                    return
                self.level += 1
                self._build()
            return
        for b in self.beetles:
            self._beetle_step(b, dt)
        if not self.multi:
            self._hero_step(dt)
            if self.over:
                return
        else:
            self._save(self._seat)
            for seat in self.seat_order:
                self._load(seat)
                self._hero_step(dt)
                self._save(seat)
                if self.over or self.win_t > 0:
                    break
            self._load(1 if 1 in self.heroes else self.seat_order[0])
            if self.over:
                return
        self._camera()

    def _camera(self) -> None:
        if not self.multi:
            self.screen = int(clamp((self.x + 1.5) // 32, 0, SCREENS - 1))
            return
        self._save(self._seat)
        alive = [s for s in self.seat_order if self.heroes[s]["dead_t"] <= 0]
        if not alive:
            return
        lead = max(alive, key=lambda s: self.heroes[s]["x"])
        scr = int(clamp((self.heroes[lead]["x"] + 1.5) // 32, 0, SCREENS - 1))
        self.screen = scr
        # a straggler is pulled onto the leader's screen (the camera never scrolls back)
        cur = self._seat
        for s in alive:
            if (self.heroes[s]["x"] + 1.5) // 32 < scr:
                self._load(s)
                self._spawn(scr)
                self.safe = 1.0
                self._save(s)
        self._load(cur)

    def _hero_step(self, dt: float) -> None:
        self.safe = max(0.0, self.safe - dt)
        if self.dead_t > 0:
            self.dead_t -= dt
            if self.dead_t <= 0:
                self._respawn()
            return
        if self._controlled():
            self.move_t = max(0.0, self.move_t - dt)
            run = self.move_dir if self.move_t > 0 else 0
            jump = self.jump_q > 0
            self.jump_q = max(0.0, self.jump_q - dt)
        else:
            self.ai_t -= dt
            self.hold = max(0.0, self.hold - dt)
            jump = False
            if self.ai_t <= 0 and self.ground:
                self.ai_t = 0.12 + (1 - self.skill) * 0.15
                self.plan_run, jump = self._ai()
                self.hold = self.HOLD
            run = self.plan_run if self.hold > 0 else 1
        if run:
            self.face = run
        st = [self.x, self.y, self.vx, self.vy, 1.0 if self.ground else 0.0]
        pit = self._move(st, dt, run, jump)
        self.x, self.y, self.vx, self.vy, g = st
        self.ground = g > 0
        if pit:
            self._die()
            return
        # beetles: stomp from above, hurt from the side
        for b in self.beetles:
            if b[3] <= 0:
                continue
            if abs(self.x + 1.5 - (b[0] + 2)) < 3.2 and abs(self.y + HH - (b[1] + 3)) < 3.5:
                if self.vy > 0 and self.y + HH <= b[1] + 2.0:
                    b[3] = 0
                    self.vy = -20.0
                    self._gain(20)
                    self.fx.burst(self.rng, b[0] + 2 - self.screen * 32, b[1] + 1, (190, 90, 255), 8, 9, 0.5)
                    self.fx.burst(self.rng, b[0] + 2 - self.screen * 32, b[1] - 1, WHITE, 3, 5, 0.3)
                elif self.safe <= 0:
                    self._die()
                    return
        for c in list(self.coins):
            if abs(self.x + 1 - c[0] - 0.5) < 2.5 and abs(self.y + 1 - c[1] - 0.5) < 2.5:
                self.coins.remove(c)
                self._gain(10)
                self.fx.burst(self.rng, c[0] + 1 - self.screen * 32, c[1] + 1, (255, 220, 60), 5, 7, 0.35)
        if self.x + HW >= self.flag_x:
            self._gain(100)
            self.wins += 1
            self.win_t = 2.0
            self.flash = 0.3
            self.winner = self._seat
            self.fx.burst(self.rng, self.flag_x - self.screen * 32, 10, (120, 255, 90), 16, 12, 0.8)

    def _gain(self, n: int) -> None:
        self.pts += n
        if self.play_mode.id != "race" or self._seat == 1:
            self.score += n

    def _die(self) -> None:
        if self.play_mode.id != "race":
            self.lives -= 1  # co-op shares one pool of lives
        self.dead_t = 1.1
        if self._controlled():
            self.damage()  # the red fade: only for a person, never for the AI
        self.fx.burst(
            self.rng, self.x + 1 - self.screen * 32, min(30.0, self.y + 1), (120, 255, 150), 10, 10, 0.6
        )
        self.fx.burst(
            self.rng, self.x + 1 - self.screen * 32, min(30.0, self.y + 1), (255, 60, 60), 4, 6, 0.4
        )

    def _respawn(self) -> None:
        if self.lives <= 0:
            others = [s for s in self.seat_order if s != self._seat and self.heroes[s]["dead_t"] <= 0]
            if not others or not self.multi:
                self.dead_t = 0.0
                self._out()
                return
            self.dead_t = 0.5  # co-op: out of lives — this sprout waits while the partner plays on
            return
        partner = next(
            (s for s in self.seat_order if s != self._seat and self.heroes.get(s, {}).get("dead_t", 1) <= 0),
            None,
        )
        if partner is not None and self.play_mode.id == "coop":
            p = self.heroes[partner]
            self._spawn(self.screen)
            if p["ground"] and int((p["x"] + 1.5) // 32) == self.screen:
                self.x, self.y = p["x"], p["y"] - 4  # pops in right above the partner
                while self._solid_box(self.x, self.y) and self.y > 0:
                    self.y -= 1
            self.fx.burst(self.rng, self.x + 1 - self.screen * 32, self.y, (120, 255, 150), 8, 6, 0.5)
        else:
            self._spawn(self.screen)

    def _out(self) -> None:
        """Out of lives: solo = game over, co-op = the match ends."""
        if self.play_mode.id == "coop" and self.roster:
            self.result(
                scores={s: int(self.heroes.get(s, {}).get("pts", 0)) for s in self.seat_order},
                text=f"LEVEL {self.level}",
            )
        else:
            self.game_over()

    def _race_result(self) -> None:
        self._save(self._seat)
        scores = {s: int(h["wins"]) for s, h in self.heroes.items()}
        pts = {s: int(h["pts"]) for s, h in self.heroes.items()}
        win = max(self.seat_order, key=lambda s: (scores[s], pts[s]))
        self.result(winner_seat=win, scores=scores)

    # ------------------------------------------------------------------- draw
    @property
    def theme_id(self) -> str:
        return str(self.sel.get("theme", self.settings.theme))

    def _pal(self) -> dict[str, RGB]:
        tid = self.theme_id
        if tid == "classic":
            return MEADOW_LOOK
        if tid in LOOKS:
            return LOOKS[tid]
        th = self.theme
        return {
            "sky": th.bg,
            "grass": th.p,
            "dirt": scale(th.w, 0.45),
            "brick": th.r[1],
            "brick2": scale(th.r[1], 0.6),
            "hero": tint(th.x, 0.1),
            "leaf": th.p,
            "beetle": th.e,
            "coin": th.x,
            "star": (60, 60, 90),
            "rock": scale(th.w, 0.4),
        }

    def draw(self, f: Frame, now: float) -> None:
        pal = self._pal()
        f.clear(pal["sky"])
        caves = self.g[0][0] == ROCK
        if not caves:
            for sx, sy in self.stars:
                f.set(sx, sy, pal["star"])
        ox = self.screen * 32
        c0 = self.screen * 8
        for r in range(LH):
            row = self.g[r]
            for c in range(c0, c0 + 8):
                t = row[c]
                if t == EMPTY:
                    continue
                x, y = (c - c0) * T, r * T
                if t == GROUND:
                    top = r == 0 or self.g[r - 1][c] == EMPTY
                    f.rect(x, y, T, T, pal["dirt"])
                    if top:
                        f.hline(x, y, T, pal["grass"])
                elif t == ROCK:
                    if r == 0:
                        f.rect(x, y, T, T - 1, pal["rock"])
                        f.set(x + (c % 3), y + T - 1, pal["rock"])
                    else:  # a stalactite
                        f.rect(x + 1, y, 2, 2, pal["rock"])
                        f.set(x + 1 + (c % 2), y + 2, pal["rock"])
                else:
                    f.rect(x, y, T, T, pal["brick"])
                    f.hline(x, y + T - 1, T, pal["brick2"])
        # flag on the last screen
        fx = self.flag_x - ox
        if 0 <= fx < 32:
            base = 6 * T
            while self._tile(self.flag_x, base - 1) != EMPTY:
                base -= T
            f.vline(fx, base - 12, 12, (170, 170, 190))
            wave = int(now * 4) % 2
            f.rect(fx + 1, base - 12 + wave, 3, 2, (255, 60, 110))
        blink = int(now * 3) % 2
        for cx, cy in self.coins:
            x = int(cx - ox)
            if -2 < x < 32:
                f.rect(x, int(cy), 2, 2, pal["coin"] if blink else tint(pal["coin"], 0.35))
        for bx, by, bd, alive in self.beetles:
            x = round(bx - ox)
            if alive <= 0 or not -4 < x < 32:
                continue
            y = round(by)
            f.rect(x + 1, y, 2, 1, pal["beetle"])
            f.rect(x, y + 1, 4, 1, pal["beetle"])
            f.set(x + (3 if bd > 0 else 0), y + 1, WHITE)
            leg = int(now * 6 + bx) % 2
            f.set(x + leg, y + 2, scale(pal["beetle"], 0.6))
            f.set(x + 2 + leg, y + 2, scale(pal["beetle"], 0.6))
        self._save(self._seat)
        for seat in reversed(self.seat_order):
            body = self.colour_of(seat) if self.multi else pal["hero"]
            self._hero(f, self.heroes[seat], body, pal, now, ox)
        self._hud(f, pal)

    def _hero(self, f: Frame, h: dict[str, Any], body: RGB, pal: dict[str, RGB], now: float, ox: int) -> None:
        if h["dead_t"] > 0 or (h["safe"] > 0 and int(now * 10) % 2):
            return
        x, y = round(h["x"] - ox), round(h["y"])
        f.set(x + 1, y - 1, pal["leaf"])
        if h["face"] > 0:
            f.set(x + 2, y - 2, pal["leaf"])
        else:
            f.set(x, y - 2, pal["leaf"])
        f.hline(x, y, 3, body)
        f.set(x + (2 if h["face"] > 0 else 0), y, WHITE)  # the eye looks where Sprig runs
        f.hline(x, y + 1, 3, body)
        if not h["ground"]:
            f.hline(x, y + 2, 3, scale(body, 0.7))
        elif abs(h["vx"]) > 0 and int(now * 8) % 2:
            f.set(x + 1, y + 2, scale(body, 0.7))
        else:
            f.set(x, y + 2, scale(body, 0.7))
            f.set(x + 2, y + 2, scale(body, 0.7))

    def _hud(self, f: Frame, pal: dict[str, RGB]) -> None:
        y0 = 5 if self.g[0][0] == ROCK else 1
        if self.play_mode.id == "race" and self.multi:
            for i, seat in enumerate(self.seat_order):  # level wins, one dot each, in seat colours
                col = self.colour_of(seat)
                f.set(1 + i * 4, y0, col)
                for k in range(int(self.heroes[seat]["wins"])):
                    f.set(1 + i * 4 + 1 + k % 2, y0 + 1 + k // 2, col)
        else:
            for i in range(max(0, self.lives)):
                f.set(1 + i * 2, y0, (120, 255, 150))
        self.hud(f, str(self.score), y=y0)
        if self.win_t > 0:
            if self.play_mode.id == "race" and self.multi:
                w = getattr(self, "winner", 1)
                f.text_center(12, f"P{w}", self.colour_of(w))
            else:
                f.text_center(12, f"LV {self.level + 1}", (255, 230, 120))

    def status(self) -> dict[str, Any]:
        st = super().status()
        st.update({"level": self.level, "lives": self.lives, "screen": self.screen + 1})
        return st
