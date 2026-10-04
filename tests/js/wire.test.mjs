// node --test tests/js/*.test.mjs — the data-channel wire format shared by host-rtc.js and the join page (host-rtc-wire.js).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// a classic browser script: run it in a context with the globals it uses
const src = readFileSync(new URL("../../web/webapp/host-rtc-wire.js", import.meta.url), "utf8");
// (this realm's JSON and typed arrays, so results compare with deepEqual)
const ctx = { TextEncoder, TextDecoder, btoa, atob, crypto, setTimeout, clearTimeout, AbortController, JSON, Uint8Array, ArrayBuffer, Object, fetch: async () => ({}) };
ctx.globalThis = ctx;
vm.runInNewContext(src, ctx);
const W = ctx.DeskDotWire;

test("small envelopes are one text message", () => {
  const f = W.frames({ t: "ws-send", id: 3, d: "hello" });
  assert.equal(f.length, 1);
  assert.equal(typeof f[0], "string");
  assert.deepEqual(W.assembler()(f[0]), { t: "ws-send", id: 3, d: "hello" });
});

test("large envelopes are split into ≤ 16 KB parts and reassembled", () => {
  const body = new Uint8Array(200_000).map((_, i) => (i * 7) & 255);
  const env = { t: "res", id: 9, s: 200, h: [["content-type", "text/html"]], b: W.b64(body), note: "é✓ unicode" };
  const parts = W.frames(env);
  assert.ok(parts.length > 10);
  for (const p of parts) assert.ok(p.byteLength <= W.MAX_MSG, "fits a data-channel message");
  const push = W.assembler();
  let out = null;
  parts.forEach((p, i) => {
    out = push(p);
    if (i < parts.length - 1) assert.equal(out, null);
  });
  assert.deepEqual(JSON.parse(JSON.stringify(out)), env);
  assert.deepEqual(new Uint8Array(W.unb64(out.b)), body);
  // the assembler is ready for the next envelope
  assert.deepEqual(push(W.frames({ t: "hello", v: 1 })[0]), { t: "hello", v: 1 });
});

test("garbage is refused", () => {
  assert.throws(() => W.assembler()(new Uint8Array([7, 1, 2]).buffer));
  assert.throws(() => W.assembler(100)(new Uint8Array(500).buffer), /too large/);
  const push = W.assembler();
  push(new Uint8Array([1, 123]).buffer); // a part with "more follows"
  assert.throws(() => push('{"t":"x"}'), /inside a split envelope/);
});

test("ids and base64", () => {
  assert.match(W.randomId(20), /^[a-z0-9]{20}$/);
  assert.match(W.randomHex(24), /^[a-f0-9]{48}$/);
  assert.equal(W.b64(new TextEncoder().encode("DeskDot")), "RGVza0RvdA==");
  assert.equal(W.utf8(W.unb64("RGVza0RvdA==")), "DeskDot");
});
