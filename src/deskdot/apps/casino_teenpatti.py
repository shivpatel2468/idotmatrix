"""Teen Patti on the panel: the pot (hero), the current stake, every player in the hand as a colour bar with a
B (blind) / S (seen) marker — packed players fade, the player to act gets a gold caret and the edge ring as their
turn clock — the latest move (CHAAL 20, RAISE, PACK, SEEN, SIDE?, SHOW …), and the show: both hands face up, the
winner lit. Cards stay hidden until a show. Rules: ``deskdot.casino.games.teenpatti``.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field

from ..casino.games._pvp import Player, PvPGame
from ..casino.games.teenpatti import TP_LABEL, TeenPatti
from ..engine import register
from ..gfx import Frame, measure, mix, scale
from . import _cardart as cards
from ._casino import GOLD, GOLD_DIM, MUTE, WHITE, _rgb
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

SEEN_RGB = (40, 220, 255)
BLIND_RGB = (150, 150, 170)
STAKE_RGB = (255, 170, 20)


class TeenPattiSettings(PvPSettings):
    boot: int = Field(
        10, ge=1, le=100_000, title="Boot (ante)", description="Everyone's entry into each pot."
    )
    chaal_limit: int = Field(
        1280, ge=1, le=10_000_000, title="Chaal limit", description="The largest the stake may grow to."
    )
    pot_limit: int = Field(
        10240, ge=2, le=100_000_000, title="Pot limit", description="When the pot reaches it, everyone shows."
    )
    max_blind_rounds: int = Field(
        4, ge=1, le=20, title="Blind bets before you must see", description="Then your cards open."
    )


def crown(f: Frame, x: int, y: int) -> None:
    """A 7×4 gold crown: the winning hand."""
    for j, r in enumerate(("#..#..#", "##.#.##", "#######", "#######")):
        for i, ch in enumerate(r):
            if ch == "#":
                f.set(x + i, y + j, GOLD)


@register
class CasinoTeenPatti(PvPCasinoApp):
    id = "casino_teenpatti"
    name = "Teen Patti"
    description = (
        "Three-card Indian poker: play blind or seen, chaal, raise, sideshow and show from your phone."
    )
    icon = "spade"
    Game = TeenPatti
    Settings = TeenPattiSettings
    title = "3 PATTI"
    demo_players = 4
    demo_seed = b"casino_teenpatti-demo-0006000000"

    def policy(self, g: PvPGame, p: Player, k: int) -> tuple[str, dict[str, Any]]:
        tp: Any = g
        i = tp.players.index(p)
        lg = tp.legal(p, i)
        ops = lg["ops"]
        if i == 1 and p.pid not in tp.seen:
            tp.handle(p.pid, "see", {}, tp.session.clock())
            lg = tp.legal(p, i)
            ops = lg["ops"]
        if i == 2 and k >= 4:
            return "pack", {}
        if "show" in ops and k >= 8:
            return "show", {}
        if "sideshow" in ops and k >= 6:
            return "sideshow", {}
        if i == 0 and k == 0 and "raise" in ops:
            return "raise", {}
        if i == 3 and k >= 3 and p.pid not in tp.seen:
            tp.handle(p.pid, "see", {}, tp.session.clock())
        return "chaal", {}

    def stakes_label(self, snap: dict[str, Any]) -> str:
        return f"BOOT {num(snap['rules']['boot'])}"

    # ------------------------------------------------------------------ hand
    def draw_hand(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        t = snap["table"]
        if t.get("finished") and t.get("end") in ("show", "limit", "allin"):
            self.draw_showdown(f, snap, now)
            return
        pot_row(f, 1, t["pot"])
        stake = int(t.get("stake") or 0)
        txt = f"STAKE {num(stake)}"
        if measure(txt) > 30:
            txt = f"STK {num(stake)}"
        f.text_center(9, txt, STAKE_RGB)
        self.players_row(f, 16, snap, now)
        seats = t["seats"]
        fl = t.get("flash")
        ss = t.get("sideshow")
        turn = next((s for s in seats if s["seat"] == t.get("turn_seat")), None)
        if ss and turn is not None:
            # a sideshow question: the asked player's clock runs
            name_tab(f, 21 + 6, turn["name"], _rgb(turn["color"]), "SS?", (190, 90, 255))
            turn_ring(f, snap, now)
            return
        if fl is not None and fl["age"] < 1.8 and fl["text"] != "BOOT":
            fs = next((s for s in seats if s["seat"] == fl["seat"]), None)
            text = fl["text"]
            if text in ("CHAAL", "RAISE", "SHOW", "ALL-IN") and fs is not None:
                amt = int(fl.get("amount") or 0)
                full = f"{text} {num(amt)}" if amt else text
                text = full if measure(full) <= 30 else text
            flash_text(f, 27, text, fl["age"])
        elif turn is not None:
            name_tab(f, 27, turn["name"], _rgb(turn["color"]), num(turn["stack"]))
        if turn is not None:
            turn_ring(f, snap, now)
        if t.get("finished"):
            winner_flash(f, snap, now)

    def players_row(self, f: Frame, y: int, snap: dict[str, Any], now: float) -> None:
        """Every player in the hand: a colour bar; under it B (blind) or S (seen); packed players fade; the player
        to act has a gold caret above their bar."""
        t = snap["table"]
        seats = t["seats"]
        n = max(1, len(seats))
        w = min(6, 31 // n)
        x0 = (32 - (w * n - 1)) // 2
        for j, s in enumerate(seats):
            c = _rgb(s["color"])
            x = x0 + j * w
            bw = w - 1
            packed = s["folded"]
            f.rect(x, y + 1, bw, 3, scale(c, 0.22) if packed else c)
            if s["seat"] == t.get("turn_seat") and not packed:
                pulse = 0.55 + 0.45 * math.sin(now * 6)
                f.rect(x, y - 1, bw, 1, mix(GOLD_DIM, GOLD, pulse))
            mark = "X" if packed else "S" if s.get("seen") else "B"
            col = (90, 90, 104) if packed else SEEN_RGB if s.get("seen") else BLIND_RGB
            if bw >= 3:
                f.text(x + (bw - 3) // 2, y + 5, mark, col)
            elif not packed and s.get("seen"):
                f.rect(x, y + 6, bw, 2, SEEN_RGB)
            if s.get("dealer"):
                f.set(x + bw // 2, y + 11, WHITE)
            if s["allin"]:
                f.rect(x, y + 11, bw, 1, (255, 40, 60))

    # -------------------------------------------------------------- showdown
    def draw_showdown(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        t = snap["table"]
        ws = t.get("winners") or []
        shown = t.get("showdown") or {}
        if not shown:  # everybody else packed: no cards are shown
            self.draw_winner(f, snap, now)
            return
        win_seats = {w["seat"] for w in ws}
        seats = [s for s in t["seats"] if str(s["seat"]) in shown]
        # the winner first, then (for a two-player show) the other hand
        seats.sort(key=lambda s: (s["seat"] not in win_seats, str(s["seat"])))
        for row, s in enumerate(seats[:2]):
            y = 1 + row * 12
            win = s["seat"] in win_seats
            hand = shown[str(s["seat"])]
            for i, code in enumerate(hand):
                cards.narrow(f, 1 + i * 6, y, code, hi=win, dim=1.0 if win else 0.6)
            c = _rgb(s["color"])
            nm = s["name"].upper()
            while nm and measure(nm) > 11:
                nm = nm[:-1]
            f.text_right(30, y + 1, nm, mix(c, WHITE, 0.35))
            if win:
                crown(f, 22, y + 7)
        w = ws[0] if ws else None
        if w:
            hand_text(f, 26, TP_LABEL.get(w.get("hand") or "", ""), GOLD, small=False)
        if snap["phase"] == "result":
            winner_flash(f, snap, now)

    def draw_winner(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        t = snap["table"]
        ws = t.get("winners") or []
        if not ws:
            f.text_center(12, "NO HAND", MUTE)
            return
        w = ws[0]
        c = seat_colour(snap, w["seat"])
        name_tab(f, 1, w["name"], c)
        shown = (t.get("showdown") or {}).get(str(w["seat"]))
        if shown:
            for i, code in enumerate(shown):
                cards.card(f, 5 + i * 8, 8, code, hi=True)
            hand_text(f, 20, TP_LABEL.get(w.get("hand") or "", ""), GOLD, small=False)
        else:
            pot_row(f, 9, int(w.get("won") or 0))
            f.text_center(19, "ALL PACKED", MUTE)
        f.text_center(26, f"+{num(int(w.get('amount') or 0))}", GOLD)
        winner_flash(f, snap, now)

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        return str(summary.get("label", "?")), (120, 90, 14)
