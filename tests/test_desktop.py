"""The installed desktop app's start-up (src/deskdot/desktop.py) and the launcher's frozen-app commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from deskdot import desktop as D
from deskdot import launcher as L


def test_home_dir_per_platform(tmp_path: Path) -> None:
    assert D.home_dir("win32", {"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "DeskDot"
    assert D.home_dir("darwin", {}) == Path.home() / "Library" / "Application Support" / "DeskDot"
    assert D.home_dir("linux", {"XDG_DATA_HOME": str(tmp_path)}) == tmp_path / "deskdot"
    assert D.home_dir("win32", {"DESKDOT_HOME": str(tmp_path / "x")}) == tmp_path / "x"


def test_first_run_copies_the_example_once(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "deskdot.example.toml").write_text('port = 8765\naddress = ""\n', encoding="utf-8")
    home = tmp_path / "home"
    toml = D.first_run(home, bundle)
    assert toml == home / "deskdot.toml" and 'address = ""' in toml.read_text(encoding="utf-8")
    assert (home / "data").is_dir() and (home / "plugins").is_dir()
    toml.write_text('address = "mine"\n', encoding="utf-8")
    D.first_run(home, bundle)  # never overwrites the user's file
    assert toml.read_text(encoding="utf-8") == 'address = "mine"\n'


def test_the_repo_example_config_has_no_personal_values() -> None:
    text = (D.bundle_dir() / "deskdot.example.toml").read_text(encoding="utf-8")
    assert 'address = ""' in text  # never a real panel MAC in the file every install starts from


def test_frozen_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = L.LauncherConfig(config_path=tmp_path / "deskdot.toml")
    assert L.engine_command(cfg)[1:4] == ["-m", "deskdot", "serve"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DeskDot.exe"))
    assert L.engine_command(cfg) == [
        str(tmp_path / "DeskDot.exe"),
        "serve",
        "--config",
        str(tmp_path / "deskdot.toml"),
    ]
    assert L.autostart_command(cfg) == [str(tmp_path / "DeskDot.exe"), "--background"]
