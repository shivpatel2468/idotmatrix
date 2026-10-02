"""HTTP endpoints for the calibration wizard, picture presets and the motion lab (docs/API.md, docs/CALIBRATION.md).

Kept out of server.py so the calibration feature is one module; `server.create_app` calls `register()`.
Everything that touches the panel goes through the engine (rule 4): test cards are streamed by its tick.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Store
from .engine import Engine
from .gfx.calib import PanelCalibration, channel_gains, kelvin_gains
from .gfx.calib_presets import (
    MIN_SAFE_PACKET_GAP_MS,
    MOTION_PRESETS,
    Room,
    Tint,
    Use,
    autotune,
    get_motion_preset,
    get_preset,
    preset_listing,
    quick_match,
)
from .gfx.image import GIF_BUDGET
from .gfx.testvideo import (
    CAL_FPS,
    CAL_VIDEOS,
    CLIP_MAX_FPS,
    MOTION_MAX_FPS,
    MOTION_MIN_FPS,
    MOTION_TESTS,
    CalCard,
    CalVideoName,
    MotionCard,
    MotionCfg,
    MotionTestName,
)

DISCLAIMER = (
    "Brand-style presets are approximations inspired by how those displays tend to look. They are not official "
    "values and are not affiliated with or endorsed by the companies named."
)


class PresetBody(BaseModel):
    keep_balance: bool = Field(True, description="Keep the panel's measured RGB gains (white balance)")
    apply: bool = Field(True, description="Save it as the panel calibration (false = just return it)")


class QuickBody(BaseModel):
    room: Room = "dim"
    use: Use = "mixed"
    tint: Tint = "neutral"
    apply: bool = False


class CalTestBody(BaseModel):
    video: CalVideoName = "card"
    a: PanelCalibration = Field(default_factory=PanelCalibration)
    b: PanelCalibration | None = None
    layout: Literal["ab", "wipe"] = "ab"
    split: int = Field(16, ge=0, le=32)
    labels: tuple[str, str] | None = None
    seconds: float = Field(180, ge=1, le=1800)  # expires if the studio goes away


class MotionCfgBody(BaseModel):
    fps: float = Field(8.0, ge=MOTION_MIN_FPS, le=MOTION_MAX_FPS)
    speed: float = Field(8.0, ge=1, le=24, description="pixels per second")
    soft: bool = False
    smoothing: float = Field(0.0, ge=0, le=0.6)
    transition: Literal["cut", "push", "fade", "wipe"] = "cut"

    def cfg(self) -> MotionCfg:
        return MotionCfg(**self.model_dump())


class MotionTestBody(BaseModel):
    test: MotionTestName = "ufo"
    a: MotionCfgBody = Field(default_factory=MotionCfgBody)
    b: MotionCfgBody | None = None
    layout: Literal["stack", "alternate"] = "stack"
    mode: Literal["stream", "clip"] = "stream"
    seconds: float = Field(180, ge=1, le=1800)  # expires if the studio goes away


class AutotuneBody(BaseModel):
    seconds: float = Field(4.0, ge=2, le=8)
    apply: bool = False


def _labels(lab: tuple[str, str] | None) -> tuple[str, str] | None:
    if lab is None:
        return None
    return (lab[0][:4].upper(), lab[1][:4].upper())


def motion_limits(engine: Engine) -> dict[str, Any]:
    """The link's fixed, hardware-verified physics: shown in the studio as facts, never as knobs."""
    return {
        "stream_fps_max": MOTION_MAX_FPS,
        "stream_fps_min": MOTION_MIN_FPS,
        "clip_fps_max": CLIP_MAX_FPS,
        "gif_budget_kb": GIF_BUDGET // 1024,
        "frames_in_flight": 1,
        "packet_gap_min_ms": MIN_SAFE_PACKET_GAP_MS,
        "packet_gap_verified_ms": 30.0,
        "one_packet_bytes": 514,
        "measured_ui_fps": 9.0,
        "measured_photo_fps": 6.5,
        "device": engine.device.kind,
    }


