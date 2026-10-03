"""Big Six (the money wheel), against the house.

A vertical wheel of **54 equal segments**: 24 × "1", 15 × "2", 7 × "5", 4 × "10", 2 × "20", 1 × joker, 1 × logo.
Bet on a symbol; the wheel is spun and the leather clapper stops on one segment. Pays the number on the symbol:
1:1, 2:1, 5:1, 10:1, 20:1, and **40:1 for the joker and the logo** (the standard Las Vegas wheel).

Exact house edges (n segments of 54, paying m:1 → 1 − n·(m+1)/54):
1 → 6/54 = 11.11 %, 2 → 9/54 = 16.67 %, 5 → 12/54 = 22.22 %, 10 → 10/54 = 18.52 %, 20 → 12/54 = 22.22 %,
joker / logo → 13/54 = 24.07 %.

Outcome: ``segment = rng.randint(0, 53)``, an index into `WHEEL` (clockwise from the top of the wheel at rest).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from ..fair import Rng
from ..table import CasinoGame, Rules, Spot, register_game

#: symbol -> (spot id, label, segments on the wheel, pays to 1)
SYMBOLS: dict[str, tuple[str, str, int, int]] = {
    "1": ("s1", "1", 24, 1),
    "2": ("s2", "2", 15, 2),
    "5": ("s5", "5", 7, 5),
    "10": ("s10", "10", 4, 10),
    "20": ("s20", "20", 2, 20),
    "joker": ("joker", "Joker", 1, 40),
    "logo": ("logo", "Logo", 1, 40),
}


def _layout() -> tuple[str, ...]:
    """Spread every symbol evenly round the wheel (joker and logo opposite each other), like a real wheel: each
    segment goes to the symbol whose next 'ideal' position is closest (a deterministic largest-gap fill)."""
    n = 54
    slots: list[str | None] = [None] * n
    slots[0], slots[27] = "joker", "logo"
    for sym in ("20", "10", "5", "2"):
        k = SYMBOLS[sym][2]
        for j in range(k):
            ideal = (j + 0.5) * n / k + 1.7 * len(sym)
            i = round(ideal) % n
            for d in range(n):  # the nearest free segment
                for cand in ((i + d) % n, (i - d) % n):
                    if slots[cand] is None:
                        slots[cand] = sym
                        break
                else:
                    continue
                break
    return tuple(s or "1" for s in slots)


WHEEL: tuple[str, ...] = _layout()
assert len(WHEEL) == 54 and all(WHEEL.count(s) == v[2] for s, v in SYMBOLS.items())


class BigSixRules(Rules):
    pass


@register_game
class BigSix(CasinoGame):
    id = "bigsix"
    name = "Big Six"
    Rules = BigSixRules
    spin_seconds = 7.0

    def spots(self) -> dict[str, Spot]:
        return {
            sid: Spot(sid, label, "bigsix_" + sym, Fraction(pays + 1), (n,))
            for sym, (sid, label, n, pays) in SYMBOLS.items()
        }

    @staticmethod
    def outcome_at(segment: int) -> dict[str, Any]:
        return {"segment": segment, "symbol": WHEEL[segment]}

    def draw(self, rng: Rng) -> dict[str, Any]:
        return self.outcome_at(rng.randint(0, len(WHEEL) - 1))

    def outcomes(self) -> list[tuple[dict[str, Any], Fraction]]:
        return [(self.outcome_at(i), Fraction(1, len(WHEEL))) for i in range(len(WHEEL))]

    def returns(self, outcome: dict[str, Any]) -> dict[str, Fraction]:
        sid = SYMBOLS[str(outcome["symbol"])][0]
        return {sid: self._spots[sid].win}

    def public_state(self, now: float) -> dict[str, Any]:
        out = super().public_state(now)
        out["spots"] = self.spot_table()  # the phone prints these payouts (the server's own numbers)
        return out

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        sym = str(outcome["symbol"])
        return {"label": {"joker": "J", "logo": "L"}.get(sym, sym), "tone": "b6_" + sym}
