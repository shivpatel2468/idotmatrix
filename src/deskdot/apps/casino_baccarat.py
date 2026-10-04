"""Baccarat on the panel: the betting board, then the coup dealt card by card — Player on the left in blue, Banker on
the right in red, each with its running total in big digits and a third card laid sideways under the pair, as at a
real table — then the winning side flashes (pairs light their cards gold), and the results board with the bead
strip. Rules live in ``deskdot.casino.games.baccarat``.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..casino.cards import Card, baccarat_total
from ..casino.games.baccarat import Baccarat
from ..casino.table import LOCK_SECONDS
from ..engine import Choice, register
from ..gfx import Frame, mix, scale
from . import _cardart as art
from ._casino import INK, WHITE, CasinoApp, CasinoSettings, View, win_flash

SIDE = {
    "player": (40, 110, 255),
    "banker": (235, 30, 50),
    "tie": (20, 185, 85),
}
SLIDE = 0.28  # a card slides down into place


class BaccaratSettings(CasinoSettings):
    commission: str = Choice(
        "standard",
        {
            "standard": "Banker pays 0.95:1 (5 % commission)",
            "no_commission": "No commission (Banker 6 pays 1:2)",
        },
        title="Banker commission",
        description="Standard: Banker edge 1.06 %. No commission: a Banker win with 6 pays half (edge 1.46 %).",
    )
    tie_pays: int = Field(
        8, ge=8, le=9, title="Tie pays (to 1)", description="8:1 = 14.4 % house edge; 9:1 = 4.8 %."
    )
    decks: int = Field(
        8, ge=1, le=8, title="Decks", description="A fresh shoe of this many decks every coup."
    )


def sideways(f: Frame, x: int, y: int, code: str, hi: bool = False) -> None:
    """A card turned sideways (10×7) — how a real baccarat table lays the third card."""
    face = art.FACE_HI if hi else art.FACE
    f.rect(x + 1, y, 8, 7, face)
    f.rect(x, y + 1, 10, 5, face)
    col = art.ink(code)
    art.draw_rank(f, x, y + 1, code, col)
    art._stamp(f, x + 6, y + 2, art.PIP3[code[-1]], col)


@register
class CasinoBaccarat(CasinoApp):
    id = "casino_baccarat"
    name = "Baccarat"
    description = (
        "Punto Banco for parties: bet Player, Banker or Tie from your phone; the panel deals the coup."
    )
    icon = "spade"
    Game = Baccarat
    Settings = BaccaratSettings
    table_seconds = 4.2

    def draw_table(self, f: Frame, v: View, now: float) -> None:
        f.clear(INK)
        o = v.outcome
        if o is None:
            return
        t = 99.0 if v.phase == "result" else (v.since_lock or 0.0) - LOCK_SECONDS
        shown: dict[str, list[tuple[str, float]]] = {"player": [], "banker": []}
        for side, i, at in Baccarat.deal_times(o):
            if t >= at:
                shown[side].append((o[side][i], t - at))
        done = v.phase == "result"
        winner = str(o["winner"]) if done else ""
        pulse = 0.5 + 0.5 * math.sin(now * 7)
        for k, side in enumerate(("player", "banker")):
            x0 = 16 * k
            col = SIDE[side]
            cards = shown[side]
            # big running total (once both first cards are down) in the side's colour
            if len(cards) >= 2:
                total = baccarat_total(Card.parse(c) for c, _ in cards)
                tc = mix(col, WHITE, 0.35) if winner in (side, "tie") or not done else scale(col, 0.45)
                f.text(x0 + 5, 1, str(total), tc, font="big")
            f.text(x0 + 1 if k == 0 else x0 + 12, 1, "P" if k == 0 else "B", scale(col, 0.9))
            pair = done and bool(o["ppair" if k == 0 else "bpair"])
            for i, (code, age) in enumerate(cards[:2]):
                dy = round(-8 * max(0.0, 1 - age / SLIDE) ** 2)
                lit = not done or winner in (side, "tie")
                art.card(f, x0 + 8 * i, 12 + dy, code, hi=pair, dim=1.0 if lit else 0.7)
            if len(cards) == 3:
                code, age = cards[2]
                dx = round((10 if k == 0 else -10) * max(0.0, 1 - age / (SLIDE * 1.4)) ** 2)
                sideways(f, x0 + 2 + dx, 23, code)
            if done and winner == side:
                f.rect(x0 + 1, 31, 14, 1, mix(col, self.th.accent, pulse * 0.5))
        if done and winner == "tie":
            f.rect(1, 31, 30, 1, mix(SIDE["tie"], WHITE, pulse * 0.4))
            if not any(len(shown[s]) == 3 for s in shown):  # the third-card row is free: say it
                f.text_center(25, "TIE", SIDE["tie"])
        if done and v.winners:
            win_flash(f, now, v.winners, self.th)

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        tone = str(summary.get("tone"))
        return str(summary.get("label", "?")), scale(SIDE.get(tone, (90, 90, 104)), 0.85)

    def hero_result(self, f: Frame, v: View, now: float) -> None:
        o = v.outcome
        if o is None:
            return
        w = str(o["winner"])
        col = SIDE[w]
        f.rect(2, 2, 28, 15, scale(col, 0.85))
        f.rect(3, 17, 27, 1, scale(col, 0.4))
        f.text_center(3, {"player": "PLAYER", "banker": "BANKER", "tie": "TIE"}[w], WHITE)
        # the two totals, winner first
        a, b = (o["p"], o["b"]) if w != "banker" else (o["b"], o["p"])
        f.text(8, 9, str(a), WHITE, font="small")
        f.text_center(10, "-", WHITE)
        f.text(20, 9, str(b), scale(WHITE, 0.7), font="small")
