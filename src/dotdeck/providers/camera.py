"""Webcam capture for Camera Mirror, with optional face tracking.

A worker thread owns the camera only while an app holds this provider, so the camera light is off
the rest of the time. Frames are cropped (optionally around your face), styled for LEDs and
downsampled to 32x32.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np

from .base import Provider

log = logging.getLogger("dotdeck.camera")


def _levels(img: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(img, 3), np.percentile(img, 99)
    return np.clip((img.astype(np.float32) - lo) / max(1.0, hi - lo) * 255, 0, 255).astype(np.uint8)


def stylize(bgr: np.ndarray, style: str) -> np.ndarray:
    """bgr (N, N, 3) uint8 at ~96 px (already tone-adjusted) -> RGB 32x32 uint8 for the panel."""
    import cv2

    if style == "neon":
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 50, 120)
        small = cv2.resize(edges, (32, 32), interpolation=cv2.INTER_AREA)
        mask = small > 40
        hue = np.linspace(0, 179, 32, dtype=np.uint8)[None, :].repeat(32, 0)
        hsv = np.dstack([(hue + int(time.time() * 20)) % 180, np.full_like(hue, 255), np.full_like(hue, 255)])
        rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
        rgb[~mask] = 0
        return rgb
    small = cv2.resize(bgr, (32, 32), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    if style == "thermal":
        gray = _levels(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        return cv2.cvtColor(cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO), cv2.COLOR_BGR2RGB)
    if style == "mono":
        gray = _levels(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)).astype(np.float32) / 255
        bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16
        on = gray > np.tile(bayer, (8, 8))
        out = np.zeros((32, 32, 3), np.uint8)
        out[on] = (255, 90, 30)
        return out
    if style == "pop":
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * 1.8, 0, 255)
        rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
        rgb = (rgb // 64) * 64 + 32  # posterise to 4 levels per channel
    return rgb


class CameraProvider(Provider[np.ndarray]):
    name = "camera"
    interval = 0.08
    retry = 3.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.index = 0
        self.style = "natural"
        self.track_face = True
        self.controls: Any = None  # CameraSettings (ImageControls + hardware fields)
        self._hw_applied: tuple[Any, ...] | None = None
        self._frame: np.ndarray | None = None
        self._err: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._center: tuple[float, float, float] | None = None  # smoothed face box (cx, cy, size)

    def configure(self, index: int, style: str, track_face: bool, controls: Any) -> None:
        restart = index != self.index
        self.index, self.style, self.track_face, self.controls = index, style, track_face, controls
        if restart and self._thread and self._thread.is_alive():
            self._stop.set()

    def _apply_hardware(self, cap: Any) -> None:
        """Push the camera's own controls (exposure, focus, white balance) when they change."""
        import cv2

        c = self.controls
        if c is None:
            return
        key = (c.hw_auto_exposure, c.hw_exposure, c.autofocus, c.focus, c.hw_auto_wb, c.wb_kelvin, c.hw_gain)
        if key == self._hw_applied:
            return
        self._hw_applied = key
        # DirectShow: 0.75 = auto exposure on, 0.25 = manual (AVFoundation ignores most of these)
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if c.hw_auto_exposure else 0.25)
        if not c.hw_auto_exposure:
            cap.set(cv2.CAP_PROP_EXPOSURE, float(c.hw_exposure))
            cap.set(cv2.CAP_PROP_GAIN, float(c.hw_gain))
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if c.autofocus else 0)
        if not c.autofocus:
            cap.set(cv2.CAP_PROP_FOCUS, float(c.focus))
        cap.set(cv2.CAP_PROP_AUTO_WB, 1 if c.hw_auto_wb else 0)
        if not c.hw_auto_wb:
            cap.set(cv2.CAP_PROP_WB_TEMPERATURE, float(c.wb_kelvin))

    def announce(self, old: Any, new: Any) -> bool:
        return False

    # ---------------------------------------------------------------- worker
    def _run(self) -> None:
        import sys

        import cv2
        from PIL import Image

        from ..gfx.adjust import ImageControls, crop_box, geometry, to_panel

        backend = (
            cv2.CAP_DSHOW
            if sys.platform == "win32"
            else (cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY)
        )
        cap = cv2.VideoCapture(self.index, backend)
        if not cap.isOpened():
            self._err = f"camera {self.index} not available (in use by another app?)"
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._hw_applied = None
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        n = 0
        self._err = None
        try:
            while not self._stop.is_set():
                self._apply_hardware(cap)
                ok, bgr = cap.read()
                if not ok:
                    self._err = "camera stopped delivering frames"
                    time.sleep(0.5)
                    continue
                c = self.controls or ImageControls()
                h, w = bgr.shape[:2]
                if self.track_face and n % 4 == 0:
                    gray = cv2.cvtColor(cv2.resize(bgr, (w // 4, h // 4)), cv2.COLOR_BGR2GRAY)
                    faces = cascade.detectMultiScale(gray, 1.15, 5, minSize=(20, 20))
                    if len(faces):
                        fx, fy, fw, fh = (int(v) * 4 for v in max(faces, key=lambda r: r[2] * r[3]))
                        target = (fx + fw / 2, fy + fh * 0.55, fw * 2.2)
                        cur = self._center or target
                        self._center = tuple(p + (q - p) * 0.35 for p, q in zip(cur, target, strict=True))  # type: ignore[assignment]
                n += 1
                if self.track_face and self._center:
                    cx, cy, size = self._center
                    size = max(64.0, min(float(min(w, h)), size / c.zoom))
                    x0 = int(min(max(0, cx - size / 2), w - size))
                    y0 = int(min(max(0, cy - size / 2), h - size))
                    box = (x0, y0, x0 + int(size), y0 + int(size))
                else:
                    box = crop_box(w, h, c.zoom, c.pan_x, c.pan_y, square=True)
                img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).crop(box)
                img = geometry(img, c).resize((128, 128), Image.Resampling.BOX)
                if self.style == "neon":  # edges need resolution: detect before shrinking
                    self._frame = stylize(cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR), "neon")
                else:
                    rgb = to_panel(img, c)
                    self._frame = stylize(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), self.style)
        finally:
            cap.release()

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
            self._thread.start()

    def acquire(self) -> None:
        super().acquire()
        self._ensure_thread()

    def release(self) -> None:
        super().release()
        if self._refs == 0:
            self._stop.set()

    async def fetch(self) -> np.ndarray:
        if self._refs:
            self._ensure_thread()  # restarts after a camera switch
        if self._err:
            raise RuntimeError(self._err)
        if self._frame is None:
            raise RuntimeError("starting camera…")
        return self._frame
