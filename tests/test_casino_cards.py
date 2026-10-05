"""Casino wave 2 (docs/CASINO.md §7–9): Texas Hold'em, Teen Patti, Andar Bahar and Big Six — exact odds, the
poker side-pot builder, action validation, Teen Patti's show / sideshow rules, privacy of hole cards, frozen bets,
and the panel art (render speed in every view, the wheel landing exactly on the drawn segment)."""

from __future__ import annotations

import gc
import json
import time
from fractions import Fraction
from itertools import combinations, pairwise
from math import comb
from typing import Any

import pytest

from deskdot.casino import CasinoSession, fair
from deskdot.casino.cards import Card, cards, new_deck, teen_patti_name, teen_patti_rank
from deskdot.casino.games import _pvp
from deskdot.casino.games._pvp import Player, build_pots, snapshot_pots, split_pot
from deskdot.casino.games.andarbahar import BANDS, P_FIRST, AndarBahar, AndarBaharRules, p_count
from deskdot.casino.games.bigsix import SYMBOLS, WHEEL, BigSix
from deskdot.casino.games.holdem import Holdem, HoldemRules
from deskdot.casino.games.teenpatti import TeenPatti, TeenPattiRules
from deskdot.casino.table import LOCK_SECONDS

APPS = ("casino_holdem", "casino_teenpatti", "casino_andarbahar", "casino_bigsix")


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _session(**house: Any) -> tuple[CasinoSession, Clock]:
    clk = Clock()
    s = CasinoSession(clock=clk)
    if house:
        s.host_op("settings", house)
    return s, clk


def _rig(monkeypatch: pytest.MonkeyPatch, codes: str) -> None:
    """The next shuffles put these cards on top (the rest of the deck follows in order)."""
    top = cards(codes)
    rest = [c for c in new_deck() if c not in top]
    monkeypatch.setattr(_pvp, "shuffled_deck", lambda rng: list(top) + rest)


def _table(
    cls: Any, n: int, credits: list[int] | None = None, rules: Any = None, **house: Any
) -> tuple[Any, Clock]:
    """A PvP table with players p0..p{n-1} (seats 2…), dealt in and at the first turn."""
    s, clk = _session(**house)
    for i in range(n):
        s.join(f"p{i}", i + 2, name=f"P{i}")
        if credits:
            s.bank.set_credits(f"p{i}", credits[i])
    g = cls(s, rules)
    s.use(g)
    g.open_betting(clk.t)
    assert g.lock(clk.t)
    clk.t += LOCK_SECONDS + g.deal_beat + 0.01
    g.tick(clk.t)
    return g, clk


def _act(g: Any, clk: Clock, pid: str, op: str, **payload: Any) -> Any:
    clk.t += 0.2
    g.tick(clk.t)
    return g.handle(pid, op, payload, clk.t)


def _to_turn(g: Any, clk: Clock) -> str:
    """Advance through animation beats until somebody must act; their pid."""
    for _ in range(100):
        if g.phase == "action" and g.turn is not None:
            return str(g.players[g.turn].pid)
        if g.phase == "result":
            return ""
        clk.t += 0.5
        g.tick(clk.t)
    raise AssertionError("no turn came")


def _finish(g: Any, clk: Clock) -> None:
    for _ in range(100):
        if g.phase == "result":
            return
        clk.t += 0.5
        g.tick(clk.t)
    raise AssertionError("the hand never settled")


# ================================================================== Big Six
def test_big_six_wheel_and_exact_edges() -> None:
    assert len(WHEEL) == 54
    assert {s: WHEEL.count(s) for s in SYMBOLS} == {
        "1": 24,
        "2": 15,
        "5": 7,
        "10": 4,
        "20": 2,
        "joker": 1,
        "logo": 1,
    }
    s, _ = _session()
    ev = BigSix(s).expected_values()
    assert ev == {
        "s1": Fraction(-6, 54),
        "s2": Fraction(-9, 54),
        "s5": Fraction(-12, 54),
        "s10": Fraction(-10, 54),
        "s20": Fraction(-12, 54),
        "joker": Fraction(-13, 54),
        "logo": Fraction(-13, 54),
    }
    g = BigSix(s)
    assert g.returns(g.outcome_at(WHEEL.index("joker"))) == {"joker": Fraction(41)}
    assert g.returns(g.outcome_at(WHEEL.index("20"))) == {"s20": Fraction(21)}
    assert g.spot_table()[0]["pays"] == "1:1"


