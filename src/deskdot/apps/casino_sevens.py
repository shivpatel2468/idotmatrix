"""7 Up 7 Down on the panel: the betting board, two big red dice tumbling in and bouncing to rest on the round's
(provably fair) faces, then the sum in its zone colour with the ▼ / 7 / ▲ zones lit, and the results strip.

Rules live in ``deskdot.casino.games.sevens``.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..casino.games.sevens import Sevens
from ..casino.table import LOCK_SECONDS
from ..engine import register
from ..gfx import Frame, mix, scale
from ._casino import INK, TONES, WHITE, CasinoApp, CasinoSettings, View, cosmetic, win_flash

DIE = 12
BODY = (205, 18, 32)
LIGHT = (255, 90, 96)
SHADE = (120, 8, 18)
PIP = (250, 250, 250)
# pip cells (col, row) in a 3×3 grid per face
FACES: dict[int, tuple[tuple[int, int], ...]] = {
    1: ((1, 1),),
    2: ((0, 0), (2, 2)),
    3: ((0, 0), (1, 1), (2, 2)),
    4: ((0, 0), (2, 0), (0, 2), (2, 2)),
    5: ((0, 0), (2, 0), (1, 1), (0, 2), (2, 2)),
    6: ((0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)),
}
ZONE_RGB = {"down": TONES["down"], "seven": TONES["seven"], "up": TONES["up"]}
REST = ((3, 1), (17, 1))  # where the two dice sit for the result (x, y)
ROLL_Y = 10  # they tumble and land in the middle of the panel, then slide up to make room for the sum
SLIDE = 0.3


class SevensSettings(CasinoSettings):
    seven_pays: int = Field(
        4,
        ge=4,
        le=5,
        title="Lucky 7 pays (to 1)",
        description="4:1 is the classic table (16.7 % edge on every bet); 5:1 makes the 7 a fair bet.",
    )


def draw_die(f: Frame, x: int, y: int, face: int, h: int = DIE) -> None:
    """A red casino die with white pips; `h` < 12 squashes it (it is hitting the felt)."""
    w = DIE
    f.rect(x + 1, y, w - 2, h, BODY)
    f.rect(x, y + 1, w, h - 2, BODY)
    f.rect(x + 1, y, w - 2, 1, LIGHT)  # top highlight
    f.rect(x, y + 1, 1, h - 2, scale(LIGHT, 0.8))
    f.rect(x + 1, y + h - 1, w - 2, 1, SHADE)  # bottom / right shade
    f.rect(x + w - 1, y + 1, 1, h - 2, SHADE)
    for cx, cy in FACES.get(face, FACES[1]):
        py = y + 2 + round(cy * (h - 6) / 2)
        f.rect(x + 2 + 3 * cx, py, 2, 2, PIP)


def arrow(f: Frame, cx: int, y: int, up: bool, col: tuple[int, int, int]) -> None:
    """A 5×3 triangle pointing up or down."""
    rows = (1, 3, 5) if up else (5, 3, 1)
    for i, w in enumerate(rows):
        f.rect(cx - w // 2, y + i, w, 1, col)


@register
class CasinoSevens(CasinoApp):
    id = "casino_sevens"
    name = "7 Up 7 Down"
    description = "The dice party game: bet under 7, over 7 or lucky 7 from your phone; the panel rolls."
    icon = "dices"
    Game = Sevens
    Settings = SevensSettings
    table_seconds = 3.6
    tv_reveal = True

    def tv_reveal_extra(self, outcome: dict[str, Any], nonce: int) -> dict[str, Any]:
        """The faces each die shows while it tumbles (`dice_at`: flip 0…18), so a TV rolls the same dice."""
        return {"faces": [[1 + int(cosmetic(nonce, i, k) * 6) for k in range(19)] for i in range(2)]}

    def dice_at(self, v: View) -> list[tuple[int, int, int, int]]:
        """[(x, y, face, height)] for both dice at this moment of the roll."""
        assert v.outcome is not None
        final = list(v.outcome["dice"])
        if v.phase == "result" or v.since_lock is None:
            k = min(1.0, v.since / SLIDE) if v.phase == "result" else 1.0
            y = round(ROLL_Y + (REST[0][1] - ROLL_Y) * (1 - (1 - k) ** 2))
            return [(REST[i][0], y, final[i], DIE) for i in range(2)]
        span = self.Game.spin_seconds
        u = max(0.0, min(1.0, (v.since_lock - LOCK_SECONDS) / span))
        out = []
        for i in range(2):
            lag = 0.06 * i
            k = max(0.0, min(1.0, (u - lag) / (1 - lag)))
            # thrown in from the right, bouncing lower each time, settling at k = 1
            hop = 9 * math.exp(-2.6 * k) * abs(math.cos(math.pi * 2.5 * k))
            ease = 1 - (1 - k) ** 3
            x = REST[i][0] + round((26 - 6 * i) * (1 - ease))
            y = ROLL_Y - round(hop)
            squash = DIE - 2 if hop < 0.8 and k < 0.92 and k > 0.05 else DIE
            if k >= 0.86:
                face = final[i]
            else:  # tumbling: the face flips, slower as the die loses energy
                flips = int(18 * (1 - (1 - k) ** 2))
                face = 1 + int(cosmetic(v.nonce, i, flips) * 6)
            out.append((x, y + (DIE - squash), face, squash))
        return out

    def draw_table(self, f: Frame, v: View, now: float) -> None:
        f.clear(INK)
        if v.outcome is None:
            return
        for x, y, face, h in self.dice_at(v):
            draw_die(f, x, y, face, h)
        if v.phase != "result" or v.since < SLIDE:
            return
        total = int(v.outcome["sum"])
        zone = str(v.outcome["zone"])
        col = ZONE_RGB[zone]
        pop = min(1.0, (v.since - SLIDE) / 0.3)
        f.text_center(14, str(total), mix(WHITE, mix(col, WHITE, 0.25), pop), font="big")
        self.zones(f, 25, zone, now)
        if v.winners:
            win_flash(f, now, v.winners, self.th)

    def zones(self, f: Frame, y: int, lit: str | None, now: float) -> None:
        """▼ 7 ▲ — the three betting zones, the winner lit in its colour."""
        for i, z in enumerate(("down", "seven", "up")):
            x = 1 + 10 * i
            on = z == lit
            c = ZONE_RGB[z]
            bg = c if on else scale(c, 0.22)
            f.rect(x, y, 9, 7, bg)
            fg = WHITE if on else scale(c, 0.85)
            if z == "seven":
                f.text(x + 3, y + 1, "7", fg)
            else:
                arrow(f, x + 4, y + 2, z == "up", fg)

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        lbl, _bg = super().tile(summary)
        return lbl, ZONE_RGB.get(str(summary.get("tone")), TONES["white"])
