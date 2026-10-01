"""Text — messages auto-fitted, smoothly scrolling, or animated like Spotify lyrics."""

from __future__ import annotations

import math

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Color, Kind, register
from ..gfx import Frame, hsv, mix, scale
from ..gfx.font import FONTS, measure
from .daily import wrap_text


class TextSettings(AppSettings):
    text: str = Field("HELLO WORLD", max_length=500, title="Text")
    font: str = Choice("auto", {"auto": "Auto fit", "small": "Small (7px)", "tiny": "Tiny (5px)"})
    mode: str = Choice(
        "auto",
        {
            "auto": "Auto (Lyrics)",
            "lyrics": "Spotify Lyrics (Vertical)",
            "scroll": "Marquee (Horizontal)",
            "static": "Static (Wrap)",
        },
        title="Mode",
    )
    color: Color = Field("#ffffff", title="Colour")
    effect: str = Choice("solid", {"solid": "Solid", "rainbow": "Rainbow", "gradient": "Gradient"})
    color2: Color = Field("#ff00be", title="Gradient end")
    frame: str = Choice(
        "none", {"none": "None", "underline": "Underline", "border": "Border", "glow": "Glow bar"}
    )
    speed: int = Field(18, ge=4, le=40, title="Scroll speed (px/s)")


