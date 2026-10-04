"""Camera / screen / sound in the web app (providers/webmedia.py), fed with synthetic frames and samples.

In the browser the page captures (web/webapp/host-media.js) and the worker forwards to `web_main.media_*`; here a
fake bridge stands in for the page, so the providers are tested on the desktop without Pyodide.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from deskdot import platforms, web_main
from deskdot.apps.live import Camera, CameraSettings, Mirror, MirrorSettings, Visualizer
from deskdot.config import Store
from deskdot.providers import build_hub, webmedia
from deskdot.providers.camera import CameraProvider
from deskdot.providers.capture import AudioProvider, ScreenProvider
from deskdot.providers.webmedia import WebAudioProvider, WebCameraProvider, WebScreenProvider


class FakePage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def want(self, kind: str, opts: str) -> None:
        self.calls.append(("want", kind, json.loads(opts)))

    def stop(self, kind: str) -> None:
        self.calls.append(("stop", kind, None))


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakePage]:
    monkeypatch.setattr(platforms, "current", lambda: "web")
    page = FakePage()
    webmedia.set_bridge(page)
    yield page
    webmedia.set_bridge(None)
    webmedia._live.clear()


def _hub(settings: dict[str, Any] | None = None) -> Any:
    changes: list[str] = []
    data = dict(settings or {})
    store = SimpleNamespace(get=lambda k, d=None: data.get(k, d), set=data.__setitem__)
    return SimpleNamespace(store=store, on_change=changes.append, changes=changes)


def _rgb(w: int, h: int, color: tuple[int, int, int]) -> bytes:
    return bytes(np.tile(np.array(color, np.uint8), (h, w, 1)).tobytes())


# ------------------------------------------------------------------ platform wiring
def test_features_and_apps_on_the_web() -> None:
    for f in ("screen", "camera", "audio", "audio_loopback"):
        assert platforms.supported(f, "web")
    for f in ("screen_window", "media", "window", "idle", "system", "onair", "notifications"):
        assert not platforms.supported(f, "web")
    for app in (Mirror, Camera, Visualizer):
        assert "web" in app.platforms and "android" not in app.platforms
        assert set(platforms.DESKTOP) <= set(app.platforms)


def test_desktop_hub_keeps_the_desktop_providers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for plat in ("windows", "macos", "linux", "android"):
        monkeypatch.setattr(platforms, "current", lambda plat=plat: plat)
        hub = build_hub(Store(tmp_path / "state.json"), lambda _n: None)
        assert type(hub.get("screen")) is ScreenProvider
        assert type(hub.get("camera")) is CameraProvider
        assert type(hub.get("audio")) is AudioProvider


def test_web_hub_swaps_in_the_browser_providers(tmp_path: Path, web: FakePage) -> None:
    hub = build_hub(Store(tmp_path / "state.json"), lambda _n: None)
    assert isinstance(hub.get("screen"), WebScreenProvider)
    assert isinstance(hub.get("camera"), WebCameraProvider)
    assert isinstance(hub.get("audio"), WebAudioProvider)
    assert hub.get("camera").supported and hub.get("camera").feature == "camera"


# ------------------------------------------------------------------ camera
def test_camera_asks_the_page_only_while_held(web: FakePage) -> None:
    p = WebCameraProvider(_hub())
    p.push_frame(4, 4, _rgb(4, 4, (255, 0, 0)))
    assert p.value is None, "frames nobody asked for are dropped"
    p.acquire()
    p.acquire()
    assert web.calls == [("want", "camera", {"index": 0})], "one request however many holders"
    assert p._task is None, "push-based: no polling task"
    p.configure(1, "natural", True, CameraSettings())
    assert web.calls[-1] == ("want", "camera", {"index": 1}), "switching cameras reopens the stream"
    p.release()
    assert web.calls[-1][0] == "want"
    p.release()
    assert web.calls[-1] == ("stop", "camera", None)
    assert p.value is None


@pytest.mark.parametrize("style", ["natural", "pop", "neon", "thermal", "mono"])
def test_camera_frames_become_panel_pictures(web: FakePage, style: str) -> None:
    p = WebCameraProvider(_hub())
    p.configure(0, style, True, CameraSettings())
    p.acquire()
    w, h = 160, 120
    img = np.zeros((h, w, 3), np.uint8)
    img[:, : w // 2] = (230, 40, 20)  # left half red: edges for "neon"
    img[30:90, 60:100] = (20, 200, 255)
    web_main.media_frame("camera", w, h, img.tobytes())  # the worker's entry point
    v = p.value
    assert isinstance(v, np.ndarray) and v.shape == (32, 32, 3) and v.dtype == np.uint8
    assert v.any(), "something lights up"
    assert p.updated > 0


def test_states_from_the_page(web: FakePage) -> None:
    hub = _hub()
    p = WebCameraProvider(hub)
    p.acquire()
    web_main.media_state("camera", "waiting", "Camera Mirror needs your camera.")
    assert p.error is None and p.stream == "waiting", "waiting = the app's loading animation"
    web_main.media_state("camera", "denied", "The camera is blocked for this site.")
    assert p.error == "The camera is blocked for this site." and hub.changes == ["camera"]
    assert p.snapshot()["stream"] == "denied"
    web_main.media_frame("camera", 8, 8, _rgb(8, 8, (0, 255, 0)))
    assert p.error is None and p.value is not None, "a frame clears the error"


def test_page_reload_repeats_the_request(web: FakePage) -> None:
    p = WebScreenProvider(_hub())
    q = WebCameraProvider(_hub())
    p.acquire()
    web.calls.clear()
    web_main.media_hello()
    assert web.calls == [("want", "screen", {})], "only what is still held"
    assert q._refs == 0


def test_unsupported_host_never_asks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platforms, "current", lambda: "android")
    page = FakePage()
    webmedia.set_bridge(page)
    try:
        p = WebScreenProvider(_hub())
        p.acquire()
        assert page.calls == [] and "not available on Android" in (p.error or "")
    finally:
        webmedia.set_bridge(None)
        webmedia._live.clear()


# ------------------------------------------------------------------ screen
def test_screen_letterboxes_a_wide_screen(web: FakePage) -> None:
    p = WebScreenProvider(_hub())
    p.configure("full", 128, "contain", MirrorSettings(auto_exposure=False, black_point=0))
    p.acquire()
    p.push_frame(192, 108, _rgb(192, 108, (200, 200, 200)))
    v = p.value
    assert v.shape == (32, 32, 3)
    assert not v[0].any() and not v[-1].any(), "16:9 fits with black bars top and bottom"
    assert v[16].any()


@pytest.mark.parametrize("mode,fit", [("full", "cover"), ("ambilight", "contain"), ("window", "contain")])
def test_screen_modes(web: FakePage, mode: str, fit: str) -> None:
    p = WebScreenProvider(_hub())
    p.configure(mode, 128, fit, MirrorSettings())
    p.acquire()
    rng = np.random.default_rng(1)
    p.push_frame(192, 108, rng.integers(0, 255, (108, 192, 3), dtype=np.uint8).tobytes())
    assert p.value.shape == (32, 32, 3) and p.value.any()


def test_short_or_bad_frames_are_ignored(web: FakePage) -> None:
    p = WebScreenProvider(_hub())
    p.acquire()
    p.push_frame(10, 10, b"\x00" * 20)
    p.push_frame(0, 10, b"")
    assert p.value is None


# ------------------------------------------------------------------ audio
DESKTOP_KEYS = {
    "bands",
    "peaks",
    "level",
    "wave",
    "bass",
    "mid",
    "treble",
    "beat",
    "beats",
    "bpm",
    "music",
    "source",
    "t",
}


def _tone(hz: float, n: int = 2048, sr: float = 48000.0, amp: float = 0.4, t0: int = 0) -> np.ndarray:
    t = (np.arange(n) + t0) / sr
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_audio_has_the_desktop_shape(web: FakePage) -> None:
    p = WebAudioProvider(_hub({"audio_source": "mic"}))
    p.acquire()
    assert web.calls == [("want", "audio", {"source": "mic"})]
    for i in range(6):
        web_main.media_audio(48000, _tone(440, t0=i * 2048).tobytes(), "mic")
    v = p.value
    assert set(v) == DESKTOP_KEYS
    assert len(v["bands"]) == 32 and len(v["peaks"]) == 32 and len(v["wave"]) == 32
    assert v["music"] is True and v["source"] == "mic" and 0.2 < v["level"] < 0.4
    edges = np.geomspace(40, 16000, 33)
    band = int(np.searchsorted(edges, 440)) - 1
    assert int(np.argmax(v["bands"])) in (band - 1, band, band + 1), "the tone lands in its band"
    assert all(0 <= b <= 1 for b in v["bands"])


def test_audio_beats_and_tempo(web: FakePage) -> None:
    p = WebAudioProvider(_hub())
    p.acquire()
    sr, n = 48000.0, 2048
    dt = n / sr  # one block every ~43 ms, like the page's ScriptProcessorNode
    for i in range(140):  # 6 s of a kick drum at 120 bpm (every 0.5 s)
        now = i * dt
        kick = (now % 0.5) < dt
        block = _tone(60, amp=0.8) if kick else _tone(3000, amp=0.02, t0=i * n)
        p.push_audio(sr, block, "system", now=now)
    v = p.value
    assert v["beats"] >= 8
    assert 110 <= v["bpm"] <= 130


def test_audio_source_change_reasks_the_page(web: FakePage) -> None:
    hub = _hub({"audio_source": "system"})
    p = WebAudioProvider(hub)
    p.restart()
    assert web.calls == [], "not held: nothing to restart"
    p.acquire()
    hub.store.set("audio_source", "mic")
    p.restart()
    assert web.calls == [("want", "audio", {"source": "system"}), ("want", "audio", {"source": "mic"})]


# ------------------------------------------------------------------ apps on the web
async def test_pet_asks_for_sound_only_when_dancing(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    class Held:  # counts holders without opening a real sound device
        _refs = 0
        value = None

        def acquire(self) -> None:
            self._refs += 1

        def release(self) -> None:
            self._refs -= 1

    audio = Held()
    monkeypatch.setitem(engine.hub.providers, "audio", audio)
    monkeypatch.setattr(
        "deskdot.apps.pets.current_platform", lambda: "web"
    )  # desktop pets hold audio throughout
    slot = engine._slot("pet")
    engine._show(slot)
    try:
        assert audio._refs == 0, "a pet that doesn't dance never opens the mic"
        slot.app.settings = slot.app.settings.model_copy(update={"music_sync": True})
        slot.app.on_settings()
        assert audio._refs == 1
    finally:
        engine._hide(slot)
    assert audio._refs == 0


async def test_desktop_pet_still_holds_sound_throughout(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("deskdot.apps.pets.current_platform", lambda: "windows")
    slot = engine._slot("pet")
    assert tuple(slot.app.uses) == ("audio",)