def test_big_six_wheel_lands_exactly_on_the_drawn_segment() -> None:
    from deskdot.apps.casino_bigsix import SPIN_T, under_clapper, wheel_angle

    for seg in range(54):
        for nonce in (1, 7, 123, 99999):
            assert under_clapper(wheel_angle(SPIN_T, seg, nonce)) == seg
            assert under_clapper(wheel_angle(SPIN_T + 5, seg, nonce)) == seg  # and stays there
    # it decelerates: each second covers less arc than the one before
    arcs = [wheel_angle(t + 1, 5, 3) - wheel_angle(t, 5, 3) for t in range(int(SPIN_T))]
    assert all(a > b for a, b in pairwise(arcs)) and arcs[0] > 2


# =============================================================== Andar Bahar
def test_andar_bahar_exact_probabilities_and_edges() -> None:
    assert sum(p_count(k) for k in range(1, 50)) == 1
    # brute force: positions of the three remaining cards of the joker's rank among the 51
    first: dict[int, int] = {}
    for trio in combinations(range(1, 52), 3):
        first[trio[0]] = first.get(trio[0], 0) + 1
    assert all(Fraction(first.get(k, 0), comb(51, 3)) == p_count(k) for k in range(1, 50))
    assert Fraction(429, 833) == P_FIRST
    s, _ = _session()
    ev = AndarBahar(s).expected_values()
    assert ev["andar"] == Fraction(-179, 8330)  # first card to Andar, pays 0.9:1 → 2.149 %
    assert ev["bahar"] == Fraction(-25, 833)  # pays 1:1 → 3.001 %
    for sid, a, b, p, pay in BANDS:
        assert p == sum(p_count(k) for k in range(a, b + 1))
        edge = -ev[sid]
        assert Fraction(5, 100) <= edge < Fraction(7, 100), (sid, float(edge))
        assert edge == 1 - p * (pay + 1)
    assert sum(b[3] for b in BANDS) == 1
    # first card to Bahar: the payouts follow the advantage (Bahar 0.9:1, Andar 1:1) — never a player edge
    ev_b = AndarBahar(s, AndarBaharRules(first="bahar")).expected_values()
    assert ev_b["bahar"] == Fraction(-179, 8330) and ev_b["andar"] == Fraction(-25, 833)
    no_side = AndarBahar(s, AndarBaharRules(side_bets=False))
    assert set(no_side.spots()) == {"andar", "bahar"}


def test_andar_bahar_deal_follows_the_shuffle() -> None:
    s, _ = _session()
    g = AndarBahar(s)
    for n in range(1, 30):
        rng = fair.Rng(b"k" * 32, "c", n)
        o = g.draw(rng)
        deck = _pvp.shuffled_deck(fair.Rng(b"k" * 32, "c", n))
        assert o["joker"] == deck[0].code
        dealt = [Card.parse(c) for c in o["cards"]]
        assert [c.code for c in deck[1 : 1 + len(dealt)]] == o["cards"]
        assert dealt[-1].rank == deck[0].rank and all(c.rank != deck[0].rank for c in dealt[:-1])
        assert o["winner"] == ("andar" if len(dealt) % 2 else "bahar") and o["count"] == len(dealt)
        ret = g.returns(o)
        assert ret[o["winner"]] == (Fraction(19, 10) if o["winner"] == "andar" else 2)
        assert sum(1 for k in ret if k.startswith("c:")) == 1


@pytest.mark.parametrize("game_cls", [AndarBahar, BigSix])
def test_house_games_bets_frozen_from_lock_until_settlement(game_cls: Any) -> None:
    s, clk = _session()
    s.join("a", 2)
    g = game_cls(s)
    s.use(g)
    g.open_betting()
    spot = "andar" if game_cls is AndarBahar else "s2"
    assert g.place_bet("a", spot, 20) is None
    g.lock()
    snap = (json.dumps(g.bets), s.bank.credits("a"))
    for step in (0.0, LOCK_SECONDS + 0.05, 0.3):
        clk.t += step
        g.tick()
        assert g.phase in ("locked", "spinning", "dealing")
        for op, pl in (
            ("bet", {"spot": spot, "amount": 5}),
            ("unbet", {"spot": spot}),
            ("clear", {}),
            ("rebet", {}),
        ):
            g.handle("a", op, pl, clk.t)
            assert (json.dumps(g.bets), s.bank.credits("a")) == snap
    clk.t += 30
    g.tick()
    assert g.phase == "result" and s.bank.get("a").escrow == 0  # type: ignore[union-attr]
    r = g.result.payouts["a"]
    expect = g.returns(g.outcome).get(spot, 0) * 20
    assert r["payout"] == int(expect)


