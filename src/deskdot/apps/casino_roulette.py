"""Roulette on the panel: the betting board, then a spinning wheel whose ball slows, drops and lands in the
round's (provably fair) pocket, then the number big in its colour, the win flash and the results strip.

The wheel fills the panel: a ring of red / black / green pockets (r 10–13.6) inside a wooden ball track with a
gold rim, and a dark cone with a turning gold turret. The ball's path is solved backwards from the outcome: it is
launched at whatever angle makes its natural, exponentially slowing run end exactly in the winning pocket, so the
animation is smooth and always honest. Rules live in ``deskdot.casino.games.roulette``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pydantic import Field

from ..casino.games.roulette import DOUBLE_ZERO, EU_WHEEL, US_WHEEL, Roulette, colour
from ..casino.table import LOCK_SECONDS
from ..engine import Choice, register
from ..gfx import Frame, mix
from ._casino import (
    BLACKP,
    GOLD,
    GOLD_DIM,
    GREEN,
    INK,
    RED,
    WHITE,
    CasinoApp,
    CasinoSettings,
    View,
    win_flash,
)

# ---------------------------------------------------------------- wheel geometry (pixel centres at x + 0.5)
_ys, _xs = np.mgrid[0:32, 0:32]
_DX = _xs + 0.5 - 16.0
_DY = _ys + 0.5 - 16.0
R = np.hypot(_DX, _DY)
THETA = np.arctan2(_DX, -_DY) % (2 * math.pi)  # 0 at the top, clockwise
POCKETS = (R >= 10.0) & (R < 13.6)
TRACK = (R >= 13.6) & (R < 15.4)
RIM = (R >= 15.4) & (R < 16.4)
CONE = R < 10.0
CONE_SHADE = np.clip(0.55 + 0.45 * (R / 10.0), 0, 1)  # the cone darkens towards the hub

TRACK_RGB = np.array((70, 42, 22), np.float32)
RIM_RGB = np.array((150, 108, 20), np.float32)
CONE_RGB = np.array((34, 30, 44), np.float32)
POCKET_RGB = {"red": RED, "black": BLACKP, "green": GREEN}
NUMBER_RGB = {"red": (255, 44, 56), "black": WHITE, "green": (40, 235, 110)}

# ball and wheel motion (seconds since betting closed)
TRACK_R, POCKET_R = 14.5, 11.7
BALL_W0, BALL_TAU = 6.4, 3.3  # rad/s, s — the ball, clockwise, slowing exponentially
WHEEL_W0, WHEEL_TAU, DRIFT = 2.3, 5.5, 0.32  # the wheel, anticlockwise, plus a slow idle drift


def _ball_travel(t: float) -> float:
    return BALL_W0 * BALL_TAU * (1 - math.exp(-t / BALL_TAU))


def _wheel_travel(t: float) -> float:
    """How far the wheel has turned (anticlockwise, positive) t seconds after the croupier's spin."""
    return WHEEL_W0 * WHEEL_TAU * (1 - math.exp(-t / WHEEL_TAU)) + DRIFT * t


class RouletteSettings(CasinoSettings):
    wheel: str = Choice(
        "european",
        {"european": "European (single 0)", "american": "American (0 and 00)"},
        title="Wheel",
        description="European pays the same with one zero: 2.70 % house edge. American adds 00: 5.26 %.",
    )
    la_partage: bool = Field(
        False,
        title="La Partage",
        description="European only: even-money bets get half back when the ball lands on 0 (edge 1.35 %).",
    )


