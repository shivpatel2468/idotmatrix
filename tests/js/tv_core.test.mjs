// node --test tests/js/*.test.mjs — the TV view's core (src/deskdot/tv/tv.js): the quality tier, the panel looks, who
// decides them (the TV, the studio, the address) and the panel's bloom. tv.js runs in a vm with a minimal DOM; its
// start() waits for DOMContentLoaded, which never fires.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const src = readFileSync(new URL("../../src/deskdot/tv/tv.js", import.meta.url), "utf8");

function load(search = "", stored = null) {
  const store = new Map(Object.entries(stored || {}));
  const window = {};
  const sandbox = {
    window,
    document: { readyState: "loading", documentElement: { dataset: {} }, addEventListener() {}, getElementById: () => null, hidden: false },
    location: { pathname: "/tv/ABCD", search, protocol: "http:", host: "tv.test" },
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) },
    performance: { now: () => 0 },
    requestAnimationFrame: () => 1,
    cancelAnimationFrame() {},
    URLSearchParams,
    TextEncoder,
    console,
    setTimeout,
    clearTimeout,
    queueMicrotask,
  };
  vm.runInNewContext(src, sandbox);
  return { TV: window.TV, doc: sandbox.document };
}

test("quality tier: ?lite=1 / ?hq=1 / ?quality= force it, otherwise hq until measured", () => {
  const { TV } = load();
  assert.equal(TV.tierFromQuery("?lite=1"), "lite");
  assert.equal(TV.tierFromQuery("?quality=lite"), "lite");
  assert.equal(TV.tierFromQuery("?hq=1"), "hq");
  assert.equal(TV.tierFromQuery("?quality=high"), "hq");
  assert.equal(TV.tierFromQuery("?lite=0"), null);
  assert.equal(TV.tierFromQuery(""), null);
  assert.equal(TV.qualityFromQuery("?quality=auto"), "auto");
  assert.equal(TV.qualityFromQuery("?lite=1"), "lite");
  assert.equal(TV.quality, "hq");
  assert.equal(TV.qualityMode, "auto");
  assert.equal(TV.qualityForced, false);
  const forced = load("?lite=1");
  assert.equal(forced.TV.quality, "lite");
  assert.equal(forced.TV.qualityMode, "lite");
  assert.equal(forced.TV.qualityForced, true);
  assert.equal(forced.doc.documentElement.dataset.q, "lite");
  // remembered on this TV
  const kept = load("", { "deskdot.tv.quality": JSON.stringify({ v: "lite", rev: null }) });
  assert.equal(kept.TV.quality, "lite");
  assert.equal(load("?quality=auto", { "deskdot.tv.quality": JSON.stringify({ v: "lite", rev: null }) }).TV.qualityMode, "auto");
});

test("quality tier: slow frame windows drop to lite, smooth ones stay hq", () => {
  const { TV } = load();
  const many = (ms, n = 120) => Array.from({ length: n }, () => ms);
  assert.equal(TV.judgeFrames(many(16.7)), "hq");
  assert.equal(TV.judgeFrames(many(33.3)), "lite"); // a steady 30 fps on a 60 Hz TV
  assert.equal(TV.judgeFrames([...many(16.7, 90), ...many(50, 30)]), "lite"); // a quarter of the frames dropped
  assert.equal(TV.judgeFrames([...many(16.7, 110), ...many(50, 10)]), "hq"); // a few hiccups are fine
  assert.equal(TV.judgeFrames(many(16.7, 20)), null); // too few to say
  assert.equal(TV.judgeFrames([...many(16.7, 119), 5000]), "hq"); // a hidden tab's gap says nothing
});

test("panel look: the studio's three, LED by default, the address or the remembered choice", () => {
  assert.deepEqual([...load().TV.looks], ["pixel", "led", "glow"]);
  assert.equal(load().TV.look, "led");
  for (const v of ["pixel", "led", "glow"]) assert.equal(load(`?look=${v}`).TV.look, v);
  assert.equal(load("?look=hd").TV.look, "led", "the HD look is gone");
  assert.equal(load("", { "deskdot.tv.look": JSON.stringify({ v: "glow", rev: null }) }).TV.look, "glow");
  assert.equal(load("?look=pixel", { "deskdot.tv.look": JSON.stringify({ v: "glow", rev: null }) }).TV.look, "pixel");
  assert.equal(load("", { "deskdot.tv.look": "{not json" }).TV.look, "led");
  assert.equal(load("", { "deskdot.tv.panel-look": "hd" }).TV.look, "led", "an old HD choice falls back to LED");
  assert.equal(load().TV.lookFromQuery("?look=nope"), null);
});

