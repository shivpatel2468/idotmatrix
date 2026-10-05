"""The shared machinery of player-vs-player card games (Texas Hold'em, Teen Patti): the house deals, players bet
against each other, the pot goes to the best hand.

How these games sit on the `CasinoGame` round machine (docs/CASINO.md §8, "Player-vs-player tables"):

* ``betting`` is the **"next hand" lobby**. Phones are dealt in automatically when they sit down (``sit`` op
  toggles it; the studio host opts in with ``sit``). As soon as two players are in, the countdown starts
  (``house.bet_seconds``; 3 s once everybody seated is in). There are no chips to place: ``bet`` / ``unbet`` …
  are refused, the money goes in with the moves.
* ``lock`` fixes the round's client seed and the deck is shuffled with the round's provably fair `Rng`
  (``outcome = {"deck": "AS KD …"}``, a Fisher–Yates shuffle of `cards.new_deck()`; the phone replays it). The
  game then posts the forced bets (blinds / boot) and deals: ``dealing`` (animation beats) ↔ ``action`` (one
  player's turn, ``house.turn_seconds``; an expired turn takes the safe default).
* Every chip a player puts in moves into escrow at once (`Bank.stake`); at the end of the hand the pots are
  built from the contributions (`build_pots`: side pots for every all-in level) and paid out; settlement is
  exactly once, through the bank, with one ledger entry per player.
* Hole cards are only ever in ``private_state(pid)`` of their owner. At a showdown the hands that are shown
  become public in the result. After settlement the server seed is revealed (provable fairness), so anyone can
  recompute the whole deck order: that is inherent to provably fair card games and is how they are audited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..cards import Card, new_deck
from ..fair import Rng
from ..table import LOCK_SECONDS, CasinoGame, RoundResult, Spot, _left

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

READY_SECONDS = 3.0  # everybody seated is in: deal after this short beat


@dataclass
class Pot:
    amount: int
    eligible: list[str]  # pids that can win it, in table order

    def public(self) -> dict[str, Any]:
        return {"amount": self.amount, "eligible": list(self.eligible)}


def build_pots(contrib: dict[str, int], live: Sequence[str]) -> list[Pot]:
    """Main pot and side pots from what every player put in (folded players included) and who is still live.

    One pot per distinct contribution level of the live players: each player gives ``min(c, level) −
    min(c, previous level)`` to it and the live players who reached the level can win it. Folded money above the
    top live level joins the top pot. Neighbouring pots with the same eligible players merge. A pot with one
    eligible player is an uncalled bet (it simply goes back to that player)."""
    live_set = [p for p in live if p in contrib]
    levels = sorted({contrib[p] for p in live_set if contrib[p] > 0})
    pots: list[Pot] = []
    prev = 0
    for lv in levels:
        amt = sum(min(c, lv) - min(c, prev) for c in contrib.values())
        elig = [p for p in live_set if contrib[p] >= lv]
        if amt > 0:
            if pots and pots[-1].eligible == elig:
                pots[-1].amount += amt
            else:
                pots.append(Pot(amt, elig))
        prev = lv
    extra = sum(max(0, c - prev) for c in contrib.values())
    if extra:
        if pots:
            pots[-1].amount += extra
        elif live_set:
            pots.append(Pot(extra, list(live_set)))
    return pots


def snapshot_pots(total: int, players: Sequence[Player]) -> list[Pot]:
    """Pots for games where stakes differ by design (teen patti: blind players pay half): an all-in player can win
    the pot as it stood when they went all-in (``cap``), plus nothing that went in afterwards. One pot per all-in
    level; the rest belongs to the players still betting (or joins the top pot if everyone is all-in)."""
    live = [p for p in players if p.live]
    levels = sorted({p.cap for p in live if p.allin})
    pots: list[Pot] = []
    prev = 0
    for lv in levels:
        if lv > prev:
            pots.append(Pot(lv - prev, [p.pid for p in live if not p.allin or p.cap >= lv]))
        prev = lv
    rest = total - prev
    if rest > 0:
        betting = [p.pid for p in live if not p.allin]
        if betting:
            pots.append(Pot(rest, betting))
        elif pots:
            pots[-1].amount += rest
        else:
            pots.append(Pot(rest, [p.pid for p in live]))
    return pots


def split_pot(amount: int, winners: Sequence[str], order_from_button: Sequence[str]) -> dict[str, int]:
    """Split `amount` evenly between `winners`; the odd chips go one each to the winners closest to the left of
    the button (`order_from_button` lists every player clockwise starting with the first seat after it)."""
    if not winners:
        return {}
    share, odd = divmod(amount, len(winners))
    out = dict.fromkeys(winners, share)
    ranked = sorted(winners, key=lambda p: order_from_button.index(p) if p in order_from_button else 99)
    for p in ranked[:odd]:
        out[p] += 1
    return out


def shuffled_deck(rng: Rng) -> list[Card]:
    deck = new_deck()
    rng.shuffle(deck)
    return deck


@dataclass
class Player:
    """One player in the current hand."""

    pid: str
    seat: int | str
    stack: int  # chips behind (credits at the deal minus what went in)
    cards: list[Card] = field(default_factory=list)
    bet: int = 0  # this street (hold'em)
    total: int = 0  # everything put in this hand
    folded: bool = False
    allin: bool = False
    acted: bool = False
    faced: int = 0  # the bet level when this player last acted (hold'em: may they re-raise?)
    cap: int = 0  # the pot total when this player went all-in (teen patti side pots)
    last: str = ""  # last action, for the panel: FOLD CHECK CALL RAISE ALL-IN BLIND …

    @property
    def live(self) -> bool:
        return not self.folded

    @property
    def active(self) -> bool:
        """Still has decisions to make."""
        return not self.folded and not self.allin


class PvPGame(CasinoGame):
    """Base for games where players bet against each other (see the module docstring)."""

    reveal_phase = "dealing"
    spin_seconds = 0.0
    min_players = 2
    max_seats = 10
    deal_beat = 2.0  # seconds of dealing animation before the first turn
    end_beat = 2.4  # the last cards / the show on the panel before the result

    def __init__(self, session: Any, rules: Any = None) -> None:
        super().__init__(session, rules)
        self.sitting: set[str] = set()  # pids dealt into the next hand
        self.seen_pids: set[str] = set()  # phones auto-sat once (sitting out is then their choice)
        self.players: list[Player] = []  # this hand, in table order
        self.turn: int | None = None  # index into players
        self.turn_deadline: float | None = None
        self.beat_until: float | None = None  # animation beat (dealing, a new street, a show)
        self.dealer: int | str | None = None  # the button's seat (persists between hands)
        self.hands = 0  # hands dealt at this table (blind levels)
        self.awards: dict[str, int] = {}
        self.won: dict[str, int] = {}  # pots won at showdown (uncalled chips coming back excluded)
        self.finished = False
        self.showdown: dict[str, list[str]] = {}  # pid -> cards shown at the end (public in the result)
        self.winners: list[dict[str, Any]] = []
        self.flash: dict[str, Any] | None = None  # the latest action for the panel {seat, text, at}
        self.log: list[str] = []
        self.deck: list[Card] = []
        self.rake_taken = 0

    # ============================================================== rules API
    def spots(self) -> dict[str, Spot]:
        return {}

    def draw(self, rng: Rng) -> dict[str, Any]:
        return {"deck": " ".join(c.code for c in shuffled_deck(rng))}

    def outcomes(self) -> list[tuple[dict[str, Any], Any]]:
        return []

    def edges(self) -> dict[str, float]:
        """Players play each other: the house has no edge (beyond an optional rake)."""
        return {}

    def buy_in(self) -> int:
        """Credits a player needs to be dealt in (one big blind / one boot)."""
        return 1

    # ============================================================ who is in
    def pid_order(self) -> list[str]:
        return [p.pid for p in self.session.seated()]

    def eligible(self, pid: str) -> bool:
        p = self.session.players.get(pid)
        return bool(
            p and p.online and p.seat and not p.kicked and self.session.bank.credits(pid) >= self.buy_in()
        )

    def ready(self) -> list[str]:
        return [pid for pid in self.pid_order() if pid in self.sitting and self.eligible(pid)]

    def _auto_sit(self) -> None:
        for p in self.session.seated():
            if p.pid not in self.seen_pids and isinstance(p.seat, int):
                self.seen_pids.add(p.pid)
                self.sitting.add(p.pid)

    def _arm(self, now: float) -> None:
        """The deal countdown: runs while at least two players are in."""
        if self.phase != "betting" or self.session.paused:
            return
        self._auto_sit()
        n = len(self.ready())
        if n < self.min_players:
            if self.deadline is not None:
                self.deadline = None
                self.session.changed()
            return
        everyone = all(p.pid in self.sitting for p in self.session.seated() if self.eligible(p.pid))
        want = now + (READY_SECONDS if everyone else self.session.house.bet_seconds)
        if self.deadline is None or (everyone and self.deadline > want):
            self.deadline = want
            self.session.changed()

    def open_betting(self, now: float | None = None) -> None:
        now = self.session.clock() if now is None else now
        super().open_betting(now)
        self.players, self.turn, self.turn_deadline, self.beat_until = [], None, None, None
        self.awards, self.won, self.finished, self.showdown, self.winners = {}, {}, False, {}, []
        self.flash, self.log, self.deck, self.rake_taken = None, [], [], 0
        for pid in list(self.sitting):
            if pid in self.session.players and self.session.bank.credits(pid) < self.buy_in():
                self.sitting.discard(pid)
                self._note(pid, f"You need {self.buy_in():,} credits to play — sitting out", "info")
        self._arm(now)

    def lock(self, now: float | None = None) -> bool:
        now = self.session.clock() if now is None else now
        if self.phase != "betting" or len(self.ready()) < self.min_players:
            self.deadline = None
            return False
        return super().lock(now)

    def tick(self, now: float | None = None) -> None:
        now = self.session.clock() if now is None else now
        if self.phase == "betting":
            self._arm(now)
        super().tick(now)

    def pause_shift(self, dt: float) -> None:
        super().pause_shift(dt)
        if self.turn_deadline is not None:
            self.turn_deadline += dt
        if self.beat_until is not None:
            self.beat_until += dt

    # ================================================================ the hand
    def on_locked(self, rng: Rng, now: float) -> None:
        self.outcome = self.draw(rng)
        self.deck = [Card.parse(c) for c in self.outcome["deck"].split()]
        order = self.ready()[: self.max_seats]
        bank = self.session.bank
        self.players = [Player(pid, self.session.seat_of(pid) or 0, bank.credits(pid)) for pid in order]
        self.hands += 1
        self.beat_until = now + LOCK_SECONDS + self.deal_beat
        self.start_hand(now)

    def start_hand(self, now: float) -> None:
        raise NotImplementedError

    def next_dealer(self) -> int:
        """Index (in `players`) of this hand's button: the next player clockwise after the last button."""
        keys = [_seat_key(p.seat) for p in self.players]
        if self.dealer is None:
            return 0
        last = _seat_key(self.dealer)
        for i, k in enumerate(keys):
            if k > last:
                return i
        return 0

    def put_in(self, p: Player, amount: int) -> int:
        """Move `amount` (capped by the stack) from the player's stack into the pot. Returns what went in."""
        amount = max(0, min(int(amount), p.stack))
        if amount and not self.session.bank.stake(
            p.pid, amount, round_=self.nonce, game=self.id, seat=p.seat
        ):  # the host lowered their credits mid-hand: whatever is left goes in
            amount = min(amount, self.session.bank.credits(p.pid))
            if amount and not self.session.bank.stake(
                p.pid, amount, round_=self.nonce, game=self.id, seat=p.seat
            ):
                amount = 0
            p.stack = amount
        p.stack -= amount
        p.total += amount
        p.bet += amount
        if amount:
            self.bets.setdefault(p.pid, {})
            self.bets[p.pid]["pot"] = self.bets[p.pid].get("pot", 0) + amount
        if p.stack == 0 and not p.folded and not p.allin:
            p.allin = True
            p.cap = self.pot_total()
        self.session.changed()
        return amount

    def pot_total(self) -> int:
        return sum(p.total for p in self.players)

    def contrib(self) -> dict[str, int]:
        return {p.pid: p.total for p in self.players}

    def live(self) -> list[Player]:
        return [p for p in self.players if p.live]

    def by_pid(self, pid: str) -> Player | None:
        return next((p for p in self.players if p.pid == pid), None)

    def from_button(self, button: int) -> list[str]:
        n = len(self.players)
        return [self.players[(button + 1 + i) % n].pid for i in range(n)]

    def set_flash(self, p: Player, text: str, now: float, amount: int = 0) -> None:
        p.last = text
        self.flash = {"seat": p.seat, "pid": p.pid, "text": text, "at": now, "amount": amount}
        self.log.append(f"{self.session.name_of(p.pid)} {text.lower()}")
        del self.log[:-12]

    def award(
        self,
        pots: list[Pot],
        best: Callable[[list[str]], list[str]],
        order_from_button: Sequence[str],
        rake: Callable[[Pot], int] | None = None,
    ) -> None:
        """Pay every pot to its best eligible hand(s) (`best` picks the winners among the eligible)."""
        for pot in pots:
            amount = pot.amount
            if rake is not None and len(pot.eligible) > 1:
                r = min(amount, rake(pot))
                amount -= r
                self.rake_taken += r
            winners = best(pot.eligible) if len(pot.eligible) > 1 else list(pot.eligible)
            for pid, v in split_pot(amount, winners, order_from_button).items():
                self.awards[pid] = self.awards.get(pid, 0) + v
                if len(pot.eligible) > 1:  # a real win, not an uncalled bet coming back
                    self.won[pid] = self.won.get(pid, 0) + v

    def finish(self, now: float, beat: float | None = None) -> None:
        """The hand is decided (`awards` filled): show it on the panel for a beat, then settle."""
        start = max(now, self.beat_until or now)
        self.finished = True
        self.turn = None
        self.turn_deadline = None
        self.beat_until = None
        self.reveal_at = start + (self.end_beat if beat is None else beat)
        if self.phase == "action":
            self._set_phase("dealing", now)
        self.session.changed()

    # ================================================================== timers
    def play_tick(self, now: float) -> None:
        if self.finished:
            return
        if self.beat_until is not None:
            if now < self.beat_until:
                return
            self.beat_until = None
            self.after_beat(now)
            return
        if self.phase == "dealing" and self.turn is not None:
            self.turn_deadline = now + self.session.house.turn_seconds
            self._set_phase("action", now)
        elif self.phase == "action" and self.turn_deadline is not None and now >= self.turn_deadline:
            p = self.players[self.turn] if self.turn is not None else None
            if p is not None:
                self.timeout(p, now)

    def after_beat(self, now: float) -> None:
        """An animation beat ended (dealing, a new street): hand the turn over."""
        if self.turn is not None and self.phase in ("dealing", "locked"):
            self.turn_deadline = now + self.session.house.turn_seconds
            self._set_phase("action", now)

    def give_turn(self, i: int | None, now: float) -> None:
        self.turn = i
        self.turn_deadline = now + self.session.house.turn_seconds if i is not None else None
        self.session.changed()

    def timeout(self, p: Player, now: float) -> None:
        raise NotImplementedError

    # ============================================================== settlement
    def stakes(self, pid: str) -> int:
        p = self.by_pid(pid)
        return p.total if p else 0

    def payout(self, pid: str, outcome: dict[str, Any]) -> tuple[int, list[str]]:
        v = self.awards.get(pid, 0)
        return v, (["pot"] if v > self.stakes(pid) else [])

    def settle(self) -> RoundResult | None:
        if self.round is None or self.outcome is None or self._settled_nonce == self.round.nonce:
            return self.result
        self._settled_nonce = self.round.nonce
        res = RoundResult(self.round.nonce, self.outcome, self.summary(self.outcome))
        bank = self.session.bank
        for p in self.players:
            if p.total <= 0 and not self.awards.get(p.pid):
                continue
            paid, wins = self.payout(p.pid, self.outcome)
            net = bank.settle(p.pid, p.total, paid, round_=self.round.nonce, game=self.id, seat=p.seat)
            res.payouts[p.pid] = {"stake": p.total, "payout": paid, "net": net, "wins": wins}
        self.round.revealed = True
        self.result = res
        self.session.record(self, res)
        for pid, v in res.payouts.items():
            n = v["net"]
            self._note(pid, f"You won {n:,}" if n > 0 else "Even" if n == 0 else f"You lost {-n:,}", "result")
        return res

    def abort(self, now: float | None = None) -> None:
        """The table closes: a decided hand is paid, an unfinished one is void (everything goes back)."""
        now = self.session.clock() if now is None else now
        if self.finished and self.phase != "result":
            self.settle()
        elif self.phase != "result":
            self.refund_all()
        self.players, self.turn, self.turn_deadline, self.beat_until = [], None, None, None
        self.finished = False
        self.bets, self.done = {}, set()
        self.deadline = self.reveal_at = self.result_until = self.locked_at = None
        self.round = None
        self._set_phase("idle", now)

    # =================================================================== ops
    def handle(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        if op == "sit":
            on = payload.get("on")
            on = (pid not in self.sitting) if not isinstance(on, bool) else on
            self.seen_pids.add(pid)
            if on:
                if self.session.bank.credits(pid) < self.buy_in() and not self.by_pid(pid):
                    return self._note(pid, f"You need {self.buy_in():,} credits to play")
                self.sitting.add(pid)
            else:
                self.sitting.discard(pid)
            self._arm(now)
            self.session.changed()
            return None
        if op in ("bet", "unbet", "clear", "rebet", "done"):
            return self._note(pid, "No chips to place here — your money goes in with your moves")
        if self.phase != "action" or self.finished:
            return self._note(pid, "Wait for your turn")
        return self.game_op(pid, op, payload, now)

    def my_turn(self, pid: str) -> Player | None:
        if self.phase != "action" or self.turn is None or self.finished:
            return None
        p = self.players[self.turn]
        return p if p.pid == pid else None

    # ================================================================= state
    def seat_public(self, p: Player, i: int) -> dict[str, Any]:
        return {
            "seat": p.seat,
            "name": self.session.name_of(p.pid),
            "color": (self.session.players[p.pid].color if p.pid in self.session.players else "#f0f0f0"),
            "stack": p.stack,
            "bet": p.bet,
            "total": p.total,
            "folded": p.folded,
            "allin": p.allin,
            "last": p.last,
            "turn": i == self.turn and self.phase == "action",
        }

    def public_state(self, now: float) -> dict[str, Any]:
        out = super().public_state(now)
        out.pop("totals", None)  # pot contributions are in `table` per seat
        out.pop("spot_bets", None)
        out["pvp"] = True
        out["ends_in"] = _left(self.deadline, now)
        out["sitting"] = sorted(
            (self.session.seat_of(p) for p in self.ready()), key=lambda s: _seat_key(s or 0)
        )
        out["buy_in"] = self.buy_in()
        out["table"] = {
            "seats": [self.seat_public(p, i) for i, p in enumerate(self.players)],
            "pot": self.pot_total(),
            "turn_seat": self.players[self.turn].seat
            if self.turn is not None and self.phase == "action"
            else None,
            "turn_in": _left(self.turn_deadline, now) if self.phase == "action" else None,
            "turn_span": self.session.house.turn_seconds,
            "flash": {k: v for k, v in self.flash.items() if k != "pid"}
            | {"age": round(now - self.flash["at"], 2)}
            if self.flash
            else None,
            "log": list(self.log[-6:]),
            "finished": self.finished,
            "hand": self.hands,
        }
        if self.finished or self.phase == "result":
            out["table"]["showdown"] = {str(self.session.seat_of(k)): v for k, v in self.showdown.items()}
            out["table"]["winners"] = list(self.winners)
        return out

    def private_state(self, pid: str, now: float) -> dict[str, Any]:
        out = super().private_state(pid, now)
        out["can_bet"] = False
        out["ops"] = []
        out["sitting"] = pid in self.sitting
        out["in_hand"] = self.by_pid(pid) is not None and self.phase not in ("betting", "idle")
        return out


def _seat_key(seat: int | str) -> int:
    return 0 if seat == "host" else int(seat or 0)
