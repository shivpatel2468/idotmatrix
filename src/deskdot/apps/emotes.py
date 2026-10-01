"""Emotes — big animated reaction faces that fill the panel (arena-game style), baked as native loops."""

from __future__ import annotations

import math
import random

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import Frame, hsv, mix, scale

EMOTES = {
    "laugh": "Laughing",
    "cry": "Crying",
    "angry": "Angry",
    "thumbs": "Thumbs up",
    "love": "Heart eyes",
    "wow": "Wow",
    "cool": "Cool",
    "wink": "Wink",
    "sleepy": "Sleepy",
    "think": "Thinking",
    "skull": "Skull",
    "fire": "On fire",
    "gg": "GG",
    "party": "Party",
    "clap": "Clap",
    "hundred": "100",
    "rage": "Rage quit",
}
STYLES = {"smiley": "Smiley", "king": "Arena King", "goblin": "Goblin", "cat": "Cat"}
SKIN = {"smiley": (255, 200, 0), "king": (255, 190, 140), "goblin": (110, 200, 60), "cat": (255, 150, 60)}

YY, XX = np.mgrid[0:32, 0:32]


class EmoteSettings(AppSettings):
    emote: str = Choice("laugh", EMOTES, title="Emote")
    style: str = Choice("smiley", STYLES, title="Face")
    cycle: bool = Field(False, title="Cycle through all emotes")
    background: str = Choice(
        "rays", {"none": "Black", "rays": "Sun rays", "burst": "Burst", "hearts": "Hearts"}
    )
    skin: Color = Field("#ffc800", title="Skin", description="Overrides the face colour")
    custom_skin: bool = Field(False, title="Use custom skin")
    speed: float = Field(1.0, ge=0.25, le=3.0, title="Speed")


