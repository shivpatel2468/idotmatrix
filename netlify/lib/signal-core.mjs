// Signalling for "play with friends over the internet" in the DeskDot web app (docs/WEB_APP.md).
//
// The engine runs in someone's browser tab, so a phone can't reach it directly. Each phone and the host tab swap
// one WebRTC offer/answer through here (non-trickle ICE: one round trip), then talk peer-to-peer over a data channel.
// Pure logic (validation + the room state machine) lives here so it can be tested in Node without Netlify;
// netlify/functions/signal.mjs wires it to a Netlify Blobs store.
//
// It is NOT a relay: only SDP-shaped text up to 16 KB, keyed by a 4-character room code that a host tab registered
// with a secret. Only that tab can read its room's offers and answer them. Everything expires on its own.
//
// Ops (POST JSON {op, ...}; every response is JSON, never cached):
//   host → {op:"poll",   code, secret}        register / refresh the room; returns {offers:[{peer, sdp}]} (consumed)
//   host → {op:"answer", code, secret, peer, sdp}
//   host → {op:"close",  code, secret}        the lobby closed: drop the room and anything pending
//   phone → {op:"offer", code, peer, sdp}      404 when no host tab has this room open
//   phone → {op:"wait",  code, peer}           {sdp} once answered, else {pending:true}; 404 when the room is gone

export const ROOM_TTL_MS = 10 * 60 * 1000; // a room lives 10 min after its host's last poll
const ROOM_REFRESH_MS = 2 * 60 * 1000; // re-write the room record at most every 2 min (polls are reads otherwise)
export const OFFER_TTL_MS = 60 * 1000;
export const ANSWER_TTL_MS = 60 * 1000;
export const MAX_SDP = 16 * 1024;
export const MAX_BODY = 20 * 1024;
export const MAX_PENDING = 12; // unanswered offers per room

const CODE_RE = /^[A-Z0-9]{4}$/;
const PEER_RE = /^[A-Za-z0-9_-]{8,40}$/;
const SECRET_RE = /^[a-f0-9]{32,64}$/;
// an SDP is short ASCII lines "x=…" (RFC 8866); anything else is refused, so this can't carry arbitrary data
const SDP_LINE_RE = /^[a-z]=[\x20-\x7e]*$/;

export const validCode = (c) => typeof c === "string" && CODE_RE.test(c);
export const validPeer = (p) => typeof p === "string" && PEER_RE.test(p);
export const validSecret = (s) => typeof s === "string" && SECRET_RE.test(s);

export function validSdp(sdp) {
  if (typeof sdp !== "string" || sdp.length < 20 || sdp.length > MAX_SDP) return false;
  if (!sdp.startsWith("v=0")) return false;
  const lines = sdp.split(/\r?\n/);
  if (lines[lines.length - 1] === "") lines.pop();
  return lines.length > 3 && lines.every((l) => SDP_LINE_RE.test(l));
}

export class BadRequest extends Error {
  constructor(message, status = 400) {
    super(message);
    this.status = status;
  }
}

/** Parse and validate a request body (a string). Returns {op, code, peer?, secret?, sdp?} or throws BadRequest. */
export function parseRequest(text) {
  if (typeof text !== "string" || text.length > MAX_BODY) throw new BadRequest("body too large", 413);
  let b;
  try {
    b = JSON.parse(text);
  } catch {
    throw new BadRequest("bad json");
  }
  if (!b || typeof b !== "object" || Array.isArray(b)) throw new BadRequest("bad json");
  const op = b.op;
  const need = {
    poll: ["secret"],
    close: ["secret"],
    answer: ["secret", "peer", "sdp"],
    offer: ["peer", "sdp"],
    wait: ["peer"],
    ice: [], // relay (TURN) credentials for a live room's host or phone — the function adds them
  }[op];
  if (!need) throw new BadRequest("unknown op");
  const code = typeof b.code === "string" ? b.code.toUpperCase() : b.code;
  if (!validCode(code)) throw new BadRequest("bad code");
  const out = { op, code };
  for (const k of need) {
    const ok = k === "secret" ? validSecret(b[k]) : k === "peer" ? validPeer(b[k]) : validSdp(b[k]);
    if (!ok) throw new BadRequest(`bad ${k}`);
    out[k] = b[k];
  }
  return out;
}

