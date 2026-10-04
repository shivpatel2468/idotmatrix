"""Camera, screen and sound in the web app (docs/WEB_APP.md): the browser's media APIs instead of the OS.

In a browser tab the engine (a Web Worker under Pyodide) can't open a webcam, grab the screen or record sound; only
the page can, and only after the user allows it (`getUserMedia` / `getDisplayMedia`). So these providers *ask* the
page for a stream while an app holds them and are fed by it:

    engine → page   want(kind, opts) / stop(kind)        kind: "camera" | "screen" | "audio"
    page → engine   frame(kind, w, h, rgb bytes)         camera / screen, downscaled in the page (≤ 10 fps)
                    audio(sample rate, float32 samples)  the newest ~2048 samples, ~20×/s
                    state(kind, state, detail)           "waiting" (needs a click) | "live" | "denied" | "error" |
                                                         "stopped" | "unsupported"

The page is `web/webapp/host-media.js`; the worker forwards both ways (`worker.js`, `web_main.media_*`). Values
have exactly the shape of the desktop providers (`capture.py`, `camera.py`), so the apps don't know the
difference. Push-based: no polling task; every frame is processed when it arrives (small: ≤ 192 px, once).

Only `build_hub` on the "web" platform uses these; the desktop providers are untouched.
"""

from __future__ import annotations

import itertools
import json
import logging
import time
from typing import Any, ClassVar

import numpy as np

from .base import Provider

log = logging.getLogger("deskdot.webmedia")

KINDS = ("camera", "screen", "audio")
#: page states (host-media.js) → what the provider reports while there is no picture/sound yet
PROBLEMS = {"denied", "error", "stopped", "unsupported"}

_bridge: Any = None  # object with want(kind, opts_json) / stop(kind); None → the worker's `deskdotMedia`
_live: dict[str, WebMediaProvider] = {}  # kind → the provider the page feeds (the engine's hub)


def set_bridge(bridge: Any) -> None:
    """Inject the page bridge (tests); None restores the worker's `deskdotMedia`."""
    global _bridge
    _bridge = bridge


def _page() -> Any:
    if _bridge is not None:
        return _bridge
    try:
        import js  # type: ignore[import-not-found]

        return js.deskdotMedia
    except Exception:  # not in a browser (tests without a bridge, `deskdot preview`): nobody to ask
        return None


# ===================================================================== entry points (web_main → here)
def frame(kind: str, w: int, h: int, data: bytes) -> None:
    p = _live.get(kind)
    if p is not None:
        p.push_frame(int(w), int(h), data)


def audio(sample_rate: float, data: bytes, source: str = "") -> None:
    p = _live.get("audio")
    if isinstance(p, WebAudioProvider):
        p.push_audio(float(sample_rate), np.frombuffer(data, np.float32), source or None)


def state(kind: str, st: str, detail: str = "") -> None:
    p = _live.get(kind)
    if p is not None:
        p.on_state(str(st), str(detail or ""))


def hello() -> None:
    """The page's capture add-on (re)started: repeat every request that is still wanted."""
    for p in list(_live.values()):
        if p._refs and p.supported:
            p._ask()


