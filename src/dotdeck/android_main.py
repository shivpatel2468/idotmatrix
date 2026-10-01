"""Entry point for the DotDeck Android app (see docs/adr/0011 and android/).

The app's foreground service calls `run(files_dir)` once on a background thread; it blocks while the engine
serves the studio on port 8765 and holds the panel link through `device/android.py`. `stop()` (from the service's
onDestroy) asks uvicorn to shut down cleanly, which hands the panel off exactly like the desktop's Ctrl+C.

Configuration: `<files_dir>/dotdeck.toml` if present (same keys as on the desktop), with the phone's defaults
below. The studio stays reachable only from the phone itself unless `lan_studio = true` is set there; the
multiplayer controller pages are always reachable on the LAN, as on the desktop.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("dotdeck.android")
_server: Any = None


def _web_dist() -> Path | None:
    """The studio is packaged as the `dotdeck_web` package (extracted to disk by the app's build)."""
    try:
        import dotdeck_web  # type: ignore[import-not-found]
    except ImportError:
        return None
    return Path(next(iter(dotdeck_web.__path__))) / "dist"


def run(files_dir: str, port: int = 8765) -> None:
    global _server
    base = Path(files_dir)
    (base / "data").mkdir(parents=True, exist_ok=True)
    (base / "plugins").mkdir(parents=True, exist_ok=True)
    web = _web_dist()
    if web is not None and web.is_dir():
        os.environ["DOTDECK_WEB_DIST"] = str(web)  # read when dotdeck.server is imported (below)

    import uvicorn

    from .config import load_config
    from .server import create_app

    cfg = load_config(
        base / "dotdeck.toml",
        device="android",
        data_dir=base / "data",
        plugins_dir=base / "plugins",
        port=port,
    )
    logging.basicConfig(
        level=cfg.log_level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S"
    )
    log.info("DotDeck on Android: data in %s, studio %s", cfg.data_dir, web or "missing")
    # pure-Python protocol stacks: uvloop / httptools are not available on Android
    config = uvicorn.Config(
        create_app(cfg),
        host=cfg.host,
        port=cfg.port,
        log_level="warning",
        ws_ping_interval=20,
        loop="asyncio",
        http="h11",
        ws="websockets",
    )
    _server = uvicorn.Server(config)
    _server.run()
    _server = None


def stop() -> None:
    if _server is not None:
        _server.should_exit = True
