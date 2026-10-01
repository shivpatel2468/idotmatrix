"""Player avatars: tiny 8×8 pixel characters a phone player picks in the multiplayer lobby (original art).

The same bitmaps are drawn on the panel (lobby join card) and sent to the phone controller, which draws them
on a canvas — one source of truth. Pixel codes: `c` player colour, `d` darker player colour, `w` white,
`k` black (reads as "off" on the LEDs), `y` yellow, `r` red, `.` transparent.
"""

from __future__ import annotations

from functools import lru_cache

from .color import RGB, scale
from .frame import Frame, Sprite

AVATARS: dict[str, tuple[str, tuple[str, ...]]] = {
    "bot": (
        "Robot",
        (
            "...y....",
            "...c....",
            ".cccccc.",
            ".cwccwc.",
            ".cccccc.",
            ".ckkkkc.",
            "..dddd..",
            ".cc..cc.",
        ),
    ),
    "cat": (
        "Cat",
        (
            "c......c",
            "cc....cc",
            "cccccccc",
            "cwkccwkc",
            "cccccccc",
            "cccrrccc",
            ".cccccc.",
            "..d..d..",
        ),
    ),
    "ghost": (
        "Ghost",
        (
            "..cccc..",
            ".cccccc.",
            "cwwccwwc",
            "cwkccwkc",
            "cccccccc",
            "cccccccc",
            "cccccccc",
            "c.cc.cc.",
        ),
    ),
    "alien": (
        "Alien",
        (
            "y......y",
            ".c....c.",
            "..cccc..",
            ".cccccc.",
            "ckkcckkc",
            "cwkcckwc",
            ".cccccc.",
            "..d..d..",
        ),
    ),
    "knight": (
        "Knight",
        (
            "....rr..",
            "..cccr..",
            ".cccccc.",
            ".ckkkkc.",
            ".cwkkwc.",
            ".cccccc.",
            "..dddd..",
            ".dd..dd.",
        ),
    ),
    "ninja": (
        "Ninja",
        (
            "..cccc..",
            ".cccccc.",
            ".kkkkkkr",
            ".kwkkwkr",
            ".kkkkkk.",
            ".cccccc.",
            "..dddd..",
            ".cc..cc.",
        ),
    ),
    "slime": (
        "Slime",
        (
            "........",
            "...cc...",
            "..cccc..",
            ".cwccwc.",
            ".ckccck.",
            "cccccccc",
            "cccccccc",
            ".dddddd.",
        ),
    ),
    "frog": (
        "Frog",
        (
            ".ww..ww.",
            "wkwccwkw",
            "cccccccc",
            "cccccccc",
            "crrrrrrc",
            ".cccccc.",
            "d.d..d.d",
            "........",
        ),
    ),
}
AVATAR_IDS: tuple[str, ...] = tuple(AVATARS)
SIZE = 8


@lru_cache(maxsize=128)
def avatar_sprite(avatar: str, colour: RGB) -> Sprite:
    """The avatar as a sprite in `colour` (unknown ids fall back to the first avatar)."""
    _label, rows = AVATARS.get(avatar) or AVATARS[AVATAR_IDS[0]]
    pal = {
        "c": colour,
        "d": scale(colour, 0.5),
        "w": (235, 235, 235),
        "k": (0, 0, 0),
        "y": (255, 200, 0),
        "r": (255, 40, 60),
    }
    return Sprite.parse(rows, pal)


def draw_avatar(f: Frame, x: int, y: int, avatar: str, colour: RGB, zoom: int = 1) -> None:
    """Draw an avatar with its top-left at (x, y); `zoom` scales each pixel to a zoom × zoom block (clipped)."""
    sp = avatar_sprite(avatar, tuple(colour))  # type: ignore[arg-type]
    if zoom == 1:
        f.sprite(sp, x, y)
        return
    for yy in range(sp.h):
        for xx in range(sp.w):
            if sp.mask[yy, xx]:
                p = sp.px[yy, xx]
                f.rect(x + xx * zoom, y + yy * zoom, zoom, zoom, (int(p[0]), int(p[1]), int(p[2])))
