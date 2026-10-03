"""Blackjack (docs/CASINO.md §7): every rule with stacked shoes, turn order and timers, frozen bets, the per-round
shoe verification chain, the cut card, closing mid-hand, a basic-strategy simulation of the house edge, the phone
protocol and render speed."""

from __future__ import annotations

import gc
import itertools
import json
import time
from pathlib import Path
from typing import Any, ClassVar

import pytest

from deskdot.casino import CasinoSession, fair
from deskdot.casino.cards import CARD_KINDS, Card, DealingShoe, cards, full_composition
from deskdot.casino.games import blackjack as bjmod
from deskdot.casino.games.blackjack import (
    Blackjack,
    BlackjackRules,
    basic_strategy,
    house_edge,
    insurance_edge,
)
from deskdot.casino.table import LOCK_SECONDS


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class StackedShoe:
    """Deals the cards in `STACK` order (tests only)."""

    STACK: ClassVar[list[Card]] = []

    def __init__(self, decks: int = 6, composition: str | None = None) -> None:
        self.decks = decks
        self.cards = list(self.STACK)
        self.drawn: list[Card] = []

    size = property(lambda self: 52 * self.decks)
    remaining = property(lambda self: 52 * self.decks - len(self.drawn))
    composition = property(lambda self: full_composition(self.decks))

    def begin(self, rng: Any) -> None:
        pass

    def draw(self) -> Card:
        c = self.cards.pop(0)
        self.drawn.append(c)
        return c


def _table(n: int = 2, stack: str | None = None, mp: pytest.MonkeyPatch | None = None, **rules: Any) -> Any:
    clk = Clock()
    s = CasinoSession(clock=clk)
    for i in range(n):
        s.join("ab"[i] if i < 2 else f"p{i}", 2 + i, name=f"P{i}")
    g = Blackjack(s, BlackjackRules(**rules))
    s.use(g)
    g.open_betting()
    if stack is not None and mp is not None:
        StackedShoe.STACK = cards(stack)
        mp.setattr(bjmod, "DealingShoe", StackedShoe)
    return s, clk, g


def _deal(g: Blackjack, clk: Clock, bets: dict[str, int]) -> None:
    for pid, amt in bets.items():
        assert g.place_bet(pid, "main", amt) is None
    g.lock()
    clk.t += LOCK_SECONDS + 0.01
    g.tick()
    assert g.deal_end is not None
    clk.t = g.deal_end + 0.01
    g.tick()


def _to_result(g: Blackjack, clk: Clock) -> None:
    for _ in range(200):
        if g.phase == "result":
            return
        clk.t += 0.5
        g.tick()
    raise AssertionError(f"stuck in {g.phase}/{g.stage}")


def _net(g: Blackjack, pid: str) -> int:
    assert g.result is not None
    return int(g.result.payouts[pid]["net"])


# ===================================================================== payouts
@pytest.mark.parametrize(("pays", "net"), [("3:2", 15), ("6:5", 12)])
def test_blackjack_pays_3_2_or_6_5(monkeypatch: pytest.MonkeyPatch, pays: str, net: int) -> None:
    # a: A K (blackjack) · dealer 9 7 = 16: with only a blackjack left to beat, the dealer turns over and stops
    _s, clk, g = _table(1, "AS 9D KH 7C 5S", monkeypatch, blackjack_pays=pays)
    _deal(g, clk, {"a": 10})
    assert g.hands["a"][0].status == "blackjack" and g.stage == "dealer"  # nobody to play: the dealer draws
    _to_result(g, clk)
    assert _net(g, "a") == net
    assert g.result is not None and g.result.outcome["dealer"] == ["9D", "7C"]


