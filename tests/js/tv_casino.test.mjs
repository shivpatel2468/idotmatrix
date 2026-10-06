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
  const state = { globalAlpha: 1, lineWidth: 1, globalCompositeOperation: "source-over" };
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

/** The TV-only anchors of a snapshot, re-based so "server time" = the test's local clock t. */
function tvAt(st, t) {
  if (!st._tv) return null;
  const out = {};
  for (const [k, v] of Object.entries(st._tv)) out[k] = v && typeof v === "object" && "at_age" in v ? { ...v, at: t - v.at_age } : v;
  return out;
}

/**
 * Mount the scene for `app` and replay every fixture status on the engine's own timeline (snapshot._t), painting
 * at 60 fps in between; `each(S, t)` runs after every painted frame.
 */
function play(app, each, opts = {}) {
  const scene = registered.find((s) => s.match(app));
  assert.ok(scene, `a scene for ${app}`);
  const ctx = ctxFor(app);
  const snaps = FIX.statuses[app];
  ctx.status = snaps[0];
  scene.mount(element(), ctx);
  let t = snaps[0]._t;
  for (let i = 0; i < snaps.length; i++) {
    const st = snaps[i];
    t = Math.max(t, st._t);
    ctx.status = Object.fromEntries(Object.entries(st).filter(([k]) => !k.startsWith("_"))); // the real status
    ctx.tv = tvAt(st, t);
    ctx.stateAt = t;
    scene.update(ctx);
    const end = i + 1 < snaps.length ? Math.min(snaps[i + 1]._t, t + (opts.maxGap || 60)) : t + 4;
    for (; t < end; t += 1 / 60) {
      scene._paint(t);
      if (each) each(scene._state(), t, st);
    }
  }
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

const MOTION = JSON.parse(readFileSync(new URL("./fixtures/casino_motion.json", import.meta.url), "utf8"));
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg}: ${a} vs ${b}`);
const xyOf = (style) => {
  const m = /translate\(([-\d.]+)px,([-\d.]+)px\)/.exec(style.transform || "");
  return m ? [+m[1], +m[2]] : null;
};
const degOf = (style) => {
  const m = /rotate\(([-\d.]+)deg\)/.exec(style.transform || "");
  return m ? (+m[1] * Math.PI) / 180 : null;
};
const wrap = (a) => a - 2 * Math.PI * Math.floor((a + Math.PI) / (2 * Math.PI));

test("roulette: the TV port gives the panel's ball angle and radius (casino_roulette.ball) at every moment", () => {
  for (const r of MOTION.roulette.ball) {
    const b = C.rouletteBallRel(r.t, r.pocket, r.n, 7.5, 1.0);
    near(b.a, r.a, 1e-9, `angle n=${r.n} pocket=${r.pocket} t=${r.t}`);
    near(b.r, r.r, 1e-9, `radius t=${r.t}`);
  }
  for (const r of MOTION.roulette.step) near(C.wheelStep(r.since_lock, r.dt), r.d, 1e-12, `wheel_step ${r.since_lock} ${r.dt}`);
});

test("big six / 7 up 7 down / slots / card deals: the same motion and timing as the panel apps", () => {
  for (const r of MOTION.bigsix) if (r.ts >= 0) near(C.b6Phi(r.end, r.travel, r.stop_s, r.ts), r.phi, 1e-9, `big six ts=${r.ts}`);
  for (const r of MOTION.sevens) {
    const rv = { outcome: { dice: r.dice }, faces: r.faces, lock_s: 1.0, spin_s: 2.6 };
    C.sevensDice(rv, r.t).forEach((d, i) => {
      const [x, y, face, h] = r.at[i];
      near(d.x, x, 0.5, `die ${i} x t=${r.t}`);
      near(d.y, y, 0.5 + 1e-9, `die ${i} y t=${r.t}`);
      assert.equal(d.face, face, `die ${i} face t=${r.t}`);
      assert.equal(d.h, h, `die ${i} squash t=${r.t}`);
    });
  }
  for (const r of MOTION.slots) near(C.reelPos(r.stop, r.n, r.t, r.i), r.pos, 1e-9, `reel ${r.i} t=${r.t}`);
  const outs = [{ player: ["9S", "KS"], banker: ["8H", "QC"] }, { player: ["2S", "3S", "4S"], banker: ["KS", "5H", "9C"] }];
  outs.forEach((o, i) => assert.deepEqual(JSON.parse(JSON.stringify(C.bacDealTimes(o))), MOTION.deals.baccarat[i]));
  for (const [n, pace] of Object.entries(MOTION.deals.andar.pace)) near(C.abPace(+n), pace, 1e-12, `andar pace ${n}`);
});

test("roulette: the ball never teleports and lands in the drawn pocket when the panel's does", () => {
  let prev = null;
  let worst = 0;
  let landed = 0;
  play("casino_roulette", (S, t, st) => {
    const bs = S.L.ball.c.style;
    const p = xyOf(bs);
    const shown = p && +bs.opacity > 0.99;
    if (shown && prev) worst = Math.max(worst, Math.hypot(p[0] - prev[0], p[1] - prev[1]));
    prev = shown ? p : null;
    const rv = (S.ctx.tv || {}).reveal;
    if (shown && rv && t - (rv.at - rv.since_lock) > 7.5 + 0.6) {
      // settled: the ball sits in the drawn pocket of the wheel as the TV draws it
      const rot = degOf(S.L.wheel.c.style);
      const a = Math.atan2(p[0] + 17 - C.R_CX, -(p[1] + 17 - C.R_CY));
      const n = C.EU_WHEEL.length;
      near(Math.abs(wrap(a - rot - (rv.outcome.pocket * 2 * Math.PI) / n)), 0, 0.02, "ball in its pocket");
      landed++;
    }
  });
  assert.ok(landed > 30, `checked ${landed} settled frames`);
  assert.ok(worst < 40, `largest ball step between two 60 fps frames: ${worst.toFixed(1)} px`);
});

test("roulette: the TV wheel follows the panel's angle (tv.wheel anchors) without jumps", () => {
  let prevRot = null;
  let worst = 0;
  let err = 0;
  let t0 = null;
  play("casino_roulette", (S, t, st) => {
    const rot = degOf(S.L.wheel.c.style);
    if (prevRot != null) worst = Math.max(worst, Math.abs(rot - prevRot));
    prevRot = rot;
    const w = (S.ctx.tv || {}).wheel;
    if (!w) return;
    if (t0 == null) t0 = t;
    const rv = (S.ctx.tv || {}).reveal;
    const sl = rv ? t - (rv.at - rv.since_lock) : null;
    const panel = w.rot - C.wheelStep(sl, t - w.at); // where the panel's wheel is now
    // (during the 1 s lock the panel shows NO MORE BETS, not the wheel: the TV may still be slewing then)
    if (t - t0 > 2 && st.phase !== "locked") err = Math.max(err, Math.abs(wrap(rot - panel)));
  });
  assert.ok(worst < 0.15, `largest wheel step per frame ${worst.toFixed(3)} rad`);
  assert.ok(err < 0.02, `the TV wheel strays ${err.toFixed(4)} rad from the panel's`);
});

