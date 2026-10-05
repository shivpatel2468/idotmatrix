"""Housie (Tambola) on the panel: the buy-in (countdown, the pot, a column of ticket pips per player), then the
caller — the current number big on a ball coloured by its decade, the last three calls under it, the called
count / 90 as a bar, and the prizes still open as pips — and every verified claim flashes in the winner's colour
with chasing bulbs. The result: HOUSIE! for the Full House, then the winners board. Tickets live on the phones.
Rules and the fair draw: ``deskdot.casino.games.housie``.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from pydantic import Field

from ..casino.games.housie import PRIZES, Housie
from ..casino.table import LOCK_SECONDS
from ..engine import Choice, register
from ..gfx import Frame, measure, mix, scale
from ._casino import INK, MUTE, RGB3, WHITE, CasinoApp, CasinoSettings, _rgb, draw_paused, draw_qr, win_flash

HOUSIE_VIEWS = {
    "live": "Live table",
    "demo": "Demo game",
    "betting": "Preview: buy-in",
    "locked": "Preview: tickets dealt",
    "calling": "Preview: calling",
    "claim": "Preview: a claim",
    "result": "Preview: Full House",
    "board": "Preview: winners board",
    "lobby": "Preview: join QR",
    "paused": "Preview: paused",
}
#: the caller's balls, one colour per decade (1–9, 10s … 80s), LED-bright
BALL: tuple[RGB3, ...] = (
    (220, 30, 50),
    (240, 110, 0),
    (200, 160, 0),
    (20, 170, 70),
    (0, 160, 190),
    (40, 90, 230),
    (140, 60, 220),
    (210, 40, 150),
    (120, 120, 140),
)
SHORT = {"early5": "EARLY 5", "top": "TOP", "middle": "MIDDLE", "bottom": "BOTTOM", "corners": "CORNERS",
         "full": "HOUSIE!"}  # fmt: skip
CODE = {"early5": "E5", "top": "TOP", "middle": "MID", "bottom": "BOT", "corners": "4C", "full": "FH"}
FLASH_SECONDS = 2.6
DEMO_COLOURS: tuple[RGB3, ...] = ((0, 200, 255), (255, 60, 90), (80, 255, 120), (255, 200, 0))
DEMO_TICKETS = (3, 1, 2, 2)
# the demo game: buy-in, the lock, 13 calls a second apart, the result
D_BUY, D_CALLS, D_RES = 4.0, 13, 7.0
D_CALL = 1.0
D_EVENTS = {
    4: ("early5", 0),
    8: ("top", 1),
    10: ("corners", 2),
    13: ("full", 0),
}  # shown call -> (prize, player)
D_FULL_AT = 54  # the call count the demo's Full House lands on


def ball_colour(n: int) -> RGB3:
    return BALL[min(8, n // 10)]


class HousieSettings(CasinoSettings):
    view: str = Choice(
        "live",
        HOUSIE_VIEWS,
        title="Panel view",
        group="Preview",
        description="Live plays the real table. The others are a self-playing demo game or one frozen moment of "
        "it, to check the art (no credits move).",
    )
    ticket_price: int = Field(10, ge=1, le=100_000, title="Ticket price (credits)")
    max_tickets: int = Field(3, ge=1, le=6, title="Max tickets per player")
    buy_seconds: int = Field(
        45, ge=10, le=300, title="Buy-in time", description="Seconds to buy tickets, from the first ticket."
    )
    call_seconds: int = Field(
        6,
        ge=3,
        le=20,
        title="Seconds between calls",
        description="The caller's pace (also live from the host bar).",
    )
    rake: int = Field(
        0, ge=0, le=20, title="House rake (%)", description="The house's cut of the pot (0 = friendly)."
    )
    bogey: str = Choice(
        "none",
        {
            "none": "Just rejected",
            "prize": "That ticket can't win that prize",
            "ticket": "That ticket is out",
        },
        title="False claim (bogey)",
        description="What happens when someone claims a prize their ticket hasn't completed.",
    )
    auto_claim: bool = Field(
        False,
        title="Claim for everyone automatically",
        description="The server claims the moment a pattern completes.",
    )
    early5: bool = Field(True, title="Early Five", description="The first five numbers on a ticket.")
    early5_share: int = Field(10, ge=0, le=100, title="Early Five share (%)")
    top: bool = Field(True, title="Top Line", description="All five numbers of the top row.")
    top_share: int = Field(15, ge=0, le=100, title="Top Line share (%)")
    middle: bool = Field(True, title="Middle Line", description="All five numbers of the middle row.")
    middle_share: int = Field(15, ge=0, le=100, title="Middle Line share (%)")
    bottom: bool = Field(True, title="Bottom Line", description="All five numbers of the bottom row.")
    bottom_share: int = Field(15, ge=0, le=100, title="Bottom Line share (%)")
    corners: bool = Field(
        True, title="Four Corners", description="The first and last numbers of the top and bottom rows."
    )
    corners_share: int = Field(10, ge=0, le=100, title="Four Corners share (%)")
    full: bool = Field(True, title="Full House", description="All 15 numbers: the game ends.")
    full_share: int = Field(35, ge=0, le=100, title="Full House share (%)")


def label(f: Frame, y: int, text: str, col: RGB3) -> None:
    """A word as big as fits: the small font, else tiny."""
    f.text_center(y, text, col, font="small" if measure(text, "small") <= 30 else "tiny")


def ticket_icon(f: Frame, x: int, y: int, th: Any, now: float) -> None:
    """A little 3 × 9 ticket (19 × 9): the accent frame and a few lit cells."""
    f.rect(x, y, 19, 9, th.accent_dim)
    f.rect(x + 1, y + 1, 17, 7, INK)
    lit = (0, 3, 5, 7, 10, 11, 14, 17, 20, 22, 24, 26)
    k = int(now * 3) % 27
    for i in range(27):
        r, c = divmod(i, 9)
        if i in lit:
            on = i == k or (i + 5) % 27 == k
            f.rect(x + 1 + c * 2, y + 1 + r * 2 + 1, 1, 1, WHITE if on else th.accent)


@register
class CasinoHousie(CasinoApp):
    id = "casino_housie"
    name = "Housie"
    description = (
        "Tambola / bingo, the Indian way: buy tickets, the caller draws 1-90, claim lines and Full House."
    )
    icon = "grid"
    Game = Housie
    Settings: ClassVar[Any] = HousieSettings
    table_seconds = 3.4
    preview_span = (2.0, 21.0, 6.0)

    # ------------------------------------------------------------------ snapshot
    def live_snap(self, now: float) -> dict[str, Any]:
        g, s = self.game, self.session
        colours = {p.pid: _rgb(p.color) for p in s.players.values()}
        calls = g.calls() if g.phase in ("dealing", "result") else []
        fl = g.flash
        prizes = []
        for p in PRIZES:
            if p in (g.amounts or {}):
                st = g.claims.get(p) or {}
                prizes.append((p, [colours.get(pid, WHITE) for pid, _ in st.get("winners") or []]))
        full = [colours.get(pid, WHITE) for pid, _ in (g.claims.get("full") or {}).get("winners") or []]
        res = g.result if g.phase == "result" else None
        return {
            "phase": g.phase,
            "since": max(0.0, now - g.phase_at),
            "ends_in": (g.deadline - now) if g.deadline is not None else None,
            "bet_span": float(g.rules.buy_seconds),
            "buyers": [
                (colours.get(p, WHITE), g.count(p)) for p in sorted(g.bets, key=g._seat_key) if g.bets[p]
            ],
            "pot": sum(g.stake_of(p) for p in g.bets) if g.outcome is None else g.pot,
            "calls": calls,
            "count": len(calls),
            "call_age": (now - g.last_call_at) if g.last_call_at is not None else 9.0,
            "first_in": (g.next_call_at - now) if g.next_call_at is not None and not g.called else None,
            "prizes": prizes,
            "flash": (fl["prize"], colours.get(fl["pid"], WHITE), s.name_of(fl["pid"]), now - fl["at"])
            if fl
            else None,
            "full": full,
            "winners": [colours.get(p, WHITE) for p, v in res.payouts.items() if v["net"] > 0] if res else [],
            "history": [h for h in s.history if h.get("game") == self.Game.id][-10:],
            "paused": s.paused,
            "lobby": self.lobby_waiting(),
        }

    def demo_snap(self, view: str, t: float) -> dict[str, Any]:
        """The self-playing demo (`demo`) or one frozen moment of it, as a pure function of t."""
        spin = LOCK_SECONDS + D_CALLS * D_CALL
        cycle = D_BUY + spin + D_RES
        k = int(t // cycle) if view == "demo" else 3
        o = self.demo_outcome(k)
        hist = [{"label": str(48 + (i * 7) % 30), "tone": "gold"} for i in range(k - 8, k)]
        ph = {
            "betting": 1.0 + t % 3.0,
            "lobby": 1.0,
            "paused": 2.5,
            "locked": D_BUY + (t % LOCK_SECONDS),
            "calling": D_BUY + LOCK_SECONDS + 5.4 + (t % 1.8),
            "claim": D_BUY + LOCK_SECONDS + 7.2 + (t % 1.6),
            "result": D_BUY + spin + (t % 3.0),
            "board": D_BUY + spin + self.table_seconds + 0.5 + (t % 3.0),
        }.get(view, t % cycle)
        snap: dict[str, Any] = {
            "phase": "betting",
            "since": 0.0,
            "ends_in": None,
            "bet_span": 10.0,
            "buyers": [],
            "pot": 0,
            "calls": [],
            "count": 0,
            "call_age": 9.0,
            "first_in": None,
            "prizes": [(p, []) for p in PRIZES],
            "flash": None,
            "full": [],
            "winners": [],
            "history": hist,
            "paused": view == "paused",
            "lobby": view == "lobby",
        }
        if ph < D_BUY:
            snap["since"] = ph
            snap["ends_in"] = 10.0 - ph if ph > 0.8 else None
            snap["buyers"] = [
                (c, min(n, int(ph * 1.6 + i % 2)))
                for i, (c, n) in enumerate(zip(DEMO_COLOURS, DEMO_TICKETS, strict=True))
            ]
            snap["buyers"] = [b for b in snap["buyers"] if b[1] > 0]
            snap["pot"] = 10 * sum(n for _, n in snap["buyers"])
            return snap
        snap["buyers"] = list(zip(DEMO_COLOURS, DEMO_TICKETS, strict=True))
        snap["pot"] = 10 * sum(DEMO_TICKETS)
        ls = ph - D_BUY
        if ls < LOCK_SECONDS:
            snap["phase"], snap["since"], snap["first_in"] = "locked", ls, 3.0
            return snap
        ct = ls - LOCK_SECONDS
        shown = min(D_CALLS, int(ct / D_CALL) + 1)
        result = ph >= D_BUY + spin
        if result:
            shown = D_CALLS
        counts = [max(1, round(i * D_FULL_AT / D_CALLS)) for i in range(1, shown + 1)]
        calls = list(o["calls"])
        snap["calls"] = [calls[c - 1] for c in counts]
        snap["count"] = counts[-1]
        snap["call_age"] = ct - (shown - 1) * D_CALL
        won: dict[str, list[RGB3]] = {}
        for at, (prize, who) in D_EVENTS.items():
            if at <= shown:
                won[prize] = [DEMO_COLOURS[who]]
                age = (ct - (at - 1) * D_CALL) - 0.5
                if age >= 0 and not result:
                    snap["flash"] = (prize, DEMO_COLOURS[who], ("ASHA", "RAVI", "MEI", "JOE")[who], age)
        snap["prizes"] = [(p, won.get(p, [])) for p in PRIZES]
        if result:
            snap["phase"], snap["since"] = "result", ph - D_BUY - spin
            snap["full"] = [DEMO_COLOURS[0]]
            snap["winners"] = [DEMO_COLOURS[0], DEMO_COLOURS[1], DEMO_COLOURS[2]]
            snap["history"] = [*hist[1:], {"label": str(D_FULL_AT), "tone": "gold"}]
        else:
            snap["phase"], snap["since"] = "dealing", ct
        return snap

    def demo_outcome(self, k: int) -> dict[str, Any]:
        from ..casino import fair

        return self.game.draw(fair.Rng(b"deskdot-casino-demo", "demo", k), [[2, 1]])

    # ------------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        view = self.settings.view
        if view == "live":
            self._live()
            now = self.clock()
            self.game.tick(now)
            s = self.live_snap(now)
        else:
            now = t
            s = self.demo_snap(view, t)
            if s["lobby"]:
                self.lobby_url = self.lobby_url or "http://192.168.1.20:8765/p/K7QX"
        if s["lobby"] and self.lobby_url:
            draw_qr(f, self.lobby_url, self.seats, now)
            return
        f.clear(INK)
        ph = s["phase"]
        if ph in ("idle", "betting"):
            self.draw_buyin(f, s, now)
        elif ph == "locked" or (ph == "dealing" and not s["calls"]):
            self.draw_dealt(f, s, now)
        elif ph == "result" and s["since"] >= self.table_seconds:
            self.draw_winners(f, s, now)
        elif ph == "result":
            self.draw_housie(f, s, now)
        else:
            self.draw_calling(f, s, now)
        if s["paused"]:
            draw_paused(f, self.th)

    # ------------------------------------------------------------------ screens
    def draw_buyin(self, f: Frame, s: dict[str, Any], now: float) -> None:
        th = self.th
        waiting = s["ends_in"] is None
        pulse = 0.5 + 0.5 * math.sin(now * 4)
        f.text_center(1, "HOUSIE", mix(th.accent_dim, th.accent, pulse) if waiting else th.accent)
        if waiting:
            ticket_icon(f, 6, 10 + round(math.sin(now * 2.2)), th, now)
        else:
            left = max(0, math.ceil(s["ends_in"] - 1e-6))
            hurry = left <= 5
            f.text_center(9, str(left), th.alert if hurry and int(now * 4) % 2 == 0 else th.text, font="big")
            frac = max(0.0, min(1.0, s["ends_in"] / max(1.0, s["bet_span"])))
            f.rect(1, 19, 30, 1, th.felt_dark)
            f.rect(1, 19, round(30 * frac), 1, th.alert if hurry else th.accent)
        pot = int(s["pot"])
        if pot:
            txt = f"POT {pot}" if measure(f"POT {pot}") <= 30 else str(pot)
            f.text_center(21, txt, th.accent)
        else:
            f.text_center(21, "TICKETS", MUTE)
        buyers = s["buyers"][:9]
        if buyers:
            x0 = (32 - (len(buyers) * 3 - 1)) // 2
            for i, (c, n) in enumerate(buyers):
                h = min(5, n)
                f.rect(x0 + 3 * i, 31 - h, 2, h, c)
                if n > 5:
                    f.rect(x0 + 3 * i, 26, 2, 1, WHITE)

    def draw_dealt(self, f: Frame, s: dict[str, Any], now: float) -> None:
        th = self.th
        k = min(1.0, s["since"] / 0.3) if s["phase"] == "locked" else 1.0
        f.text_center(2, "TICKETS", scale(th.accent, 0.4 + 0.6 * k))
        f.text_center(8, "DEALT", scale(th.accent, 0.4 + 0.6 * k))
        ticket_icon(f, 6, 15, th, now)
        fi = s["first_in"]
        f.text_center(
            26, f"FIRST {max(1, math.ceil(fi))}" if fi is not None and fi < 9.5 else "GET SET", MUTE
        )

    def draw_calling(self, f: Frame, s: dict[str, Any], now: float) -> None:
        th = self.th
        calls = s["calls"]
        n = calls[-1]
        col = ball_colour(n)
        pop = min(1.0, s["call_age"] / 0.3)
        r = round(5 + 4 * pop)
        f.circle(16, 10, r, col)
        f.circle(16, 10, max(1, r - 2), mix(col, WHITE, 0.08))
        if pop >= 1:
            f.set(12, 4, mix(col, WHITE, 0.6))  # a glint
            f.set(11, 5, mix(col, WHITE, 0.35))
            txt = str(n)
            f.text((32 - measure(txt, "big")) // 2, 6, txt, WHITE, font="big")
        # called so far, top left; the prizes still open, top right
        f.text(1, 1, str(s["count"]), th.text)
        for i, (_p, ws) in enumerate(s["prizes"][:6]):
            f.rect(29, 1 + 2 * i, 2, 1, ws[0] if ws else th.accent_dim)
        # the last three calls before this one
        prev = list(reversed(calls[:-1]))[:3]
        for i, m in enumerate(prev):
            x = 2 + 10 * i
            f.rect(x, 22, 8, 7, scale(ball_colour(m), 0.62 if i == 0 else 0.42))
            t = str(m)
            f.text(x + (8 - measure(t)) // 2, 23, t, WHITE if i == 0 else (200, 200, 200))
        # progress: called / 90
        f.rect(1, 30, 30, 1, th.felt_dark)
        f.rect(1, 30, max(1, round(30 * s["count"] / 90)), 1, th.accent)
        fl = s["flash"]
        if fl is not None and 0 <= fl[3] < FLASH_SECONDS:
            self.draw_claim(f, fl, now)

    def draw_claim(self, f: Frame, fl: tuple[str, RGB3, str, float], now: float) -> None:
        prize, col, who, age = fl
        k = min(1.0, age / 0.2)
        band = scale(col, 0.55 + 0.25 * (0.5 + 0.5 * math.sin(now * 9)))
        f.rect(0, 6, 32, 16, scale(band, k))
        f.rect(0, 6, 32, 1, mix(col, WHITE, 0.4))
        f.rect(0, 21, 32, 1, mix(col, WHITE, 0.4))
        label(f, 8, SHORT[prize], WHITE)
        nm = who.upper()
        while nm and measure(nm) > 30:
            nm = nm[:-1]
        f.text_center(16, nm, mix(col, WHITE, 0.75))
        win_flash(f, now, [col], self.th)

    def draw_housie(self, f: Frame, s: dict[str, Any], now: float) -> None:
        th = self.th
        full = s["full"]
        col = full[0] if full else MUTE
        if full:
            f.rect(1, 6, 30, 15, scale(col, 0.6 + 0.2 * math.sin(now * 6)))
            f.rect(1, 6, 30, 1, mix(col, WHITE, 0.5))
            label(f, 10, "HOUSIE!", WHITE)
            if len(full) > 1:
                f.text_center(23, f"{len(full)} TIE", th.accent)
            win_flash(f, now, full, th)
        else:
            f.text_center(9, "GAME", MUTE)
            f.text_center(15, "OVER", MUTE)
        f.text_center(26, f"CALL {s['count']}", MUTE)

    def draw_winners(self, f: Frame, s: dict[str, Any], now: float) -> None:
        th = self.th
        for i, (p, ws) in enumerate(s["prizes"][:6]):
            x, y = 1 + (i % 2) * 16, 1 + (i // 2) * 7
            bg = ws[0] if ws else (46, 46, 56)
            f.rect(x, y, 14, 6, scale(bg, 0.8) if ws else bg)
            f.text(x + (14 - measure(CODE[p])) // 2, y + 1, CODE[p], WHITE if ws else MUTE)
            if len(ws) > 1:  # a tie: a pip per extra winner
                for j, c in enumerate(ws[1:4]):
                    f.set(x + 13 - 2 * j, y + 5, c)
        self.history_strip(f, 25, s["history"])
        if s["winners"]:
            win_flash(f, now, s["winners"], th)

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        return str(summary.get("label", "?")), scale(self.th.accent, 0.55)
