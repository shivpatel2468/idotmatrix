"""Teen Patti (three-card brag, the Indian way), 2–10 players against each other; the house deals.

Rules (pagat.com "Teen Patti" plus the common Indian table limits — boot, chaal limit, pot limit, blind limit):

* **Boot.** Everyone dealt in puts the boot into the pot; the **stake** starts at the boot. Three cards each,
  one at a time from the left of the dealer (the dealer moves one seat clockwise every hand); the player left of
  the dealer acts first, then clockwise.
* **Blind and seen.** Players start *blind* (cards face down). ``see`` looks at your cards (any time, it doesn't
  use your turn); you are *seen* from then on. On your turn:
  - **chaal** — a blind player puts in **1× the stake**, a seen player **2× the stake**;
  - **raise** — double: blind **2×**, seen **4×**; the stake doubles (never above the chaal limit);
  - **pack** — fold (your money stays in the pot).
  After ``max_blind_rounds`` blind bets a player must see (their cards open automatically).
* **Show** — only when **two players** remain. A **blind** player may call for a show at **1× the stake**
  (whether the other is blind or seen); a **seen** player pays **2× the stake** but **may not ask a blind player
  for a show**. Both hands are shown; the better hand wins; **if they are equal, the player who did not pay for the
  show wins**.
* **Sideshow** (compromise) — with three or more players left, a **seen** player puts in their chaal (2× the
  stake) and asks the **previous** player still in the hand (who must be seen and must already have bet) to
  compare privately. The other may **refuse** (play goes on) or **accept**: the two see each other's cards, the
  lower hand packs; **equal hands — the player who asked packs**. Unanswered requests are refused when the timer
  runs out.
* **Limits.** The stake never exceeds the **chaal limit**; when the pot reaches the **pot limit** every player
  still in shows and the best hand wins. A player who can't cover a bet may go all-in for what they have (they
  then only compete for the pot as it stood when they went all-in; later bets form a side pot among the others
  (`_pvp.snapshot_pots` — stakes differ by design in Teen Patti, so poker's matched-level side pots don't apply).
* **Ranking** (`cards.teen_patti_rank`): trail (three of a kind) > pure sequence > sequence > colour > pair >
  high card; A-K-Q is the top sequence and A-2-3 the second. Exact ties at a final show / pot-limit show split the
  pot (odd chips from the dealer's left).
* **Turn timer** (``house.turn_seconds``): an expired turn packs (there is no free check in Teen Patti).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..cards import Card, teen_patti_name, teen_patti_rank
from ..table import Rules, register_game
from ._pvp import Player, PvPGame, snapshot_pots

TP_SHORT = {
    "trail": "TR",
    "pure sequence": "PS",
    "sequence": "SQ",
    "colour": "CL",
    "pair": "PR",
    "high card": "HC",
}
TP_LABEL = {
    "trail": "TRAIL",
    "pure sequence": "PURE SEQ",
    "sequence": "SEQ",
    "colour": "COLOUR",
    "pair": "PAIR",
    "high card": "HIGH",
}


class TeenPattiRules(Rules):
    boot: int = Field(10, ge=1, le=100_000, title="Boot (ante)")
    chaal_limit: int = Field(1280, ge=1, le=10_000_000, title="Chaal limit (largest stake)")
    pot_limit: int = Field(10240, ge=2, le=100_000_000, title="Pot limit (forces a show)")
    max_blind_rounds: int = Field(4, ge=1, le=20, title="Blind bets before you must see")


@register_game
class TeenPatti(PvPGame):
    id = "teenpatti"
    name = "Teen Patti"
    Rules = TeenPattiRules
    max_seats = 10
    deal_beat = 2.0
    end_beat = 3.2

    def __init__(self, session: Any, rules: Any = None) -> None:
        super().__init__(session, rules)
        self._reset_hand()

    def _reset_hand(self) -> None:
        self.stake = 0
        self.dealer_i = 0
        self.seen: set[str] = set()
        self.blind_bets: dict[str, int] = {}
        self.sideshow: dict[str, Any] | None = None  # {"from": pid, "to": pid, "deadline": t}
        self.peeks: dict[str, dict[str, list[str]]] = {}  # pid -> {other pid: their cards} (sideshows)
        self.event: dict[str, Any] | None = None  # the last show / sideshow, for the panel
        self.end_kind = ""  # "pack" | "show" | "limit" | "allin"

    def buy_in(self) -> int:
        return int(self.rules.boot)

    def open_betting(self, now: float | None = None) -> None:
        super().open_betting(now)
        self._reset_hand()

    def pause_shift(self, dt: float) -> None:
        super().pause_shift(dt)
        if self.sideshow is not None:
            self.sideshow["deadline"] += dt

    # =================================================================== deal
    def start_hand(self, now: float) -> None:
        self._reset_hand()
        ps = self.players
        n = len(ps)
        self.dealer_i = self.next_dealer()
        self.dealer = ps[self.dealer_i].seat
        deck = iter(self.deck)
        for _ in range(3):
            for k in range(n):
                ps[(self.dealer_i + 1 + k) % n].cards.append(next(deck))
        boot = int(self.rules.boot)
        for p in ps:
            self.put_in(p, boot)
            p.last = "BOOT"
        self.stake = min(boot, int(self.rules.chaal_limit))
        self.turn = None
        if self._check_end(now):
            return
        self.turn = self._next_active((self.dealer_i + 1) % n, include=True)
        self.turn_deadline = None

    def _next_active(self, start: int, include: bool = False) -> int | None:
        n = len(self.players)
        for k in range(0, n) if include else range(1, n + 1):
            i = (start + k) % n
            if self.players[i].active:
                return i
        return None

    def _prev_live(self, i: int) -> Player | None:
        """The previous player still in the hand (counter-clockwise), all-in included."""
        n = len(self.players)
        for k in range(1, n):
            q = self.players[(i - k) % n]
            if q.live:
                return q
        return None

    # ================================================================ amounts
    def is_seen(self, p: Player) -> bool:
        return p.pid in self.seen

    def chaal_amount(self, p: Player) -> int:
        return self.stake * (2 if self.is_seen(p) else 1)

    def raise_amount(self, p: Player) -> int | None:
        if self.stake * 2 > int(self.rules.chaal_limit):
            return None
        return self.stake * (4 if self.is_seen(p) else 2)

    def show_cost(self, p: Player) -> int | None:
        live = self.live()
        if len(live) != 2:
            return None
        other = live[0] if live[1] is p else live[1]
        if self.is_seen(p) and not self.is_seen(other):
            return None  # a seen player may not ask a blind player for a show
        return self.stake * (2 if self.is_seen(p) else 1)

    def sideshow_target(self, p: Player, i: int) -> Player | None:
        if not self.is_seen(p) or len(self.live()) < 3:
            return None
        q = self._prev_live(i)
        if q is None or not q.active or not self.is_seen(q) or not q.acted:
            return None
        return q

    def legal(self, p: Player, i: int) -> dict[str, Any]:
        ops = ["pack"]
        chaal = self.chaal_amount(p)
        out: dict[str, Any] = {"chaal": min(chaal, p.stack), "seen": self.is_seen(p), "stake": self.stake}
        ops.append("chaal")
        r = self.raise_amount(p)
        if r is not None and p.stack > chaal:
            ops.append("raise")
            out["raise"] = min(r, p.stack)
        sc = self.show_cost(p)
        if sc is not None:
            ops.append("show")
            out["show"] = min(sc, p.stack)
        tgt = self.sideshow_target(p, i)
        if tgt is not None and p.stack > 0:
            ops.append("sideshow")
            out["sideshow"] = min(chaal, p.stack)
            out["sideshow_seat"] = tgt.seat
            out["sideshow_name"] = self.session.name_of(tgt.pid)
        if not self.is_seen(p):
            ops.append("see")
        out["ops"] = ops
        out["allin"] = p.stack <= chaal
        return out

    # ================================================================== moves
    def handle(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        if op == "see" and self.phase in ("dealing", "action") and not self.finished:
            p = self.by_pid(pid)
            if p is None or not p.live:
                return self._note(pid, "You're not in this hand")
            if pid not in self.seen:
                self.seen.add(pid)
                self.set_flash(p, "SEEN", now)
                self.session.changed()
            return None
        if op in ("accept", "refuse") and self.sideshow is not None and self.phase == "action":
            if self.sideshow["to"] != pid:
                return self._note(pid, "Nobody asked you for a sideshow")
            self._answer(op == "accept", now)
            return None
        return super().handle(pid, op, payload, now)

    def game_op(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        if self.sideshow is not None:
            return self._note(pid, "Waiting for the sideshow answer")
        p = self.my_turn(pid)
        if p is None:
            return self._note(pid, "It's not your turn")
        i = self.turn if self.turn is not None else 0
        lg = self.legal(p, i)
        if op not in lg["ops"]:
            why = {
                "show": "A show needs exactly two players — and a seen player can't show against a blind one",
                "sideshow": "A sideshow needs you and the previous player both seen, with three or more in",
                "raise": "The stake is at the chaal limit",
            }
            return self._note(pid, why.get(op, f"You can't {op} now"))
        if op == "pack":
            self._pack(p, now)
            self._after_move(i, now)
        elif op in ("chaal", "raise"):
            amount = lg["chaal"] if op == "chaal" else lg["raise"]
            if op == "raise":
                self.stake *= 2
            self._bet(p, amount, now, "RAISE" if op == "raise" else "CHAAL")
            if not self._check_end(now):
                self._after_move(i, now)
        elif op == "show":
            self._bet(p, lg["show"], now, "SHOW")
            if self.pot_total() >= int(self.rules.pot_limit):
                self._showdown(now, "limit")
            else:
                self._show(p, now)
        elif op == "sideshow":
            tgt = self.sideshow_target(p, i)
            assert tgt is not None
            self._bet(p, lg["sideshow"], now, "SIDE?")
            if self._check_end(now):
                return None
            self.sideshow = {"from": p.pid, "to": tgt.pid, "deadline": now + self.session.house.turn_seconds}
            self.turn_deadline = self.sideshow["deadline"]
            self.session.changed()
        return None

    def _bet(self, p: Player, amount: int, now: float, word: str) -> None:
        if not self.is_seen(p):
            self.blind_bets[p.pid] = self.blind_bets.get(p.pid, 0) + 1
        put = self.put_in(p, amount)
        p.acted = True
        self.set_flash(p, "ALL-IN" if p.allin else word, now, put)

    def _pack(self, p: Player, now: float, word: str = "PACK") -> None:
        p.folded = True
        p.acted = True
        self.set_flash(p, word, now)

    def _after_move(self, i: int, now: float) -> None:
        if self._check_end(now):
            return
        nxt = self._next_active(i)
        self.give_turn(nxt, now)
        self._force_see(now)

    def _force_see(self, now: float) -> None:
        """Blind limit: the player to act has made `max_blind_rounds` blind bets — their cards open."""
        if self.turn is None:
            return
        p = self.players[self.turn]
        if p.pid not in self.seen and self.blind_bets.get(p.pid, 0) >= int(self.rules.max_blind_rounds):
            self.seen.add(p.pid)
            self.set_flash(p, "SEEN", now)
            self._note(p.pid, "Blind limit reached — your cards are open", "info")

    def _check_end(self, now: float) -> bool:
        """Ends the hand if it is decided: one player left, the pot limit, or nobody left who can bet."""
        live = self.live()
        if len(live) == 1:
            w = live[0]
            self.end_kind = "pack"
            self.awards = {w.pid: self.pot_total()}
            self.won = dict(self.awards)
            self.winners = [{"seat": w.seat, "name": self.session.name_of(w.pid), "hand": "",
                             "amount": self.pot_total() - w.total, "won": self.pot_total()}]  # fmt: skip
            self.finish(now, beat=1.6)
            return True
        if self.pot_total() >= int(self.rules.pot_limit):
            self._showdown(now, "limit")
            return True
        if len([p for p in live if p.active]) <= 1:  # everyone else is all-in: nobody left to bet against
            self._showdown(now, "allin")
            return True
        return False

    # ========================================================= show / sideshow
    def _rank(self, p: Player) -> Any:
        return teen_patti_rank(p.cards)

    def _show(self, payer: Player, now: float) -> None:
        """A two-player show: equal hands — the player who did not pay wins."""
        a, b = self.live()
        other = b if a is payer else a
        ra, rb = self._rank(payer), self._rank(other)
        winner = payer if ra > rb else other
        self.event = {"kind": "show", "by": payer.seat, "with": other.seat,
                      "winner": winner.seat, "tie": ra == rb}  # fmt: skip
        self._showdown(now, "show", forced_winner=winner)

    def _answer(self, accept: bool, now: float) -> None:
        ss = self.sideshow
        assert ss is not None
        asker, target = self.by_pid(ss["from"]), self.by_pid(ss["to"])
        self.sideshow = None
        assert asker is not None and target is not None
        i = self.players.index(asker)
        if not accept:
            self.set_flash(target, "REFUSED", now)
            self.event = {"kind": "refused", "by": asker.seat, "with": target.seat}
        else:
            ra, rb = self._rank(asker), self._rank(target)
            loser = asker if ra <= rb else target  # equal: the player who asked packs
            self.peeks.setdefault(asker.pid, {})[target.pid] = [c.code for c in target.cards]
            self.peeks.setdefault(target.pid, {})[asker.pid] = [c.code for c in asker.cards]
            self.event = {"kind": "sideshow", "by": asker.seat, "with": target.seat, "loser": loser.seat}
            self._pack(loser, now, "SS PACK")
        self._after_move(i, now)

    def _showdown(self, now: float, kind: str, forced_winner: Player | None = None) -> None:
        live = self.live()
        self.end_kind = kind
        for p in live:
            self.showdown[p.pid] = [c.code for c in p.cards]
            self.seen.add(p.pid)
        ranks = {p.pid: self._rank(p) for p in live}
        order = self.from_button(self.dealer_i)
        pots = snapshot_pots(self.pot_total(), self.players)

        def best(elig: list[str]) -> list[str]:
            if forced_winner is not None and forced_winner.pid in elig:
                return [forced_winner.pid]
            top = max(ranks[p] for p in elig)
            return [p for p in elig if ranks[p] == top]

        self.award(pots, best, order)
        for pid, v in sorted(self.won.items(), key=lambda kv: -kv[1]):
            p = self.by_pid(pid)
            if p is None or v <= 0:
                continue
            self.winners.append({"seat": p.seat, "name": self.session.name_of(pid),
                                 "hand": teen_patti_name(ranks[pid]), "amount": self.awards[pid] - p.total,
                                 "won": v})  # fmt: skip
        self.finish(now)

    # ================================================================ timers
    def play_tick(self, now: float) -> None:
        if self.sideshow is not None and not self.finished and self.phase == "action":
            if now >= self.sideshow["deadline"]:
                self._answer(False, now)
            return
        super().play_tick(now)

    def timeout(self, p: Player, now: float) -> None:
        self.game_op(p.pid, "pack", {}, now)

    def after_beat(self, now: float) -> None:
        super().after_beat(now)
        self._force_see(now)

    # ================================================================= state
    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        if not self.winners:
            return {"label": "—", "tone": "white", "hand": ""}
        w = self.winners[0]
        if not w.get("hand"):
            return {"label": "W", "tone": "white", "hand": "", "winners": self.winners}
        return {
            "label": TP_SHORT.get(w["hand"], "?"),
            "tone": "gold",
            "hand": w["hand"],
            "winners": self.winners,
        }

    def seat_public(self, p: Player, i: int) -> dict[str, Any]:
        out = super().seat_public(p, i)
        out["seen"] = self.is_seen(p)
        out["dealer"] = i == self.dealer_i
        return out

    def public_state(self, now: float) -> dict[str, Any]:
        out = super().public_state(now)
        t = out["table"]
        t["stake"] = self.stake or int(self.rules.boot)
        t["boot"] = int(self.rules.boot)
        t["dealer_seat"] = self.players[self.dealer_i].seat if self.players else None
        ss = self.sideshow
        t["sideshow"] = (
            {"from": self.session.seat_of(ss["from"]), "to": self.session.seat_of(ss["to"]),
             "in": max(0, round(ss["deadline"] - now))} if ss else None
        )  # fmt: skip
        if ss:
            t["turn_seat"] = self.session.seat_of(ss["to"])
        t["event"] = self.event
        t["end"] = self.end_kind
        if self.finished or self.phase == "result":
            t["hands"] = {
                str(self.session.seat_of(pid)): teen_patti_name(teen_patti_rank([Card.parse(c) for c in cs]))
                for pid, cs in self.showdown.items()
            }
        return out

    def private_state(self, pid: str, now: float) -> dict[str, Any]:
        out = super().private_state(pid, now)
        p = self.by_pid(pid)
        if p is None or self.phase in ("betting", "idle"):
            return out
        seen = pid in self.seen
        out["seen"] = seen
        out["folded"] = p.folded
        if seen:  # a blind player's cards stay on the server until they look
            out["cards"] = [c.code for c in p.cards]
            out["hand"] = teen_patti_name(teen_patti_rank(p.cards))
        out["peeks"] = {str(self.session.seat_of(k)): v for k, v in self.peeks.get(pid, {}).items()}
        out["blind_left"] = max(0, int(self.rules.max_blind_rounds) - self.blind_bets.get(pid, 0))
        ss = self.sideshow
        if ss and ss["to"] == pid:
            out["ops"] = ["accept", "refuse"]
            out["sideshow_from"] = self.session.name_of(ss["from"])
            out["turn_in"] = max(0.0, round(ss["deadline"] - now, 1))
        else:
            me = self.my_turn(pid) if ss is None else None
            if me is not None:
                lg = self.legal(me, self.players.index(me))
                out.update({k: v for k, v in lg.items() if k != "ops"})
                out["ops"] = lg["ops"]
                out["turn_in"] = max(0.0, round((self.turn_deadline or now) - now, 1))
            elif p.live and not seen and not self.finished:
                out["ops"] = ["see"]
        out["my_turn"] = bool(self.my_turn(pid)) and ss is None
        out["stake"] = self.stake
        return out
