"""The phone page's bet input (casino.html) with a mouse, a pen and a finger: a click on a spot is exactly one chip,
rapid clicks are one chip each, right / middle clicks do nothing, a click on a rack chip picks it (no pointer capture
on the rack: with a mouse it retargets the click), keyboard Enter / Space still bets once. Runs the page's real
handlers in Node against a tiny fake DOM; skipped when Node isn't installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "src" / "deskdot" / "casino.html"

HARNESS = r"""
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const src = html.slice(html.lastIndexOf("<script>") + 8, html.lastIndexOf("</script>"));
const stub = new Proxy(function () {}, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : k === "length" ? 0 : k === Symbol.iterator ? [][Symbol.iterator] : stub), apply: () => stub, construct: () => stub, set: () => true });
function mk(name, extra) {
  const o = Object.assign({ name, _h: {}, dataset: {}, captured: [], style: { setProperty() {}, removeProperty() {} },
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    addEventListener(t, f) { (o._h[t] = o._h[t] || []).push(f); }, removeEventListener() {},
    setPointerCapture(id) { o.captured.push(id); }, closest: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100 }) }, extra || {});
  return new Proxy(o, { get: (t, k) => (k in t ? t[k] : stub), set: (t, k, v) => { t[k] = v; return true; } });
}
const reg = {}, winH = {};
let under = null; // what document.elementFromPoint returns
const doc = new Proxy({}, { get: (t, k) => {
  if (k === "querySelector") return (s) => (reg[s] = reg[s] || mk(s));
  if (k === "querySelectorAll") return () => [];
  if (k === "createElement") return () => mk("new");
  if (k === "elementFromPoint") return () => under;
  if (k === "addEventListener") return (t, f) => { (winH[t] = winH[t] || []).push(f); };
  return stub;
} });
const g = globalThis;
Object.defineProperty(g, "navigator", { value: {}, configurable: true });
let clock = 1e6;
Object.defineProperty(g, "performance", { value: { now: () => clock }, configurable: true });
Object.assign(g, { document: doc, window: g, localStorage: { getItem: () => null, setItem() {} }, sessionStorage: { getItem: () => null, setItem() {} },
  matchMedia: () => ({ matches: true }), requestAnimationFrame: () => 0, cancelAnimationFrame() {}, location: { pathname: "/p/TEST", protocol: "http:", host: "x" },
  WebSocket: function () { throw new Error("offline"); }, devicePixelRatio: 1, ResizeObserver: function () { return { observe() {}, disconnect() {} }; },
  getComputedStyle: () => ({ getPropertyValue: () => "" }), addEventListener: (t, f) => { (winH[t] = winH[t] || []).push(f); } });
