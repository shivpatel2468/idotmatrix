"""Character / pet sprites: ~45 original pixel characters on a part-based rig.

    from dotdeck.gfx.characters import draw_character, CHARACTERS
    draw_character(f, "clawd", "dance", t, 0, 0, scale=2, beat=pulse)

Every character supports the COMMON animations (idle, walk, run, jump, dance, sleep, sit, eat, happy, sad,
wave, kick, work) plus group extras (troops: attack/cast, fps: shoot/reload/crouch, monsters: attack,
claude: think). Recolour through `colors={slot: "#rrggbb"}`; the slots are listed per character.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from ..color import to_rgb
from ..frame import Frame
from . import claude, critters, dogs_cats, fps, monsters, sports, troops, tv  # noqa: F401 — registers rigs
from .accessories import ACCESSORIES, accessory_fx
from .anims import COMMON
from .build import EXTRAS, RIGS
from .rig import PAD, PROJECTILES, SHEET, Rig, sample


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    group: str
    description: str
    w: int
    h: int
    slots: dict[str, tuple[int, int, int]]
    anims: tuple[str, ...]


GROUPS: dict[str, str] = {
    "claude": "Claude",
    "dogs": "Dogs",
    "cats": "Cats",
    "critters": "Critters",
    "monsters": "Monsters",
    "troops": "Troops",
    "fps": "Shooters",
    "tv": "TV & Cartoons",
    "sports": "Sports",
}

_ORDER = {g: i for i, g in enumerate(GROUPS)}

CHARACTERS: dict[str, Character] = {
    r.id: Character(r.id, r.name, r.group, r.description, r.w, r.h, dict(r.slots), tuple(r.anims))
    for r in sorted(RIGS.values(), key=lambda r: _ORDER.get(r.group, 99))
}

_all: list[str] = list(COMMON)
for _r in RIGS.values():
    for _a in _r.anims:
        if _a not in _all:
            _all.append(_a)
ANIMS: tuple[str, ...] = tuple(_all)

_RGB: OrderedDict[tuple, tuple[np.ndarray, np.ndarray, tuple]] = OrderedDict()
_EMO: dict[str, tuple[np.ndarray, np.ndarray]] = {}


def _emote(name: str) -> tuple[np.ndarray, np.ndarray]:
    hit = _EMO.get(name)
    if hit is None or len(_EMO) == 0:
        arr = SHEET.sprites[name]
        lut = np.array(SHEET.colors, np.uint8).reshape(-1, 3)
        m = arr >= 0
        hit = (np.ascontiguousarray(lut[np.where(m, arr, 0)]), m)
        _EMO[name] = hit
    return hit


def _colors(rig: Rig, colors: dict[str, str] | None) -> dict[str, tuple[int, int, int]] | None:
    if not colors:
        return None
    out = {}
    for k, c in colors.items():
        if k in rig.slots and c:
            try:
                out[k] = to_rgb(c)
            except (ValueError, TypeError):
                continue
    return out or None


def _pose(rig: Rig, parts: dict[str, tuple[int, int, str | None]]) -> tuple:
    pose = []
    for pname in rig._order:
        part = rig.parts[pname]
        d = parts.get(pname)
        want = d[2] if d else None
        if want is None and part.follow:
            f = parts.get(part.follow)
            want = f[2] if f else None
        var = "-" if want == "-" else rig.variant(pname, want)
        if d:
            pose.append((pname, d[0], d[1], var))
        else:
            pose.append((pname, 0, 0, var))
    return tuple(pose)


def draw_character(
    f: Frame,
    char_id: str,
    anim: str,
    t: float,
    x: int,
    y: int,
    *,
    colors: dict[str, str] | None = None,
    flip: bool = False,
    scale: int = 1,
    beat: float = 0.0,
    accessory: str = "none",
) -> tuple[int, int, int, int]:
    """Draw with top-left at (x, y); returns the drawn bbox (x, y, w, h). `beat` 0..1 is a music pulse that
    accents dance/idle (bounce harder on the beat). Unknown anim falls back to idle. scale 1 or 2."""
    rig = RIGS.get(char_id) or RIGS["clawd"]
    an = rig.anims.get(anim) or rig.anims["idle"]
    s = 2 if scale >= 2 else 1
    parts, root, sq, fx = sample(an, t)
    pose = _pose(rig, parts)
    b = max(0.0, min(1.0, float(beat or 0.0)))
    bounce = round(an.beat * b) if an.beat else 0
    if an.beat and b > 0.75 and not sq:
        sq = -1 if anim == "dance" else 0
    if sq:
        pose = (*pose, ("__sq__", sq, 0, None))
    extra = fx
    acc = accessory_fx(rig, accessory) if accessory and accessory != "none" else None
    if acc:
        extra = (*fx, acc)
    cols = _colors(rig, colors)
    ck = tuple(sorted(cols.items())) if cols else ()
    key = (rig.id, pose, extra, ck, bool(flip), s)
    hit = _RGB.get(key)
    if hit is None:
        canvas, emotes = rig.compose(pose, extra)
        lut = rig.lut(cols)
        mask = canvas >= 0
        px = lut[np.where(mask, canvas, 0)]
        if flip:
            px = px[:, ::-1]
            mask = mask[:, ::-1]
        if s == 2:
            px = px.repeat(2, 0).repeat(2, 1)
            mask = mask.repeat(2, 0).repeat(2, 1)
        hit = (np.ascontiguousarray(px), np.ascontiguousarray(mask), emotes)
        if len(_RGB) > 2048:
            _RGB.popitem(last=False)
        _RGB[key] = hit
    else:
        _RGB.move_to_end(key)
    rx, ry = root
    if flip:
        rx = -rx
    ry -= bounce
    f.blit(hit[0], x + (rx - PAD) * s, y + (ry - PAD) * s, hit[1])
    for name, ax, ay, dx, dy in hit[2]:
        px, m = _emote(name)
        eh, ew = m.shape
        if name in PROJECTILES:  # launched from the scaled anchor, flying in panel pixels
            cx = (rig.w - 1 - ax if flip else ax) + rx
            sx = x + cx * s + (s - 1) // 2 + (-dx if flip else dx) - ew // 2
            sy = y + (ay + ry) * s + (s - 1) // 2 + dy - eh // 2
            f.blit(px[:, ::-1] if flip else px, sx, sy, m[:, ::-1] if flip else m)
            continue
        ex, ey = ax + dx, ay + dy
        cx = (rig.w - 1 - ex if flip else ex) + rx
        sx = x + cx * s + (s - 1) // 2 - ew // 2
        sy = y + (ey + ry) * s - eh // 2
        sx = max(0, min(32 - ew, sx))  # keep emotes on the panel
        sy = max(0, min(32 - eh, sy))
        f.blit(px, sx, sy, m)
    return x, y, rig.w * s, rig.h * s


def list_characters(group: str | None = None) -> list[Character]:
    return [c for c in CHARACTERS.values() if group is None or c.group == group]


def extras(char_id: str) -> tuple[str, ...]:
    return EXTRAS.get(char_id, ())


@lru_cache(maxsize=128)
def foot_gap(char_id: str) -> int:
    """Empty rows between a character's feet (idle pose, scale 1) and the bottom of its box. Add it to y to
    stand the character exactly on a floor line instead of floating above it (Clawd's legs end 1 px short)."""
    c = CHARACTERS.get(char_id) or CHARACTERS["clawd"]
    f = Frame()
    draw_character(f, char_id, "idle", 0.0, 0, 0)
    rows = np.flatnonzero(f.px[: c.h].any(axis=(1, 2)))
    return c.h - 1 - int(rows[-1]) if rows.size else 0


def step_anim_time(char_id: str, anim: str, t_anim: float, dt: float) -> float:
    """Advance an animation clock by `dt` without ever skipping a pose.

    Streamed apps show frames at the link's pace (~6 fps), but many poses are shorter than a frame (a walk step
    is 0.14 s). Sampling real time then skips poses unevenly — legs judder. This clock lands on the next pose's
    start instead of jumping past it: every pose is shown at least once, long poses still hold their time.
    """
    rig = RIGS.get(char_id) or RIGS["clawd"]
    an = rig.anims.get(anim) or rig.anims["idle"]
    if an.total <= 0 or dt <= 0:
        return t_anim + max(0.0, dt)
    base = t_anim - (t_anim % an.total)
    tt = t_anim % an.total
    starts = [fr[0] for fr in an._norm]
    i = 0
    while i + 1 < len(starts) and starts[i + 1] <= tt:
        i += 1
    nxt = starts[i + 1] if i + 1 < len(starts) else an.total
    # land just past the next pose's start: exact landings on a boundary read back (after `% total` on a large
    # clock) as 0.1399999… < 0.14 — still the old pose — and the clock would stall forever
    return base + min(tt + dt, nxt + 1e-6)


__all__ = [
    "ACCESSORIES",
    "ANIMS",
    "CHARACTERS",
    "GROUPS",
    "Character",
    "draw_character",
    "foot_gap",
    "list_characters",
    "step_anim_time",
]
