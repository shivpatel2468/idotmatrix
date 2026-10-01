"""Claude: Clawd, the orange Claude Code crab-ish mascot, and a pocket-sized Clawd."""

from __future__ import annotations

from .build import biped
from .rig import v

# Claude's brand terracotta is #D97757 on screens, but on the LED panel (after calibration) that reads as a
# washed-out salmon/pink — verified on hardware 2026-09-27. This saturated orange is what reads as Claude orange
# on the LEDs. Clawd stays one flat colour.
CLAUDE_ORANGE = (249, 74, 24)  # #F94A18, picked by eye on the panel from a side-by-side card

_CLAWD_LEGS = {
    "stand": v("b.b....b.b", "b.b....b.b", "b.b....b.b"),
    "walk_a": v("b.b....b.b", "b.b....b..", "b......b.."),
    "walk_b": v("b.b....b.b", "..b......b", "..b......b"),
    "run_a": v("b.b....b.b", ".b.b....b.b", "b...b..b...b", ox=-1),
    "run_b": v("b.b....b.b", "b.b....b.b"),
    "crouch": v("b.b....b.b", "b.b....b.b", oy=1),
    "sit": v("bb.b..b.bb", oy=2),
    "tuck": v("b.b....b.b", "b.b....b.b"),
    "kick_back": v("b.b....b.b", "b.b...b.b.", "b.b..b.b.."),
    "kick_fwd": v("b.b....b.b", "b.b.....b.b", "b.b.......bb"),
}

biped(
    "clawd",
    "Clawd",
    "claude",
    "The Claude Code mascot: a chunky orange block with two dark eyes, stubby arms and four little legs.",
    slots={"body": CLAUDE_ORANGE, "eyes": (12, 10, 14)},
    key={
        "b": "body",
        "B": "body",  # Clawd is one flat colour — no highlight or shade rows
        "h": "body",
        "c": "body",
        "n": "body",
        "f": "body",
        "p": "body",
        "e": "eyes",
    },
    head=(
        "hhhhhhhhhhhh",
        "bbbbbbbbbbbb",
        "bbbbbbbbbbbb",
        "bbbbbbbbbbbb",
        "bbbbbbbbbbbb",
        "bbbbbbbbbbbb",
        "bbbbbbbbbbbb",
        "BBBBBBBBBBBB",
    ),
    head_xy=(2, 4),
    torso=("",),
    torso_xy=(2, 4),
    eyes={"pts": [(5, 6), (10, 6)], "w": 1, "h": 2},
    limbs="nub",
    arms_xy=(14, 0, 8),
    parts=None,
    legs=_CLAWD_LEGS,
    feet_xy=(3, 12),
    mouth=(8, 9),
    opts={"food": "cookie", "sit_drop": 2, "attack_fx": "orb"},
    extras=("think",),
    squash_row=8,
    lap=(8, 9),
)

_MINI_LEGS = {
    "stand": v("b.b..b.b", "b.b..b.b"),
    "walk_a": v("b.b..b.b", "b....b.."),
    "walk_b": v("b.b..b.b", "..b....b"),
    "run_a": v("b.b..b.b", ".b.b...b.b", ox=-1),
    "run_b": v(
        "b.b..b.b",
    ),
    "crouch": v("b.b..b.b", oy=1),
    "sit": v("bb.b.bb", oy=1),
    "tuck": v(
        "b.b..b.b",
    ),
    "kick_back": v("b.b..b.b", "b.b.b.b."),
    "kick_fwd": v("b.b..b.b", "b.b.....bb"),
}

biped(
    "claude_mini",
    "Clawd Mini",
    "claude",
    "A pocket-sized Clawd: same orange block, extra bouncy.",
    slots={"body": CLAUDE_ORANGE, "eyes": (12, 10, 14)},
    key={
        "b": "body",
        "B": "body",  # Clawd is one flat colour — no highlight or shade rows
        "h": "body",
        "c": "body",
        "n": "body",
        "f": "body",
        "p": "body",
        "e": "eyes",
    },
    head=(
        "hhhhhhhh",
        "bbbbbbbb",
        "bbbbbbbb",
        "bbbbbbbb",
        "bbbbbbbb",
        "BBBBBBBB",
    ),
    head_xy=(4, 8),
    torso=("",),
    torso_xy=(4, 8),
    eyes={"pts": [(6, 10), (9, 10)], "w": 1, "h": 2},
    limbs="nub",
    arms_xy=(12, 2, 10),
    legs=_MINI_LEGS,
    feet_xy=(4, 14),
    opts={"food": "cookie", "sit_drop": 1},
    extras=("think",),
    squash_row=11,
    lap=(8, 12),
)
