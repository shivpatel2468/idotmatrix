/* DeskDot join page — a phone joining a game that runs in someone's web-app tab (docs/WEB_APP.md,
 * "Play with friends over the internet").
 *
 * Served at idotmatrix.com/p/<code> (netlify.toml rewrites /p/* to /app/join/index.html). There is no server that
 * runs the game: the engine lives in the host's browser tab. This page:
 *
 *   1. swaps one WebRTC offer/answer with that tab through /app/signal (non-trickle ICE, STUN only);
 *   2. asks the tab for /p/<code> over the data channel (does the room exist? a casino table or a game pad?);
 *   3. installs fetch + WebSocket shims that send same-origin /p/, /api/ and /ws/ traffic over the data channel,
 *      then writes the phone controller page (the engine's controller.html / casino.html, built into
 *      /app/join/<kind>.html with its script moved to <kind>.js — the page's CSP allows no inline script) into this
 *      document. The controller builds its socket URL from `location`, which is still /p/<code>, so it connects
 *      through the shim to the engine exactly as it would over the Wi-Fi;
 *   4. keeps the link up: when it drops, an overlay says so and the handshake runs again; the controller's own
 *      socket reconnects and gets its seat back by client id.
 *
 * Wire format: /app/host/host-rtc-wire.js. Host side: /app/host/host-rtc.js.
 */
