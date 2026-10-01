"""Shared parts: humanoid limbs, critter nubs and feet, quadruped legs, eyes, and the effect/prop sheet.

Generic limb art uses a small letter vocabulary that each character's key maps to its own slots:

    c / C   sleeve / sleeve shade        n       hand (skin or glove)
    p / P   trousers / trousers shade    f       shoes
    l / L   quadruped leg / far leg      q / Q   paw / far paw
"""

from __future__ import annotations

from typing import Any

from .rig import SHEET, Part, V, mirror_variants, v

# --------------------------------------------------------------------------- humanoid (16x16 chibi)
# head x3..12 y0..7 · torso x4..11 y8..12 · arms x2..3 / x12..13 y8..11 · legs x4..11 y13..15
ARM_R: dict[str, V] = {
    "down": v("Cc", "Cc", "Cc", "nn", hand=(0, 3)),
    "up": v(".nn", ".cc", "Cc.", "Cc.", oy=-3, hand=(1, 0)),
    "wave": v("..nn", ".cc.", "Cc..", "Cc..", oy=-3, hand=(2, 0)),
    "fwd": v("Cccn", "CCcn", hand=(3, 1)),
    "out": v("Cc..", ".Cc.", "..nn", hand=(2, 2)),
    "mouth": v("nn.", ".Cc", ".Cc", ox=-1, oy=-2, hand=(0, 0)),
    "chin": v("n.", "Cc", "Cc", ox=-1, oy=-1, hand=(0, 0)),
    "aim": v("Cc..", ".Ccn", hand=(3, 1)),
    "hold": v(".Cc", "Cc.", "nn.", ox=-1, hand=(0, 2)),
    "back": v("Cc", ".C", ".n", hand=(1, 2)),
}

LEGS: dict[str, V] = {
    "stand": v(".pp..pp.", ".pp..pp.", ".fff.fff"),
    "walk_a": v(".pp..pp.", ".pp...fff", ".fff....."),
    "walk_b": v(".pp..pp.", ".fff.pp..", ".....fff."),
    "run_a": v("..pppp...", ".pp...pp.", "ff.....fff", ox=-1),
    "run_b": v("..pppp..", "..pppp..", "..ff.fff"),
    "crouch": v("pppppppp", "fff..fff", oy=1),
    "sit": v(".pppppp.", ".pppppfff", oy=1),
    "tuck": v(".pp..pp.", ".fff.fff"),
    "kick_back": v(".pp.pp..", ".pppp...", ".ffff..."),
    "kick_fwd": v(".pp..ppp", ".pp....fff", ".fff......"),
}


ROBE: dict[str, V] = {
    "stand": v("pppppppp", "pppppppp", ".ff..ff."),
    "walk_a": v("pppppppp", "pppppppp", ".ff...ff"),
    "walk_b": v("pppppppp", "pppppppp", "ff...ff."),
    "run_a": v("pppppppp", "ppppppppp", "ff.....ff"),
    "run_b": v("pppppppp", "pppppppp", "..ff.ff."),
    "crouch": v("pppppppppp", "ff......ff", ox=-1, oy=1),
    "sit": v("pppppppppp", "pppppppppff", ox=-1, oy=1),
    "tuck": v("pppppppp", ".ff..ff."),
    "kick_back": v("pppppppp", "pppppppp", "ff..ff.."),
    "kick_fwd": v("pppppppp", "ppppppppff", "ff......"),
}

# Guns: `hold` (low ready across the body) first so it is the default; `aim` shoulders it inside the box.
RIFLE: dict[str, V] = {
    "hold": v("..G....", "GGGGGGG", "G.gg...", grip=(2, 1)),
    "aim": v("..G....", "GGGGGGG", "G.gg...", grip=(6, 1)),
    "down": v("G.", "GG", "G.", "GG", "G.", grip=(0, 2)),
}
SNIPER: dict[str, V] = {
    "hold": v("...GG....", "GGGGGGGGG", "Gg.g.....", grip=(3, 1)),
    "aim": v("...GG....", "GGGGGGGGG", "Gg.g.....", grip=(8, 1)),
    "down": v("G.", "GG", "G.", "G.", "G.", "G.", grip=(0, 2)),
}


