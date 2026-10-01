"""Active App — the app you're using right now: its real icon, a matching animation, and focus stats."""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
from PIL import Image
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, register
from ..gfx import Frame, hsv, mix, scale
from ..gfx.color import calibrate
from ..gfx.font import draw_marquee, fit, measure
from ._kit import loading, offline
from .timer import smooth_bar

Icon = tuple[np.ndarray, np.ndarray]  # (rgb, mask)


def icon_rgb(rgba: np.ndarray | None, size: int) -> Icon | None:
    """Resize an RGBA icon to `size`, LED-calibrate it, and return (rgb, mask)."""
    if rgba is None:
        return None
    img = Image.fromarray(rgba, "RGBA")
    if size != img.width:
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    arr = np.asarray(img)
    rgb = np.asarray(calibrate(Image.fromarray(np.ascontiguousarray(arr[..., :3]), "RGB"), "natural"))
    return rgb.copy(), arr[..., 3] > 90


def accent_of(ic: Icon | None) -> tuple[int, int, int]:
    """The icon's dominant saturated colour, normalised to full LED brightness."""
    if ic is None:
        return (0, 200, 255)
    rgb, mask = ic
    px = rgb[mask].astype(np.float32)
    if len(px) == 0:
        return (0, 200, 255)
    mx, mn = px.max(axis=1), px.min(axis=1)
    sat = (mx - mn) / (mx + 1)
    pick = px[sat > 0.35] if (sat > 0.35).sum() > 8 else px
    c = pick.mean(axis=0)
    c = c / max(float(c.max()), 1.0) * 255
    return int(c[0]), int(c[1]), int(c[2])


