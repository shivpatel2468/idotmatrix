"""The TV-only reveal (docs/TV_VIEW.md §3, `tv`): a casino round's outcome + the panel's clock, from the lock only.

Bets are frozen at the lock, so a TV may know the drawn outcome from then on (it animates the wheel / dice / reels
exactly like the panel); before the lock it must not, and phones never get it in their status.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

import deskdot.apps  # noqa: F401 — registers built-in apps
from deskdot.casino.table import LOCK_SECONDS
from deskdot.engine.app import REGISTRY
from deskdot.gfx import Frame


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def _table(app_id: str) -> Any:
    cls = REGISTRY[app_id]
    app = cls(object(), cls.Settings())
    app.session.clock = Clock()
    await app.action(
        "seat", {"player": 2, "joined": True, "name": "P2", "color": "#ff3f78", "pid": "pid00002"}
    )
    return app


@pytest.mark.parametrize(
    ("app_id", "spot"),
    [
        ("casino_roulette", "red"),
        ("casino_bigsix", "s1"),
        ("casino_sevens", "up"),
        ("casino_baccarat", "player"),
        ("casino_andarbahar", "andar"),
    ],
)
async def test_reveal_only_after_the_lock_and_never_for_phones(app_id: str, spot: str) -> None:
    app = await _table(app_id)
    clk = app.session.clock
    await app.action("casino", {"op": "bet", "spot": spot, "amount": 10, "player": 2})
    app.render(Frame(), clk.t)
    tv = app.tv_extra() or {}
    assert "reveal" not in tv, "betting: the outcome isn't drawn yet, and must not leak"
    await app.action("casino", {"op": "lock", "player": "host"})
    seen = 0
    for _ in range(200):
        clk.t += 0.1
        app.render(Frame(), clk.t)
        st = app.status()
        assert "reveal" not in st and "tv" not in st, "phones never get the TV reveal"
        assert "reveal" not in json.dumps(app.private_status(2) or {})
        if app.game.phase in ("locked", "spinning", "dealing", "result"):
            rv = (app.tv_extra() or {}).get("reveal")
            assert rv is not None, app.game.phase
            assert rv["outcome"] == app.game.outcome
            assert rv["round"] == app.game.nonce
            assert rv["lock_s"] == LOCK_SECONDS and rv["spin_s"] == app.Game.spin_seconds
            assert abs(rv["since_lock"] - (clk.t - app.game.locked_at)) < 1e-3
            assert abs(rv["at"] - time.time()) < 5
            seen += 1
        elif seen:
            assert "reveal" not in (app.tv_extra() or {}), "the next round's betting: gone again"
            break
    assert seen > 10


async def test_turn_games_and_housie_never_reveal() -> None:
    for app_id in ("casino_blackjack", "casino_holdem", "casino_teenpatti", "casino_housie"):
        app = await _table(app_id)
        assert not app.tv_reveal
        assert app.tv_extra() is None


async def test_roulette_reports_the_panels_wheel_angle() -> None:
    app = await _table("casino_roulette")
    clk = app.session.clock
    for _ in range(5):
        clk.t += 0.1
        app.render(Frame(), clk.t)
    w = (app.tv_extra() or {})["wheel"]
    assert w["rot"] == pytest.approx(app._rot, abs=1e-4)
    assert abs(w["at"] - time.time()) < 5


def test_tv_state_carries_tv_but_the_status_stays_public(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from deskdot.config import Config
    from deskdot.server import create_app

    with TestClient(
        create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins"))
    ) as c:
        c.post("/api/apps/casino_roulette/activate", json={})
        code = c.post("/api/tv").json()["code"]
        with c.websocket_connect(f"/ws/tv/{code}") as tv:
            end = time.monotonic() + 4
            while time.monotonic() < end:
                m = tv.receive()
                if m.get("text") is None:
                    continue
                msg = json.loads(m["text"])
                if msg["type"] == "state" and msg["app"] == "casino_roulette":
                    assert "tv" in msg and "reveal" not in msg["status"]
                    assert "reveal" not in (msg["tv"] or {})  # betting: nothing drawn yet
                    return
            raise AssertionError("no state")


async def test_status_clock_anchors_are_public_and_steady() -> None:
    """`status.clock`: the round's timers as engine wall-clock times — the same anchors for every device."""
    app = await _table("casino_roulette")
    clk = app.session.clock
    st = app.status()
    assert st["clock"]["lock_at"] is None and st["clock"]["ends_at"] is None
    await app.action("casino", {"op": "bet", "spot": "red", "amount": 10, "player": 2})
    a = app.status()["clock"]
    assert a["ends_at"] is not None and app.status()["clock"] == a, "constant between polls"
    await app.action("casino", {"op": "lock", "player": "host"})
    c = app.status()["clock"]
    assert c["lock_at"] is not None and c["reveal_at"] is not None
    assert c["reveal_at"] - c["lock_at"] == pytest.approx(LOCK_SECONDS + app.Game.spin_seconds, abs=2e-3)
    clk.t += 0.5
    app.render(Frame(), clk.t)
    rv = (app.tv_extra() or {})["reveal"]
    assert rv["at"] - rv["since_lock"] == pytest.approx(app.status()["clock"]["lock_at"], abs=0.02)
    assert "outcome" not in json.dumps(app.status()["clock"])