def humanoid_limbs(z_arms: int = 5) -> dict[str, Part]:
    return {
        "legs": Part(4, 13, dict(LEGS), z=0),
        "arm_r": Part(12, 8, dict(ARM_R), parent="body", z=z_arms),
        "arm_l": Part(2, 8, mirror_variants(ARM_R, 12, 2), parent="body", z=-1),
    }


# --------------------------------------------------------------------------- critter nubs & feet
NUB_R: dict[str, V] = {
    "down": v("cc", ".n", hand=(1, 1)),
    "up": v(".n", "cc", oy=-2, hand=(1, 0)),
    "wave": v("..n", ".c.", "c..", oy=-2, hand=(2, 0)),
    "fwd": v("ccn", hand=(2, 0)),
    "out": v("c.", ".n", hand=(1, 1)),
    "mouth": v("n.", "cc", ox=-1, oy=-1, hand=(0, 0)),
    "chin": v("n.", "c.", ox=-1, hand=(0, 0)),
    "aim": v("ccn", hand=(2, 0)),
    "hold": v("c.", "n.", ox=-1, hand=(0, 1)),
    "back": v("c", "n", hand=(0, 1)),
}


def nub_arms(xr: int, xl: int, y: int, axis: int = 15, z: int = 5) -> dict[str, Part]:
    return {
        "arm_r": Part(xr, y, dict(NUB_R), parent="body", z=z),
        "arm_l": Part(xl, y, mirror_variants(NUB_R, xr, xl, axis), parent="body", z=-1),
    }


FEET: dict[str, V] = {
    "stand": v("ff..ff", "ff..fff"),
    "walk_a": v("ff..fff", "ff....."),
    "walk_b": v("ff..ff", ".....fff"),
    "run_a": v("ff...fff", ".......", ox=-1),
    "run_b": v(".ff.fff", ".......", ox=0),
    "crouch": v("fff.fff", oy=1),
    "sit": v("..ffff", "..fffff", oy=0),
    "tuck": v(
        "ff..ff",
    ),
    "kick_back": v("ff.ff", "ff.ff", ox=-1),
    "kick_fwd": v("ff..", "ff..fff"),
}


def feet(x: int, y: int) -> dict[str, Part]:
    return {"legs": Part(x, y, dict(FEET), z=0)}


# --------------------------------------------------------------------------- quadruped legs
def quad_leg(h: int = 3, far: bool = False) -> dict[str, V]:
    lg, q = ("L", "Q") if far else ("l", "q")
    col = [lg + lg] * (h - 1) + [q + q]
    return {
        "stand": v(*col),
        "fwd": v(*([lg + lg] * (h - 2) + ["." + lg + lg] + ["." + q + q]), hand=(2, h - 1)),
        "back": v(*([lg + lg] * (h - 2) + [lg + lg + "."] + [q + q + "."]), ox=-1),
        "lift": v(*([lg + lg] * (h - 2) + ["." + q + q]), hand=(2, h - 2)),
        "tuck": v(lg + lg, q + q),
        "kick": v(lg + lg + lg, "." + q + q + q, hand=(3, 1)),
        "-": v(),
    }


def quad_legs(fx: int, bx: int, y: int, h: int = 3, gap: int = 1) -> dict[str, Part]:
    """Four legs: front near/far at fx, back near/far at bx (far legs one px behind, darker)."""
    return {
        "leg_ff": Part(fx + gap, y, quad_leg(h, True), z=-2),
        "leg_bf": Part(bx + gap, y, quad_leg(h, True), z=-2),
        "leg_fn": Part(fx, y, quad_leg(h), z=2),
        "leg_bn": Part(bx, y, quad_leg(h), z=2),
    }


