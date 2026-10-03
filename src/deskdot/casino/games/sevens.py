"""7 Up 7 Down: two dice, bet on the sum being under 7, exactly 7, or over 7.

Payouts: under 7 (2–6) 1:1, over 7 (8–12) 1:1, exactly 7 4:1 (default) or 5:1. Each die is
``rng.randint(1, 6)``, first die first.

House edge: under / over 1 − 2·15/36 = 16.67 %; seven at 4:1 1 − 5·6/36 = 16.67 %, at 5:1 exactly 0 % (a fair bet).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from pydantic import Field

from ..fair import Rng
from ..table import CasinoGame, Rules, Spot, register_game

ZONES = ("down", "seven", "up")


def zone(total: int) -> str:
    return "down" if total < 7 else "seven" if total == 7 else "up"


class SevensRules(Rules):
    seven_pays: int = Field(4, ge=4, le=5, title="Lucky 7 pays (to 1)")


@register_game
class Sevens(CasinoGame):
    id = "sevens"
    name = "7 Up 7 Down"
    Rules = SevensRules
    spin_seconds = 2.6

    def spots(self) -> dict[str, Spot]:
        return {
            "down": Spot("down", "Under 7", "down", Fraction(2), (2, 3, 4, 5, 6)),
            "seven": Spot("seven", "Lucky 7", "seven", Fraction(int(self.rules.seven_pays) + 1), (7,)),
            "up": Spot("up", "Over 7", "up", Fraction(2), (8, 9, 10, 11, 12)),
        }

    @staticmethod
    def outcome_of(d1: int, d2: int) -> dict[str, Any]:
        s = d1 + d2
        return {"dice": [d1, d2], "sum": s, "zone": zone(s)}

    def draw(self, rng: Rng) -> dict[str, Any]:
        d1 = rng.randint(1, 6)
        d2 = rng.randint(1, 6)
        return self.outcome_of(d1, d2)

    def outcomes(self) -> list[tuple[dict[str, Any], Fraction]]:
        return [(self.outcome_of(a, b), Fraction(1, 36)) for a in range(1, 7) for b in range(1, 7)]

    def returns(self, outcome: dict[str, Any]) -> dict[str, Fraction]:
        z = str(outcome["zone"])
        return {z: self._spots[z].win}

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        return {"label": str(outcome["sum"]), "tone": outcome["zone"]}