def test_turn_order_hit_stand_bust_and_dealer_s17(monkeypatch: pytest.MonkeyPatch) -> None:
    # deal: a T, b 9, dealer 5 up, a 6, b 9, dealer 6 in the hole · a hits 8 → bust, b stands 18, dealer 11 + 7
    _s, clk, g = _table(2, "TS 9D 5C 6H 9C 6D 8S 7H", monkeypatch)
    _deal(g, clk, {"a": 10, "b": 20})
    assert g.turn == ("a", 0) and g.phase == "action"
    assert g.game_op("b", "hit", {}, clk.t) == "Wait for your turn"  # turn order: seat 2 before seat 3
    assert set(g.moves("a")) >= {"hit", "stand", "double", "surrender"}
    assert "split" not in g.moves("a")
    g.handle("a", "hit", {}, clk.t)
    assert g.hands["a"][0].status == "bust" and g.turn == ("b", 0)
    assert "split" in g.moves("b")
    g.handle("b", "stand", {}, clk.t)
    _to_result(g, clk)
    assert g.result is not None and g.result.outcome["dealer"] == ["5C", "6D", "7H"]
    assert _net(g, "a") == -10 and _net(g, "b") == 0  # 18 v 18 pushes


@pytest.mark.parametrize(("soft17", "dealer"), [("stand", ["AC", "6D"]), ("hit", ["AC", "6D", "4H"])])
def test_dealer_soft_17_rule(monkeypatch: pytest.MonkeyPatch, soft17: str, dealer: list[str]) -> None:
    _s, clk, g = _table(1, "TS AC 8S 6D 4H", monkeypatch, soft17=soft17, insurance=False)
    _deal(g, clk, {"a": 10})
    g.handle("a", "stand", {}, clk.t)
    _to_result(g, clk)
    assert g.result is not None and g.result.outcome["dealer"] == dealer
    assert _net(g, "a") == (10 if soft17 == "stand" else -10)  # 18 beats 17; loses to 21


def test_double_rules_and_double_after_split(monkeypatch: pytest.MonkeyPatch) -> None:
    _, clk, g = _table(1, "6S 9D 5C 7H TH 2C", monkeypatch)  # a: 6 5 = 11 doubles into 21; dealer 16 + 2
    _deal(g, clk, {"a": 10})
    g.handle("a", "double", {}, clk.t)
    h = g.hands["a"][0]
    assert h.doubled and h.bet == 20 and len(h.cards) == 3 and h.status == "stand"
    _to_result(g, clk)
    assert _net(g, "a") == 20  # 21 v dealer 18
    # 9–11 only: no double on a soft 18 or a hard 12
    _, clk, g = _table(1, "AS 9D 7C 7H", monkeypatch, double_on="9-11")
    _deal(g, clk, {"a": 10})
    assert "double" not in g.moves("a")
    # no double after split when DAS is off
    _s, clk, g = _table(1, "8S 9D 8C 7H 3D 3C", monkeypatch, double_after_split=False)
    _deal(g, clk, {"a": 10})
    g.handle("a", "split", {}, clk.t)
    assert len(g.hands["a"]) == 2 and g.hands["a"][0].cards == cards("8S 3D")
    assert "double" not in g.moves("a")


def test_splits_resplits_and_split_aces(monkeypatch: pytest.MonkeyPatch) -> None:
    # 8 8 → split; the first hand draws another 8 → resplit; up to max_splits (3 = four hands)
    s, clk, g = _table(1, "8S 9D 8C 7H 8D 8H 8C TC TD TH TS", monkeypatch, max_splits=3)
    _deal(g, clk, {"a": 10})
    for k in range(3):
        assert "split" in g.moves("a"), k
        g.handle("a", "split", {}, clk.t)
    assert len(g.hands["a"]) == 4
    assert "split" not in g.moves("a")  # four hands: no more splits even with 8 8
    assert s.bank.get("a").escrow == 40  # type: ignore[union-attr]
    # split aces: one card each, no more moves, and A + T is 21 but not a blackjack
    s, clk, g = _table(1, "AS 9D AC 7H KD 5C 2C", monkeypatch)
    _deal(g, clk, {"a": 10})
    g.handle("a", "split", {}, clk.t)
    hs = g.hands["a"]
    assert [len(h.cards) for h in hs] == [2, 2] and all(h.status == "stand" for h in hs)
    assert g.moves("a") == []  # the split aces are finished: no hit, no resplit
    assert not hs[0].natural and hs[0].total == 21 and hs[1].total == 16
    _to_result(g, clk)
    assert g.hand_return(hs[0]) == 20  # A + K after a split is 21, paid 1:1 — not a 3:2 blackjack
    assert _net(g, "a") == 0  # 21 wins 10, 16 loses 10 against the dealer's 18