# --------------------------------------------------------------------------- eyes
def eye_variants(
    pts: list[tuple[int, int]], w: int = 1, h: int = 2, shine: bool = False, lid: str = "k"
) -> tuple[int, int, dict[str, V]]:
    """Build the eyes part (origin, variants) from eye top-left points in character space.

    Variants: open, closed, happy (^ ^), sad (droopy, looking down), up (looking up), wide.
    Uses key letters 'e' (eye) 'W' (shine) and `lid` (closed-eye line)."""
    x0 = min(p[0] for p in pts) - 1
    y0 = min(p[1] for p in pts) - 1
    x1 = max(p[0] for p in pts) + w + 1
    y1 = max(p[1] for p in pts) + h + 1
    W, H = x1 - x0 + 1, y1 - y0 + 1

    def grid() -> list[list[str]]:
        return [["."] * W for _ in range(H)]

    def put(g: list[list[str]], x: int, y: int, c: str) -> None:
        gx, gy = x - x0, y - y0
        if 0 <= gx < W and 0 <= gy < H:
            g[gy][gx] = c

    def rows(g: list[list[str]]) -> tuple[str, ...]:
        return tuple("".join(r) for r in g)

    out: dict[str, V] = {}
    g = grid()
    for px, py in pts:
        for yy in range(h):
            for xx in range(w):
                put(g, px + xx, py + yy, "e")
        if shine and w >= 2 and h >= 2:
            put(g, px + w - 1, py, "W")
    out["open"] = V(rows(g))
    g = grid()
    cx = sum(p[0] for p in pts) / len(pts)
    for px, py in pts:
        # w == 1: a 2 px lid, extended away from the face centre so the two lids never merge
        xs = ((px - 1, px) if px < cx else (px, px + 1)) if w == 1 else tuple(range(px, px + w))
        for xx in xs:
            put(g, xx, py + h - 1, lid)
    out["closed"] = V(rows(g))
    g = grid()
    for px, py in pts:  # ^ arch: sides one row below the top
        top = py + h - 2 if h > 1 else py - 1
        put(g, px - 1, top + 1, "e")
        put(g, px + w, top + 1, "e")
        for xx in range(w):
            put(g, px + xx, top, "e")
    out["happy"] = V(rows(g))
    g = grid()
    for i, (px, py) in enumerate(pts):
        for yy in range(max(1, h - 1)):
            for xx in range(w):
                put(g, px + xx, py + h - 1 - yy, "e")
        # droopy brow slanting outwards-down
        if i == 0:
            put(g, px - 1, py, lid)
        else:
            put(g, px + w, py, lid)
    out["sad"] = V(rows(g))
    g = grid()
    for px, py in pts:
        for yy in range(max(1, h - 1)):
            for xx in range(w):
                put(g, px + xx, py - 1 + yy, "e")
    out["up"] = V(rows(g))
    g = grid()
    for px, py in pts:
        for yy in range(h):
            for xx in range(w):
                put(g, px + xx, py + yy, "e")
        put(g, px + w - 1, py, "W")
    out["wide"] = V(rows(g))
    return x0, y0, out


def eyes_part(spec: dict[str, Any], parent: str = "head") -> Part:
    x0, y0, var = eye_variants(
        spec["pts"], spec.get("w", 1), spec.get("h", 2), spec.get("shine", False), spec.get("lid", "k")
    )
    return Part(x0, y0, var, parent=spec.get("parent", parent), z=spec.get("z", 20))


# --------------------------------------------------------------------------- effects & props
_FX_KEY = {
    "Z": "#9ab4ff",
    "z": "#5a6ec8",
    "h": "#ff2a5a",
    "H": "#ff9ab4",
    "n": "#ffd21e",
    "N": "#00dcff",
    "t": "#50b4ff",
    "T": "#c8ecff",
    "s": "#fff08c",
    "S": "#ffffff",
    "W": "#ffffff",
    "w": "#c8c8d2",
    "k": "#141418",
    "g": "#8c8ca0",
    "G": "#46465a",
    "L": "#b4b4c3",
    "o": "#ff5a1e",
    "y": "#ffdc00",
    "Y": "#fff5aa",
    "r": "#ff2814",
    "R": "#b41400",
    "b": "#1e8cff",
    "B": "#0a46b4",
    "c": "#50e6ff",
    "v": "#b450ff",
    "V": "#50146e",
    "m": "#ff50c8",
    "l": "#50dc28",
    "D": "#1e7814",
    "u": "#a0643c",
    "U": "#643c1e",
    "e": "#e6c896",
    "a": "#ff9632",
    "x": "#28283a",
    "q": "#3cff8c",
}

