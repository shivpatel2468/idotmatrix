"""Casino mode (docs/CASINO.md): provably fair RNG, the bank, card rankings, the round machine, roulette and
7 Up 7 Down payouts (exact house edges), frozen bets after the lock, the phone protocol and render speed."""

from __future__ import annotations

import gc
import json
import time
from collections import Counter
from fractions import Fraction
from itertools import permutations
from pathlib import Path
from typing import Any

import pytest

from deskdot.casino import CasinoSession, fair
from deskdot.casino.bank import Bank
from deskdot.casino.cards import (
    Card,
    Shoe,
    baccarat_total,
    best_of,
    blackjack_total,
    cards,
    new_deck,
    poker_rank5,
    poker_rank7,
    teen_patti_name,
    teen_patti_rank,
)
from deskdot.casino.games.roulette import DOUBLE_ZERO, EU_WHEEL, US_WHEEL, Roulette, RouletteRules
from deskdot.casino.games.sevens import Sevens, SevensRules
from deskdot.casino.table import LOCK_SECONDS


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


def _seat(s: CasinoSession, pid: str, seat: int, seed: str = "") -> None:
    s.join(pid, seat, name=pid.upper())
    if seed:
        assert s.set_seed(pid, seed) is None


def _finish(g: Any, clk: Clock) -> None:
    """Run a locked round to its result."""
    clk.t += LOCK_SECONDS + g.spin_seconds + 0.01
    g.tick()
    assert g.phase == "result"


# =================================================================== fairness
def test_rng_pinned_vector_and_determinism() -> None:
    """These numbers are also what casino.html's JavaScript port computes (checked in a browser)."""
    seed = bytes(range(32))
    assert fair.commit(seed) == "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd"
    r = fair.Rng(seed, "alice.bob", 7)
    assert [r.u32() for _ in range(3)] == [2318060159, 2460596217, 872695403]
    r1, r2 = fair.Rng(seed, "alice.bob", 7), fair.Rng(seed, "alice.bob", 7)
    assert [r1.randint(0, 36) for _ in range(50)] == [r2.randint(0, 36) for _ in range(50)]
    assert fair.Rng(seed, "alice.bob", 7).randint(0, 36) == 21
    assert [fair.Rng(seed, "alice.bob", n).u32() for n in (1, 2)] != [
        fair.Rng(seed, "alice.bob", 1).u32()
    ] * 2
    assert fair.Rng(seed, "x", 1).u32() != fair.Rng(seed, "y", 1).u32()


def test_rejection_sampling_has_no_modulo_bias() -> None:
    """Words at or above the largest multiple of n are thrown away, never folded in."""
    r = fair.Rng(b"k" * 32, "c", 1)
    limit = 2**32 - (2**32 % 37)
    feed = iter([limit, 2**32 - 1, limit - 1, 74])
    r.u32 = lambda: next(feed)  # type: ignore[method-assign]
    assert r.below(37) == (limit - 1) % 37  # the first two (biased) words were rejected
    assert r.below(37) == 0
    # statistical sanity: 37 000 spins are close to uniform (chi-square, 36 dof; p ≈ 1e-6 cut-off)
    r = fair.Rng(b"\x07" * 32, "stats", 3)
    n = 37_000
    c = Counter(r.below(37) for _ in range(n))
    chi2 = sum((c[k] - n / 37) ** 2 / (n / 37) for k in range(37))
    assert len(c) == 37 and chi2 < 85


def test_shuffle_is_a_uniform_permutation() -> None:
    deck = new_deck()
    r = fair.Rng(b"s" * 32, "c", 1)
    sh = r.shuffle(list(deck))
    assert sorted(sh) == sorted(deck) and sh != deck
    counts: Counter[tuple[int, ...]] = Counter()
    rr = fair.Rng(b"p" * 32, "c", 2)
    for _ in range(6000):
        counts[tuple(rr.shuffle([0, 1, 2]))] += 1
    assert set(counts) == set(permutations(range(3)))
    assert all(800 < v < 1200 for v in counts.values())


