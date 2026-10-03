"""Baccarat (Punto Banco): two hands, Player and Banker, dealt by the standard third-card rules.

Each coup is dealt from a fresh shoe of ``decks`` decks (1–8, default 8) — a continuous-shuffle shoe, so every coup
has exactly the textbook probabilities — with `cards.DealingShoe` on the round's `Rng`. Draw order: Player 1,
Banker 1, Player 2, Banker 2, then the Player's third card, then the Banker's.

Third-card rules (no player choices):

* A two-card 8 or 9 is a *natural*: both hands stand.
* Player draws on 0–5, stands on 6–7.
* If the Player stood, the Banker draws on 0–5 and stands on 6–7.
* If the Player drew a third card worth ``v``, the Banker (two-card total ``b``) draws when
  ``b ≤ 2``; ``b = 3`` unless ``v = 8``; ``b = 4`` and ``v ∈ 2–7``; ``b = 5`` and ``v ∈ 4–7``;
  ``b = 6`` and ``v ∈ 6–7``; stands on 7.

Pays (docs/CASINO.md §7): Player 1:1; Banker 1:1 minus 5 % commission (0.95:1) — or *no commission*: a Banker win
with 6 pays 1:2 and every other Banker win 1:1; Tie 8:1 (or 9:1), and a tie pushes Player / Banker bets; Player
Pair / Banker Pair (the hand's first two cards are the same rank) 11:1. Payouts are whole credits, rounded down.

Exact house edges with 8 decks (computed by `edges()` from the exact distribution, checked in the tests):
Banker 1.06 % (no-commission 1.46 %), Player 1.24 %, Tie 14.36 % at 8:1 (4.84 % at 9:1), pairs 10.36 %.

Spot ids: ``player`` ``banker`` ``tie`` ``ppair`` ``bpair``.
"""

from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field

from ..cards import Card, DealingShoe, baccarat_total, baccarat_value, full_composition
from ..fair import Rng
from ..table import CasinoGame, Rules, Spot, register_game


class BaccaratRules(Rules):
    commission: Literal["standard", "no_commission"] = Field("standard", title="Banker commission")
    tie_pays: int = Field(8, ge=8, le=9, title="Tie pays (to 1)")
    decks: int = Field(8, ge=1, le=8, title="Decks")


def banker_draws(banker: int, third: int | None) -> bool:
    """The Banker's tableau: does a two-card Banker total draw, given the Player's third card value (or None)?"""
    if third is None:
        return banker <= 5
    if banker <= 2:
        return True
    if banker == 3:
        return third != 8
    if banker == 4:
        return 2 <= third <= 7
    if banker == 5:
        return 4 <= third <= 7
    if banker == 6:
        return third in (6, 7)
    return False


def deal_coup(draw: Any) -> dict[str, Any]:
    """Play one coup with `draw()` → `Card` (the rules leave no choices). Returns the outcome dict."""
    p = [draw()]
    b = [draw()]
    p.append(draw())
    b.append(draw())
    pt, bt = baccarat_total(p), baccarat_total(b)
    natural = pt >= 8 or bt >= 8
    if not natural:
        third: int | None = None
        if pt <= 5:
            p.append(draw())
            third = baccarat_value(p[2])
        if banker_draws(bt, third):
            b.append(draw())
    return outcome_of(p, b)


def outcome_of(p: list[Card], b: list[Card]) -> dict[str, Any]:
    pt, bt = baccarat_total(p), baccarat_total(b)
    return {
        "player": [c.code for c in p],
        "banker": [c.code for c in b],
        "p": pt,
        "b": bt,
        "winner": "player" if pt > bt else "banker" if bt > pt else "tie",
        "natural": len(p) == 2 and len(b) == 2 and (pt >= 8 or bt >= 8),
        "ppair": p[0].rank == p[1].rank,
        "bpair": b[0].rank == b[1].rank,
    }


@lru_cache(maxsize=16)
def coup_distribution(decks: int) -> dict[tuple[str, int], Fraction]:
    """The exact distribution of (winner, banker total) for a fresh shoe, by enumerating every ordered sequence
    of card *values* (0–9) with its without-replacement weight. Pair bets don't need it (see `pair_probability`)."""
    counts = [16 * decks] + [4 * decks] * 9  # value 0: tens and faces; 1–9: four ranks' worth each
    total = 52 * decks
    # every leaf is scaled to six cards so all weights share the denominator total·(total-1)…(total-5)
    tail4 = (total - 4) * (total - 5)
    tail5 = total - 5
    acc: dict[tuple[str, int], int] = {}

    def add(pt: int, bt: int, w: int) -> None:
        k = ("player" if pt > bt else "banker" if bt > pt else "tie", bt)
        acc[k] = acc.get(k, 0) + w

    c = counts
    for p1 in range(10):
        w1 = c[p1]
        c[p1] -= 1
        for b1 in range(10):
            w2 = w1 * c[b1]
            if not w2:
                continue
            c[b1] -= 1
            for p2 in range(10):
                w3 = w2 * c[p2]
                if not w3:
                    continue
                c[p2] -= 1
                for b2 in range(10):
                    w4 = w3 * c[b2]
                    if not w4:
                        continue
                    c[b2] -= 1
                    pt, bt = (p1 + p2) % 10, (b1 + b2) % 10
                    if pt >= 8 or bt >= 8:
                        add(pt, bt, w4 * tail4)
                    elif pt >= 6:  # the Player stands; the Banker draws on 0–5
                        if bt <= 5:
                            for b3 in range(10):
                                if c[b3]:
                                    add(pt, (bt + b3) % 10, w4 * c[b3] * tail5)
                        else:
                            add(pt, bt, w4 * tail4)
                    else:
                        for p3 in range(10):
                            w5 = w4 * c[p3]
                            if not w5:
                                continue
                            c[p3] -= 1
                            pt3 = (pt + p3) % 10
                            if banker_draws(bt, p3):
                                for b3 in range(10):
                                    if c[b3]:
                                        add(pt3, (bt + b3) % 10, w5 * c[b3])
                            else:
                                add(pt3, bt, w5 * tail5)
                            c[p3] += 1
                    c[b2] += 1
                c[p2] += 1
            c[b1] += 1
        c[p1] += 1
    den = 1
    for k in range(6):
        den *= total - k
    return {k: Fraction(v, den) for k, v in acc.items()}


