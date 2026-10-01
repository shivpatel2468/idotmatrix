"""Gallery — show an uploaded image or GIF. GIFs play natively on the panel."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Clip, Kind, register
from ..gfx import Frame
from ..gfx.image import import_media
from ._kit import INFO, setup


class GallerySettings(AppSettings):
    media: str = Field("", title="Media", json_schema_extra={"format": "media"})
    fit: str = Choice("contain", {"contain": "Fit", "cover": "Fill (crop)", "stretch": "Stretch"})
    profile: str = Choice(
        "auto",
        {"auto": "Auto", "vibrant": "Vibrant", "natural": "Natural", "raw": "Raw 1:1"},
        title="LED colour",
    )
    speed: float = Field(1.0, ge=0.25, le=4.0, title="Animation speed")


@register
class Gallery(App):
    id = "gallery"
    name = "Gallery"
    description = "Your uploads — photos are LED-calibrated, pixel art stays crisp."
    icon = "images"
    category = "media"
    Settings = GallerySettings
    fps = 1.0

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._key: str | None = None
        self._frames: list[Frame] = []
        self._durations: list[int] = []

    def _load(self) -> None:
        key = self.clip_key()
        if key == self._key:
            return
        self._key = key
        self._frames, self._durations = [], []
        lib = self.ctx.library
        if lib is None or not self.settings.media:
            return
        try:
            data = lib.read(self.settings.media)
        except (KeyError, OSError):
            return
        frames, durations = import_media(data, self.settings.fit, self.settings.profile)
        self._frames = frames
        self._durations = [max(20, round(d / self.settings.speed)) for d in durations]

    def kind(self) -> Kind:
        self._load()
        return "clip" if len(self._frames) > 1 else "stream"

    def clip_frames(self) -> Clip:
        self._load()
        return Clip(list(self._frames), list(self._durations))

    def render(self, f: Frame, t: float) -> None:
        self._load()
        if not self._frames:
            setup(f, "GALLERY", "UPLOAD", INFO)  # the shared "not configured" screen
            return
        f.px[:] = Clip(self._frames, self._durations).frame_at(t).px
