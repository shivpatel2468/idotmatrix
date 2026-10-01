"""Sports: a footballer and a goalkeeper whose kit colours are recolourable slots."""

from __future__ import annotations

from .build import biped
from .rig import v

_KIT_LEGS = {  # socks up to the knee, boots at the bottom
    "stand": v(".ss..ss.", ".pp..pp.", ".fff.fff"),
    "walk_a": v(".ss..ss.", ".pp...fff", ".fff....."),
    "walk_b": v(".ss..ss.", ".fff.pp..", ".....fff."),
    "run_a": v("..ssss...", ".pp...pp.", "ff.....fff", ox=-1),
    "run_b": v("..ssss..", "..pppp..", "..ff.fff"),
    "crouch": v("pppppppp", "fff..fff", oy=1),
    "sit": v(".ssssss.", ".ppppppff", oy=1),
    "tuck": v(".ss..ss.", ".fff.fff"),
    "kick_back": v(".ss.ss..", ".pppp...", ".ffff..."),
    "kick_fwd": v(".ss..sss", ".pp....pff", ".fff......"),
}

_HEAD = (
    "..hhhhhh..",
    ".hhhhhhhh.",
    "hhhhhhhhhh",
    "hhhsssssss",
    "hhssssssss",
    "hsssssssss",
    ".sssskkss.",
    "..ssssss..",
)

biped(
    "footballer",
    "Footballer",
    "sports",
    "A footballer in full kit. Shirt, shorts, socks, skin and hair are all recolourable: pick your club.",
    slots={
        "shirt": (255, 30, 40),
        "shorts": (250, 250, 255),
        "socks": (255, 30, 40),
        "skin": (255, 190, 140),
        "hair": (90, 50, 20),
    },
    key={
        "h": "hair",
        "s": "skin",
        "S": "skin*0.8",
        "k": "skin*0.55",
        "r": "shirt",
        "R": "shirt*0.7",
        "W": "#ffffff",
        "w": "shorts",
        "c": "shirt",
        "n": "skin",
        "p": "socks",
        "f": "#50505f",
    },
    head=_HEAD,
    torso=("RrrrrrrR", "RrrWWrrR", "RrrWWrrR", "RrrrrrrR", "wwwwwwww"),
    eyes={"pts": [(7, 4), (10, 4)], "w": 1, "h": 2},
    legs=_KIT_LEGS,
    opts={"food": "apple"},
)

biped(
    "goalkeeper",
    "Goalkeeper",
    "sports",
    "A goalkeeper in a bright jersey with oversized gloves, ready to dive.",
    slots={
        "shirt": (140, 255, 0),
        "gloves": (0, 210, 255),
        "shorts": (40, 40, 60),
        "skin": (240, 170, 120),
        "hair": (40, 30, 30),
    },
    key={
        "h": "hair",
        "s": "skin",
        "S": "skin*0.8",
        "k": "skin*0.55",
        "r": "shirt",
        "R": "shirt*0.65",
        "w": "shorts",
        "c": "shirt",
        "n": "gloves",
        "p": "shirt*0.8",
        "f": "#50505f",
    },
    head=_HEAD,
    torso=("RrrrrrrR", "RrRrrRrR", "RrrrrrrR", "RrRrrRrR", "wwwwwwww"),
    eyes={"pts": [(7, 4), (10, 4)], "w": 1, "h": 2},
    legs=_KIT_LEGS,
    arms={"arm_r": {"down": v("Cc", "Cc", "nn", "nn", hand=(0, 3))}},
    opts={"food": "apple"},
)