(function () {
  "use strict";

  const W = window.DeskDotWire;
  const SELF = document.currentScript ? new URL(document.currentScript.src) : new URL("/app/join/join.js", location.href);
  const VERSION = SELF.search; // ?v=<build>
  const code = (location.pathname.split("/").filter(Boolean).pop() || "").toUpperCase();
  const realFetch = window.fetch.bind(window);
  const RealWebSocket = window.WebSocket;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ===================================================================================== screens
  const SCREENS = {
    connecting: { tone: "busy", title: "Connecting to the host's table…", text: "Your phone is linking straight to the computer running the game." },
    reconnecting: { tone: "busy", title: "Reconnecting to the host's table…", text: "The link dropped for a moment. Your seat is kept." },
    loading: { tone: "busy", title: "Connected!", text: "Loading the controller…" },
    "no-room": {
      tone: "bad",
      title: "No open game with this code",
      text: "The host's table isn't open, or the code expired. Ask them to open Play with friends again, then scan the new QR code.",
      button: "Try again",
    },
    expired: { tone: "bad", title: "This game link has expired", text: "Scan the QR code on the panel again to join the current game.", button: "Try again" },
    closed: { tone: "warn", title: "The host closed this table", text: "Scan the QR code on the panel to join the next game.", button: "Rejoin" },
    "host-gone": {
      tone: "warn",
      title: "The host's tab isn't answering",
      text: "Their DeskDot tab may be closed, asleep, or hidden in the background for a long time. Ask them to bring it to the front, then try again.",
      button: "Try again",
    },
    blocked: {
      tone: "bad",
      title: "Couldn't reach the host's computer",
      text: "Your phone and the host's computer have to connect directly, and this network won't let them (a strict firewall or router). There's no relay server to go through.",
      tips: [
        "Join the same Wi-Fi as the host, or",
        "switch between Wi-Fi and mobile data, then try again.",
        "Office, school and hotel networks often block direct links.",
      ],
      button: "Try again",
    },
    busy: { tone: "warn", title: "Lots of phones are joining", text: "Give it a few seconds, then try again.", button: "Try again" },
    offline: { tone: "warn", title: "You're offline", text: "Check this phone's internet connection, then try again.", button: "Try again" },
    server: { tone: "warn", title: "Something went wrong", text: "The connection hiccupped. Try again in a moment.", button: "Try again" },
    unsupported: {
      tone: "bad",
      title: "This browser can't join",
      text: "It doesn't support direct connections (WebRTC). Open this link in Chrome, Safari, Firefox or Edge.",
    },
    "bad-code": { tone: "bad", title: "That link doesn't look right", text: "Scan the QR code on the panel again." },
  };

  let ui = null;
  let gameWritten = false;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function mountUI() {
    const host = el("div");
    host.id = "deskdot-join";
    const root = host.attachShadow({ mode: "open" });
    const css = el("link");
    css.rel = "stylesheet";
    css.href = "/app/join/join.css" + VERSION;
    const veil = el("div", "veil");
    veil.hidden = true;
    veil.setAttribute("role", "status");
    veil.setAttribute("aria-live", "polite");
    const card = el("div", "card");
    const dots = el("div", "dots");
    for (let i = 0; i < 4; i++) dots.appendChild(el("i"));
    const title = el("h1");
    const text = el("p");
    const tips = el("ul");
    const chip = el("div", "code");
    chip.append(el("span", null, "Room"), el("b", null, code));
    const step = el("div", "step");
    const button = el("button");
    button.type = "button";
    button.addEventListener("click", retry);
    const note = el("div", "note", "DeskDot · the game runs in the host's browser tab");
    card.append(el("div", "brand", "DeskDot · play with friends"), dots, title, text, tips, chip, step, button, note);
    veil.appendChild(card);
    root.append(css, veil);
    (document.body || document.documentElement).appendChild(host);
    ui = { host, veil, card, title, text, tips, chip, step, button, state: "" };
  }

  function show(state, stepText) {
    const s = SCREENS[state] || SCREENS.server;
    if (!ui || !ui.host.isConnected) mountUI();
    ui.state = state;
    ui.card.className = "card " + s.tone;
    ui.title.textContent = s.title;
    ui.text.textContent = s.text;
    ui.tips.replaceChildren(...(s.tips || []).map((t) => el("li", null, t)));
    ui.tips.hidden = !s.tips;
    ui.chip.hidden = !/^[A-Z0-9]{4}$/.test(code);
    ui.step.textContent = stepText || "";
    ui.button.hidden = !s.button;
    ui.button.textContent = s.button || "";
    ui.veil.classList.toggle("over", gameWritten);
    ui.veil.hidden = false;
    document.title = gameWritten ? document.title : `${s.title} · DeskDot`;
    if (s.button) setTimeout(() => ui && ui.button.focus({ preventScroll: true }), 50);
  }

  function step(text) {
    if (ui) ui.step.textContent = text || "";
  }

  function hideUI() {
    if (ui) ui.veil.hidden = true;
  }

  function retry() {
    // before the game page is up, a clean start is simplest; afterwards keep the page (and its seat) and re-link
    if (!gameWritten || T.bye || (ui && ["closed", "no-room", "expired"].includes(ui.state))) return location.reload();
    connectLoop(false);
  }

  // ===================================================================================== the link
  const T = {
    pc: null,
    ch: null,
    gen: 0,
    seq: 0,
    reqs: new Map(), // request id -> {resolve, reject}
    socks: new Map(), // socket id -> TunnelSocket
    everUp: false,
    bye: false, // the host closed the room: don't reconnect
    grace: 0,
  };

  class Fail extends Error {
    constructor(reason, cause) {
      super(reason + (cause ? `: ${cause}` : ""));
      this.reason = reason;
    }
  }

  /** Resolves when the data channel opens; rejects (blocked) when ICE fails or nothing happens for `ms`. */
  function opened(pc, ch, ms) {
    return new Promise((resolve, reject) => {
      if (ch.readyState === "open") return resolve();
      const timer = setTimeout(() => reject(new Fail("blocked", "timed out")), ms);
      ch.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      });
      pc.addEventListener("connectionstatechange", () => {
        if (pc.connectionState === "failed") {
          clearTimeout(timer);
          reject(new Fail("blocked", "ICE failed"));
        }
      });
    });
  }

  async function handshake() {
    if (typeof RTCPeerConnection !== "function") throw new Fail("unsupported");
    const peer = W.randomId(20);
    const pc = new RTCPeerConnection({ iceServers: await W.ice(code) });
    const ch = pc.createDataChannel("deskdot", { ordered: true });
    ch.binaryType = "arraybuffer";
    try {
      step("Preparing a direct link…");
      await pc.setLocalDescription(await pc.createOffer());
      await W.iceGathered(pc, 3000);
      step("Knocking on the host's table…");
      let r = await W.signal({ op: "offer", code, peer, sdp: pc.localDescription.sdp });
      if (r.status === 0) throw new Fail("offline");
      if (r.status === 404) throw new Fail("no-room");
      if (r.status === 429) throw new Fail("busy");
      if (r.status === 400 && r.error === "bad code") throw new Fail("bad-code");
      if (r.status !== 200) throw new Fail("server", `signal ${r.status}`);
      step("Waiting for the host's tab to answer…");
      const until = Date.now() + 30000;
      let answer = null;
      while (!answer && Date.now() < until) {
        await sleep(1000);
        r = await W.signal({ op: "wait", code, peer });
        if (r.status === 404) throw new Fail("no-room");
        if (r.status === 200 && typeof r.sdp === "string") answer = r.sdp;
      }
      if (!answer) throw new Fail("host-gone");
      step("Linking up…");
      await pc.setRemoteDescription({ type: "answer", sdp: answer });
      await opened(pc, ch, 15000);
      return { pc, ch };
    } catch (e) {
      try {
        pc.close();
      } catch {
        /* closed */
      }
      throw e instanceof Fail ? e : new Fail("blocked", e);
    }
  }

  let connecting = false;
  async function connectLoop(first) {
    if (connecting || T.ch || T.bye) return false;
    connecting = true;
    // a first visit tries twice (ICE can be flaky); a dropped link keeps trying for about a minute
    const delays = first ? [0, 1500] : [0, 1000, 2000, 4000, 8000, 10000, 10000, 10000];
    let last = "blocked";
    try {
      for (let i = 0; i < delays.length; i++) {
        if (delays[i]) await sleep(delays[i]);
        if (T.bye) return false;
        show(first ? "connecting" : "reconnecting", i ? `Try ${i + 1} of ${delays.length}` : "");
        try {
          const { pc, ch } = await handshake();
          attach(pc, ch);
          return true;
        } catch (e) {
          last = e.reason || "blocked";
          console.warn("DeskDot join:", e.message);
          if (["no-room", "bad-code", "unsupported", "host-gone"].includes(last) && (first || last !== "host-gone")) break;
        }
      }
      show(last === "no-room" && T.everUp ? "closed" : last);
      return false;
    } finally {
      connecting = false;
    }
  }

  function attach(pc, ch) {
    const gen = ++T.gen;
    T.pc = pc;
    T.ch = ch;
    const asm = W.assembler();
    ch.onmessage = (e) => {
      if (gen !== T.gen) return;
      let m;
      try {
        m = asm(e.data);
      } catch (err) {
        return linkDown(gen, `garbled: ${err}`);
      }
      if (m) onEnvelope(m);
    };
    ch.onclose = () => linkDown(gen, "channel closed");
    pc.onconnectionstatechange = () => {
      if (gen !== T.gen) return;
      const s = pc.connectionState;
      clearTimeout(T.grace);
      if (s === "failed" || s === "closed") linkDown(gen, s);
      else if (s === "disconnected") T.grace = setTimeout(() => linkDown(gen, "disconnected"), 6000);
    };
    T.everUp = true;
    for (const s of T.socks.values()) s._announce(); // sockets the page opened while the link was down
    if (gameWritten) hideUI();
    else startGame();
  }

  function linkDown(gen, why) {
    if (gen !== T.gen || !T.ch) return;
    console.warn("DeskDot join: link down —", why);
    T.gen++;
    T.ch = null;
    clearTimeout(T.grace);
    try {
      T.pc.close();
    } catch {
      /* closed */
    }
    T.pc = null;
    for (const r of T.reqs.values()) r.reject(new TypeError("Failed to fetch: the link to the host dropped"));
    T.reqs.clear();
    for (const s of [...T.socks.values()]) {
      if (s.readyState === 0) s._announced = false; // re-sent on the next link
      else s._event("close", 1006);
    }
    if (T.bye) {
      if (!gameWritten) show("closed");
      return;
    }
    connectLoop(false);
  }

  function onEnvelope(m) {
    if (!m || typeof m !== "object") return;
    if (m.t === "res") {
      const r = T.reqs.get(m.id);
      if (r) {
        T.reqs.delete(m.id);
        r.resolve(m);
      }
    } else if (m.t === "ws-ev") {
      const s = T.socks.get(m.id);
      if (s) s._event(m.ev, m.d);
    } else if (m.t === "bye") {
      T.bye = true;
    }
  }

  /** One HTTP request to the engine over the link: resolves to {s, h, b} (b base64 or null). */
  function tunnelRequest(path, headers) {
    return new Promise((resolve, reject) => {
      if (!T.ch) return reject(new TypeError("Failed to fetch: not linked to the host"));
      const id = ++T.seq;
      const timer = setTimeout(() => {
        T.reqs.delete(id);
        reject(new TypeError("Failed to fetch: the host didn't answer"));
      }, 20000);
      T.reqs.set(id, {
        resolve: (m) => (clearTimeout(timer), resolve(m)),
        reject: (e) => (clearTimeout(timer), reject(e)),
      });
      W.send(T.ch, { t: "req", id, m: "GET", p: path, h: headers || [] });
    });
  }

  // ===================================================================================== shims
  const tunnelled = (u) => u.host === location.host && /^\/(api|p|ws)(\/|$)/.test(u.pathname);
  const NULL_BODY = new Set([101, 103, 204, 205, 304]);

  async function fetchShim(input, init) {
    const req = new Request(input, init);
    const u = new URL(req.url);
    if (!tunnelled(u)) return realFetch(input, init);
    if (req.method !== "GET" && req.method !== "HEAD") throw new TypeError("only GET requests reach the host's game");
    const m = await tunnelRequest(u.pathname + u.search, [...req.headers]);
    const headers = new Headers();
    for (const h of Array.isArray(m.h) ? m.h : []) {
      try {
        headers.append(String(h[0]), String(h[1]));
      } catch {
        /* a header the browser won't accept */
      }
    }
    const status = Number(m.s) >= 200 && Number(m.s) <= 599 ? Number(m.s) : 502;
    const body = NULL_BODY.has(status) || req.method === "HEAD" || !m.b ? null : W.unb64(m.b);
    return new Response(body, { status, headers });
  }

  class TunnelSocket extends EventTarget {
    constructor(u) {
      super();
      this.url = u.href;
      this.readyState = 0;
      this.binaryType = "blob";
      this.protocol = "";
      this.extensions = "";
      this.bufferedAmount = 0;
      this.onopen = this.onmessage = this.onclose = this.onerror = null;
      this._id = ++T.seq;
      this._path = u.pathname + u.search;
      this._announced = false;
      T.socks.set(this._id, this);
      this._announce();
    }
    _announce() {
      if (this.readyState === 0 && !this._announced && T.ch) this._announced = W.send(T.ch, { t: "ws-open", id: this._id, p: this._path });
    }
    send(data) {
      if (this.readyState !== 1) throw new DOMException("WebSocket is not open", "InvalidStateError");
      const out = (d, b) => T.ch && W.send(T.ch, b ? { t: "ws-send", id: this._id, d, b: 1 } : { t: "ws-send", id: this._id, d });
      if (typeof data === "string") out(data, false);
      else if (data instanceof ArrayBuffer) out(W.b64(data), true);
      else if (ArrayBuffer.isView(data)) out(W.b64(new Uint8Array(data.buffer, data.byteOffset, data.byteLength)), true);
      else if (data instanceof Blob) data.arrayBuffer().then((b) => this.readyState === 1 && out(W.b64(b), true));
    }
    close(code) {
      if (this.readyState >= 2) return;
      const announced = this._announced && T.ch;
      this.readyState = 2;
      if (announced) W.send(T.ch, { t: "ws-close", id: this._id, c: code || 1000 });
      else this._event("close", code || 1000);
    }
    _fire(type, ev) {
      this.dispatchEvent(ev);
      const h = this["on" + type];
      if (typeof h === "function") h.call(this, ev);
    }
    _event(ev, data) {
      if (this.readyState === 3) return;
      if (ev === "open") {
        if (this.readyState !== 0) return;
        this.readyState = 1;
        this._fire("open", new Event("open"));
      } else if (ev === "text") {
        this._fire("message", new MessageEvent("message", { data: String(data), origin: location.origin }));
      } else if (ev === "bytes") {
        const buf = W.unb64(String(data || ""));
        this._fire("message", new MessageEvent("message", { data: this.binaryType === "arraybuffer" ? buf : new Blob([buf]), origin: location.origin }));
      } else if (ev === "close") {
        this.readyState = 3;
        T.socks.delete(this._id);
        const code = Number(data) || 1000;
        if (code === 1006) this._fire("error", new Event("error"));
        this._fire("close", new CloseEvent("close", { code, wasClean: code !== 1006 }));
      }
    }
  }
  for (const [k, v] of Object.entries({ CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 })) {
    TunnelSocket[k] = v;
    TunnelSocket.prototype[k] = v;
  }

  function WebSocketShim(url, protocols) {
    const u = new URL(url, location.href);
    // the controller builds ws(s)://<location.host>/ws/p/<code>: accept either scheme for this host
    if (/^(wss?|https?):$/.test(u.protocol) && tunnelled(u) && u.pathname.startsWith("/ws/")) return new TunnelSocket(u);
    return protocols === undefined ? new RealWebSocket(url) : new RealWebSocket(url, protocols);
  }
  WebSocketShim.prototype = RealWebSocket.prototype;
  Object.assign(WebSocketShim, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });

  function installShims() {
    window.fetch = fetchShim;
    window.WebSocket = WebSocketShim;
  }

  // ===================================================================================== the game page
  let starting = false;
  async function startGame() {
    if (starting || gameWritten) return;
    starting = true;
    try {
      show("loading");
      const m = await tunnelRequest(`/p/${code}`, [["accept", "text/html"]]);
      if (m.s === 404) return show("expired");
      if (m.s !== 200) return show("server", `The host answered ${m.s}.`);
      // which phone page the engine serves for this room: a casino table or a game pad
      const html = m.b ? W.utf8(W.unb64(m.b)) : "";
      const kind = html.includes("DeskDotCasino") ? "casino" : "controller";
      const r = await realFetch(`/app/join/${kind}.html${VERSION}`, { cache: "no-cache" });
      if (!r.ok) return show("server", `Couldn't load the controller (${r.status}).`);
      const page = await r.text();
      if (!T.ch) return; // the link dropped meanwhile: the reconnect calls startGame again
      writeGame(page);
    } catch (e) {
      console.warn("DeskDot join: couldn't start the game page", e);
      if (T.ch) show("server");
    } finally {
      starting = false;
    }
  }

  function writeGame(page) {
    installShims();
    gameWritten = true;
    ui = null; // the old document's overlay goes with it
    // the window (and this script's state, the shims, the peer connection) survives document.open()
    document.open();
    document.write(page);
    document.close();
    document.addEventListener("visibilitychange", onVisible);
    if (!T.ch) show("reconnecting");
  }

  function onVisible() {
    if (document.visibilityState !== "visible" || T.bye) return;
    // a phone that slept often comes back with a dead link: notice now instead of after the timeouts
    if (T.ch && T.pc && ["failed", "disconnected", "closed"].includes(T.pc.connectionState)) linkDown(T.gen, "woke up");
    else if (!T.ch && !connecting && gameWritten) connectLoop(false);
  }

  // ===================================================================================== start
  function start() {
    if (!/^[A-Z0-9]{4}$/.test(code)) return show("bad-code");
    if (!W) return show("offline");
    if (typeof RTCPeerConnection !== "function" || typeof TextEncoder !== "function") return show("unsupported");
    document.addEventListener("visibilitychange", onVisible);
    connectLoop(true);
  }

  // for tests and the curious
  window.deskdotJoin = {
    state: () => ({ code, linked: !!T.ch, link: T.pc && T.pc.connectionState, gameWritten, sockets: T.socks.size, screen: ui && !ui.veil.hidden ? ui.state : null }),
  };

  start();
})();
