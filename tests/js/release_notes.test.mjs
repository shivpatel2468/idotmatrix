// node --test tests/js/*.test.mjs — release notes in Settings → Updates (web/src/lib/notes.ts, R-STU-6).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const { joinContinuations } = await import(new URL("../../web/src/lib/notes.ts", import.meta.url));

test("a bullet's wrapped lines join the bullet", () => {
  const out = joinContinuations([
    "- **Title**",
    "  - Before: to move the panel you had to find the app that had it, then",
    "    Reconnect on the other one.",
    "  - Now: press Use the panel here.",
    "",
    "A paragraph",
  ]);
  assert.deepEqual(out, [
    "- **Title**",
    "  - Before: to move the panel you had to find the app that had it, then Reconnect on the other one.",
    "  - Now: press Use the panel here.",
    "",
    "A paragraph",
  ]);
});

test("headings and plain paragraphs stay their own lines", () => {
  assert.deepEqual(joinContinuations(["- item", "### Fixed", "text"]), ["- item", "### Fixed", "text"]);
});

test("every wrapped line in WHATS_NEW.md lands inside a bullet", () => {
  const lines = readFileSync(new URL("../../WHATS_NEW.md", import.meta.url), "utf8")
    .replace(/<!--[\s\S]*?-->/g, "")
    .split("\n");
  for (const l of joinContinuations(lines)) assert.ok(!/^\s{3,}[^\s\-*]/.test(l), `stray wrapped line: ${l}`);
});
