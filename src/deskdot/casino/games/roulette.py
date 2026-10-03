"""Roulette: European single zero (default) or American 0/00, every standard inside and outside bet.

Payouts (docs/CASINO.md §7): straight 35:1, split 17:1, street 11:1 (also the 0-1-2 / 0-2-3 / 0-00-2 / 00-2-3
trios), corner 8:1, six line 5:1, first four 0-1-2-3 8:1 (European), top line 0-00-1-2-3 6:1 (American), dozen and
column 2:1, red/black, odd/even, low/high 1:1. La Partage (European only): an even-money bet gets half its stake
back when the ball lands on 0.

House edge: every European bet 1/37 = 2.70 % (even money with La Partage 1/74 = 1.35 %); every American bet 2/38
= 5.26 %, except the top line 3/38 = 7.89 %.

Outcome: ``pocket = rng.randint(0, N - 1)``, an index into the wheel's pocket order (`EU_WHEEL` / `US_WHEEL`);
the number is ``wheel[pocket]`` (37 stands for 00).

Spot ids (what phones send): ``n:17`` ``n:0`` ``n:00`` · ``s:8-11`` (split, smaller number first; ``s:0-00``,
``s:00-2``) · ``st:13`` (street from its first number) · ``tr:0-1-2`` (trios) · ``c:8`` (corner from its
top-left number: 8, 9, 11, 12) · ``sl:13`` (six line 13–18) · ``ff`` (first four) · ``tl`` (top line) ·
``dz:1..3`` · ``col:1..3`` (column 1 = 1, 4 … 34) · ``red`` ``black`` ``odd`` ``even`` ``low`` ``high``.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Literal

from pydantic import Field

from ..fair import Rng
from ..table import CasinoGame, Rules, Spot, register_game

DOUBLE_ZERO = 37  # how 00 is stored
EU_WHEEL = (0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14,
            31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26)  # fmt: skip
US_WHEEL = (0, 28, 9, 26, 30, 11, 7, 20, 32, 17, 5, 22, 34, 15, 3, 24, 36, 13, 1, DOUBLE_ZERO, 27, 10, 25, 29,
            12, 8, 19, 31, 18, 6, 21, 33, 16, 4, 23, 35, 14, 2)  # fmt: skip
RED = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})
EVEN_MONEY = ("red", "black", "odd", "even", "low", "high")


def label(n: int) -> str:
    return "00" if n == DOUBLE_ZERO else str(n)


def colour(n: int) -> Literal["green", "red", "black"]:
    if n in (0, DOUBLE_ZERO):
        return "green"
    return "red" if n in RED else "black"


class RouletteRules(Rules):
    wheel: Literal["european", "american"] = Field("european", title="Wheel")
    la_partage: bool = Field(False, title="La Partage (half back on zero)")


@register_game
class Roulette(CasinoGame):
    id = "roulette"
    name = "Roulette"
    Rules = RouletteRules
    spin_seconds = 7.5

    @property
    def wheel(self) -> tuple[int, ...]:
        return US_WHEEL if self.rules.wheel == "american" else EU_WHEEL

    @property
    def american(self) -> bool:
        return bool(self.rules.wheel == "american")

    # ------------------------------------------------------------------ spots
    def spots(self) -> dict[str, Spot]:
        us = self.rules.wheel == "american"
        out: dict[str, Spot] = {}

        def add(sid: str, lbl: str, kind: str, nums: tuple[int, ...], win: Fraction | None = None) -> None:
            out[sid] = Spot(sid, lbl, kind, win if win is not None else Fraction(36, len(nums)), nums)

        zeros = (0, DOUBLE_ZERO) if us else (0,)
        for n in zeros + tuple(range(1, 37)):
            add(f"n:{label(n)}", label(n), "straight", (n,))
        # splits on the grid: across (a, a+1) inside a row, down (a, a+3)
        for a in range(1, 37):
            if a % 3:
                add(f"s:{a}-{a + 1}", f"{a}/{a + 1}", "split", (a, a + 1))
            if a <= 33:
                add(f"s:{a}-{a + 3}", f"{a}/{a + 3}", "split", (a, a + 3))
        if us:
            for a, b in ((0, DOUBLE_ZERO), (0, 1), (0, 2), (DOUBLE_ZERO, 2), (DOUBLE_ZERO, 3)):
                add(f"s:{label(a)}-{label(b)}", f"{label(a)}/{label(b)}", "split", (a, b))
            for trio in ((0, 1, 2), (0, DOUBLE_ZERO, 2), (DOUBLE_ZERO, 2, 3)):
                name = "-".join(label(n) for n in trio)
                add(f"tr:{name}", name.replace("-", "/"), "street", trio)
            add("tl", "0/00/1/2/3", "top_line", (0, DOUBLE_ZERO, 1, 2, 3), Fraction(7))
        else:
            for b in (1, 2, 3):
                add(f"s:0-{b}", f"0/{b}", "split", (0, b))
            for trio in ((0, 1, 2), (0, 2, 3)):
                name = "-".join(str(n) for n in trio)
                add(f"tr:{name}", name.replace("-", "/"), "street", trio)
            add("ff", "0/1/2/3", "first_four", (0, 1, 2, 3))
        for a in range(1, 35, 3):
            add(f"st:{a}", f"{a}-{a + 2}", "street", (a, a + 1, a + 2))
        for a in range(1, 33):
            if a % 3:
                add(f"c:{a}", f"{a}/{a + 1}/{a + 3}/{a + 4}", "corner", (a, a + 1, a + 3, a + 4))
        for a in range(1, 32, 3):
            add(f"sl:{a}", f"{a}-{a + 5}", "six_line", tuple(range(a, a + 6)))
        for d in (1, 2, 3):
            add(f"dz:{d}", f"{12 * d - 11}-{12 * d}", "dozen", tuple(range(12 * d - 11, 12 * d + 1)))
        for c in (1, 2, 3):
            add(f"col:{c}", f"Column {c}", "column", tuple(range(c, 37, 3)))
        add("red", "Red", "red", tuple(sorted(RED)))
        add("black", "Black", "black", tuple(n for n in range(1, 37) if n not in RED))
        add("odd", "Odd", "odd", tuple(range(1, 37, 2)))
        add("even", "Even", "even", tuple(range(2, 37, 2)))
        add("low", "1-18", "low", tuple(range(1, 19)))
        add("high", "19-36", "high", tuple(range(19, 37)))
        # which spots each pocket wins (returns() is a lookup, not a scan)
        self._covers: dict[int, list[str]] = {}
        for sid, sp in out.items():
            for n in sp.numbers:
                self._covers.setdefault(n, []).append(sid)
        return out

    # ---------------------------------------------------------------- outcome
    def outcome_at(self, pocket: int) -> dict[str, Any]:
        n = self.wheel[pocket]
        return {"pocket": pocket, "number": n, "label": label(n), "color": colour(n)}

    def draw(self, rng: Rng) -> dict[str, Any]:
        return self.outcome_at(rng.randint(0, len(self.wheel) - 1))

    def outcomes(self) -> list[tuple[dict[str, Any], Fraction]]:
        n = len(self.wheel)
        return [(self.outcome_at(i), Fraction(1, n)) for i in range(n)]

    def returns(self, outcome: dict[str, Any]) -> dict[str, Fraction]:
        n = int(outcome["number"])
        out = {sid: self._spots[sid].win for sid in self._covers.get(n, ())}
        if n == 0 and self.rules.la_partage and not self.american:
            for sid in EVEN_MONEY:
                out[sid] = Fraction(1, 2)
        return out

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        return {"label": outcome["label"], "tone": outcome["color"]}