def register(app: FastAPI, engine: Engine, store: Store) -> None:
    # ------------------------------------------------------------ calibration presets & quick match
    @app.get("/api/calibration/presets")
    async def calibration_presets() -> dict[str, Any]:
        return {
            "presets": preset_listing(),
            "groups": {
                "claude": "Claude presets",
                "inspired": "Inspired by popular displays",
                "standard": "Standards",
            },
            "disclaimer": DISCLAIMER,
            "current": engine.calibration.preset,
        }

    @app.post("/api/calibration/preset/{pid}")
    async def calibration_preset(pid: str, body: PresetBody | None = None) -> dict[str, Any]:
        body = body or PresetBody()
        p = get_preset(pid)
        if p is None:
            raise HTTPException(404, f"no preset {pid!r}")
        c = p.calibration(engine.calibration, keep_balance=body.keep_balance)
        if body.apply:
            engine.set_calibration(c)
        return c.model_dump()

    @app.post("/api/calibration/quick")
    async def calibration_quick(body: QuickBody) -> dict[str, Any]:
        c = quick_match(body.room, body.use, body.tint, engine.calibration)
        if body.apply:
            engine.set_calibration(c)
        return c.model_dump()

    @app.post("/api/calibration/gains")
    async def calibration_gains(c: PanelCalibration) -> dict[str, Any]:
        """The effective per-channel gains of a calibration (white balance x temperature x peak)."""
        return {"gains": channel_gains(c), "temperature_gains": kelvin_gains(c.temperature)}

    # ------------------------------------------------------------------- test videos
    @app.get("/api/calibration/videos")
    async def calibration_videos() -> dict[str, Any]:
        return {
            "videos": [{"id": v.id, "name": v.name, "hint": v.hint} for v in CAL_VIDEOS.values()],
            "motion": [{"id": m.id, "name": m.name, "hint": m.hint} for m in MOTION_TESTS.values()],
            "fps": CAL_FPS,
        }

    @app.post("/api/calibration/test")
    async def calibration_test(body: CalTestBody) -> dict[str, Any]:
        """Play a calibration video on the panel: full screen through `a`, or A/B halves / a before-after wipe."""
        card = CalCard(
            video=body.video,
            a=body.a,
            b=body.b,
            layout=body.layout,
            split=body.split,
            labels=_labels(body.labels),
        )
        return engine.show_test(card, body.seconds)

    # -------------------------------------------------------------------- motion lab
    @app.get("/api/motion")
    async def motion_info() -> dict[str, Any]:
        d = engine.display()
        return {
            "presets": [p.model_dump() for p in MOTION_PRESETS],
            "limits": motion_limits(engine),
            "current": {
                "max_fps": d["max_fps"],
                "packet_gap_ms": d["packet_gap_ms"],
                "smoothing": d.get("smoothing", 0.0),
                "transition": store.get("transition", "push"),
                "preset": d.get("motion_preset"),
            },
            "tests": [{"id": m.id, "name": m.name, "hint": m.hint} for m in MOTION_TESTS.values()],
        }

    @app.post("/api/motion/test")
    async def motion_test(body: MotionTestBody) -> dict[str, Any]:
        """Run a motion test on the panel. `b` compares two configs (stacked or alternating); mode "clip" bakes
        config A as a native GIF loop instead (rate-limited: 20 s between uploads)."""
        card = MotionCard(
            test=body.test, a=body.a.cfg(), b=body.b.cfg() if body.b else None, layout=body.layout
        )
        if body.mode == "clip":
            r = await engine.show_test_clip(card, body.seconds)
            if not r["ok"]:
                raise HTTPException(
                    429, f"The panel needs a pause between loop uploads — try again in {r['wait']:.0f} s"
                )
            return r
        return engine.show_test(card, body.seconds)

    def apply_motion(
        max_fps: float, gap: float, transition: str, smoothing: float, pid: str
    ) -> dict[str, Any]:
        gap = max(MIN_SAFE_PACKET_GAP_MS, gap)
        engine.set_display(
            {"max_fps": max_fps, "packet_gap_ms": gap, "smoothing": smoothing, "motion_preset": pid}
        )
        store.set("transition", transition)
        engine.changed()
        return {
            "max_fps": max_fps,
            "packet_gap_ms": gap,
            "transition": transition,
            "smoothing": smoothing,
            "preset": pid,
        }

    @app.post("/api/motion/preset/{pid}")
    async def motion_preset(pid: str) -> dict[str, Any]:
        p = get_motion_preset(pid)
        if p is None:
            raise HTTPException(404, f"no motion preset {pid!r}")
        return apply_motion(p.max_fps, p.packet_gap_ms, p.transition, p.smoothing, p.id)

    @app.post("/api/motion/autotune")
    async def motion_autotune(body: AutotuneBody | None = None) -> dict[str, Any]:
        """Stream the heaviest motion test at the ceiling rate for a few seconds, measure what the link delivered,
        and recommend (or apply) settings within the verified bounds."""
        body = body or AutotuneBody()
        card = MotionCard(test="pan", a=MotionCfg(fps=MOTION_MAX_FPS, speed=12, soft=True))
        prev_interval = engine.device.min_frame_interval
        engine.device.min_frame_interval = 1 / MOTION_MAX_FPS  # measure the link, not the current cap
        sent0 = engine.device.info.frames_sent
        t0 = time.monotonic()
        try:
            engine.show_test(card, body.seconds + 5)
            await asyncio.sleep(body.seconds)
        finally:
            engine.device.min_frame_interval = prev_interval
        measured = (engine.device.info.frames_sent - sent0) / max(0.1, time.monotonic() - t0)
        frame_bytes = len(card.frames(1.0)[1].to_png())
        rec = autotune(measured, frame_bytes)
        out = {**rec.model_dump(), "measured_fps": round(measured, 2), "frame_bytes": frame_bytes}
        if body.apply:
            out["applied"] = apply_motion(
                rec.max_fps, rec.packet_gap_ms, rec.transition, rec.smoothing, "auto"
            )
        return out
