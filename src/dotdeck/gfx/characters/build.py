"""Builders that turn compact character descriptions into rigs (biped and quadruped body plans)."""

from __future__ import annotations

from typing import Any

from .anims import biped_anims, compile_all, quad_anims
from .parts import FEET, LEGS, eyes_part, humanoid_limbs, nub_arms
from .rig import Part, Rig, V, v

RIGS: dict[str, Rig] = {}
EXTRAS: dict[str, tuple[str, ...]] = {}

BASE_KEY = {"e": "#0c0c12", "W": "#ffffff", "k": "#0c0c12", "M": "#9c1e32"}


def _shade_key(k: dict[str, str]) -> dict[str, str]:
    """Default the sleeve shade C to the sleeve colour darkened."""
    if "C" not in k and "c" in k and not k["c"].startswith("#"):
        k["C"] = k["c"].split("*")[0].split("^")[0] + "*0.7"
    elif "C" not in k and "c" in k:
        k["C"] = k["c"]
    if "S" not in k and "s" in k and not k["s"].startswith("#"):
        k["S"] = k["s"].split("*")[0].split("^")[0] + "*0.8"
    return k


def _box(rows: tuple[str, ...], x: int, y: int) -> tuple[int, int, int, int]:
    xs = [i for r in rows for i, ch in enumerate(r) if ch not in ". "]
    ys = [j for j, r in enumerate(rows) if any(ch not in ". " for ch in r)]
    return x + min(xs), y + min(ys), x + max(xs), y + max(ys)


def _as_variants(d: Any) -> dict[str, V]:
    if isinstance(d, V):
        return {"default": d}
    if isinstance(d, dict):
        return {k: (val if isinstance(val, V) else v(*val)) for k, val in d.items()}
    return {"default": v(*d)}


def _mouth(spec: Any) -> Part | None:
    if spec is None:
        return None
    if isinstance(spec, Part):
        return spec
    x, y = spec[0], spec[1]
    parent = spec[2] if len(spec) > 2 else "head"
    return Part(x, y, {"closed": v(), "open": v("M"), "-": v()}, parent=parent, z=21)


def _register(rig: Rig, extras: tuple[str, ...]) -> Rig:
    RIGS[rig.id] = rig
    EXTRAS[rig.id] = extras
    return rig


def biped(
    id: str,
    name: str,
    group: str,
    desc: str,
    *,
    slots: dict[str, tuple[int, int, int]],
    key: dict[str, str],
    head: Any,
    torso: Any,
    eyes: dict[str, Any],
    head_xy: tuple[int, int] = (3, 0),
    torso_xy: tuple[int, int] = (4, 8),
    limbs: str = "human",
    arms_xy: tuple[int, int, int] = (12, 2, 8),
    feet_xy: tuple[int, int] = (5, 14),
    mouth: Any = None,
    item: dict[str, Any] | None = None,
    parts: dict[str, Part] | None = None,
    legs: dict[str, Any] | None = None,
    arms: dict[str, Any] | None = None,
    opts: dict[str, Any] | None = None,
    anchors: dict[str, tuple[str, int, int]] | None = None,
    extras: tuple[str, ...] = (),
    squash_row: int = 10,
    lap: tuple[int, int] = (8, 12),
) -> Rig:
    k = _shade_key({**BASE_KEY, **key})
    hx, hy = head_xy
    head_v = _as_variants(head)
    ps: dict[str, Part] = {
        "body": Part(torso_xy[0], torso_xy[1], _as_variants(torso), z=1),
        "head": Part(hx, hy, head_v, parent="body", z=3),
    }
    if limbs == "human":
        ps.update(humanoid_limbs())
    else:
        xr, xl, ay = arms_xy
        ps.update(nub_arms(xr, xl, ay))
        ps["legs"] = Part(feet_xy[0], feet_xy[1], dict(FEET), z=0)
    if legs:
        base = dict(ps["legs"].variants)
        base.update(_as_variants(legs))
        ps["legs"].variants = base
    if arms:
        for side, var in arms.items():
            if var is None:
                ps.pop(side, None)
            else:
                ps[side].variants = {**ps[side].variants, **_as_variants(var)}
    ps["eyes"] = eyes_part(eyes)
    m = _mouth(mouth)
    if m:
        ps["mouth"] = m
    if item:
        ps["item"] = Part(0, 0, _as_variants(item), parent="arm_r", z=6, attach="arm_r", follow="arm_r")
    if parts:
        ps.update(parts)
    first = next(iter(head_v.values()))
    box = _box(first.rows, hx + first.ox, hy + first.oy)
    pts = eyes["pts"]
    ew, eh = eyes.get("w", 1), eyes.get("h", 2)
    cx = (box[0] + box[2] + 1) // 2
    ex = (min(p[0] for p in pts) + max(p[0] for p in pts) + ew) // 2
    ey = min(p[1] for p in pts)
    anc = {
        "hat": ("head", cx, box[1]),
        "eyes": ("head", ex, ey),
        "eye": ("head", max(p[0] for p in pts), ey + eh),
        "mouth": ("head", max(p[0] for p in pts), ey + eh + 1),
        "neck": ("head", cx, min(box[3] + 1, ey + eh + 2)),
        "feet": ("root", 12, 14),
        "lap": ("body", lap[0], lap[1]),
        "bowl": ("root", 13, 14),
    }
    if m:
        anc["mouth"] = (m.parent, m.x, m.y)
    if anchors:
        anc.update(anchors)
    o = dict(opts or {})
    o["extras"] = extras
    rig = Rig(
        id,
        name,
        group,
        desc,
        dict(slots),
        k,
        ps,
        compile_all(biped_anims(o)),
        anc,
        eyes,
        squash_row=squash_row,
        head_box=box,
    )
    return _register(rig, extras)