test("big six: the wheel stops exactly on the drawn segment at the panel's stop time, without jumps", () => {
  let prev = null;
  let worst = 0;
  let checked = 0;
  play("casino_bigsix", (S, t) => {
    const phi = degOf(S.L.wheel.c.style);
    if (prev != null) worst = Math.max(worst, Math.abs(wrap(phi - prev)));
    prev = phi;
    const rv = (S.ctx.tv || {}).reveal;
    if (rv && t - (rv.at - rv.since_lock) - 1 > 6.4 + 0.05) {
      const under = Math.floor((((-phi % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) / ((2 * Math.PI) / 54)) % 54;
      assert.equal(under, rv.outcome.segment);
      checked++;
    }
  });
  assert.ok(checked > 30);
  assert.ok(worst < 0.25, `largest wheel step per frame ${worst.toFixed(3)} rad`);
});

test("7 up 7 down: the dice end on the drawn faces at the panel's moment", () => {
  let checked = 0;
  play("casino_sevens", (S, t) => {
    const rv = (S.ctx.tv || {}).reveal;
    if (rv && t - (rv.at - rv.since_lock) > 1 + 2.6 + 0.05) {
      assert.deepEqual([...S.fx.faces], rv.outcome.dice);
      checked++;
    }
  });
  assert.ok(checked > 30);
});

test("the table layer is not repainted while a wheel spins (60 fps budget)", () => {
  for (const app of ["casino_roulette", "casino_bigsix"]) {
    let spinFrames = 0;
    let repaints = 0;
    let lastKey = null;
    play(app, (S, t, st) => {
      if (st.phase !== "spinning") return (lastKey = S.lastKey);
      spinFrames++;
      if (S.lastKey !== lastKey) repaints++;
      lastKey = S.lastKey;
    });
    assert.ok(spinFrames > 200, `${app}: ${spinFrames} spin frames`);
    assert.ok(repaints <= 4, `${app}: the table layer repainted ${repaints}× during the spin`);
  }
});

test("the synced clock slews, never jumps back, snaps only on a big change", () => {
  let off = 0;
  const S = { ctx: { now: () => 0, serverNow: () => 0 + off }, sclk: {} };
  assert.equal(C.serverClock(S, 10), 10);
  off = 0.2; // the estimate moves by 200 ms: slewed in, never more than 30 % of real time
  let last = 10;
  for (let t = 10 + 1 / 60; t < 12; t += 1 / 60) {
    const T = C.serverClock(S, t);
    assert.ok(T - last > 0 && T - last <= (1 / 60) * 1.31, "monotonic, bounded rate");
    last = T;
  }
  near(last - 12, 0.2, 0.02, "converged");
  off = -0.5; // backwards: slows down, never goes back
  for (let t = 12; t < 15; t += 1 / 60) {
    const T = C.serverClock(S, t);
    assert.ok(T >= last);
    last = T;
  }
  off = 30; // a big jump (first sync, wake from sleep) snaps
  near(C.serverClock(S, 15.1), 45.1, 1e-9, "snap");
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

test("one clock model on every device: the phone page's and the studio's shared clocks behave like the TV's", async () => {
  // the phone page: the marked block in casino.html, run as is
  const page = readFileSync(new URL("../../src/deskdot/casino.html", import.meta.url), "utf8");
  const block = page.slice(page.indexOf("/* ===== BEGIN shared sync clock"), page.indexOf("/* ===== END shared sync clock"));
  let perf = 0;
  const box = { performance: { now: () => perf * 1000 }, Date: { now: () => 5e12 }, Math, Number };
  vm.runInNewContext(`${block}; globalThis.SYNC = SYNC;`, box);
  // the studio: web/src/components/casino/sync.ts (Node strips its types)
  const studio = await import(new URL("../../web/src/components/casino/sync.ts", import.meta.url));
  const realPerf = globalThis.performance;
  Object.defineProperty(globalThis, "performance", { value: { now: () => perf * 1000 }, configurable: true });
  try {
    for (const clock of [{ name: "phone", s: box.SYNC, now: () => box.SYNC.now() }, { name: "studio", s: studio, now: () => studio.serverNow() }]) {
      perf = 100;
      clock.s.sample(5000, 99.95, 100.05); // the engine's clock is 4900 s ahead of this device's
      near(clock.now(), 5000, 1e-6, `${clock.name}: first sample snaps`);
      clock.s.sample(5000.3, 100.95, 101.05); // the next sample says +0.3 s: slewed, never a jump
      let last = clock.now();
      for (perf = 100.01; perf < 104; perf += 1 / 60) {
        const T = clock.now();
        assert.ok(T >= last && T - last <= (1 / 60) * 1.31 + 1e-9, `${clock.name}: smooth and monotonic`);
        last = T;
      }
    }
  } finally {
    Object.defineProperty(globalThis, "performance", { value: realPerf, configurable: true });
  }
});

// ------------------------------------------------------------------ the chip ladder (casino/chips.py, docs/CASINO.md §5)
// Expected racks: uv run python -c "from deskdot.casino.chips import chip_rack; print([c['v'] for c in chip_rack(a, b)])"
const eq = (a, b, m) => assert.deepEqual(JSON.parse(JSON.stringify(a)), JSON.parse(JSON.stringify(b)), m); // across the vm realm
const RACKS = {
  "1-500": [1, 5, 25, 100, 500], "5-500": [5, 25, 100, 500], "1-1000000": [1, 25, 1000, 5000, 25000, 250000, 1000000],
  "10-100000": [10, 100, 500, 2000, 10000, 25000, 100000], "1000-50000": [1000, 2000, 5000, 10000, 25000, 50000],
  "2-300": [2, 5, 25, 100], "250-250": [250], "7-7": [7], "100-10000": [100, 500, 1000, 2000, 5000, 10000],
  "1-5000": [1, 5, 25, 500, 1000, 2000, 5000], "3-2000000": [3, 25, 1000, 5000, 25000, 250000, 1000000],
  "500-1000000": [500, 2000, 5000, 25000, 100000, 250000, 1000000], "50-25000": [50, 100, 500, 2000, 5000, 10000, 25000],
};

test("chip rack: the same chips as casino/chips.py chip_rack (fallback for an engine without status.chips)", () => {
  for (const [k, want] of Object.entries(RACKS)) {
    const [lo, hi] = k.split("-").map(Number);
    eq(C.chipRack(lo, hi).map((c) => c.v), want, k);
    assert.ok(C.chipRack(lo, hi).length <= C.RACK_MAX);
  }
  // an off-ladder table minimum is the smallest chip, coloured like the next ladder chip up
  eq(C.chipRack(2, 300)[0], { v: 2, label: "2", color: "#d23a3a", edge: "#ffffff" });
  eq(C.chipRack(7, 7), [{ v: 7, label: "7", color: "#2e9a55", edge: "#ffffff" }]);
  const hr = C.chipRack(1000, 50000);
  eq(hr.map((c) => c.label), ["1K", "2K", "5K", "10K", "25K", "50K"]);
  eq(hr.map((c) => c.color), ["#f2c230", "#e85d9f", "#c9772b", "#2f6fd6", "#18a39a", "#9a2f4d"]);
  assert.equal(C.pyRound(4.5), 4);
  assert.equal(C.pyRound(1.5), 2);
});

test("chip rack: status.chips wins, the house limits are the fallback, K / M labels", () => {
  const sent = [{ v: 1000, label: "1K", color: "#f2c230", edge: "#5a3d00" }, { v: 5000, label: "5K", color: "#c9772b", edge: "#ffffff" }];
  eq(C.rackOf({ chips: sent, house: { min_bet: 1, max_bet: 500 } }), sent);
  eq(C.rackOf({ house: { min_bet: 1000, max_bet: 50000 } }).map((c) => c.v), RACKS["1000-50000"]);
  eq(C.rackOf({ chips: "nonsense", house: {} }).map((c) => c.v), RACKS["1-500"]);
  eq(C.rackOf({}).map((c) => c.v), RACKS["1-500"]);
  for (const [v, s] of [[1000, "1K"], [2500, "2.5K"], [1250, "1.25K"], [1000000, "1M"], [750, "750"], [25000, "25K"]]) assert.equal(C.shortChip(v), s);
});

test("stacks break into ladder chips, largest first (casino/chips.py break_into)", () => {
  eq(C.breakInto(12345), [10000, 2000, 100, 100, 100, 25, 5, 5, 5, 5]);
  eq(C.breakInto(2600), [2000, 500, 100]);
  eq(C.breakInto(0), []);
  // a table whose minimum is off the ladder uses that chip too
  eq(C.breakInto(7, C.chipRack(7, 7)), [7]);
  assert.equal(C.chipStyle(5000).color, "#c9772b");
  assert.equal(C.chipStyle(7, C.chipRack(7, 7)).color, "#2e9a55");
});

test("a high-roller table draws its stacks without errors (status.chips from a new engine)", () => {
  bad.length = 0;
  const scene = registered.find((s) => s.match("casino_roulette"));
  const ctx = ctxFor("casino_roulette");
  const st = JSON.parse(JSON.stringify(FIX.statuses.casino_roulette.find((s) => Object.keys(s.spot_bets || {}).length)));
  st.house = { ...st.house, min_bet: 1000, max_bet: 50000 };
  st.chips = C.chipRack(1000, 50000);
  for (const list of Object.values(st.spot_bets)) for (const e of list) e.amount = 12500;
  ctx.status = st;
  scene.mount(element(), ctx);
  scene.update(ctx);
  scene._paint(1000);
  assert.equal(scene._state().err, null);
  eq(scene._state().rack.map((c) => c.label), ["1K", "2K", "5K", "10K", "25K", "50K"]);
  eq(bad.slice(0, 5), []);
  scene.unmount();
});