@register
class Text(App):
    id = "text"
    name = "Text"
    description = "Messages, auto-fitted, smoothly scrolling, or flowing like Spotify lyrics."
    icon = "type"
    category = "creative"
    Settings = TextSettings
    fps = 1.0

    # ------------------------------------------------------------- layout
    def _layout(self) -> tuple[str, list[str], str]:
        s = self.settings
        text = " ".join(s.text.split()) or " "
        fonts = ["small", "tiny"] if s.font == "auto" else [s.font]

        if s.mode == "scroll":
            fnt = "small" if s.font != "tiny" else "tiny"
            return fnt, [text], "marquee"

        if s.mode == "static":
            for font in fonts:
                lines = wrap_text(text, 30, font)
                h = FONTS[font].height
                if len(lines) * (h + 2) - 2 <= 30:
                    return font, lines, "static"
            return "tiny", wrap_text(text, 30, "tiny")[:5], "static"

        if s.mode == "auto":
            for font in fonts:
                lines = wrap_text(text, 30, font)
                h = FONTS[font].height
                if len(lines) * (h + 2) - 2 <= 30 and len(lines) <= 2:
                    return font, lines, "static"

        # Multi-line / long text or s.mode == "lyrics": Spotify lyrics vertical flow
        chosen_font = "tiny"
        if s.font == "small" or (
            s.font == "auto"
            and all(measure(w, "small") <= 30 for w in text.split())
            and len(text.split()) <= 4
        ):
            chosen_font = "small"
        lines = wrap_text(text, 30, chosen_font)
        return chosen_font, lines, "lyrics"

    def _animated(self) -> bool:
        return self.settings.effect == "rainbow" or self.settings.frame == "glow"

    def kind(self) -> Kind:
        _, _, mode = self._layout()
        return "clip" if mode in ("marquee", "lyrics") or self._animated() else "stream"

    def _marquee_pacing(self, travel: int) -> tuple[int, int]:
        """(px per frame, frame ms) for a marquee: whole-pixel steps at an even rate, never faster than
        10 frames/s (the fastest GIF rate verified on the panel), at most 160 frames per loop."""
        speed = self.settings.speed
        step = max(1, math.ceil(speed / 10), math.ceil(travel / 160))
        return step, round(1000 * step / speed)

    def _loop_seconds(self) -> float:
        """Length of the baked loop, so colour cycles and pulses can repeat a whole number of times in it."""
        font, lines, mode = self._layout()
        if mode == "marquee":
            travel = measure(lines[0], font) + 32
            step, ms = self._marquee_pacing(travel)
            return math.ceil(travel / step) * ms / 1000
        if mode == "lyrics":
            return self._lyrics_cycle(len(lines))
        return 4.0

    def _lyrics_cycle(self, n: int) -> float:
        dwell = max(1.2, min(3.0, 26.0 / max(6, self.settings.speed)))
        return n * dwell + 1.2

    def _rate(self, per_second: float) -> float:
        """`per_second` cycles/s, rounded to a whole number of cycles per loop."""
        loop = self._loop_seconds()
        return max(1, round(per_second * loop)) / loop

    def _color(self, x: int, t: float) -> tuple[int, int, int]:
        s = self.settings
        if s.effect == "rainbow":
            return hsv(x / 40 + t * self._rate(0.25))
        if s.effect == "gradient":
            return mix(s.color, s.color2, x / 31)
        return mix(s.color, s.color, 0)

    def _paint_line(
        self,
        f: Frame,
        x: int,
        y: int,
        line: str,
        font: str,
        t: float,
        dim: bool = False,
        spacing: int = 1,
    ) -> None:
        if self.settings.effect == "solid":
            col = self.settings.color
            if dim:
                col = scale(col, 0.35)
            f.text(x, y, line, col, font=font, spacing=spacing)
            return
        cur = x
        for ch in line:
            c = self._color(cur, t)
            if dim:
                c = scale(c, 0.35)
            f.text(cur, y, ch, c, font=font, spacing=spacing)
            cur += measure(ch, font, spacing=spacing) + spacing

    def _decor(self, f: Frame, t: float) -> None:
        s = self.settings
        c = scale(s.color if s.effect == "solid" else s.color2, 0.6)
        if s.frame == "border":
            f.rect(0, 0, 32, 32, c, fill=False)
        elif s.frame == "underline":
            f.hline(4, 29, 24, c)
        elif s.frame == "glow":
            k = 0.5 + 0.5 * math.sin(t * math.tau * self._rate(1 / math.pi))
            f.hline(0, 0, 32, scale(c, 0.4 + 0.6 * k))
            f.hline(0, 31, 32, scale(c, 0.4 + 0.6 * (1 - k)))

    def _render_lyrics(self, f: Frame, lines: list[str], font: str, t: float) -> None:
        N = len(lines)
        if N == 0:
            return
        h = FONTS[font].height
        pitch = h + (3 if font == "small" else 2)
        dwell = max(1.2, min(3.0, 26.0 / max(6, self.settings.speed)))
        cycle = self._lyrics_cycle(N)
        tt = t % cycle
        k = min(N - 1, int(tt / dwell))
        since = tt - k * dwell

        p_ease = min(1.0, since / 0.35)
        ease = 1.0 - (1.0 - p_ease) ** 3

        top = 4 if self.settings.frame == "none" else 6
        bot = 32 - h - (4 if self.settings.frame == "none" else 6)

        max_vis = max(1, (bot - top) // pitch + 1)
        if max_vis >= N:
            scroll = 0.0
        else:
            scroll_target = float(max(0, min(N - max_vis, k - 1)))
            scroll_prev = float(max(0, min(N - max_vis, (k - 1) - 1)))
            scroll = scroll_target if k <= 1 else scroll_prev + (scroll_target - scroll_prev) * ease

        for j, ln in enumerate(lines):
            yj = round(top + (j - scroll) * pitch)
            if yj > 31 or yj + h <= 0:
                continue
            is_active = j == k
            w = measure(ln, font)
            sp = 1
            if w > 30 and font == "tiny" and measure(ln, font, spacing=0) <= 32:
                w = measure(ln, font, spacing=0)
                sp = 0
            x = (32 - w) // 2
            self._paint_line(f, x, yj, ln, font, t, dim=(not is_active), spacing=sp)

    def render(self, f: Frame, t: float) -> None:
        font, lines, mode = self._layout()
        h = FONTS[font].height
        if mode == "marquee":
            w = measure(lines[0], font)
            step, _ = self._marquee_pacing(w + 32)
            lap = math.ceil((w + 32) / step) * step  # a whole number of steps, so the loop closes exactly
            x = 32 - int(round(t * self.settings.speed, 6)) % lap
            self._paint_line(f, x, (32 - h) // 2, lines[0], font, t)
        elif mode == "lyrics":
            self._render_lyrics(f, lines, font, t)
        else:
            total = len(lines) * (h + 2) - 2
            y = (32 - total) // 2
            for ln in lines:
                w = measure(ln, font)
                sp = 1
                if w > 30 and font == "tiny" and measure(ln, font, spacing=0) <= 32:
                    w = measure(ln, font, spacing=0)
                    sp = 0
                self._paint_line(f, (32 - w) // 2, y, ln, font, t, spacing=sp)
                y += h + 2
        self._decor(f, t)

    def clip_frames(self) -> Clip:
        font, lines, mode = self._layout()
        if mode == "marquee":
            travel = measure(lines[0], font) + 32
            step, ms = self._marquee_pacing(travel)
            n = math.ceil(travel / step)
            frames = []
            for i in range(n):
                f = Frame()
                self.render(f, i * step / self.settings.speed)
                frames.append(f)
            return Clip(frames, [ms] * n)
        elif mode == "lyrics":
            cycle = self._lyrics_cycle(len(lines))
            fps = 8.0
            n = min(160, max(8, round(cycle * fps)))
            dt = cycle / n
            ms = round(dt * 1000)
            frames = []
            for i in range(n):
                f = Frame()
                self.render(f, i * dt)
                frames.append(f)
            return Clip(frames, [ms] * n)
        elif self._animated():  # a static layout with a rainbow / glow: one 4 s loop at 10 fps
            n = 40
            frames = []
            for i in range(n):
                f = Frame()
                self.render(f, i * 0.1)
                frames.append(f)
            return Clip(frames, [100] * n)
        else:
            f = Frame()
            self.render(f, 0.0)
            return Clip([f], [1000])