def test_verify_round() -> None:
    rnd = fair.Round.fresh(5)
    assert rnd.proof()["server_seed"] is None  # secret until revealed
    rng = rnd.lock(["aa", "", "bb"])
    assert rnd.client_seed == "aa.bb"
    first = rng.randint(0, 36)
    rnd.revealed = True
    pr = rnd.proof()
    ok = fair.verify(
        pr["server_seed"], pr["hash"], pr["client_seed"], pr["nonce"], lambda g: g.randint(0, 36)
    )
    assert ok["ok"] and ok["outcome"] == first
    bad = fair.verify("00" * 32, pr["hash"], pr["client_seed"], pr["nonce"])
    assert not bad["ok"] and not bad["hash_ok"]
    assert not fair.verify("zz", pr["hash"], "c", 1)["ok"]
    assert fair.client_seed([]) == fair.HOUSE_CLIENT_SEED
    assert fair.clean_client_seed("a:b c") == "abc" and fair.clean_client_seed(5) is None


def test_session_verify_and_outcome_ignores_bets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same seeds → same results whatever anyone bets or holds: the house never adapts."""
    results = []
    for betting in (False, True):
        seeds = iter([bytes([i]) * 32 for i in range(1, 40)])
        monkeypatch.setattr(fair, "new_server_seed", lambda seeds=seeds: next(seeds))
        s, clk = _session(bet_seconds=10)
        _seat(s, "a", 2, "seedA")
        _seat(s, "b", 3, "seedB")
        if betting:
            s.bank.set_credits("a", 50_000)
        g = Roulette(s)
        s.use(g)
        out = []
        for i in range(12):
            g.open_betting()
            if betting:
                g.place_bet("a", "n:17", 500)
                g.place_bet("b", "red" if i % 2 else "black", 7)
            g.lock()
            _finish(g, clk)
            out.append(g.result.outcome if g.result else None)
        results.append(out)
        last = s.history[-1]["round"]
        v = s.verify(last)
        assert v["ok"] and v["matches"] and v["hash_ok"]
    assert results[0] == results[1]


# ======================================================================= bank
def test_bank_escrow_settlement_and_never_negative() -> None:
    b = Bank()
    b.open("p", 100)
    assert not b.stake("p", 101, round_=1, game="g", seat=2)
    assert not b.stake("p", 0, round_=1, game="g", seat=2) and not b.stake(
        "p", -5, round_=1, game="g", seat=2
    )
    assert b.stake("p", 60, round_=1, game="g", seat=2)
    w = b.get("p")
    assert w and (w.credits, w.escrow) == (40, 60)
    assert b.release("p", 10, round_=1, game="g", seat=2) and (w.credits, w.escrow) == (50, 50)
    assert not b.release("p", 51, round_=1, game="g", seat=2)
    assert b.settle("p", 50, 150, round_=1, game="g", seat=2) == 100
    assert (w.credits, w.escrow, w.won, w.biggest) == (200, 0, 100, 100)
    with pytest.raises(ValueError):
        b.settle("p", 10, 0, round_=1, game="g", seat=2)  # nothing in escrow: can't settle twice
    assert b.set_credits("p", -50) == 0
    assert b.add_credits("p", 30) == 30
    reasons = [e["reason"] for e in b.ledger]
    assert reasons == ["base", "bet", "unbet", "win", "host_set", "host_add"]
    assert all(e["balance"] >= 0 for e in b.ledger)


def test_bank_persistence_refunds_open_escrow_and_drops_bad_data() -> None:
    sec: dict[str, Any] = {}
    b = Bank(sec)
    b.open("p", 100)
    b.stake("p", 40, round_=1, game="g", seat=2)
    sec["wallets"]["bad"] = {"credits": -3}
    sec["wallets"]["worse"] = "nope"
    b2 = Bank(sec)
    w = b2.get("p")
    assert w and (w.credits, w.escrow) == (100, 0)  # the stopped round is void
    assert b2.get("bad") is None and b2.get("worse") is None
    assert b2.ledger[-1]["reason"] == "refund"


def test_settle_exactly_once_and_ledger() -> None:
    s, clk = _session()
    _seat(s, "a", 2)
    g = Sevens(s)
    s.use(g)
    g.open_betting()
    assert g.place_bet("a", "seven", 10) is None
    g.lock()
    _finish(g, clk)
    before = s.bank.credits("a")
    assert g.settle() is g.result  # a second settle is a no-op
    assert s.bank.credits("a") == before
    pays = [e for e in s.bank.ledger if e["reason"] in ("win", "lose", "push")]
    assert len(pays) == 1 and pays[0]["round"] == g.round.nonce  # type: ignore[union-attr]


# ================================================================ frozen bets
@pytest.mark.parametrize("game_cls", [Roulette, Sevens])
def test_bets_frozen_from_lock_until_settlement(game_cls: Any) -> None:
    """Once betting closes nothing can change: no new bets, no unbet / clear / rebet / done, on any phase."""
    s, clk = _session()
    _seat(s, "a", 2)
    _seat(s, "b", 3)
    g = game_cls(s)
    s.use(g)
    g.open_betting()
    spot = "red" if game_cls is Roulette else "up"
    other = "black" if game_cls is Roulette else "down"
    assert g.place_bet("a", spot, 20) is None
    g.lock()
    snapshot = (json.dumps(g.bets, sort_keys=True), s.bank.credits("a"), s.bank.credits("b"))
    for phase_step in ("locked", g.reveal_phase):
        if phase_step != "locked":
            clk.t += LOCK_SECONDS + 0.01
            g.tick()
        assert g.phase == phase_step
        for pid, op, payload in [
            ("a", "bet", {"spot": spot, "amount": 5}),
            ("a", "bet", {"spot": other, "amount": 5}),
            ("b", "bet", {"spot": other, "amount": 5}),
            ("a", "unbet", {"spot": spot}),
            ("a", "unbet", {"spot": spot, "amount": 5}),
            ("a", "clear", {}),
            ("a", "rebet", {}),
            ("a", "done", {}),
        ]:
            g.handle(pid, op, payload, clk.t)
            assert (
                json.dumps(g.bets, sort_keys=True),
                s.bank.credits("a"),
                s.bank.credits("b"),
            ) == snapshot, op
        assert g.private_state("a", clk.t)["can_bet"] is False
        assert g.private_state("a", clk.t)["ops"] == []
    clk.t += g.spin_seconds
    g.tick()
    assert g.phase == "result"
    w = s.bank.get("a")
    assert w and w.escrow == 0  # settled exactly the 20 that was frozen
    assert g.result and g.result.payouts["a"]["stake"] == 20
    assert g.place_bet("a", spot, 5) == "Bets are closed"  # also in the result phase
    assert "b" not in g.result.payouts


# ===================================================================== roulette
def _ev(game: Any) -> dict[str, Fraction]:
    """Expected net return per credit of every spot, by enumerating every pocket independently."""
    n = len(game.wheel)
    out = {}
    for sid in game.spots():
        total = Fraction(0)
        for pocket in range(n):
            total += Fraction(1, n) * game.returns(game.outcome_at(pocket)).get(sid, Fraction(0))
        out[sid] = total - 1
    return out


def test_roulette_every_bet_has_the_standard_house_edge() -> None:
    s, _ = _session()
    eu = Roulette(s, RouletteRules())
    assert len(eu.wheel) == 37 and sorted(EU_WHEEL) == list(range(37))
    assert len(eu.spots()) == 157
    assert set(_ev(eu).values()) == {Fraction(-1, 37)}  # 2.70 % on every bet
    lp = Roulette(s, RouletteRules(la_partage=True))
    ev = _ev(lp)
    for sid in ("red", "black", "odd", "even", "low", "high"):
        assert ev[sid] == Fraction(-1, 74)  # 1.35 %
    assert ev["n:17"] == ev["dz:2"] == Fraction(-1, 37)
    us = Roulette(s, RouletteRules(wheel="american"))
    assert sorted(US_WHEEL) == list(range(38)) and DOUBLE_ZERO in US_WHEEL
    ev = _ev(us)
    assert ev.pop("tl") == Fraction(-3, 38)  # the top line: 7.89 %
    assert set(ev.values()) == {Fraction(-2, 38)}  # 5.26 % on everything else
    assert round(eu.edges()["straight"], 4) == 0.027 and round(us.edges()["top_line"], 4) == 0.0789


def test_roulette_payouts_per_bet_type() -> None:
    s, _ = _session()
    g = Roulette(s)
    on = lambda n: g.returns({"number": n})  # noqa: E731
    assert on(17)["n:17"] == 36  # 35:1
    assert on(17)["s:17-20"] == on(17)["s:16-17"] == 18  # 17:1
    assert on(17)["st:16"] == 12 and on(2)["tr:0-1-2"] == 12  # 11:1
    assert on(17)["c:13"] == on(17)["c:17"] == 9  # 8:1
    assert on(3)["ff"] == 9  # first four 8:1
    assert on(17)["sl:13"] == on(17)["sl:16"] == 6  # 5:1
    assert on(17)["dz:2"] == on(17)["col:2"] == 3  # 2:1
    assert {k for k, v in on(17).items() if v == 2} == {"black", "odd", "low"}
    assert set(on(0)) == {"n:0", "s:0-1", "s:0-2", "s:0-3", "tr:0-1-2", "tr:0-2-3", "ff"}
    us = Roulette(s, RouletteRules(wheel="american"))
    assert us.returns({"number": DOUBLE_ZERO})["tl"] == 7 and "n:00" in us.spots()
    assert us.returns({"number": DOUBLE_ZERO})["s:0-00"] == 18


def test_roulette_round_pays_whole_credits_and_la_partage() -> None:
    s, clk = _session(bet_seconds=10)
    _seat(s, "a", 2)
    g = Roulette(s, RouletteRules(la_partage=True))
    s.use(g)
    g.open_betting()
    g.place_bet("a", "red", 11)
    g.place_bet("a", "n:0", 2)
    g.lock()
    g.outcome = g.outcome_at(0)  # force zero to check the La Partage arithmetic
    _finish(g, clk)
    p = g.result.payouts["a"]  # type: ignore[union-attr]
    assert p["payout"] == 72 + 5  # 2 × 36 on zero + half of 11 rounded down
    assert s.bank.credits("a") == 1000 - 13 + 77


# ================================================================== 7 up 7 down
def test_sevens_exact_expected_values() -> None:
    s, _ = _session()
    for pays, seven_ev in ((4, Fraction(-1, 6)), (5, Fraction(0))):
        g = Sevens(s, SevensRules(seven_pays=pays))
        ev = {sid: sum(Fraction(1, 36) * g.returns(g.outcome_of(a, b)).get(sid, 0) for a in range(1, 7)
                       for b in range(1, 7)) - 1 for sid in g.spots()}  # fmt: skip
        assert ev == {"down": Fraction(-1, 6), "seven": seven_ev, "up": Fraction(-1, 6)}
    assert Sevens.outcome_of(3, 4) == {"dice": [3, 4], "sum": 7, "zone": "seven"}


def test_round_flow_limits_and_auto_next() -> None:
    s, clk = _session(min_bet=5, max_bet=50, bet_seconds=10, result_seconds=4)
    _seat(s, "a", 2)
    g = Sevens(s)
    s.use(g)
    g.open_betting()
    assert g.deadline is None  # nobody has bet: no countdown, the dice never roll for nobody
    assert g.place_bet("a", "up", 3) == "Table min is 5"
    assert g.place_bet("a", "nope", 10) == "Not a bet on this table"
    assert g.place_bet("a", "up", 80) is None and g.bets["a"]["up"] == 50  # topped up to the max
    assert g.deadline == clk.t + 10
    assert g.unbet("a", "up", 47) is None and "up" not in g.bets.get("a", {})  # never below the min
    g.place_bet("a", "down", 10)
    g.mark_done("a")
    assert g.phase == "locked"  # everyone with a bet is done
    _finish(g, clk)
    clk.t += 4.01
    g.tick()
    assert g.phase == "betting" and g.round and g.round.nonce == 2
    assert g.rebet("a") is None and g.bets["a"] == {"down": 10}


def test_host_ops() -> None:
    s, clk = _session()
    _seat(s, "a", 2)
    g = Roulette(s)
    s.use(g)
    g.open_betting()
    assert s.host_op("credits", {"seat": 2, "add": 250})["credits"]["a"] == 1250
    assert s.host_op("credits", {"all": True, "set": 10})["credits"] == {"a": 10}
    with pytest.raises(ValueError):
        s.host_op("credits", {"seat": 2, "add": 1, "set": 2})
    s.host_op("pause", {"on": True})
    g.place_bet("a", "red", 5)
    dl = g.deadline
    clk.t += 100
    g.tick()
    assert g.phase == "betting"  # paused: the countdown is frozen
    s.host_op("pause", {"on": False})
    assert g.deadline == (dl or 0) + 100
    s.host_op("kick", {"seat": 2})
    assert s.players["a"].kicked and not g.bets
    s.host_op("reset_session", {"base_credits": 300})
    assert s.bank.credits("a") == 300 and not s.history
    with pytest.raises(KeyError):
        s.host_op("nope", {})


# ======================================================================= cards
def test_poker_rankings() -> None:
    def r(h: str) -> Any:
        return poker_rank5(cards(h))

    order = [
        "2S 4D 6H 9C JD",  # high card
        "2S 2D 6H 9C JD",  # pair
        "2S 2D 6H 6C JD",  # two pair
        "2S 2D 2H 9C JD",  # trips
        "AS 2D 3H 4C 5D",  # wheel straight (lowest)
        "6S 2D 3H 4C 5D",
        "2H 4H 6H 9H JH",  # flush
        "2S 2D 2H 9C 9D",  # full house
        "2S 2D 2H 2C JD",  # quads
        "AH 2H 3H 4H 5H",  # steel wheel
        "TS JS QS KS AS",  # royal
    ]
    ranks = [r(h) for h in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert ranks[-1].name == "royal flush" and ranks[4].tiebreak == (5,)
    assert r("KS KD 4H 4C 2D") > r("QS QD JH JC AD")  # two pair: top pair first
    assert r("AS AD 9H 8C 7D") > r("AS AH 9C 8D 6S")  # kicker
    assert r("AS AD 9H 8C 7D") == r("AH AC 9S 8D 7C")  # split pot
    rank, five = best_of(cards("AS KS QS JS TS 2D 3C"))
    assert rank.name == "royal flush" and len(five) == 5
    assert poker_rank7(cards("2S 2D 2H 9C 9D 9H 4S")).tiebreak == (9, 2)  # best full house


def test_teen_patti_ranking() -> None:
    def r(h: str) -> Any:
        return teen_patti_rank(cards(h))

    order = ["2S 5D 9H", "AS 4D 9H", "QS QD 2H", "2H 7H 9H", "4S 3D 2H", "AS 2D 3H", "AS KD QH", "4H 3H 2H",
             "AH KH QH", "2S 2D 2H", "AS AD AH"]  # fmt: skip
    ranks = [r(h) for h in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert teen_patti_name(r("AH 2H 3H")) == "pure sequence"
    assert r("AH 2H 3H") > r("KH QH JH")  # A-2-3 is the second best sequence
    assert r("KS KD 9H") > r("KH KC 8D")


def test_point_values_and_shoe() -> None:
    assert baccarat_total(cards("9S 8D")) == 7 and baccarat_total(cards("KS AS")) == 1
    assert blackjack_total(cards("AS KD")) == (21, True)
    assert blackjack_total(cards("AS AD 9H")) == (21, True)
    assert blackjack_total(cards("AS 9D 5H")) == (15, False)
    assert Card.parse("10H") == Card(10, "H") and Card(10, "H").glyph == "10" and Card(14, "D").red
    shoe = Shoe(decks=2, penetration=0.75)
    assert shoe.needs_shuffle
    shoe.shuffle(fair.Rng(b"x" * 32, "c", 1))
    assert shoe.remaining == 104 and not shoe.needs_shuffle
    drawn = [shoe.draw() for _ in range(78)]
    assert shoe.needs_shuffle and len(set(drawn)) < 78  # two decks: duplicates exist


# ===================================================================== protocol
def _client(tmp_path: Path) -> Any:
    from fastapi.testclient import TestClient

    from deskdot.config import Config
    from deskdot.server import create_app

    return TestClient(create_app(Config(device="sim", data_dir=tmp_path, plugins_dir=tmp_path / "plugins")))


def _state(ws: Any, pred: Any, timeout: float = 3.0) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        m = ws.receive_json()
        if m["type"] == "state" and pred(m):
            return m  # type: ignore[no-any-return]
    raise AssertionError("state never arrived")


def test_phone_protocol_bet_settle_and_private_state(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "casino_roulette"}).json()["code"]
        page = c.get(f"/p/{code}").text
        assert "DeskDot casino" in page and "registerGame" in page
        app = c.app.state.engine._slot("casino_roulette").app
        clk = Clock()
        app.session.clock = clk
        with (
            c.websocket_connect(f"/ws/p/{code}?cid=phoneAAAA1") as a,
            c.websocket_connect(f"/ws/p/{code}?cid=phoneBBBB2") as b,
        ):
            sa, sb = a.receive_json()["seat"], b.receive_json()["seat"]
            a.send_text(json.dumps({"type": "profile", "name": "ADA", "ready": True}))
            a.send_text(json.dumps({"type": "casino", "op": "seed", "client_seed": "ada-seed"}))
            # a phone can't pose as another seat or as the host
            a.send_text(
                json.dumps({"type": "casino", "op": "bet", "spot": "n:17", "amount": 25, "player": "host"})
            )
            a.send_text(json.dumps({"type": "casino", "op": "credits", "seat": sa, "set": 99999}))
            m = _state(a, lambda m: m.get("private", {}).get("bets"))
            assert m["private"]["bets"] == {"n:17": 25} and m["private"]["credits"] == 975
            assert m["private"]["client_seed"] == "ada-seed"
            mb = _state(b, lambda m: m["status"].get("totals"))
            assert (
                mb["private"]["bets"] == {} and mb["private"]["credits"] == 1000
            )  # B never sees A's private view
            assert mb["status"]["totals"] == {"n:17": 25}
            assert "result" not in mb["status"] and "outcome" not in json.dumps(mb["status"]).replace(
                '"outcome": null', ""
            )
            r = c.post("/api/apps/casino_roulette/actions/casino", json={"op": "lock"}).json()
            assert r["result"]["phase"] == "locked"
            # frozen: a bet after the lock is refused and the phone is told why
            a.send_text(json.dumps({"type": "casino", "op": "bet", "spot": "red", "amount": 5}))
            a.send_text(json.dumps({"type": "casino", "op": "clear"}))
            m = _state(a, lambda m: (m["private"].get("notice") or {}).get("text") == "Bets are closed")
            assert m["private"]["bets"] == {"n:17": 25} and m["private"]["can_bet"] is False
            clk.t += 20
            m = _state(a, lambda m: m["status"]["phase"] == "result")
            res = m["status"]["result"]
            mine = m["private"]["result"]
            win = res["outcome"]["number"] == 17
            assert mine["net"] == (25 * 35 if win else -25)
            assert m["private"]["credits"] == 975 + (25 * 36 if win else 0)
            h = m["status"]["history"][-1]
            assert h["proof"]["server_seed"] and "ada-seed" in h["proof"]["client_seed"]
            v = c.post(
                "/api/apps/casino_roulette/actions/casino", json={"op": "verify", "round": h["round"]}
            ).json()
            assert v["result"]["ok"] is True
            assert sb != sa


def test_wallet_follows_the_phone_across_seats(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "casino_sevens"}).json()["code"]
        with c.websocket_connect(f"/ws/p/{code}?cid=walletCID1") as a:
            a.receive_json()
            a.send_text(json.dumps({"type": "casino", "op": "bet", "spot": "up", "amount": 100}))
            _state(a, lambda m: m.get("private", {}).get("credits") == 900)
        app = c.app.state.engine._slot("casino_sevens").app
        app.session.host_op(
            "credits", {"pid": next(iter(p for p in app.session.players if p != "host")), "set": 4321}
        )
        c.app.state.lobby.room.reserved.clear()  # the seat reservation expired: the phone comes back on a new socket
        with c.websocket_connect(f"/ws/p/{code}?cid=walletCID1") as a:
            a.receive_json()
            m = _state(a, lambda m: m.get("private", {}).get("seated"))
            assert m["private"]["credits"] == 4321


# ======================================================================== render
@pytest.mark.parametrize("app_id", ["casino_roulette", "casino_sevens"])
async def test_render_every_phase_fast(engine: Any, app_id: str) -> None:
    from deskdot.apps._casino import VIEWS
    from deskdot.gfx import Frame

    worst, total, n = 0.0, 0.0, 0
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
                dt = time.perf_counter() - t0
                worst, total, n = max(worst, dt), total + dt, n + 1
                if view not in ("live", "lobby"):
                    assert f.px.any(), (view, t)
    finally:
        gc.enable()
    assert worst < 0.05, f"{app_id} worst render {worst * 1000:.1f} ms"
    assert total / n < 0.004, f"{app_id} typical render {total / n * 1000:.2f} ms"


async def test_live_table_with_players(engine: Any) -> None:
    """The live roulette table through a whole round with 1, 4 and 8 players."""
    from deskdot.gfx import Frame

    for players in (1, 4, 8):
        engine.slots.clear()
        engine.shared.clear()
        app = engine._slot("casino_roulette").app
        clk = Clock()
        app.session.clock = clk
        for i in range(players):
            await app.action(
                "seat",
                {"player": i + 2, "joined": True, "name": f"P{i}", "color": "#ff3c5a", "pid": f"pid{i:04d}"},
            )
            await app.action(
                "casino", {"op": "bet", "spot": "red" if i % 2 else "n:5", "amount": 10, "player": i + 2}
            )
        assert len(app.game.bets) == players
        app.render(Frame(), 0)
        await app.action("casino", {"op": "lock", "player": "host"})
        for _ in range(100):
            clk.t += 0.12
            f = Frame()
            app.render(f, clk.t)
        assert app.game.phase in ("result", "betting")
        assert all(w.escrow == 0 for w in app.session.bank.wallets.values())
        st = app.status()
        assert len(st["players"]) == players and st["casino"] is True
        assert app.private_status(2)["seated"] is True and app.private_status(30) == {"seated": False}


# ================================================================= multiplayer sync
def _check_spot_bets(st: dict[str, Any], privs: dict[int, dict[str, Any]]) -> None:
    """`spot_bets` agrees with `totals` and with every seat's own private `bets`."""
    sb = st["spot_bets"]
    assert {k: sum(w["amount"] for w in v) for k, v in sb.items()} == st["totals"]
    for seat, pv in privs.items():
        if not pv.get("seated", True):
            continue
        mine = {k: w["amount"] for k, v in sb.items() for w in v if w["seat"] == seat}
        assert mine == pv["bets"], seat
    for rows in sb.values():  # table order, each player once per spot
        seats = [w["seat"] for w in rows]
        assert len(set(seats)) == len(seats)
        assert seats == sorted(seats, key=lambda s: (0, 0) if s == "host" else (1, int(s)))


