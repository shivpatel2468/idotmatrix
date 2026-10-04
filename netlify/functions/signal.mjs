// idotmatrix.com/app/signal — WebRTC signalling for "play with friends over the internet" (docs/WEB_APP.md).
//
// A phone that scans the join QR of a game running in someone's web-app tab swaps one offer/answer with that tab
// through here; then they talk peer-to-peer (host-rtc.js ↔ join.js). The logic and every check live in
// netlify/lib/signal-core.mjs (tested in tests/js/signal_core.test.mjs); this file only wires it to Netlify Blobs.
// Not a relay: SDP-shaped text only, ≤ 16 KB, per room code, readable only by the tab that registered the room.

import { getStore } from "@netlify/blobs";
import { BadRequest, handle, parseRequest, sweep } from "../lib/signal-core.mjs";

const HEADERS = { "content-type": "application/json", "cache-control": "no-store" };
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: HEADERS });

function blobStore() {
  const s = getStore({ name: "deskdot-signal", consistency: "strong" });
  return {
    get: (k) => s.get(k, { type: "json" }),
    set: (k, v) => s.setJSON(k, v),
    delete: (k) => s.delete(k),
    list: async (prefix) => (await s.list({ prefix })).blobs.map((b) => b.key),
  };
}

export default async (req) => {
  if (req.method !== "POST") return json(405, { error: "POST only" });
  const type = req.headers.get("content-type") || "";
  if (!type.startsWith("application/json") && !type.startsWith("text/plain")) return json(415, { error: "json only" });
  let parsed;
  try {
    parsed = parseRequest(await req.text());
  } catch (e) {
    if (e instanceof BadRequest) return json(e.status, { error: e.message });
    throw e;
  }
  const store = blobStore();
  try {
    const [status, body] = await handle(parsed, store);
    // now and then, clear rooms whose host tab vanished without saying goodbye
    if (parsed.op === "close" || Math.random() < 0.01) await sweep(store).catch(() => {});
    return json(status, body);
  } catch (e) {
    return json(503, { error: "signal store unavailable", detail: String(e).slice(0, 200) });
  }
};

export const config = { path: "/app/signal" };
