"""Accessories fitted to each character's head: generated from the head box and eye positions, so a cap
sits on a pug as well as on a knight. Sprites are cached per (character, accessory) in the shared sheet."""

from __future__ import annotations

from .rig import SHEET, Rig

ACCESSORIES: dict[str, str] = {
    "none": "None",
    "cap": "Cap",
    "beanie": "Beanie",
    "crown": "Crown",
    "party_hat": "Party hat",
    "headphones": "Headphones",
    "sunglasses": "Sunglasses",
    "halo": "Halo",
    "bow": "Bow",
    "scarf": "Scarf",
    "helmet": "Helmet",
    "wizard_hat": "Wizard hat",
    "santa_hat": "Santa hat",
}

_KEY = {
    "r": "#ff2a1e",
    "R": "#a0140a",
    "b": "#1e78ff",
    "B": "#0a3c9c",
    "y": "#ffd200",
    "Y": "#fff5a0",
    "o": "#ff8c00",
    "m": "#ff3cb4",
    "M": "#b4146e",
    "W": "#ffffff",
    "w": "#c8c8dc",
    "k": "#1a1a22",
    "K": "#3c3c50",
    "g": "#8c96a5",
    "G": "#4b5564",
    "v": "#7832ff",
    "V": "#3c148c",
    "c": "#32dcff",
    "l": "#50dc3c",
    "e": "#ff1e5a",
}


