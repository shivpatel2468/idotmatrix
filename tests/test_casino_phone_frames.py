"""Live panel frames on a phone socket (/ws/p/{code}): only after the phone opts in ({"type": "frames", "on": true}),
as binary 32x32x3 RGB messages; old pages that never ask get text only."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _client(tmp_path: Path) -> Any:
    from fastapi.testclient import TestClient

    from deskdot.config import Config
    from deskdot.server import create_app

    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def _until_bytes(ws: Any, limit: int = 200) -> bytes:
    for _ in range(limit):
        m = ws.receive()
        if m.get("bytes") is not None:
            return m["bytes"]  # type: ignore[no-any-return]
    raise AssertionError("no frame arrived")


def test_phone_gets_frames_only_after_opting_in(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "casino_roulette"}).json()["code"]
        with c.websocket_connect(f"/ws/p/{code}?cid=framesCID01") as a:
            first = [a.receive() for _ in range(3)]  # hello, roster, states … never a frame
            assert all(m.get("bytes") is None and m.get("text") for m in first)
            assert json.loads(first[0]["text"])["type"] == "hello"

            a.send_text(json.dumps({"type": "frames", "on": True}))
            t0 = time.monotonic()
            fr = _until_bytes(a)
            assert len(fr) == 32 * 32 * 3 and time.monotonic() - t0 < 5
            fr2 = _until_bytes(a)  # and they keep coming (latest wins, <= 10 fps)
            assert len(fr2) == 32 * 32 * 3

            a.send_text(json.dumps({"type": "frames", "on": False}))
            a.send_text(json.dumps({"type": "ping", "t": 1}))
            # after the pong, nothing binary any more (one frame may have been in flight before "off")
            for _ in range(40):
                m = a.receive()
                if m.get("text") and json.loads(m["text"])["type"] == "pong":
                    break
            later = [a.receive() for _ in range(2)]
            assert all(m.get("bytes") is None for m in later)
