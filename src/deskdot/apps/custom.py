"""Custom: renders apps pushed over HTTP (`POST /api/custom/{name}`, AWTRIX 3 compatible subset).

Layout follows the "icon + one value" idiom: the icon sits centred in the top half, the value below it in
`small` type (scrolling when it doesn't fit), and an optional progress bar on the bottom rows. With no icon
the value is centred (short) or wrapped (long). Pushed apps join the playlist on their own while fresh; this
app can also be pinned to one of them by name.

Static screens stream at 1 fps (deduped, so they cost nothing); scrolling or rainbow text is a clip whose
length is exactly one marquee pass, so the loop is seamless and the panel plays it natively.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Clip, register
from ..gfx import Frame, Sprite, hsv, scale, to_rgb
from ..gfx.font import measure, wrap
from ..gfx.icons import ICONS, draw_icon
from ._kit import INFO, setup

SPEED = 10.0  # px/s: exactly 1 px per clip frame at clip_fps (14 fps was above the panel's verified 10)
GAP = 12
HOLD = 1.2


class CustomSettings(AppSettings):
    name: str = Field(
        "",
        max_length=32,
        title="Pushed app",
        description="Name used in POST /api/custom/{name}. Empty = the first pushed app.",
    )


def _period(text: str, box_w: int, font: str) -> float:
    w = measure(text, font)
    return HOLD + (w + GAP) / SPEED if w > box_w else 0.0


@register
class Custom(App):
    id = "custom"
    name = "Custom"
    description = "Screens pushed by other tools (Home Assistant, scripts) via POST /api/custom/{name}."
    icon = "webhook"
    category = "productivity"
    Settings = CustomSettings
    fps = 1.0
    clip_fps = 10.0
    clip_colors = 64

    def __init__(self, ctx: Any, settings: AppSettings) -> None:
        super().__init__(ctx, settings)
        self._sprites: dict[Any, Sprite] = {}

    # ------------------------------------------------------------- data
    def entry(self) -> dict[str, Any] | None:
        apps = self.ctx.provider("custom").value or {}
        name = self.settings.name
        if name:
            return apps.get(name)
        return next(iter(apps.values()), None)

    def relevant(self) -> bool:
        return self.entry() is not None

    @staticmethod
    def _text(d: dict[str, Any]) -> str:
        text = str(d.get("text") or "")
        return text if d.get("textCase") == 2 else text.upper()

    def _plan(self, d: dict[str, Any]) -> dict[str, Any]:
        """Layout decisions shared by render / kind / clip length."""
        text = self._text(d)
        has_icon = bool(d.get("icon") or d.get("rows"))
        has_bar = int(d.get("progress", -1)) >= 0
        if has_icon:
            font, scroll = "small", measure(text, "small") > 30
        else:
            lines = wrap(text, 30, "tiny")
            short = measure(text, "small") <= 30
            font = "small" if short else "tiny"
            scroll = not short and len(lines) > (3 if has_bar else 4)
            if scroll:
                font = "small"
        return {"text": text, "icon": has_icon, "bar": has_bar, "font": font, "scroll": scroll}

    # ----------------------------------------------------------- output
    def kind(self) -> str:  # type: ignore[override]
        d = self.entry()
        if d is None:
            return "stream"
        p = self._plan(d)
        return "clip" if p["scroll"] or d.get("rainbow") else "stream"

    def clip_key(self) -> str:
        d = self.entry() or {}
        keep = {k: v for k, v in d.items() if k not in ("pushed", "expires", "lifetime", "duration")}
        return json.dumps([self.settings.name, keep], sort_keys=True, default=str)

    def clip_frames(self) -> Clip:
        d = self.entry() or {}
        p = self._plan(d)
        period = _period(p["text"], 30, "small") if p["scroll"] else 0.0
        seconds = period or 2.0  # a rainbow on still text loops every 2 s
        # 1.2 s hold + 1 frame per px; text frames cost ~100 B, so 360 frames stay under the 40 KB GIF budget
        n = max(2, min(360, round(seconds * self.clip_fps)))
        dt = seconds / n
        frames = []
        for i in range(n):
            f = Frame()
            self.render(f, i * dt)
            frames.append(f)
        return Clip(frames, [round(dt * 1000)] * n)

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        d = self.entry()
        if d is None:
            self._empty(f)
            return
        p = self._plan(d)
        color = to_rgb(d.get("color") or "#ffffff")
        rainbow = bool(d.get("rainbow"))
        period = _period(p["text"], 30, "small") if p["scroll"] else 0.0
        push = int(d.get("pushIcon", 0))
        show_icon = p["icon"]
        icon_dx = 0
        if show_icon and p["scroll"] and push and period:
            off = self._offset(t % period)
            if push == 2 and t >= period:
                show_icon = False  # scrolled away once, stays away
            else:
                icon_dx = -off
        if p["bar"]:
            self._bar(f, d)
        if show_icon:
            ty = 19 if p["bar"] else 21
            self._icon(f, d, icon_dx, 1 if p["bar"] else 2)
            self._line(f, p["text"], ty, t, period, color, rainbow)
        elif p["scroll"] or p["font"] == "small":
            y = 10 if p["bar"] else 12
            self._line(f, p["text"], y, t, period, color, rainbow)
        else:
            lines = wrap(p["text"], 30, "tiny")[: 3 if p["bar"] else 4]
            area = 27 if p["bar"] else 32
            y0 = max(1, (area - (len(lines) * 7 - 2)) // 2)
            for i, ln in enumerate(lines):
                self._chars(
                    f, (32 - measure(ln, "tiny")) // 2, y0 + i * 7, ln, "tiny", color, rainbow, t, i * 9
                )

    @staticmethod
    def _offset(phase: float) -> int:
        # the epsilon keeps float error (e.g. 0.99999) from repeating a pixel and then skipping one
        return 0 if phase < HOLD else int((phase - HOLD) * SPEED + 1e-6)

    def _line(self, f: Frame, text: str, y: int, t: float, period: float, color: Any, rainbow: bool) -> None:
        if not period:
            self._chars(f, (32 - measure(text, "small")) // 2, y, text, "small", color, rainbow, t)
            return
        x = 1 - self._offset(t % period)
        w = measure(text, "small")
        self._chars(f, x, y, text, "small", color, rainbow, t, clip=(1, y, 30, y + 6))
        self._chars(f, x + w + GAP, y, text, "small", color, rainbow, t, clip=(1, y, 30, y + 6))

    @staticmethod
    def _chars(
        f: Frame,
        x: int,
        y: int,
        text: str,
        font: str,
        color: Any,
        rainbow: bool,
        t: float,
        seed: int = 0,
        clip: tuple[int, int, int, int] | None = None,
    ) -> None:
        if not rainbow:
            f.text(x, y, text, color, font=font, clip=clip)
            return
        for i, ch in enumerate(text):
            c = hsv((i + seed) / 12 - t * 0.5)
            x = f.text(x, y, ch, c, font=font, clip=clip) + 1

    def _icon(self, f: Frame, d: dict[str, Any], dx: int, top: int) -> None:
        color = to_rgb(d.get("color") or "#ffffff")
        if d.get("rows"):
            rows = d["rows"]
            w = max((len(r) for r in rows), default=0)
            h = len(rows)
            k = 2 if w <= 8 and h <= 8 else 1
            key = (tuple(rows), tuple(sorted((d.get("palette") or {}).items())))
            sp = self._sprites.get(key)
            if sp is None:
                self._sprites = {key: Sprite.parse(rows, dict(d.get("palette") or {}))}  # keep one
                sp = self._sprites[key]
            x0 = (32 - w * k) // 2 + dx
            y0 = top + (16 - h * k) // 2
            if k == 1:
                f.sprite(sp, x0, y0)
            else:
                for yy in range(h):
                    for xx in range(w):
                        if sp.mask[yy, xx]:
                            f.rect(x0 + xx * k, y0 + yy * k, k, k, tuple(int(v) for v in sp.px[yy, xx]))
            return
        name = d.get("icon")
        if name in ICONS:
            rows = ICONS[name]
            w, h = len(rows[0]) * 2, len(rows) * 2
            draw_icon(f, name, (32 - w) // 2 + dx, top + (16 - h) // 2, color, 2)

    @staticmethod
    def _bar(f: Frame, d: dict[str, Any]) -> None:
        pct = max(0, min(100, int(d.get("progress", 0))))
        fg = to_rgb(d.get("progressC") or "#00ff8c")
        bg = to_rgb(d.get("progressBC")) if d.get("progressBC") else scale(fg, 0.14)
        f.bar(1, 29, 30, 2, pct / 100, fg, track=bg)

    def _empty(self, f: Frame) -> None:
        setup(f, "CUSTOM", self.settings.name.upper() or "PUSH APP", INFO, icon="bolt")

    def status(self) -> dict[str, Any]:
        d = self.entry()
        if d is None:
            return {"pushed": 0}
        n = len(self.ctx.provider("custom").value or {})
        return {"text": str(d.get("text", ""))[:40], "pushed": n}