def test_late_surrender(monkeypatch: pytest.MonkeyPatch) -> None:
    _, clk, g = _table(1, "TS TD 6C 9H", monkeypatch)
    _deal(g, clk, {"a": 15})
    assert "surrender" in g.moves("a")
    g.handle("a", "surrender", {}, clk.t)
    _to_result(g, clk)
    assert _net(g, "a") == -8  # half of 15 back, rounded down
    _, clk, g = _table(1, "TS TD 6C 9H", monkeypatch, surrender="none")
    _deal(g, clk, {"a": 10})
    assert "surrender" not in g.moves("a")
    _s, clk, g = _table(1, "5S TD 6C 9H 2C", monkeypatch)
    _deal(g, clk, {"a": 10})
    g.handle("a", "hit", {}, clk.t)
    assert "surrender" not in g.moves("a")  # only as the first decision


def test_insurance_and_dealer_peek(monkeypatch: pytest.MonkeyPatch) -> None:
    # dealer A up, K in the hole: a takes insurance, b declines; peek finds the blackjack → no one plays
    _, clk, g = _table(2, "TS 9D AC 9H 7D KC", monkeypatch)
    _deal(g, clk, {"a": 20, "b": 10})
    assert g.stage == "insurance" and g.phase == "action"
    assert g.private_state("a", clk.t)["insurance_offer"] == 10
    g.handle("a", "insurance", {}, clk.t)
    assert g.stage == "insurance"  # still waiting for b
    g.handle("b", "insurance", {"take": False}, clk.t)
    assert g.stage == "dealer"  # the peek found 21: straight to the dealer
    _to_result(g, clk)
    assert _net(g, "a") == -20 + 20  # loses 20, insurance 10 pays 2:1
    assert _net(g, "b") == -10
    # the insurance timer: nobody answers → declined, then play goes on (no dealer blackjack)
    _s, clk, g = _table(1, "TS AC 9D 7D", monkeypatch)
    _deal(g, clk, {"a": 20})
    assert g.stage == "insurance"
    clk.t += 30
    g.tick()
    assert g.stage == "turns" and g.insurance == {}


def test_no_peek_dealer_blackjack_takes_doubles(monkeypatch: pytest.MonkeyPatch) -> None:
    """European no-hole-card: the dealer's blackjack is found at the end and takes the doubled bet too."""
    _, clk, g = _table(1, "6S TD 5C AH 9C", monkeypatch, dealer_peek=False, insurance=False)
    _deal(g, clk, {"a": 10})
    assert g.stage == "turns"  # no peek: play goes on
    g.handle("a", "double", {}, clk.t)
    _to_result(g, clk)
    assert _net(g, "a") == -20
    _s, clk, g = _table(1, "6S TD 5C AH 9C", monkeypatch, dealer_peek=True, insurance=False)
    _deal(g, clk, {"a": 10})
    assert g.stage == "dealer"  # peek: the blackjack is found at once, only the original bet is lost
    _to_result(g, clk)
    assert _net(g, "a") == -10


def test_turn_timer_takes_the_safe_default(monkeypatch: pytest.MonkeyPatch) -> None:
    s, clk, g = _table(2, "TS 9D 7C 6H 2D 5C 9S", monkeypatch)
    _deal(g, clk, {"a": 10, "b": 10})
    assert g.turn == ("a", 0)
    clk.t += s.house.turn_seconds + 0.1
    g.tick()
    assert g.hands["a"][0].status == "stand" and g.turn == ("b", 0)  # stood, never hit for them
    assert g.log[-1][2] == "stand*"


