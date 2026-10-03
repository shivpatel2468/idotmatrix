"""Baccarat (docs/CASINO.md §7): the third-card tableau, exact house edges by enumeration, payouts, frozen bets,
verification, the table closing mid-coup, and render speed."""

from __future__ import annotations

import gc
import json
import time
from collections import Counter
from fractions import Fraction
from typing import Any

import pytest

from deskdot.casino import CasinoSession, fair
from deskdot.casino.cards import cards
from deskdot.casino.games.baccarat import (
    Baccarat,
    BaccaratRules,
    banker_draws,
    coup_distribution,
    deal_coup,
    pair_probability,
)
from deskdot.casino.table import LOCK_SECONDS


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _table(**rules: Any) -> tuple[CasinoSession, Clock, Baccarat]:
    clk = Clock()
    s = CasinoSession(clock=clk)
    s.join("a", 2, name="A")
    s.join("b", 3, name="B")
    g = Baccarat(s, BaccaratRules(**rules))
    s.use(g)
    g.open_betting()
    return s, clk, g


def _finish(g: Baccarat, clk: Clock) -> None:
    clk.t += LOCK_SECONDS + g.spin_seconds + 2
    g.tick()
    assert g.phase == "result"


def _stack(codes: str) -> Any:
    it = iter(cards(codes))
    return lambda: next(it)


# ===================================================================== the rules
def test_banker_tableau_is_the_standard_table() -> None:
    """Banker total (rows) × player's third card (columns): D = draw, S = stand — the printed casino tableau."""
    table = {
        0: "DDDDDDDDDD",
        1: "DDDDDDDDDD",
        2: "DDDDDDDDDD",
        3: "DDDDDDDDSD",  # stands only when the player's third card is an 8
        4: "SSDDDDDDSS",  # draws on 2–7
        5: "SSSSDDDDSS",  # draws on 4–7
        6: "SSSSSSDDSS",  # draws on 6–7
        7: "SSSSSSSSSS",
    }
    for b, row in table.items():
        for v, ch in enumerate(row):
            assert banker_draws(b, v) is (ch == "D"), (b, v)
        assert banker_draws(b, None) is (b <= 5)  # player stood: banker draws on 0–5


def test_third_card_rules_with_stacked_shoes() -> None:
    # draw order: P1 B1 P2 B2 P3 B3
    o = deal_coup(_stack("9S KD KS 7D"))  # player natural 9: both stand
    assert (
        o["player"] == ["9S", "KS"]
        and o["banker"] == ["KD", "7D"]
        and o["natural"]
        and o["winner"] == "player"
    )
    o = deal_coup(_stack("4S 8D 4H TD"))  # two naturals (8 v 8): both stand, a tie
    assert len(o["player"]) == 2 and len(o["banker"]) == 2 and o["winner"] == "tie" and o["natural"]
    o = deal_coup(_stack("3S 2D 3H 3D 8C 9C"))  # player 6 stands; banker 5 draws (player stood)
    assert o["player"] == ["3S", "3H"] and o["banker"] == ["2D", "3D", "8C"] and o["b"] == 3
    o = deal_coup(_stack("2S 2D 2H AD 8C 9C"))  # player 4 draws an 8; banker 3 stands on a third-card 8
    assert o["player"] == ["2S", "2H", "8C"] and o["banker"] == ["2D", "AD"] and o["winner"] == "banker"
    o = deal_coup(_stack("2S 3D 2H 3H 6C 9C"))  # player 4 draws a 6; banker 6 draws on 6
    assert len(o["banker"]) == 3 and o["banker"][2] == "9C"
    o = deal_coup(_stack("2S 3D 2H 3H 5C 9C"))  # player 4 draws a 5; banker 6 stands
    assert len(o["banker"]) == 2
    o = deal_coup(_stack("QS QD QH 7H 4C"))  # player 0 draws, banker 7 stands
    assert len(o["player"]) == 3 and len(o["banker"]) == 2 and o["winner"] == "banker"
    o = deal_coup(_stack("KS KD 5H 5D 3C"))  # pairs: K-5 / K-5, no pair
    assert not o["ppair"] and not o["bpair"]
    o = deal_coup(_stack("7S 9D 7H 9C"))
    assert o["ppair"] and o["bpair"]  # same rank = a pair, suits don't matter


