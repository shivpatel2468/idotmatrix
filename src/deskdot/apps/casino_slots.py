"""Slots on the panel: the reels of whoever pulled, in turn — the player's name in their colour on top, three reels
of original pixel symbols (Classic fruits, Neon 7s, Space) spinning fast and stopping one after the other (with a
small overshoot and settle) exactly on the spin's provably fair stops, then the winning lines flashing gold, the
win in big digits and a burst of coins. Spins queue when several players pull; pips top-right show who is
waiting. With nobody spinning the machine shows its last result and a blinking PULL. Rules live in
``deskdot.casino.games.slots``.
"""

from __future__ import annotations

import math
import time
from functools import lru_cache
from typing import Any

from ..casino import fair
from ..casino.games.slots import BIG_WIN, LINES, SPIN_STOPS, STRIPS, Slots, evaluate
from ..engine import Choice, register
from ..gfx import Frame, Sprite, fit, mix, scale
from ._casino import GOLD, INK, WHITE, CasinoApp, CasinoSettings, View, _rgb, draw_paused, draw_qr, win_flash

CELL_W, CELL_H = 9, 8
REEL_X = (2, 12, 22)
WIN_Y0 = 7  # the window: rows at y 7, 15, 23 (to 30)
REEL_BG = (30, 26, 44)
REEL_EDGE = (70, 56, 96)

_P = {
    "r": (240, 30, 40),
    "R": (150, 10, 20),
    "g": (40, 210, 70),
    "G": (20, 120, 40),
    "y": (255, 220, 30),
    "o": (255, 130, 20),
    "p": (170, 60, 230),
    "w": (235, 235, 235),
    "s": (150, 150, 170),
    "k": (60, 60, 76),
    "b": (40, 120, 255),
    "c": (30, 220, 230),
    "m": (255, 60, 200),
    "l": (150, 255, 60),
    "t": (220, 170, 90),
    "Y": (255, 240, 150),
    "B": (25, 60, 200),
}


def _sp(rows: str, **over: tuple[int, int, int]) -> Sprite:
    pal = {**_P, **over}
    return Sprite.parse(rows.split(), {k: v for k, v in pal.items()})


SEVEN = """
yyyyyyy
yyyyyyy
....yy.
...yy..
..yy...
..yy...
..yy...
"""
SYMBOLS: dict[str, dict[str, Sprite]] = {
    "classic": {
        "7": _sp(SEVEN, y=(240, 30, 40)),
        "X": _sp(""".......
wwwwwww
wkkkkkw
wkwkwkw
wkkkkkw
wwwwwww
......."""),
        "B": _sp("""...y...
..yyy..
.yyyyy.
.yyyyy.
.yyyyy.
yyyyyyy
...o..."""),
        "P": _sp("""...g...
..ppp..
.ppppp.
ppppppp
ppppppp
.ppppp.
..ppp.."""),
        "O": _sp("""....gg.
.ooooo.
ooooooo
ooooooo
ooooooo
.ooooo.
..ooo.."""),
        "L": _sp(""".......
..yyy..
.yyyyy.
yyyyyyy
.yyyyy.
..yyy..
......."""),
        "C": _sp("""....g..
...g.g.
..g...g
.g....g
rr...rr
rr...rr
......."""),
    },
    "neon": {
        "S": _sp("""...y...
...y...
yyyyyyy
.yyyyy.
..yyy..
.yy.yy.
.y...y."""),
        "G": _sp(SEVEN, y=(255, 200, 30)),
        "R": _sp(SEVEN, y=(255, 40, 60)),
        "U": _sp(SEVEN, y=(40, 140, 255)),
        "3": _sp("""mmmmmmm
.......
mmmmmmm
.......
mmmmmmm
.......
......."""),
        "2": _sp("""ccccccc
ccccccc
.......
ccccccc
ccccccc
.......
......."""),
        "1": _sp(""".......
lllllll
lllllll
lllllll
.......
.......
......."""),
    },
    "space": {
        "A": _sp(""".g...g.
..ggg..
.ggggg.
gg.g.gg
ggggggg
.g.g.g.
g.....g"""),
        "U": _sp("""..ccc..
.ccccc.
sssssss
sysysys
.sssss.
.......
......."""),
        "R": _sp("""...w...
..www..
..wbw..
..www..
..www..
.rwwwr.
.r.o.r."""),
        "P": _sp("""..ooo..
.ooooo.
ttttttt
.ooooo.
..ooo..
.......
......."""),
        "M": _sp("""..YYY..
.YY....
YY.....
YY.....
YY.....
.YY....
..YYY.."""),
        "C": _sp("""....ccc
...cccc
..ccc..
.bb....
bb.....
b......
......."""),
        "S": _sp("""...y...
..yyy..
yyyyyyy
.yyyyy.
..y.y..
.y...y.
......."""),
    },
}
THEME_ACCENT = {"classic": (255, 60, 70), "neon": (255, 60, 220), "space": (40, 220, 230)}


