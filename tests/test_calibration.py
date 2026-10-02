"""Panel calibration maths, presets, animated test cards, motion lab and their endpoints (docs/CALIBRATION.md)."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from deskdot.config import Config, Store
from deskdot.gfx.calib import PanelCalibration, apply, channel_gains, kelvin_gains, lut
from deskdot.gfx.calib_presets import (
    MIN_SAFE_PACKET_GAP_MS,
    MOTION_PRESETS,
    PRESETS,
    autotune,
    quick_match,
)
from deskdot.gfx.image import GIF_BUDGET, encode_gif_budget
from deskdot.gfx.testvideo import (
    CAL_VIDEOS,
    CLIP_MAX_FPS,
    MOTION_MAX_FPS,
    MOTION_TESTS,
    CalCard,
    MotionCard,
    MotionCfg,
)
from deskdot.server import create_app

#: One BLE packet carries ~514 B; test-card frames must stay within two (they stream for minutes).
TWO_PACKETS = 2 * 514

# Golden values shared with web/src/lib/calib.ts (the studio preview mirrors this maths). Change both together.
GOLDEN_CAL = PanelCalibration(
    gamma=1.7,
    red=0.95,
    blue=0.9,
    lift=3,
    black_level=2,
    contrast=1.15,
    temperature=5000,
    gamma_blue=1.1,
    level=0.9,
)
GOLDEN_IDX = [0, 1, 2, 8, 32, 64, 128, 192, 255]
GOLDEN_LUT = [
    [0, 0, 0, 0, 7, 20, 70, 145, 218],
    [0, 0, 0, 0, 7, 19, 66, 137, 207],
    [0, 0, 0, 0, 5, 13, 49, 109, 171],
]


# ------------------------------------------------------------------------------------------- maths
def test_default_is_identity_and_passes_frames_through() -> None:
    c = PanelCalibration()
    assert c.identity
    px = np.random.default_rng(1).integers(0, 256, (32, 32, 3), dtype=np.uint8)
    assert apply(px, c) is px
    assert PanelCalibration(preset="sony_natural").identity  # the preset tag alone changes nothing


def test_old_calibrations_render_exactly_as_before() -> None:
    """New fields default to "no change": a stored v1 calibration keeps its exact LUT."""
    c = PanelCalibration(gamma=1.5, lift=5)
    t = lut(c)
    i = np.arange(256) / 255.0
    v = (i**1.5) * 255.0
    want = np.where(v > 0.5, 5 + v * 250 / 255, 0)
    assert np.array_equal(t[0], np.clip(np.round(want), 0, 255).astype(np.uint8))


def test_golden_lut_matches_the_studio_port() -> None:
    t = lut(GOLDEN_CAL)
    assert [[int(t[ch][i]) for i in GOLDEN_IDX] for ch in range(3)] == GOLDEN_LUT


def test_kelvin_gains() -> None:
    assert kelvin_gains(6500) == (1.0, 1.0, 1.0)
    warm = kelvin_gains(3400)
    cool = kelvin_gains(9000)
    assert warm[0] == 1.0 and warm[2] < warm[1] < 1.0  # warm: blue cut most
    assert cool[2] == 1.0 and cool[0] < 1.0  # cool: red cut
    assert all(0 < g <= 1.0 for k in range(3000, 9501, 250) for g in kelvin_gains(k))  # never brightens


def test_contrast_keeps_black_and_white() -> None:
    for k in (0.6, 0.8, 1.3, 1.6):
        t = lut(PanelCalibration(contrast=k))
        assert t[0][0] == 0 and t[0][255] == 255
    lo, hi = lut(PanelCalibration(contrast=0.7)), lut(PanelCalibration(contrast=1.4))
    assert hi[0][60] < 60 < lo[0][60] and hi[0][200] > 200 > lo[0][200]


def test_peak_level_and_per_channel_gamma() -> None:
    t = lut(PanelCalibration(level=0.8))
    assert t[0][255] == 204
    t = lut(PanelCalibration(gamma=1.5, gamma_blue=1.3))
    assert t[2][128] < t[0][128] == t[1][128]
    assert channel_gains(PanelCalibration(red=0.9, level=0.5)) == pytest.approx((0.45, 0.5, 0.5))


def test_dither_is_static_and_one_bit_safe() -> None:
    c = PanelCalibration(gamma=1.8, dither=True)
    flat = np.full((32, 32, 3), 60, np.uint8)
    out = apply(flat, c)
    assert len(np.unique(out)) == 2  # ordered dither between two neighbouring levels...
    assert np.array_equal(out, apply(flat, c))  # ...and identical every frame (no shimmer)
    pure = np.zeros((32, 32, 3), np.uint8)
    pure[::2, :, 0] = 255  # 1-bit content: full-on / full-off channels never change
    assert np.array_equal(apply(pure, c), pure)


def test_stale_stored_calibration_is_tolerated() -> None:
    c = PanelCalibration.load({"gamma": 1.5, "lift": 999, "contrast": "x", "temperature": 4000, "gone": 1})
    assert c.gamma == 1.5 and c.lift == 0 and c.contrast == 1.0 and c.temperature == 4000
    assert PanelCalibration.load(None).identity
    assert PanelCalibration.load(["junk"]).identity


# ------------------------------------------------------------------------------------------ presets
def test_presets_are_valid_distinct_and_in_range() -> None:
    ids = [p.id for p in PRESETS]
    assert len(ids) == len(set(ids))
    groups = {p.group for p in PRESETS}
    assert groups == {"claude", "inspired", "standard"}
    for p in PRESETS:
        c = p.calibration()
        assert c.preset == p.id
        sw = p.swatches()
        assert len(sw) == 7 and all(s.startswith("#") and len(s) == 7 for s in sw)
        if p.id != "native":
            assert not c.identity, p.id
    for p in PRESETS:
        if p.group == "inspired":
            assert p.name.split("-style")[0] and "-style" in p.name  # clearly "inspired by", never official
    for want in (
        "sony_natural",
        "sony_cinema",
        "lg_oled",
        "samsung_vivid",
        "apple_p3",
        "dell_srgb",
        "std_srgb",
        "std_rec709",
        "std_warm",
        "claude_quick",
        "claude_accurate",
        "claude_night",
        "claude_games",
        "claude_photo",
        "claude_lowglare",
    ):
        assert want in ids


def test_preset_keeps_the_measured_white_balance() -> None:
    p = next(p for p in PRESETS if p.id == "samsung_vivid")
    mine = PanelCalibration(red=1.0, green=0.9, blue=0.8, gamma=1.2)
    kept = p.calibration(mine, keep_balance=True)
    assert (kept.red, kept.green, kept.blue) == (1.0, 0.9, 0.8) and kept.saturation == 1.3
    fresh = p.calibration(mine, keep_balance=False)
    assert (fresh.red, fresh.green, fresh.blue) == (1.0, 1.0, 1.0)
    again = p.calibration(kept, keep_balance=True)  # applying twice never compounds
    assert again == kept


def test_quick_match_answers_move_the_right_way() -> None:
    base = quick_match("bright", "mixed", "neutral")
    dark = quick_match("dark", "mixed", "neutral")
    games = quick_match("bright", "games", "neutral")
    blue = quick_match("bright", "mixed", "blue")
    assert dark.temperature < base.temperature and dark.level < base.level
    assert games.saturation > base.saturation
    assert blue.blue < base.blue
    assert base.preset == "claude_quick"
    for room in ("bright", "dim", "dark"):
        for use in ("mixed", "text", "photos", "games"):
            for tint in ("neutral", "blue", "yellow", "green", "pink"):
                PanelCalibration.model_validate(quick_match(room, use, tint).model_dump())  # always in range


def test_motion_presets_respect_the_link_physics() -> None:
    for p in MOTION_PRESETS:
        assert p.packet_gap_ms >= MIN_SAFE_PACKET_GAP_MS
        assert p.max_fps <= MOTION_MAX_FPS
    assert autotune(30, 300).max_fps == 12  # a fast (simulated) link is still capped
    slow = autotune(3, 900)
    assert slow.max_fps >= 4 and slow.packet_gap_ms >= 30


# ------------------------------------------------------------------------------------- test cards
@pytest.mark.parametrize("video", sorted(CAL_VIDEOS))
def test_calibration_videos_are_small_fast_and_animated(video: str) -> None:
    a = PanelCalibration(gamma=1.5, lift=5)
    b = PanelCalibration(gamma=2.0, temperature=5000, dither=True)
    seen = set()
    t0 = time.perf_counter()
    for i in range(12):
        for card in (
            CalCard(video, a),
            CalCard(video, a, b, labels=("A", "B")),
            CalCard(video, PanelCalibration(), a, layout="wipe", split=11, labels=("OLD", "NEW")),
        ):
            ref, pan = card.frames(i * 0.5)
            assert len(pan.to_png()) <= TWO_PACKETS and len(ref.to_png()) <= TWO_PACKETS
            seen.add(ref.to_bytes())
    assert (time.perf_counter() - t0) / 36 < 0.05
    assert len(seen) > 3, "test videos move"


def test_ab_card_shows_the_same_content_in_both_halves() -> None:
    a, b = PanelCalibration(), PanelCalibration(gamma=2.0)
    ref, pan = CalCard("ramp", a, b).frames(1.0)
    assert np.array_equal(ref.px[:, :16], ref.px[:, 16:])  # the screen shows the reference twice
    assert np.array_equal(pan.px[:, :16], ref.px[:, :16])  # A = identity: left half untouched
    assert not np.array_equal(pan.px[:, 16:], ref.px[:, 16:])  # B corrected


@pytest.mark.parametrize("test", sorted(MOTION_TESTS))
def test_motion_tests_render_within_budget(test: str) -> None:
    card = MotionCard(test, MotionCfg(fps=8, soft=True, smoothing=0.3), MotionCfg(fps=12, transition="fade"))
    frames = {card.frames(i / 12)[1].to_bytes() for i in range(24)}
    assert len(frames) > 1
    assert all(len(card.frames(i / 12)[1].to_png()) <= TWO_PACKETS for i in range(0, 24, 5))
    alt = MotionCard(test, MotionCfg(fps=6), MotionCfg(fps=10), layout="alternate")
    alt.frames(0.0)
    alt.frames(MotionCard.ALT_SECONDS + 0.1)


@pytest.mark.parametrize("test", ["ufo", "ball", "scroll", "sweep"])
def test_motion_clips_fit_the_gif_budget(test: str) -> None:
    frames, durations = MotionCard(test, MotionCfg(fps=12, speed=8)).clip()
    assert len(frames) <= 96 and all(d >= round(1000 / CLIP_MAX_FPS) for d in durations)  # baked <= 10 fps
    assert len(encode_gif_budget(frames, durations)) <= GIF_BUDGET


def test_lower_fps_means_fewer_distinct_frames() -> None:
    def distinct(fps: float) -> int:
        return len({MotionCard("ufo", MotionCfg(fps=fps)).frames(i / 24)[0].to_bytes() for i in range(48)})

    assert distinct(4) < distinct(12)


# ------------------------------------------------------------------------------------------ engine
async def test_engine_streams_a_test_card_and_preview_gets_the_reference(engine) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    got = []
    engine.frame_listeners.add(got.append)
    await engine.start()
    card = CalCard("ramp", PanelCalibration(), PanelCalibration(gamma=2.0))
    engine.show_test(card)
    await asyncio.sleep(0.6)

    assert any(
        np.array_equal(f.px[:, :16], f.px[:, 16:]) for f in got[-3:]
    )  # reference, not the A/B panel frame
    assert engine.snapshot()["engine"]["test"]["kind"] == "calibration"
    started = engine.pattern[1]
    engine.show_test(CalCard("ramp", PanelCalibration(gamma=1.2), PanelCalibration(gamma=1.4)))
    assert engine.pattern[1] == started  # changing candidates keeps the video's clock
    engine.clear_pattern()
    await asyncio.sleep(0.3)
    assert engine.pattern is None
    await engine.stop()


async def test_stream_smoothing_converges(engine) -> None:  # type: ignore[no-untyped-def]
    from deskdot.gfx import Frame

    engine.store.set("display", {"smoothing": 0.5})
    a = engine._smooth(Frame(fill=(0, 0, 0)), True)
    b = engine._smooth(Frame(fill=(200, 0, 0)), True)
    assert 90 <= b.px[0, 0, 0] <= 110 and a.px[0, 0, 0] == 0
    for _ in range(12):
        c = engine._smooth(Frame(fill=(200, 0, 0)), True)
    assert c.px[0, 0, 0] == 200  # settles exactly
    assert engine._smooth(Frame(fill=(9, 9, 9)), False).px[0, 0, 0] == 9  # off for non-streams


# --------------------------------------------------------------------------------------- endpoints
def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def test_calibration_endpoints(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.get("/api/calibration/presets").json()
        assert len(r["presets"]) == len(PRESETS) and "not official" in r["disclaimer"]
        assert c.put("/api/calibration", json={"red": 1.0, "green": 0.9, "blue": 0.8}).status_code == 200
        got = c.post("/api/calibration/preset/lg_oled", json={"keep_balance": True}).json()
        assert got["preset"] == "lg_oled" and got["green"] == 0.9 and got["black_level"] == 6
        assert c.get("/api/calibration").json()["preset"] == "lg_oled"
        assert c.get("/api/state").json()["settings"]["calibration"]["contrast"] == 1.15
        assert c.post("/api/calibration/preset/nope", json={}).status_code == 404
        q = c.post("/api/calibration/quick", json={"room": "dark", "use": "photos", "tint": "blue"}).json()
        assert q["preset"] == "claude_quick" and q["dither"] is True
        assert c.get("/api/calibration").json()["preset"] == "lg_oled"  # quick match only previews by default
        assert c.put("/api/calibration", json={"temperature": 20000}).status_code == 422
        vids = c.get("/api/calibration/videos").json()
        assert {v["id"] for v in vids["videos"]} >= {"bars", "ramp", "skin", "sky", "wheel", "pulse"}
        r = c.post(
            "/api/calibration/test",
            json={"video": "sky", "a": {"gamma": 1.4}, "b": {"gamma": 2.0}, "labels": ["A", "B"]},
        )
        assert r.status_code == 200 and r.json()["pattern"] == "video:sky"
        assert c.get("/api/state").json()["engine"]["pattern"] == "video:sky"
        assert c.post("/api/calibration/test", json={"video": "nope"}).status_code == 422
        assert c.post("/api/calibration/pattern/gamma").status_code == 200  # first-generation still cards
        assert c.delete("/api/calibration/pattern").status_code == 200


def test_motion_endpoints(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        info = c.get("/api/motion").json()
        assert info["limits"]["packet_gap_min_ms"] == MIN_SAFE_PACKET_GAP_MS
        assert {p["id"] for p in info["presets"]} >= {"smoothest", "balanced", "ble_friendly"}
        r = c.post("/api/motion/test", json={"test": "ball", "a": {"fps": 6}, "b": {"fps": 12}})
        assert r.status_code == 200 and r.json()["fps"] == 12
        assert c.post("/api/motion/test", json={"test": "ball", "a": {"fps": 30}}).status_code == 422
        clip = c.post("/api/motion/test", json={"test": "ufo", "mode": "clip", "a": {"fps": 12}})
        assert clip.status_code == 200 and clip.json()["bytes"] <= GIF_BUDGET
        again = c.post("/api/motion/test", json={"test": "ufo", "mode": "clip"})
        assert again.status_code == 429  # GIF uploads are rate-limited (HARDWARE_PROTOCOL #16)
        p = c.post("/api/motion/preset/ble_friendly").json()
        assert p["max_fps"] == 6 and p["packet_gap_ms"] == 30
        st = c.get("/api/state").json()["settings"]
        assert st["display"]["max_fps"] == 6 and st["transition"] == "cut"
        assert c.patch("/api/display", json={"smoothing": 0.3}).json()["smoothing"] == 0.3
        assert c.patch("/api/display", json={"smoothing": 0.9}).status_code == 422
        assert c.post("/api/calibration/transfer/apply", json={"packet_gap_ms": 10}).status_code == 422
        tune = c.post("/api/motion/autotune", json={"seconds": 2}).json()
        assert 4 <= tune["max_fps"] <= 12 and tune["packet_gap_ms"] >= MIN_SAFE_PACKET_GAP_MS
        c.delete("/api/calibration/pattern")


def test_store_with_stale_calibration_still_boots(tmp_path: Path) -> None:
    Store(tmp_path / "state.json").set("calibration", {"gamma": 9, "lift": 4, "dither": "maybe"})
    with _client(tmp_path) as c:
        cal = c.get("/api/calibration").json()
        assert cal["lift"] == 4 and cal["gamma"] == 1.0


def test_choosing_an_app_ends_a_forgotten_test_card(tmp_path: Path) -> None:
    """A studio tab closed mid-calibration must not leave the test video on the panel."""
    from fastapi.testclient import TestClient

    from deskdot.config import Config
    from deskdot.server import create_app

    with TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "p"))) as c:
        assert c.post("/api/calibration/test", json={"video": "ramp"}).status_code == 200
        assert c.get("/api/state").json()["engine"].get("test")
        c.post("/api/apps/clock/activate", json={})
        assert not c.get("/api/state").json()["engine"].get("test")
