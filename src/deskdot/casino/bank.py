"""The bank: one wallet per player, escrow for open bets, an append-only ledger and per-player stats.

Invariants (tests/test_casino.py):

* Credits and escrow are whole numbers and never negative. A bet larger than the free credits is refused.
* A bet moves credits into escrow when it is placed (`stake`), back out if it is withdrawn (`release`), and is
  settled exactly once (`settle`: the stake leaves escrow, the payout — stake included — returns to credits).
* Every change of credits is a ledger entry ``{round, game, seat, pid, delta, reason, balance}``.

Persisted in the store section ``casino`` (keys ``wallets`` and ``ledger``). Stored data is never trusted: a bad
wallet is dropped, and escrow found at load (the engine stopped mid-round) is refunded — that round never happened.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from typing import Any

LEDGER_MAX = 2000  # entries kept in the state file (oldest dropped first)
CREDITS_MAX = 1_000_000_000


@dataclass
class Wallet:
    pid: str
    credits: int = 0
    escrow: int = 0
    won: int = 0  # sum of winning round nets
    lost: int = 0  # sum of losing round nets (as a positive number)
    biggest: int = 0  # biggest single-round net win
    rounds: int = 0  # rounds with a bet settled
    wagered: int = 0  # total stakes settled
    name: str = ""  # last known display name (the leaderboard outlives the lobby)
    color: str = ""
    avatar: str = ""

    @property
    def net(self) -> int:
        return self.won - self.lost

    def public(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "color": self.color,
            "avatar": self.avatar,
            "credits": self.credits,
            "escrow": self.escrow,
            "won": self.won,
            "lost": self.lost,
            "net": self.net,
            "biggest": self.biggest,
            "rounds": self.rounds,
        }

    @classmethod
    def load(cls, pid: str, raw: Any) -> Wallet | None:
        if not isinstance(raw, dict):
            return None
        kw: dict[str, Any] = {"pid": pid}
        for f in fields(cls):
            if f.name == "pid" or f.name not in raw:
                continue
            v = raw[f.name]
            if f.type == "int" or f.type is int:
                if type(v) is not int or v < 0 or v > CREDITS_MAX * 100:
                    return None
            elif not isinstance(v, str):
                return None
            kw[f.name] = v
        return cls(**kw)


class Bank:
    def __init__(self, section: dict[str, Any] | None = None, save: Callable[[], None] | None = None) -> None:
        self.section: dict[str, Any] = section if section is not None else {}
        self._save = save or (lambda: None)
        self.wallets: dict[str, Wallet] = {}
        self.ledger: list[dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        raw = self.section.get("wallets")
        refunded = False
        if isinstance(raw, dict):
            for pid, w in raw.items():
                if not isinstance(pid, str) or not pid or len(pid) > 40:
                    continue
                wallet = Wallet.load(pid, w)
                if wallet is None:
                    continue
                if wallet.escrow:  # the engine stopped mid-round: that round is void, the stake goes back
                    back, wallet.escrow = wallet.escrow, 0
                    wallet.credits += back
                    self._entry(wallet, back, "refund", round_=None, game="", seat=None)
                    refunded = True
                self.wallets[pid] = wallet
        led = self.section.get("ledger")
        if isinstance(led, list):
            self.ledger = [e for e in led if isinstance(e, dict) and isinstance(e.get("delta"), int)][
                -LEDGER_MAX:
            ] + self.ledger
        if refunded:
            self.save()

    def save(self) -> None:
        if len(self.ledger) > LEDGER_MAX:
            del self.ledger[: len(self.ledger) - LEDGER_MAX]
        self.section["wallets"] = {pid: _dump(w) for pid, w in self.wallets.items()}
        self.section["ledger"] = self.ledger
        self._save()

    # ---------------------------------------------------------------- wallets
    def has(self, pid: str) -> bool:
        return pid in self.wallets

    def open(self, pid: str, base: int, **profile: str) -> Wallet:
        """The player's wallet, created with `base` credits the first time they sit down."""
        w = self.wallets.get(pid)
        if w is None:
            w = self.wallets[pid] = Wallet(pid=pid)
            if base > 0:
                w.credits = int(base)
                self._entry(w, int(base), "base", round_=None, game="", seat=None)
        for k in ("name", "color", "avatar"):
            v = profile.get(k)
            if isinstance(v, str) and v:
                setattr(w, k, v)
        self.save()
        return w

    def get(self, pid: str) -> Wallet | None:
        return self.wallets.get(pid)

    def credits(self, pid: str) -> int:
        w = self.wallets.get(pid)
        return w.credits if w else 0

    # ------------------------------------------------------------------- bets
    def stake(self, pid: str, amount: int, *, round_: int | None, game: str, seat: int | str | None) -> bool:
        """Move `amount` from credits into escrow. False (and nothing changes) if it isn't affordable."""
        w = self.wallets.get(pid)
        if w is None or type(amount) is not int or amount <= 0 or amount > w.credits:
            return False
        w.credits -= amount
        w.escrow += amount
        self._entry(w, -amount, "bet", round_=round_, game=game, seat=seat)
        self.save()
        return True

    def release(
        self, pid: str, amount: int, *, round_: int | None, game: str, seat: int | str | None
    ) -> bool:
        """Return `amount` of an open bet from escrow to credits (the player withdrew it, or the round was void)."""
        w = self.wallets.get(pid)
        if w is None or type(amount) is not int or amount <= 0 or amount > w.escrow:
            return False
        w.escrow -= amount
        w.credits += amount
        self._entry(w, amount, "unbet", round_=round_, game=game, seat=seat)
        self.save()
        return True

    def settle(
        self, pid: str, stake: int, payout: int, *, round_: int, game: str, seat: int | str | None
    ) -> int:
        """Close a player's bets for a round: `stake` leaves escrow and `payout` (stake included, 0 for a loss)
        is credited. Returns the round's net for the player. Call exactly once per player per round."""
        w = self.wallets.get(pid)
        if w is None:
            raise KeyError(pid)
        if stake < 0 or payout < 0 or stake > w.escrow:
            raise ValueError(f"bad settlement for {pid}: stake {stake}, payout {payout}, escrow {w.escrow}")
        w.escrow -= stake
        w.credits = min(CREDITS_MAX, w.credits + payout)
        net = payout - stake
        w.rounds += 1
        w.wagered += stake
        if net > 0:
            w.won += net
            w.biggest = max(w.biggest, net)
        elif net < 0:
            w.lost += -net
        self._entry(w, payout, "win" if net > 0 else "push" if net == 0 else "lose", round_, game, seat, net)
        self.save()
        return net

    # -------------------------------------------------------------------- host
    def set_credits(self, pid: str, value: int, *, reason: str = "host_set") -> int:
        w = self.wallets.get(pid)
        if w is None:
            raise KeyError(pid)
        value = max(0, min(CREDITS_MAX, int(value)))
        delta, w.credits = value - w.credits, value
        self._entry(w, delta, reason, round_=None, game="", seat=None)
        self.save()
        return w.credits

    def add_credits(self, pid: str, delta: int) -> int:
        w = self.wallets.get(pid)
        if w is None:
            raise KeyError(pid)
        return self.set_credits(pid, w.credits + int(delta), reason="host_add")

    def reset(self, base: int) -> None:
        """A new session: everyone known starts again from `base` credits with clean stats. Open bets are refunded
        first by the table, so escrow is already empty here."""
        for w in self.wallets.values():
            w.credits = max(0, int(base)) + w.escrow
            w.won = w.lost = w.biggest = w.rounds = w.wagered = 0
        self.ledger.clear()
        for w in self.wallets.values():
            self._entry(w, w.credits, "base", round_=None, game="", seat=None)
        self.save()

    def remove(self, pid: str) -> None:
        w = self.wallets.get(pid)
        if w is not None and not w.escrow:
            del self.wallets[pid]
            self.save()

    def leaderboard(self, pids: list[str] | None = None) -> list[dict[str, Any]]:
        ws = (
            [self.wallets[p] for p in pids if p in self.wallets]
            if pids is not None
            else list(self.wallets.values())
        )
        ws.sort(key=lambda w: (-(w.credits + w.escrow), w.name))
        return [w.public() for w in ws]

    # ------------------------------------------------------------------ ledger
    def _entry(
        self,
        w: Wallet,
        delta: int,
        reason: str,
        round_: int | None,
        game: str,
        seat: int | str | None,
        net: int | None = None,
    ) -> None:
        e: dict[str, Any] = {
            "t": round(time.time(), 2),
            "round": round_,
            "game": game,
            "seat": seat,
            "pid": w.pid,
            "delta": int(delta),
            "reason": reason,
            "balance": w.credits,  # after the change
        }
        if net is not None:
            e["net"] = net
        self.ledger.append(e)


def _dump(w: Wallet) -> dict[str, Any]:
    d = asdict(w)
    d.pop("pid", None)
    return d
