"""Housie (Tambola / Indian Bingo): players buy tickets into a pot, the caller draws 1–90, the first to complete a
pattern and claim it wins that prize.

Rules (the Indian Tambola rulebook):

* A **ticket** is a 3 × 9 grid with **15 numbers, 5 in every row**. Column ``c`` holds numbers from ``10c`` to
  ``10c + 9`` (column 0: 1–9, column 8: 80–90), each column has **1–3 numbers**, sorted top to bottom.
* During the **buy-in** (the table's ``betting`` phase) every player buys 0…``max_tickets`` tickets at
  ``ticket_price`` credits each (op ``buy {count}``; ``bet``/``unbet`` on the spot ``ticket`` add / remove one,
  ``clear``, ``rebet`` and ``done`` work as usual). The first ticket starts the buy-in countdown (``buy_seconds``);
  the host can start the calling early (host op ``lock``); it also starts once everyone with tickets is done.
* At the lock the round's provably fair `Rng` draws **the whole call order first** (Fisher–Yates of 1…90) and then
  **every ticket**, in seat order (the host first), each player's tickets one after the other (`make_ticket`). The
  outcome is ``{"calls": [90 numbers], "holders": [[seat, tickets], …], "tickets": [[27 cells, 0 = blank], …]}``;
  `replay_with` rebuilds it from the revealed seeds and the stored holders, and the phone does the same.
* The **pot** is every ticket sold; the house keeps ``rake`` % (rounded down, default 0) and the rest is the
  **prize pool**, split between the enabled prizes by their shares (credits rounded down; the odd credits go to
  the Full House, else the biggest prize): **Early Five** (any 5 numbers), **Top / Middle / Bottom Line** (all 5 of
  that row), **Four Corners** (the first and last number of the top and bottom rows), **Full House** (all 15).
* The caller draws one number every ``call_seconds`` (the host can change the pace live: host op ``pace``; the
  table's pause freezes it). Players **claim** (op ``claim {prize, ticket?}`` or ``claim_<prize>``); the server
  checks the ticket against the numbers called so far. A false claim (a **bogey**) is rejected; with ``bogey`` =
  ``prize`` that ticket can no longer win that prize, with ``ticket`` the ticket is out of the game.
* Every valid claim for a prize made before the **next** number is called shares it (a tie: split per winning
  ticket, odd credits to the earliest claims). Once the next number is called the prize is closed.
* The game ends when the Full House is won (a short grace for ties first), when every enabled prize is won, or
  after all 90 numbers; prizes nobody claimed are shared back to the ticket holders in proportion to their tickets
  (odd credits by seat order). ``auto_claim`` makes the server claim for everyone the moment a pattern completes.
* Settlement goes through the bank once per player: stake = tickets × price, payout = prizes (+ any share back);
  the nets add up to minus the rake.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Literal

from pydantic import Field

from ..fair import Rng
from ..table import BET_OPS, LOCK_SECONDS, CasinoGame, RoundResult, Rules, Spot, _int, _left, register_game

PRIZES = ("early5", "top", "middle", "bottom", "corners", "full")
PRIZE_NAMES = {
    "early5": "Early Five",
    "top": "Top Line",
    "middle": "Middle Line",
    "bottom": "Bottom Line",
    "corners": "Four Corners",
    "full": "Full House",
}
DEFAULT_SHARES = {"early5": 10, "top": 15, "middle": 15, "bottom": 15, "corners": 10, "full": 35}
#: the numbers each column may hold: 1–9, 10–19 … 70–79, 80–90
COLUMNS: tuple[tuple[int, ...], ...] = tuple(
    tuple(range(1 if c == 0 else 10 * c, 91 if c == 8 else 10 * c + 10)) for c in range(9)
)
TICKET_BEAT = 4.0  # after the lock: seconds to look at the tickets before the first call
END_GRACE = 3.0  # after the Full House (or the last prize): seconds for tied claims before the game ends
END_BEAT = 2.5  # the last claim on the panel before the result


# =========================================================================== tickets
def make_ticket(rng: Rng) -> list[int]:
    """One valid ticket from the fair stream: 27 cells, row-major (``cells[r * 9 + c]``), 0 = blank.

    1. Column sizes: one number per column, then 6 more, each to a column chosen uniformly among those with < 3.
    2. Each column's numbers: a Fisher–Yates shuffle of its range, the first ``k`` taken, sorted.
    3. Rows: columns from the fullest down (column order within a size); each takes the ``k`` rows with the most
       room left, ties broken by a shuffle of (0, 1, 2) — every row ends with exactly 5 numbers.
    `casino.html` mirrors this draw for draw."""
    counts = [1] * 9
    for _ in range(6):
        free = [c for c in range(9) if counts[c] < 3]
        counts[free[rng.below(len(free))]] += 1
    nums: list[list[int]] = []
    for c in range(9):
        pool = list(COLUMNS[c])
        rng.shuffle(pool)
        nums.append(sorted(pool[: counts[c]]))
    cells = [0] * 27
    room = [5, 5, 5]
    for c in sorted(range(9), key=lambda c: -counts[c]):
        perm = list(rng.shuffle([0, 1, 2]))
        rows = sorted(sorted(perm, key=lambda r: -room[r])[: counts[c]])
        for r, n in zip(rows, nums[c], strict=True):
            cells[r * 9 + c] = n
            room[r] -= 1
    return cells


def ticket_rows(t: list[int]) -> list[list[int]]:
    """The numbers of each row, left to right."""
    return [[n for n in t[r * 9 : r * 9 + 9] if n] for r in range(3)]


def ticket_numbers(t: list[int]) -> list[int]:
    return [n for n in t if n]


def needs(t: list[int], prize: str) -> list[int]:
    """The numbers a prize needs (Early Five: any 5 of these)."""
    top, mid, bot = ticket_rows(t)
    if prize == "top":
        return top
    if prize == "middle":
        return mid
    if prize == "bottom":
        return bot
    if prize == "corners":
        return [top[0], top[-1], bot[0], bot[-1]]
    return ticket_numbers(t)


def complete(t: list[int], prize: str, called: set[int] | frozenset[int]) -> bool:
    """Is `prize` done on ticket `t` with these numbers called?"""
    if prize == "early5":
        return sum(1 for n in ticket_numbers(t) if n in called) >= 5
    return all(n in called for n in needs(t, prize))


def completes_at(t: list[int], prize: str, calls: list[int]) -> int:
    """The call (1-based) on which `prize` completes on `t` (with the whole call order)."""
    pos = {n: i + 1 for i, n in enumerate(calls)}
    got = sorted(pos[n] for n in needs(t, prize))
    return got[4] if prize == "early5" else got[-1]


def valid_ticket(t: list[int]) -> bool:
    """3 × 9, 15 numbers, 5 per row, 1–3 per column, each in its column's range, columns sorted top to bottom."""
    if len(t) != 27 or any(len(r) != 5 for r in ticket_rows(t)):
        return False
    for c in range(9):
        col = [t[r * 9 + c] for r in range(3) if t[r * 9 + c]]
        if not 1 <= len(col) <= 3 or any(n not in COLUMNS[c] for n in col) or col != sorted(set(col)):
            return False
    return True


