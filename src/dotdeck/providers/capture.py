"""Live capture sources: the PC screen (for Screen Mirror) and system audio (for the Visualizer).

Both run their blocking capture in a worker thread and only while an app holds them.
"""

from __future__ import annotations

import asyncio
import ctypes
import itertools
import logging
import sys
import threading
import time
import warnings
from typing import Any

import numpy as np
from PIL import Image, ImageGrab

from .base import Provider

log = logging.getLogger("dotdeck.capture")


def _cursor() -> tuple[int, int]:
    if sys.platform == "darwin":
        try:
            from AppKit import NSEvent, NSScreen  # type: ignore[import-not-found]

            loc = NSEvent.mouseLocation()  # origin bottom-left
            h = NSScreen.mainScreen().frame().size.height
            return int(loc.x), int(h - loc.y)
        except Exception:
            return (0, 0)
    if sys.platform != "win32":
        return (0, 0)

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    p = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def _foreground_rect() -> tuple[int, int, int, int] | None:
    if sys.platform == "darwin":
        try:
            from AppKit import NSWorkspace  # type: ignore[import-not-found]
            from Quartz import (  # type: ignore[import-not-found]
                CGWindowListCopyWindowInfo,
                kCGNullWindowID,
                kCGWindowListOptionOnScreenOnly,
            )

            pid = NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()
            for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []:
                if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0:
                    b = w["kCGWindowBounds"]
                    x, y, ww, hh = int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])
                    return (x, y, x + ww, y + hh) if ww > 50 and hh > 50 else None
        except Exception:
            return None
        return None
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    r = wintypes.RECT()
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    if r.right - r.left < 50 or r.bottom - r.top < 50:
        return None
    return r.left, r.top, r.right, r.bottom


class ScreenProvider(Provider[np.ndarray]):
    """Grabs the screen ~10x/s and turns it into a 32x32 frame through the shared image controls."""

    name = "screen"
    interval = 0.1
    retry = 2.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.mode = "full"
        self.cursor_box = 128  # px square around the cursor in "cursor" mode
        self.fit = "contain"
        self.controls: Any = None  # ImageControls, set by the app

    def configure(self, mode: str, cursor_box: int, fit: str, controls: Any) -> None:
        self.mode, self.cursor_box, self.fit, self.controls = mode, cursor_box, fit, controls

    def _grab(self) -> np.ndarray:
        from ..gfx.adjust import ImageControls, adjust, crop_box, geometry, to_panel

        c = self.controls or ImageControls()
        bbox = None
        if self.mode == "cursor":
            x, y = _cursor()
            h = self.cursor_box // 2
            bbox = (x - h, y - h, x + h, y + h)
        elif self.mode == "window":
            bbox = _foreground_rect()
        img = ImageGrab.grab(bbox=bbox, all_screens=self.mode == "cursor")
        if self.mode == "ambilight":
            small = img.resize((8, 8), Image.Resampling.BOX).resize((32, 32), Image.Resampling.BICUBIC)
            return adjust(geometry(small, c), c)
        square = self.fit == "cover" or self.mode == "cursor"
        img = img.crop(crop_box(img.width, img.height, c.zoom, c.pan_x, c.pan_y, square))
        img = geometry(img, c)
        s = 128 / max(img.size)  # working resolution for sharpening
        work = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.Resampling.BOX)
        s = 32 / max(work.size)
        nw, nh = max(1, round(work.width * s)), max(1, round(work.height * s))
        small = to_panel(work, c, (nw, nh))
        frame = np.zeros((32, 32, 3), np.uint8)
        y0, x0 = (32 - nh) // 2, (32 - nw) // 2
        frame[y0 : y0 + nh, x0 : x0 + nw] = small
        return frame

    async def fetch(self) -> np.ndarray:
        return await asyncio.to_thread(self._grab)

    def announce(self, old: Any, new: Any) -> bool:
        return False


