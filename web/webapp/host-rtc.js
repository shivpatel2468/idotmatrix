/* DeskDot web app add-on: play with friends over the internet (docs/WEB_APP.md, "Play with friends over the internet").
 *
 * On the desktop, phones join a game at http://<laptop>:8765/p/<code> over the local Wi-Fi. In the web app the
 * engine lives in this tab, so there is nothing a phone could reach: the lobby QR points at
 * https://idotmatrix.com/p/<code> instead (config `public_url`), a page that connects the phone to THIS tab over
 * WebRTC. This add-on is the tab's side:
 *
 *   1. it watches the engine's lobby (GET /api/play/lobby, a local call) and, while one is open, registers the room
 *      code with the signalling function (/app/signal, netlify/functions/signal.mjs) and polls it every ~2 s for
 *      phones' offers;
 *   2. it answers each offer with an RTCPeerConnection (STUN only, non-trickle ICE);
 *   3. over the phone's data channel it tunnels the phone page's HTTP requests and WebSocket sessions into the
 *      engine (DeskDotHost.request / .socket), each phone with its own client address 10.88.0.<n>, so the engine
 *      treats it exactly like a phone on the Wi-Fi (LanGate: /p/ and /ws/p/ only).
 *
 * The wire format is in host-rtc-wire.js (shared with the phone's join page).
 */