def test_bets_frozen_from_lock_to_settlement(monkeypatch: pytest.MonkeyPatch) -> None:
    s, clk, g = _table(2, "TS 9D 7C 6H 2D 5C 9S 9H 9C", monkeypatch)
    assert g.place_bet("a", "main", 20) is None
    g.lock()

    def frozen() -> None:
        snap = (json.dumps(g.bets), s.bank.credits("a"), s.bank.credits("b"))
        for pid, op, payload in [
            ("a", "bet", {"spot": "main", "amount": 5}),
            ("b", "bet", {"spot": "main", "amount": 5}),
            ("a", "unbet", {"spot": "main"}),
            ("a", "unbet", {"spot": "main", "amount": 5}),
            ("a", "clear", {}),
            ("a", "rebet", {}),
            ("a", "done", {}),
        ]:
            g.handle(pid, op, payload, clk.t)
            assert (json.dumps(g.bets), s.bank.credits("a"), s.bank.credits("b")) == snap, (g.phase, op)
        assert g.private_state("a", clk.t)["can_bet"] is False and g.private_state("a", clk.t)["ops"] == []

    assert g.phase == "locked"
    frozen()
    clk.t += LOCK_SECONDS + 0.01
    g.tick()
    assert g.phase == "dealing"
    frozen()
    clk.t = (g.deal_end or 0) + 0.01
    g.tick()
    assert g.phase == "action"
    frozen()
    assert g.game_op("b", "hit", {}, clk.t) == "You're not in this hand"  # b never bet
    g.handle("a", "stand", {}, clk.t)
    assert g.phase == "dealing" and g.stage == "dealer"
    frozen()
    _to_result(g, clk)
    assert s.bank.get("a").escrow == 0  # type: ignore[union-attr]


# ================================================================ fairness / shoe
def _play_round(g: Blackjack, clk: Clock, bets: dict[str, int]) -> None:
    g.open_betting()
    for pid, amt in bets.items():
        g.place_bet(pid, "main", amt)
    g.lock()
    for _ in range(400):
        clk.t += 0.25
        g.tick()
        if g.phase == "action":
            if g.stage == "insurance":
                for pid in list(g.ins_pending):
                    g.handle(pid, "no_insurance", {}, clk.t)
            elif g.turn:
                pid, i = g.turn
                h = g.hands[pid][i]
                g.handle(pid, basic_strategy(h.cards, g.dealer[0], g.moves(pid), g.rules), {}, clk.t)
        if g.phase == "result":
            return
    raise AssertionError("round never finished")


def test_every_round_verifies_and_the_shoe_chains() -> None:
    clk = Clock()
    s = CasinoSession(clock=clk)
    s.join("a", 2, name="A")
    s.join("b", 3, name="B")
    s.set_seed("a", "alice")
    g = Blackjack(s, BlackjackRules(decks=1, penetration=60))
    s.use(g)
    outs = []
    for _ in range(14):
        _play_round(g, clk, {"a": 10, "b": 10})
        assert g.result is not None
        outs.append(g.result.outcome)
        v = s.verify(g.result.nonce)
        assert v["ok"] and v["matches"], v
    shuffles = sum(1 for o in outs if o["shuffled"])
    assert shuffles >= 2  # one deck at 60 %: the cut card came out at least once
    for prev, cur in itertools.pairwise(outs):
        if cur["shuffled"]:
            assert cur["shoe"] == full_composition(1)
            continue
        counts = [int(ch) for ch in prev["shoe"]]
        for code in prev["cards"]:
            counts[CARD_KINDS.index(Card.parse(code))] -= 1
        assert "".join(map(str, counts)) == cur["shoe"]  # this round's shoe = last one's minus its cards
    # a forged composition doesn't verify
    assert g.result is not None
    e = s.find_round(g.result.nonce)
    assert e is not None
    shoe = e["outcome"]["shoe"]
    forged = ("0" if shoe[0] != "0" else "1") + shoe[1:]  # claim the shoe had one card more / less
    e["outcome"] = {**e["outcome"], "shoe": forged, "shuffled": False}
    assert not s.verify(e["round"])["ok"]


