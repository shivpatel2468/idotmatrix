/* DeskDot web app — the page host (docs/WEB_APP.md, ADR 0012).
 *
 * Loaded before the studio (a classic script, so it runs first). It:
 *   1. starts the engine worker (Pyodide + the real deskdot package),
 *   2. routes the studio's /api/* fetches and /ws sockets to that worker (fetch + WebSocket shims; the service
 *      worker routes <img src="/api/…"> the same way), so the studio code is unchanged,
 *   3. owns the panel's GATT session through Web Bluetooth (the bridge device/web.py drives),
 *   4. shows the landing card (what works here, browser support, the "Connect panel" button) and a small
 *      connection pill until the studio's own pill takes over (window.deskdotWeb.attachStudio),
 *   5. hands the panel between tabs of this browser without a reload ("Use it here" / "Take it back"), and tells the
 *      studio's Connection sheet what it knows (window.deskdotWeb + "deskdot-web" events). docs/WEB_APP.md.
 */
(function () {
  "use strict";

  // The studio theme before first paint (the website's CSP blocks index.html's inline copy of this): localStorage
  // deskdot.theme = light | dark (default, first run) | system → <html data-theme>, as web/src/lib/theme.ts does.
  try {
    let pref = "dark";
    try { pref = localStorage.getItem("deskdot.theme") || "dark"; } catch { /* storage blocked */ }
    const t = pref === "light" || pref === "dark" ? pref : matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
    document.documentElement.style.colorScheme = t;
  } catch { /* never block the host */ }
  // Liquid Glass before first paint (web/src/lib/glass.ts refines it once the studio loads; the same rules as the inline
  // script in web/index.html): solid for reduced transparency; frosted — near opaque, no blur — without backdrop-filter
  // or inside the Android app (its WebView let content show through translucent bars); clear glass otherwise.
  try {
    let g = "auto";
    try { g = localStorage.getItem("deskdot.glass") || "auto"; } catch { /* storage blocked */ }
    const blur = !!(window.CSS && (CSS.supports("backdrop-filter", "blur(1px)") || CSS.supports("-webkit-backdrop-filter", "blur(1px)")));
    const rt = !!(window.matchMedia && matchMedia("(prefers-reduced-transparency: reduce)").matches);
    document.documentElement.setAttribute("data-glass", rt || g === "solid" ? "solid" : g === "frosted" || !blur || (g !== "liquid" && window.DeskDotAndroid) ? "frosted" : "liquid");
  } catch { /* never block the host */ }
  // The page theme (web/src/lib/pageTheme.ts) the studio cached on the last visit, before first paint. A constructed
  // stylesheet, so the website's CSP (no inline styles) can't block it; the studio takes over once it loads. The
  // website's pick (deskdot.siteTheme) leads: when it is another table, the studio's default sheet shows until the
  // studio paints that one.
  try {
    const id = localStorage.getItem("deskdot.pageTheme"), css = localStorage.getItem("deskdot.pageThemeCss");
    const site = localStorage.getItem("deskdot.siteTheme");
    if (id && css && (!site || site === id) && document.adoptedStyleSheets && "replaceSync" in CSSStyleSheet.prototype) {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(css);
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
      document.documentElement.setAttribute("data-page-theme", id);
    }
  } catch { /* the default look */ }

  // <deskdot-logo> The DeskDot logo in LEDs: a plain-JS copy of web/src/lib/logo.ts (same glyphs, tubes, colours,
  // styles and timings; tests/test_logo_copies.py keeps every copy identical). Three neon tubes, "D", "esk", "Dot": the
  // D drops in, "esk" types in, "Dot" rains down, then each tube is struck like neon, hums, powers down and loops. The
  // canvas redraws only while something moves (build, strike, the loose letter's blink, power-down), idles in between
  // and stops while the page is hidden; reduced motion draws it lit once. It follows the page's light / dark: dark draws
  // neon on black, light the "paper" style (ink tubes), straight on the page — no sign or plate
  // behind it in either theme. DeskDotLogo.mount(canvas, { pitch, grid, dpr, once, light }).
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
    const NEON_STYLE = { grid: "rgba(255,255,255,0.045)", glass: 0.22, halo: 0.5, blend: "lighter", fill: "lighter", core: "#fff4e0", coreAlpha: 0.5 };
    const PAPER_STYLE = { tubes: ["#c2154d", "#c2154d", "#996300"], grid: "rgba(74,58,36,0.13)", glass: 0.13, halo: 0.26, blend: "multiply", fill: "source-over", core: "#fff6ea", coreAlpha: 0.3 };
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
    const glows = {};
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

    /** Draw at (ox, oy) with dot pitch p (CSS px); lt = seconds into the loop; look = "neon" | "paper". */
    function draw(ctx, lt, ox, oy, p, grid, still, look) {
      const st = look === "paper" ? PAPER_STYLE : NEON_STYLE;
      const tubes = look === "paper" ? PAPER_STYLE.tubes : LOGO;
      const gl = glows[look] || (glows[look] = tubes.map((c) => glowSprite(c)));
      if (still) lt = tl.build + 3;
      const r = p * 0.36;
      if (grid) {
        ctx.fillStyle = st.grid;
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
        const color = tubes[part], glow = gl[part];
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
          ctx.globalAlpha = st.glass * fade * Math.min(1, k * 2);
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(cx, cy, r * (1 + pop * 0.6), 0, Math.PI * 2);
          ctx.fill();
          const light = Math.max(lv, pop * 0.9) * fade;
          if (light > 0.02) {
            ctx.globalCompositeOperation = st.blend;
            ctx.globalAlpha = Math.min(st.halo, light * st.halo);
            const gs = p * 3.4;
            ctx.drawImage(glow, cx - gs / 2, cy - gs / 2, gs, gs);
            ctx.globalCompositeOperation = st.fill;
            ctx.globalAlpha = Math.min(1, light);
            ctx.beginPath();
            ctx.arc(cx, cy, r * (1 + pop * 0.5), 0, Math.PI * 2);
            ctx.fill();
            ctx.globalAlpha = Math.min(1, light * st.coreAlpha);
            ctx.fillStyle = st.core;
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
     *  giving device px per CSS px (default devicePixelRatio, capped at 2); once = build in once, then hold it lit;
     *  light = a function answering "is this page light?" (default: a shadow host's or <html>'s data-theme, else the
     *  system preference — followed live). Returns { resize, restart, restyle }. */
    function mount(canvas, opts) {
      const o = opts || {};
      const ctx = canvas && canvas.getContext && canvas.getContext("2d");
      if (!ctx) return { resize() {}, restart() {}, restyle() {} };
      const media = window.matchMedia ? matchMedia("(prefers-color-scheme: light)") : null;
      const watched = [];
      const isLight = o.light || (() => {
        const root = canvas.getRootNode ? canvas.getRootNode() : null;
        const host = root && root.host;
        if (host && watched.indexOf(host) < 0 && mo) watched.push(host), mo.observe(host, { attributes: true, attributeFilter: ["data-theme"] });
        const t = (host && host.getAttribute("data-theme")) || document.documentElement.getAttribute("data-theme");
        return t ? t === "light" : !!(media && media.matches);
      });
      let look = "";
      /** The page's light / dark changed? Re-pick the style. True when it changed. */
      const restyle = () => {
        const next = isLight() ? "paper" : "neon";
        if (next === look) return false;
        look = next;
        return true;
      };
      const watch = () => restyle() && now();
      const mo = window.MutationObserver ? new MutationObserver(watch) : null;
      if (mo) mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      if (media && media.addEventListener) media.addEventListener("change", watch);
      const still = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
      const once = !!o.once; // play the intro once, then stay lit: steady, no hum, no power-down
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
        restyle();
        drawn = true;
        const age = (performance.now() - t0) / 1000;
        const done = once && age >= litAt;
        const lt = done ? 0 : age % cycle;
        ctx.setTransform(k, 0, 0, k, 0, 0);
        ctx.clearRect(0, 0, w, h);
        draw(ctx, lt, PAD * p, PAD * p, p, !!o.grid, still || done, look);
        if (still || done) return;
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
        restyle: watch,
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
  let engineReady = new Promise((r) => (readyResolve = r));
  let worker = null;
  let engineState = "booting"; // booting | ready | fatal | busy-tab | moved | unsupported-runtime
  let handedOff = null; // resolves when the worker confirms a hand-off ({t:"handed-off"})

  function startWorker() {
    engineState = "booting";
    worker = new Worker(new URL("engine/worker.js", APP));
    worker.onmessage = (e) => onWorker(e.data);
    worker.onerror = (e) => ui.fatal(e.message || "the engine worker crashed");
  }

  /** Another tab takes the panel: let the engine finish the write in flight and save, then stop it (no reload).
   * The studio's sockets close (it shows "connecting" and comes back by itself when this tab takes the panel back). */
  async function stopWorker(graceful) {
    if (!worker) return;
    if (graceful && engineState === "ready") {
      await new Promise((res) => {
        const t = setTimeout(res, 7000);
        handedOff = () => (clearTimeout(t), res());
        worker.postMessage({ t: "handoff" });
      });
    }
    handedOff = null;
    for (const fn of addonListeners) for (const kind of ["camera", "screen", "audio"]) {
      try {
        fn({ t: "media", op: "stop", kind }); // camera light off: nothing reads the frames any more
      } catch {
        /* an add-on that doesn't care */
      }
    }
    worker.terminate();
    worker = null;
    engineState = "moved";
    ble.write = ble.notify = null; // the GATT handle itself stays open until the new tab has the panel
    for (const [id, p] of pending) {
      pending.delete(id);
      p.resolve({ status: 503, headers: [["content-type", "text/plain"]], body: null });
    }
    for (const s of [...sockets.values()]) s._event("close", 1001);
    engineReady = new Promise((r) => (readyResolve = r));
  }

  function onWorker(m) {
    switch (m.t) {
      case "handed-off":
        return handedOff && handedOff();
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
    get ready() {
      return engineReady; // a new promise after the engine moved to another tab and came back
    },
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
  // DeskDot on this computer (the desktop engine) answers here; the web app asks it whether it holds the panel.
  const DESKTOP = "http://127.0.0.1:8765";
  const changed = () => window.dispatchEvent(new CustomEvent("deskdot-web")); // the studio's Connection sheet listens
  const desktopHolds = (d) =>
    `Your panel${d.panel ? ` (${d.panel})` : ""} is connected to DeskDot on this computer. Open it there and press Release the panel (or quit DeskDot), then Reconnect now here.`;

  const ble = {
    device: null, // the BluetoothDevice the user picked (or the browser remembered)
    write: null,
    notify: null,
    size: packetSize(),
    state: "idle", // idle | needs-user | connecting | connected | error
    detail: "",
    step: "", // what a connect attempt is doing right now ("Waiting for IDM-… to show up")
    needsPick: false, // the browser has no panel it may use: only a click on "Pick panel" helps
    desktop: null, // the last check of DeskDot on this computer: {running, holding, panel, url, at}
    connecting: false,
    watching: null, // AbortController while we wait for the panel's advertisements (it came back → retry at once)
    letGoTimer: 0,
    closing: null, // the device we disconnected on purpose (its gattserverdisconnected is not a link loss)
    chain: Promise.resolve(),

    toWorker(ev, ...args) {
      if (worker) worker.postMessage({ t: "ble-ev", ev, args });
    },
    set(state, detail, step) {
      this.state = state;
      this.detail = detail || "";
      this.step = step || "";
      ui.link(state, this.detail, this.device && this.device.name);
      changed();
    },
    progress(step) {
      this.set(this.state, step, step);
    },

    request(m) {
      if (m.op === "connect") return this.connect();
      if (m.op === "write") return this.enqueue(m.data, m.withResponse, m.token);
      if (m.op === "disconnect") return this.disconnect();
    },

    /** Nudge the engine to try now instead of after its back-off (the panel advertised, Bluetooth came on…). */
    retry() {
      if (worker && engineState === "ready" && this.state !== "connected" && !this.connecting) worker.postMessage({ t: "ble-retry" });
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
      if (tabs.role !== "owner") return; // a tab that handed the panel over never touches it
      if (this.connecting) return; // the running attempt reports for this request too
      if (!hasBluetooth) {
        this.set("needs-user", "This browser can't use Bluetooth");
        return this.toWorker("onNeedsUser", "This browser can't reach the panel (no Web Bluetooth). The studio works; the panel needs Chrome, Edge or the desktop app.");
      }
      try {
        if (navigator.bluetooth.getAvailability && !(await navigator.bluetooth.getAvailability())) {
          this.set("error", "Bluetooth is off");
          return this.toWorker("onConnectFailed", "Bluetooth is turned off on this computer (or it has no Bluetooth adapter).");
        }
      } catch {
        /* not implemented: the connect attempt will say */
      }
      if (!this.device) this.device = await this.remembered();
      if (!this.device) {
        // Chrome forgets a granted panel when site data is cleared or the permission is revoked
        const forgot = !!LS.get("deskdot.web.panel") && !!navigator.bluetooth.getDevices;
        this.needsPick = true;
        this.set("needs-user", forgot ? "Permission needed — pick your panel again" : "Pick your panel to connect");
        return this.toWorker(
          "onNeedsUser",
          forgot ? "Bluetooth permission for your panel has expired — press Pick panel and choose it again." : "Click “Connect panel” and pick your IDM-… panel",
        );
      }
      this.needsPick = false;
      this.connecting = true;
      this.unwatch();
      const dev = this.device;
      const name = dev.name || "the panel";
      this.set("connecting", `Connecting to ${name}…`, `Looking for ${name}`);
      try {
        if (!dev._ddWatched) {
          dev._ddWatched = true;
          dev.addEventListener("gattserverdisconnected", () => this.lost(dev));
        }
        // a panel another tab of this browser still holds doesn't advertise: Chrome shares that link, skip the wait
        if (!tabs.otherTabHolds) {
          this.progress(`Waiting for ${name} to show up…`);
          await this.wake(dev);
        }
        this.progress(`Connecting to ${name}…`);
        // Chrome's gatt.connect() can hang (the panel half-held by another central): cancel it after 20 s, or this
        // tab ignores every later attempt (`connecting` stays true) and only a reload helps
        const server = await withTimeout(dev.gatt.connect(), 20000, () => dev.gatt.disconnect());
        this.progress("Setting up the link…");
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
        tabs.otherTabHolds = false;
        this.desktop = null;
        this.closing = null;
        this.set("connected", `${dev.name || "Panel"} · ${this.size}-byte packets`);
        tabs.say({ t: "connected", panel: dev.name || null }); // a tab that handed the panel over lets go of it now
        desk.connected();
        this.toWorker("onConnected", "web:" + dev.id, dev.name || "IDM-panel", this.size);
      } catch (e) {
        if (tabs.otherTabHolds) {
          // sharing the other tab's link didn't work: ask it to let go now, and wait for adverts next time
          tabs.otherTabHolds = false;
          tabs.say({ t: "let-go" });
        }
        let msg = explain(e);
        // the usual cause on a computer: DeskDot itself holds the panel — say so instead of a GATT error
        const d = await this.probeDesktop(true);
        if (d && d.holding) msg = desktopHolds(d);
        this.set("error", msg);
        this.toWorker("onConnectFailed", msg);
        this.watch(dev);
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

    /** While the panel is away, listen for it: the first advertisement starts a connect at once (no back-off wait). */
    watch(dev) {
      if (this.watching || !dev || typeof dev.watchAdvertisements !== "function") return;
      const ctl = new AbortController();
      this.watching = ctl;
      dev.addEventListener(
        "advertisementreceived",
        () => {
          if (this.watching !== ctl) return;
          this.unwatch();
          this.retry();
        },
        { signal: ctl.signal },
      );
      dev.watchAdvertisements({ signal: ctl.signal }).catch(() => {
        if (this.watching === ctl) this.watching = null; // not allowed / not supported: the engine's back-off still runs
      });
    },
    unwatch() {
      if (!this.watching) return;
      this.watching.abort();
      this.watching = null;
    },

    lost(dev) {
      if (dev !== this.device) return;
      this.write = this.notify = null;
      if (tabs.role !== "owner") return; // our handle closed after handing the panel to another tab
      if (this.closing === dev) {
        this.closing = null; // we closed it on the user's request (Release / Reconnect): not a loss
        return;
      }
      this.set("error", "Link lost — reconnecting…");
      this.toWorker("onDisconnected", "link lost (gattserverdisconnected)");
      this.watch(dev);
    },

    async disconnect() {
      // only on the user's request (Release the panel, Reconnect, a hand-over) or to cancel a stuck attempt: never
      // voluntarily. The engine already paused its writes; let the packet in flight settle, then close and wait
      // until Chrome reports the link down, so the next app finds the panel advertising (ADR 0015).
      const dev = this.device;
      this.unwatch();
      await Promise.race([this.chain.catch(() => undefined), new Promise((r) => setTimeout(r, 3000))]);
      this.write = this.notify = null;
      if (dev && (dev.gatt.connected || this.connecting)) {
        this.closing = dev;
        dev.gatt.disconnect(); // also cancels a pending gatt.connect()
        for (let i = 0; i < 20 && dev.gatt.connected; i++) await new Promise((r) => setTimeout(r, 100));
      }
      this.set("idle", "Disconnected");
      desk.report();
    },

    /** This tab handed the panel to another tab, which has it now (or never answered): drop our GATT handle. */
    letGo() {
      clearTimeout(this.letGoTimer);
      this.letGoTimer = 0;
      this.unwatch();
      const dev = this.device;
      this.write = this.notify = null;
      if (dev && dev.gatt.connected) dev.gatt.disconnect();
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

    /** The "Connect panel" / "Pick panel" click: the user gesture Web Bluetooth requires for its chooser. */
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
        if (e && e.name === "NotFoundError" && /adapter/i.test(e.message || ""))
          return ui.toast("Bluetooth is off, or this computer has no Bluetooth adapter. Turn it on and try again.", true);
        if (e && e.name === "NotFoundError") {
          const d = await this.probeDesktop(true);
          if (d && d.holding) return ui.toast(desktopHolds(d) + ` <a href="${d.url}" target="_blank" rel="noreferrer">Open DeskDot on this computer</a>`, true);
          return ui.toast(
            "No panel picked. Not in the list? It's off, out of range, or still connected to the iDotMatrix phone app or the DeskDot desktop / Android app — close those first (only one app can hold the panel).",
            true,
          );
        }
        return ui.toast(explain(e), true);
      }
      if (this.device && this.device !== dev && this.device.gatt.connected) this.device.gatt.disconnect();
      this.device = dev;
      this.needsPick = false;
      this.unwatch();
      LS.set("deskdot.web.panel", dev.id);
      ui.dismissLanding();
      changed();
      if (worker) worker.postMessage({ t: "ble-picked" });
    },

    /** Is DeskDot running on this computer, and does it hold the panel? (GET /api/health allows this site.) Chrome may
     * ask once to let this site reach devices on the local network; without that, we only learn "can't tell". */
    async probeDesktop(cached) {
      if (cached && this.desktop && Date.now() - this.desktop.at < 60000) return this.desktop;
      const url = DESKTOP + "/#connection";
      const get = (opts) => {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), 2500);
        return realFetch(DESKTOP + "/api/health", Object.assign({ cache: "no-store", credentials: "omit", signal: ctl.signal }, opts)).finally(() => clearTimeout(t));
      };
      let r = { running: false, holding: false, panel: null, url, at: Date.now() };
      try {
        const j = await (await get({})).json();
        r = { running: true, holding: j.device === "connected" && j.kind !== "sim", panel: j.panel || null, url, at: Date.now(), name: j.instance || null, handover: !!j.handover };
        if (j.handover) desk.start();
      } catch {
        try {
          await get({ mode: "no-cors" }); // an older DeskDot: it's there, but it can't tell us more
          r = { running: true, holding: null, panel: null, url, at: Date.now() };
        } catch {
          /* nothing listening on this computer (or the browser didn't allow the check) */
        }
      }
      this.desktop = r;
      changed();
      return r;
    },
  };

  function withTimeout(promise, ms, onTimeout) {
    let t = 0;
    return Promise.race([
      promise.finally(() => clearTimeout(t)),
      new Promise((_, reject) => {
        t = setTimeout(() => {
          try {
            onTimeout && onTimeout();
          } catch {
            /* already gone */
          }
          reject(Object.assign(new Error("the panel didn't answer in time (GATT connect timed out)"), { name: "NetworkError" }));
        }, ms);
      }),
    ]);
  }

  // ======================================================================================= hand-over with DeskDot here
  // ADR 0015. A browser can't join the LAN discovery (no UDP) and an https page can't call a phone's http address, but
  // it may talk to DeskDot on this computer over loopback (Private Network Access headers): this tab reports whether it
  // holds the panel (DeskDot answers "please let go" when someone wants it — the laptop itself, or a phone on the
  // LAN through it) and asks DeskDot to free the panel for it ("Use the panel here"). The Connection sheet shows
  // `deskdotWeb.state().handover`, built here in the same shape as the engine's `state.handover`.
  const desk = {
    brief: null, // the desktop's last /api/handover/tab answer (its handover brief + `want`)
    timer: 0,
    progress: null,
    movedTo: null,
    letting: false,

    holding() {
      return ble.state === "connected" && tabs.role === "owner";
    },
    /** This tab connected: if DeskDot was ever seen on this computer, start reporting (and learn who's nearby). */
    connected() {
      this.movedTo = null;
      if (LS.get("deskdot.web.desktopSeen")) this.start();
      else this.report();
    },
    start() {
      if (this.timer) return;
      LS.set("deskdot.web.desktopSeen", "1");
      const tick = async () => {
        await this.report();
        this.timer = setTimeout(tick, this.brief ? 3000 : 15000);
      };
      this.timer = setTimeout(tick, 0);
    },
    async report() {
      if (!this.timer && !(ble.desktop && ble.desktop.running)) return;
      let r = null;
      try {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), 2500);
        const res = await realFetch(DESKTOP + "/api/handover/tab", {
          method: "POST",
          credentials: "omit",
          cache: "no-store",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ holding: this.holding(), panel: ble.device ? ble.device.name || null : null }),
          signal: ctl.signal,
        }).finally(() => clearTimeout(t));
        if (res.ok) r = await res.json();
      } catch {
        /* DeskDot isn't running here (or the browser didn't allow the local request) */
      }
      this.brief = r;
      if (r && r.want && this.holding() && !this.letting) this.letGoFor(r.want);
      changed();
    },
    /** Someone (DeskDot here, or a phone through it) wants the panel: release it gracefully from this tab. */
    async letGoFor(name) {
      this.letting = true;
      try {
        await fetch("/api/device/link", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ enabled: false, moved_to: name }),
        });
        this.movedTo = { id: "desktop", name, at: Date.now() / 1000 };
        ui.toast(`Panel moved to ${name.replace(/</g, "&lt;")}. Press Use the panel here to take it back.`);
      } finally {
        this.letting = false;
        await this.report();
      }
    },
    steps(who) {
      return [
        { id: "ask", label: who ? `Asking ${who} to let go` : "Checking nobody else has it", state: "active" },
        { id: "released", label: "Released", state: "todo" },
        { id: "waiting", label: "Waiting for the panel", state: "todo" },
        { id: "connected", label: "Connected", state: "todo" },
      ];
    },
    step(id, state, label) {
      const steps = this.progress.steps;
      const i = steps.findIndex((s) => s.id === id);
      steps[i].state = state;
      if (label) steps[i].label = label;
      if (state === "done" && steps[i + 1] && steps[i + 1].state === "todo") steps[i + 1].state = "active";
      changed();
    },
    fail(error, canForce) {
      for (const s of this.progress.steps) if (s.state === "active") s.state = "failed";
      Object.assign(this.progress, { error, can_force: !!canForce, done: true });
      changed();
    },
    /** "Use the panel here" in this tab. Must not await before ble.pick() could be needed: it never picks. */
    async useHere(force) {
      if (this.progress && !this.progress.done) return;
      const d = await ble.probeDesktop(true);
      const holder = this.brief && this.brief.holder;
      const who = d && d.running && d.holding ? d.name || "DeskDot on this computer" : holder && holder.id !== "tab" ? holder.name : null;
      this.progress = { steps: this.steps(force ? null : who), error: null, can_force: false, done: false, target: who };
      changed();
      if (!force && d && d.running && d.handover) {
        this.start();
        let r = null;
        try {
          const res = await realFetch(DESKTOP + "/api/handover/free", { method: "POST", credentials: "omit", cache: "no-store", headers: { "content-type": "application/json" }, body: "{}" });
          r = await res.json();
        } catch {
          r = null;
        }
        if (!r || !r.ok)
          return this.fail(
            (r && r.detail ? r.detail + ". " : "DeskDot on this computer didn't answer. ") + "You can also try anyway: this tab waits for the panel to be free.",
            true,
          );
        this.step("ask", "done");
        this.step("released", "done", r.released_by ? `Released by ${r.released_by}` : "Nobody else had it");
      } else {
        // no DeskDot here to ask (or forced): an https page can't reach a phone on the LAN — wait for the panel instead
        this.step("ask", "done", force ? "Trying anyway" : "No DeskDot on this computer to ask");
        this.step("released", "done", "Waiting for whoever has it to let go");
      }
      this.movedTo = null;
      await fetch("/api/device/link", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled: true }) }).catch(() => undefined);
      ble.retry();
      const end = Date.now() + 45000;
      while (Date.now() < end && ble.state !== "connected") {
        if (this.progress.steps[2].state === "active" && ble.state === "connecting") this.step("waiting", "done");
        await new Promise((r) => setTimeout(r, 300));
      }
      if (ble.state !== "connected")
        return this.fail(
          "The panel didn't connect. It's probably still held by another app — DeskDot on your phone (open it and press Release the panel), the iDotMatrix phone app, or another computer. If nothing holds it, unplug the panel for 5 seconds.",
          true,
        );
      if (this.progress.steps[2].state !== "done") this.step("waiting", "done");
      this.step("connected", "done");
      this.progress.done = true;
      changed();
      this.report();
    },
    /** The engine-shaped hand-over state for the Connection sheet. */
    state() {
      const b = this.brief;
      const peers = [];
      let holder = null;
      if (b && b.me) {
        const deskHolds = !!(b.holder && b.holder.me);
        peers.push({ id: b.me.id, name: `${b.me.name} (DeskDot)`, kind: b.me.kind || "ble", holding: deskHolds, panel: null, online: true, paired: true, ago: 0 });
        for (const p of b.peers || []) if (p.id !== "tab") peers.push(Object.assign({}, p, { paired: true }));
        if (b.holder && b.holder.id !== "tab") holder = Object.assign({}, b.holder, { me: false, name: deskHolds ? b.me.name : b.holder.name });
      }
      if (!b && !this.progress && !this.movedTo) return null;
      return {
        enabled: !!b,
        me: { id: "tab", name: "This browser tab", kind: "web" },
        holder: this.holding() ? { id: "tab", name: "This browser tab", kind: "web", me: true } : holder,
        probable: null,
        peers,
        lease: null,
        progress: this.progress,
        moved_to: ble.state !== "connected" ? this.movedTo : null,
        pair_requests: [],
        pairing: [],
      };
    },
  };

  if (hasBluetooth && navigator.bluetooth.addEventListener) {
    // Bluetooth switched back on: try at once instead of waiting out the back-off
    navigator.bluetooth.addEventListener("availabilitychanged", (e) => e.value && ble.retry());
  }
  document.addEventListener("visibilitychange", () => !document.hidden && ble.state === "error" && ble.retry());

  function explain(e) {
    const name = (e && e.name) || "";
    const msg = (e && e.message) || String(e);
    if (name === "SecurityError")
      return "Bluetooth permission was blocked for this site. Allow it in the address bar's site settings (the icon left of the address), then press Pick panel.";
    if (/adapter/i.test(msg) && /not available|off|powered/i.test(msg)) return "Bluetooth is turned off on this computer (or it has no Bluetooth adapter).";
    if (name === "NetworkError" || /GATT|connect|range|disconnected/i.test(msg))
      return "The panel didn't answer. It may be off, out of range, or connected to another app (the iDotMatrix phone app, DeskDot on this computer or the Android app). " + `(${msg})`;
    if (name === "NotFoundError") return "This panel doesn't offer the expected Bluetooth service — is it an iDotMatrix 32×32?";
    return msg;
  }

  // ======================================================================================= UI
  const ui = (function () {
    const host = document.createElement("div");
    host.id = "deskdot-web-host";
    const root = host.attachShadow({ mode: "open" });
    // the card follows the studio theme (host.css :host([data-theme="light"])); the studio may switch it live
    // …and its glass mode (host.css :host([data-glass]); <html data-glass>, set above and by the studio's lib/glass.ts)
    const syncTheme = () => {
      host.setAttribute("data-theme", document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark");
      host.setAttribute("data-glass", document.documentElement.getAttribute("data-glass") || "liquid");
    };
    syncTheme();
    new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "data-glass"] });
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
<div class="landing handoff" role="dialog" aria-modal="true" aria-labelledby="dd-h-title" hidden>
  <div class="card">
    <div class="brand">ONE TAB DRIVES THE PANEL</div>
    <h1 id="dd-h-title" class="h-title">The panel is connected in another tab</h1>
    <p class="lede h-text"></p>
    <div class="actions">
      <button class="key ember h-use" type="button">Use it here</button>
      <button class="key ghost h-find" type="button">Find that tab</button>
    </div>
    <p class="hint h-note">Only one tab can drive the panel. Moving it takes a few seconds (this tab starts the engine)
    and needs no reload; the other tab steps back and can take it back the same way.</p>
  </div>
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
    let studioPill = false; // the studio shows its own connection pill (ConnectionSheet.tsx): ours stays hidden
    const handoff = $(".handoff");
    const NOTE = $(".h-note").textContent;
    $(".h-use").addEventListener("click", () => tabs.useHere());
    $(".h-find").addEventListener("click", () => {
      tabs.say({ t: "find" });
      toast("Look for the tab whose title blinks “● DeskDot has the panel”.");
    });

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
      if (isReady && !studioPill) pill.hidden = false;
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
        if (!handoff.hidden && handoff.dataset.mode === "moving") $(".h-note").textContent = detail || phase;
        $(".phase").textContent = detail || phase;
        if (pct != null) $(".bar i").style.width = Math.max(3, pct) + "%";
      },
      ready() {
        isReady = true;
        handoff.hidden = true; // the engine runs in this tab (again)
        $(".boot").classList.add("done");
        $(".phase").textContent = "Engine running in this tab";
        if ((landing.hidden || landing.classList.contains("gone")) && !studioPill) pill.hidden = false;
      },
      attachStudio() {
        studioPill = true;
        pill.hidden = true;
      },
      /** The hand-off card. mode: "standby" (another tab has the panel) · "moving" · "moved" (this tab gave it away)
       * · "old" (another tab runs an older DeskDot that can't hand over) · null (hide). */
      tabs(mode, info) {
        if (!mode) {
          handoff.hidden = true;
          return;
        }
        const panel = info && info.panel ? info.panel : "your panel";
        const T = {
          standby: ["The panel is connected in another tab", `DeskDot is driving ${panel} from another tab of this browser. Use it here and that tab steps back — no reload, no closing tabs.`],
          moving: info && info.starting
            ? ["Starting DeskDot in this tab…", "The engine is starting here (a few seconds). It connects to the panel by itself — nothing to click."]
            : ["Moving the panel to this tab…", "The other tab is finishing what it was sending and saving your settings. This tab then starts the engine and connects to the panel by itself."],
          moved: ["Panel moved to another tab", `${panel} is now driven from another tab. This tab is resting: take the panel back whenever you like.`],
          old: ["DeskDot is open in another tab", "That tab runs an older DeskDot that can’t hand the panel over. Close it — this tab then takes the panel by itself (no reload needed)."],
        }[mode];
        $(".h-title").textContent = T[0];
        $(".h-text").textContent = T[1];
        const use = $(".h-use");
        use.textContent = mode === "moved" ? "Take it back" : "Use it here";
        use.hidden = mode === "old";
        use.disabled = mode === "moving";
        $(".h-find").hidden = mode === "moving";
        handoff.dataset.mode = mode;
        if (mode !== "moving") $(".h-note").textContent = NOTE;
        landing.hidden = true;
        pill.hidden = true;
        handoff.hidden = false;
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

  // ======================================================================================= one tab drives the panel
  // Rule 4 (exactly one BLE owner): a Web Lock decides which tab runs the engine — two engines would interleave
  // packets on one link. Tabs talk over a BroadcastChannel, so a second tab can take the panel over without a reload
  // and the first one steps back ("Panel moved to another tab — Take it back"). docs/WEB_APP.md "Two tabs".
  const LOCK = "deskdot-web-engine";
  const TAB = Math.random().toString(36).slice(2, 10);
  const tabs = {
    role: "starting", // owner | standby | moving (taking it) | stepping (giving it away) | moved
    chan: typeof BroadcastChannel === "function" ? new BroadcastChannel("deskdot-web") : null,
    owner: null, // what the tab that drives the panel last told us: {panel, link}
    otherTabHolds: false, // the previous owner (same browser) still holds the GATT link: Chrome shares it, connect at once
    hold: null, // resolves our lock (lets it go)
    queue: null, // AbortController of our queued lock request (standby: take over by ourselves when that tab closes)
    released: null, // resolves when the owner says it stepped back
    titleTimer: 0,

    say(msg) {
      if (!this.chan) return;
      try {
        this.chan.postMessage(Object.assign({ from: TAB }, msg));
      } catch {
        /* closing */
      }
    },
    announce() {
      if (this.role === "owner") this.say({ t: "owner", panel: ble.device ? ble.device.name || null : null, link: ble.state });
    },

    /** Ask for the lock. `steal` takes it from the tab that has it (after that tab stepped back, or never answered). */
    request(opts) {
      let mine = null;
      navigator.locks
        .request(LOCK, opts, (lock) => {
          if (!lock) return this.standby(); // ifAvailable: another tab has it
          this.queue = null;
          return new Promise((res) => {
            mine = res;
            this.hold = res;
            this.own();
          });
        })
        .catch((e) => {
          if (!e || e.name !== "AbortError") return console.warn("DeskDot: tab lock", e);
          if (mine && this.hold === mine) {
            this.hold = null;
            if (this.role === "owner") this.giveAway(true); // stolen without a hand-off: stop writing at once
          }
        });
    },

    /** We hold the lock: run the engine here (again, after a hand-off back — no reload). */
    own() {
      const again = this.role !== "starting";
      this.role = "owner";
      if (again) ui.tabs("moving", { starting: true });
      if (!worker) startWorker();
      this.announce();
    },

    /** Another tab drives the panel: offer "Use it here"; queue for the lock so we take over if that tab closes. */
    standby() {
      this.role = "standby";
      engineState = "busy-tab";
      ui.tabs(this.chan ? "standby" : "old", this.owner);
      this.queueForLock();
      this.say({ t: "who" });
      if (this.chan) setTimeout(() => this.role === "standby" && !this.owner && ui.tabs("old"), 1500);
      return undefined;
    },
    queueForLock() {
      if (this.queue) return;
      this.queue = new AbortController();
      this.request({ signal: this.queue.signal });
    },

    /** "Use it here" / "Take it back": the owner finishes its write, saves and steps back; then we take the lock. */
    async useHere() {
      if (this.role !== "standby" && this.role !== "moved") return;
      const from = this.role;
      this.role = "moving";
      ui.tabs("moving");
      if (this.queue) {
        this.queue.abort();
        this.queue = null;
      }
      if (from === "moved") ble.letGo(); // we may still hold our old GATT handle: the owner tab has the panel now
      await new Promise((res) => {
        const t = setTimeout(res, 9000); // an owner that never answers (an older version, a frozen tab): go ahead
        this.released = () => (clearTimeout(t), res());
        this.say({ t: "takeover" });
      });
      this.released = null;
      this.request({ steal: true });
    },

    /** Step back: another tab takes the panel. `stolen`: it already took the lock, so stop without waiting. */
    async giveAway(stolen) {
      if (this.role !== "owner") return;
      this.role = "stepping"; // nothing (a second takeover, a click) acts until we're done
      const panel = ble.device ? ble.device.name || null : null;
      ui.tabs("moved", { panel });
      const holding = !!(ble.device && ble.device.gatt.connected);
      await stopWorker(!stolen);
      ble.unwatch();
      // keep our GATT handle until the new tab says it's connected: Chrome shares one link between tabs, so the panel
      // never sees a disconnect (rule 5). If it never says so, let go after a minute.
      if (holding) ble.letGoTimer = setTimeout(() => ble.letGo(), 60000);
      ble.set("idle", "Moved to another tab");
      this.role = "moved";
      this.say({ t: "released", holding, panel });
      const hold = this.hold;
      if (hold) setTimeout(() => this.hold === hold && (hold(), (this.hold = null)), 10000); // nobody stole it: free it
    },

    onMessage(m) {
      if (!m || m.from === TAB) return;
      switch (m.t) {
        case "who":
          return this.announce();
        case "owner":
          this.owner = { panel: m.panel, link: m.link };
          if (this.role === "standby") ui.tabs("standby", this.owner);
          return;
        case "takeover":
          return this.giveAway(false);
        case "released":
          this.otherTabHolds = !!m.holding;
          if (m.panel) this.owner = { panel: m.panel, link: "idle" };
          if (this.released) this.released();
          return;
        case "connected":
          this.owner = { panel: m.panel, link: "connected" };
          if (this.role === "moved") {
            ble.letGo(); // the new tab has the panel: our handle can go (the link stays up, it's shared)
            ui.tabs("moved", this.owner);
          } else if (this.role === "standby") ui.tabs("standby", this.owner);
          return;
        case "let-go":
          if (this.role === "moved") ble.letGo();
          return;
        case "find":
          if (this.role === "owner") this.flashTitle();
          return;
      }
    },

    /** "Find that tab": blink this tab's title (browsers don't let a page switch tabs for the user). */
    flashTitle() {
      clearInterval(this.titleTimer);
      const mark = "● DeskDot has the panel · ";
      const base = document.title.replace(mark, "");
      let n = 0;
      this.titleTimer = setInterval(() => {
        document.title = n++ % 2 ? base : mark + base;
        if (n > 14) {
          clearInterval(this.titleTimer);
          document.title = base;
        }
      }, 700);
      try {
        window.focus(); // works when the browser allows it (e.g. a separate window)
      } catch {
        /* not allowed */
      }
    },
  };
  if (tabs.chan) tabs.chan.onmessage = (e) => tabs.onMessage(e.data);
  window.addEventListener("deskdot-web", () => tabs.announce());

  // ======================================================================================= start
  window.addEventListener("pagehide", () => worker && worker.postMessage({ t: "sync" }));
  document.addEventListener("visibilitychange", () => document.hidden && worker && worker.postMessage({ t: "sync" }));
  if (typeof WebAssembly !== "object") {
    engineState = "unsupported-runtime";
    ui.blocked("This browser can't run WebAssembly, which the engine needs. Use a current Chrome, Edge, Firefox or Safari.");
  } else if (navigator.locks && navigator.locks.request) {
    tabs.request({ ifAvailable: true });
  } else {
    tabs.role = "owner"; // no Web Locks (very old browsers): one tab at a time is up to the user
    startWorker();
  }

  // The page host's API: the studio's Connection sheet (web/src/components/ConnectionSheet.tsx) and tests.
  // Changes are announced with a "deskdot-web" event on window.
  window.deskdotWeb = {
    state: () => ({
      engine: engineState,
      role: tabs.role,
      link: ble.state,
      detail: ble.detail,
      step: ble.step,
      panel: ble.device ? ble.device.name || null : null,
      packet: ble.size,
      packetChoice: Number(LS.get("deskdot.web.packet") || 0) || null,
      bluetooth: hasBluetooth,
      needsPick: ble.needsPick,
      desktop: ble.desktop,
      handover: desk.state(),
    }),
    request: engineRequest,
    /** Must be called from a click (Web Bluetooth's user gesture). */
    pick: () => ble.pick(),
    retry: () => ble.retry(),
    probeDesktop: () => ble.probeDesktop(false),
    /** "Use the panel here": ask DeskDot on this computer (and through it a phone on the LAN) to let go, then connect. */
    useHere: (force) => desk.useHere(!!force),
    /** Bytes per write: 20 / 182 / 244 / 512, or null for automatic. Applies on the next connect. */
    setPacket(n) {
      LS.set("deskdot.web.packet", n ? String(n) : null);
      window.dispatchEvent(new CustomEvent("deskdot-web"));
    },
    attachStudio: () => ui.attachStudio(),
  };

  // ======================================================================================= browser stats
  // System Monitor in a tab (providers/system.py `browser_stats`): a page can't read the computer's CPU, RAM or disk,
  // so every 2 s it sends what browsers do tell — CPU pressure (Compute Pressure API: nominal / fair / serious /
  // critical), this tab's JavaScript memory, the battery, the network estimate, the page's frame rate while visible,
  // CPU cores and the device-memory hint. Anything a browser doesn't support is simply left out.
  const sysStats = (() => {
    const s = {};
    try {
      if ("PressureObserver" in window) {
        const po = new window.PressureObserver((records) => {
          const r = records[records.length - 1];
          if (r) s.pressure = r.state;
        });
        po.observe("cpu", { sampleInterval: 2000 }).catch(() => undefined);
      }
    } catch { /* no Compute Pressure here */ }
    try {
      if (navigator.getBattery) {
        navigator.getBattery().then((b) => {
          const read = () => ((s.battery = b.level), (s.charging = b.charging));
          read();
          b.addEventListener("levelchange", read);
          b.addEventListener("chargingchange", read);
        }, () => undefined);
      }
    } catch { /* no Battery Status API */ }
    let frames = 0;
    let since = performance.now();
    const tick = () => {
      frames++;
      if (!document.hidden) requestAnimationFrame(tick);
    };
    document.addEventListener("visibilitychange", () => {
      frames = 0;
      since = performance.now();
      if (!document.hidden) requestAnimationFrame(tick);
    });
    requestAnimationFrame(tick);
    setInterval(() => {
      if (!worker || engineState !== "ready") return;
      const now = performance.now();
      const fps = document.hidden ? null : Math.round((frames * 1000) / Math.max(1, now - since));
      frames = 0;
      since = now;
      const mem = performance.memory; // Chrome / Edge only
      const net = navigator.connection;
      worker.postMessage({
        t: "sys-stats",
        stats: {
          pressure: s.pressure || null,
          heap_used: mem ? mem.usedJSHeapSize : null,
          heap_limit: mem ? mem.jsHeapSizeLimit : null,
          battery: typeof s.battery === "number" ? s.battery : null,
          charging: typeof s.charging === "boolean" ? s.charging : null,
          downlink_mbps: net && typeof net.downlink === "number" ? net.downlink : null,
          rtt_ms: net && typeof net.rtt === "number" ? net.rtt : null,
          fps,
          cores: navigator.hardwareConcurrency || null,
          device_memory_gb: navigator.deviceMemory || null,
        },
      });
    }, 2000);
    return { snapshot: () => ({ ...s }) };
  })();
  window.deskdotWeb.sysStats = sysStats.snapshot;

  // add-ons (built next to host.js by scripts/build_webapp.py): online play with friends, camera / screen / mic
  for (const name of ["host-rtc.js", "host-media.js"]) {
    const el = document.createElement("script");
    el.src = new URL(name + VERSION, BASE).href;
    el.async = true;
    document.head.appendChild(el);
  }
})();
