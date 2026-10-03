"""Panel base for player-vs-player card tables (Hold'em, Teen Patti): players bet against each other, so the
panel shows the *table* — the pot, the board, whose turn it is (the edge ring is their turn clock, in their
colour), what everybody just did, and the showdown — never anybody's hole cards before a showdown.

The panel draws from a **snapshot**: the game's public state plus timing (``phase``, ``since``). Live tables
snapshot the real game every frame; the preview / demo views replay a scripted hand that bots play at a private
table (fixed seed, fixed clock), recorded once per settings change, so previews are deterministic and cheap.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, ClassVar

from ..casino import CasinoSession, fair
from ..casino.games._pvp import Player, PvPGame
from ..casino.table import LOCK_SECONDS
from ..engine import Choice
from ..gfx import Frame, measure, mix, scale
from . import _cardart as cards
from ._casino import (
    GOLD,
    GOLD_DIM,
    INK,
    MUTE,
    WHITE,
    CasinoApp,
    CasinoSettings,
    _rgb,
    draw_paused,
    draw_qr,
    win_flash,
)
from ._kit import PERIMETER

PVP_VIEWS = {
    "live": "Live table",
    "demo": "Demo hand (bots)",
    "betting": "Preview: next hand",
    "locked": "Preview: shuffle",
    "dealing": "Preview: dealing",
    "action": "Preview: a turn",
    "result": "Preview: showdown",
    "board": "Preview: winner",
    "lobby": "Preview: join QR",
    "paused": "Preview: paused",
}

ACTION_RGB: dict[str, tuple[int, int, int]] = {
    "FOLD": (120, 120, 140),
    "PACK": (120, 120, 140),
    "CHECK": (60, 230, 160),
    "CALL": (70, 170, 255),
    "CHAAL": (70, 170, 255),
    "BET": (255, 170, 20),
    "RAISE": (255, 170, 20),
    "ALL-IN": (255, 40, 60),
    "SB": (140, 140, 160),
    "BB": (140, 140, 160),
    "BOOT": (140, 140, 160),
    "SEEN": (40, 220, 255),
    "SHOW": GOLD,
    "SIDE?": (190, 90, 255),
    "REFUSED": (190, 90, 255),
    "SS": (190, 90, 255),
}
DEMO_NAMES = ("ASHA", "RAVI", "MEI", "JOE", "LENA", "OMAR", "KAI", "ZOE")
DEMO_COLOURS = ("#ff3c5a", "#00c8ff", "#50ff78", "#ffc800", "#c864ff", "#ff7419", "#ff8cc8", "#a0f0ff")
STEP = 0.1  # seconds between two recorded demo snapshots


def num(n: int) -> str:
    """Credits as the panel prints them: 980, 9999, 12K, 1.2M (never a decimal for small numbers)."""
    n = int(n)
    if abs(n) < 10_000:
        return str(n)
    if abs(n) < 1_000_000:
        return f"{n // 1000}K"
    v = n / 1_000_000
    return (f"{v:.1f}".rstrip("0").rstrip(".") if v < 10 else str(int(v))) + "M"


class PvPSettings(CasinoSettings):
    view: str = Choice(
        "live",
        PVP_VIEWS,
        title="Panel view",
        group="Preview",
        description="Live plays the real table. The others replay a demo hand played by bots, or freeze one "
        "moment of it, to check the art (no credits move).",
    )


Policy = Callable[[PvPGame, Player, int], tuple[str, dict[str, Any]]]


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def record_demo(
    game_cls: type[PvPGame], rules: Any, players: int, seed: bytes, policy: Policy, cap: float = 90.0
) -> list[dict[str, Any]]:
    """Play one hand with bots at a private table and record a snapshot every STEP seconds (betting → result)."""
    clk = _Clock()
    s = CasinoSession(clock=clk)
    s.house = s.house.model_copy(update={"turn_seconds": 15, "result_seconds": 9, "auto_next": False})
    for i in range(players):
        s.join(f"bot{i}", i + 2, name=DEMO_NAMES[i % len(DEMO_NAMES)], color=DEMO_COLOURS[i % 8])
    g = game_cls(s, rules)
    s.use(g)
    g.open_betting(clk.t)
    g.round = fair.Round(nonce=7, server_seed=seed, hash=fair.commit(seed))
    snaps: list[dict[str, Any]] = []
    last_key: Any = None
    since = 0.0
    moves = 0
    while clk.t < cap:
        g.tick(clk.t)
        if g.phase == "action" and g.turn is not None and moves < 80:
            ss = getattr(g, "sideshow", None)
            key = (g.turn, len(g.log), bool(ss))
            if key != last_key:
                last_key, since = key, clk.t
            elif clk.t - since >= 1.4:  # bots think for a moment, like people
                if ss:
                    g.handle(ss["to"], "accept", {}, clk.t)
                else:
                    p = g.players[g.turn]
                    op, payload = policy(g, p, moves)
                    if g.handle(p.pid, op, payload, clk.t) is not None:
                        for safe in ("check", "call", "chaal", "fold", "pack"):
                            if g.handle(p.pid, safe, {}, clk.t) is None:
                                break
                moves += 1
        snaps.append(snapshot(g, clk.t))
        if g.phase == "result" and clk.t - g.phase_at >= 8.0:
            break
        clk.t = round(clk.t + STEP, 3)
    return snaps


def snapshot(g: PvPGame, now: float) -> dict[str, Any]:
    st = g.public_state(now)
    st["since"] = max(0.0, now - g.phase_at)
    st["paused"] = g.session.paused
    st["players_seated"] = [
        {"seat": p.seat, "color": p.color, "name": p.name}
        for p in g.session.seated()
        if isinstance(p.seat, int)
    ]
    return st


class PvPCasinoApp(CasinoApp):
    Settings: ClassVar[Any] = PvPSettings
    Game: ClassVar[type[PvPGame]]
    table_seconds = 3.6
    demo_players: ClassVar[int] = 4
    demo_seed: ClassVar[bytes] = b"deskdot-pvp-demo-seed-0000000000"
    title: ClassVar[str] = "TABLE"

    def __init__(self, ctx: Any, settings: Any) -> None:
        super().__init__(ctx, settings)
        self._demo: list[dict[str, Any]] | None = None
        if self.settings.view != "live":
            self.demo()

    def on_settings(self) -> None:
        super().on_settings()
        self._demo = None
        if self.settings.view != "live":
            self.demo()

    # -------------------------------------------------------------- demo
    def policy(self, g: PvPGame, p: Player, k: int) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    def demo(self) -> list[dict[str, Any]]:
        if self._demo is None:
            self._demo = record_demo(self.Game, self._rules(), self.demo_players, self.demo_seed, self.policy)
        return self._demo

    def demo_snap(self, view: str, t: float) -> dict[str, Any]:
        snaps = self.demo()
        if view == "demo":
            return snaps[int((t % (len(snaps) * STEP)) / STEP) % len(snaps)]
        want = {"betting": "betting", "lobby": "betting", "paused": "betting", "locked": "locked",
                "dealing": "dealing", "action": "action", "result": "result", "board": "result"}[view]  # fmt: skip
        idx = [i for i, s in enumerate(snaps) if s["phase"] == want]
        if not idx:
            return snaps[-1]
        if view == "action":  # a turn a little into the hand (the flop is out), looping a few seconds
            later = [i for i in idx if len(snaps[i]["table"].get("board") or []) >= 3] or idx
            start = later[min(len(later) - 1, 12)]
            seg = [i for i in idx if i >= start][:40]
        elif view == "board":
            seg = [i for i in idx if snaps[i]["since"] >= self.table_seconds + 0.2][:30] or idx[-30:]
        elif view == "dealing":
            seg = idx[:20]
        else:
            seg = idx[:30]
        s = dict(snaps[seg[int(t / STEP) % len(seg)]])
        if view == "paused":
            s["paused"] = True
        if view == "lobby":
            s["lobby"] = True
        return s

    # -------------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        view = self.settings.view
        if view == "live":
            self._live()
            now = self.clock()
            self.game.tick(now)
            snap = snapshot(self.game, now)  # type: ignore[arg-type]
            snap["lobby"] = self.lobby_waiting()
        else:
            now = t
            snap = self.demo_snap(view, t)
            if snap.get("lobby"):
                self.lobby_url = self.lobby_url or "http://192.168.1.20:8765/p/K7QX"
        if snap.get("lobby") and self.lobby_url:
            draw_qr(f, self.lobby_url, self.seats, now)
            return
        f.clear(INK)
        ph = snap["phase"]
        if ph in ("idle", "betting"):
            self.draw_lobby(f, snap, now)
        elif ph == "locked":
            draw_shuffle(f, snap["since"], self.title)
        elif ph == "result":
            if snap["since"] < self.table_seconds:
                self.draw_showdown(f, snap, now)
            else:
                self.draw_winner(f, snap, now)
        else:
            self.draw_hand(f, snap, now)
        if snap.get("paused"):
            draw_paused(f)

    # ------------------------------------------------------- shared screens
    def draw_lobby(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        """Between hands: the game's name, the stakes, who's in, and the deal countdown."""
        f.text_center(1, self.title, GOLD)
        f.text_center(8, self.stakes_label(snap), MUTE)
        seated = snap.get("players_seated") or []
        sitting = set(snap.get("sitting") or [])
        ends = snap.get("ends_in")
        if ends is not None:
            f.text_center(14, str(ends), WHITE, font="big")
        else:
            need = max(0, 2 - len(sitting))
            pulse = 0.5 + 0.5 * math.sin(now * 4)
            f.text_center(15, "WAITING", mix(GOLD_DIM, GOLD, pulse))
            f.text_center(21, f"{need} MORE" if need else "READY", MUTE)
        seat_pips(f, 27, [(_rgb(p["color"]), p["seat"] in sitting) for p in seated])

    def stakes_label(self, snap: dict[str, Any]) -> str:
        return ""

    def draw_hand(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        raise NotImplementedError

    def draw_showdown(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        self.draw_hand(f, snap, now)

    def draw_winner(self, f: Frame, snap: dict[str, Any], now: float) -> None:
        raise NotImplementedError


# =========================================================================== shared art
def seat_colour(snap: dict[str, Any], seat: Any) -> tuple[int, int, int]:
    for s in snap["table"]["seats"]:
        if s["seat"] == seat:
            return _rgb(s["color"])
    return WHITE


def chip_icon(f: Frame, x: int, y: int) -> None:
    """A 5×5 gold chip."""
    f.rect(x + 1, y, 3, 5, GOLD)
    f.rect(x, y + 1, 5, 3, GOLD)
    f.set(x + 2, y + 2, (120, 70, 0))


def pot_row(f: Frame, y: int, amount: int, pots: int = 1, col: tuple[int, int, int] = GOLD) -> None:
    """The pot as the screen's hero: a chip and the amount in the small font (compact when long)."""
    txt = num(amount)
    font = "small" if measure(txt, "small") <= 23 else "tiny"
    w = 6 + measure(txt, font)
    x = (32 - w) // 2
    chip_icon(f, x, y + (1 if font == "small" else 0))
    f.text(x + 6, y, txt, col, font=font)
    if pots > 1:  # side pots: one dot per pot under the amount
        x0 = 16 - pots
        for i in range(pots):
            f.set(x0 + 2 * i, y + 8, GOLD_DIM)