def test_andar_bahar_reveal_waits_for_the_whole_deal() -> None:
    from deskdot.casino.games.andarbahar import deal_seconds

    s, clk = _session()
    s.join("a", 2)
    g = AndarBahar(s)
    s.use(g)
    g.open_betting()
    g.place_bet("a", "bahar", 10)
    g.lock()
    n = g.outcome["count"]
    assert g.reveal_at == pytest.approx(clk.t + LOCK_SECONDS + deal_seconds(n))
    assert deal_seconds(1) >= 2 and deal_seconds(49) <= 11


# ============================================================ pots & splits
def test_build_pots_side_pots_and_folded_money() -> None:
    # A all-in 50, B all-in 120, C and D bet 300; E folded after putting in 30
    contrib = {"a": 50, "b": 120, "c": 300, "d": 300, "e": 30}
    pots = build_pots(contrib, ["a", "b", "c", "d"])
    assert [(p.amount, p.eligible) for p in pots] == [
        (50 * 4 + 30, ["a", "b", "c", "d"]),
        (70 * 3, ["b", "c", "d"]),
        (180 * 2, ["c", "d"]),
    ]
    assert sum(p.amount for p in pots) == sum(contrib.values())
    # an uncalled bet comes back as a one-player pot
    pots = build_pots({"a": 1000, "b": 200}, ["a", "b"])
    assert [(p.amount, p.eligible) for p in pots] == [(400, ["a", "b"]), (800, ["a"])]
    # a folded player who put in more than an all-in player: their money above that level goes up a pot
    pots = build_pots({"a": 40, "b": 100, "c": 100, "f": 80}, ["a", "b", "c"])
    assert [(p.amount, p.eligible) for p in pots] == [(160, ["a", "b", "c"]), (160, ["b", "c"])]


def test_split_pot_odd_chips_go_left_of_the_button() -> None:
    order = ["c", "d", "a", "b"]  # clockwise from the first seat after the button
    assert split_pot(101, ["a", "c"], order) == {"c": 51, "a": 50}
    assert split_pot(100, ["a", "b", "d"], order) == {"d": 34, "a": 33, "b": 33}
    assert split_pot(7, ["b"], order) == {"b": 7}


def test_snapshot_pots_for_teen_patti() -> None:
    a = Player("a", 2, 0, total=30, allin=True, cap=100)
    b = Player("b", 3, 500, total=200)
    c = Player("c", 4, 500, total=200)
    pots = snapshot_pots(430, [a, b, c])
    assert [(p.amount, p.eligible) for p in pots] == [(100, ["a", "b", "c"]), (330, ["b", "c"])]


# ================================================================== Hold'em
def test_holdem_blinds_order_and_heads_up(monkeypatch: pytest.MonkeyPatch) -> None:
    g, clk = _table(Holdem, 3)
    assert [p.last for p in g.players] == ["", "SB", "BB"]  # button p0, SB p1, BB p2
    assert [p.total for p in g.players] == [0, 5, 10]
    assert _to_turn(g, clk) == "p0"  # left of the big blind
    # heads-up: the button posts the small blind and acts first pre-flop, last after the flop
    h, clk2 = _table(Holdem, 2)
    btn = h.players[h.button]
    assert btn.last == "SB" and _to_turn(h, clk2) == btn.pid
    assert _act(h, clk2, btn.pid, "call") is None
    other = h.players[1 - h.button].pid
    assert _to_turn(h, clk2) == other  # big blind's option
    assert _act(h, clk2, other, "check") is None
    assert _to_turn(h, clk2) == other and h.street == "flop"  # post-flop the non-button acts first


def test_holdem_action_validation() -> None:
    g, clk = _table(Holdem, 4)
    first = _to_turn(g, clk)
    nxt = g.players[(g.turn + 1) % 4].pid
    assert _act(g, clk, nxt, "call") == "It's not your turn"
    assert _act(g, clk, first, "check") is not None  # there's a big blind to call
    assert _act(g, clk, first, "raise", amount=15) == "Minimum raise is to 20"
    assert _act(g, clk, first, "raise", amount=10**9) is not None
    assert _act(g, clk, first, "raise", amount=35) is None  # a raise of 25
    p = _to_turn(g, clk)
    lg = g.legal(g.by_pid(p))
    assert lg["min_to"] == 60 and lg["to_call"] == 35  # the next raise must be at least 25 more
    assert _act(g, clk, p, "raise", amount=59) == "Minimum raise is to 60"
    for op in ("bet", "unbet", "clear", "rebet", "done"):  # no chips to place at a poker table
        assert g.handle(p, op, {"spot": "x", "amount": 5}, clk.t) is not None


