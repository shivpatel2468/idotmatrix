"""Texas Hold'em on the panel: the pot (hero), the board (five cards, dealt street by street), whose turn it is
(name, stack, and the edge ring as their turn clock in their colour), what just happened (FOLD / CHECK / CALL /
RAISE / ALL-IN flashes) and the showdown: the winning hand's name, its five cards lit on the board, the winner's
hole cards and what they won. Hole cards never reach the panel before a showdown. Phones hold the private side
(their own two cards, the bet slider). Rules: ``deskdot.casino.games.holdem``.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..casino.games._pvp import Player, PvPGame
from ..casino.games.holdem import HAND_LABEL, Holdem
from ..engine import register
from ..gfx import Frame, measure, mix, scale
from . import _cardart as cards
from ._casino import MUTE, WHITE, _rgb
from ._pvpapp import (
    PvPCasinoApp,
    PvPSettings,
    flash_text,
    hand_text,
    name_tab,
    num,
    pot_row,
    seat_colour,
    turn_ring,
    winner_flash,
)

BOARD_X, BOARD_Y = 1, 10
SLOT = (46, 46, 60)  # an empty board slot (lit: the panel's gamma crushes anything darker)
NARROW_W = 5  # board cards are 5×10 at a 6 px pitch so five fit across the panel


class HoldemSettings(PvPSettings):
    small_blind: int = Field(5, ge=1, le=100_000, title="Small blind")
    big_blind: int = Field(10, ge=2, le=200_000, title="Big blind")
    blind_up_every: int = Field(
        0, ge=0, le=100, title="Double the blinds every N hands", description="0 keeps the blinds fixed."
    )
    rake_percent: int = Field(
        0, ge=0, le=10, title="Rake (%)", description="The house's share of each pot at a showdown. 0 = none."
    )
    rake_cap: int = Field(0, ge=0, le=1_000_000, title="Rake cap per hand", description="0 = no cap.")


def board_card(f: Frame, x: int, y: int, code: str | None, hi: bool = False, dim: float = 1.0) -> None:
    if code is None:  # an empty slot: a dim outline
        f.rect(x + 1, y, NARROW_W - 2, 10, SLOT)
        f.rect(x, y + 1, NARROW_W, 8, SLOT)
        f.rect(x + 1, y + 1, NARROW_W - 2, 8, (0, 0, 0))
        return
    cards.narrow(f, x, y, code, hi=hi, dim=dim)


def draw_board(f: Frame, board: list[str], since: float | None, hi: set[str] | None = None,
               dim_rest: bool = False) -> None:  # fmt: skip
    """Five slots; with `since` (seconds into a deal beat) the newest cards drop in one after another."""
    n_new = 0
    if since is not None:
        n_new = 3 if len(board) == 3 else 1 if len(board) in (4, 5) else 0
    for i in range(5):
        x = BOARD_X + i * 6
        code = board[i] if i < len(board) else None
        dy = 0
        if code is not None and since is not None and i >= len(board) - n_new:
            k = (since - 0.15 - 0.22 * (i - (len(board) - n_new))) / 0.3
            if k <= 0:
                board_card(f, x, BOARD_Y, None)
                continue
            dy = -round(8 * (1 - min(1.0, k)) ** 2)
        on = bool(hi and code in hi)
        board_card(f, x, BOARD_Y + dy, code, hi=on, dim=0.55 if (dim_rest and code and not on) else 1.0)


@register
class CasinoHoldem(PvPCasinoApp):
    id = "casino_holdem"
    name = "Texas Hold'em"
    description = (
        "No-limit poker for the party: phones hold the cards, the panel shows the board, pot and turns."
    )
    icon = "spade"
    Game = Holdem
    Settings = HoldemSettings
    title = "HOLD'EM"
    demo_players = 4
    demo_seed = b"casino_holdem-demo-0004000000000"

    # -------------------------------------------------------------- demo bots
    def policy(self, g: PvPGame, p: Player, k: int) -> tuple[str, dict[str, Any]]:
        h: Any = g
        lg = h.legal(p)
        street = h.street
        i = h.players.index(p)
        if street == "preflop":
            if i == (h.bb_i + 1) % len(h.players) and h.cur_bet == h.bb and "raise" in lg["ops"]:
                return "raise", {"amount": 3 * h.bb}
            if i == h.button and len(h.players) > 3:
                return "fold", {}
            return ("call" if "call" in lg["ops"] else "check"), {}
        if street == "flop":
            if h.cur_bet == 0 and i == h.players.index(next(q for q in h.players if q.active)):
                return "check", {}
            if h.cur_bet == 0 and "raise" in lg["ops"]:
                return "raise", {"amount": max(lg["min_to"] or 0, h.pot_total() // 2)}
            return ("call" if "call" in lg["ops"] else "check"), {}
        if street == "river" and h.cur_bet == 0 and i == h.sb_i and "allin" in lg["ops"]:
            return "raise", {"amount": max(lg["min_to"] or 0, h.pot_total())}
        return ("call" if "call" in lg["ops"] else "check"), {}

    def stakes_label(self, snap: dict[str, Any]) -> str:
        b = snap["table"].get("blinds") or [snap["rules"]["small_blind"], snap["rules"]["big_blind"]]
        return f"{num(b[0])}/{num(b[1])}"

    # ------------------------------------------------------------------ hand
    def draw_hand(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        t = snap["table"]
        if t.get("finished"):
            self.draw_showdown(f, snap, now)
            return
        seats = t["seats"]
        dealing = snap["phase"] == "dealing" and not t.get("board")
        pot_row(f, 1, t["pot"], len(t.get("pots") or []), th=self.th)
        if dealing:
            self.draw_deal(f, snap)
            return
        else:
            beat = snap["since"] if snap["phase"] == "dealing" else None
            draw_board(f, t.get("board") or [], beat)
        turn = next((s for s in seats if s["seat"] == t.get("turn_seat")), None)
        fl = t.get("flash")
        if turn is not None:
            c = _rgb(turn["color"])
            name_tab(f, 21, turn["name"], c, num(turn["stack"]))
            turn_ring(f, snap, now)
        elif fl is not None:
            fs = next((s for s in seats if s["seat"] == fl["seat"]), None)
            if fs is not None:
                name_tab(f, 21, fs["name"], _rgb(fs["color"]), num(fs["stack"]))
        if fl is not None and fl["age"] < 1.8 and fl["text"] not in ("SB", "BB"):
            fs = next((s for s in seats if s["seat"] == fl["seat"]), None)
            txt = fl["text"]
            amt = int(fl.get("amount") or 0)
            if txt in ("CALL", "BET", "RAISE", "ALL-IN") and amt:
                txt = f"{txt} {num(amt)}" if measure(f"{txt} {num(amt)}") <= 30 else txt
            flash_text(f, 27, txt, fl["age"])
        else:
            self.status_pips(f, 27, snap, now)

    def draw_deal(self, f: Frame, snap: dict[str, Any]) -> None:
        """Hole cards go out one at a time, round the table twice (faces down, of course)."""
        t = snap["table"]
        seats = t["seats"]
        n = max(1, len(seats))
        dealt = min(2 * n, int(max(0.0, snap["since"] - 0.2) / 0.16) if snap["phase"] == "dealing" else 0)
        for i in range(5):
            board_card(f, BOARD_X + i * 6, BOARD_Y, None)
        # under each player's colour, their two face-down cards arrive one by one
        w = min(6, 31 // n)
        x0 = (32 - (w * n - 1)) // 2
        for j, s in enumerate(seats):
            c = _rgb(s["color"])
            x = x0 + j * w
            got = (dealt // n) + (1 if j < dealt % n else 0)
            f.rect(x, 21, w - 1, 2, c)
            cw = max(1, (w - 2) // 2)
            for k in range(min(2, got)):
                f.rect(x + k * (cw + 1), 25, cw, 4, cards.BACK)
                f.rect(x + k * (cw + 1), 25, cw, 1, cards.BACK_RIM)

    def status_pips(self, f: Frame, y: int, snap: dict[str, Any], now: float) -> None:
        """Everyone in the hand: their colour, dimmed when folded, red underline all-in, the turn blinking,
        and a small dot on the button."""
        t = snap["table"]
        seats = t["seats"]
        n = len(seats)
        w = min(5, 31 // max(1, n))
        x0 = (32 - (w * n - 1)) // 2
        for j, s in enumerate(seats):
            c = _rgb(s["color"])
            x = x0 + j * w
            on = s["turn"] and int(now * 3) % 2 == 0
            col = scale(c, 0.22) if s["folded"] else (mix(c, WHITE, 0.4) if on else c)
            f.rect(x, y, w - 1, 3, col)
            if s["allin"]:
                f.rect(x, y + 4, w - 1, 1, (255, 40, 60))
            elif s["seat"] == t.get("button_seat"):
                f.set(x + (w - 1) // 2, y + 4, WHITE)

    # -------------------------------------------------------------- showdown
    def draw_showdown(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        t = snap["table"]
        ws = t.get("winners") or []
        board = t.get("board") or []
        if not ws:
            draw_board(f, board, None)
            return
        w = ws[0]
        best = set(w.get("best") or [])
        label = HAND_LABEL.get(w.get("hand") or "", "") if w.get("hand") else "WINS"
        hand_text(f, 1, label, self.th.accent)
        draw_board(f, board, None, hi=best, dim_rest=bool(best))
        c = seat_colour(snap, w["seat"])
        name_tab(f, 21, w["name"], c)
        won = w.get("won", w.get("amount", 0))
        txt = f"+{num(won)}" if len(ws) == 1 else f"SPLIT {len(ws)}"
        pulse = 0.6 + 0.4 * math.sin(now * 6)
        f.text_center(27, txt, mix(self.th.accent_dim, self.th.accent, pulse))
        if snap["phase"] == "result":
            winner_flash(f, snap, now, self.th)

    def draw_winner(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        """After the showdown: each winner in turn with their two hole cards, hand name and winnings."""
        t = snap["table"]
        ws = t.get("winners") or []
        if not ws:
            f.text_center(12, "NO HAND", MUTE)
            return
        k = int(max(0.0, snap["since"] - self.table_seconds) / 2.5) % len(ws)
        w = ws[k]
        c = seat_colour(snap, w["seat"])
        shown = (t.get("showdown") or {}).get(str(w["seat"]))
        name_tab(f, 1, w["name"], c)
        if shown:
            best = set(w.get("best") or [])
            cards.card(f, 8, 8, shown[0], hi=shown[0] in best)
            cards.card(f, 17, 8, shown[1], hi=shown[1] in best)
            hand_text(f, 20, HAND_LABEL.get(w.get("hand") or "", ""), self.th.accent, small=False)
        else:
            f.text_center(11, "TAKES", MUTE)
            f.text_center(17, "THE POT", MUTE)
        won = w.get("won", 0)
        f.text_center(26, f"+{num(won)}", self.th.accent)
        winner_flash(f, snap, now, self.th)

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        return str(summary.get("label", "?")), (120, 90, 14)
