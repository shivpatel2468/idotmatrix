// node --test tests/js/*.test.mjs — the phone layout's alignment rules (web/SPEC.md R-STU-13). The studio has no
// component test runner, so this pins the CSS and markup that keep every phone screen inside its width; the screens
// themselves were measured at 360, 393 and 430 px (no element wider than the screen, no sideways scroll).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (p) => readFileSync(new URL(`../../web/src/${p}`, import.meta.url), "utf8");
const css = read("index.css");
const rule = (sel) => {
  const i = css.indexOf(`${sel} {`);
  assert.ok(i >= 0, `no rule for ${sel}`);
  return css.slice(i, css.indexOf("}", i));
};

test("the phone has one 16 px side gutter, used by every edge that touches the screen", () => {
  assert.match(css, /--gutter:\s*16px;/);
  for (const sel of [".phone-scroll", ".lib-head", ".insp-actions", ".phone-stage", ".rail", ".rail-track", ".theme-fab"]) {
    assert.match(rule(sel), /var\(--gutter\)/, `${sel} must use var(--gutter)`);
    assert.doesNotMatch(rule(sel), /\b12px\b/, `${sel} still has the old 12 px gutter`);
  }
  assert.match(read("components/TopBar.tsx"), /phone-head[^"]*px-\[var\(--gutter\)\]/);
});

test("on phones a segmented control shrinks to its row and wraps between words", () => {
  const start = css.search(/@media \(max-width: 767\.98px\) \{\s+input:not/);
  assert.ok(start >= 0, "no phones block");
  const phones = css.slice(start);
  const block = phones.slice(0, phones.search(/\r?\n\}\r?\n/));
  assert.match(block, /\.seg \{[^}]*max-width: 100%[^}]*min-width: 0/);
  assert.match(block, /\.seg > button \{[^}]*white-space: normal/);
  assert.doesNotMatch(block, /overflow-wrap: anywhere/, "labels must not break inside a word");
});

test("a settings row never lets its controls run off the screen", () => {
  assert.match(read("components/controls.tsx"), /row-ctl flex min-w-0 max-w-full flex-wrap/);
});

test("the Settings search is as tall as the section keys beside it and centred with them", () => {
  const s = read("components/Settings.tsx");
  const nav = s.slice(s.indexOf('aria-label="Settings sections"') - 400, s.indexOf("</nav>"));
  assert.match(nav, /flex shrink-0 items-center gap-1/);
  assert.match(nav, /aria-label="Search settings" className="field !h-12/); // 48 px
  assert.match(nav, /py-2\.5/); // the keys: 10 + 28 + 10 = 48 px
  assert.match(nav, /size=\{28\}/);
});

test("the Apps search stretches to the view toggle's height on phones", () => {
  const s = read("components/Library.tsx");
  assert.match(s, /flat \? "items-stretch" : "items-center"/);
  assert.match(s, /flat \? "!h-auto" : "!h-9"/);
});

test("the message composer stacks Style and Seconds on phones", () => {
  assert.match(read("components/Overlays.tsx"), /grid grid-cols-1 gap-3 sm:grid-cols-2/);
});