def test_holdem_short_all_in_does_not_reopen_the_betting() -> None:
    g, clk = _table(Holdem, 3, credits=[1000, 1000, 1000])
    a = _to_turn(g, clk)  # p0 (button), then p1 SB, p2 BB
    assert _act(g, clk, a, "raise", amount=100) is None
    b = _to_turn(g, clk)
    g.by_pid(b).stack = 120 - g.by_pid(b).bet  # p1 can only go to 120 in total
    assert _act(g, clk, b, "allin") is None  # 120 < 100 + 90: not a full raise
    c = _to_turn(g, clk)
    assert "raise" in g.legal(g.by_pid(c))["ops"]  # p2 hasn't acted yet: may raise
    assert _act(g, clk, c, "call") is None
    assert _to_turn(g, clk) == a
    lg = g.legal(g.by_pid(a))
    assert "raise" not in lg["ops"] and lg["to_call"] == 20  # p0 faces an incomplete raise: call or fold only


def test_holdem_timer_checks_if_free_else_folds() -> None:
    g, clk = _table(Holdem, 3, turn_seconds=5)
    p = _to_turn(g, clk)
    clk.t += 5.1
    g.tick(clk.t)
    assert g.by_pid(p).folded  # facing the big blind: fold
    q = _to_turn(g, clk)
    assert _act(g, clk, q, "call") is None
    bb = _to_turn(g, clk)
    clk.t += 5.1
    g.tick(clk.t)
    assert not g.by_pid(bb).folded and g.street == "flop"  # free: checked, and the flop came


def test_holdem_side_pots_and_split_with_odd_chip(monkeypatch: pytest.MonkeyPatch) -> None:
    # p0 button, p1 SB, p2 BB. Deal order p1 p2 p0 p1 p2 p0, burn, flop, burn, turn, burn, river.
    # p0 AA (short, all-in 100), p1 KK (300), p2 AK... board gives p1 a set of kings; p0 second, p2 last.
    _rig(monkeypatch, "KS QD AH KH QC AD 2C KD 7S 3H 4C 8D 5H 9C")
    g, clk = _table(Holdem, 3, credits=[100, 300, 1000])
    assert [c.code for c in g.by_pid("p1").cards] == ["KS", "KH"]
    assert _act(g, clk, _to_turn(g, clk), "allin") is None  # p0 all-in 100
    assert _act(g, clk, _to_turn(g, clk), "allin") is None  # p1 all-in 300
    assert _act(g, clk, _to_turn(g, clk), "call") is None  # p2 calls 300
    _finish(g, clk)
    assert [c.code for c in g.board] == ["KD", "7S", "3H", "8D", "9C"]
    # main 300 (all three) and side 400 (p1, p2): kings full win both
    assert g.awards == {"p1": 700}
    nets = {pid: v["net"] for pid, v in g.result.payouts.items()}
    assert nets == {"p0": -100, "p1": 400, "p2": -300} and sum(nets.values()) == 0
    assert all(w.escrow == 0 for w in g.session.bank.wallets.values())
    st = g.public_state(clk.t)
    assert (
        st["table"]["showdown"]["3"] == ["KS", "KH"]
        and st["table"]["winners"][0]["hand"] == "three of a kind"
    )


def test_holdem_split_pot_odd_chip(monkeypatch: pytest.MonkeyPatch) -> None:
    # board is a royal straight for everyone: a three-way chop of a pot with an odd chip
    _rig(monkeypatch, "2C 3D 4S 2D 3H 4C 5S AS KS QS 6H JS 7H TS")
    g, clk = _table(Holdem, 3, rules=HoldemRules(small_blind=5, big_blind=10))
    a = _to_turn(g, clk)
    assert _act(g, clk, a, "raise", amount=31) is None  # pot will be 31 × 3 + … odd
    for _ in range(2):
        assert _act(g, clk, _to_turn(g, clk), "call") is None
    while g.phase != "result":
        p = _to_turn(g, clk)
        if not p:
            break
        _act(g, clk, p, "check")
    _finish(g, clk)
    total = sum(p.total for p in g.players)
    assert total == 93 and sorted(g.awards.values()) == [31, 31, 31]
    g2, _ = _table(Holdem, 3)
    order = g2.from_button(g2.button)
    assert split_pot(94, ["p0", "p1", "p2"], order)[order[0]] == 32


