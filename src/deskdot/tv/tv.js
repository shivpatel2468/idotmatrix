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

  function fmt(n, short) {
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
  // Two tiers: "hq" (glows, soft shadows, cross-faded HD panel, full-resolution canvases) and "lite" (no blur, fewer
  // particles, canvases at 3/4 resolution) for weak TV sticks. `?lite=1` / `?hq=1` (or `?quality=lite|hq`) force one;
  // otherwise the page starts in hq and watches its own frame times while something animates: a window of ~2 s that
  // runs slow (median frame > 22 ms, or > 20 % of frames over 34 ms) drops it to lite for the rest of the visit.
  // Pure helpers (tierFromQuery, judgeFrames) are exported on TV for tests/js/tv_core.test.mjs.
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

  const forcedTier = tierFromQuery(location.search);

  /** The panel look: "hd" (the frame upscaled with smooth edges) or "led" (the classic LED matrix). */
  function lookFromQuery(search) {
    try {
      const v = (new URLSearchParams(search || "").get("look") || "").toLowerCase();
      return v === "led" || v === "hd" ? v : null;
    } catch {
      return null;
    }
  }
  const LOOK_KEY = "deskdot.tv.look";
  function initialLook() {
    const q = lookFromQuery(location.search);
    if (q) return q;
    try {
      const v = localStorage.getItem(LOOK_KEY);
      if (v === "led" || v === "hd") return v;
    } catch {
      /* storage blocked */
    }
    return "hd";
  }

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
    version: 2,
    quality: forcedTier || "hq",
    qualityForced: !!forcedTier,
    look: initialLook(),
    every,
    setQuality,
    setLook,
    tierFromQuery,
    judgeFrames,
    lookFromQuery,
    upscale: (data, passes) => upscale(data, passes),
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

  /** Switch the tier (auto = measured) and re-mount the scene so its canvases take the new resolution. */
  function setQuality(q, auto) {
    if (q !== "lite" && q !== "hq") return;
    if (q === TV.quality) return;
    TV.quality = q;
    document.documentElement.dataset.q = q;
    if (auto) console.info("DeskDot TV: this screen runs slow — switching to the lite look (add ?hq=1 to the address to keep HQ)");
    ledCache.clear();
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

  /** The panel look ("hd" | "led"), remembered on this screen. */
  function setLook(v, announce) {
    if (v !== "hd" && v !== "led") return;
    TV.look = v;
    try {
      localStorage.setItem(LOOK_KEY, v);
    } catch {
      /* storage blocked */
    }
    redrawPanels();
    if (announce) toast(v === "hd" ? "Panel look: HD" : "Panel look: classic LED");
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

  // =========================================================================================== LED renderer
  // Per size: static layers (unlit dots + rims, the LED shape mask, specular highlights) are drawn once; a frame then
  // costs a handful of drawImage calls: the 32×32 image scaled up without smoothing and cut into round dots by the
  // mask, two blurred bloom passes added on top ("lighter"), the highlights last.
  const ledCache = new Map(); // `${D}|${round}` -> layers
  const work = { small: null, smallG: null, img: null, glowA: null, glowB: null, filter: null };

  function mk(w, h) {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h || w;
    return c;
  }

  function canFilter() {
    if (work.filter !== null) return work.filter;
    try {
      const g = mk(4).getContext("2d");
      g.filter = "blur(1px)";
      work.filter = g.filter === "blur(1px)";
    } catch {
      work.filter = false;
    }
    return work.filter;
  }

  function ledLayers(D, round) {
    const key = `${D}|${round ? 1 : 0}`;
    let L = ledCache.get(key);
    if (L) return L;
    if (ledCache.size > 8) ledCache.clear();
    const p = D / PANEL;
    const r = p * (round ? 0.43 : 0.5);
    const gap = round ? 0 : Math.max(1, p * 0.08);
    // one dot sprite per layer, stamped 1024 times (only when the size changes)
    const sp = Math.ceil(p);
    const stamp = (draw) => {
      const s = mk(sp);
      draw(s.getContext("2d"), sp / 2);
      const c = mk(D);
      const g = c.getContext("2d");
      for (let y = 0; y < PANEL; y++) for (let x = 0; x < PANEL; x++) g.drawImage(s, Math.round(x * p), Math.round(y * p));
      return c;
    };
    const shape = (g, c, rad) => {
      g.beginPath();
      if (round) g.arc(c, c, rad, 0, Math.PI * 2);
      else g.rect(gap / 2, gap / 2, sp - gap, sp - gap);
    };
    // the backplate and the unlit LEDs: a dark dome with a faint rim
    const under = mk(D);
    {
      const g = under.getContext("2d");
      g.fillStyle = "#040405";
      g.fillRect(0, 0, D, D);
      const dots = stamp((s, c) => {
        const gr = s.createRadialGradient(c - r * 0.3, c - r * 0.35, r * 0.1, c, c, r);
        gr.addColorStop(0, "#1d1d23");
        gr.addColorStop(0.7, "#121216");
        gr.addColorStop(1, "#0b0b0e");
        s.fillStyle = gr;
        shape(s, c, r);
        s.fill();
        if (round && p >= 8) {
          s.lineWidth = Math.max(1, p * 0.04);
          s.strokeStyle = "rgba(255,255,255,0.045)";
          s.beginPath();
          s.arc(c, c, r - s.lineWidth / 2, Math.PI * 1.05, Math.PI * 1.75);
          s.stroke();
        }
      });
      g.drawImage(dots, 0, 0);
    }
    // the lit shape: a dome — full at the centre, a little dimmer towards the edge, soft anti-aliased rim
    const mask = stamp((s, c) => {
      if (round) {
        const gr = s.createRadialGradient(c, c, 0, c, c, r);
        gr.addColorStop(0, "rgba(255,255,255,1)");
        gr.addColorStop(0.55, "rgba(255,255,255,0.97)");
        gr.addColorStop(0.86, "rgba(255,255,255,0.72)");
        gr.addColorStop(1, "rgba(255,255,255,0.0)");
        s.fillStyle = gr;
      } else s.fillStyle = "#fff";
      shape(s, c, r * 1.02);
      s.fill();
    });
    // a hot core: lit LEDs bleach towards white in the middle (drawn "lighter", scaled by the LED's own colour)
    const core = stamp((s, c) => {
      const gr = s.createRadialGradient(c - r * 0.12, c - r * 0.12, 0, c, c, r * 0.62);
      gr.addColorStop(0, "rgba(255,255,255,0.55)");
      gr.addColorStop(1, "rgba(255,255,255,0)");
      s.fillStyle = gr;
      shape(s, c, r);
      s.fill();
    });
    // the epoxy lens catching the room light, on every LED (lit or not)
    const spec = stamp((s, c) => {
      if (!round || p < 6) return;
      const gr = s.createRadialGradient(c - r * 0.38, c - r * 0.42, 0, c - r * 0.38, c - r * 0.42, r * 0.42);
      gr.addColorStop(0, "rgba(255,255,255,0.16)");
      gr.addColorStop(1, "rgba(255,255,255,0)");
      s.fillStyle = gr;
      s.beginPath();
      s.arc(c, c, r, 0, Math.PI * 2);
      s.fill();
    });
    L = { D, p, under, mask, core, spec, lit: mk(D), hot: mk(D) };
    ledCache.set(key, L);
    return L;
  }

  function putFrame(data) {
    if (!work.small) {
      work.small = mk(PANEL);
      work.smallG = work.small.getContext("2d");
      work.img = work.smallG.createImageData(PANEL, PANEL);
    }
    const d = work.img.data;
    for (let i = 0, j = 0; i < FRAME_BYTES; i += 3, j += 4) {
      d[j] = data[i];
      d[j + 1] = data[i + 1];
      d[j + 2] = data[i + 2];
      d[j + 3] = 255;
    }
    work.smallG.putImageData(work.img, 0, 0);
    return work.small;
  }

  function bloom(src) {
    // two soft copies of the frame at 4 px per LED: a tight halo and a wide one
    const G = PANEL * 4;
    if (!work.glowA) {
      work.glowA = mk(G);
      work.glowB = mk(G);
    }
    const a = work.glowA.getContext("2d");
    const b = work.glowB.getContext("2d");
    a.clearRect(0, 0, G, G);
    b.clearRect(0, 0, G, G);
    a.imageSmoothingEnabled = true;
    b.imageSmoothingEnabled = true;
    if (canFilter()) {
      a.filter = "blur(3px)";
      a.drawImage(src, 0, 0, G, G);
      a.filter = "none";
      b.filter = "blur(10px)";
      b.drawImage(src, 0, 0, G, G);
      b.filter = "none";
    } else {
      // no canvas filters (older Safari / TV browsers): blur by scaling down and back up
      a.drawImage(src, 0, 0, G, G);
      b.drawImage(src, 0, 0, 8, 8);
      b.drawImage(work.glowB, 0, 0, 8, 8, 0, 0, G, G);
    }
    return [work.glowA, work.glowB];
  }

  const drawn = new Set(); // canvases drawn with drawPanel (redrawn on a resize)

  // ------------------------------------------------------------------------------------------- the HD look
  // The frame upscaled ×8 with Scale2x / EPX (three passes: 32 → 64 → 128 → 256) — a pixel-art upscaler that only
  // ever copies a pixel's own colour or a neighbour's, so shapes get smooth diagonals and round corners while every
  // colour and every position stays exactly the panel's — then drawn to the canvas with bilinear smoothing (soft,
  // anti-aliased edges). A few hundred thousand integer compares per frame, no WebGL needed (a TV stick's WebGL is
  // the least reliable part of its browser). In hq a new frame cross-fades in over ~60 ms and a cheap bloom (the
  // frame scaled down and back up, no canvas filter) sits under it.
  const HD = {}; // per pass count: the shared upscaled frame (hdImage)

  /** One Scale2x / EPX pass: src (w×w, packed 32-bit pixels) → dst (2w×2w). */
  function scale2x(src, w, dst) {
    const W2 = w * 2;
    for (let y = 0; y < w; y++) {
      const row = y * w;
      const up = y > 0 ? row - w : row;
      const dn = y < w - 1 ? row + w : row;
      const o = y * 2 * W2;
      for (let x = 0; x < w; x++) {
        const P = src[row + x];
        const A = src[up + x];
        const D = src[dn + x];
        const C = x > 0 ? src[row + x - 1] : P;
        const B = x < w - 1 ? src[row + x + 1] : P;
        const i = o + x * 2;
        dst[i] = C === A && C !== D && A !== B ? A : P;
        dst[i + 1] = A === B && A !== C && B !== D ? B : P;
        dst[i + W2] = D === C && D !== B && C !== A ? C : P;
        dst[i + W2 + 1] = B === D && B !== A && D !== C ? D : P;
      }
    }
  }

  /** The frame (3072 RGB bytes) upscaled 2^passes times into Uint32 pixels (little-endian ABGR). Pure. */
  function upscale(data, passes, bufs) {
    const n = PANEL << passes;
    bufs = bufs || [];
    let src = bufs[0] && bufs[0].length === PANEL * PANEL ? bufs[0] : (bufs[0] = new Uint32Array(PANEL * PANEL));
    for (let i = 0, j = 0; i < PANEL * PANEL; i++, j += 3) src[i] = 0xff000000 | (data[j + 2] << 16) | (data[j + 1] << 8) | data[j];
    let w = PANEL;
    for (let p = 1; p <= passes; p++) {
      const len = (w * 2) * (w * 2);
      const dst = bufs[p] && bufs[p].length === len ? bufs[p] : (bufs[p] = new Uint32Array(len));
      scale2x(src, w, dst);
      src = dst;
      w *= 2;
    }
    return { px: src, size: n };
  }

  /**
   * The upscaled frame as a canvas, shared by every panel on the page and rebuilt only for a new frame: 2 passes
   * (128 px) for small panels and the lite tier, 3 (256 px) for the big ones. Its 16 px bloom source comes along.
   */
  function hdImage(data, passes) {
    const slot = HD[passes] || (HD[passes] = { canvas: null, img: null, bufs: [], last: null, halo: null });
    if (slot.last === data && slot.canvas) return slot;
    const n = PANEL << passes;
    if (!slot.canvas) {
      slot.canvas = mk(n);
      slot.img = slot.canvas.getContext("2d").createImageData(n, n);
      slot.halo = mk(16);
    }
    const out = upscale(data, passes, slot.bufs);
    new Uint32Array(slot.img.data.buffer).set(out.px);
    slot.canvas.getContext("2d").putImageData(slot.img, 0, 0);
    const hg = slot.halo.getContext("2d");
    hg.imageSmoothingEnabled = true;
    hg.clearRect(0, 0, 16, 16);
    hg.drawImage(slot.canvas, 0, 0, 16, 16);
    slot.last = data;
    return slot;
  }

  /**
   * Paint the HD look into `canvas` (backing store already sized D×D). A new frame on a big panel in hq cross-fades
   * in: for ~60 ms the new picture is laid over the old one at a growing opacity (no copy of the old one needed),
   * then drawn once more in full with its bloom.
   */
  function paintHD(canvas, D, data, glow) {
    const lite = TV.quality === "lite";
    const passes = lite || D <= 420 ? 2 : 3;
    let st = canvas._hd;
    if (!st) st = canvas._hd = { src: null, at: 0, dur: 0, job: null, last: 0, D: 0 };
    if (data && st.src !== data) {
      const t = now();
      const gap = st.src ? t - st.at : 1;
      // only big panels fade (the small casino inset gains nothing from it); never in lite or for the first frame
      st.dur = lite || !st.src || D < 600 || st.D !== D ? 0 : Math.min(0.07, gap * 0.6);
      st.at = t;
      st.src = data;
      st.passes = passes;
      st.last = 0;
      if (st.dur > 0) {
        if (!st.job) {
          st.job = every(() => {
            const done = stepHD(canvas, st, glow);
            if (done) st.job = null;
            return !done;
          });
        }
        st.D = D;
        return;
      }
    } else if (st.job || (st.D === D && st.glow === glow && st.drawn === st.src && st.passes === passes)) return; // nothing new
    st.D = D;
    st.glow = glow;
    st.passes = passes;
    fullHD(canvas, st, glow);
  }

  /** One cross-fade step: the new frame over what's on the canvas, at the opacity that keeps the blend linear. */
  function stepHD(canvas, st, glow) {
    if (!canvas.isConnected || canvas._hd !== st) return true; // gone, or switched to the LED look meanwhile
    const k = st.dur > 0 ? Math.min(1, (now() - st.at) / st.dur) : 1;
    if (k >= 1) {
      fullHD(canvas, st, glow);
      return true;
    }
    // after drawing at a, the old picture weighs (1 − a)·(its weight): pick a so it weighs exactly 1 − k now
    const a = st.last >= 1 ? 1 : 1 - (1 - k) / (1 - st.last);
    st.last = k;
    const g = canvas.getContext("2d");
    g.imageSmoothingEnabled = true;
    g.globalCompositeOperation = "source-over";
    g.globalAlpha = Math.max(0, Math.min(1, a));
    g.drawImage(hdImage(st.src, st.passes).canvas, 0, 0, st.D, st.D);
    g.globalAlpha = 1;
    return false;
  }

  function fullHD(canvas, st, glow) {
    const g = canvas.getContext("2d");
    const D = st.D;
    g.globalCompositeOperation = "source-over";
    g.globalAlpha = 1;
    g.fillStyle = "#050507";
    g.fillRect(0, 0, D, D);
    st.drawn = st.src;
    if (!st.src) return;
    const slot = hdImage(st.src, st.passes);
    g.imageSmoothingEnabled = true;
    if ("imageSmoothingQuality" in g) g.imageSmoothingQuality = "low"; // bilinear: the upscaler made the edges
    g.drawImage(slot.canvas, 0, 0, D, D);
    if (glow > 0 && TV.quality !== "lite") {
      // bloom: the frame squeezed to 16 px and stretched back — a wide soft halo, no blur filter
      g.globalCompositeOperation = "lighter";
      g.globalAlpha = 0.22 * glow;
      g.drawImage(slot.halo, 0, 0, D, D);
      g.globalAlpha = 1;
      g.globalCompositeOperation = "source-over";
    }
  }

  /**
   * Paints a 32×32 RGB frame big: the HD look (default) or the classic LED matrix (opts.look / TV.look = "led").
   * opts: pitch (stage px per LED; sets the CSS size), glow 0..1 (default 0.6), round (LED dots, default true),
   * data (another 3072-byte frame), look ("hd" | "led").
   */
  function drawPanel(canvas, opts) {
    if (!canvas) return;
    opts = opts || {};
    const data = opts.data || ctx.panel;
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
    const lite = TV.quality === "lite";
    const glow = opts.glow == null ? 0.6 : Math.max(0, Math.min(1, Number(opts.glow) || 0));
    const look = opts.look || TV.look;
    // backing store: the canvas's real device pixels, capped (3/4 of them in lite: the GPU scales it up)
    const dev = css * TV.pixelRatio * (lite ? 0.75 : 1);
    if (look !== "led") {
      const D = Math.max(PANEL, Math.min(lite ? 1024 : 1600, Math.round(dev)));
      if (canvas.width !== D || canvas.height !== D) {
        canvas.width = D;
        canvas.height = D;
        if (canvas._hd) canvas._hd.D = 0; // a resized canvas is blank: paint it in full
      }
      paintHD(canvas, D, data && data.length >= FRAME_BYTES ? data : null, glow);
      return;
    }
    if (canvas._hd) canvas._hd = null;
    const D = Math.max(PANEL, Math.min(1600, Math.round(dev / PANEL) * PANEL)); // a whole number of px per LED
    if (canvas.width !== D || canvas.height !== D) {
      canvas.width = D;
      canvas.height = D;
    }
    const round = opts.round !== false;
    const L = ledLayers(D, round);
    const g = canvas.getContext("2d");
    g.globalCompositeOperation = "source-over";
    g.globalAlpha = 1;
    g.drawImage(L.under, 0, 0);
    if (!data || data.length < FRAME_BYTES) {
      g.drawImage(L.spec, 0, 0);
      return;
    }
    const small = putFrame(data);
    // lit dots: nearest-neighbour upscale, cut by the dome mask
    const lg = L.lit.getContext("2d");
    lg.globalCompositeOperation = "source-over";
    lg.clearRect(0, 0, D, D);
    lg.imageSmoothingEnabled = false;
    lg.drawImage(small, 0, 0, D, D);
    lg.globalCompositeOperation = "destination-in";
    lg.drawImage(L.mask, 0, 0);
    g.globalCompositeOperation = "lighter";
    g.drawImage(L.lit, 0, 0);
    if (!lite) {
      // the hot core: the same colours, through the core mask (hq only)
      const hg = L.hot.getContext("2d");
      hg.globalCompositeOperation = "source-over";
      hg.clearRect(0, 0, D, D);
      hg.imageSmoothingEnabled = false;
      hg.drawImage(small, 0, 0, D, D);
      hg.globalCompositeOperation = "destination-in";
      hg.drawImage(L.core, 0, 0);
      g.drawImage(L.hot, 0, 0);
    }
    if (glow > 0 && !lite) {
      const [tight, wide] = bloom(small);
      g.imageSmoothingEnabled = true;
      g.globalAlpha = 0.55 * glow;
      g.drawImage(tight, 0, 0, D, D);
      g.globalAlpha = 0.45 * glow;
      g.drawImage(wide, 0, 0, D, D);
      g.globalAlpha = 1;
    }
    g.globalCompositeOperation = "source-over";
    g.drawImage(L.spec, 0, 0);
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
      // (lite: never — a per-frame repaint of it was a main cause of stutter on TV sticks)
      if (TV.quality === "lite") return;
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
    // the panel look: L on a keyboard, the remote's select / play-pause / menu button on a TV stick
    window.addEventListener("keydown", (e) => {
      const k = e.key;
      if (k === "l" || k === "L" || k === "Enter" || k === "MediaPlayPause" || k === "ContextMenu" || e.keyCode === 179 || e.keyCode === 82) {
        setLook(TV.look === "hd" ? "led" : "hd", true);
      }
    });
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
