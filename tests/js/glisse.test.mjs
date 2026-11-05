// node --test tests/js/*.test.mjs — the phone app's glass after Glisse (web/src/lib/glisse.ts, R-STU-14).
import assert from "node:assert/strict";
import test from "node:test";

const g = await import(new URL("../../web/src/lib/glisse.ts", import.meta.url));

const at = (m, x, y) => (y * m.cols + x) * 4;

test("the lens leaves the middle alone and pulls from further in near the rim", () => {
  const m = g.lensPixels({ w: 360, h: 64, r: 30 }, 1);
  const mid = at(m, 180, 32);
  assert.ok(Math.abs(m.across[mid] - 128) <= 1 && Math.abs(m.down[mid] - 128) <= 1, "no pull in the middle");
  // near the left rim the pull is across (grey off 128) and the mask covers
  const left = at(m, 6, 32);
  assert.ok(m.mask[left + 3] > 200, `left rim mask ${m.mask[left + 3]}`);
  assert.ok(Math.abs(m.across[left] - 128) > 10, `left rim pull ${m.across[left]}`);
  // the two sides pull in opposite directions
  const right = at(m, 353, 32);
  assert.ok(Math.sign(m.across[left] - 128) === -Math.sign(m.across[right] - 128));
  // outside the rounded corner: no pull, no mask
  const corner = at(m, 0, 0);
  assert.equal(m.across[corner], 128);
  assert.equal(m.mask[corner + 3], 0);
});

test("the maps are drawn at the device's density", () => {
  const m = g.lensPixels({ w: 80, h: 50, r: 24 }, 2);
  assert.equal(m.cols, 160);
  assert.equal(m.rows, 100);
  assert.equal(m.across.length, 160 * 100 * 4);
});

test("the rim light is a thin line lit on the straight sides, dark on the top-right and bottom-left corners", () => {
  const s = { w: 200, h: 60, r: 30 };
  const m = g.rimPixels(s, 0.5, 1);
  const a = (x, y) => m.data[(y * m.cols + x) * 4 + 3];
  assert.ok(a(100, 0) > 60, `top edge ${a(100, 0)}`);
  assert.ok(a(100, 59) > 60, `bottom edge ${a(100, 59)}`);
  assert.equal(a(100, 30), 0, "nothing inside");
  assert.equal(a(100, 4), 0, "gone a few px in");
  // the corner arcs facing the light (top-left) are lit, the ones between are not
  const tl = a(9, 9), tr = a(190, 9);
  assert.ok(tl > tr, `top-left ${tl} vs top-right ${tr}`);
});

test("the rim's strength follows the shine", () => {
  const s = { w: 120, h: 40, r: 12 };
  const lo = g.rimPixels(s, 0.2, 1).data[(0 * 120 + 60) * 4 + 3];
  const hi = g.rimPixels(s, 0.45, 1).data[(0 * 120 + 60) * 4 + 3];
  assert.ok(hi > lo && lo > 0, `${lo} → ${hi}`);
});