_FX: dict[str, tuple[str, ...]] = {
    "z": ("zzz", ".z.", "zzz"),
    "Z": ("ZZZZ", "..Z.", ".Z..", "ZZZZ"),
    "heart": ("hh.hh", "hHhhh", "hhhhh", ".hhh.", "..h.."),
    "heart_s": ("h.h", "hhh", ".h."),
    "note": (".nn", ".n.", ".n.", "nn."),
    "note2": (".NNN", ".N.N", ".N.N", "NN.N"),
    "tear": ("T", "t", "t"),
    "sweat": (".T", "tt", "t."),
    "sparkle": (".s.", "sSs", ".s."),
    "sparkle_s": ("S",),
    "star": ("..y..", ".yYy.", "yYSYy", ".yYy.", "..y.."),
    "ball": (".WW.", "WkWW", "WWkW", ".WW."),
    "laptop": ("gggggg", "ggoggg", "gggggg", "wwwwwwww"),
    "screen_glow": ("c",),
    "bowl": (".uuuu.", "rrrrrr", ".rRRr."),
    "bone": ("W....W", "WWWWWW", "W....W"),
    "apple": (".D", "rr", "rR"),
    "drumstick": ("uu..", "uuuW", ".uW."),
    "fish": ("b.bbb.", "bbbWkb", "b.bbb."),
    "carrot": ("..l", ".a.", "a.."),
    "cookie": (".uu", "uUu", "uu."),
    "leaf": (".l", "lD"),
    "bamboo": (".l", "lD", "lD", "lD"),
    "flash": (".y.", "ySy", ".y."),
    "flash_big": ("..y..", ".yYy.", "yYSYy", ".yYy.", "..y.."),
    "bullet": ("YYy",),
    "shell": ("y",),
    "mag": ("xx", "xx", "x."),
    "slash": ("..W", ".Wc", "Wc.", "c.."),
    "slash2": ("WWW.", "...W", "...c"),
    "arrow": ("uuuuWW",),
    "orb": (".c.", "cSc", ".c."),
    "orb_v": (".v.", "vmv", ".v."),
    "bolt": ("..y", ".y.", "yyy", ".y.", "y.."),
    "zap": ("y.y", ".Y.", "y.y"),
    "flame": (".y..", "yYy.", "aYa", ".a."),
    "fire": ("..rr", "aayY", "..ra"),
    "breath": ("...aa.", "aayYYy", "...aa."),
    "water": (".b.", "bcb", ".b."),
    "splash": ("c.c", ".b.", "bbb"),
    "vine": ("l.", "Dl", ".l"),
    "shadow": (".vv.", "vVVv", "vVVv", ".vv."),
    "song": ("m.m", ".m.", "m.m"),
    "cloud": (".www.", "wwwww", ".GGG."),
    "rain": ("t.t",),
    "dot": ("W",),
    "dot2": ("WW", "WW"),
    "bubble": (".WWWW.", "WkWkWW", ".WWWW."),
    "q": ("WW", "..W", ".W.", "...", ".W."),
    "bang": ("r", "r", "r", ".", "r"),
    "dust": ("g.", ".G"),
    "rock": (".U.", "UuU"),
    "pan": (".GG.", "GggG", ".GG."),
    "code": ("q.q",),
    "punch": ("W.W", ".W.", "W.W"),
    "hammer": ("gg", "gg", ".u"),
    "coin": (".y.", "yYy", ".y."),
    "yawn": ("ee",),
}
for _n, _rows in _FX.items():
    SHEET.add(_n, _rows, _FX_KEY)
