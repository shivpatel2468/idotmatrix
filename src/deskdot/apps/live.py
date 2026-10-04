"""Live-capture apps: audio Visualizer (system sound), Screen Mirror and Camera Mirror."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pydantic import Field

from ..engine.app import App, AppSettings, Choice, Color, register
from ..gfx import Frame, hsv, mix, scale
from ..gfx.adjust import ImageControls
from ..platforms import DESKTOP, FEATURES
from ._kit import loading, offline, unsupported

FALL = 1.2  # bars fall at most this share of full height per second: a smooth decay, not a drop
PEAK_HOLD = 0.35  # seconds a peak dot hangs before it falls
PEAK_FALL = 0.6
LEVELS = 4  # sub-pixel steps for the top pixel of a bar (keeps the colour count small)


class VisualizerSettings(AppSettings):
    style: str = Choice(
        "bars",
        {
            "bars": "Spectrum bars",
            "mirror": "Mirrored",
            "radial": "Radial burst",
            "wave": "Waveform",
            "fire": "Spectrum fire",
            "rings": "Pulse rings",
        },
    )
    palette: str = Choice("rainbow", {"rainbow": "Rainbow", "heat": "Heat", "mono": "Single colour"})
    color: Color = Field("#00ff8c", title="Colour (single-colour palette)")
    peaks: bool = Field(True, title="Peak dots")
    gain: float = Field(1.0, ge=0.3, le=3.0, title="Sensitivity")


@register
class Visualizer(App):
    id = "visualizer"
    name = "Visualizer"
    description = "Reacts to whatever your PC is playing — Spotify, YouTube, games. No mic needed."
    icon = "audio-lines"
    category = "media"
    Settings = VisualizerSettings
    fps = 12.0
    uses = ("audio",)
    # sound capture (soundcard); in the web app the page's mic / shared-tab sound (providers/webmedia.py); the
    # Android app can't capture other apps' audio
    platforms = (*DESKTOP, "web")

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._lv: np.ndarray | None = None  # displayed band levels (smoothed)
        self._pk: np.ndarray | None = None
        self._pk_age: np.ndarray | None = None
        self._t: float | None = None

    def _smooth(self, bands: np.ndarray, peaks: np.ndarray, t: float) -> tuple[np.ndarray, np.ndarray]:
        """Instant attack, even fall. The capture already decays, but between 12 fps frames a bar could
        still drop 10 rows at once; here it glides down at `FALL` and peaks hang, then drift down."""
        dt = None if self._t is None else t - self._t
        self._t = t
        if self._lv is None or self._lv.shape != bands.shape or dt is None or not 0 < dt < 0.5:
            self._lv, self._pk = bands.copy(), np.maximum(bands, peaks)
            self._pk_age = np.zeros_like(bands)
            return self._lv, self._pk
        assert self._pk is not None and self._pk_age is not None
        self._lv = np.maximum(bands, self._lv - FALL * dt)
        top = np.maximum(self._lv, peaks)
        fresh = top >= self._pk
        self._pk_age = np.where(fresh, 0.0, self._pk_age + dt)
        falling = np.where(self._pk_age > PEAK_HOLD, self._pk - PEAK_FALL * dt, self._pk)
        self._pk = np.where(fresh, top, np.maximum(falling, self._lv))
        return self._lv, self._pk

    def _column(self, f: Frame, x: int, base: int, h: float, color: Any, up: bool = True) -> None:
        """A bar of fractional height `h` px from row `base`; the top pixel lights in proportion."""
        n = int(h)
        for k in range(n):
            f.set(x, base - k if up else base + k, color(k))
        part = round((h - n) * LEVELS) / LEVELS
        if part > 0:
            f.set(x, base - n if up else base + n, scale(color(n), part))

    def _col(self, i: float, v: float) -> tuple[int, int, int]:
        s = self.settings
        if s.palette == "heat":
            return mix((255, 30, 0), (255, 230, 60), v)
        if s.palette == "mono":
            return scale(s.color, 0.35 + 0.65 * v)
        return hsv(0.66 - 0.66 * i)

    def render(self, f: Frame, t: float) -> None:
        p = self.ctx.provider("audio")
        d = p.value
        if not d:
            if not self.supported_here():
                unsupported(f, "AUDIO")
            else:
                (offline(f, "AUDIO", "NO DEVICE") if p.error else loading(f, t, "AUDIO"))
            return
        s = self.settings
        bands = np.clip(np.asarray(d["bands"], np.float32) * s.gain, 0, 1)
        peaks = np.clip(np.asarray(d["peaks"], np.float32) * s.gain, 0, 1)
        bands, peaks = self._smooth(bands, peaks, t)
        getattr(self, f"st_{s.style}")(f, t, bands, peaks, d)

    def st_bars(self, f: Frame, t: float, b: np.ndarray, pk: np.ndarray, d: dict[str, Any]) -> None:
        for i, v in enumerate(b):
            h = float(v) * 31
            self._column(f, i, 31, h, lambda k, i=i: self._col(i / 31, k / 31))
            if self.settings.peaks:
                y = 31 - round(pk[i] * 31)
                if y < 31 - int(h + 0.999):  # above the bar, never on top of its lit pixels
                    f.set(i, y, (255, 255, 255))

    def st_mirror(self, f: Frame, t: float, b: np.ndarray, pk: np.ndarray, d: dict[str, Any]) -> None:
        half = b[::2]  # 16 bands, mirrored left/right
        for i, v in enumerate(half):
            h = float(v) * 15
            for x in (15 - i, 16 + i):
                self._column(f, x, 15, h, lambda k, i=i: self._col(i / 15, k / 15))
                self._column(f, x, 16, h, lambda k, i=i: scale(self._col(i / 15, k / 15), 0.55), up=False)

    def st_radial(self, f: Frame, t: float, b: np.ndarray, pk: np.ndarray, d: dict[str, Any]) -> None:
        bass = float(b[:4].mean())
        f.circle(15, 15, round(2 + bass * 4), self._col(0.0, bass))
        for i, v in enumerate(b):
            a = i / len(b) * math.tau + t * 0.3
            ln = float(v) * 10
            for r in range(6, 6 + int(ln) + 1):
                k = min(1.0, 6 + ln - r)  # the ray's tip dims with the remainder: it grows smoothly
                if k > 0:
                    c = scale(self._col(i / 31, r / 16), round(k * LEVELS) / LEVELS)
                    f.set(round(15.5 + math.cos(a) * r), round(15.5 + math.sin(a) * r), c)

    def st_wave(self, f: Frame, t: float, b: np.ndarray, pk: np.ndarray, d: dict[str, Any]) -> None:
        w = np.asarray(d["wave"])
        amp = max(0.02, float(np.abs(w).max()))
        pts = [
            (x, round(15.5 - w[x] / amp * 12 * min(1.0, d["level"] * 20 * self.settings.gain)))
            for x in range(32)
        ]
        f.polyline(pts, self._col(0.3, 1.0))
        f.hline(0, 16, 32, (20, 20, 30))

    def st_fire(self, f: Frame, t: float, b: np.ndarray, pk: np.ndarray, d: dict[str, Any]) -> None:
        for i, v in enumerate(b):
            h = float(v) * 31
            self._column(
                f, i, 31, h, lambda k, v=v, h=h: mix((255, 40, 0), (255, 240, 120), k / max(1.0, h) * v)
            )

    def st_rings(self, f: Frame, t: float, b: np.ndarray, pk: np.ndarray, d: dict[str, Any]) -> None:
        for j, part in enumerate((b[:6], b[6:16], b[16:])):
            v = float(part.mean())
            f.circle(15, 15, round(3 + j * 5 + v * 4), self._col(j / 2, v), fill=False)

    def status(self) -> dict[str, Any]:
        d = self.ctx.provider("audio").value or {}
        return {"level": round(float(d.get("level", 0)) * 100, 1)}


class MirrorSettings(ImageControls):
    mode: str = Choice(
        "full",
        {
            "full": "Whole screen",
            "window": "Active window",
            "cursor": "Around cursor",
            "ambilight": "Ambilight colours",
        },
        title="Source",
        # Linux has no portable window rect / cursor position: those fall back to the whole screen there
        platforms={"window": list(FEATURES["screen_window"]), "cursor": list(FEATURES["screen_window"])},
    )
    fit: str = Choice("contain", {"contain": "Fit whole screen", "cover": "Fill (crop)"})
    cursor_box: int = Field(
        96, ge=48, le=800, title="Cursor box (px)", description="Smaller = more magnified"
    )
    contrast: float = Field(1.15, ge=0.2, le=3.0, title="Contrast", json_schema_extra={"group": "Exposure"})
    black_point: int = Field(
        35,
        ge=0,
        le=60,
        title="Black point %",
        description="High = dark UIs go black",
        json_schema_extra={"group": "Exposure"},
    )


@register
class Mirror(App):
    id = "mirror"
    name = "Screen Mirror"
    description = "Your screen, a window, the area under the cursor, or ambient colours — live on the panel."
    icon = "monitor-up"
    category = "media"
    Settings = MirrorSettings
    fps = 10.0
    uses = ("screen",)
    # Linux: X11 (or GNOME's screenshot tool on Wayland); the web app: getDisplayMedia; not in the Android app
    platforms = (*DESKTOP, "web")

    def on_start(self) -> None:
        s = self.settings
        self.ctx.provider("screen").configure(s.mode, s.cursor_box, s.fit, s)

    on_settings = on_start

    def render(self, f: Frame, t: float) -> None:
        p = self.ctx.provider("screen")
        if p.value is None:
            if not self.supported_here():
                unsupported(f, "SCREEN")
            else:
                (offline(f, "SCREEN", "N/A") if p.error else loading(f, t, "SCREEN"))
            return
        f.px[:] = p.value


class CameraSettings(ImageControls):
    style: str = Choice(
        "natural",
        {
            "natural": "Natural",
            "pop": "Pop art",
            "neon": "Neon edges",
            "thermal": "Thermal",
            "mono": "1-bit ember",
        },
        title="Look",
    )
    track_face: bool = Field(True, title="Follow my face")
    flip_h: bool = Field(True, title="Mirror (selfie view)", json_schema_extra={"group": "Framing"})
    black_point: int = Field(3, ge=0, le=60, title="Black point %", json_schema_extra={"group": "Exposure"})
    camera: int = Field(0, ge=0, le=5, title="Camera index", json_schema_extra={"group": "Camera hardware"})
    # the webcam's own (hardware) controls
    hw_auto_exposure: bool = Field(
        True, title="Camera auto exposure", json_schema_extra={"group": "Camera hardware"}
    )
    hw_exposure: int = Field(
        -6,
        ge=-13,
        le=0,
        title="Camera exposure",
        description="When auto is off; lower = darker",
        json_schema_extra={"group": "Camera hardware"},
    )
    hw_gain: int = Field(
        0, ge=0, le=255, title="Camera gain (ISO)", json_schema_extra={"group": "Camera hardware"}
    )
    hw_auto_wb: bool = Field(
        True, title="Camera auto white balance", json_schema_extra={"group": "Camera hardware"}
    )
    wb_kelvin: int = Field(
        4600, ge=2800, le=6500, title="White balance (K)", json_schema_extra={"group": "Camera hardware"}
    )
    autofocus: bool = Field(True, title="Autofocus", json_schema_extra={"group": "Camera hardware"})
    focus: int = Field(0, ge=0, le=255, title="Manual focus", json_schema_extra={"group": "Camera hardware"})


@register
class Camera(App):
    id = "camera"
    name = "Camera Mirror"
    description = "Your webcam on the LEDs — follows your face, with pop-art, neon, thermal and 1-bit looks."
    icon = "camera"
    category = "media"
    Settings = CameraSettings
    fps = 10.0
    uses = ("camera",)
    # OpenCV (DirectShow / AVFoundation / V4L2); the web app: getUserMedia; not packaged in the Android app
    platforms = (*DESKTOP, "web")

    def on_start(self) -> None:
        s = self.settings
        self.ctx.provider("camera").configure(s.camera, s.style, s.track_face, s)

    on_settings = on_start

    def render(self, f: Frame, t: float) -> None:
        p = self.ctx.provider("camera")
        if p.value is None and not self.supported_here():
            unsupported(f, "CAMERA")
            return
        if p.value is None:
            (
                offline(f, "CAMERA", "N/A")
                if p.error and "starting" not in p.error
                else loading(f, t, "CAMERA")
            )
            return
        f.px[:] = p.value