def test_holdem_uncontested_shows_no_cards_and_bust_players_sit_out() -> None:
    g, clk = _table(Holdem, 3, credits=[1000, 1000, 12])
    _act(g, clk, _to_turn(g, clk), "fold")
    _act(g, clk, _to_turn(g, clk), "fold")
    _finish(g, clk)
    st = g.public_state(clk.t)
    assert st["table"]["showdown"] == {} and g.result.summary["hand"] == ""
    assert g.result.payouts["p2"]["net"] == 5  # the big blind takes the small blind
    g.session.bank.set_credits("p0", 3)  # can't cover a big blind any more
    clk.t += 60
    g.tick(clk.t)
    assert g.phase in ("betting", "locked", "dealing", "action")
    assert "p0" not in g.ready()


def test_holdem_verify_replays_the_deck() -> None:
    g, clk = _table(Holdem, 2)
    _act(g, clk, _to_turn(g, clk), "fold")
    _finish(g, clk)
    v = g.session.verify(g.result.nonce)
    assert v["ok"] and v["matches"]
    assert sorted(g.outcome["deck"].split()) == sorted(c.code for c in new_deck())


# ================================================================ privacy
@pytest.mark.parametrize("cls", [Holdem, TeenPatti])
def test_hole_cards_never_public_nor_in_other_seats_private_state(cls: Any) -> None:
    g, clk = _table(cls, 4)
    if cls is TeenPatti:
        for p in g.players:
            g.handle(p.pid, "see", {}, clk.t)
    for _ in range(3):
        pub = json.dumps(g.public_state(clk.t))
        board = set(getattr(g, "board", []) and [c.code for c in g.board])
        for p in g.players:
            for c in p.cards:
                if c.code not in board:
                    assert f'"{c.code}"' not in pub, c.code
            for q in g.players:
                if q is p:
                    continue
                priv = json.dumps(g.private_state(q.pid, clk.t))
                for c in p.cards:
                    if c.code not in board:
                        assert f'"{c.code}"' not in priv
            mine = g.private_state(p.pid, clk.t)
            assert mine["cards"] == [c.code for c in p.cards]
        pid = _to_turn(g, clk)
        _act(g, clk, pid, "call" if cls is Holdem else "chaal")


def test_teen_patti_blind_player_gets_no_cards_until_seen() -> None:
    g, clk = _table(TeenPatti, 3)
    p = g.players[0]
    assert "cards" not in g.private_state(p.pid, clk.t)
    assert g.private_state(p.pid, clk.t)["ops"] == ["see"]  # not their turn: they may still look
    g.handle(p.pid, "see", {}, clk.t)
    assert g.private_state(p.pid, clk.t)["cards"] == [c.code for c in p.cards]
    assert g.public_state(clk.t)["table"]["seats"][0]["seen"] is True


# =============================================================== Teen Patti
def test_teen_patti_ranking_edge_cases() -> None:
    r = lambda s: teen_patti_rank(cards(s))  # noqa: E731
    assert r("AS KS QS") > r("AH 2H 3H") > r("KD QD JD")  # A-K-Q top, A-2-3 second, then K-Q-J
    assert r("2C 3C 4C") > r("AD KS QH")  # any pure sequence beats any plain sequence
    assert r("4D 3S 2H") < r("5D 4S 3H") and r("AS 2D 3C") > r("KS QD JC")
    assert r("2S 2H 2D") > r("AS KS QS")  # trail beats pure sequence
    assert r("AS AH AD") > r("KS KH KD")
    assert r("2D 3D 4S") > r("AH KH 9H")  # sequence beats colour
    assert r("2H 5H 9H") > r("AS AD KC")  # colour beats pair
    assert r("KS KD 9C") > r("KH KC 5D") and r("2S 2D AC") < r("3S 3D 4C")  # pair, then kicker
    assert r("AS KD 9C") > r("AH KC 8D")  # high card by ranks
    assert r("AS KD QC") == r("AH KC QD")  # exact tie (suits never break ties)
    assert r("AS QD 3C").category == 0 and r("AS 2D 4C").category == 0  # A-2-4 / A-Q-3 are not sequences
    assert teen_patti_name(r("AS 2S 3S")) == "pure sequence"