def quad(
    id: str,
    name: str,
    group: str,
    desc: str,
    *,
    slots: dict[str, tuple[int, int, int]],
    key: dict[str, str],
    head: Any,
    head_xy: tuple[int, int],
    body: Any,
    body_xy: tuple[int, int],
    rump: Any,
    rump_xy: tuple[int, int],
    tail: dict[str, Any],
    tail_xy: tuple[int, int],
    legs_xy: tuple[int, int, int],  # front x, back x, top y
    leg_h: int = 3,
    eyes: dict[str, Any],
    mouth: Any = None,
    parts: dict[str, Part] | None = None,
    opts: dict[str, Any] | None = None,
    anchors: dict[str, tuple[str, int, int]] | None = None,
    extras: tuple[str, ...] = (),
    squash_row: int = 9,
) -> Rig:
    from .parts import quad_legs

    k = {**BASE_KEY, **key}
    head_v = _as_variants(head)
    ps: dict[str, Part] = {
        "body": Part(body_xy[0], body_xy[1], _as_variants(body), z=1),
        "rump": Part(rump_xy[0], rump_xy[1], _as_variants(rump), parent="body", z=1),
        "head": Part(head_xy[0], head_xy[1], head_v, parent="body", z=4),
        "tail": Part(tail_xy[0], tail_xy[1], _as_variants(tail), parent="rump", z=0),
    }
    fx_, bx_, ly = legs_xy
    legs = quad_legs(fx_, bx_, ly, leg_h)
    legs["leg_bn"].parent = legs["leg_bf"].parent = "root"
    ps.update(legs)
    ps["eyes"] = eyes_part(eyes)
    m = _mouth(mouth)
    if m:
        ps["mouth"] = m
    if parts:
        ps.update(parts)
    first = next(iter(head_v.values()))
    box = _box(first.rows, head_xy[0] + first.ox, head_xy[1] + first.oy)
    pts = eyes["pts"]
    ew, eh = eyes.get("w", 1), eyes.get("h", 2)
    ey = min(p[1] for p in pts)
    ex = (min(p[0] for p in pts) + max(p[0] for p in pts) + ew) // 2
    cx = (box[0] + box[2] + 1) // 2
    anc = {
        "hat": ("head", cx, box[1]),
        "eyes": ("head", ex, ey),
        "eye": ("head", max(p[0] for p in pts), ey + eh),
        "mouth": ("head", box[2], box[3] - 1),
        "neck": ("head", cx - 1, box[3]),
        "feet": ("root", min(15, fx_ + 4), 14),
        "bowl": ("root", min(14, box[2]), 14),
        "lap": ("root", min(13, fx_ + 3), 13),
    }
    if m:
        anc["mouth"] = (m.parent, m.x, m.y)
    if anchors:
        anc.update(anchors)
    rig = Rig(
        id,
        name,
        group,
        desc,
        dict(slots),
        k,
        ps,
        compile_all(quad_anims(dict(opts or {}))),
        anc,
        eyes,
        squash_row=squash_row,
        head_box=box,
    )
    return _register(rig, extras)


__all__ = ["EXTRAS", "LEGS", "RIGS", "biped", "quad"]
