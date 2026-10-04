"""Blackjack on the panel: the dealer's hand along the top, the player in focus large below — their name in their
colour, the hand total, the cards — with a turn bar that empties as their timer runs, a pip per player along the
bottom edge, and BUST / BJ / WIN flashes. Between turns (the deal, insurance, the dealer's draw, the result) the
focus cycles round the table every two seconds. Blackjack hands are public; the hole card stays face down until
the dealer turns it. Rules live in ``deskdot.casino.games.blackjack``.

The preview views (``demo``, ``spinning`` …) run a real `Blackjack` table on a fake clock with three bot players
playing basic strategy, so what the studio shows is the real rules engine, frame for frame.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..casino import CasinoSession, fair
from ..casino.games.blackjack import Blackjack, BlackjackRules, basic_strategy
from ..casino.table import LOCK_SECONDS
from ..engine import Choice, register
from ..gfx import Frame, fit, measure, mix, scale
from . import _cardart as art
from ._casino import (
    INK,
    RED,
    WHITE,
    CasinoApp,
    CasinoSettings,
    View,
    _rgb,
    draw_no_more_bets,
    draw_paused,
    draw_qr,
    win_flash,
)

FOCUS_SECONDS = 2.0
SLIDE = 0.25
DIMLINE = (52, 52, 66)
BUST = (255, 50, 50)
WINC = (60, 235, 110)
BJ_GOLD = (255, 205, 40)


class BlackjackSettings(CasinoSettings):
    decks: int = Field(6, ge=1, le=8, title="Decks in the shoe")
    penetration: int = Field(
        75,
        ge=50,
        le=90,
        title="Cut card at (% of the shoe)",
        description="A new shoe starts after the cut card.",
    )
    soft17: str = Choice(
        "stand",
        {"stand": "Dealer stands on soft 17 (S17)", "hit": "Dealer hits soft 17 (H17, +0.22 %)"},
        title="Dealer on soft 17",
    )
    blackjack_pays: str = Choice(
        "3:2",
        {"3:2": "Blackjack pays 3:2", "6:5": "Blackjack pays 6:5 (+1.4 % edge)"},
        title="Blackjack pays",
    )
    double_on: str = Choice(
        "any", {"any": "Any first two cards", "9-11": "Hard 9, 10, 11 only"}, title="Double on"
    )
    double_after_split: bool = Field(True, title="Double after split")
    max_splits: int = Field(3, ge=1, le=3, title="Splits per hand", description="3 = up to four hands.")
    surrender: str = Choice("late", {"late": "Late surrender", "none": "No surrender"}, title="Surrender")
    insurance: bool = Field(True, title="Offer insurance (pays 2:1)")
    dealer_peek: bool = Field(
        True,
        title="Dealer peeks for blackjack",
        description="Off = European no-hole-card: a dealer blackjack also takes doubles and splits.",
    )


def _pitch(n: int, room: int) -> int:
    """Card pitch so `n` cards (7 px wide) fit in `room` pixels: 6 (1 px overlap of the blank edge) down to 4."""
    if n <= 1:
        return 6
    return max(3, min(6, (room - 7) // (n - 1)))


def draw_cards(f: Frame, x: int, y: int, cards: list[str], ages: list[float] | None, room: int) -> int:
    """A hand left to right; a new card drops in. Returns the x after the last card."""
    p = _pitch(len(cards), room)
    for i, code in enumerate(cards):
        age = ages[i] if ages else 9.0
        dy = round(-7 * max(0.0, 1 - age / SLIDE) ** 2)
        cx = x + p * i
        art.card(f, cx, y + dy, None if code == "??" else code)
        if i and p < 8:  # overlapping cards: a dark seam keeps them apart
            f.rect(cx, y + dy + 1, 1, 8, (24, 24, 32))
    return x + p * (len(cards) - 1) + 7 if cards else x


def total_label(h: dict[str, Any]) -> str:
    if h.get("bj"):
        return "BJ"
    if not h.get("cards"):
        return ""
    t = int(h.get("total") or 0)
    return str(t)


class _DemoTable:
    """A real blackjack round on a fake clock, played by bots, sampled every 0.1 s (cached per demo round)."""

    STEP = 0.1
    BET = 4.0  # seconds of betting before the lock
    TAIL = 7.0  # the result phase

    def __init__(self, rules: BlackjackRules, k: int) -> None:
        self.t = 0.0
        s = CasinoSession(clock=lambda: self.t)
        bots = [("ADA", "#00c8ff", 2), ("BOB", "#ff3c5a", 3), ("CY", "#50ff78", 4)]
        for name, col, seat in bots:
            s.join(name.lower(), seat, name=name, color=col)
            s.bank.set_credits(name.lower(), 5000)
        g = Blackjack(s, rules)
        s.use(g)
        g.open_betting(0.0)
        seed = f"deskdot-bj-demo-{k}".encode()
        g.round = fair.Round(nonce=k, server_seed=seed, hash=fair.commit(seed))
        for i, (name, _c, _s) in enumerate(bots):
            g.place_bet(name.lower(), "main", (10, 25, 50)[i], 0.0)
        self.frames: list[tuple[str, float, dict[str, Any], float | None, list[tuple[int, int, int]]]] = []
        self.t = self.BET
        g.lock(self.t)
        think = 0.0
        end = None
        while self.t < 60:
            g.tick(self.t)
            if end is not None and g.phase != "result":
                break
            if g.phase == "action":
                if g.stage == "insurance":
                    for pid in list(g.ins_pending):
                        g.handle(pid, "no_insurance", {}, self.t)
                elif g.turn is not None:
                    think += self.STEP
                    if think >= 1.3:
                        pid, i = g.turn
                        h = g.hands[pid][i]
                        mv = basic_strategy(h.cards, g.dealer[0], g.moves(pid), rules)
                        g.handle(pid, mv, {}, self.t)
                        think = 0.0
            left = (g.turn_deadline - self.t) / s.house.turn_seconds if g.turn_deadline is not None else None
            winners = []
            if g.phase == "result" and g.result:
                winners = [_rgb(s.players[p].color) for p, v in g.result.payouts.items() if v["net"] > 0]
            self.frames.append((g.phase, self.t - g.phase_at, g.table_state(self.t), left, winners))
            if g.phase == "result":
                end = end or self.t
                if self.t - end >= self.TAIL:
                    break
            self.t += self.STEP
        self.lock_at = self.BET
        self.length = self.t

    def at(self, t: float) -> tuple[str, float, dict[str, Any], float | None, list[tuple[int, int, int]]]:
        i = max(0, min(len(self.frames) - 1, int((t - self.BET) / self.STEP)))
        return self.frames[i]


@register
class CasinoBlackjack(CasinoApp):
    id = "casino_blackjack"
    name = "Blackjack"
    description = (
        "Blackjack for parties: everyone plays the dealer from their phone; the panel deals the hands."
    )
    icon = "club"
    Game = Blackjack
    Settings = BlackjackSettings
    table_seconds = 3.6

    def __init__(self, ctx: Any, settings: Any) -> None:
        super().__init__(ctx, settings)
        self._demo: dict[tuple[str, int], _DemoTable] = {}

    # ------------------------------------------------------------------ demo
    def demo_outcome(self, k: int) -> dict[str, Any]:
        """A dealer result for the base class's preview history (blackjack rounds aren't a pure draw)."""
        t = (17, 19, 22, 20, 21, 18, 24)[k % 7]
        return {"dealer_total": t, "dealer_bj": k % 9 == 4}

    def demo_table(self, k: int) -> _DemoTable:
        key = (repr(self.game.rules), k)
        d = self._demo.get(key)
        if d is None:
            if len(self._demo) > 2:
                self._demo.clear()
            d = self._demo[key] = _DemoTable(self.game.rules, k)
        return d

    def _demo_frame(self, view: str, t: float) -> tuple[View, dict[str, Any] | None, float | None]:
        hist = [
            {"label": lbl, "tone": tone}
            for lbl, tone in (
                ("19", "black"),
                ("BUST", "gold"),
                ("20", "black"),
                ("BJ", "red"),
                ("17", "black"),
            )
        ]
        if view in ("betting", "paused", "lobby"):
            v = self.demo_view(view, t)
            v.history = hist
            return v, None, None
        k = 3
        if view == "demo":
            d0 = self.demo_table(int(t // 40))
            k = int(t // 40)
            t = t % 40
            if t < d0.BET:
                v = View(
                    phase="betting",
                    since=t,
                    ends_in=d0.BET + 3 - t,
                    bet_span=10.0,
                    history=hist,
                    bettors=[(0, 200, 255), (255, 60, 90), (80, 255, 120)],
                )
                return v, None, None
            if t >= d0.length:
                t = d0.length - 0.01
        d = self.demo_table(k)
        if view == "locked":
            t = d.BET + (t % LOCK_SECONDS)
        elif view == "spinning":  # mid-hand: a player deciding (or the deal)
            turns = [i for i, fr in enumerate(d.frames) if fr[2]["turn"]]
            i = turns[min(len(turns) - 1, int(t / 0.1) % max(1, len(turns)))] if turns else len(d.frames) // 2
            t = d.BET + i * d.STEP
        elif view in ("result", "board"):
            res = [i for i, fr in enumerate(d.frames) if fr[0] == "result"]
            base = 0.0 if view == "result" else self.table_seconds + 0.5
            i = min(len(d.frames) - 1, res[0] + int((base + t % 3.0) / d.STEP)) if res else len(d.frames) - 1
            t = d.BET + i * d.STEP
        phase, since, snap, left, winners = d.at(t)
        v = View(phase=phase, since=since, since_lock=t - d.BET, history=hist, winners=winners, nonce=k)
        return v, snap, left

    # ------------------------------------------------------------------ draw
    def render(self, f: Frame, t: float) -> None:
        view = self.settings.view
        snap: dict[str, Any] | None = None
        left: float | None = None
        if view == "live":
            self._live()
            now = self.clock()
            g = self.game
            g.tick(now)
            v = self.live_view(now)
            if g.phase in ("dealing", "action", "result") and g.order:
                snap = g.table_state(now)
                if g.turn_deadline is not None:
                    left = (g.turn_deadline - now) / max(1, self.session.house.turn_seconds)
                elif g.stage == "insurance" and g.stage_deadline is not None:
                    left = (g.stage_deadline - now) / 12.0
        else:
            now = t
            v, snap, left = self._demo_frame(view, t)
        if v.lobby and self.lobby_url:
            draw_qr(f, self.lobby_url, self.seats, now)
            return
        if v.phase in ("idle", "betting"):
            self.draw_betting(f, v, now)
        elif v.phase == "locked" or snap is None:
            draw_no_more_bets(f, v.since, self.th)
        elif v.phase == "result" and v.since >= self.table_seconds:
            self.draw_board(f, v, now, snap)
        else:
            self.draw_hand(f, v, snap, left, now)
        if v.paused:
            draw_paused(f, self.th)

    def focus(self, snap: dict[str, Any], now: float) -> int:
        seats = snap["seats"]
        if not seats:
            return -1
        turn = snap.get("turn")
        if turn is not None:
            for i, s in enumerate(seats):
                if s["seat"] == turn["seat"]:
                    return i
        return int(now / FOCUS_SECONDS) % len(seats)

    def draw_hand(self, f: Frame, v: View, snap: dict[str, Any], left: float | None, now: float) -> None:
        f.clear(INK)
        d = snap["dealer"]
        # ---- the dealer, along the top
        dl = str(d["total"]) if d["cards"] and not d["bj"] else ("BJ" if d["bj"] else "")
        if d["hole"] and d["cards"]:
            dl = str(d["total"])
        dw = measure(dl, "small") if dl else 0
        draw_cards(f, 1, 1, d["cards"], None, 30 - dw - 1)
        if dl:
            dcol = BUST if d["total"] > 21 else BJ_GOLD if d["bj"] else (190, 190, 205)
            f.text_right(30, 2, dl, dcol, font="small")
        # ---- the player in focus
        i = self.focus(snap, now)
        if i < 0:
            return
        seat = snap["seats"][i]
        col = _rgb(seat["color"])
        turn = snap.get("turn")
        on_turn = turn is not None and turn["seat"] == seat["seat"]
        # separator: the turn timer in the player's colour (or the insurance clock), else a dim rule
        if on_turn and left is not None:
            w = max(0, min(30, round(30 * left)))
            f.rect(1, 12, 30, 1, scale(col, 0.25))
            f.rect(1, 12, w, 1, RED if left < 0.25 and int(now * 4) % 2 == 0 else col)
        elif snap["stage"] == "insurance":
            f.rect(1, 12, 30, 1, scale(self.th.accent, 0.35))
            if left is not None:
                f.rect(1, 12, max(0, min(30, round(30 * left))), 1, self.th.accent)
        else:
            f.rect(1, 12, 30, 1, DIMLINE)
        hands = seat["hands"]
        hi = turn["hand"] if on_turn else 0
        if not on_turn and len(hands) > 1:  # between turns, flip through a split player's hands too
            hi = int(now / (FOCUS_SECONDS / len(hands))) % len(hands)
        h = hands[min(hi, len(hands) - 1)] if hands else {"cards": []}
        name = fit(str(seat["name"]).upper(), 18)
        f.text(1, 14, name, col)
        lbl = total_label(h)
        if snap["stage"] == "insurance":
            lbl = "INS?" if int(now * 2) % 2 == 0 else lbl
        if lbl:
            tc = BJ_GOLD if h.get("bj") else BUST if (h.get("total") or 0) > 21 else WHITE
            if h.get("soft") and lbl.isdigit():
                tc = mix(WHITE, col, 0.35)
            f.text_right(30, 13, lbl, tc, font="small")
        # split hands: one pip each (white = this hand, red = bust), under the name
        if len(hands) > 1:
            for k, hh in enumerate(hands):
                pc = WHITE if k == hi else BUST if hh["status"] == "bust" else scale(col, 0.6)
                f.rect(1 + 4 * k, 20, 3, 1, pc)
        ages = None
        draw_cards(f, 1, 21, h.get("cards", []), ages, 30)
        # flashes over the cards
        st = h.get("status")
        net = seat.get("net")
        if v.phase == "result" and net is not None:
            word, wc = ("WIN", WINC) if net > 0 else ("PUSH", (170, 170, 190)) if net == 0 else ("LOSE", BUST)
            if h.get("bj") and net > 0:
                word, wc = "BJ!", BJ_GOLD
            self.flash(f, word, wc, now)
        elif st == "bust":
            self.flash(f, "BUST", BUST, now)
        elif h.get("bj"):
            self.flash(f, "BJ!", BJ_GOLD, now)
        elif st == "surrender":
            self.flash(f, "GIVE", (170, 170, 190), now)
        # pips: one per player along the bottom edge, the one in focus lit
        n = len(snap["seats"])
        w = n * 3 - 1
        x0 = (32 - w) // 2
        for k, s in enumerate(snap["seats"]):
            c = _rgb(s["color"])
            f.rect(x0 + 3 * k, 31, 2, 1, c if k == i else scale(c, 0.35))
        if v.phase == "result" and v.winners:
            win_flash(f, now, v.winners, self.th)

    def flash(self, f: Frame, word: str, col: tuple[int, int, int], now: float) -> None:
        """A word stamped across the hand: a dark band with the word in small type."""
        w = measure(word, "small") + 4
        x = 31 - w
        pop = 0.75 + 0.25 * math.sin(now * 8)
        f.rect(x, 22, w, 9, (14, 14, 20))
        f.rect(x, 22, w, 1, scale(col, 0.6))
        f.rect(x, 30, w, 1, scale(col, 0.6))
        f.text(x + 2, 23, word, scale(col, pop), font="small")

    def draw_board(self, f: Frame, v: View, now: float, snap: dict[str, Any] | None = None) -> None:  # type: ignore[override]
        """The results board: the dealer's final hand and total, how many won, the history strip."""
        f.clear(INK)
        if snap is not None:
            d = snap["dealer"]
            draw_cards(f, 1, 1, d["cards"], None, 30)
            t = int(d["total"])
            word = "BJ" if d["bj"] else "BUST" if t > 21 else str(t)
            col = BJ_GOLD if d["bj"] else BUST if t > 21 else WHITE
            f.text_center(12, word, col, font="small")
        n = len(v.winners)
        if n:
            f.text_center(19, "WIN" if n == 1 else f"{n} WIN", self.th.accent)
            win_flash(f, now, v.winners, self.th)
        else:
            f.text_center(19, "HOUSE", (140, 140, 160))
        self.history_strip(f, 25, v.history)

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        lbl = str(summary.get("label", "?"))
        tone = summary.get("tone")
        bg = (200, 150, 0) if tone == "gold" else (200, 20, 34) if tone == "red" else (66, 66, 76)
        return lbl, bg