def fmt_dur(s: float) -> str:
    m = int(s // 60)
    return f"{m // 60}H{m % 60:02d}" if m >= 60 else f"{m}M"


def fmt_short(s: float) -> str:
    """At most three glyphs for the focus rows: '15M', '90M', '2H', '12H' (never a cut-off '1H3')."""
    m = int(s // 60)
    return f"{m}M" if m < 100 else f"{m // 60}H"


FOCUS_BLOCK = 25 * 60  # the title layout's bar fills over one 25-minute focus block in the current app


class ActiveAppSettings(AppSettings):
    layout: str = Choice("icon", {"icon": "Icon", "title": "Title", "focus": "Focus"}, title="Layout")
    take_over: bool = Field(False, title="Pop up when you switch apps", description="In the playlist")
    popup_seconds: int = Field(5, ge=2, le=30, title="Pop-up seconds")


@register
class ActiveApp(App):
    id = "activeapp"
    name = "Active App"
    description = (
        "The app you're using right now — its real icon, a matching animation and today's focus time."
    )
    icon = "app-window"
    category = "productivity"
    Settings = ActiveAppSettings
    fps = 8.0
    uses = ("window",)

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._icons: dict[tuple[str, int], Icon | None] = {}
        self._proc: str | None = None
        self._switched = 0.0

    # ---------------------------------------------------------------- focus
    def _track(self, w: dict[str, Any]) -> None:
        if w["proc"] != self._proc:
            first = self._proc is None
            self._proc, self._switched = w["proc"], 0.0 if first else time.monotonic()

    def watches_focus(self) -> bool:
        return self.settings.take_over

    def wants_focus(self) -> bool:
        w = self.ctx.provider("window").value
        if not w:
            return False
        self._track(w)
        return self._switched > 0 and time.monotonic() - self._switched < self.settings.popup_seconds

    def get_icon(self, exe: str, size: int) -> Icon | None:
        key = (exe, size)
        if key not in self._icons:
            self._icons[key] = icon_rgb(self.ctx.provider("window").icon(exe), size) if exe else None
        return self._icons[key]

    def status(self) -> dict[str, Any]:
        w = self.ctx.provider("window").value or {}
        return {"app": w.get("name"), "for": fmt_dur(time.time() - w["since"]) if w.get("since") else None}

    # ---------------------------------------------------------------- render
    def render(self, f: Frame, t: float) -> None:
        p = self.ctx.provider("window")
        w = p.value
        if not w:
            (offline(f, "WINDOW", "N/A") if p.error else loading(f, t, "APP"))
            return
        self._track(w)
        {"icon": self.lay_icon, "title": self.lay_title, "focus": self.lay_focus}[self.settings.layout](
            f, t, w
        )

    def _blit_icon(self, f: Frame, w: dict[str, Any], size: int, x: int, y: int) -> tuple[int, int, int]:
        ic = self.get_icon(w["exe"], size)
        if ic is None:  # no icon: a monogram tile
            f.rect(x, y, size, size, (50, 50, 72))  # visible through the panel gamma (was near black)
            f.text(
                x + (size - 5) // 2,
                y + (size - 7) // 2,
                (w["name"][:1] or "?"),
                (255, 255, 255),
                font="small",
            )
            return (0, 200, 255)
        f.blit(ic[0], x, y, ic[1])
        return accent_of(ic)

    def lay_icon(self, f: Frame, t: float, w: dict[str, Any]) -> None:
        since_switch = time.monotonic() - self._switched if self._switched else 99.0
        size = 22
        # switch-in: the icon pops from small to full size with a flash ring
        if since_switch < 0.5:
            size = max(8, round(22 * (0.4 + 0.6 * since_switch / 0.5)))
        x, y = 16 - size // 2, 12 - size // 2
        acc = self._blit_icon(f, w, size, x, y)
        if since_switch < 0.6:
            r = round(4 + since_switch * 26)
            f.circle(16, 12, r, scale(acc, max(0.0, 1 - since_switch / 0.6)), fill=False)
        self._animate(f, t, w["category"], acc)
        f.text_center(26, fit(w["name"].upper(), 30), mix(acc, (255, 255, 255), 0.45))

    def _animate(self, f: Frame, t: float, cat: str, acc: tuple[int, int, int]) -> None:
        """A per-category micro-animation in the space around the icon."""
        if cat == "code":  # blinking cursor + keystrokes
            if int(t * 2) % 2 == 0:
                f.rect(28, 19, 2, 4, acc)
            for i in range(3):
                if (int(t * 6) + i) % 3 == 0:
                    f.set(2 + i * 2, 21, mix(acc, (255, 255, 255), 0.5))
        elif cat == "browser":  # loading orbit
            for i in range(3):
                a = t * 4 - i * 0.5
                f.set(round(16 + math.cos(a) * 14), round(12 + math.sin(a) * 12), scale(acc, 1 - i * 0.3))
        elif cat == "music":  # side equalisers
            for side, x0 in ((0, 1), (1, 28)):
                for b in range(2):
                    h = 2 + int((math.sin(t * 7 + b * 1.7 + side) * 0.5 + 0.5) * 9)
                    f.rect(x0 + b * 2, 22 - h, 1, h, hsv(0.33 + 0.1 * b))
        elif cat == "chat":  # typing bubble
            f.rect(23, 1, 9, 5, (40, 40, 56))
            for i in range(3):
                on = int(t * 4) % 3 == i
                f.set(25 + i * 2, 3, acc if on else (90, 90, 110))
        elif cat == "game":  # twinkling stars
            for i, (sx, sy) in enumerate(((2, 3), (29, 5), (3, 20), (28, 19))):
                k = 0.5 + 0.5 * math.sin(t * 5 + i * 1.3)
                f.set(sx, sy, scale((255, 255, 200), k))
        elif cat == "design":  # palette dots cycling
            for i in range(4):
                f.set(4 + i * 8, 23, hsv(t * 0.3 + i / 4))
        else:  # gentle breathing corners
            k = 0.3 + 0.3 * math.sin(t * 2)
            for cx, cy in ((1, 1), (30, 1)):
                f.set(cx, cy, scale(acc, k))

    def lay_title(self, f: Frame, t: float, w: dict[str, Any]) -> None:
        acc = self._blit_icon(f, w, 14, 1, 1)
        f.text(17, 2, fit(w["name"].upper(), 14), acc)
        f.text(17, 9, fmt_dur(time.time() - w["since"]), (255, 255, 255))
        f.hline(0, 17, 32, (24, 24, 34))
        title = w["title"] or w["name"]
        draw_marquee(f, title.upper(), t, 1, 20, 30, (220, 220, 230), speed=self.fps)  # 1 px per frame
        block = ((time.time() - w["since"]) % FOCUS_BLOCK) / FOCUS_BLOCK
        smooth_bar(f, 1, 28, 30, 2, block, scale(acc, 0.6), track=(30, 30, 44))

    def lay_focus(self, f: Frame, t: float, w: dict[str, Any]) -> None:
        top = w.get("top") or []
        total = sum(a["seconds"] for a in top) or 1
        f.text(1, 1, "DAY", (140, 140, 160))
        f.text_right(30, 1, fmt_dur(total), (255, 255, 255))
        for i, a in enumerate(top[:4]):
            y = 8 + i * 6
            ic = self.get_icon(a.get("exe", ""), 5)
            col = accent_of(ic) if ic else hsv(i * 0.17 + 0.5)
            if ic:
                f.blit(ic[0], 1, y, ic[1])
            else:
                f.rect(1, y, 5, 5, scale(col, 0.8))
            dur = fmt_short(a["seconds"])
            f.text_right(30, y, dur, (200, 200, 210))
            bw = 30 - measure(dur) - 2 - 8 + 1  # the bar ends 2 px before the time, never under it
            smooth_bar(
                f, 8, y + 1, bw, 3, a["seconds"] / top[0]["seconds"] if top else 0, col, track=(30, 30, 44)
            )