@lru_cache(maxsize=8)
def sprite_table(theme: str) -> dict[str, Any]:
    """The theme's symbols for the phone (the same pixels as the panel): a palette and one row string per sprite
    row, each character an index into the palette (base 36) or '.' for an unlit pixel."""
    pal: list[str] = []
    out: dict[str, list[str]] = {}
    for ch, sp in SYMBOLS[theme].items():
        rows = []
        for j in range(sp.mask.shape[0]):
            row = ""
            for i in range(sp.mask.shape[1]):
                if not sp.mask[j, i]:
                    row += "."
                    continue
                hexc = "#{:02x}{:02x}{:02x}".format(*tuple(int(v) for v in sp.px[j, i]))
                if hexc not in pal:
                    pal.append(hexc)
                row += "0123456789abcdefghijklmnopqrstuvwxyz"[pal.index(hexc)]
            rows.append(row)
        out[ch] = rows
    return {"palette": pal, "symbols": out}


def reel_pos(stop: int, n: int, t: float, i: int) -> float:
    """Where reel `i` shows (a float strip index for the middle row) `t` s after the spin starts. It runs fast,
    then eases into `stop` at SPIN_STOPS[i] with a one-row-third overshoot that settles back."""
    T = SPIN_STOPS[i]
    travel = 3 * n + 4 * i  # whole turns: the reel lands where the stop says, whatever the start
    if t <= 0:
        return float(stop - travel)
    if t < T:
        u = t / T
        ease = 1 - (1 - u) ** 3
        return stop - travel * (1 - ease) + 0.35 * math.sin(math.pi * min(1.0, u * 1.0) ** 8)
    k = t - T
    return stop + 0.3 * math.exp(-k * 9) * math.sin(k * 26)  # the settle wobble


class SlotsSettings(CasinoSettings):
    theme: str = Choice(
        "classic", {"classic": "Classic fruits", "neon": "Neon 7s", "space": "Space"}, title="Machine theme"
    )
    volatility: str = Choice(
        "medium",
        {"low": "Low: frequent small wins", "medium": "Medium", "high": "High: rarer, bigger wins"},
        title="Volatility",
        description="Picks the reel-strip set. Every preset's RTP (≈95–96 %) is computed exactly and shown.",
    )
    lines: str = Choice(
        "5",
        {"1": "1 line (middle row)", "3": "3 lines (the rows)", "5": "5 lines (rows + diagonals)"},
        title="Paylines",
    )
    bet_per_line: str = Choice(
        "1",
        {"1": "1", "2": "2", "5": "5", "10": "10", "25": "25"},
        title="Default bet per line",
        description="Players pick their own bet per line on the phone; this is where it starts.",
    )


