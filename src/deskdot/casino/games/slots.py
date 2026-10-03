"""Slots: every player has their own 3-reel, 3-row machine with 5 paylines; the panel plays the spins in turn.

**Machine.** Each reel is an explicit strip of symbols (`STRIPS`); a spin draws one uniform stop per reel from the
spin's provably fair `Rng` — ``rng.randint(0, len(strip) - 1)`` for reel 1, 2, 3 in that order — and the window
shows the symbols at ``stop - 1`` (top row), ``stop`` (middle) and ``stop + 1`` (bottom), wrapping round.
Paylines: 1 = middle row, 2 = top row, 3 = bottom row, 4 = top-left → bottom-right, 5 = bottom-left → top-right;
the host picks 1, 3 or 5 lines. A spin costs *bet per line × lines*; each line pays its best win × bet per line.

**Pay rules** (`Theme`): three of a kind pays `three[s]`; a *group* pays when every symbol on the line is in it
(any mix of 7s, any bars, any ships); a *lead* symbol pays for 1 or 2 in a row from the left (cherries, stars);
the Neon star is *wild* (it stands in for any symbol in a three-of-a-kind or a group; three stars pay their own).

**RTP is computed, not claimed.** Every line sees one uniformly random symbol per reel (the stop is uniform), so a
line's return is the exact average of its pay over every combination of stops; the machine's RTP is the same
whatever the number of lines. `machine_stats()` enumerates all ``len(r1)·len(r2)·len(r3)`` stop combinations
(exact fractions) and the tests check it against a big simulation. The *volatility* preset picks the strip set:
low = frequent small wins, high = rarer, bigger ones; every preset of every theme sits at 95–96.5 % RTP.

**Round machine.** Slots have no shared betting phase: the table stays open (``betting``) and each pull is its own
fair round — the player's *next* spin is sealed (its server-seed hash published to their phone) before they pull;
the pull fixes the client seed, stakes the bet and queues the spin. The panel plays the queue one spin at a time
(`SPIN_STOPS`, then the win), the player's credits settle when the last reel stops, and the seed is revealed.
From the pull until settlement the player's spin is frozen: no second pull, no other bet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
from itertools import product
from typing import Any, Literal

from pydantic import Field

from .. import fair
from ..table import CasinoGame, RoundResult, Rules, Spot, _left, register_game

SPIN_STOPS = (1.5, 2.1, 2.7)  # seconds after the spin starts on the panel when reels 1, 2, 3 stop
HOLD_WIN, HOLD_BIG, HOLD_NONE = 2.6, 4.0, 0.8  # how long the panel shows the result before the next spin
BIG_WIN = 20  # × the spin's stake
BET_STEPS = (1, 2, 5, 10, 25, 50, 100, 250, 500)
LINES: tuple[tuple[int, int, int], ...] = (
    (1, 1, 1),
    (0, 0, 0),
    (2, 2, 2),
    (0, 1, 2),
    (2, 1, 0),
)  # row per reel


@dataclass(frozen=True)
class Theme:
    name: str
    symbols: str  # one character per symbol, best first
    names: dict[str, str]
    three: dict[str, int]  # three of a kind → pays (× bet per line)
    groups: tuple[tuple[str, str, int], ...] = ()  # (label, members, pays) — any mix of the members
    lead: dict[int, int] = field(default_factory=dict)  # n lead symbols from the left → pays
    lead_symbol: str = ""
    wild: str = ""


BLANK = "_"  # an empty stop: pays nothing (classic reels alternate symbols and blanks)

THEMES: dict[str, Theme] = {
    "classic": Theme(
        name="Classic fruits",
        symbols="7XBPOLC",
        names={
            "7": "Seven",
            "X": "Bar",
            "B": "Bell",
            "P": "Plum",
            "O": "Orange",
            "L": "Lemon",
            "C": "Cherry",
            BLANK: "Blank",
        },
        three={"7": 100, "X": 40, "B": 18, "P": 14, "O": 10, "L": 8, "C": 10},
        lead={2: 5, 1: 2},
        lead_symbol="C",
    ),
    "neon": Theme(
        name="Neon 7s",
        symbols="SGRU321",
        names={
            "S": "Star (wild)",
            "G": "Gold 7",
            "R": "Red 7",
            "U": "Blue 7",
            "3": "Triple bar",
            "2": "Double bar",
            "1": "Bar",
            BLANK: "Blank",
        },
        three={"S": 200, "G": 100, "R": 50, "U": 25, "3": 15, "2": 10, "1": 5},
        groups=(("Any 7s", "GRU", 10), ("Any bars", "321", 2)),
        wild="S",
    ),
    "space": Theme(
        name="Space",
        symbols="AURPMCS",
        names={
            "A": "Alien",
            "U": "UFO",
            "R": "Rocket",
            "P": "Planet",
            "M": "Moon",
            "C": "Comet",
            "S": "Star",
            BLANK: "Blank",
        },
        three={"A": 200, "U": 50, "R": 25, "P": 15, "M": 10, "C": 5, "S": 15},
        groups=(("Any ships", "AUR", 4),),
        lead={2: 4, 1: 1},
        lead_symbol="S",
    ),
}

VOLATILITY = ("low", "medium", "high")

# The reel strips: theme → volatility → three strips (reel 1, 2, 3), one character per stop (``_`` = blank).
# Symbol counts were tuned once for each preset's RTP / hit rate, spread evenly round each reel and frozen here:
# these strings ARE the machine. `machine_stats` computes exactly what they pay.
STRIPS: dict[str, dict[str, tuple[str, str, str]]] = {
    "classic": {
        "low": ("OCL_C_COBL_PC7_CXOL_CBC_P", "BCPO_LC_CO_LCBP_CO_7CLXC_", "7C_BOXPLC_C_OCL_BCP_COLC_"),
        "medium": ("OLC_CPXBLC7OPC_LXCBP", "BPCOLCPXCBO_CLP7CX", "7XPBCLOCP_CLXBCOPLC_"),
        "high": ("OL_X7CBXP_7OLX_7BXP", "BPOLX_7CXB_P7OLXC_7X", "7XBPOX7L_XB7POXCL_"),
    },
    "neon": {
        "low": ("321_12_12U1_S321G_21R2_1U", "R21U_312_121_2U13_2S12G1_", "S12_G1U23_R121_12_1U23_121_"),
        "medium": ("_12_31RU_S312G_1R_U", "RU1_231_21R_U31_S21G_", "SR_G1U32_1_R1U_321_"),
        "high": ("_12_31RU_S12G_1R_U", "RU_12_3_1RU_2_S1G_", "S_R_U_1_G31R_2U_1_"),
    },
    "space": {
        "low": ("MCS_SCMRSCPASCUM_SCRSP", "RSCPMSC_SMCSRPSCMAS_CUS", "ASCRMUPSCSMCSRPCSMCS"),
        "medium": ("MCSAUSMRC_PSMCAUSRP", "RPMSCSAMUCRPS_MCSAU", "AURMSPCSMACURSPMCS_"),
        "high": ("M_SCA_U_RP_AM_S_UAR_P", "A_PM_A_CU_RS_P_M_ARU_", "AU_RP_MA_RU_A_CPM_S_"),
    },
}


def line_pay(theme: Theme, a: str, b: str, c: str) -> tuple[int, str]:
    """(pays, what) for one line's three symbols, left to right: the line's best win, or (0, "")."""
    best, what = 0, ""
    syms = (a, b, c)
    w = theme.wild
    real = [s for s in syms if s != w] if w else list(syms)
    if not real:  # three wilds
        return theme.three[w], f"3 {theme.names[w]}"
    if all(s == real[0] for s in real):
        p = theme.three.get(real[0], 0)
        if p > best:
            best, what = p, f"3 {theme.names[real[0]]}"
    for label, members, p in theme.groups:
        if all(s in members for s in real) and p > best:
            best, what = p, label
    if theme.lead_symbol:
        n = 0
        for s in syms:
            if s != theme.lead_symbol:
                break
            n += 1
        p = theme.lead.get(n, 0)
        if p > best:
            best, what = p, f"{n} {theme.names[theme.lead_symbol]}"
    return best, what


def window(strips: tuple[str, str, str], stops: list[int]) -> list[str]:
    """The 3×3 window as three row strings (top, middle, bottom), reel 1 first in each."""
    return ["".join(s[(st + dr) % len(s)] for s, st in zip(strips, stops, strict=True)) for dr in (-1, 0, 1)]


def evaluate(theme_id: str, volatility: str, stops: list[int], lines: int) -> dict[str, Any]:
    """The grid and the winning lines of a spin: pays are × bet per line."""
    theme = THEMES[theme_id]
    grid = window(STRIPS[theme_id][volatility], stops)
    wins = []
    for i, rows in enumerate(LINES[:lines]):
        p, what = line_pay(theme, *(grid[r][k] for k, r in enumerate(rows)))
        if p:
            wins.append({"line": i + 1, "pays": p, "what": what})
    return {"grid": grid, "wins": wins, "pays": sum(w["pays"] for w in wins)}


@lru_cache(maxsize=32)
def machine_stats(theme_id: str, volatility: str) -> dict[str, Any]:
    """Exact per-line statistics by enumerating every stop combination: RTP, hit rate, variance, top pay odds."""
    theme = THEMES[theme_id]
    strips = STRIPS[theme_id][volatility]
    counts = [{s: strip.count(s) for s in set(strip)} for strip in strips]
    n = len(strips[0]) * len(strips[1]) * len(strips[2])
    ev = Fraction(0)
    ev2 = Fraction(0)
    hits = 0
    top = 0
    top_pay = max(theme.three.values())
    for a, b, c in product(*(sorted(cs) for cs in counts)):
        w = counts[0][a] * counts[1][b] * counts[2][c]
        p, _ = line_pay(theme, a, b, c)
        if p:
            hits += w
            ev += Fraction(p * w, n)
            ev2 += Fraction(p * p * w, n)
            if p == top_pay:
                top += w
    var = ev2 - ev * ev
    return {
        "rtp": ev,  # exact (Fraction): expected return per credit staked
        "hit": Fraction(hits, n),
        "variance": var,  # per line, in (bet per line)²
        "combos": n,
        "top_odds": Fraction(top, n),
        "reels": [len(s) for s in strips],
    }


class SlotsRules(Rules):
    theme: Literal["classic", "neon", "space"] = Field("classic", title="Machine")
    volatility: Literal["low", "medium", "high"] = Field("medium", title="Volatility")
    lines: int = Field(5, ge=1, le=5, title="Paylines (1, 3 or 5)")
    bet_per_line: int = Field(1, ge=1, le=500, title="Default bet per line")


@dataclass
class Spin:
    pid: str
    round: fair.Round
    stops: list[int]
    bet: int  # per line
    lines: int
    stake: int
    theme: str
    volatility: str
    pulled_at: float
    start: float | None = None  # when the panel starts this spin
    settled: bool = False
    payout: int = 0
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def nonce(self) -> int:
        return self.round.nonce

    def hold(self) -> float:
        if not self.payout:
            return HOLD_NONE
        return HOLD_BIG if self.payout >= BIG_WIN * self.stake else HOLD_WIN

    def end(self) -> float:
        assert self.start is not None
        return self.start + SPIN_STOPS[-1] + self.hold()


def _lines(n: int) -> int:
    return 5 if n >= 5 else 3 if n >= 3 else 1


@register_game
class Slots(CasinoGame):
    id = "slots"
    name = "Slots"
    Rules = SlotsRules
    spin_seconds = SPIN_STOPS[-1]

    def __init__(self, session: Any, rules: Rules | None = None) -> None:
        super().__init__(session, rules)
        self.queue: list[Spin] = []
        self.sealed: dict[str, fair.Round] = {}  # pid -> the committed round of their next pull
        self.recent: list[Spin] = []  # finished spins, newest last
        self.free_at = 0.0  # when the panel is free for the next spin
        self.last_bet: dict[str, int] = {}

    # ------------------------------------------------------------------ rules
    def spots(self) -> dict[str, Spot]:
        return {}  # no shared betting: a pull is the bet

    @property
    def lines(self) -> int:
        return _lines(int(self.rules.lines))

    def draw(self, rng: fair.Rng) -> dict[str, Any]:
        strips = STRIPS[self.rules.theme][self.rules.volatility]
        return {"stops": [rng.randint(0, len(s) - 1) for s in strips]}

    def stats(self) -> dict[str, Any]:
        return machine_stats(self.rules.theme, self.rules.volatility)

    def edges(self) -> dict[str, float]:
        return {"spin": round(float(1 - self.stats()["rtp"]), 5)}

    def summary(self, outcome: dict[str, Any]) -> dict[str, Any]:
        ev = evaluate(self.rules.theme, self.rules.volatility, list(outcome["stops"]), self.lines)
        return {"label": f"×{ev['pays']}" if ev["pays"] else "–", "tone": "gold" if ev["pays"] else "black"}

    def set_rules(self, rules: Rules) -> None:
        if self.queue:
            self._pending_rules = rules
        else:
            self.rules = rules
            self._pending_rules = None

    # ----------------------------------------------------------------- spins
    def sealed_for(self, pid: str) -> fair.Round:
        """The player's next spin, committed before they pull (its hash is on their phone)."""
        r = self.sealed.get(pid)
        if r is None:
            r = self.sealed[pid] = fair.Round.fresh(self.session.next_nonce())
        return r

    def spin_of(self, pid: str) -> Spin | None:
        return next((s for s in self.queue if s.pid == pid), None)

    def bet_options(self) -> list[int]:
        h = self.session.house
        return [b for b in BET_STEPS if h.min_bet <= b * self.lines <= h.max_bet] or [
            max(1, h.min_bet // self.lines + (1 if h.min_bet % self.lines else 0))
        ]

    def pull(self, pid: str, bet: Any, now: float) -> str | None:
        if self.session.paused:
            return self._note(pid, "The host paused the table")
        if self.spin_of(pid) is not None:
            return self._note(pid, "Your reels are still spinning")
        opts = self.bet_options()
        b = bet if type(bet) is int else self.last_bet.get(pid, int(self.rules.bet_per_line))
        if b not in opts:
            b = max([o for o in opts if o <= b] or [opts[0]])
        stake = b * self.lines
        if not self.session.bank.stake(
            pid, stake, round_=self.sealed_for(pid).nonce, game=self.id, seat=self.session.seat_of(pid)
        ):
            return self._note(pid, "Not enough credits for this bet")
        rnd = self.sealed.pop(pid)
        rng = rnd.lock(self.session.client_seeds())
        outcome = self.draw(rng)
        spin = Spin(
            pid=pid,
            round=rnd,
            stops=outcome["stops"],
            bet=b,
            lines=self.lines,
            stake=stake,
            theme=self.rules.theme,
            volatility=self.rules.volatility,
            pulled_at=now,
        )
        self.last_bet[pid] = b
        self.queue.append(spin)
        self.sealed_for(pid)  # seal the next one at once
        self.tick(now)
        self.session.changed()
        return None

    def game_op(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        if op == "pull":
            return self.pull(pid, payload.get("bet"), now)
        return self._note(pid, f"Unknown move {op!r}")

    def handle(self, pid: str, op: str, payload: dict[str, Any], now: float) -> Any:
        if op in ("bet", "unbet", "clear", "rebet", "done"):
            spin = self.spin_of(pid)
            return self._note(pid, "Your spin is locked in" if spin else "Pull the lever to play")
        return self.game_op(pid, op, payload, now)

    def open_betting(self, now: float | None = None) -> None:
        """The machines are always open: no shared round, no countdown."""
        now = self.session.clock() if now is None else now
        if self._pending_rules is not None and not self.queue:
            self.rules, self._pending_rules = self._pending_rules, None
        self.round = None
        self._set_phase("betting", now)

    def lock(self, now: float | None = None) -> bool:
        return False  # nothing to lock: every pull locks itself

    def tick(self, now: float | None = None) -> None:
        now = self.session.clock() if now is None else now
        if self.session.paused:
            return
        if self.phase == "idle":
            self.open_betting(now)
        for _ in range(64):
            if not self.queue:
                break
            head = self.queue[0]
            if head.start is None:
                head.start = max(now, self.free_at, head.pulled_at)
                self.session.changed()
            if not head.settled and now >= head.start + SPIN_STOPS[-1]:
                self._settle(head)
            if head.settled and now >= head.end():
                self.queue.pop(0)
                self.free_at = head.end()
                self.session.changed()
                continue
            break
        if not self.queue and self._pending_rules is not None:
            self.rules, self._pending_rules = self._pending_rules, None
            self.session.changed()

    def _settle(self, spin: Spin) -> None:
        """Pay one spin exactly once and record it with its revealed seed."""
        if spin.settled:
            return
        spin.settled = True
        ev = evaluate(spin.theme, spin.volatility, spin.stops, spin.lines)
        spin.payout = ev["pays"] * spin.bet
        spin.result = ev
        seat = self.session.seat_of(spin.pid)
        net = self.session.bank.settle(
            spin.pid, spin.stake, spin.payout, round_=spin.nonce, game=self.id, seat=seat
        )
        outcome = {"stops": list(spin.stops)}
        rules_now = self.rules
        self.rules = SlotsRules(theme=spin.theme, volatility=spin.volatility, lines=spin.lines)  # type: ignore[arg-type]
        try:
            res = RoundResult(spin.nonce, outcome, self.summary(outcome))
            res.payouts[spin.pid] = {"stake": spin.stake, "payout": spin.payout, "net": net, "wins": []}
            spin.round.revealed = True
            self.round = spin.round
            self.session.record(self, res)
        finally:
            self.rules = rules_now
            self.round = None
        self.recent.append(spin)
        del self.recent[:-12]
        if spin.payout:
            self._note(spin.pid, f"You won {spin.payout:,}", "result")
        self.session.changed()

    def abort(self, now: float | None = None) -> None:
        """The machine closes: every queued spin was fixed at its pull, so each one is paid now."""
        for spin in list(self.queue):
            self._settle(spin)
        self.queue.clear()
        self.sealed.clear()
        self.round = None
        self._set_phase("idle", self.session.clock() if now is None else now)

    def pause_shift(self, dt: float) -> None:
        super().pause_shift(dt)
        self.free_at += dt
        for s in self.queue:
            if s.start is not None:
                s.start += dt

    # ------------------------------------------------------------------ state
    def now_playing(self, now: float) -> Spin | None:
        """The spin on the panel: the queue's head once it has started, else the last finished one."""
        if self.queue and self.queue[0].start is not None and self.queue[0].start <= now:
            return self.queue[0]
        return None

    def _spin_public(self, s: Spin, now: float) -> dict[str, Any]:
        p = self.session.players.get(s.pid)
        t = now - s.start if s.start is not None else None
        shown = [st if t is not None and t >= SPIN_STOPS[i] else None for i, st in enumerate(s.stops)]
        out: dict[str, Any] = {
            "id": s.nonce,
            "seat": self.session.seat_of(s.pid),
            "name": self.session.name_of(s.pid),
            "color": p.color if p else "#f0f0f0",
            "bet": s.bet,
            "lines": s.lines,
            "stake": s.stake,
            "theme": s.theme,
            "volatility": s.volatility,
            "t": round(t, 2) if t is not None else None,
            "stops": shown,
        }
        if s.settled:
            out["win"] = s.payout
            out["wins"] = s.result.get("wins", [])
        return out

    def public_state(self, now: float) -> dict[str, Any]:
        st = self.stats()
        th = THEMES[self.rules.theme]
        playing = self.now_playing(now)
        return {
            "game": self.id,
            "phase": self.phase,
            "round": None,
            "hash": None,
            "ends_in": None,
            "reveal_in": None,
            "next_in": None,
            "rules": self.rules.model_dump(mode="json"),
            "totals": {},
            "bettors": sorted(self.session.seat_of(s.pid) or 0 for s in self.queue),
            "done": [],
            "machine": {
                "theme": self.rules.theme,
                "volatility": self.rules.volatility,
                "name": th.name,
                "lines": self.lines,
                "strips": list(STRIPS[self.rules.theme][self.rules.volatility]),
                "symbols": th.symbols,
                "names": th.names,
                "three": th.three,
                "groups": [list(g) for g in th.groups],
                "lead": {str(k): v for k, v in th.lead.items()},
                "lead_symbol": th.lead_symbol,
                "wild": th.wild,
                "rtp": round(float(st["rtp"]), 6),
                "hit": round(float(st["hit"]), 6),
                "sd": round(float(st["variance"]) ** 0.5, 3),
                "bets": self.bet_options(),
                "stops_at": list(SPIN_STOPS),
            },
            "playing": self._spin_public(playing, now) if playing else None,
            "queue": [self._spin_public(s, now) for s in self.queue if s is not playing],
            "recent": [self._spin_public(s, now) for s in reversed(self.recent[-6:])],
        }

    def private_state(self, pid: str, now: float) -> dict[str, Any]:
        spin = self.spin_of(pid)
        sealed = self.sealed_for(pid)
        out: dict[str, Any] = {
            "bets": {},
            "staked": spin.stake if spin else 0,
            "last_bets": {},
            "can_bet": False,
            "done": False,
            "ops": [] if spin else ["pull"],
            "can_pull": spin is None and not self.session.paused,
            "bet": self.last_bet.get(pid, int(self.rules.bet_per_line)),
            "sealed": {"round": sealed.nonce, "hash": sealed.hash},
        }
        if spin is not None:
            pos = self.queue.index(spin)
            ahead = self.queue[:pos]
            if spin.start is None:  # waiting: roughly when it will start
                eta = max(now, self.free_at)
                for s in ahead:
                    hold = s.hold() if s.settled else HOLD_WIN
                    eta = (s.start if s.start is not None else max(eta, now)) + SPIN_STOPS[-1] + hold
                out["spin"] = {**self._spin_public(spin, now), "ahead": pos, "starts_in": _left(eta, now)}
            else:
                out["spin"] = {**self._spin_public(spin, now), "ahead": 0, "starts_in": 0}
        last = next((s for s in reversed(self.recent) if s.pid == pid), None)
        if last is not None:
            out["last"] = self._spin_public(last, now)
        return out