def test_dealing_shoe_is_a_lazy_fisher_yates() -> None:
    """Dealing lazily from the bottom gives exactly the cards a full Fisher–Yates shuffle puts at the end."""
    rng_a, rng_b = fair.Rng(b"s" * 32, "c", 9), fair.Rng(b"s" * 32, "c", 9)
    full = [c for c, n in zip(CARD_KINDS, [2] * 52, strict=True) for _ in range(n)]
    rng_a.shuffle(full)
    shoe = DealingShoe(2)
    shoe.begin(rng_b)
    lazy = [shoe.draw() for _ in range(104)]
    assert lazy == list(reversed(full))


def test_closing_the_table_mid_hand_plays_it_out(monkeypatch: pytest.MonkeyPatch) -> None:
    s, clk, g = _table(1, "TS 9D 8C 7H 5S", monkeypatch)
    _deal(g, clk, {"a": 10})
    assert g.phase == "action"
    g.abort()
    assert s.bank.get("a").escrow == 0  # type: ignore[union-attr]
    # a's 18 stands (the safe default), the dealer's 16 draws the 5: 21 — the hand was paid, not voided
    assert s.history[-1]["game"] == "blackjack" and s.bank.credits("a") == 990


def test_outcome_never_depends_on_bets(monkeypatch: pytest.MonkeyPatch) -> None:
    res = []
    for big in (False, True):
        seeds = iter([bytes([i]) * 32 for i in range(1, 30)])
        monkeypatch.setattr(fair, "new_server_seed", lambda seeds=seeds: next(seeds))
        clk = Clock()
        s = CasinoSession(clock=clk)
        s.join("a", 2)
        s.bank.set_credits("a", 100_000)
        g = Blackjack(s, BlackjackRules())
        s.use(g)
        for _ in range(5):
            _play_round(g, clk, {"a": 500 if big else 1})
        res.append([e["outcome"]["cards"][:4] for e in s.history])
    assert res[0] == res[1]


# ========================================================== the house edge, simulated
def _simulate(rules: BlackjackRules, hands: int, seed: int) -> float:
    clk = Clock()
    s = CasinoSession(clock=clk)
    s.host_op("settings", {"max_bet": 1000})
    s.join("a", 2)
    s.bank.set_credits("a", 10**8)
    g = Blackjack(s, rules)
    s.use(g)
    seeds = iter(range(10**9))
    real = fair.Round.fresh
    fair_round = fair.Round

    def fresh(nonce: int) -> fair.Round:
        k = f"{seed}-{next(seeds)}".encode().ljust(32, b".")
        return fair_round(nonce=nonce, server_seed=k, hash=fair.commit(k))

    fair.Round.fresh = staticmethod(fresh)  # type: ignore[method-assign]
    try:
        start = s.bank.credits("a")
        for _ in range(hands):
            _play_round(g, clk, {"a": 100})
            s.bank.ledger.clear()
            s.history.clear()
    finally:
        fair.Round.fresh = real  # type: ignore[method-assign]
    return -(s.bank.credits("a") - start) / (100 * hands)


def test_basic_strategy_house_edge_is_in_the_textbook_range() -> None:
    """60 000 hands of basic strategy through the real engine (6 decks, S17, DAS, late surrender, 3:2): the edge
    lands within 4 standard errors (SD ≈ 1.15 per hand) of the rule-table estimate."""
    rules = BlackjackRules()
    n = 60_000
    edge = _simulate(rules, n, 1)
    se = 1.15 / n**0.5
    assert abs(edge - house_edge(rules)) < 4 * se + 0.002, (edge, house_edge(rules))
    assert -0.02 < edge < 0.025


