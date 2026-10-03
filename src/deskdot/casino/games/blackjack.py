"""Blackjack: everyone at the table against the dealer, from one shoe with a cut card (docs/CASINO.md §7).

Round: bets → lock → the deal (each player one card in seat order, the dealer's up card, a second card each, the
dealer's hole card face down) → insurance when the dealer shows an ace → the dealer peeks (US rules) → each player
plays their hand(s) in seat order, with a turn timer whose safe default is *stand* → the dealer turns the hole
card and draws to 17 (stands or hits soft 17) → settlement.

Rules (host options, `BlackjackRules`):

* 1–8 decks; the cut card sits at ``penetration`` % of the shoe and a new shoe starts with the next round once it
  is out (also when fewer than 12 cards per hand at the table are left);
* blackjack pays 3:2 (or 6:5); a win 1:1; a push returns the bet; insurance 2:1 (half the bet, rounded down);
* double on any first two cards, or only on hard 9–11; double after split (option);
* split any two cards of the same value up to ``max_splits`` times (4 hands); split aces get one card each and
  can't be re-split; 21 after a split is not a blackjack;
* late surrender (half back) on the first two cards of an unsplit hand;
* dealer peek (US): with an ace or ten up the dealer checks for blackjack before anyone plays, so only original
  bets can be lost to it. Without peek (European no-hole-card style) a dealer blackjack found at the end takes
  every bet on the table — doubles and splits included — except a player blackjack, which pushes; a surrendered
  hand then loses its whole bet too.

Payouts are whole credits, rounded down (bet even amounts for exact 3:2).

**Fairness.** The shoe lasts many rounds, yet every round is verifiable on its own: each round starts a lazy
Fisher–Yates shuffle of the cards still in the shoe (`cards.DealingShoe`, identical in distribution to one
shuffle per shoe) with its own provably fair `Rng`. The outcome records the shoe's composition at the start of the
round (``shoe``, one digit per card kind), whether the round started a new shoe (``shuffled``) and every card
dealt in order (``cards``); `replay_with` recomputes those cards from the revealed seeds, and the next round's
``shoe`` must equal this one's minus its ``cards`` (the phone checks that chain).

The house edge shown to the host (`edges`) is an *estimate* from standard rule-effect tables (base 0.40 % for six
decks, S17, DAS, no surrender, peek, 3:2); `tests/test_casino_blackjack.py` checks it against a basic-strategy
simulation of this very engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from pydantic import Field

from ..cards import Card, DealingShoe, blackjack_total, full_composition
from ..fair import Rng
from ..table import LOCK_SECONDS, CasinoGame, Rules, Spot, _left, register_game

DEAL_STEP = 0.42  # seconds between cards of the opening deal (the panel slides each one in)
HIT_DELAY = 0.25  # a hit card lands this long after the tap
DEALER_STEP = 0.95  # the dealer's draws
INSURANCE_SECONDS = 12


class BlackjackRules(Rules):
    decks: int = Field(6, ge=1, le=8, title="Decks in the shoe")
    penetration: int = Field(75, ge=50, le=90, title="Cut card at (% of the shoe)")
    soft17: Literal["stand", "hit"] = Field("stand", title="Dealer on soft 17")
    blackjack_pays: Literal["3:2", "6:5"] = Field("3:2", title="Blackjack pays")
    double_on: Literal["any", "9-11"] = Field("any", title="Double on")
    double_after_split: bool = Field(True, title="Double after split")
    max_splits: int = Field(3, ge=1, le=3, title="Splits per hand (3 = four hands)")
    surrender: Literal["late", "none"] = Field("late", title="Surrender")
    insurance: bool = Field(True, title="Offer insurance")
    dealer_peek: bool = Field(True, title="Dealer peeks for blackjack (US)")


def card_value(c: Card) -> int:
    """Blackjack value for splitting: 2–10, faces 10, ace 11."""
    return 11 if c.rank == 14 else min(c.rank, 10)


def is_natural(cards: list[Card]) -> bool:
    return len(cards) == 2 and blackjack_total(cards)[0] == 21


def dealer_hits(cards: list[Card], soft17: str) -> bool:
    total, soft = blackjack_total(cards)
    return total < 17 or (total == 17 and soft and soft17 == "hit")


def bj_win(bet: int, pays: str) -> int:
    """The profit on a blackjack, rounded down: 3:2 or 6:5."""
    return bet * 3 // 2 if pays == "3:2" else bet * 6 // 5


def house_edge(rules: BlackjackRules) -> float:
    """Estimated house edge of the main bet (a fraction), from standard rule-effect tables (multi-deck values).
    Base: 6 decks, S17, double any two, DAS, split to 4 hands, no resplit aces, no surrender, peek, 3:2 → 0.40 %."""
    decks = {1: -0.54, 2: -0.19, 3: -0.10, 4: -0.06, 5: -0.02, 6: 0.0, 7: 0.02, 8: 0.03}
    e = 0.40 + decks[int(rules.decks)]
    if rules.soft17 == "hit":
        e += 0.22
    if rules.blackjack_pays == "6:5":
        e += 1.36
    if rules.double_on == "9-11":
        e += 0.09
    if not rules.double_after_split:
        e += 0.14
    e += {3: 0.0, 2: 0.01, 1: 0.04}[int(rules.max_splits)]
    if rules.surrender == "late":
        e -= 0.08
    if not rules.dealer_peek:
        e += 0.11
    return round(e / 100, 5)


def insurance_edge(decks: int) -> float:
    """Exact edge of insurance off the top of a fresh shoe: 1 − 3·P(hole card is a ten | ace up)."""
    p = Fraction(16 * decks, 52 * decks - 1)
    return float(1 - 3 * p)


@dataclass
class Hand:
    cards: list[Card]
    bet: int
    times: list[float] = field(default_factory=list)  # when each card lands (the panel slides it in)
    split: bool = False  # came from a split
    split_aces: bool = False
    doubled: bool = False
    status: str = "play"  # play · stand · bust · blackjack · surrender

    @property
    def total(self) -> int:
        return blackjack_total(self.cards)[0]

    @property
    def soft(self) -> bool:
        return blackjack_total(self.cards)[1]

    @property
    def natural(self) -> bool:
        return not self.split and is_natural(self.cards)


@register_game
class Blackjack(CasinoGame):
    id = "blackjack"
    name = "Blackjack"
    Rules = BlackjackRules
    reveal_phase = "dealing"
    spin_seconds = 3.0  # nominal (previews); the real round runs on its own clock

    def __init__(self, session: Any, rules: Rules | None = None) -> None:
        super().__init__(session, rules)
        self.shoe: DealingShoe | None = None
        self._reset_hand()

    def _reset_hand(self) -> None:
        self.order: list[str] = []  # pids in seat order (host first)
        self.hands: dict[str, list[Hand]] = {}
        self.dealer: list[Card] = []
        self.dealer_times: list[float] = []
        self.hole_at: float | None = None  # when the hole card is turned (None: still face down)
        self.insurance: dict[str, int] = {}
        self.ins_pending: set[str] = set()
        self.extra: dict[str, int] = {}  # doubles, splits and insurance staked during play
        self.stage = "bets"  # bets · deal · insurance · turns · dealer · done
        self.turn: tuple[str, int] | None = None
        self.turn_deadline: float | None = None
        self.stage_deadline: float | None = None
        self.deal_end: float | None = None
        self.log: list[list[Any]] = []  # [seat, hand, op] — what each player chose, in order

    # ------------------------------------------------------------------ rules
    def spots(self) -> dict[str, Spot]:
        return {"main": Spot("main", "Bet", "main", Fraction(2))}

    def draw(self, rng: Rng) -> dict[str, Any]:
        """Not used for a live round (cards are dealt as players act); see `replay_with`."""
        raise NotImplementedError("blackjack rounds are replayed with replay_with()")

    def edges(self) -> dict[str, float]:
        out = {"main": house_edge(self.rules)}
        if self.rules.insurance:
            out["insurance"] = round(insurance_edge(int(self.rules.decks)), 5)
        return out

    @classmethod
    def replay_with(cls, rules: dict[str, Any], rng: Rng, stored: dict[str, Any] | None) -> dict[str, Any]:
        """Recompute a round's cards from its revealed seeds and the shoe it started from."""
        r = cls.Rules.model_validate(rules)
        stored = dict(stored or {})
        decks = int(r.decks)
        comp = full_composition(decks) if stored.get("shuffled") else str(stored.get("shoe", ""))
        try:
            shoe = DealingShoe(decks, comp)
        except ValueError:
            return {"error": "bad shoe composition"}
        shoe.begin(rng)
        n = len(stored.get("cards") or [])
        return {**stored, "shoe": comp, "cards": [shoe.draw().code for _ in range(n)]}

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        d = outcome.get("dealer_total")
        if outcome.get("dealer_bj"):
            return {"label": "BJ", "tone": "red"}
        if isinstance(d, int) and d > 21:
            return {"label": "BUST", "tone": "gold"}
        return {"label": str(d if d is not None else "?"), "tone": "black"}

    # ----------------------------------------------------------------- round
    def open_betting(self, now: float | None = None) -> None:
        self._reset_hand()
        super().open_betting(now)

    def _card(self) -> Card:
        assert self.shoe is not None and self.outcome is not None
        c = self.shoe.draw()
        self.outcome["cards"].append(c.code)
        return c

    def _seat_key(self, pid: str) -> tuple[int, int]:
        seat = self.session.seat_of(pid)
        if seat == "host":
            return (0, 0)
        return (1, seat) if isinstance(seat, int) else (2, 0)

    def on_locked(self, rng: Rng, now: float) -> None:
        r = self.rules
        decks = int(r.decks)
        self.order = sorted((p for p, b in self.bets.items() if sum(b.values()) > 0), key=self._seat_key)
        cut = round(52 * decks * int(r.penetration) / 100)
        need = 12 * (len(self.order) + 1)
        sh = self.shoe
        shuffled = sh is None or sh.decks != decks or sh.size - sh.remaining >= cut or sh.remaining < need
        if shuffled or sh is None:
            sh = self.shoe = DealingShoe(decks)
        self.outcome = {"decks": decks, "shoe": sh.composition, "shuffled": shuffled, "cards": []}
        sh.begin(rng)
        for pid in self.order:
            self.hands[pid] = [Hand([], sum(self.bets[pid].values()))]
        t = now + LOCK_SECONDS + 0.35
        for _ in range(2):
            for pid in self.order:
                h = self.hands[pid][0]
                h.cards.append(self._card())
                h.times.append(t)
                t += DEAL_STEP
            self.dealer.append(self._card())
            self.dealer_times.append(t)
            t += DEAL_STEP
        for pid in self.order:
            h = self.hands[pid][0]
            if h.natural:
                h.status = "blackjack"
        self.deal_end = t + 0.2
        self.stage = "deal"

    def play_tick(self, now: float) -> None:
        if self.stage == "deal" and self.deal_end is not None and now >= self.deal_end:
            self._after_deal(now)
        elif self.stage == "insurance" and (
            not self.ins_pending or (self.stage_deadline is not None and now >= self.stage_deadline)
        ):
            self._after_insurance(now)
        elif (
            self.stage == "turns"
            and self.turn
            and self.turn_deadline is not None
            and now >= self.turn_deadline
        ):
            self._act(self.turn[0], "stand", now, auto=True)  # the safe default

    @property
    def dealer_bj(self) -> bool:
        return is_natural(self.dealer)

    def _after_deal(self, now: float) -> None:
        self.deal_end = None
        up = self.dealer[0]
        if self.rules.insurance and up.rank == 14:
            self.ins_pending = {p for p in self.order if self.hands[p][0].bet // 2 >= 1}
            if self.ins_pending:
                self.stage = "insurance"
                self.stage_deadline = now + min(INSURANCE_SECONDS, self.session.house.turn_seconds)
                self._set_phase("action", now)
                return
        self._peek(now)

    def _after_insurance(self, now: float) -> None:
        self.ins_pending = set()
        self.stage_deadline = None
        self._peek(now)

    def _peek(self, now: float) -> None:
        up = self.dealer[0]
        if self.rules.dealer_peek and card_value(up) >= 10 and self.dealer_bj:
            self._dealer_turn(now)
            return
        self._next_turn(now)

    def _next_turn(self, now: float) -> None:
        for pid in self.order:
            for i, h in enumerate(self.hands[pid]):
                if h.status != "play":
                    continue
                if len(h.cards) == 1:  # the second card of a split hand, dealt when play reaches it
                    self._give(h, now)
                    if h.total == 21:
                        h.status = "stand"
                        continue
                self.stage = "turns"
                self.turn = (pid, i)
                self.turn_deadline = now + self.session.house.turn_seconds
                self._set_phase("action", now)
                return
        self._dealer_turn(now)

    def _give(self, h: Hand, now: float) -> Card:
        c = self._card()
        h.cards.append(c)
        h.times.append(now + HIT_DELAY)
        return c

    def _dealer_turn(self, now: float) -> None:
        self.stage = "dealer"
        self.turn = self.turn_deadline = None
        self.ins_pending = set()
        t = now + 0.6
        self.hole_at = t
        live = any(h.status in ("stand", "play") for hs in self.hands.values() for h in hs)
        if live and not self.dealer_bj:
            while dealer_hits(self.dealer, self.rules.soft17):
                t += DEALER_STEP
                self.dealer.append(self._card())
                self.dealer_times.append(t)
        self.stage_deadline = t
        self.reveal_at = t + 1.5
        self._finish_outcome()
        self._set_phase("dealing", now)

    def _finish_outcome(self) -> None:
        assert self.outcome is not None
        self.outcome["dealer"] = [c.code for c in self.dealer]
        self.outcome["dealer_total"] = blackjack_total(self.dealer)[0]
        self.outcome["dealer_bj"] = self.dealer_bj
        self.outcome["hands"] = {
            str(self.session.seat_of(p) or p): [[c.code for c in h.cards] for h in hs]
            for p, hs in self.hands.items()
        }
        self.outcome["log"] = self.log

    def reveal(self, now: float) -> None:
        self.stage = "done"
        super().reveal(now)

    # ------------------------------------------------------------------ moves
    def moves(self, pid: str) -> list[str]:
        """The moves `pid` may make right now (only the player whose turn it is has any, except insurance)."""
        if self.phase != "action":
            return []
        if self.stage == "insurance":
            if pid not in self.ins_pending:
                return []
            amt = self.hands[pid][0].bet // 2
            return (
                ["insurance", "no_insurance"] if self.session.bank.credits(pid) >= amt else ["no_insurance"]
            )
        if self.stage != "turns" or self.turn is None or self.turn[0] != pid:
            return []
        hands = self.hands[pid]
        h = hands[self.turn[1]]
        r = self.rules
        out = ["hit", "stand"]
        credits = self.session.bank.credits(pid)
        if len(h.cards) == 2 and credits >= h.bet:
            hard9_11 = not h.soft and h.total in (9, 10, 11)
            if (r.double_on == "any" or hard9_11) and (not h.split or r.double_after_split):
                out.append("double")
            if (
                card_value(h.cards[0]) == card_value(h.cards[1])
                and len(hands) < 1 + int(r.max_splits)
                and not h.split_aces
            ):
                out.append("split")
        if r.surrender == "late" and len(hands) == 1 and len(h.cards) == 2 and not h.split:
            out.append("surrender")
        return out

    def game_op(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        if op == "insurance" and payload.get("take") is False:
            op = "no_insurance"
        if op not in ("hit", "stand", "double", "split", "surrender", "insurance", "no_insurance"):
            return self._note(pid, f"Unknown move {op!r}")
        if pid not in self.hands:
            return self._note(pid, "You're not in this hand")
        legal = self.moves(pid)
        if op not in legal:
            if self.stage == "turns" and self.turn and self.turn[0] != pid:
                return self._note(pid, "Wait for your turn")
            return self._note(pid, "You can't do that now")
        return self._act(pid, op, now)

    def _stake(self, pid: str, amount: int) -> bool:
        ok = self.session.bank.stake(
            pid, amount, round_=self.nonce, game=self.id, seat=self.session.seat_of(pid)
        )
        if ok:
            self.extra[pid] = self.extra.get(pid, 0) + amount
        return ok

    def _act(self, pid: str, op: str, now: float, auto: bool = False) -> str | None:
        seat = self.session.seat_of(pid)
        if op in ("insurance", "no_insurance"):
            if op == "insurance":
                amt = self.hands[pid][0].bet // 2
                if not self._stake(pid, amt):
                    return self._note(pid, "Not enough credits")
                self.insurance[pid] = amt
            self.ins_pending.discard(pid)
            self.log.append([seat, 0, op])
            self.session.changed()
            if not self.ins_pending:
                self._after_insurance(now)
            return None
        assert self.turn is not None
        i = self.turn[1]
        hands = self.hands[pid]
        h = hands[i]
        self.log.append([seat, i, op + ("*" if auto else "")])
        if op == "hit":
            self._give(h, now)
            if h.total > 21:
                h.status = "bust"
            elif h.total == 21:
                h.status = "stand"
            else:
                self.turn_deadline = now + self.session.house.turn_seconds
                self.session.changed()
                return None
        elif op == "stand":
            h.status = "stand"
        elif op == "surrender":
            h.status = "surrender"
        elif op == "double":
            if not self._stake(pid, h.bet):
                return self._note(pid, "Not enough credits to double")
            h.bet *= 2
            h.doubled = True
            self._give(h, now)
            h.status = "bust" if h.total > 21 else "stand"
        elif op == "split":
            if not self._stake(pid, h.bet):
                return self._note(pid, "Not enough credits to split")
            aces = h.cards[0].rank == 14
            second = Hand([h.cards[1]], h.bet, [h.times[1]], split=True, split_aces=aces)
            h.cards, h.times, h.split, h.split_aces = [h.cards[0]], [h.times[0]], True, aces
            hands.insert(i + 1, second)
            if aces:  # one card each, and that's it
                for sh in (h, second):
                    self._give(sh, now)
                    sh.status = "stand"
            else:
                self._give(h, now)
                if h.total == 21:
                    h.status = "stand"
                else:
                    self.turn_deadline = now + self.session.house.turn_seconds
                    self.session.changed()
                    return None
        self.session.changed()
        self._next_turn(now)
        return None

    # ------------------------------------------------------------- settlement
    def stakes(self, pid: str) -> int:
        return self.stake_of(pid) + self.extra.get(pid, 0)

    def hand_return(self, h: Hand) -> int:
        """Credits one hand gives back at the end (stake included)."""
        r = self.rules
        dbj = self.dealer_bj
        if h.status == "surrender":
            return 0 if dbj and not r.dealer_peek else h.bet // 2
        if dbj:
            return h.bet if h.natural else 0
        if h.natural:
            return h.bet + bj_win(h.bet, r.blackjack_pays)
        if h.total > 21:
            return 0
        d = blackjack_total(self.dealer)[0]
        if d > 21 or h.total > d:
            return 2 * h.bet
        return h.bet if h.total == d else 0

    def payout(self, pid: str, outcome: dict[str, Any]) -> tuple[int, list[str]]:
        total = sum(self.hand_return(h) for h in self.hands.get(pid, []))
        if self.dealer_bj:
            total += 3 * self.insurance.get(pid, 0)
        return total, (["main"] if total > self.stakes(pid) else [])

    def abort(self, now: float | None = None) -> None:
        """The table closes mid-hand: the cards were fixed by the round's seed, so the hand is played out with the
        safe defaults (everyone left stands, no insurance) and paid, never voided."""
        now = self.session.clock() if now is None else now
        if (
            self.phase in ("locked", "dealing", "action")
            and self.outcome is not None
            and self.stage != "done"
        ):
            self.ins_pending = set()
            for hs in self.hands.values():
                for h in hs:
                    if h.status == "play":
                        if len(h.cards) == 1:
                            self._give(h, now)
                        h.status = "stand"
            if self.stage != "dealer":
                self._dealer_turn(now)
            self.settle()
            self.stage = "done"
            self.phase = "result"
        super().abort(now)

    def pause_shift(self, dt: float) -> None:
        super().pause_shift(dt)
        for name in ("turn_deadline", "stage_deadline", "deal_end", "hole_at"):
            v = getattr(self, name)
            if v is not None:
                setattr(self, name, v + dt)
        self.dealer_times = [t + dt for t in self.dealer_times]
        for hs in self.hands.values():
            for h in hs:
                h.times = [t + dt for t in h.times]

    # ------------------------------------------------------------------ state
    def _hand_public(self, h: Hand, now: float) -> dict[str, Any]:
        shown = [c for c, t in zip(h.cards, h.times, strict=True) if t <= now]
        total, soft = blackjack_total(shown) if shown else (0, False)
        complete = len(shown) == len(h.cards)
        return {
            "cards": [c.code for c in shown],
            "total": total,
            "soft": soft and total < 21,
            "bet": h.bet,
            "doubled": h.doubled,
            "split": h.split,
            "status": h.status if complete else "play",
            "bj": h.natural and complete,
        }

    def dealer_public(self, now: float) -> dict[str, Any]:
        hole_up = self.hole_at is not None and now >= self.hole_at
        cards: list[str] = []
        for i, (c, t) in enumerate(zip(self.dealer, self.dealer_times, strict=True)):
            if t > now:
                break
            cards.append("??" if i == 1 and not hole_up else c.code)
        visible = [Card.parse(c) for c in cards if c != "??"]
        total, soft = blackjack_total(visible) if visible else (0, False)
        return {
            "cards": cards,
            "total": total,
            "soft": soft and total < 21,
            "bj": hole_up and self.dealer_bj,
            "hole": "??" in cards,
            "done": self.stage in ("dealer", "done") and len(cards) == len(self.dealer) and hole_up,
        }

    def table_state(self, now: float) -> dict[str, Any]:
        """Everything on the felt — blackjack hands are public; the hole card stays '??' until it is turned."""
        seats = []
        for pid in self.order:
            p = self.session.players.get(pid)
            hs = self.hands.get(pid, [])
            row: dict[str, Any] = {
                "seat": self.session.seat_of(pid),
                "name": self.session.name_of(pid),
                "color": p.color if p else "#f0f0f0",
                "hands": [self._hand_public(h, now) for h in hs],
                "insurance": self.insurance.get(pid, 0),
            }
            if self.phase == "result" and self.result is not None and pid in self.result.payouts:
                row["net"] = self.result.payouts[pid]["net"]
            seats.append(row)
        turn = None
        if self.stage == "turns" and self.turn is not None:
            turn = {
                "seat": self.session.seat_of(self.turn[0]),
                "hand": self.turn[1],
                "ends_in": _left(self.turn_deadline, now),
            }
        sh = self.shoe
        return {
            "stage": self.stage,
            "dealer": self.dealer_public(now),
            "seats": seats,
            "turn": turn,
            "insurance_in": _left(self.stage_deadline, now) if self.stage == "insurance" else None,
            "shoe": {
                "decks": sh.decks if sh else int(self.rules.decks),
                "left": sh.remaining if sh else 52 * int(self.rules.decks),
                "cut": bool(
                    sh and sh.size - sh.remaining >= round(sh.size * int(self.rules.penetration) / 100)
                ),
            },
        }

    def public_state(self, now: float) -> dict[str, Any]:
        out = super().public_state(now)
        out["table"] = self.table_state(now)
        return out

    def private_state(self, pid: str, now: float) -> dict[str, Any]:
        out = super().private_state(pid, now)
        mv = self.moves(pid)
        out["moves"] = mv
        out["in_hand"] = pid in self.hands
        if self.stage == "turns" and self.turn and self.turn[0] == pid:
            out["turn"] = {"hand": self.turn[1], "ends_in": _left(self.turn_deadline, now)}
        if self.stage == "insurance" and pid in self.ins_pending:
            out["insurance_offer"] = self.hands[pid][0].bet // 2
        out["insured"] = self.insurance.get(pid, 0)
        return out


# ---------------------------------------------------------------- basic strategy (tests, the demo's bots)
def basic_strategy(cards: list[Card], up: Card, moves: list[str], rules: BlackjackRules | None = None) -> str:
    """Textbook multi-deck basic strategy (S17 tables, H17 tweaks), picking only from the legal `moves`."""
    rules = rules or BlackjackRules()
    total, soft = blackjack_total(cards)
    d = card_value(up)  # 2..11
    h17 = rules.soft17 == "hit"

    def pick(*prefs: str) -> str:
        for m in prefs:
            if m in moves:
                return m
        return "stand" if "stand" in moves else moves[0]

    if "surrender" in moves:
        if not soft and total == 16 and d in (9, 10, 11) and not (len(cards) == 2 and cards[0].rank == 8):
            return "surrender"
        if not soft and total == 15 and (d == 10 or (h17 and d == 11)):
            return "surrender"
    if "split" in moves:
        v = card_value(cards[0])
        das = rules.double_after_split
        split = {
            11: True,
            10: False,
            9: d in (2, 3, 4, 5, 6, 8, 9),
            8: True,
            7: d <= 7,
            6: d <= 6 if das else 3 <= d <= 6,
            5: False,
            4: d in (5, 6) and das,
            3: d <= 7 if das else 4 <= d <= 7,
            2: d <= 7 if das else 4 <= d <= 7,
        }[v]
        if split:
            return "split"
    if soft:
        if total >= 20:
            return "stand"
        if total == 19:
            return pick("double", "stand") if d == 6 and h17 else "stand"
        if total == 18:
            if 2 <= d <= 6:
                return pick("double", "stand")
            return "stand" if d in (7, 8) else "hit"
        if total == 17:
            return pick("double", "hit") if 3 <= d <= 6 else "hit"
        if total in (15, 16):
            return pick("double", "hit") if 4 <= d <= 6 else "hit"
        return pick("double", "hit") if 5 <= d <= 6 else "hit"
    if total >= 17:
        return "stand"
    if total >= 13:
        return "stand" if d <= 6 else "hit"
    if total == 12:
        return "stand" if 4 <= d <= 6 else "hit"
    if total == 11:
        return pick("double", "hit")
    if total == 10:
        return pick("double", "hit") if d <= 9 else "hit"
    if total == 9:
        return pick("double", "hit") if 3 <= d <= 6 else "hit"
    return "hit"


BotPolicy = Callable[[list[Card], Card, list[str]], str]