def _cap(hw: int) -> tuple[list[str], int, int]:
    cw = max(5, hw - 2)
    rows = ["." + "r" * (cw - 2) + ".", "r" * (cw // 2) + "W" + "r" * (cw - cw // 2 - 1), "r" * cw + "RRR"]
    return rows, -(cw // 2), -2


def _beanie(hw: int) -> tuple[list[str], int, int]:
    w = max(6, hw)
    rows = [
        "." * (w // 2 - 1) + "WW" + "." * (w - w // 2 - 1),
        ".." + "b" * (w - 4) + "..",
        "." + "b" * (w - 2) + ".",
        "b" * w,
        "".join("B" if i % 2 == 0 else "b" for i in range(w)),
    ]
    return rows, -(w // 2), -3


def _crown(hw: int) -> tuple[list[str], int, int]:
    big = ["y..y..y", "yy.y.yy", "yyyyyyy", "yeyYycy"]
    rows = big if hw >= 8 else ["y.y.y", "yyyyy", "yeYcy"]
    w = len(rows[0])
    return rows, -(w // 2), -len(rows) + 1


def _party(hw: int) -> tuple[list[str], int, int]:
    rows = ["..W..", "..m..", ".myc.", ".cmy.", "ymcmy", "mcymc"]
    return rows, -2, -len(rows) + 1


def _wizard(hw: int) -> tuple[list[str], int, int]:
    rows = ["......v.", ".....vv.", "....vvv.", "...vvyv.", "..vvvvv.", ".vvvvvvv.", "VVVVVVVVVV"]
    return rows, -5, -len(rows) + 1


def _santa(hw: int) -> tuple[list[str], int, int]:
    w = max(7, hw)
    rows = [
        "..rrrr" + "." * (w - 6) + "..",
        ".rrrrrrr" + "." * max(0, w - 8) + "WW",
        "r" * (w - 1) + "RWW",
        "W" * w,
    ]
    return rows, -(w // 2), -3


def _helmet(hw: int) -> tuple[list[str], int, int]:
    w = hw + 2
    rows = [
        "..." + "g" * (w - 6) + "...",
        "." + "g" * (w - 2) + ".",
        "g" * (w // 2 - 1) + "ww" + "g" * (w - w // 2 - 1),
        "G" * w,
    ]
    return rows, -(w // 2), -2


def _halo(hw: int) -> tuple[list[str], int, int]:
    w = max(5, hw - 3)
    rows = ["." + "Y" * (w - 2) + ".", "y" + "." * (w - 2) + "y", "." + "y" * (w - 2) + "."]
    return rows, -(w // 2), -6


def _bow(hw: int) -> tuple[list[str], int, int]:
    rows = ["mm.mm", "mmMmm", "m...m"]
    return rows, -(hw // 2) - 1, -1


def _headphones(rig: Rig) -> tuple[list[str], int, int, str]:
    x0, y0, x1, _ = rig.head_box
    ey = rig.eye_y
    w = x1 - x0 + 3
    h = max(4, ey - y0 + 3)
    g = [["."] * w for _ in range(h)]
    for x in range(2, w - 2):
        g[0][x] = "K"
    for y in range(1, h - 3):
        g[y][0] = g[y][w - 1] = "K"
    g[1][1] = g[1][w - 2] = "K"
    for y in range(h - 3, h):
        for x in (0, 1):
            g[y][x] = "r" if x == 0 else "k"
            g[y][w - 1 - x] = "r" if x == 0 else "k"
    return ["".join(r) for r in g], -(w // 2), -1, "hat"


def _sunglasses(rig: Rig) -> tuple[list[str], int, int, str]:
    pts, ew, eh = rig.eye_pts, rig.eye_w, rig.eye_h
    xa = min(p[0] for p in pts) - 1
    xb = max(p[0] for p in pts) + ew
    ya = min(p[1] for p in pts)
    lh = max(2, eh)
    w = xb - xa + 1
    g = [["."] * w for _ in range(lh)]
    for px, py in pts:
        for yy in range(lh):
            for xx in range(px - 1, px + ew + 1):
                if 0 <= xx - xa < w:
                    g[yy + (py - ya)][xx - xa] = "k"
        g[0 + (py - ya)][px - xa] = "w"
    for x in range(w):
        if g[0][x] == ".":
            g[0][x] = "K"
    cx, cy = rig.anchors["eyes"][1:]
    return ["".join(r) for r in g], xa - cx, ya - cy, "eyes"


def _scarf(rig: Rig) -> tuple[list[str], int, int, str]:
    x0, _, x1, _ = rig.head_box
    w = max(5, x1 - x0 - 1)
    rows = ["".join("r" if i % 3 else "W" for i in range(w)), "rr" + "." * (w - 2), "rW" + "." * (w - 2)]
    return rows, -(w // 2), 0, "neck"


_HATS = {
    "cap": _cap,
    "beanie": _beanie,
    "crown": _crown,
    "party_hat": _party,
    "wizard_hat": _wizard,
    "santa_hat": _santa,
    "helmet": _helmet,
    "halo": _halo,
    "bow": _bow,
}


def accessory_fx(rig: Rig, acc: str) -> tuple[str, str, int, int] | None:
    """-> an effect entry (sprite name, anchor, dx, dy) for Rig.compose (sprites are centred on anchor+d)."""
    if acc == "none" or acc not in ACCESSORIES:
        return None
    name = f"acc:{rig.id}:{acc}"
    cache = rig.__dict__.setdefault("_acc", {})
    if name in cache:
        return cache[name]
    if acc in _HATS:
        x0, _, x1, _ = rig.head_box
        rows, ox, oy = _HATS[acc](x1 - x0 + 1)
        anchor = "hat"
    elif acc == "headphones":
        rows, ox, oy, anchor = _headphones(rig)
        oy = max(oy, -rig.head_box[1])
    elif acc == "sunglasses":
        rows, ox, oy, anchor = _sunglasses(rig)
    else:
        rows, ox, oy, anchor = _scarf(rig)
    if anchor == "hat":
        # keep hats inside the character box so they stay visible when the character fills the panel
        top = rig.head_box[1] + oy
        if top < 0:
            oy -= top
    SHEET.add(name, rows, _KEY)
    sh, sw = SHEET.sprites[name].shape
    entry = (name, anchor, ox + sw // 2, oy + sh // 2)
    cache[name] = entry
    return entry