class AudioProvider(Provider[dict[str, Any]]):
    """Audio spectrum + beat tracking from system playback (loopback) or the microphone.

    A worker thread records ~21 ms blocks with `soundcard`, computes 32 log-spaced bands, and runs an
    onset detector on the bass/low-mid spectral flux with an adaptive threshold. Output (read by apps):
    bands, peaks, level, wave, bass/mid/treble, beat (1.0 on a beat, decaying), beats (count), bpm.

    Source is the store key "audio_source": "system" (Windows WASAPI loopback; on macOS needs a loopback
    device such as BlackHole) or "mic".
    """

    name = "audio"
    interval = 0.04
    retry = 5.0
    BANDS = 32

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._bands = np.zeros(self.BANDS, np.float32)
        self._peaks = np.zeros(self.BANDS, np.float32)
        self._level = 0.0
        self._wave = np.zeros(32, np.float32)
        self._err: str | None = None
        self._agc = 0.05
        self._beat_t = 0.0
        self._beats = 0
        self._intervals: list[float] = []
        self._source = "system"

    @property
    def source(self) -> str:
        store = getattr(self.hub, "store", None)
        return (store.get("audio_source", "system") if store else "system") or "system"

    def restart(self) -> None:
        """Called after the audio source setting changes."""
        self._stop.set()
        if self._refs:
            t = self._thread
            if t is not None:
                t.join(timeout=1.5)
            self._start_thread()

    def _recorder(self, sc: Any, sr: int, n: int) -> Any:
        src = self.source
        self._source = src
        if src == "mic":
            return sc.default_microphone().recorder(samplerate=sr, channels=1, blocksize=n)
        spk = sc.default_speaker()
        try:
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
        except Exception as e:  # macOS has no native loopback
            raise RuntimeError(
                "system-audio loopback unavailable here (on macOS install BlackHole, or choose 'Microphone')"
            ) from e
        return mic.recorder(samplerate=sr, channels=1, blocksize=n)

    def _run(self) -> None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import soundcard as sc

                sr, n = 48000, 1024
                freqs = np.fft.rfftfreq(n * 2, 1 / sr)
                edges = np.geomspace(40, 16000, self.BANDS + 1)
                idx = [np.where((freqs >= lo) & (freqs < hi))[0] for lo, hi in itertools.pairwise(edges)]
                window = np.hanning(n * 2)
                low = (freqs >= 40) & (freqs < 250)
                prev_spec = np.zeros(len(freqs), np.float32)
                flux_hist: list[float] = []
                buf = np.zeros(n * 2, np.float32)
                with self._recorder(sc, sr, n) as rec:
                    self._err = None
                    while not self._stop.is_set():
                        data = rec.record(numframes=n)[:, 0].astype(np.float32)
                        buf = np.concatenate([buf[n:], data])  # 50 % overlap, 2048-point FFT
                        spec = np.abs(np.fft.rfft(buf * window)).astype(np.float32)
                        bands = np.array([spec[i].mean() if len(i) else 0.0 for i in idx], np.float32)
                        bands = np.log1p(bands * 4)
                        peak = float(bands.max())
                        self._agc = max(0.02, 0.97 * self._agc + 0.03 * peak)  # auto gain
                        norm = np.clip(bands / (self._agc * 1.6 + 1e-6), 0, 1)
                        self._bands = np.maximum(norm, self._bands * 0.82)  # fast attack, smooth decay
                        self._peaks = np.maximum(self._bands, self._peaks - 0.02)
                        self._level = float(np.sqrt(np.mean(data**2)))
                        self._wave = data[:: n // 32][:32]
                        # --- beat: positive spectral flux in the low end vs. its recent average
                        flux = float(np.maximum(spec[low] - prev_spec[low], 0).sum())
                        prev_spec = spec
                        flux_hist.append(flux)
                        del flux_hist[:-43]  # ~0.9 s of history
                        mean = float(np.mean(flux_hist))
                        std = float(np.std(flux_hist))
                        now = time.monotonic()
                        if (
                            len(flux_hist) > 10
                            and flux > mean + 1.4 * std
                            and flux > 1e-3
                            and self._level > 0.004
                            and now - self._beat_t > 0.28
                        ):
                            if self._beat_t:
                                gap = now - self._beat_t
                                if 0.28 < gap < 1.5:
                                    self._intervals.append(gap)
                                    del self._intervals[:-16]
                            self._beat_t = now
                            self._beats += 1
        except Exception as e:
            self._err = f"audio capture unavailable: {e}"
            log.info(self._err)

    def _start_thread(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="audio-capture", daemon=True)
        self._thread.start()

    def acquire(self) -> None:
        super().acquire()
        if self._thread is None or not self._thread.is_alive():
            self._start_thread()

    def release(self) -> None:
        super().release()
        if self._refs == 0:
            self._stop.set()

    def announce(self, old: Any, new: Any) -> bool:
        return False

    async def fetch(self) -> dict[str, Any]:
        if self._err:
            raise RuntimeError(self._err)
        since = time.monotonic() - self._beat_t if self._beat_t else 99.0
        bpm = 60.0 / float(np.median(self._intervals)) if len(self._intervals) >= 4 else 0.0
        b = self._bands
        return {
            "bands": b.tolist(),
            "peaks": self._peaks.tolist(),
            "level": self._level,
            "wave": self._wave.tolist(),
            "bass": float(b[:6].mean()),
            "mid": float(b[6:20].mean()),
            "treble": float(b[20:].mean()),
            "beat": max(0.0, 1.0 - since / 0.25),  # 1 on the beat, fades over 250 ms
            "beats": self._beats,
            "bpm": round(bpm, 1),
            "music": self._level > 0.004,
            "source": self._source,
            "t": time.time(),
        }


class GitHubProvider(Provider[dict[str, Any]]):
    """Public contribution calendar for a user (no token needed)."""

    name = "github"
    interval = 1800.0
    retry = 120.0

    def __init__(self, hub: Any) -> None:
        super().__init__(hub)
        self.user = ""

    def want(self, user: str) -> None:
        user = user.strip().lstrip("@")
        if user and user != self.user:
            self.user = user
            self.value = None
            self.refresh()

    async def fetch(self) -> dict[str, Any]:
        import re

        if not self.user:
            raise RuntimeError("set a GitHub username")
        r = await self.hub.http.get(f"https://github.com/users/{self.user}/contributions")
        r.raise_for_status()
        html = r.text
        cells = re.findall(r'data-date="(\d{4}-\d{2}-\d{2})"[^>]*?data-level="(\d)"', html)
        if not cells:
            cells = [
                (d, lv)
                for lv, d in re.findall(r'data-level="(\d)"[^>]*?data-date="(\d{4}-\d{2}-\d{2})"', html)
            ]
        days = sorted({d: int(lv) for d, lv in cells}.items())
        total_m = re.search(r"([\d,]+)\s+contributions?\s+in the last year", html)
        levels = [lv for _, lv in days]
        streak = 0
        for lv in reversed(levels):
            if lv == 0 and streak == 0:
                continue  # today may be empty yet
            if lv == 0:
                break
            streak += 1
        return {
            "user": self.user,
            "days": days,  # [(iso date, level 0..4)] oldest first
            "total": int(total_m.group(1).replace(",", "")) if total_m else None,
            "streak": streak,
        }
