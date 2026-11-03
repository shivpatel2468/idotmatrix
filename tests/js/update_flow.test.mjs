// node --test tests/js/*.test.mjs — the Updates sheet's live steps and its one primary action
// (web/src/lib/updateFlow.ts; node strips the TypeScript types itself, no build needed).
import assert from "node:assert/strict";
import test from "node:test";
import { flowSteps, primaryAction } from "../../web/src/lib/updateFlow.ts";

const base = {
  kind: "windows",
  status: "idle",
  progress: null,
  lastBusy: null,
  result: null,
  target: "3.10.0",
  current: "3.9.0",
  linkOpen: true,
};
const states = (steps) => steps.map((s) => `${s.id}:${s.state}`).join(" ");

test("nothing to show before Install is pressed", () => {
  assert.equal(flowSteps(base), null);
  assert.equal(flowSteps({ ...base, kind: "source" }), null);
  assert.equal(flowSteps({ ...base, kind: "web" }), null);
});

test("desktop steps follow the engine: download, checksums, install, restart", () => {
  const dl = flowSteps({ ...base, status: "downloading", progress: 0.42, lastBusy: "downloading" });
  assert.equal(states(dl), "download:active verify:todo install:todo restart:todo");
  assert.equal(dl[0].detail, "42%");
  assert.equal(dl[1].label, "Check it against checksums.txt");
  assert.equal(states(flowSteps({ ...base, status: "verifying", lastBusy: "verifying" })), "download:done verify:active install:todo restart:todo");
  assert.equal(states(flowSteps({ ...base, status: "installing", lastBusy: "installing" })), "download:done verify:done install:active restart:todo");
  const restarting = flowSteps({ ...base, lastBusy: "installing", result: "restart", linkOpen: false });
  assert.equal(states(restarting), "download:done verify:done install:done restart:active");
  // the engine still says "installing" until it exits; the installer has it, so the restart is the live step
  const handedOff = flowSteps({ ...base, status: "installing", lastBusy: "installing", result: "restart" });
  assert.equal(states(handedOff), "download:done verify:done install:done restart:active");
  const back = flowSteps({ ...base, lastBusy: "installing", result: "restart", current: "3.10.0" });
  assert.equal(states(back), "download:done verify:done install:done restart:done");
});

test("no percentage is invented when the engine doesn't know the size", () => {
  for (const progress of [null, 0, 1]) {
    const s = flowSteps({ ...base, status: "downloading", progress, lastBusy: "downloading" });
    assert.equal(s[0].detail, undefined);
  }
});

test("a failure lands on the step it happened in", () => {
  assert.equal(states(flowSteps({ ...base, status: "error", lastBusy: "downloading" })), "download:failed verify:todo install:todo restart:todo");
  assert.equal(states(flowSteps({ ...base, status: "error", lastBusy: "verifying" })), "download:done verify:failed install:todo restart:todo");
  assert.equal(states(flowSteps({ ...base, kind: "android", status: "error", lastBusy: "installing", result: "signature" })), "download:done verify:done install:failed");
});

test("Android hands over to its installer; the mac dmg fallback opens the installer", () => {
  const started = flowSteps({ ...base, kind: "android", lastBusy: "installing", result: "started" });
  assert.equal(states(started), "download:done verify:done install:done");
  assert.equal(started[2].label, "Open Android's installer");
  assert.equal(states(flowSteps({ ...base, kind: "android", lastBusy: "installing", result: "permission" })), "download:done verify:done install:failed");
  const opened = flowSteps({ ...base, kind: "macos", lastBusy: "installing", result: "opened" });
  assert.equal(states(opened), "download:done verify:done install:done");
  assert.equal(opened[2].label, "Open the installer");
});

test("the browser app reads version.json, then reloads", () => {
  assert.equal(states(flowSteps({ ...base, kind: "web", reloading: true })), "version:done reload:active");
});

test("one primary action", () => {
  const p = { kind: "windows", available: true, canInstall: true, status: "idle", lastBusy: null, result: null };
  assert.equal(primaryAction(p), "install");
  assert.equal(primaryAction({ ...p, kind: "web", canInstall: false }), "reload");
  assert.equal(primaryAction({ ...p, available: false }), null);
  assert.equal(primaryAction({ ...p, kind: "source", canInstall: false }), null);
  assert.equal(primaryAction({ ...p, status: "downloading" }), null);
  assert.equal(primaryAction({ ...p, status: "checking" }), null);
  assert.equal(primaryAction({ ...p, result: "restart" }), null);
  assert.equal(primaryAction({ ...p, status: "error", lastBusy: "verifying" }), "retry-install");
  assert.equal(primaryAction({ ...p, available: false, status: "error" }), "retry-check");
  // a fresh tab that never saw the failed step still retries the install, not just the check
  assert.equal(primaryAction({ ...p, status: "error" }), "retry-install");
  assert.equal(primaryAction({ ...p, kind: "web", canInstall: false, status: "error" }), "retry-check");
  assert.equal(primaryAction({ ...p, kind: "android", result: "permission" }), "install");
});
