"""DeskDot Launcher: page route, hotkey parsing, config, start-with-login (never written unless enabled)."""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from deskdot import launcher as L
from deskdot.config import Config


# ------------------------------------------------------------------ the page route
def _client(tmp_path: Path) -> TestClient:
    from deskdot.server import create_app

    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def test_launcher_page_served_from_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import deskdot.server as server

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<p>studio</p>", encoding="utf-8")
    (dist / "launcher.html").write_text("<p>launcher page</p>", encoding="utf-8")
    monkeypatch.setattr(server, "WEB_DIST", dist)
    with _client(tmp_path / "data") as c:
        r = c.get("/launcher")
        assert r.status_code == 200 and "launcher page" in r.text
        assert r.headers["cache-control"] == "no-store"
        assert "studio" in c.get("/").text  # the studio mount still works next to it


def test_launcher_page_fallback_when_not_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import deskdot.server as server

    monkeypatch.setattr(server, "WEB_DIST", tmp_path / "missing")
    with _client(tmp_path / "data") as c:
        r = c.get("/launcher")
        assert r.status_code == 200 and "npm run build" in r.text


# ------------------------------------------------------------------ hotkeys
@pytest.mark.parametrize(
    ("text", "mods", "key"),
    [
        ("Ctrl+Alt+Space", {"ctrl", "alt"}, "space"),
        ("ctrl + alt + space", {"ctrl", "alt"}, "space"),
        ("Cmd+Shift+K", {"win", "shift"}, "k"),
        ("⌥Space".replace("⌥", "⌥+"), {"alt"}, "space"),
        ("option space", {"alt"}, "space"),
        ("F9", set(), "f9"),
        ("Win+`", {"win"}, "backquote"),
        ("Control+Return", {"ctrl"}, "enter"),
    ],
)
def test_parse_hotkey(text: str, mods: set[str], key: str) -> None:
    hk = L.parse_hotkey(text)
    assert hk.mods == frozenset(mods) and hk.key == key


@pytest.mark.parametrize("bad", ["", "Ctrl+Alt", "Space", "Ctrl+A+B", "Ctrl+Banana", "F30"])
def test_parse_hotkey_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        L.parse_hotkey(bad)


def test_hotkey_round_trip_and_win32_codes() -> None:
    hk = L.parse_hotkey("alt+ctrl+space")
    assert str(hk) == "Ctrl+Alt+Space"
    assert L.parse_hotkey(str(hk)) == hk
    mods, vk = L.win_hotkey(hk)
    assert mods == 0x0001 | 0x0002 | L.MOD_NOREPEAT and vk == 0x20
    assert L.win_hotkey(L.parse_hotkey("Win+Shift+K")) == (0x0008 | 0x0004 | L.MOD_NOREPEAT, ord("K"))
    assert L.win_hotkey(L.parse_hotkey("Ctrl+F12"))[1] == 0x7B
    assert L.MAC_KEYCODES["space"] == 49 and L.MAC_KEYCODES["k"] == 40


def test_config_reads_toml_and_env(tmp_path: Path) -> None:
    cfg_file = tmp_path / "deskdot.toml"
    cfg_file.write_text('port = 8800\nlauncher_hotkey = "Ctrl+Shift+D"\n', encoding="utf-8")
    cfg = L.load_launcher_config(cfg_file, env={})
    assert cfg.url == "http://127.0.0.1:8800"
    assert str(cfg.hotkey) == "Ctrl+Shift+D"
    assert cfg.autostart is False  # off by default
    assert cfg.project_dir == tmp_path.resolve() and cfg.config_path == cfg_file.resolve()
    env = {"DESKDOT_URL": "http://10.0.0.2:8765/", "DESKDOT_LAUNCHER_HOTKEY": "nonsense+key"}
    cfg2 = L.load_launcher_config(cfg_file, env=env)
    assert cfg2.url == "http://10.0.0.2:8765"
    assert str(cfg2.hotkey) == L.DEFAULT_HOTKEY  # a bad hotkey falls back instead of crashing
    assert L.load_launcher_config(tmp_path / "none.toml", env={}).url == L.DEFAULT_URL


def test_engine_config_ignores_launcher_keys(tmp_path: Path) -> None:
    from deskdot.config import load_config

    f = tmp_path / "deskdot.toml"
    f.write_text(
        f'launcher_hotkey = "Ctrl+Alt+Space"\nlauncher_autostart = false\ndata_dir = "{(tmp_path / "d").as_posix()}"\n',
        encoding="utf-8",
    )
    assert load_config(f).port == 8765


