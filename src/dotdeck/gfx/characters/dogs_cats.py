"""Dogs and cats: chibi quadrupeds (big friendly face on a side-on body, facing right)."""

from __future__ import annotations

from typing import Any

from .build import quad

# Template (authored with the nose at x=15, drawn 1 px further left): head 8x7 at (8, 3) · chest x7..11 /
# rump x2..6 rows 9..12 · legs rows 13..15 · tail rising from the rump.
_EYES = {"pts": [(10, 6), (13, 6)], "w": 1, "h": 2}


def pet(
    id: str,
    name: str,
    group: str,
    desc: str,
    *,
    slots: dict[str, tuple[int, int, int]],
    key: dict[str, str],
    head: tuple[str, ...],
    tail: dict[str, Any],
    chest: tuple[str, ...] = ("ooooo", "ooooo", "oooob", ".obbb"),
    rump: tuple[str, ...] = (".oooo", "ooooo", "ooooo", ".oooo"),
    head_xy: tuple[int, int] = (8, 3),
    body_y: int = 9,
    rump_x: int = 2,
    tail_xy: tuple[int, int] = (0, 3),
    leg_h: int = 3,
    legs_x: tuple[int, int] = (9, 3),
    eyes: dict[str, Any] | None = None,
    food: str = "bowl",
) -> None:
    food = "bowl"  # a full bowl reads better than a loose snack at 16 px
    k = {"l": "coat", "L": "coat*0.55", "q": "coat", "Q": "coat*0.55", "e": "eyes", **key}
    # authored on a 16 px grid with the nose at x=15; shift left 1 px so head motion never clips
    ey = eyes or _EYES
    ey = {**ey, "pts": [(x - 1, y) for x, y in ey["pts"]]}
    head_xy = (head_xy[0] - 1, head_xy[1])
    rump_x -= 1
    legs_x = (legs_x[0] - 1, legs_x[1] - 1)
    quad(
        id,
        name,
        group,
        desc,
        slots=slots,
        key=k,
        head=head,
        head_xy=head_xy,
        body=chest,
        body_xy=(6, body_y),
        rump=rump,
        rump_xy=(rump_x, body_y),
        tail=tail,
        tail_xy=tail_xy,
        legs_xy=(legs_x[0], legs_x[1], 16 - leg_h),
        leg_h=leg_h,
        eyes=ey,
        mouth=None,
        opts={"food": food},
        anchors={"bowl": ("root", 12, 14), "feet": ("root", 12, 14)},
        squash_row=body_y,
    )


_CURL = {
    "a": (".oo.", "o..o", "o.o.", ".o.."),
    "b": ("..oo.", ".o..o", ".o.o.", "..o.."),
    "down": ("....", "....", "o...", ".oo."),
}
_BUSHY = {
    "a": (".oo", "ooo", "oo.", "o..", "o.."),
    "b": ("oo.", "ooo", ".oo", "..o", "..o"),
    "down": ("...", "...", "o..", "oo.", ".oo"),
}
_CAT_TAIL = {
    "a": (".o", "o.", "o.", "o.", ".o", ".o"),
    "b": ("o.", ".o", ".o", ".o", "o.", ".o"),
    "down": ("..", "..", "..", "o.", "o.", ".o"),
}

# ----------------------------------------------------------------------------------------------- dogs
pet(
    "shiba",
    "Shiba",
    "dogs",
    "A foxy little shiba: russet coat, cream cheeks and a curly tail.",
    slots={"coat": (255, 118, 26), "cream": (255, 226, 180), "eyes": (16, 10, 8)},
    key={
        "o": "coat",
        "c": "cream",
        "b": "cream",
        "q": "cream",
        "Q": "cream*0.6",
        "i": "#ff7c8c",
        "n": "#1e1410",
    },
    head=(
        ".o....o.",
        "ooi..ioo",
        "oooooooo",
        "oooooooo",
        "cooooooc",
        "cccnnccc",
        ".cccccc.",
    ),
    tail=_CURL,
    tail_xy=(0, 5),
    chest=("ooooo", "ooocc", "ooocc", ".occc"),
)

