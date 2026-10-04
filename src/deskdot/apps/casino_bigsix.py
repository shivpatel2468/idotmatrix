"""Big Six (the money wheel) on the panel: the betting board, then the whole wheel spinning — 54 coloured
segments round the rim, a gold clapper at 12 o'clock that flicks as the pegs pass, and the symbol under the
clapper big in the hub — slowing at a constant deceleration (like a real wheel losing speed to the clapper) and
stopping exactly on the round's provably fair segment. Rules and exact edges: ``deskdot.casino.games.bigsix``.

The motion is solved backwards from the outcome: rotation φ(t) = φ_end − D·(1 − t/T)², where φ_end puts the drawn
segment under the clapper and D is a few full turns, so the wheel always lands where the RNG said, smoothly.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..casino.games.bigsix import WHEEL, BigSix
from ..casino.table import LOCK_SECONDS
from ..engine import register
from ..gfx import Frame, mix, scale
from ._casino import CLASSIC, GOLD, INK, RGB3, WHITE, CasinoApp, CasinoSettings, View, cosmetic, win_flash

N = len(WHEEL)
SEG = 2 * math.pi / N
SYMBOL_RGB: dict[str, tuple[int, int, int]] = {
    "1": (255, 200, 30),
    "2": (40, 120, 255),
    "5": (0, 200, 90),
    "10": (190, 80, 255),
    "20": (255, 90, 20),
    "joker": (255, 40, 150),
    "logo": (255, 236, 170),
}
HUB_RGB = (52, 40, 64)
WOOD = (74, 46, 24)
SPIN_T = BigSix.spin_seconds - 0.6  # the wheel stops, then a short beat before the reveal

_ys, _xs = np.mgrid[0:32, 0:32]
_DX = _xs + 0.5 - 16.0
_DY = _ys + 0.5 - 16.5
R = np.hypot(_DX, _DY)
THETA = np.arctan2(_DX, -_DY) % (2 * math.pi)  # 0 at the top, clockwise
RIM = (R >= 10.6) & (R < 15.6)
EDGE = (R >= 15.6) & (R < 16.6)
HUB = R < 9.6
_SEG_RGB = np.array([SYMBOL_RGB[s] for s in WHEEL], np.float32)


class BigSixSettings(CasinoSettings):
    pass


def wheel_angle(since_spin: float, segment: int, nonce: int) -> float:
    """Rotation of the wheel (radians, clockwise) `since_spin` seconds after the croupier's spin."""
    off = (cosmetic(nonce, "b6") - 0.5) * 0.6 * SEG  # rest somewhere inside the segment, not dead centre
    end = -(segment + 0.5) * SEG + off
    travel = 2 * math.pi * (3 + cosmetic(nonce, "turns")) + 0.0
    u = max(0.0, min(1.0, since_spin / SPIN_T))
    return end - travel * (1 - u) ** 2