def test_teen_patti_stakes_blind_seen_raise_and_limits() -> None:
    g, clk = _table(TeenPatti, 3, rules=TeenPattiRules(boot=10, chaal_limit=40, pot_limit=10_000))
    assert g.pot_total() == 30 and g.stake == 10
    p = _to_turn(g, clk)
    lg = g.legal(g.by_pid(p), g.turn)
    assert (lg["chaal"], lg["raise"]) == (10, 20)  # blind: 1×, raise 2×
    assert _act(g, clk, p, "raise") is None and g.stake == 20
    q = _to_turn(g, clk)
    g.handle(q, "see", {}, clk.t)
    lg = g.legal(g.by_pid(q), g.turn)
    assert (lg["chaal"], lg["raise"]) == (40, 80)  # seen: 2×, raise 4×
    assert _act(g, clk, q, "raise") is None and g.stake == 40
    r = _to_turn(g, clk)
    assert "raise" not in g.legal(g.by_pid(r), g.turn)["ops"]  # the stake is at the chaal limit
    assert _act(g, clk, r, "raise") is not None
    assert "show" not in g.legal(g.by_pid(r), g.turn)["ops"]  # three players: no show


def test_teen_patti_show_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    # dealer p0: deal order p1 p0, three rounds → p1 = AS KS QS? p1 gets cards 1,3,5; p0 cards 2,4,6
    _rig(monkeypatch, "AS 9D KS 9C QS 9H")
    g, clk = _table(TeenPatti, 2)
    assert {p.pid: [c.code for c in p.cards] for p in g.players} == {
        "p1": ["AS", "KS", "QS"],
        "p0": ["9D", "9C", "9H"],
    }
    p1 = _to_turn(g, clk)
    assert p1 == "p1"
    g.handle("p1", "see", {}, clk.t)
    lg = g.legal(g.by_pid("p1"), g.turn)
    assert "show" not in lg["ops"]  # a seen player can't ask a blind player for a show
    assert _act(g, clk, "p1", "chaal") is None
    lg = g.legal(g.by_pid("p0"), g.turn)
    assert lg["show"] == 10  # a blind player shows for 1× the stake
    assert _act(g, clk, "p0", "show") is None
    _finish(g, clk)
    assert g.awards == {"p0": g.pot_total()}  # trail beats the pure sequence
    assert g.public_state(clk.t)["table"]["hands"] == {"2": "trail", "3": "pure sequence"}


def test_teen_patti_equal_show_goes_to_the_player_who_did_not_pay(monkeypatch: pytest.MonkeyPatch) -> None:
    _rig(monkeypatch, "AS AH KS KH 9C 9D")  # p1: AS KS 9C · p0: AH KH 9D — identical ranks
    g, clk = _table(TeenPatti, 2)
    assert teen_patti_rank(g.by_pid("p0").cards) == teen_patti_rank(g.by_pid("p1").cards)
    assert _act(g, clk, "p1", "show") is None  # blind p1 pays for the show
    _finish(g, clk)
    assert g.awards == {"p0": g.pot_total()}


def test_teen_patti_sideshow(monkeypatch: pytest.MonkeyPatch) -> None:
    # dealer p0 → order p1 p2 p0. p1: 2C 5D 9H (worst), p2: KS KD 3C, p0: AS AD AH
    _rig(monkeypatch, "2C KS AS 5D KD AD 9H 3C AH")
    g, clk = _table(TeenPatti, 3)
    for pid in ("p0", "p1", "p2"):
        g.handle(pid, "see", {}, clk.t)
    assert _act(g, clk, "p1", "chaal") is None
    assert "sideshow" in g.legal(g.by_pid("p2"), g.turn)["ops"]  # previous player p1 is seen and has bet
    assert _act(g, clk, "p2", "sideshow") is None
    assert g.sideshow == {"from": "p2", "to": "p1", "deadline": pytest.approx(clk.t + 20)}
    assert _act(g, clk, "p0", "chaal") is not None  # everything waits for the answer
    assert g.handle("p0", "accept", {}, clk.t) is not None  # only the asked player answers
    assert g.private_state("p1", clk.t)["ops"] == ["accept", "refuse"]
    assert _act(g, clk, "p1", "accept") is None
    assert g.by_pid("p1").folded and not g.by_pid("p2").folded  # the lower hand packs
    assert g.private_state("p1", clk.t)["peeks"] == {"4": ["KS", "KD", "3C"]}
    assert g.private_state("p0", clk.t)["peeks"] == {}
    assert _to_turn(g, clk) == "p0"


