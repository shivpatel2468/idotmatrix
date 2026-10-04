// node --test tests/js/*.test.mjs — the signalling logic behind /app/signal (netlify/lib/signal-core.mjs), no Netlify needed.
import assert from "node:assert/strict";
import test from "node:test";
import {
  ANSWER_TTL_MS,
  BadRequest,
  MAX_PENDING,
  ROOM_TTL_MS,
  handle,
  memoryStore,
  parseRequest,
  sweep,
  validCode,
  validSdp,
} from "../../netlify/lib/signal-core.mjs";

const SDP = "v=0\r\no=- 46117 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\na=group:BUNDLE 0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\nc=IN IP4 0.0.0.0\r\na=candidate:1 1 udp 2122260223 192.168.1.4 50000 typ host\r\n";
const SECRET = "a".repeat(48);
const OTHER = "b".repeat(48);
const req = (o) => parseRequest(JSON.stringify(o));

test("validation", () => {
  assert.ok(validCode("AB12") && !validCode("ab1") && !validCode("ABCDE") && !validCode("A/B1"));
  assert.ok(validSdp(SDP));
  assert.ok(!validSdp("hello world, not an sdp at all"));
  assert.ok(!validSdp("v=0\r\n" + "x".repeat(40)), "every line is x=…");
  assert.ok(!validSdp("v=0\r\no=a\r\ns=-\r\nt=0 0\r\na=é\r\n"), "ASCII only");
  assert.ok(!validSdp("v=0\r\n" + "a=x\r\n".repeat(4000)), "16 KB cap");
  assert.equal(req({ op: "poll", code: "ab12", secret: SECRET }).code, "AB12", "codes are case-insensitive");
  for (const bad of [
    { op: "poll", code: "AB12" }, // no secret
    { op: "poll", code: "AB12", secret: "short" },
    { op: "offer", code: "AB12", peer: "x", sdp: SDP },
    { op: "offer", code: "AB12", peer: "phone-peer-1", sdp: "nope" },
    { op: "relay", code: "AB12" },
    { op: "wait", code: "../x", peer: "phone-peer-1" },
  ]) {
    assert.throws(() => req(bad), BadRequest, JSON.stringify(bad));
  }
  assert.throws(() => parseRequest("{not json"), BadRequest);
  assert.throws(() => parseRequest("[]"), BadRequest);
  assert.throws(() => parseRequest("x".repeat(30000)), (e) => e.status === 413);
});

test("one handshake: offer → poll → answer → wait", async () => {
  const s = memoryStore();
  const t = 1_000_000;
  // a phone can't knock on a room nobody opened
  assert.equal((await handle(req({ op: "offer", code: "AB12", peer: "phone-peer-1", sdp: SDP }), s, t))[0], 404);
  // the host tab registers the room by polling
  let [st, body] = await handle(req({ op: "poll", code: "AB12", secret: SECRET }), s, t);
  assert.equal(st, 200);
  assert.deepEqual(body.offers, []);
  // another tab can't take or read it
  assert.equal((await handle(req({ op: "poll", code: "AB12", secret: OTHER }), s, t))[0], 403);
  assert.equal((await handle(req({ op: "close", code: "AB12", secret: OTHER }), s, t))[0], 403);
  // phone offers, host picks it up exactly once
  assert.equal((await handle(req({ op: "offer", code: "AB12", peer: "phone-peer-1", sdp: SDP }), s, t + 10))[0], 200);
  [st, body] = await handle(req({ op: "wait", code: "AB12", peer: "phone-peer-1" }), s, t + 20);
  assert.deepEqual(body, { pending: true });
  [st, body] = await handle(req({ op: "poll", code: "AB12", secret: SECRET }), s, t + 2000);
  assert.deepEqual(body.offers, [{ peer: "phone-peer-1", sdp: SDP }]);
  assert.deepEqual((await handle(req({ op: "poll", code: "AB12", secret: SECRET }), s, t + 4000))[1].offers, []);
  // host answers; the phone reads it once
  assert.equal((await handle(req({ op: "answer", code: "AB12", secret: SECRET, peer: "phone-peer-1", sdp: SDP }), s, t + 4100))[0], 200);
  assert.equal((await handle(req({ op: "answer", code: "AB12", secret: OTHER, peer: "phone-peer-1", sdp: SDP }), s, t + 4100))[0], 403);
  [st, body] = await handle(req({ op: "wait", code: "AB12", peer: "phone-peer-1" }), s, t + 5000);
  assert.deepEqual(body, { sdp: SDP });
  assert.deepEqual((await handle(req({ op: "wait", code: "AB12", peer: "phone-peer-1" }), s, t + 6000))[1], { pending: true });
  // the host closes the lobby: everything goes
  assert.equal((await handle(req({ op: "close", code: "AB12", secret: SECRET }), s, t + 7000))[0], 200);
  assert.equal(s.m.size, 0);
  assert.equal((await handle(req({ op: "wait", code: "AB12", peer: "phone-peer-1" }), s, t + 8000))[0], 404);
});

test("expiry, refresh, limits", async () => {
  const s = memoryStore();
  const t = 5_000_000;
  await handle(req({ op: "poll", code: "ZZ99", secret: SECRET }), s, t);
  // polling keeps the room alive past its first TTL
  await handle(req({ op: "poll", code: "ZZ99", secret: SECRET }), s, t + ROOM_TTL_MS - 1000);
  assert.equal((await handle(req({ op: "wait", code: "ZZ99", peer: "phone-peer-1" }), s, t + ROOM_TTL_MS + 1000))[0], 200);
  // pending offers are capped per room
  for (let i = 0; i < MAX_PENDING; i++) {
    const r = await handle(req({ op: "offer", code: "ZZ99", peer: `phone-peer-${i}x`, sdp: SDP }), s, t + ROOM_TTL_MS);
    assert.equal(r[0], 200);
  }
  assert.equal((await handle(req({ op: "offer", code: "ZZ99", peer: "phone-peer-over", sdp: SDP }), s, t + ROOM_TTL_MS))[0], 429);
  // an old answer isn't handed out
  await handle(req({ op: "answer", code: "ZZ99", secret: SECRET, peer: "phone-peer-late", sdp: SDP }), s, t + ROOM_TTL_MS);
  assert.deepEqual((await handle(req({ op: "wait", code: "ZZ99", peer: "phone-peer-late" }), s, t + ROOM_TTL_MS + ANSWER_TTL_MS + 1))[1], { pending: true });
  // a host that vanished: the room expires, and a new tab may claim the code
  const later = t + 3 * ROOM_TTL_MS;
  assert.equal((await handle(req({ op: "offer", code: "ZZ99", peer: "phone-peer-1", sdp: SDP }), s, later))[0], 404);
  assert.equal((await handle(req({ op: "poll", code: "ZZ99", secret: OTHER }), s, later))[0], 200);
  assert.equal(await sweep(s, later + 3 * ROOM_TTL_MS), 1);
  assert.equal(s.m.size, 0);
});
