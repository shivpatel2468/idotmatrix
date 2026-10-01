"""The part-based pixel rig behind every character.

A character (`Rig`) is a handful of small parts (body, head, arms, legs, tail, eyes, items...) authored as
ASCII rows. Every letter maps through the rig's `key` to a *slot spec*:

    "body"        a recolourable slot
    "body*0.6"    that slot scaled darker (derived, follows recolours)
    "body^0.4"    that slot mixed 40 % towards white (a highlight)
    "#rrggbb"     a fixed colour

Parts form a tiny hierarchy (legs hang off the root, the head off the body, eyes off the head), so moving
the body carries everything attached to it. Animations are keyframes of per-part offsets and variant swaps
(`anims.py`); `pose_at()` samples them at time `t` (optionally tweening offsets), and the resolved integer
pose is the cache key for the composited index image. Colours are applied last through a small LUT, so
recolouring never re-composites.

Compositing happens in "index space" (int16, -1 = transparent) on a padded canvas, so effects such as
flying balls, Zzz and music notes may leave the character box; `Frame.blit` clips the result safely.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..color import RGB, mix, to_rgb
from ..color import scale as cscale

PAD = 10  # canvas padding around the character box (effects may reach this far out)

# Emotes are drawn as a crisp 1x overlay on top of the (possibly doubled) character and kept on-panel;
# every other effect is a prop that scales with the character.
EMOTES = frozenset(
    (
        "z",
        "Z",
        "heart",
        "heart_s",
        "note",
        "note2",
        "tear",
        "sweat",
        "sparkle",
        "sparkle_s",
        "star",
        "dot",
        "dot2",
        "bubble",
        "q",
        "bang",
        "cloud",
        "rain",
        "code",
        "dust",
        "zap",
        "song",
        "slash",
        "slash2",
        "punch",
        "flash",
        "flash_big",
    )
)
# Projectiles are also drawn at 1x, but travel in panel pixels (not scaled) and are never clamped, so a
# shot crosses the panel visibly even when the character is doubled.
PROJECTILES = frozenset(
    (
        "arrow",
        "bullet",
        "orb",
        "orb_v",
        "bolt",
        "fire",
        "breath",
        "water",
        "shadow",
        "vine",
        "song",
        "shell",
        "mag",
    )
)


Offset = tuple[int, int]


# --------------------------------------------------------------------------- parts
@dataclass(frozen=True)
class V:
    """One variant of a part: ASCII rows, placed at part origin + (ox, oy).

    `hand` is an attach point (local coords) other parts can hang from (items held in a hand).
    `grip` is where *this* variant is held when it is attached to another part's hand.
    """

    rows: tuple[str, ...]
    ox: int = 0
    oy: int = 0
    hand: tuple[int, int] | None = None
    grip: tuple[int, int] = (0, 0)

    @property
    def w(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    @property
    def h(self) -> int:
        return len(self.rows)


def v(
    *rows: str, ox: int = 0, oy: int = 0, hand: tuple[int, int] | None = None, grip: tuple[int, int] = (0, 0)
) -> V:
    return V(tuple(rows), ox, oy, hand, grip)


@dataclass
class Part:
    x: int
    y: int
    variants: dict[str, V]
    parent: str = "root"
    z: int = 0
    attach: str | None = None  # position from this part's current variant's `hand` point instead of (x, y)
    follow: str | None = None  # take the same variant name as this part (items follow the arm's pose)

    @property
    def default(self) -> str:
        return next(iter(self.variants))


def mirror_variants(variants: dict[str, V], x_from: int, x_to: int, axis: int = 15) -> dict[str, V]:
    """Mirror a right-side part's variants to the left side (`axis` = sum of mirrored columns)."""
    out: dict[str, V] = {}
    for name, var in variants.items():
        w = var.w
        rows = tuple(r.ljust(w, ".")[::-1] for r in var.rows)
        b = x_from + var.ox + w - 1  # rightmost absolute column on the right side
        ox = (axis - b) - x_to
        hand = (w - 1 - var.hand[0], var.hand[1]) if var.hand else None
        out[name] = V(rows, ox, var.oy, hand, (w - 1 - var.grip[0], var.grip[1]))
    return out


