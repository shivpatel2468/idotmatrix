/* DeskDot TV view — core (docs/TV_VIEW.md).
 *
 * A read-only, full-screen view of whatever DeskDot is playing, for any screen with a browser. The page is a fixed
 * 1920×1080 stage scaled to fit; this file owns the stage, the top bar, the connection (WS /ws/tv/<code>), the LED
 * panel renderer, a QR encoder, the scene registry and the generic scene. Scenes for games and casino tables
 * register themselves from tv-games.js and tv-casino.js (loaded after this file).
 *
 * Plain modern JS, no dependencies, no inline script (the web app's CSP), nothing loaded from elsewhere.
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

  const W = 1920;
  const H = 1080;
  const BAR = 96;
  const PANEL = 32;
  const FRAME_BYTES = PANEL * PANEL * 3;
  const SEAT_COLORS = { 1: "#00c8ff", 2: "#ff3c5a", 3: "#50ff78", 4: "#ffc800" };

  const $ = (id) => document.getElementById(id);
  const code = (location.pathname.split("/").filter(Boolean).pop() || "").toUpperCase();

  // =========================================================================================== small helpers
  function el(tag, className, text) {
    const e = document.createElement(tag);
    if (className) e.className = className;
    if (text != null) e.textContent = String(text);
    return e;
  }
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);

  // Intl formatting is slow and a table redraw formats dozens of amounts: remember the recent ones
  const fmtCache = new Map();
  function fmt(n, short) {
    const key = short ? `s${n}` : n;
    let out = fmtCache.get(key);
    if (out === undefined) {
      if (fmtCache.size > 2000) fmtCache.clear();
      out = fmtRaw(n, short);
      fmtCache.set(key, out);
    }
    return out;
  }
  function fmtRaw(n, short) {
    const v = Number(n);
    if (!Number.isFinite(v)) return n == null ? "–" : String(n);
    if (short) {
      const a = Math.abs(v);
      if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1).replace(/\.0$/, "") + "B";
      if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M";
      if (a >= 1e4) return (v / 1e3).toFixed(a >= 1e5 ? 0 : 1).replace(/\.0$/, "") + "K";
    }
    const r = Math.round(v * 100) / 100;
    return r.toLocaleString("en-US", { maximumFractionDigits: Number.isInteger(r) ? 0 : 2 });
  }

  const now = () => performance.now() / 1000;

  // =========================================================================================== quality tier
  // Two tiers that look the same: "hq" and "lite" draw the same picture at the same resolution with the same glows,
  // particles and animations — both get their speed from cheap techniques (glow sprites instead of shadowBlur,
  // cached static layers, canvases shown as finished bitmaps, redraws skipped when nothing changed). Lite only trims
  // work nobody can see (docs/TV_VIEW.md §2). The choice is "auto" (the default: hq, dropping to lite when this
  // screen measures slow), "hq" or "lite" — from the on-TV menu, the studio, or `?quality=auto|hq|lite` (also
  // `?lite=1` / `?hq=1`). Auto watches the page's frame times while something animates: a window of ~2 s that runs
  // slow (median frame > 22 ms, or > 20 % of frames over 34 ms) drops it to lite for the rest of the visit.
  // Pure helpers (tierFromQuery, judgeFrames, pickDisplay) are exported on TV for tests/js/tv_core.test.mjs.
  function tierFromQuery(search) {
    let q;
    try {
      q = new URLSearchParams(search || "");
    } catch {
      return null;
    }
    const v = (q.get("quality") || "").toLowerCase();
    if (v === "lite" || v === "low") return "lite";
    if (v === "hq" || v === "high") return "hq";
    if (q.has("lite") && q.get("lite") !== "0") return "lite";
    if (q.has("hq") && q.get("hq") !== "0") return "hq";
    return null;
  }

  /** A window of frame intervals (ms) → "lite" when the device can't keep up, "hq" when it can, null if too few. */
  function judgeFrames(dts) {
    const xs = (dts || []).filter((d) => d > 0 && d < 1000); // a hidden tab / a GC pause of seconds says nothing
    if (xs.length < 30) return null;
    const s = xs.slice().sort((a, b) => a - b);
    const p50 = s[Math.floor(s.length / 2)];
    const slow = xs.filter((d) => d > 34).length / xs.length;
    return p50 > 22 || slow > 0.2 ? "lite" : "hq";
  }

  /** The quality choice in the address: "auto" | "hq" | "lite", or null. */
  function qualityFromQuery(search) {
    try {
      if ((new URLSearchParams(search || "").get("quality") || "").toLowerCase() === "auto") return "auto";
    } catch {
      return null;
    }
    return tierFromQuery(search);
  }

  // =========================================================================================== display choices
  // The panel look — the studio's three (web/src/lib/look.ts): "pixel" (sharp square pixels), "led" (a physical LED
  // matrix, the default here: the TV shows the panel) and "glow" (sharp pixels with a soft bloom) — and the quality.
  // Who decides, per choice (pickDisplay): the studio's choice (POST /api/tv/settings, sent to every TV as
  // hello / state `display`) wins over what this TV remembers, until someone picks on this TV again (the pick is
  // remembered with the studio revision it overrode); an address parameter wins over the studio's choice that was
  // already set when the page loaded, never over a later one.
  const LOOKS = ["pixel", "led", "glow"];
  const QUALITIES = ["auto", "hq", "lite"];
  const LOOK_NAMES = { pixel: "Pixel", led: "LED", glow: "Glow" };
  const QUALITY_NAMES = { auto: "Auto", hq: "HQ", lite: "Lite" };
  const PREF_KEYS = { look: "deskdot.tv.look", quality: "deskdot.tv.quality" };
  const DEFAULTS = { look: "led", quality: "auto" };
  const ALLOWED = { look: LOOKS, quality: QUALITIES };

  /** The panel look in the address (?look=pixel|led|glow), or null. */
  function lookFromQuery(search) {
    try {
      const v = (new URLSearchParams(search || "").get("look") || "").toLowerCase();
      return LOOKS.includes(v) ? v : null;
    } catch {
      return null;
    }
  }

  /**
   * Which value one display choice takes, and from where. Pure (tests).
   * o: { url: value | null, local: {v, rev} | null (this TV's pick + the studio revision it overrode),
   *      studio: value | null, rev: the studio's revision | null, loadRev: the studio revision when the page loaded }
   */
  function pickDisplay(o, fallback) {
    const local = o.local && o.local.v ? o.local : null;
    if (o.studio != null && o.rev != null && !(local && local.rev === o.rev) && !(o.url && o.rev === o.loadRev))
      return { v: o.studio, from: "studio" };
    if (o.url) return { v: o.url, from: "url" };
    if (local) return { v: local.v, from: "tv" };
    return { v: fallback, from: "default" };
  }

  function readPref(key) {
    try {
      const raw = localStorage.getItem(PREF_KEYS[key]);
      if (raw) {
        const p = JSON.parse(raw);
        if (p && ALLOWED[key].includes(p.v)) return { v: p.v, rev: typeof p.rev === "number" ? p.rev : null };
      }
      // the earlier key: "led" was the LED look (its "hd" look is gone)
      if (key === "look" && localStorage.getItem("deskdot.tv.panel-look") === "led") return { v: "led", rev: null };
    } catch {
      /* storage blocked, or junk in it */
    }
    return null;
  }
  function writePref(key, p) {
    try {
      localStorage.setItem(PREF_KEYS[key], JSON.stringify(p));
    } catch {
      /* storage blocked: the choice lasts until the page reloads */
    }
  }

  const disp = {
    url: { look: lookFromQuery(location.search), quality: qualityFromQuery(location.search) },
    local: { look: readPref("look"), quality: readPref("quality") },
    studio: { look: null, quality: null, rev: null },
    loadRev: undefined, // the studio revision in the first message (undefined until then)
    from: { look: "default", quality: "default" },
  };
  function resolveDisplay(key) {
    return pickDisplay(
      { url: disp.url[key], local: disp.local[key], studio: disp.studio[key], rev: disp.studio.rev, loadRev: disp.loadRev },
      DEFAULTS[key],
    );
  }
  const initial = { look: resolveDisplay("look"), quality: resolveDisplay("quality") };
  disp.from.look = initial.look.from;
  disp.from.quality = initial.quality.from;
  const startTier = initial.quality.v === "auto" ? "hq" : initial.quality.v;

  // =========================================================================================== stage scaling
  const TV = {
    W,
    H,
    BAR,
    SCENE_W: W,
    SCENE_H: H - BAR,
    scale: 1,
    pixelRatio: window.devicePixelRatio || 1,
    scenes: [],
    registerScene,
    version: 3,
    quality: startTier, // the tier in effect: "hq" | "lite"
    qualityMode: initial.quality.v, // the choice: "auto" | "hq" | "lite"
    qualityForced: initial.quality.v !== "auto",
    look: initial.look.v, // "pixel" | "led" | "glow"
    looks: LOOKS,
    qualities: QUALITIES,
    every,
    setQuality,
    setLook: (v) => choose("look", v),
    setQualityMode: (v) => choose("quality", v),
    openMenu: () => openMenu(),
    tierFromQuery,
    qualityFromQuery,
    judgeFrames,
    lookFromQuery,
    pickDisplay,
    surface,
    showSurface,
    bloomField: (data, look, n) => bloomField(data, look, n),
  };
  window.TV = TV;
  document.documentElement.dataset.q = TV.quality;

  // =========================================================================================== the one animation loop
  // Every per-frame job (casino scenes, the HD panel's cross-fade, a waiting panel frame) runs from this single
  // requestAnimationFrame loop; it stops when nobody needs it. It also feeds the quality tier its frame times.
  const loop = { subs: new Set(), raf: 0, last: 0, dts: [], dtSum: 0 };
  function every(fn) {
    loop.subs.add(fn);
    kickLoop();
    return () => loop.subs.delete(fn);
  }
  function kickLoop() {
    if (!loop.raf) loop.raf = requestAnimationFrame(tick);
  }
  function tick(ts) {
    loop.raf = 0;
    const dt = loop.last ? ts - loop.last : 0;
    loop.last = ts;
    if (frameWaiting) {
      frameWaiting = false;
      if (current && current.scene.frame) safe(() => current.scene.frame(ctx));
    }
    const t = ts / 1000;
    for (const fn of [...loop.subs]) {
      try {
        if (fn(t) === false) loop.subs.delete(fn);
      } catch (e) {
        loop.subs.delete(fn);
        console.error("DeskDot TV frame job:", e);
      }
    }
    // the tier watch: only frames that ran back to back while something animated count
    if (loop.subs.size && dt > 0 && !TV.qualityForced && TV.quality === "hq" && !document.hidden) {
      loop.dts.push(dt);
      loop.dtSum += dt;
      // a window: 120 frames, or ~2.5 s of them on a device too slow to show 120 in time
      if (loop.dts.length >= 120 || (loop.dtSum >= 2500 && loop.dts.length >= 30)) {
        loop.dtSum = 0;
        const verdict = judgeFrames(loop.dts);
        loop.dts.length = 0;
        if (verdict === "lite") setQuality("lite", true);
        else if (verdict === "hq" && probeUntil) probeUntil = Math.min(probeUntil, now()); // fine here: stop probing
      }
    }
    if (loop.subs.size || frameWaiting) loop.raf = requestAnimationFrame(tick);
    else loop.last = 0;
  }
  document.addEventListener("visibilitychange", () => {
    loop.last = 0; // the first frame back is not a slow frame
    loop.dts.length = 0;
    loop.dtSum = 0;
  });

  /**
   * After a scene mounts (hq, not forced): keep the loop running for a few seconds so the tier watch sees the
   * page's real frame rate with the scene's work in it — even a scene that only redraws on a new panel frame.
   */
  let probeUntil = 0;
  function probe() {
    if (TV.qualityForced || TV.quality !== "hq") return;
    const start = !probeUntil || now() > probeUntil;
    probeUntil = now() + 8;
    loop.dts.length = 0;
    loop.dtSum = 0;
    if (start) every(() => TV.quality === "hq" && now() < probeUntil);
  }

  /** Switch the tier in effect (auto = measured) and re-mount the scene so it picks the tier up. */
  let measuredLite = false; // auto measured this screen as slow (for the rest of the visit)
  function setQuality(q, auto) {
    if (q !== "lite" && q !== "hq") return;
    if (auto) measuredLite = q === "lite";
    if (q === TV.quality) return;
    TV.quality = q;
    document.documentElement.dataset.q = q;
    if (auto) console.info("DeskDot TV: this screen runs slow — Auto switched to Lite (same picture, less work)");
    renderMenu();
    if (current) {
      const sc = current.scene;
      current = null;
      broken.delete(`${sc.id}|${ctx.app}`);
      // force a fresh mount of the same scene
      const host = $("scene");
      try {
        if (sc.unmount) sc.unmount();
      } catch (e) {
        console.error(e);
      }
      if (host) host.replaceChildren();
    }
    pickScene();
    redrawPanels();
  }

  /** Apply the display choices as pickDisplay resolves them now (no reload: panels redraw, the tier switches). */
  function applyDisplay() {
    const L = resolveDisplay("look");
    const Q = resolveDisplay("quality");
    disp.from.look = L.from;
    disp.from.quality = Q.from;
    if (L.v !== TV.look) {
      TV.look = L.v;
      redrawPanels();
    }
    if (Q.v !== TV.qualityMode) {
      TV.qualityMode = Q.v;
      TV.qualityForced = Q.v !== "auto";
      if (Q.v === "auto") probe();
      setQuality(Q.v === "auto" ? (measuredLite ? "lite" : "hq") : Q.v);
    }
    renderMenu();
  }

  /** Someone picked on this TV (the menu, or TV.setLook): it wins until the studio changes its choice again. */
  function choose(key, v) {
    if (!ALLOWED[key] || !ALLOWED[key].includes(v)) return;
    disp.url[key] = null;
    disp.local[key] = { v, rev: disp.studio.rev };
    writePref(key, disp.local[key]);
    applyDisplay();
  }

  /** The studio's choices (hello / state `display`): applied whenever its revision changes. */
  function onStudioDisplay(d) {
    if (!d || typeof d !== "object") return;
    const rev = typeof d.rev === "number" ? d.rev : null;
    if (disp.loadRev === undefined) disp.loadRev = rev;
    const look = LOOKS.includes(d.look) ? d.look : null;
    const quality = QUALITIES.includes(d.quality) ? d.quality : null;
    const s = disp.studio;
    if (rev === s.rev && look === s.look && quality === s.quality) return;
    const before = { look: TV.look, quality: TV.qualityMode };
    disp.studio = { look, quality, rev };
    applyDisplay();
    const said = [];
    if (TV.look !== before.look && disp.from.look === "studio") said.push(`Panel look: ${LOOK_NAMES[TV.look]}`);
    if (TV.qualityMode !== before.quality && disp.from.quality === "studio") said.push(`Quality: ${QUALITY_NAMES[TV.qualityMode]}`);
    if (said.length) toast(`From the studio · ${said.join(" · ")}`);
  }

  let toastTimer = 0;
  function toast(text) {
    let t = $("tv-toast");
    if (!t) {
      t = el("div");
      t.id = "tv-toast";
      const stage = $("stage");
      if (!stage) return;
      stage.appendChild(t);
    }
    t.textContent = text;
    t.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("on"), 1800);
  }

  function fit() {
    const stage = $("stage");
    if (!stage) return;
    const vw = window.innerWidth || document.documentElement.clientWidth || W;
    const vh = window.innerHeight || document.documentElement.clientHeight || H;
    const s = Math.min(vw / W, vh / H);
    const x = Math.round((vw - W * s) / 2);
    const y = Math.round((vh - H * s) / 2);
    stage.style.transform = `translate(${x}px, ${y}px) scale(${s})`;
    const pr = s * (window.devicePixelRatio || 1);
    const changed = Math.abs(pr - TV.pixelRatio) > 1e-3;
    TV.scale = s;
    TV.pixelRatio = pr;
    if (changed && current && current.scene.resize) safe(() => current.scene.resize(ctx));
    if (changed) redrawPanels();
    if (changed) logos.forEach((l) => l.resize());
  }
  const logos = []; // the LED logos in the bar and on the veil (DeskDotLogo, above), re-sized with the stage

  // =========================================================================================== QR encoder
  // byte mode, error correction L or M, versions 1–40 — after Project Nayuki's reference implementation (the same
  // encoder as the studio's web/src/lib/qr.ts). Returns rows of modules (true = dark), no quiet zone.
  const ECC_PER_BLOCK = {
    L: [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    M: [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
  };
  const NUM_BLOCKS = {
    L: [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    M: [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
  };
  const FORMAT_BITS = { L: 1, M: 0 };
  const qbit = (x, i) => ((x >>> i) & 1) !== 0;

  function rawModules(ver) {
    let r = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
      const n = Math.floor(ver / 7) + 2;
      r -= (25 * n - 10) * n - 55;
      if (ver >= 7) r -= 36;
    }
    return r;
  }
  const dataCodewords = (ver, e) => Math.floor(rawModules(ver) / 8) - ECC_PER_BLOCK[e][ver] * NUM_BLOCKS[e][ver];
  function gfMul(x, y) {
    let z = 0;
    for (let i = 7; i >= 0; i--) {
      z = (z << 1) ^ ((z >>> 7) * 0x11d);
      z ^= ((y >>> i) & 1) * x;
    }
    return z & 0xff;
  }
  function rsDivisor(degree) {
    const r = new Array(degree).fill(0);
    r[degree - 1] = 1;
    let root = 1;
    for (let i = 0; i < degree; i++) {
      for (let j = 0; j < r.length; j++) {
        r[j] = gfMul(r[j], root);
        if (j + 1 < r.length) r[j] ^= r[j + 1];
      }
      root = gfMul(root, 0x02);
    }
    return r;
  }
  function rsRemainder(data, div) {
    const r = div.map(() => 0);
    for (const b of data) {
      const f = b ^ r.shift();
      r.push(0);
      div.forEach((c, i) => (r[i] ^= gfMul(c, f)));
    }
    return r;
  }

  function qrEncode(text, ecl) {
    ecl = ecl || "L";
    const bytes = [...new TextEncoder().encode(text)];
    let ver = 1;
    for (; ver <= 40; ver++) {
      const cc = ver < 10 ? 8 : 16;
      if (4 + cc + bytes.length * 8 <= dataCodewords(ver, ecl) * 8) break;
    }
    if (ver > 40) throw new Error("text too long for a QR code");
    const bits = [];
    const put = (v, n) => {
      for (let i = n - 1; i >= 0; i--) bits.push((v >>> i) & 1);
    };
    put(4, 4);
    put(bytes.length, ver < 10 ? 8 : 16);
    bytes.forEach((b) => put(b, 8));
    const cap = dataCodewords(ver, ecl) * 8;
    put(0, Math.min(4, cap - bits.length));
    put(0, (8 - (bits.length % 8)) % 8);
    for (let pad = 0xec; bits.length < cap; pad ^= 0xec ^ 0x11) put(pad, 8);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));

    const nb = NUM_BLOCKS[ecl][ver];
    const eccLen = ECC_PER_BLOCK[ecl][ver];
    const raw = Math.floor(rawModules(ver) / 8);
    const nShort = nb - (raw % nb);
    const shortLen = Math.floor(raw / nb);
    const div = rsDivisor(eccLen);
    const blocks = [];
    for (let i = 0, k = 0; i < nb; i++) {
      const dat = data.slice(k, k + shortLen - eccLen + (i < nShort ? 0 : 1));
      k += dat.length;
      const ecc = rsRemainder(dat, div);
      if (i < nShort) dat.push(0);
      blocks.push(dat.concat(ecc));
    }
    const codewords = [];
    for (let i = 0; i < blocks[0].length; i++)
      blocks.forEach((b, j) => {
        if (i !== shortLen - eccLen || j >= nShort) codewords.push(b[i]);
      });

    const size = ver * 4 + 17;
    const m = Array.from({ length: size }, () => new Array(size).fill(false));
    const fn = Array.from({ length: size }, () => new Array(size).fill(false));
    const setF = (x, y, d) => {
      m[y][x] = d;
      fn[y][x] = true;
    };
    for (let i = 0; i < size; i++) {
      setF(6, i, i % 2 === 0);
      setF(i, 6, i % 2 === 0);
    }
    for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]]) {
      for (let dy = -4; dy <= 4; dy++)
        for (let dx = -4; dx <= 4; dx++) {
          const d = Math.max(Math.abs(dx), Math.abs(dy));
          const x = cx + dx;
          const y = cy + dy;
          if (x >= 0 && x < size && y >= 0 && y < size) setF(x, y, d !== 2 && d !== 4);
        }
    }
    if (ver > 1) {
      const n = Math.floor(ver / 7) + 2;
      const step = ver === 32 ? 26 : Math.ceil((ver * 4 + 4) / (n * 2 - 2)) * 2;
      const pos = [6];
      for (let p = size - 7; pos.length < n; p -= step) pos.splice(1, 0, p);
      pos.forEach((px, i) =>
        pos.forEach((py, j) => {
          if ((i === 0 && j === 0) || (i === 0 && j === n - 1) || (i === n - 1 && j === 0)) return;
          for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) setF(px + dx, py + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
        }),
      );
    }
    const drawFormat = (mask) => {
      const d = (FORMAT_BITS[ecl] << 3) | mask;
      let rem = d;
      for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
      const b = ((d << 10) | rem) ^ 0x5412;
      for (let i = 0; i <= 5; i++) setF(8, i, qbit(b, i));
      setF(8, 7, qbit(b, 6));
      setF(8, 8, qbit(b, 7));
      setF(7, 8, qbit(b, 8));
      for (let i = 9; i < 15; i++) setF(14 - i, 8, qbit(b, i));
      for (let i = 0; i < 8; i++) setF(size - 1 - i, 8, qbit(b, i));
      for (let i = 8; i < 15; i++) setF(8, size - 15 + i, qbit(b, i));
      setF(8, size - 8, true);
    };
    drawFormat(0);
    if (ver >= 7) {
      let rem = ver;
      for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
      const b = (ver << 12) | rem;
      for (let i = 0; i < 18; i++) {
        const a = size - 11 + (i % 3);
        const c = Math.floor(i / 3);
        setF(a, c, qbit(b, i));
        setF(c, a, qbit(b, i));
      }
    }
    let i = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let v = 0; v < size; v++)
        for (let j = 0; j < 2; j++) {
          const x = right - j;
          const up = ((right + 1) & 2) === 0;
          const y = up ? size - 1 - v : v;
          if (!fn[y][x] && i < codewords.length * 8) {
            m[y][x] = qbit(codewords[i >>> 3], 7 - (i & 7));
            i++;
          }
        }
    }
    const masks = [
      (x, y) => (x + y) % 2 === 0,
      (_x, y) => y % 2 === 0,
      (x) => x % 3 === 0,
      (x, y) => (x + y) % 3 === 0,
      (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
      (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
      (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
      (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
    ];
    const apply = (k) => {
      for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (!fn[y][x] && masks[k](x, y)) m[y][x] = !m[y][x];
    };
    const penalty = () => {
      let p = 0;
      let dark = 0;
      const line = (get) => {
        for (let a = 0; a < size; a++) {
          let run = 0;
          let prev = null;
          let s = "";
          for (let b = 0; b < size; b++) {
            const c = get(a, b);
            s += c ? "1" : "0";
            if (c === prev) {
              run++;
              if (run === 5) p += 3;
              else if (run > 5) p++;
            } else {
              run = 1;
              prev = c;
            }
          }
          s = `0000${s}0000`;
          for (let k = s.indexOf("1011101"); k >= 0; k = s.indexOf("1011101", k + 1))
            if (s.slice(k - 4, k) === "0000" || s.slice(k + 7, k + 11) === "0000") p += 40;
        }
      };
      line((a, b) => m[a][b]);
      line((a, b) => m[b][a]);
      for (let y = 0; y < size; y++)
        for (let x = 0; x < size; x++) {
          if (m[y][x]) dark++;
          if (x < size - 1 && y < size - 1 && m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1]) p += 3;
        }
      const total = size * size;
      p += (Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1) * 10;
      return p;
    };
    let best = 0;
    let bestP = Infinity;
    for (let k = 0; k < 8; k++) {
      apply(k);
      drawFormat(k);
      const p = penalty();
      if (p < bestP) {
        bestP = p;
        best = k;
      }
      apply(k);
    }
    apply(best);
    drawFormat(best);
    return m;
  }

  /** Draws `text` as a QR code into `canvas` (crisp: whole device pixels per module). */
  function qr(text, canvas, opts) {
    opts = opts || {};
    if (!canvas || !text) return;
    const key = `${text}|${opts.dark || ""}|${opts.light || ""}|${opts.quiet == null ? 2 : opts.quiet}|${TV.pixelRatio.toFixed(3)}|${opts.size || ""}`;
    if (canvas._qrKey === key) return;
    let mods;
    try {
      mods = qrEncode(String(text), opts.ecl || "M");
    } catch {
      mods = qrEncode(String(text), "L");
    }
    const quiet = opts.quiet == null ? 2 : opts.quiet;
    const n = mods.length + quiet * 2;
    const css = opts.size || canvas.clientWidth || parseFloat(canvas.style.width) || canvas.width;
    if (opts.size) {
      canvas.style.width = `${css}px`;
      canvas.style.height = `${css}px`;
    }
    const per = Math.max(1, Math.floor((css * TV.pixelRatio) / n));
    const px = per * n;
    canvas.width = px;
    canvas.height = px;
    const g = canvas.getContext("2d");
    g.fillStyle = opts.light || "#ffffff";
    g.fillRect(0, 0, px, px);
    g.fillStyle = opts.dark || "#08080a";
    for (let y = 0; y < mods.length; y++)
      for (let x = 0; x < mods.length; x++) if (mods[y][x]) g.fillRect((x + quiet) * per, (y + quiet) * per, per, per);
    canvas._qrKey = key;
  }

  // =========================================================================================== surfaces
  // Software compositing (what a TV stick's browser often does, and any browser without GPU raster) copies every
  // visible 2D canvas on every composited frame, changed or not: with a wheel spinning, each big canvas on the page
  // was copied 60 times a second. A surface draws off-screen (OffscreenCanvas) and hands the visible canvas a
  // finished bitmap (ImageBitmapRenderingContext) only when its picture changed, so the compositor never reads the
  // drawing buffer. showSurface() leaves the drawing buffer blank (transferToImageBitmap): a caller redraws in full
  // before each show, as every user of a surface does. Without OffscreenCanvas / bitmaprenderer a surface is the
  // canvas's own 2D context and showSurface does nothing — the same picture either way.
  const SURF = (() => {
    try {
      return (
        typeof OffscreenCanvas === "function" &&
        typeof ImageBitmapRenderingContext === "function" &&
        typeof OffscreenCanvas.prototype.transferToImageBitmap === "function" &&
        !!new OffscreenCanvas(1, 1).getContext("2d")
      );
    } catch {
      return false;
    }
  })();

  /** The drawing surface of `canvas`, sized w×h device px: { g (its 2D context), w, h }. */
  function surface(canvas, w, h) {
    let s = canvas._surf;
    if (!s) {
      let br = null;
      if (SURF) {
        try {
          br = canvas.getContext("bitmaprenderer"); // null if the canvas already has a 2D context
        } catch {
          br = null;
        }
      }
      const off = br ? new OffscreenCanvas(1, 1) : null;
      s = canvas._surf = { br, off, g: (off || canvas).getContext("2d"), w: -1, h: -1 };
    }
    w = Math.max(1, Math.round(w));
    h = Math.max(1, Math.round(h));
    if (s.w !== w || s.h !== h) {
      s.w = w;
      s.h = h;
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
      if (s.off) {
        s.off.width = w;
        s.off.height = h;
      }
    }
    return s;
  }

  /** Put a surface's picture on screen: one bitmap hand-over (a plain canvas already shows it). */
  function showSurface(s) {
    if (s && s.br) s.br.transferFromImageBitmap(s.off.transferToImageBitmap());
  }

  function mk(w, h) {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h || w;
    return c;
  }

  // =========================================================================================== the panel
  // The studio's three looks (web/src/components/LedPanel.tsx, web/src/lib/look.ts), drawn the same way here:
  //  - "pixel": sharp square pixels (nearest-neighbour);
  //  - "glow":  the same sharp pixels with a soft bloom (two Gaussian blurs: σ 0.8 LED at 0.28, σ 2.4 LED at 0.2);
  //  - "led":   a physical LED matrix — rounded LEDs (13 % inset, 24 % corner radius) in a #060608 grille, unlit
  //             ones #15151b, very dim ones lifted a little (as the studio does, so they stay visible), a hot white
  //             core on bright ones, bloom σ 0.9 LED at 0.55 + σ 2.6 LED at 0.3.
  // Cheap by construction, identical in both tiers: the canvas is a whole number of device px per LED, and a new
  // frame costs one 32×32 putImageData, one nearest-neighbour upscale, the cached grille and a few core sprites
  // (LED). The bloom (glow, LED) is blurred on the CPU at 2 px per LED — three running-sum box blurs per Gaussian, no
  // canvas filter or shadowBlur — once per frame, shared by every panel, and shown as a 64×64 canvas laid over the
  // panel that the compositor scales up and adds (mix-blend-mode: plus-lighter): the same sum the studio draws
  // ("lighter"), without a full-size bilinear pass on the main thread. Browsers without plus-lighter get the bloom
  // drawn into the panel canvas instead (the same picture). A panel skips frames whose bytes didn't change.
  const BLOOMS = { led: [[0.9, 0.55], [2.6, 0.3]], glow: [[0.8, 0.28], [2.4, 0.2]] }; // [σ in LEDs, strength]
  const BLOOM_N = 64; // the bloom's grid (2 px per LED; the blurs are ≥ 0.8 LED wide, finer adds nothing)
  const LED_BG = "#060608";
  const LED_OFF = [0x15, 0x15, 0x1b];
  const pv = { data: null, raw: null, rawG: null, rawImg: null, led: null, ledG: null, ledImg: null, cores: null, coreN: 0, bloom: {}, bloomCanvas: {} };

  /** The frame as 32×32 images — raw (pixel, glow, the bloom) and the LED look's colours — and its hot cores. */
  function frameImages(data) {
    if (pv.data === data) return pv;
    if (!pv.raw) {
      pv.raw = mk(PANEL);
      pv.rawG = pv.raw.getContext("2d");
      pv.rawImg = pv.rawG.createImageData(PANEL, PANEL);
      pv.led = mk(PANEL);
      pv.ledG = pv.led.getContext("2d");
      pv.ledImg = pv.ledG.createImageData(PANEL, PANEL);
      pv.cores = new Float32Array(PANEL * PANEL * 3);
    }
    const a = pv.rawImg.data;
    const b = pv.ledImg.data;
    const cores = pv.cores;
    let n = 0;
    for (let p = 0, i = 0, j = 0; p < PANEL * PANEL; p++, i += 3, j += 4) {
      const r = data[i];
      const gg = data[i + 1];
      const bb = data[i + 2];
      a[j] = r;
      a[j + 1] = gg;
      a[j + 2] = bb;
      a[j + 3] = 255;
      const lum = r > gg ? (r > bb ? r : bb) : gg > bb ? gg : bb;
      if (lum < 6) {
        b[j] = LED_OFF[0];
        b[j + 1] = LED_OFF[1];
        b[j + 2] = LED_OFF[2];
      } else {
        const k = lum < 40 ? 1 + (40 - lum) / 60 : 1;
        b[j] = Math.min(255, Math.round(r * k));
        b[j + 1] = Math.min(255, Math.round(gg * k));
        b[j + 2] = Math.min(255, Math.round(bb * k));
        if (lum > 90) {
          cores[n++] = p & 31;
          cores[n++] = p >> 5;
          cores[n++] = (lum / 255) * 0.22;
        }
      }
      b[j + 3] = 255;
    }
    pv.coreN = n / 3;
    pv.rawG.putImageData(pv.rawImg, 0, 0);
    pv.ledG.putImageData(pv.ledImg, 0, 0);
    pv.data = data;
    pv.bloom = {};
    return pv;
  }

  // ------------------------------------------------------------------------------------------- the bloom
  const blur = { n: 0, src: null, tmp: null, work: null, out: null };

  /** Three box widths whose repeated box blur approximates a Gaussian of `sigma` (Kovesi). */
  function boxSizes(sigma) {
    let wl = Math.floor(Math.sqrt(4 * sigma * sigma + 1));
    if (wl % 2 === 0) wl--;
    const m = Math.round((12 * sigma * sigma - 3 * wl * wl - 12 * wl - 9) / (-4 * wl - 4));
    return [0, 1, 2].map((i) => (i < m ? wl : wl + 2));
  }

  /**
   * One box blur of radius r over an n×n RGB field (interleaved), along rows (step 3) or columns (step 3n), with
   * running sums. Past the edge counts as EDGE × the edge pixel: what the studio's canvas blur filter does in effect
   * (between transparent and a repeated edge; 0.35 fits it best), so a lit LED at the border glows as in the studio.
   */
  const EDGE = 0.35;
  function boxPass(src, dst, n, r, step) {
    const inv = 1 / (2 * r + 1);
    const across = step === 3 ? 3 * n : 3;
    const last = (n - 1) * step;
    for (let line = 0; line < n; line++) {
      const base = line * across;
      const end = base + last;
      const k0 = src[base] * EDGE;
      const k1 = src[base + 1] * EDGE;
      const k2 = src[base + 2] * EDGE;
      const e0 = src[end] * EDGE;
      const e1 = src[end + 1] * EDGE;
      const e2 = src[end + 2] * EDGE;
      let ar = k0 * r;
      let ag = k1 * r;
      let ab = k2 * r;
      for (let i = 0, o = base; i <= r; i++, o += step) {
        if (i < n) {
          ar += src[o];
          ag += src[o + 1];
          ab += src[o + 2];
        } else {
          ar += e0;
          ag += e1;
          ab += e2;
        }
      }
      for (let i = 0, o = base; i < n; i++, o += step) {
        dst[o] = ar * inv;
        dst[o + 1] = ag * inv;
        dst[o + 2] = ab * inv;
        if (i + r + 1 < n) {
          const q = o + (r + 1) * step;
          ar += src[q];
          ag += src[q + 1];
          ab += src[q + 2];
        } else {
          ar += e0;
          ag += e1;
          ab += e2;
        }
        if (i - r >= 0) {
          const q = o - r * step;
          ar -= src[q];
          ag -= src[q + 1];
          ab -= src[q + 2];
        } else {
          ar -= k0;
          ag -= k1;
          ab -= k2;
        }
      }
    }
  }

  /** bloomField into the shared buffer (no allocation per frame); false when the frame is dark. */
  function bloomInto(data, spec, n) {
    const N3 = n * n * 3;
    if (blur.n !== n) {
      blur.n = n;
      blur.src = new Float32Array(N3);
      blur.tmp = new Float32Array(N3);
      blur.work = new Float32Array(N3);
      blur.out = new Float32Array(N3);
    }
    const src = blur.src;
    const per = n / PANEL;
    let any = 0;
    for (let y = 0, o = 0; y < n; y++) {
      const row = Math.floor(y / per) * PANEL;
      for (let x = 0; x < n; x++, o += 3) {
        const i = (row + Math.floor(x / per)) * 3;
        src[o] = data[i];
        src[o + 1] = data[i + 1];
        src[o + 2] = data[i + 2];
        any |= data[i] | data[i + 1] | data[i + 2];
      }
    }
    const out = blur.out;
    out.fill(0);
    if (!any) return false;
    const t = blur.tmp;
    for (const [sigma, strength] of spec) {
      t.set(src);
      for (const w of boxSizes(sigma * per)) {
        const r = (w - 1) / 2;
        if (r < 1) continue;
        boxPass(t, blur.work, n, r, 3);
        boxPass(blur.work, t, n, r, 3 * n);
      }
      for (let i = 0; i < N3; i++) out[i] += t[i] * strength;
    }
    return true;
  }

  /**
   * A look's bloom of a frame as an n×n RGB field (a new Float32Array of n·n·3, interleaved): the studio's two
   * Gaussian blurs of the frame at their strengths, summed (each blur ≈ three box blurs). null for the pixel look.
   */
  function bloomField(data, look, n) {
    const spec = BLOOMS[look];
    if (!spec || !data) return null;
    n = n || BLOOM_N;
    bloomInto(data, spec, n);
    return blur.out.slice();
  }

  /** The bloom of the current frame (frameImages) as BLOOM_N² RGBA pixels, made once per frame and look; null if dark. */
  function bloomPixels(look) {
    if (look in pv.bloom) return pv.bloom[look];
    let img = null;
    if (BLOOMS[look] && pv.data && bloomInto(pv.data, BLOOMS[look], BLOOM_N)) {
      const f = blur.out;
      img = new ImageData(BLOOM_N, BLOOM_N);
      const d = img.data;
      for (let i = 0, j = 0; i < f.length; i += 3, j += 4) {
        d[j] = f[i];
        d[j + 1] = f[i + 1];
        d[j + 2] = f[i + 2];
        d[j + 3] = 255;
      }
    }
    pv.bloom[look] = img;
    return img;
  }
  /** The bloom as a small canvas (for drawing it into a panel canvas); null if dark. */
  function bloomImage(look) {
    const img = bloomPixels(look);
    if (!img) return null;
    const c = pv.bloomCanvas[look] || (pv.bloomCanvas[look] = mk(BLOOM_N));
    if (c._img !== img) {
      c.getContext("2d").putImageData(img, 0, 0);
      c._img = img;
    }
    return c;
  }

  // the bloom overlay: a BLOOM_N² canvas over the panel canvas, scaled and added by the compositor
  const PLUS_LIGHTER = (() => {
    try {
      return !!(window.CSS && CSS.supports && CSS.supports("mix-blend-mode", "plus-lighter"));
    } catch {
      return false;
    }
  })();
  /** The panel canvas's bloom overlay (made on first use), placed exactly over it; null if it can't be. */
  function bloomLayer(canvas, css) {
    if (!PLUS_LIGHTER || !canvas.parentNode) return null;
    let o = canvas._bloomEl;
    if (!o || o.parentNode !== canvas.parentNode) {
      o = canvas._bloomEl = mk(BLOOM_N);
      o.className = "tv-bloom";
      o.setAttribute("aria-hidden", "true");
      const st = o.style;
      st.position = "absolute";
      st.pointerEvents = "none";
      st.mixBlendMode = "plus-lighter";
      canvas.parentNode.insertBefore(o, canvas.nextSibling);
      o._at = "";
    }
    // the canvas's box in its parent (read only when the panel's size changes)
    const at = `${css}|${canvas.style.left}|${canvas.style.top}`;
    if (o._at !== at) {
      o._at = at;
      const st = o.style;
      st.left = `${canvas.offsetLeft}px`;
      st.top = `${canvas.offsetTop}px`;
      st.width = `${css}px`;
      st.height = `${css}px`;
      st.borderRadius = canvas.style.borderRadius || "";
    }
    return o;
  }

  // ------------------------------------------------------------------------------------------- the LED grille
  const grilles = new Map(); // D -> { grille, core, cell, s }
  function ledParts(D) {
    let p = grilles.get(D);
    if (p) return p;
    if (grilles.size > 6) grilles.clear();
    const cell = D / PANEL;
    const inset = cell * 0.13;
    const led = cell - inset * 2;
    const rad = led * 0.24;
    // the grille: the backplate with a rounded hole per LED (anti-aliased edges blend the LED into the plate)
    const grille = mk(D);
    const g = grille.getContext("2d");
    g.fillStyle = LED_BG;
    g.fillRect(0, 0, D, D);
    g.globalCompositeOperation = "destination-out";
    g.fillStyle = "#000";
    // one fill per LED, as the studio draws them: a lone rounded rect gets exact anti-aliasing (one path of 1024
    // of them goes through the supersampling rasterizer, whose edges come out a little different)
    for (let y = 0; y < PANEL; y++)
      for (let x = 0; x < PANEL; x++) {
        const x0 = x * cell + inset;
        const y0 = y * cell + inset;
        g.beginPath();
        if (g.roundRect) g.roundRect(x0, y0, led, led, rad);
        else {
          g.moveTo(x0 + rad, y0);
          g.arcTo(x0 + led, y0, x0 + led, y0 + led, rad);
          g.arcTo(x0 + led, y0 + led, x0, y0 + led, rad);
          g.arcTo(x0, y0 + led, x0, y0, rad);
          g.arcTo(x0, y0, x0 + led, y0, rad);
          g.closePath();
        }
        g.fill();
      }
    // the hot core of a bright LED: a white dot 30 % of the LED across
    const c = led * 0.3;
    const s = Math.ceil(c) + 2;
    const core = mk(s);
    const cg = core.getContext("2d");
    cg.fillStyle = "#fff";
    cg.beginPath();
    cg.arc(s / 2, s / 2, c / 2, 0, Math.PI * 2);
    cg.fill();
    p = { grille, core, cell, s };
    grilles.set(D, p);
    return p;
  }

  /** Paint the panel (D×D device px) in a look; data null = no frame yet (the panel dark). glow: draw the bloom in. */
  function paintPanel(g, D, data, look, glow) {
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalAlpha = 1;
    g.globalCompositeOperation = "source-over";
    if (!data) {
      g.fillStyle = look === "led" ? `rgb(${LED_OFF.join(",")})` : "#000";
      g.fillRect(0, 0, D, D);
      if (look === "led") g.drawImage(ledParts(D).grille, 0, 0);
      return;
    }
    const f = frameImages(data);
    g.imageSmoothingEnabled = false;
    g.drawImage(look === "led" ? f.led : f.raw, 0, 0, D, D);
    if (look === "led") {
      const p = ledParts(D);
      g.drawImage(p.grille, 0, 0);
      const h = p.s / 2;
      const cores = f.cores;
      for (let i = 0; i < f.coreN * 3; i += 3) {
        g.globalAlpha = cores[i + 2];
        g.drawImage(p.core, (cores[i] + 0.5) * p.cell - h, (cores[i + 1] + 0.5) * p.cell - h);
      }
      g.globalAlpha = 1;
    }
    if (glow && look !== "pixel") {
      const b = bloomImage(look);
      if (b) {
        g.globalCompositeOperation = "lighter";
        g.imageSmoothingEnabled = true;
        g.drawImage(b, 0, 0, D, D);
        g.globalCompositeOperation = "source-over";
      }
    }
  }

  const drawn = new Set(); // canvases drawn with drawPanel (redrawn on a resize or a look change)

  function sameFrame(a, b) {
    if (!a || !b) return a === b;
    for (let i = 0; i < FRAME_BYTES; i++) if (a[i] !== b[i]) return false;
    return true;
  }

  /**
   * Paints a 32×32 RGB frame big, in the TV's look (opts.look overrides it for this canvas).
   * opts: pitch (stage px per LED; sets the CSS size), data (another 3072-byte frame), look ("pixel" | "led" |
   * "glow"), glow (0 / false turns the bloom off). Nothing is drawn when the frame, size and look are unchanged.
   */
  function drawPanel(canvas, opts) {
    if (!canvas) return;
    opts = opts || {};
    const src = opts.data || ctx.panel;
    const data = src && src.length >= FRAME_BYTES ? src : null;
    let css;
    if (opts.pitch) {
      css = PANEL * opts.pitch;
      const w = `${css}px`;
      if (canvas.style.width !== w) {
        canvas.style.width = w;
        canvas.style.height = w;
      }
    } else css = canvas.clientWidth || parseFloat(canvas.style.width) || canvas.width / TV.pixelRatio || 320;
    canvas._ledOpts = opts;
    drawn.add(canvas);
    const look = LOOKS.includes(opts.look) ? opts.look : TV.look;
    const glow = opts.glow === 0 || opts.glow === false ? 0 : 1;
    // the canvas's real device pixels, a whole number per LED (crisp squares), capped
    const D = Math.max(PANEL, Math.min(1600, Math.round((css * TV.pixelRatio) / PANEL) * PANEL));
    const st = canvas._pv || (canvas._pv = { data: undefined, bytes: null, D: 0, look: "", glow: -1 });
    if (st.D === D && st.look === look && st.glow === glow && (st.data === data || sameFrame(st.bytes, data))) {
      st.data = data;
      return; // a status update, or the same frame again: the canvas already shows it
    }
    st.data = data;
    st.D = D;
    st.look = look;
    st.glow = glow;
    if (data) {
      if (!st.bytes) st.bytes = new Uint8Array(FRAME_BYTES);
      for (let i = 0; i < FRAME_BYTES; i++) st.bytes[i] = data[i];
    } else st.bytes = null;
    // the panel itself is a plain canvas: it changes with nearly every frame anyway, and a surface's bitmap
    // hand-over costs more than the compositor's copy of a canvas this size
    if (canvas.width !== D) canvas.width = D;
    if (canvas.height !== D) canvas.height = D;
    const g = canvas.getContext("2d");
    const wantBloom = !!(glow && data && look !== "pixel");
    const layer = wantBloom ? bloomLayer(canvas, css) : null;
    paintPanel(g, D, data, look, wantBloom && !layer);
    const img = layer ? bloomPixels(look) : null;
    if (img) {
      if (layer._img !== img) {
        layer.getContext("2d").putImageData(img, 0, 0);
        layer._img = img;
      }
      if (layer.style.display) layer.style.display = "";
    } else if (canvas._bloomEl && canvas._bloomEl.style.display !== "none") canvas._bloomEl.style.display = "none";
  }

  function redrawPanels() {
    for (const c of [...drawn]) {
      if (!c.isConnected) drawn.delete(c);
      else drawPanel(c, c._ledOpts);
    }
  }

  // =========================================================================================== avatars
  function hexRgb(h) {
    const m = /^#?([0-9a-f]{6})$/i.exec(String(h || ""));
    const v = m ? parseInt(m[1], 16) : 0xf0f0f0;
    return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
  }

  /** An 8×8 avatar (hello.avatars) in a player colour, pixel-crisp. */
  function drawAvatar(canvas, id, color) {
    if (!canvas) return;
    const art = (ctx.avatars || {})[id];
    const css = canvas.clientWidth || parseFloat(canvas.style.width) || 48;
    const k = Math.max(1, Math.round((css * TV.pixelRatio) / 8));
    canvas.width = canvas.height = 8 * k;
    canvas.classList.add("tv-avatar");
    const g = canvas.getContext("2d");
    g.clearRect(0, 0, 8 * k, 8 * k);
    const [r, gg, b] = hexRgb(color);
    const pal = {
      c: `rgb(${r},${gg},${b})`,
      d: `rgb(${Math.round(r * 0.55)},${Math.round(gg * 0.55)},${Math.round(b * 0.55)})`,
      w: "#f0f0f0",
      k: "#000000",
      y: "#ffc800",
      r: "#ff3c3c",
    };
    if (!art) {
      g.fillStyle = pal.c;
      g.beginPath();
      g.arc(4 * k, 4 * k, 3 * k, 0, Math.PI * 2);
      g.fill();
      return;
    }
    art.px.forEach((row, y) => {
      for (let x = 0; x < 8; x++) {
        const f = pal[row[x]];
        if (f) {
          g.fillStyle = f;
          g.fillRect(x * k, y * k, k, k);
        }
      }
    });
  }

  // =========================================================================================== the context
  let clockOffset = 0; // server seconds - local seconds
  const ctx = {
    app: null,
    meta: null,
    status: {},
    lobby: null,
    tv: null,
    panel: null,
    frameAt: 0,
    stateAt: 0,
    connected: false,
    avatars: {},
    theme: {},
    now,
    serverNow: () => now() + clockOffset,
    drawPanel,
    drawAvatar,
    qr,
    fmt,
    el,
    esc,
    seatColor(n) {
      const s = ((ctx.lobby && ctx.lobby.seats) || []).find((x) => x.seat === n);
      return (s && s.color) || SEAT_COLORS[n] || "#f0f0f0";
    },
  };
  TV.ctx = ctx;

  function setOffset(serverTime, rtt) {
    if (typeof serverTime !== "number") return;
    const off = serverTime - (now() - (rtt || 0) / 2);
    // first sample sets it, later ones smooth it (a socket's latency jitters)
    clockOffset = clockOffset === 0 ? off : clockOffset * 0.8 + off * 0.2;
  }

  // =========================================================================================== scenes
  let current = null; // {scene, root}
  const broken = new Set(); // `${scene id}|${app}` that threw: the generic scene stands in

  function safe(fn) {
    try {
      return fn();
    } catch (e) {
      console.error("DeskDot TV scene error:", e);
      if (current && current.scene !== GENERIC) {
        broken.add(`${current.scene.id}|${ctx.app}`);
        queueMicrotask(pickScene);
      }
      return undefined;
    }
  }

  function registerScene(scene) {
    if (!scene || typeof scene.match !== "function" || typeof scene.mount !== "function") {
      console.warn("DeskDot TV: a scene needs match() and mount()", scene);
      return;
    }
    TV.scenes = TV.scenes.filter((s) => s.id !== scene.id);
    TV.scenes.push(scene);
    if (started) pickScene();
  }

  function choose() {
    for (const s of TV.scenes) {
      if (broken.has(`${s.id}|${ctx.app}`)) continue;
      let ok = false;
      try {
        ok = !!s.match(ctx.app, ctx.meta, ctx.status);
      } catch (e) {
        console.error(`DeskDot TV: ${s.id}.match failed`, e);
      }
      if (ok) return s;
    }
    return GENERIC;
  }

  function pickScene() {
    const next = choose();
    if (current && current.scene === next) return false;
    const host = $("scene");
    if (current) {
      const old = current;
      current = null;
      try {
        if (old.scene.unmount) old.scene.unmount();
      } catch (e) {
        console.error("DeskDot TV: unmount failed", e);
      }
      old.root.remove();
    }
    const root = el("div", "tv-scene");
    root.dataset.scene = next.id;
    host.appendChild(root);
    current = { scene: next, root };
    safe(() => next.mount(root, ctx));
    probe();
    if (current && current.scene === next) {
      safe(() => next.update && next.update(ctx));
      if (ctx.panel) safe(() => next.frame && next.frame(ctx));
    }
    return true;
  }

  // =========================================================================================== the bar
  const CATEGORY = {
    games: "Games",
    casino: "Casino",
    arcade: "Arcade",
    pets: "Pets",
    productivity: "Productivity",
    time: "Time",
    data: "Live data",
    media: "Media",
    ambient: "Ambient",
    creative: "Creative",
    fun: "Fun",
    system: "System",
  };
  const catName = (c) => CATEGORY[c] || (c ? String(c).replace(/[_-]/g, " ") : "");

  function renderBar() {
    const name = (ctx.meta && ctx.meta.name) || (ctx.app ? ctx.app : "DeskDot");
    $("bar-name").textContent = ctx.connected || ctx.app ? name : "Connecting…";
    $("bar-cat").textContent = ctx.meta ? catName(ctx.meta.category) : "";
    document.title = ctx.meta ? `${name} · DeskDot TV` : "DeskDot TV";
    const lob = ctx.lobby;
    const join = $("bar-join");
    if (lob && lob.url) {
      join.hidden = false;
      $("bar-code").textContent = lob.code || "";
      qr(lob.url, $("bar-qr"), { size: 72, quiet: 1 });
    } else join.hidden = true;
  }

  function tickClock() {
    const d = new Date(Date.now() + 0);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const c = $("bar-clock");
    if (c) c.textContent = `${hh}:${mm}`;
  }

  function setDot(state) {
    const d = $("bar-dot");
    if (d) d.dataset.on = state;
  }

  // =========================================================================================== veil
  function veil(state) {
    const v = $("veil");
    if (!v) return;
    if (!state) {
      if (!v.hidden && !v.classList.contains("fade")) {
        v.classList.add("fade");
        setTimeout(() => {
          if (v.classList.contains("fade")) v.hidden = true;
        }, 650);
      }
      return;
    }
    const S = {
      waiting: ["busy", "Waiting for DeskDot…", "Connecting to the computer running DeskDot. Keep it on and on the same network as this screen."],
      closed: ["bad", "This TV link has closed", "Open Show on TV in the DeskDot studio and scan the new QR code, or type its address here."],
      full: ["bad", "Too many screens are watching", "Close the TV view on another screen, then this one connects by itself."],
      bad: ["bad", "That TV link doesn't look right", "Open Show on TV in the DeskDot studio and use the address it shows."],
    }[state];
    v.dataset.tone = S[0];
    $("veil-title").textContent = S[1];
    $("veil-text").textContent = S[2];
    $("veil-code").textContent = /^[A-Z0-9]{4}$/.test(code) ? `TV CODE  ${code}` : "";
    v.classList.remove("fade");
    v.hidden = false;
  }

  // =========================================================================================== the socket
  const link = { ws: null, tries: 0, timer: 0, ping: 0, lastMsg: 0, closed: false, gen: 0 };

  function connect() {
    clearTimeout(link.timer);
    if (link.ws) return;
    const gen = ++link.gen;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    let ws;
    try {
      ws = new WebSocket(`${proto}//${location.host}/ws/tv/${code}`);
    } catch (e) {
      console.warn("DeskDot TV: couldn't open the socket", e);
      return retry();
    }
    ws.binaryType = "arraybuffer";
    link.ws = ws;
    link.lastMsg = now();
    ws.onopen = () => {
      if (gen !== link.gen) return;
      link.tries = 0;
      sendPing();
    };
    ws.onmessage = (e) => {
      if (gen !== link.gen) return;
      link.lastMsg = now();
      if (typeof e.data === "string") onText(e.data);
      else onFrame(new Uint8Array(e.data));
    };
    ws.onclose = () => {
      if (gen !== link.gen) return;
      link.ws = null;
      ctx.connected = false;
      setDot(link.closed ? "bad" : "warn");
      if (link.closed) return later(20000);
      veil("waiting");
      retry();
    };
    ws.onerror = () => {
      /* onclose follows */
    };
  }

  function later(ms) {
    clearTimeout(link.timer);
    link.timer = setTimeout(() => {
      link.closed = false;
      connect();
    }, ms);
  }

  function retry() {
    const ms = Math.min(8000, 500 * 2 ** Math.min(link.tries++, 4));
    clearTimeout(link.timer);
    link.timer = setTimeout(connect, ms);
  }

  function sendPing() {
    const ws = link.ws;
    if (ws && ws.readyState === 1) {
      try {
        ws.send(JSON.stringify({ type: "ping", t: now() }));
      } catch {
        /* closing */
      }
    }
  }

  function watchdog() {
    // a TV on Wi-Fi can lose the socket without a close event: nothing for 8 s → start over
    if (link.ws && now() - link.lastMsg > 8) {
      try {
        link.ws.close();
      } catch {
        /* closed */
      }
      link.gen++;
      link.ws = null;
      ctx.connected = false;
      setDot("warn");
      veil("waiting");
      retry();
    }
  }

  function onText(txt) {
    let m;
    try {
      m = JSON.parse(txt);
    } catch {
      return;
    }
    if (!m || typeof m !== "object") return;
    if (m.type === "hello") {
      setOffset(m.server_time, 0);
      ctx.app = m.app || null;
      ctx.meta = m.meta || null;
      if (m.avatars) ctx.avatars = m.avatars;
      onStudioDisplay(m.display); // the studio's look / quality for every TV (POST /api/tv/settings)
      ctx.connected = true;
      link.closed = false;
      setDot("ok");
      veil(null);
      renderBar();
      pickScene();
    } else if (m.type === "state") {
      setOffset(m.server_time, 0);
      ctx.connected = true;
      if ((m.app || null) !== ctx.app) ctx.app = m.app || null;
      ctx.status = m.status && typeof m.status === "object" ? m.status : {};
      ctx.lobby = m.lobby || null;
      ctx.tv = m.tv || null; // TV-only anchors (docs/TV_VIEW.md §3): e.g. a locked casino round's outcome + clock
      ctx.stateAt = now();
      onStudioDisplay(m.display);
      applyTheme(ctx.status.table_theme);
      renderBar();
      if (!pickScene() && current) safe(() => current.scene.update && current.scene.update(ctx));
    } else if (m.type === "pong") {
      if (typeof m.t === "number") setOffset(m.server_time, Math.max(0, now() - m.t));
    } else if (m.type === "closed" || m.type === "full") {
      link.closed = true;
      ctx.connected = false;
      setDot("bad");
      veil(m.type);
    }
  }

  let frameWaiting = false;
  function onFrame(buf) {
    if (buf.length !== FRAME_BYTES) return;
    ctx.panel = buf;
    ctx.frameAt = now();
    // latest wins: drawn by the animation loop's next frame, skipping frames that arrive faster than the screen
    frameWaiting = true;
    kickLoop();
  }

  // =========================================================================================== table theme
  let themeId = null;
  function applyTheme(t) {
    const id = (t && t.id) || null;
    ctx.theme = (t && t.css) || {};
    if (id === themeId) return;
    themeId = id;
    const st = $("stage").style;
    const css = ctx.theme;
    const map = {
      "--felt": css.felt,
      "--felt2": css.felt2,
      "--felt3": css.felt3,
      "--accent": css.accent,
      "--accent-hi": css.accent_hi,
      "--accent-lo": css.accent_lo,
      "--accent-deep": css.accent_deep,
      "--accent-rgb": css.accent_rgb,
      "--ink": css.ink,
      // the bar and the page around the scene (tv.html: stage[data-table])
      "--wing": css.wing2 || css.wing,
      "--wing3": css.wing3,
      "--bar-line": css.accent_rgb ? `rgba(${css.accent_rgb}, .38)` : null,
      "--bar-tint": css.accent_rgb ? `rgba(${css.accent_rgb}, .16)` : null,
    };
    for (const [k, v] of Object.entries(map)) {
      if (v) st.setProperty(k, v);
      else st.removeProperty(k);
    }
    $("stage").dataset.theme = id || "";
    $("stage").dataset.table = id ? "1" : ""; // a casino table: the bar and the page take its theme
  }

  // =========================================================================================== generic scene
  // The live panel as a huge LED matrix in its bezel, the app's name and its simple status values at the side,
  // the lobby's players when friends are joining. Every app without a scene of its own shows this.
  const SKIP = new Set(["rev", "casino", "edges", "table_theme", "view", "lobby", "max_players", "game", "name", "id", "app", "seq", "hash", "commit", "seed", "server_seed", "deal"]);
  const LABELS = { hi: "Best", best: "Best", score: "Score", lvl: "Level", level: "Level", lives: "Lives", player: "Player", turn: "Turn", phase: "Phase", flow: "Now", round: "Round", lines: "Lines", time: "Time", mode: "Mode" };
  const FLOW = { demo: "AI demo", home: "Menu on panel", teams: "Picking sides", intro: "Get ready", play: "Playing", outro: "Results" };

  function statusItems(st) {
    const out = [];
    for (const [k, v] of Object.entries(st || {})) {
      if (SKIP.has(k) || k.startsWith("_")) continue;
      let val;
      if (typeof v === "number") val = fmt(v);
      else if (typeof v === "boolean") val = v ? "Yes" : "No";
      else if (typeof v === "string" && v.length && v.length <= 28) val = k === "flow" ? FLOW[v] || v : v;
      else continue;
      out.push([LABELS[k] || k.replace(/_/g, " "), val]);
      if (out.length >= 8) break;
    }
    return out;
  }

  const GENERIC = {
    id: "generic",
    match: () => true,
    mount(root) {
      this.root = root;
      this.amb = [255, 72, 24];
      this.ambA = 0.12;
      root.innerHTML = `
        <div class="g-ambient"></div><div class="g-floor"></div>
        <div class="g-panel"><div class="tv-bezel"><i class="tv-screw tl"></i><i class="tv-screw tr"></i><i class="tv-screw bl"></i><i class="tv-screw br"></i>
          <div class="tv-well"><canvas class="g-led"></canvas></div></div></div>
        <div class="g-side">
          <div class="g-cat"><i></i><span class="tv-label g-catname"></span></div>
          <div class="g-name"></div>
          <div class="g-chips"></div>
          <div class="g-lobby" hidden><div class="tv-label" style="margin-bottom:16px">Players</div><div class="g-players"></div></div>
          <div class="g-hint">Live from the DeskDot panel</div>
        </div>`;
      this.canvas = root.querySelector(".g-led");
      this.ambEl = root.querySelector(".g-ambient");
      this.chipsKey = "";
      this.lobbyKey = "";
      drawPanel(this.canvas, { pitch: 24, glow: 0.65, round: true });
    },
    update(c) {
      const r = this.root;
      r.querySelector(".g-catname").textContent = c.meta ? catName(c.meta.category) || "Now showing" : "Now showing";
      r.querySelector(".g-name").textContent = (c.meta && c.meta.name) || "DeskDot";
      const items = statusItems(c.status);
      const key = JSON.stringify(items);
      if (key !== this.chipsKey) {
        this.chipsKey = key;
        const box = r.querySelector(".g-chips");
        box.replaceChildren(
          ...items.map(([k, v]) => {
            const s = el("div", "g-stat");
            s.append(el("div", "tv-label", k), el("b", null, v));
            return s;
          }),
        );
      }
      const seats = (c.lobby && c.lobby.seats) || [];
      const lkey = JSON.stringify(seats);
      if (lkey !== this.lobbyKey) {
        this.lobbyKey = lkey;
        const wrap = r.querySelector(".g-lobby");
        wrap.hidden = !c.lobby;
        const list = r.querySelector(".g-players");
        list.replaceChildren(
          ...seats.slice(0, 6).map((s) => {
            const row = el("div", "g-player");
            row.style.setProperty("--c", s.color || "#888");
            const cv = el("canvas");
            row.append(cv, el("span", null, s.name || `P${s.seat}`), el("em", s.ready ? "ready" : "", s.ready ? "Ready" : `Seat ${s.seat}`));
            requestAnimationFrame(() => drawAvatar(cv, s.avatar, s.color));
            return row;
          }),
        );
        if (c.lobby && !seats.length) list.replaceChildren(el("div", "g-desc", "Scan the code at the top to join."));
      }
    },
    frame(c) {
      drawPanel(this.canvas, { pitch: 24, glow: 0.65 });
      // bias lighting: the wall behind the panel takes on its average colour
      const p = c.panel;
      let r = 0;
      let g = 0;
      let b = 0;
      for (let i = 0; i < FRAME_BYTES; i += 3) {
        r += p[i];
        g += p[i + 1];
        b += p[i + 2];
      }
      const n = FRAME_BYTES / 3;
      const lum = (r + g + b) / (n * 3 * 255);
      const m = Math.max(r, g, b) || 1;
      const t = [(r / m) * 255, (g / m) * 255, (b / m) * 255];
      for (let i = 0; i < 3; i++) this.amb[i] += (t[i] - this.amb[i]) * 0.25;
      this.ambA += (Math.min(0.32, 0.06 + lum * 0.9) - this.ambA) * 0.25;
      // the glow is a 1700 px gradient: repaint it at most twice a second, and only when it visibly changed
      // (a per-frame repaint of it was a main cause of stutter on TV sticks; at ≤ 2 Hz it costs nothing)
      const nowS = now();
      const amb = this.amb.map((v) => Math.round(v / 8) * 8).join(",");
      const a = (Math.round(this.ambA * 50) / 50).toFixed(2);
      if (nowS - (this.ambAt || 0) < 0.5 || (amb === this.ambKey && a === this.ambAKey)) return;
      this.ambAt = nowS;
      this.ambKey = amb;
      this.ambAKey = a;
      this.ambEl.style.setProperty("--amb", amb);
      this.ambEl.style.setProperty("--amb-a", a);
    },
    unmount() {
      this.root = null;
    },
  };

  // =========================================================================================== the options menu
  // A small overlay for a TV remote (Fire TV / Android TV: the D-pad, OK / select, Back, the menu key) and for a
  // mouse or a keyboard: "Panel look: Pixel · LED · Glow" and "Quality: Auto · HQ · Lite". OK / select / menu (Enter
  // or M on a keyboard, a click or a tap) opens it; the arrows move the highlight, OK picks — applied at once,
  // remembered on this TV — and Back / Escape (or the menu key again) closes it; it closes itself after 8 s without
  // a key. Back on a TV browser goes back in history, so an open menu holds one history entry and Back pops it.
  const MENU_IDLE_MS = 8000;
  const SWATCH = ["#ff3f78", "#ffcc33", "#36c5f0", "#3ddc84", "#ff4818", "#ffcc33", "#36c5f0", "#ff3f78", "#3ddc84"];
  const swatch = (kind) => {
    const cells = SWATCH.map((c, i) => {
      const x = (i % 3) * 20;
      const y = Math.floor(i / 3) * 20;
      return kind === "led"
        ? `<rect x="${x + 2.6}" y="${y + 2.6}" width="14.8" height="14.8" rx="3.6" fill="${c}"/>`
        : `<rect x="${x}" y="${y}" width="20" height="20" fill="${c}"/>`;
    }).join("");
    const bg = kind === "led" ? '<rect width="60" height="60" fill="#060608"/>' : "";
    const glow = kind === "glow" ? `<g filter="url(#tvm-soft)" opacity=".9">${cells}</g>` : "";
    return `<svg viewBox="0 0 60 60" aria-hidden="true">${bg}${glow}${cells}</svg>`;
  };
  const MENU_ROWS = [
    {
      key: "look", label: "Panel look", opts: LOOKS, names: LOOK_NAMES,
      hints: { pixel: "Sharp square pixels", led: "Like the real LED panel", glow: "Sharp pixels, soft glow" },
    },
    {
      key: "quality", label: "Quality", opts: QUALITIES, names: QUALITY_NAMES,
      hints: { auto: "Picks for this screen", hq: "Full quality, always", lite: "Same picture, less work" },
    },
  ]; // fmt: skip
  const menu = { el: null, open: false, row: 0, col: 0, timer: 0, hideTimer: 0, pushed: false, skipPop: false };

  function buildMenu() {
    const stage = $("stage");
    if (!stage) return null;
    const m = el("div");
    m.id = "tv-menu";
    m.hidden = true;
    m.setAttribute("role", "dialog");
    m.setAttribute("aria-label", "Display options");
    const rows = MENU_ROWS.map((r, ri) => {
      const opts = r.opts.map((v, ci) =>
        `<button type="button" class="tvm-opt" role="radio" data-row="${ri}" data-col="${ci}" aria-checked="false">` +
        `${r.key === "look" ? swatch(v) : ""}<div><b>${esc(r.names[v])}</b><span>${esc(r.hints[v])}</span></div></button>`,
      ).join("");
      return `<div class="tvm-row" role="radiogroup" aria-label="${esc(r.label)}"><div class="tvm-label">${esc(r.label)}<small></small></div><div class="tvm-opts">${opts}</div></div>`;
    }).join("");
    m.innerHTML =
      '<svg width="0" height="0" style="position:absolute"><filter id="tvm-soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="3.2"/></filter></svg>' +
      `<div class="tvm-card"><div class="tvm-head"><div class="tvm-title">Display</div><div class="tvm-sub">This TV</div></div>${rows}` +
      '<div class="tvm-hint"><span><kbd>◀ ▶</kbd><kbd>▲ ▼</kbd>Move</span><span><kbd>OK</kbd>Choose</span><span><kbd>Back</kbd>Close</span></div></div>';
    m.addEventListener("pointerover", (e) => {
      const opt = e.target.closest && e.target.closest(".tvm-opt");
      if (!opt) return;
      menu.row = Number(opt.dataset.row);
      menu.col = Number(opt.dataset.col);
      bumpMenu();
      renderMenu();
    });
    stage.appendChild(m);
    menu.el = m;
    return m;
  }

  function renderMenu() {
    const m = menu.el;
    if (!m) return;
    const cur = { look: TV.look, quality: TV.qualityMode };
    m.querySelectorAll(".tvm-opt").forEach((b) => {
      const r = MENU_ROWS[Number(b.dataset.row)];
      const v = r.opts[Number(b.dataset.col)];
      b.setAttribute("aria-checked", String(cur[r.key] === v));
      b.classList.toggle("focus", menu.open && Number(b.dataset.row) === menu.row && Number(b.dataset.col) === menu.col);
      if (r.key === "quality" && v === "auto") {
        const hint = b.querySelector("span");
        const text = TV.qualityMode === "auto" ? `Picks for this screen · now ${TV.quality === "lite" ? "Lite" : "HQ"}` : r.hints.auto;
        if (hint.textContent !== text) hint.textContent = text;
      }
    });
    m.querySelectorAll(".tvm-row").forEach((row, ri) => {
      const from = disp.from[MENU_ROWS[ri].key];
      const note = from === "studio" ? "Set from the studio" : from === "url" ? "Set in the address" : "";
      const small = row.querySelector("small");
      if (small.textContent !== note) small.textContent = note;
    });
  }

  function bumpMenu() {
    clearTimeout(menu.timer);
    menu.timer = setTimeout(() => closeMenu(), MENU_IDLE_MS);
  }

  function openMenu() {
    const m = menu.el || buildMenu();
    if (!m || menu.open) return;
    menu.open = true;
    menu.row = 0;
    menu.col = Math.max(0, LOOKS.indexOf(TV.look));
    clearTimeout(menu.hideTimer);
    m.hidden = false;
    renderMenu();
    requestAnimationFrame(() => menu.open && m.classList.add("on"));
    bumpMenu();
    // Back on a TV remote navigates history: hold one entry while the menu is open, so Back only closes it
    try {
      if (!menu.pushed && history.pushState) {
        history.pushState({ tvMenu: 1 }, "");
        menu.pushed = true;
      }
    } catch {
      menu.pushed = false;
    }
  }

  function closeMenu(viaHistory) {
    if (!menu.open || !menu.el) return;
    menu.open = false;
    clearTimeout(menu.timer);
    const m = menu.el;
    m.classList.remove("on");
    menu.hideTimer = setTimeout(() => {
      if (!menu.open) m.hidden = true;
    }, 220);
    renderMenu();
    if (menu.pushed) {
      menu.pushed = false;
      if (!viaHistory) {
        menu.skipPop = true;
        try {
          history.back();
        } catch {
          menu.skipPop = false;
        }
      }
    }
  }

  function onMenuPop() {
    if (menu.skipPop) {
      menu.skipPop = false;
      return;
    }
    if (menu.open) {
      menu.pushed = false;
      closeMenu(true);
    }
  }

  function pickFocused() {
    const r = MENU_ROWS[menu.row];
    const v = r && r.opts[menu.col];
    if (v) choose(r.key, v);
  }

  /** A key as the menu understands it: TV remotes send the arrows and Enter; Back varies by browser. */
  function menuKey(e) {
    const k = e.key;
    const c = e.keyCode;
    if (k === "ArrowLeft" || k === "Left" || c === 37) return "left";
    if (k === "ArrowRight" || k === "Right" || c === 39) return "right";
    if (k === "ArrowUp" || k === "Up" || c === 38) return "up";
    if (k === "ArrowDown" || k === "Down" || c === 40) return "down";
    if (k === "Enter" || k === " " || k === "Select" || k === "Accept" || c === 13) return "ok";
    if (k === "Escape" || k === "GoBack" || k === "BrowserBack" || k === "Backspace" || c === 27 || c === 4 || c === 8 || c === 461 || c === 10009) return "back";
    if (k === "ContextMenu" || k === "Menu" || k === "MediaPlayPause" || k === "m" || k === "M" || c === 93 || c === 179 || (c === 82 && k !== "r" && k !== "R")) return "menu";
    return null;
  }

  function onMenuKey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = menuKey(e);
    if (!k) return;
    if (!menu.open) {
      if (k === "ok" || k === "menu") {
        e.preventDefault();
        openMenu();
      }
      return; // Back with the menu closed: the browser's own (leave the page)
    }
    e.preventDefault();
    bumpMenu();
    if (k === "back" || k === "menu") return closeMenu();
    if (k === "ok") return pickFocused();
    const n = MENU_ROWS[menu.row].opts.length;
    if (k === "left") menu.col = (menu.col + n - 1) % n;
    else if (k === "right") menu.col = (menu.col + 1) % n;
    else {
      menu.row = (menu.row + (k === "up" ? MENU_ROWS.length - 1 : 1)) % MENU_ROWS.length;
      menu.col = Math.min(menu.col, MENU_ROWS[menu.row].opts.length - 1);
    }
    renderMenu();
  }

  function onStageClick(e) {
    const t = e.target;
    const opt = t && t.closest && t.closest(".tvm-opt");
    if (!menu.open) return openMenu();
    bumpMenu();
    if (opt) {
      menu.row = Number(opt.dataset.row);
      menu.col = Number(opt.dataset.col);
      pickFocused();
    } else if (!(t && t.closest && t.closest(".tvm-card"))) closeMenu();
  }

  // =========================================================================================== chrome: cursor, wake lock
  let cursorTimer = 0;
  function wakeCursor() {
    document.body.classList.remove("nocursor");
    clearTimeout(cursorTimer);
    cursorTimer = setTimeout(() => document.body.classList.add("nocursor"), 3000);
  }

  let wakeLock = null;
  async function keepAwake() {
    if (document.visibilityState !== "visible" || !("wakeLock" in navigator)) return;
    if (wakeLock && !wakeLock.released) return;
    try {
      wakeLock = await navigator.wakeLock.request("screen");
    } catch {
      wakeLock = null; // not allowed (no user gesture yet on some browsers): try again on the next tap / visibility
    }
  }

  // =========================================================================================== start
  let started = false;
  function start() {
    if (started) return;
    started = true;
    fit();
    window.addEventListener("resize", fit);
    if (window.matchMedia) {
      // devicePixelRatio changes (moving the window to another screen, browser zoom) don't fire resize everywhere
      const watch = () => {
        const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
        const on = () => {
          fit();
          watch();
        };
        if (mq.addEventListener) mq.addEventListener("change", on, { once: true });
      };
      watch();
    }
    const ratio = () => TV.pixelRatio;
    if ($("bar-logo")) logos.push(DeskDotLogo.mount($("bar-logo"), { pitch: 6, grid: true, dpr: ratio }));
    if ($("veil-logo")) logos.push(DeskDotLogo.mount($("veil-logo"), { pitch: 22, grid: true, dpr: ratio }));
    tickClock();
    setInterval(tickClock, 1000);
    setInterval(sendPing, 5000);
    setInterval(watchdog, 2000);
    ["mousemove", "pointerdown", "keydown"].forEach((t) => window.addEventListener(t, wakeCursor, { passive: true }));
    ["pointerdown", "keydown"].forEach((t) => window.addEventListener(t, keepAwake, { passive: true }));
    // the options menu: OK / select / menu on a TV remote, Enter / M on a keyboard, a click or a tap
    window.addEventListener("keydown", onMenuKey);
    window.addEventListener("popstate", onMenuPop);
    if ($("stage")) $("stage").addEventListener("click", onStageClick);
    wakeCursor();
    document.addEventListener("visibilitychange", () => {
      keepAwake();
      if (document.visibilityState === "visible" && !link.ws && !link.closed) connect();
    });
    keepAwake();
    pickScene();
    renderBar();
    setDot("warn");
    if (!/^[A-Z0-9]{4}$/.test(code)) return veil("bad");
    veil("waiting");
    connect();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else setTimeout(start, 0); // after tv-games.js / tv-casino.js have registered their scenes
})();