export async function sha256hex(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

const roomKey = (code) => `room/${code}`;
const offerKey = (code, peer) => `offer/${code}/${peer}`;
const answerKey = (code, peer) => `answer/${code}/${peer}`;

/**
 * Run one validated request against `store` — {get(key) -> object|null, set(key, obj), delete(key),
 * list(prefix) -> [key]} — at time `now` (ms). Returns [status, body].
 */
export async function handle(req, store, now = Date.now()) {
  const { op, code } = req;
  const room = await store.get(roomKey(code));
  const live = room && room.exp > now;
  if (room && !live) await dropRoom(store, code);

  if (op === "ice") return live ? [200, { ok: true }] : [404, { error: "no-room" }];

  if (op === "offer" || op === "wait") {
    if (!live) return [404, { error: "no-room" }];
    if (op === "offer") {
      const pending = await store.list(`offer/${code}/`);
      if (pending.length >= MAX_PENDING && !pending.includes(offerKey(code, req.peer))) return [429, { error: "busy" }];
      await store.set(offerKey(code, req.peer), { sdp: req.sdp, exp: now + OFFER_TTL_MS });
      return [200, { ok: true }];
    }
    const ans = await store.get(answerKey(code, req.peer));
    if (!ans || ans.exp <= now) return [200, { pending: true }];
    await store.delete(answerKey(code, req.peer));
    return [200, { sdp: ans.sdp }];
  }

  // host ops: the secret proves this is the tab that registered the room
  const hash = await sha256hex(req.secret);
  if (live && room.hash !== hash) return [403, { error: "taken" }]; // another tab owns this code right now
  if (op === "close") {
    if (live) await dropRoom(store, code);
    return [200, { ok: true }];
  }
  if (!live) return op === "poll" ? createAndPoll(store, code, hash, now) : [404, { error: "no-room" }];
  if (op === "answer") {
    await store.set(answerKey(code, req.peer), { sdp: req.sdp, exp: now + ANSWER_TTL_MS });
    return [200, { ok: true }];
  }
  // poll: a read, plus a TTL refresh write at most every ROOM_REFRESH_MS (a poll every 2 s stays cheap)
  if (room.exp - now < ROOM_TTL_MS - ROOM_REFRESH_MS) await store.set(roomKey(code), { ...room, exp: now + ROOM_TTL_MS });
  return [200, { offers: await takeOffers(store, code, now), ttl: ROOM_TTL_MS }];
}

async function createAndPoll(store, code, hash, now) {
  await store.set(roomKey(code), { hash, exp: now + ROOM_TTL_MS });
  return [200, { offers: await takeOffers(store, code, now), ttl: ROOM_TTL_MS }];
}

async function takeOffers(store, code, now) {
  const out = [];
  for (const key of await store.list(`offer/${code}/`)) {
    const o = await store.get(key);
    await store.delete(key);
    if (o && o.exp > now) out.push({ peer: key.split("/").pop(), sdp: o.sdp });
  }
  return out;
}

async function dropRoom(store, code) {
  await store.delete(roomKey(code));
  for (const p of ["offer", "answer"]) for (const key of await store.list(`${p}/${code}/`)) await store.delete(key);
}

/** Occasional clean-up of rooms whose host vanished without closing (called now and then by the function). */
export async function sweep(store, now = Date.now()) {
  let n = 0;
  for (const key of await store.list("room/")) {
    const r = await store.get(key);
    if (!r || r.exp <= now) {
      await dropRoom(store, key.slice("room/".length));
      n++;
    }
  }
  return n;
}

/** An in-memory store with the same interface (tests, local experiments). */
export function memoryStore() {
  const m = new Map();
  return {
    m,
    get: async (k) => (m.has(k) ? JSON.parse(m.get(k)) : null),
    set: async (k, v) => void m.set(k, JSON.stringify(v)),
    delete: async (k) => void m.delete(k),
    list: async (prefix) => [...m.keys()].filter((k) => k.startsWith(prefix)).sort(),
  };
}
