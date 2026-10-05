"""Dump sample game statuses to tests/js/fixtures/game_statuses.json (attract, every multiplayer mode: start /
play / outro). Run: uv run python tests/js/fixtures/dump_game_statuses.py"""

import asyncio
import json
import tempfile
from pathlib import Path

import deskdot.apps  # noqa: F401
from deskdot.config import Config, Store
from deskdot.device import SimDevice
from deskdot.engine import REGISTRY, Engine
from deskdot.gfx import Frame
from deskdot.providers import build_hub

IDS = [
    "arcade",
    "invaders",
    "maze",
    "asteroids",
    "infinity",
    "tictactoe",
    "mines",
    "starship",
    "neonheat",
    "pong",
    "breakout",
    "flappy",
    "dino",
    "racer",
    "fourup",
    "cycles",
    "penguin",
    "leafleap",
    "tetris",
    "g2048",
    "streetsurge",
    "rps",
    "digworld",
    "chess",
    "trivia",
    "pet",
    "petworld",
]
PHONES = {2: ("MAYA", "#ff7419"), 3: ("LEO", "#c864ff")}


async def main():
    tmp = Path(tempfile.mkdtemp())
    store = Store(tmp / "state.json")
    hub = build_hub(store, lambda _n: None)
    eng = Engine(
        Config(device="sim", data_dir=tmp),
        store,
        SimDevice(bytes_per_second=1e7, min_frame_interval=0.0),
        hub,
    )
    out = {}
    for aid in IDS:
        cls = REGISTRY[aid]
        app = eng._slot(aid).app
        d = {
            "meta": {
                "id": aid,
                "name": cls.name,
                "category": cls.category,
                "icon": cls.icon,
                "max_players": getattr(cls, "max_players", None) or 1,
            }
        }
        for t in (0.0, 0.5, 1.0):
            app.render(Frame(), t)
        d["attract"] = app.status()
        for m in [m for m in getattr(cls, "modes", ()) if m.max_players > 1]:
            n = min(m.max_players, max(3, m.min_players))
            for seat in range(2, min(n, 3) + 1):
                name, col = PHONES[seat]
                try:
                    await app.action("seat", {"player": seat, "name": name, "color": col, "ready": True})
                except TypeError:  # games that shadow GameApp._seat (see report); seat the phone directly
                    app.seats[seat] = {
                        "name": name,
                        "at": 0,
                        "color": None,
                        "avatar": None,
                        "team": None,
                        "ready": True,
                    }
            await app.action("start", {"mode": m.id, "players": n})
            d[f"start_{m.id}"] = app.status()
            if app.flow == "teams":
                for seat in sorted(app.roster):
                    if app.roster[seat]["human"]:
                        await app.action("input", {"key": "a", "player": seat})
            app.flow = "play"
            for i in range(20):
                app.render(Frame(), 2.0 + i * 0.2)
            d[f"play_{m.id}"] = app.status()
            if m.teams == "versus":
                app.result(winner_team=1)
            elif m.teams == "coop":
                app.result(text="CLEARED")
            else:
                app.result(winner_seat=2)
            app.flow = "outro"
            d[f"outro_{m.id}"] = app.status()
            app.outcome, app.over_at = None, None
        out[aid] = d
    # the pixel-art hands are the same in every RPS status: keep them once
    for k, v in out["rps"].items():
        if k not in ("meta", "attract") and isinstance(v, dict) and "rps" in v:
            v["rps"].pop("art", None)
    await hub.http.aclose()
    return out


if __name__ == "__main__":
    data = asyncio.run(main())
    p = Path(__file__).with_name("game_statuses.json")
    p.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    print("wrote", p, p.stat().st_size)