pet(
    "pug",
    "Pug",
    "dogs",
    "A snorty fawn pug with a dark squashed face and a curly tail.",
    slots={"coat": (255, 196, 120), "mask": (70, 44, 36), "eyes": (12, 8, 8)},
    key={"o": "coat", "d": "mask", "b": "coat^0.25", "n": "#140a0a", "i": "#ff7c8c"},
    head=(
        "........",
        ".dd..dd.",
        "dooooood",
        "oooooooo",
        "oooooooo",
        "ooddddoo",
        ".odnndo.",
    ),
    eyes={"pts": [(9, 6), (13, 6)], "w": 2, "h": 2, "shine": True},
    tail=_CURL,
    tail_xy=(0, 5),
    chest=("ooooo", "ooooo", "oooob", "oobbb"),
    rump=("ooooo", "ooooo", "ooooo", ".oooo"),
)

pet(
    "husky",
    "Husky",
    "dogs",
    "A fluffy grey-and-white husky with ice-blue eyes.",
    slots={"coat": (140, 150, 180), "white": (245, 245, 255), "eyes": (60, 200, 255)},
    key={
        "o": "coat",
        "c": "white",
        "b": "white",
        "q": "white",
        "Q": "white*0.6",
        "i": "#ff8c9c",
        "n": "#141418",
    },
    head=(
        ".o....o.",
        "ooi..ioo",
        "oooccooo",
        "occcccco",
        "cccccccc",
        "cccnnccc",
        ".cccccc.",
    ),
    tail={
        "a": ("occ", "ooo", "oo.", "o.."),
        "b": ("cco", "ooo", ".oo", "..o"),
        "down": ("...", "o..", "oo.", ".oc"),
    },
    tail_xy=(0, 5),
    chest=("ooooo", "ooocc", "ooccc", ".occc"),
)

pet(
    "dachshund",
    "Dachshund",
    "dogs",
    "A long, low sausage dog with floppy ears and tiny legs.",
    slots={"coat": (205, 84, 26), "ears": (120, 44, 14), "eyes": (14, 8, 6)},
    key={"o": "coat", "d": "ears", "c": "coat^0.3", "b": "coat^0.2", "n": "#140a08"},
    head=(
        ".oooooo.",
        "oooooooo",
        "dooooood",
        "dooooood",
        "ddccccdd",
        "dccnnccd",
        "..cccc..",
    ),
    head_xy=(8, 4),
    eyes={"pts": [(10, 6), (13, 6)], "w": 1, "h": 2},
    chest=("ooooo", "ooooo", "oooob", ".bbb."),
    rump=(".ooooo", "oooooo", "oooooo", ".ooooo"),
    rump_x=1,
    body_y=10,
    leg_h=2,
    legs_x=(9, 2),
    tail={
        "a": ("..", "..", "..", "..", ".o", "o."),
        "b": ("..", "..", "..", "o.", ".o", ".."),
        "down": ("..", "..", "..", "..", "..", "oo"),
    },
    tail_xy=(0, 5),
)

pet(
    "golden",
    "Golden Retriever",
    "dogs",
    "A sunny golden retriever: floppy ears, feathery tail, endless joy.",
    slots={"coat": (255, 176, 50), "ears": (205, 110, 20), "eyes": (20, 10, 6)},
    key={"o": "coat", "d": "ears", "c": "coat^0.35", "b": "coat^0.3", "n": "#1e0f08"},
    head=(
        ".oooooo.",
        "oooooooo",
        "dooooood",
        "dooooood",
        "ddoooodd",
        "dccnnccd",
        ".cccccc.",
    ),
    tail={
        "a": ("..o", ".oo", "oo.", "o.."),
        "b": ("o..", "oo.", ".oo", "..o"),
        "down": ("...", "o..", "oo.", ".oo"),
    },
    tail_xy=(0, 6),
    chest=("ooooo", "ooooo", "oooob", "obbbb"),
)