def seat_pips(f: Frame, y: int, pips: list[tuple[tuple[int, int, int], bool]]) -> None:
    """One 2×2 pip per seated player (lit = in the hand / sitting in)."""
    n = len(pips)
    if not n:
        return
    w = n * 3 - 1
    x = (32 - w) // 2
    for i, (c, on) in enumerate(pips):
        f.rect(x + 3 * i, y, 2, 2, c if on else scale(c, 0.25))


def turn_ring(f: Frame, snap: dict[str, Any], now: float) -> None:
    """The edge ring counts down the player to act, in their colour."""
    t = snap["table"]
    seat = t.get("turn_seat")
    if seat is None or t.get("turn_in") is None:
        return
    span = max(1.0, float(t.get("turn_span") or 20))
    left = float(t["turn_in"])
    c = seat_colour(snap, seat)
    hurry = left <= 5
    if hurry and int(now * 4) % 2:
        c = scale(c, 0.45)
    n = len(PERIMETER)
    lit = round(n * max(0.0, min(1.0, left / span)))
    for i, (x, y) in enumerate(PERIMETER):
        f.set(x, y, c if i < lit else scale(c, 0.18))


def name_tab(f: Frame, y: int, name: str, col: tuple[int, int, int], right: str = "",
             right_col: tuple[int, int, int] = MUTE) -> None:  # fmt: skip
    """A colour tab, the player's name, and a value right-aligned (their stack)."""
    f.rect(1, y, 1, 5, col)
    rw = measure(right) if right else 0
    room = 30 - 3 - (rw + 2 if right else 0)
    nm = name.upper()
    while nm and measure(nm) > room:
        nm = nm[:-1]
    f.text(3, y, nm, mix(col, WHITE, 0.55))
    if right:
        f.text_right(30, y, right, right_col)


