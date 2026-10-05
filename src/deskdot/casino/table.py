"""`CasinoGame`: the table every casino game runs on — rules, phases, bets, the fair round, settlement.

A game file (``casino/games/<name>.py``) is pure rules: no drawing, no I/O. The minimum for a bet-then-reveal game
(roulette, dice, wheels, baccarat, andar bahar):

* ``Rules`` — a pydantic model of the host options (the panel app's Settings carry the same field names);
* ``spots()`` — every bet a player can place: ``{spot_id: Spot}``;
* ``draw(rng)`` — the outcome from the round's provably fair `Rng` (JSON-able dict, never looks at bets);
* ``returns(outcome)`` — what each spot gives back per credit staked (stake included; spots not listed lose);
* ``outcomes()`` — every outcome with its exact probability (so the house edge of each bet is computed, not
  claimed); optional for games whose outcome space is too large (then override ``edges()``);
* ``summary(outcome)`` — a short label for history strips: ``{"label": "17", "tone": "red"}``.

Turn games (blackjack, hold'em, teen patti) also override ``on_locked`` (deal instead of revealing), ``game_op``
(their actions), ``play_tick`` (turn deadlines) and ``stakes``/``settle`` as needed; see each method's docstring.

Phases: ``idle → betting → locked → spinning|dealing → action → result → betting (auto) | idle``. Betting opens
without a deadline; the first bet starts the countdown (``house.bet_seconds``), so the wheel never spins for
nobody. The host can lock early, and the round also locks when every player with a bet pressed *done*.
All times are ``session.clock()`` (monotonic seconds); the panel app calls ``tick()`` from its render loop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from . import fair

if TYPE_CHECKING:
    from .session import CasinoSession

Phase = Literal["idle", "betting", "locked", "spinning", "dealing", "action", "result"]
LOCK_SECONDS = 1.0  # "no more bets" beat before the wheel / dice go
BET_OPS = ("bet", "unbet", "clear", "rebet", "done")


class Rules(BaseModel):
    """Base for a game's host options. Unknown keys are ignored (the app's Settings carry extra fields)."""

    model_config = ConfigDict(extra="ignore")


@dataclass(frozen=True)
class Spot:
    """A place to put chips. `win` is the total return per credit on a win (stake included): 36 for 35:1."""

    id: str
    label: str
    kind: str  # bet family, e.g. "straight", "split", "dozen", "red" — the studio groups edges by it
    win: Fraction
    numbers: tuple[int, ...] = ()  # what it covers (roulette pockets, dice sums) so phones can highlight

    @property
    def pays(self) -> str:
        """The payout as the table prints it: "35:1", "1:1", "0.95:1"."""
        p = self.win - 1
        return f"{p.numerator}:{p.denominator}" if p.denominator != 1 or p.numerator else "0:1"

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "pays": self.pays,
            "numbers": list(self.numbers),
        }


@dataclass
class RoundResult:
    nonce: int
    outcome: dict[str, Any]
    summary: dict[str, Any]
    payouts: dict[str, dict[str, Any]] = field(default_factory=dict)  # pid -> {stake, payout, net, wins}


GAMES: dict[str, type[CasinoGame]] = {}


def register_game(cls: type[CasinoGame]) -> type[CasinoGame]:
    GAMES[cls.id] = cls
    return cls


class CasinoGame:
    id: ClassVar[str] = "game"
    name: ClassVar[str] = "Game"
    Rules: ClassVar[type[Rules]] = Rules
    #: how long the panel animates between the lock and the reveal (wheel spin, dice tumble)
    spin_seconds: ClassVar[float] = 5.0
    reveal_phase: ClassVar[Phase] = "spinning"

    def __init__(self, session: CasinoSession, rules: Rules | None = None) -> None:
        self.session = session
        self.rules: Any = rules or self.Rules()
        self._pending_rules: Rules | None = None
        self.phase: Phase = "idle"
        self.phase_at = session.clock()
        self.deadline: float | None = None  # betting countdown (None = waiting for the first bet)
        self.reveal_at: float | None = None
        self.result_until: float | None = None
        self.locked_at: float | None = None  # when betting closed (the panel's spin / roll starts here)
        self.round: fair.Round | None = None
        self.rng: fair.Rng | None = None
        self.bets: dict[str, dict[str, int]] = {}  # pid -> spot -> credits
        self.last_bets: dict[str, dict[str, int]] = {}  # each player's previous round (rebet)
        self.done: set[str] = set()
        self.outcome: dict[str, Any] | None = None  # known from the lock; public only from the result phase
        self.result: RoundResult | None = None
        self._settled_nonce: int | None = None
        self._spots = self.spots()

    # ================================================================== rules
    def spots(self) -> dict[str, Spot]:
        raise NotImplementedError

    def draw(self, rng: fair.Rng) -> dict[str, Any]:
        raise NotImplementedError

    def returns(self, outcome: dict[str, Any]) -> dict[str, Fraction]:
        """Return factor per spot for this outcome (stake included): 36 = a 35:1 win, 1 = push, ½ = half back."""
        raise NotImplementedError

    def outcomes(self) -> list[tuple[dict[str, Any], Fraction]]:
        """Every outcome with its exact probability (sums to 1)."""
        raise NotImplementedError

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        return {"label": str(outcome), "tone": "white"}

    def edges(self) -> dict[str, float]:
        """House edge per bet family (worst spot in the family), as a fraction: 0.027 for European roulette."""
        return {k: float(-v) for k, v in self.expected_values(by_kind=True).items()}

    def expected_values(self, by_kind: bool = False) -> dict[str, Fraction]:
        """Exact expected net return per credit of every spot (−1/37 for any European roulette bet); with
        `by_kind`, the worst spot of each bet family."""
        rets = [(self.returns(o), p) for o, p in self.outcomes()]
        out: dict[str, Fraction] = {}
        for sid, spot in self._spots.items():
            ev = sum((p * r.get(sid, Fraction(0)) for r, p in rets), Fraction(0)) - 1
            key = spot.kind if by_kind else sid
            if key not in out or ev < out[key]:
                out[key] = ev
        return out

    def set_rules(self, rules: Rules) -> None:
        """New host options: applied now between rounds, else when the next round opens."""
        if self.phase in ("idle", "betting") and not self.bets:
            self.rules = rules
            self._spots = self.spots()
        else:
            self._pending_rules = rules

    @classmethod
    def replay(cls, rules: dict[str, Any], rng: fair.Rng) -> dict[str, Any]:
        """Recompute a round's outcome from its revealed seeds (fair.verify's `draw`)."""
        from .session import CasinoSession

        g = cls(CasinoSession(), cls.Rules.model_validate(rules))
        return g.draw(rng)

    @classmethod
    def replay_with(
        cls, rules: dict[str, Any], rng: fair.Rng, stored: dict[str, Any] | None
    ) -> dict[str, Any]:
        """`replay` for games whose round depends on more than its seeds — e.g. blackjack's shoe composition
        at the start of the round, recorded in the stored outcome. Default: `replay(rules, rng)`."""
        return cls.replay(rules, rng)

    # ================================================================ helpers
    @property
    def nonce(self) -> int | None:
        return self.round.nonce if self.round else None

    def stake_of(self, pid: str) -> int:
        return sum(self.bets.get(pid, {}).values())

    def _note(self, pid: str, text: str, kind: str = "error") -> str:
        self.session.notify(pid, text, kind)
        return text

    def _set_phase(self, phase: Phase, now: float) -> None:
        self.phase = phase
        self.phase_at = now
        self.session.changed()

    # ================================================================= rounds
    def open_betting(self, now: float | None = None) -> None:
        """A new round: fresh committed server seed, bets open, countdown waits for the first chip."""
        now = self.session.clock() if now is None else now
        if self._pending_rules is not None:
            self.rules, self._pending_rules = self._pending_rules, None
            self._spots = self.spots()
        self.round = fair.Round.fresh(self.session.next_nonce())
        self.rng = None
        self.bets, self.done = {}, set()
        self.outcome = None
        self.deadline = self.reveal_at = self.result_until = self.locked_at = None
        self._set_phase("betting", now)

    def lock(self, now: float | None = None) -> bool:
        """No more bets: fix the client seed and start the reveal. False unless betting is open."""
        now = self.session.clock() if now is None else now
        if self.phase != "betting" or self.round is None:
            return False
        self.rng = self.round.lock(self.session.client_seeds())
        self.deadline = None
        self.locked_at = now
        self._set_phase("locked", now)
        self.on_locked(self.rng, now)
        return True

    def on_locked(self, rng: fair.Rng, now: float) -> None:
        """Default: draw the whole outcome now (it stays secret) and reveal after the spin animation.
        Turn games override this to deal and move to ``action``."""
        self.outcome = self.draw(rng)
        self.reveal_at = now + LOCK_SECONDS + self.spin_seconds

    def tick(self, now: float | None = None) -> None:
        """Advance timers. Cheap; called from the panel's render loop, status() and every action."""
        now = self.session.clock() if now is None else now
        if self.session.paused:
            return
        if self.phase == "betting":
            if self.deadline is not None and now >= self.deadline:
                self.lock(now)
        elif self.phase == "locked" and now >= self.phase_at + LOCK_SECONDS:
            self._set_phase(self.reveal_phase, self.phase_at + LOCK_SECONDS)
        if self.phase in ("spinning", "dealing", "action"):
            self.play_tick(now)
            if self.reveal_at is not None and now >= self.reveal_at and self.phase != "action":
                self.reveal(now)
        elif self.phase == "result" and self.result_until is not None and now >= self.result_until:
            if self.session.house.auto_next:
                self.open_betting(now)
            else:
                self.result_until = None
                self._set_phase("idle", now)

    def play_tick(self, now: float) -> None:
        """Turn games: advance dealing / turn deadlines here (an expired turn takes the safe default)."""

    def reveal(self, now: float) -> None:
        """The outcome is public: settle every bet, reveal the seed, show the result."""
        self.settle()
        self.reveal_at = None
        self.result_until = now + self.session.house.result_seconds
        self._set_phase("result", now)

    def stakes(self, pid: str) -> int:
        return self.stake_of(pid)

    def payout(self, pid: str, outcome: dict[str, Any]) -> tuple[int, list[str]]:
        """(credits returned, winning spots) for one player. Whole credits, rounded down (never in the
        player's favour by a fraction). Turn games override this."""
        rets = self.returns(outcome)
        total, wins = 0, []
        for spot, amount in self.bets.get(pid, {}).items():
            k = rets.get(spot, Fraction(0))
            if k > 0:
                total += (amount * k).numerator // (amount * k).denominator
                if k >= 1:
                    wins.append(spot)
        return total, wins

    def settle(self) -> RoundResult | None:
        """Pay every bet of the round exactly once (a second call is a no-op)."""
        if self.round is None or self.outcome is None or self._settled_nonce == self.round.nonce:
            return self.result
        self._settled_nonce = self.round.nonce
        res = RoundResult(self.round.nonce, self.outcome, self.summary(self.outcome))
        bank = self.session.bank
        for pid in list(self.bets):
            stake = self.stakes(pid)
            if stake <= 0:
                continue
            paid, wins = self.payout(pid, self.outcome)
            seat = self.session.seat_of(pid)
            net = bank.settle(pid, stake, paid, round_=self.round.nonce, game=self.id, seat=seat)
            res.payouts[pid] = {"stake": stake, "payout": paid, "net": net, "wins": wins}
        self.round.revealed = True
        self.result = res
        self.last_bets = {pid: dict(b) for pid, b in self.bets.items() if b} | {
            pid: lb for pid, lb in self.last_bets.items() if pid not in self.bets
        }
        self.session.record(self, res)
        for pid, p in res.payouts.items():
            n = p["net"]
            self._note(pid, f"You won {n:,}" if n > 0 else "Push" if n == 0 else f"You lost {-n:,}", "result")
        return res

    def abort(self, now: float | None = None) -> None:
        """The table closes (another game, reset): open bets are refunded; a locked round still pays out."""
        now = self.session.clock() if now is None else now
        if self.phase in ("locked", "spinning") and self.outcome is not None:
            self.settle()  # the outcome was fixed at the lock: pay it rather than void it
        elif self.phase != "result":
            self.refund_all()
        self.bets, self.done = {}, set()
        self.deadline = self.reveal_at = self.result_until = self.locked_at = None
        self.round = None  # closed: the next time the table opens it starts a fresh round
        self._set_phase("idle", now)

    def refund_all(self) -> None:
        for pid in list(self.bets):
            self._refund(pid)

    def _refund(self, pid: str) -> None:
        amt = self.stake_of(pid)
        if amt:
            self.session.bank.release(
                pid, amt, round_=self.nonce, game=self.id, seat=self.session.seat_of(pid)
            )
        self.bets.pop(pid, None)
        self.done.discard(pid)

    def pause_shift(self, dt: float) -> None:
        """The host resumed after `dt` seconds of pause: push every running timer back."""
        for name in ("deadline", "reveal_at", "result_until", "locked_at"):
            v = getattr(self, name)
            if v is not None:
                setattr(self, name, v + dt)
        self.phase_at += dt

    # =================================================================== bets
    def place_bet(self, pid: str, spot: str, amount: int, now: float | None = None) -> str | None:
        """Put `amount` more on `spot`. Returns an error message (and changes nothing) or None."""
        now = self.session.clock() if now is None else now
        h = self.session.house
        if self.phase != "betting":
            return self._note(pid, "Bets are closed")
        sp = self._spots.get(spot)
        if sp is None:
            return self._note(pid, "Not a bet on this table")
        if type(amount) is not int or amount <= 0:
            return self._note(pid, "Pick a chip")
        cur = self.bets.get(pid, {}).get(spot, 0)
        room = h.max_bet - cur
        if room <= 0:
            return self._note(pid, f"Table max is {h.max_bet:,} per bet")
        amount = min(amount, room)  # a chip over the limit tops the spot up to the max
        if cur + amount < h.min_bet:
            return self._note(pid, f"Table min is {h.min_bet:,}")
        if not self.session.bank.stake(
            pid, amount, round_=self.nonce, game=self.id, seat=self.session.seat_of(pid)
        ):
            return self._note(pid, "Not enough credits")
        self.bets.setdefault(pid, {})[spot] = cur + amount
        self.done.discard(pid)
        if self.deadline is None:
            self.deadline = now + h.bet_seconds
        self.session.changed()
        return None

    def unbet(self, pid: str, spot: str, amount: int | None = None) -> str | None:
        """Take chips back off `spot` (all of them, or `amount`) while betting is open."""
        if self.phase != "betting":
            return self._note(pid, "Bets are closed")
        mine = self.bets.get(pid, {})
        cur = mine.get(spot, 0)
        if not cur:
            return None
        take = cur if amount is None or type(amount) is not int else max(0, min(cur, amount))
        left = cur - take
        if 0 < left < self.session.house.min_bet:  # never leave less than the table min on a spot
            take, left = cur, 0
        if take <= 0:
            return None
        self.session.bank.release(pid, take, round_=self.nonce, game=self.id, seat=self.session.seat_of(pid))
        if left:
            mine[spot] = left
        else:
            mine.pop(spot, None)
        if not mine:
            self.bets.pop(pid, None)
        self.done.discard(pid)
        self.session.changed()
        return None

    def clear(self, pid: str) -> str | None:
        if self.phase != "betting":
            return self._note(pid, "Bets are closed")
        self._refund(pid)
        self.session.changed()
        return None

    def rebet(self, pid: str, now: float | None = None) -> str | None:
        """Place last round's bets again (as far as credits allow)."""
        prev = self.last_bets.get(pid)
        if not prev:
            return self._note(pid, "No previous bets")
        for spot, amount in prev.items():
            if spot in self._spots:
                err = self.place_bet(pid, spot, amount, now)
                if err:
                    return err
        return None

    def mark_done(self, pid: str, now: float | None = None) -> None:
        """The player is happy with their bets; when everyone with a bet is, the round locks early."""
        if self.phase != "betting" or not self.bets.get(pid):
            return
        self.done.add(pid)
        if all(p in self.done for p, b in self.bets.items() if b):
            self.lock(now)

    # ================================================================ actions
    def handle(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        """A player's op. Betting ops are shared by every game; anything else goes to ``game_op``."""
        if op == "bet":
            return self.place_bet(pid, str(payload.get("spot", "")), _int(payload.get("amount")), now)
        if op == "unbet":
            amt = payload.get("amount")
            return self.unbet(pid, str(payload.get("spot", "")), _int(amt) if amt is not None else None)
        if op == "clear":
            return self.clear(pid)
        if op == "rebet":
            return self.rebet(pid, now)
        if op == "done":
            self.mark_done(pid, now)
            return None
        return self.game_op(pid, op, payload, now)

    def game_op(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        """Game-specific player ops (hit, stand, fold, pull …). Return an error message or None."""
        return self._note(pid, f"Unknown move {op!r}")

    #: the game's own host ops (the studio's ``POST /api/apps/{id}/actions/casino``), e.g. Housie's ``pace``
    host_ops: ClassVar[tuple[str, ...]] = ()

    def host_op(self, op: str, payload: dict[str, Any], now: float) -> dict[str, Any]:
        """A host op listed in ``host_ops``. Raise on bad input (HTTP 400). Returns a small JSON result."""
        raise KeyError(op)

    # ================================================================== state
    def public_state(self, now: float) -> dict[str, Any]:
        """Everything every phone and the studio may see. Never the outcome before the result phase, never
        anyone's private cards."""
        totals: dict[str, int] = {}
        for b in self.bets.values():
            for s, a in b.items():
                totals[s] = totals.get(s, 0) + a
        out: dict[str, Any] = {
            "game": self.id,
            "phase": self.phase,
            "round": self.nonce,
            "hash": self.round.hash if self.round else None,
            "ends_in": _left(self.deadline, now),
            "reveal_in": _left(self.reveal_at, now),
            "next_in": _left(self.result_until, now),
            "rules": self.rules.model_dump(mode="json"),
            "totals": totals,
            "spot_bets": self.spot_bets(),
            "bettors": _seats(self.session.seat_of(p) for p, b in self.bets.items() if b),
            "done": _seats(self.session.seat_of(p) for p in self.done),
        }
        if self.phase == "result" and self.result is not None:
            r = self.result
            out["result"] = {
                "round": r.nonce,
                "outcome": r.outcome,
                **r.summary,
                "winners": sorted(
                    (
                        {"seat": self.session.seat_of(p), "name": self.session.name_of(p), "net": v["net"]}
                        for p, v in r.payouts.items()
                        if v["net"] > 0
                    ),
                    key=lambda w: -w["net"],
                ),
            }
        return out

    def spot_bets(self) -> dict[str, list[dict[str, Any]]]:
        """Who has chips on which spot: ``{spot: [{seat, name, color, amount}, …]}`` in table order (host first,
        then by seat; a player whose seat was taken counts as seat 0). Built from the same `bets` as ``totals`` in
        the same call, so every phone and the studio draw the same chips with the same colours."""
        s = self.session
        rows: dict[str, list[tuple[tuple[int, int, str], dict[str, Any]]]] = {}
        for pid, b in self.bets.items():
            seat = s.seat_of(pid) or 0
            p = s.players.get(pid)
            key = (0, 0, pid) if seat == "host" else (1, int(seat), pid)
            for spot, amount in b.items():
                if amount > 0:
                    who = {
                        "seat": seat,
                        "name": s.name_of(pid),
                        "color": (p.color if p else "") or "#f0f0f0",
                        "amount": amount,
                    }
                    rows.setdefault(spot, []).append((key, who))
        return {spot: [w for _k, w in sorted(r, key=lambda kw: kw[0])] for spot, r in sorted(rows.items())}

    def private_state(self, pid: str, now: float) -> dict[str, Any]:
        mine = self.bets.get(pid, {})
        out: dict[str, Any] = {
            "bets": dict(mine),
            "staked": sum(mine.values()),
            "last_bets": self.last_bets.get(pid, {}),
            "can_bet": self.phase == "betting",
            "done": pid in self.done,
            "ops": list(BET_OPS) if self.phase == "betting" else [],
        }
        if self.phase == "result" and self.result is not None and pid in self.result.payouts:
            out["result"] = {"round": self.result.nonce, **self.result.payouts[pid]}
        return out

    def spot_table(self) -> list[dict[str, Any]]:
        return [s.public() for s in self._spots.values()]


def _seats(seats: Any) -> list[int | str]:
    """Seats in table order: the host ("host") first, then phone seats; a player without a seat counts as 0."""
    return sorted((s or 0 for s in seats), key=lambda s: (0, 0) if s == "host" else (1, int(s)))


def _left(t: float | None, now: float) -> int | None:
    """Whole seconds left, rounded up (the status JSON changes once a second; phones count down smoothly)."""
    if t is None:
        return None
    return max(0, math.ceil(t - now - 1e-6))


def _int(v: Any) -> int:
    return v if type(v) is int else int(v) if isinstance(v, float) and v.is_integer() else 0
