"""Slots (docs/CASINO.md §7): pay rules, the exact RTP by enumeration (and against a big simulation), commit–reveal
per spin, the frozen spin, the queue, verification, closing the machine, the phone protocol and render speed."""

from __future__ import annotations

import gc
import json
import time
from fractions import Fraction
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from deskdot.casino import CasinoSession, fair
from deskdot.casino.games.slots import (
    LINES,
    SPIN_STOPS,
    STRIPS,
    THEMES,
    VOLATILITY,
    Slots,
    SlotsRules,
    evaluate,
    line_pay,
    machine_stats,
    window,
)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _machine(**rules: Any) -> tuple[CasinoSession, Clock, Slots]:
    clk = Clock()
    s = CasinoSession(clock=clk)
    s.join("a", 2, name="A")
    s.join("b", 3, name="B")
    g = Slots(s, SlotsRules(**rules))
    s.use(g)
    g.open_betting()
    return s, clk, g


# ===================================================================== pay rules
def test_pay_rules() -> None:
    c, n, sp = THEMES["classic"], THEMES["neon"], THEMES["space"]
    assert line_pay(c, "7", "7", "7") == (100, "3 Seven")
    # cherries count from the left
    assert line_pay(c, "C", "C", "X")[0] == 5 and line_pay(c, "C", "X", "C")[0] == 2
    assert line_pay(c, "X", "C", "C")[0] == 0 and line_pay(c, "_", "7", "7")[0] == 0
    assert line_pay(n, "S", "G", "G")[0] == 100  # the star is wild
    assert line_pay(n, "S", "S", "S")[0] == 200
    assert line_pay(n, "G", "R", "S")[0] == 10  # any 7s, with a wild
    assert line_pay(n, "3", "1", "2")[0] == 2 and line_pay(n, "3", "_", "2")[0] == 0
    assert line_pay(sp, "A", "U", "R")[0] == 4 and line_pay(sp, "S", "S", "M")[0] == 4
    assert line_pay(sp, "S", "M", "S")[0] == 1
    for th in THEMES.values():  # a line pays its best win only
        for a, b, cc in product(th.symbols + "_", repeat=3):
            p, what = line_pay(th, a, b, cc)
            assert p >= 0 and bool(p) == bool(what)


def test_paylines_and_window() -> None:
    strips = STRIPS["classic"]["medium"]
    stops = [3, 7, 11]
    grid = window(strips, stops)
    assert [grid[1][i] for i in range(3)] == [strips[i][stops[i]] for i in range(3)]  # middle row = the stops
    assert grid[0][0] == strips[0][2] and grid[2][2] == strips[2][12]
    assert LINES[0] == (1, 1, 1) and LINES[3] == (0, 1, 2) and LINES[4] == (2, 1, 0)
    for lines in (1, 3, 5):
        ev = evaluate("classic", "medium", stops, lines)
        assert all(w["line"] <= lines for w in ev["wins"])
        assert ev["pays"] == sum(w["pays"] for w in ev["wins"])


# ========================================================================== RTP
@pytest.mark.parametrize(("theme", "vol"), [(t, v) for t in THEMES for v in VOLATILITY])
def test_rtp_is_exact_and_in_range(theme: str, vol: str) -> None:
    """machine_stats (by symbol counts) equals a brute force over every stop combination of the real window."""
    st = machine_stats(theme, vol)
    strips = STRIPS[theme][vol]
    total = Fraction(0)
    n = 0
    for stops in product(*(range(len(s)) for s in strips)):
        total += evaluate(theme, vol, list(stops), 1)["pays"]  # the middle line
        n += 1
    assert st["rtp"] == total / n and st["combos"] == n
    assert Fraction(95, 100) <= st["rtp"] <= Fraction(965, 1000), float(st["rtp"])
    # every line has the same return (each sees uniform stops), so 5 lines return 5 × the middle line
    five = sum(
        Fraction(evaluate(theme, vol, list(s), 5)["pays"]) for s in product(*(range(len(x)) for x in strips))
    )
    assert five / n == 5 * st["rtp"]


def test_volatility_presets_differ_as_labelled() -> None:
    for theme in THEMES:
        hit = {v: machine_stats(theme, v)["hit"] for v in VOLATILITY}
        assert hit["low"] > hit["high"], theme  # low = frequent small wins, high = rarer
        sd = {v: machine_stats(theme, v)["variance"] for v in VOLATILITY}
        assert sd["high"] > sd["low"], theme


