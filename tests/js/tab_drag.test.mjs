// node --test tests/js/*.test.mjs — the phone tab bar's draggable bubble (web/src/lib/tabDrag.ts, R-WEB-TABBAR).
import assert from "node:assert/strict";
import test from "node:test";

const t = await import(new URL("../../web/src/lib/tabDrag.ts", import.meta.url));

const SLOT = 90; // a 360 px bar with four tabs
const N = 4;

test("the spring settles on its target with only a small overshoot", () => {
  let s = { x: 0, v: 0 };
  let peak = 0;
  for (let i = 0; i < 120; i++) {
    s = t.springStep(s, 100, 1 / 60);
    peak = Math.max(peak, s.x);
  }
  assert.ok(t.settled(s, 100), `still moving: ${JSON.stringify(s)}`);
  assert.ok(peak > 100 && peak < 112, `overshoot ${peak}`);
});

test("a long frame does not blow the spring up", () => {
  const s = t.springStep({ x: 0, v: 0 }, 300, 0.5);
  assert.ok(Number.isFinite(s.x) && s.x > 0 && s.x < 400);
});

test("the bubble snaps to the tab it mostly covers", () => {
  assert.equal(t.nearestTab(0, SLOT, N), 0);
  assert.equal(t.nearestTab(44, SLOT, N), 0);
  assert.equal(t.nearestTab(46, SLOT, N), 1);
  assert.equal(t.nearestTab(200, SLOT, N), 2);
  assert.equal(t.nearestTab(-50, SLOT, N), 0);
  assert.equal(t.nearestTab(999, SLOT, N), 3);
  assert.equal(t.slotX(2, SLOT), 180);
});

test("dragging follows the finger and rubber-bands past the ends", () => {
  assert.equal(t.dragTarget(100, 45, SLOT, N), 55);
  const past = t.dragTarget(-200, 45, SLOT, N);
  assert.ok(past < 0 && past > -SLOT * 0.35, `left band ${past}`);
  const far = t.dragTarget(2000, 45, SLOT, N);
  assert.ok(far > 270 && far < 270 + SLOT * 0.35, `right band ${far}`);
});

test("a flick on release carries the bubble one tab further", () => {
  assert.equal(t.releaseTab(100, 0, SLOT, N), 1);
  assert.equal(t.releaseTab(100, 1200, SLOT, N), 2);
  assert.equal(t.releaseTab(100, -1200, SLOT, N), 0);
});

test("a press becomes a drag only once it moves sideways past the slop", () => {
  assert.equal(t.isDrag(4, 0), false);
  assert.equal(t.isDrag(10, 2), true);
  assert.equal(t.isDrag(10, 20), false);
});

test("the bubble stretches with speed, within limits", () => {
  assert.deepEqual(t.stretch(0), { sx: 1, sy: 1 });
  const fast = t.stretch(100000);
  assert.ok(fast.sx <= 1.22 && fast.sy >= 0.87 && fast.sy < 1);
});

test("the tap animation's easing is the same spring, from 0 to exactly 1", () => {
  const { easing, ms } = t.springEasing();
  assert.match(easing, /^linear\(0, .*, 1\)$/);
  const pts = easing.slice(7, -1).split(", ").map(Number);
  assert.ok(Math.max(...pts) > 1 && Math.max(...pts) < 1.12, "a small overshoot");
  assert.ok(ms > 200 && ms < 1200, `${ms} ms`);
  // already moving toward the target: it starts faster
  const moving = t.springEasing(6).easing.slice(7, -1).split(", ").map(Number);
  assert.ok(moving[2] > pts[2]);
});
