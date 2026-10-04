// idotmatrix.com/app/signal — WebRTC signalling for "play with friends over the internet" (docs/WEB_APP.md).
//
// A phone that scans the join QR of a game running in someone's web-app tab swaps one offer/answer with that tab
// through here; then they talk peer-to-peer (host-rtc.js ↔ join.js). The logic and every check live in
// netlify/lib/signal-core.mjs (tested in tests/js/signal_core.test.mjs); this file only wires it to Netlify Blobs.
// Not a relay: SDP-shaped text only, ≤ 16 KB, per room code, readable only by the tab that registered the room.

import { getStore } from "@netlify/blobs";
import { BadRequest, handle, parseRequest, sweep } from "../lib/signal-core.mjs";

// Relay (TURN) for networks that block a direct link (mobile carriers' shared addresses, routers that won't loop
// back): short-lived credentials, handed out only to a live room. Cloudflare Realtime TURN (free tier) when
// CF_TURN_KEY_ID + CF_TURN_API_TOKEN are set in the site's environment; else a static TURN_URLS (comma separated) +
// TURN_USERNAME + TURN_CREDENTIAL; else none (direct links only).
const STUN = { urls: ["stun:stun.cloudflare.com:3478", "stun:stun.l.google.com:19302"] };
const env = (k) => (globalThis.Netlify && Netlify.env.get(k)) || process.env[k] || "";

async function iceServers() {
  const keyId = env("CF_TURN_KEY_ID");
  const token = env("CF_TURN_API_TOKEN");
  if (keyId && token) {
    const r = await fetch(`https://rtc.live.cloudflare.com/v1/turn/keys/${encodeURIComponent(keyId)}/credentials/generate-ice-servers`, {
      method: "POST",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: JSON.stringify({ ttl: 6 * 3600 }),
    });
    if (r.ok) {
      const data = await r.json();
      const list = Array.isArray(data.iceServers) ? data.iceServers : data.iceServers ? [data.iceServers] : [];
      // Cloudflare lists :53 too, which browsers refuse to dial and then report as an error: drop those
      const clean = list.map((s) => ({ ...s, urls: [].concat(s.urls).filter((u) => !/:53(\?|$)/.test(u)) })).filter((s) => s.urls.length);
      if (clean.length) return { iceServers: [STUN, ...clean], relay: "cloudflare" };
    }
  }
  const urls = env("TURN_URLS").split(",").map((u) => u.trim()).filter(Boolean);
  if (urls.length && env("TURN_USERNAME") && env("TURN_CREDENTIAL")) {
    return { iceServers: [STUN, { urls, username: env("TURN_USERNAME"), credential: env("TURN_CREDENTIAL") }], relay: "static" };
  }
  return { iceServers: [STUN], relay: null };
}

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
    if (parsed.op === "ice" && status === 200) return json(200, await iceServers().catch(() => ({ iceServers: [STUN], relay: null })));
    // now and then, clear rooms whose host tab vanished without saying goodbye
    if (parsed.op === "close" || Math.random() < 0.01) await sweep(store).catch(() => {});
    return json(status, body);
  } catch (e) {
    return json(503, { error: "signal store unavailable", detail: String(e).slice(0, 200) });
  }
};

export const config = { path: "/app/signal" };