def test_rtp_matches_a_big_simulation() -> None:
    """300 000 spins with the fair RNG on the medium classic machine: the mean return is within 4 standard
    errors of the exact RTP, and the hit rate within 4 SE of the exact hit rate."""
    _s, _, g = _machine(theme="classic", volatility="medium", lines=1)
    st = machine_stats("classic", "medium")
    n = 300_000
    paid = hits = 0
    rng = fair.Rng(b"slot-sim".ljust(32, b"."), "sim", 1)
    strips = STRIPS["classic"]["medium"]
    for _ in range(n):
        stops = [rng.randint(0, len(x) - 1) for x in strips]
        p = evaluate("classic", "medium", stops, 1)["pays"]
        paid += p
        hits += p > 0
    sd = float(st["variance"]) ** 0.5
    assert abs(paid / n - float(st["rtp"])) < 4 * sd / n**0.5
    h = float(st["hit"])
    assert abs(hits / n - h) < 4 * (h * (1 - h) / n) ** 0.5
    assert g.edges()["spin"] == round(float(1 - st["rtp"]), 5)


# =================================================================== the machine
def test_commit_before_pull_then_reveal_and_verify() -> None:
    s, clk, g = _machine(lines=5)
    sealed = g.private_state("a", clk.t)["sealed"]
    assert len(sealed["hash"]) == 64
    assert g.handle("a", "pull", {"bet": 2}, clk.t) is None
    spin = g.spin_of("a")
    assert spin is not None and spin.nonce == sealed["round"] and spin.round.hash == sealed["hash"]
    assert spin.stake == 10 and s.bank.get("a").escrow == 10  # type: ignore[union-attr]
    # the next spin is sealed at once
    assert g.private_state("a", clk.t)["sealed"]["round"] != sealed["round"]
    # the outcome is not public before the reels stop
    pub = g.public_state(clk.t)
    assert pub["playing"]["stops"] == [None, None, None]
    clk.t += SPIN_STOPS[0] + 0.01
    assert g.public_state(clk.t)["playing"]["stops"][0] == spin.stops[0]  # reel 1 stopped
    assert g.public_state(clk.t)["playing"]["stops"][2] is None
    clk.t += SPIN_STOPS[-1]
    g.tick()
    assert spin.settled and s.bank.get("a").escrow == 0  # type: ignore[union-attr]
    assert s.bank.credits("a") == 1000 - 10 + spin.payout
    e = s.history[-1]
    assert e["game"] == "slots" and e["outcome"] == {"stops": spin.stops} and e["proof"]["server_seed"]
    v = s.verify(e["round"])
    assert v["ok"] and v["matches"]


def test_spin_is_frozen_until_settled_and_queue_plays_in_order() -> None:
    s, clk, g = _machine(lines=3)
    g.handle("a", "pull", {"bet": 5}, clk.t)
    clk.t += 0.3
    g.handle("b", "pull", {"bet": 1}, clk.t)
    snap = (s.bank.credits("a"), s.bank.get("a").escrow)  # type: ignore[union-attr]
    for op, payload in [
        ("pull", {"bet": 25}),
        ("bet", {"spot": "x", "amount": 5}),
        ("unbet", {}),
        ("clear", {}),
        ("rebet", {}),
        ("done", {}),
    ]:
        assert g.handle("a", op, payload, clk.t) is not None, op  # every one refused …
        w = s.bank.get("a")
        assert w is not None and (w.credits, w.escrow) == snap, op  # … and nothing moved
    assert g.private_state("a", clk.t)["can_pull"] is False
    a, b = g.queue
    assert g.now_playing(clk.t) is a and b.start is None
    assert g.private_state("b", clk.t)["spin"]["ahead"] == 1
    for _ in range(200):
        clk.t += 0.1
        g.tick()
        if not g.queue:
            break
    assert a.settled and b.settled and b.start is not None and a.start is not None
    assert b.start >= a.start + SPIN_STOPS[-1] + a.hold() - 1e-9  # one machine on the panel at a time
    assert g.private_state("a", clk.t)["can_pull"] is True


def test_bets_follow_the_house_limits() -> None:
    s, clk, g = _machine(lines=5)
    s.host_op("settings", {"min_bet": 5, "max_bet": 50})
    assert g.bet_options() == [1, 2, 5, 10]  # ×5 lines = 5 … 50
    g.handle("a", "pull", {"bet": 25}, clk.t)  # over the max: the nearest allowed bet below
    assert g.spin_of("a").stake == 50  # type: ignore[union-attr]
    s.bank.set_credits("b", 3)
    assert g.handle("b", "pull", {"bet": 1}, clk.t) == "Not enough credits for this bet"