@register
class CasinoRoulette(CasinoApp):
    id = "casino_roulette"
    name = "Roulette"
    description = "Casino roulette for parties: friends bet from their phones, the panel spins the wheel."
    icon = "circle-dot"
    Game = Roulette
    Settings = RouletteSettings
    table_seconds = 3.6

    def __init__(self, ctx: Any, settings: Any) -> None:
        super().__init__(ctx, settings)
        self._rot = 0.0  # wheel angle (live mode integrates it so it never jumps between phases)
        self._rot_t: float | None = None

    @property
    def wheel(self) -> tuple[int, ...]:
        return US_WHEEL if self.game.rules.wheel == "american" else EU_WHEEL

    # ------------------------------------------------------------- the motion
    def wheel_angle(self, v: View, now: float) -> float:
        """Clockwise wheel rotation in radians."""
        if self.settings.view != "live":  # previews: a pure function of time
            base = -DRIFT * now
            return base - (
                _wheel_travel(v.since_lock) - DRIFT * v.since_lock if v.since_lock is not None else 0.0
            )
        dt = 0.0 if self._rot_t is None else max(0.0, min(0.3, now - self._rot_t))
        self._rot_t = now
        w = DRIFT
        if v.since_lock is not None:
            w += WHEEL_W0 * math.exp(-v.since_lock / WHEEL_TAU)
        self._rot -= w * dt
        return self._rot

    def ball(self, v: View, rot: float) -> tuple[float, float] | None:
        """(angle, radius) of the ball on screen, or None before it is launched."""
        if v.since_lock is None or v.outcome is None:
            return None
        n = len(self.wheel)
        t = v.since_lock
        total = LOCK_SECONDS + self.Game.spin_seconds
        t_settle = total - 1.0
        t_drop = t_settle - 1.3
        target = int(v.outcome["pocket"]) * 2 * math.pi / n  # the pocket's angle on the wheel
        # launch angle (in the wheel's frame) chosen so the natural run ends exactly on the pocket
        psi0 = target - _ball_travel(t_settle) - _wheel_travel(t_settle)
        if t >= t_settle:
            u = t - t_settle
            wobble = 0.09 * math.sin(u * 19) * math.exp(-u * 4.5)
            return rot + target + wobble, POCKET_R
        psi = psi0 + _ball_travel(t) + _wheel_travel(t)
        r = TRACK_R
        if t > t_drop:
            u = (t - t_drop) / (t_settle - t_drop)
            ease = u * u * (3 - 2 * u)
            r = TRACK_R - (TRACK_R - POCKET_R) * ease + 1.6 * abs(math.sin(u * 2.6 * math.pi)) * (1 - u) ** 2
        return rot + psi, r

    # --------------------------------------------------------------- drawing
    def draw_wheel(
        self, f: Frame, rot: float, glow: float = 0.0, hit: int | None = None, now: float = 0
    ) -> None:
        n = len(self.wheel)
        lut = np.array([POCKET_RGB[colour(num)] for num in self.wheel], np.float32)
        if hit is not None and int(now * 5) % 2 == 0:
            lut[hit] = mix(lut[hit].astype(int).tolist(), GOLD, 0.75)
        idx = np.floor((THETA - rot) / (2 * math.pi) * n + 0.5).astype(np.int64) % n
        px = np.zeros((32, 32, 3), np.float32)
        px[POCKETS] = lut[idx[POCKETS]]
        px[TRACK] = TRACK_RGB
        px[RIM] = RIM_RGB * (1.0 + 0.7 * glow)
        px[CONE] = CONE_RGB * CONE_SHADE[CONE][:, None]
        f.blit(np.clip(px, 0, 255).astype(np.uint8), 0, 0)

    def draw_turret(self, f: Frame, rot: float) -> None:
        """The gold turret on the cone: four spokes turning with the wheel."""
        for k in range(4):
            a = rot + k * math.pi / 2
            for d in (2, 3, 4, 5):
                f.set(round(16 + d * math.sin(a) - 0.5), round(16 - d * math.cos(a) - 0.5), GOLD_DIM)
        f.rect(15, 15, 2, 2, GOLD)

    def draw_ball(self, f: Frame, a: float, r: float) -> None:
        x = 16 + r * math.sin(a)
        y = 16 - r * math.cos(a)
        f.rect(round(x - 1), round(y - 1), 2, 2, (255, 255, 255))

    def draw_table(self, f: Frame, v: View, now: float) -> None:
        rot = self.wheel_angle(v, now)
        f.clear(INK)
        settled = v.phase == "result"
        hit = int(v.outcome["pocket"]) if settled and v.outcome else None
        glow = (0.5 + 0.5 * math.sin(now * 9)) if settled and v.winners else 0.0
        self.draw_wheel(f, rot, glow, hit, now)
        b = self.ball(v, rot)
        if settled and v.outcome is not None:
            num = int(v.outcome["number"])
            lbl = "00" if num == DOUBLE_ZERO else str(num)
            pop = min(1.0, v.since / 0.35)
            col = mix(WHITE, NUMBER_RGB[colour(num)], pop)
            f.text_center(11, lbl, col, font="big")
        else:
            self.draw_turret(f, rot)
        if b is not None:
            self.draw_ball(f, *b)
        if settled and v.winners:
            win_flash(f, now, v.winners)

    def draw_betting(self, f: Frame, v: View, now: float) -> None:
        self.wheel_angle(v, now)  # keep the wheel's clock running so it doesn't jump at the next spin
        super().draw_betting(f, v, now)

    def draw_board(self, f: Frame, v: View, now: float) -> None:
        self.wheel_angle(v, now)
        super().draw_board(f, v, now)
