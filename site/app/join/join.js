/* DeskDot join page — a phone joining a game that runs in someone's web-app tab (docs/WEB_APP.md,
 * "Play with friends over the internet").
 *
 * Served at idotmatrix.com/p/<code> (netlify.toml rewrites /p/* to /app/join/index.html). There is no server that
 * runs the game: the engine lives in the host's browser tab. This page:
 *
 *   1. swaps one WebRTC offer/answer with that tab through /app/signal (non-trickle ICE, STUN only);
 *   2. asks the tab for /p/<code> over the data channel (does the room exist? a casino table or a game pad?) — or,
 *      at /tv/<code>, for the TV view (docs/TV_VIEW.md: the `tv` page, its scripts in /app/join/tv/);
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

  const W = window.DeskDotWire;
  const SELF = document.currentScript ? new URL(document.currentScript.src) : new URL("/app/join/join.js", location.href);
  const VERSION = SELF.search; // ?v=<build>
  const code = (location.pathname.split("/").filter(Boolean).pop() || "").toUpperCase();
  // /tv/<code>: a TV watching the host's panel (docs/TV_VIEW.md) — same link, the read-only TV page instead of a pad
  const isTv = /^\/tv\//.test(location.pathname);
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
  if (isTv) {
    Object.assign(SCREENS, {
      connecting: { tone: "busy", title: "Connecting to DeskDot…", text: "This screen is linking straight to the browser tab running DeskDot." },
      reconnecting: { tone: "busy", title: "Reconnecting to DeskDot…", text: "The link dropped for a moment." },
      loading: { tone: "busy", title: "Connected!", text: "Loading the TV view…" },
      "no-room": { tone: "bad", title: "No TV link with this code", text: "Open Show on TV in DeskDot again, then use the new address.", button: "Try again" },
      expired: { tone: "bad", title: "This TV link has closed", text: "Open Show on TV in DeskDot again, then use the new address.", button: "Try again" },
      closed: { tone: "warn", title: "This TV link has closed", text: "Open Show on TV in DeskDot again, then use the new address.", button: "Try again" },
      "bad-code": { tone: "bad", title: "That TV link doesn't look right", text: "Use the address Show on TV shows in DeskDot." },
    });
  }

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
    chip.append(el("span", null, isTv ? "TV" : "Room"), el("b", null, code));
    const step = el("div", "step");
    const button = el("button");
    button.type = "button";
    button.addEventListener("click", retry);
    const note = el("div", "note", "DeskDot · the game runs in the host's browser tab");
    const logo = el("canvas", "logo");
    logo.setAttribute("role", "img");
    logo.setAttribute("aria-label", "DeskDot, written in glowing LED dots");
    card.append(logo, el("div", "brand", isTv ? "TV view" : "Play with friends"), dots, title, text, tips, chip, step, button, note);
    veil.appendChild(card);
    root.append(css, veil);
    (document.body || document.documentElement).appendChild(host);
    DeskDotLogo.mount(logo, { pitch: 5, grid: true });
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
      const m = await tunnelRequest(isTv ? `/tv/${code}` : `/p/${code}`, [["accept", "text/html"]]);
      if (m.s === 404) return show("expired");
      if (m.s !== 200) return show("server", `The host answered ${m.s}.`);
      // which phone page the engine serves for this room: a casino table or a game pad
      const html = m.b ? W.utf8(W.unb64(m.b)) : "";
      const kind = isTv ? "tv" : html.includes("DeskDotCasino") ? "casino" : "controller";
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
