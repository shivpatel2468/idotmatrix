"""Photo Frame — a slideshow of public-domain art, nature photos and animals, prepared for 32×32.

Photos come from the ``photos`` provider already smart-cropped, LANCZOS-downscaled and LED-calibrated
(once, at import). The app only composes ready arrays:

* **Still** mode streams: one frame per photo, plus a short crossfade and the optional caption intro.
* **Ken Burns** mode streams only the intro (crossfade + caption), then turns into a *clip*: the photo's
  baked zoom loop plays natively on the panel with zero Bluetooth traffic until the next photo.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import Action, App, AppSettings, Choice, Clip, Kind, register
from ..gfx import PALETTE, Frame, draw_marquee, fit, measure, scale
from ..providers.photos import SOURCES, Photo
from ._kit import loading, offline

FADE = 0.8  # crossfade seconds
MARQUEE_SPEED = 12.0
KB_FRAME_MS = 300
CAPTION_OUT = 0.5  # the scroll-once caption fades away instead of vanishing
# caption band: a short ramp from the photo into near-black behind the text (a hard edge looked cut out)
BAND = np.array([0.6, 0.32, 0.18, 0.18, 0.18, 0.18, 0.18, 0.18, 0.18], np.float32)[:, None, None]


class PhotoFrameSettings(AppSettings):
    art_met: bool = Field(True, title="Art: The Met", json_schema_extra={"group": "Sources"})
    art_cleveland: bool = Field(True, title="Art: Cleveland Museum", json_schema_extra={"group": "Sources"})
    picsum: bool = Field(False, title="Nature & random photos", json_schema_extra={"group": "Sources"})
    dogs: bool = Field(False, title="Dogs", json_schema_extra={"group": "Sources"})
    cats: bool = Field(False, title="Cats", json_schema_extra={"group": "Sources"})
    foxes: bool = Field(False, title="Foxes", json_schema_extra={"group": "Sources"})
    ducks: bool = Field(False, title="Ducks", json_schema_extra={"group": "Sources"})
    art_query: str = Field(
        "painting",
        max_length=40,
        title="Met search",
        description="What to look for in The Met's highlights, e.g. painting, landscape, flowers, cat",
        json_schema_extra={"group": "Sources"},
    )
    dog_breed: str = Field(
        "",
        max_length=40,
        title="Dog breed",
        description="Empty = any. e.g. husky, corgi, golden retriever, shiba",
        json_schema_extra={"group": "Sources"},
    )
    interval: int = Field(20, ge=5, le=600, title="Seconds per photo", json_schema_extra={"group": "Show"})
    motion: str = Choice(
        "kenburns", {"still": "Still", "kenburns": "Ken Burns"}, title="Motion", group="Show"
    )
    crossfade: bool = Field(True, title="Crossfade", json_schema_extra={"group": "Show"})
    caption: str = Choice(
        "intro",
        {"off": "Off", "intro": "Scroll once", "always": "Always"},
        title="Caption (title · artist)",
        group="Show",
    )
    framing: str = Choice(
        "smart",
        {"smart": "Smart crop", "center": "Centre crop", "fit": "Fit (letterbox)"},
        title="Framing",
        group="Image",
    )
    profile: str = Choice(
        "vibrant", {"vibrant": "Vibrant", "natural": "Natural"}, title="LED colour", group="Image"
    )

    def sources(self) -> list[str]:
        flags = {
            "met": self.art_met,
            "cleveland": self.art_cleveland,
            "picsum": self.picsum,
            "dogs": self.dogs,
            "cats": self.cats,
            "foxes": self.foxes,
            "ducks": self.ducks,
        }
        return [k for k in SOURCES if flags[k]] or ["picsum"]


def caption_text(p: Photo) -> str:
    parts = [x for x in (p.title, p.artist) if x]
    return " · ".join(parts).upper().replace("·", "-")


@register
class PhotoFrame(App):
    id = "photoframe"
    name = "Photo Frame"
    description = "A slideshow of public-domain art, nature photos, dogs, cats, foxes and ducks."
    icon = "frame"
    category = "media"
    Settings = PhotoFrameSettings
    uses = ("photos",)
    actions = (Action("next", "Next photo", "skip-forward"),)
    clip_fps = 1000 / KB_FRAME_MS

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._clock = time.monotonic
        self._cur: Photo | None = None
        self._prev: Photo | None = None
        self._prev_px: np.ndarray | None = None  # what the panel showed when the photo changed
        self._t0 = 0.0
        self._skip = False

    # ------------------------------------------------------------ provider
    def _provider(self) -> Any:
        try:
            return self.ctx.provider("photos")
        except KeyError:
            return None

    def on_start(self) -> None:
        p = self._provider()
        if p is not None:
            s = self.settings
            p.want(s.sources(), s.dog_breed, s.art_query, s.framing, s.profile)

    def on_settings(self) -> None:
        self.on_start()

    async def action(self, name: str, payload: dict[str, Any]) -> Any:
        if name != "next":
            raise KeyError(name)
        self._skip = True
        self.ctx.invalidate()
        return self.status()

    # ------------------------------------------------------------ rotation
    def _photos(self) -> list[Photo]:
        p = self._provider()
        return list((p.value if p is not None else None) or [])

    def _advance(self) -> float:
        """Pick the photo on screen; returns seconds since it appeared."""
        photos = self._photos()
        now = self._clock()
        if not photos:
            self._cur = None
            return 0.0
        seqs = [p.seq for p in photos]
        due = now - self._t0 >= self.settings.interval or self._skip
        if self._cur is None or self._cur.seq not in seqs or (due and len(photos) > 1):
            p = self._provider()
            seen = getattr(p, "_seen", set())
            nxt = next((x for x in photos if x.seq not in seen and x is not self._cur), None)
            if nxt is None:  # everything seen: keep cycling the ring
                i = seqs.index(self._cur.seq) if self._cur and self._cur.seq in seqs else -1
                nxt = photos[(i + 1) % len(photos)]
            keep = self._cur is not None and self._cur.seq in seqs
            self._prev_px = self._showing(now - self._t0) if keep else None  # before _prev changes
            self._prev = self._cur if keep else None
            self._cur = nxt
            self._t0 = now
            self._skip = False
            if p is not None and hasattr(p, "seen"):
                p.seen(nxt.seq)
        return now - self._t0

    def _clip_start(self) -> float:
        """Age at which the baked Ken Burns loop takes over (after the intro and the caption fade)."""
        fade = CAPTION_OUT if self._caption() else 0.0
        return self._intro_len() + fade

    def _kb_index(self, age: float) -> int:
        """The Ken Burns frame on the panel at `age`: frame 0 until the loop takes over, then the loop."""
        start = self._clip_start()
        assert self._cur is not None
        return 0 if age < start else int((age - start) * 1000 / KB_FRAME_MS) % len(self._cur.kb)

    def _showing(self, age: float) -> np.ndarray:
        """The current photo's pixels at `age` — the crossfade to the next photo starts from exactly this
        frame, so it never jumps back to the start of the zoom first."""
        assert self._cur is not None
        return self._cur.kb[self._kb_index(age)] if self._kb() else self._cur.still

    def _caption(self) -> str:
        return caption_text(self._cur) if self._cur and self.settings.caption != "off" else ""

    def _intro_len(self) -> float:
        n = FADE if self.settings.crossfade and self._prev is not None else 0.0
        cap = self._caption()
        if self.settings.caption in ("intro", "always") and cap:
            w = measure(cap)
            n = max(n, 1.2 + (w + 30) / MARQUEE_SPEED if w > 30 else 3.5)
        # never let the caption eat the photo: Ken Burns must get the rest of the interval
        return min(n, max(FADE, self.settings.interval * 0.6))

    @property  # type: ignore[override]
    def fps(self) -> float:  # type: ignore[override]
        if self._cur is not None and self._clock() - self._t0 < self._intro_len() + CAPTION_OUT + 0.2:
            return 12.0
        return 2.0

    # ------------------------------------------------------------ output kind
    def _kb(self) -> bool:
        return self.settings.motion == "kenburns" and self._cur is not None and bool(self._cur.kb)

    def kind(self) -> Kind:
        age = self._advance()
        if self._kb() and age >= self._clip_start():
            return "clip"
        return "stream"

    def clip_key(self) -> str:
        self._advance()
        return super().clip_key() + f"#{self._cur.seq if self._cur else 0}"

    def clip_frames(self) -> Clip:
        cur = self._cur
        if cur is None or not cur.kb:
            f = Frame()
            self.render(f, 0.0)
            return Clip([f], [1000])
        frames = []
        for px in cur.kb:
            f = Frame(px.copy())
            self._overlay_caption(f, None)
            frames.append(f)
        return Clip(frames, [KB_FRAME_MS] * len(frames))

    # ------------------------------------------------------------ render
    def render(self, f: Frame, t: float) -> None:
        age = self._advance()
        cur = self._cur
        if cur is None:
            p = self._provider()
            if p is not None and p.error:
                offline(f, "PHOTOS", "OFFLINE")
            else:
                loading(f, t, "PHOTOS", PALETTE["gold"])
            return
        base = self._showing(age)
        px = base
        if self.settings.crossfade and self._prev is not None and age < FADE:
            prev = self._prev_px if self._prev_px is not None else self._prev.still
            k = age / FADE
            px = (prev.astype(np.float32) * (1 - k) + base.astype(np.float32) * k).astype(np.uint8)
        f.px[:] = px
        self._overlay_caption(f, age)
        p = self._provider()
        if p is not None and p.error:
            f.set(0, 31, PALETTE["amber"])  # showing cached photos: stale marker

    def _overlay_caption(self, f: Frame, age: float | None) -> None:
        """Caption band: bottom rows darkened, tiny text. `age=None` = inside a baked clip (static).

        Both modes scroll the caption once during the intro. "Scroll once" then fades it away; "Always"
        keeps it as a static line (a marquee can't live inside the short baked zoom loop, and a streamed
        one at 2 fps would jump 6 px a frame).
        """
        cap = self._caption()
        mode = self.settings.caption
        if not cap:
            return
        intro = self._intro_len()
        white = PALETTE["white"]
        u = 1.0 if age is None else (age - intro) / CAPTION_OUT  # progress of the hand-over, 0..1
        if mode == "intro" and u >= 1:
            return
        band_k = 1.0 - max(0.0, u) if mode == "intro" else 1.0
        band_k = round(band_k * 4) / 4
        f.px[23:32] = (f.px[23:32].astype(np.float32) * (1 - (1 - BAND) * band_k)).astype(np.uint8)
        assert age is not None or u >= 1
        if u < 0:  # the intro: scroll once
            draw_marquee(f, cap, age, 1, 26, 30, white, speed=MARQUEE_SPEED)  # type: ignore[arg-type]
        elif u < 1:  # hand-over: the scrolling line fades out where it is ("always": the static one fades in)
            if mode == "intro" or u < 0.5:
                k = round((1 - u if mode == "intro" else 1 - 2 * u) * 4) / 4
                draw_marquee(f, cap, age, 1, 26, 30, scale(white, k), speed=MARQUEE_SPEED)  # type: ignore[arg-type]
            else:
                self._static_caption(f, cap, scale(white, round((2 * u - 1) * 4) / 4))
        else:
            self._static_caption(f, cap, white)

    @staticmethod
    def _static_caption(f: Frame, cap: str, color: tuple[int, int, int]) -> None:
        if measure(cap) <= 30:
            f.text_center(26, cap, color)
        else:
            f.text(1, 26, fit(cap, 30), color)

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        c = self._cur
        return {
            "photos": len(self._photos()),
            "source": c.source if c else None,
            "title": c.title if c else None,
            "artist": c.artist if c else None,
        }