def deal(rng: Rng, holders: list[list[Any]]) -> dict[str, Any]:
    """The round's outcome: the call order, then every ticket (holders = [[seat, count], …] in seat order)."""
    calls = list(range(1, 91))
    rng.shuffle(calls)
    n = sum(max(0, int(h[1])) for h in holders)
    return {
        "calls": calls,
        "holders": [[h[0], int(h[1])] for h in holders],
        "tickets": [make_ticket(rng) for _ in range(n)],
    }


def split(amount: int, n: int) -> list[int]:
    """`amount` in `n` whole shares, the odd credits to the first ones."""
    if n <= 0:
        return []
    q, r = divmod(amount, n)
    return [q + (1 if i < r else 0) for i in range(n)]


# =========================================================================== rules
class HousieRules(Rules):
    ticket_price: int = Field(10, ge=1, le=100_000, title="Ticket price (credits)")
    max_tickets: int = Field(3, ge=1, le=6, title="Max tickets per player")
    buy_seconds: int = Field(45, ge=10, le=300, title="Buy-in time (from the first ticket)")
    call_seconds: int = Field(6, ge=3, le=20, title="Seconds between calls")
    rake: int = Field(0, ge=0, le=20, title="House rake (% of the pot)")
    bogey: Literal["none", "prize", "ticket"] = Field("none", title="False claim (bogey)")
    auto_claim: bool = Field(False, title="Claim for everyone automatically")
    early5: bool = Field(True, title="Early Five")
    early5_share: int = Field(DEFAULT_SHARES["early5"], ge=0, le=100, title="Early Five share (%)")
    top: bool = Field(True, title="Top Line")
    top_share: int = Field(DEFAULT_SHARES["top"], ge=0, le=100, title="Top Line share (%)")
    middle: bool = Field(True, title="Middle Line")
    middle_share: int = Field(DEFAULT_SHARES["middle"], ge=0, le=100, title="Middle Line share (%)")
    bottom: bool = Field(True, title="Bottom Line")
    bottom_share: int = Field(DEFAULT_SHARES["bottom"], ge=0, le=100, title="Bottom Line share (%)")
    corners: bool = Field(True, title="Four Corners")
    corners_share: int = Field(DEFAULT_SHARES["corners"], ge=0, le=100, title="Four Corners share (%)")
    full: bool = Field(True, title="Full House")
    full_share: int = Field(DEFAULT_SHARES["full"], ge=0, le=100, title="Full House share (%)")


