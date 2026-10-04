// node --test tests/js/*.test.mjs — the web app's read-only CORS fallback (netlify/functions/cors-proxy.mjs), no Netlify needed.
import assert from "node:assert/strict";
import test from "node:test";
import handler from "../../netlify/functions/cors-proxy.mjs";

const realFetch = globalThis.fetch;
let seen = [];
// fake upstreams: a redirect off the list, a redirect on the same host, and plain answers
function fakeFetch(u) {
  u = new URL(u);
  seen.push(u.href);
  if (u.pathname === "/off-list") return new Response(null, { status: 302, headers: { location: "https://evil.example/x" } });
  if (u.pathname === "/same-host") return new Response(null, { status: 301, headers: { location: "/final" } });
  if (u.pathname === "/loop") return new Response(null, { status: 302, headers: { location: "/loop" } });
  return new Response("ok", { status: 200, headers: { "content-type": "text/plain", "set-cookie": "a=b" } });
}
const call = (url, method = "GET") =>
  handler(new Request("https://idotmatrix.com/app/proxy?url=" + encodeURIComponent(url), { method }));

test.beforeEach(() => {
  seen = [];
  globalThis.fetch = fakeFetch;
});
test.after(() => {
  globalThis.fetch = realFetch;
});

test("only allowlisted hosts, GET only, no credentials in the URL", async () => {
  assert.equal((await call("https://evil.example/")).status, 403);
  assert.equal((await call("https://ntfy.sh/x", "POST")).status, 405);
  assert.equal((await call("https://user:pw@ntfy.sh/x")).status, 403);
  assert.equal((await call("file:///etc/passwd")).status, 403);
  assert.equal((await call("https://p52-caldav.icloud.com.evil.example/x")).status, 403);
  assert.deepEqual(seen, []);
});

test("allowed hosts answer, marked and without cookies", async () => {
  for (const url of ["https://images.metmuseum.org/a.jpg", "https://p52-caldav.icloud.com/published/2/x", "http://ip-api.com/json/"]) {
    const r = await call(url);
    assert.equal(r.status, 200, url);
    assert.equal(r.headers.get("x-deskdot-proxy"), "1");
    assert.equal(r.headers.get("set-cookie"), null);
  }
});

test("redirects are followed only while they stay on the allowlist", async () => {
  assert.equal((await call("https://www.cheapshark.com/off-list")).status, 403);
  assert.deepEqual(seen, ["https://www.cheapshark.com/off-list"]); // evil.example never fetched
  const r = await call("https://lobste.rs/same-host");
  assert.equal(r.status, 200);
  assert.equal(await r.text(), "ok");
  assert.equal((await call("https://lobste.rs/loop")).status, 502);
});
