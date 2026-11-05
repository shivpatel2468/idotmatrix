/* DeskDot — idotmatrix.com. Plain JS, no dependencies, shared by every page.
 * 1. the neon LED logo (canvas)   2. page chrome (notice, menu, reveal, LED hovers, tabs, copy, download)
 * 3. the Apps explorer   4. light / dark / auto and the page themes (the theme menu).
 * No third-party requests: the GitHub star count and the release downloads are baked in at build time. */
(() => {
  "use strict";

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const store = {
    get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* storage blocked */ } },
  };

  /* ===================================================================== 1. neon logo
   * The "DeskDot" wordmark as LEDs in three neon tubes ("Desk" rose, "Dot" gold: two shades). The dots build in
   * (the D drops, "esk" types in, "Dot" rains down), then each tube is struck like real neon: a stutter of flashes,
   * then a steady hum, with one loose letter that blinks now and then. Same idea as web/src/lib/logo.ts. */
  const GLYPHS = {
    D: ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    e: ["....", "....", ".##.", "#..#", "####", "#...", ".###"],
    s: ["....", "....", ".###", "#...", ".##.", "...#", "###."],
    k: ["#...", "#...", "#..#", "#.#.", "##..", "#.#.", "#..#"],
    o: ["....", "....", ".##.", "#..#", "#..#", "#..#", ".##."],
    t: ["...", ".#.", "###", ".#.", ".#.", ".#.", "..#"],
  };
  const WORDS = ["D", "esk", "Dot"];
  const LOOSE = 5; // the "o" of Dot
  const ROWS = 7;
  const NEON = ["#ff3f78", "#ff3f78", "#ffcc33"]; // two shades: "Desk" rose, "Dot" gold
  // Two looks, as web/src/lib/logo.ts: `neon` on dark pages (additive halos, white-hot cores) and `paper` on light ones
  // (the same tubes as deep ink, a halo that darkens instead of glowing, a soft sheen for the core).
  const LOOKS = {
    neon: { tubes: NEON, grid: "rgba(255,255,255,0.05)", glass: 0.22, halo: 0.5, blend: "lighter", fill: "lighter", core: "#fff", coreAlpha: 0.8, coreR: 0.45 },
    paper: { tubes: ["#c2154d", "#c2154d", "#996300"], grid: "rgba(74,58,36,0.13)", glass: 0.13, halo: 0.26, blend: "multiply", fill: "source-over", core: "#fff6ea", coreAlpha: 0.3, coreR: 0.3 },
  };
  const lookNow = () => (document.documentElement.dataset.theme === "light" ? "paper" : "neon");
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
    WORDS.forEach((w, part) => {
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
  const GLOWS = { neon: LOOKS.neon.tubes.map((c) => glowSprite(c, 64)), paper: LOOKS.paper.tubes.map((c) => glowSprite(c, 64)) };

  /** Draw the logo at (ox, oy) with dot pitch p. lt = seconds since start. */
  function drawLogo(ctx, lt, ox, oy, p, { build = 1.6, grid = false, flare = 0, still = false } = {}) {
    if (still) lt = build + 3;
    const igniteAt = build + 0.15;
    const r = p * 0.36;
    const look = lookNow(), st = LOOKS[look];
    if (grid) {
      ctx.fillStyle = st.grid;
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
      const color = st.tubes[part], glow = GLOWS[look][part];
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
        if (lit && !still && d.letter === LOOSE) {
          // the loose tube: one letter blinks out for a beat now and then
          const g = (lt * 0.37) % 1;
          if (g > 0.62 && g < 0.645) lv *= 0.1;
          else if (g > 0.66 && g < 0.672) lv *= 0.3;
        }
        const cx = ox + (x + 0.5) * p, cy = oy + (y + 0.5) * p;
        ctx.globalAlpha = st.glass * Math.min(1, k * 2);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(cx, cy, r * (1 + pop * 0.6), 0, Math.PI * 2);
        ctx.fill();
        const light = Math.max(lv, pop * 0.9);
        if (light > 0.02) {
          ctx.globalCompositeOperation = st.blend;
          ctx.globalAlpha = Math.min(st.halo, light * st.halo);
          const gs = p * (3.4 + flare * 2.5);
          ctx.drawImage(glow, cx - gs / 2, cy - gs / 2, gs, gs);
          ctx.globalCompositeOperation = st.fill;
          ctx.globalAlpha = Math.min(1, light);
          ctx.beginPath();
          ctx.arc(cx, cy, r * (1 + pop * 0.5), 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = Math.min(1, light * st.coreAlpha);
          ctx.fillStyle = st.core;
          ctx.beginPath();
          ctx.arc(cx, cy, r * st.coreR, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalCompositeOperation = "source-over";
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  // seconds until every tube has struck and holds steady (the build-in, the ignition and the longest strike)
  const SETTLE = 1.6 + 0.15 + Math.max(...STRIKE.map((_, p) => DELAY[p] + strikeLen(p))) + 0.1;

  /** Mount a logo on a canvas: sizes to its CSS box, animates only while visible.
   *  `built` skips the build-in (the header logo builds once per visit, not on every page).
   *  `settle`: once lit, draw one still frame and stop (the header and footer logos: no per-frame work while the
   *  page scrolls); a hover flares it and it settles again. Otherwise it idles on the hum at `fps`. */
  function mountLogo(canvas, { grid = false, pad = 1, interactive = false, startDelay = 0, built = false, settle = false, fps = 30 } = {}) {
    if (!canvas || !canvas.getContext) return;
    const ctx = canvas.getContext("2d");
    const cols = LOGO.cols + pad * 2, rows = ROWS + pad * 2;
    let w = 0, h = 0, p = 0, t0 = 0, raf = 0, visible = false, started = false, flare = 0, settled = false, last = 0;
    const resize = () => {
      const dpr = Math.min(2, devicePixelRatio || 1);
      const cw = canvas.clientWidth || canvas.width;
      p = cw / cols;
      w = cw; h = p * rows;
      canvas.style.height = h + "px";
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (reduced || !raf) frame(performance.now());
    };
    const frame = (now) => {
      ctx.clearRect(0, 0, w, h);
      const lt = started ? (now - t0) / 1000 : -1;
      flare *= 0.92;
      drawLogo(ctx, lt, pad * p, pad * p, p, { grid, flare, still: reduced || settled });
    };
    const loop = (now) => {
      // the build-in runs at full rate; the steady hum only needs `fps`
      const lit = started && (now - t0) / 1000 > SETTLE;
      if (!(lit && now - last < 1000 / fps - 4)) {
        last = now;
        if (settle && lit && flare < 0.02) settled = true;
        frame(now);
        if (settled && flare < 0.02) { raf = 0; return; }
      }
      raf = visible && !document.hidden ? requestAnimationFrame(loop) : 0;
    };
    const kick = () => { if (!raf && !reduced && visible && !document.hidden) raf = requestAnimationFrame(loop); };
    if (built) { started = true; t0 = performance.now() - 4000; }
    new ResizeObserver(resize).observe(canvas);
    new IntersectionObserver(([en]) => {
      visible = en.isIntersecting;
      if (visible && !started) {
        setTimeout(() => { started = true; t0 = performance.now(); kick(); }, startDelay);
      } else kick();
    }).observe(canvas);
    document.addEventListener("visibilitychange", kick);
    if (interactive && !reduced) canvas.addEventListener("pointerenter", () => { flare = 0.6; kick(); });
    redraws.push(() => (reduced || !raf) && frame(performance.now()));
    resize();
  }
  const redraws = []; // a theme change repaints idle logos in the new look

  const seenLogo = store.get("dd-logo") === "1";
  mountLogo($("#logo"), { grid: true, interactive: true, startDelay: 150 });
  mountLogo($(".mini-logo"), { pad: 0.5, startDelay: 500, built: seenLogo, settle: true, interactive: true });
  mountLogo($(".footer-logo"), { pad: 0.5, built: true, settle: true });
  store.set("dd-logo", "1");

  /* ===================================================================== 2. page chrome */
  // the "unofficial" notice strip under the header: dismissible, remembered in this browser
  const notice = $("#notice");
  if (notice) {
    $("button", notice)?.addEventListener("click", () => {
      document.documentElement.classList.add("no-notice");
      try { localStorage.setItem("dd-notice", "1"); } catch { /* storage blocked: hidden for this page only */ }
    });
  }

  // download page: the downloads and source links stay disabled until the Terms and Privacy box is ticked (clickwrap,
  // unticked by default); this computer's platform is marked as the recommended download
  const plat = (() => {
    const ua = navigator.userAgent || "", pf = navigator.userAgentData?.platform || navigator.platform || "";
    if (/Android/i.test(ua)) return "android";
    if (/iPhone|iPad|iPod/i.test(ua)) return "";
    if (/Win/i.test(pf)) return "windows";
    if (/Mac/i.test(pf)) return "mac";
    return "";
  })();
  if (plat) $$(`.dl-card[data-platform="${plat}"]`).forEach((c) => c.classList.add("mine"));
  $$("[data-agree]").forEach((box) => {
    const targets = box.dataset.agree.split(/\s+/).map((id) => $("#" + id)).filter(Boolean);
    const sync = () => targets.forEach((t) => {
      t.setAttribute("aria-disabled", String(!box.checked));
      t.tabIndex = box.checked ? 0 : -1;
    });
    targets.forEach((t) => t.addEventListener("click", (e) => { if (!box.checked) e.preventDefault(); }));
    box.checked = false;
    box.addEventListener("change", sync);
    sync();
  });

  // mobile menu: toggles, closes on Escape, on a link, or on a click outside
  const menuBtn = $("#menu-btn"), nav = $("#nav");
  const setMenu = (open) => {
    menuBtn.setAttribute("aria-expanded", String(open));
    nav.classList.toggle("open", open);
  };
  if (menuBtn && nav) {
    menuBtn.addEventListener("click", () => setMenu(menuBtn.getAttribute("aria-expanded") !== "true"));
    nav.addEventListener("click", (e) => { if (e.target.closest("a")) setMenu(false); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && nav.classList.contains("open")) { setMenu(false); menuBtn.focus(); }
    });
    document.addEventListener("click", (e) => {
      if (nav.classList.contains("open") && !e.target.closest("#nav, #menu-btn")) setMenu(false);
    });
  }

  // scroll reveal (stagger comes from --i in the markup)
  const revealObs = "IntersectionObserver" in window && !reduced
    ? new IntersectionObserver((entries) => {
      for (const en of entries) if (en.isIntersecting) { en.target.classList.add("in"); revealObs.unobserve(en.target); }
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.06 })
    : null;
  $$(".reveal").forEach((el) => (revealObs ? revealObs.observe(el) : el.classList.add("in")));

  // LEDs under the cursor on cards (at most once per frame: read the box, then write, never interleaved)
  let cardEv = null, cardRaf = 0;
  document.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse") return;
    cardEv = e;
    cardRaf ||= requestAnimationFrame(() => {
      cardRaf = 0;
      const card = cardEv.target.closest && cardEv.target.closest(".card");
      if (!card) return;
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", cardEv.clientX - r.left + "px");
      card.style.setProperty("--my", cardEv.clientY - r.top + "px");
    });
  }, { passive: true });

  // 5×5 LED icons from data-led="#.#.#|..."
  $$(".ledico[data-led]").forEach((el) => {
    let n = 0;
    el.innerHTML = el.dataset.led.split("|").flatMap((row) => [...row].map((c) => `<i class="${c === "#" ? "on" : ""}" style="--d:${n++}"></i>`)).join("");
    el.setAttribute("aria-hidden", "true");
  });

  // the hero panel tilts toward the cursor
  const device = $("#device .device-frame");
  if (device && !reduced && matchMedia("(pointer: fine)").matches) {
    const hero = $(".hero");
    let tiltEv = null, tiltRaf = 0;
    hero.addEventListener("pointermove", (e) => {
      tiltEv = e;
      tiltRaf ||= requestAnimationFrame(() => {
        tiltRaf = 0;
        const r = device.getBoundingClientRect();
        const dx = (tiltEv.clientX - (r.left + r.width / 2)) / innerWidth;
        const dy = (tiltEv.clientY - (r.top + r.height / 2)) / innerHeight;
        device.style.setProperty("--ry", (dx * 16 - 4).toFixed(2) + "deg");
        device.style.setProperty("--rx", (-dy * 12 + 2).toFixed(2) + "deg");
      });
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
  if (osBtns.length) {
    const setOS = (os) => {
      osBtns.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.os === os)));
      $$("[data-os-panel]").forEach((p) => (p.hidden = p.dataset.osPanel !== os));
    };
    osBtns.forEach((b) => b.addEventListener("click", () => setOS(b.dataset.os)));
    setOS(/Win/i.test(navigator.userAgentData?.platform || navigator.platform || navigator.userAgent) ? "win" : "unix");
  }

  // copy buttons: every code block gets one; [data-copy-target] buttons copy an element by id
  const toast = $("#toast");
  let toastTimer = 0;
  const say = (msg) => {
    if (!toast) return;
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
  $$(".code").forEach((box) => {
    const pre = $("pre", box);
    if (!pre || $(".copy", box)) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "copy";
    b.setAttribute("aria-label", "Copy to clipboard");
    b.innerHTML = '<svg aria-hidden="true"><use href="#i-copy"/></svg>';
    b.addEventListener("click", () => copy(textOf(pre), b));
    box.append(b);
  });
  $$("[data-copy-target]").forEach((b) => b.addEventListener("click", () => copy(textOf($("#" + b.dataset.copyTarget)), b)));

  // the home page's tagline: each word lights up as it crosses into the lower third of the screen, in reading order
  const tagWords = $$(".tagline .w");
  if (tagWords.length) {
    if (reduced || !("IntersectionObserver" in window)) tagWords.forEach((w) => w.classList.add("on"));
    else {
      const wordObs = new IntersectionObserver((entries) => {
        for (const en of entries) if (en.isIntersecting) { en.target.classList.add("on"); wordObs.unobserve(en.target); }
      }, { rootMargin: "0px 0px -30% 0px" });
      tagWords.forEach((w) => wordObs.observe(w));
    }
  }

  /* ===================================================================== 3. apps explorer (apps.html)
   * The cards are static HTML (generated by scripts/build_site_pages.py); this only filters them. */
  const tools = $(".explorer-tools");
  if (tools && !reduced) {
    // The search bar's neon tube is struck now and then like the logo's tubes: one of the same STRIKE stutters
    // (on/off levels), at a random moment every few seconds. Only `--neon` (an opacity) changes.
    const flicker = () => {
      if (!document.hidden) {
        let at = 0;
        for (const [d, v] of STRIKE[Math.floor(Math.random() * STRIKE.length)]) {
          setTimeout(() => tools.style.setProperty("--neon", v), at * 1000);
          at += d;
        }
        setTimeout(() => tools.style.setProperty("--neon", 1), at * 1000);
      }
      setTimeout(flicker, 3500 + Math.random() * 7500);
    };
    setTimeout(flicker, 1500 + Math.random() * 3000);
  }
  const grid = $("#app-grid");
  if (grid) {
    const cards = $$(".app-card", grid);
    const casinoNote = $(".casino-note", grid);
    const search = $("#app-search"), chipsEl = $("#cat-chips"), countEl = $("#result-count"), none = $("#no-results");
    const hay = new Map(cards.map((c) => [c, (c.dataset.search || c.textContent).toLowerCase()]));
    const state = { q: "", cat: "all", flags: new Set() };

    const apply = () => {
      const terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
      let shown = 0;
      for (const c of cards) {
        const flags = (c.dataset.flags || "").split(" ");
        const ok = (state.cat === "all" || c.dataset.cat === state.cat) &&
          [...state.flags].every((f) => flags.includes(f)) &&
          terms.every((t) => hay.get(c).includes(t));
        c.hidden = !ok;
        if (ok) c.style.setProperty("--i", String(Math.min(shown, 12)));
        shown += ok ? 1 : 0;
      }
      none.hidden = shown > 0;
      if (casinoNote) casinoNote.hidden = !cards.some((c) => !c.hidden && c.dataset.cat === "casino");
      countEl.textContent = shown === cards.length ? `Showing all ${cards.length} apps` : `Showing ${shown} of ${cards.length} apps`;
    };
    const syncChips = () => $$("button", chipsEl).forEach((b) => {
      const on = b.dataset.cat ? b.dataset.cat === state.cat : state.flags.has(b.dataset.flag);
      b.setAttribute("aria-pressed", String(on));
    });
    const syncHash = () => {
      const h = state.cat !== "all" ? `#cat=${state.cat}` : "";
      history.replaceState(null, "", location.pathname + location.search + h);
    };
    chipsEl.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.cat) state.cat = b.dataset.cat;
      if (b.dataset.flag) state.flags.has(b.dataset.flag) ? state.flags.delete(b.dataset.flag) : state.flags.add(b.dataset.flag);
      syncChips();
      syncHash();
      apply();
    });
    let qTimer = 0;
    search.addEventListener("input", () => {
      clearTimeout(qTimer);
      qTimer = setTimeout(() => { state.q = search.value.trim(); apply(); }, 80);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement?.tagName || "")) {
        e.preventDefault();
        search.focus();
      }
    });
    const fromHash = () => {
      const m = location.hash.match(/^#cat=([\w-]+)$/);
      state.cat = m && $(`[data-cat="${m[1]}"]`, chipsEl) ? m[1] : "all";
      syncChips();
      apply();
    };
    addEventListener("hashchange", fromHash);
    fromHash();
  }

  /* ===================================================================== 4. light / dark / auto and table themes
   * Light / dark / auto is the studio's (web/src/lib/theme.ts: `deskdot.theme`, shared with the web app at /app/; nothing
   * stored = dark here). The table theme is one of the casino's 21 (scripts/site_theme.py), kept in `deskdot.siteTheme`
   * (the web app's landing card reads it too); an old studio pick that is also a table id still counts, else Cyber grid.
   * The inline script in <head> applied both before first paint. */
  const THEME_KEY = "deskdot.theme", PAGE_KEY = "deskdot.siteTheme", STUDIO_KEY = "deskdot.pageTheme", DEFAULT = "cyber";
  const root = document.documentElement;
  const light = matchMedia("(prefers-color-scheme: light)");
  const local = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: this page only */ } },
  };
  const menu = $("#theme-menu"), themeBtn = $("#theme-btn");
  const swatches = $$("[data-page-theme-pick]", menu || document);
  const pref = () => { const v = local.get(THEME_KEY); return v === "light" || v === "dark" || v === "system" ? v : "dark"; };
  const resolve = (p) => (p === "system" ? (light.matches ? "light" : "dark") : p);
  const known = (v) => swatches.some((b) => b.dataset.pageThemePick === v);
  const pageTheme = () => {
    const v = local.get(PAGE_KEY), w = local.get(STUDIO_KEY);
    return known(v) ? v : known(w) ? w : DEFAULT;
  };
  const sync = () => {
    $$("[data-theme-pick]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themePick === pref())));
    const pt = pageTheme();
    swatches.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.pageThemePick === pt)));
    const name = $("#theme-name");
    const cur = swatches.find((b) => b.dataset.pageThemePick === pt);
    if (name && cur) name.textContent = cur.title;
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", getComputedStyle(root).getPropertyValue("--theme-color").trim() || "#06080a");
  };
  const paint = (fn) => {
    const go = () => { fn(); sync(); redraws.forEach((r) => r()); };
    if (reduced) return go();
    if (document.startViewTransition) {
      root.classList.add("theme-vt");
      const vt = document.startViewTransition(go);
      const done = () => root.classList.remove("theme-vt");
      vt.finished ? vt.finished.then(done, done) : done();
      return;
    }
    root.classList.add("theme-fade");
    setTimeout(() => root.classList.remove("theme-fade"), 450);
    go();
  };
  const applyMode = (p) => paint(() => root.setAttribute("data-theme", resolve(p)));
  const applyPage = (id) => paint(() => root.setAttribute("data-page-theme", id));
  const openMenu = (open, from) => {
    if (!menu) return;
    menu.hidden = !open;
    $$("[aria-controls='theme-menu']").forEach((b) => b.setAttribute("aria-expanded", String(open)));
    if (open) {
      sync();
      ($('[aria-pressed="true"]', menu) || $("button", menu))?.focus();
      if (from && from !== themeBtn) menu.scrollIntoView?.({ block: "nearest" });
    } else if (from) from.focus();
  };
  if (menu) {
    let opener = null;
    $$("[aria-controls='theme-menu']").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      opener = b;
      openMenu(menu.hidden, b);
    }));
    $(".theme-close", menu)?.addEventListener("click", () => openMenu(false, opener || themeBtn));
    $$("[data-theme-pick]", menu).forEach((b) => b.addEventListener("click", () => {
      local.set(THEME_KEY, b.dataset.themePick);
      applyMode(b.dataset.themePick);
    }));
    swatches.forEach((b) => b.addEventListener("click", () => {
      local.set(PAGE_KEY, b.dataset.pageThemePick);
      applyPage(b.dataset.pageThemePick);
    }));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) openMenu(false, opener || themeBtn); });
    document.addEventListener("click", (e) => { if (!menu.hidden && !e.target.closest("#theme-menu")) openMenu(false); });
  }
  light.addEventListener?.("change", () => pref() === "system" && applyMode("system"));
  addEventListener("storage", (e) => {
    if (e.key === THEME_KEY) applyMode(pref());
    if (e.key === PAGE_KEY) applyPage(pageTheme());
  });
  sync();
})();
