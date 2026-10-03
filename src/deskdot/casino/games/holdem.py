"""Texas Hold'em, no-limit, 2–10 players against each other; the house deals (and takes an optional rake).

Rules (the standard rulebook, Robert's Rules of Poker / TDA where they differ in detail):

* **Button and blinds.** The button moves one player clockwise every hand. The small blind is the first player
  after the button, the big blind the next; **heads-up the button posts the small blind** and acts first before
  the flop, last after it. A player who can't cover a blind posts what they have and is all-in. Blinds can double
  every N hands (``blind_up_every``; level k = blinds × 2^k).
* **Dealing** follows the deck order of the round's provably fair shuffle: hole cards one at a time, two rounds,
  starting left of the button; then burn + flop (3), burn + turn, burn + river.
* **Betting** (no-limit): pre-flop the first to act is left of the big blind (the button heads-up) and the big
  blind has the option; after the flop the first live player left of the button acts first. A bet is at least
  the big blind; a raise is **at least the size of the last full bet or raise** (``raise to`` ≥ current bet + that
  size); a player may always go all-in for less. An all-in raise smaller than a full raise does **not reopen**
  the betting for players who already acted (they may only call or fold) unless the raises since they acted add
  up to a full raise. Players facing the full big blind pre-flop must call the full big blind even if the big
  blind is short.
* **The hand ends** when one player is left (uncontested: no cards shown, uncalled chips come back), or after the
  river, or as soon as at most one player can still bet (everyone else all-in): the board is run out.
* **Showdown:** every live hand is shown; the best five of seven (`cards.best_of`) wins. **Side pots** are built
  from the contributions (`_pvp.build_pots`): one pot per all-in level, each won by the best hand among the
  players who matched it. Ties split the pot; **odd chips go to the first winner clockwise from the button**.
* **Turn timer** (``house.turn_seconds``): an expired turn checks if checking is free, otherwise folds.
* Players with less than a big blind sit out (the host can top them up); ``rake_percent`` (default 0) takes a
  share of every contested pot, only when a flop was dealt ("no flop, no drop"), capped at ``rake_cap``.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..cards import Card, HandRank, best_of
from ..table import Rules, register_game
from ._pvp import Player, PvPGame, build_pots

STREETS = ("preflop", "flop", "turn", "river")
#: short labels for history chips and the phone's result ball (the full name travels in `winners[].hand`)
HAND_SHORT = {
    "high card": "HC",
    "pair": "1P",
    "two pair": "2P",
    "three of a kind": "3K",
    "straight": "ST",
    "flush": "FL",
    "full house": "FH",
    "four of a kind": "4K",
    "straight flush": "SF",
    "royal flush": "RF",
}
HAND_LABEL = {
    "high card": "HIGH",
    "pair": "PAIR",
    "two pair": "2 PAIR",
    "three of a kind": "TRIPS",
    "straight": "STRAIGHT",
    "flush": "FLUSH",
    "full house": "FULL",
    "four of a kind": "QUADS",
    "straight flush": "STR FL",
    "royal flush": "ROYAL",
}


class HoldemRules(Rules):
    small_blind: int = Field(5, ge=1, le=100_000, title="Small blind")
    big_blind: int = Field(10, ge=2, le=200_000, title="Big blind")
    blind_up_every: int = Field(0, ge=0, le=100, title="Double the blinds every N hands (0 = never)")
    rake_percent: int = Field(0, ge=0, le=10, title="Rake (% of each pot, after a flop)")
    rake_cap: int = Field(0, ge=0, le=1_000_000, title="Rake cap per hand (0 = no cap)")


@register_game
class Holdem(PvPGame):
    id = "holdem"
    name = "Texas Hold'em"
    Rules = HoldemRules
    max_seats = 10
    deal_beat = 2.2
    street_beat = 1.2
    end_beat = 3.0

    def __init__(self, session: Any, rules: Any = None) -> None:
        super().__init__(session, rules)
        self._reset_hand()
        self.level_from = 0  # hands counted for blind levels from here (rules changed)

    def _reset_hand(self) -> None:
        self.board: list[Card] = []
        self.street = "preflop"
        self.cur_bet = 0
        self.min_raise = 0
        self.full_level = 0
        self.button = 0
        self.sb_i = self.bb_i = 0
        self.dpos = 0  # next card in the deck
        self.sb = self.bb = 0
        self.uncontested = False

    # ================================================================ blinds
    def blinds(self) -> tuple[int, int]:
        r = self.rules
        sb, bb = int(r.small_blind), max(int(r.big_blind), int(r.small_blind))
        every = int(r.blind_up_every)
        level = min(20, max(0, self.hands - 1 - self.level_from) // every) if every else 0
        return sb << level, bb << level

    def buy_in(self) -> int:
        nxt = self.hands + (1 if self.phase in ("betting", "idle", "result") else 0)  # the hand to come
        saved, self.hands = self.hands, nxt
        try:
            return self.blinds()[1]
        finally:
            self.hands = saved

    def set_rules(self, rules: Any) -> None:
        super().set_rules(rules)
        self.level_from = self.hands

    def open_betting(self, now: float | None = None) -> None:
        super().open_betting(now)
        self._reset_hand()

    # ================================================================== deal
    def _card(self) -> Card:
        c = self.deck[self.dpos]
        self.dpos += 1
        return c

    def start_hand(self, now: float) -> None:
        self._reset_hand()
        ps = self.players
        n = len(ps)
        self.button = self.next_dealer()
        self.dealer = ps[self.button].seat
        self.sb, self.bb = self.blinds()
        if n == 2:
            self.sb_i, self.bb_i = self.button, (self.button + 1) % n
        else:
            self.sb_i, self.bb_i = (self.button + 1) % n, (self.button + 2) % n
        for _ in range(2):  # one card at a time, starting left of the button
            for k in range(n):
                ps[(self.button + 1 + k) % n].cards.append(self._card())
        self.put_in(ps[self.sb_i], self.sb)
        ps[self.sb_i].last = "SB"
        self.put_in(ps[self.bb_i], self.bb)
        ps[self.bb_i].last = "BB"
        self.cur_bet = self.bb  # the full big blind, even when the big blind is short
        self.min_raise = self.bb
        self.full_level = self.bb
        self.street = "preflop"
        first = (self.bb_i + 1) % n
        self._first_turn(first, now)

    def _seek(self, start: int) -> int | None:
        """The first player from `start` (inclusive, clockwise) who still has to act this street."""
        n = len(self.players)
        for k in range(n):
            i = (start + k) % n
            p = self.players[i]
            if p.active and (not p.acted or p.bet < self.cur_bet):
                return i
        return None

    def _first_turn(self, start: int, now: float) -> None:
        """The first turn of the hand, unless the blinds left nobody able to bet (then the board runs out)."""
        i = self._seek(start)
        active = [p for p in self.players if p.active]
        if i is None or (len(active) == 1 and self.players[i].bet >= self.cur_bet):
            self.turn = None
            self._run_out(now)
            return
        self.turn = i
        self.turn_deadline = None

    def _advance(self, frm: int, now: float) -> None:
        """After a move by player `frm` (or at the start of a street from `frm`): next turn, next street, or the
        end of the hand."""
        live = self.live()
        if len(live) == 1:
            self._end_uncontested(live[0], now)
            return
        i = self._seek(frm)
        active = [p for p in live if p.active]
        if i is not None and not (len(active) == 1 and self.players[i].bet >= self.cur_bet):
            self.give_turn(i, now)
            return
        # the street is complete
        if len([p for p in live if p.active]) <= 1 or self.street == "river":
            self._run_out(now)
            return
        self._next_street(now)

    def _next_street(self, now: float) -> None:
        for p in self.players:
            p.bet = 0
            p.acted = False
            p.faced = 0
            if p.active and p.last not in ("ALL-IN",):
                p.last = ""
        self.cur_bet = 0
        self.min_raise = self.bb
        self.full_level = 0
        self.street = STREETS[STREETS.index(self.street) + 1]
        self._card()  # burn
        self.board += [self._card() for _ in range(3 if self.street == "flop" else 1)]
        n = len(self.players)
        i = self._seek((self.button + 1) % n)
        self.turn = i
        self.turn_deadline = None
        self.beat_until = now + self.street_beat
        self._set_phase("dealing", now)

    def _run_out(self, now: float) -> None:
        """Deal the rest of the board (nobody can bet any more) and show down."""
        while len(self.board) < 5:
            self._card()
            self.board += [self._card() for _ in range(3 if not self.board else 1)]
        self.street = "river"
        self._showdown(now)

    def _end_uncontested(self, winner: Player, now: float) -> None:
        self.uncontested = True
        self.awards = {winner.pid: self.pot_total()}  # nobody called: no showdown, no rake
        self.won = {winner.pid: self.pot_total()}
        self.winners = [{"seat": winner.seat, "name": self.session.name_of(winner.pid), "hand": "",
                         "amount": self.pot_total() - winner.total, "won": self.pot_total()}]  # fmt: skip
        self.finish(now, beat=1.6)

    def _showdown(self, now: float) -> None:
        live = self.live()
        ranks: dict[str, tuple[HandRank, tuple[Card, ...]]] = {
            p.pid: best_of(p.cards + self.board) for p in live
        }
        for p in live:
            self.showdown[p.pid] = [c.code for c in p.cards]
        pots = build_pots(self.contrib(), [p.pid for p in live])
        order = self.from_button(self.button)
        rules = self.rules
        cap = int(rules.rake_cap)
        pct = int(rules.rake_percent)

        def best(elig: list[str]) -> list[str]:
            top = max(ranks[p][0] for p in elig)
            return [p for p in elig if ranks[p][0] == top]

        def rake(pot: Any) -> int:  # showdown pots only, so the flop was always dealt
            r = pot.amount * pct // 100
            if cap:
                r = min(r, cap - self.rake_taken)
            return max(0, r)

        self.award(pots, best, order, rake if pct else None)
        for pid, v in sorted(self.won.items(), key=lambda kv: -kv[1]):
            p = self.by_pid(pid)
            if p is None or v <= 0:
                continue
            net = self.awards[pid] - p.total
            self.winners.append({"seat": p.seat, "name": self.session.name_of(pid), "hand": ranks[pid][0].name,
                                 "amount": net, "won": v, "best": [c.code for c in ranks[pid][1]]})  # fmt: skip
        self.finish(now)

    # ================================================================= moves
    def can_raise(self, p: Player) -> bool:
        others = [q for q in self.players if q is not p and q.active]
        if not others:
            return False  # everyone else is all-in: nobody could call a raise
        if p.stack <= self.cur_bet - p.bet:
            return False
        return not p.acted or p.faced < self.full_level

    def legal(self, p: Player) -> dict[str, Any]:
        to_call = min(self.cur_bet - p.bet, p.stack)
        max_to = p.bet + p.stack
        out: dict[str, Any] = {"to_call": max(0, to_call), "max_to": max_to}
        ops = ["fold"]
        ops.append("call" if to_call > 0 else "check")
        if self.can_raise(p):
            min_to = (self.cur_bet + self.min_raise) if self.cur_bet else self.bb
            out["min_to"] = min(min_to, max_to)
            ops.append("raise")
        else:
            out["min_to"] = None
        if p.stack > 0 and ("raise" in ops or to_call >= p.stack):
            ops.append("allin")
        out["ops"] = ops
        out["bet_word"] = "bet" if self.cur_bet == 0 else "raise"
        return out

    def game_op(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        p = self.my_turn(pid)
        if p is None:
            return self._note(pid, "It's not your turn")
        lg = self.legal(p)
        if op not in lg["ops"]:
            return self._note(pid, {"check": "You can't check — there's a bet to call", "raise": "You can't raise now",
                                    "call": "Nothing to call — check"}.get(op, f"You can't {op} now"))  # fmt: skip
        i = self.turn if self.turn is not None else 0
        if op == "fold":
            p.folded = True
            p.acted = True
            self.set_flash(p, "FOLD", now)
        elif op == "check":
            p.acted, p.faced = True, self.cur_bet
            self.set_flash(p, "CHECK", now)
        elif op == "call":
            self.put_in(p, lg["to_call"])
            p.acted, p.faced = True, self.cur_bet
            self.set_flash(p, "ALL-IN" if p.allin else "CALL", now, p.bet)
        else:
            if op == "allin":
                to = lg["max_to"]
            else:
                to = payload.get("amount")
                if type(to) is not int:
                    return self._note(pid, "Pick an amount")
                if to > lg["max_to"]:
                    return self._note(pid, f"You only have {lg['max_to']:,}")
                if to < lg["min_to"] and to != lg["max_to"]:
                    return self._note(pid, f"Minimum {lg['bet_word']} is to {lg['min_to']:,}")
            if to <= self.cur_bet:  # an all-in that doesn't even match the bet is a call
                self.put_in(p, to - p.bet)
                p.acted, p.faced = True, self.cur_bet
                self.set_flash(p, "ALL-IN", now, p.bet)
            else:
                word = "BET" if self.cur_bet == 0 else "RAISE"
                self.put_in(p, to - p.bet)
                if to - self.full_level >= self.min_raise:  # a full raise (re)opens the betting
                    self.min_raise = to - self.full_level
                    self.full_level = to
                self.cur_bet = to
                p.acted, p.faced = True, to
                self.set_flash(p, "ALL-IN" if p.allin else word, now, to)
        self._advance((i + 1) % len(self.players), now)
        return None

    def timeout(self, p: Player, now: float) -> None:
        lg = self.legal(p)
        self.game_op(p.pid, "check" if "check" in lg["ops"] else "fold", {}, now)

    # ================================================================= state
    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        if not self.winners:
            return {"label": "—", "tone": "white", "hand": ""}
        w = self.winners[0]
        hand = str(w.get("hand") or "")
        label = HAND_SHORT.get(hand, "?") if hand else "W"
        return {"label": label, "tone": "gold" if hand else "white", "hand": hand, "winners": self.winners}

    def public_state(self, now: float) -> dict[str, Any]:
        out = super().public_state(now)
        t = out["table"]
        t["board"] = [c.code for c in self.board]
        t["street"] = self.street
        t["cur_bet"] = self.cur_bet
        t["min_raise"] = self.min_raise
        t["blinds"] = list(self.blinds()) if not self.players else [self.sb, self.bb]
        t["button_seat"] = self.players[self.button].seat if self.players else None
        t["sb_seat"] = self.players[self.sb_i].seat if self.players else None
        t["bb_seat"] = self.players[self.bb_i].seat if self.players else None
        t["pots"] = self.display_pots()
        t["rake"] = self.rake_taken
        return out

    def display_pots(self) -> list[dict[str, Any]]:
        """The pots as the table shows them now: one pot, plus a side pot per all-in level once someone is all-in
        (bets still open above the all-ins stay in the top pot until the hand ends)."""
        if not self.players:
            return []
        seat = self.session.seat_of
        if self.finished:
            pots = build_pots(self.contrib(), [p.pid for p in self.live()])
            return [{"amount": pt.amount, "seats": [seat(x) for x in pt.eligible]} for pt in pots]
        live = self.live()
        levels = sorted({p.total for p in live if p.allin})
        out: list[dict[str, Any]] = []
        prev = 0
        for lv in levels:
            amt = sum(min(p.total, lv) - min(p.total, prev) for p in self.players)
            out.append({"amount": amt, "seats": [seat(p.pid) for p in live if p.total >= lv or not p.allin]})
            prev = lv
        rest = sum(max(0, p.total - prev) for p in self.players)
        if rest or not out:
            out.append({"amount": rest, "seats": [seat(p.pid) for p in live if not p.allin]})
        return out

    def private_state(self, pid: str, now: float) -> dict[str, Any]:
        out = super().private_state(pid, now)
        p = self.by_pid(pid)
        if p is None or self.phase in ("betting", "idle"):
            return out
        out["cards"] = [c.code for c in p.cards]
        if len(self.board) >= 3:
            r, five = best_of(p.cards + self.board)
            out["hand"] = r.name
            out["best"] = [c.code for c in five]
        out["folded"] = p.folded
        me = self.my_turn(pid)
        if me is not None:
            lg = self.legal(me)
            out["ops"] = lg["ops"]
            out["to_call"] = lg["to_call"]
            out["min_to"] = lg["min_to"]
            out["max_to"] = lg["max_to"]
            out["bet_word"] = lg["bet_word"]
            out["my_bet"] = me.bet
            out["turn_in"] = max(0.0, round((self.turn_deadline or now) - now, 1))
        out["my_turn"] = me is not None
        return out
