"""Housie (Tambola): valid tickets from the fair stream, claims verified for every prize, bogeys, ties, the pot /
rake / credit conservation, the fair replay (Python and the phone's JavaScript), host pace, the panel and rulebook."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from deskdot.casino import CasinoSession, fair
from deskdot.casino.games.housie import (
    COLUMNS,
    PRIZES,
    Housie,
    HousieRules,
    complete,
    completes_at,
    make_ticket,
    needs,
    prize_amounts,
    ticket_rows,
    valid_ticket,
)
from deskdot.casino.rulebook import guide
from deskdot.casino.table import LOCK_SECONDS
from test_casino_house_phone import HARNESS, PAGE

# the shared harness, plus window listeners (the page's tutorial listens for resize)
_HARNESS = HARNESS.replace(
    "g.setInterval = () => 0;", "g.setInterval = () => 0; g.addEventListener = () => {};"
)


def _node(cases: list[dict[str, Any]], tmp_path: Path) -> list[Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    h = tmp_path / "harness.js"
    h.write_text(_HARNESS, encoding="utf-8")
    r = subprocess.run(
        [node, str(h), str(PAGE)], input=json.dumps(cases), capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)  # type: ignore[no-any-return]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def table(n: int = 3, credits: int = 1000, **rules: Any) -> tuple[CasinoSession, Housie, Clock, list[str]]:
    clk = Clock()
    s = CasinoSession(clock=clk)
    pids = []
    for i in range(n):
        pid = f"p{i}"
        s.join(pid, i + 2, name=f"P{i}", color="#ff0000")
        s.bank.set_credits(pid, credits)
        pids.append(pid)
    g = Housie(s, HousieRules(**rules))
    s.use(g)
    g.open_betting(clk.t)
    return s, g, clk, pids


def start(g: Housie, clk: Clock) -> None:
    assert g.lock(clk.t)
    clk.t += LOCK_SECONDS + 0.01
    g.tick(clk.t)
    assert g.phase == "dealing"


def call_until(g: Housie, clk: Clock, n: int) -> None:
    """Advance until `n` numbers have been called."""
    for _ in range(2000):
        if g.called >= n:
            return
        clk.t += 0.5
        g.tick(clk.t)
    raise AssertionError("calls stalled")


def total_credits(s: CasinoSession) -> int:
    return sum(w.credits + w.escrow for w in s.bank.wallets.values())


# ------------------------------------------------------------------ tickets
def test_tickets_are_valid_over_many_seeds() -> None:
    for k in range(1500):
        t = make_ticket(fair.Rng(f"seed-{k}".encode(), "client", k))
        assert valid_ticket(t), t
        assert len([n for n in t if n]) == 15
        rows = ticket_rows(t)
        assert [len(r) for r in rows] == [5, 5, 5]
        for c in range(9):
            col = [t[r * 9 + c] for r in range(3) if t[r * 9 + c]]
            assert 1 <= len(col) <= 3 and col == sorted(col) and all(n in COLUMNS[c] for n in col)
    assert COLUMNS[0] == tuple(range(1, 10)) and COLUMNS[8] == tuple(range(80, 91))
    assert not valid_ticket([0] * 27)


def test_patterns() -> None:
    t = make_ticket(fair.Rng(b"x", "y", 1))
    top, _mid, bot = ticket_rows(t)
    assert needs(t, "corners") == [top[0], top[-1], bot[0], bot[-1]]
    assert complete(t, "top", frozenset(top)) and not complete(t, "top", frozenset(top[:4]))
    assert complete(t, "early5", frozenset(bot)) and not complete(t, "early5", frozenset(bot[:4]))
    assert not complete(t, "full", frozenset(top + bot))
    calls = list(range(1, 91))
    assert completes_at(t, "full", calls) == max(n for n in t if n)


# ------------------------------------------------------------------ buy-in
def test_buyin_escrow_and_frozen_after_lock() -> None:
    s, g, clk, (a, b, _c) = table(ticket_price=10, max_tickets=3)
    assert g.handle(a, "buy", {"count": 2}, clk.t) is None
    assert s.bank.get(a).escrow == 20 and g.deadline is not None
    g.handle(a, "buy", {"count": 9}, clk.t)  # capped at the max
    assert g.count(a) == 3
    g.handle(a, "unbet", {"spot": "ticket", "amount": 1}, clk.t)
    assert g.count(a) == 2
    g.handle(b, "bet", {"spot": "ticket", "amount": 25}, clk.t)  # a generic chip = one ticket
    assert g.count(b) == 1 and g.public_state(clk.t)["totals"] == {"ticket": 30}
    start(g, clk)
    for op, pl in (
        ("buy", {"count": 1}),
        ("bet", {"spot": "ticket"}),
        ("clear", {}),
        ("unbet", {"spot": "ticket"}),
    ):
        assert g.handle(a, op, pl, clk.t) is not None
    assert g.count(a) == 2 and len(g.tickets[a]) == 2 and len(g.tickets[b]) == 1
    assert all(valid_ticket(t) for ts in g.tickets.values() for t in ts)


def test_no_tickets_no_calling() -> None:
    _s, g, clk, _ = table()
    assert not g.lock(clk.t) and g.phase == "betting"


def test_poor_player_buys_what_they_can() -> None:
    s, g, clk, (a, *_rest) = table(credits=25, ticket_price=10)
    g.handle(a, "buy", {"count": 3}, clk.t)
    assert g.count(a) == 2 and s.bank.credits(a) == 5


# ------------------------------------------------------------------ claims
@pytest.mark.parametrize("prize", PRIZES)
def test_each_prize_is_verified(prize: str) -> None:
    _s, g, clk, (a, b, c) = table()
    for p in (a, b, c):
        g.handle(p, "buy", {"count": 1}, clk.t)
    start(g, clk)
    t = g.tickets[a][0]
    at = completes_at(t, prize, g.outcome["calls"])
    if at > 1:
        call_until(g, clk, at - 1)
        assert g.handle(a, "claim", {"prize": prize, "ticket": 0}, clk.t) is not None  # one short: a bogey
        assert prize not in g.claims
    call_until(g, clk, at)
    assert g.handle(a, f"claim_{prize}", {"ticket": 0}, clk.t) is None
    assert g.claims[prize]["winners"] == [[a, 0]]
    st = g.private_state(a, clk.t)["housie"]
    assert prize not in st["claimable"] or g.claims[prize]["winners"]


def test_bogey_penalties() -> None:
    for pen, blocked, out in (("none", False, False), ("prize", True, False), ("ticket", True, True)):
        _s, g, clk, (a, *_rest) = table(bogey=pen)
        g.handle(a, "buy", {"count": 1}, clk.t)
        start(g, clk)
        call_until(g, clk, 1)
        assert g.handle(a, "claim", {"prize": "full", "ticket": 0}, clk.t).startswith("Bogey")
        assert ((a, 0, "full") in g.blocked) == (blocked and not out)
        assert ((a, 0) in g.void) == out
        at = completes_at(g.tickets[a][0], "top", g.outcome["calls"])
        call_until(g, clk, at)
        ok = g.handle(a, "claim", {"prize": "top", "ticket": 0}, clk.t) is None
        assert ok == (not out)


def test_late_claim_after_the_next_call_is_refused() -> None:
    _s, g, clk, (a, b, _c) = table()
    g.handle(a, "buy", {"count": 1}, clk.t)
    g.handle(b, "buy", {"count": 1}, clk.t)
    start(g, clk)
    # whoever completes the Early Five first claims it; once a number is called after that, it's closed
    at = min(completes_at(g.tickets[p][0], "early5", g.outcome["calls"]) for p in (a, b))
    call_until(g, clk, at)
    first = next(p for p in (a, b) if complete(g.tickets[p][0], "early5", g.called_set()))
    other = b if first == a else a
    assert g.handle(first, "claim", {"prize": "early5"}, clk.t) is None
    call_until(g, clk, max(at + 1, completes_at(g.tickets[other][0], "early5", g.outcome["calls"])))
    err = g.handle(other, "claim", {"prize": "early5"}, clk.t)
    assert err is not None and "already went" in err


def test_tie_on_the_same_call_splits_the_prize() -> None:
    _s, g, clk, (a, b, c) = table(n=3, ticket_price=11, rake=0)
    for p in (a, b, c):
        g.handle(p, "buy", {"count": 1}, clk.t)
    start(g, clk)
    # make a and b hold the same ticket: both complete every pattern on the same call
    g.tickets[b] = [list(g.tickets[a][0])]
    at = completes_at(g.tickets[a][0], "top", g.outcome["calls"])
    call_until(g, clk, at)
    assert g.handle(a, "claim", {"prize": "top"}, clk.t) is None
    assert g.handle(b, "claim", {"prize": "top"}, clk.t) is None
    amount = g.amounts["top"]
    g.finish(clk.t)
    got = {w["prize"]: w["amount"] for w in g.won[a]}, {w["prize"]: w["amount"] for w in g.won[b]}
    assert got[0]["top"] + got[1]["top"] == amount and abs(got[0]["top"] - got[1]["top"]) <= 1
    assert got[0]["top"] >= got[1]["top"]  # the odd credit to the earliest claim


# ------------------------------------------------------------------ money
@pytest.mark.parametrize("rake", [0, 5, 20])
def test_pot_rake_and_conservation(rake: int) -> None:
    s, g, clk, pids = table(n=4, ticket_price=7, rake=rake, auto_claim=True)
    before = total_credits(s)
    for i, p in enumerate(pids):
        g.handle(p, "buy", {"count": 1 + i % 3}, clk.t)
    start(g, clk)
    pot = 7 * sum(1 + i % 3 for i in range(4))
    assert g.pot == pot and g.rake_taken == pot * rake // 100
    assert sum(g.amounts.values()) == g.pool == pot - g.rake_taken
    for _ in range(4000):
        clk.t += 0.5
        g.tick(clk.t)
        if g.phase == "result":
            break
    assert g.phase == "result" and "full" in g.claims
    res = g.result
    assert res is not None and sum(v["net"] for v in res.payouts.values()) == -g.rake_taken
    assert total_credits(s) == before - g.rake_taken
    assert all(w.escrow == 0 for w in s.bank.wallets.values())


def test_unclaimed_prizes_are_shared_back() -> None:
    s, g, clk, (a, b, _c) = table(ticket_price=10)
    g.handle(a, "buy", {"count": 2}, clk.t)
    g.handle(b, "buy", {"count": 1}, clk.t)
    before = total_credits(s)
    start(g, clk)
    call_until(g, clk, 90)
    for _ in range(100):
        clk.t += 1
        g.tick(clk.t)
        if g.phase == "result":
            break
    assert g.phase == "result" and g.returned == g.pool == 30
    assert g.awards == {a: 20, b: 10} and total_credits(s) == before


def test_prize_amounts_and_shares() -> None:
    amt = prize_amounts(HousieRules(), 1000)
    assert amt == {"early5": 100, "top": 150, "middle": 150, "bottom": 150, "corners": 100, "full": 350}
    assert sum(prize_amounts(HousieRules(), 997).values()) == 997
    only = prize_amounts(HousieRules(early5=False, top=False, middle=False, bottom=False, corners=False), 77)
    assert only == {"full": 77}
    none = prize_amounts(HousieRules(**{p: False for p in PRIZES}), 50)
    assert none == {"full": 50}


def test_abort_mid_game_refunds() -> None:
    s, g, clk, (a, b, _c) = table()
    before = total_credits(s)
    g.handle(a, "buy", {"count": 2}, clk.t)
    g.handle(b, "buy", {"count": 1}, clk.t)
    start(g, clk)
    call_until(g, clk, 10)
    g.abort(clk.t)
    assert total_credits(s) == before and all(w.escrow == 0 for w in s.bank.wallets.values())


# ------------------------------------------------------------------ fairness
def _play_one(seed_round: int = 0) -> tuple[CasinoSession, Housie]:
    s, g, clk, pids = table(n=3, auto_claim=True)
    s.set_seed(pids[0], f"phone-{seed_round}")
    for i, p in enumerate(pids):
        g.handle(p, "buy", {"count": i + 1}, clk.t)
    start(g, clk)
    for _ in range(4000):
        clk.t += 0.5
        g.tick(clk.t)
        if g.phase == "result":
            break
    return s, g


def test_fair_replay_matches() -> None:
    s, _g = _play_one()
    e = s.history[-1]
    assert e["game"] == "housie" and e["outcome"]["holders"] == [[2, 1], [3, 2], [4, 3]]
    v = s.verify(e["round"])
    assert v["ok"] and v["matches"]
    assert sorted(e["outcome"]["calls"]) == list(range(1, 91))
    # the call order does not depend on how many tickets were sold
    pr = e["proof"]
    rng = lambda: fair.Rng(bytes.fromhex(pr["server_seed"]), pr["client_seed"], pr["nonce"])  # noqa: E731
    lone = Housie.replay_with({}, rng(), {"holders": [[2, 1]]})
    assert lone["calls"] == e["outcome"]["calls"]


def test_phone_replay_matches_the_engine(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    cases = []
    for k in range(3):
        s, _g = _play_one(k)
        e = s.history[-1]
        pr = e["proof"]
        cases.append(
            {"game": "housie", "seed": pr["server_seed"], "client": pr["client_seed"], "nonce": pr["nonce"],
             "rules": e["rules"], "outcome": e["outcome"], "round": e["round"]}
        )  # fmt: skip
    got = _node(cases, tmp_path)
    for c, out in zip(cases, got, strict=True):
        assert json.dumps(out, sort_keys=True) == json.dumps(c["outcome"], sort_keys=True)


def test_public_state_hides_future_calls_and_tickets() -> None:
    _s, g, clk, (a, b, _c) = table()
    g.handle(a, "buy", {"count": 1}, clk.t)
    g.handle(b, "buy", {"count": 1}, clk.t)
    start(g, clk)
    call_until(g, clk, 5)
    pub = g.public_state(clk.t)
    blob = json.dumps(pub)
    assert pub["housie"]["calls"] == g.outcome["calls"][:5]
    assert '"tickets"' not in blob and "outcome" not in pub
    assert g.private_state(a, clk.t)["housie"]["tickets"] == g.tickets[a]
    assert g.private_state(b, clk.t)["housie"]["tickets"] != g.tickets[a] or g.tickets[a] == g.tickets[b]


# ------------------------------------------------------------------ host + panel + rulebook
async def test_host_pace_and_lock(engine: Any) -> None:
    app = engine._slot("casino_housie").app
    app._live()
    r = app.casino({"op": "pace", "seconds": 4})
    assert r["ok"] and r["call_seconds"] == 4 and app.game.rules.call_seconds == 4
    assert app.casino({"op": "pace", "delta": 100})["call_seconds"] == 20
    with pytest.raises(ValueError):
        app.casino({"op": "pace"})


def test_rulebook_has_housie() -> None:
    g = guide("housie")
    assert g is not None and g["title"] == "Housie"
    text = " ".join(" ".join(r["items"]) for r in g["rules"])
    for word in (
        "Early Five",
        "Top Line",
        "Middle Line",
        "Bottom Line",
        "Four Corners",
        "Full House",
        "bogey",
    ):
        assert word.lower() in text.lower(), word
    for p, share in (("Early Five", 10), ("Full House", 35)):
        assert f"{p} **{share} %**" in text
