/* DeskDot web app — the page host (docs/WEB_APP.md, ADR 0012).
 *
 * Loaded before the studio (a classic script, so it runs first). It:
 *   1. starts the engine worker (Pyodide + the real deskdot package),
 *   2. routes the studio's /api/* fetches and /ws sockets to that worker (fetch + WebSocket shims; the service
 *      worker routes <img src="/api/…"> the same way), so the studio code is unchanged,
 *   3. owns the panel's GATT session through Web Bluetooth (the bridge device/web.py drives),
 *   4. shows the landing card (what works here, browser support, the "Connect panel" button) and a small
 *      connection pill once the studio is up.
 */
(function () {
  "use strict";

  // <deskdot-logo> The DeskDot logo in LEDs: a plain-JS copy of web/src/lib/logo.ts (same glyphs, tubes, colours and
  // timings; tests/test_logo_copies.py keeps every copy identical). Three neon tubes, "D", "esk", "Dot": the D drops
  // in, "esk" types in, "Dot" rains down, then each tube is struck like neon, hums, powers down and loops. The canvas
  // redraws only while something moves (build, strike, the loose letter's blink, power-down), idles in between and
  // stops while the page is hidden; reduced motion draws it lit once. DeskDotLogo.mount(canvas, { pitch, grid, dpr }).
  const DeskDotLogo = (() => {
    const GLYPHS = {
      D: ["###.", "#..#", "#..#", "#..#", "#..#", "#..#", "###."],
      e: ["....", "....", ".##.", "#..#", "####", "#...", ".###"],
      s: ["....", "....", ".###", "#...", ".##.", "...#", "###."],
      k: ["#...", "#...", "#..#", "#.#.", "##..", "#.#.", "#..#"],
      o: ["....", "....", ".##.", "#..#", "#..#", "#..#", ".##."],
      t: ["...", ".#.", "###", ".#.", ".#.", ".#.", "..#"],
    };
    const TUBES = ["D", "esk", "Dot"];
    const LOGO = ["#ff3f78", "#ff3f78", "#ffcc33"];
    const STRIKE = [
      [[0.05, 1], [0.07, 0], [0.03, 0.7], [0.16, 0], [0.04, 1], [0.05, 0.15], [0.09, 0.55], [0.05, 0], [0.06, 0.9], [0.04, 0.4]],
      [[0.04, 0.6], [0.12, 0], [0.05, 1], [0.04, 0], [0.03, 1], [0.22, 0.05], [0.05, 0.8], [0.03, 0.2], [0.07, 1], [0.05, 0.5]],
      [[0.03, 0.8], [0.05, 0], [0.04, 0.5], [0.09, 0], [0.05, 1], [0.03, 0], [0.12, 0.3], [0.04, 1], [0.08, 0.1], [0.06, 0.85]],
    ];
    const DELAY = [0, 0.28, 0.12];
    const glitchLetter = 5;
    const ROWS = 7;
    const HEADER = { build: 1.5, hold: 14, off: 1.2 };
    const PAD = 2.2; // dots of room round the word for the glow

    const dots = [];
    let cols = 0;
    {
      const parts = [];
      let letter = 0;
      TUBES.forEach((w, part) => {
        if (part) cols += 1;
        const from = cols;
        [...w].forEach((ch, i) => {
          const g = GLYPHS[ch];
          if (i) cols += 1;
          g.forEach((row, y) => [...row].forEach((c, dx) => {
            if (c === "#") dots.push({ x: cols + dx, y, part, col: 0, seed: Math.random(), letter });
          }));
          cols += g[0].length;
          letter++;
        });
        parts.push({ from, to: cols });
      });
      for (const d of dots) {
        const p = parts[d.part];
        d.col = (d.x - p.from) / Math.max(1, p.to - p.from - 1);
      }
    }

    const strikeLen = (p) => STRIKE[p].reduce((n, [d]) => n + d, 0);
    const strike = (p, t) => {
      if (t < 0) return 0;
      let acc = 0;
      for (const [d, v] of STRIKE[p]) if (t < (acc += d)) return v;
      return 1;
    };
    const easeOut = (k) => 1 - (1 - k) ** 3;
    const bounce = (k) => {
      const n = 7.5625, d = 2.75;
      if (k < 1 / d) return n * k * k;
      if (k < 2 / d) return n * (k -= 1.5 / d) * k + 0.75;
      if (k < 2.5 / d) return n * (k -= 2.25 / d) * k + 0.9375;
      return n * (k -= 2.625 / d) * k + 0.984375;
    };
    let glows = null;
    const glowSprite = (color) => {
      const c = document.createElement("canvas");
      c.width = c.height = 64;
      const g = c.getContext("2d");
      const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      r.addColorStop(0, color);
      r.addColorStop(0.25, color + "aa");
      r.addColorStop(0.6, color + "22");
      r.addColorStop(1, color + "00");
      g.fillStyle = r;
      g.fillRect(0, 0, 64, 64);
      return c;
    };

    const tl = HEADER;
    const cycle = tl.build + 1.4 + tl.hold + tl.off;
    const igniteAt = tl.build + 0.15;
    const offAt = tl.build + 1.4 + tl.hold;
    const litAt = Math.max(tl.build + 0.6, igniteAt + Math.max(...[0, 1, 2].map((p) => DELAY[p] + strikeLen(p)))) + 0.05;

    /** Draw at (ox, oy) with dot pitch p (CSS px); lt = seconds into the loop. */
    function draw(ctx, lt, ox, oy, p, grid, still) {
      if (!glows) glows = LOGO.map(glowSprite);
      if (still) lt = tl.build + 3;
      const r = p * 0.36;
      if (grid) {
        ctx.fillStyle = "rgba(255,255,255,0.045)";
        for (let y = 0; y < ROWS; y++)
          for (let x = 0; x < cols; x++) {
            ctx.beginPath();
            ctx.arc(ox + (x + 0.5) * p, oy + (y + 0.5) * p, r * 0.7, 0, Math.PI * 2);
            ctx.fill();
          }
      }
      for (let part = 0; part < 3; part++) {
        let level = strike(part, lt - igniteAt - DELAY[part]);
        const lit = lt > igniteAt + DELAY[part] + strikeLen(part);
        if (lit) level = still ? 1 : 0.93 + 0.07 * Math.sin(lt * 47 + part * 3) * Math.sin(lt * 13.3);
        let dying = 0;
        if (lt > offAt) {
          dying = Math.min(1, (lt - offAt) / tl.off);
          const sputter = dying < 0.35 ? (Math.sin(lt * 90) > 0.2 ? 1 : 0.25) : 0;
          level = Math.max(0, 1 - dying * 2.4) * (0.5 + sputter * 0.5);
        }
        const color = LOGO[part], glow = glows[part];
        for (const d of dots) {
          if (d.part !== part) continue;
          let x = d.x, y = d.y, k, pop = 0;
          if (part === 0) {
            k = Math.min(1, Math.max(0, (lt - (6 - d.y) * 0.05) / 0.5));
            y = d.y - (1 - bounce(k)) * 9;
          } else if (part === 1) {
            k = Math.min(1, Math.max(0, (lt - (d.col * tl.build * 0.75 + d.y * 0.012)) / 0.22));
            pop = k > 0 && k < 1 ? Math.sin(k * Math.PI) : 0;
            x = d.x - (1 - easeOut(k)) * 1.2;
          } else {
            k = Math.min(1, Math.max(0, (lt - ((1 - d.col) * tl.build * 0.55 + d.seed * tl.build * 0.3)) / 0.55));
            y = d.y - (1 - bounce(k)) * (6 + d.y);
          }
          if (k <= 0) continue;
          let fade = 1;
          if (dying > 0.35) {
            const q = Math.min(1, Math.max(0, (dying - 0.35) / 0.65 - (part === 2 ? d.seed * 0.3 : d.col * 0.4)));
            fade = 1 - q;
            if (part !== 2) x += easeOut(q) * 3;
            else y += q * q * 9;
            if (fade <= 0) continue;
          }
          let lv = level;
          if (lit && !still && dying === 0 && d.letter === glitchLetter) {
            const g = (lt * 0.37) % 1;
            if (g > 0.62 && g < 0.645) lv *= 0.1;
            else if (g > 0.66 && g < 0.672) lv *= 0.3;
          }
          const cx = ox + (x + 0.5) * p, cy = oy + (y + 0.5) * p;
          ctx.globalAlpha = 0.22 * fade * Math.min(1, k * 2);
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(cx, cy, r * (1 + pop * 0.6), 0, Math.PI * 2);
          ctx.fill();
          const light = Math.max(lv, pop * 0.9) * fade;
          if (light > 0.02) {
            ctx.globalCompositeOperation = "lighter";
            ctx.globalAlpha = Math.min(0.5, light * 0.5);
            const gs = p * 3.4;
            ctx.drawImage(glow, cx - gs / 2, cy - gs / 2, gs, gs);
            ctx.globalAlpha = Math.min(1, light);
            ctx.beginPath();
            ctx.arc(cx, cy, r * (1 + pop * 0.5), 0, Math.PI * 2);
            ctx.fill();
            ctx.globalAlpha = Math.min(1, light * 0.5);
            ctx.fillStyle = "#fff4e0";
            ctx.beginPath();
            ctx.arc(cx, cy, r * 0.3, 0, Math.PI * 2);
            ctx.fill();
            ctx.globalCompositeOperation = "source-over";
          }
        }
      }
      ctx.globalAlpha = 1;
    }

    /** Seconds until the picture changes again (0 = it is moving now): the hold only wakes for the loose letter. */
    function wake(lt) {
      if (lt < litAt || lt >= offAt) return 0;
      const g = (lt * 0.37) % 1;
      if (g > 0.61 && g < 0.68) return 0;
      return Math.min(((1.61 - g) % 1) / 0.37, offAt - lt);
    }

    /** Animate the logo on `canvas`. pitch = CSS px per dot (omit to fit the canvas's CSS width); dpr = a function
     *  giving device px per CSS px (default devicePixelRatio, capped at 2). Returns { resize, restart }. */
    function mount(canvas, opts) {
      const o = opts || {};
      const ctx = canvas && canvas.getContext && canvas.getContext("2d");
      if (!ctx) return { resize() {}, restart() {} };
      const still = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
      const ratio = o.dpr || (() => Math.min(2, window.devicePixelRatio || 1));
      let p = 0, w = 0, h = 0, k = 0, t0 = performance.now(), raf = 0, timer = 0, drawn = false;
      const size = () => {
        const pp = o.pitch || (canvas.clientWidth || 0) / (cols + PAD * 2);
        const kk = ratio();
        if (!pp) return false;
        if (pp === p && kk === k) return true;
        p = pp;
        k = kk;
        w = (cols + PAD * 2) * p;
        h = (ROWS + PAD * 2) * p;
        canvas.width = Math.max(1, Math.round(w * k));
        canvas.height = Math.max(1, Math.round(h * k));
        if (o.pitch) canvas.style.width = w + "px";
        canvas.style.height = h + "px";
        return true;
      };
      const later = (s) => { timer = setTimeout(() => { timer = 0; kick(); }, s * 1000); };
      const tick = () => {
        raf = 0;
        if (document.hidden) return; // visibilitychange wakes it
        if (!canvas.isConnected && drawn) return document.removeEventListener("visibilitychange", onVis); // removed
        if (!canvas.getClientRects().length || !size()) return later(1); // not on screen (yet): look again in a second
        drawn = true;
        const lt = ((performance.now() - t0) / 1000) % cycle;
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.clearRect(0, 0, w, h);
        draw(ctx, lt, PAD * p, PAD * p, p, !!o.grid, still);
        if (still) return;
        const s = wake(lt);
        if (s > 0) later(s);
        else raf = requestAnimationFrame(tick);
      };
      function kick() {
        if (!raf && !timer) raf = requestAnimationFrame(tick);
      }
      const now = () => {
        clearTimeout(timer);
        timer = 0;
        kick();
      };
      function onVis() {
        if (!document.hidden) return now();
        clearTimeout(timer);
        timer = 0;
      }
      document.addEventListener("visibilitychange", onVis);
      if (window.ResizeObserver && !o.pitch) new ResizeObserver(now).observe(canvas);
      kick();
      return {
        resize: now,
        restart() {
          t0 = performance.now();
          now();
        },
      };
    }

    return { mount, cols, rows: ROWS, pad: PAD };
  })();
  // </deskdot-logo>

  const BASE = new URL(".", document.currentScript ? document.currentScript.src : location.href);
  const APP = new URL("../", BASE); // …/app/
  const VERSION = document.currentScript ? new URL(document.currentScript.src).search : ""; // ?v=<build>, for add-ons
  const SERVICE = "000000fa-0000-1000-8000-00805f9b34fb";
  const WRITE = "0000fa02-0000-1000-8000-00805f9b34fb";
  const NOTIFY = "0000fa03-0000-1000-8000-00805f9b34fb";
  const STEP_DOWN = [244, 182, 20]; // packet sizes to fall back to when the stack refuses a longer write
  const LS = {
    get(k) {
      try {
        return localStorage.getItem(k);
      } catch {
        return null;
      }
    },
    set(k, v) {
      try {
        if (v == null) localStorage.removeItem(k);
        else localStorage.setItem(k, v);
      } catch {
        /* private mode */
      }
    },
  };

  // ======================================================================================= browser support
  const ua = navigator.userAgent;
  const isIOS = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/.test(ua);
  const isMac = /Macintosh/.test(ua) && !isIOS;
  const isFirefox = /Firefox\//.test(ua);
  const isSafari = /Safari\//.test(ua) && !/Chrome\/|Chromium\/|Edg\//.test(ua);
  const isLinux = /Linux/.test(ua) && !isAndroid && !/CrOS/.test(ua);
  const hasBluetooth = !!navigator.bluetooth && typeof navigator.bluetooth.requestDevice === "function";

  function unsupportedReason() {
    if (hasBluetooth) return null;
    if (!window.isSecureContext) return "Bluetooth needs a secure page: open https://idotmatrix.com/app/.";
    if (isIOS)
      return 'iPhone and iPad browsers can\'t use Bluetooth from a web page (Apple doesn\'t support Web Bluetooth). Install the free <b>Bluefy – Web BLE Browser</b> app and open <b>idotmatrix.com/app</b> in it, or use the desktop app.';
    if (isFirefox) return "Firefox doesn't support Web Bluetooth. Open this page in <b>Chrome</b>, <b>Edge</b> or <b>Opera</b>, or use the desktop app.";
    if (isSafari) return "Safari doesn't support Web Bluetooth. Open this page in <b>Chrome</b> or <b>Edge</b> for Mac, or use the desktop app.";
    if (/Brave/.test(ua) || navigator.brave) return "Brave turns Web Bluetooth off. Enable it at <b>brave://flags/#brave-web-bluetooth-api</b> and restart, or use Chrome or Edge.";
    if (isLinux)
      return "Chrome on Linux keeps Web Bluetooth behind a flag: enable <b>chrome://flags/#enable-experimental-web-platform-features</b> and restart, or use the desktop app.";
    return "This browser doesn't support Web Bluetooth. Use <b>Chrome</b>, <b>Edge</b> or <b>Opera</b> on Windows, macOS, ChromeOS, Linux or Android.";
  }

  /** Bytes per GATT write. Browsers don't expose the MTU, so guess per OS; the user can override it. */
  function packetSize() {
    const pick = Number(LS.get("deskdot.web.packet") || 0);
    if (pick >= 20) return pick;
    if (isAndroid) return 20; // Chrome on Android doesn't raise the MTU and silently truncates longer writes
    if (isMac) return 182;
    return 512; // Windows / ChromeOS / Linux negotiate MTU 517; a refused write steps down automatically
  }

  // ======================================================================================= engine worker
  const pending = new Map(); // http id -> {resolve, reject}
  const sockets = new Map(); // sid -> EngineSocket
  let seq = 0;
  let readyResolve;
  const engineReady = new Promise((r) => (readyResolve = r));
  let worker = null;
  let engineState = "booting"; // booting | ready | fatal | busy-tab | unsupported-runtime

  function startWorker() {
    worker = new Worker(new URL("engine/worker.js", APP));
    worker.onmessage = (e) => onWorker(e.data);
    worker.onerror = (e) => ui.fatal(e.message || "the engine worker crashed");
  }

  function onWorker(m) {
    switch (m.t) {
      case "status":
        return ui.progress(m.phase, m.detail, m.pct);
      case "ready":
        engineState = "ready";
        readyResolve();
        return ui.ready(m.version);
      case "fatal":
        engineState = "fatal";
        return ui.fatal(m.error);
      case "http": {
        const p = pending.get(m.id);
        if (!p) return;
        pending.delete(m.id);
        return p.resolve(m);
      }
      case "ws": {
        const s = sockets.get(m.sid);
        if (s) s._event(m.ev, m.data);
        return;
      }
      case "ble":
        return ble.request(m);
      default:
        for (const fn of addonListeners) {
          try {
            fn(m);
          } catch (e) {
            console.warn("DeskDot add-on", e);
          }
        }
    }
  }

  /** One request to the in-browser engine. Returns {status, headers: [[k, v]], body: ArrayBuffer|null}. */
  async function engineRequest(method, path, headers, body, client) {
    await engineReady;
    const id = ++seq;
    return new Promise((resolve) => {
      pending.set(id, { resolve });
      worker.postMessage({ t: "http", id, method, path, headers, body, client: client || null }, body ? [body] : []);
    });
  }

  const NULL_BODY = new Set([101, 103, 204, 205, 304]);
  function toResponse(r) {
    return new Response(NULL_BODY.has(r.status) ? null : r.body, { status: r.status, headers: r.headers });
  }

  function isEnginePath(u) {
    return u.origin === location.origin && (u.pathname.startsWith("/api/") || u.pathname === "/api");
  }

  // ----------------------------------------------------------------------------------------- fetch shim
  const realFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const req = new Request(input, init);
    const u = new URL(req.url);
    if (!isEnginePath(u)) return realFetch(input, init);
    const body = ["GET", "HEAD"].includes(req.method) ? null : await req.arrayBuffer();
    const r = await engineRequest(req.method, u.pathname + u.search, [...req.headers], body && body.byteLength ? body : null);
    return toResponse(r);
  };

  // ------------------------------------------------------------------------------------- WebSocket shim
  const RealWebSocket = window.WebSocket;
  let sidSeq = 0;
  class EngineSocket extends EventTarget {
    constructor(url, client) {
      super();
      this.url = url;
      this.readyState = 0;
      this.binaryType = "blob";
      this.protocol = "";
      this.extensions = "";
      this.bufferedAmount = 0;
      this.onopen = this.onmessage = this.onclose = this.onerror = null;
      this._sid = ++sidSeq;
      sockets.set(this._sid, this);
      const u = new URL(url);
      const path = u.pathname + u.search; // phones reconnect to their seat with /ws/p/<code>?cid=…
      engineReady.then(() => {
        if (this.readyState === 0) worker.postMessage({ t: "ws-open", sid: this._sid, path, client: client || null });
      });
    }
    send(data) {
      if (this.readyState !== 1) throw new DOMException("WebSocket is not open", "InvalidStateError");
      if (typeof data === "string") worker.postMessage({ t: "ws-send", sid: this._sid, data });
      else if (data instanceof ArrayBuffer) worker.postMessage({ t: "ws-send", sid: this._sid, data: data.slice(0) });
      else if (ArrayBuffer.isView(data)) worker.postMessage({ t: "ws-send", sid: this._sid, data: data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) });
      else if (data instanceof Blob) data.arrayBuffer().then((b) => this.readyState === 1 && worker.postMessage({ t: "ws-send", sid: this._sid, data: b }));
    }
    close(code) {
      if (this.readyState >= 2) return;
      this.readyState = 2;
      if (worker) worker.postMessage({ t: "ws-close", sid: this._sid, code: code || 1000 });
      else this._event("close", 1000);
    }
    _fire(type, ev) {
      this.dispatchEvent(ev);
      const h = this["on" + type];
      if (typeof h === "function") h.call(this, ev);
    }
    _event(ev, data) {
      if (ev === "open") {
        this.readyState = 1;
        this._fire("open", new Event("open"));
      } else if (ev === "text") {
        this._fire("message", new MessageEvent("message", { data, origin: location.origin }));
      } else if (ev === "bytes") {
        const payload = this.binaryType === "arraybuffer" ? data : new Blob([data]);
        this._fire("message", new MessageEvent("message", { data: payload, origin: location.origin }));
      } else if (ev === "close") {
        if (this.readyState === 3) return;
        this.readyState = 3;
        sockets.delete(this._sid);
        this._fire("close", new CloseEvent("close", { code: data || 1000, wasClean: true }));
      }
    }
  }
  for (const [k, v] of Object.entries({ CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 })) {
    EngineSocket[k] = v;
    EngineSocket.prototype[k] = v;
  }
  function WebSocketShim(url, protocols) {
    const u = new URL(url, location.href);
    if (u.host === location.host && (u.pathname === "/ws" || u.pathname.startsWith("/ws/")))
      return new EngineSocket(u.href);
    return protocols === undefined ? new RealWebSocket(url) : new RealWebSocket(url, protocols);
  }
  WebSocketShim.prototype = RealWebSocket.prototype;

  /**
   * For the add-on scripts loaded below (host-*.js): the engine as an API. `client` is the address the engine sees
   * (a phone tunnelled in over WebRTC must not look like this tab, which is 127.0.0.1).
   *   request(method, path, headers, body?: ArrayBuffer, client?) -> {status, headers: [[k, v]], body: ArrayBuffer|null}
   *   socket(path, client?) -> a WebSocket-like object (onopen/onmessage/onclose, send, close)
   *   post(msg) -> a raw message to the engine worker;  onMessage(fn) -> fn(msg) for worker messages host.js doesn't own
   */
  const addonListeners = [];
  window.DeskDotHost = {
    ready: engineReady,
    request: engineRequest,
    socket: (path, client) => new EngineSocket(new URL(path, location.href).href, client),
    post: (msg, transfer) => engineReady.then(() => worker.postMessage(msg, transfer || [])),
    onMessage: (fn) => addonListeners.push(fn),
    origin: location.origin,
  };
  Object.assign(WebSocketShim, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
  window.WebSocket = WebSocketShim;

  // -------------------------------------------------------------------- service worker (+ <img> requests)
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", async (e) => {
      const m = e.data || {};
      if (m.t !== "sw-api" || !e.ports[0]) return;
      try {
        const r = await engineRequest(m.method, m.path, m.headers || [], m.body || null);
        e.ports[0].postMessage({ status: r.status, headers: r.headers, body: r.body }, r.body ? [r.body] : []);
      } catch (err) {
        e.ports[0].postMessage({ status: 502, headers: [], body: null, error: String(err) });
      }
    });
    navigator.serviceWorker.register(new URL("sw.js", APP), { scope: APP.pathname }).catch((err) => console.warn("DeskDot: service worker", err));
  }

  // ======================================================================================= Web Bluetooth
  const ble = {
    device: null, // the BluetoothDevice the user picked (or the browser remembered)
    write: null,
    notify: null,
    size: packetSize(),
    state: "idle", // idle | needs-user | connecting | connected | error
    detail: "",
    connecting: false,
    chain: Promise.resolve(),

    toWorker(ev, ...args) {
      if (worker) worker.postMessage({ t: "ble-ev", ev, args });
    },
    set(state, detail) {
      this.state = state;
      this.detail = detail || "";
      ui.link(state, this.detail, this.device && this.device.name);
    },

    request(m) {
      if (m.op === "connect") return this.connect();
      if (m.op === "write") return this.enqueue(m.data, m.withResponse, m.token);
      if (m.op === "disconnect") return this.disconnect();
    },

    async remembered() {
      if (!navigator.bluetooth || !navigator.bluetooth.getDevices) return null;
      try {
        const list = (await navigator.bluetooth.getDevices()).filter((d) => (d.name || "").startsWith("IDM-"));
        const id = LS.get("deskdot.web.panel");
        return list.find((d) => d.id === id) || list[0] || null;
      } catch {
        return null;
      }
    },

    async connect() {
      if (this.connecting) return; // the running attempt reports for this request too
      if (!hasBluetooth) {
        this.set("needs-user", "This browser can't use Bluetooth");
        return this.toWorker("onNeedsUser", "This browser can't reach the panel (no Web Bluetooth). The studio works; the panel needs Chrome, Edge or the desktop app.");
      }
      if (!this.device) this.device = await this.remembered();
      if (!this.device) {
        this.set("needs-user", "Pick your panel to connect");
        return this.toWorker("onNeedsUser", "Click “Connect panel” and pick your IDM-… panel");
      }
      this.connecting = true;
      const dev = this.device;
      this.set("connecting", `Connecting to ${dev.name || "the panel"}…`);
      try {
        if (!dev._ddWatched) {
          dev._ddWatched = true;
          dev.addEventListener("gattserverdisconnected", () => this.lost(dev));
        }
        await this.wake(dev);
        const server = await dev.gatt.connect();
        const service = await server.getPrimaryService(SERVICE);
        this.write = await service.getCharacteristic(WRITE);
        try {
          this.notify = await service.getCharacteristic(NOTIFY);
          this.notify.addEventListener("characteristicvaluechanged", (ev) => {
            const v = ev.target.value;
            this.toWorker("onNotify", new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength)));
          });
          await this.notify.startNotifications();
        } catch (e) {
          console.info("DeskDot: ack notifications unavailable", e); // acks are an optimisation
        }
        this.size = packetSize();
        LS.set("deskdot.web.panel", dev.id);
        this.set("connected", `${dev.name || "Panel"} · ${this.size}-byte packets`);
        this.toWorker("onConnected", "web:" + dev.id, dev.name || "IDM-panel", this.size);
      } catch (e) {
        const msg = explain(e);
        this.set("error", msg);
        this.toWorker("onConnectFailed", msg);
      } finally {
        this.connecting = false;
      }
    },

    /** A device remembered from an earlier visit must be seen advertising before Chrome can connect to it. */
    async wake(dev) {
      if (dev.gatt.connected || typeof dev.watchAdvertisements !== "function") return;
      const ctl = new AbortController();
      await new Promise((res) => {
        const t = setTimeout(res, 6000);
        dev.addEventListener("advertisementreceived", () => (clearTimeout(t), res()), { once: true });
        dev.watchAdvertisements({ signal: ctl.signal }).catch(() => (clearTimeout(t), res()));
      });
      ctl.abort();
    },

    lost(dev) {
      if (dev !== this.device) return;
      this.write = this.notify = null;
      this.set("error", "Link lost — reconnecting…");
      this.toWorker("onDisconnected", "link lost (gattserverdisconnected)");
    },

    disconnect() {
      // only on the user's request (Settings → Device → link off, or Reconnect): never voluntarily
      const dev = this.device;
      this.write = this.notify = null;
      if (dev && dev.gatt.connected) dev.gatt.disconnect();
      this.set("idle", "Unlinked");
    },

    enqueue(data, withResponse, token) {
      this.chain = this.chain.then(() => this.send(data, withResponse, token));
    },

    async send(data, withResponse, token) {
      const ch = this.write;
      if (!ch) return this.toWorker("onWriteDone", token, false, "not connected");
      try {
        await (withResponse ? ch.writeValueWithResponse(data) : ch.writeValueWithoutResponse(data));
        this.toWorker("onWriteDone", token, true, "");
      } catch (e) {
        // The stack refused a packet this long (no MTU API in browsers): re-send it in smaller, paced pieces and
        // tell the engine the size that works. A real link failure falls through to an error.
        const smaller = STEP_DOWN.find((n) => n < data.length && n < this.size);
        if (smaller && this.device && this.device.gatt.connected) {
          try {
            for (let i = 0; i < data.length; i += smaller) {
              if (i) await new Promise((r) => setTimeout(r, 20));
              const part = data.slice(i, i + smaller);
              await (withResponse ? ch.writeValueWithResponse(part) : ch.writeValueWithoutResponse(part));
            }
            this.size = smaller;
            console.info(`DeskDot: the link refused ${data.length}-byte packets; using ${smaller}`);
            this.toWorker("onWriteSize", smaller);
            this.set("connected", `${this.device.name || "Panel"} · ${smaller}-byte packets`);
            return this.toWorker("onWriteDone", token, true, "");
          } catch (e2) {
            e = e2;
          }
        }
        this.toWorker("onWriteDone", token, false, explain(e));
      }
    },

    /** The "Connect panel" click: the user gesture Web Bluetooth requires for its chooser. */
    async pick() {
      if (!hasBluetooth) return ui.toast(unsupportedReason(), true);
      try {
        if (navigator.bluetooth.getAvailability && !(await navigator.bluetooth.getAvailability()))
          return ui.toast("Bluetooth is off, or this computer has no Bluetooth adapter. Turn it on and try again.", true);
      } catch {
        /* not implemented: let the chooser say it */
      }
      let dev;
      try {
        dev = await navigator.bluetooth.requestDevice({ filters: [{ namePrefix: "IDM-" }], optionalServices: [SERVICE] });
      } catch (e) {
        if (e && e.name === "NotFoundError")
          return ui.toast(
            "No panel picked. Not in the list? It's off, out of range, or still connected to the iDotMatrix phone app or the DeskDot desktop / Android app — close those first (only one app can hold the panel).",
            true,
          );
        return ui.toast(explain(e), true);
      }
      if (this.device && this.device !== dev && this.device.gatt.connected) this.device.gatt.disconnect();
      this.device = dev;
      LS.set("deskdot.web.panel", dev.id);
      ui.dismissLanding();
      if (worker) worker.postMessage({ t: "ble-picked" });
    },
  };

  function explain(e) {
    const name = (e && e.name) || "";
    const msg = (e && e.message) || String(e);
    if (name === "SecurityError") return "Bluetooth permission was blocked for this site. Allow it in the address bar's site settings, then click Connect panel.";
    if (name === "NetworkError" || /GATT|connect|range|disconnected/i.test(msg))
      return "The panel didn't answer. Is it powered and close by, and not connected to the iDotMatrix phone app, the DeskDot desktop app or the Android app? " + `(${msg})`;
    if (name === "NotFoundError") return "This panel doesn't offer the expected Bluetooth service — is it an iDotMatrix 32×32?";
    return msg;
  }

  // ======================================================================================= UI
  const ui = (function () {
    const host = document.createElement("div");
    host.id = "deskdot-web-host";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<link rel="stylesheet" href="${new URL("host.css", BASE).href}">
<div class="landing" part="landing" role="dialog" aria-modal="true" aria-labelledby="dd-title">
  <div class="card">
    <div class="brand"><canvas class="logo" role="img" aria-label="DeskDot, written in glowing LED dots"></canvas>IN YOUR BROWSER</div>
    <h1 id="dd-title">Your panel, straight from this tab</h1>
    <p class="lede">The full DeskDot engine runs right here (Python in WebAssembly). Pick your iDotMatrix panel and
    everything you do in the studio shows on it — no install.</p>
    <div class="support" hidden></div>
    <div class="boot"><div class="bar"><i></i></div><div class="phase">Starting…</div></div>
    <div class="actions">
      <button class="key ember connect" type="button">Connect panel</button>
      <button class="key ghost open" type="button">Open studio</button>
    </div>
    <p class="hint">The panel must be on and <b>not connected to another app</b> (the iDotMatrix phone app, the DeskDot
    desktop or Android app): a panel talks to one app at a time.</p>
    <details>
      <summary>What works in the browser</summary>
      <div class="cols">
        <div><h3>Works here</h3><ul>
          <li>Every game, clock, timer, pet, loop and creative app</li>
          <li>Live data: weather, sports, markets, flights, space, quakes, news…</li>
          <li>Playlists, presets, autopilot, notifications &amp; text</li>
          <li>Drawing, photo / GIF upload, AI creator, Font Lab</li>
          <li>Calibration, brightness, night mode, all settings</li>
          <li>Camera &amp; Screen mirror, Visualizer (the browser asks first)</li>
          <li>Settings are saved in this browser</li>
        </ul></div>
        <div><h3>Needs the desktop app</h3><ul>
          <li>Now Playing, Active App, face tracking</li>
          <li>System Monitor, On Air, idle eye-break</li>
          <li>OS notification mirroring, sleep hand-off</li>
          <li>Phone multiplayer over Wi-Fi, Claude Code / MCP</li>
          <li>Services on your LAN (OBS, printer, Home Assistant)</li>
        </ul></div>
      </div>
      <p class="small">The panel only runs while this tab is open (it can be in the background). For 24/7, use the
      desktop app, a Raspberry Pi or the Android app — <a href="/guide.html" target="_top">setup guide</a>.</p>
    </details>
  </div>
</div>
<div class="pill" hidden>
  <span class="led"></span><span class="txt">Panel not connected</span>
  <button class="key small connect2" type="button">Connect panel</button>
  <select class="speed" title="Bluetooth packet size (link speed)">
    <option value="">Auto</option><option value="20">20 B · safest</option><option value="182">182 B</option>
    <option value="244">244 B</option><option value="512">512 B · fastest</option>
  </select>
  <button class="x" type="button" title="Hide" aria-label="Hide">×</button>
</div>
<div class="toast" role="status" hidden></div>`;
    const $ = (s) => root.querySelector(s);
    DeskDotLogo.mount($(".logo"), { pitch: 3.6, grid: true }); // draws once the card is on the page
    const mount = () => document.body.appendChild(host);
    if (document.body) mount();
    else document.addEventListener("DOMContentLoaded", mount);

    const landing = $(".landing");
    const pill = $(".pill");
    let toastTimer = 0;
    let isReady = false;

    const reason = unsupportedReason();
    if (reason) {
      const s = $(".support");
      s.hidden = false;
      s.innerHTML = `<b>Bluetooth isn't available here.</b> ${reason} <span class="small">You can still use the studio and its live preview.</span>`;
      $(".connect").disabled = true;
    } else if (navigator.bluetooth.getAvailability) {
      navigator.bluetooth.getAvailability().then((ok) => {
        if (ok) return;
        const s = $(".support");
        s.hidden = false;
        s.innerHTML = "<b>Bluetooth is off</b> (or this computer has no adapter). Turn it on to connect the panel.";
      }, () => {});
    }

    $(".connect").addEventListener("click", () => ble.pick());
    $(".connect2").addEventListener("click", () => ble.pick());
    $(".open").addEventListener("click", () => dismissLanding());
    $(".x").addEventListener("click", () => (pill.classList.add("min")));
    pill.addEventListener("click", (e) => {
      if (pill.classList.contains("min") && e.target === pill) pill.classList.remove("min");
    });
    const speed = $(".speed");
    speed.value = LS.get("deskdot.web.packet") || "";
    speed.addEventListener("change", () => {
      LS.set("deskdot.web.packet", speed.value || null);
      toast(`Packet size: ${speed.value ? speed.value + " bytes" : "automatic"}. Applies on the next connect — use Settings → Device → Reconnect.`);
    });
    if (hasBluetooth) {
      ble.remembered().then((d) => {
        if (d && LS.get("deskdot.web.seen")) dismissLanding(); // returning visitor with a remembered panel
      });
    }

    function dismissLanding() {
      landing.classList.add("gone");
      setTimeout(() => (landing.hidden = true), 300);
      LS.set("deskdot.web.seen", "1");
      if (isReady) pill.hidden = false;
    }

    function toast(html, bad) {
      const t = $(".toast");
      t.innerHTML = html;
      t.classList.toggle("bad", !!bad);
      t.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => (t.hidden = true), bad ? 12000 : 5000);
    }

    return {
      dismissLanding,
      toast,
      progress(phase, detail, pct) {
        $(".phase").textContent = detail || phase;
        if (pct != null) $(".bar i").style.width = Math.max(3, pct) + "%";
      },
      ready() {
        isReady = true;
        $(".boot").classList.add("done");
        $(".phase").textContent = "Engine running in this tab";
        if (landing.hidden || landing.classList.contains("gone")) pill.hidden = false;
      },
      fatal(err) {
        $(".boot").classList.add("bad");
        $(".phase").innerHTML = `The engine couldn't start: ${String(err).replace(/</g, "&lt;")}. <a href="" target="_top">Reload</a> — if it keeps failing, use the desktop app.`;
        landing.hidden = false;
        landing.classList.remove("gone");
      },
      blocked(html) {
        $(".boot").classList.add("bad");
        $(".phase").innerHTML = html;
        $(".connect").disabled = true;
        $(".open").disabled = true;
      },
      link(state, detail, name) {
        const led = $(".pill .led");
        led.dataset.on = state === "connected" ? "ok" : state === "connecting" ? "warn" : state === "error" ? "bad" : "";
        $(".pill .txt").textContent =
          state === "connected" ? detail : state === "connecting" ? detail : state === "error" ? detail : name ? `${name} — not connected` : "Panel not connected";
        $(".connect2").hidden = state === "connected" || state === "connecting";
        if (state === "error") pill.classList.remove("min");
      },
    };
  })();

  // ======================================================================================= start
  // One tab owns the panel (rule 4: exactly one BLE owner). A second tab would interleave packets on the same link.
  window.addEventListener("pagehide", () => worker && worker.postMessage({ t: "sync" }));
  document.addEventListener("visibilitychange", () => document.hidden && worker && worker.postMessage({ t: "sync" }));
  if (typeof WebAssembly !== "object") {
    engineState = "unsupported-runtime";
    ui.blocked("This browser can't run WebAssembly, which the engine needs. Use a current Chrome, Edge, Firefox or Safari.");
  } else if (navigator.locks && navigator.locks.request) {
    navigator.locks.request("deskdot-web-engine", { ifAvailable: true }, (lock) => {
      if (!lock) {
        engineState = "busy-tab";
        ui.blocked("DeskDot is already open in another tab or window — only one can drive the panel. Switch to it, or close it and reload this one.");
        return undefined;
      }
      startWorker();
      return new Promise(() => {}); // hold the lock for this tab's lifetime
    });
  } else {
    startWorker();
  }

  // for tests and the curious: window.deskdotWeb.state()
  window.deskdotWeb = {
    state: () => ({ engine: engineState, link: ble.state, detail: ble.detail, packet: ble.size, bluetooth: hasBluetooth }),
    request: engineRequest,
  };

  // add-ons (built next to host.js by scripts/build_webapp.py): online play with friends, camera / screen / mic
  for (const name of ["host-rtc.js", "host-media.js"]) {
    const el = document.createElement("script");
    el.src = new URL(name + VERSION, BASE).href;
    el.async = true;
    document.head.appendChild(el);
  }
})();
