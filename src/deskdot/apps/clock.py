"""Clock — four designed faces."""

from __future__ import annotations

import math
import random
from datetime import datetime

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import Frame, mix, scale
from ._kit import label, ring


class ClockSettings(AppSettings):
    style: str = Choice(
        "hero",
        {
            "hero": "Hero",
            "stacked": "Stacked",
            "minimal": "Minimal",
            "analog": "Analog",
            "nixie": "Nixie tubes",
            "segment": "7-segment LCD",
            "flip": "Split-flap",
            "binary": "Binary",
            "word": "Word clock",
            "rings": "Rings",
            "sky": "Sun & moon",
            "rain": "Digital rain",
        },
    )
    hour24: bool = Field(True, title="24-hour")
    seconds: str = Choice("ring", {"ring": "Edge ring", "none": "Hidden"}, title="Seconds")
    blink: bool = Field(True, title="Blink colon")
    color: Color = Field("#ffffff", title="Time colour")
    accent: Color = Field("#ff4818", title="Accent")


@register
class Clock(App):
    id = "clock"
    name = "Clock"
    description = "Hero, stacked, minimal and analog faces with a seconds ring."
    icon = "clock"
    category = "time"
    Settings = ClockSettings
    fps = 2.0

    def _hm(self, now: datetime) -> tuple[str, str]:
        h = now.hour if self.settings.hour24 else (now.hour % 12 or 12)
        return f"{h:02d}", f"{now.minute:02d}"  # fixed width: digits never shift

    def render(self, f: Frame, t: float) -> None:
        now = datetime.now()
        getattr(self, f"_{self.settings.style}", self._hero)(f, now)

    # ------------------------------------------------------------------ faces
    def _colon(self, now: datetime) -> bool:
        return not self.settings.blink or now.microsecond < 500_000

    def _hero(self, f: Frame, now: datetime) -> None:
        s = self.settings
        hh, mm = self._hm(now)
        # the full "28 SEP" date on top, weekday (plus AM/PM in 12 h) underneath — the user's preferred order
        day = now.strftime("%A").upper()[:3]
        top = now.strftime("%d %b").upper()
        bottom = day if s.hour24 else f"{day} {'AM' if now.hour < 12 else 'PM'}"
        f.text_center(4, top, mix(s.accent, (255, 255, 255), 0.25))
        x = 1
        x = f.text(x, 11, hh, s.color, font="big") + 1
        if self._colon(now):
            f.text(x, 11, ":", s.accent, font="big")
        f.text(x + 3, 11, mm, s.color, font="big")
        f.text_center(24, bottom, scale(s.accent, 0.8))
        if s.seconds == "ring":
            # the full, unbroken ring (a gap beside the digits read as "cut" on the panel)
            ring(f, (now.second + now.microsecond / 1e6) / 60, s.accent, track=None)

    def _stacked(self, f: Frame, now: datetime) -> None:
        s = self.settings
        hh, mm = self._hm(now)
        f.text(2, 3, hh, s.color, font="big")
        f.text(2, 19, mm, s.accent, font="big")
        if self._colon(now):
            f.rect(7, 15, 2, 2, scale(s.color, 0.6))
            f.rect(10, 15, 2, 2, scale(s.color, 0.6))
        # right column x = 17..30 (14 px): clear of the digits; the seconds bar owns x = 31
        col = (17, 14)
        label(f, 4, now.strftime("%a").upper(), mix(s.accent, (255, 255, 255), 0.3), x=col[0], w=col[1])
        label(f, 12, now.strftime("%d"), s.color, font="small", x=col[0], w=col[1])
        label(f, 22, now.strftime("%b").upper(), scale(s.accent, 0.8), x=col[0], w=col[1])
        if s.seconds == "ring":
            h = round(30 * now.second / 59)
            f.vline(31, 31 - h, h, scale(s.accent, 0.7))

    def _minimal(self, f: Frame, now: datetime) -> None:
        s = self.settings
        hh, mm = self._hm(now)
        f.text_center(12, f"{hh}{':' if self._colon(now) else ' '}{mm}", s.color, font="small")
        f.text_center(22, now.strftime("%d.%m"), scale(s.accent, 0.8))
        if s.seconds == "ring":
            ring(f, now.second / 60, scale(s.accent, 0.6), track=None, head=False)

    def _analog(self, f: Frame, now: datetime) -> None:
        s = self.settings
        cx = cy = 15.5
        for i in range(12):
            a = i / 12 * math.tau
            r = 14.6
            x, y = round(cx + math.sin(a) * r - 0.5), round(cy - math.cos(a) * r - 0.5)
            f.set(x, y, s.accent if i % 3 == 0 else (60, 60, 80))

        def hand(frac: float, length: float, color: tuple[int, int, int] | str) -> None:
            a = frac * math.tau
            f.line(15, 15, round(15 + math.sin(a) * length), round(15 - math.cos(a) * length), color)

        sec = now.second + now.microsecond / 1e6
        hand(((now.hour % 12) + now.minute / 60) / 12, 7, s.color)
        hand((now.minute + sec / 60) / 60, 11, scale(s.color, 0.85))
        if s.seconds == "ring":
            hand(sec / 60, 13, s.accent)
        f.rect(15, 15, 2, 2, s.accent)

    # ------------------------------------------------------------------ more faces
    def _nixie(self, f: Frame, now: datetime) -> None:
        """Warm glowing tube digits with the unlit '8' cathode ghosts behind them."""
        s = self.settings
        hh, mm = self._hm(now)
        glow = (255, 120, 20) if s.color == "#ffffff" else s.color
        ghost = scale(glow, 0.09)
        for i, ch in enumerate(hh + mm):
            x = 1 + i * 8 + (1 if i >= 2 else 0)
            f.rect(x - 1, 2, 8, 28, (14, 8, 4))  # tube glass
            f.rect(x - 1, 2, 8, 1, (40, 24, 12))
            f.text(x, 6, "8", ghost, font="big")
            f.text(x, 6, ch, glow, font="big")
            f.text(x, 6, ch, mix(glow, (255, 230, 180), 0.35), font="big", clip=(x, 6, x + 5, 8))
        if self._colon(now):
            f.set(16, 12, glow)
            f.set(16, 18, glow)
        f.hline(0, 30, 32, scale(glow, 0.25))
        if s.seconds == "ring":
            f.hline(0, 31, round(32 * now.second / 59), scale(glow, 0.7))

    def _segment(self, f: Frame, now: datetime) -> None:
        """Retro LCD: tall 7-segment digits with ghost segments, a date line and seconds bar."""
        s = self.settings
        hh, mm = self._hm(now)
        on = s.color if s.color != "#ffffff" else (120, 255, 150)
        off = scale(on, 0.08)
        xs = (0, 7, 18, 25)
        for x, ch in zip(xs, hh + mm, strict=True):
            seven_seg(f, x, 4, ch, on, off, w=7, h=15)
        colon = on if self._colon(now) else off
        f.rect(15, 8, 2, 2, colon)
        f.rect(15, 14, 2, 2, colon)
        f.text_center(23, now.strftime("%a %d").upper(), scale(on, 0.75))
        if s.seconds == "ring":
            f.bar(0, 30, 32, 2, now.second / 59, scale(on, 0.8), track=off)

    def _flip(self, f: Frame, now: datetime) -> None:
        """Split-flap cards: each digit on its own card with a hinge; the minute card flips as it turns."""
        s = self.settings
        hh, mm = self._hm(now)
        card, edge = (30, 30, 40), (56, 56, 70)
        flipping = now.second == 59 and now.microsecond > 500_000
        for i, ch in enumerate(hh + mm):
            x = [0, 8, 18, 26][i]
            f.rect(x, 4, 7, 18, card)
            f.hline(x, 4, 7, edge)
            if flipping and i == 3:  # the top half folds down: squash it toward the hinge
                f.rect(x, 4, 7, 9, scale(card, 1.6))
            else:
                f.text(x, 8, ch, s.color, font="big")
            f.hline(x, 12, 7, (0, 0, 0))  # hinge gap splits the card
        dot = s.accent if self._colon(now) else (40, 40, 50)
        f.rect(15, 9, 2, 2, dot)
        f.rect(15, 15, 2, 2, dot)
        f.text_center(25, now.strftime("%a %d").upper(), scale(s.accent, 0.85))

    def _binary(self, f: Frame, now: datetime) -> None:
        """BCD binary clock: six columns (H H M M S S), four bits each, bottom = 1."""
        s = self.settings
        digits = now.strftime("%H%M%S")
        colors = [s.accent, s.accent, s.color, s.color, (0, 220, 255), (0, 220, 255)]
        for col, ch in enumerate(digits):
            x = 1 + col * 5 + (col // 2)
            v = int(ch)
            for bit in range(4):
                y = 22 - bit * 6
                on = (v >> bit) & 1
                f.rect(x, y, 4, 4, colors[col] if on else (22, 22, 30))
            f.text(x + 1, 27, ch, scale(colors[col], 0.6))

    def _word(self, f: Frame, now: datetime) -> None:
        """Word clock: the time as words, centred, lit words bright and big where they fit."""
        s = self.settings
        words = word_time(now)
        ys = {1: [12], 2: [7, 17], 3: [3, 12, 21]}[len(words)]
        for w, y in zip(words, ys, strict=True):
            font = "small" if len(w) <= 5 else "tiny"
            col = s.accent if w in ("PAST", "TO", "O'CLOCK") else s.color
            f.text_center(y + (1 if font == "tiny" else 0), w, col, font=font)
        f.text_right(30, 27, now.strftime("%M"), (60, 60, 80))

    def _rings(self, f: Frame, now: datetime) -> None:
        """Concentric arcs for hours, minutes and seconds with the time in the middle."""
        s = self.settings
        sec = now.second + now.microsecond / 1e6
        arcs = (
            (15.0, ((now.hour % 12) + now.minute / 60) / 12, s.accent),
            (12.5, (now.minute + sec / 60) / 60, s.color),
            (10.0, sec / 60, (0, 220, 255)),
        )
        for r, frac, col in arcs:
            steps = int(2 * math.pi * r * 1.6)
            for k in range(steps):
                a = k / steps
                c = col if a <= frac else scale(col, 0.1)
                f.set(
                    round(15.5 + math.sin(a * math.tau) * r - 0.5),
                    round(15.5 - math.cos(a * math.tau) * r - 0.5),
                    c,
                )
        hh, mm = self._hm(now)
        f.text_center(10, hh, s.color, font="small")
        f.text_center(18, mm, s.accent, font="small")

    def _sky(self, f: Frame, now: datetime) -> None:
        """The sun (or moon) travels an arc across a sky whose colour follows the time of day."""
        s = self.settings
        day = (now.hour + now.minute / 60) / 24
        light = max(0.0, math.sin((day - 0.25) * math.tau))  # 0 at night, 1 at noon
        top = mix((4, 6, 24), (20, 90, 200), light)
        bottom = mix((10, 10, 40), (255, 150, 60), light**0.5 if 0.2 < day < 0.85 else 0)
        f.gradient_v(top, bottom, 0, 24)
        rnd = random.Random(3)
        for _ in range(12 if light < 0.2 else 0):
            f.set(rnd.randrange(32), rnd.randrange(18), (200, 200, 230))
        is_day = 0.25 <= day < 0.75
        p = (day - 0.25) / 0.5 if is_day else ((day + 0.25) % 1) / 0.5
        cx, cy = round(2 + p * 27), round(19 - math.sin(p * math.pi) * 15)
        if is_day:
            f.circle(cx, cy, 2, (255, 214, 0))
        else:
            f.circle(cx, cy, 2, (230, 230, 210))
            f.circle(cx + 1, cy - 1, 1, top)
        f.rect(0, 24, 32, 8, (8, 20, 10) if light > 0.05 else (4, 8, 6))
        hh, mm = self._hm(now)
        f.text_center(26, f"{hh}:{mm}", s.color)

    def _rain(self, f: Frame, now: datetime) -> None:
        """Big time over falling green code."""
        s = self.settings
        t = now.timestamp()
        rnd = random.Random(9)
        for x in range(0, 32, 2):
            speed, off, length = rnd.uniform(6, 14), rnd.random() * 40, rnd.randint(4, 10)
            y = int((t * speed + off * 10) % 44) - 6
            for k in range(length):
                yy = y - k
                if 0 <= yy < 32:
                    f.set(x, yy, (180, 255, 180) if k == 0 else (0, max(30, 200 - k * 22), 40))
        hh, mm = self._hm(now)
        f.rect(0, 10, 32, 12, (0, 0, 0))
        x = f.text(1, 11, hh, s.color if s.color != "#ffffff" else (160, 255, 170), font="big") + 1
        if self._colon(now):
            f.text(x, 11, ":", (0, 255, 90), font="big")
        f.text(x + 3, 11, mm, s.color if s.color != "#ffffff" else (160, 255, 170), font="big")


# ------------------------------------------------------------------ helpers for the extra faces
SEGMENTS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgedc",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
}