async def test_spot_bets_follow_every_op(engine: Any) -> None:
    """bet / unbet (part and all) / clear / rebet / done from several players and the host, a phone dropping and
    coming back on another seat: the public spot breakdown always matches the private views."""
    app = engine._slot("casino_roulette").app
    clk = Clock()
    app.session.clock = clk
    for seat, pid, col in ((2, "pidAAAA", "#ff3c5a"), (3, "pidBBBB", "#00c8ff"), (4, "pidCCCC", "#50ff78")):
        await app.action("seat", {"player": seat, "joined": True, "name": pid[-4:], "color": col, "pid": pid})

    async def op(player: int | str, **kw: Any) -> None:
        await app.action("casino", {"player": player, **kw})
        _check_spot_bets(app.status(), {s: app.private_status(s) for s in (2, 3, 4)})

    for spot in ("n:17", "red", "n:17", "s:17-18"):
        for p in (2, 3, 4):
            await op(p, op="bet", spot=spot, amount=5 * p)
    await op("host", op="bet", spot="n:17", amount=25)
    st = app.status()
    assert [w["seat"] for w in st["spot_bets"]["n:17"]] == ["host", 2, 3, 4]
    assert [w["color"] for w in st["spot_bets"]["n:17"]] == ["#00c8ff", "#ff3c5a", "#00c8ff", "#50ff78"]
    assert st["totals"]["n:17"] == 25 + 2 * (10 + 15 + 20)
    await op(2, op="unbet", spot="n:17", amount=5)
    await op(3, op="unbet", spot="red")
    await op(4, op="clear")
    await op(2, op="done")
    # seat 3 drops and its phone comes back on seat 5: its chips stay on the table, now under seat 5
    await app.action("seat", {"player": 3, "joined": False})
    await app.action(
        "seat", {"player": 5, "joined": True, "name": "BBBB", "color": "#00c8ff", "pid": "pidBBBB"}
    )
    st = app.status()
    assert {w["seat"] for v in st["spot_bets"].values() for w in v} == {"host", 2, 5}
    _check_spot_bets(st, {s: app.private_status(s) for s in (2, 4, 5)})
    # next round: rebet repeats everyone's previous bets
    await app.action("casino", {"op": "lock", "player": "host"})
    clk.t += 60
    app.status()
    clk.t += 60
    app.status()
    assert app.game.phase == "betting" and app.status()["spot_bets"] == {}
    await op(2, op="rebet")
    assert app.status()["spot_bets"]["n:17"] == [
        {"seat": 2, "name": "AAAA", "color": "#ff3c5a", "amount": 15}
    ]


