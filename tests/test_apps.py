"""Every app must render every one of its choices, fast, without providers having data."""

from __future__ import annotations

import gc
import itertools
import time
from typing import Any

import pytest

from dotdeck.engine import REGISTRY, AppSettings
from dotdeck.gfx import Frame


def _variants(cls: type) -> list[dict[str, Any]]:
    """Default settings plus one variant per option of every Choice field."""
    out: list[dict[str, Any]] = [{}]
    for name, field in cls.Settings.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and "enum" in extra:
            out += [{name: v} for v in extra["enum"]]
    return out


CASES = [(aid, v) for aid, cls in REGISTRY.items() for v in _variants(cls)]


@pytest.mark.parametrize(("app_id", "settings"), CASES, ids=[f"{a}-{list(s.values())}" for a, s in CASES])
async def test_render_all_variants(engine, app_id: str, settings: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
    engine.store.section("apps")[app_id] = settings
    slot = engine._slot(app_id)
    worst = 0.0
    gc.collect()  # time the render, not a full-heap collection that happens to land inside it
    gc.disable()
    try:
        for t in (0.0, 0.37, 1.9, 7.3):
            f = Frame()
            t0 = time.perf_counter()
            slot.app.render(f, t)
            worst = max(worst, time.perf_counter() - t0)
            assert f.px.shape == (32, 32, 3)
    finally:
        gc.enable()
    assert worst < 0.05, f"{app_id} render took {worst * 1000:.1f} ms"
    assert slot.app.kind() in ("stream", "clip", "native")


@pytest.mark.parametrize(
    "app_id",
    [
        a
        for a, c in REGISTRY.items()
        if c.id
        in (
            "agent",
            "ambient",
            "pixabots",
            "text",
            "sand",
            "raycaster",
            "brain",
            "focuspet",
            "boids",
            "synthwave",
            "wireframe",
        )
    ],
)
async def test_clips_bake(engine, app_id: str) -> None:  # type: ignore[no-untyped-def]
    engine.store.section("apps")[app_id] = (
        {"text": "A LONG MESSAGE THAT MUST SCROLL"} if app_id == "text" else {}
    )
    app = engine._slot(app_id).app
    if app.kind() != "clip":
        pytest.skip("not a clip in default settings")
    clip = app.clip_frames()
    assert 1 <= len(clip.frames) <= 200
    assert len(clip.durations_ms) == len(clip.frames)


def test_settings_schemas_are_json() -> None:
    import json

    for cls in REGISTRY.values():
        assert issubclass(cls.Settings, AppSettings)
        json.dumps(cls.Settings.model_json_schema())
        cls.Settings()  # defaults must be valid


def test_choice_rejects_unknown_option() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        REGISTRY["clock"].Settings(style="nope")


def test_ids_unique_and_complete() -> None:
    names = [c.name for c in REGISTRY.values()]
    assert len(set(names)) == len(names)
    for c in REGISTRY.values():
        assert c.description and c.icon and c.category


def test_canvas_pixel_art(engine) -> None:  # type: ignore[no-untyped-def]
    from dotdeck.apps.canvas import frame_from_rows

    f = frame_from_rows(["#.", ".#"], {"#": "#ff0000"})
    assert f.get(0, 0) == (255, 0, 0) and f.get(1, 0) == (0, 0, 0)
    with pytest.raises(ValueError):
        frame_from_rows(["x"], {})
    _ = list(itertools.islice(range(3), 1))


def test_app_icons_exist_in_the_studio_icon_set() -> None:
    """Apps name lucide icons; a name missing from the installed lucide-react renders as a blank square."""
    from pathlib import Path

    icons_dir = (
        Path(__file__).resolve().parents[1]
        / "web"
        / "node_modules"
        / "lucide-react"
        / "dist"
        / "esm"
        / "icons"
    )
    if not icons_dir.is_dir():
        pytest.skip("studio dependencies not installed (cd web && npm install)")
    names = {p.name.removesuffix(".mjs") for p in icons_dir.glob("*.mjs")}
    missing = {aid: cls.icon for aid, cls in REGISTRY.items() if cls.icon not in names}
    assert not missing, f"unknown lucide icons: {missing}"


def test_synthwave_loop_is_seamless() -> None:
    """The baked loop must wrap without a jump: frame N (one past the end) equals frame 0, at every speed."""
    from dotdeck.apps.synthwave import N_FRAMES, Synthwave, SynthwaveSettings

    class Ctx:
        data: dict[str, object] = {}  # noqa: RUF012

        def save(self) -> None: ...

    for speed in (0.5, 0.8, 1.0, 1.5, 2.0):
        app = Synthwave(Ctx(), SynthwaveSettings(speed=speed))  # type: ignore[arg-type]
        first, wrapped = Frame(), Frame()
        app.render(first, 0.0)
        app.render(wrapped, N_FRAMES / app.clip_fps)
        assert first == wrapped, f"speed {speed}: the loop jumps"
        clip = app.clip_frames()
        assert len(set(clip.durations_ms)) == 1, "an even frame rate"
