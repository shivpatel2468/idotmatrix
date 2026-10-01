"""Street Surge — a pseudo-3D night street race for 1–2 players. Original code, track generator and pixel art.

Classic segment-based pseudo-3D: every track segment carries a curve and a height; segments are projected from
the camera, near to far, and each fills the screen rows between itself and the previous one with flat colour
bands (verge, red/white rumble strip, asphalt, lane dashes), clipped so hill crests hide what is behind them.
Street lamps and billboards stand at the roadside, rivals race ahead, and a skyline slides with the curves.

Hardware notes (docs/HARDWARE_PROTOCOL.md #9, #13): this game streams, so it keeps frames small — flat bands
compress to ~one PNG row filter each — and runs at a modest speed with long (2-segment) stripes, so the stripes
advance a fraction of their period per streamed frame instead of strobing.

Up to four players (free-for-all, or two teams scoring by finishing place): the camera rides behind whichever
racer is furthest back, so every player's car is on screen (leaders appear on the road ahead in their colours).
Tracks (maps) change the course itself: the city's mixed curves and hills, a sweeping coast road, a tight mountain
pass and a wide, flat speedway oval.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from pydantic import Field

from ..engine.app import register
from ..gfx import RGB, Frame, measure, scale
from .games_core import BLACK, WHITE, GameApp, GameSettings, Mode, Theme, approach, clamp

SEAT_COLORS: tuple[RGB, ...] = ((0, 200, 255), (255, 60, 90), (80, 255, 120), (255, 200, 0))

HOR = 12  # horizon row
KX, KY = 22.0, 19.0  # projection scale (px per world unit at z = 1)
CAMH = 1.0  # camera height over the road
RW = 1.0  # road half-width
DRAW = 34  # segments drawn
AHEAD = 1.7  # the camera racer sits this far in front of the camera
BAND = 2  # segments per colour band
LAPS = 2  # default race length (the `laps` setting)
VMAX, VNITRO, VGRASS = 6.0, 7.6, 3.2  # segments per second
CF = 2.6  # centrifugal push on curves


class Racer:
    __slots__ = (
        "ai_x",
        "brake",
        "bump",
        "col",
        "d",
        "done",
        "kind",
        "nitro",
        "nitro_t",
        "seat",
        "steer",
        "v",
        "vt",
        "x",
    )

    def __init__(self, kind: str, d: float, x: float, col: RGB, seat: int = 0, vt: float = VMAX) -> None:
        self.kind = kind  # player | rival
        self.d = d  # distance along the course, segments
        self.x = x
        self.v = 0.0
        self.vt = vt
        self.col = col
        self.seat = seat
        self.steer = 0.0  # human steering, -1..1, decays
        self.brake = 0.0
        self.nitro = 3
        self.nitro_t = 0.0
        self.bump = 0.0
        self.ai_x = x
        self.done: float | None = None  # finish time


#: the hand-tuned default look (also used for the shared "classic" theme)
MIDNIGHT: dict[str, Any] = {
    # flat verge and asphalt; only the rumble strips and lane dashes carry the motion (small PNGs)
    "verge": ((6, 6, 20), (6, 6, 20)),
    "rumble": ((110, 110, 125), (210, 20, 40)),
    "road": ((34, 34, 48), (34, 34, 48)),
    "lane": (170, 170, 180),
    "sky": ((2, 0, 14), (26, 4, 46)),
    "city": (16, 8, 40),
    "win": (120, 100, 40),
    "lamp": (255, 210, 110),
    "moon": (220, 220, 200),
}
LOOKS: dict[str, dict[str, Any]] = {
    "midnight": MIDNIGHT,
    "dusk": {
        "verge": ((14, 8, 12), (14, 8, 12)),
        "rumble": ((200, 130, 70), (150, 40, 50)),
        "road": ((44, 36, 44), (44, 36, 44)),
        "lane": (230, 190, 150),
        "sky": ((16, 8, 14), (40, 18, 28)),
        "city": (12, 6, 10),
        "win": (210, 150, 60),
        "lamp": (255, 190, 90),
        "moon": (255, 150, 70),
    },
    "frost": {
        "verge": ((10, 14, 22), (10, 14, 22)),
        "rumble": ((150, 170, 200), (40, 120, 220)),
        "road": ((40, 46, 60), (40, 46, 60)),
        "lane": (200, 220, 240),
        "sky": ((4, 8, 18), (16, 26, 44)),
        "city": (8, 14, 28),
        "win": (140, 200, 255),
        "lamp": (200, 230, 255),
        "moon": (230, 240, 255),
    },
}
RIVAL_COLORS: tuple[RGB, ...] = (
    (255, 150, 30),
    (170, 90, 255),
    (230, 230, 240),
    (80, 255, 120),
    (255, 220, 40),
    (255, 90, 200),
    (120, 160, 255),
)


def _theme(look: dict[str, Any]) -> Theme:
    return Theme(
        p=SEAT_COLORS[0],
        e=RIVAL_COLORS[0],
        x=look["lamp"],
        w=look["rumble"][1],
        hud=WHITE,
        bg=look["sky"][0],
        r=RIVAL_COLORS,
    )


#: tracks: id -> (label, road half-width)
TRACKS: dict[str, tuple[str, float]] = {
    "city": ("City", 1.0),
    "coast": ("Coast Road", 1.0),
    "pass": ("Mountain Pass", 0.9),
    "speedway": ("Speedway", 1.3),
}


class SurgeSettings(GameSettings):
    rivals: int = Field(5, ge=1, le=7, title="Rivals", json_schema_extra={"group": "Game"})
    hills: bool = Field(True, title="Hills", json_schema_extra={"group": "Game"})
    laps: int = Field(LAPS, ge=1, le=5, title="Laps", json_schema_extra={"group": "Game"})


@register
class StreetSurge(GameApp):
    id = "streetsurge"
    name = "Street Surge"
    description = (
        "Pseudo-3D night street race: laps of curves and hills against rival cars on four tracks. Left/right "
        "steer, A fires nitro, down/B brakes. Up to four players race each other or in two teams; the camera "
        "follows whoever is behind."
    )
    icon = "gauge"
    Settings = SurgeSettings
    max_players: ClassVar[int] = 4
    controls = (
        "tap",
        "tilt",
        "joystick",
        "gamepad",
        "dpad",
    )  # best controllers first (phone + Play mode default to the first)
    modes: ClassVar[tuple[Mode, ...]] = (
        Mode("solo", "Grand Prix"),
        Mode("race", "Versus", 2, 4, "ffa", "Beat the other players to the line"),
        Mode("teams", "Team Race", 2, 4, "versus", "Finishing places score points for your team"),
    )
    maps: ClassVar[dict[str, str]] = {k: v[0] for k, v in TRACKS.items()}
    game_themes: ClassVar[dict[str, Theme]] = {k: _theme(v) for k, v in LOOKS.items()}
    game_theme_labels: ClassVar[dict[str, str]] = {"midnight": "Midnight", "dusk": "Dusk", "frost": "Frost"}
    step_hz = 30.0
    over_hold = 2.5

    # ------------------------------------------------------------------ track
    def new_game(self) -> None:
        self.laps = int(self.settings.laps)
        self._track()
        self.t = 0.0
        # the intro screen already counted down: then only a short beat before the lights go green
        self.go = 0.3 if self.roster and self.settings.intro_outro else 2.4
        self.racers: list[Racer] = []
        self.players: dict[int, Racer] = {}
        for seat in sorted(self.roster) if self.roster else (1, 2):
            col = self.colour_of(seat) if self.roster else SEAT_COLORS[seat - 1]
            row = (seat - 1) // 2  # a two-wide grid: seats 3 and 4 start a row behind
            r = Racer("player", -1.4 * row, -0.45 if seat % 2 else 0.45, col, seat)
            self.players[seat] = r
            self.racers.append(r)
        pal = RIVAL_COLORS
        for i in range(self.settings.rivals):
            x = (-0.5, 0.5)[i % 2] + self.rng.uniform(-0.1, 0.1)
            vt = VMAX * self.rng.uniform(0.80, 0.93)
            self.racers.append(Racer("rival", 4.0 + i * 3.2, x, pal[i % len(pal)], vt=vt))
        self.banner, self.banner_t = "", 0.0
        self.finish_t: float | None = None
        self.overtakes = 0
        self._last_place = 0
        self.cam_seat = 1

    def _track(self) -> None:
        rng = self.rng
        tid = self.map_id if self.map_id in TRACKS else "city"
        self.rw = TRACKS[tid][1]
        curve: list[float] = []
        hill: list[float] = []
        h = 0.0

        def add(n: int, c: float, dh: float) -> None:
            nonlocal h
            h0 = h
            for i in range(n):
                k = i / max(1, n - 1)
                ease = math.sin(math.pi * k)  # curves ease in and out
                curve.append(c * ease)
                hill.append(h0 + dh * (0.5 - 0.5 * math.cos(math.pi * k)))
            h = h0 + dh

        add(16, 0.0, 0.0)
        if tid == "speedway":  # an oval: two long straights and two long left-handers, dead flat
            for _ in range(2):
                add(34, 0.0, 0.0)
                add(44, -0.045, 0.0)
        else:
            # segment lengths, curve range and chance, hill range and chance, course length
            n0, n1, c0, c1, pc, hr, ph, length = {
                "city": (12, 28, 0.025, 0.06, 0.7, 1.4, 0.55, 170),
                "coast": (24, 40, 0.018, 0.04, 0.85, 0.6, 0.3, 200),
                "pass": (8, 18, 0.05, 0.085, 0.8, 1.5, 0.8, 170),
            }[tid]
            while len(curve) < length:
                n = rng.randrange(n0, n1)
                c = rng.choice((-1, 1)) * rng.uniform(c0, c1) if rng.random() < pc else 0.0
                dh = rng.uniform(-hr, hr) if self.settings.hills and rng.random() < ph else 0.0
                dh = clamp(h + dh, -1.5, 1.5) - h
                add(n, c, dh)
        add(14, 0.0, -h)  # back to level for the start line
        self.curve = curve
        self.hill = hill
        self.L = len(curve)
        # roadside: lamps on both sides, the odd billboard
        self.props: dict[int, list[tuple[str, float]]] = {}
        lamp_gap, sign_gap = {"coast": (7, 17), "pass": (6, 29), "speedway": (9, 11)}.get(tid, (5, 23))
        for s in range(0, self.L, lamp_gap):
            side = 1 if (s // lamp_gap) % 2 else -1
            self.props.setdefault(s, []).append(("lamp", (self.rw + 0.35) * side))
        for s in range(12, self.L, sign_gap):
            self.props.setdefault(s, []).append(("sign", rng.choice((-1.9, 1.9)) * self.rw))
        self.skyline = [(x, rng.choice((2, 4, 5)), rng.random() < 0.3) for x in range(0, 64, 4)]

    def _seg(self, d: float) -> int:
        return int(d) % self.L

    def _height(self, d: float) -> float:
        s = int(d)
        a, b = self.hill[s % self.L], self.hill[(s + 1) % self.L]
        return a + (b - a) * (d - s)

    # ----------------------------------------------------------------- input
    def key(self, k: str) -> None:
        self.key_p(k, 1)

    def key_p(self, k: str, player: int) -> None:
        r = self.players.get(player)
        if r is None or player not in self.active_seats:
            return
        if k == "left":
            r.steer = -1.0
        elif k == "right":
            r.steer = 1.0
        elif k in ("down", "b"):
            r.brake = 0.35
        elif k == "a":
            self._nitro(r)

    def _nitro(self, r: Racer) -> None:
        if r.nitro > 0 and r.nitro_t <= 0 and self.go <= 0:
            r.nitro -= 1
            r.nitro_t = 1.6

    @property
    def active_seats(self) -> list[int]:
        if self.roster:
            return [s for s in sorted(self.roster) if s in self.players]
        if 2 in self.seats or not self.human:
            return [1, 2]
        return [1]

    # ------------------------------------------------------------------ loop
    def update(self, dt: float) -> None:
        self.t += dt
        self.banner_t = max(0.0, self.banner_t - dt)
        seats = self.active_seats
        if self.go > 0:
            self.go -= dt
            if self.go <= 0:
                self._say("GO!", 0.8)
            return
        field = [r for r in self.racers if r.kind == "rival" or r.seat in seats]
        for r in field:
            if r.done is not None:
                r.v = approach(r.v, 2.0, 3.0 * dt)
                r.d += r.v * dt
                continue
            s = self._seg(r.d)
            human = r.kind == "player" and self.is_human(r.seat)
            if r.kind == "rival":
                self._rival_ai(r, dt)
            elif not human:
                self._driver_ai(r, dt)
            # speed
            vmax = VNITRO if r.nitro_t > 0 else r.vt if r.kind == "rival" else VMAX
            if abs(r.x) > self.rw + 0.1:
                vmax = min(vmax, VGRASS)
            if r.brake > 0:
                vmax = min(vmax, r.v - 4.0 * dt)
            acc = 2.2 if r.v < vmax else 5.0
            r.v = approach(r.v, max(0.0, vmax), acc * dt)
            r.nitro_t = max(0.0, r.nitro_t - dt)
            r.brake = max(0.0, r.brake - dt)
            r.bump = max(0.0, r.bump - dt)
            # steering + centrifugal drift
            if r.kind == "player":
                steer = r.steer if human else clamp((r.ai_x - r.x) * 3.0, -1.0, 1.0)
                r.x += steer * 1.7 * dt * (0.4 + 0.6 * min(1.0, r.v / VMAX))
                r.steer = approach(r.steer, 0.0, 5.0 * dt) if human else 0.0
                r.x -= self.curve[s] * r.v * CF * dt
            else:
                r.x = approach(r.x, r.ai_x, 0.8 * dt)
            r.x = clamp(r.x, -2.0, 2.0)
            r.d += r.v * dt
            laps = self.laps
            if r.d >= self.L * laps and r.done is None:
                r.done = self.t
                if r.kind == "player":
                    self._say(self._ordinal(self._place(r)), 2.0)
                    if r.seat == self.cam_seat:  # chequered flag: a flash and a burst of the car's colour
                        self.flash = 0.3
                        self.fx.burst(self.rng, 16, 20, r.col, 12, 12, 0.7)
            elif (
                r.kind == "player"
                and r.d - r.v * dt >= 0
                and int((r.d - r.v * dt) // self.L) < int(r.d // self.L) < laps
            ):
                self._say("FINAL LAP" if int(r.d // self.L) == laps - 1 else "LAP", 1.2)
        self._collide(field)
        for p in (self.players[s] for s in seats):
            if p.nitro < 3 and int(self.t / 9.0) != int((self.t - dt) / 9.0):
                p.nitro += 1  # a pip refills every 9 s
        # camera: behind the rear-most racing player
        live = [self.players[s] for s in seats]
        cam = min(live, key=lambda r: r.d)
        self.cam_seat = cam.seat
        # scoring: overtakes by seat 1, then points for the finish
        me = self.players[1]
        place = self._place(me)
        if self._last_place and place < self._last_place:
            self.overtakes += self._last_place - place
        self._last_place = place
        self.score = self.overtakes * 5 + (max(0, 12 - place) * 10 if me.done is not None else 0)
        if self.roster and len(seats) > 1:
            self._multi_finish(seats)
            return
        if all(self.players[s].done is not None for s in seats) or (
            me.done is not None and self.t - me.done > 4.0
        ):
            if self.finish_t is None:
                self.finish_t = self.t
            if self.t - self.finish_t > 1.6:
                self.game_over()

    def _multi_finish(self, seats: list[int]) -> None:
        """Multiplayer: the race ends when every player is home, or 15 s after the first one."""
        done = [self.players[s].done for s in seats if self.players[s].done is not None]
        if not done:
            return
        if len(done) < len(seats) and self.t - min(d for d in done if d is not None) < 15.0:
            return
        if self.finish_t is None:
            self.finish_t = self.t
        if self.t - self.finish_t <= 1.6:
            return
        places = {s: self._place(self.players[s]) for s in seats}
        pts = {s: (max(0, 11 - places[s]) if self.players[s].done is not None else 0) for s in seats}
        best = min(seats, key=lambda s: places[s])
        if self.play_mode.teams == "versus":
            team = {0: 0, 1: 0}
            for s in seats:
                t = self.team_of(s)
                if t in team:
                    team[t] += pts[s]
            win = self.team_of(best) if team[0] == team[1] else (0 if team[0] > team[1] else 1)
            self.result(winner_team=win, scores=pts)
        else:
            self.result(winner_seat=best, scores=pts)

    def _rival_ai(self, r: Racer, dt: float) -> None:
        if self.rng.random() < dt * 0.25:
            r.ai_x = self.rng.choice((-0.55, 0.0, 0.55))

    def _driver_ai(self, r: Racer, dt: float) -> None:
        """Take the inside of curves, pass slower cars through the widest gap, lift when boxed in, nitro on
        straights. Each seat keeps its own side of the racing line so two AI players don't trade paint."""
        s = self._seg(r.d)
        ahead = sum(self.curve[(s + k) % self.L] for k in range(2, 9))
        bias = (-0.2, 0.2, -0.45, 0.45)[(r.seat - 1) % 4]
        want = clamp(ahead * 4.0 + bias, -0.7, 0.7)
        look = 4.0 + 5.0 * self.skill
        blockers = [o.x for o in self.racers if o is not r and 0 < o.d - r.d < look and o.v < r.v + 0.8]
        blockers += [o.x for o in self.racers if o is not r and -0.6 < o.d - r.d <= 0]  # alongside
        if blockers:
            # candidate lines across the road; keep the one furthest from every blocker, nearest our wish
            best, best_s = want, -1e9
            for k in range(-8, 9):
                x = k * 0.1
                gap = min(abs(x - bx) for bx in blockers)
                sc = min(gap, 0.6) * 10 - abs(x - want) - abs(x - r.x) * 0.5
                if sc > best_s:
                    best, best_s = x, sc
            want = best
            if min(abs(want - bx) for bx in blockers) < 0.45:
                close = [
                    o for o in self.racers if o is not r and 0 < o.d - r.d < 2.0 and abs(o.x - r.x) < 0.5
                ]
                if close:
                    r.brake = 0.1  # no gap: lift instead of rear-ending
        noise = (1.0 - self.skill) * 0.6 * math.sin(self.t * 1.3 + r.seat)
        r.ai_x = clamp(want + noise, -0.85, 0.85)
        straight = abs(ahead) < 0.05
        if (
            straight
            and not blockers
            and r.nitro > 0
            and r.nitro_t <= 0
            and r.v > VMAX * 0.9
            and self.rng.random() < dt * 0.6 * self.skill
        ):
            self._nitro(r)

    def _collide(self, field: list[Racer]) -> None:
        for a in field:
            if a.kind != "player":
                continue
            for b in field:
                if b is a:
                    continue
                dz = b.d - a.d
                if 0 < dz < 0.9 and abs(b.x - a.x) < 0.42 and a.bump <= 0:
                    a.v = min(a.v, b.v * 0.6)
                    a.bump = 0.6
                    a.x += 0.25 if a.x > b.x else -0.25
                    if self.is_human(a.seat):
                        self.damage(0.6)  # a person rear-ended someone: red fade + shake
                    if a.seat == self.cam_seat:
                        self.flash = 0.2
                        self.fx.burst(self.rng, 16, 25, (255, 170, 40), 7, 9, 0.4)

    def _place(self, r: Racer) -> int:
        def key(o: Racer) -> float:
            return -o.done + 1e6 if o.done is not None else o.d

        field = [o for o in self.racers if o.kind == "rival" or o.seat in self.active_seats]
        return 1 + sum(1 for o in field if o is not r and key(o) > key(r))

    @staticmethod
    def _ordinal(n: int) -> str:
        return f"{n}{'ST' if n == 1 else 'ND' if n == 2 else 'RD' if n == 3 else 'TH'}"

    def _say(self, text: str, t: float) -> None:
        self.banner, self.banner_t = text, t

    # ------------------------------------------------------------------ draw
    def _colors(self) -> dict[str, Any]:
        th = self.theme
        tid = str(self.sel.get("theme", self.settings.theme))
        if tid == "classic":
            return MIDNIGHT
        if tid in LOOKS:
            return LOOKS[tid]
        return {
            "verge": (scale(th.bg, 1.5), scale(th.bg, 1.5)),
            "rumble": (th.e, scale(th.hud, 0.8)),
            "road": (scale(th.w, 0.2), scale(th.w, 0.2)),
            "lane": scale(th.hud, 0.7),
            "sky": (th.bg, scale(th.w, 0.25)),
            "city": scale(th.w, 0.12),
            "win": scale(th.x, 0.45),
            "lamp": th.x,
            "moon": (220, 220, 200),
        }

    def draw(self, f: Frame, now: float) -> None:
        pal = self._colors()
        cam = self.players[self.cam_seat]
        cz = cam.d - AHEAD
        base = math.floor(cz)
        frac = cz - base
        cam_y = self._height(cz % self.L) + CAMH
        cam_x = cam.x * 0.85
        # sky: flat bands, a moon and a skyline that slides with the curves
        sky = pal["sky"]
        f.rect(0, 0, 32, 8, sky[0])
        f.rect(0, 8, 32, HOR - 8 + 1, sky[1])
        f.rect(15, 3, 2, 2, pal["moon"])  # the moon, clear of the HUD corners
        shift = int(self._sky_shift(cam.d)) % 64
        for bx, bh, lit in self.skyline:
            x = (bx - shift) % 64 - 16
            f.rect(x, HOR + 1 - bh, 4, bh, pal["city"])
            if lit and bh > 3:
                f.set(x + 1, HOR + 3 - bh, pal["win"])
        f.rect(0, HOR + 1, 32, 32 - HOR - 1, pal["verge"][0])
        # road, near to far
        maxy = 32
        x_off, dx = 0.0, -self.curve[base % self.L] * frac
        prev: tuple[float, float, float] | None = None
        items: list[tuple[float, int, float, float, float, int]] = []  # z, seg, sx-centre, sy, scale, clip
        for n in range(0, DRAW):
            s = base + n
            z = n - frac
            seg = s % self.L
            if n > 0:
                dx += self.curve[seg]
                x_off += dx
            if z < 0.6:
                continue
            sc = 1.0 / z
            sy = HOR + (cam_y - self.hill[seg]) * KY * sc
            cx = 16 + (x_off - cam_x) * KX * sc
            hw = self.rw * KX * sc
            clip = maxy
            if prev is not None:
                py, pcx, phw = prev
                top = max(HOR + 1, math.ceil(sy))
                if top < maxy and py > sy:
                    band = ((s - 1) // BAND) % 2
                    for y in range(top, min(maxy, math.ceil(py) + 1)):
                        t = (y - sy) / (py - sy) if py != sy else 0.0
                        t = clamp(t, 0.0, 1.0)
                        rcx = cx + (pcx - cx) * t
                        rhw = hw + (phw - hw) * t
                        self._row(f, y, rcx, rhw, band, pal, (s - 1) % self.L == 0)
                    maxy = min(maxy, top)
            items.append((z, seg, cx, sy, sc, clip))
            prev = (sy, cx, hw)
        # roadside props and cars, far to near
        cars = self._cars_by_seg(cam)
        for _z, seg, cx, sy, sc, clip in reversed(items):
            for kind, px in self.props.get(seg, ()):
                self._prop(f, kind, cx + px * KX * sc, sy, sc, clip, pal)
            for r, _dz in cars.get(seg, ()):
                self._car(f, r, cx + r.x * KX * sc, sy, sc, clip, now)
        self._player(f, cam, now)
        self._hud(f, now, cam)

    def _sky_shift(self, d: float) -> float:
        # the skyline turns with the accumulated curvature of the course
        s = int(d) % self.L
        acc = sum(self.curve[:s])
        return acc * 18.0 + (d // self.L) * sum(self.curve) * 18.0

    def _row(
        self, f: Frame, y: int, cx: float, hw: float, band: int, pal: dict[str, Any], start: bool
    ) -> None:
        f.hline(0, y, 32, pal["verge"][band])
        rw = hw * 1.18
        x0, x1 = round(cx - rw), round(cx + rw)
        f.hline(x0, y, x1 - x0 + 1, pal["rumble"][band])
        x0, x1 = round(cx - hw), round(cx + hw)
        if start:  # chequered start/finish line
            for x in range(x0, x1 + 1):
                f.set(x, y, WHITE if (x + y) % 2 else BLACK)
            return
        f.hline(x0, y, x1 - x0 + 1, pal["road"][band])
        if band and hw > 2:  # one centre dash line: the motion cue, at the lowest byte cost
            f.hline(round(cx - hw * 0.04), y, max(1, round(hw * 0.08)), pal["lane"])

    def _prop(
        self, f: Frame, kind: str, x: float, sy: float, sc: float, clip: int, pal: dict[str, Any]
    ) -> None:
        if sc < 0.07:
            return
        ix = round(x)
        base = round(sy)
        if kind == "lamp":
            h = max(2, round(1.7 * KY * sc))
            for y in range(base - h, base):
                if y < clip:
                    f.set(ix, y, (70, 70, 90))
            top = base - h
            if top < clip:
                f.set(ix, top, pal["lamp"])
                if sc > 0.25:
                    f.set(ix + (1 if x < 16 else -1), top, pal["lamp"])
        else:
            w = max(2, round(0.9 * KX * sc))
            h = max(1, round(0.5 * KY * sc))
            top = base - round(1.2 * KY * sc)
            col = (255, 0, 150) if (int(x) // 7) % 2 else (0, 200, 255)
            for y in range(top, top + h):
                if y < clip:
                    f.hline(ix - w // 2, y, w, col)
            for y in range(top + h, base):
                if y < clip:
                    f.set(ix, y, (60, 60, 80))

    def _cars_by_seg(self, cam: Racer) -> dict[int, list[tuple[Racer, float]]]:
        out: dict[int, list[tuple[Racer, float]]] = {}
        seats = self.active_seats
        for r in self.racers:
            if r is cam or (r.kind == "player" and r.seat not in seats):
                continue
            dz = r.d - (cam.d - AHEAD)
            if dz % self.L < 0.9 or dz % self.L > DRAW - 1:
                continue
            seg = int(r.d) % self.L
            out.setdefault(seg, []).append((r, dz))
        return out

    def _car(self, f: Frame, r: Racer, x: float, sy: float, sc: float, clip: int, now: float) -> None:
        w = max(2, round(0.62 * KX * sc))
        if w <= 2:
            if round(sy) - 1 < clip:
                f.set(round(x) - 1, round(sy) - 1, (255, 30, 30))
                f.set(round(x) + 1, round(sy) - 1, (255, 30, 30))
            return
        self._car_sprite(f, round(x), round(sy), w, r.col, clip, r.nitro_t > 0 and int(now * 10) % 2 == 0)

    def _car_sprite(self, f: Frame, cx: int, bottom: int, w: int, col: RGB, clip: int, flame: bool) -> None:
        h = max(2, round(w * 0.45))
        x0 = cx - w // 2
        top = bottom - h
        dark = scale(col, 0.45)
        for y in range(top, bottom):
            if y >= clip:
                continue
            k = y - top
            if k == 0 and h >= 3:  # roof / rear window
                f.hline(x0 + max(1, w // 5), y, w - 2 * max(1, w // 5), dark)
            elif k == h - 1:  # tail lights and wheels
                f.hline(x0, y, w, col)
                f.set(x0, y, (255, 30, 30))
                f.set(x0 + w - 1, y, (255, 30, 30))
            else:
                f.hline(x0, y, w, col)
        if h >= 3 and bottom < clip:
            f.set(x0 + 1, bottom, (20, 20, 20))
            f.set(x0 + w - 2, bottom, (20, 20, 20))
        if flame and bottom < clip:
            f.set(cx, bottom, (255, 140, 20))

    def _player(self, f: Frame, r: Racer, now: float) -> None:
        bob = 1 if abs(r.x) > self.rw + 0.1 and int(now * 10) % 2 else 0
        shake = 1 if r.bump > 0.3 and int(now * 20) % 2 else 0
        cx = 16 + round((r.x - r.x * 0.85) * KX / AHEAD) + shake
        self._car_sprite(f, cx, 30 - bob, 11, r.col, 32, False)
        if r.nitro_t > 0:
            c = (255, 140, 20) if int(now * 12) % 2 else (255, 230, 90)
            f.set(cx - 3, 31, c)
            f.set(cx + 2, 31, c)

    def _hud(self, f: Frame, now: float, cam: Racer) -> None:
        if self.settings.show_score:
            kmh = str(int(cam.v * 30))
            if len(self.active_seats) <= 2:  # with 3–4 players the row belongs to the places
                f.text(1, 1, kmh, WHITE)  # plain text: the night sky behind the HUD is already dark
            for i in range(3):
                c = (0, 220, 255) if i < cam.nitro else (20, 40, 60)
                f.rect(1 + i * 3, 7, 2, 1, c)
            seats = self.active_seats
            x = 31
            for s in reversed(seats):
                t = str(self._place(self.players[s]))
                x -= measure(t)
                f.text(x, 1, t, self.players[s].col if len(seats) > 1 else (255, 220, 60))
                x -= 2
        if self.go > 0:
            n = str(int(self.go / 0.8) + 1)
            f.text_center(14, n, (255, 220, 60), font="small")
        elif self.banner_t > 0:
            w = measure(self.banner)
            f.rect((32 - w) // 2 - 1, 13, w + 2, 7, BLACK)
            f.text_center(14, self.banner, (255, 230, 120))

    def status(self) -> dict[str, Any]:
        st = super().status()
        st["places"] = {s: self._place(self.players[s]) for s in self.active_seats}
        st["lap"] = min(self.laps, max(0, int(self.players[1].d // self.L)) + 1)
        return st
