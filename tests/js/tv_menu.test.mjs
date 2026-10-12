// node --test tests/js/tv_menu.test.mjs — the TV options menu in a real (headless) Chrome: every tile answers a mouse
// click, a touch tap, the keyboard (arrows, Enter, Space, Escape) and a TV remote (D-pad centre, Back), and the
// casino table's Dolly / Chips tiles send the one narrow `house` message (docs/TV_VIEW.md §2).
//
// Needs playwright-core and a Chrome: found from this repo, or PLAYWRIGHT_DIR (a folder whose node_modules has
// playwright-core) and CHROME (the browser's path). Skipped when either is missing (CI without a browser).
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import test from "node:test";

const REPO = new URL("../../", import.meta.url);
const SRC = new URL("src/deskdot/", REPO);
const CAS = JSON.parse(readFileSync(new URL("tests/js/fixtures/casino_status.json", REPO), "utf8"));
const CHROME = process.env.CHROME || ["C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].find((p) => existsSync(p));

function playwright() {
  for (const base of [process.env.PLAYWRIGHT_DIR, new URL(".", REPO).pathname.replace(/^\/([A-Za-z]:)/, "$1"), join(new URL(".", REPO).pathname, "web")].filter(Boolean)) {
    try {
      return createRequire(join(base, "package.json"))("playwright-core");
    } catch {
      /* next */
    }
  }
  return null;
}
const pw = playwright();
const skip = !pw || !CHROME ? "needs playwright-core (PLAYWRIGHT_DIR) and Chrome (CHROME)" : false;

async function openTv(theme = "dark") {
  const browser = await pw.chromium.launch({ executablePath: CHROME, headless: true });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, hasTouch: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("http://tv.test/**", (route) => {
    const u = new URL(route.request().url());
    const name = u.pathname.split("/").pop();
    if (u.pathname.startsWith("/tv/static/"))
      return route.fulfill({ body: readFileSync(new URL(`tv/${name}`, SRC)), contentType: name.endsWith(".woff2") ? "font/woff2" : "text/javascript" });
    return route.fulfill({ body: readFileSync(new URL("tv.html", SRC)), contentType: "text/html" });
  });
  const status = JSON.parse(JSON.stringify(CAS.statuses.casino_roulette[1]));
  status.table_theme = CAS.statuses.casino_roulette.find((s) => s.table_theme).table_theme;
  const sent = [];
  const state = () => JSON.stringify({ type: "state", app: "casino_roulette", status, lobby: null, tv: null, display: { look: null, quality: null, rev: null }, server_time: Date.now() / 1000 });
  await page.routeWebSocket("ws://tv.test/ws/tv/ABCD", (ws) => {
    ws.onMessage((m) => {
      const j = JSON.parse(String(m));
      if (j.type === "ping") return ws.send(JSON.stringify({ type: "pong", t: j.t, server_time: Date.now() / 1000 }));
      sent.push(j);
      if (j.type === "house") {
        const k = "dolly" in j ? "dolly" : "chip_set";
        status.house = { ...status.house, [k]: j[k] }; // the engine takes it and every screen gets the new status
        ws.send(JSON.stringify({ type: "house_ok", [k]: j[k] }));
        ws.send(state());
      }
    });
    ws.send(JSON.stringify({ type: "hello", app: "casino_roulette", meta: { id: "casino_roulette", name: "Roulette", category: "casino" }, avatars: {}, display: { look: null, quality: null, rev: null }, server_time: Date.now() / 1000 }));
    ws.send(state());
  });
  await page.goto(`http://tv.test/tv/ABCD?theme=${theme}`);
  await page.waitForFunction(() => window.TV && TV.ctx && TV.ctx.status && TV.ctx.status.house);
  return { browser, page, errors, sent };
}

const tile = (page, key, v) => page.locator(`#tv-menu .tvm-row[aria-label] .tvm-opt[data-key="${key}"][data-v="${v}"]`);
const now = (page) => page.evaluate(() => ({ look: TV.look, quality: TV.qualityMode, theme: TV.theme, open: !document.getElementById("tv-menu").hidden }));
const checked = (page, key, v) => tile(page, key, v).getAttribute("aria-checked");

test("every tile works with a mouse click, at once, with the chosen one marked", { skip, timeout: 60000 }, async () => {
  const { browser, page, errors, sent } = await openTv("dark");
  try {
    await page.mouse.click(700, 500); // a click anywhere opens the menu
    await page.waitForSelector("#tv-menu.on");
    for (const [key, values, prop] of [["look", ["pixel", "glow", "led"], "look"], ["quality", ["lite", "hq", "auto"], "quality"], ["theme", ["light", "dark"], "theme"]]) {
      for (const v of values) {
        await tile(page, key, v).click();
        assert.equal((await now(page))[prop], v, `${key} → ${v}`);
        assert.equal(await checked(page, key, v), "true");
      }
    }
    assert.equal(await page.evaluate(() => localStorage.getItem("deskdot.tv.look")).then((s) => JSON.parse(s).v), "led", "remembered on this TV");
    // the house's rows: a click sends {type: "house", key: value} and the tile is marked when the table says so
    for (const [key, v] of [["dolly", "crystal"], ["dolly", "neon"], ["chip_set", "jade"], ["chip_set", "auto"]]) {
      await tile(page, key, v).click();
      await page.waitForFunction(([k, val]) => TV.ctx.status.house[k] === val, [key, v]);
      assert.deepEqual(sent.at(-1), { type: "house", [key]: v });
      assert.equal(await checked(page, key, v), "true");
    }
    assert.ok(sent.every((m) => m.type === "house" && Object.keys(m).length === 2), "a TV sends nothing else");
    await page.mouse.click(30, 1060); // outside the card: closes
    await page.waitForFunction(() => document.getElementById("tv-menu").hidden);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});

test("a touch tap picks, the keyboard and a TV remote move, pick and close", { skip, timeout: 60000 }, async () => {
  const { browser, page, errors } = await openTv("light");
  try {
    await page.touchscreen.tap(900, 500); // a tap opens
    await page.waitForSelector("#tv-menu.on");
    const box = await tile(page, "look", "pixel").boundingBox();
    await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    assert.equal((await now(page)).look, "pixel", "a tap picks");
    // keyboard: the highlight starts on the current look; → Enter picks LED, → Space picks Glow
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.getElementById("tv-menu").hidden);
    await page.keyboard.press("Enter");
    await page.waitForSelector("#tv-menu.on");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter");
    assert.equal((await now(page)).look, "led");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press(" ");
    assert.equal((await now(page)).look, "glow");
    // ↓ ↓ to Theme, ← picks Dark with Enter
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("Enter");
    assert.equal((await now(page)).theme, "dark");
    // a TV remote: D-pad centre (keyCode 23) picks, Back (keyCode 4) closes
    await page.keyboard.press("ArrowRight");
    await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Unidentified", keyCode: 23, bubbles: true, cancelable: true })));
    assert.equal((await now(page)).theme, "light", "OK on a remote");
    await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "GoBack", keyCode: 4, bubbles: true, cancelable: true })));
    await page.waitForFunction(() => document.getElementById("tv-menu").hidden);
    assert.equal((await now(page)).open, false, "Back closes");
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