# ------------------------------------------------------------------ start with login
class FakeReg:
    """Stands in for `winreg`: no real registry writes in tests."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.writes = 0

    class _Key:
        def __enter__(self) -> FakeReg._Key:
            return self

        def __exit__(self, *_: Any) -> None: ...

    def OpenKey(self, root: str, path: str, _res: int, _access: int) -> FakeReg._Key:
        assert root == "HKCU" and path == L.RUN_KEY
        return FakeReg._Key()

    def QueryValueEx(self, _k: Any, name: str) -> tuple[str, int]:
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def SetValueEx(self, _k: Any, name: str, _r: int, _t: int, value: str) -> None:
        self.writes += 1
        self.values[name] = value

    def DeleteValue(self, _k: Any, name: str) -> None:
        self.writes += 1
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def test_autostart_windows_registry_only_when_enabled() -> None:
    reg = FakeReg()
    assert not L.autostart_enabled(platform="win32", reg=reg)
    cmd = ["C:\\Py\\pythonw.exe", "-m", "deskdot", "launcher", "--background"]
    L.set_autostart(True, cmd, platform="win32", reg=reg)
    assert L.autostart_enabled(platform="win32", reg=reg)
    assert reg.values[L.RUN_VALUE].endswith("launcher --background")
    L.set_autostart(False, cmd, platform="win32", reg=reg)
    assert not L.autostart_enabled(platform="win32", reg=reg)
    L.set_autostart(False, cmd, platform="win32", reg=reg)  # removing twice is fine


def test_autostart_macos_launch_agent(tmp_path: Path) -> None:
    cmd = ["/usr/bin/python3", "-m", "deskdot", "launcher", "--background"]
    assert not L.autostart_enabled(platform="darwin", home=tmp_path)
    where = L.set_autostart(True, cmd, workdir=tmp_path, platform="darwin", home=tmp_path)
    plist = plistlib.loads(Path(where).read_bytes())
    assert plist["Label"] == L.LAUNCH_AGENT_ID and plist["ProgramArguments"] == cmd and plist["RunAtLoad"]
    assert L.autostart_enabled(platform="darwin", home=tmp_path)
    L.set_autostart(False, cmd, platform="darwin", home=tmp_path)
    assert not Path(where).exists()


def test_autostart_linux_desktop_entry(tmp_path: Path) -> None:
    where = L.set_autostart(
        True, ["/bin/python", "-m", "deskdot", "launcher"], platform="linux", home=tmp_path
    )
    assert "Exec=/bin/python -m deskdot launcher" in Path(where).read_text(encoding="utf-8")
    L.set_autostart(False, [], platform="linux", home=tmp_path)
    assert not L.autostart_enabled(platform="linux", home=tmp_path)


def test_launcher_main_never_writes_autostart_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(L, "set_autostart", lambda *a, **k: calls.append(a) or "x")
    monkeypatch.setattr(L, "autostart_enabled", lambda **_: False)
    monkeypatch.setattr(L, "send_control", lambda *_a, **_k: True)  # pretend an instance is running
    (tmp_path / "deskdot.toml").write_text("", encoding="utf-8")
    assert L.main(str(tmp_path / "deskdot.toml")) == 0
    assert calls == []  # default config: nothing written
    (tmp_path / "deskdot.toml").write_text("launcher_autostart = true\n", encoding="utf-8")
    L.main(str(tmp_path / "deskdot.toml"))
    assert len(calls) == 1 and calls[0][0] is True  # opted in through deskdot.toml
    calls.clear()
    assert L.main(str(tmp_path / "deskdot.toml"), autostart="off") == 0
    assert calls == [(False, L.autostart_command(L.load_launcher_config(tmp_path / "deskdot.toml")))]


def test_control_server_round_trip() -> None:
    got: list[str] = []
    srv = L.ControlServer(got.append, port=0)
    port = srv.sock.getsockname()[1]
    srv.start()
    try:
        assert L.send_control("toggle", port=port)
        assert got == ["toggle"]
    finally:
        srv.stop()
    assert not L.send_control("show", port=port)


def test_tray_image() -> None:
    img = L.tray_image(32)
    assert img.size == (32, 32) and img.mode == "RGBA"