# --------------------------------------------------------------------------- anims
@dataclass
class Anim:
    """Keyframes: (duration_s, {part: (dx, dy) | (dx, dy, variant) | variant, "root": (dx, dy),
    "sq": ±1, "fx": [(sprite, anchor, dx, dy), ...]}). `tween` interpolates offsets between keyframes."""

    frames: list[tuple[float, dict[str, Any]]]
    tween: bool = False
    beat: int = 0  # extra upward bounce in px at beat=1 (music pulse)
    _norm: list[tuple[float, dict[str, tuple[int, int, str | None]], tuple[int, int], int, tuple]] = field(
        default_factory=list, repr=False
    )
    total: float = 0.0

    def compile(self) -> Anim:
        norm = []
        start = 0.0
        for dur, kf in self.frames:
            parts: dict[str, tuple[int, int, str | None]] = {}
            root = (0, 0)
            sq = 0
            fx: tuple = ()
            for k, val in kf.items():
                if k == "root":
                    root = (int(val[0]), int(val[1]))
                elif k == "sq":
                    sq = int(val)
                elif k == "fx":
                    fx = tuple((str(a[0]), str(a[1]), int(a[2]), int(a[3])) for a in val)
                elif isinstance(val, str):
                    parts[k] = (0, 0, val)
                elif len(val) == 2:
                    parts[k] = (int(val[0]), int(val[1]), None)
                else:
                    parts[k] = (int(val[0]), int(val[1]), val[2])
            norm.append((start, parts, root, sq, fx))
            start += max(0.01, float(dur))
        self._norm = norm
        self.total = start
        return self


def _lerp(a: int, b: int, u: float) -> int:
    return round(a + (b - a) * u)


def sample(
    anim: Anim, t: float
) -> tuple[dict[str, tuple[int, int, str | None]], tuple[int, int], int, tuple]:
    """Resolve an animation at time t -> (parts, root, sq, fx)."""
    frames = anim._norm
    n = len(frames)
    tt = t % anim.total if anim.total > 0 else 0.0
    i = 0
    while i + 1 < n and frames[i + 1][0] <= tt:
        i += 1
    start, parts, root, sq, fx = frames[i]
    if not anim.tween or n == 1:
        return parts, root, sq, fx
    end = frames[i + 1][0] if i + 1 < n else anim.total
    u = (tt - start) / max(1e-6, end - start)
    u = u * u * (3 - 2 * u)  # smoothstep
    _, nparts, nroot, _, nfx = frames[(i + 1) % n]
    out: dict[str, tuple[int, int, str | None]] = {}
    for k in parts.keys() | nparts.keys():
        a = parts.get(k, (0, 0, None))
        b = nparts.get(k, (0, 0, None))
        out[k] = (_lerp(a[0], b[0], u), _lerp(a[1], b[1], u), a[2])
    r = (_lerp(root[0], nroot[0], u), _lerp(root[1], nroot[1], u))
    if fx and nfx:
        fx2 = []
        for j, e in enumerate(fx):
            if j < len(nfx) and nfx[j][0] == e[0] and nfx[j][1] == e[1]:
                fx2.append((e[0], e[1], _lerp(e[2], nfx[j][2], u), _lerp(e[3], nfx[j][3], u)))
            else:
                fx2.append(e)
        fx = tuple(fx2)
    return out, r, sq, fx


# --------------------------------------------------------------------------- global sprites (fx, props)
class Sheet:
    """Sprites that don't belong to one character (effects, props, accessories): fixed colours only."""

    def __init__(self) -> None:
        self.colors: list[RGB] = []
        self._cidx: dict[RGB, int] = {}
        self.sprites: dict[str, np.ndarray] = {}

    def color(self, c: RGB) -> int:
        if c not in self._cidx:
            self._cidx[c] = len(self.colors)
            self.colors.append(c)
        return self._cidx[c]

    def add(self, name: str, rows: tuple[str, ...] | list[str], key: dict[str, str]) -> None:
        h = len(rows)
        w = max((len(r) for r in rows), default=0)
        arr = np.full((h, w), -1, np.int16)
        for yy, row in enumerate(rows):
            for xx, ch in enumerate(row):
                if ch in ". ":
                    continue
                arr[yy, xx] = self.color(to_rgb(key[ch]))
        self.sprites[name] = arr


SHEET = Sheet()