g.setInterval = () => 0; g.setTimeout = () => 0; g.clearTimeout = () => {};
const api = new Function(src + "\n;return { S, setWs: (w) => { ws = w; }, primary, liveWanted, GAMES };")();
const S = api.S, sent = [];
api.setWs({ readyState: 1, send: (m) => sent.push(JSON.parse(m)) });
S.pub = { phase: "betting", house: {} }; S.priv = { can_bet: true, credits: 1000, bets: {} }; S.chip = 5; S.mod = null;
const fire = (el, type, ev) => { for (const f of (el._h || {})[type] || []) f(ev); };
const fireWin = (type, ev) => { for (const f of winH[type] || []) f(ev); };
const zone = mk("zone"); zone.dataset.spot = "red"; zone.closest = (s) => (s.includes("data-spot") ? zone : null);
const board = reg["#board"], rack = reg["#rack"];
const ev = (type, o) => Object.assign({ type, pointerId: 1, pointerType: "mouse", button: 0, isPrimary: true, clientX: 50, clientY: 50, detail: 1, target: zone, cancelable: true, preventDefault() {} }, o || {});
function click(o) { under = zone; fire(board, "pointerdown", ev("pointerdown", o)); fire(board, "pointerup", ev("pointerup", o)); fireWin("pointerup", ev("pointerup", o)); fire(board, "click", ev("click", o)); }
const bets = () => sent.filter((m) => m.op === "bet").length;
const out = {};
click(); out.one = bets();
click(); click(); click(); out.rapid = bets() - out.one;
let b0 = bets(); click({ button: 2 }); click({ button: 1 }); out.rightMiddle = bets() - b0;
b0 = bets(); click({ pointerType: "pen" }); click({ pointerType: "touch", detail: 0 }); out.penTouch = bets() - b0;
clock += 1000; b0 = bets(); fire(board, "click", ev("click", { detail: 0 })); out.keyboard = bets() - b0;
// the rack: a mouse click on a chip picks it, and nothing captures the pointer
const chip = mk("chip"); chip.dataset.v = "25"; chip.disabled = false; chip.closest = (s) => (s === ".chip" ? chip : null);
fire(rack, "pointerdown", ev("pointerdown", { target: chip })); fireWin("pointerup", ev("pointerup", { target: chip })); fire(rack, "click", ev("click", { target: chip }));
out.chip = S.chip; out.rackCaptured = rack.captured.length;
out.primary = [api.primary({ pointerType: "mouse", button: 0 }), api.primary({ pointerType: "mouse", button: 2 }), api.primary({ pointerType: "touch", button: 0 }), api.primary({ pointerType: "mouse", button: 0, isPrimary: false })];
// the live panel: big while the table plays, the betting table while betting; games played on the phone opt out
const lw = (phase, mod) => api.liveWanted({ casino: true, phase }, mod);
out.live = { betting: lw("betting"), locked: lw("locked"), spinning: lw("spinning"), dealing: lw("dealing"), result: lw("result"),
  idle: lw("idle"), action: lw("action"), notCasino: api.liveWanted({ phase: "spinning" }),
  optOut: ["slots", "housie", "blackjack", "holdem", "teenpatti"].filter((g) => api.GAMES[g] && api.GAMES[g].livePanel === false).length,
  roulette: api.GAMES.roulette.livePanel !== false };
process.stdout.write(JSON.stringify(out));
"""


def test_mouse_pen_and_touch_bet_exactly_once(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    h = tmp_path / "input.js"
    h.write_text(HARNESS, encoding="utf-8")
    r = subprocess.run([node, str(h), str(PAGE)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["one"] == 1, (
        "a mouse click on a spot is exactly one chip (pointerup bets, the click doesn't again)"
    )
    assert out["rapid"] == 3, "rapid clicks: one chip each"
    assert out["rightMiddle"] == 0, "right / middle clicks never bet"
    assert out["penTouch"] == 2
    assert out["keyboard"] == 1, "Enter / Space on a focused zone still bets once"
    assert out["chip"] == 25 and out["rackCaptured"] == 0, "a click on a rack chip picks it"
    assert out["primary"] == [True, False, True, False]


def test_live_panel_follows_the_phase(tmp_path: Path) -> None:
    """Phones show the live panel (opt-in binary frames) instead of the board while the table plays, and the
    betting table again when betting reopens; games played on the phone itself keep their own view."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    h = tmp_path / "input.js"
    h.write_text(HARNESS, encoding="utf-8")
    r = subprocess.run([node, str(h), str(PAGE)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    live = json.loads(r.stdout)["live"]
    assert live["betting"] is False and live["idle"] is False and live["action"] is False
    assert live["locked"] and live["spinning"] and live["dealing"] and live["result"]
    assert live["notCasino"] is False and live["optOut"] == 5 and live["roulette"]
    page = PAGE.read_text(encoding="utf-8")
    assert page.count("<script") == 1 and 'sock.binaryType = "arraybuffer"' in page
    assert '{ type: "frames", on: !!v }' in page  # opt in per socket (old pages never get binary)
