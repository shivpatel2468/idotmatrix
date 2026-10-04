// idotmatrix.com/app/proxy?url=… — a read-only CORS fallback for the DeskDot web app (docs/WEB_APP.md).
//
// The engine runs in the browser, so every data source is fetched by the page and needs CORS. Most public APIs the
// apps use allow it; the few below don't (or are plain http, which an https page may not fetch). The web app tries
// each request directly first and only falls back here. This is NOT an open proxy: GET only, an allowlist of the
// exact API hosts DeskDot's providers use, no cookies or auth forwarded, and a 3 MB cap. Redirects are followed
// only while they stay on allowed hosts. tests/test_web_apps.py checks every provider host is either CORS-friendly
// or listed here (and that this list stays an exact-host allowlist).

const ALLOW = new Set([
  "ip-api.com", // IP geolocation (http only on the free tier)
  "api.open-notify.org", // astronauts (http only)
  "query1.finance.yahoo.com",
  "query2.finance.yahoo.com",
  "stooq.com",
  "zenquotes.io",
  "lobste.rs",
  "hacker-news.firebaseio.com",
  "api.adsb.lol",
  "api.airplanes.live",
  "opensky-network.org",
  "random-d.uk",
  "openaccess-api.clevelandart.org",
  "openaccess-cdn.clevelandart.org", // Cleveland Museum artwork images (the API allows CORS, its CDN doesn't)
  "images.metmuseum.org", // Met Museum artwork images (same)
  "www.cheapshark.com",
  "api.binance.com",
  "site.api.espn.com",
  "site.web.api.espn.com",
  "earthquake.usgs.gov",
  "tilecache.rainviewer.com",
  "api.mojang.com",
  "github.com",
  "ntfy.sh",
  "calendar.google.com",
  "outlook.office365.com", // published Outlook / Microsoft 365 calendars (.ics)
  "outlook.live.com", // published Outlook.com calendars (.ics)
  "lrclib.net",
  "api.chess.com",
  "api.wikimedia.org",
]);
// published iCloud calendars live on numbered hosts (webcal://p52-caldav.icloud.com/published/2/…)
const ALLOW_PATTERNS = [/^p\d{1,3}-(caldav|calendars)\.icloud\.com$/];
const allowed = (host) => ALLOW.has(host) || ALLOW_PATTERNS.some((re) => re.test(host));
const MAX_REDIRECTS = 4;
const MAX_BYTES = 3 * 1024 * 1024;
// response headers worth passing on; everything else (cookies, CSP, HSTS…) is dropped
const PASS = ["content-type", "cache-control", "etag", "last-modified"];

export default async (req) => {
  if (req.method !== "GET") return new Response("GET only", { status: 405 });
  const raw = new URL(req.url).searchParams.get("url") || "";
  let target;
  try {
    target = new URL(raw);
  } catch {
    return new Response("bad url", { status: 400 });
  }
  const ok = (u) => /^https?:$/.test(u.protocol) && !u.username && !u.password && allowed(u.hostname);
  if (!ok(target)) return new Response(`host not allowed: ${target.hostname}`, { status: 403 });
  let upstream;
  try {
    const signal = AbortSignal.timeout(12000);
    for (let hop = 0; ; hop++) {
      upstream = await fetch(target, {
        headers: { "user-agent": "DeskDot-web/3 (+https://idotmatrix.com/app/)", accept: req.headers.get("accept") || "*/*" },
        redirect: "manual", // follow by hand: a redirect must not lead off the allowlist
        signal,
      });
      const loc = upstream.status >= 300 && upstream.status < 400 && upstream.headers.get("location");
      if (!loc) break;
      if (hop >= MAX_REDIRECTS) return new Response("too many redirects", { status: 502 });
      target = new URL(loc, target);
      if (!ok(target)) return new Response(`redirect to a host not allowed: ${target.hostname}`, { status: 403 });
    }
  } catch (e) {
    return new Response(`upstream failed: ${e}`, { status: 502 });
  }
  const body = await upstream.arrayBuffer();
  if (body.byteLength > MAX_BYTES) return new Response("response too large", { status: 502 });
  const headers = new Headers({ "x-deskdot-proxy": "1" });
  for (const h of PASS) {
    const v = upstream.headers.get(h);
    if (v) headers.set(h, v);
  }
  if (!headers.has("cache-control")) headers.set("cache-control", "public, max-age=30");
  return new Response(body, { status: upstream.status, headers });
};

export const config = { path: "/app/proxy" };
