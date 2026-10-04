"""Andar Bahar on the panel: the betting board, then the joker turned face up in the middle (A on the left, B on
the right), cards flying alternately onto the Andar pile (left) and the Bahar pile (right) with their running
counts, until the matching card lands — it glows gold, its side pulses, and the winners' bulbs chase round the
edge. Rules and exact odds: ``deskdot.casino.games.andarbahar``.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..casino.games.andarbahar import DEAL_LEAD, AndarBahar, deal_pace
from ..casino.table import LOCK_SECONDS
from ..engine import Choice, register
from ..gfx import Frame, mix, scale
from . import _cardart as cards
from ._casino import INK, MUTE, WHITE, CasinoApp, CasinoSettings, View, win_flash

ANDAR = (40, 140, 255)
BAHAR = (255, 50, 110)
SIDE_RGB = {"andar": ANDAR, "bahar": BAHAR}
JOKER_X, JOKER_Y = 12, 1
PILE = {"andar": (3, 13), "bahar": (22, 13)}
FLY = 0.25  # seconds a card takes from the shoe to its pile


class AndarBaharSettings(CasinoSettings):
    first: str = Choice(
        "andar",
        {"andar": "Andar (the standard table)", "bahar": "Bahar"},
        title="First card goes to",
        description="The side that gets the first card wins 51.5 % of games, so it pays 0.9:1 (edge 2.15 %); "
        "the other side pays 1:1 (edge 3.00 %).",
    )
    side_bets: bool = Field(
        True, title="Card-count side bets", description="Bet on how many cards are dealt (1-5, 6-10 … 41-49)."
    )


def pile(f: Frame, x: int, y: int, top: str | None, n: int, col: tuple[int, int, int], hi: bool = False,
         dim: float = 1.0) -> None:  # fmt: skip
    """A pile of `n` cards: a few card edges stacked under the top card, its count underneath in the side's
    colour."""
    depth = min(3, max(0, n - 1))
    for d in range(1, depth + 1):  # the cards underneath show as edges below the top card
        f.rect(
            x + 1, y + cards.CARD_H - 1 + d, cards.CARD_W - 2, 1, scale((110, 110, 130), (1 - 0.25 * d) * dim)
        )
    if top is None:
        f.rect(x + 1, y, 5, 10, scale(col, 0.25))
        f.rect(x, y + 1, 7, 8, scale(col, 0.25))
        f.rect(x + 1, y + 1, 5, 8, (0, 0, 0))
    else:
        cards.card(f, x, y, top, hi=hi, dim=dim)


@register
class CasinoAndarBahar(CasinoApp):
    id = "casino_andarbahar"
    name = "Andar Bahar"
    description = "The Indian card game: the joker is turned, bet Andar or Bahar, watch the cards fall."
    icon = "spade"
    Game = AndarBahar
    Settings = AndarBaharSettings
    table_seconds = 3.4

    def dealt_at(self, v: View) -> tuple[float, int]:
        """(seconds since the deal began, cards dealt so far)."""
        assert v.outcome is not None
        n = int(v.outcome["count"])
        if v.phase == "result" or v.since_lock is None:
            return 99.0, n
        t = v.since_lock - LOCK_SECONDS
        pace = deal_pace(n)
        k = 0 if t < DEAL_LEAD else min(n, 1 + int((t - DEAL_LEAD) / pace))
        return t, k

    def draw_table(self, f: Frame, v: View, now: float) -> None:
        f.clear(INK)
        if v.outcome is None:
            return
        o = v.outcome
        t, k = self.dealt_at(v)
        first = str(o["first"])
        other = "bahar" if first == "andar" else "andar"
        dealt: list[str] = list(o["cards"])[:k]
        piles: dict[str, list[str]] = {first: dealt[0::2], other: dealt[1::2]}
        done = k >= int(o["count"]) and (v.phase == "result" or t >= DEAL_LEAD + k * deal_pace(k) + FLY)
        winner = str(o["winner"])
        # the joker: turned over at the start of the deal
        flip = min(1.0, max(0.0, t / 0.5))
        if flip < 0.5:
            cards.back(f, JOKER_X, JOKER_Y)
        else:
            cards.card(f, JOKER_X, JOKER_Y, str(o["joker"]))
        pulse = 0.5 + 0.5 * math.sin(now * 7)
        for side, letter, lx in (("andar", "A", 3), ("bahar", "B", 24)):
            col = SIDE_RGB[side]
            on = done and side == winner
            c = mix(col, WHITE, 0.45 * pulse) if on else (scale(col, 0.45) if done else col)
            f.text(lx, 3, letter, c, font="small")
        # piles (the card in flight isn't on its pile yet)
        flying: tuple[str, str, float] | None = None
        if k and not done and v.phase != "result":
            u = (t - DEAL_LEAD - (k - 1) * deal_pace(int(o["count"]))) / FLY
            if u < 1:
                side = first if (k - 1) % 2 == 0 else other
                flying = (side, dealt[-1], max(0.0, u))
                piles[side] = piles[side][:-1]
        for side in ("andar", "bahar"):
            x, y = PILE[side]
            ps = piles[side]
            top = ps[-1] if ps else None
            win_card = done and side == winner
            dim = 0.55 if done and side != winner else 1.0
            pile(f, x, y, top, len(ps), SIDE_RGB[side], hi=win_card, dim=dim)
            cnt = str(len(ps))
            cx = x + 3 - (len(cnt) * 4 - 1) // 2
            f.text(cx, 26, cnt, SIDE_RGB[side] if dim == 1.0 else scale(SIDE_RGB[side], 0.5))
        if flying is not None:
            side, code, u = flying
            tx, ty = PILE[side]
            e = 1 - (1 - u) ** 2
            x = round(JOKER_X + (tx - JOKER_X) * e)
            y = round(JOKER_Y + 10 + (ty - JOKER_Y - 10) * e)
            cards.card(f, x, y, code)
        # the total dealt, between the piles
        f.text_center(26, str(k) if k else "", MUTE)
        if done and v.winners:
            win_flash(f, now, v.winners, self.th)

    def hero_result(self, f: Frame, v: View, now: float) -> None:
        if v.outcome is None:
            return
        w = str(v.outcome["winner"])
        col = SIDE_RGB[w]
        f.rect(1, 2, 30, 13, col)
        f.rect(2, 15, 29, 1, scale(col, 0.45))
        f.text_center(5, w.upper(), WHITE, font="small")

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        tone = str(summary.get("tone"))
        return str(summary.get("label", "?")), scale(SIDE_RGB.get(tone, MUTE), 0.85)