def test_outcome_never_depends_on_the_bet(monkeypatch: pytest.MonkeyPatch) -> None:
    res = []
    for bet in (1, 25):
        seeds = iter([bytes([i]) * 32 for i in range(1, 40)])
        monkeypatch.setattr(fair, "new_server_seed", lambda seeds=seeds: next(seeds))
        _s, clk, g = _machine()
        out = []
        for _ in range(6):
            g.handle("a", "pull", {"bet": bet}, clk.t)
            out.append(list(g.spin_of("a").stops))  # type: ignore[union-attr]
            clk.t += 10
            g.tick()
        res.append(out)
    assert res[0] == res[1]


def test_closing_the_machine_pays_every_queued_spin() -> None:
    s, clk, g = _machine()
    g.handle("a", "pull", {"bet": 1}, clk.t)
    g.handle("b", "pull", {"bet": 1}, clk.t)
    g.abort()
    assert not g.queue
    assert all(w.escrow == 0 for w in s.bank.wallets.values())
    assert len([e for e in s.history if e["game"] == "slots"]) == 2


# ===================================================================== protocol
def _client(tmp_path: Path) -> Any:
    from fastapi.testclient import TestClient

    from deskdot.config import Config
    from deskdot.server import create_app

    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def _state(ws: Any, pred: Any, timeout: float = 4.0) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        m = ws.receive_json()
        if m["type"] == "state" and pred(m):
            return m  # type: ignore[no-any-return]
    raise AssertionError("state never arrived")


def test_phone_protocol_pull(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "casino_slots"}).json()["code"]
        assert 'registerGame("slots"' in c.get(f"/p/{code}").text
        app = c.app.state.engine._slot("casino_slots").app
        clk = Clock()
        app.session.clock = clk
        with c.websocket_connect(f"/ws/p/{code}?cid=phoneSLOT01") as a:
            a.receive_json()
            m = _state(a, lambda m: m.get("private", {}).get("sealed"))
            sealed = m["private"]["sealed"]
            assert m["status"]["machine"]["rtp"] > 0.9 and len(m["status"]["machine"]["strips"]) == 3
            a.send_text(json.dumps({"type": "casino", "op": "pull", "bet": 2}))
            m = _state(a, lambda m: m["private"].get("spin"))
            assert m["private"]["spin"]["id"] == sealed["round"] and m["private"]["credits"] == 990
            assert m["private"]["spin"]["stops"] == [None, None, None]  # secret until the reels stop
            clk.t += 10
            m = _state(a, lambda m: m["private"].get("last") and not m["private"].get("spin"))
            last = m["private"]["last"]
            assert None not in last["stops"] and m["private"]["credits"] == 990 + last["win"]
            assert m["status"]["history"][-1]["proof"]["server_seed"]


# ======================================================================== render
@pytest.mark.parametrize("theme", list(THEMES))
async def test_render_every_view_fast(engine: Any, theme: str) -> None:
    from deskdot.apps._casino import VIEWS
    from deskdot.gfx import Frame

    app_id = "casino_slots"
    worst, total, n = 0.0, 0.0, 0
    gc.collect()
    gc.disable()
    try:
        for view in VIEWS:
            engine.store.section("apps")[app_id] = {"view": view, "theme": theme}
            engine.slots.clear()
            app = engine._slot(app_id).app
            for t in (0.0, 0.4, 1.3, 2.7, 4.1, 6.0, 8.2, 9.9, 13.0, 17.5):
                f = Frame()
                t0 = time.perf_counter()
                app.render(f, t)
                dt = time.perf_counter() - t0
                worst, total, n = max(worst, dt), total + dt, n + 1
                if view not in ("live", "lobby"):
                    assert f.px.any(), (view, t)
    finally:
        gc.enable()
    assert worst < 0.05 and total / n < 0.006, (worst, total / n)


async def test_live_machine_with_players(engine: Any) -> None:
    from deskdot.gfx import Frame

    engine.slots.clear()
    engine.shared.clear()
    app = engine._slot("casino_slots").app
    clk = Clock()
    app.session.clock = clk
    for i in range(4):
        await app.action(
            "seat",
            {"player": i + 2, "joined": True, "name": f"P{i}", "color": "#ff3c5a", "pid": f"pid{i:04d}"},
        )
        await app.action("casino", {"op": "pull", "bet": 1, "player": i + 2})
    assert len(app.game.queue) == 4
    for _ in range(300):
        clk.t += 0.1
        app.render(Frame(), clk.t)
    assert not app.game.queue and all(w.escrow == 0 for w in app.session.bank.wallets.values())
    assert app.status()["machine"]["rtp"] > 0.9
