"""Cross-platform compatibility (docs/COMPATIBILITY.md).

* Every provider and app module imports — and the engine serves /api/meta — when the platform-specific modules
  are missing (winrt, pyobjc, psutil, soundcard, OpenCV, bleak, winreg, syncedlyrics) and `sys.platform` says
  Windows, macOS, Linux or Android. Each case runs in a fresh interpreter so nothing leaks into this one.
* /api/meta reports the host platform, feature support and the `platforms` markers on apps and settings.
* On a host that lacks a feature, providers report it instead of polling, and apps render their
  "not on <OS>" state without exceptions.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot import platforms
from deskdot.config import Config
from deskdot.engine import REGISTRY
from deskdot.gfx import Frame
from deskdot.server import create_app

ROOT = Path(__file__).resolve().parents[1]

# modules that only exist on some hosts (or may fail to install there)
BLOCKED = (
    "winrt",
    "winreg",
    "AppKit",
    "Quartz",
    "Foundation",
    "objc",
    "psutil",
    "soundcard",
    "cv2",
    "bleak",
    "syncedlyrics",
    "java",
)

PROBE = textwrap.dedent(
    """
    import importlib, importlib.abc, json, pkgutil, sys, tempfile
    from pathlib import Path

    BLOCKED = set(json.loads(sys.argv[1]))
    for name in list(sys.modules):  # nothing pre-imported may leak through
        if name.split(".")[0] in BLOCKED:
            del sys.modules[name]

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ImportError(f"{name} blocked for this test")
            return None

    sys.meta_path.insert(0, Block())

    # stdlib / core deps first, under the real platform (asyncio picks its loop implementation at import)
    import asyncio, ctypes, sqlite3, subprocess, numpy, PIL.Image, PIL.ImageGrab, pydantic, httpx, fastapi
    from fastapi.testclient import TestClient

    sys.platform = sys.argv[2]
    if sys.argv[2] == "android":
        sys.getandroidapilevel = lambda: 34

    import deskdot
    failed = []
    for mod in pkgutil.walk_packages(deskdot.__path__, "deskdot."):
        if mod.name == "deskdot.__main__" or mod.name.startswith(("deskdot.fly", "deskdot.mcp_server", "deskdot.device.ble", "deskdot.android_main")):
            continue  # fly: optional brain data; mcp: optional extra; ble: needs bleak by design (desktop only)
        try:
            importlib.import_module(mod.name)
        except Exception as e:
            failed.append(f"{mod.name}: {type(e).__name__}: {e}")
    from deskdot import platforms
    from deskdot.config import Config
    from deskdot.server import create_app

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(device="sim", data_dir=Path(tmp), plugins_dir=Path(tmp) / "plugins")
        with TestClient(create_app(cfg)) as c:
            meta = c.get("/api/meta").json()
            for app_id in ("sysmon", "activeapp", "nowplaying"):  # host-dependent providers start (or decline)
                assert c.post(f"/api/apps/{app_id}/activate").status_code == 200
                assert c.get("/api/state").status_code == 200
    print(json.dumps({
        "failed": failed,
        "platform": meta["platform"],
        "current": platforms.current(),
        "apps": len(meta["apps"]),
        "unsupported": sorted(a["id"] for a in meta["apps"] if a.get("supported") is False),
    }))
    """
)


@pytest.mark.parametrize("plat", ["win32", "darwin", "linux", "android"])
def test_imports_and_meta_without_platform_modules(plat: str) -> None:
    r = subprocess.run(
        [sys.executable, "-c", PROBE, json.dumps(BLOCKED), plat],
        capture_output=True,
        text=True,
        timeout=240,
        cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr[-4000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["failed"] == []
    expect = {"win32": "windows", "darwin": "macos", "linux": "linux", "android": "android"}[plat]
    assert out["platform"] == out["current"] == expect
    assert out["apps"] > 50
    if expect == "android":
        assert {"nowplaying", "activeapp", "mirror", "camera", "visualizer"} <= set(out["unsupported"])
    else:
        assert out["unsupported"] == []


# ------------------------------------------------------------------ platform detection
def test_current_platform_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    for value, expect in (
        ("win32", "windows"),
        ("darwin", "macos"),
        ("linux", "linux"),
        ("android", "android"),
    ):
        monkeypatch.setattr(sys, "platform", value)
        platforms.current.cache_clear()
        assert platforms.current() == expect
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "getandroidapilevel", lambda: 34, raising=False)
    platforms.current.cache_clear()
    assert platforms.current() == "android"  # Chaquopy before Python 3.13 says "linux"
    monkeypatch.undo()
    platforms.current.cache_clear()


def test_platform_labels() -> None:
    assert platforms.label(["windows", "macos"]) == "Windows/macOS only"
    assert platforms.only_on(feature="onair", group="X") == {"platforms": ["windows"], "group": "X"}
    assert platforms.supported("onair", "linux") is False
    assert platforms.supported("no-such-feature", "android") is True


# ------------------------------------------------------------------ /api/meta markers
def _meta(tmp_path: Path) -> dict[str, Any]:
    cfg = Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")
    with TestClient(create_app(cfg)) as c:
        return c.get("/api/meta").json()


def test_meta_reports_platform_and_markers(tmp_path: Path) -> None:
    meta = _meta(tmp_path)
    assert meta["platform"] == platforms.current()
    assert meta["platform_label"].startswith(platforms.LABELS[platforms.current()])
    assert set(meta["features"]) == set(platforms.FEATURES)
    apps = {a["id"]: a for a in meta["apps"]}
    np_ = apps["nowplaying"]
    assert np_["platforms"] == list(platforms.DESKTOP) and np_["schema"]["platforms"] == np_["platforms"]
    assert apps["clock"]["platforms"] is None and "platforms" not in apps["clock"]["schema"]
    mode = apps["mirror"]["schema"]["properties"]["mode"]
    assert mode["enumPlatforms"]["window"] == list(platforms.FEATURES["screen_window"])
    assert "full" not in mode["enumPlatforms"]
    assert apps["pet"]["schema"]["properties"]["music_sync"]["platforms"] == list(platforms.FEATURES["audio"])


def test_meta_on_android_marks_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platforms, "current", lambda: "android")
    meta = _meta(tmp_path)
    assert meta["platform"] == "android"
    assert meta["features"]["media"] is False and meta["features"]["system"] is True
    apps = {a["id"]: a for a in meta["apps"]}
    assert apps["nowplaying"]["supported"] is False
    assert apps["clock"]["supported"] is True


# ------------------------------------------------------------------ unsupported states
GATED = [cls.id for cls in REGISTRY.values() if cls.platforms]


@pytest.mark.parametrize("app_id", GATED)
async def test_apps_render_unsupported_state(engine, monkeypatch: pytest.MonkeyPatch, app_id: str) -> None:  # type: ignore[no-untyped-def]
    # a host the app doesn't support: Android for desktop-only apps, the browser for System Monitor
    host = next(h for h in ("android", "web") if h not in REGISTRY[app_id].platforms)
    monkeypatch.setattr(platforms, "current", lambda: host)
    slot = engine._slot(app_id)
    engine._hold(slot)  # acquiring an unsupported provider must not start polling
    try:
        for name in slot.app.uses:
            p = engine.hub.get(name)
            if p.feature and not platforms.supported(p.feature):
                assert p.supported is False and p._task is None
                assert f"not available on {platforms.LABELS[host]}" in (p.error or "")
                assert p.snapshot()["supported"] is False
        assert slot.app.relevant() is False  # the playlist skips it
        for t in (0.0, 1.3):
            f = Frame()
            slot.app.render(f, t)
            assert f.px.any(), f"{app_id} drew nothing"
    finally:
        engine._release(slot)


async def test_settings_marked_unsupported_still_render(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(platforms, "current", lambda: "android")
    for app_id, settings in (("pet", {"music_sync": True}), ("petworld", {"music_sync": True})):
        engine.store.section("apps")[app_id] = settings
        slot = engine._slot(app_id)
        f = Frame()
        slot.app.render(f, 0.5)
        assert slot.app.kind() in ("stream", "clip")


# ------------------------------------------------------------------ degraded data
async def test_system_provider_survives_hidden_metrics(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    import psutil

    from deskdot.providers.system import SystemProvider

    def denied(*_a: Any, **_k: Any) -> Any:
        raise PermissionError("/proc/stat")  # what Android 8+ does to apps

    for fn in ("cpu_percent", "net_io_counters", "boot_time", "sensors_battery"):
        monkeypatch.setattr(psutil, fn, denied)
    p = SystemProvider(engine.hub)
    v = await p.fetch()
    assert v["cpu"] is None and v["net_down"] is None and v["uptime"] is None and v["battery"] is None
    assert v["ram"] is not None
    p.value = v
    engine.hub.providers["system"] = p
    for layout in ("bars", "graph"):
        engine.store.section("apps")["sysmon"] = {"layout": layout}
        engine.slots.pop("sysmon", None)
        f = Frame()
        engine._slot("sysmon").app.render(f, 0.0)
        assert f.px.any()


def test_linux_mpris_parsing() -> None:
    from deskdot.providers.media_linux import SEP, parse_line

    line = SEP.join(
        ["Playing", "Song", "Artist", "Album", "215000000", "12500000", "https://i.scdn.co/x.jpg", "spotify"]
    )
    s = parse_line(line, sampled=1.0)
    assert s is not None and s.playing and s.title == "Song" and s.app == "spotify"
    assert s.duration == 215.0 and s.position == 12.5 and s.art_url == "https://i.scdn.co/x.jpg"
    paused = parse_line(SEP.join(["Paused", "T", "", "", "", "", "file:///tmp/a.png", "vlc"]))
    assert paused is not None and not paused.playing and paused.art_url is None and not paused.position_known
    assert parse_line(SEP.join(["Stopped", "T", "", "", "", "", "", "vlc"])) is None
    assert parse_line("garbage") is None


def test_window_names_work_without_exe_suffix() -> None:
    from deskdot.providers.window import category_of, friendly_name

    assert friendly_name("code") == "VS Code" and category_of("code") == "code"  # Linux process names
    assert friendly_name("Spotify.exe") == "Spotify" and friendly_name("") == "Desktop"
