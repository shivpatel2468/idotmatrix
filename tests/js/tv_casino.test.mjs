// node --test tests/js/*.test.mjs — the TV view's casino scenes (src/deskdot/tv/tv-casino.js).
// Fixtures: tests/js/fixtures/casino_status.json, real public statuses from the Python tables
// (regenerate: uv run python tests/js/fixtures/dump_casino_status.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const src = readFileSync(new URL("../../src/deskdot/tv/tv-casino.js", import.meta.url), "utf8");
const FIX = JSON.parse(readFileSync(new URL("./fixtures/casino_status.json", import.meta.url), "utf8"));

// ------------------------------------------------------------------ a DOM-free canvas: every call is checked for NaN
const bad = [];
function fake2d() {
  const state = {};
  const gradient = { addColorStop() {} };
  return new Proxy(state, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (prop === "measureText") return (s) => ({ width: String(s).length * 10 });
      if (prop === "createLinearGradient" || prop === "createRadialGradient" || prop === "createPattern")
        return (...a) => (check(prop, a), gradient);
      return (...a) => check(prop, a);
    },
    set(target, prop, v) {
      if (typeof v === "number" && !Number.isFinite(v)) bad.push(`${String(prop)} = ${v}`);
      target[prop] = v;
      return true;
    },
  });
}
function check(name, args) {
  for (const a of args) if (typeof a === "number" && Number.isNaN(a)) bad.push(`${name}(${args.join(", ")})`);
  if (name === "drawImage" && args[0] == null) bad.push("drawImage(null)");
}
function element() {
  return { style: {}, width: 0, height: 0, children: [], appendChild(c) { this.children.push(c); }, getContext: () => fake2d(), remove() {} };
}
const registered = [];
const TV = { pixelRatio: 1, registerScene: (s) => registered.push(s) };
const sandbox = { window: { TV }, document: { createElement: element, hidden: false }, console, Math, JSON, Object, Array, Number, String, Set, Map, Proxy };
sandbox.requestAnimationFrame = () => 0; // the tests paint by hand
sandbox.cancelAnimationFrame = () => {};
vm.runInNewContext(src, sandbox);
const C = TV.casino;

function ctxFor(app) {
  return { app, meta: { id: app }, status: {}, lobby: null, panel: null, stateAt: 0, theme: {}, avatars: {}, now: () => 0, fmt: (n) => String(n), drawPanel() {} };
}

/** Mount the scene for `app`, feed it every fixture status 0.25 s apart (painting a few frames in between). */
function play(app, each) {
  const scene = registered.find((s) => s.match(app));
  assert.ok(scene, `a scene for ${app}`);
  const ctx = ctxFor(app);
  const snaps = FIX.statuses[app];
  ctx.status = snaps[0];
  scene.mount(element(), ctx);
  let t = 100;
  for (const st of snaps) {
    ctx.status = st;
    ctx.stateAt = t;
    scene.update(ctx);
    for (const dt of [0, 0.1, 0.6, 1.2]) scene._paint(t + dt);
    if (each) each(scene._state(), st, t);
    t += 1.3;
  }
  // and let the last state play out
  for (let i = 0; i < 20; i++) scene._paint(t + i * 0.25);
  const S = scene._state();
  assert.equal(S.err, null, `${app}: ${S.err && S.err.stack}`);
  scene.unmount();
  return S;
}

test("ten casino scenes register, one per table", () => {
  const apps = ["casino_roulette", "casino_blackjack", "casino_baccarat", "casino_slots", "casino_holdem", "casino_teenpatti",
    "casino_andarbahar", "casino_bigsix", "casino_sevens", "casino_housie"];
  assert.equal(registered.length, 10);
  for (const a of apps) assert.equal(registered.filter((s) => s.match(a)).length, 1, a);
  assert.equal(registered.filter((s) => s.match("snake")).length, 0);
});

for (const app of Object.keys(FIX.statuses)) {
  test(`${app}: every captured status draws without errors or NaN`, () => {
    bad.length = 0;
    play(app);
    assert.deepEqual(bad.slice(0, 5), []);
  });
}

test("the scenes survive a preview status and an empty one", () => {
  for (const s of registered) {
    const ctx = ctxFor(s.id);
    ctx.status = { casino: true, game: "x", view: "demo", table_theme: { id: "royal", css: { felt: "#1b4aa8" } } };
    s.mount(element(), ctx);
    s._paint(1);
    ctx.status = {};
    s.update(ctx);
    s._paint(2);
    assert.equal(s._state().err, null, `${s.id}: ${s._state().err}`);
    s.unmount();
  }
});