# ===================================================================== providers
class WebMediaProvider(Provider[Any]):
    """Base: ref-counted `want`/`stop` toward the page, values pushed by it."""

    kind: ClassVar[str]

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.stream = "idle"  # the page's state for this kind (see module doc)
        self.detail = ""
        _live[self.kind] = self

    def options(self) -> dict[str, Any]:
        return {}

    def _ask(self) -> None:
        page = _page()
        if page is None:
            return
        try:
            page.want(self.kind, json.dumps(self.options()))
        except Exception as e:  # pragma: no cover — the bridge is a thin postMessage
            log.warning("media want %s failed: %s", self.kind, e)

    def acquire(self) -> None:
        self._refs += 1
        if not self.supported:
            if self.error is None:
                self.error = self.unsupported_error()
                self.hub.on_change(self.name)
            return
        if self._refs == 1:
            self.stream = "asking"
            self._ask()

    def release(self) -> None:
        was = self._refs
        super().release()
        if was and self._refs == 0:
            self.value = None  # a stale picture must not flash up next time
            self.stream, self.detail = "idle", ""
            if self.supported and (page := _page()) is not None:
                try:
                    page.stop(self.kind)
                except Exception as e:  # pragma: no cover
                    log.warning("media stop %s failed: %s", self.kind, e)

    def on_state(self, st: str, detail: str) -> None:
        self.stream, self.detail = st, detail
        old = self.error
        if st in PROBLEMS:
            self.value = None
            self.error = detail or f"{self.kind} {st}"
        else:  # waiting / live: no error (the app shows its "loading" animation until the first frame)
            self.error = None
        if self.error != old:
            self.hub.on_change(self.name)

    def push_frame(self, w: int, h: int, data: bytes) -> None:
        if not self._refs or w <= 0 or h <= 0 or len(data) < w * h * 3:
            return
        from PIL import Image

        try:
            img = Image.frombuffer("RGB", (w, h), bytes(data[: w * h * 3]), "raw", "RGB", 0, 1)
            self.value = self.process(img)
        except Exception as e:
            log.warning("%s frame failed: %s", self.kind, e)
            return
        self.updated = time.time()
        if self.error is not None:
            self.error = None
            self.hub.on_change(self.name)

    def process(self, img: Any) -> Any:  # pragma: no cover — overridden
        raise NotImplementedError

    def announce(self, old: Any, new: Any) -> bool:
        return False

    async def fetch(self) -> Any:  # never polled (acquire starts no task); kept for the Provider contract
        if self.value is None:
            raise RuntimeError(self.error or f"waiting for the {self.kind}")
        return self.value

    def snapshot(self) -> dict[str, Any]:
        return {**super().snapshot(), "stream": self.stream}


class WebScreenProvider(WebMediaProvider):
    """Screen Mirror in a tab: a screen, window or tab the user shares (getDisplayMedia)."""

    name = "screen"
    kind = "screen"
    feature = "screen"

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.mode = "full"
        self.cursor_box = 128
        self.fit = "contain"
        self.controls: Any = None

    def configure(self, mode: str, cursor_box: int, fit: str, controls: Any) -> None:
        self.mode, self.cursor_box, self.fit, self.controls = mode, cursor_box, fit, controls

    def process(self, img: Any) -> np.ndarray:
        """Same pipeline as the desktop `ScreenProvider._grab`, minus the grab. The browser picks the source
        (screen / window / tab), so "Active window" / "Around cursor" mirror whatever was shared."""
        from PIL import Image

        from ..gfx.adjust import ImageControls, adjust, crop_box, geometry, to_panel

        c = self.controls or ImageControls()
        if self.mode == "ambilight":
            small = img.resize((8, 8), Image.Resampling.BOX).resize((32, 32), Image.Resampling.BICUBIC)
            return adjust(geometry(small, c), c)
        img = img.crop(crop_box(img.width, img.height, c.zoom, c.pan_x, c.pan_y, self.fit == "cover"))
        img = geometry(img, c)
        s = 128 / max(img.size)
        work = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.Resampling.BOX)
        s = 32 / max(work.size)
        nw, nh = max(1, round(work.width * s)), max(1, round(work.height * s))
        small = to_panel(work, c, (nw, nh))
        out = np.zeros((32, 32, 3), np.uint8)
        y0, x0 = (32 - nh) // 2, (32 - nw) // 2
        out[y0 : y0 + nh, x0 : x0 + nw] = small
        return out


# inferno-like ramp for the "thermal" look (no OpenCV in the browser)
_THERMAL = np.array(
    [(0, 0, 4), (40, 11, 84), (101, 21, 110), (159, 42, 99), (212, 72, 66), (245, 125, 21), (250, 193, 39),
     (252, 255, 164)],
    np.float32,
)  # fmt: skip


def _lut(stops: np.ndarray) -> np.ndarray:
    x = np.linspace(0, len(stops) - 1, 256)
    i = np.minimum(x.astype(int), len(stops) - 2)
    f = (x - i)[:, None]
    return (stops[i] * (1 - f) + stops[i + 1] * f).astype(np.uint8)


THERMAL_LUT = _lut(_THERMAL)


def _gray(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114).astype(np.float32)