def seven_seg(
    f: Frame,
    x: int,
    y: int,
    ch: str,
    on: tuple[int, int, int],
    off: tuple[int, int, int],
    w: int = 6,
    h: int = 13,
    t: int = 2,
) -> None:
    """A 7-segment digit, `w` x `h`, segment thickness `t`; unlit segments drawn in `off` (ghosting)."""
    lit = SEGMENTS.get(ch, "")
    mid = y + (h - t) // 2
    segs = {
        "a": (x + 1, y, w - 2, t),
        "d": (x + 1, y + h - t, w - 2, t),
        "g": (x + 1, mid, w - 2, t),
        "f": (x, y + 1, t, mid - y),
        "b": (x + w - t, y + 1, t, mid - y),
        "e": (x, mid + 1, t, y + h - mid - 2),
        "c": (x + w - t, mid + 1, t, y + h - mid - 2),
    }
    for name, (sx, sy, sw, sh) in segs.items():
        f.rect(sx, sy, sw, sh, on if name in lit else off)


WORDS_H = ["TWELVE", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN"]


def word_time(now: datetime) -> list[str]:
    m = (now.minute + 2) // 5 * 5
    h = now.hour % 12
    if m >= 35:
        h = (h + 1) % 12
    hour = WORDS_H[h]
    phrases = {
        0: [hour, "O'CLOCK"],
        5: ["FIVE", "PAST", hour],
        10: ["TEN", "PAST", hour],
        15: ["QUARTER", "PAST", hour],
        20: ["TWENTY", "PAST", hour],
        25: ["25", "PAST", hour],
        30: ["HALF", "PAST", hour],
        35: ["25", "TO", hour],
        40: ["TWENTY", "TO", hour],
        45: ["QUARTER", "TO", hour],
        50: ["TEN", "TO", hour],
        55: ["FIVE", "TO", hour],
        60: [hour, "O'CLOCK"],
    }
    return phrases[m]
