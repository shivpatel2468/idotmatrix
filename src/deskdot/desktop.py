"""The installed desktop app (Windows installer / macOS dmg, built from packaging/): `DeskDot.exe`, `DeskDot.app`.

Double-clicking DeskDot (no arguments):

1. uses a per-user folder for everything it writes — `%LOCALAPPDATA%\\DeskDot` on Windows,
   `~/Library/Application Support/DeskDot` on macOS (`DESKDOT_HOME` overrides it) — never the install folder;
2. on the first run copies the bundled `deskdot.example.toml` there as `deskdot.toml`;
3. starts the engine in the background (`DeskDot serve`, the same exe) unless one is already answering;
4. opens the studio in the browser (not with `--background`, which start-with-login uses);
5. runs the launcher (docs/LAUNCHERS.md): tray icon on Windows, the Ctrl+Alt+Space command bar.

Any other arguments go to the normal CLI: `DeskDot.exe serve --sim --port 8799`, `DeskDot.exe scan`, …
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import webbrowser
from pathlib import Path

APP_NAME = "DeskDot"
COMMANDS = {"serve", "scan", "doctor", "preview", "launcher", "-h", "--help"}


def bundle_dir() -> Path:
    """Where the read-only files are: PyInstaller's `_MEIPASS`, or the repo when run from source."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def home_dir(platform: str | None = None, env: dict[str, str] | None = None) -> Path:
    """The per-user folder for deskdot.toml, data/ and plugins/."""
    env = dict(os.environ) if env is None else env
    platform = platform or sys.platform
    if env.get("DESKDOT_HOME"):
        return Path(env["DESKDOT_HOME"])
    if platform == "win32":
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "deskdot"


def first_run(home: Path, bundle: Path) -> Path:
    """Create the folder and deskdot.toml (from the bundled example) if they aren't there. Returns the toml."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "plugins").mkdir(exist_ok=True)
    (home / "data").mkdir(exist_ok=True)
    toml = home / "deskdot.toml"
    if not toml.exists():
        example = bundle / "deskdot.example.toml"
        if example.is_file():
            shutil.copyfile(example, toml)
        else:
            toml.write_text('port = 8765\ndevice = "ble"\naddress = ""\n', encoding="utf-8")
    return toml


def _quiet_streams(home: Path) -> None:
    """A windowed app has no console: give print/logging somewhere to go (uvicorn calls sys.stdout.isatty())."""
    if sys.stdout is None or sys.stderr is None:
        log = (home / "data" / "deskdot.log").open("a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log


def prepare(env: dict[str, str] | None = None) -> Path:
    """Set up the per-user folder, the working directory and the env the engine reads. Returns deskdot.toml."""
    home = home_dir(env=env)
    bundle = bundle_dir()
    toml = first_run(home, bundle)
    os.chdir(home)  # data_dir / plugins_dir in deskdot.toml are relative to here
    os.environ.setdefault("DESKDOT_CONFIG", str(toml))
    web = bundle / "web" / "dist"
    if web.is_dir():
        os.environ.setdefault("DESKDOT_WEB_DIST", str(web))
    _quiet_streams(home)
    return toml


def run_app(toml: Path, background: bool) -> int:
    from .launcher import engine_alive, load_launcher_config, send_control, start_engine

    cfg = load_launcher_config(toml)
    if not engine_alive(cfg.url):
        start_engine(cfg)
    if not background:
        for _ in range(60):  # the studio answers within a few seconds
            if engine_alive(cfg.url):
                break
            time.sleep(0.5)
        webbrowser.open(cfg.url + "/")
    if send_control("hide"):
        return 0  # a launcher is already running (it keeps the tray)
    from .launcher import main as launcher_main

    return launcher_main(str(toml), background=True)


def main(argv: list[str] | None = None) -> None:
    import multiprocessing

    multiprocessing.freeze_support()
    args = list(sys.argv[1:] if argv is None else argv)
    toml = prepare()
    if args and args[0] in COMMANDS:
        from .cli import main as cli_main

        if args[0] in ("serve", "launcher") and "--config" not in args:
            args += ["--config", str(toml)]
        cli_main(args)
        return
    background = "--background" in args
    import logging

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S"
    )
    code = run_app(toml, background)
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