def prize_shares(rules: Any) -> dict[str, int]:
    """The enabled prizes and their shares (the Full House alone at 100 if nothing usable is enabled)."""
    out = {p: int(getattr(rules, f"{p}_share")) for p in PRIZES if getattr(rules, p)}
    out = {p: s for p, s in out.items() if s > 0}
    return out or {"full": 100}


def prize_amounts(rules: Any, pool: int) -> dict[str, int]:
    """The pool split by the shares (rounded down); the odd credits go to the Full House, else the biggest."""
    shares = prize_shares(rules)
    total = sum(shares.values())
    out = {p: pool * s // total for p, s in shares.items()}
    rest = pool - sum(out.values())
    if rest:
        key = "full" if "full" in out else max(shares, key=lambda p: shares[p])
        out[key] += rest
    return out


# =========================================================================== the game
@register_game
class Housie(CasinoGame):
    id = "housie"
    name = "Housie"
    Rules = HousieRules
    reveal_phase = "dealing"  # the calling
    spin_seconds = 0.0

    def __init__(self, session: Any, rules: Any = None) -> None:
        super().__init__(session, rules)
        self._reset()

    def _reset(self) -> None:
        self.tickets: dict[str, list[list[int]]] = {}  # pid -> tickets (dealt at the lock)
        self.first_ticket: dict[str, int] = {}  # pid -> index of its first ticket in the outcome
        self.called = 0
        self.next_call_at: float | None = None
        self.last_call_at: float | None = None  # when the current number was called (the panel's ball pops)
        self.claims: dict[str, dict[str, Any]] = {}  # prize -> {call, winners [[pid, ticket]], closed}
        self.blocked: set[tuple[str, int, str]] = set()
        self.void: set[tuple[str, int]] = set()
        self.bogeys: list[dict[str, Any]] = []
        self.flash: dict[str, Any] | None = None
        self.pot = self.rake_taken = self.pool = 0
        self.amounts: dict[str, int] = {}
        self.awards: dict[str, int] = {}
        self.won: dict[str, list[dict[str, Any]]] = {}  # pid -> [{prize, ticket, amount}]
        self.returned = 0  # unclaimed prize money shared back
        self.finished = False

    # ================================================================ rules API
    def spots(self) -> dict[str, Spot]:
        return {"ticket": Spot("ticket", f"Ticket · {self.rules.ticket_price:,}", "ticket", Fraction(1))}

    def draw(self, rng: Rng, holders: list[list[Any]] | None = None) -> dict[str, Any]:
        return deal(rng, holders or [])

    @classmethod
    def replay_with(cls, rules: dict[str, Any], rng: Rng, stored: dict[str, Any] | None) -> dict[str, Any]:
        holders = (stored or {}).get("holders") or []
        return deal(rng, [list(h) for h in holders if isinstance(h, list | tuple) and len(h) == 2])

    def returns(self, outcome: dict[str, Any]) -> dict[str, Fraction]:
        return {}

    def outcomes(self) -> list[tuple[dict[str, Any], Fraction]]:
        return []

    def edges(self) -> dict[str, float]:
        """Players play for each other's pot: the house keeps only its rake."""
        return {"ticket": self.rules.rake / 100}

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        """History label: the call the game ended on (live), else the call of the first Full House."""
        if outcome is self.outcome and self.called:
            n = self.called
        else:
            ts, calls = outcome.get("tickets") or [], outcome.get("calls") or []
            n = min((completes_at(t, "full", calls) for t in ts), default=90) if calls else 0
        return {"label": str(n), "tone": "gold"}

    def set_rules(self, rules: Any) -> None:
        """The pace applies at once (it changes nothing about the money); the rest between games."""
        if self.phase not in ("idle", "betting") or self.bets:
            self.rules = self.rules.model_copy(update={"call_seconds": rules.call_seconds})
        super().set_rules(rules)

    # ================================================================ helpers
    def count(self, pid: str) -> int:
        return self.stake_of(pid) // max(1, self.rules.ticket_price)

    def _seat_key(self, pid: str) -> tuple[int, int]:
        s = self.session.seat_of(pid)
        return (0, 0) if s == "host" else (1, int(s or 99))

    def calls(self) -> list[int]:
        return list(self.outcome["calls"][: self.called]) if self.outcome else []

    def called_set(self) -> frozenset[int]:
        return frozenset(self.calls())

    def color_of(self, pid: str) -> str:
        p = self.session.players.get(pid)
        return p.color if p else "#f0f0f0"

    def open_prizes(self) -> list[str]:
        return [p for p in self.amounts if not (self.claims.get(p) or {}).get("winners")]

    # ================================================================ buy-in
    def open_betting(self, now: float | None = None) -> None:
        super().open_betting(now)
        self._reset()

    def buy(self, pid: str, n: int, now: float) -> str | None:
        """Set the player's ticket count to `n` (0 … max_tickets) while the buy-in is open."""
        if self.phase != "betting":
            return self._note(pid, "Tickets are sold before the calling starts")
        mx = self.rules.max_tickets
        if n > mx:
            self._note(pid, f"Max {mx} ticket{'s' if mx > 1 else ''} each", "info")
        n = max(0, min(mx, n))
        price, cur = self.rules.ticket_price, self.count(pid)
        bank, seat = self.session.bank, self.session.seat_of(pid)
        if n > cur:
            afford = bank.credits(pid) // price
            if afford <= 0:
                return self._note(pid, "Not enough credits")
            n = min(n, cur + afford)
            bank.stake(pid, (n - cur) * price, round_=self.nonce, game=self.id, seat=seat)
        elif n < cur:
            bank.release(pid, (cur - n) * price, round_=self.nonce, game=self.id, seat=seat)
        if n:
            self.bets[pid] = {"ticket": n * price}
            if self.deadline is None:
                self.deadline = now + self.rules.buy_seconds
        else:
            self.bets.pop(pid, None)
        self.done.discard(pid)
        self.session.changed()
        return None

    def lock(self, now: float | None = None) -> bool:
        if self.phase == "betting" and not any(self.bets.values()):
            self.deadline = None
            return False
        return super().lock(now)

    def on_locked(self, rng: Rng, now: float) -> None:
        order = sorted((p for p, b in self.bets.items() if b), key=self._seat_key)
        holders = [[self.session.seat_of(p) or 0, self.count(p)] for p in order]
        self.outcome = deal(rng, holders)
        k = 0
        for p, (_seat, n) in zip(order, holders, strict=True):
            self.first_ticket[p] = k
            self.tickets[p] = [list(t) for t in self.outcome["tickets"][k : k + n]]
            k += n
        self.pot = sum(self.stake_of(p) for p in order)
        self.rake_taken = self.pot * self.rules.rake // 100
        self.pool = self.pot - self.rake_taken
        self.amounts = prize_amounts(self.rules, self.pool)
        self.next_call_at = now + LOCK_SECONDS + TICKET_BEAT
        self.reveal_at = None

    # ================================================================ calling
    def play_tick(self, now: float) -> None:
        if self.finished or self.next_call_at is None or now < self.next_call_at:
            return
        self._close_claims()
        if not self.open_prizes() or "full" in self.claims or self.called >= 90:
            self.finish(now)
            return
        self.called += 1
        self.last_call_at = now
        step = float(self.rules.call_seconds)
        self.next_call_at = max(self.next_call_at + step, now + step * 0.5)
        self.session.changed()
        if self.rules.auto_claim:
            self._auto_claim(now)

    def _close_claims(self) -> None:
        for st in self.claims.values():
            if st["winners"]:
                st["closed"] = True

    def _auto_claim(self, now: float) -> None:
        called = self.called_set()
        for pid in sorted(self.tickets, key=self._seat_key):
            for prize in PRIZES:
                if prize in self.amounts and self._valid(pid, prize, called):
                    self.claim(pid, prize, None, now, auto=True)

    def _valid(self, pid: str, prize: str, called: frozenset[int]) -> list[int]:
        """The player's tickets that may claim `prize` now."""
        st = self.claims.get(prize)
        if st and st["closed"]:
            return []
        had = {i for p, i in (st or {}).get("winners", []) if p == pid}
        return [
            i
            for i, t in enumerate(self.tickets.get(pid, []))
            if i not in had
            and (pid, i) not in self.void
            and (pid, i, prize) not in self.blocked
            and complete(t, prize, called)
        ]

    def claim(self, pid: str, prize: str, ticket: Any, now: float, auto: bool = False) -> str | None:
        if self.phase != "dealing" or self.finished:
            return self._note(pid, "No game in play" if self.phase != "dealing" else "The game is over")
        if prize not in PRIZE_NAMES:
            return self._note(pid, "Not a prize")
        name = PRIZE_NAMES[prize]
        if prize not in self.amounts:
            return self._note(pid, f"{name} isn't played at this table")
        mine = self.tickets.get(pid)
        if not mine:
            return self._note(pid, "You have no tickets in this game")
        if not self.called:
            return self._note(pid, "No numbers called yet")
        st = self.claims.get(prize)
        if st and st["closed"]:
            who = ", ".join(sorted({self.session.name_of(p) for p, _ in st["winners"]}))
            return self._note(pid, f"{name} already went to {who}")
        t = _int(ticket) if ticket is not None else None
        if t is not None and not 0 <= t < len(mine):
            return self._note(pid, "Not one of your tickets")
        if t is not None and (pid, t) in self.void:
            return self._note(pid, "That ticket is out of the game (bogey)")
        ok = [i for i in self._valid(pid, prize, self.called_set()) if t is None or i == t]
        if not ok:
            if st and any(p == pid and (t is None or i == t) for p, i in st["winners"]):
                return self._note(pid, f"You already have {name}", "info")
            return self._bogey(pid, prize, t, now)
        if st is None:
            st = self.claims[prize] = {"call": self.called, "winners": [], "closed": False}
        for i in ok:
            st["winners"].append([pid, i])
            self.flash = {"prize": prize, "pid": pid, "ticket": i, "at": now}
        if (prize == "full" or not self.open_prizes()) and self.next_call_at is not None:
            self.next_call_at = max(self.next_call_at, now + END_GRACE)
        self._note(pid, f"{name}! Verified on call {self.called}" + (" (auto)" if auto else ""), "info")
        self.session.changed()
        return None

    def _bogey(self, pid: str, prize: str, ticket: int | None, now: float) -> str:
        name = PRIZE_NAMES[prize]
        tix = [ticket] if ticket is not None else list(range(len(self.tickets.get(pid, []))))
        pen = self.rules.bogey
        for i in tix:
            if pen == "prize":
                self.blocked.add((pid, i, prize))
            elif pen == "ticket":
                self.void.add((pid, i))
        self.bogeys.append({"pid": pid, "prize": prize, "ticket": ticket, "at": now, "call": self.called})
        del self.bogeys[:-8]
        self.session.changed()
        extra = {
            "none": "",
            "prize": f" — that ticket can't win {name} now",
            "ticket": " — that ticket is out",
        }[pen]
        return self._note(pid, f"Bogey! {name} isn't complete{extra}")

    def finish(self, now: float) -> None:
        """The game is decided: pay the prizes (ties split per ticket), share back what nobody claimed."""
        if self.finished:
            return
        self._close_claims()
        self.finished = True
        self.awards, self.won, self.returned = {}, {}, 0
        for prize, amount in self.amounts.items():
            ws = (self.claims.get(prize) or {}).get("winners") or []
            if ws:
                for (pid, i), v in zip(ws, split(amount, len(ws)), strict=True):
                    self.awards[pid] = self.awards.get(pid, 0) + v
                    self.won.setdefault(pid, []).append({"prize": prize, "ticket": i, "amount": v})
            else:
                self.returned += amount
        if self.returned:  # nobody claimed it: back to the ticket holders, by tickets
            order = sorted(self.tickets, key=self._seat_key)
            n = sum(len(self.tickets[p]) for p in order)
            base = {p: self.returned * len(self.tickets[p]) // n for p in order}
            odd = self.returned - sum(base.values())
            for i, p in enumerate(order):
                v = base[p] + (1 if i < odd else 0)
                if v:
                    self.awards[p] = self.awards.get(p, 0) + v
        self.next_call_at = None
        self.reveal_at = now + END_BEAT
        self.session.changed()

    # ================================================================ settlement
    def payout(self, pid: str, outcome: dict[str, Any]) -> tuple[int, list[str]]:
        return self.awards.get(pid, 0), [w["prize"] for w in self.won.get(pid, [])]

    def settle(self) -> RoundResult | None:
        if not self.finished:
            return self.result
        return super().settle()

    def abort(self, now: float | None = None) -> None:
        """The table closes: a decided game is paid; an unfinished one is void (every ticket refunded)."""
        now = self.session.clock() if now is None else now
        if self.finished and self.phase != "result":
            self.settle()
        elif self.phase != "result":
            self.refund_all()
        self._reset()
        self.bets, self.done = {}, set()
        self.deadline = self.reveal_at = self.result_until = self.locked_at = None
        self.round = None
        self._set_phase("idle", now)

    def pause_shift(self, dt: float) -> None:
        super().pause_shift(dt)
        if self.next_call_at is not None:
            self.next_call_at += dt
        if self.flash:
            self.flash["at"] += dt
        if self.last_call_at is not None:
            self.last_call_at += dt

    # ================================================================ ops
    def handle(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        cur = self.count(pid)
        if op == "buy":
            return self.buy(pid, _int(payload.get("count", payload.get("tickets"))), now)
        if op == "bet":  # the generic chip ops: one ticket per tap
            if str(payload.get("spot", "ticket")) != "ticket":
                return self._note(pid, "Not a bet on this table")
            return self.buy(pid, cur + 1, now)
        if op == "unbet":
            return self.buy(pid, 0 if payload.get("amount") is None else cur - 1, now)
        if op == "clear":
            return self.buy(pid, 0, now)
        if op == "rebet":
            prev = (self.last_bets.get(pid) or {}).get("ticket", 0)
            if not prev:
                return self._note(pid, "No previous tickets")
            return self.buy(pid, prev // max(1, self.rules.ticket_price), now)
        if op == "done":
            self.mark_done(pid, now)
            return None
        if op.startswith("claim_"):
            return self.claim(pid, op[6:], payload.get("ticket"), now)
        if op == "claim":
            return self.claim(pid, str(payload.get("prize", "")), payload.get("ticket"), now)
        return self._note(pid, f"Unknown move {op!r}")

    host_ops = ("pace",)

    def host_op(self, op: str, payload: dict[str, Any], now: float) -> dict[str, Any]:
        """``pace {seconds}`` (or ``{delta}``): seconds between calls, applied at once."""
        if op != "pace":
            raise KeyError(op)
        cur = int(self.rules.call_seconds)
        s, d = payload.get("seconds"), payload.get("delta")
        want = s if type(s) is int else cur + d if type(d) is int else None
        if want is None:
            raise ValueError("send seconds (or delta) as a whole number")
        lo, hi = 3, 20
        want = max(lo, min(hi, want))
        self.rules = self.rules.model_copy(update={"call_seconds": want})
        if self._pending_rules is not None:
            self._pending_rules = self._pending_rules.model_copy(update={"call_seconds": want})
        if self.next_call_at is not None and self.phase == "dealing" and not self.finished:
            self.next_call_at = min(self.next_call_at, now + want)
        self.session.changed()
        return {"call_seconds": want}

    # ================================================================ state
    def _prize_rows(self, now: float) -> list[dict[str, Any]]:
        amounts = self.amounts or prize_amounts(self.rules, self._pool_estimate())
        shares = prize_shares(self.rules)
        rows = []
        for p in PRIZES:
            if p not in amounts:
                continue
            st = self.claims.get(p) or {}
            ws = st.get("winners") or []
            rows.append(
                {
                    "id": p,
                    "name": PRIZE_NAMES[p],
                    "share": shares.get(p, 0),
                    "amount": amounts[p],
                    "state": "won" if st.get("closed") else "claimed" if ws else "open",
                    "call": st.get("call"),
                    "winners": [
                        {
                            "seat": self.session.seat_of(pid),
                            "name": self.session.name_of(pid),
                            "color": self.color_of(pid),
                            "ticket": i,
                        }
                        for pid, i in ws
                    ],
                }
            )
        return rows

    def _pool_estimate(self) -> int:
        pot = sum(self.stake_of(p) for p in self.bets)
        return pot - pot * self.rules.rake // 100

    def public_state(self, now: float) -> dict[str, Any]:
        out = super().public_state(now)
        playing = self.phase in ("dealing", "result") and self.outcome is not None
        buyers = sorted((p for p, b in self.bets.items() if b), key=self._seat_key)
        pot = self.pot if self.outcome is not None else sum(self.stake_of(p) for p in buyers)
        fl = self.flash
        out["housie"] = {
            "price": self.rules.ticket_price,
            "max": self.rules.max_tickets,
            "pace": self.rules.call_seconds,
            "pot": pot,
            "rake": self.rake_taken if self.outcome is not None else pot * self.rules.rake // 100,
            "sold": sum(self.count(p) for p in buyers),
            "buyers": [
                {
                    "seat": self.session.seat_of(p),
                    "name": self.session.name_of(p),
                    "color": self.color_of(p),
                    "n": self.count(p),
                }
                for p in buyers
            ],
            "prizes": self._prize_rows(now),
            "calls": self.calls() if playing else [],
            "called": self.called if playing else 0,
            "call_in": (
                round(max(0.0, self.next_call_at - now), 1)
                if self.next_call_at is not None and self.phase == "dealing" and not self.finished
                else None
            ),
            "first_in": _left(self.next_call_at, now)
            if self.phase in ("locked", "dealing") and not self.called
            else None,
            "flash": {
                "prize": fl["prize"],
                "name": PRIZE_NAMES[fl["prize"]],
                "seat": self.session.seat_of(fl["pid"]),
                "who": self.session.name_of(fl["pid"]),
                "color": self.color_of(fl["pid"]),
                "age": round(now - fl["at"], 2),
            }
            if fl
            else None,
            "bogeys": [
                {
                    "seat": self.session.seat_of(b["pid"]),
                    "name": self.session.name_of(b["pid"]),
                    "prize": b["prize"],
                    "age": round(now - b["at"], 1),
                }
                for b in self.bogeys[-3:]
            ],
            "finished": self.finished,
            "returned": self.returned,
        }
        return out

    def private_state(self, pid: str, now: float) -> dict[str, Any]:
        out = super().private_state(pid, now)
        mine = self.tickets.get(pid, []) if self.phase in ("dealing", "result") else []
        called = self.called_set()
        claimable = (
            [p for p in PRIZES if p in self.amounts and self._valid(pid, p, called)]
            if self.phase == "dealing" and not self.finished and self.called
            else []
        )
        out["housie"] = {
            "count": self.count(pid),
            "can_buy": self.phase == "betting",
            "tickets": mine,
            "first": self.first_ticket.get(pid, 0),
            "claimable": claimable,
            "ready": {p: self._valid(pid, p, called) for p in claimable},
            "void": sorted(i for p, i in self.void if p == pid),
            "blocked": sorted([i, pr] for p, i, pr in self.blocked if p == pid),
            "won": list(self.won.get(pid, [])),
            "award": self.awards.get(pid, 0) if self.finished else 0,
        }
        if self.phase == "dealing":
            out["ops"] = [f"claim_{p}" for p in claimable]
        elif self.phase == "betting":
            out["ops"] = list(BET_OPS)
        return out