# ============================================================ exact probabilities
def test_exact_distribution_and_house_edges_8_decks() -> None:
    dist = coup_distribution(8)
    assert sum(dist.values()) == 1
    win = Counter[str]()
    for (w, _bt), p in dist.items():
        win[w] += p  # type: ignore[assignment]
    assert round(float(win["banker"]), 6) == 0.458597
    assert round(float(win["player"]), 6) == 0.446247
    assert round(float(win["tie"]), 6) == 0.095156
    s, _, g = _table()
    e = g.edges()
    assert round(e["banker"] * 100, 2) == 1.06
    assert round(e["player"] * 100, 2) == 1.24
    assert round(e["tie"] * 100, 2) == 14.36
    assert round(e["pair"] * 100, 2) == 10.36
    ev = g.expected_values()
    assert ev["ppair"] == ev["bpair"] == 12 * pair_probability(8) - 1
    nine = Baccarat(s, BaccaratRules(tie_pays=9)).edges()
    assert round(nine["tie"] * 100, 2) == 4.84
    nc = Baccarat(s, BaccaratRules(commission="no_commission")).edges()
    assert round(nc["banker"] * 100, 2) == 1.46
    assert round(nc["player"] * 100, 2) == 1.24


def test_enumeration_matches_dealing_the_real_shoe() -> None:
    """The enumeration and the real dealer (`draw` with a fresh fair shoe) agree: a single deck, 30 000 coups,
    every (winner) frequency within 4 standard errors."""
    _s, _, g = _table(decks=1)
    dist = coup_distribution(1)
    want = Counter[str]()
    for (w, _bt), p in dist.items():
        want[w] += float(p)  # type: ignore[assignment]
    n = 30_000
    got = Counter(g.draw(fair.Rng(b"bac" * 11, "sim", i))["winner"] for i in range(n))
    for w in ("player", "banker", "tie"):
        p = want[w]
        se = (p * (1 - p) / n) ** 0.5
        assert abs(got[w] / n - p) < 4 * se, (w, got[w] / n, p)


# =================================================================== the table
def test_payouts_commission_ties_and_pairs() -> None:
    _s, clk, g = _table()
    g.place_bet("a", "banker", 20)
    g.place_bet("a", "ppair", 5)
    g.place_bet("b", "banker", 10)
    g.place_bet("b", "player", 10)
    g.place_bet("b", "tie", 10)
    g.lock()
    g.outcome = {
        "player": ["7S", "7D"],
        "banker": ["3H", "6C"],
        "p": 4,
        "b": 9,
        "winner": "banker",
        "natural": True,
        "ppair": True,
        "bpair": False,
    }
    _finish(g, clk)
    assert g.result is not None
    pa, pb = g.result.payouts["a"], g.result.payouts["b"]
    assert pa["payout"] == 39 + 60  # banker 20 × 1.95, pair 5 × 12
    assert pb["payout"] == 19  # 10 × 1.95 rounded down; player and tie lose
    _s2, clk2, g2 = _table(commission="no_commission")
    g2.place_bet("a", "banker", 10)
    g2.place_bet("b", "player", 10)
    g2.lock()
    g2.outcome = {
        "player": ["2S", "4D"],
        "banker": ["3H", "3C"],
        "p": 6,
        "b": 6,
        "winner": "tie",
        "natural": False,
        "ppair": False,
        "bpair": False,
    }
    _finish(g2, clk2)
    assert g2.result is not None
    assert g2.result.payouts["a"]["net"] == 0 and g2.result.payouts["b"]["net"] == 0  # a tie pushes P/B
    assert g2.returns({"winner": "banker", "b": 6}) == {"banker": Fraction(3, 2)}  # no-commission 6 pays 1:2
    assert g2.returns({"winner": "banker", "b": 7}) == {"banker": Fraction(2)}