def pair_probability(decks: int) -> Fraction:
    """P(a hand's first two cards share a rank): 13 ranks × (4n)(4n−1) / ((52n)(52n−1))."""
    n = 4 * decks
    return Fraction(13 * n * (n - 1), 52 * decks * (52 * decks - 1))


@register_game
class Baccarat(CasinoGame):
    id = "baccarat"
    name = "Baccarat"
    Rules = BaccaratRules
    reveal_phase = "dealing"
    spin_seconds = 6.4  # the longest deal (six cards); shorter coups reveal sooner (`deal_times`)

    def spots(self) -> dict[str, Spot]:
        nc = self.rules.commission == "no_commission"
        return {
            "player": Spot("player", "Player", "player", Fraction(2)),
            "banker": Spot("banker", "Banker", "banker", Fraction(2) if nc else Fraction(39, 20)),
            "tie": Spot("tie", "Tie", "tie", Fraction(int(self.rules.tie_pays) + 1)),
            "ppair": Spot("ppair", "Player pair", "pair", Fraction(12)),
            "bpair": Spot("bpair", "Banker pair", "pair", Fraction(12)),
        }

    # ---------------------------------------------------------------- outcome
    def draw(self, rng: Rng) -> dict[str, Any]:
        shoe = DealingShoe(int(self.rules.decks), full_composition(int(self.rules.decks)))
        shoe.begin(rng)
        return deal_coup(shoe.draw)

    def returns(self, outcome: dict[str, Any]) -> dict[str, Fraction]:
        out: dict[str, Fraction] = {}
        w = outcome["winner"]
        if w == "tie":
            out["tie"] = self._spots["tie"].win
            out["player"] = out["banker"] = Fraction(1)  # a tie pushes Player and Banker
        elif w == "player":
            out["player"] = Fraction(2)
        else:
            nc = self.rules.commission == "no_commission"
            out["banker"] = (
                (Fraction(3, 2) if int(outcome["b"]) == 6 else Fraction(2)) if nc else Fraction(39, 20)
            )
        if outcome.get("ppair"):
            out["ppair"] = Fraction(12)
        if outcome.get("bpair"):
            out["bpair"] = Fraction(12)
        return out

    def outcomes(self) -> list[tuple[dict[str, Any], Fraction]]:
        """Exact for every bet: the (winner, banker total) distribution × the two pair events. The pairs are not
        independent of the totals in reality, but each bet's expected value depends only on its own marginal, and
        this product has exactly the right marginals."""
        main = coup_distribution(int(self.rules.decks))
        pp = pair_probability(int(self.rules.decks))
        out = []
        for (winner, bt), p in main.items():
            for a in (True, False):
                for b in (True, False):
                    q = p * (pp if a else 1 - pp) * (pp if b else 1 - pp)
                    out.append(({"winner": winner, "b": bt, "ppair": a, "bpair": b}, q))
        return out

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        w = str(outcome["winner"])
        lbl = {"player": "P", "banker": "B", "tie": "T"}[w] + str(
            outcome["p"] if w == "player" else outcome["b"]
        )
        return {"label": lbl, "tone": w}

    @staticmethod
    def deal_times(outcome: dict[str, Any]) -> list[tuple[str, int, float]]:
        """When each card lands, seconds after the reveal phase starts: [(side, index, t)] in deal order."""
        out: list[tuple[str, int, float]] = [
            ("player", 0, 0.3),
            ("banker", 0, 0.9),
            ("player", 1, 1.5),
            ("banker", 1, 2.1),
        ]
        t = 2.1
        if len(outcome["player"]) == 3:
            t += 1.6
            out.append(("player", 2, t))
        if len(outcome["banker"]) == 3:
            t += 1.6
            out.append(("banker", 2, t))
        return out

    def on_locked(self, rng: Rng, now: float) -> None:
        from ..table import LOCK_SECONDS

        self.outcome = self.draw(rng)
        last = self.deal_times(self.outcome)[-1][2]
        self.reveal_at = now + LOCK_SECONDS + last + 1.4

    def abort(self, now: float | None = None) -> None:
        """The table closes while the coup is dealt: its cards were fixed at the lock, so it is paid, not voided."""
        if self.phase == "dealing" and self.outcome is not None:
            self.settle()
            self.phase = "result"
        super().abort(now)

    def public_state(self, now: float) -> dict[str, Any]:
        """Adds the cards on the felt so far (``cards``) while the coup is dealt — they are face up for everyone."""
        out = super().public_state(now)
        if self.phase == "dealing" and self.outcome is not None:
            t = now - self.phase_at
            shown: dict[str, list[str]] = {"player": [], "banker": []}
            for side, i, at in self.deal_times(self.outcome):
                if t >= at:
                    shown[side].append(self.outcome[side][i])
            out["cards"] = shown
        return out
