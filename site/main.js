/* DotDeck — idotmatrix.com. Plain JS, no dependencies.
 * 1. the neon LED logo (canvas)   2. page chrome (menu, reveal, LED hovers, tabs, copy)   3. the Apps explorer */
(() => {
  "use strict";

  const REPO = "https://github.com/shivpatel2468/idotmatrix";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  /* ===================================================================== 1. neon logo
   * The "idotmatrix" wordmark as LEDs in three neon tubes ("i" pink, "dot" amber, "matrix" cyan). The dots build in
   * (the i drops, "dot" types in, "matrix" rains down), then each tube is struck like real neon: a stutter of
   * flashes, then a steady hum, with one loose letter that blinks now and then. Same idea as web/src/lib/logo.ts. */
  const GLYPHS = {
    i: ["#", ".", "#", "#", "#", "#", "#"],
    d: ["...#", "...#", ".###", "#..#", "#..#", "#..#", ".###"],
    o: ["....", "....", ".##.", "#..#", "#..#", "#..#", ".##."],
    t: ["...", ".#.", "###", ".#.", ".#.", ".#.", "..#"],
    m: [".....", ".....", "####.", "#.#.#", "#.#.#", "#.#.#", "#.#.#"],
    a: ["....", "....", ".###", "...#", ".###", "#..#", ".###"],
    r: ["....", "....", "#.##", "##..", "#...", "#...", "#..."],
    x: [".....", ".....", "#...#", ".#.#.", "..#..", ".#.#.", "#...#"],
  };
  const ROWS = 7;
  const NEON = ["#ff2d78", "#ffb21a", "#1fe0ff"];
  const STRIKE = [
    [[0.05, 1], [0.07, 0], [0.03, 0.7], [0.16, 0], [0.04, 1], [0.05, 0.15], [0.09, 0.55], [0.05, 0], [0.06, 0.9], [0.04, 0.4]],
    [[0.04, 0.6], [0.12, 0], [0.05, 1], [0.04, 0], [0.03, 1], [0.22, 0.05], [0.05, 0.8], [0.03, 0.2], [0.07, 1], [0.05, 0.5]],
    [[0.03, 0.8], [0.05, 0], [0.04, 0.5], [0.09, 0], [0.05, 1], [0.03, 0], [0.12, 0.3], [0.04, 1], [0.08, 0.1], [0.06, 0.85]],
  ];
  const DELAY = [0, 0.28, 0.12];
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
  function glowSprite(color, size) {
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const g = c.getContext("2d");
    const r = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    r.addColorStop(0, color);
    r.addColorStop(0.25, color + "aa");
    r.addColorStop(0.6, color + "22");
    r.addColorStop(1, color + "00");
    g.fillStyle = r;
    g.fillRect(0, 0, size, size);
    return c;
  }
  function layoutLogo() {
    const dots = [], parts = [];
    let x = 0, letter = 0;
    ["i", "dot", "matrix"].forEach((w, part) => {
      if (part) x += 1;
      const from = x;
      [...w].forEach((ch, i) => {
        const g = GLYPHS[ch];
        if (i) x += 1;
        g.forEach((row, y) => [...row].forEach((c, dx) => {
          if (c === "#") dots.push({ x: x + dx, y, part, col: 0, seed: Math.random(), letter });
        }));
        x += g[0].length;
        letter++;
      });
      parts.push({ from, to: x });
    });
    for (const d of dots) {
      const p = parts[d.part];
      d.col = (d.x - p.from) / Math.max(1, p.to - p.from - 1);
    }
    return { dots, cols: x };
  }
  const LOGO = layoutLogo();
  const GLOWS = NEON.map((c) => glowSprite(c, 64));

  /** Draw the logo at (ox, oy) with dot pitch p. lt = seconds since start. */
  function drawLogo(ctx, lt, ox, oy, p, { build = 1.6, grid = false, flare = 0, still = false } = {}) {
    if (still) lt = build + 3;
    const igniteAt = build + 0.15;
    const r = p * 0.36;
    if (grid) {
      ctx.fillStyle = "rgba(255,255,255,0.05)";
      for (let y = -1; y <= ROWS; y++)
        for (let x = -1; x <= LOGO.cols; x++) {
          ctx.beginPath();
          ctx.arc(ox + (x + 0.5) * p, oy + (y + 0.5) * p, r * 0.62, 0, Math.PI * 2);
          ctx.fill();
        }
    }
    for (let part = 0; part < 3; part++) {
      let level = strike(part, lt - igniteAt - DELAY[part]);
      const lit = lt > igniteAt + DELAY[part] + strikeLen(part);
      if (lit) level = still ? 1 : 0.93 + 0.07 * Math.sin(lt * 47 + part * 3) * Math.sin(lt * 13.3);
      level = Math.min(1.6, level + flare * 0.8);
      const color = NEON[part], glow = GLOWS[part];
      for (const d of LOGO.dots) {
        if (d.part !== part) continue;
        let x = d.x, y = d.y, k, pop = 0;
        if (part === 0) {
          k = Math.min(1, Math.max(0, (lt - (6 - d.y) * 0.05) / 0.5));
          y = d.y - (1 - bounce(k)) * 9;
        } else if (part === 1) {
          k = Math.min(1, Math.max(0, (lt - (d.col * build * 0.75 + d.y * 0.012)) / 0.22));
          pop = k > 0 && k < 1 ? Math.sin(k * Math.PI) : 0;
          x = d.x - (1 - easeOut(k)) * 1.2;
        } else {
          k = Math.min(1, Math.max(0, (lt - ((1 - d.col) * build * 0.55 + d.seed * build * 0.3)) / 0.55));
          y = d.y - (1 - bounce(k)) * (6 + d.y);
        }
        if (k <= 0) continue;
        let lv = level;
        if (lit && !still && d.letter === 7) {
          // the loose tube: the "r" of matrix blinks out for a beat now and then
          const g = (lt * 0.37) % 1;
          if (g > 0.62 && g < 0.645) lv *= 0.1;
          else if (g > 0.66 && g < 0.672) lv *= 0.3;
        }
        const cx = ox + (x + 0.5) * p, cy = oy + (y + 0.5) * p;
        ctx.globalAlpha = 0.22 * Math.min(1, k * 2);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(cx, cy, r * (1 + pop * 0.6), 0, Math.PI * 2);
        ctx.fill();
        const light = Math.max(lv, pop * 0.9);
        if (light > 0.02) {
          ctx.globalCompositeOperation = "lighter";
          ctx.globalAlpha = Math.min(1, light * 0.5);
          const gs = p * (3.4 + flare * 2.5);
          ctx.drawImage(glow, cx - gs / 2, cy - gs / 2, gs, gs);
          ctx.globalAlpha = Math.min(1, light);
          ctx.beginPath();
          ctx.arc(cx, cy, r * (1 + pop * 0.5), 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = Math.min(1, light * 0.8);
          ctx.fillStyle = "#fff";
          ctx.beginPath();
          ctx.arc(cx, cy, r * 0.45, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalCompositeOperation = "source-over";
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  /** Mount a logo on a canvas: sizes to its CSS box, animates only while visible, then idles on the hum. */
  function mountLogo(canvas, { grid = false, pad = 1, interactive = false, startDelay = 0 } = {}) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const cols = LOGO.cols + pad * 2, rows = ROWS + pad * 2;
    let w = 0, h = 0, p = 0, t0 = 0, raf = 0, visible = false, started = false, flare = 0;
    const resize = () => {
      const dpr = Math.min(2, devicePixelRatio || 1);
      const cw = canvas.clientWidth || canvas.width;
      p = cw / cols;
      w = cw; h = p * rows;
      canvas.style.height = h + "px";
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (reduced || !started) frame(performance.now());
    };
    const frame = (now) => {
      ctx.clearRect(0, 0, w, h);
      const lt = started ? (now - t0) / 1000 : -1;
      flare *= 0.92;
      drawLogo(ctx, lt, pad * p, pad * p, p, { grid, flare, still: reduced });
    };
    const loop = (now) => {
      frame(now);
      raf = visible && !document.hidden ? requestAnimationFrame(loop) : 0;
    };
    const kick = () => { if (!raf && !reduced && visible && !document.hidden) raf = requestAnimationFrame(loop); };
    new ResizeObserver(resize).observe(canvas);
    new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (visible && !started) {
        setTimeout(() => { started = true; t0 = performance.now(); kick(); }, startDelay);
      } else kick();
    }).observe(canvas);
    document.addEventListener("visibilitychange", kick);
    if (interactive && !reduced) canvas.addEventListener("pointerenter", () => { flare = 0.6; });
    resize();
  }

  mountLogo($("#logo"), { grid: true, interactive: true, startDelay: 150 });
  mountLogo($("#mini-logo"), { pad: 0.5, startDelay: 600 });
  mountLogo($("#footer-logo"), { pad: 0.5 });

  /* ===================================================================== 2. page chrome */
  // header border once scrolled; current section in the nav
  const bar = $("#bar");
  const onScroll = () => bar.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  const navLinks = $$("#nav a");
  const sectionObs = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      navLinks.forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === "#" + e.target.id ? "true" : "false"));
    }
  }, { rootMargin: "-45% 0px -50% 0px" });
  navLinks.forEach((a) => { const s = $(a.getAttribute("href")); if (s) sectionObs.observe(s); });

  // mobile menu
  const menuBtn = $("#menu-btn"), nav = $("#nav");
  menuBtn.addEventListener("click", () => {
    const open = menuBtn.getAttribute("aria-expanded") !== "true";
    menuBtn.setAttribute("aria-expanded", String(open));
    nav.classList.toggle("open", open);
  });
  nav.addEventListener("click", (e) => {
    if (e.target.closest("a")) { menuBtn.setAttribute("aria-expanded", "false"); nav.classList.remove("open"); }
  });

  // scroll reveal (stagger comes from --i in the markup)
  const revealObs = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); revealObs.unobserve(e.target); }
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  const observeReveal = (root = document) => $$(".reveal:not(.in)", root).forEach((el) => (reduced ? el.classList.add("in") : revealObs.observe(el)));
  observeReveal();

  // LEDs under the cursor on cards
  document.addEventListener("pointermove", (e) => {
    const card = e.target.closest && e.target.closest(".card");
    if (!card) return;
    const r = card.getBoundingClientRect();
    card.style.setProperty("--mx", e.clientX - r.left + "px");
    card.style.setProperty("--my", e.clientY - r.top + "px");
  }, { passive: true });

  // 5×5 LED icons from data-led="#.#.#|..."
  $$(".ledico[data-led]").forEach((el) => {
    let n = 0;
    el.innerHTML = el.dataset.led.split("|").flatMap((row) => [...row].map((c) => `<i class="${c === "#" ? "on" : ""}" style="--d:${n++}"></i>`)).join("");
    el.setAttribute("aria-hidden", "true");
  });

  // the panel tilts toward the cursor
  const device = $("#device .device-frame");
  if (device && !reduced && matchMedia("(pointer: fine)").matches) {
    const hero = $(".hero");
    hero.addEventListener("pointermove", (e) => {
      const r = device.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width / 2)) / innerWidth;
      const dy = (e.clientY - (r.top + r.height / 2)) / innerHeight;
      device.style.setProperty("--ry", (dx * 16 - 4).toFixed(2) + "deg");
      device.style.setProperty("--rx", (-dy * 12 + 2).toFixed(2) + "deg");
    }, { passive: true });
    hero.addEventListener("pointerleave", () => { device.style.removeProperty("--ry"); device.style.removeProperty("--rx"); });
  }

  // tabs (WAI-ARIA pattern: arrows move, Home/End jump)
  $$("[data-tabs]").forEach((root) => {
    const tabs = $$('[role="tab"]', root);
    const select = (tab, focus) => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        $("#" + t.getAttribute("aria-controls")).hidden = !on;
      });
      if (focus) tab.focus();
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(t));
      t.addEventListener("keydown", (e) => {
        const j = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (j === undefined) return;
        e.preventDefault();
        select(tabs[(j + tabs.length) % tabs.length], true);
      });
    });
  });

  // OS switch for the uv installer (guess from the browser)
  const osBtns = $$("[data-os]");
  const setOS = (os) => {
    osBtns.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.os === os)));
    $$("[data-os-panel]").forEach((p) => (p.hidden = p.dataset.osPanel !== os));
  };
  osBtns.forEach((b) => b.addEventListener("click", () => setOS(b.dataset.os)));
  setOS(/Win/i.test(navigator.userAgentData?.platform || navigator.platform || navigator.userAgent) ? "win" : "unix");

  // copy buttons: every code block gets one; [data-copy-target] buttons copy an element by id
  const toast = $("#toast");
  let toastTimer = 0;
  const say = (msg) => {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  };
  const textOf = (pre) => {
    const c = pre.cloneNode(true);
    $$(".p", c).forEach((p) => p.remove());
    return c.textContent.replace(/\s+$/, "");
  };
  async function copy(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = Object.assign(document.createElement("textarea"), { value: text });
      ta.style.cssText = "position:fixed;opacity:0";
      document.body.append(ta);
      ta.select();
      try { document.execCommand("copy"); } catch { /* nothing else to try */ }
      ta.remove();
    }
    say("Copied to clipboard");
    if (btn) {
      btn.classList.add("done");
      const use = $("use", btn);
      use?.setAttribute("href", "#i-check");
      setTimeout(() => { btn.classList.remove("done"); use?.setAttribute("href", "#i-copy"); }, 1600);
    }
  }
  const addCopyButtons = (root = document) => $$(".code", root).forEach((box) => {
    if ($(".copy", box)) return;
    const pre = $("pre", box);
    const b = document.createElement("button");
    b.type = "button";
    b.className = "copy";
    b.setAttribute("aria-label", "Copy to clipboard");
    b.innerHTML = '<svg aria-hidden="true"><use href="#i-copy"/></svg>';
    b.addEventListener("click", () => copy(textOf(pre), b));
    box.append(b);
  });
  addCopyButtons();
  $$("[data-copy-target]").forEach((b) => b.addEventListener("click", () => copy(textOf($("#" + b.dataset.copyTarget)), b)));

  // GitHub stars (best effort; cached for the session)
  (async () => {
    const slots = $$("[data-stars]");
    let n = null;
    try { n = sessionStorage.getItem("dd-stars"); } catch { /* storage blocked */ }
    if (n === null) {
      try {
        const r = await fetch("https://api.github.com/repos/shivpatel2468/idotmatrix", { headers: { Accept: "application/vnd.github+json" } });
        if (r.ok) n = String((await r.json()).stargazers_count ?? "");
        try { sessionStorage.setItem("dd-stars", n ?? ""); } catch { /* storage blocked */ }
      } catch { /* offline or rate-limited: buttons just say GitHub */ }
    }
    if (n && Number(n) > 0) {
      const v = Number(n);
      const label = v >= 1000 ? (v / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(v);
      slots.forEach((s) => { s.textContent = "★ " + label; s.setAttribute("aria-label", `${v} stars`); });
    }
  })();

  /* ===================================================================== 3. apps explorer */
  const CAT_COLOR = {
    time: "#ffb21a", data: "#1fe0ff", media: "#ff2d78", creative: "#b98cff", pets: "#4dff9a",
    games: "#ff4818", ambient: "#3ee6c1", productivity: "#ffd84a", device: "#9aa3ff",
  };
  const KIND = {
    clip: { label: "Baked loop", c: "#4dff9a", text: "Rendered once into a GIF that the panel loops with its own firmware: perfectly smooth, no Bluetooth traffic." },
    stream: { label: "Live", c: "#1fe0ff", text: "Rendered by the engine and streamed over Bluetooth as its data changes (about 5–9 frames a second)." },
    native: { label: "Firmware", c: "#ffb21a", text: "Uses one of the panel's own built-in modes, so it keeps running even with the computer off." },
  };
  const CONTROL = { dpad: "D-pad", joystick: "Analog stick", swipe: "Swipe", tap: "Tap zones", gamepad: "Gamepad", keyboard: "Keyboard", tilt: "Tilt" };
  const TEAMS = { solo: "Solo", coop: "Co-op", ffa: "Free-for-all", versus: "Teams" };

  // 3×5 pixel font for the generated thumbnails (rows top to bottom, "#" = lit)
  const F3 = {
    A: ".#.|#.#|###|#.#|#.#", B: "##.|#.#|##.|#.#|##.", C: ".##|#..|#..|#..|.##", D: "##.|#.#|#.#|#.#|##.",
    E: "###|#..|##.|#..|###", F: "###|#..|##.|#..|#..", G: ".##|#..|#.#|#.#|.##", H: "#.#|#.#|###|#.#|#.#",
    I: "###|.#.|.#.|.#.|###", J: "..#|..#|..#|#.#|.#.", K: "#.#|#.#|##.|#.#|#.#", L: "#..|#..|#..|#..|###",
    M: "#.#|###|###|#.#|#.#", N: "##.|#.#|#.#|#.#|#.#", O: ".#.|#.#|#.#|#.#|.#.", P: "##.|#.#|##.|#..|#..",
    Q: ".#.|#.#|#.#|##.|.##", R: "##.|#.#|##.|#.#|#.#", S: ".##|#..|.#.|..#|##.", T: "###|.#.|.#.|.#.|.#.",
    U: "#.#|#.#|#.#|#.#|###", V: "#.#|#.#|#.#|#.#|.#.", W: "#.#|#.#|###|###|#.#", X: "#.#|#.#|.#.|#.#|#.#",
    Y: "#.#|#.#|.#.|.#.|.#.", Z: "###|..#|.#.|#..|###", 0: "###|#.#|#.#|#.#|###", 1: ".#.|##.|.#.|.#.|###",
    2: "##.|..#|.#.|#..|###", 3: "##.|..#|.#.|..#|##.", 4: "#.#|#.#|###|..#|..#", 5: "###|#..|##.|..#|##.",
    6: ".##|#..|###|#.#|###", 7: "###|..#|.#.|.#.|.#.", 8: "###|#.#|###|#.#|###", 9: "###|#.#|###|..#|##.",
  };
  const glyph = (ch) => (F3[ch] ? F3[ch].split("|") : null);
  const hash = (s) => { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; };
  const initials = (name) => {
    const words = name.toUpperCase().replace(/[^A-Z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
    if (!words.length) return "?";
    if (words.length === 1) return words[0].slice(0, 2);
    return words.slice(0, 3).map((w) => w[0]).join("").slice(0, words.length > 2 && words[2].length > 2 ? 3 : 2);
  };

  /** A 32×32 "LED panel" thumbnail for apps without a recorded GIF: initials plus a seeded level meter. */
  function thumbCanvas(app) {
    const S = 8, c = document.createElement("canvas");
    c.width = c.height = 32 * S;
    c.setAttribute("role", "img");
    c.setAttribute("aria-label", `${app.name} icon`);
    const g = c.getContext("2d");
    const col = CAT_COLOR[app.category] || "#ffffff";
    const px = new Map();
    const set = (x, y, a = 1) => { if (x >= 0 && x < 32 && y >= 0 && y < 32) px.set(y * 32 + x, a); };
    const text = initials(app.name);
    const sc = text.length > 2 ? 2 : 3;
    const tw = text.length * 3 * sc + (text.length - 1) * sc;
    let x0 = Math.round((32 - tw) / 2);
    const y0 = text.length > 2 ? 8 : 5;
    for (const ch of text) {
      const gl = glyph(ch);
      if (gl) gl.forEach((row, y) => [...row].forEach((v, x) => {
        if (v === "#") for (let a = 0; a < sc; a++) for (let b = 0; b < sc; b++) set(x0 + x * sc + a, y0 + y * sc + b);
      }));
      x0 += 4 * sc;
    }
    let h = hash(app.id);
    for (let x = 3; x < 29; x++) {
      h = Math.imul(h ^ (h >>> 15), 2246822507) >>> 0;
      const bar = 1 + (h % 5);
      for (let k = 0; k < bar; k++) set(x, 28 - k, 0.35 + 0.15 * (bar - k) / bar);
    }
    g.fillStyle = "#000";
    g.fillRect(0, 0, c.width, c.height);
    for (let y = 0; y < 32; y++)
      for (let x = 0; x < 32; x++) {
        const a = px.get(y * 32 + x);
        g.beginPath();
        g.arc(x * S + S / 2, y * S + S / 2, S * 0.38, 0, Math.PI * 2);
        if (a) { g.globalAlpha = a; g.fillStyle = col; g.shadowColor = col; g.shadowBlur = 6; }
        else { g.globalAlpha = 1; g.fillStyle = "#121216"; g.shadowBlur = 0; }
        g.fill();
      }
    g.globalAlpha = 1;
    return c;
  }
  const thumb = (app, eager) => {
    if (app.gif) {
      const img = new Image(276, 276);
      img.src = app.gif;
      img.alt = `${app.name} running on the panel`;
      if (!eager) img.loading = "lazy";
      img.decoding = "async";
      return img;
    }
    return thumbCanvas(app);
  };

  const grid = $("#app-grid"), search = $("#app-search"), chipsEl = $("#cat-chips"), countEl = $("#result-count");
  const dialog = $("#app-dialog");
  let DATA = null;
  const state = { q: "", cat: "all", flags: new Set() };
  const FLAGS = {
    multiplayer: { label: "Multiplayer", c: "#ff4818", test: (a) => (a.game?.max_players || 1) > 1 },
    clip: { label: "Baked loops", c: "#4dff9a", test: (a) => a.kinds.includes("clip") },
    gif: { label: "Has preview", c: "#ffffff", test: (a) => !!a.gif },
  };

  function haystack(a) {
    const parts = [a.name, a.id, a.description, a.category, a.kind, ...a.kinds.map((k) => KIND[k]?.label || k)];
    for (const s of a.settings) {
      parts.push(s.title, s.key, s.description || "", s.group || "");
      for (const o of s.options || []) parts.push(o.label);
    }
    if (a.game) {
      parts.push(`${a.game.max_players} players`, "game");
      for (const m of a.game.modes) parts.push(m.name, TEAMS[m.teams] || m.teams);
      for (const m of a.game.maps) parts.push(m.label);
      for (const c of a.game.controls) parts.push(CONTROL[c] || c);
    }
    return parts.join(" \u0001 ").toLowerCase();
  }

  function renderChips() {
    const chip = (id, label, count, c, pressed, kind) =>
      `<button type="button" class="chip" data-${kind}="${esc(id)}" aria-pressed="${pressed}" style="--c:${c}"><i></i>${esc(label)}${count != null ? ` <small>${count}</small>` : ""}</button>`;
    chipsEl.innerHTML =
      chip("all", "All", DATA.count, "#f3f1ec", state.cat === "all", "cat") +
      DATA.categories.map((c) => chip(c.id, c.label, c.count, CAT_COLOR[c.id], state.cat === c.id, "cat")).join("") +
      '<span class="sep" aria-hidden="true"></span>' +
      Object.entries(FLAGS).map(([id, f]) => chip(id, f.label, null, f.c, state.flags.has(id), "flag")).join("");
  }

  function card(a) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "card app-card";
    b.style.setProperty("--glow", CAT_COLOR[a.category]);
    b.dataset.app = a.id;
    b.setAttribute("aria-haspopup", "dialog");
    const players = (a.game?.max_players || 1) > 1 ? `<span>${a.game.max_players} players</span>` : "";
    const k = KIND[a.kind];
    b.innerHTML = `
      <div class="thumb"><span class="badge" style="--c:${k.c}"><i></i>${k.label}</span></div>
      <div class="body">
        <div class="badges"><span class="tag" style="color:${CAT_COLOR[a.category]}">${esc(DATA.catLabel[a.category])}</span></div>
        <h3>${esc(a.name)}</h3>
        <p>${esc(a.description)}</p>
        <div class="foot"><span>${a.settings.length} settings</span>${players}${a.game?.maps.length ? `<span>${a.game.maps.length} maps</span>` : ""}</div>
      </div>`;
    $(".thumb", b).prepend(thumb(a));
    return b;
  }

  function applyFilters() {
    const terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    const list = DATA.apps.filter((a) =>
      (state.cat === "all" || a.category === state.cat) &&
      [...state.flags].every((f) => FLAGS[f].test(a)) &&
      terms.every((t) => a._hay.includes(t)));
    grid.replaceChildren(...list.map((a, i) => { const c = card(a); c.style.setProperty("--i", String(Math.min(i, 12))); return c; }));
    if (!list.length) grid.innerHTML = `<p class="empty">No app matches “${esc(state.q)}”. Try fewer words, or clear the filters.</p>`;
    countEl.textContent = list.length === DATA.count ? `Showing all ${DATA.count} apps` : `Showing ${list.length} of ${DATA.count} apps`;
  }

  // ------------------------------------------------------------ the detail dialog
  const fmt = (s, v) => {
    if (v === undefined) return '<span class="range">—</span>';
    if (v === null) return '<span class="range">none</span>';
    if (typeof v === "boolean") return v ? "On" : "Off";
    if (s.options) {
      const o = s.options.find((o) => o.value === v);
      return esc(o ? o.label : v);
    }
    if (s.type === "color" && typeof v === "string") return `<span class="swatch" style="background:${esc(v)}"></span>${esc(v)}`;
    if (typeof v === "string") return v === "" ? '<span class="range">empty</span>' : esc(v.length > 60 ? v.slice(0, 57) + "…" : v);
    if (typeof v === "number") return esc(String(v));
    const j = JSON.stringify(v);
    return `<code>${esc(j.length > 60 ? j.slice(0, 57) + "…" : j)}</code>`;
  };
  const optionsCell = (s) => {
    if (s.options) {
      return `<div class="opts">${s.options.map((o) => `<span class="pill${o.value === s.default ? " def" : ""}">${esc(o.label)}</span>`).join("")}</div>`;
    }
    if (s.min != null || s.max != null) {
      const lo = s.min ?? "", hi = s.max ?? "";
      let bar = "";
      if (typeof s.min === "number" && typeof s.max === "number" && typeof s.default === "number" && s.max > s.min) {
        const pct = Math.max(0, Math.min(100, ((s.default - s.min) / (s.max - s.min)) * 100));
        bar = `<span class="range-bar" aria-hidden="true"><i style="left:${pct.toFixed(1)}%"></i></span>`;
      }
      return `<span class="range">${esc(lo)} – ${esc(hi)}</span>${bar}`;
    }
    if (s.max_length != null) return `<span class="range">up to ${esc(s.max_length)} characters</span>`;
    if (s.type === "color") return '<span class="range">any colour (#rrggbb)</span>';
    if (s.type === "toggle") return '<span class="range">on / off</span>';
    if (s.type === "text") return '<span class="range">free text</span>';
    return '<span class="range">—</span>';
  };
  const TYPE = { choice: "choice", toggle: "on/off", integer: "whole number", number: "number", color: "colour", text: "text" };

  function settingsTable(settings) {
    const groups = new Map();
    for (const s of settings) {
      const g = s.group || "";
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(s);
    }
    const order = [...groups.keys()].sort((a, b) => (a === "" ? -1 : b === "" ? 1 : 0));
    const many = order.length > 1;
    const rows = order.map((g) => {
      const head = many ? `<tr><td colspan="4" class="group-title">${esc(g || "General")}</td></tr>` : "";
      return head + groups.get(g).map((s) => `
        <tr>
          <td class="k">${esc(s.title)}<code>${esc(s.key)}</code>${s.description ? `<span class="d">${esc(s.description)}</span>` : ""}</td>
          <td><span class="t">${esc(TYPE[s.type] || s.type)}</span></td>
          <td class="def-cell"><span class="v">${fmt(s, s.default)}</span></td>
          <td class="opt-cell">${optionsCell(s)}</td>
        </tr>`).join("");
    }).join("");
    return `<div class="table-scroll"><table class="settings-table">
      <thead><tr><th scope="col">Setting</th><th scope="col">Type</th><th scope="col">Default</th><th scope="col">Options / range</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }

  function codeBlock(label, cmd) {
    return `<div class="code"><span class="label">${esc(label)}</span><pre><span class="p">$ </span>${esc(cmd)}</pre></div>`;
  }

  function openApp(id, push = true) {
    const a = DATA?.apps.find((x) => x.id === id);
    if (!a) return;
    const col = CAT_COLOR[a.category];
    $("#dlg-thumb").replaceChildren(thumb(a, true));
    $("#dlg-title").textContent = a.name;
    $("#dlg-desc").textContent = a.description;
    $("#dlg-badges").innerHTML =
      `<span class="badge" style="--c:${col}"><i></i>${esc(DATA.catLabel[a.category])}</span>` +
      a.kinds.map((k) => `<span class="badge" style="--c:${KIND[k].c}"><i></i>${KIND[k].label}</span>`).join("") +
      ((a.game?.max_players || 1) > 1 ? `<span class="badge" style="--c:#ff4818"><i></i>${a.game.max_players} players</span>` : "");

    const k = KIND[a.kind];
    const kindNote = a.kinds.length > 1 ? `${k.text} Some options switch it to ${a.kinds.filter((x) => x !== a.kind).map((x) => KIND[x].label.toLowerCase()).join(" / ")}.` : k.text;
    let html = `<h3>At a glance</h3><div class="facts">
      <div class="fact"><span>Output</span><b>${k.label}</b><small>${esc(kindNote)}</small></div>
      <div class="fact"><span>Settings</span><b>${a.settings.length}</b><small>every one editable live in the studio, or by an agent with <code>update_app_settings</code></small></div>
      ${a.actions.length ? `<div class="fact"><span>Buttons</span><b>${a.actions.map((x) => esc(x.label)).join(" · ")}</b><small>studio buttons, or <code>app_action</code> over MCP</small></div>` : ""}
      ${a.source ? `<div class="fact"><span>Source</span><b><a href="${REPO}/blob/main/${esc(a.source)}">${esc(a.source.split("/").pop())}</a></b><small>${esc(a.source)}</small></div>` : ""}
    </div>`;

    if (a.game) {
      const gm = a.game;
      html += `<h3>Game</h3><div class="facts">
        <div class="fact"><span>Players</span><b>${gm.max_players > 1 ? `1–${gm.max_players}` : "1"}</b><small>${gm.max_players > 1 ? "seat 1 on the keyboard or studio, the rest on phones over your Wi-Fi; empty seats are played by the AI" : "single player"}</small></div>
        ${gm.controls.length ? `<div class="fact"><span>Controllers</span><div class="pills" style="margin-top:6px">${gm.controls.map((c, i) => `<span class="pill${i === 0 ? " def" : ""}">${esc(CONTROL[c] || c)}</span>`).join("")}</div></div>` : ""}
      </div>`;
      if (gm.modes.length) {
        html += `<div class="table-scroll" style="margin-top:10px"><table class="settings-table"><thead><tr><th scope="col">Mode</th><th scope="col">Players</th><th scope="col">Play</th></tr></thead><tbody>${gm.modes
          .map((m, i) => `<tr><td class="k">${esc(m.name)}${i === 0 ? ' <span class="tag" style="color:var(--ember-2)">default</span>' : ""}</td><td class="v">${m.min_players === m.max_players ? m.min_players : `${m.min_players}–${m.max_players}`}</td><td>${esc(TEAMS[m.teams] || m.teams)}</td></tr>`)
          .join("")}</tbody></table></div>`;
      }
      if (gm.maps.length) html += `<h3>Maps</h3><div class="pills">${gm.maps.map((m, i) => `<span class="pill${i === 0 ? " def" : ""}">${esc(m.label)}</span>`).join("")}</div>`;
      if (gm.themes.length) {
        const def = a.settings.find((s) => s.key === "theme")?.default;
        html += `<h3>Themes</h3><div class="pills">${gm.themes.map((t) => `<span class="pill${t.value === def ? " def" : ""}">${esc(t.label)}</span>`).join("")}</div>`;
      }
    }

    html += `<h3>Settings</h3>${a.settings.length ? settingsTable(a.settings) : '<p class="range">This app has no settings.</p>'}`;

    const choice = a.settings.find((s) => s.options && s.options.length > 1);
    const example = choice ? ` --settings '${JSON.stringify({ [choice.key]: choice.options.find((o) => o.value !== choice.default)?.value ?? choice.default })}'` : "";
    html += `<h3>Try it</h3>
      ${codeBlock("render a frame to PNG (no panel needed)", `uv run dotdeck preview ${a.id}${example} --out ${a.id}.png`)}
      <p class="range" style="margin-top:10px">Or ask your agent: “Show ${esc(a.name)} on my panel”. It calls <code>show_app</code> with <code>"${esc(a.id)}"</code>.</p>`;

    $("#dlg-body").innerHTML = html;
    addCopyButtons($("#dlg-body"));
    $("#dlg-body").scrollTop = 0;
    if (!dialog.open) dialog.showModal();
    if (push) history.replaceState(null, "", "#app/" + a.id);
  }

  dialog.addEventListener("close", () => {
    if (location.hash.startsWith("#app/")) history.replaceState(null, "", "#apps");
  });
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });

  grid.addEventListener("click", (e) => {
    const b = e.target.closest("[data-app]");
    if (b) openApp(b.dataset.app);
  });
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-open-app]");
    if (a && DATA) { e.preventDefault(); openApp(a.dataset.openApp); }
  });
  chipsEl.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.cat) state.cat = b.dataset.cat;
    if (b.dataset.flag) state.flags.has(b.dataset.flag) ? state.flags.delete(b.dataset.flag) : state.flags.add(b.dataset.flag);
    renderChips();
    applyFilters();
  });
  let qTimer = 0;
  search.addEventListener("input", () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { state.q = search.value.trim(); applyFilters(); }, 90);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement?.tagName || "") && !dialog.open) {
      e.preventDefault();
      search.focus();
      search.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
    }
  });
  addEventListener("hashchange", () => {
    const m = location.hash.match(/^#app\/(.+)$/);
    if (m) openApp(decodeURIComponent(m[1]), false);
  });

  fetch("apps.json")
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((data) => {
      DATA = data;
      DATA.catLabel = Object.fromEntries(data.categories.map((c) => [c.id, c.label]));
      for (const a of DATA.apps) a._hay = haystack(a);
      const totals = { apps: data.count, games: data.games, multiplayer: data.multiplayer, settings: data.apps.reduce((n, a) => n + a.settings.length, 0) };
      $$("[data-count]").forEach((el) => {
        const v = totals[el.dataset.count];
        if (v == null) return;
        el.textContent = el.dataset.count === "apps" && el.tagName !== "B" ? `${v}` : v.toLocaleString("en");
      });
      renderChips();
      applyFilters();
      const m = location.hash.match(/^#app\/(.+)$/);
      if (m) { $("#apps").scrollIntoView(); openApp(decodeURIComponent(m[1]), false); }
    })
    .catch(() => {
      grid.innerHTML = `<p class="empty">Couldn't load the app list. It's also on GitHub: <a href="${REPO}#-the-apps">README: The Apps</a>.</p>`;
    });
})();
