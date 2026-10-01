"""Keyframed animations shared by every character of a body plan (biped / quadruped).

Characters face right; `flip` mirrors them. Offsets are in character pixels. Parts a character lacks are
simply ignored, so one table serves humans, chibi critters, monsters and the Claude crab alike.
"""

from __future__ import annotations

from typing import Any

from .rig import Anim

COMMON = (
    "idle",
    "walk",
    "run",
    "jump",
    "dance",
    "sleep",
    "sit",
    "eat",
    "happy",
    "sad",
    "wave",
    "kick",
    "work",
)

KF = tuple[float, dict[str, Any]]


def _idle(sit: dict[str, Any] | None = None, look: str = "head") -> Anim:
    b = dict(sit or {})
    down = {**b, "body": (0, (b.get("body", (0, 0))[1]) + 1)}
    return Anim(
        [
            (0.7, b),
            (0.6, down),
            (0.7, b),
            (0.12, {**b, "eyes": "closed"}),
            (0.6, down),
            (0.7, {**b, look: (1, 0)} if look else b),
            (0.6, {**down, look: (1, 0)} if look else down),
            (0.5, b),
            (0.12, {**b, "eyes": "closed"}),
            (0.3, b),
        ],
        beat=1,
    )


# --------------------------------------------------------------------------- biped
def biped_anims(o: dict[str, Any]) -> dict[str, Anim]:
    """o: food, attack ('melee'|'bow'|'magic'|'punch'|'breath'), attack_fx, extras (tuple of anim names),
    sit_drop (how far the torso sinks when seated), gun (bool)."""
    food = o.get("food", "apple")
    drop = o.get("sit_drop", 2)
    tail = {"tail": "b"}
    seat = {"body": (0, drop), "legs": "sit"}
    a: dict[str, Anim] = {}
    armed = {"arm_r": "hold", "arm_l": "hold"} if o.get("gun") else {}
    a["idle"] = _idle(armed or None)
    a["walk"] = Anim(
        [
            (
                0.14,
                {
                    **armed,
                    "legs": "walk_a",
                    "arm_r": armed.get("arm_r", "down"),
                    "arm_l": (0, 1, armed.get("arm_l")),
                    **tail,
                },
            ),
            (0.14, {**armed, "legs": "stand", "root": (0, -1)}),
            (0.14, {**armed, "legs": "walk_b", "arm_r": (0, 1, armed.get("arm_r")), **tail}),
            (0.14, {**armed, "legs": "stand", "root": (0, -1)}),
        ]
    )
    a["run"] = Anim(
        [
            (
                0.1,
                {"legs": "run_a", "root": (0, -1), "head": (1, 0), "arm_r": "fwd", "arm_l": "back", **tail},
            ),
            (0.1, {"legs": "run_b", "head": (1, 0), "arm_r": "out", "arm_l": "out"}),
            (
                0.1,
                {"legs": "run_a", "root": (0, -2), "head": (1, 0), "arm_r": "back", "arm_l": "fwd", **tail},
            ),
            (0.1, {"legs": "run_b", "head": (1, 0), "arm_r": "out", "arm_l": "out"}),
        ]
    )
    a["jump"] = Anim(
        [
            (0.16, {"legs": "crouch", "body": (0, 1), "sq": 1, "arm_r": "out", "arm_l": "out"}),
            (0.1, {"root": (0, -3), "legs": "tuck", "arm_r": "up", "arm_l": "up", "sq": -1}),
            (0.2, {"root": (0, -6), "legs": "tuck", "arm_r": "up", "arm_l": "up", "eyes": "happy", **tail}),
            (0.12, {"root": (0, -3), "legs": "stand", "arm_r": "out", "arm_l": "out"}),
            (0.12, {"legs": "crouch", "body": (0, 1), "sq": 1}),
            (0.45, {}),
        ],
        tween=True,
    )
    note = lambda n, dx, dy: [(n, "hat", dx, dy)]  # noqa: E731
    a["dance"] = Anim(
        [
            (
                0.18,
                {
                    "arm_r": "up",
                    "arm_l": "down",
                    "body": (1, 0),
                    "legs": "walk_a",
                    "eyes": "happy",
                    "fx": note("note", 7, -2),
                    **tail,
                },
            ),
            (
                0.18,
                {"arm_r": "out", "arm_l": "out", "root": (0, -1), "eyes": "happy", "fx": note("note", 8, -4)},
            ),
            (
                0.18,
                {
                    "arm_l": "up",
                    "arm_r": "down",
                    "body": (-1, 0),
                    "legs": "walk_b",
                    "eyes": "happy",
                    "fx": note("note2", -7, -3),
                },
            ),
            (0.18, {"arm_r": "wave", "arm_l": "wave", "root": (0, -1), "fx": note("note2", -8, -5)}),
            (0.18, {"arm_r": "up", "arm_l": "up", "legs": "crouch", "body": (0, 1), "eyes": "happy", **tail}),
            (
                0.18,
                {"arm_r": "up", "arm_l": "up", "root": (0, -2), "eyes": "happy", "fx": note("note", 6, -3)},
            ),
            (
                0.18,
                {"arm_r": "out", "arm_l": "up", "body": (1, 0), "legs": "walk_b", "fx": note("note", 7, -5)},
            ),
            (0.18, {"arm_r": "up", "arm_l": "out", "body": (-1, 0), "legs": "walk_a", "eyes": "happy"}),
        ],
        beat=2,
    )
    zz = lambda s: [("z", "hat", 6, -1 - s), ("Z", "hat", 9, -5 - s)] if s else [("z", "hat", 6, -1)]  # noqa: E731
    sl = {**seat, "head": (0, 1), "eyes": "closed", "arm_r": "down", "arm_l": "down", "mouth": "-"}
    a["sleep"] = Anim(
        [
            (0.8, {**sl, "fx": zz(0)}),
            (0.8, {**sl, "body": (0, drop + 1), "fx": zz(1)}),
            (0.8, {**sl, "fx": zz(2)}),
            (0.8, {**sl, "body": (0, drop + 1), "fx": [("Z", "hat", 10, -8)]}),
        ]
    )
    a["sit"] = _idle(seat)
    a["eat"] = Anim(
        [
            (0.35, {**seat, "arm_r": "hold", "fx": [(food, "hand_r", 0, -1)]}),
            (0.25, {**seat, "arm_r": "mouth", "mouth": "open", "fx": [(food, "hand_r", 0, 0)]}),
            (
                0.2,
                {**seat, "arm_r": "mouth", "head": (0, 1), "eyes": "happy", "fx": [(food, "hand_r", 0, 0)]},
            ),
            (0.2, {**seat, "arm_r": "hold", "fx": [(food, "hand_r", 0, -1), ("dust", "mouth", 2, 2)]}),
            (
                0.2,
                {**seat, "arm_r": "hold", "head": (0, 1), "eyes": "happy", "fx": [(food, "hand_r", 0, -1)]},
            ),
            (0.3, {**seat, "arm_r": "hold", "fx": [(food, "hand_r", 0, -1)]}),
        ]
    )
    hy = [("heart_s", "hat", 7, -2)]
    a["happy"] = Anim(
        [
            (
                0.12,
                {
                    "eyes": "happy",
                    "arm_r": "up",
                    "arm_l": "up",
                    "mouth": "open",
                    "legs": "crouch",
                    "body": (0, 1),
                },
            ),
            (
                0.16,
                {
                    "eyes": "happy",
                    "arm_r": "up",
                    "arm_l": "up",
                    "mouth": "open",
                    "root": (0, -3),
                    "legs": "tuck",
                    "fx": hy,
                    **tail,
                },
            ),
            (
                0.12,
                {
                    "eyes": "happy",
                    "arm_r": "wave",
                    "arm_l": "wave",
                    "mouth": "open",
                    "root": (0, -1),
                    "fx": [("heart", "hat", 8, -5)],
                },
            ),
            (
                0.3,
                {
                    "eyes": "happy",
                    "arm_r": "out",
                    "arm_l": "out",
                    "mouth": "open",
                    "fx": [("heart", "hat", 9, -7)],
                },
            ),
        ],
        tween=True,
    )
    sad = {"head": (0, 1), "eyes": "sad", "arm_r": (0, 1, "down"), "arm_l": (0, 1, "down"), "tail": "down"}
    a["sad"] = Anim(
        [
            (0.6, {**sad, "fx": [("tear", "eye", 0, 1)]}),
            (0.6, {**sad, "fx": [("tear", "eye", 0, 3)]}),
            (0.6, {**sad, "body": (0, 1), "fx": [("tear", "eye", 0, 5)]}),
            (
                0.8,
                {
                    **sad,
                    "body": (0, 1),
                    "eyes": "closed",
                    "fx": [("cloud", "hat", 0, -6), ("rain", "hat", 0, -3)],
                },
            ),
            (0.6, {**sad, "fx": [("cloud", "hat", 0, -6), ("rain", "hat", 0, -2)]}),
        ],
        tween=True,
    )
    a["wave"] = Anim(
        [
            (0.2, {"arm_r": "up", "eyes": "happy", "mouth": "open"}),
            (0.2, {"arm_r": "wave", "eyes": "happy", "mouth": "open"}),
            (0.2, {"arm_r": "up", "eyes": "open", "mouth": "open"}),
            (
                0.2,
                {"arm_r": "wave", "eyes": "happy", "mouth": "open", "fx": [("sparkle_s", "hand_r", 2, -1)]},
            ),
        ]
    )
    ball = lambda dx, dy: [("ball", "feet", dx, dy)]  # noqa: E731
    a["kick"] = Anim(
        [
            (0.35, {"fx": ball(2, -2)}),
            (
                0.22,
                {"legs": "kick_back", "body": (-1, 0), "arm_l": "out", "arm_r": "back", "fx": ball(2, -2)},
            ),
            (0.08, {"legs": "kick_fwd", "arm_r": "out", "arm_l": "back", "fx": ball(4, -2)}),
            (0.14, {"legs": "kick_fwd", "arm_r": "out", "arm_l": "back", "fx": ball(9, -6)}),
            (0.3, {"legs": "stand", "eyes": "happy", "fx": ball(18, -10)}),
            (0.3, {"eyes": "happy", "arm_r": "up", "fx": ball(40, -10)}),
            (0.35, {"fx": ball(-16, -2)}),
        ],
        tween=True,
    )
    laptop = ("laptop", "lap", 0, 0)
    wk = {**seat, "arm_r": "out", "arm_l": "out"}
    a["work"] = Anim(
        [
            (0.14, {**wk, "arm_r": (0, -1, "out"), "fx": [laptop]}),
            (0.14, {**wk, "arm_l": (0, -1, "out"), "fx": [laptop, ("code", "lap", 0, -4)]}),
            (0.14, {**wk, "arm_r": (0, -1, "out"), "fx": [laptop, ("code", "lap", 1, -6)]}),
            (0.14, {**wk, "arm_l": (0, -1, "out"), "fx": [laptop]}),
            (0.4, {**wk, "head": (1, 0), "fx": [laptop]}),
            (0.14, {**wk, "arm_r": (0, -1, "out"), "fx": [laptop, ("code", "lap", -1, -5)]}),
            (0.14, {**wk, "arm_l": (0, -1, "out"), "fx": [laptop]}),
            (0.12, {**wk, "eyes": "closed", "fx": [laptop]}),
        ]
    )
    ex = o.get("extras", ())
    if "think" in ex:
        a["think"] = Anim(
            [
                (0.35, {"arm_r": "chin", "eyes": "up", "fx": [("dot", "hat", 5, -1)]}),
                (
                    0.35,
                    {"arm_r": "chin", "eyes": "up", "fx": [("dot", "hat", 5, -1), ("dot2", "hat", 7, -3)]},
                ),
                (
                    0.5,
                    {
                        "arm_r": "chin",
                        "eyes": "up",
                        "head": (1, 0),
                        "fx": [("dot", "hat", 5, -1), ("dot2", "hat", 7, -3), ("bubble", "hat", 8, -7)],
                    },
                ),
                (
                    0.5,
                    {
                        "arm_r": "chin",
                        "eyes": "up",
                        "head": (1, 0),
                        "fx": [("dot2", "hat", 7, -3), ("bubble", "hat", 8, -7)],
                    },
                ),
                (0.12, {"arm_r": "chin", "eyes": "closed"}),
                (0.4, {"arm_r": "chin", "eyes": "open", "fx": [("q", "hat", 7, -4)]}),
            ]
        )
    style = o.get("attack", "melee")
    fxn = o.get("attack_fx", "slash")
    if "attack" in ex:
        if style == "bow":
            a["attack"] = Anim(
                [
                    (0.3, {"arm_r": "aim", "arm_l": "hold", "body": (-1, 0)}),
                    (0.08, {"arm_r": "aim", "arm_l": "hold", "fx": [("arrow", "hand_r", 4, 0)]}),
                    (0.16, {"arm_r": "aim", "fx": [("arrow", "hand_r", 12, 0)]}),
                    (0.2, {"arm_r": "aim", "fx": [("arrow", "hand_r", 24, 0)]}),
                    (0.3, {}),
                ],
                tween=True,
            )
        elif style in ("breath", "magic"):
            src = "mouth" if style == "breath" else "hand_r"
            arm = {} if style == "breath" else {"arm_r": "fwd"}
            a["attack"] = Anim(
                [
                    (
                        0.25,
                        {
                            "body": (-1, 0),
                            "head": (-1, 0),
                            "eyes": "closed",
                            "arm_r": "back",
                            "arm_l": "back",
                        },
                    ),
                    (0.08, {**arm, "mouth": "open", "root": (1, 0), "fx": [(fxn, src, 3, 0)]}),
                    (
                        0.15,
                        {**arm, "mouth": "open", "root": (1, 0), "eyes": "wide", "fx": [(fxn, src, 8, 0)]},
                    ),
                    (0.15, {**arm, "mouth": "open", "root": (1, 0), "fx": [(fxn, src, 14, -1)]}),
                    (0.15, {**arm, "fx": [(fxn, src, 22, -1)]}),
                    (0.35, {}),
                ],
                tween=True,
            )
        else:  # melee / punch
            a["attack"] = Anim(
                [
                    (0.24, {"arm_r": "up", "body": (-1, 0), "head": (-1, 0), "legs": "kick_back"}),
                    (
                        0.07,
                        {"arm_r": "fwd", "root": (1, 0), "legs": "walk_a", "fx": [(fxn, "hand_r", 2, -2)]},
                    ),
                    (
                        0.14,
                        {
                            "arm_r": "out",
                            "root": (2, 0),
                            "legs": "walk_a",
                            "fx": [("slash2" if fxn == "slash" else fxn, "hand_r", 3, 0)],
                        },
                    ),
                    (0.2, {"arm_r": "out", "root": (1, 0)}),
                    (0.35, {}),
                ]
            )
    if "cast" in ex:
        sp = lambda *p: [("sparkle", "hand_r", dx, dy) for dx, dy in p]  # noqa: E731
        a["cast"] = Anim(
            [
                (0.18, {"arm_r": "up", "eyes": "closed", "fx": sp((0, -3))}),
                (0.18, {"arm_r": "up", "eyes": "closed", "arm_l": "out", "fx": sp((3, -1), (-3, -2))}),
                (
                    0.18,
                    {"arm_r": "up", "eyes": "closed", "arm_l": "out", "fx": sp((-2, 1), (2, -4), (0, -5))},
                ),
                (0.18, {"arm_r": "wave", "eyes": "wide", "fx": [("orb", "hand_r", 0, -2), *sp((4, 2))]}),
                (0.1, {"arm_r": "fwd", "root": (1, 0), "fx": [("orb", "hand_r", 4, 0)]}),
                (0.12, {"arm_r": "fwd", "fx": [("orb", "hand_r", 10, 0)]}),
                (0.12, {"arm_r": "fwd", "fx": [("orb", "hand_r", 16, 0), ("sparkle_s", "hand_r", 8, -2)]}),
                (0.3, {}),
            ]
        )
    if "shoot" in ex:
        aim = {"arm_r": "aim", "arm_l": "hold"}
        gl = o.get("gun_len", 1)
        a["shoot"] = Anim(
            [
                (0.3, {**aim}),
                (0.06, {**aim, "fx": [("flash", "hand_r", gl, 0)]}),
                (
                    0.08,
                    {
                        **aim,
                        "body": (-1, 0),
                        "head": (-1, 0),
                        "fx": [("bullet", "hand_r", gl + 5, 0), ("shell", "hand_r", -1, -2)],
                    },
                ),
                (0.1, {**aim, "fx": [("bullet", "hand_r", gl + 12, 0), ("shell", "hand_r", -2, 0)]}),
                (0.06, {**aim, "fx": [("flash", "hand_r", gl, 0), ("shell", "hand_r", -2, 3)]}),
                (0.08, {**aim, "body": (-1, 0), "head": (-1, 0), "fx": [("bullet", "hand_r", gl + 5, 0)]}),
                (0.1, {**aim, "fx": [("bullet", "hand_r", gl + 12, 0), ("shell", "hand_r", -1, -1)]}),
                (0.4, {**aim}),
            ]
        )
    if "reload" in ex:
        rl = {"arm_r": "hold", "head": (0, 1), "eyes": "sad"}
        a["reload"] = Anim(
            [
                (0.25, {**rl, "arm_l": "down", "fx": [("mag", "hand_r", 0, 3)]}),
                (0.25, {**rl, "arm_l": "down", "fx": [("mag", "hand_r", -1, 9)]}),
                (0.3, {**rl, "arm_l": "out", "fx": [("mag", "hand_l", 0, 0)]}),
                (0.2, {**rl, "arm_l": "hold", "fx": [("mag", "hand_r", 0, 2)]}),
                (0.12, {**rl, "arm_l": "hold", "body": (0, 1)}),
                (
                    0.4,
                    {"arm_r": "aim", "arm_l": "hold", "eyes": "open", "fx": [("sparkle_s", "hand_r", 3, -2)]},
                ),
            ]
        )
    if "crouch" in ex:
        cr = {"legs": "crouch", "body": (0, 2), "arm_r": "aim", "arm_l": "hold"}
        a["crouch"] = Anim(
            [
                (0.6, cr),
                (0.5, {**cr, "head": (1, 0)}),
                (0.12, {**cr, "eyes": "closed"}),
                (0.6, {**cr, "head": (-1, 0)}),
                (0.5, {**cr, "body": (0, 1)}),
            ]
        )
    return a


