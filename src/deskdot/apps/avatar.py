"""Pixel Avatar — Minecraft faces, GitHub identicons and DiceBear pixel characters on an exact grid.

Every source is pixel art whose native grid divides the panel: an 8×8 Minecraft face ×4, a 5×5 identicon in
6 px cells with a 1 px margin, a 16×16 DiceBear character ×2. Names rotate with a name tag; bob and blink
are drawn in code. The rotation is deterministic, so it is baked as a clip and plays natively.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import PALETTE, Frame, draw_marquee, scale
from ..gfx.color import RGB
from ..providers.avatars import Avatar, parse_names
from ._kit import loading, offline
from .pokedex import bake

BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)
SOURCE_COLORS: dict[str, RGB] = {
    "minecraft": (90, 200, 60),
    "github": (200, 200, 220),
    "dicebear": (255, 120, 40),
}


class AvatarSettings(AppSettings):
    names: str = Field(
        "Notch, jeb_, gh:torvalds, db:deskdot",
        max_length=400,
        title="Names",
        description="Comma-separated. Prefix gh: for a GitHub identicon, db: for a DiceBear character, "
        "mc: for a Minecraft face; unprefixed names use the default source",
    )
    source: str = Choice(
        "minecraft",
        {"minecraft": "Minecraft face", "github": "GitHub identicon", "dicebear": "DiceBear pixel art"},
        title="Default source",
    )
    layout: str = Choice("framed", {"framed": "Face + name tag", "full": "Full screen"}, title="Layout")
    tag: str = Choice(
        "intro", {"off": "Off", "intro": "Flash on change", "always": "Always"}, title="Name tag"
    )
    animation: str = Choice(
        "both", {"none": "None", "bob": "Bob", "blink": "Blink", "both": "Bob + blink"}, title="Animation"
    )
    seconds: int = Field(8, ge=2, le=120, title="Seconds per name")
    background: str = Choice(
        "source", {"black": "Black", "source": "Source tint", "grid": "Grid"}, title="Background"
    )


def scaled(
    av: Avatar, k: int, crop: tuple[int, int, int, int] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest-neighbour ×k (the only resampling pixel art ever gets), optionally cropping (x0, y0, x1, y1)."""
    px, mask = av.px, av.mask
    if crop:
        x0, y0, x1, y1 = crop
        px, mask = px[y0:y1, x0:x1], mask[y0:y1, x0:x1]
    return np.repeat(np.repeat(px, k, 0), k, 1), np.repeat(np.repeat(mask, k, 0), k, 1)


def blinked(av: Avatar) -> Avatar:
    """A Minecraft face with its eyes closed (unchanged if no eyes are found).

    Skins put the eyes anywhere in rows 2–5, columns 1–2 and 5–6, so they are found by colour: cells there
    that differ from the skin tone (the most common colour of the cheek / nose-bridge columns 0, 3, 4, 7 in
    rows 2–4). The first row pair with eyes on both sides is painted with skin, the lower row as a lid line.
    """
    px = av.px.copy()
    probe = px[2:5][:, [0, 3, 4, 7]].reshape(-1, 3)
    cols, counts = np.unique(probe, axis=0, return_counts=True)
    skin = cols[counts.argmax()].astype(np.int32)

    def odd(r: int) -> list[int]:
        return [c for c in (1, 2, 5, 6) if int(np.abs(px[r, c].astype(np.int32) - skin).sum()) > 90]

    rows = [r for r in range(2, 5) if any(c < 4 for c in odd(r)) and any(c > 4 for c in odd(r))]
    if not rows:  # no recognisable pair of eyes: don't mangle the face
        return av
    eye_rows = [rows[0]] + ([rows[0] + 1] if rows[0] + 1 in rows else [])
    for r in eye_rows:
        for c in odd(r):
            px[r, c] = skin
    for c in (1, 2, 5, 6):
        px[eye_rows[-1], c] = (skin * 0.6).astype(np.uint8)
    return Avatar(av.source, av.name, px, av.mask)