def test_bets_frozen_from_lock_to_settlement_and_cards_reveal_in_order() -> None:
    s, clk, g = _table()
    assert g.place_bet("a", "player", 20) is None
    g.lock()
    snap = (json.dumps(g.bets, sort_keys=True), s.bank.credits("a"), s.bank.credits("b"))
    for step in ("locked", "dealing"):
        if step == "dealing":
            clk.t += LOCK_SECONDS + 0.01
            g.tick()
        assert g.phase == step
        for pid, op, payload in [
            ("a", "bet", {"spot": "player", "amount": 5}),
            ("a", "bet", {"spot": "tie", "amount": 5}),
            ("b", "bet", {"spot": "banker", "amount": 5}),
            ("a", "unbet", {"spot": "player"}),
            ("a", "clear", {}),
            ("a", "rebet", {}),
            ("a", "done", {}),
        ]:
            g.handle(pid, op, payload, clk.t)
            assert (json.dumps(g.bets, sort_keys=True), s.bank.credits("a"), s.bank.credits("b")) == snap
        pub = g.public_state(clk.t)
        assert "result" not in pub
    assert g.outcome is not None
    seen = []
    for _ in range(80):
        clk.t += 0.1
        g.tick()
        if g.phase != "dealing":
            break
        c = g.public_state(clk.t)["cards"]
        seen.append(len(c["player"]) + len(c["banker"]))
    assert seen == sorted(seen) and seen[-1] == len(g.outcome["player"]) + len(g.outcome["banker"])
    assert g.phase == "result"
    w = s.bank.get("a")
    assert w is not None and w.escrow == 0


def test_verify_round_and_outcome_independent_of_bets(monkeypatch: pytest.MonkeyPatch) -> None:
    outs = []
    for betting in (False, True):
        seeds = iter([bytes([i]) * 32 for i in range(1, 20)])
        monkeypatch.setattr(fair, "new_server_seed", lambda seeds=seeds: next(seeds))
        s, clk, g = _table()
        res = []
        for _ in range(4):
            g.open_betting()
            if betting:
                g.place_bet("a", "banker", 100)
            g.lock()
            _finish(g, clk)
            res.append(g.result.outcome if g.result else None)
        outs.append(res)
        v = s.verify(s.history[-1]["round"])
        assert v["ok"] and v["matches"]
    assert outs[0] == outs[1]


def test_closing_the_table_mid_coup_pays_it() -> None:
    s, clk, g = _table()
    g.place_bet("a", "player", 50)
    g.lock()
    clk.t += LOCK_SECONDS + 0.5
    g.tick()
    assert g.phase == "dealing"
    g.abort()
    w = s.bank.get("a")
    assert w is not None and w.escrow == 0
    assert s.history and s.history[-1]["game"] == "baccarat"  # paid and recorded, not refunded
    assert w.credits == 1000 - 50 + (
        100
        if s.history[-1]["outcome"]["winner"] == "player"
        else 50
        if s.history[-1]["outcome"]["winner"] == "tie"
        else 0
    )


# ====================================================================== render
async def test_render_every_view_fast(engine: Any) -> None:
    from deskdot.apps._casino import VIEWS
    from deskdot.gfx import Frame

    app_id = "casino_baccarat"
    worst = 0.0
    gc.collect()
    gc.disable()
    try:
        for view in VIEWS:
            engine.store.section("apps")[app_id] = {"view": view}
            engine.slots.clear()
            app = engine._slot(app_id).app
            for t in (0.0, 0.4, 1.3, 2.7, 4.1, 6.0, 8.2, 9.9, 13.0, 17.5):
                f = Frame()
                t0 = time.perf_counter()
                app.render(f, t)
                worst = max(worst, time.perf_counter() - t0)
                if view not in ("live", "lobby"):
                    assert f.px.any(), (view, t)
    finally:
        gc.enable()
    assert worst < 0.05