pet(
    "corgi",
    "Corgi",
    "dogs",
    "A loaf-shaped corgi: huge ears, tiny legs, fluffy bottom.",
    slots={"coat": (255, 128, 36), "white": (255, 245, 235), "eyes": (16, 10, 8)},
    key={
        "o": "coat",
        "c": "white",
        "b": "white",
        "q": "white",
        "Q": "white*0.6",
        "i": "#ff7c8c",
        "n": "#140a08",
    },
    head=(
        "o......o",
        "oi....io",
        "oooccooo",
        "oooccooo",
        "occcccco",
        "cccnnccc",
        ".cccccc.",
    ),
    head_xy=(8, 4),
    body_y=10,
    leg_h=2,
    chest=("ooooo", "ooocc", "ooccc", ".occc"),
    rump=(".oooo", "ooooo", "ooooc", ".oocc"),
    tail={
        "a": ("..", "..", "..", "..", ".c", "cc"),
        "b": ("..", "..", "..", "..", "c.", "cc"),
        "down": ("..", "..", "..", "..", "..", "cc"),
    },
    tail_xy=(1, 4),
)

# ----------------------------------------------------------------------------------------------- cats
_CAT = (
    "o......o",
    "oi....io",
    "oooooooo",
    "oooooooo",
    "oooooooo",
    "woonnoow",
    ".oooooo.",
)

pet(
    "tabby",
    "Orange Tabby",
    "cats",
    "A chunky orange tabby with stripes and a swishy tail.",
    slots={"coat": (255, 140, 30), "stripes": (190, 70, 10), "eyes": (20, 12, 6)},
    key={"o": "coat", "d": "stripes", "b": "coat^0.4", "i": "#ff8c9c", "n": "#ff6e8c", "w": "#ffe6c8"},
    head=(
        "o......o",
        "oi....io",
        "oodoodoo",
        "oooooooo",
        "oooooooo",
        "woonnoow",
        ".oooooo.",
    ),
    chest=("ooooo", "odooo", "ooobb", ".obbb"),
    rump=(".odod", "odooo", "ooodo", ".oooo"),
    tail={
        "a": (".d", "o.", "d.", "o.", ".d", ".o"),
        "b": ("d.", ".o", ".d", ".o", "d.", ".o"),
        "down": _CAT_TAIL["down"],
    },
    food="fish",
)

pet(
    "black_cat",
    "Black Cat",
    "cats",
    "A sleek midnight cat with glowing yellow eyes.",
    slots={"coat": (56, 48, 88), "eyes": (255, 214, 0), "nose": (255, 110, 150)},
    key={"o": "coat", "b": "coat^0.1", "i": "nose*0.7", "n": "nose", "w": "coat^0.3"},
    head=_CAT,
    tail=_CAT_TAIL,
    food="fish",
)

pet(
    "calico",
    "Calico",
    "cats",
    "A patchwork calico: white with orange and dark patches.",
    slots={"coat": (245, 240, 235), "patch": (255, 130, 30), "patch2": (70, 56, 56), "eyes": (20, 12, 6)},
    key={
        "o": "coat",
        "a": "patch",
        "d": "patch2",
        "b": "coat",
        "i": "#ff8c9c",
        "n": "#ff6e8c",
        "w": "coat",
        "L": "coat*0.6",
        "Q": "coat*0.6",
    },
    head=(
        "a......d",
        "ai....id",
        "aaaooodd",
        "aaoooodd",
        "oooooooo",
        "woonnoow",
        ".oooooo.",
    ),
    chest=("ooooo", "ooooo", "ooooo", ".oooo"),
    rump=(".dddo", "ddaao", "ooaao", ".oooo"),
    tail={
        "a": (".d", "a.", "a.", "o.", ".o", ".o"),
        "b": ("d.", ".a", ".a", ".o", "o.", ".o"),
        "down": _CAT_TAIL["down"],
    },
    food="fish",
)

