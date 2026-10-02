/* DeskDot — idotmatrix.com. Plain JS, no dependencies, shared by every page.
 * 1. the neon LED logo (canvas)   2. page chrome (menu, reveal, LED hovers, tabs, copy, stars)   3. the Apps explorer */
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
   * The "idotmatrix" wordmark as LEDs in three neon tubes ("i" rose, "dot" tangerine, "matrix" gold). The dots
   * build in (the i drops, "dot" types in, "matrix" rains down), then each tube is struck like real neon: a stutter
   * of flashes, then a steady hum, with one loose letter that blinks now and then. Same idea as web/src/lib/logo.ts. */
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
  const NEON = ["#ff3f78", "#ff7419", "#ffcc33"];
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

  /** Mount a logo on a canvas: sizes to its CSS box, animates only while visible, then idles on the hum.
   *  `built` skips the build-in (the header logo builds once per visit, not on every page). */
  function mountLogo(canvas, { grid = false, pad = 1, interactive = false, startDelay = 0, built = false } = {}) {
    if (!canvas || !canvas.getContext) return;
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
      if (reduced || !raf) frame(performance.now());
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
    resize();
  }

  const seenLogo = store.get("dd-logo") === "1";
  mountLogo($("#logo"), { grid: true, interactive: true, startDelay: 150 });
  mountLogo($(".mini-logo"), { pad: 0.5, startDelay: 500, built: seenLogo });
  mountLogo($(".footer-logo"), { pad: 0.5, built: true });
  store.set("dd-logo", "1");

  /* ===================================================================== 2. page chrome */
  const bar = $("#bar");
  const onScroll = () => bar && bar.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

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

  // the hero panel tilts toward the cursor
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

  // GitHub stars (best effort; cached for the session)
  (async () => {
    const slots = $$("[data-stars]");
    if (!slots.length) return;
    let n = store.get("dd-stars");
    if (n === null) {
      try {
        const r = await fetch("https://api.github.com/repos/shivpatel2468/idotmatrix", { headers: { Accept: "application/vnd.github+json" } });
        if (r.ok) n = String((await r.json()).stargazers_count ?? "");
      } catch { /* offline or rate-limited: the buttons just say GitHub */ }
      store.set("dd-stars", n ?? "");
    }
    if (n && Number(n) > 0) {
      const v = Number(n);
      const label = v >= 1000 ? (v / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(v);
      slots.forEach((s) => { s.textContent = "★ " + label; s.setAttribute("aria-label", `${v} stars`); });
    }
  })();

  /* ===================================================================== 3. apps explorer (apps.html)
   * The cards are static HTML (generated by scripts/build_site_pages.py); this only filters them. */
  const grid = $("#app-grid");
  if (grid) {
    const cards = $$(".app-card", grid);
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
})();
