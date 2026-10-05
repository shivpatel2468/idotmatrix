"""Andar Bahar (the Indian card game), against the house.

Rules (the common Indian casino game):

* One 52-card deck is shuffled with the round's provably fair `Rng` (Fisher–Yates of `cards.new_deck()`).
  The top card is the **joker** (game card), face up in the middle.
* Bets go on **Andar** (inside, left) or **Bahar** (outside, right) while betting is open.
* Cards are then dealt one at a time, alternately, **starting with Andar** (host option ``first``: Andar or
  Bahar), until a card of the **joker's rank** appears. The side it lands on wins. Only the rank (value) matters,
  never the suit: a 7♥ joker is matched by the first 7♠, 7♦ or 7♣ (the standard rule — three cards in the
  remaining 51 can match, which is where the probabilities below come from).
* Pays: the side that gets the first card has a small advantage, so it pays **0.9:1**; the other side pays
  **1:1** (with the first card to Andar: Andar 0.9:1, Bahar 1:1 — the standard table).
* Optional side bet on **how many cards are dealt** (joker excluded, the matching card included: 1–49), in
  bands, each paying its fair odds minus a house edge (see `BANDS`).

Exact probabilities (3 matching cards among the 51 left; the first match is at position k with probability
C(51−k, 2) / C(51, 3)): the first side wins with odd k: **P = 429/833 = 51.50 %**, the other side 404/833.
House edge: first side at 0.9:1 → 1 − 1.9·429/833 = **179/8330 = 2.149 %**; other side at 1:1 →
1 − 2·404/833 = **25/833 = 3.001 %**. (At even money the first side would give the player a 3.0 % edge; that is
why it pays 0.9:1.) The side-bet payouts are fair odds less ≈ 5 %, rounded *down* to a printable step (0.1 below
10:1, 0.5 below 50:1, else 1); each band's exact edge is computed by `outcomes()` and shown in the studio.

Host option ``match``: **value** (the standard rule above) or **exact card** — then only the identical card (same
rank *and* suit) wins. One deck holds just one such card (the joker itself), so the exact-card game turns the joker
from one shuffled deck and deals from a second, fresh shuffled deck (both from the round's `Rng`, in that order):
the twin is equally likely at each of the 52 positions, so each side wins exactly 1/2 and both pay **0.95:1**
(house edge 2.5 %); the count bands run to 52 (one per 52 for every count), paying fair odds less ≈ 5 %. Games run
longer (26.5 cards on average instead of ≈ 12).

Outcome: ``{"joker": "7H", "cards": [...], "first": "andar", "winner": "andar"|"bahar", "count": n}``; the
i-th dealt card (0-based) goes to the first side when i is even.
"""

from __future__ import annotations

from fractions import Fraction
from math import comb
from typing import Any, Literal

from pydantic import Field

from ..cards import Card
from ..fair import Rng
from ..table import LOCK_SECONDS, CasinoGame, Rules, Spot, register_game
from ._pvp import shuffled_deck

SIDES = ("andar", "bahar")
SIDE_EDGE = Fraction(5, 100)  # the target edge of the count side bets (each band's exact edge is computed)


def p_count(k: int, exact: bool = False) -> Fraction:
    """P(the first card matching the joker is the k-th card dealt): k = 1..49 by value, 1..52 for the exact card."""
    if exact:
        return Fraction(1, 52) if 1 <= k <= 52 else Fraction(0)
    return Fraction(comb(51 - k, 2), comb(51, 3))