test("display choices: the studio wins until this TV picks again; the address beats the studio's choice at load", () => {
  const { TV } = load();
  const pick = (o) => TV.pickDisplay({ url: null, local: null, studio: null, rev: null, loadRev: null, ...o }, "led");
  assert.deepEqual({ ...pick({}) }, { v: "led", from: "default" });
  assert.deepEqual({ ...pick({ local: { v: "glow", rev: null } }) }, { v: "glow", from: "tv" });
  // the studio set "pixel" (revision 10): it wins over what the TV remembered from before
  assert.deepEqual({ ...pick({ local: { v: "glow", rev: null }, studio: "pixel", rev: 10 }) }, { v: "pixel", from: "studio" });
  // someone picked on the TV after that (their pick carries revision 10): the TV's pick wins…
  assert.deepEqual({ ...pick({ local: { v: "glow", rev: 10 }, studio: "pixel", rev: 10 }) }, { v: "glow", from: "tv" });
  // …until the studio changes its choice again
  assert.deepEqual({ ...pick({ local: { v: "glow", rev: 10 }, studio: "led", rev: 11 }) }, { v: "led", from: "studio" });
  // an address parameter beats the studio's choice that was set when the page loaded, not a later one
  assert.deepEqual({ ...pick({ url: "glow", studio: "pixel", rev: 10, loadRev: 10 }) }, { v: "glow", from: "url" });
  assert.deepEqual({ ...pick({ url: "glow", studio: "pixel", rev: 11, loadRev: 10 }) }, { v: "pixel", from: "studio" });
  // no studio choice (null) leaves the TV's own
  assert.deepEqual({ ...pick({ local: { v: "glow", rev: 3 }, studio: null, rev: 12 }) }, { v: "glow", from: "tv" });
});

test("bloom: the studio's two Gaussian blurs, centred on the light, none for the pixel look", () => {
  const { TV } = load();
  const frame = new Uint8Array(3072);
  assert.equal(TV.bloomField(frame, "pixel", 64), null);
  assert.ok(TV.bloomField(frame, "led", 64).every((v) => v === 0), "a dark frame has no bloom");
  const i = (16 * 32 + 16) * 3;
  frame[i] = 255; // one red LED in the middle
  const n = 64;
  for (const [look, strength] of [["led", 0.55 + 0.3], ["glow", 0.28 + 0.2]]) {
    const f = TV.bloomField(frame, look, n);
    const at = (x, y, c) => f[(y * n + x) * 3 + c];
    let sum = 0;
    for (let k = 0; k < f.length; k += 3) {
      sum += f[k];
      assert.equal(f[k + 1], 0);
      assert.equal(f[k + 2], 0);
    }
    // a blur moves light around, never adds any: the total is the LED (2×2 px at 2 px per LED) × the strengths
    assert.ok(Math.abs(sum - 255 * 4 * strength) < 1, `${look}: ${sum}`);
    // brightest on the LED, symmetric, falling off with distance
    const c = at(32, 32, 0) + at(33, 33, 0);
    assert.ok(at(32, 32, 0) > at(36, 32, 0) && at(36, 32, 0) > at(44, 32, 0) && at(44, 32, 0) > 0);
    assert.ok(Math.abs(at(28, 32, 0) - at(37, 32, 0)) < 1e-3 && Math.abs(at(32, 28, 0) - at(32, 37, 0)) < 1e-3);
    assert.ok(c > 0);
  }
  // the LED look's bloom is the stronger one (0.55 + 0.3 against 0.28 + 0.2), as in the studio
  assert.ok(TV.bloomField(frame, "led", n)[(32 * n + 32) * 3] > TV.bloomField(frame, "glow", n)[(32 * n + 32) * 3]);
});
