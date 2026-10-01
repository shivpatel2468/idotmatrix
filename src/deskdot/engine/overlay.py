"""Notification overlay and app-switch transitions, composed on top of the live frame."""

from __future__ import annotations

import math
import random
import time
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from ..gfx import Frame, Sprite, draw_marquee, ease_in_out, mix, scale, to_rgb
from ..gfx.font import measure
from ..gfx.icons import ICONS

Transition = Literal["cut", "push", "fade", "wipe"]


class Notice(BaseModel):
    title: str = Field(default="", max_length=40)
    message: str = Field(default="", max_length=280)
    color: str = "#00dcff"
    icon: str | None = "bell"
    duration: float = Field(default=6.0, ge=1.0, le=120.0)
    style: Literal["banner", "full", "celebrate"] = "banner"


class ActiveNotice:
    SLIDE = 0.28

    def __init__(self, notice: Notice) -> None:
        self.n = notice
        self.start = time.monotonic()
        self.color = to_rgb(notice.color)
        self.icon = Sprite.parse(ICONS[notice.icon], {"#": self.color}) if notice.icon in ICONS else None

    @property
    def done(self) -> bool:
        return time.monotonic() - self.start >= self.n.duration

    def render(self, f: Frame) -> None:
        t = time.monotonic() - self.start
        d = self.n.duration
        if t < self.SLIDE:
            k = ease_in_out(t / self.SLIDE)
        elif t > d - self.SLIDE:
            k = ease_in_out((d - t) / self.SLIDE)
        else:
            k = 1.0
        if self.n.style == "full":
            self._full(f, t, k)
        elif self.n.style == "celebrate":
            self._celebrate(f, t)
        else:
            self._banner(f, t, k)

    def _banner(self, f: Frame, t: float, k: float) -> None:
        # 13-px card rising from the bottom edge; the app stays visible (dimmed) above it
        h = 13
        y = 32 - round(h * k)
        f.px[: max(0, y)] = (f.px[: max(0, y)].astype(np.float32) * (1 - 0.55 * k)).astype(np.uint8)
        f.rect(0, y, 32, h, (6, 6, 12))
        f.hline(0, y, 32, self.color)
        x = 1
        if self.icon:
            f.sprite(self.icon, 1, y + 3)
            x = 8
        label = self.n.message or self.n.title
        if self.n.title and self.n.message:
            f.text(x, y + 2, self.n.title, self.color, clip=(x, y + 1, 31, y + 6))
            draw_marquee(f, self.n.message, max(0.0, t - 0.5), x, y + 7, 32 - x, (255, 255, 255), speed=14)
        else:
            draw_marquee(f, label, max(0.0, t - 0.5), x, y + 5, 32 - x, (255, 255, 255), speed=14)

    def _celebrate(self, f: Frame, t: float) -> None:
        """Goal! Team-colour strobe, then fireworks behind the big word and a scrolling score line."""
        c = self.color
        f.clear()
        if t < 0.9:  # strobe
            if int(t * 10) % 2 == 0:
                f.clear(c)
            return
        tt = t - 0.9
        rnd = random.Random(42)
        for burst in range(5):
            cx, cy = rnd.randint(4, 27), rnd.randint(3, 20)
            start = burst * 0.7
            age = (tt - start) % 3.5
            if age > 1.6:
                continue
            col = c if burst % 2 == 0 else mix(c, (255, 255, 255), 0.5)
            r = age * 9
            fade = max(0.0, 1 - age / 1.6)
            for i in range(12):
                a = i / 12 * math.tau
                f.set(
                    round(cx + math.cos(a) * r), round(cy + math.sin(a) * r + age * age * 2), scale(col, fade)
                )
        word, _, rest = self.n.message.partition(" ")
        f.text_center(5, self.n.title, c)
        pulse = 0.75 + 0.25 * math.sin(tt * 8)
        f.text_center(13, word, scale((255, 255, 255), pulse), font="small")
        draw_marquee(f, rest, tt, 0, 25, 32, mix(c, (255, 255, 255), 0.4), speed=14)

    def _full(self, f: Frame, t: float, k: float) -> None:
        base = f.px.astype(np.float32) * (1 - k)
        f.px[:] = base.astype(np.uint8)
        if k < 0.5:
            return
        f.rect(0, 0, 32, 8, scale(self.color, 0.25))
        f.hline(0, 7, 32, self.color)
        if self.icon:
            f.sprite(self.icon, 1, 0)
        f.text(
            8 if self.icon else 1,
            1,
            self.n.title or "ALERT",
            self.color,
            clip=(8 if self.icon else 1, 0, 31, 6),
        )
        msg = self.n.message
        if measure(msg, "small") <= 30:
            f.text_center(14, msg, (255, 255, 255), font="small")
        else:
            draw_marquee(f, msg, max(0.0, t - 0.6), 1, 14, 30, (255, 255, 255), font="small", speed=16)
        # remaining-time bar
        rem = max(0.0, 1 - t / self.n.duration)
        f.hline(1, 29, round(30 * rem), mix(self.color, (40, 40, 40), 0.35))


def transition(old: Frame, new: Frame, p: float, style: Transition) -> Frame:
    """Blend two frames; p goes 0 -> 1."""
    p = ease_in_out(p)
    if style == "cut" or p >= 1:
        return new
    out = Frame()
    if style == "fade":
        a = old.px.astype(np.float32)
        b = new.px.astype(np.float32)
        # fade through black reads better on LEDs than a cross-dissolve
        k = 1 - 2 * p if p < 0.5 else 2 * p - 1
        out.px[:] = ((a if p < 0.5 else b) * k).astype(np.uint8)
    elif style == "push":
        dx = round(32 * p)
        out.px[:, : 32 - dx] = old.px[:, dx:]
        out.px[:, 32 - dx :] = new.px[:, :dx]
    else:  # wipe: a bright scan line reveals the new frame top-down
        dy = round(32 * p)
        out.px[:dy] = new.px[:dy]
        out.px[dy:] = old.px[dy:]
        if 0 < dy < 32:
            out.px[dy] = (255, 255, 255)
    return out