pet(
    "siamese",
    "Siamese",
    "cats",
    "An elegant cream siamese with dark points and sapphire eyes.",
    slots={"coat": (255, 232, 196), "points": (110, 60, 40), "eyes": (40, 120, 255)},
    key={
        "o": "coat",
        "d": "points",
        "b": "coat",
        "l": "coat",
        "q": "points",
        "L": "coat*0.6",
        "Q": "points*0.6",
        "i": "points*0.6",
        "n": "#ff8ca0",
        "w": "points",
    },
    head=(
        "d......d",
        "dd....dd",
        "oooooooo",
        "oooddooo",
        "oddddddo",
        "dddnnddd",
        ".dddddd.",
    ),
    tail={
        "a": (".d", "d.", "d.", "d.", ".o", ".o"),
        "b": ("d.", ".d", ".d", ".d", "o.", ".o"),
        "down": ("..", "..", "..", "d.", "d.", ".d"),
    },
    food="fish",
)

pet(
    "kitten",
    "Grey Kitten",
    "cats",
    "A tiny grey kitten with a pink nose and a white muzzle.",
    slots={"coat": (160, 164, 190), "white": (245, 245, 255), "eyes": (16, 12, 20)},
    key={"o": "coat", "c": "white", "b": "white", "i": "#ff8cb4", "n": "#ff6ea0", "w": "white"},
    head=(
        "o......o",
        "oi....io",
        "oooooooo",
        "oooooooo",
        "occcccco",
        "wccnnccw",
        ".cccccc.",
    ),
    eyes={"pts": [(9, 6), (13, 6)], "w": 2, "h": 2, "shine": True},
    chest=("ooooo", "ooocc", "ooocc", ".occc"),
    rump=(".ooo.", "ooooo", "ooooo", ".oooo"),
    rump_x=3,
    tail=_CAT_TAIL,
    tail_xy=(1, 3),
    food="fish",
)


# ----------------------------------------------------------------------------------------------- critters
pet(
    "fox",
    "Fox",
    "critters",
    "A clever red fox: black-tipped ears, white chest, huge white-tipped tail.",
    slots={"coat": (255, 96, 20), "white": (255, 245, 235), "socks": (60, 36, 30), "eyes": (20, 10, 6)},
    key={
        "o": "coat",
        "c": "white",
        "b": "white",
        "k": "socks",
        "l": "socks",
        "q": "socks",
        "L": "socks*0.7",
        "Q": "socks*0.7",
        "n": "#141010",
        "i": "#ff8c96",
    },
    head=(
        "k......k",
        "oo....oo",
        "oooooooo",
        "oooooooo",
        "cooooooc",
        "cccnnccc",
        "..cccc..",
    ),
    chest=("ooooo", "ooocc", "ooccc", ".occc"),
    tail={
        "a": ("..oo", ".ooo", "oooo", "ooo.", "cc..", "c..."),
        "b": (".oo.", "ooo.", "oooo", ".ooo", "..cc", "...c"),
        "down": ("....", "....", "o...", "ooo.", "oooc", ".occ"),
    },
    tail_xy=(0, 4),
)

pet(
    "capybara",
    "Capybara",
    "critters",
    "The calmest capybara: boxy snout, sleepy eyes, zero worries.",
    slots={"coat": (175, 110, 60), "snout": (120, 70, 36), "eyes": (20, 12, 8)},
    key={"o": "coat", "d": "snout", "b": "coat*0.85", "n": "#1e120a"},
    head=(
        ".o....o.",
        "oooooooo",
        "oooooooo",
        "oooooooo",
        "oooooooo",
        "ooddddoo",
        ".dnddnd.",
    ),
    eyes={"pts": [(10, 6), (13, 6)], "w": 1, "h": 1},
    chest=("ooooo", "ooooo", "ooooo", "ooooo"),
    rump=(".oooo", "ooooo", "ooooo", "ooooo"),
    tail={"a": ("..",), "b": ("..",), "down": ("..",)},
    tail_xy=(1, 9),
)