def test_phones_betting_at_once_see_the_same_table(tmp_path: Path) -> None:
    """Three phones fire bets, undos and clears at the same time; once each phone's taps are acknowledged, every
    phone (and the studio) holds the identical public table: totals, who is on which spot, in which colour."""
    with _client(tmp_path) as c:
        code = c.post("/api/play/lobby", json={"app": "casino_roulette"}).json()["code"]
        app = c.app.state.engine._slot("casino_roulette").app
        app.session.clock = Clock()
        with (
            c.websocket_connect(f"/ws/p/{code}?cid=syncAAAA01") as a,
            c.websocket_connect(f"/ws/p/{code}?cid=syncBBBB02") as b,
            c.websocket_connect(f"/ws/p/{code}?cid=syncCCCC03") as d,
        ):
            phones = [a, b, d]
            seats = [p.receive_json()["seat"] for p in phones]
            script = [
                ("bet", {"spot": "n:17", "amount": 5}),
                ("bet", {"spot": "red", "amount": 25}),
                ("bet", {"spot": "n:17", "amount": 1}),
                ("unbet", {"spot": "n:17", "amount": 1}),
                ("bet", {"spot": "c:13", "amount": 100}),
                ("bet", {"spot": "n:17", "amount": 5}),
                ("unbet", {"spot": "red"}),
                ("bet", {"spot": "black", "amount": 5}),
            ]
            sent = [0, 0, 0]
            for i, (o, kw) in enumerate(script):  # interleaved: a, b, c, a, b, c …
                for j, p in enumerate(phones):
                    if o == "unbet" and (i + j) % 3 == 0:
                        continue
                    sent[j] += 1
                    p.send_text(json.dumps({"type": "casino", "op": o, "seq": sent[j], **kw}))
            sent[1] += 1
            b.send_text(json.dumps({"type": "casino", "op": "clear", "seq": sent[1]}))
            # each phone's own last op is applied …
            for j, p in enumerate(phones):
                _state(p, lambda m, w=sent[j]: m.get("ack") == w, timeout=5)
            # … then every phone converges on the same revision of the table
            rev = app.status()["rev"]
            got = [_state(p, lambda m, r=rev: m["status"].get("rev", -1) >= r, timeout=5) for p in phones]
            pub = [
                {k: m["status"][k] for k in ("totals", "spot_bets", "bettors", "round", "phase")} for m in got
            ]
            assert pub[0] == pub[1] == pub[2]
            assert pub[0]["totals"]  # the table isn't empty
            privs = {s: m["private"] for s, m in zip(seats, got, strict=True)}
            _check_spot_bets(got[0]["status"], privs)
            assert privs[seats[1]]["bets"] == {}  # b cleared everything last
            view = c.post("/api/apps/casino_roulette/actions/casino", json={"op": "view"}).json()["result"]
            assert {k: view["status"][k] for k in ("totals", "spot_bets")} == {
                k: pub[0][k] for k in ("totals", "spot_bets")
            }