def under_clapper(phi: float) -> int:
    return int(((-phi) % (2 * math.pi)) // SEG) % N


def draw_wheel(f: Frame, phi: float, lit: int | None = None, blink: bool = False, edge: RGB3 = WOOD) -> None:
    idx = (((THETA - phi) % (2 * math.pi)) // SEG).astype(np.int64) % N
    col = _SEG_RGB[idx]
    # thin dark spokes between segments make each one readable
    frac = ((THETA - phi) % SEG) / SEG
    spoke = (frac < 0.12) & RIM & (R > 12)
    shade = np.where(R[..., None] < 12.2, 0.62, 1.0)
    img = np.zeros((32, 32, 3), np.float32)
    img[RIM] = (col * shade)[RIM]
    if lit is not None:
        m = RIM & (idx == lit)
        img[m] = np.array(WHITE if blink else SYMBOL_RGB[WHEEL[lit]], np.float32)
        if not blink:
            dimm = RIM & (idx != lit)
            img[dimm] *= 0.45
    img[spoke] *= 0.25
    img[EDGE] = edge  # the wooden rim (or the theme's rim)
    img[HUB] = HUB_RGB
    f.px[:] = np.clip(img, 0, 255).astype(np.uint8)


CLAPPER = (255, 40, 60)


def draw_clapper(f: Frame, kick: int) -> None:
    """The red leather clapper at 12 o'clock reaching into the rim, its tip flicked sideways by a passing peg."""
    for i, w in enumerate((5, 3, 3, 1, 1)):
        x0 = 16 - w // 2 + (kick if i >= 3 else 0)
        f.rect(x0, i, w, 1, CLAPPER if i else (255, 120, 130))


def hub_symbol(f: Frame, sym: str, k: float = 1.0) -> None:
    col = mix(WHITE, SYMBOL_RGB[sym], 0.35) if k >= 1 else scale(SYMBOL_RGB[sym], 0.7 + 0.3 * k)
    if sym in ("joker", "logo"):
        star(f, 16, 16, SYMBOL_RGB[sym]) if sym == "logo" else jester(f, 16, 16, SYMBOL_RGB[sym])
        return
    f.text_center(12, sym, col, font="big")


def star(f: Frame, cx: int, cy: int, col: tuple[int, int, int]) -> None:
    rows = ("...#...", "...#...", "#######", ".#####.", "..###..", ".##.##.", "#.....#")
    for j, r in enumerate(rows):
        for i, ch in enumerate(r):
            if ch == "#":
                f.set(cx - 3 + i, cy - 3 + j, col)


def jester(f: Frame, cx: int, cy: int, col: tuple[int, int, int]) -> None:
    rows = ("#.....#", "##...##", ".#####.", ".#.#.#.", ".#####.", "..#.#..", "...#...")
    for j, r in enumerate(rows):
        for i, ch in enumerate(r):
            if ch == "#":
                f.set(cx - 3 + i, cy - 3 + j, col if j < 2 else GOLD if ch == "#" and j >= 5 else col)


@register
class CasinoBigSix(CasinoApp):
    id = "casino_bigsix"
    name = "Big Six"
    description = "The money wheel: bet on 1, 2, 5, 10, 20, joker or logo; the panel spins the big wheel."
    icon = "disc"
    Game = BigSix
    Settings = BigSixSettings
    table_seconds = 3.4

    @property
    def edge(self) -> RGB3:
        """The wheel's outer rim: wood on the classic table, the theme's rim colour otherwise."""
        return WOOD if self.th is CLASSIC else self.th.rim

    def draw_table(self, f: Frame, v: View, now: float) -> None:
        f.clear(INK)
        if v.outcome is None:
            return
        seg = int(v.outcome["segment"])
        if v.phase == "result" or v.since_lock is None:
            phi = wheel_angle(SPIN_T, seg, v.nonce)
            blink = int(now * 4) % 2 == 0
            draw_wheel(f, phi, lit=seg, blink=blink and v.since < 1.2, edge=self.edge)
            draw_clapper(f, 0)
            hub_symbol(f, WHEEL[seg])
            if v.winners:
                win_flash(f, now, v.winners, self.th)
            return
        ts = v.since_lock - LOCK_SECONDS
        phi = wheel_angle(ts, seg, v.nonce)
        draw_wheel(f, phi, edge=self.edge)
        # the clapper kicks while a peg (segment edge) is passing under it
        pos = ((-phi) % (2 * math.pi)) / SEG
        kick = 1 if (pos % 1) < 0.3 and ts < SPIN_T else 0
        draw_clapper(f, kick)
        hub_symbol(f, WHEEL[under_clapper(phi)], k=0.0 if ts < SPIN_T else 1.0)

    def hero_result(self, f: Frame, v: View, now: float) -> None:
        if v.outcome is None:
            return
        sym = str(v.outcome["symbol"])
        col = SYMBOL_RGB[sym]
        f.rect(1, 2, 30, 14, col)
        f.rect(2, 16, 29, 1, scale(col, 0.45))
        if sym in ("joker", "logo"):
            f.text_center(5, sym.upper(), (20, 20, 20), font="small")
        else:
            f.text_center(4, sym, (20, 20, 20) if sym in ("1", "logo") else WHITE, font="big")

    def tile(self, summary: dict[str, Any]) -> tuple[str, tuple[int, int, int]]:
        sym = str(summary.get("tone", "")).removeprefix("b6_")
        lbl = {"joker": "J", "logo": "L"}.get(sym, sym)
        return lbl, scale(SYMBOL_RGB.get(sym, (90, 90, 104)), 0.8)