# --------------------------------------------------------------------------- quadruped
def quad_anims(o: dict[str, Any]) -> dict[str, Anim]:
    food = o.get("food", "bowl")
    a: dict[str, Anim] = {}
    wag = lambda k: {"tail": "a" if k % 2 == 0 else "b"}  # noqa: E731
    sit = {
        "rump": (0, 2),
        "leg_bn": (0, 1, "tuck"),
        "leg_bf": (0, 1, "tuck"),
        "tail": (0, 2, "down"),
        "head": (0, -1),
        "body": (0, 0),
    }
    a["idle"] = Anim(
        [
            (0.6, {**wag(0)}),
            (0.6, {"body": (0, 1), **wag(1)}),
            (0.6, {**wag(0)}),
            (0.12, {"eyes": "closed", **wag(1)}),
            (0.6, {"body": (0, 1), **wag(0)}),
            (0.6, {"head": (1, 0), **wag(1)}),
            (0.6, {"head": (1, 1), "body": (0, 1), **wag(0)}),
            (0.5, {**wag(1)}),
        ],
        beat=1,
    )
    a["walk"] = Anim(
        [
            (0.14, {"leg_fn": "fwd", "leg_bf": "fwd", "leg_ff": "back", "leg_bn": "back", **wag(0)}),
            (0.14, {"leg_fn": "lift", "leg_bf": "lift", "head": (0, 1)}),
            (0.14, {"leg_fn": "back", "leg_bf": "back", "leg_ff": "fwd", "leg_bn": "fwd", **wag(1)}),
            (0.14, {"leg_ff": "lift", "leg_bn": "lift", "head": (0, 1)}),
        ]
    )
    a["run"] = Anim(
        [
            (
                0.09,
                {
                    "leg_fn": "fwd",
                    "leg_ff": "fwd",
                    "leg_bn": "back",
                    "leg_bf": "back",
                    "root": (0, -2),
                    "tail": "b",
                    "head": (1, 0),
                },
            ),
            (
                0.09,
                {
                    "leg_fn": "back",
                    "leg_ff": "lift",
                    "leg_bn": "fwd",
                    "leg_bf": "lift",
                    "root": (0, -1),
                    "body": (0, 1),
                    "head": (0, 1),
                },
            ),
            (0.09, {"leg_fn": "back", "leg_ff": "back", "leg_bn": "fwd", "leg_bf": "fwd", "tail": "a"}),
        ]
    )
    a["jump"] = Anim(
        [
            (0.16, {"body": (0, 1), "head": (0, 1), "sq": 1}),
            (
                0.1,
                {
                    "root": (0, -3),
                    "leg_fn": "fwd",
                    "leg_ff": "fwd",
                    "leg_bn": "back",
                    "leg_bf": "back",
                    "head": (0, -1),
                    "sq": -1,
                },
            ),
            (
                0.2,
                {
                    "root": (0, -6),
                    "leg_fn": "tuck",
                    "leg_ff": "tuck",
                    "leg_bn": "tuck",
                    "leg_bf": "tuck",
                    "eyes": "happy",
                    "tail": "b",
                },
            ),
            (0.12, {"root": (0, -3), "leg_fn": "fwd", "leg_ff": "fwd", "leg_bn": "back", "leg_bf": "back"}),
            (0.12, {"body": (0, 1), "head": (0, 1), "sq": 1}),
            (0.45, {}),
        ],
        tween=True,
    )
    note = lambda n, dx, dy: [(n, "hat", dx, dy)]  # noqa: E731
    a["dance"] = Anim(
        [
            (0.18, {**sit, "leg_fn": (0, -2, "lift"), "eyes": "happy", "fx": note("note", 5, -2), **wag(0)}),
            (0.18, {**sit, "head": (1, -2), "root": (0, -1), "fx": note("note", 6, -4), **wag(1)}),
            (
                0.18,
                {
                    **sit,
                    "leg_ff": (0, -2, "lift"),
                    "eyes": "happy",
                    "head": (-1, -1),
                    "fx": note("note2", -4, -3),
                    **wag(0),
                },
            ),
            (0.18, {**sit, "head": (0, -2), "root": (0, -1), "fx": note("note2", -5, -5), **wag(1)}),
            (0.18, {"root": (0, -2), "eyes": "happy", "leg_fn": "fwd", "leg_bn": "back", **wag(0)}),
            (0.18, {"body": (0, 1), "head": (1, 1), "eyes": "happy", "fx": note("note", 6, -3), **wag(1)}),
        ],
        beat=2,
    )
    lie = {
        "body": (0, 2),
        "rump": (0, 0),
        "head": (0, 1),
        "tail": (0, 0, "down"),
        "eyes": "closed",
        "leg_fn": (1, 2, "tuck"),
        "leg_ff": "-",
        "leg_bn": (0, 2, "tuck"),
        "leg_bf": "-",
        "mouth": "-",
    }
    a["sleep"] = Anim(
        [
            (0.8, {**lie, "fx": [("z", "hat", 4, -1)]}),
            (0.8, {**lie, "head": (0, 2), "fx": [("z", "hat", 5, -2), ("Z", "hat", 8, -5)]}),
            (0.8, {**lie, "fx": [("z", "hat", 5, -3), ("Z", "hat", 8, -6)]}),
            (0.8, {**lie, "head": (0, 2), "fx": [("Z", "hat", 9, -8)]}),
        ]
    )
    a["sit"] = Anim(
        [
            (0.8, sit),
            (0.12, {**sit, "eyes": "closed"}),
            (0.7, {**sit, "head": (1, -1)}),
            (0.7, {**sit, "tail": (1, 2, "down")}),
            (0.6, {**sit, "head": (0, -2)}),
        ],
        beat=1,
    )
    bowl = ("bowl", "bowl", 0, 0) if food == "bowl" else (food, "bowl", 0, 1)
    down = {"head": (1, 3), "body": (0, 1)}
    a["eat"] = Anim(
        [
            (0.3, {**down, "fx": [bowl], **wag(0)}),
            (0.15, {**down, "head": (1, 2), "mouth": "open", "fx": [bowl], **wag(1)}),
            (0.15, {**down, "fx": [bowl], **wag(0)}),
            (
                0.15,
                {**down, "head": (1, 2), "mouth": "open", "fx": [bowl, ("dust", "bowl", 3, -3)], **wag(1)},
            ),
            (0.3, {**down, "fx": [bowl], **wag(0)}),
            (0.5, {"head": (0, -1), "eyes": "happy", "fx": [bowl], **wag(1)}),
        ]
    )
    a["happy"] = Anim(
        [
            (0.12, {"body": (0, 1), "eyes": "happy", "mouth": "open", **wag(0)}),
            (
                0.16,
                {
                    "root": (0, -3),
                    "leg_fn": "fwd",
                    "leg_ff": "fwd",
                    "leg_bn": "back",
                    "leg_bf": "back",
                    "eyes": "happy",
                    "mouth": "open",
                    "fx": [("heart_s", "hat", 5, -2)],
                    **wag(1),
                },
            ),
            (
                0.12,
                {
                    "root": (0, -1),
                    "eyes": "happy",
                    "mouth": "open",
                    "fx": [("heart", "hat", 6, -5)],
                    **wag(0),
                },
            ),
            (0.3, {"eyes": "happy", "mouth": "open", "fx": [("heart", "hat", 7, -7)], **wag(1)}),
        ],
        tween=True,
    )
    sd = {"head": (0, 2), "eyes": "sad", "tail": (0, 1, "down"), "body": (0, 1)}
    a["sad"] = Anim(
        [
            (0.6, {**sd, "fx": [("tear", "eye", 0, 1)]}),
            (0.6, {**sd, "fx": [("tear", "eye", 0, 3)]}),
            (0.6, {**sd, "head": (0, 3), "fx": [("tear", "eye", 0, 5)]}),
            (0.8, {**sd, "eyes": "closed", "fx": [("cloud", "hat", 0, -5), ("rain", "hat", 0, -2)]}),
        ],
        tween=True,
    )
    a["wave"] = Anim(
        [
            (0.2, {**sit, "leg_fn": (1, -3, "lift"), "eyes": "happy", "mouth": "open", **wag(0)}),
            (0.2, {**sit, "leg_fn": (2, -4, "lift"), "eyes": "happy", "mouth": "open", **wag(1)}),
            (0.2, {**sit, "leg_fn": (1, -3, "lift"), "mouth": "open", **wag(0)}),
            (0.2, {**sit, "leg_fn": (2, -4, "lift"), "eyes": "happy", "mouth": "open", **wag(1)}),
        ]
    )
    ball = lambda dx, dy: [("ball", "feet", dx, dy)]  # noqa: E731
    a["kick"] = Anim(
        [
            (0.35, {"fx": ball(2, -2)}),
            (0.22, {"leg_fn": "back", "body": (-1, 0), "head": (-1, 1), "fx": ball(2, -2)}),
            (0.08, {"leg_fn": "kick", "fx": ball(4, -2)}),
            (0.14, {"leg_fn": "kick", "fx": ball(9, -6)}),
            (0.3, {"eyes": "happy", "fx": ball(18, -10), **wag(0)}),
            (0.3, {"eyes": "happy", "fx": ball(40, -10), **wag(1)}),
            (0.35, {"fx": ball(-16, -2)}),
        ],
        tween=True,
    )
    lap = ("laptop", "lap", 0, 0)
    a["work"] = Anim(
        [
            (0.14, {**sit, "leg_fn": (1, -1, "lift"), "fx": [lap]}),
            (0.14, {**sit, "leg_ff": (1, -1, "lift"), "fx": [lap, ("code", "lap", 0, -4)]}),
            (0.14, {**sit, "leg_fn": (1, -1, "lift"), "fx": [lap, ("code", "lap", 1, -6)]}),
            (0.14, {**sit, "leg_ff": (1, -1, "lift"), "fx": [lap]}),
            (0.4, {**sit, "head": (1, -1), "fx": [lap]}),
            (0.12, {**sit, "eyes": "closed", "fx": [lap]}),
        ]
    )
    return a


def compile_all(anims: dict[str, Anim]) -> dict[str, Anim]:
    for an in anims.values():
        an.compile()
    return anims