@register
class PixelAvatar(App):
    id = "avatar"
    name = "Pixel Avatar"
    description = (
        "Minecraft faces, GitHub identicons and DiceBear pixel characters — pixel-exact, with a name tag."
    )
    icon = "user-round"
    category = "creative"
    Settings = AvatarSettings
    uses = ("avatars",)
    fps = 5.0
    clip_fps = 10.0
    clip_colors = 64

    # ------------------------------------------------------------ data
    def _provider(self) -> Any:
        try:
            return self.ctx.provider("avatars")
        except KeyError:
            return None

    def items(self) -> list[tuple[str, str]]:
        return parse_names(self.settings.names, self.settings.source) or [(self.settings.source, "Steve")]

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            p.want(self.items())

    def on_settings(self) -> None:
        self.on_start()

    def loaded(self) -> list[Avatar]:
        p = self._provider()
        cache = (p.value if p is not None else None) or {}
        if p is not None and any(k not in cache and not p.failed(k) for k in self.items()):
            self.on_start()
        return [cache[k] for k in self.items() if k in cache]

    # ------------------------------------------------------------ output
    def kind(self) -> Kind:
        return "clip" if self.loaded() else "stream"

    def clip_key(self) -> str:
        return super().clip_key() + "|" + ",".join(f"{a.source}:{a.name}" for a in self.loaded())

    def clip_frames(self) -> Clip:
        return bake(self, self.settings.seconds * max(1, len(self.loaded())), fps=self.clip_fps)

    def render(self, f: Frame, t: float) -> None:
        avs = self.loaded()
        if not avs:
            p = self._provider()
            if p is not None and (p.error or all(p.failed(k) for k in self.items())):
                offline(f, "AVATAR", "OFFLINE" if p.error else "NOT FOUND")
            else:
                loading(f, t, "AVATAR", PALETTE["lime"])
            return
        s = self.settings
        i = int(t // s.seconds) % len(avs)
        lt = t % s.seconds
        self.draw(f, avs[i], lt)

    def draw(self, f: Frame, av: Avatar, lt: float) -> None:
        s = self.settings
        anim = s.animation
        blink = (
            anim in ("blink", "both")
            and av.source == "minecraft"
            and any(a <= lt < a + 0.18 for a in (2.2, 2.55, 5.8))
        )
        bob = -1 if anim in ("bob", "both") and int(lt / 0.6) % 2 else 0
        src = blinked(av) if blink else av
        tint = SOURCE_COLORS.get(av.source, PALETTE["mute"])
        full = s.layout == "full"
        f.clear(scale(tint, 0.07) if s.background == "source" else BLACK)
        if s.background == "grid":
            for y in range(0, 32, 2):
                for x in range(y % 4 // 2, 32, 2):
                    f.set(x, y, PALETTE["ink"])
        if full:
            if av.source == "minecraft":
                px, m = scaled(src, 4)
                x, y = 0, 0
            elif av.source == "github":
                px, m = scaled(src, 6)
                x, y = 1, 1
            else:
                px, m = scaled(src, 2)
                x, y = 0, 0
            f.blit(px, x, y + (bob if av.source != "minecraft" else 0), m)
            tag_on = s.tag == "always" or (s.tag == "intro" and lt < 2.5)
            if tag_on:
                f.px[25:32] = (f.px[25:32].astype(np.float32) * 0.18).astype(np.uint8)
                draw_marquee(f, av.name.upper(), lt, 1, 26, 30, WHITE)
            return
        # framed: 24×24 face (identicon 20×20 on a tile), name tag below
        if av.source == "minecraft":
            px, m = scaled(src, 3)
            x, y = 4, 1
        elif av.source == "github":
            f.rect(4, 1, 24, 24, scale(tint, 0.10))
            px, m = scaled(src, 4)
            x, y = 6, 3
        else:
            px, m = scaled(src, 2, crop=(2, 0, 14, 12))
            x, y = 4, 1
        f.blit(px, x, y + bob, m)
        if s.tag != "off":
            flash = s.tag == "intro" and lt < 0.4
            col = WHITE if flash else scale(WHITE, 0.9)
            draw_marquee(f, av.name.upper(), lt, 1, 26, 30, col)
            f.hline(1, 32 - 1, 30, scale(tint, 0.6 if flash else 0.3))

    def status(self) -> dict[str, Any]:
        return {"names": [f"{s}:{n}" for s, n in self.items()], "loaded": len(self.loaded())}