def stylize_rgb(
    rgb: np.ndarray, style: str, work: np.ndarray | None = None, t: float | None = None
) -> np.ndarray:
    """The Camera Mirror looks in numpy (the desktop uses OpenCV, which the browser build doesn't ship).

    `rgb` is the 32x32 tone-adjusted picture; `work` the 128x128 crop (edges need resolution)."""
    from .camera import _levels

    if style == "neon":
        src = _gray(work if work is not None else rgb)
        gx = np.zeros_like(src)
        gy = np.zeros_like(src)
        gx[:, 1:-1] = src[:, 2:] - src[:, :-2]
        gy[1:-1, :] = src[2:, :] - src[:-2, :]
        mag = np.hypot(gx, gy)
        n = mag.shape[0] // 32
        pooled = mag[: n * 32, : n * 32].reshape(32, n, 32, n).max(axis=(1, 3)) if n > 1 else mag
        thr = max(40.0, float(np.percentile(pooled, 80)))
        mask = pooled > thr
        hue = (np.linspace(0, 1, 32, endpoint=False)[None, :].repeat(32, 0) + (t or time.time()) * 0.11) % 1.0
        h6 = hue * 6
        k = np.stack([(5 + h6) % 6, (3 + h6) % 6, (1 + h6) % 6], axis=-1)
        out = (255 * (1 - np.clip(np.minimum(k, 4 - k), 0, 1))).astype(np.uint8)
        out[~mask] = 0
        return out
    if style == "thermal":
        return THERMAL_LUT[_levels(_gray(rgb).astype(np.uint8))]
    if style == "mono":
        gray = _levels(_gray(rgb).astype(np.uint8)).astype(np.float32) / 255
        bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16
        on = gray > np.tile(bayer, (8, 8))
        out = np.zeros((32, 32, 3), np.uint8)
        out[on] = (255, 90, 30)
        return out
    if style == "pop":
        a = rgb.astype(np.float32)
        g = _gray(a)[..., None]
        a = np.clip(g + (a - g) * 1.8, 0, 255).astype(np.uint8)  # saturation x1.8
        return (a // 64) * 64 + 32  # posterise to 4 levels per channel
    return rgb


class WebCameraProvider(WebMediaProvider):
    """Camera Mirror in a tab (getUserMedia). Camera index 0 = the front / default camera; on a phone 1 = the
    back camera. No face tracking in the browser (no OpenCV): the picture is centre-cropped (zoom / pan work)."""

    name = "camera"
    kind = "camera"
    feature = "camera"

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.index = 0
        self.style = "natural"
        self.track_face = True
        self.controls: Any = None

    def options(self) -> dict[str, Any]:
        return {"index": self.index}

    def configure(self, index: int, style: str, track_face: bool, controls: Any) -> None:
        switch = index != self.index
        self.index, self.style, self.track_face, self.controls = index, style, track_face, controls
        if switch and self._refs and self.supported:
            self._ask()  # the page reopens the stream on the other camera

    def process(self, img: Any) -> np.ndarray:
        from PIL import Image

        from ..gfx.adjust import ImageControls, crop_box, geometry, to_panel

        c = self.controls or ImageControls()
        img = img.crop(crop_box(img.width, img.height, c.zoom, c.pan_x, c.pan_y, square=True))
        img = geometry(img, c).resize((128, 128), Image.Resampling.BOX)
        if self.style == "neon":
            return stylize_rgb(np.zeros((32, 32, 3), np.uint8), "neon", np.asarray(img.convert("RGB")))
        return stylize_rgb(to_panel(img, c), self.style)


class WebAudioProvider(WebMediaProvider):
    """Visualizer / dancing pets in a tab: the microphone (getUserMedia) or a shared tab's / the system's sound
    (getDisplayMedia with audio — Chrome / Edge on a computer). Same analysis and output as `AudioProvider`."""

    name = "audio"
    kind = "audio"
    feature = "audio"
    BANDS = 32

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._bands = np.zeros(self.BANDS, np.float32)
        self._peaks = np.zeros(self.BANDS, np.float32)
        self._agc = 0.05
        self._beat_t = 0.0
        self._beats = 0
        self._intervals: list[float] = []
        self._flux: list[tuple[float, float]] = []  # (time, low-end spectral flux)
        self._prev: np.ndarray | None = None
        self._plan: tuple[int, float, Any] | None = (
            None  # (window, sample rate, (window fn, band idx, low mask))
        )
        self._source = "system"

    @property
    def source(self) -> str:
        store = getattr(self.hub, "store", None)
        return (store.get("audio_source", "system") if store else "system") or "system"

    def options(self) -> dict[str, Any]:
        return {"source": self.source}

    def restart(self) -> None:
        """The audio source setting changed (server.py calls this on every host)."""
        if self._refs and self.supported:
            self._prev = None
            self._ask()

    def _setup(self, n: int, sr: float) -> Any:
        if self._plan is None or self._plan[:2] != (n, sr):
            freqs = np.fft.rfftfreq(n, 1 / sr)
            edges = np.geomspace(40, 16000, self.BANDS + 1)
            idx = [np.where((freqs >= lo) & (freqs < hi))[0] for lo, hi in itertools.pairwise(edges)]
            self._plan = (n, sr, (np.hanning(n), idx, (freqs >= 40) & (freqs < 250)))
            self._prev = None
        return self._plan[2]

    def push_audio(
        self, sr: float, buf: np.ndarray, source: str | None = None, now: float | None = None
    ) -> None:
        if not self._refs or len(buf) < 256 or sr <= 0:
            return
        now = time.monotonic() if now is None else now
        buf = np.nan_to_num(buf.astype(np.float32))
        window, idx, low = self._setup(len(buf), sr)
        spec = np.abs(np.fft.rfft(buf * window)).astype(np.float32)
        bands = np.array([spec[i].mean() if len(i) else 0.0 for i in idx], np.float32)
        bands = np.log1p(bands * 4)
        self._agc = max(0.02, 0.97 * self._agc + 0.03 * float(bands.max()))  # auto gain
        norm = np.clip(bands / (self._agc * 1.6 + 1e-6), 0, 1)
        self._bands = np.maximum(norm, self._bands * 0.82)
        self._peaks = np.maximum(self._bands, self._peaks - 0.02)
        data = buf[-len(buf) // 2 :]  # the newest half: level and waveform, like the desktop's block
        level = float(np.sqrt(np.mean(data**2)))
        wave = data[:: max(1, len(data) // 32)][:32]
        # beat: positive spectral flux in the low end vs. its recent (0.9 s) average
        prev = self._prev if self._prev is not None and len(self._prev) == len(spec) else spec
        flux = float(np.maximum(spec[low] - prev[low], 0).sum())
        self._prev = spec
        self._flux.append((now, flux))
        self._flux = [(t, v) for t, v in self._flux if now - t <= 0.9]
        hist = [v for _, v in self._flux]
        mean, std = float(np.mean(hist)), float(np.std(hist))
        if (
            len(hist) > 10
            and flux > mean + 1.4 * std
            and flux > 1e-3
            and level > 0.004
            and now - self._beat_t > 0.28
        ):
            if self._beat_t:
                gap = now - self._beat_t
                if 0.28 < gap < 1.5:
                    self._intervals.append(gap)
                    del self._intervals[:-16]
            self._beat_t = now
            self._beats += 1
        if source:
            self._source = source
        since = now - self._beat_t if self._beat_t else 99.0
        bpm = 60.0 / float(np.median(self._intervals)) if len(self._intervals) >= 4 else 0.0
        b = self._bands
        self.value = {
            "bands": b.tolist(),
            "peaks": self._peaks.tolist(),
            "level": level,
            "wave": wave.tolist(),
            "bass": float(b[:6].mean()),
            "mid": float(b[6:20].mean()),
            "treble": float(b[20:].mean()),
            "beat": max(0.0, 1.0 - since / 0.25),
            "beats": self._beats,
            "bpm": round(bpm, 1),
            "music": level > 0.004,
            "source": self._source,
            "t": time.time(),
        }
        self.updated = time.time()
        if self.error is not None:
            self.error = None
            self.hub.on_change(self.name)


#: the providers the web platform swaps in (providers.build_hub)
WEB: tuple[type[WebMediaProvider], ...] = (WebScreenProvider, WebCameraProvider, WebAudioProvider)
