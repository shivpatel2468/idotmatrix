/* DeskDot web app — service worker (scope /app/; docs/WEB_APP.md).
 *
 * 1. Routes requests for the engine's /api/* that the page's fetch shim can't see (<img src="/api/…">, previews)
 *    to the page, which hands them to the engine worker. App library thumbnails come from the site's prebuilt
 *    reels (/media/apps/<id>.gif) so the in-browser engine isn't busy rendering 90 GIFs.
 * 2. Caches the Pyodide runtime (pinned CDN version), the engine archive and the studio, so a second visit
 *    starts without downloading anything and the app opens offline.
 */
"use strict";

const BUILD = "46cdecc7912e"; // replaced by scripts/build_webapp.py
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/";
const APP_CACHE = `deskdot-app-${BUILD}`;
const RUNTIME_CACHE = `deskdot-pyodide-${PYODIDE.split("/").filter(Boolean).slice(-2).join("-")}`;
const SCOPE = new URL("./", self.location.href);

self.addEventListener("install", (e) => {
  // the shell, so an offline second visit still opens; everything else is cached as it's first used
  e.waitUntil(
    caches
      .open(APP_CACHE)
      .then((c) => c.addAll(["./", "host/host.js", "host/host.css", "engine/worker.js", "engine/manifest.json"].map((p) => new URL(p, SCOPE).href)))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("deskdot-") && k !== APP_CACHE && k !== RUNTIME_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function viaPage(event, req) {
  let client = event.clientId ? await self.clients.get(event.clientId) : null;
  if (!client || client.type !== "window") {
    const all = await self.clients.matchAll({ type: "window" });
    client = all.find((c) => c.url.startsWith(SCOPE.href)) || null;
  }
  if (!client) return new Response("DeskDot engine isn't running (open /app/)", { status: 503 });
  const url = new URL(req.url);
  const body = ["GET", "HEAD"].includes(req.method) ? null : await req.arrayBuffer();
  const ch = new MessageChannel();
  const reply = new Promise((resolve) => {
    ch.port1.onmessage = (m) => resolve(m.data);
    setTimeout(() => resolve({ status: 504, headers: [], body: null }), 60000);
  });
  client.postMessage({ t: "sw-api", method: req.method, path: url.pathname + url.search, headers: [...req.headers], body }, [ch.port2]);
  const r = await reply;
  const nullBody = [101, 103, 204, 205, 304].includes(r.status);
  return new Response(nullBody ? null : r.body, { status: r.status, headers: r.headers });
}

async function cacheFirst(cacheName, req) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok || res.type === "opaque") cache.put(req, res.clone()).catch(() => undefined);
  return res;
}

async function networkFirst(req) {
  const cache = await caches.open(APP_CACHE);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone()).catch(() => undefined);
    return res;
  } catch (e) {
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    throw e;
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) {
    const m = req.method === "GET" && url.pathname.match(/^\/api\/apps\/([\w-]+)\/preview\.gif$/);
    if (m) {
      event.respondWith(
        cacheFirst(APP_CACHE, new Request(`/media/apps/${m[1]}.gif`)).then((r) => (r.ok ? r : viaPage(event, req)), () => viaPage(event, req)),
      );
    } else {
      event.respondWith(viaPage(event, req));
    }
    return;
  }
  if (req.method !== "GET") return;
  if (req.url.startsWith(PYODIDE)) return event.respondWith(cacheFirst(RUNTIME_CACHE, req));
  if (url.origin !== self.location.origin || !url.pathname.startsWith(SCOPE.pathname)) return;
  if (url.pathname === SCOPE.pathname + "proxy") return; // live data: never cached here
  // content-hashed files never change: the studio's assets, the engine archive and vendored wheels
  if (/\/assets\/|\/engine\/.+\.(zip|whl)$/.test(url.pathname)) return event.respondWith(cacheFirst(APP_CACHE, req));
  event.respondWith(networkFirst(req));
});