@register
class Emotes(App):
    id = "emotes"
    name = "Emotes"
    description = "Full-screen animated emotes: laughing King, crying, GG, fire, 100, rage quit…"
    icon = "face-slightly-smiling-plus"
    category = "creative"
    Settings = EmoteSettings
    clip_seconds = 4.0
    clip_fps = 10.0  # the fastest GIF rate verified on the panel
    clip_colors = 64
    fps = 10.0

    def kind(self) -> Kind:
        return "stream" if self.settings.cycle else "clip"

    def n_frames(self) -> int:
        """Frames per baked loop: speed picks the loop length (40 = 4 s at speed 1), never the frame duration."""
        return min((16, 20, 24, 32, 40, 60, 80, 120, 160), key=lambda n: abs(n - 40 / self.settings.speed))

    def render(self, f: Frame, t: float) -> None:
        s = self.settings
        emote = s.emote
        if s.cycle:  # streamed: the emote changes every 3 s, so there is no loop to close
            t *= s.speed
            emote = list(EMOTES)[int(t // 3) % len(EMOTES)]
            loop = (t % 4.0) / 4.0
        else:  # baked: one loop of n_frames; the face runs 2 cycles in it, the background 1
            loop = (t * self.clip_fps / self.n_frames()) % 1.0
        ph = (loop * 2) % 1.0
        self._background(f, loop, emote)
        skin = s.skin if s.custom_skin else SKIN[s.style]
        self._face(f, ph, emote, skin)

    def clip_frames(self) -> Clip:
        n = self.n_frames()
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i / self.clip_fps)
            frames.append(f)
        return Clip(frames, [round(1000 / self.clip_fps)] * n)

    # ------------------------------------------------------------------ parts
    def _background(self, f: Frame, ph: float, emote: str) -> None:
        bg = self.settings.background
        if bg == "rays":
            ang = (
                np.arctan2(YY - 16, XX - 16) / math.tau + ph / 12
            ) % 1.0  # one ray pitch per loop: seamless
            mask = (ang * 12 % 1.0) < 0.5
            # dark but lit: (40, 22, 0) vanished at the panel's gamma 1.5
            f.px[mask] = (60, 32, 0) if emote not in ("cry", "sleepy") else (0, 24, 60)
        elif bg == "burst":
            d = np.hypot(XX - 15.5, YY - 15.5)
            ring = np.abs((d - ph * 22) % 11 - 5.5) < 1
            f.px[ring] = (72, 0, 60)
        elif bg == "hearts":
            rnd = random.Random(4)
            for _ in range(7):
                x, y0 = rnd.randrange(32), rnd.randrange(32)
                y = int((y0 - ph * 36) % 36) - 3  # one 36 px lap per loop: seamless, < 1 px per frame
                heart(f, x, y, (120, 0, 40))

    def _face(self, f: Frame, ph: float, emote: str, skin: tuple[int, int, int] | str) -> None:
        style = self.settings.style
        bounce = round(math.sin(ph * math.tau * 2) * 1.2) if emote in ("laugh", "party", "gg", "clap") else 0
        shake = [0, -1, 1, 0][int(ph * 16) % 4] if emote in ("angry", "rage") else 0
        cx, cy, r = 16 + shake, 17 + bounce, 12
        outline = scale(skin, 0.45)
        if emote == "skull":
            skin, outline = (235, 235, 225), (90, 90, 90)
        if emote == "angry" or emote == "rage":
            skin = mix(skin, (255, 40, 20), 0.45 + 0.25 * math.sin(ph * math.tau * 4))
        if style == "cat":
            for sx in (-1, 1):  # ears
                for k in range(6):
                    f.hline(cx + sx * 8 - (k if sx < 0 else 0) // 2, cy - r - 2 + k, k + 1, skin)
        if style == "goblin":
            for sx in (-1, 1):  # long pointy ears
                f.line(cx + sx * 11, cy - 2, cx + sx * 15, cy - 6, skin)
                f.line(cx + sx * 11, cy - 1, cx + sx * 15, cy - 5, outline)
        f.circle(cx, cy, r + 1, outline)
        f.circle(cx, cy, r, skin)
        f.circle(cx - 4, cy - 5, 3, mix(skin, (255, 255, 255), 0.35))  # highlight
        if style == "king":
            self._crown(f, cx, cy - r - 1, ph)
            beard = (240, 120, 30)
            for k in range(7):
                f.hline(cx - 7 + k // 2, cy + 6 + k, 15 - k, beard)
        getattr(self, f"_e_{emote}")(f, ph, cx, cy, skin)

    def _crown(self, f: Frame, cx: int, y: int, ph: float) -> None:
        gold = (255, 200, 0)
        f.rect(cx - 7, y - 1, 15, 3, gold)
        for dx in (-7, -3, 1, 5):
            f.rect(cx + dx, y - 4, 2, 3, gold)
        f.set(cx - 1, y, (255, 30, 60))
        if int(ph * 8) % 4 == 0:
            f.set(cx + 5, y - 4, (255, 255, 255))

    # ------------------------------------------------------------------ eyes / mouths
    @staticmethod
    def _eye(f: Frame, x: int, y: int, kind: str) -> None:
        dark = (30, 16, 10)
        if kind == "dot":
            f.rect(x, y, 2, 3, dark)
        elif kind == "happy":  # ^ shape
            f.set(x - 1, y + 1, dark)
            f.set(x, y, dark)
            f.set(x + 1, y, dark)
            f.set(x + 2, y + 1, dark)
        elif kind == "closed":
            f.hline(x - 1, y + 1, 4, dark)
        elif kind == "big":
            f.rect(x - 1, y - 1, 4, 4, (255, 255, 255))
            f.rect(x, y, 2, 2, dark)
        elif kind == "angry":
            f.rect(x, y + 1, 2, 2, dark)
            f.line(x - 2, y - 2, x + 2, y, dark)

    def _eyes(self, f: Frame, cx: int, cy: int, kind: str, dy: int = -3) -> None:
        self._eye(f, cx - 5, cy + dy, kind)
        self._eye(f, cx + 4, cy + dy, kind)

    def _e_laugh(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "happy")
        f.rect(cx - 5, cy + 1, 11, 5, (80, 10, 10))
        f.hline(cx - 5, cy + 1, 11, (255, 255, 255))
        f.rect(cx - 2, cy + 4, 5, 2, (255, 90, 110))
        for side in (-1, 1):  # tears flying out
            k = (ph * 4) % 1.0
            f.set(cx + side * (9 + round(k * 5)), cy - 3 + round(k * k * 6), (80, 200, 255))

    def _e_cry(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "closed")
        f.hline(cx - 3, cy + 4, 7, (80, 10, 10))
        f.set(cx - 4, cy + 5, (80, 10, 10))
        f.set(cx + 4, cy + 5, (80, 10, 10))
        for side in (-5, 4):  # streams of tears
            for k in range(4):
                y = cy - 1 + ((k * 3 + int(ph * 24)) % 12)
                f.set(cx + side, y, (60, 170, 255))

    def _e_angry(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "angry")
        f.hline(cx - 4, cy + 4, 9, (60, 0, 0))
        f.hline(cx - 4, cy + 5, 9, (255, 255, 255))
        for side in (-1, 1):  # steam puffs
            k = (ph * 2) % 1.0
            f.circle(cx + side * (10 + round(k * 3)), cy - 9 - round(k * 5), 1, scale((220, 220, 220), 1 - k))

    def _e_rage(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._e_angry(f, ph, cx, cy, skin)
        if int(ph * 8) % 2:
            f.text(cx - 6, cy - 16, "!!!", (255, 255, 255), font="small")

    def _e_thumbs(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "dot")
        f.hline(cx - 3, cy + 4, 7, (80, 10, 10))
        up = round(math.sin(ph * math.tau * 2) * 1.5)
        hx, hy = cx + 7, cy + 2 - up
        f.rect(hx, hy + 2, 6, 6, (255, 190, 120))
        f.rect(hx + 1, hy - 3, 3, 5, (255, 190, 120))
        f.vline(hx - 1, hy + 2, 6, (140, 90, 50))

    def _e_love(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        pulse = 1 if int(ph * 8) % 2 else 0
        for ex in (cx - 6, cx + 3):
            heart(f, ex, cy - 6 - pulse, (255, 30, 80))
        f.rect(cx - 3, cy + 3, 7, 2, (80, 10, 10))
        f.set(cx - 4, cy + 2, (80, 10, 10))
        f.set(cx + 4, cy + 2, (80, 10, 10))

    def _e_wow(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "big")
        r = 2 + (1 if int(ph * 6) % 2 else 0)
        f.circle(cx, cy + 5, r, (70, 10, 10))

    def _e_cool(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        f.rect(cx - 9, cy - 4, 8, 4, (10, 10, 20))
        f.rect(cx + 1, cy - 4, 8, 4, (10, 10, 20))
        f.hline(cx - 9, cy - 4, 18, (10, 10, 20))
        glint = int(ph * 16) % 16
        if glint < 6:
            f.set(cx - 8 + glint, cy - 3, (255, 255, 255))
        f.line(cx - 3, cy + 5, cx + 4, cy + 4, (80, 10, 10))

    def _e_wink(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eye(f, cx - 5, cy - 3, "dot")
        self._eye(f, cx + 4, cy - 3, "happy" if ph > 0.3 else "dot")
        f.line(cx - 4, cy + 3, cx + 3, cy + 5, (80, 10, 10))
        f.set(cx + 5, cy + 4, (255, 90, 110))

    def _e_sleepy(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "closed")
        f.circle(cx + 1, cy + 5, 1, (80, 10, 10))
        z = (ph * 1.0) % 1.0
        f.text(
            cx + 8 + round(z * 3),
            cy - 10 - round(z * 6),
            "Z",
            scale((180, 200, 255), 1 - z * 0.6),
            font="small",
        )

    def _e_think(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eye(f, cx - 4, cy - 4, "dot")
        self._eye(f, cx + 5, cy - 4, "dot")
        f.hline(cx - 2, cy + 5, 6, (80, 10, 10))
        f.rect(cx + 3, cy + 7, 6, 4, (255, 190, 120))  # hand on chin
        for i in range(3):
            on = int(ph * 6) % 3 == i
            f.set(cx + 10 + i * 2, cy - 12 + i, (255, 255, 255) if on else (90, 90, 110))

    def _e_skull(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        for ex in (cx - 6, cx + 2):
            f.rect(ex, cy - 4, 4, 4, (20, 20, 20))
        if int(ph * 4) % 2:
            f.set(cx - 5, cy - 3, (255, 40, 40))
            f.set(cx + 3, cy - 3, (255, 40, 40))
        f.rect(cx - 1, cy + 1, 2, 2, (20, 20, 20))
        for k in range(5):
            f.vline(cx - 4 + k * 2, cy + 5, 3, (20, 20, 20))

    def _e_fire(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "angry")
        f.hline(cx - 4, cy + 4, 9, (80, 10, 10))
        rnd = np.random.default_rng(int(ph * 24))
        for x in range(cx - 10, cx + 11):
            h = int(4 + rnd.integers(0, 6) + 3 * math.sin(x * 0.7 + ph * math.tau * 2))
            for k in range(h):
                f.set(x, cy - 12 - k + 3, mix((255, 60, 0), (255, 230, 80), k / max(1, h)))

    def _e_gg(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "happy", dy=-5)
        # cycle blue -> magenta -> red and back: never through yellow, which vanishes on the yellow face
        col = hsv(0.55 + 0.5 * (1 - abs(2 * ph - 1)))
        f.text(cx - 5, cy - 1, "GG", col, font="small")
        for i in range(4):
            a = ph * math.tau + i * math.pi / 2
            f.set(round(cx + math.cos(a) * 15), round(cy + math.sin(a) * 14), (255, 255, 255))

    def _e_party(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "happy")
        f.rect(cx - 4, cy + 2, 9, 3, (80, 10, 10))
        f.line(cx + 4, cy - 12, cx + 9, cy - 22, (0, 200, 255))  # party hat
        f.line(cx + 4, cy - 12, cx + 12, cy - 13, (0, 200, 255))
        rnd = random.Random(7)
        for _ in range(16):
            x, y0 = rnd.randrange(32), rnd.randrange(32)
            y = int((y0 + ph * 32) % 32)
            f.set(x, y, hsv(rnd.random()))

    def _e_clap(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        self._eyes(f, cx, cy, "happy")
        f.rect(cx - 3, cy + 2, 7, 3, (80, 10, 10))
        gap = 1 + round(abs(math.sin(ph * math.tau * 3)) * 5)
        for side in (-1, 1):
            f.rect(cx + side * gap - (5 if side < 0 else 0), cy + 7, 5, 6, (255, 190, 120))
        if gap <= 2:
            for dx in (-7, 0, 7):
                f.set(cx + dx, cy + 5, (255, 255, 255))

    def _e_hundred(self, f: Frame, ph: float, cx: int, cy: int, skin: object) -> None:
        f.rect(0, 0, 32, 32, (0, 0, 0))
        col = mix((255, 30, 40), (255, 120, 0), 0.5 + 0.5 * math.sin(ph * math.tau * 2))
        f.text(2, 8, "100", col, font="big")
        for k in range(2):
            f.hline(3, 21 + k * 3, 26, col)


def heart(f: Frame, x: int, y: int, c: tuple[int, int, int]) -> None:
    for dx, dy in ((1, 0), (3, 0), (0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (1, 2), (2, 2), (3, 2), (2, 3)):
        f.set(x + dx, y + dy, c)
