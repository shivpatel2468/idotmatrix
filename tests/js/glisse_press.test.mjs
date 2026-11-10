// node --test tests/js/*.test.mjs — the phone's glass keys after Glisse (web/src/lib/glissePress.ts, R-STU-15) and the
// tab bar's lifted lens (web/src/lib/glisse.ts TAB_LENS, R-STU-11).
import assert from "node:assert/strict";
import test from "node:test";

const p = await import(new URL("../../web/src/lib/glissePress.ts", import.meta.url));
const g = await import(new URL("../../web/src/lib/glisse.ts", import.meta.url));

test("a finger grows a key until its longer side is ~15 px bigger; a mouse only 6 px", () => {
  const [sx, sy, tx, ty] = p.pressTarget(120, 40, 0, 0, p.TOUCH);
  assert.ok(Math.abs(sx * 120 - 135) < 0.01, `touch width ${sx * 120}`);
  assert.equal(sx, sy);
  assert.equal(tx, 0);
  assert.equal(ty, 0);
  const [mx] = p.pressTarget(120, 40, 0, 0, p.POINTER);
  assert.ok(Math.abs(mx * 120 - 126) < 0.01, `mouse width ${mx * 120}`);
});

test("dragging stretches the key along the drag, thins it across and leans it that way, with a rubber band", () => {
  const [sx, sy, tx, ty] = p.pressTarget(120, 40, 60, 0, p.TOUCH);
  assert.ok(sx > sy, "longer along a sideways drag");
  assert.ok(tx > 0 && ty === 0, "leans toward the finger");
  const [, , far] = p.pressTarget(120, 40, 6000, 0, p.TOUCH);
  assert.ok(far < 8 && far > tx, `the lean tops out under 8 px (${far})`);
  const [ux, uy, , uty] = p.pressTarget(120, 40, 0, -60, p.TOUCH);
  assert.ok(uy > ux && uty < 0, "a drag up stretches it up");
});

test("a menu card gives at most 7 px under a finger", () => {
  assert.equal(p.resistance(0), 0);
  assert.ok(p.resistance(20) > 0 && p.resistance(20) < 7);
  assert.ok(p.resistance(10000) <= 7 && p.resistance(10000) > 6.99);
  assert.equal(p.resistance(-30), -p.resistance(30));
});

test("the spring settles on its target from any frame time, and the release bounces past it", () => {
  for (const dt of [1 / 120, 1 / 60, 1 / 30]) {
    let x = 1.12, v = 0;
    for (let t = 0; t < 2; t += dt) [x, v] = p.advance(x, v, 1, ...p.TOUCH.release, dt);
    assert.ok(Math.abs(x - 1) < 1e-3 && Math.abs(v) < 1e-2, `dt ${dt}: ${x}`);
  }
  // under-damped release: it overshoots its resting size once
  let x = 1.12, v = 0, min = 2;
  for (let i = 0; i < 120; i++) {
    [x, v] = p.advance(x, v, 1, ...p.TOUCH.release, 1 / 120);
    min = Math.min(min, x);
  }
  assert.ok(min < 1, `bounces past (${min})`);
});

test("the tab bar's lens bends only a narrow band at its rim and leaves the labels inside sharp", () => {
  const shape = { w: 114, h: 70, r: 32 };
  const tab = g.lensPixels(shape, 1, g.TAB_LENS);
  const glass = g.lensPixels(shape, 1);
  const at = (m, x, y) => (y * m.cols + x) * 4;
  // a point a quarter of the way in: the glass lens still bends there, the tab lens doesn't
  const q = at(tab, 28, 35);
  assert.ok(tab.mask[q + 3] < glass.mask[q + 3], `tab mask ${tab.mask[q + 3]} vs glass ${glass.mask[q + 3]}`);
  assert.ok(Math.abs(tab.across[q] - 128) <= 2, `tab pull ${tab.across[q]}`);
  // at the rim it does pull
  const rim = at(tab, 2, 35);
  assert.ok(tab.mask[rim + 3] > 100 && Math.abs(tab.across[rim] - 128) > 2, `rim ${tab.mask[rim + 3]} ${tab.across[rim]}`);
});
