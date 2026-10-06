"""The phone page (casino.html) against the engine: the roulette layout's drop targets resolve like a real table and
only to spots the engine knows, and the chip rack / K-M labels are the same as casino/chips.py. Runs the page's pure
helpers in Node against a do-nothing DOM; skipped when Node isn't installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from deskdot.casino import CasinoSession
from deskdot.casino.chips import chip_rack, short
from deskdot.casino.games.roulette import Roulette, RouletteRules

PAGE = Path(__file__).resolve().parents[1] / "src" / "deskdot" / "casino.html"

HARNESS = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.slice(html.lastIndexOf("<script>") + 8, html.lastIndexOf("</script>"));
const stub = new Proxy(function () {}, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : k === "length" ? 0 : k === Symbol.iterator ? [][Symbol.iterator] : stub), apply: () => stub, construct: () => stub, set: () => true });
const g = globalThis;
Object.defineProperty(g, "navigator", { value: {}, configurable: true });
Object.assign(g, { document: stub, window: g, localStorage: { getItem: () => null, setItem() {} }, sessionStorage: { getItem: () => null, setItem() {} },
  matchMedia: () => ({ matches: false }), requestAnimationFrame: () => 0, cancelAnimationFrame() {}, location: { pathname: "/p/TEST", protocol: "http:", host: "x" },
  WebSocket: function () { throw new Error("offline"); }, devicePixelRatio: 1, ResizeObserver: function () { return { observe() {}, disconnect() {} }; } });
g.setInterval = () => 0; g.setTimeout = () => 0;
const api = new Function(src + "\n;return { rouletteSpot, short, chipRack, rackChips, chipStyle, S };")();
const q = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {
  points: q.points.map(([u, v, us]) => api.rouletteSpot(u, v, us, 0.22, 0.22)),
  sweep: {},
  short: q.short.map((n) => api.short(n)),
  racks: q.racks.map(([a, b]) => api.chipRack(a, b)),
};
for (const us of [false, true]) {
  const seen = new Set();
  for (const t of [0.22, 0.3, 0.34]) for (let u = -1; u < 13; u += 0.01) for (let v = -2.35; v < 3; v += 0.01) { const s = api.rouletteSpot(u, v, us, t, t); if (s) seen.add(s); }
  out.sweep[us ? "us" : "eu"] = [...seen];
}
api.S.pub = { house: { min_bet: 1, max_bet: 500 }, chips: [{ v: 7, label: "7", color: "#123456", edge: "#abcdef" }] };
out.fromStatus = api.rackChips().map((c) => c.v);
out.style = api.chipStyle(3000);
process.stdout.write(JSON.stringify(out));
"""


def _run(query: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    h = tmp_path / "roulette.js"
    h.write_text(HARNESS, encoding="utf-8")
    r = subprocess.run(
        [node, str(h), str(PAGE)], input=json.dumps(query), capture_output=True, text=True, timeout=120
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)  # type: ignore[no-any-return]


# (u, v, american) → spot: u runs along the table (row r holds 3r+1 … 3r+3), v across it (0 … 3; the rail below 0)
POINTS: list[tuple[float, float, bool, str]] = [
    (5.5, 1.5, False, "n:17"),  # inside a number
    (5.97, 1.5, False, "s:17-20"),  # on the line between two rows
    (6.03, 1.5, False, "s:17-20"),
    (5.5, 1.97, False, "s:17-18"),  # on the line between two numbers of a street
    (5.98, 1.98, False, "c:17"),  # where 17, 18, 20, 21 meet
    (6.02, 2.02, False, "c:17"),
    (6.02, 1.03, False, "c:16"),
    (5.5, 0.05, False, "st:16"),  # the street's outer edge
    (5.5, -0.1, False, "st:16"),  # the rail beside it
    (5.98, 0.05, False, "sl:16"),  # where two streets meet on the outer edge: six line 16-21
    (6.02, -0.1, False, "sl:16"),
    (0.02, 0.05, False, "ff"),  # the outer corner of 0 / 1: first four
    (0.02, 0.05, True, "tl"),  # American: top line
    (0.02, 1.02, False, "tr:0-1-2"),  # the zero line where 1 and 2 meet
    (-0.05, 2.0, False, "tr:0-2-3"),
    (0.03, 1.5, False, "s:0-2"),
    (0.03, 1.5, True, "tr:0-00-2"),
    (0.03, 2.5, True, "s:00-3"),
    (-0.5, 1.5, True, "s:0-00"),
    (-0.5, 2.5, True, "n:00"),
    (-0.5, 2.5, False, "n:0"),
    (11.98, 1.98, False, "s:35-36"),  # the last street has no row after it
    (12.5, 0.5, False, "col:1"),
    (5.0, -0.8, False, "dz:2"),
    (1.0, -2.0, False, "low"),
    (7.0, -2.0, False, "black"),
]


def test_roulette_drop_targets_resolve_like_a_real_table(tmp_path: Path) -> None:
    rack_q = [
        (1, 500),
        (1_000, 10_000),
        (10, 100),
        (1_500, 5_000),
        (1, 1_000_000),
        (5, 100_000),
        (3, 4),
        (500, 100),
    ]
    shorts = [
        1,
        750,
        999,
        1_000,
        1_250,
        1_999,
        2_500,
        10_000,
        12_345,
        99_999,
        250_000,
        999_999,
        1_000_000,
        1_500_000,
    ]
    out = _run(
        {"points": [[u, v, us] for u, v, us, _ in POINTS], "short": shorts, "racks": rack_q},
        tmp_path,
    )
    got = dict(zip([(u, v, us) for u, v, us, _ in POINTS], out["points"], strict=True))
    want = {(u, v, us): s for u, v, us, s in POINTS}
    assert got == want

    # every target the geometry can produce is a bet the engine takes (and every inside bet can be reached)
    s = CasinoSession()
    for key, wheel in (("eu", "european"), ("us", "american")):
        spots = set(Roulette(s, RouletteRules(wheel=wheel)).spots())
        seen = set(out["sweep"][key])
        assert seen <= spots, (key, seen - spots)
        assert spots == seen, (key, spots - seen)

    # the page's chips are the engine's: the same K / M labels and the same rack for any limits
    assert out["short"] == [short(n) for n in shorts]
    assert out["racks"] == [chip_rack(a, b) for a, b in rack_q]
    assert out["fromStatus"] == [7], "status.chips wins over the local fallback"
    assert "--cc:#e85d9f" in out["style"], "a 3000 stack is topped by its biggest ladder chip (2K)"
