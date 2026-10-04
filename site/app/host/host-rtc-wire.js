/* DeskDot web app — the wire format of "play with friends over the internet" (docs/WEB_APP.md).
 *
 * Shared by both ends of the tunnel: the host tab (host-rtc.js, next to the engine) and the phone's join page
 * (/app/join/join.js, served at /p/<code>). A classic script: it sets `DeskDotWire` on the global object (and
 * module.exports under Node, for tests/js/wire.test.mjs).
 *
 * One ordered, reliable RTCDataChannel ("deskdot") per phone carries JSON envelopes:
 *
 *   phone → host  {t:"req", id, m, p, h:[[k, v]]}                 an HTTP request (GET /p/<code> only)
 *   host → phone  {t:"res", id, s, h:[[k, v]], b?: base64}        its response
 *   phone → host  {t:"ws-open", id, p}                            open a WebSocket (/ws/p/<code>?cid=…)
 *   host → phone  {t:"ws-ev", id, ev:"open"|"text"|"bytes"|"close", d?}   text: string, bytes: base64, close: code
 *   phone → host  {t:"ws-send", id, d, b?: 1}                     a frame (b=1: d is base64 bytes)
 *   phone → host  {t:"ws-close", id, c?}
 *   host → phone  {t:"hello", v:1} on open · {t:"bye"} when the room closes
 *
 * An envelope travels as one text message when it fits MAX_MSG bytes; a larger one is sent as consecutive binary
 * messages of its UTF-8 JSON, each prefixed by a flag byte (1 = more follows, 0 = last). Data channels are
 * ordered and the parts are queued back to back, so parts of two envelopes never interleave.
 */
(function (root) {
  "use strict";

  const MAX_MSG = 16000; // bytes per data-channel message: every browser accepts 16 KiB
  const MAX_ENVELOPE = 8 * 1024 * 1024; // refuse to reassemble anything bigger (a confused or hostile peer)
  const ICE_SERVERS = [{ urls: ["stun:stun.l.google.com:19302", "stun:stun.cloudflare.com:3478"] }];
  const SIGNAL = "/app/signal";
  const enc = new TextEncoder();
  const dec = new TextDecoder();
  const realFetch = typeof root.fetch === "function" ? root.fetch.bind(root) : null; // before any page shim

  function b64(buf) {
    const u = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    let s = "";
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
    return btoa(s);
  }

  function unb64(s) {
    const bin = atob(s);
    const u = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return u.buffer;
  }

  /** One envelope → the data-channel messages that carry it (a string, or flagged binary parts). */
  function frames(obj) {
    const text = JSON.stringify(obj);
    if (text.length * 3 <= MAX_MSG) return [text]; // fits even if every char took 3 UTF-8 bytes
    const bytes = enc.encode(text);
    if (bytes.length <= MAX_MSG) return [text];
    const out = [];
    const step = MAX_MSG - 1;
    for (let i = 0; i < bytes.length; i += step) {
      const part = bytes.subarray(i, i + step);
      const f = new Uint8Array(part.length + 1);
      f[0] = i + step < bytes.length ? 1 : 0;
      f.set(part, 1);
      out.push(f.buffer);
    }
    return out;
  }

  /** A reassembler: push(message data) returns the envelope once complete, else null. Throws on garbage. */
  function assembler(limit) {
    const max = limit || MAX_ENVELOPE;
    let parts = [];
    let size = 0;
    return function push(data) {
      if (typeof data === "string") {
        if (parts.length) throw new Error("text message inside a split envelope");
        return JSON.parse(data);
      }
      const u = new Uint8Array(data);
      if (!u.length || u[0] > 1) throw new Error("bad part");
      size += u.length - 1;
      if (size > max) throw new Error("envelope too large");
      parts.push(u.subarray(1));
      if (u[0] === 1) return null;
      const all = new Uint8Array(size);
      let o = 0;
      for (const p of parts) {
        all.set(p, o);
        o += p.length;
      }
      parts = [];
      size = 0;
      return JSON.parse(dec.decode(all));
    };
  }

  /** Send one envelope on an open channel; false when the channel isn't open. */
  function send(channel, obj) {
    if (!channel || channel.readyState !== "open") return false;
    for (const f of frames(obj)) channel.send(f);
    return true;
  }

  /** Resolves when ICE gathering is complete (or after `ms`): non-trickle, the SDP then carries every candidate. */
  function iceGathered(pc, ms) {
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        clearTimeout(timer);
        pc.removeEventListener("icegatheringstatechange", check);
        resolve();
      };
      const check = () => pc.iceGatheringState === "complete" && done();
      const timer = setTimeout(done, ms || 3000);
      pc.addEventListener("icegatheringstatechange", check);
    });
  }

  /** POST one op to the signalling function. Returns {status, ...json}; status 0 = network error. */
  async function signal(body, timeoutMs) {
    const ctl = typeof AbortController === "function" ? new AbortController() : null;
    const timer = ctl ? setTimeout(() => ctl.abort(), timeoutMs || 10000) : 0;
    try {
      const r = await realFetch(SIGNAL, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
        signal: ctl ? ctl.signal : undefined,
      });
      let data = {};
      try {
        data = await r.json();
      } catch {
        /* not json (a 502 page) */
      }
      return Object.assign({}, data, { status: r.status });
    } catch (e) {
      return { status: 0, error: String(e) };
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * ICE servers for a room: STUN, plus a relay (TURN) when the site has one configured — strict networks (mobile
   * carriers' shared addresses, routers that won't loop a connection back) need it. Cached for an hour per code.
   */
  const iceCache = new Map();
  async function ice(code) {
    const hit = iceCache.get(code);
    if (hit && hit.exp > Date.now()) return hit.servers;
    const r = await signal({ op: "ice", code }, 8000);
    const servers = r.status === 200 && Array.isArray(r.iceServers) && r.iceServers.length ? r.iceServers : ICE_SERVERS;
    if (r.status === 200) iceCache.set(code, { servers, exp: Date.now() + 3600e3, relay: r.relay || null });
    return servers;
  }
  const relayOf = (code) => (iceCache.get(code) || {}).relay || null;

  const ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";
  function randomId(n) {
    const a = new Uint8Array(n || 20);
    crypto.getRandomValues(a);
    return [...a].map((b) => ALPHABET[b % 36]).join("");
  }
  function randomHex(bytes) {
    const a = new Uint8Array(bytes || 24);
    crypto.getRandomValues(a);
    return [...a].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  const api = { MAX_MSG, ICE_SERVERS, SIGNAL, ice, relayOf, b64, unb64, frames, assembler, send, iceGathered, signal, randomId, randomHex, utf8: (b) => dec.decode(b) };
  root.DeskDotWire = api;
  if (typeof module === "object" && module && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
