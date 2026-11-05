// node --test tests/js/*.test.mjs — Android's Back button in the phone studio (web/src/lib/backStep.ts)
import assert from "node:assert/strict";
import test from "node:test";
import { backStep } from "../../web/src/lib/backStep.ts";

test("Back closes what is open on top first, on any tab", () => {
  for (const tab of ["panel", "apps", "play", "tune"]) assert.equal(backStep(true, tab), "close");
});

test("Back from Apps, Presets or Settings goes to the Panel tab instead of leaving the app", () => {
  assert.equal(backStep(false, "tune"), "panel");
  assert.equal(backStep(false, "apps"), "panel");
  assert.equal(backStep(false, "play"), "panel");
});

test("Back on the Panel tab with nothing open leaves (the app keeps running)", () => {
  assert.equal(backStep(false, "panel"), "leave");
});