(function () {
  "use strict";

  const H = window.DeskDotHost;
  if (!H || typeof RTCPeerConnection !== "function" || typeof fetch !== "function") return;

  const SELF = document.currentScript ? new URL(document.currentScript.src) : new URL("/app/host/host-rtc.js", location.href);
  const LOBBY_MS = 2500; // engine lobby check while a room is open or the tab is visible (a local call, no network)
  const LOBBY_IDLE_MS = 15000; // hidden tab, no room
  const SIGNAL_MS = 2000; // signalling poll while a room is open (the only network traffic)
  const SIGNAL_RETRY_MS = 6000;
  const MAX_PEERS = 12;
  const MAX_SOCKETS = 4; // per phone (the phone page keeps one)
  const MAX_INFLIGHT = 8; // HTTP requests per phone
  const OPEN_TIMEOUT_MS = 30000; // answered but no channel by then: the network blocked it
  const GRACE_MS = 10000; // "disconnected" can recover on its own (a Wi-Fi hand-over)
  const allowed = (p) => typeof p === "string" && (p.startsWith("/p/") || p.startsWith("/ws/p/")) && p.length < 400;

  let W = null; // DeskDotWire
  let room = null; // {code, secret, timer, state}
  const peers = new Map(); // peer id -> Peer
  let lastClient = 1;

  function loadWire() {
    if (window.DeskDotWire) return Promise.resolve(window.DeskDotWire);
    return new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = new URL("host-rtc-wire.js" + SELF.search, SELF).href;
      el.onload = () => (window.DeskDotWire ? resolve(window.DeskDotWire) : reject(new Error("wire missing")));
      el.onerror = () => reject(new Error("couldn't load host-rtc-wire.js"));
      document.head.appendChild(el);
    });
  }

  /** A client address no connected phone uses: 10.88.0.2 … 10.88.0.250 (never loopback: the engine sees a phone). */
  function nextClient() {
    const used = new Set([...peers.values()].map((p) => p.client));
    for (let i = 0; i < 250; i++) {
      lastClient = (lastClient % 249) + 1;
      const a = `10.88.0.${lastClient + 1}`;
      if (!used.has(a)) return a;
    }
    return "10.88.0.251";
  }

  // =================================================================================== lobby → room
  async function lobbyTick() {
    let lobby = null;
    let ok = false;
    try {
      const r = await H.request("GET", "/api/play/lobby", [["accept", "application/json"]], null);
      if (r.status === 200 && r.body) {
        lobby = JSON.parse(W.utf8(r.body)).lobby || null;
        ok = true;
      }
    } catch (e) {
      console.debug("DeskDot online play: lobby check failed", e);
    }
    if (ok) {
      let code = null;
      try {
        // only a lobby whose QR points at this site (public_url) is joinable over the internet
        if (lobby && lobby.url && new URL(lobby.url).origin === location.origin) code = String(lobby.code || "").toUpperCase();
      } catch {
        code = null;
      }
      if (room && room.code !== code) closeRoom();
      if (code && !room) openRoom(code);
    }
    const ms = room || !document.hidden ? LOBBY_MS : LOBBY_IDLE_MS;
    setTimeout(lobbyTick, ms);
  }

  function openRoom(code) {
    room = { code, secret: W.randomHex(24), timer: 0, state: "opening" };
    console.info(`DeskDot online play: room ${code} open — phones join at ${location.origin}/p/${code}`);
    signalTick(room);
  }

  function closeRoom() {
    const r = room;
    room = null;
    if (!r) return;
    clearTimeout(r.timer);
    r.state = "closed";
    W.signal({ op: "close", code: r.code, secret: r.secret }).catch(() => {});
    for (const p of peers.values()) p.bye();
  }

  async function signalTick(r) {
    if (room !== r) return;
    const res = await W.signal({ op: "poll", code: r.code, secret: r.secret });
    if (room !== r) return;
    let next = SIGNAL_MS;
    if (res.status === 200) {
      r.state = "open";
      for (const o of res.offers || []) accept(o.peer, o.sdp);
    } else if (res.status === 403) {
      // another tab registered this code first (rare: 4 characters): phones would reach it, not us
      r.state = "taken";
      console.warn(`DeskDot online play: room code ${r.code} is in use elsewhere — close the lobby and open a new one`);
      next = SIGNAL_RETRY_MS * 5;
    } else {
      r.state = res.status === 0 ? "offline" : "signal-error";
      next = SIGNAL_RETRY_MS;
    }
    r.timer = setTimeout(() => signalTick(r), next);
  }

  // =================================================================================== one phone
  function accept(id, sdp) {
    if (peers.has(id) || typeof sdp !== "string") return;
    if (peers.size >= MAX_PEERS) {
      // drop the oldest phone that never finished connecting, else refuse (it times out and says so)
      const stale = [...peers.values()].find((p) => !p.open);
      if (!stale) return;
      stale.close("replaced by a newer phone");
    }
    const p = new Peer(id, room);
    peers.set(id, p);
    p.start(sdp).catch((e) => p.close(String(e)));
  }

  class Peer {
    constructor(id, r) {
      this.id = id;
      this.room = r;
      this.client = nextClient();
      this.sockets = new Map(); // phone's socket id -> engine socket
      this.inflight = 0;
      this.open = false;
      this.closed = false;
      this.ch = null;
      this.asm = W.assembler();
      this.pc = new RTCPeerConnection({ iceServers: W.ICE_SERVERS });
      this.pc.ondatachannel = (e) => this.attach(e.channel);
      this.pc.onconnectionstatechange = () => this.onState();
    }

    async start(sdp) {
      await this.pc.setRemoteDescription({ type: "offer", sdp });
      await this.pc.setLocalDescription(await this.pc.createAnswer());
      await W.iceGathered(this.pc, 3000);
      if (this.closed || room !== this.room) return this.close("room closed");
      const r = await W.signal({ op: "answer", code: this.room.code, secret: this.room.secret, peer: this.id, sdp: this.pc.localDescription.sdp });
      if (r.status !== 200) return this.close(`answer refused (${r.status})`);
      this.openTimer = setTimeout(() => !this.open && this.close("no direct connection"), OPEN_TIMEOUT_MS);
    }

    attach(ch) {
      if (ch.label !== "deskdot" || this.ch) return ch.close();
      this.ch = ch;
      ch.binaryType = "arraybuffer";
      ch.onopen = () => {
        this.open = true;
        clearTimeout(this.openTimer);
        console.info(`DeskDot online play: a phone connected (${this.client})`);
        this.send({ t: "hello", v: 1 });
      };
      ch.onmessage = (e) => {
        let m;
        try {
          m = this.asm(e.data);
        } catch (err) {
          return this.close(`bad message: ${err}`);
        }
        if (m) this.onEnvelope(m);
      };
      ch.onclose = () => this.close("channel closed");
      if (ch.readyState === "open") ch.onopen();
    }

    onState() {
      const s = this.pc.connectionState;
      clearTimeout(this.graceTimer);
      if (s === "failed" || s === "closed") this.close(`connection ${s}`);
      else if (s === "disconnected") this.graceTimer = setTimeout(() => this.close("connection lost"), GRACE_MS);
    }

    send(obj) {
      try {
        return W.send(this.ch, obj);
      } catch (e) {
        this.close(`send failed: ${e}`);
        return false;
      }
    }

    onEnvelope(m) {
      if (!m || typeof m !== "object") return;
      const id = Number(m.id);
      if (m.t === "req") return this.request(id, m);
      if (!Number.isInteger(id) || id < 1) return;
      if (m.t === "ws-open") return this.socketOpen(id, m.p);
      const s = this.sockets.get(id);
      if (!s) return;
      if (m.t === "ws-send") {
        try {
          if (m.b) s.send(W.unb64(String(m.d || "")));
          else s.send(String(m.d == null ? "" : m.d));
        } catch {
          /* not open yet / closing: like a real socket, the frame is lost */
        }
      } else if (m.t === "ws-close") {
        s.close(1000);
      }
    }

    async request(id, m) {
      const reply = (s, h, b) => this.send({ t: "res", id, s, h: h || [], b: b || null });
      if (!Number.isInteger(id)) return;
      if (m.m !== "GET" || !allowed(m.p)) return reply(403, [["content-type", "text/plain"]], W.b64(new TextEncoder().encode("not allowed")));
      if (this.inflight >= MAX_INFLIGHT) return reply(429, [["content-type", "text/plain"]], null);
      this.inflight++;
      try {
        const accept = (Array.isArray(m.h) ? m.h : []).filter((x) => Array.isArray(x) && /^(accept|accept-language)$/i.test(String(x[0])));
        const r = await H.request("GET", m.p, accept.map((x) => [String(x[0]), String(x[1])]), null, this.client);
        reply(r.status, r.headers, r.body && r.body.byteLength ? W.b64(r.body) : null);
      } catch (e) {
        reply(502, [["content-type", "text/plain"]], W.b64(new TextEncoder().encode(String(e))));
      } finally {
        this.inflight--;
      }
    }

    socketOpen(id, path) {
      const ev = (e, d) => this.send({ t: "ws-ev", id, ev: e, d });
      if (this.sockets.has(id)) return;
      if (!allowed(path) || !path.startsWith("/ws/p/")) return ev("close", 1008);
      if (this.sockets.size >= MAX_SOCKETS) return ev("close", 1013);
      const s = H.socket(path, this.client);
      s.binaryType = "arraybuffer";
      this.sockets.set(id, s);
      s.onopen = () => ev("open");
      s.onmessage = (e) => (typeof e.data === "string" ? ev("text", e.data) : ev("bytes", W.b64(e.data)));
      s.onclose = (e) => {
        if (this.sockets.get(id) !== s) return;
        this.sockets.delete(id);
        ev("close", (e && e.code) || 1000);
      };
    }

    /** The room closed: let the engine's own "closed" messages reach the phone first, then hang up. */
    bye() {
      this.send({ t: "bye" });
      setTimeout(() => this.close("room closed"), 1500);
    }

    close(why) {
      if (this.closed) return;
      this.closed = true;
      clearTimeout(this.openTimer);
      clearTimeout(this.graceTimer);
      for (const s of this.sockets.values()) {
        try {
          s.onclose = null;
          s.close(1001);
        } catch {
          /* already closed */
        }
      }
      this.sockets.clear();
      try {
        if (this.ch) this.ch.close();
      } catch {
        /* closed */
      }
      try {
        this.pc.close();
      } catch {
        /* closed */
      }
      if (peers.get(this.id) === this) peers.delete(this.id);
      if (this.open) console.info(`DeskDot online play: a phone left (${this.client}: ${why || "closed"})`);
      else if (why) console.debug(`DeskDot online play: phone ${this.id} gave up: ${why}`);
    }
  }

  // =================================================================================== start
  window.addEventListener("pagehide", () => {
    // the tab is going away: free the room code at once (it would expire in 10 minutes anyway)
    const r = room;
    if (r && navigator.sendBeacon) {
      try {
        navigator.sendBeacon(W.SIGNAL, new Blob([JSON.stringify({ op: "close", code: r.code, secret: r.secret })], { type: "application/json" }));
      } catch {
        /* best effort */
      }
    }
  });

  // for tests and the curious: window.deskdotRtc.state()
  window.deskdotRtc = {
    state: () => ({
      room: room && { code: room.code, state: room.state },
      phones: [...peers.values()].map((p) => ({ client: p.client, open: p.open, link: p.pc.connectionState, sockets: p.sockets.size })),
    }),
  };

  loadWire()
    .then((w) => {
      W = w;
      return H.ready;
    })
    .then(() => lobbyTick())
    .catch((e) => console.warn("DeskDot online play is off:", e));
})();
