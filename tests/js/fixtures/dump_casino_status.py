"""Dump sample public casino statuses (what phones and the TV view receive) to tests/js/fixtures/casino_status.json.

Run: ``uv run python tests/js/fixtures/dump_casino_status.py``. Each casino table plays a few real rounds on a
fake clock with three phone players (plus a demo bot policy for the poker-style tables); a snapshot of
``app.status()`` is kept on every phase change and a few times inside long phases. Only the PUBLIC status is
dumped — the JS test (tests/js/tv_casino.test.mjs) runs every TV casino scene's update() on these.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import deskdot.apps  # noqa: F401 — registers built-in apps
from deskdot.engine.app import REGISTRY
from deskdot.gfx import Frame

OUT = Path(__file__).with_name("casino_status.json")
COLOURS = ("#ff3f78", "#33d1ff", "#7dff5a", "#ffcc33")
PLAYERS = 3


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


_CLOCK: list[Clock] = []
# the engine's wall clock follows the fake table clock, so `status.clock` anchors are as steady as on a real table
time.time = lambda: 1_760_000_000.0 + (_CLOCK[-1].t if _CLOCK else 0.0)


def _app(app_id: str) -> Any:
    cls = REGISTRY[app_id]
    app = cls(object(), cls.Settings())
    app.session.clock = Clock()
    _CLOCK.append(app.session.clock)
    return app


async def _seat(app: Any) -> None:
    for i in range(PLAYERS):
        await app.action(
            "seat",
            {"player": i + 2, "joined": True, "name": f"P{i + 2}", "color": COLOURS[i], "pid": f"pid{i:04d}",
             "avatar": "bot"},
        )  # fmt: skip


async def _op(app: Any, seat: int | str, **kw: Any) -> Any:
    return await app.action("casino", {**kw, "player": seat})


def _snap(app: Any, out: list[dict[str, Any]], tag: str) -> None:
    st = json.loads(json.dumps(app.status()))
    tv = app.tv_extra() if hasattr(app, "tv_extra") else None
    if tv:  # TV-only anchors, with their server times made relative to the snapshot (the test re-bases them)
        wall = time.time()
        for part in tv.values():
            if isinstance(part, dict) and "at" in part:
                part["at_age"] = round(wall - part.pop("at"), 4)
    st["_tv"] = tv
    st["_tag"] = tag
    st["_t"] = round(app.session.clock.t, 2)
    out.append(st)


async def _run(app: Any, seconds: float, out: list[dict[str, Any]], step: float = 0.1, every: float = 1.5,
               bot: Any = None) -> None:  # fmt: skip
    """Advance the clock, ticking the table; snapshot on every phase change (and every `every` s)."""
    clk = app.session.clock
    last_phase, last_snap = None, -99.0
    end = clk.t + seconds
    while clk.t < end:
        clk.t += step
        app.game.tick(clk.t)
        app.render(
            Frame(), clk.t
        )  # the panel draws (the roulette wheel's angle is integrated frame by frame)
        if bot is not None:
            await bot(app)
        ph = app.game.phase
        if ph != last_phase or clk.t - last_snap >= every:
            _snap(app, out, ph)
            last_phase, last_snap = ph, clk.t


async def bet_game(app_id: str, bets: list[tuple[int, str, int]], rounds: int = 2) -> list[dict[str, Any]]:
    app = _app(app_id)
    await _seat(app)
    out: list[dict[str, Any]] = []
    _snap(app, out, "open")
    span = 4.0 + app.Game.spin_seconds + 9.0
    for _ in range(rounds):
        for seat, spot, amount in bets:
            await _op(app, seat, op="bet", spot=spot, amount=amount)
        _snap(app, out, "bets")
        await _op(app, "host", op="lock")
        await _run(app, span, out)
    return out


async def blackjack() -> list[dict[str, Any]]:
    from deskdot.casino.cards import Card
    from deskdot.casino.games.blackjack import basic_strategy

    app = _app("casino_blackjack")
    await _seat(app)
    out: list[dict[str, Any]] = []

    async def bot(a: Any) -> None:
        for seat in range(2, 2 + PLAYERS):
            pv = a.private_status(seat) or {}
            if pv.get("insurance_offer"):
                await _op(a, seat, op="insurance", take=False)
            if pv.get("turn") and pv.get("moves"):
                t = a.status()["table"]
                me = next(s for s in t["seats"] if s["seat"] == seat)
                hand = me["hands"][pv["turn"]["hand"]]
                up = Card.parse(t["dealer"]["cards"][0])
                mv = basic_strategy([Card.parse(c) for c in hand["cards"]], up, pv["moves"])
                await _op(a, seat, op=mv)

    for _ in range(2):
        for i in range(PLAYERS):
            await _op(app, i + 2, op="bet", spot="main", amount=20 + 10 * i)
        _snap(app, out, "bets")
        await _op(app, "host", op="lock")
        await _run(app, 30.0, out, every=1.0, bot=bot)
    return out


async def pvp(app_id: str) -> list[dict[str, Any]]:
    app = _app(app_id)
    await _seat(app)
    out: list[dict[str, Any]] = []
    k = [0]

    async def bot(a: Any) -> None:
        g = a.game
        if g.phase != "action" or g.turn is None or g.finished:
            return
        p = g.players[g.turn]
        op, payload = a.policy(g, p, k[0])
        k[0] += 1
        await _op(a, p.seat, op=op, **payload)

    _snap(app, out, "lobby")
    await _run(app, 70.0, out, every=2.0, bot=bot)
    return out


async def housie() -> list[dict[str, Any]]:
    app = _app("casino_housie")
    await app.action("casino", {"op": "pace", "seconds": 3, "player": "host"})
    await _seat(app)
    out: list[dict[str, Any]] = []
    for i in range(PLAYERS):
        await _op(app, i + 2, op="buy", count=1 + i)
    _snap(app, out, "bought")
    await _op(app, "host", op="lock")
    await _run(app, 300.0, out, step=0.25, every=12.0)
    return out


async def slots() -> list[dict[str, Any]]:
    app = _app("casino_slots")
    await _seat(app)
    out: list[dict[str, Any]] = []
    _snap(app, out, "idle")
    for i in range(PLAYERS):
        await _op(app, i + 2, op="pull", bet=5)
    await _run(app, 14.0, out, step=0.1, every=0.6)
    return out


async def main() -> None:
    data: dict[str, list[dict[str, Any]]] = {
        "casino_roulette": await bet_game(
            "casino_roulette",
            [(2, "red", 20), (3, "n:17", 5), (4, "dz:2", 10), (2, "c:8", 5), (3, "black", 15)],
        ),
        "casino_bigsix": await bet_game("casino_bigsix", [(2, "s1", 10), (3, "s5", 5), (4, "joker", 2)]),
        "casino_sevens": await bet_game("casino_sevens", [(2, "down", 10), (3, "seven", 5), (4, "up", 10)]),
        "casino_baccarat": await bet_game(
            "casino_baccarat", [(2, "player", 20), (3, "banker", 20), (4, "tie", 5), (2, "ppair", 2)]
        ),
        "casino_andarbahar": await bet_game(
            "casino_andarbahar", [(2, "andar", 20), (3, "bahar", 20), (4, "c:1-5", 5)]
        ),
        "casino_blackjack": await blackjack(),
        "casino_holdem": await pvp("casino_holdem"),
        "casino_teenpatti": await pvp("casino_teenpatti"),
        "casino_housie": await housie(),
        "casino_slots": await slots(),
    }
    from deskdot.casino.games.bigsix import WHEEL
    from deskdot.casino.games.roulette import RouletteRules
    from deskdot.casino.session import CasinoSession
    from deskdot.casino.table import GAMES

    tables: dict[str, Any] = {"bigsix_wheel": list(WHEEL)}
    for wheel in ("european", "american"):  # every roulette spot id with the pockets it covers
        game = GAMES["roulette"](CasinoSession(), RouletteRules(wheel=wheel))
        tables[f"roulette_{wheel}"] = {s["id"]: s["numbers"] for s in game.spot_table()}
    for snaps in data.values():
        for s in snaps:  # proofs make the file big and the TV never shows them
            for h in s.get("history", []):
                h.pop("proof", None)
                h.pop("rules", None)
                if h.get("game") not in ("roulette", "bigsix", "sevens", "baccarat"):
                    h.pop("outcome", None)  # decks / shoes: the TV only reads these four games' outcomes
            s.pop("edges", None)
            s.pop("hash", None)
            if s is not snaps[0]:
                s.pop("table_theme", None)  # the same on every snapshot
                s.get("machine", {}).pop("sprites", None)  # slots: the TV keeps the last sprites it saw
    OUT.write_text(json.dumps({"statuses": data, "tables": tables}, separators=(",", ":")), encoding="utf-8")
    print(OUT, {k: len(v) for k, v in data.items()})


if __name__ == "__main__":
    asyncio.run(main())