def _payout(p: Fraction) -> Fraction:
    """Fair odds minus SIDE_EDGE, rounded down to a printable step: the "to 1" payout of a band."""
    raw = (1 - SIDE_EDGE) / p - 1
    step = Fraction(1, 10) if raw < 10 else Fraction(1, 2) if raw < 50 else Fraction(1)
    return (raw // step) * step


_BAND_RANGES = ((1, 5), (6, 10), (11, 15), (16, 25), (26, 30), (31, 35), (36, 40), (41, 49))
_BAND_RANGES_EXACT = ((1, 5), (6, 10), (11, 15), (16, 25), (26, 30), (31, 35), (36, 40), (41, 52))
Band = tuple[str, int, int, Fraction, Fraction]


def _bands(exact: bool) -> tuple[Band, ...]:
    return tuple(
        (f"c:{a}-{b}", a, b, p, _payout(p))
        for a, b in (_BAND_RANGES_EXACT if exact else _BAND_RANGES)
        for p in [sum((p_count(k, exact) for k in range(a, b + 1)), Fraction(0))]
    )


#: count side bets: (spot id, first, last, probability, payout to 1) — by value, and for the exact-card game
BANDS: tuple[Band, ...] = _bands(False)
BANDS_EXACT: tuple[Band, ...] = _bands(True)
P_FIRST = sum((p_count(k) for k in range(1, 50, 2)), Fraction(0))  # 429/833


def deal_pace(count: int) -> float:
    """Seconds between two dealt cards: slow and suspenseful for short games, brisk for long ones."""
    return max(0.18, min(0.6, 9.0 / max(1, count)))


DEAL_LEAD = 0.9  # the joker is turned over first
DEAL_TAIL = 1.0  # the winning card glows before the result


def deal_seconds(count: int) -> float:
    return DEAL_LEAD + count * deal_pace(count) + DEAL_TAIL


class AndarBaharRules(Rules):
    first: Literal["andar", "bahar"] = Field("andar", title="First card goes to")
    side_bets: bool = Field(True, title="Card-count side bets")
    match: Literal["value", "card"] = Field(
        "value",
        title="Winning card",
        description="Value (standard): any card of the joker's rank wins, suit doesn't matter. Exact card: only the "
        "identical card (same rank and suit), dealt from a second deck — both sides pay 0.95:1.",
    )


@register_game
class AndarBahar(CasinoGame):
    id = "andarbahar"
    name = "Andar Bahar"
    Rules = AndarBaharRules
    spin_seconds = deal_seconds(52)
    reveal_phase = "dealing"

    @property
    def exact(self) -> bool:
        return self.rules.match == "card"

    @property
    def bands(self) -> tuple[Band, ...]:
        return BANDS_EXACT if self.exact else BANDS

    def spots(self) -> dict[str, Spot]:
        first = self.rules.first
        if self.exact:  # each side wins exactly 1/2: both pay 0.95:1
            out = {s: Spot(s, s.title(), s, Fraction(195, 100)) for s in SIDES}
        else:
            out = {s: Spot(s, s.title(), s, Fraction(19, 10) if s == first else Fraction(2)) for s in SIDES}
        if self.rules.side_bets:
            for sid, a, b, _p, pay in self.bands:
                out[sid] = Spot(sid, f"{a}-{b} cards", "count", pay + 1, tuple(range(a, b + 1)))
        return out

    # ---------------------------------------------------------------- outcome
    def draw(self, rng: Rng) -> dict[str, Any]:
        deck = shuffled_deck(rng)
        joker, rest = deck[0], deck[1:]
        exact = self.exact
        if exact:
            rest = shuffled_deck(rng)  # a second deck: it holds the joker's one identical twin
        dealt: list[Card] = []
        for c in rest:
            dealt.append(c)
            if (c.code == joker.code) if exact else (c.rank == joker.rank):
                break
        n = len(dealt)
        first = str(self.rules.first)
        other = "bahar" if first == "andar" else "andar"
        return {
            "joker": joker.code,
            "cards": [c.code for c in dealt],
            "first": first,
            "winner": first if n % 2 == 1 else other,
            "count": n,
            "match": "card" if exact else "value",
        }

    def on_locked(self, rng: Rng, now: float) -> None:
        self.outcome = self.draw(rng)
        self.reveal_at = now + LOCK_SECONDS + deal_seconds(int(self.outcome["count"]))

    def outcomes(self) -> list[tuple[dict[str, Any], Fraction]]:
        first = str(self.rules.first)
        other = "bahar" if first == "andar" else "andar"
        last = 52 if self.exact else 49
        return [
            ({"winner": first if k % 2 else other, "count": k}, p_count(k, self.exact))
            for k in range(1, last + 1)
        ]

    def returns(self, outcome: dict[str, Any]) -> dict[str, Fraction]:
        w = str(outcome["winner"])
        out = {w: self._spots[w].win}
        k = int(outcome["count"])
        for sid, a, b, _p, _pay in self.bands:
            if a <= k <= b and sid in self._spots:
                out[sid] = self._spots[sid].win
        return out

    def dealt(self, now: float) -> int:
        """How many cards the panel has dealt so far (the same clock as the panel app's animation)."""
        if self.outcome is None or self.phase != "dealing":
            return 0
        n = int(self.outcome["count"])
        t = now - self.phase_at
        return 0 if t < DEAL_LEAD else min(n, 1 + int((t - DEAL_LEAD) / deal_pace(n)))

    def public_state(self, now: float) -> dict[str, Any]:
        out = super().public_state(now)
        out["spots"] = self.spot_table()  # the phone prints these payouts (the server's own numbers)
        if self.phase == "dealing" and self.outcome is not None:
            # the deal as the panel shows it: the joker (face up from the start) and the cards dealt so far, so
            # phones can follow along and light up the card that matches the joker's rank (any suit)
            o, k = self.outcome, self.dealt(now)
            out["deal"] = {
                "joker": o["joker"],
                "first": o["first"],
                "cards": list(o["cards"])[:k],
                "matched": k >= int(o["count"]),
                "match": o.get("match", "value"),
            }
        return out

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        w = str(outcome["winner"])
        return {"label": "A" if w == "andar" else "B", "tone": w, "count": outcome.get("count")}
