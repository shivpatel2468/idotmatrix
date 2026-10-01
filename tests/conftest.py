from __future__ import annotations

from pathlib import Path

import pytest

import dotdeck.apps  # noqa: F401 — registers built-in apps
from dotdeck.config import Config, Store
from dotdeck.device import SimDevice
from dotdeck.engine import Engine
from dotdeck.providers import build_hub


@pytest.fixture
async def engine(tmp_path: Path):  # type: ignore[no-untyped-def]
    cfg = Config(device="sim", data_dir=tmp_path)
    store = Store(tmp_path / "state.json")
    hub = build_hub(store, lambda _n: None)
    eng = Engine(cfg, store, SimDevice(bytes_per_second=1e7, min_frame_interval=0.0), hub)
    yield eng
    await hub.http.aclose()
