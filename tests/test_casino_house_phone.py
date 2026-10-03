"""The phone page's house-game modules (blackjack, baccarat, slots in casino.html): their `replay()` recomputes
exactly what the Python engine dealt — run in Node against real rounds — and the slot strips in the page match the
engine's. Skipped when Node isn't installed."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from deskdot.casino import CasinoSession, fair
from deskdot.casino.games.baccarat import Baccarat, BaccaratRules
from deskdot.casino.games.blackjack import Blackjack, BlackjackRules, basic_strategy
from deskdot.casino.games.slots import STRIPS, Slots, SlotsRules
from deskdot.casino.table import LOCK_SECONDS

PAGE = Path(__file__).resolve().parents[1] / "src" / "deskdot" / "casino.html"

HARNESS = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.slice(html.lastIndexOf("<script>") + 8, html.lastIndexOf("</script>"));
// a do-nothing DOM: every property is a callable stub, so the page's boot code runs harmlessly
const stub = new Proxy(function () {}, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : k === "length" ? 0 : k === Symbol.iterator ? [][Symbol.iterator] : stub), apply: () => stub, construct: () => stub, set: () => true });
const g = globalThis;
Object.defineProperty(g, "navigator", { value: {}, configurable: true });
Object.assign(g, { document: stub, window: g, localStorage: { getItem: () => null, setItem() {} }, sessionStorage: { getItem: () => null, setItem() {} },
  matchMedia: () => ({ matches: false }), requestAnimationFrame: () => 0, cancelAnimationFrame() {}, location: { pathname: "/p/TEST", protocol: "http:", host: "x" },
  WebSocket: function () { throw new Error("offline"); }, devicePixelRatio: 1, ResizeObserver: function () { return { observe() {}, disconnect() {} }; } });
g.setInterval = () => 0; g.setTimeout = () => 0;
const api = new Function(src + "\n;return { GAMES, Rng, S };")();
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const hexBytes = (s) => new Uint8Array(s.match(/../g).map((x) => parseInt(x, 16)));
const out = cases.map((c) => {
  api.S.pub = { history: c.history || [] };
  api.S.verifying = c.round || 0;
  return api.GAMES[c.game].replay(new api.Rng(hexBytes(c.seed), c.client, c.nonce), c.rules, c.outcome);
});
process.stdout.write(JSON.stringify(out));
"""


def _node(cases: list[dict[str, Any]], tmp_path: Path) -> list[Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    h = tmp_path / "harness.js"
    h.write_text(HARNESS, encoding="utf-8")
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


def _canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True)


def test_phone_replays_match_the_engine(tmp_path: Path) -> None:
    clk = Clock()
    s = CasinoSession(clock=clk)
    s.join("a", 2, name="A")
    s.set_seed("a", "phone-seed")
    s.bank.set_credits("a", 10**6)
    cases: list[dict[str, Any]] = []
    # blackjack: a few rounds from one 2-deck shoe (so most rounds start mid-shoe), played by basic strategy
    g = Blackjack(s, BlackjackRules(decks=2, penetration=80))
    s.use(g)
    for _ in range(6):
        g.open_betting()
        g.place_bet("a", "main", 10)
        g.lock()
        for _ in range(400):
            clk.t += 0.25
            g.tick()
            if g.phase == "action":
                if g.stage == "insurance":
                    g.handle("a", "no_insurance", {}, clk.t)
                elif g.turn:
                    h = g.hands["a"][g.turn[1]]
                    g.handle("a", basic_strategy(h.cards, g.dealer[0], g.moves("a"), g.rules), {}, clk.t)
            if g.phase == "result":
                break
    # baccarat and slots
    b = Baccarat(s, BaccaratRules(decks=6))
    s.use(b)
    for _ in range(4):
        b.open_betting()
        b.place_bet("a", "player", 5)
        b.lock()
        clk.t += LOCK_SECONDS + b.spin_seconds + 3
        b.tick()
    m = Slots(s, SlotsRules(theme="space", volatility="high"))
    s.use(m)
    for _ in range(4):
        m.handle("a", "pull", {"bet": 1}, clk.t)
        clk.t += 10
        m.tick()
    hist = s.history
    assert {e["game"] for e in hist} == {"blackjack", "baccarat", "slots"}
    for i, e in enumerate(hist):
        pr = e["proof"]
        cases.append(
            {
                "game": e["game"],
                "seed": pr["server_seed"],
                "client": pr["client_seed"],
                "nonce": pr["nonce"],
                "rules": e["rules"],
                "outcome": e["outcome"],
                "round": e["round"],
                "history": [
                    {"game": x["game"], "round": x["round"], "outcome": x["outcome"]} for x in hist[:i]
                ],
            }
        )
    got = _node(cases, tmp_path)
    for c, g_out in zip(cases, got, strict=True):
        assert _canon(g_out) == _canon(c["outcome"]), (c["game"], c["round"])
    # a forged blackjack shoe is caught by the phone too (the chain from the previous round breaks)
    bj = [c for c in cases if c["game"] == "blackjack" and not c["outcome"]["shuffled"]]
    assert bj
    forged = dict(bj[-1])
    shoe = forged["outcome"]["shoe"]
    forged["outcome"] = {**forged["outcome"], "shoe": ("0" if shoe[0] != "0" else "1") + shoe[1:]}
    assert _canon(_node([forged], tmp_path)[0]) != _canon(forged["outcome"])


def test_page_strips_match_the_engine() -> None:
    page = PAGE.read_text(encoding="utf-8")
    m = re.search(r"const STRIPS = (\{.*?\n  \});", page, re.S)
    assert m, "STRIPS not found in casino.html"
    js = re.sub(r",\s*}", "}", re.sub(r"(\w+):", r'"\1":', m.group(1)))
    assert json.loads(js) == {t: {v: list(s) for v, s in vs.items()} for t, vs in STRIPS.items()}
    for game in ("blackjack", "baccarat", "slots"):
        assert f'registerGame("{game}"' in page
    _ = fair  # the page's Rng is the one pinned in tests/test_casino.py