@register
class CasinoSlots(CasinoApp):
    id = "casino_slots"
    name = "Slots"
    description = "A slot machine for every phone: pull the lever, watch your reels spin on the panel."
    icon = "cherry"
    Game = Slots
    Settings = SlotsSettings

    def __init__(self, ctx: Any, settings: Any) -> None:
        super().__init__(ctx, settings)
        self._demo_cache: dict[tuple[str, str, int, int], dict[str, Any]] = {}

    def status(self) -> dict[str, Any]:
        st = super().status()
        if isinstance(st.get("machine"), dict):  # the phone draws the very same pixel symbols
            st["machine"]["sprites"] = sprite_table(str(st["machine"]["theme"]))
        return st

    def tv_extra(self) -> dict[str, Any] | None:
        """TV-only: the spin on the panel with all its stops (fixed and staked at the pull, so nothing left to
        decide) and its clock, so a TV turns the reels exactly with the panel (`reel_pos`)."""
        if self.settings.view != "live":
            return None
        g = self.game
        now = self.clock()
        sp = g.now_playing(now)
        if sp is None or sp.start is None:
            return None
        return {
            "reveal": {
                "game": "slots",
                "spin": sp.nonce,
                "stops": list(sp.stops),
                "t": round(now - sp.start, 4),
                "at": round(time.time(), 4),
                "paused": self.session.paused,
                "stops_at": list(SPIN_STOPS),
            }
        }

    def lobby_waiting(self) -> bool:
        g = self.game
        return (
            self.lobby_url is not None
            and len(self.seats) < self.max_players - 1
            and not g.queue
            and not g.recent
            and not self.session.paused
        )

    # ------------------------------------------------------------------ demo
    DEMO_PLAYERS = (("ADA", (0, 200, 255)), ("BOB", (255, 60, 90)), ("CY", (80, 255, 120)))

    def demo_spin(self, k: int) -> dict[str, Any]:
        r = self.game.rules
        key = (r.theme, r.volatility, self.game.lines, k)
        hit = self._demo_cache.get(key)
        if hit is not None:
            return hit
        if len(self._demo_cache) > 64:
            self._demo_cache.clear()
        rng = fair.Rng(b"deskdot-slots-demo", "demo", k)
        stops = [rng.randint(0, len(s) - 1) for s in STRIPS[r.theme][r.volatility]]
        if k % 3 == 1:  # every third demo spin shows a win so the art for wins is always in the loop
            for kk in range(k * 50, k * 50 + 4000):
                rng = fair.Rng(b"deskdot-slots-demo", "win", kk)
                stops = [rng.randint(0, len(s) - 1) for s in STRIPS[r.theme][r.volatility]]
                if evaluate(r.theme, r.volatility, stops, self.game.lines)["pays"] >= 4:
                    break
        name, col = self.DEMO_PLAYERS[k % 3]
        out = {"stops": stops, "name": name, "color": col, "bet": 2, "lines": self.game.lines, "nonce": k}
        self._demo_cache[key] = out
        return out

    def spin_view(
        self, view: str, t: float
    ) -> tuple[dict[str, Any] | None, float, list[tuple[int, int, int]]]:
        cycle = SPIN_STOPS[-1] + 3.4
        if view == "demo":
            k = int(t // cycle)
            return self.demo_spin(k), t % cycle, [self.DEMO_PLAYERS[(k + 1) % 3][1]]
        if view == "locked":
            return self.demo_spin(1), 0.2 + t % 0.6, []
        if view == "spinning":
            return self.demo_spin(1), t % SPIN_STOPS[-1], [(255, 60, 90)]
        if view in ("result", "board"):
            return self.demo_spin(1), SPIN_STOPS[-1] + (0.2 if view == "result" else 1.4) + t % 1.5, []
        return None, 0.0, []

    # ------------------------------------------------------------------ draw
    def render(self, f: Frame, t: float) -> None:
        view = self.settings.view
        g = self.game
        if view == "live":
            self._live()
            now = self.clock()
            g.tick(now)
            if self.lobby_waiting() and self.lobby_url:
                draw_qr(f, self.lobby_url, self.seats, now)
                return
            sp = g.now_playing(now)
            waiting = [_rgb(self.session.players[s.pid].color) for s in g.queue if s is not sp]
            if sp is not None and sp.start is not None:
                p = self.session.players.get(sp.pid)
                spin = {
                    "stops": sp.stops,
                    "name": self.session.name_of(sp.pid),
                    "lines": sp.lines,
                    "color": _rgb(p.color) if p else WHITE,
                    "bet": sp.bet,
                    "nonce": sp.nonce,
                    "theme": sp.theme,
                    "volatility": sp.volatility,
                }
                self.draw_spin(f, spin, now - sp.start, now, waiting)
            else:
                last = g.recent[-1] if g.recent else None
                self.draw_idle(f, last.stops if last else None, now, waiting)
            if self.session.paused:
                draw_paused(f, self.th)
            return
        if view == "lobby":
            self.lobby_url = self.lobby_url or "http://192.168.1.20:8765/p/K7QX"
            draw_qr(f, self.lobby_url, self.seats, t)
            return
        spin, st, waiting = self.spin_view(view, t)
        if spin is None:
            self.draw_idle(f, self.demo_spin(0)["stops"], t, [])
        else:
            self.draw_spin(f, spin, st, t, waiting)
        if view == "paused":
            draw_paused(f, self.th)

    def draw_reels(
        self,
        f: Frame,
        theme: str,
        vol: str,
        pos: list[float],
        lit: set[tuple[int, int]],
        blur: list[float],
        now: float,
    ) -> None:
        strips = STRIPS[theme][vol]
        sym = SYMBOLS[theme]
        f.rect(0, WIN_Y0 - 1, 32, 26, (16, 14, 24))
        for i, x in enumerate(REEL_X):
            f.rect(x - 1, WIN_Y0 - 1, CELL_W + 1, 3 * CELL_H + 1, REEL_EDGE)
            f.rect(x, WIN_Y0, CELL_W - 1, 3 * CELL_H - 1, REEL_BG)
            for r in range(3):
                if (r, i) in lit:
                    f.rect(
                        x,
                        WIN_Y0 + r * CELL_H,
                        CELL_W - 1,
                        CELL_H - 1,
                        scale(GOLD, 0.45 + 0.25 * math.sin(now * 10)),
                    )
            p = pos[i]
            base = math.floor(p)
            frac = p - base
            n = len(strips[i])
            k = max(0.35, 1.0 - blur[i])
            for dr in (-2, -1, 0, 1, 2):
                ch = strips[i][(base + dr) % n]
                if ch == "_" or ch not in sym:
                    continue
                y = WIN_Y0 + CELL_H + round((dr - frac) * CELL_H)
                self._blit(f, sym[ch], x, y, k, WIN_Y0, WIN_Y0 + 3 * CELL_H - 2)

    @staticmethod
    def _blit(f: Frame, s: Sprite, x: int, y: int, k: float, y0: int, y1: int) -> None:
        """A sprite clipped to the reel window rows y0..y1, dimmed by k (motion blur)."""
        h, w = s.mask.shape
        for j in range(h):
            yy = y + j
            if yy < y0 or yy > y1:
                continue
            for i in range(w):
                if s.mask[j, i]:
                    c = s.px[j, i]
                    f.set(x + i, yy, (int(c[0] * k), int(c[1] * k), int(c[2] * k)))

    def header(self, f: Frame, name: str, col: tuple[int, int, int], right: str, waiting: list[Any]) -> None:
        f.text(1, 1, fit(name.upper(), 20), col)
        x = 30
        for c in waiting[:5]:
            f.rect(x - 1, 2, 2, 2, c)
            x -= 3
        if right and not waiting:
            f.text_right(30, 1, right, (200, 200, 215))

    def draw_spin(self, f: Frame, spin: dict[str, Any], t: float, now: float, waiting: list[Any]) -> None:
        f.clear(INK)
        r = self.game.rules
        theme = str(spin.get("theme", r.theme))
        vol = str(spin.get("volatility", r.volatility))
        strips = STRIPS[theme][vol]
        stops = list(spin["stops"])
        pos, blur = [], []
        for i in range(3):
            pos.append(reel_pos(stops[i], len(strips[i]), t, i))
            dt = 0.05
            speed = abs(reel_pos(stops[i], len(strips[i]), t + dt, i) - pos[-1]) / dt
            blur.append(min(0.65, speed / 30))
        settled = t >= SPIN_STOPS[-1]
        ev = evaluate(theme, vol, stops, int(spin.get("lines", 5)))
        win = ev["pays"] * int(spin.get("bet", 1))
        lit: set[tuple[int, int]] = set()
        after = t - SPIN_STOPS[-1]
        if settled and ev["wins"]:
            w = ev["wins"][int(after / 0.7) % len(ev["wins"])]
            rows = LINES[w["line"] - 1]
            lit = {(rows[i], i) for i in range(3)}
        col = tuple(spin.get("color", WHITE))
        stake = int(spin.get("bet", 1)) * int(spin.get("lines", 5))
        self.header(f, str(spin.get("name", "")), col, str(stake), waiting)  # type: ignore[arg-type]
        self.draw_reels(f, theme, vol, pos, lit, blur, now)
        if settled and win:
            big = win >= BIG_WIN * stake
            if after > 0.5 and int((after - 0.5) / 1.3) % 2 == 0:  # the win, then the lines, in turn
                self.win_banner(f, win, after, big, now)
            self.coins(f, after, int(spin.get("nonce", 0)), big)
            win_flash(f, now, [col])  # type: ignore[list-item]
        elif settled and after > 0.15:
            f.rect(0, 31, 32, 1, (60, 60, 76))

    def win_banner(self, f: Frame, win: int, after: float, big: bool, now: float) -> None:
        txt = str(win)
        from ..gfx import measure

        w = measure(txt, "big") + 4
        x = (32 - w) // 2
        pop = min(1.0, (after - 0.5) / 0.25)
        f.rect(x, 13, w, 12, (20, 16, 6))
        f.rect(x, 13, w, 1, scale(GOLD, 0.7))
        f.rect(x, 24, w, 1, scale(GOLD, 0.7))
        f.text(x + 2, 14, txt, mix(WHITE, GOLD, pop * (0.6 + 0.4 * math.sin(now * 9))), font="big")
        if big and int(now * 3) % 2 == 0:
            f.rect(0, 0, 32, 7, (40, 30, 0))
            f.text_center(1, "BIG WIN", GOLD)

    def coins(self, f: Frame, after: float, nonce: int, big: bool) -> None:
        """Gold coins burst from the middle and fall away (cosmetic, seeded by the spin)."""
        if after > 1.6:
            return
        from ._casino import cosmetic

        n = 18 if big else 10
        for i in range(n):
            a = cosmetic(nonce, "coin", i) * 2 * math.pi
            v = 9 + 9 * cosmetic(nonce, "v", i)
            x = 16 + math.cos(a) * v * after
            y = 18 + math.sin(a) * v * after + 14 * after * after
            if 0 <= x < 32 and 0 <= y < 32:
                f.set(int(x), int(y), GOLD if (i + int(after * 10)) % 3 else (255, 250, 200))

    def draw_idle(self, f: Frame, stops: list[int] | None, now: float, waiting: list[Any]) -> None:
        f.clear(INK)
        r = self.game.rules
        strips = STRIPS[r.theme][r.volatility]
        stops = stops or [0, len(strips[1]) // 3, len(strips[2]) // 2]
        acc = THEME_ACCENT.get(r.theme, GOLD)
        on = int(now * 2) % 2 == 0
        f.text(1, 1, "PULL!", acc if on else scale(acc, 0.45))
        x = 30
        for c in waiting[:5]:
            f.rect(x - 1, 2, 2, 2, c)
            x -= 3
        self.draw_reels(f, r.theme, r.volatility, [float(s) for s in stops], set(), [0.0, 0.0, 0.0], now)

    def draw_table(self, f: Frame, v: View, now: float) -> None:  # not used: render() draws the machine
        self.draw_idle(f, None, now, [])