def test_rule_estimates_and_insurance_edge() -> None:
    assert house_edge(BlackjackRules(surrender="none")) == 0.004  # the base table: 6D S17 DAS peek 3:2
    assert house_edge(BlackjackRules(blackjack_pays="6:5")) > house_edge(BlackjackRules()) + 0.013
    assert house_edge(BlackjackRules(soft17="hit")) > house_edge(BlackjackRules())
    assert house_edge(BlackjackRules(decks=1)) < house_edge(BlackjackRules(decks=8))
    assert round(insurance_edge(6), 4) == 0.074  # 1 − 3·96/311
    assert round(insurance_edge(1), 4) == 0.0588  # 1 − 3·16/51


# ====================================================================== protocol
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


def test_phone_protocol_moves_and_public_hands(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "casino_blackjack"}).json()["code"]
        assert 'registerGame("blackjack"' in c.get(f"/p/{code}").text
        app = c.app.state.engine._slot("casino_blackjack").app
        clk = Clock()
        app.session.clock = clk
        with c.websocket_connect(f"/ws/p/{code}?cid=phoneBJAAA1") as a:
            a.receive_json()
            a.send_text(json.dumps({"type": "casino", "op": "bet", "spot": "main", "amount": 10}))
            _state(a, lambda m: m.get("private", {}).get("bets") == {"main": 10})
            c.post("/api/apps/casino_blackjack/actions/casino", json={"op": "lock"})
            clk.t += 30
            m = _state(a, lambda m: m["status"]["phase"] in ("action", "dealing", "result"))
            tab = m["status"]["table"]
            assert tab["dealer"]["cards"][1] == "??" or tab["stage"] in ("dealer", "done")  # hole card hidden
            assert len(tab["seats"]) == 1 and len(tab["seats"][0]["hands"][0]["cards"]) == 2
            if m["status"]["phase"] == "action" and m["private"]["moves"]:
                assert "stand" in m["private"]["moves"] or "no_insurance" in m["private"]["moves"]
                a.send_text(json.dumps({"type": "casino", "op": "bet", "spot": "main", "amount": 10}))
                m = _state(a, lambda m: (m["private"].get("notice") or {}).get("text") == "Bets are closed")
                assert m["private"]["bets"] == {"main": 10}
                for mv in ("no_insurance", "stand"):
                    a.send_text(json.dumps({"type": "casino", "op": mv}))

            def done(m: dict[str, Any]) -> bool:
                clk.t += 5  # nobody else acts: timers run out (stand) and the dealer plays
                return bool(m["status"]["phase"] == "result")

            m = _state(a, done, timeout=8.0)
            assert "net" in m["private"]["result"] and m["status"]["result"]["outcome"]["cards"]
            assert m["status"]["table"]["dealer"]["hole"] is False


# ====================================================================== render
async def test_render_every_view_fast(engine: Any) -> None:
    from deskdot.apps._casino import VIEWS
    from deskdot.gfx import Frame

    app_id = "casino_blackjack"
    worst, total, n = 0.0, 0.0, 0
    gc.collect()
    gc.disable()
    try:
        for view in VIEWS:
            engine.store.section("apps")[app_id] = {"view": view}
            engine.slots.clear()
            app = engine._slot(app_id).app
            app.render(Frame(), 0.0)  # the demo table is built once per demo round (cached)
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


async def test_live_table_with_1_4_8_players(engine: Any) -> None:
    from deskdot.gfx import Frame

    for players in (1, 4, 8):
        engine.slots.clear()
        engine.shared.clear()
        app = engine._slot("casino_blackjack").app
        clk = Clock()
        app.session.clock = clk
        for i in range(players):
            await app.action(
                "seat",
                {"player": i + 2, "joined": True, "name": f"P{i}", "color": "#ff3c5a", "pid": f"pid{i:04d}"},
            )
            await app.action("casino", {"op": "bet", "spot": "main", "amount": 10, "player": i + 2})
        await app.action("casino", {"op": "lock", "player": "host"})
        for _ in range(1600):  # nobody acts: every turn times out to stand
            clk.t += 0.25
            app.render(Frame(), clk.t)
            if app.game.phase == "result":
                break
        assert app.game.phase == "result"
        assert all(w.escrow == 0 for w in app.session.bank.wallets.values())
        st = app.status()
        assert len(st["table"]["seats"]) == players