# --------------------------------------------------------------------------- the rig
@dataclass
class Rig:
    id: str
    name: str
    group: str
    description: str
    slots: dict[str, RGB]
    key: dict[str, str]
    parts: dict[str, Part]
    anims: dict[str, Anim]
    anchors: dict[str, tuple[str, int, int]]  # name -> (parent part, x, y) in character space
    eyes: dict[str, Any] | None = None  # eye spec (see parts.eye_variants); compiled into the "eyes" part
    w: int = 16
    h: int = 16
    squash_row: int = 10
    head_box: tuple[int, int, int, int] = (3, 0, 12, 7)  # x0, y0, x1, y1 (inclusive) of the head, neutral
    head_part: str = "head"

    @property
    def eye_pts(self) -> list[tuple[int, int]]:
        return list(self.eyes["pts"]) if self.eyes else [(self.w // 2, self.h // 3)]

    @property
    def eye_w(self) -> int:
        return int(self.eyes.get("w", 1)) if self.eyes else 1

    @property
    def eye_h(self) -> int:
        return int(self.eyes.get("h", 2)) if self.eyes else 2

    @property
    def eye_y(self) -> int:
        return min(p[1] for p in self.eye_pts)

    def __post_init__(self) -> None:
        self._specs: list[str] = []
        self._spec_idx: dict[str, int] = {}
        self._arrays: dict[tuple[str, str], np.ndarray] = {}
        self._order = sorted(self.parts, key=lambda p: self.parts[p].z)
        self._comp: OrderedDict[tuple, tuple[np.ndarray, tuple]] = OrderedDict()
        self._rgb: OrderedDict[tuple, tuple[np.ndarray, np.ndarray]] = OrderedDict()
        self._luts: dict[tuple, np.ndarray] = {}
        self._chain: dict[str, list[str]] = {}
        for name in self.parts:
            chain = []
            p: str | None = name
            seen = 0
            while p and p != "root" and seen < 16:
                chain.append(p)
                p = self.parts[p].parent if p in self.parts else None
                seen += 1
            self._chain[name] = chain
        for pname, part in self.parts.items():
            for vname, var in part.variants.items():
                self._arrays[(pname, vname)] = self._parse(var.rows)

    # ------------------------------------------------------------ parsing
    def _spec(self, spec: str) -> int:
        if spec not in self._spec_idx:
            self._check_spec(spec)
            self._spec_idx[spec] = len(self._specs)
            self._specs.append(spec)
        return self._spec_idx[spec]

    def _check_spec(self, spec: str) -> None:
        if spec.startswith("#"):
            to_rgb(spec)
            return
        base = spec.split("*")[0].split("^")[0]
        if base not in self.slots:
            raise KeyError(f"{self.id}: slot {base!r} (from {spec!r}) not defined")

    def _parse(self, rows: tuple[str, ...]) -> np.ndarray:
        h = len(rows)
        w = max((len(r) for r in rows), default=0)
        arr = np.full((h, w), -1, np.int16)
        for yy, row in enumerate(rows):
            for xx, ch in enumerate(row):
                if ch in ". ":
                    continue
                if ch not in self.key:
                    raise KeyError(f"{self.id}: char {ch!r} not in key")
                arr[yy, xx] = self._spec(self.key[ch])
        return arr

    # ------------------------------------------------------------ colours
    def lut(self, colors: dict[str, RGB] | None) -> np.ndarray:
        ck = tuple(sorted(colors.items())) if colors else ()
        lut = self._luts.get(ck)
        if lut is not None and len(lut) == len(self._specs) + len(SHEET.colors):
            return lut
        slots = dict(self.slots)
        if colors:
            slots.update({k: c for k, c in colors.items() if k in slots})
        rows: list[RGB] = []
        for spec in self._specs:
            if spec.startswith("#"):
                rows.append(to_rgb(spec))
            elif "*" in spec:
                base, k = spec.split("*")
                rows.append(cscale(slots[base], float(k)))
            elif "^" in spec:
                base, k = spec.split("^")
                rows.append(mix(slots[base], (255, 255, 255), float(k)))
            else:
                rows.append(slots[spec])
        rows.extend(SHEET.colors)
        lut = np.array(rows or [(0, 0, 0)], np.uint8).reshape(-1, 3)
        if len(self._luts) > 64:
            self._luts.clear()
        self._luts[ck] = lut
        return lut

    # ------------------------------------------------------------ composing
    def variant(self, pname: str, want: str | None) -> str:
        part = self.parts[pname]
        if want and want in part.variants:
            return want
        return part.default

    def compose(
        self, pose: tuple, extra: tuple[tuple[str, str, int, int], ...]
    ) -> tuple[np.ndarray, tuple[tuple[str, int, int], ...]]:
        """pose: tuple of (part, dx, dy, variant) for every part; extra: global sprites (name, anchor, dx, dy)."""
        key = (pose, extra)
        hit = self._comp.get(key)
        if hit is not None:
            self._comp.move_to_end(key)
            return hit
        W, H = self.w + 2 * PAD, self.h + 2 * PAD
        canvas = np.full((H, W), -1, np.int16)
        offs = {p: (dx, dy) for p, dx, dy, _ in pose}
        vars_ = {p: var for p, _, _, var in pose}
        pos: dict[str, tuple[int, int]] = {}

        def acc(pname: str) -> tuple[int, int]:
            ox = oy = 0
            for p in self._chain[pname]:
                d = offs.get(p, (0, 0))
                ox += d[0]
                oy += d[1]
            return ox, oy

        def place(pname: str) -> tuple[int, int]:
            if pname in pos:
                return pos[pname]
            part = self.parts[pname]
            if part.attach and part.attach in self.parts:
                ax, ay = place(part.attach)
                av = self.parts[part.attach].variants[
                    vars_.get(part.attach) or self.parts[part.attach].default
                ]
                hx, hy = av.hand or (0, 0)
                me = part.variants[vars_.get(pname) or part.default]
                d = offs.get(pname, (0, 0))
                r = (ax + av.ox + hx - me.grip[0] - me.ox + d[0], ay + av.oy + hy - me.grip[1] - me.oy + d[1])
            else:
                dx, dy = acc(pname)
                r = (part.x + dx, part.y + dy)
            pos[pname] = r
            return r

        n_char = len(self._specs)
        items: list[tuple[int, np.ndarray, int, int]] = []
        for pname in self._order:
            vname = vars_.get(pname)
            if vname == "-":  # hidden
                continue
            vname = vname or self.parts[pname].default
            var = self.parts[pname].variants[vname]
            px, py = place(pname)
            items.append((self.parts[pname].z, self._arrays[(pname, vname)], px + var.ox, py + var.oy))
        emotes: list[tuple[str, int, int, int, int]] = []
        for name, anchor, dx, dy in extra:
            spr = SHEET.sprites.get(name)
            if spr is None:
                continue
            ax, ay = self.anchor(anchor, place, vars_)
            if name in EMOTES or name in PROJECTILES:
                emotes.append((name, ax, ay, dx, dy))
                continue
            sh, sw = spr.shape
            items.append(
                (
                    1000,
                    np.where(spr >= 0, spr + n_char, -1).astype(np.int16),
                    ax + dx - sw // 2,
                    ay + dy - sh // 2,
                )
            )
        items.sort(key=lambda it: it[0])
        for _, arr, x, y in items:
            _stamp(canvas, arr, x + PAD, y + PAD)
        sq = dict((p, dx) for p, dx, _, _ in pose if p == "__sq__").get("__sq__", 0)
        if sq:
            canvas = _squash(canvas, self.squash_row + PAD, sq, self.h + PAD)
        out = (canvas, tuple(emotes))
        if len(self._comp) > 512:
            self._comp.popitem(last=False)
        self._comp[key] = out
        return out

    def anchor(self, name: str, place: Any, vars_: dict[str, str | None]) -> tuple[int, int]:
        if name in ("hand_r", "hand_l"):
            arm = "arm_r" if name == "hand_r" else "arm_l"
            if arm in self.parts:
                ax, ay = place(arm)
                var = self.parts[arm].variants[vars_.get(arm) or self.parts[arm].default]
                hx, hy = var.hand or (0, var.h - 1)
                return ax + var.ox + hx, ay + var.oy + hy
            name = "mouth"
        if name == "ground":
            return self.w // 2, self.h
        a = self.anchors.get(name)
        if a is None:
            return self.w // 2, self.h // 2
        parent, x, y = a
        if parent in self.parts:
            px, py = place(parent)
            part = self.parts[parent]
            return x + px - part.x, y + py - part.y
        return x, y


def _stamp(canvas: np.ndarray, arr: np.ndarray, x: int, y: int) -> None:
    H, W = canvas.shape
    h, w = arr.shape
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    sub = arr[y0 - y : y1 - y, x0 - x : x1 - x]
    dst = canvas[y0:y1, x0:x1]
    m = sub >= 0
    dst[m] = sub[m]


def _squash(canvas: np.ndarray, row: int, sq: int, bottom: int) -> np.ndarray:
    """sq>0: drop `sq` copies of `row` (everything above sinks); sq<0: duplicate it (stretch up)."""
    out = canvas.copy()
    if sq > 0:
        k = min(sq, row)
        out[k : row + 1] = canvas[0 : row + 1 - k]
        out[:k] = -1
    else:
        k = min(-sq, row)
        out[0 : row - k + 1] = canvas[k : row + 1]
        out[row - k + 1 : row + 1] = canvas[row]
    return out