def test_teen_patti_sideshow_refused_on_timeout_and_tie_packs_the_asker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rig(monkeypatch, "KS KH AS QS QH AD 4C 4D AH")  # p1 KS QS 4C == p2 KH QH 4D
    g, clk = _table(TeenPatti, 3, turn_seconds=5)
    for pid in ("p0", "p1", "p2"):
        g.handle(pid, "see", {}, clk.t)
    _act(g, clk, "p1", "chaal")
    _act(g, clk, "p2", "sideshow")
    clk.t += 5.5
    g.tick(clk.t)  # no answer: refused, play goes on with p0
    assert g.sideshow is None and not g.by_pid("p1").folded and _to_turn(g, clk) == "p0"
    _act(g, clk, "p0", "chaal")
    _act(g, clk, "p1", "chaal")
    _act(g, clk, "p2", "sideshow")
    _act(g, clk, "p1", "accept")
    assert g.by_pid("p2").folded and not g.by_pid("p1").folded  # equal hands: the asker packs


def test_teen_patti_blind_limit_pot_limit_and_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    g, clk = _table(
        TeenPatti, 2, rules=TeenPattiRules(boot=10, max_blind_rounds=2, pot_limit=60), turn_seconds=5
    )
    a = _to_turn(g, clk)
    _act(g, clk, a, "chaal")
    b = _to_turn(g, clk)
    _act(g, clk, b, "chaal")
    _act(g, clk, a, "chaal")
    _act(g, clk, b, "chaal")  # boots 20 + four blind chaals of 10 = 60: the pot limit forces the show
    _finish(g, clk)
    assert g.end_kind == "limit" and len(g.showdown) == 2
    h, clk2 = _table(TeenPatti, 2, rules=TeenPattiRules(boot=10, max_blind_rounds=2), turn_seconds=5)
    x = _to_turn(h, clk2)
    _act(h, clk2, x, "chaal")
    y = _to_turn(h, clk2)
    _act(h, clk2, y, "chaal")
    _act(h, clk2, x, "chaal")
    assert x not in h.seen
    _act(h, clk2, y, "chaal")
    assert _to_turn(h, clk2) == x and x in h.seen  # two blind bets made: the cards open
    clk2.t += 5.5
    h.tick(clk2.t)
    assert h.by_pid(x).folded  # the timer packs
    _finish(h, clk2)
    assert h.result.payouts[y]["net"] > 0


def test_pvp_outcome_ignores_play_and_conserves_credits() -> None:
    for cls in (Holdem, TeenPatti):
        g, clk = _table(cls, 4)
        total0 = sum(w.credits + w.escrow for w in g.session.bank.wallets.values())
        for k in range(200):
            p = _to_turn(g, clk)
            if not p:
                break
            ops = (g.legal(g.by_pid(p)) if cls is Holdem else g.legal(g.by_pid(p), g.turn))["ops"]
            if k == 1 and "raise" in ops:
                op = "raise"
                _act(g, clk, p, op, amount=g.legal(g.by_pid(p))["min_to"]) if cls is Holdem else _act(
                    g, clk, p, op
                )
                continue
            if k == 2:
                _act(g, clk, p, "fold" if cls is Holdem else "pack")
                continue
            _act(g, clk, p, next(o for o in ("show", "call", "check", "chaal") if o in ops))
        _finish(g, clk)
        total1 = sum(w.credits + w.escrow for w in g.session.bank.wallets.values())
        assert total0 == total1 and all(w.escrow == 0 for w in g.session.bank.wallets.values())


# ================================================================== panel
@pytest.mark.parametrize("app_id", APPS)
async def test_render_every_view_fast(engine: Any, app_id: str) -> None:
    from deskdot.engine import REGISTRY
    from deskdot.gfx import Frame

    views = list(REGISTRY[app_id].Settings.model_fields["view"].json_schema_extra["enum"])  # type: ignore[index]
    worst, total, n = 0.0, 0.0, 0
    gc.collect()
    gc.disable()
    try:
        for view in views:
            engine.store.section("apps")[app_id] = {"view": view}
            engine.slots.clear()
            app = engine._slot(app_id).app
            for t in (0.0, 0.4, 1.3, 2.7, 4.1, 6.0, 8.2, 9.9, 13.0, 17.5, 25.0, 33.0):
                f = Frame()
                t0 = time.perf_counter()
                app.render(f, t)
                dt = time.perf_counter() - t0
                worst, total, n = max(worst, dt), total + dt, n + 1
                if view not in ("live", "lobby"):
                    assert f.px.any(), (view, t)
    finally:
        gc.enable()
    assert worst < 0.05, f"{app_id} worst render {worst * 1000:.1f} ms"
    assert total / n < 0.004, f"{app_id} typical render {total / n * 1000:.2f} ms"