def test_andar_bahar_deal_on_phones_matches_by_rank_any_suit() -> None:
    """While the cards are dealt the phones get the joker and the cards so far (never the winner ahead of the
    deal); the game ends on the first card of the joker's rank, whatever its suit (the standard rule)."""
    from deskdot.casino.games.andarbahar import AndarBahar

    for k in range(6):
        s, clk = _session()
        _seat(s, "a", 2, seed=f"ab-{k}")
        g = AndarBahar(s)
        s.use(g)
        g.open_betting()
        assert g.place_bet("a", "andar", 10) is None
        assert "deal" not in g.public_state(clk.t)
        g.lock()
        seen: list[int] = []
        for _ in range(400):
            clk.t += 0.1
            g.tick()
            st = g.public_state(clk.t)
            if g.phase != "dealing":
                continue
            d = st["deal"]
            assert "winner" not in d and "result" not in st
            cards = d["cards"]
            seen.append(len(cards))
            joker = d["joker"]
            assert all(c[0] != joker[0] for c in cards[:-1])  # no earlier card had the joker's rank
            if d["matched"]:
                assert cards[-1][0] == joker[0] and cards[-1] != joker
        assert seen == sorted(seen) and g.phase in ("result", "betting")
        o = g.result.outcome  # type: ignore[union-attr]
        assert o["cards"][-1][0] == o["joker"][0] and len(o["cards"]) == o["count"]
        assert o["winner"] == (o["first"] if o["count"] % 2 else ({"andar", "bahar"} - {o["first"]}).pop())
