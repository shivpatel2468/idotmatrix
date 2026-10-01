"""Static configuration (deskdot.toml + environment) and the persisted state store.

Precedence: CLI flags > environment (DESKDOT_*) > deskdot.toml > defaults.
The project was called DotDeck before; a `dotdeck.toml` and `DOTDECK_*` variables are still read as a fallback.
Runtime state the user changes from the studio (brightness, playlist, app
settings…) lives in data/state.json, written with a short debounce.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

log = logging.getLogger("deskdot.config")


class Config(BaseModel):
    # Listen on the local network so friends' phones can join multiplayer games. Safe by default: `LanGate` only
    # lets other devices reach the phone controller (with a room code); the studio/API stay on this computer.
    host: str = "0.0.0.0"
    lan_studio: bool = Field(
        default=False, description="Also allow the studio/API from other devices on the LAN"
    )
    port: int = 8765
    device: Literal["ble", "sim", "android"] = "ble"  # "android": inside the DeskDot Android app
    address: str | None = Field(
        default=None, description="Panel MAC (`deskdot scan`); empty = first IDM-* found"
    )
    max_fps: float = Field(default=12.0, ge=0.5, le=30, description="Upper bound on frames pushed over BLE")
    packet_gap_ms: float = Field(
        default=18.0, ge=0, le=200, description="Gap between BLE packets; the panel drops unpaced bursts"
    )
    data_dir: Path = Path("data")
    plugins_dir: Path = Path("plugins")
    log_level: str = "INFO"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"


def load_config(path: Path | None = None, **overrides: Any) -> Config:
    raw: dict[str, Any] = {}
    p = path or Path(os.environ.get("DESKDOT_CONFIG") or os.environ.get("DOTDECK_CONFIG") or "deskdot.toml")
    if path is None and not p.exists() and Path("dotdeck.toml").exists():
        p = Path("dotdeck.toml")  # the old name
    if p.exists():
        raw.update(tomllib.loads(p.read_text(encoding="utf-8")))
    for key in Config.model_fields:
        env = os.environ.get(f"DESKDOT_{key.upper()}", os.environ.get(f"DOTDECK_{key.upper()}"))
        if env is not None:
            raw[key] = env
    raw.update({k: v for k, v in overrides.items() if v is not None})
    if raw.get("address") == "":
        raw["address"] = None
    cfg = Config.model_validate(raw)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.media_dir.mkdir(parents=True, exist_ok=True)
    return cfg


class Store:
    """A JSON document on disk with debounced async saves.

    Keys (top level): brightness, power, flip, apps{id: settings}, app_data{id: any},
    playlist, active, location, units, transition.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        self._save_task: asyncio.Task[None] | None = None
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                log.error("state file unreadable (%s); starting fresh, old copy kept as .bak", e)
                path.replace(path.with_suffix(".bak"))

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save_soon()

    def section(self, key: str) -> dict[str, Any]:
        sec = self.data.setdefault(key, {})
        assert isinstance(sec, dict)
        return sec

    def save_soon(self, delay: float = 0.4) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.save_now()
            return
        if self._save_task and not self._save_task.done():
            return

        async def later() -> None:
            await asyncio.sleep(delay)
            self.save_now()

        self._save_task = loop.create_task(later())

    def save_now(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)
