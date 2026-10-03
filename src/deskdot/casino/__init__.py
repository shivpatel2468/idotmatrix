"""Casino mode: provably fair table games for parties (docs/CASINO.md).

`fair` (commit–reveal RNG) · `bank` (wallets, escrow, ledger) · `cards` (decks, shoes, hand rankings) ·
`table` (`CasinoGame`, the round machine) · `session` (`CasinoSession`, players + house) · `games/*` (rules).
Importing this package registers every game in `table.GAMES` (used by `CasinoSession.verify`).
"""

from __future__ import annotations

from . import games  # noqa: F401 — registers the games
from .session import HOST, CasinoSession, House
from .table import GAMES, CasinoGame, Rules, Spot

__all__ = ["GAMES", "HOST", "CasinoGame", "CasinoSession", "House", "Rules", "Spot"]
