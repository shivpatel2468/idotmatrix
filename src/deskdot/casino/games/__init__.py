"""One module per casino game: pure rules (no drawing). Importing registers each in `table.GAMES`.

Wave 1: roulette, sevens. Player-vs-player card games and Indian / wheel games: holdem, teenpatti, andarbahar,
bigsix. House-banked card games and the slot machines: blackjack, baccarat, slots.
"""

from __future__ import annotations

from . import andarbahar, baccarat, bigsix, blackjack, holdem, roulette, sevens, slots, teenpatti

__all__ = [
    "andarbahar",
    "baccarat",
    "bigsix",
    "blackjack",
    "holdem",
    "roulette",
    "sevens",
    "slots",
    "teenpatti",
]