test("roulette: every spot of both wheels has a place on the layout and the right pockets", () => {
  for (const wheel of ["european", "american"]) {
    const B = C.rouletteBoard(wheel === "american");
    for (const [id, nums] of Object.entries(FIX.tables[`roulette_${wheel}`])) {
      const p = C.rouletteSpotXY(id, B);
      assert.ok(p && Number.isFinite(p[0]) && Number.isFinite(p[1]), `${wheel} ${id}`);
      assert.ok(p[0] >= B.x0 && p[0] <= B.x0 + B.zw + 12 * B.cw + B.colW && p[1] >= B.y0 && p[1] <= B.y0 + 3 * B.ch + B.dzH + B.emH, `${id} on the board`);
      assert.deepEqual([...C.rouletteCovers(id)].sort((a, b) => a - b), [...nums].sort((a, b) => a - b), id);
    }
  }
  assert.equal(new Set(Object.keys(FIX.tables.roulette_european).map((id) => C.rouletteSpotXY(id, C.rouletteBoard(false)).join())).size,
    Object.keys(FIX.tables.roulette_european).length, "no two spots share a point");
});

test("roulette: the ball lands in the drawn pocket", () => {
  const S = play("casino_roulette");
  const res = FIX.statuses.casino_roulette.filter((s) => s.phase === "result").at(-1).result.outcome;
  assert.equal(S.fx.landed, res.pocket);
  assert.equal(S.fx.land, null);
});

test("big six: the wheel stops with the drawn segment under the clapper", () => {
  assert.deepEqual([...C.B6_WHEEL], FIX.tables.bigsix_wheel);
  const scene = registered.find((s) => s.match("casino_bigsix"));
  const snaps = FIX.statuses.casino_bigsix;
  const ctx = ctxFor("casino_bigsix");
  ctx.status = snaps[0];
  scene.mount(element(), ctx);
  let t = 50;
  let checked = 0;
  for (const st of snaps) {
    ctx.status = st;
    ctx.stateAt = t;
    scene.update(ctx);
    for (let i = 0; i < 6; i++) scene._paint(t + i * 0.25);
    const S = scene._state();
    if (st.phase === "result" && !S.fx.land && S.fx.landed != null) {
      const phi = S.fx.rest;
      const under = Math.floor((((-phi % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) / ((2 * Math.PI) / 54)) % 54;
      assert.equal(under, st.result.outcome.segment);
      checked++;
    }
    t += 1.5;
  }
  assert.ok(checked > 0);
  scene.unmount();
});

test("countdowns converge on the real deadline from whole seconds", () => {
  const cd = new C.Countdown();
  const deadline = 17.37;
  for (let t = 3; t < 17; t += 0.2) cd.observe("k", Math.max(0, Math.ceil(deadline - t - 1e-6)), t);
  assert.ok(Math.abs(cd.at - deadline) < 0.21, `${cd.at}`);
  cd.observe("k", 20, 17); // the deadline moved: start again
  assert.ok(Math.abs(cd.at - 36.5) < 0.51);
  cd.observe("k", null, 18);
  assert.equal(cd.at, null);
});

test("the spin clock: lock time from the reveal deadline", () => {
  const pt = new C.PhaseTracker();
  // a roulette round locked at t = 10: reveal at 18.5
  for (let t = 10.05; t < 18; t += 0.2) pt.observe({ round: 4, phase: t < 11 ? "locked" : "spinning", reveal_in: Math.ceil(18.5 - t - 1e-6) }, t);
  assert.ok(Math.abs(C.lockTime(pt, 7.5) - 10) < 0.21);
});

test("card and road helpers", () => {
  assert.deepEqual({ ...C.parseCard("TD") }, { rank: "10", suit: "D", red: true });
  assert.equal(C.parseCard("??"), null);
  assert.equal(C.baccaratTotal(["9S", "8H"]), 7);
  assert.equal(C.baccaratTotal(["KS", "AH", "5C"]), 6);
  const road = C.bigRoad([{ winner: "player" }, { winner: "player" }, { winner: "tie" }, { winner: "banker" }]);
  assert.deepEqual(JSON.parse(JSON.stringify(road.map((e) => [e.c, e.r, e.w, e.ties]))), [[0, 0, "player", 0], [0, 1, "player", 1], [1, 0, "banker", 0]]);
  // the slot reel lands exactly on its stop and settles there
  assert.equal(C.reelPos(5, 20, 0, 0), 5 - 60);
  assert.ok(Math.abs(C.reelPos(5, 20, 9, 2) - 5) < 1e-6);
  assert.ok(Math.abs(C.settle(3, 2, 1.5, 1.5) - 3) < 1e-9);
});

test("seats stay on the stage", () => {
  for (let n = 1; n <= 10; n++)
    for (let i = 0; i < n; i++) {
      const [x, y] = C.pokerSeatXY(i, n);
      assert.ok(x > 60 && x < 1480 && y > 100 && y < 900, `poker ${i}/${n}`);
      const [bx, by] = C.bjSeatXY(i, Math.max(n, 3));
      assert.ok(bx > 60 && bx < 1480 && by > 200 && by < 800, `blackjack ${i}/${n}`);
    }
});
