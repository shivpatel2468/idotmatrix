"""Playing cards on the panel: 7×10 px cards (docs/CASINO.md §3) and small helpers shared by the card tables
(Hold'em, Teen Patti, Andar Bahar).

A face-up card is a rounded slate face with the rank glyph (tiny font; "10" is a narrow two-digit glyph) on top,
a blank row, and a 5×3 suit pip at the bottom, red for hearts / diamonds and white for spades / clubs. A face-down
card is a red back with a gold rim and a diagonal lattice. Dark tones stay ≥ 45 per channel (gamma 1.5).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ..gfx import Frame, scale

CARD_W, CARD_H = 7, 10
FACE = (64, 64, 84)
FACE_HI = (120, 92, 12)  # a highlighted card (the winning hand, the joker's match)
INK_RED = (255, 40, 52)
INK_WHITE = (236, 236, 236)
BACK = (150, 16, 34)
BACK_RIM = (210, 150, 20)
BACK_LATTICE = (220, 60, 70)

_PIPS = {  # 5×3 pips under the rank (the card's 5×8 inside: rank rows 1-5, pip rows 6-8)
    "H": ("##.##", "#####", ".###."),
    "D": ("..#..", ".###.", "..#.."),
    "S": ("..#..", ".###.", "#####"),
    "C": (".#.#.", "#####", ".#.#."),
}
_PIPS3 = {  # 3×3 pips for mini cards
    "H": ("#.#", "###", ".#."),
    "D": (".#.", "###", ".#."),
    "S": (".#.", "###", "#.#"),
    "C": ("###", "###", ".#."),
}
_TEN = ("#.###", "#.#.#", "#.#.#", "#.#.#", "#.###")  # "10" in 5 px


def _mask(rows: Sequence[str]) -> np.ndarray:
    return np.array([[c == "#" for c in r] for r in rows], dtype=bool)


PIP = {k: _mask(v) for k, v in _PIPS.items()}
PIP3 = {k: _mask(v) for k, v in _PIPS3.items()}
TEN = _mask(_TEN)


def _stamp(f: Frame, x: int, y: int, m: np.ndarray, col: tuple[int, int, int]) -> None:
    h, w = m.shape
    for j in range(h):
        for i in range(w):
            if m[j, i]:
                f.set(x + i, y + j, col)


def ink(code: str) -> tuple[int, int, int]:
    return INK_RED if code[-1] in "HD" else INK_WHITE


def rank_glyph(code: str) -> str:
    r = code[:-1]
    return "10" if r in ("T", "10") else r


def draw_rank(f: Frame, x: int, y: int, code: str, col: tuple[int, int, int]) -> None:
    """The rank, 5 px tall, centred on a 7 px card at `x`."""
    g = rank_glyph(code)
    if g == "10":
        _stamp(f, x + 1, y, TEN, col)
    else:
        f.text(x + 2, y, g, col)


def card(
    f: Frame,
    x: int,
    y: int,
    code: str | None,
    *,
    hi: bool = False,
    dim: float = 1.0,
) -> None:
    """A 7×10 card with its top-left at (x, y): a rounded face, the rank on rows 1–5, the suit pip on rows 7–9.
    `code` None = face down. `hi` lights the face gold (a winning card); `dim` < 1 fades it (folded, not played)."""
    if code is None:
        back(f, x, y, dim=dim)
        return
    face = scale(FACE_HI if hi else FACE, max(0.8, dim))
    f.rect(x + 1, y, CARD_W - 2, CARD_H, face)
    f.rect(x, y + 1, CARD_W, CARD_H - 2, face)
    col = scale(ink(code), dim)
    draw_rank(f, x, y + 1, code, col)
    _stamp(f, x + 1, y + 7, PIP[code[-1]], col)


def narrow(f: Frame, x: int, y: int, code: str | None, *, hi: bool = False, dim: float = 1.0) -> None:
    """A 5×10 card for rows that must fit five (the hold'em board) or sit beside labels: the 7×10 card without
    its blank side columns, so cards at a 6 px pitch keep a dark 1 px gap."""
    if code is None:
        f.rect(x + 1, y, 3, CARD_H, scale(BACK_RIM, dim))
        f.rect(x, y + 1, 5, CARD_H - 2, scale(BACK_RIM, dim))
        f.rect(x + 1, y + 1, 3, CARD_H - 2, scale(BACK, dim))
        return
    face = scale(FACE_HI if hi else FACE, max(0.8, dim))
    f.rect(x + 1, y, 3, CARD_H, face)
    f.rect(x, y + 1, 5, CARD_H - 2, face)
    col = scale(ink(code), dim)
    if rank_glyph(code) == "10":
        _stamp(f, x, y + 1, TEN, col)
    else:
        f.text(x + 1, y + 1, rank_glyph(code), col)
    _stamp(f, x, y + 7, PIP[code[-1]], col)


def back(f: Frame, x: int, y: int, dim: float = 1.0) -> None:
    """A face-down card: red back, gold rim, a lattice."""
    f.rect(x + 1, y, CARD_W - 2, CARD_H, scale(BACK_RIM, dim))
    f.rect(x, y + 1, CARD_W, CARD_H - 2, scale(BACK_RIM, dim))
    f.rect(x + 1, y + 1, CARD_W - 2, CARD_H - 2, scale(BACK, dim))
    for j in range(1, CARD_H - 1):
        for i in range(1, CARD_W - 1):
            if (i + j) % 3 == 0:
                f.set(x + i, y + j, scale(BACK_LATTICE, dim))


def mini(f: Frame, x: int, y: int, code: str | None, dim: float = 1.0) -> None:
    """A 5×7 mini card (rank over a 3×3 pip, no rim) for crowded rows: showdown hands, piles."""
    if code is None:
        f.rect(x, y, 5, 7, scale(BACK, dim))
        f.rect(x, y, 5, 1, scale(BACK_RIM, dim))
        return
    f.rect(x, y, 5, 7, scale(FACE, max(0.8, dim)))
    col = scale(ink(code), dim)
    g = rank_glyph(code)
    if g == "10":
        _stamp(f, x, y, TEN[:, :], col)
    else:
        f.text(x + 1, y, g, col)


def row(
    f: Frame,
    x: int,
    y: int,
    codes: Sequence[str | None],
    pitch: int = 8,
    hi: Sequence[bool] | None = None,
    dim: Sequence[float] | None = None,
) -> None:
    """Cards left to right, `pitch` apart (8 = a 1 px gap)."""
    for i, c in enumerate(codes):
        card(f, x + i * pitch, y, c, hi=bool(hi and hi[i]), dim=dim[i] if dim else 1.0)