def hand_text(f: Frame, y: int, text: str, col: tuple[int, int, int], small: bool = True) -> None:
    """A hand name, as big as fits in 30 px: small font, else tiny, else tiny with 1 px "I"s (STRAIGHT)."""
    if small and measure(text, "small") <= 30:
        f.text_center(y, text, col, font="small")
        return
    if measure(text) <= 30:
        f.text_center(y, text, col)
        return
    w = sum(1 if ch == "I" else measure(ch) for ch in text) + len(text) - 1
    x = (32 - w) // 2
    for ch in text:
        if ch == "I":
            f.rect(x, y, 1, 5, col)
            x += 2
        else:
            x = f.text(x, y, ch, col) + 1


def flash_text(f: Frame, y: int, text: str, age: float) -> None:
    """The latest move, popping in (white for a beat, then its colour)."""
    word = text.split(" ")[0]
    col = ACTION_RGB.get(word, ACTION_RGB.get(text, WHITE))
    k = min(1.0, age / 0.25)
    f.text_center(y, text, mix(WHITE, col, k))


def draw_shuffle(f: Frame, since: float, title: str) -> None:
    """The lock beat: the dealer riffles the deck."""
    f.text_center(2, title, GOLD)
    k = min(1.0, since / LOCK_SECONDS)
    sp = round(4 * math.sin(k * math.pi * 3))
    cards.back(f, 8 - abs(sp), 12)
    cards.back(f, 17 + abs(sp), 12)
    cards.back(f, 12 + (1 if sp > 0 else 0), 11 + (1 if sp < 0 else 0))
    f.text_center(25, "SHUFFLE", MUTE)


def winner_flash(f: Frame, snap: dict[str, Any], now: float) -> None:
    ws = snap["table"].get("winners") or []
    win_flash(f, now, [seat_colour(snap, w["seat"]) for w in ws])
