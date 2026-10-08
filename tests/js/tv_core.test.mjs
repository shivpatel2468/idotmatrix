// node --test tests/js/*.test.mjs — the TV view's core (src/deskdot/tv/tv.js): the quality tier, the panel look and
// the HD upscaler. tv.js runs in a vm with a minimal DOM; its start() waits for DOMContentLoaded, which never fires.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const src = readFileSync(new URL("../../src/deskdot/tv/tv.js", import.meta.url), "utf8");

function load(search = "", stored = null) {
  const store = new Map(stored ? [["deskdot.tv.panel-look", stored]] : []);
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
  assert.equal(TV.quality, "hq");
  assert.equal(TV.qualityForced, false);
  const forced = load("?lite=1");
  assert.equal(forced.TV.quality, "lite");
  assert.equal(forced.TV.qualityForced, true);
  assert.equal(forced.doc.documentElement.dataset.q, "lite"); // CSS keys the lite rules off html[data-q]
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

test("panel look: the classic LEDs by default, ?look=hd or the remembered choice for HD", () => {
  assert.equal(load().TV.look, "led");
  assert.equal(load("?look=hd").TV.look, "hd");
  assert.equal(load("", "hd").TV.look, "hd");
  assert.equal(load("?look=led", "hd").TV.look, "led");
  assert.equal(load("?look=hd", "led").TV.look, "hd");
  assert.equal(load().TV.lookFromQuery("?look=nope"), null);
});

// ------------------------------------------------------------------ the HD upscaler (Scale2x / EPX, three passes)
const rgb = (r, g, b) => (0xff000000 | (b << 16) | (g << 8) | r) >>> 0;
function frame(fill) {
  const d = new Uint8Array(3072);
  for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) {
    const c = fill(x, y);
    if (c) d.set(c, (y * 32 + x) * 3);
  }
  return d;
}

test("HD upscaler: only the frame's own colours, every pixel where the panel put it", () => {
  const { TV } = load();
  const data = frame((x, y) => (x === y ? [255, 60, 30] : (x + 2 * y) % 7 === 0 ? [0, 200, 255] : x > 25 ? [20, 80, 30] : null));
  const colours = new Set();
  for (let i = 0; i < 1024; i++) colours.add(rgb(data[i * 3], data[i * 3 + 1], data[i * 3 + 2]));
  for (const passes of [2, 3]) {
    const { px, size } = TV.upscale(data, passes);
    assert.equal(size, 32 << passes);
    assert.equal(px.length, size * size);
    const k = 1 << passes;
    for (let i = 0; i < px.length; i++) assert.ok(colours.has(px[i] >>> 0), "a colour the frame doesn't have");
    // the centre of each panel pixel's block keeps that pixel's colour (shapes don't move or swap)
    for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) {
      const i = (y * 32 + x) * 3;
      const c = (y * k + k / 2) * size + x * k + k / 2;
      const want = rgb(data[i], data[i + 1], data[i + 2]);
      const block = [px[c], px[c - 1], px[c - size], px[c - size - 1]].map((v) => v >>> 0);
      assert.ok(block.includes(want), `pixel ${x},${y}`);
    }
  }
});

test("HD upscaler: flat areas stay flat, a staircase diagonal gets smooth", () => {
  const { TV } = load();
  const flat = TV.upscale(frame(() => [10, 20, 30]), 3).px;
  assert.ok(flat.every((v) => v >>> 0 === rgb(10, 20, 30)));
  // a filled triangle below the diagonal: nearest-neighbour keeps 8-px steps, the upscaler cuts them finer
  const data = frame((x, y) => (y > x ? [255, 255, 255] : null));
  const { px, size } = TV.upscale(data, 3);
  const steps = (row) => {
    let n = 0;
    for (let x = 1; x < size; x++) if ((px[row * size + x] >>> 0) !== (px[row * size + x - 1] >>> 0)) n++;
    return n;
  };
  // where a row's edge sits, per output row: nearest-neighbour moves it 8 px every 8 rows, EPX in smaller steps
  const edge = (row) => {
    for (let x = 0; x < size; x++) if ((px[row * size + x] >>> 0) !== rgb(255, 255, 255)) return x;
    return size;
  };
  const moves = new Set();
  for (let row = 8; row < 200; row++) moves.add(Math.abs(edge(row) - edge(row - 1)));
  assert.ok(Math.max(...moves) < 8, `edge moves ${[...moves]}`);
  assert.ok(steps(100) <= 2);
});