async def test_live_pvp_table_from_phones(engine: Any) -> None:
    """A live Hold'em table with 1, 4 and 8 players, played from the protocol until the hand settles."""
    from deskdot.gfx import Frame

    for players in (1, 4, 8):
        engine.slots.clear()
        engine.shared.clear()
        app = engine._slot("casino_holdem").app
        clk = Clock()
        app.session.clock = clk
        for i in range(players):
            await app.action(
                "seat",
                {"player": i + 2, "joined": True, "name": f"P{i}", "color": "#ff3c5a", "pid": f"pid{i:04d}"},
            )
        r = await app.action("casino", {"op": "bet", "spot": "x", "amount": 5, "player": 2})
        assert r["ok"] is False
        app.render(Frame(), 0)
        clk.t += 30
        app.render(Frame(), 0)
        if players == 1:
            assert app.game.phase == "betting"  # nobody to play against
            continue
        for _ in range(400):
            g = app.game
            if g.phase == "action" and g.turn is not None:
                seat = g.players[g.turn].seat
                pv = app.private_status(seat)
                assert pv["my_turn"] and pv["ops"]
                op = "check" if "check" in pv["ops"] else "call"
                assert (await app.action("casino", {"op": op, "player": seat}))["ok"]
            clk.t += 0.3
            app.render(Frame(), clk.t)
            if g.phase == "result":
                break
        assert app.game.phase == "result"
        assert all(w.escrow == 0 for w in app.session.bank.wallets.values())
        st = app.status()
        assert st["pvp"] is True and len(st["table"]["seats"]) == players


def test_replay_vectors_shared_with_the_phone() -> None:
    """casino.html's replay() for these games computes the same outcomes (checked in a browser, 2026-10-04)."""
    from deskdot.casino.table import GAMES

    seed = bytes(range(32))
    deck = GAMES["holdem"].replay({}, fair.Rng(seed, "alice.bob", 7))["deck"]
    assert deck.startswith("KS 2C QC QD 5C TH 9H 9C 6C 6D 9S 6S 7C 8S") and deck.endswith(
        "AS KD AD 3H 5S 9D AC"
    )
    assert GAMES["teenpatti"].replay({}, fair.Rng(seed, "alice.bob", 7))["deck"] == deck
    ab = GAMES["andarbahar"].replay({"first": "bahar"}, fair.Rng(seed, "alice.bob", 7))
    assert (ab["joker"], ab["count"], ab["winner"], ab["cards"][-1]) == ("KS", 19, "bahar", "KC")
    assert GAMES["bigsix"].replay({}, fair.Rng(seed, "alice.bob", 7)) == {"segment": 53, "symbol": "1"}


def test_andar_bahar_exact_card_option() -> None:
    """Host option match="card": only the joker's identical twin wins, dealt from a second shuffled deck."""
    from deskdot.casino.games.andarbahar import BANDS_EXACT

    s, _ = _session()
    g = AndarBahar(s, AndarBaharRules(match="card"))
    ev = g.expected_values()
    assert ev["andar"] == ev["bahar"] == Fraction(-1, 40)  # each side wins 1/2 and pays 0.95:1 → 2.5 %
    assert sum(b[3] for b in BANDS_EXACT) == 1 and BANDS_EXACT[-1][2] == 52
    for sid, _a, _b, p, pay in BANDS_EXACT:
        assert Fraction(5, 100) <= -ev[sid] < Fraction(8, 100), sid
        assert -ev[sid] == 1 - p * (pay + 1)
    for n in range(1, 40):
        rng = fair.Rng(b"x" * 32, "c", n)
        o = g.draw(rng)
        r2 = fair.Rng(b"x" * 32, "c", n)
        joker = _pvp.shuffled_deck(r2)[0]
        second = _pvp.shuffled_deck(r2)
        assert o["joker"] == joker.code and o["match"] == "card"
        assert o["cards"] == [c.code for c in second[: o["count"]]]
        assert o["cards"][-1] == joker.code and joker.code not in o["cards"][:-1]
        assert o["winner"] == ("andar" if o["count"] % 2 else "bahar")
        assert g.returns(o)[o["winner"]] == Fraction(195, 100)
    assert AndarBahar(s).draw(fair.Rng(b"x" * 32, "c", 1))["match"] == "value"  # the default is unchanged
