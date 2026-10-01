"""Animated thumbnails of every app for the studio's library — rendered in a sandbox.

Each preview uses a throwaway app instance with a sandboxed context: it can read provider values (so
previews show live data when it's already cached) but can't persist data, notify, or touch the real
slot. Results are cached per (app, settings) for a short time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .engine import REGISTRY
from .gfx import Frame
from .gfx.image import encode_gif

log = logging.getLogger("deskdot.previews")


class PreviewContext:
    """Just enough of AppContext for rendering; every side effect is a no-op."""

    def __init__(self, engine: Any, app_id: str) -> None:
        self._engine = engine
        self.key = f"preview:{app_id}"
        self.app_id = app_id
        self.data: dict[str, Any] = dict(engine.store.section("app_data").get(app_id, {}))

    def provider(self, name: str) -> Any:
        return self._engine.hub.get(name)

    def save(self) -> None: ...
    def invalidate(self) -> None: ...
    def notify(self, **_: Any) -> None: ...

    @property
    def library(self) -> Any:
        return self._engine.library

    @property
    def media_dir(self) -> Any:
        return self._engine.config.media_dir


class Previews:
    TTL = 20.0

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self._cache: dict[str, tuple[float, str, bytes]] = {}  # app -> (time, settings key, gif)
        self._lock = asyncio.Lock()

    def _render(self, app_id: str, frames: int = 14, fps: float = 7.0) -> bytes:
        cls = REGISTRY[app_id]
        ctx = PreviewContext(self.engine, app_id)
        try:
            settings = cls.Settings.model_validate(self.engine.base_settings(app_id))
        except Exception:
            settings = cls.Settings()
        app = cls(ctx, settings)  # type: ignore[arg-type]
        frames_out: list[Frame] = []
        if self._is_clip(app):
            # Clip apps: sample the real baked loop (some only simulate it in clip_frames, off the render path)
            clip = app.clip_frames()
            step = max(1, len(clip.frames) // frames)
            picked = clip.frames[::step][:frames]
            ms = max(60, round(sum(clip.durations_ms[: step * len(picked)]) / max(1, len(picked))))
            return encode_gif([self.engine._panel(f) for f in picked], [ms] * len(picked), max_colors=128)
        for i in range(frames):
            f = Frame()
            try:
                app.render(f, 0.4 + i / fps)
            except Exception:
                f.text_center(13, "?", (255, 30, 60), font="small")
            frames_out.append(self.engine._panel(f))  # show what the LEDs would show
        return encode_gif(frames_out, [round(1000 / fps)] * frames, max_colors=128)

    @staticmethod
    def _is_clip(app: object) -> bool:
        try:
            return app.kind() == "clip"  # type: ignore[attr-defined]
        except Exception:
            return False

    async def get(self, app_id: str) -> bytes:
        key = json.dumps(self.engine.base_settings(app_id), sort_keys=True)
        hit = self._cache.get(app_id)
        if hit and hit[1] == key and time.monotonic() - hit[0] < self.TTL:
            return hit[2]
        async with self._lock:  # one render at a time keeps the event loop responsive
            gif = await asyncio.to_thread(self._render, app_id)
        self._cache[app_id] = (time.monotonic(), key, gif)
        return gif
