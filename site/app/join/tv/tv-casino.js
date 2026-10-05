/* DeskDot TV view — the casino tables (docs/TV_VIEW.md §4, docs/CASINO.md).
 *
 * One bespoke 1920×984 broadcast scene per casino game: roulette, blackjack, baccarat, slots, Texas hold'em,
 * teen patti, andar bahar, big six, 7 up 7 down and housie. Each scene is one canvas redrawn every animation frame
 * over a cached background (felt, printed layout, rail), in the table's theme (status.table_theme → ctx.theme), plus
 * the live LED panel as a small inset in the right-hand rail.
 *
 * Only public information is drawn — it is all the TV receives: the public casino status phones get (spot_bets,
 * totals, players, history, the result after the reveal, face-up cards; hole cards only at a showdown).
 *
 * Timing. Countdown fields (ends_in, reveal_in, next_in, turn_in …) are whole seconds left, rounded up, measured when
 * the state was built (ctx.stateAt). `Countdown` intersects the windows of successive states to estimate the real
 * deadline to ~0.2 s, and spin animations run from the estimated lock time (reveal deadline − LOCK − spin seconds),
 * the same clock the panel apps use. The outcome is secret until the result phase, so wheels / balls / dice spin
 * honestly and only settle on the outcome once it is public (a short, natural-looking settle).
 *
 * Plain modern JS, no dependencies. Helpers are exposed as TV.casino for tests (tests/js/tv_casino.test.mjs).
 */
(function () {
  "use strict";

  const TV = typeof window !== "undefined" ? window.TV : undefined;

  // ================================================================================================ constants
  const SW = 1920;
  const SH = 984;
  const RAIL_X = 1540;
  const RAIL_W = SW - RAIL_X;
  const PANEL_PITCH = 9;
  const PANEL_SIZE = 32 * PANEL_PITCH;
  const PANEL_X = RAIL_X + (RAIL_W - PANEL_SIZE) / 2;
  const PANEL_Y = 672;
  const LOCK = 1.0; // casino/table.py LOCK_SECONDS
  const TAU = Math.PI * 2;
  const FONT = '"Segoe UI Variable Display","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif';
  const MONO = '"Cascadia Mono","SF Mono",Consolas,"Roboto Mono",ui-monospace,Menlo,monospace';
  const CLASSIC = {
    felt: "#0d6b45", felt2: "#0a5236", felt3: "#063823", accent: "#ffcc33", accent_hi: "#ffe08a", accent_lo: "#e2a400",
    accent_deep: "#3a2c08", accent_rgb: "255, 204, 51", ink: "#1a1200", wing: "#102a20", wing2: "#0b1c16", wing3: "#0a1512",
  }; // fmt: skip
  const TONE = {
    red: "#d0182f", black: "#26262e", green: "#0e9a4c", white: "#5a5a68", gold: "#c99a00",
    player: "#1f5fe0", banker: "#d0182f", tie: "#0e9a4c", andar: "#e0641a", bahar: "#1f8fe0",
    down: "#1f6fff", seven: "#d9a000", up: "#e0263c",
    b6_1: "#e6b31e", b6_2: "#2a78ff", b6_5: "#12b35a", b6_10: "#a64dff", b6_20: "#ff6a1a", b6_joker: "#ff2f96", b6_logo: "#d9c27a",
  }; // fmt: skip
  const OK = "#3ddc84";
  const BAD = "#ff4d5e";
  const INK1 = "#f3eee2";
  const INK2 = "#c4bfb2";
  const INK3 = "#8b877e";

  // ================================================================================================ small helpers
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, k) => a + (b - a) * k;
  const easeOut = (u) => 1 - Math.pow(1 - clamp(u, 0, 1), 3);
  const easeIn = (u) => Math.pow(clamp(u, 0, 1), 2);
  const easeInOut = (u) => ((u = clamp(u, 0, 1)), u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
  const wrapPi = (a) => a - TAU * Math.floor((a + Math.PI) / TAU);
  const mod = (a, n) => ((a % n) + n) % n;
  const num = (v, d = 0) => (typeof v === "number" && Number.isFinite(v) ? v : d);
  const arr = (v) => (Array.isArray(v) ? v : []);
  const obj = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : {});

  /** A stable pseudo-random number in [0, 1) for animation flourishes (never for outcomes). */
  function hash01(s) {
    let h = 2166136261;
    const str = String(s);
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    h ^= h >>> 13;
    h = Math.imul(h, 0x5bd1e995);
    h ^= h >>> 15;
    return (h >>> 0) / 4294967296;
  }

  function hexRgb(h) {
    let s = String(h || "").trim().replace("#", "");
    if (s.length === 3) s = s.split("").map((c) => c + c).join("");
    const m = /^[0-9a-f]{6}$/i.test(s) ? parseInt(s, 16) : 0xf0f0f0;
    return [(m >> 16) & 255, (m >> 8) & 255, m & 255];
  }
  const rgba = (h, a) => {
    const [r, g, b] = hexRgb(h);
    return `rgba(${r},${g},${b},${a})`;
  };
  /** k < 1 darkens, k > 1 lightens toward white (1.3 = 30 % of the way). */
  function shade(h, k) {
    const f = (v) => Math.round(clamp(k >= 1 ? v + (255 - v) * (k - 1) : v * k, 0, 255));
    const [r, g, b] = hexRgb(h);
    return `rgb(${f(r)},${f(g)},${f(b)})`;
  }

  function fmt(S, n) {
    const c = S && S.ctx;
    if (c && typeof c.fmt === "function") return c.fmt(n);
    const v = Number(n);
    return Number.isFinite(v) ? Math.round(v).toLocaleString("en-US") : "–";
  }
  const signed = (S, n) => (n > 0 ? "+" : n < 0 ? "−" : "±") + fmt(S, Math.abs(n));

  // ================================================================================================ timing
  /**
   * A deadline from whole-second "left" values (ceil, as casino/table.py `_left` builds them) observed at times t:
   * each sample says deadline ∈ (t + left − 1, t + left]. Samples under the same key narrow the window; a sample
   * that contradicts it (the deadline moved) restarts it.
   */
  class Countdown {
    constructor() {
      this.key = null;
      this.lo = -Infinity;
      this.hi = Infinity;
    }
    observe(key, left, t) {
      if (left == null || typeof left !== "number" || !Number.isFinite(left)) {
        this.key = null;
        return;
      }
      if (key !== this.key) {
        this.key = key;
        this.lo = -Infinity;
        this.hi = Infinity;
      }
      const lo = left <= 0 ? -Infinity : t + left - 1;
      const hi = t + left;
      const nlo = Math.max(this.lo, lo);
      const nhi = Math.min(this.hi, hi);
      if (nlo > nhi + 0.05) {
        this.lo = lo;
        this.hi = hi;
      } else {
        this.lo = nlo;
        this.hi = Math.max(nlo, nhi);
      }
    }
    /** the estimated deadline (local seconds) or null */
    get at() {
      if (this.key == null) return null;
      return Number.isFinite(this.lo) ? (this.lo + this.hi) / 2 : this.hi;
    }
    left(t) {
      const a = this.at;
      return a == null ? null : Math.max(0, a - t);
    }
  }

  /** The table's phase clock: when the current phase started and the betting / reveal / next-round deadlines. */
  class PhaseTracker {
    constructor() {
      this.key = null;
      this.phase = "idle";
      this.round = null;
      this.start = 0;
      this.prevPhase = null;
      this.ends = new Countdown();
      this.reveal = new Countdown();
      this.next = new Countdown();
    }
    observe(st, t) {
      const phase = String(st.phase || "idle");
      const key = `${st.round}|${phase}`;
      if (key !== this.key) {
        this.prevPhase = this.key ? this.phase : null;
        this.key = key;
        this.phase = phase;
        this.round = st.round;
        this.start = t;
      }
      this.ends.observe(`${st.round}|${phase}|ends`, st.ends_in, t);
      this.reveal.observe(`${st.round}|reveal`, st.reveal_in, t);
      this.next.observe(`${st.round}|${phase}|next`, st.next_in, t);
    }
    since(t) {
      return Math.max(0, t - this.start);
    }
  }

  /** When betting closed for a bet-then-reveal game: reveal deadline − (LOCK + spin), else from the phase start. */
  function lockTime(clk, spin) {
    const r = clk.reveal.at;
    if (r != null) return r - LOCK - spin;
    if (clk.phase === "locked") return clk.start;
    return clk.start - LOCK;
  }

  // ================================================================================================ cards
  const RANKS = { T: "10", J: "J", Q: "Q", K: "K", A: "A" };
  function parseCard(code) {
    const s = String(code || "").toUpperCase();
    if (s.length < 2 || s === "??") return null;
    const suit = s[s.length - 1];
    const r = s.slice(0, -1);
    if (!"SHDC".includes(suit)) return null;
    const rank = RANKS[r] || (r === "10" ? "10" : /^[2-9]$/.test(r) ? r : null);
    if (!rank) return null;
    return { rank, suit, red: suit === "H" || suit === "D" };
  }
  function baccaratValue(code) {
    const c = parseCard(code);
    if (!c) return 0;
    if (c.rank === "A") return 1;
    if (c.rank === "10" || c.rank === "J" || c.rank === "Q" || c.rank === "K") return 0;
    return parseInt(c.rank, 10);
  }
  const baccaratTotal = (codes) => arr(codes).reduce((a, c) => a + baccaratValue(c), 0) % 10;

  // ================================================================================================ roulette maths
  const EU_WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14,
    31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]; // fmt: skip
  const US_WHEEL = [0, 28, 9, 26, 30, 11, 7, 20, 32, 17, 5, 22, 34, 15, 3, 24, 36, 13, 1, 37, 27, 10, 25, 29, 12, 8,
    19, 31, 18, 6, 21, 33, 16, 4, 23, 35, 14, 2]; // fmt: skip
  const REDS = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
  const rColor = (n) => (n === 0 || n === 37 ? "green" : REDS.has(n) ? "red" : "black");
  const rLabel = (n) => (n === 37 ? "00" : String(n));
  const rNum = (s) => (s === "00" ? 37 : parseInt(s, 10));
  const EVEN_SPOTS = ["low", "even", "red", "black", "odd", "high"];
  const EVEN_LABEL = { low: "1–18", even: "EVEN", red: "", black: "", odd: "ODD", high: "19–36" };
  const range = (a, b, st = 1) => {
    const o = [];
    for (let v = a; v <= b; v += st) o.push(v);
    return o;
  };

  function splitId(id) {
    const s = String(id);
    const i = s.indexOf(":");
    return i < 0 ? [s, ""] : [s.slice(0, i), s.slice(i + 1)];
  }

  /** The pockets a roulette spot id covers (casino/games/roulette.py spot ids; 37 = 00). */
  function rouletteCovers(id) {
    const [k, r] = splitId(id);
    switch (k) {
      case "n":
        return [rNum(r)];
      case "s":
      case "tr":
        return r.split("-").map(rNum);
      case "c": {
        const a = rNum(r);
        return [a, a + 1, a + 3, a + 4];
      }
      case "st": {
        const a = rNum(r);
        return [a, a + 1, a + 2];
      }
      case "sl": {
        const a = rNum(r);
        return range(a, a + 5);
      }
      case "ff":
        return [0, 1, 2, 3];
      case "tl":
        return [0, 37, 1, 2, 3];
      case "dz":
        return range(12 * +r - 11, 12 * +r);
      case "col":
        return range(+r, 36, 3);
      case "red":
        return range(1, 36).filter((n) => REDS.has(n));
      case "black":
        return range(1, 36).filter((n) => !REDS.has(n));
      case "odd":
        return range(1, 36, 2);
      case "even":
        return range(2, 36, 2);
      case "low":
        return range(1, 18);
      case "high":
        return range(19, 36);
      default:
        return [];
    }
  }

  /** The printed layout's geometry (numbers run in columns of three: 3 on the top row, 1 at the bottom). */
  function rouletteBoard(american) {
    return { x0: 742, y0: 330, zw: 72, cw: 51, ch: 86, colW: 68, dzH: 64, emH: 64, us: !!american };
  }
  function numCell(n, B) {
    const c = Math.floor((n - 1) / 3);
    const r = 2 - ((n - 1) % 3);
    return { x: B.x0 + B.zw + c * B.cw, y: B.y0 + r * B.ch, c, r };
  }
  function rouletteCenter(n, B) {
    if (n === 0) return [B.x0 + B.zw / 2, B.y0 + (B.us ? 2.25 : 1.5) * B.ch];
    if (n === 37) return [B.x0 + B.zw / 2, B.y0 + 0.75 * B.ch];
    const q = numCell(n, B);
    return [q.x + B.cw / 2, q.y + B.ch / 2];
  }
  /** Where a spot's chips sit on the layout (stage px), or null for an unknown id. */
  function rouletteSpotXY(id, B) {
    const L = B.x0 + B.zw;
    const bottom = B.y0 + 3 * B.ch;
    const [k, r] = splitId(id);
    switch (k) {
      case "n":
        return rouletteCenter(rNum(r), B);
      case "s": {
        const [a, b] = r.split("-").map(rNum);
        if (a === 0 && b === 37) return [B.x0 + B.zw / 2, B.y0 + 1.5 * B.ch];
        if (a === 0 || a === 37) {
          let y = rouletteCenter(b, B)[1];
          if (B.us && b === 2) y += (a === 0 ? 0.25 : -0.25) * B.ch;
          return [L, y];
        }
        if (!(a >= 1 && a <= 36)) return null;
        const q = numCell(a, B);
        return b === a + 1 ? [q.x + B.cw / 2, q.y] : [q.x + B.cw, q.y + B.ch / 2];
      }
      case "tr":
        return { "0-1-2": [L, B.y0 + 2 * B.ch], "0-2-3": [L, B.y0 + B.ch], "0-00-2": [L, B.y0 + 1.5 * B.ch],
          "00-2-3": [L, B.y0 + B.ch] }[r] || null; // fmt: skip
      case "ff":
      case "tl":
        return [L, bottom];
      case "st":
      case "sl":
      case "c": {
        const a = rNum(r);
        if (!(a >= 1 && a <= 36)) return null;
        const q = numCell(a, B);
        if (k === "st") return [q.x + B.cw / 2, bottom];
        if (k === "sl") return [q.x + B.cw, bottom];
        return [q.x + B.cw, q.y];
      }
      case "dz":
        return [L + (4 * (+r - 1) + 2) * B.cw, bottom + B.dzH / 2];
      case "col":
        return [L + 12 * B.cw + B.colW / 2, B.y0 + (3 - +r) * B.ch + B.ch / 2];
      default: {
        const i = EVEN_SPOTS.indexOf(String(id));
        return i >= 0 ? [L + (2 * i + 1) * B.cw, bottom + B.dzH + B.emH / 2] : null;
      }
    }
  }

  const travelExp = (x, w0, tau) => (x <= 0 ? 0 : w0 * tau * (1 - Math.exp(-x / tau)));

  /** Cubic Hermite from 0 (speed v0 per second) to d (speed 0) over T seconds: the settle of a wheel / ball. */
  function settle(d, v0, T, s) {
    const u = clamp(s / T, 0, 1);
    const h10 = u * u * u - 2 * u * u + u;
    const h01 = -2 * u * u * u + 3 * u * u;
    return h10 * v0 * T + h01 * d;
  }

  // ================================================================================================ big six / sevens / slots data
  const B6_WHEEL = ["joker", "2", "1", "1", "2", "1", "5", "2", "1", "1", "10", "2", "1", "5", "2", "1", "1", "20", "2",
    "1", "1", "5", "2", "1", "10", "2", "1", "logo", "1", "5", "2", "1", "2", "1", "1", "2", "5", "10", "1", "1", "2", "1",
    "1", "2", "20", "5", "1", "2", "1", "1", "2", "10", "5", "1"]; // fmt: skip
  const B6 = [
    { sym: "1", id: "s1", n: 24, pays: 1, col: "#ffc81e" },
    { sym: "2", id: "s2", n: 15, pays: 2, col: "#2878ff" },
    { sym: "5", id: "s5", n: 7, pays: 5, col: "#00c85a" },
    { sym: "10", id: "s10", n: 4, pays: 10, col: "#be50ff" },
    { sym: "20", id: "s20", n: 2, pays: 20, col: "#ff5a14" },
    { sym: "joker", id: "joker", n: 1, pays: 40, col: "#ff2896" },
    { sym: "logo", id: "logo", n: 1, pays: 40, col: "#ffecaa" },
  ];
  const B6_BY = Object.fromEntries(B6.map((s) => [s.sym, s]));
  const SEVENS = [
    { id: "down", name: "UNDER 7", sub: "2 – 6", col: "#1f6fff", pays: "1 : 1" },
    { id: "seven", name: "LUCKY 7", sub: "exactly 7", col: "#e0a800", pays: "4 : 1" },
    { id: "up", name: "OVER 7", sub: "8 – 12", col: "#e0263c", pays: "1 : 1" },
  ];
  const SLOT_LINES = [[1, 1, 1], [0, 0, 0], [2, 2, 2], [0, 1, 2], [2, 1, 0]];
  const SLOT_STOPS = [1.5, 2.1, 2.7];
  const LINE_COLORS = ["#ffcc33", "#ff3f78", "#33d1ff", "#7dff5a", "#ff7419"];

  /** The panel's reel position (apps/casino_slots.py reel_pos): a float strip index for the middle row. */
  function reelPos(stop, n, t, i) {
    const T = SLOT_STOPS[i];
    const travel = 3 * n + 4 * i;
    if (t <= 0) return stop - travel;
    if (t < T) {
      const u = t / T;
      const ease = 1 - Math.pow(1 - u, 3);
      return stop - travel * (1 - ease) + 0.35 * Math.sin(Math.PI * Math.pow(Math.min(1, u), 8));
    }
    const k = t - T;
    return stop + 0.3 * Math.exp(-k * 9) * Math.sin(k * 26);
  }

  const HOUSIE_NAMES = {
    1: "Kelly's eye", 2: "One little duck", 7: "Lucky seven", 8: "Garden gate", 9: "Doctor's orders", 10: "Uncle Ben",
    11: "Legs eleven", 12: "One dozen", 13: "Unlucky for some", 16: "Sweet sixteen", 21: "Key of the door",
    22: "Two little ducks", 26: "Pick and mix", 30: "Dirty Gertie", 31: "Get up and run", 32: "Buckle my shoe",
    33: "All the threes", 39: "Steps", 44: "Droopy drawers", 45: "Halfway there", 50: "Half a century",
    55: "Snakes alive", 66: "Clickety click", 69: "Any way up", 72: "Six dozen", 77: "Sunset strip", 80: "Gandhi's breakfast",
    81: "Stop and run", 85: "Staying alive", 88: "Two fat ladies", 89: "Nearly there", 90: "Top of the shop",
  }; // fmt: skip

  // ================================================================================================ canvas kit
  function makeCanvas(w, h, k) {
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.ceil(w * k));
    c.height = Math.max(1, Math.ceil(h * k));
    const g = c.getContext("2d");
    g.setTransform(k, 0, 0, k, 0, 0);
    return { c, g, w, h, k };
  }
  function rr(g, x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    g.beginPath();
    g.moveTo(x + r, y);
    g.lineTo(x + w - r, y);
    g.arcTo(x + w, y, x + w, y + r, r);
    g.lineTo(x + w, y + h - r);
    g.arcTo(x + w, y + h, x + w - r, y + h, r);
    g.lineTo(x + r, y + h);
    g.arcTo(x, y + h, x, y + h - r, r);
    g.lineTo(x, y + r);
    g.arcTo(x, y, x + r, y, r);
    g.closePath();
  }
  function circle(g, x, y, r) {
    g.beginPath();
    g.arc(x, y, Math.max(0, r), 0, TAU);
  }
  /** Text. o: {align, base, weight, font: "mono", shadow, maxW, alpha, glow} */
  function txt(g, s, x, y, size, color, o) {
    o = o || {};
    g.save();
    g.font = `${o.weight || 700} ${size}px ${o.font === "mono" ? MONO : FONT}`;
    g.textAlign = o.align || "left";
    g.textBaseline = o.base || "alphabetic";
    if (o.alpha != null) g.globalAlpha *= o.alpha;
    if (o.glow) {
      g.shadowColor = o.glow;
      g.shadowBlur = o.glowBlur || size * 0.45;
    } else if (o.shadow !== false) {
      g.shadowColor = "rgba(0,0,0,.55)";
      g.shadowBlur = size * 0.12;
      g.shadowOffsetY = Math.max(1, size * 0.05);
    }
    g.fillStyle = color;
    if (o.maxW) g.fillText(String(s), x, y, o.maxW);
    else g.fillText(String(s), x, y);
    g.restore();
  }
  function measure(g, s, size, o) {
    g.save();
    g.font = `${(o && o.weight) || 700} ${size}px ${o && o.font === "mono" ? MONO : FONT}`;
    const w = g.measureText(String(s)).width;
    g.restore();
    return num(w, String(s).length * size * 0.55);
  }
  /** A rounded pill with text; returns its width. */
  function pill(g, s, x, y, size, bg, fg, o) {
    o = o || {};
    const padX = size * 0.6;
    const w = measure(g, s, size, o) + padX * 2;
    const h = size * 1.6;
    const x0 = o.align === "center" ? x - w / 2 : o.align === "right" ? x - w : x;
    rr(g, x0, y - h / 2, w, h, h / 2);
    g.fillStyle = bg;
    g.fill();
    if (o.stroke) {
      g.lineWidth = 2;
      g.strokeStyle = o.stroke;
      g.stroke();
    }
    txt(g, s, x0 + w / 2, y + size * 0.36, size, fg, { align: "center", shadow: false, weight: o.weight || 750, font: o.font });
    return w;
  }
  /** A countdown ring: frac of the circle left, the seconds in the middle. */
  function ring(g, x, y, r, frac, color, label, o) {
    o = o || {};
    g.save();
    circle(g, x, y, r);
    g.fillStyle = "rgba(0,0,0,.45)";
    g.fill();
    g.lineWidth = o.width || Math.max(6, r * 0.14);
    g.strokeStyle = "rgba(255,255,255,.10)";
    g.stroke();
    g.beginPath();
    g.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + TAU * clamp(frac, 0, 1));
    g.strokeStyle = color;
    g.lineCap = "round";
    g.shadowColor = color;
    g.shadowBlur = 16;
    g.stroke();
    g.restore();
    if (label != null) txt(g, label, x, y + r * 0.2, r * 0.62, INK1, { align: "center", font: "mono", weight: 700 });
  }

  // suits drawn as paths (no font dependence)
  function suitPath(g, suit, cx, cy, s) {
    g.beginPath();
    if (suit === "D") {
      g.moveTo(cx, cy - s * 0.55);
      g.quadraticCurveTo(cx + s * 0.18, cy - s * 0.2, cx + s * 0.42, cy);
      g.quadraticCurveTo(cx + s * 0.18, cy + s * 0.2, cx, cy + s * 0.55);
      g.quadraticCurveTo(cx - s * 0.18, cy + s * 0.2, cx - s * 0.42, cy);
      g.quadraticCurveTo(cx - s * 0.18, cy - s * 0.2, cx, cy - s * 0.55);
    } else if (suit === "H") {
      g.moveTo(cx, cy + s * 0.5);
      g.bezierCurveTo(cx - s * 0.75, cy - s * 0.05, cx - s * 0.45, cy - s * 0.65, cx, cy - s * 0.28);
      g.bezierCurveTo(cx + s * 0.45, cy - s * 0.65, cx + s * 0.75, cy - s * 0.05, cx, cy + s * 0.5);
    } else if (suit === "S") {
      g.moveTo(cx, cy - s * 0.55);
      g.bezierCurveTo(cx + s * 0.75, cy - s * 0.02, cx + s * 0.45, cy + s * 0.55, cx + s * 0.04, cy + s * 0.2);
      g.lineTo(cx + s * 0.16, cy + s * 0.55);
      g.lineTo(cx - s * 0.16, cy + s * 0.55);
      g.lineTo(cx - s * 0.04, cy + s * 0.2);
      g.bezierCurveTo(cx - s * 0.45, cy + s * 0.55, cx - s * 0.75, cy - s * 0.02, cx, cy - s * 0.55);
    } else {
      const r = s * 0.2;
      g.arc(cx, cy - s * 0.24, r, 0, TAU);
      g.moveTo(cx - s * 0.2 + r, cy + s * 0.06);
      g.arc(cx - s * 0.22, cy + s * 0.06, r, 0, TAU);
      g.moveTo(cx + s * 0.22 + r, cy + s * 0.06);
      g.arc(cx + s * 0.22, cy + s * 0.06, r, 0, TAU);
      g.moveTo(cx + s * 0.05, cy);
      g.lineTo(cx + s * 0.16, cy + s * 0.55);
      g.lineTo(cx - s * 0.16, cy + s * 0.55);
      g.lineTo(cx - s * 0.05, cy);
    }
    g.closePath();
  }

  const cardCache = new Map();
  function cardImage(code, w, h, k, back) {
    const key = `${code}|${w}|${h}|${k}|${back || ""}`;
    let im = cardCache.get(key);
    if (im) return im;
    if (cardCache.size > 400) cardCache.clear();
    const m = makeCanvas(w + 8, h + 8, k);
    const g = m.g;
    g.translate(4, 4);
    const r = w * 0.09;
    g.save();
    g.shadowColor = "rgba(0,0,0,.45)";
    g.shadowBlur = 6;
    g.shadowOffsetY = 2;
    rr(g, 0, 0, w, h, r);
    g.fillStyle = back ? back : "#fbf8f1";
    g.fill();
    g.restore();
    const c = back ? null : parseCard(code);
    if (back) {
      // the back: a theme-coloured lattice inside a white border
      rr(g, w * 0.07, h * 0.05, w * 0.86, h * 0.9, r * 0.6);
      g.fillStyle = shade(back, 0.7);
      g.fill();
      g.save();
      g.clip();
      g.strokeStyle = rgba("#ffffff", 0.22);
      g.lineWidth = Math.max(1, w * 0.02);
      for (let i = -h; i < w + h; i += w * 0.14) {
        g.beginPath();
        g.moveTo(i, 0);
        g.lineTo(i + h, h);
        g.moveTo(i + h, 0);
        g.lineTo(i, h);
        g.stroke();
      }
      g.restore();
      rr(g, w * 0.07, h * 0.05, w * 0.86, h * 0.9, r * 0.6);
      g.lineWidth = Math.max(1.5, w * 0.025);
      g.strokeStyle = "#f6f0e0";
      g.stroke();
      circle(g, w / 2, h / 2, w * 0.16);
      g.fillStyle = "#f6f0e0";
      g.fill();
      circle(g, w / 2, h / 2, w * 0.1);
      g.fillStyle = back;
      g.fill();
    } else if (c) {
      const ink = c.red ? "#d0172c" : "#15151c";
      const rs = w * (c.rank === "10" ? 0.27 : 0.3);
      txt(g, c.rank, w * 0.08, h * 0.04 + rs, rs, ink, { shadow: false, weight: 800, align: "left" });
      g.fillStyle = ink;
      suitPath(g, c.suit, w * 0.17, h * 0.04 + rs * 1.55, w * 0.2);
      g.fill();
      g.save();
      g.translate(w, h);
      g.rotate(Math.PI);
      txt(g, c.rank, w * 0.08, h * 0.04 + rs, rs, ink, { shadow: false, weight: 800 });
      g.fillStyle = ink;
      suitPath(g, c.suit, w * 0.17, h * 0.04 + rs * 1.55, w * 0.2);
      g.fill();
      g.restore();
      if ("JQK".includes(c.rank)) {
        rr(g, w * 0.26, h * 0.2, w * 0.48, h * 0.6, w * 0.05);
        g.fillStyle = c.red ? "#fde6e6" : "#e7e9f3";
        g.fill();
        g.lineWidth = Math.max(1, w * 0.02);
        g.strokeStyle = "#c9a24a";
        g.stroke();
        txt(g, c.rank, w / 2, h * 0.55, w * 0.36, ink, { align: "center", shadow: false, weight: 800 });
        g.fillStyle = "#c9a24a";
        suitPath(g, c.suit, w / 2, h * 0.68, w * 0.16);
        g.fill();
      } else {
        g.fillStyle = ink;
        suitPath(g, c.suit, w / 2, h / 2 + h * 0.04, w * (c.rank === "A" ? 0.62 : 0.44));
        g.fill();
      }
    }
    g.lineWidth = 1;
    rr(g, 0.5, 0.5, w - 1, h - 1, r);
    g.strokeStyle = "rgba(0,0,0,.18)";
    g.stroke();
    im = m.c;
    cardCache.set(key, im);
    return im;
  }

  /**
   * A card centred at (x, y). o: {down, back, rot, flip (0..1: 0 = back, 1 = face), alpha, glow, dim}.
   * `flip` animates a turn: the card narrows, swaps sides, widens again.
   */
  function drawCard(S, g, code, x, y, w, h, o) {
    o = o || {};
    const back = o.back || shade(S.th.accent_deep === CLASSIC.accent_deep ? "#8f1c2c" : S.th.felt3, 1.25);
    let face = !o.down && parseCard(code) != null;
    let sx = 1;
    if (o.flip != null && face) {
      const f = clamp(o.flip, 0, 1);
      sx = Math.abs(Math.cos(f * Math.PI));
      if (f < 0.5) face = false;
    }
    const im = face ? cardImage(code, w, h, S.k, null) : cardImage("back", w, h, S.k, back);
    g.save();
    g.translate(x, y);
    if (o.rot) g.rotate(o.rot);
    if (o.alpha != null) g.globalAlpha *= o.alpha;
    g.scale(Math.max(0.02, sx), 1);
    if (o.glow) {
      g.shadowColor = o.glow;
      g.shadowBlur = 28;
    }
    g.drawImage(im, -w / 2 - 4, -h / 2 - 4, w + 8, h + 8);
    if (o.dim) {
      rr(g, -w / 2, -h / 2, w, h, w * 0.09);
      g.fillStyle = `rgba(0,0,0,${o.dim})`;
      g.fill();
    }
    g.restore();
  }

  /** An empty card spot printed on the felt. */
  function cardSlot(g, x, y, w, h, color) {
    rr(g, x - w / 2, y - h / 2, w, h, w * 0.09);
    g.setLineDash([8, 6]);
    g.lineWidth = 2;
    g.strokeStyle = color;
    g.stroke();
    g.setLineDash([]);
  }

  /** Where an appearing card is: flies from (fx, fy) to its spot while it turns over. */
  function cardFly(S, key, fx, fy, x, y, t, dur) {
    const t0 = S.seen.get(key);
    if (t0 == null) {
      S.seen.set(key, S.firstIngest ? -1e9 : t);
      return { x: S.firstIngest ? x : fx, y: S.firstIngest ? y : fy, flip: S.firstIngest ? 1 : 0, rot: 0 };
    }
    const u = clamp((t - t0) / (dur || 0.55), 0, 1);
    const e = easeOut(u);
    return { x: lerp(fx, x, e), y: lerp(fy, y, e) - Math.sin(u * Math.PI) * 40, flip: clamp((u - 0.35) / 0.65, 0, 1), rot: (1 - e) * -0.5 };
  }

  // chips: a casino chip in the player's colour with white edge inserts
  function chip(g, x, y, r, color, label, o) {
    o = o || {};
    g.save();
    if (o.alpha != null) g.globalAlpha *= o.alpha;
    g.shadowColor = "rgba(0,0,0,.55)";
    g.shadowBlur = r * 0.35;
    g.shadowOffsetY = r * 0.12;
    circle(g, x, y, r);
    g.fillStyle = color;
    g.fill();
    g.restore();
    g.save();
    if (o.alpha != null) g.globalAlpha *= o.alpha;
    g.lineWidth = r * 0.22;
    g.strokeStyle = "rgba(255,255,255,.92)";
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * TAU + 0.26;
      g.beginPath();
      g.arc(x, y, r * 0.86, a, a + 0.42);
      g.stroke();
    }
    circle(g, x, y, r * 0.62);
    g.fillStyle = shade(color, 0.82);
    g.fill();
    g.lineWidth = Math.max(1, r * 0.06);
    g.setLineDash([r * 0.16, r * 0.12]);
    g.strokeStyle = "rgba(255,255,255,.65)";
    circle(g, x, y, r * 0.55);
    g.stroke();
    g.setLineDash([]);
    if (o.glow) {
      g.shadowColor = o.glow;
      g.shadowBlur = r;
      circle(g, x, y, r * 1.02);
      g.lineWidth = 3;
      g.strokeStyle = o.glow;
      g.stroke();
    }
    g.restore();
    if (label != null && label !== "") {
      const [rr2, gg, bb] = hexRgb(color);
      const light = rr2 * 0.3 + gg * 0.59 + bb * 0.11 > 150;
      const s = String(label);
      const size = r * (s.length >= 4 ? 0.5 : s.length === 3 ? 0.6 : 0.72);
      txt(g, s, x, y + size * 0.36, size, light ? "#141414" : "#ffffff", { align: "center", font: "mono", weight: 800, shadow: false, alpha: o.alpha });
    }
  }
  const shortAmt = (v) => (v >= 1e6 ? `${Math.round(v / 1e5) / 10}M` : v >= 1e4 ? `${Math.round(v / 100) / 10}K` : String(v));

  /**
   * Everyone's chips on one spot: one chip per player in their colour, fanned, the amount on each and a stack height
   * that grows with the amount. New chips drop in. o: {r, sweep (0..1 → slides to `to`, fades), glow, to: [x, y]}.
   */
  function spotChips(S, g, spot, entries, x, y, t, o) {
    o = o || {};
    const r = o.r || 22;
    const list = arr(entries);
    const n = list.length;
    list.forEach((e, i) => {
      const key = `${spot}|${e.seat}`;
      const t0 = S.chipT.get(key);
      const u = t0 == null ? 1 : clamp((t - t0) / 0.38, 0, 1);
      let cx = x + (i - (n - 1) / 2) * r * 0.9;
      let cy = y + (i - (n - 1) / 2) * r * 0.25 - (u < 1 ? (1 - easeOut(u)) * 60 : 0);
      let alpha = u < 1 ? 0.3 + 0.7 * u : 1;
      if (o.sweep) {
        const k = easeInOut(o.sweep);
        cx = lerp(cx, (o.to || [x, y - 200])[0], k);
        cy = lerp(cy, (o.to || [x, y - 200])[1], k);
        alpha *= 1 - k;
      }
      if (alpha <= 0.01) return;
      const h = clamp(Math.ceil(Math.log2(num(e.amount, 1) + 1)), 1, 6);
      for (let j = h - 1; j > 0; j--) chip(g, cx, cy + j * r * 0.16, r, shade(e.color || "#f0f0f0", 0.75), null, { alpha });
      chip(g, cx, cy, r, e.color || "#f0f0f0", shortAmt(num(e.amount)), { alpha, glow: o.glow });
    });
  }

  /** A player's avatar: the 8×8 art (hello.avatars) in their colour on a dark disc, ringed in their colour. */
  function avatar(S, g, x, y, r, p, o) {
    o = o || {};
    const color = (p && p.color) || "#f0f0f0";
    g.save();
    if (o.alpha != null) g.globalAlpha *= o.alpha;
    circle(g, x, y, r);
    g.fillStyle = "#121218";
    g.fill();
    g.lineWidth = Math.max(3, r * 0.12);
    g.strokeStyle = color;
    if (o.glow) {
      g.shadowColor = color;
      g.shadowBlur = r * 0.8;
    }
    g.stroke();
    g.shadowBlur = 0;
    const art = obj(obj(S.ctx && S.ctx.avatars)[p && p.avatar]).px;
    if (Array.isArray(art) && art.length) {
      const n = art.length;
      const cell = (r * 1.25) / n;
      const pal = { c: color, d: shade(color, 0.55), w: "#f0f0f0", k: "#000000", y: "#ffc800", r: "#ff3c3c" };
      for (let j = 0; j < n; j++) {
        const row = String(art[j]);
        for (let i = 0; i < row.length; i++) {
          const f = pal[row[i]];
          if (!f || f === "#000000") continue;
          g.fillStyle = f;
          g.fillRect(x - (cell * n) / 2 + i * cell, y - (cell * n) / 2 + j * cell, cell + 0.3, cell + 0.3);
        }
      }
    } else {
      const name = String((p && p.name) || "?");
      txt(g, name.slice(0, 1).toUpperCase(), x, y + r * 0.36, r * 1.0, color, { align: "center", weight: 800, shadow: false });
    }
    g.restore();
  }

  // felt grain (a small noise tile, one per page)
  let grainTile = null;
  function grain(g) {
    if (!grainTile) {
      const m = makeCanvas(96, 96, 1);
      let s = 7;
      for (let i = 0; i < 900; i++) {
        s = (s * 16807) % 2147483647;
        const x = s % 96;
        s = (s * 16807) % 2147483647;
        const y = s % 96;
        m.g.fillStyle = i % 3 ? "rgba(255,255,255,.035)" : "rgba(0,0,0,.08)";
        m.g.fillRect(x, y, 1.4, 1.4);
      }
      grainTile = m.c;
    }
    const p = g.createPattern && g.createPattern(grainTile, "repeat");
    return p || "rgba(0,0,0,0)";
  }

  /** Fill the current path with the theme's felt (radial light from (cx, cy)), grain on top. */
  function feltFill(g, th, cx, cy, rad) {
    const gr = g.createRadialGradient(cx, cy, 0, cx, cy, rad);
    gr.addColorStop(0, shade(th.felt, 1.12));
    gr.addColorStop(0.55, th.felt);
    gr.addColorStop(1, th.felt3);
    g.fillStyle = gr;
    g.fill();
    g.fillStyle = grain(g);
    g.fill();
  }

  /** The table's padded rail around the current path. */
  function railStroke(g, th, width) {
    g.save();
    g.lineWidth = width;
    g.strokeStyle = "#2a1a10";
    g.shadowColor = "rgba(0,0,0,.6)";
    g.shadowBlur = 24;
    g.stroke();
    g.restore();
    g.save();
    g.lineWidth = width * 0.7;
    g.strokeStyle = "#4a2d1a";
    g.stroke();
    g.lineWidth = 2;
    g.strokeStyle = rgba(th.accent, 0.55);
    g.stroke();
    g.restore();
  }

  /** A box printed on the felt (betting area): soft fill, accent outline, optional colour band. */
  function feltBox(g, th, x, y, w, h, o) {
    o = o || {};
    rr(g, x, y, w, h, o.r == null ? 18 : o.r);
    g.fillStyle = o.fill || "rgba(0,0,0,.16)";
    g.fill();
    g.lineWidth = o.lw || 3;
    g.strokeStyle = o.stroke || rgba(th.accent, 0.7);
    g.stroke();
  }

  /** A glow around a rounded box (winning area). */
  function glowBox(g, x, y, w, h, color, k, r) {
    g.save();
    g.shadowColor = color;
    g.shadowBlur = 40 * k;
    g.lineWidth = 5;
    g.strokeStyle = rgba(color, 0.4 + 0.6 * k);
    rr(g, x, y, w, h, r == null ? 18 : r);
    g.stroke();
    g.fillStyle = rgba(color, 0.12 * k);
    g.fill();
    g.restore();
  }

  // ================================================================================================ the scene shell
  function seatKey(s) {
    return s === "host" ? 0 : num(Number(s), 99);
  }

  /** Who is at the table, from status.players: online first, then by seat. */
  function tablePlayers(st) {
    return arr(st.players)
      .filter((p) => p && (p.online || num(p.staked) > 0))
      .slice()
      .sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0) || seatKey(a.seat) - seatKey(b.seat));
  }

  function ingest(S, ctx) {
    S.ctx = ctx;
    const st = obj(ctx.status);
    const t = typeof ctx.stateAt === "number" && ctx.stateAt > 0 ? ctx.stateAt : nowOf(ctx);
    S.st = st;
    S.th = Object.assign({}, CLASSIC, obj(ctx.theme && Object.keys(ctx.theme).length ? ctx.theme : obj(st.table_theme).css));
    S.preview = st.view != null && st.view !== "live";
    S.clk.observe(st, t);
    S.players = tablePlayers(st);
    S.bySeat = new Map();
    for (const p of arr(st.players)) if (p) S.bySeat.set(String(p.seat), p);
    // chips that just landed (drop-in animation)
    const sb = obj(st.spot_bets);
    const seenNow = new Set();
    for (const spot of Object.keys(sb)) {
      for (const e of arr(sb[spot])) {
        const key = `${spot}|${e.seat}`;
        seenNow.add(key);
        const prev = S.chipAmt.get(key);
        if (prev == null || num(e.amount) > prev) S.chipT.set(key, S.firstIngest ? -1e9 : t);
        S.chipAmt.set(key, num(e.amount));
      }
    }
    for (const k of [...S.chipAmt.keys()]) if (!seenNow.has(k)) {
      S.chipAmt.delete(k);
      S.chipT.delete(k);
    }
    if (S.round !== st.round) {
      if (S.round != null) S.seen.clear();
      S.round = st.round;
    }
    if (S.def.ingest) S.def.ingest(S, st, t);
    S.firstIngest = false;
  }

  function nowOf(ctx) {
    try {
      if (ctx && typeof ctx.now === "function") return ctx.now();
    } catch (e) {
      /* fall through */
    }
    return (typeof performance !== "undefined" ? performance.now() : Date.now()) / 1000;
  }

  /** The colour of a seat (status.players, then the lobby / defaults). */
  function seatColor(S, seat) {
    const p = S.bySeat.get(String(seat));
    if (p && p.color) return p.color;
    try {
      if (S.ctx && typeof S.ctx.seatColor === "function" && typeof seat === "number") return S.ctx.seatColor(seat);
    } catch (e) {
      /* ignore */
    }
    return seat === "host" ? "#00c8ff" : "#f0f0f0";
  }
  const playerOf = (S, seat) => S.bySeat.get(String(seat)) || { seat, name: `P${seat}`, color: seatColor(S, seat) };

  function winners(S) {
    const r = obj(S.st.result);
    return arr(r.winners).map((w) => ({ ...w, color: seatColor(S, w.seat), avatar: (playerOf(S, w.seat) || {}).avatar }));
  }

  function makeScene(def) {
    let S = null;
    const scene = {
      id: def.id,
      match: (app) => app === def.app,
      mount(root, ctx) {
        const k = clamp(num(TV && TV.pixelRatio, 1), 1, 1.5);
        root.style.position = "absolute";
        const cv = document.createElement("canvas");
        cv.width = Math.round(SW * k);
        cv.height = Math.round(SH * k);
        cv.style.position = "absolute";
        cv.style.left = "0px";
        cv.style.top = "0px";
        cv.style.width = `${SW}px`;
        cv.style.height = `${SH}px`;
        root.appendChild(cv);
        const pcv = document.createElement("canvas");
        pcv.style.position = "absolute";
        pcv.style.left = `${PANEL_X}px`;
        pcv.style.top = `${PANEL_Y}px`;
        pcv.style.width = `${PANEL_SIZE}px`;
        pcv.style.height = `${PANEL_SIZE}px`;
        pcv.style.borderRadius = "6px";
        root.appendChild(pcv);
        S = {
          def, root, cv, pcv, k, g: cv.getContext("2d"), ctx, st: {}, th: Object.assign({}, CLASSIC),
          clk: new PhaseTracker(), players: [], bySeat: new Map(), chipT: new Map(), chipAmt: new Map(),
          seen: new Map(), fx: {}, bg: null, round: undefined, firstIngest: true, alive: true, raf: 0, t: 0, err: null,
        }; // fmt: skip
        if (def.init) def.init(S);
        ingest(S, ctx);
        const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (f) => setTimeout(() => f(), 16);
        const step = () => {
          if (!S || !S.alive) return;
          if (!(typeof document !== "undefined" && document.hidden)) {
            try {
              paint(S, nowOf(S.ctx));
            } catch (e) {
              if (!S.err) console.error("DeskDot TV casino scene:", def.id, e);
              S.err = e;
            }
          }
          S.raf = raf(step);
        };
        S.raf = raf(step);
      },
      update(ctx) {
        if (S) ingest(S, ctx);
      },
      frame(ctx) {
        if (!S) return;
        S.ctx = ctx;
        if (typeof ctx.drawPanel === "function") ctx.drawPanel(S.pcv, { pitch: PANEL_PITCH, glow: 0.55, round: true });
      },
      resize(ctx) {
        if (!S) return;
        const k = clamp(num(TV && TV.pixelRatio, 1), 1, 1.5);
        if (Math.abs(k - S.k) < 1e-3) return;
        S.k = k;
        S.cv.width = Math.round(SW * k);
        S.cv.height = Math.round(SH * k);
        S.bg = null;
        cardCache.clear();
        if (ctx && ctx.panel) scene.frame(ctx);
      },
      unmount() {
        if (!S) return;
        S.alive = false;
        if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(S.raf);
        S = null;
      },
      // tests
      _state: () => S,
      _paint: (t) => S && paint(S, t),
    };
    return scene;
  }

  function background(S) {
    const key = `${JSON.stringify(S.th)}|${S.k}|${S.def.bgKey ? S.def.bgKey(S) : ""}`;
    if (S.bg && S.bg.key === key) return S.bg.c;
    const m = makeCanvas(SW, SH, S.k);
    const g = m.g;
    const th = S.th;
    const gr = g.createLinearGradient(0, 0, 0, SH);
    gr.addColorStop(0, th.wing);
    gr.addColorStop(0.6, th.wing2);
    gr.addColorStop(1, th.wing3);
    g.fillStyle = gr;
    g.fillRect(0, 0, SW, SH);
    const vg = g.createRadialGradient(760, 480, 200, 760, 480, 1100);
    vg.addColorStop(0, "rgba(255,255,255,.04)");
    vg.addColorStop(1, "rgba(0,0,0,.35)");
    g.fillStyle = vg;
    g.fillRect(0, 0, RAIL_X, SH);
    S.def.bg(S, g);
    railBackground(S, g);
    S.bg = { key, c: m.c };
    return m.c;
  }

  function paint(S, t) {
    S.t = t;
    const g = S.g;
    g.setTransform(S.k, 0, 0, S.k, 0, 0);
    g.globalAlpha = 1;
    g.globalCompositeOperation = "source-over";
    g.drawImage(background(S), 0, 0, SW, SH);
    S.def.draw(S, g, t);
    drawRail(S, g, t);
    if (S.st.paused) paused(S, g, t);
    if (S.preview) previewNote(S, g);
  }

  function paused(S, g) {
    g.save();
    g.fillStyle = "rgba(0,0,0,.5)";
    g.fillRect(0, 0, RAIL_X, SH);
    g.restore();
    rr(g, 470, 420, 600, 140, 30);
    g.fillStyle = "rgba(12,12,16,.92)";
    g.fill();
    g.lineWidth = 3;
    g.strokeStyle = S.th.accent;
    g.stroke();
    txt(g, "PAUSED", 770, 500, 72, S.th.accent, { align: "center", weight: 800 });
    txt(g, "The host paused the table", 770, 540, 26, INK2, { align: "center", weight: 600 });
  }

  function previewNote(S, g) {
    pill(g, "STUDIO PREVIEW — the live table shows when the panel's view is “Live table”", 770, 950, 22, "rgba(0,0,0,.7)", INK1, { align: "center", stroke: rgba(S.th.accent, 0.5) });
  }

  // ------------------------------------------------------------------------------------------------ the rail
  function railBackground(S, g) {
    const th = S.th;
    rr(g, RAIL_X, 14, RAIL_W - 16, SH - 28, 22);
    const gr = g.createLinearGradient(0, 0, 0, SH);
    gr.addColorStop(0, "rgba(0,0,0,.45)");
    gr.addColorStop(1, "rgba(0,0,0,.6)");
    g.fillStyle = gr;
    g.fill();
    g.lineWidth = 2;
    g.strokeStyle = rgba(th.accent, 0.22);
    g.stroke();
    txt(g, "AT THE TABLE", RAIL_X + 22, 54, 22, th.accent, { weight: 800, shadow: false });
    txt(g, "RECENT", RAIL_X + 22, 586, 18, INK3, { weight: 800, shadow: false });
    // the panel's housing
    rr(g, PANEL_X - 14, PANEL_Y - 14, PANEL_SIZE + 28, PANEL_SIZE + 28, 16);
    const bz = g.createLinearGradient(0, PANEL_Y - 14, 0, PANEL_Y + PANEL_SIZE + 14);
    bz.addColorStop(0, "#2b2b33");
    bz.addColorStop(1, "#111115");
    g.fillStyle = bz;
    g.fill();
    g.lineWidth = 1.5;
    g.strokeStyle = "rgba(255,255,255,.12)";
    g.stroke();
    rr(g, PANEL_X - 3, PANEL_Y - 3, PANEL_SIZE + 6, PANEL_SIZE + 6, 6);
    g.fillStyle = "#030304";
    g.fill();
  }

  function railInfoDefault(S, p) {
    const st = S.st;
    const ph = st.phase;
    if (ph === "result") {
      const w = winners(S).find((x) => String(x.seat) === String(p.seat));
      if (w) return { text: `WON ${signed(S, num(w.net))}`, color: OK };
    }
    let on = 0;
    for (const list of Object.values(obj(st.spot_bets))) for (const e of arr(list)) if (String(e.seat) === String(p.seat)) on += num(e.amount);
    if (on > 0) {
      const done = arr(st.done).some((s) => String(s) === String(p.seat));
      return { text: `${done ? "READY · " : ""}BET ${fmt(S, on)}`, color: done ? OK : S.th.accent_hi };
    }
    return { text: p.online ? "" : "AWAY", color: INK3 };
  }

  function drawRail(S, g, t) {
    const th = S.th;
    const list = S.players;
    const turn = S.def.turnSeat ? S.def.turnSeat(S) : null;
    txt(g, `${list.length}`, RAIL_X + RAIL_W - 36, 54, 22, INK3, { align: "right", weight: 800, shadow: false });
    const rows = Math.min(list.length, 8);
    const rowH = 62;
    if (!list.length) {
      txt(g, "Nobody yet — scan the code", RAIL_X + 22, 104, 24, INK3, { weight: 600 });
      txt(g, "at the top to take a seat", RAIL_X + 22, 136, 24, INK3, { weight: 600 });
    }
    for (let i = 0; i < rows; i++) {
      const p = list[i];
      const y = 76 + i * rowH;
      const hot = turn != null && String(turn) === String(p.seat);
      if (hot) {
        const k = 0.5 + 0.5 * Math.sin(t * 5);
        rr(g, RAIL_X + 8, y - 2, RAIL_W - 32, rowH - 6, 14);
        g.fillStyle = rgba(th.accent, 0.12 + 0.1 * k);
        g.fill();
        g.lineWidth = 2;
        g.strokeStyle = rgba(th.accent, 0.6 + 0.4 * k);
        g.stroke();
      }
      const alpha = p.online ? 1 : 0.45;
      avatar(S, g, RAIL_X + 42, y + 27, 22, p, { alpha });
      txt(g, String(p.name || `P${p.seat}`), RAIL_X + 76, y + 26, 25, p.color || INK1, { weight: 750, maxW: 160, alpha });
      txt(g, fmt(S, num(p.credits)), RAIL_X + RAIL_W - 36, y + 26, 25, INK1, { align: "right", font: "mono", weight: 700, alpha });
      const info = (S.def.railInfo || railInfoDefault)(S, p) || {};
      if (info.text) txt(g, info.text, RAIL_X + 76, y + 50, 17, info.color || INK3, { weight: 800, maxW: 260, shadow: false, alpha });
      else if (num(p.net) !== 0) txt(g, `SESSION ${signed(S, num(p.net))}`, RAIL_X + 76, y + 50, 17, num(p.net) > 0 ? rgba(OK, 0.8) : INK3, { weight: 700, shadow: false, alpha });
    }
    if (list.length > rows) txt(g, `+ ${list.length - rows} more`, RAIL_X + 22, 76 + rows * rowH + 18, 20, INK3, { weight: 700 });
    // the recent results strip
    const hist = arr(S.st.history).filter((h) => h && (!S.st.game || h.game === S.st.game)).slice(-7).reverse();
    let x = RAIL_X + 22;
    hist.forEach((h, i) => {
      const lbl = String(h.label == null ? "?" : h.label);
      const w = Math.max(40, measure(g, lbl, 22, { font: "mono" }) + 18);
      if (x + w > RAIL_X + RAIL_W - 24) return;
      rr(g, x, 600, w, 44, 10);
      g.fillStyle = TONE[h.tone] || TONE.white;
      g.fill();
      if (i === 0) {
        g.lineWidth = 3;
        g.strokeStyle = th.accent;
        g.stroke();
      }
      txt(g, lbl, x + w / 2, 630, 22, "#fff", { align: "center", font: "mono", weight: 800, alpha: i === 0 ? 1 : 0.8 });
      x += w + 8;
    });
    if (!hist.length) txt(g, "No rounds yet", RAIL_X + 22, 630, 20, INK3, { weight: 600 });
  }

  // ------------------------------------------------------------------------------------------------ shared headline
  /**
   * The table's headline for the phase: {title, sub, tone, ring:{frac,label}}. Games pass `custom(phase)` for their
   * own words; betting / locked / paused / idle are shared.
   */
  function headline(S, t, custom) {
    const st = S.st;
    const ph = String(st.phase || "idle");
    const th = S.th;
    const c = custom ? custom(ph) : null;
    if (c) return c;
    if (ph === "betting") {
      const left = S.clk.ends.left(t);
      const total = Object.values(obj(st.totals)).reduce((a, b) => a + num(b), 0);
      const n = arr(st.bettors).length;
      if (st.ends_in == null || left == null)
        return { title: "PLACE YOUR BETS", sub: "The countdown starts with the first chip", tone: th.accent, pulse: true };
      const span = num(obj(st.house).bet_seconds, 20);
      return {
        title: "PLACE YOUR BETS",
        sub: `${n} ${n === 1 ? "player" : "players"} in · ${fmt(S, total)} on the table`,
        tone: left <= 5 ? BAD : th.accent,
        ring: { frac: left / span, label: Math.ceil(left - 1e-6), color: left <= 5 ? BAD : th.accent },
      };
    }
    if (ph === "locked") return { title: "NO MORE BETS", sub: "Bets are locked", tone: BAD, flash: true };
    if (ph === "result") {
      const next = S.clk.next.left(t);
      const ws = winners(S);
      return {
        title: String(obj(st.result).label || "RESULT"),
        sub: ws.length ? `${ws.length} ${ws.length === 1 ? "winner" : "winners"}` : "The house wins this one",
        tone: th.accent,
        ring: next != null ? { frac: next / num(obj(st.house).result_seconds, 7), label: Math.ceil(next - 1e-6), color: INK3 } : null,
      };
    }
    if (ph === "idle") return { title: "TABLE CLOSED", sub: "Waiting for the host to open a round", tone: INK3 };
    return { title: ph.toUpperCase(), sub: "", tone: th.accent };
  }

  function drawHeadline(S, g, x, y, w, t, h, o) {
    o = o || {};
    if (!h) return;
    const size = o.size || 60;
    let alpha = 1;
    if (h.pulse) alpha = 0.65 + 0.35 * Math.sin(t * 3.4);
    if (h.flash) alpha = 0.55 + 0.45 * (Math.sin(t * 10) > 0 ? 1 : 0);
    const align = o.align || "left";
    const rx = align === "center" ? x : x + w - (o.ringR || 50);
    const tx = align === "center" ? x : x;
    txt(g, h.title, tx, y + size * 0.8, size, h.tone || INK1, { weight: 850, align, alpha, maxW: w - (h.ring && align !== "center" ? 130 : 0), glow: rgba(h.tone || INK1, 0.45) });
    if (h.sub) txt(g, h.sub, tx, y + size * 0.8 + 40, 26, INK2, { weight: 600, align, maxW: w - (h.ring && align !== "center" ? 130 : 0) });
    if (h.ring && align !== "center") ring(g, rx, y + size * 0.55, o.ringR || 50, h.ring.frac, h.ring.color || S.th.accent, h.ring.label);
  }

  /** The winners card: up to `max` winners with avatar, name and net, or "House wins". */
  function winnersCard(S, g, x, y, w, t, o) {
    o = o || {};
    const ws = winners(S);
    const max = o.max || 4;
    const k = easeOut((S.clk.since(t) - (o.delay || 0)) / 0.5);
    if (k <= 0) return;
    g.save();
    g.globalAlpha *= k;
    const h = 60 + Math.max(1, Math.min(ws.length, max)) * 54;
    rr(g, x, y, w, h, 20);
    g.fillStyle = "rgba(0,0,0,.55)";
    g.fill();
    g.lineWidth = 2;
    g.strokeStyle = rgba(S.th.accent, 0.6);
    g.stroke();
    txt(g, ws.length ? "WINNERS" : "NO WINNERS", x + 22, y + 38, 22, S.th.accent, { weight: 850, shadow: false });
    if (!ws.length) txt(g, o.empty || "The house takes the table", x + 22, y + 88, 26, INK2, { weight: 650 });
    ws.slice(0, max).forEach((wv, i) => {
      const yy = y + 62 + i * 54;
      avatar(S, g, x + 44, yy + 22, 20, wv);
      txt(g, wv.name || `P${wv.seat}`, x + 76, yy + 32, 28, wv.color, { weight: 750, maxW: w - 250 });
      txt(g, signed(S, num(wv.net)), x + w - 22, yy + 32, 30, OK, { align: "right", font: "mono", weight: 800, glow: rgba(OK, 0.5) });
    });
    if (ws.length > max) txt(g, `+ ${ws.length - max} more`, x + w - 22, y + 38, 20, INK2, { align: "right", weight: 700 });
    g.restore();
  }

  /** Chasing bulbs round a rectangle (result flourish). */
  function bulbs(g, x, y, w, h, t, color, n) {
    const per = 2 * (w + h);
    const count = n || 40;
    for (let i = 0; i < count; i++) {
      let d = (i / count) * per;
      let px;
      let py;
      if (d < w) [px, py] = [x + d, y];
      else if ((d -= w) < h) [px, py] = [x + w, y + d];
      else if ((d -= h) < w) [px, py] = [x + w - d, y + h];
      else [px, py] = [x, y + h - (d - w)];
      const on = (i + Math.floor(t * 10)) % 3 === 0;
      circle(g, px, py, on ? 6 : 4);
      g.fillStyle = on ? color : rgba(color, 0.25);
      g.fill();
    }
  }

  /** How far into the result sweep losing chips are (0..1), starting `delay` s into the result. */
  const sweepK = (S, t, delay) => (S.st.phase === "result" ? clamp((S.clk.since(t) - delay) / 0.8, 0, 1) : 0);

  // ================================================================================================ ROULETTE
  const R_CX = 382;
  const R_CY = 548;
  const R_RIM = 340;
  const R_TRACK_OUT = 300;
  const R_HEAD = 262;
  const R_NUM_IN = 222;
  const R_POCK_IN = 184;
  const R_TRACK = 281;
  const R_POCKET = 203;
  const RW = { W0: 2.3, TAU: 5.5, DRIFT: 0.32 };
  const RBALL = { W0: 6.4, TAU: 3.3 };

  function rouletteWheel(S) {
    return obj(S.st.rules).wheel === "american" ? US_WHEEL : EU_WHEEL;
  }

  function wheelHead(S) {
    const wheel = rouletteWheel(S);
    const key = `${wheel.length}|${S.k}`;
    if (S.fx.head && S.fx.head.key === key) return S.fx.head.c;
    const D = R_HEAD * 2 + 8;
    const m = makeCanvas(D, D, S.k);
    const g = m.g;
    g.translate(D / 2, D / 2);
    const N = wheel.length;
    const seg = TAU / N;
    for (let i = 0; i < N; i++) {
      const n = wheel[i];
      const a0 = i * seg - seg / 2 - Math.PI / 2;
      const base = { red: "#c3122c", black: "#17171d", green: "#0b8a43" }[rColor(n)];
      g.beginPath();
      g.arc(0, 0, R_HEAD, a0, a0 + seg);
      g.arc(0, 0, R_NUM_IN, a0 + seg, a0, true);
      g.closePath();
      g.fillStyle = base;
      g.fill();
      g.beginPath();
      g.arc(0, 0, R_NUM_IN, a0, a0 + seg);
      g.arc(0, 0, R_POCK_IN, a0 + seg, a0, true);
      g.closePath();
      const pg = g.createRadialGradient(0, 0, R_POCK_IN, 0, 0, R_NUM_IN);
      pg.addColorStop(0, shade(base, 0.45));
      pg.addColorStop(1, shade(base, 0.8));
      g.fillStyle = pg;
      g.fill();
      g.save();
      g.rotate(i * seg);
      txt(g, rLabel(n), 0, -R_HEAD + 30, 23, "#ffffff", { align: "center", weight: 800, shadow: false });
      g.restore();
    }
    g.strokeStyle = "#d9b45a";
    for (let i = 0; i < N; i++) {
      const a = i * seg - seg / 2 - Math.PI / 2;
      g.lineWidth = 2.2;
      g.beginPath();
      g.moveTo(Math.cos(a) * R_POCK_IN, Math.sin(a) * R_POCK_IN);
      g.lineTo(Math.cos(a) * R_HEAD, Math.sin(a) * R_HEAD);
      g.stroke();
    }
    for (const r of [R_POCK_IN, R_NUM_IN, R_HEAD]) {
      circle(g, 0, 0, r);
      g.lineWidth = r === R_NUM_IN ? 2 : 3;
      g.stroke();
    }
    // the cone and the turret
    circle(g, 0, 0, R_POCK_IN - 2);
    const cg = g.createRadialGradient(-40, -50, 10, 0, 0, R_POCK_IN);
    cg.addColorStop(0, "#8a5a32");
    cg.addColorStop(0.6, "#5a3518");
    cg.addColorStop(1, "#2a160a");
    g.fillStyle = cg;
    g.fill();
    for (const r of [140, 96]) {
      circle(g, 0, 0, r);
      g.lineWidth = 2;
      g.strokeStyle = "rgba(255,220,150,.25)";
      g.stroke();
    }
    g.fillStyle = "#e6c46a";
    g.strokeStyle = "#8a6a1a";
    for (let i = 0; i < 4; i++) {
      g.save();
      g.rotate((i * Math.PI) / 2);
      rr(g, -7, -118, 14, 118, 7);
      g.fill();
      circle(g, 0, -118, 15);
      g.fill();
      g.lineWidth = 2;
      g.stroke();
      g.restore();
    }
    circle(g, 0, 0, 34);
    const tg = g.createRadialGradient(-10, -12, 2, 0, 0, 34);
    tg.addColorStop(0, "#fff3c4");
    tg.addColorStop(1, "#b38a2a");
    g.fillStyle = tg;
    g.fill();
    S.fx.head = { key, c: m.c };
    return m.c;
  }

  function rouletteWheelRot(fx, t) {
    const spin = fx.lockAt != null ? travelExp(t - fx.lockAt, RW.W0, RW.TAU) : 0;
    return -(RW.DRIFT * t + fx.wOff + spin);
  }

  function rouletteBall(S, t) {
    const fx = S.fx;
    const N = rouletteWheel(S).length;
    const seg = TAU / N;
    const wr = rouletteWheelRot(fx, t);
    if (fx.pending != null) {
      // the outcome is public: settle the ball into its pocket from wherever it is now
      const cur = fx.spinning ? rouletteFreeBall(fx, t) : null;
      const target = fx.pending * seg;
      if (cur) {
        const rel0 = cur.a - wr;
        const d = wrapPi(target - rel0);
        fx.land = { t0: t, rel0, d, T: 1.0 + (0.9 * Math.abs(d)) / Math.PI, pocket: fx.pending, r0: cur.r };
      } else {
        fx.landed = fx.pending;
        fx.landedAt = t;
      }
      fx.pending = null;
      fx.spinning = false;
    }
    if (fx.land) {
      const L = fx.land;
      const u = clamp((t - L.t0) / L.T, 0, 1);
      if (u >= 1) {
        fx.landed = L.pocket;
        fx.landedAt = t;
        fx.land = null;
      } else {
        const rel = L.rel0 + L.d * easeOut(u);
        const hop = (1 - u) * Math.abs(Math.sin(u * Math.PI * 3.2));
        return { a: wr + rel, r: lerp(L.r0, R_POCKET, easeOut(u * 1.6)) + 18 * hop, landing: true };
      }
    }
    if (fx.spinning) return rouletteFreeBall(fx, t);
    if (fx.landed != null) return { a: wr + fx.landed * seg, r: R_POCKET, rest: true };
    return null;
  }

  function rouletteFreeBall(fx, t) {
    const x = Math.max(0, t - fx.lockAt);
    const a = fx.launch + travelExp(x, RBALL.W0, RBALL.TAU);
    let r = R_TRACK + Math.sin(x * 13) * 1.2;
    if (x > 6.2) {
      const k = clamp((x - 6.2) / 1.0, 0, 1);
      r = lerp(R_TRACK, R_POCKET + 16, easeIn(k)) + (k >= 1 ? 9 * Math.abs(Math.sin(x * 8)) : 0);
    }
    return { a, r };
  }

  const roulette = makeScene({
    id: "casino-roulette",
    app: "casino_roulette",
    init(S) {
      S.fx = { lockAt: null, lockRound: null, wOff: 0, launch: 0, spinning: false, land: null, landed: null, pending: null };
    },
    bgKey: (S) => (obj(S.st.rules).wheel === "american" ? "us" : "eu"),
    ingest(S, st, t) {
      const fx = S.fx;
      const ph = st.phase;
      if (ph === "locked" || ph === "spinning") {
        const est = lockTime(S.clk, 7.5);
        if (fx.lockRound !== st.round) {
          if (fx.lockAt != null) fx.wOff += travelExp(t - fx.lockAt, RW.W0, RW.TAU);
          fx.lockAt = est;
          fx.lockRound = st.round;
          fx.launch = hash01(`ball${st.round}`) * TAU;
          fx.spinning = true;
          fx.land = null;
          fx.landed = null;
          fx.pending = null;
        } else if (Math.abs(est - fx.lockAt) > 1.5) fx.lockAt = est;
        else fx.lockAt += (est - fx.lockAt) * 0.35;
      }
      const out = obj(obj(st.result).outcome);
      if (ph === "result" && typeof out.pocket === "number" && fx.resultRound !== st.round) {
        fx.resultRound = st.round;
        fx.pending = out.pocket;
      }
      if (fx.landed == null && !fx.spinning && fx.pending == null && fx.land == null) {
        const last = arr(st.history).filter((h) => h.game === "roulette").slice(-1)[0];
        const lo = obj(last && last.outcome);
        if (typeof lo.pocket === "number" && lo.pocket < rouletteWheel(S).length) fx.landed = lo.pocket;
      }
    },
    bg(S, g) {
      const th = S.th;
      // the table
      rr(g, 18, 18, RAIL_X - 34, SH - 36, 60);
      feltFill(g, th, 900, 480, 1100);
      railStroke(g, th, 18);
      // the bowl
      circle(g, R_CX, R_CY, R_RIM + 10);
      g.fillStyle = "rgba(0,0,0,.45)";
      g.fill();
      circle(g, R_CX, R_CY, R_RIM);
      const wg = g.createRadialGradient(R_CX - 80, R_CY - 120, 40, R_CX, R_CY, R_RIM);
      wg.addColorStop(0, "#7a4a24");
      wg.addColorStop(0.85, "#4a2a12");
      wg.addColorStop(1, "#2a160a");
      g.fillStyle = wg;
      g.fill();
      circle(g, R_CX, R_CY, R_TRACK_OUT + 4);
      g.lineWidth = 6;
      g.strokeStyle = shade(th.accent, 0.8);
      g.stroke();
      circle(g, R_CX, R_CY, R_TRACK_OUT);
      const tg = g.createRadialGradient(R_CX, R_CY, R_HEAD, R_CX, R_CY, R_TRACK_OUT);
      tg.addColorStop(0, "#1a110b");
      tg.addColorStop(0.7, "#3b2616");
      tg.addColorStop(1, "#22150c");
      g.fillStyle = tg;
      g.fill();
      for (let i = 0; i < 8; i++) {
        const a = (i / 8) * TAU + 0.2;
        const x = R_CX + Math.sin(a) * 272;
        const y = R_CY - Math.cos(a) * 272;
        g.save();
        g.translate(x, y);
        g.rotate(a);
        g.beginPath();
        g.moveTo(0, -9);
        g.lineTo(6, 0);
        g.lineTo(0, 9);
        g.lineTo(-6, 0);
        g.closePath();
        g.fillStyle = "#d9b45a";
        g.fill();
        g.restore();
      }
      txt(g, "ROULETTE", 60, 92, 44, th.accent, { weight: 850 });
      txt(g, obj(S.st.rules).wheel === "american" ? "AMERICAN · 0 AND 00" : "EUROPEAN · SINGLE ZERO", 62, 128, 22, INK2, { weight: 700 });
      // the printed layout
      const B = rouletteBoard(obj(S.st.rules).wheel === "american");
      const L = B.x0 + B.zw;
      const gold = th.accent;
      const cellFill = { red: "#a8112a", black: "#18181f", green: "#0b7a3e" };
      const zeros = B.us ? [37, 0] : [0];
      zeros.forEach((n, i) => {
        const h = (3 * B.ch) / zeros.length;
        g.beginPath();
        g.rect(B.x0, B.y0 + i * h, B.zw, h);
        g.fillStyle = cellFill.green;
        g.fill();
        txt(g, rLabel(n), B.x0 + B.zw / 2, B.y0 + i * h + h / 2 + 13, 36, "#fff", { align: "center", weight: 800 });
      });
      for (let n = 1; n <= 36; n++) {
        const q = numCell(n, B);
        g.beginPath();
        g.rect(q.x, q.y, B.cw, B.ch);
        g.fillStyle = cellFill[rColor(n)];
        g.fill();
        txt(g, String(n), q.x + B.cw / 2, q.y + B.ch / 2 + 12, 32, "#fff", { align: "center", weight: 800 });
      }
      for (let c = 1; c <= 3; c++) {
        const y = B.y0 + (3 - c) * B.ch;
        txt(g, "2:1", L + 12 * B.cw + B.colW / 2, y + B.ch / 2 + 10, 26, "#fff", { align: "center", weight: 800 });
      }
      const bottom = B.y0 + 3 * B.ch;
      ["1st 12", "2nd 12", "3rd 12"].forEach((s, i) => txt(g, s, L + (4 * i + 2) * B.cw, bottom + B.dzH / 2 + 10, 28, "#fff", { align: "center", weight: 800 }));
      EVEN_SPOTS.forEach((s, i) => {
        const cx = L + (2 * i + 1) * B.cw;
        const cy = bottom + B.dzH + B.emH / 2;
        if (s === "red" || s === "black") {
          g.beginPath();
          g.moveTo(cx, cy - 22);
          g.lineTo(cx + 34, cy);
          g.lineTo(cx, cy + 22);
          g.lineTo(cx - 34, cy);
          g.closePath();
          g.fillStyle = s === "red" ? "#c3122c" : "#101014";
          g.fill();
          g.lineWidth = 2;
          g.strokeStyle = "#fff";
          g.stroke();
        } else txt(g, EVEN_LABEL[s], cx, cy + 10, 28, "#fff", { align: "center", weight: 800 });
      });
      // the grid lines
      g.strokeStyle = gold;
      g.lineWidth = 2.5;
      g.beginPath();
      g.rect(B.x0, B.y0, B.zw + 12 * B.cw + B.colW, 3 * B.ch);
      for (let c = 0; c <= 12; c++) {
        g.moveTo(L + c * B.cw, B.y0);
        g.lineTo(L + c * B.cw, bottom);
      }
      for (let r = 1; r < 3; r++) {
        g.moveTo(L, B.y0 + r * B.ch);
        g.lineTo(L + 12 * B.cw + B.colW, B.y0 + r * B.ch);
      }
      if (B.us) {
        g.moveTo(B.x0, B.y0 + 1.5 * B.ch);
        g.lineTo(L, B.y0 + 1.5 * B.ch);
      }
      g.rect(L, bottom, 12 * B.cw, B.dzH + B.emH);
      for (let i = 1; i < 3; i++) {
        g.moveTo(L + 4 * i * B.cw, bottom);
        g.lineTo(L + 4 * i * B.cw, bottom + B.dzH);
      }
      g.moveTo(L, bottom + B.dzH);
      g.lineTo(L + 12 * B.cw, bottom + B.dzH);
      for (let i = 1; i < 6; i++) {
        g.moveTo(L + 2 * i * B.cw, bottom + B.dzH);
        g.lineTo(L + 2 * i * B.cw, bottom + B.dzH + B.emH);
      }
      g.stroke();
      txt(g, "LAST NUMBERS", B.x0, 70, 20, INK3, { weight: 800, shadow: false });
    },
    draw(S, g, t) {
      const st = S.st;
      const fx = S.fx;
      const th = S.th;
      const wheel = rouletteWheel(S);
      const N = wheel.length;
      const seg = TAU / N;
      const B = rouletteBoard(N === 38);
      // the wheel head
      const wr = rouletteWheelRot(fx, t);
      g.save();
      g.translate(R_CX, R_CY);
      g.rotate(wr);
      g.drawImage(wheelHead(S), -(R_HEAD + 4), -(R_HEAD + 4), 2 * R_HEAD + 8, 2 * R_HEAD + 8);
      g.restore();
      const sheen = g.createRadialGradient(R_CX - 110, R_CY - 140, 10, R_CX, R_CY, R_HEAD);
      sheen.addColorStop(0, "rgba(255,255,255,.16)");
      sheen.addColorStop(0.5, "rgba(255,255,255,.03)");
      sheen.addColorStop(1, "rgba(0,0,0,.18)");
      circle(g, R_CX, R_CY, R_HEAD);
      g.fillStyle = sheen;
      g.fill();
      const ball = rouletteBall(S, t);
      const showResult = st.phase === "result" && fx.landed != null && fx.land == null;
      if (showResult) {
        // the winning pocket glows
        const a = wr + fx.landed * seg - Math.PI / 2;
        g.save();
        g.beginPath();
        g.arc(R_CX, R_CY, R_HEAD + 6, a - seg / 2, a + seg / 2);
        g.arc(R_CX, R_CY, R_POCK_IN, a + seg / 2, a - seg / 2, true);
        g.closePath();
        g.lineWidth = 4;
        g.strokeStyle = "#ffffff";
        g.shadowColor = th.accent;
        g.shadowBlur = 24;
        g.stroke();
        g.restore();
      }
      if (ball) {
        const bx = R_CX + Math.sin(ball.a) * ball.r;
        const by = R_CY - Math.cos(ball.a) * ball.r;
        g.save();
        g.shadowColor = "rgba(0,0,0,.6)";
        g.shadowBlur = 8;
        g.shadowOffsetY = 3;
        circle(g, bx, by, 10.5);
        const bg = g.createRadialGradient(bx - 4, by - 4, 1, bx, by, 11);
        bg.addColorStop(0, "#ffffff");
        bg.addColorStop(1, "#b9bcc6");
        g.fillStyle = bg;
        g.fill();
        g.restore();
      }
      // the number, big, on the cone
      if (showResult) {
        const n = wheel[fx.landed];
        const k = easeOut((t - (fx.landedAt || t - 1)) / 0.4);
        const col = { red: "#d0182f", black: "#1b1b22", green: "#0e9a4c" }[rColor(n)];
        g.save();
        g.globalAlpha = k;
        circle(g, R_CX, R_CY, 116 * (0.7 + 0.3 * k));
        g.fillStyle = col;
        g.shadowColor = rgba(th.accent, 0.8);
        g.shadowBlur = 40;
        g.fill();
        g.lineWidth = 6;
        g.strokeStyle = th.accent;
        g.stroke();
        g.restore();
        txt(g, rLabel(n), R_CX, R_CY + 40, 120 * (0.7 + 0.3 * k), "#fff", { align: "center", weight: 850, alpha: k });
      }
      // last numbers
      const hist = arr(st.history).filter((h) => h.game === "roulette" && h.outcome).slice(-13).reverse();
      let hx = B.x0 + 30;
      hist.forEach((h, i) => {
        const n = num(obj(h.outcome).number);
        const r = i === 0 ? 30 : 23;
        circle(g, hx, 112, r);
        g.fillStyle = { red: "#c3122c", black: "#1b1b22", green: "#0b8a43" }[rColor(n)];
        g.fill();
        g.lineWidth = i === 0 ? 4 : 2;
        g.strokeStyle = i === 0 ? th.accent : "rgba(255,255,255,.35)";
        g.stroke();
        txt(g, rLabel(n), hx, 112 + r * 0.36, r * 0.95, "#fff", { align: "center", weight: 800, shadow: false });
        hx += r + (i === 0 ? 36 : 30);
      });
      // the headline
      const head = headline(S, t, (ph) => {
        if (ph === "spinning") return { title: "SPINNING…", sub: "No more bets — watch the wheel", tone: th.accent_hi };
        if (ph === "result" && !showResult) return { title: "THE BALL DROPS…", sub: "", tone: th.accent_hi };
        if (ph === "result") {
          const n = wheel[fx.landed];
          const words = n === 0 || n === 37 ? "ZERO" : `${rColor(n).toUpperCase()} · ${n % 2 ? "ODD" : "EVEN"} · ${n <= 18 ? "LOW" : "HIGH"}`;
          const hh = headline(S, t);
          return { ...hh, title: `${rLabel(n)} ${words}`, tone: { red: "#ff5a6e", black: INK1, green: "#3ddc84" }[rColor(n)] };
        }
        return null;
      });
      drawHeadline(S, g, B.x0, 160, 740, t, head, { size: 58 });
      // winning areas
      const win = showResult ? wheel[fx.landed] : null;
      if (win != null) {
        const pulse = 0.6 + 0.4 * Math.sin(t * 6);
        const L = B.x0 + B.zw;
        const bottom = B.y0 + 3 * B.ch;
        if (win === 0 || win === 37) {
          const h = (3 * B.ch) / (B.us ? 2 : 1);
          glowBox(g, B.x0, B.us ? (win === 37 ? B.y0 : B.y0 + h) : B.y0, B.zw, h, "#ffffff", pulse, 4);
        } else {
          const q = numCell(win, B);
          glowBox(g, q.x, q.y, B.cw, B.ch, "#ffffff", pulse, 4);
          const d = Math.ceil(win / 12);
          glowBox(g, L + 4 * (d - 1) * B.cw, bottom, 4 * B.cw, B.dzH, th.accent, pulse * 0.7, 4);
          glowBox(g, L + 12 * B.cw, B.y0 + q.r * B.ch, B.colW, B.ch, th.accent, pulse * 0.7, 4);
          EVEN_SPOTS.forEach((s, i) => {
            if (rouletteCovers(s).includes(win)) glowBox(g, L + 2 * i * B.cw, bottom + B.dzH, 2 * B.cw, B.emH, th.accent, pulse * 0.7, 4);
          });
        }
      }
      // everyone's chips on the layout
      const sb = obj(st.spot_bets);
      const sweep = win != null ? clamp((t - (fx.landedAt || t) - 1.4) / 0.8, 0, 1) : 0;
      for (const spot of Object.keys(sb)) {
        const p = rouletteSpotXY(spot, B);
        if (!p) continue;
        const wins = win != null && rouletteCovers(spot).includes(win);
        spotChips(S, g, spot, sb[spot], p[0], p[1], t, { r: 21, glow: wins ? th.accent : null, sweep: win != null && !wins ? sweep : 0, to: [B.x0 + 300, 150] });
      }
      // the dolly
      if (win != null) {
        const [dx, dy] = rouletteCenter(win, B);
        const k = easeOut((t - (fx.landedAt || t)) / 0.5);
        g.save();
        g.globalAlpha = k;
        g.shadowColor = "rgba(0,0,0,.6)";
        g.shadowBlur = 10;
        rr(g, dx - 14, dy - 34 - (1 - k) * 60, 28, 40, 8);
        const dg = g.createLinearGradient(dx - 14, 0, dx + 14, 0);
        dg.addColorStop(0, "#d8d8e0");
        dg.addColorStop(0.5, "#ffffff");
        dg.addColorStop(1, "#a8a8b4");
        g.fillStyle = dg;
        g.fill();
        g.restore();
      }
      // the foot: totals and winners
      const total = Object.values(obj(st.totals)).reduce((a, b) => a + num(b), 0);
      const fy = B.y0 + 3 * B.ch + B.dzH + B.emH + 34;
      txt(g, "ON THE TABLE", B.x0, fy + 22, 20, INK3, { weight: 800, shadow: false });
      txt(g, fmt(S, total), B.x0, fy + 82, 56, INK1, { font: "mono", weight: 750 });
      const house = obj(st.house);
      txt(g, `Limits ${fmt(S, num(house.min_bet, 1))} – ${fmt(S, num(house.max_bet, 500))} · straight up pays 35 to 1`, B.x0, fy + 122, 22, INK2, { weight: 600 });
      if (st.phase === "result" && showResult) winnersCard(S, g, B.x0 + 400, fy - 6, 380, t, { delay: 1.2, max: 3 });
    },
  });

  // ================================================================================================ BIG SIX
  const BX = 470;
  const BY = 500;
  const BR = 410;
  const B6_SEG = TAU / 54;
  const B6S = { v0: 7.5, vEnd: 2.6, T: 7.0 };

  function b6Rot(fx, t) {
    if (fx.land) {
      const L = fx.land;
      return L.p0 + settle(L.d, L.v, L.T, t - L.t0);
    }
    if (fx.spinFrom == null) return fx.rest;
    const x = clamp(t - fx.spinFrom, 0, 1e9);
    const xs = Math.min(x, B6S.T);
    const p = fx.rest + B6S.vEnd * xs + ((B6S.v0 - B6S.vEnd) * B6S.T) / 3 * (1 - Math.pow(1 - xs / B6S.T, 3));
    return p + B6S.vEnd * Math.max(0, x - B6S.T);
  }
  function b6Speed(fx, t) {
    if (fx.land) {
      const L = fx.land;
      const u = clamp((t - L.t0) / L.T, 0, 1);
      return Math.max(0, L.v * (3 * u * u - 4 * u + 1) + (L.d / L.T) * (-6 * u * u + 6 * u));
    }
    if (fx.spinFrom == null) return 0;
    const x = t - fx.spinFrom;
    if (x < 0) return 0;
    return x >= B6S.T ? B6S.vEnd : B6S.vEnd + (B6S.v0 - B6S.vEnd) * Math.pow(1 - x / B6S.T, 2);
  }

  function b6Wheel(S) {
    const key = `${S.k}`;
    if (S.fx.img && S.fx.img.key === key) return S.fx.img.c;
    const D = 2 * BR + 10;
    const m = makeCanvas(D, D, S.k);
    const g = m.g;
    g.translate(D / 2, D / 2);
    for (let i = 0; i < 54; i++) {
      const s = B6_BY[B6_WHEEL[i]];
      const a0 = i * B6_SEG - Math.PI / 2;
      g.beginPath();
      g.moveTo(0, 0);
      g.arc(0, 0, BR, a0, a0 + B6_SEG);
      g.closePath();
      const gg = g.createRadialGradient(0, 0, 160, 0, 0, BR);
      gg.addColorStop(0, shade(s.col, 0.55));
      gg.addColorStop(1, s.col);
      g.fillStyle = gg;
      g.fill();
      g.lineWidth = 2;
      g.strokeStyle = "rgba(0,0,0,.45)";
      g.stroke();
      g.save();
      g.rotate((i + 0.5) * B6_SEG);
      const label = s.sym === "joker" ? "J" : s.sym === "logo" ? "★" : s.sym;
      txt(g, label, 0, -BR + 66, s.sym.length > 1 && label.length > 1 ? 30 : 38, s.sym === "logo" ? "#3a2c08" : "#ffffff", { align: "center", weight: 850 });
      g.restore();
    }
    g.fillStyle = "#e6c46a";
    for (let i = 0; i < 54; i++) {
      const a = i * B6_SEG - Math.PI / 2;
      circle(g, Math.cos(a) * (BR - 8), Math.sin(a) * (BR - 8), 5);
      g.fill();
    }
    circle(g, 0, 0, 170);
    const hg = g.createRadialGradient(-40, -50, 10, 0, 0, 170);
    hg.addColorStop(0, "#3a3046");
    hg.addColorStop(1, "#141018");
    g.fillStyle = hg;
    g.fill();
    g.lineWidth = 8;
    g.strokeStyle = "#d9b45a";
    g.stroke();
    for (let i = 0; i < 12; i++) {
      g.save();
      g.rotate((i / 12) * TAU);
      rr(g, -3, -165, 6, 60, 3);
      g.fillStyle = "rgba(217,180,90,.5)";
      g.fill();
      g.restore();
    }
    S.fx.img = { key, c: m.c };
    return m.c;
  }

  const bigsix = makeScene({
    id: "casino-bigsix",
    app: "casino_bigsix",
    init(S) {
      S.fx = { rest: 0, spinFrom: null, spinRound: null, land: null, pending: null, landed: null };
    },
    ingest(S, st, t) {
      const fx = S.fx;
      if (st.phase === "locked" || st.phase === "spinning") {
        const from = lockTime(S.clk, 7.0) + LOCK;
        if (fx.spinRound !== st.round) {
          fx.rest = b6Rot(fx, t);
          fx.land = null;
          fx.landed = null;
          fx.spinFrom = from;
          fx.spinRound = st.round;
        } else if (Math.abs(from - fx.spinFrom) < 1.5) fx.spinFrom += (from - fx.spinFrom) * 0.3;
      }
      const out = obj(obj(st.result).outcome);
      if (st.phase === "result" && typeof out.segment === "number" && fx.resRound !== st.round) {
        fx.resRound = st.round;
        fx.pending = out.segment;
      }
      if (fx.spinFrom == null && fx.landed == null && fx.pending == null) {
        const last = arr(st.history).filter((h) => h.game === "bigsix").slice(-1)[0];
        const seg = obj(last && last.outcome).segment;
        if (typeof seg === "number") {
          fx.rest = -(seg + 0.5) * B6_SEG;
          fx.landed = seg;
        }
      }
    },
    bg(S, g) {
      const th = S.th;
      rr(g, 18, 18, RAIL_X - 34, SH - 36, 60);
      feltFill(g, th, 1150, 480, 900);
      railStroke(g, th, 18);
      // the wheel's housing
      circle(g, BX, BY, BR + 52);
      const wg = g.createRadialGradient(BX - 100, BY - 120, 60, BX, BY, BR + 52);
      wg.addColorStop(0, "#6a4022");
      wg.addColorStop(1, "#2a160a");
      g.fillStyle = wg;
      g.shadowColor = "rgba(0,0,0,.6)";
      g.shadowBlur = 40;
      g.fill();
      g.shadowBlur = 0;
      circle(g, BX, BY, BR + 6);
      g.lineWidth = 8;
      g.strokeStyle = "#d9b45a";
      g.stroke();
      txt(g, "BIG SIX", 990, 92, 44, th.accent, { weight: 850 });
      txt(g, "THE MONEY WHEEL · 54 SEGMENTS", 992, 128, 22, INK2, { weight: 700 });
      B6.forEach((s, i) => {
        const [x, y] = b6Tile(i);
        feltBox(g, th, x, y, 250, 140, { fill: "rgba(0,0,0,.22)" });
        rr(g, x + 14, y + 14, 92, 112, 14);
        g.fillStyle = s.col;
        g.fill();
        const label = s.sym === "joker" ? "JOKER" : s.sym === "logo" ? "LOGO" : s.sym;
        txt(g, label, x + 60, y + 88, label.length > 2 ? 22 : 54, s.sym === "logo" ? "#3a2c08" : "#fff", { align: "center", weight: 850 });
        txt(g, `PAYS ${s.pays} : 1`, x + 120, y + 48, 24, INK1, { weight: 800 });
        txt(g, `${s.n} of 54`, x + 120, y + 78, 20, INK3, { weight: 700 });
      });
    },
    draw(S, g, t) {
      const st = S.st;
      const fx = S.fx;
      const th = S.th;
      if (fx.pending != null) {
        const p0 = b6Rot(fx, t);
        const v = Math.max(1.2, b6Speed(fx, t) || 2.6);
        const off = (hash01(`b6${st.round}`) - 0.5) * 0.5 * B6_SEG;
        const target = -(fx.pending + 0.5) * B6_SEG + off;
        let d = mod(target - p0, TAU);
        if (v > 0 && d < 0.25) d += TAU;
        const T = fx.spinFrom == null ? 0.001 : clamp((2 * d) / v, 0.8, 3.0);
        fx.land = { t0: t, p0, d, v: fx.spinFrom == null ? 0 : v, T, seg: fx.pending };
        fx.pending = null;
      }
      if (fx.land && t - fx.land.t0 >= fx.land.T) {
        fx.rest = fx.land.p0 + fx.land.d;
        fx.landed = fx.land.seg;
        fx.landedAt = t;
        fx.land = null;
        fx.spinFrom = null;
      }
      const phi = b6Rot(fx, t);
      const speed = b6Speed(fx, t);
      // bulbs round the housing
      for (let i = 0; i < 36; i++) {
        const a = (i / 36) * TAU;
        const lit = speed > 0.2 ? (i + Math.floor(t * 12)) % 3 === 0 : st.phase === "result" ? (i + Math.floor(t * 6)) % 2 === 0 : i % 2 === 0;
        circle(g, BX + Math.sin(a) * (BR + 30), BY - Math.cos(a) * (BR + 30), lit ? 8 : 6);
        g.fillStyle = lit ? "#fff2c0" : "rgba(255,220,140,.25)";
        g.fill();
      }
      g.save();
      g.translate(BX, BY);
      g.rotate(phi);
      g.drawImage(b6Wheel(S), -BR - 5, -BR - 5, 2 * BR + 10, 2 * BR + 10);
      g.restore();
      const sheen = g.createRadialGradient(BX - 140, BY - 160, 20, BX, BY, BR);
      sheen.addColorStop(0, "rgba(255,255,255,.18)");
      sheen.addColorStop(1, "rgba(0,0,0,.15)");
      circle(g, BX, BY, BR);
      g.fillStyle = sheen;
      g.fill();
      // the clapper, flicked by the pegs
      const rel = mod(-phi, B6_SEG) / B6_SEG;
      const kick = speed > 0.05 ? Math.exp(-rel * 5) * clamp(speed / 3, 0.25, 1) * 0.35 : 0;
      g.save();
      g.translate(BX, BY - BR - 46);
      g.rotate(-kick);
      g.beginPath();
      g.moveTo(-16, 0);
      g.lineTo(16, 0);
      g.lineTo(3, 92);
      g.lineTo(-3, 92);
      g.closePath();
      g.fillStyle = "#d6283a";
      g.shadowColor = "rgba(0,0,0,.6)";
      g.shadowBlur = 10;
      g.fill();
      g.restore();
      circle(g, BX, BY - BR - 46, 14);
      g.fillStyle = "#e6c46a";
      g.fill();
      // the hub shows the symbol under the clapper
      const under = mod(Math.floor(mod(-phi, TAU) / B6_SEG), 54);
      const sym = B6_BY[B6_WHEEL[under]];
      const showRes = st.phase === "result" && fx.landed != null && !fx.land;
      txt(g, showRes ? (sym.sym === "joker" ? "JOKER" : sym.sym === "logo" ? "LOGO" : sym.sym) : "BIG SIX", BX, BY + (showRes ? 30 : 14), showRes ? (sym.sym.length > 2 ? 52 : 110) : 46, showRes ? sym.col : th.accent, { align: "center", weight: 850, glow: showRes ? sym.col : null });
      // headline
      drawHeadline(S, g, 990, 150, 510, t, headline(S, t, (ph) => {
        if (ph === "spinning") return { title: "SPINNING…", sub: "Listen for the clapper", tone: th.accent_hi };
        if (ph === "result" && !showRes) return { title: "SLOWING…", sub: "", tone: th.accent_hi };
        if (ph === "result") {
          const s = B6_BY[B6_WHEEL[fx.landed]];
          return { ...headline(S, t), title: `${s.sym === "joker" ? "JOKER" : s.sym === "logo" ? "LOGO" : s.sym} PAYS ${s.pays}:1`, tone: s.col };
        }
        return null;
      }), { size: 50 });
      const sb = obj(st.spot_bets);
      const winSym = showRes ? B6_WHEEL[fx.landed] : null;
      const sw = winSym != null ? clamp((t - (fx.landedAt || t) - 1.4) / 0.8, 0, 1) : 0;
      B6.forEach((s, i) => {
        const [x, y] = b6Tile(i);
        const isWin = winSym === s.sym;
        if (isWin) glowBox(g, x, y, 250, 140, s.col, 0.6 + 0.4 * Math.sin(t * 6));
        const tot = num(obj(st.totals)[s.id]);
        if (tot) txt(g, fmt(S, tot), x + 120, y + 116, 20, INK2, { font: "mono", weight: 700 });
        spotChips(S, g, s.id, sb[s.id], x + 206, y + 74, t, { r: 24, glow: isWin ? th.accent : null, sweep: winSym != null && !isWin ? sw : 0, to: [BX, BY] });
      });
      if (showRes) winnersCard(S, g, 1255, 740, 250, t, { delay: 1.2, max: 2 });
    },
  });
  function b6Tile(i) {
    if (i === 6) return [990, 740];
    return [990 + (i % 2) * 265, 250 + Math.floor(i / 2) * 160];
  }

  // ================================================================================================ 7 UP 7 DOWN
  const PIPS = { 1: [[0, 0]], 2: [[-1, -1], [1, 1]], 3: [[-1, -1], [0, 0], [1, 1]], 4: [[-1, -1], [1, -1], [-1, 1], [1, 1]],
    5: [[-1, -1], [1, -1], [0, 0], [-1, 1], [1, 1]], 6: [[-1, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [1, 1]] }; // fmt: skip
  function die(g, x, y, s, face, rot, o) {
    o = o || {};
    g.save();
    g.translate(x, y);
    g.rotate(rot || 0);
    g.shadowColor = "rgba(0,0,0,.55)";
    g.shadowBlur = s * 0.25;
    g.shadowOffsetY = s * 0.08;
    rr(g, -s / 2, -s / 2, s, s, s * 0.2);
    const gr = g.createLinearGradient(-s / 2, -s / 2, s / 2, s / 2);
    gr.addColorStop(0, "#ff4a5a");
    gr.addColorStop(1, "#a8101f");
    g.fillStyle = gr;
    g.fill();
    g.shadowBlur = 0;
    g.shadowOffsetY = 0;
    rr(g, -s / 2 + s * 0.06, -s / 2 + s * 0.05, s * 0.88, s * 0.4, s * 0.16);
    g.fillStyle = "rgba(255,255,255,.14)";
    g.fill();
    if (o.glow) {
      rr(g, -s / 2, -s / 2, s, s, s * 0.2);
      g.lineWidth = 5;
      g.strokeStyle = o.glow;
      g.shadowColor = o.glow;
      g.shadowBlur = 24;
      g.stroke();
      g.shadowBlur = 0;
    }
    for (const [px, py] of PIPS[face] || PIPS[1]) {
      circle(g, px * s * 0.27, py * s * 0.27, s * 0.085);
      g.fillStyle = "#ffffff";
      g.fill();
    }
    g.restore();
  }

  const TRAY = { x: 70, y: 180, w: 900, h: 400 };
  const sevens = makeScene({
    id: "casino-sevens",
    app: "casino_sevens",
    init(S) {
      S.fx = { lockAt: null, round: null, res: null };
    },
    ingest(S, st, t) {
      const fx = S.fx;
      if (st.phase === "locked" || st.phase === "spinning") {
        const est = lockTime(S.clk, 2.6);
        if (fx.round !== st.round) {
          fx.round = st.round;
          fx.lockAt = est;
          fx.res = null;
        } else if (Math.abs(est - fx.lockAt) < 1) fx.lockAt += (est - fx.lockAt) * 0.3;
      }
      const out = obj(obj(st.result).outcome);
      if (st.phase === "result" && Array.isArray(out.dice) && (!fx.res || fx.res.round !== st.round)) {
        fx.res = { round: st.round, dice: out.dice, sum: out.sum, zone: out.zone, t0: fx.round === st.round ? t : -1e9 };
      }
    },
    bg(S, g) {
      const th = S.th;
      rr(g, 18, 18, RAIL_X - 34, SH - 36, 60);
      feltFill(g, th, 760, 480, 1000);
      railStroke(g, th, 18);
      rr(g, TRAY.x - 16, TRAY.y - 16, TRAY.w + 32, TRAY.h + 32, 34);
      const wg = g.createLinearGradient(0, TRAY.y - 16, 0, TRAY.y + TRAY.h + 16);
      wg.addColorStop(0, "#7a4a24");
      wg.addColorStop(1, "#3a2010");
      g.fillStyle = wg;
      g.fill();
      rr(g, TRAY.x, TRAY.y, TRAY.w, TRAY.h, 22);
      feltFill(g, { ...th, felt: shade(th.felt, 0.85) }, TRAY.x + TRAY.w / 2, TRAY.y + TRAY.h / 2, 600);
      txt(g, "7 UP 7 DOWN", TRAY.x + TRAY.w / 2, TRAY.y + TRAY.h / 2 + 30, 90, rgba(th.accent, 0.12), { align: "center", weight: 900, shadow: false });
      txt(g, "LAST ROLLS", 1020, 220, 20, INK3, { weight: 800, shadow: false });
      SEVENS.forEach((z, i) => {
        const x = 60 + i * 478;
        feltBox(g, th, x, 640, 456, 300, { fill: rgba(z.col, 0.16), stroke: z.col });
        txt(g, z.name, x + 30, 712, 52, "#fff", { weight: 900 });
        txt(g, z.sub, x + 30, 754, 26, INK2, { weight: 650 });
        txt(g, `PAYS ${i === 1 ? `${num(obj(S.st.rules).seven_pays, 4)} : 1` : z.pays}`, x + 30, 905, 28, th.accent, { weight: 850 });
      });
    },
    draw(S, g, t) {
      const st = S.st;
      const fx = S.fx;
      const th = S.th;
      const ph = st.phase;
      const cx = TRAY.x + TRAY.w / 2;
      const cy = TRAY.y + TRAY.h / 2;
      const restA = [cx - 110, cy + 10];
      const restB = [cx + 110, cy - 6];
      const rolling = (ph === "locked" || ph === "spinning") && fx.lockAt != null;
      const res = fx.res && fx.res.round === st.round && ph === "result" ? fx.res : null;
      const last = arr(st.history).filter((h) => h.game === "sevens" && h.outcome).slice(-1)[0];
      const shown = res ? res.dice : arr(obj(last && last.outcome).dice);
      if (rolling || (res && t - res.t0 < 0.45)) {
        const x = rolling ? t - fx.lockAt : 9;
        const u = clamp(x / (LOCK + 2.6), 0, 1);
        const seed = hash01(`d${st.round}`);
        [restA, restB].forEach((rest, i) => {
          const sx = TRAY.x + 90;
          const sy = TRAY.y + 90 + i * 200;
          const e = easeOut(u);
          const bx = lerp(sx, rest[0], e) + Math.sin(x * 9 + i) * 30 * (1 - u);
          const by = lerp(sy, rest[1], e) - Math.abs(Math.sin(x * (7 + i) + seed * 6)) * 110 * (1 - u) * (1 - u);
          const face = 1 + Math.floor(hash01(`${st.round}|${i}|${Math.floor(x * 14)}`) * 6);
          let fxp = bx;
          let fyp = by;
          let f = face;
          let rot = x * (8 - i * 2) * (1 - u) + seed * 3 + Math.sin(x * 3) * 0.2;
          if (res) {
            const k = easeOut((t - res.t0) / 0.45);
            fxp = lerp(bx, rest[0], k);
            fyp = lerp(by, rest[1], k);
            f = k > 0.4 ? res.dice[i] : face;
            rot = lerp(rot, i ? 0.08 : -0.06, k);
          }
          die(g, fxp, fyp, 150, f, rot);
        });
      } else if (shown.length === 2) {
        die(g, restA[0], restA[1], 150, shown[0], -0.06, { glow: res ? th.accent : null });
        die(g, restB[0], restB[1], 150, shown[1], 0.08, { glow: res ? th.accent : null });
      } else {
        die(g, restA[0], restA[1], 150, 3, -0.06);
        die(g, restB[0], restB[1], 150, 4, 0.08);
      }
      if (res && t - res.t0 >= 0.45) {
        const z = SEVENS.find((s) => s.id === res.zone) || SEVENS[0];
        const k = easeOut((t - res.t0 - 0.45) / 0.4);
        txt(g, String(res.sum), cx, TRAY.y + 120, 110 * (0.6 + 0.4 * k), "#fff", { align: "center", weight: 900, glow: z.col, alpha: k });
      }
      drawHeadline(S, g, 70, 40, 900, t, headline(S, t, (p) => {
        if (p === "spinning") return { title: "ROLLING…", sub: "Under, seven or over?", tone: th.accent_hi };
        if (p === "result" && res) {
          const z = SEVENS.find((s) => s.id === res.zone) || SEVENS[0];
          return { ...headline(S, t), title: `${res.sum} · ${z.name}`, tone: z.col };
        }
        return null;
      }), { size: 56 });
      // last rolls
      const hist = arr(st.history).filter((h) => h.game === "sevens" && h.outcome).slice(-8).reverse();
      hist.forEach((h, i) => {
        const o = obj(h.outcome);
        const y = 250 + i * 46;
        const d = arr(o.dice);
        if (d.length === 2) {
          die(g, 1040, y + 20, 36, d[0], 0);
          die(g, 1084, y + 20, 36, d[1], 0);
        }
        const z = SEVENS.find((s) => s.id === o.zone) || SEVENS[0];
        txt(g, String(o.sum), 1130, y + 34, 32, "#fff", { font: "mono", weight: 800 });
        pill(g, z.name, 1190, y + 22, 18, rgba(z.col, 0.85), "#fff");
      });
      const sb = obj(st.spot_bets);
      const sw = sweepK(S, t, 1.6);
      SEVENS.forEach((z, i) => {
        const x = 60 + i * 478;
        const isWin = res && res.zone === z.id && t - res.t0 > 0.5;
        if (isWin) glowBox(g, x, 640, 456, 300, z.col, 0.6 + 0.4 * Math.sin(t * 6));
        const tot = num(obj(st.totals)[z.id]);
        if (tot) txt(g, `${fmt(S, tot)} on it`, x + 426, 712, 24, INK2, { align: "right", font: "mono", weight: 700 });
        spotChips(S, g, z.id, sb[z.id], x + 228, 820, t, { r: 34, glow: isWin ? th.accent : null, sweep: res && !isWin ? sw : 0, to: [cx, cy] });
      });
      if (res && t - res.t0 > 1) winnersCard(S, g, 1020, 40, 480, t, { delay: 1.4, max: 2 });
    },
  });

  // ================================================================================================ BACCARAT
  const BAC_SHOE = [770, 160];
  const BAC_SLOTS = {
    player: { x: 80, w: 620, col: "#1f5fe0", name: "PLAYER" },
    banker: { x: 840, w: 620, col: "#d0182f", name: "BANKER" },
  };
  const BAC_BETS = [
    { id: "ppair", name: "P PAIR", x: 80, w: 220, col: "#1f5fe0", pays: "11 : 1" },
    { id: "player", name: "PLAYER", x: 300, w: 380, col: "#1f5fe0", pays: "1 : 1" },
    { id: "tie", name: "TIE", x: 680, w: 220, col: "#0e9a4c", pays: "8 : 1" },
    { id: "banker", name: "BANKER", x: 900, w: 380, col: "#d0182f", pays: "0.95 : 1" },
    { id: "bpair", name: "B PAIR", x: 1280, w: 220, col: "#d0182f", pays: "11 : 1" },
  ];
  function bacCardXY(side, i) {
    const s = BAC_SLOTS[side];
    if (i === 2) return [s.x + s.w - 120, 300, Math.PI / 2];
    return [s.x + 110 + i * 150, 300, 0];
  }
  function bacWinSpots(out) {
    const w = String(out.winner || "");
    const s = new Set([w]);
    if (out.ppair) s.add("ppair");
    if (out.bpair) s.add("bpair");
    return s;
  }
  const baccarat = makeScene({
    id: "casino-baccarat",
    app: "casino_baccarat",
    bg(S, g) {
      const th = S.th;
      rr(g, 18, 18, RAIL_X - 34, SH - 36, 60);
      feltFill(g, th, 760, 300, 1100);
      railStroke(g, th, 18);
      for (const side of ["player", "banker"]) {
        const s = BAC_SLOTS[side];
        feltBox(g, th, s.x, 150, s.w, 300, { fill: rgba(s.col, 0.12), stroke: rgba(s.col, 0.9) });
        txt(g, s.name, s.x + s.w / 2, 190, 34, "#fff", { align: "center", weight: 900 });
        for (let i = 0; i < 3; i++) {
          const [x, y, rot] = bacCardXY(side, i);
          g.save();
          g.translate(x, y);
          g.rotate(rot);
          cardSlot(g, 0, 0, 118, 166, rgba("#ffffff", 0.25));
          g.restore();
        }
      }
      BAC_BETS.forEach((b) => {
        feltBox(g, th, b.x, 480, b.w, 200, { fill: rgba(b.col, 0.14), stroke: rgba(th.accent, 0.8), r: 8 });
        txt(g, b.name, b.x + b.w / 2, 528, b.w > 300 ? 40 : 30, "#fff", { align: "center", weight: 900 });
        let pays = b.pays;
        const r = obj(S.st.rules);
        if (b.id === "tie") pays = `${num(r.tie_pays, 8)} : 1`;
        if (b.id === "banker" && r.commission === "no_commission") pays = "1 : 1 (6 pays 1:2)";
        txt(g, pays, b.x + b.w / 2, 664, 22, th.accent, { align: "center", weight: 800 });
      });
      txt(g, "BEAD PLATE", 80, 724, 18, INK3, { weight: 800, shadow: false });
      txt(g, "BIG ROAD", 560, 724, 18, INK3, { weight: 800, shadow: false });
      for (const [x0, cols] of [[80, 12], [560, 26]]) {
        for (let r = 0; r < 6; r++)
          for (let c = 0; c < cols; c++) {
            g.beginPath();
            g.rect(x0 + c * 36, 736 + r * 36, 36, 36);
            g.lineWidth = 1;
            g.strokeStyle = "rgba(255,255,255,.1)";
            g.stroke();
          }
      }
      // the shoe
      rr(g, BAC_SHOE[0] - 60, BAC_SHOE[1] - 110, 120, 90, 14);
      g.fillStyle = "#1a1a20";
      g.fill();
      g.lineWidth = 3;
      g.strokeStyle = th.accent;
      g.stroke();
      txt(g, "SHOE", BAC_SHOE[0], BAC_SHOE[1] - 56, 22, th.accent, { align: "center", weight: 850 });
    },
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const ph = st.phase;
      const res = ph === "result" ? obj(obj(st.result).outcome) : null;
      const cards = res ? { player: arr(res.player), banker: arr(res.banker) } : ph === "dealing" ? { player: arr(obj(st.cards).player), banker: arr(obj(st.cards).banker) } : { player: [], banker: [] };
      const totals = {};
      for (const side of ["player", "banker"]) {
        const shownCodes = [];
        cards[side].forEach((code, i) => {
          const [x, y, rot] = bacCardXY(side, i);
          const f = cardFly(S, `${side}${i}`, BAC_SHOE[0], BAC_SHOE[1] - 60, x, y, t, 0.6);
          if (f.flip >= 0.5) shownCodes.push(code);
          drawCard(S, g, code, f.x, f.y, 118, 166, { rot: rot + f.rot, flip: f.flip });
        });
        totals[side] = baccaratTotal(shownCodes);
        const s = BAC_SLOTS[side];
        if (shownCodes.length) {
          const win = res && res.winner === side;
          circle(g, side === "player" ? s.x + s.w - 30 : s.x + 30, 180, 44);
          g.fillStyle = win ? th.accent : "rgba(0,0,0,.6)";
          g.fill();
          g.lineWidth = 3;
          g.strokeStyle = s.col;
          g.stroke();
          txt(g, String(totals[side]), side === "player" ? s.x + s.w - 30 : s.x + 30, 198, 50, win ? th.ink : "#fff", { align: "center", weight: 900, shadow: false });
        }
      }
      if (res && res.winner) {
        for (const side of ["player", "banker"]) if (res.winner === side || res.winner === "tie") glowBox(g, BAC_SLOTS[side].x, 150, BAC_SLOTS[side].w, 300, res.winner === "tie" ? "#3ddc84" : BAC_SLOTS[side].col, 0.6 + 0.4 * Math.sin(t * 5));
      }
      drawHeadline(S, g, 760, 40, 900, t, headline(S, t, (p) => {
        if (p === "dealing") return { title: "THE COUP IS DEALT", sub: `Player ${totals.player} · Banker ${totals.banker}`, tone: th.accent_hi };
        if (p === "result" && res) {
          const w = res.winner === "tie" ? "TIE" : `${String(res.winner).toUpperCase()} WINS`;
          const extra = [res.natural ? "NATURAL" : "", res.ppair ? "PLAYER PAIR" : "", res.bpair ? "BANKER PAIR" : ""].filter(Boolean).join(" · ");
          return { title: `${w} ${res.p} – ${res.b}`, sub: extra || headline(S, t).sub, tone: res.winner === "tie" ? "#3ddc84" : BAC_SLOTS[res.winner] ? shade(BAC_SLOTS[res.winner].col, 1.4) : th.accent };
        }
        return null;
      }), { size: 50, align: "center" });
      // the bets
      const sb = obj(st.spot_bets);
      const wins = res ? bacWinSpots(res) : new Set();
      const sw = sweepK(S, t, 1.5);
      BAC_BETS.forEach((b) => {
        const isWin = wins.has(b.id) || (res && res.winner === "tie" && (b.id === "player" || b.id === "banker"));
        if (res && wins.has(b.id)) glowBox(g, b.x, 480, b.w, 200, th.accent, 0.6 + 0.4 * Math.sin(t * 6), 8);
        const tot = num(obj(st.totals)[b.id]);
        if (tot) txt(g, fmt(S, tot), b.x + b.w / 2, 560, 22, INK2, { align: "center", font: "mono", weight: 700 });
        spotChips(S, g, b.id, sb[b.id], b.x + b.w / 2, 610, t, { r: 28, glow: res && wins.has(b.id) ? th.accent : null, sweep: res && !isWin ? sw : 0, to: [BAC_SHOE[0], 100] });
      });
      // roads
      const hist = arr(st.history).filter((h) => h.game === "baccarat" && h.outcome).map((h) => obj(h.outcome));
      const bead = hist.slice(-72);
      bead.forEach((o, i) => {
        const c = Math.floor(i / 6);
        const r = i % 6;
        const col = o.winner === "player" ? "#1f5fe0" : o.winner === "banker" ? "#d0182f" : "#0e9a4c";
        circle(g, 80 + c * 36 + 18, 736 + r * 36 + 18, 15);
        g.fillStyle = col;
        g.fill();
        txt(g, o.winner === "player" ? "P" : o.winner === "banker" ? "B" : "T", 80 + c * 36 + 18, 736 + r * 36 + 25, 18, "#fff", { align: "center", weight: 850, shadow: false });
      });
      bigRoad(hist).forEach(({ c, r, w, ties }) => {
        if (c >= 26) return;
        const x = 560 + c * 36 + 18;
        const y = 736 + r * 36 + 18;
        circle(g, x, y, 13);
        g.lineWidth = 4;
        g.strokeStyle = w === "player" ? "#4a86ff" : "#ff4a5e";
        g.stroke();
        if (ties) {
          g.beginPath();
          g.moveTo(x - 12, y + 12);
          g.lineTo(x + 12, y - 12);
          g.strokeStyle = "#3ddc84";
          g.lineWidth = 3;
          g.stroke();
        }
      });
      const count = (w) => hist.filter((o) => o.winner === w).length;
      txt(g, `P ${count("player")}  ·  B ${count("banker")}  ·  T ${count("tie")}`, 1500, 724, 20, INK2, { align: "right", weight: 800, shadow: false });
      if (res) winnersCard(S, g, 1080, 150, 380, t, { delay: 2.4, max: 3 });
    },
  });

  /** The big road: a new column when the winner changes, down then right when a column is full; ties mark. */
  function bigRoad(hist) {
    const out = [];
    let c = -1;
    let r = 0;
    let last = null;
    for (const o of hist) {
      if (o.winner === "tie") {
        if (out.length) out[out.length - 1].ties += 1;
        continue;
      }
      if (o.winner !== last) {
        c = out.length ? Math.max(...out.filter((e) => e.r === 0).map((e) => e.c)) + 1 : 0;
        r = 0;
      } else if (r < 5) r += 1;
      else c += 1;
      out.push({ c, r, w: o.winner, ties: 0 });
      last = o.winner;
    }
    return out;
  }

  // ================================================================================================ ANDAR BAHAR
  const AB_ROW = { andar: 270, bahar: 540 };
  const AB_SHOE = [760, 120];
  function abCardX(i, n) {
    const step = Math.min(70, (1020 - 110) / Math.max(1, n - 1));
    return 470 + 55 + i * step;
  }
  const andarbahar = makeScene({
    id: "casino-andarbahar",
    app: "casino_andarbahar",
    bg(S, g) {
      const th = S.th;
      rr(g, 18, 18, RAIL_X - 34, SH - 36, 60);
      feltFill(g, th, 760, 400, 1100);
      railStroke(g, th, 18);
      feltBox(g, th, 70, 170, 330, 460, { fill: "rgba(0,0,0,.2)" });
      txt(g, "JOKER", 235, 220, 34, th.accent, { align: "center", weight: 900 });
      cardSlot(g, 235, 400, 200, 280, rgba("#ffffff", 0.25));
      for (const side of ["andar", "bahar"]) {
        const y = AB_ROW[side];
        feltBox(g, th, 430, y - 110, 1080, 220, { fill: rgba(TONE[side], 0.12), stroke: rgba(TONE[side], 0.8) });
        txt(g, side.toUpperCase(), 450, y - 118 + 0, 24, TONE[side], { weight: 900 });
      }
      txt(g, "ANDAR BAHAR", 70, 120, 40, th.accent, { weight: 900 });
    },
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const ph = st.phase;
      const out = ph === "result" ? obj(obj(st.result).outcome) : null;
      const deal = ph === "dealing" ? obj(st.deal) : null;
      const joker = out ? out.joker : deal ? deal.joker : null;
      const first = (out || deal || {}).first || obj(st.rules).first || "andar";
      const cards = out ? arr(out.cards) : deal ? arr(deal.cards) : [];
      const matched = out ? true : deal ? !!deal.matched : false;
      if (joker) {
        const f = cardFly(S, "joker", AB_SHOE[0], AB_SHOE[1], 235, 400, t, 0.7);
        drawCard(S, g, joker, f.x, f.y, 200, 280, { flip: f.flip, glow: rgba(th.accent, 0.7) });
      }
      const other = first === "andar" ? "bahar" : "andar";
      const rows = { andar: [], bahar: [] };
      cards.forEach((c, i) => rows[i % 2 === 0 ? first : other].push({ c, i }));
      for (const side of ["andar", "bahar"]) {
        const list = rows[side];
        list.forEach(({ c, i }, j) => {
          const x = abCardX(j, Math.max(list.length, 8));
          const f = cardFly(S, `ab${i}`, AB_SHOE[0], AB_SHOE[1], x, AB_ROW[side], t, 0.45);
          const isMatch = matched && i === cards.length - 1;
          drawCard(S, g, c, f.x, f.y, 110, 154, { flip: f.flip, rot: f.rot, glow: isMatch && f.flip >= 1 ? th.accent : null });
        });
      }
      const winner = out ? out.winner : matched && cards.length ? (cards.length % 2 === 1 ? first : other) : null;
      if (winner && (out || matched)) glowBox(g, 430, AB_ROW[winner] - 110, 1080, 220, TONE[winner], 0.6 + 0.4 * Math.sin(t * 6));
      if (cards.length) txt(g, `${cards.length} ${cards.length === 1 ? "CARD" : "CARDS"}`, 235, 600, 30, INK1, { align: "center", font: "mono", weight: 800 });
      drawHeadline(S, g, 430, 20, 1080, t, headline(S, t, (p) => {
        if (p === "dealing") return matched ? { title: `${String(winner).toUpperCase()} MATCHES!`, sub: "", tone: TONE[winner] } : { title: "DEALING…", sub: `First card to ${first === "andar" ? "Andar" : "Bahar"} · find the joker's ${obj(st.deal).match === "card" ? "twin" : "rank"}`, tone: th.accent_hi };
        if (p === "result" && out) return { ...headline(S, t), title: `${String(out.winner).toUpperCase()} WINS · ${out.count} CARDS`, tone: TONE[out.winner] };
        return null;
      }), { size: 46 });
      // bets
      const spots = arr(st.spots);
      const sb = obj(st.spot_bets);
      const sw = sweepK(S, t, 1.5);
      const main = [{ id: "andar", x: 70, w: 440 }, { id: "bahar", x: 530, w: 440 }];
      const winSpots = new Set();
      if (out) {
        winSpots.add(out.winner);
        for (const s of spots) if (s.kind === "count" && arr(s.numbers).includes(out.count)) winSpots.add(s.id);
      }
      main.forEach((m) => {
        const sp = spots.find((s) => s.id === m.id) || {};
        feltBox(g, th, m.x, 700, m.w, 250, { fill: rgba(TONE[m.id], 0.14), stroke: TONE[m.id] });
        txt(g, m.id.toUpperCase(), m.x + 24, 752, 44, "#fff", { weight: 900 });
        txt(g, `PAYS ${sp.pays || "1:1"}`, m.x + 24, 930, 24, th.accent, { weight: 850 });
        const isWin = winSpots.has(m.id);
        if (isWin) glowBox(g, m.x, 700, m.w, 250, TONE[m.id], 0.6 + 0.4 * Math.sin(t * 6));
        spotChips(S, g, m.id, sb[m.id], m.x + m.w / 2 + 60, 840, t, { r: 32, glow: isWin ? th.accent : null, sweep: out && !isWin ? sw : 0, to: AB_SHOE });
      });
      const bands = spots.filter((s) => s.kind === "count");
      bands.forEach((s, i) => {
        const x = 990 + (i % 4) * 130;
        const y = 700 + Math.floor(i / 4) * 128;
        feltBox(g, th, x, y, 120, 116, { fill: "rgba(0,0,0,.2)", r: 12, lw: 2 });
        txt(g, String(s.label || "").replace(" cards", ""), x + 60, y + 32, 22, "#fff", { align: "center", weight: 850 });
        txt(g, s.pays || "", x + 60, y + 104, 18, th.accent, { align: "center", weight: 800 });
        const isWin = winSpots.has(s.id);
        if (isWin) glowBox(g, x, y, 120, 116, th.accent, 0.6 + 0.4 * Math.sin(t * 6), 12);
        spotChips(S, g, s.id, sb[s.id], x + 60, y + 64, t, { r: 18, glow: isWin ? th.accent : null, sweep: out && !isWin ? sw : 0, to: AB_SHOE });
      });
      if (!bands.length) txt(g, "Count side bets are off", 1240, 820, 24, INK3, { align: "center", weight: 650 });
      if (out) winnersCard(S, g, 70, 170, 330, t, { delay: 2.0, max: 3 });
    },
  });

  // ================================================================================================ BLACKJACK
  const BJ_C = [760, 40];
  const BJ_R = 700;
  const BJ_SHOE = [1330, 120];
  function bjSeatXY(i, n) {
    const a = ((155 - (130 * (i + 0.5)) / Math.max(1, n)) * Math.PI) / 180;
    return [BJ_C[0] + Math.cos(a) * BJ_R, BJ_C[1] + Math.sin(a) * BJ_R];
  }
  function arcText(g, s, cx, cy, r, mid, size, color, spacing) {
    const chars = String(s).split("");
    const step = (size * (spacing || 0.62)) / r;
    let a = mid + (step * (chars.length - 1)) / 2;
    for (const ch of chars) {
      g.save();
      g.translate(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
      g.rotate(a - Math.PI / 2);
      txt(g, ch, 0, 0, size, color, { align: "center", weight: 850, shadow: false });
      g.restore();
      a -= step;
    }
  }
  function bjSeats(S) {
    const st = S.st;
    const table = obj(st.table);
    const live = ["dealing", "action", "result", "locked"].includes(st.phase) && arr(table.seats).length;
    if (live) return arr(table.seats);
    const main = arr(obj(st.spot_bets).main);
    const seats = S.players.filter((p) => p.online || main.some((e) => String(e.seat) === String(p.seat)));
    return seats.map((p) => {
      const e = main.find((x) => String(x.seat) === String(p.seat));
      return { seat: p.seat, name: p.name, color: p.color, hands: [], bet: e ? num(e.amount) : 0 };
    });
  }
  const blackjack = makeScene({
    id: "casino-blackjack",
    app: "casino_blackjack",
    bg(S, g) {
      const th = S.th;
      g.beginPath();
      g.moveTo(40, 18);
      g.lineTo(RAIL_X - 40, 18);
      g.lineTo(RAIL_X - 40, 360);
      g.arc(BJ_C[0], BJ_C[1], BJ_R + 180, Math.atan2(360 - BJ_C[1], RAIL_X - 40 - BJ_C[0]), Math.atan2(360 - BJ_C[1], 40 - BJ_C[0]));
      g.closePath();
      feltFill(g, th, 760, 200, 1100);
      railStroke(g, th, 22);
      const r = obj(S.st.rules);
      arcText(g, `BLACKJACK PAYS ${r.blackjack_pays || "3:2"}`.replace(":", " TO "), BJ_C[0], BJ_C[1], 420, Math.PI / 2, 40, th.accent, 0.72);
      arcText(g, `DEALER ${r.soft17 === "hit" ? "HITS" : "STANDS ON"} SOFT 17 · INSURANCE PAYS 2 TO 1`, BJ_C[0], BJ_C[1], 372, Math.PI / 2, 22, rgba("#ffffff", 0.55), 0.66);
      g.beginPath();
      g.arc(BJ_C[0], BJ_C[1], 470, Math.PI * 0.17, Math.PI * 0.83);
      g.lineWidth = 3;
      g.strokeStyle = rgba(th.accent, 0.5);
      g.stroke();
      // the shoe and the discard tray
      rr(g, BJ_SHOE[0] - 70, BJ_SHOE[1] - 60, 140, 110, 16);
      g.fillStyle = "#16161c";
      g.fill();
      g.lineWidth = 3;
      g.strokeStyle = th.accent;
      g.stroke();
      rr(g, 120, 70, 120, 100, 14);
      g.fillStyle = "rgba(0,0,0,.35)";
      g.fill();
      txt(g, "DISCARD", 180, 130, 18, INK3, { align: "center", weight: 800, shadow: false });
    },
    turnSeat(S) {
      const turn = obj(obj(S.st.table).turn);
      return turn.seat != null ? turn.seat : null;
    },
    railInfo(S, p) {
      const seat = arr(obj(S.st.table).seats).find((s) => String(s.seat) === String(p.seat));
      if (seat && seat.net != null && S.st.phase === "result") return { text: `${seat.net >= 0 ? "WON" : "LOST"} ${signed(S, seat.net)}`, color: seat.net > 0 ? OK : seat.net < 0 ? BAD : INK2 };
      if (seat && arr(seat.hands).length) {
        const h = seat.hands[0];
        return { text: `${h.bj ? "BLACKJACK" : h.status === "bust" ? "BUST" : `HAND ${h.total}`} · BET ${fmt(S, arr(seat.hands).reduce((a, x) => a + num(x.bet), 0))}`, color: INK2 };
      }
      return railInfoDefault(S, p);
    },
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const table = obj(st.table);
      const shoe = obj(table.shoe);
      txt(g, `${num(shoe.decks, 6)} DECKS`, BJ_SHOE[0], BJ_SHOE[1] - 8, 20, th.accent, { align: "center", weight: 850, shadow: false });
      txt(g, `${num(shoe.left, 312)} LEFT`, BJ_SHOE[0], BJ_SHOE[1] + 26, 20, INK2, { align: "center", weight: 750, shadow: false });
      if (shoe.cut) pill(g, "CUT CARD OUT", BJ_SHOE[0], BJ_SHOE[1] + 76, 16, "#d0182f", "#fff", { align: "center" });
      // dealer
      const dealer = obj(table.dealer);
      const dc = arr(dealer.cards);
      dc.forEach((c, i) => {
        const x = 760 - ((dc.length - 1) * 96) / 2 + i * 96;
        const f = cardFly(S, `d${i}`, BJ_SHOE[0], BJ_SHOE[1], x, 170, t, 0.5);
        drawCard(S, g, c === "??" ? "back" : c, f.x, f.y, 110, 154, { down: c === "??", flip: c === "??" ? null : f.flip, rot: f.rot });
      });
      if (dc.length) {
        const bx = 760 + ((dc.length - 1) * 96) / 2 + 110;
        const label = dealer.bj ? "BJ" : `${dealer.total}${dealer.soft ? "*" : ""}`;
        circle(g, bx, 120, 38);
        g.fillStyle = dealer.total > 21 ? BAD : "rgba(0,0,0,.65)";
        g.fill();
        g.lineWidth = 3;
        g.strokeStyle = th.accent;
        g.stroke();
        txt(g, label, bx, 134, 36, "#fff", { align: "center", weight: 900, shadow: false });
        txt(g, "DEALER", 760, 275, 20, INK2, { align: "center", weight: 800, shadow: false });
      }
      // seats
      const seats = bjSeats(S);
      const n = seats.length;
      const turn = obj(table.turn);
      const sb = obj(st.spot_bets);
      seats.forEach((seat, i) => {
        const [x, y] = bjSeatXY(i, Math.max(n, 3));
        const p = { ...playerOf(S, seat.seat), color: seat.color || seatColor(S, seat.seat), name: seat.name };
        const isTurn = turn.seat != null && String(turn.seat) === String(seat.seat);
        // betting circle
        circle(g, x, y, 50);
        g.lineWidth = 4;
        g.strokeStyle = isTurn ? th.accent : rgba("#ffffff", 0.45);
        g.stroke();
        if (isTurn) {
          const tc = S.fx.turn || (S.fx.turn = new Countdown());
          tc.observe(`${seat.seat}|${turn.hand}`, turn.ends_in, S.ctx.stateAt || t);
          const left = tc.left(t);
          ring(g, x, y, 62, left == null ? 1 : left / num(obj(st.house).turn_seconds, 20), left != null && left < 5 ? BAD : th.accent, null, { width: 7 });
        }
        const hands = arr(seat.hands);
        const bet = hands.length ? hands.reduce((a, h) => a + num(h.bet), 0) : num(seat.bet);
        const entries = arr(sb.main).filter((e) => String(e.seat) === String(seat.seat));
        if (entries.length) spotChips(S, g, `main`, entries.map((e) => ({ ...e, amount: bet || e.amount })), x, y, t, { r: 30 });
        else if (bet) chip(g, x, y, 30, p.color, shortAmt(bet));
        // the hands, toward the dealer
        const dx = BJ_C[0] - x;
        const dy = BJ_C[1] - y;
        const dl = Math.hypot(dx, dy) || 1;
        hands.forEach((h, hi) => {
          const off = (hi - (hands.length - 1) / 2) * 120;
          const hx = x + (dx / dl) * 170 + off;
          const hy = y + (dy / dl) * 170;
          const cs = arr(h.cards);
          cs.forEach((c, ci) => {
            const cx = hx - (cs.length - 1) * 13 + ci * 26;
            const cy = hy - ci * 8;
            const f = cardFly(S, `s${seat.seat}h${hi}c${ci}`, BJ_SHOE[0], BJ_SHOE[1], cx, cy, t, 0.5);
            drawCard(S, g, c, f.x, f.y, 84, 118, { flip: f.flip, rot: (h.doubled && ci === 2 ? Math.PI / 2 : 0) + f.rot, dim: h.status === "bust" || h.status === "surrender" ? 0.35 : 0 });
          });
          if (cs.length) {
            const tag = h.bj ? "BLACKJACK" : h.status === "bust" ? `BUST ${h.total}` : h.status === "surrender" ? "SURRENDER" : `${h.soft ? `${h.total - 10}/` : ""}${h.total}`;
            const col = h.bj ? th.accent : h.status === "bust" ? BAD : "rgba(0,0,0,.75)";
            const isHand = isTurn && num(turn.hand) === hi;
            pill(g, tag, hx, hy - 96 - (cs.length - 1) * 8, 22, col, h.bj ? th.ink : "#fff", { align: "center", stroke: isHand ? th.accent : null });
            if (h.doubled) pill(g, "DOUBLE", hx, hy + 82, 16, rgba(th.accent, 0.9), th.ink, { align: "center" });
          }
        });
        if (num(seat.insurance)) pill(g, `INSURED ${fmt(S, seat.insurance)}`, x, y - 70, 16, "#1f5fe0", "#fff", { align: "center" });
        // the name plate
        avatar(S, g, x - 70, y + 86, 22, p, { glow: isTurn });
        txt(g, p.name || `P${seat.seat}`, x - 40, y + 95, 26, p.color, { weight: 800, maxW: 150 });
        if (seat.net != null && st.phase === "result") {
          const k = easeOut((S.clk.since(t) - 0.3) / 0.4);
          pill(g, seat.net > 0 ? `WIN ${signed(S, seat.net)}` : seat.net < 0 ? `LOSE ${fmt(S, -seat.net)}` : "PUSH", x, y + 140 - (1 - k) * 20, 22, seat.net > 0 ? OK : seat.net < 0 ? "rgba(255,77,94,.9)" : "#6a6a78", seat.net > 0 ? "#05210f" : "#fff", { align: "center" });
        }
      });
      if (!n) txt(g, "Waiting for players — scan the code to sit down", 760, 640, 32, INK2, { align: "center", weight: 650 });
      drawHeadline(S, g, 70, 210, 560, t, headline(S, t, (p) => {
        if (p === "dealing" || p === "action") {
          const stage = String(table.stage || "");
          if (stage === "insurance") {
            const ic = S.fx.ins || (S.fx.ins = new Countdown());
            ic.observe(`ins${st.round}`, table.insurance_in, S.ctx.stateAt || t);
            const left = ic.left(t);
            return { title: "INSURANCE?", sub: "The dealer shows an ace", tone: "#4a86ff", ring: left != null ? { frac: left / 12, label: Math.ceil(left - 1e-6), color: "#4a86ff" } : null };
          }
          if (turn.seat != null) {
            const who = playerOf(S, turn.seat);
            return { title: `${who.name || `P${turn.seat}`} TO PLAY`, sub: "Hit, stand, double or split", tone: seatColor(S, turn.seat) };
          }
          if (stage === "dealer") return { title: "DEALER PLAYS", sub: `Dealer ${obj(st.rules).soft17 === "hit" ? "hits" : "stands on"} soft 17`, tone: th.accent_hi };
          return { title: "DEALING…", sub: "", tone: th.accent_hi };
        }
        if (p === "result") return { ...headline(S, t), title: dealer.bj ? "DEALER BLACKJACK" : dealer.total > 21 ? `DEALER BUSTS ${dealer.total}` : `DEALER ${dealer.total || ""}` };
        return null;
      }), { size: 44, ringR: 40 });
    },
  });

  // ================================================================================================ POKER TABLES (hold'em, teen patti)
  const PK = { cx: 760, cy: 500, rx: 560, ry: 300 };
  function pokerSeatXY(i, n) {
    const a = Math.PI / 2 + (i * TAU) / Math.max(1, n);
    return [PK.cx + Math.cos(a) * (PK.rx + 70), PK.cy + Math.sin(a) * (PK.ry + 70), a];
  }
  function pokerSeats(S) {
    const st = S.st;
    const t = obj(st.table);
    if (arr(t.seats).length && st.phase !== "betting" && st.phase !== "idle") return { live: true, seats: arr(t.seats) };
    const sitting = new Set(arr(st.sitting).map(String));
    return {
      live: false,
      seats: S.players.filter((p) => p.online).map((p) => ({ seat: p.seat, name: p.name, color: p.color, stack: p.credits, sitting: sitting.has(String(p.seat)) })),
    };
  }
  function pokerBg(S, g, title) {
    const th = S.th;
    g.beginPath();
    g.ellipse(PK.cx, PK.cy, PK.rx + 34, PK.ry + 34, 0, 0, TAU);
    g.fillStyle = "#1b120c";
    g.shadowColor = "rgba(0,0,0,.7)";
    g.shadowBlur = 50;
    g.fill();
    g.shadowBlur = 0;
    g.beginPath();
    g.ellipse(PK.cx, PK.cy, PK.rx + 30, PK.ry + 30, 0, 0, TAU);
    const lg = g.createLinearGradient(0, PK.cy - PK.ry - 30, 0, PK.cy + PK.ry + 30);
    lg.addColorStop(0, "#3c2a20");
    lg.addColorStop(1, "#160d08");
    g.fillStyle = lg;
    g.fill();
    g.beginPath();
    g.ellipse(PK.cx, PK.cy, PK.rx, PK.ry, 0, 0, TAU);
    feltFill(g, th, PK.cx, PK.cy - 60, PK.rx);
    g.lineWidth = 3;
    g.strokeStyle = rgba(th.accent, 0.6);
    g.stroke();
    g.beginPath();
    g.ellipse(PK.cx, PK.cy, PK.rx - 60, PK.ry - 50, 0, 0, TAU);
    g.lineWidth = 2;
    g.strokeStyle = rgba(th.accent, 0.25);
    g.stroke();
    txt(g, title, PK.cx, PK.cy + 190, 40, rgba(th.accent, 0.18), { align: "center", weight: 900, shadow: false });
  }

  /** One seat round the oval: avatar, name plate with the stack, hole cards (backs, or the showdown), bet chips. */
  function pokerSeat(S, g, t, seat, i, n, o) {
    const th = S.th;
    const [x, y, a] = pokerSeatXY(i, n);
    const p = { ...playerOf(S, seat.seat), color: seat.color || seatColor(S, seat.seat), name: seat.name };
    const out = !!seat.folded || seat.sitting === false;
    const alpha = out ? 0.45 : 1;
    const towardX = PK.cx - x;
    const towardY = PK.cy - y;
    const dl = Math.hypot(towardX, towardY) || 1;
    const ux = towardX / dl;
    const uy = towardY / dl;
    // cards
    const shown = o.showdown ? arr(o.showdown[String(seat.seat)]) : [];
    const ncards = o.ncards;
    if (o.live && !seat.folded) {
      const cw = shown.length ? 92 : 66;
      const ch = shown.length ? 128 : 92;
      for (let c = 0; c < ncards; c++) {
        const cx = x + ux * 125 + (c - (ncards - 1) / 2) * (shown.length ? 64 : 30);
        const cy = y + uy * 125;
        const code = shown[c];
        const f = cardFly(S, `h${seat.seat}c${c}`, PK.cx, PK.cy, cx, cy, t, 0.45);
        if (code) {
          const g2 = o.best && o.best.has(code);
          const ff = cardFly(S, `sd${seat.seat}c${c}`, cx, cy, cx, cy, t, 0.5);
          drawCard(S, g, code, cx, cy - (g2 ? 10 : 0), cw, ch, { flip: ff.flip, rot: (c - (ncards - 1) / 2) * 0.08, glow: g2 ? th.accent : null });
        } else drawCard(S, g, "back", f.x, f.y, cw, ch, { down: true, rot: (c - (ncards - 1) / 2) * 0.12 + f.rot, alpha: f.flip < 1 ? 0.6 + 0.4 * f.flip : 1 });
      }
    }
    // the bet in front
    if (num(seat.bet) > 0 && !(o.finished && S.st.phase === "result")) {
      const bx = x + ux * 225;
      const by = y + uy * 200;
      chip(g, bx, by, 24, p.color, null);
      txt(g, fmt(S, seat.bet), bx + 32, by + 9, 24, INK1, { font: "mono", weight: 800 });
    }
    // avatar + plate
    const winner = o.winners && o.winners.has(String(seat.seat));
    if (seat.turn) {
      const tc = S.fx.turnCd || (S.fx.turnCd = new Countdown());
      const tb = obj(S.st.table);
      tc.observe(`${seat.seat}|${arr(tb.log).length}|${tb.hand}`, tb.turn_in, S.ctx.stateAt || t);
      const left = tc.left(t);
      ring(g, x, y, 58, left == null ? 1 : left / num(tb.turn_span, 20), left != null && left < 5 ? BAD : th.accent, null, { width: 8 });
    }
    if (winner) {
      g.save();
      circle(g, x, y, 62 + 4 * Math.sin(t * 6));
      g.strokeStyle = th.accent;
      g.lineWidth = 6;
      g.shadowColor = th.accent;
      g.shadowBlur = 30;
      g.stroke();
      g.restore();
    }
    avatar(S, g, x, y, 44, p, { alpha, glow: seat.turn || winner });
    const below = Math.sin(a) > -0.35;
    const py = below ? y + 60 : y - 124;
    rr(g, x - 110, py, 220, 64, 14);
    g.fillStyle = seat.turn ? rgba(th.accent, 0.25) : "rgba(8,8,12,.82)";
    g.fill();
    g.lineWidth = 2;
    g.strokeStyle = seat.turn ? th.accent : rgba(p.color, 0.7);
    g.stroke();
    txt(g, p.name || `P${seat.seat}`, x, py + 28, 24, p.color, { align: "center", weight: 800, maxW: 200, alpha });
    txt(g, seat.stack != null ? fmt(S, seat.stack) : "", x, py + 56, 22, INK1, { align: "center", font: "mono", weight: 700, alpha });
    // markers and the last action
    const tags = o.tags ? o.tags(seat) : [];
    tags.forEach((tg, k) => {
      const tx = x + (k % 2 ? -1 : 1) * 56;
      const ty = y - 40 + Math.floor(k / 2) * 30;
      pill(g, tg.text, tx, ty, 16, tg.bg, tg.fg || "#fff", { align: "center" });
    });
    const fl = obj(obj(S.st.table).flash);
    const age = fl.age != null ? num(fl.age) + (t - (S.ctx.stateAt || t)) : 99;
    if (String(fl.seat) === String(seat.seat) && age < 2.6) {
      const k = easeOut(age / 0.25);
      const word = fl.text + (num(fl.amount) && !/FOLD|PACK|CHECK|SEEN/.test(fl.text) ? ` ${fmt(S, fl.amount)}` : "");
      g.save();
      g.globalAlpha = age > 2.1 ? clamp((2.6 - age) / 0.5, 0, 1) : 1;
      pill(g, word, x, (below ? y - 70 : y + 72) - (1 - k) * 20, 26 * (0.8 + 0.2 * k), th.accent, th.ink, { align: "center" });
      g.restore();
    } else if (seat.last && o.live && !(o.finished && S.st.phase === "result")) {
      pill(g, String(seat.last), x, below ? y - 62 : y + 66, 16, "rgba(0,0,0,.7)", INK2, { align: "center" });
    }
    if (seat.folded) txt(g, "FOLDED", x, y + 8, 22, INK2, { align: "center", weight: 900 });
  }

  function pokerLobby(S, g, t, needs) {
    const st = S.st;
    const th = S.th;
    const n = arr(st.sitting).length;
    const left = S.clk.ends.left(t);
    if (left != null) {
      txt(g, "NEXT HAND IN", PK.cx, PK.cy - 40, 30, INK2, { align: "center", weight: 800 });
      txt(g, String(Math.ceil(left - 1e-6)), PK.cx, PK.cy + 60, 110, th.accent, { align: "center", font: "mono", weight: 800, glow: rgba(th.accent, 0.5) });
    } else {
      txt(g, n >= 2 ? "DEALING SOON" : "WAITING FOR PLAYERS", PK.cx, PK.cy, 46, th.accent, { align: "center", weight: 900 });
      txt(g, `${n} in · at least two to deal · ${needs}`, PK.cx, PK.cy + 50, 26, INK2, { align: "center", weight: 650 });
    }
  }

  const holdem = makeScene({
    id: "casino-holdem",
    app: "casino_holdem",
    bg(S, g) {
      pokerBg(S, g, "TEXAS HOLD'EM");
    },
    turnSeat: (S) => obj(S.st.table).turn_seat,
    railInfo(S, p) {
      const seat = arr(obj(S.st.table).seats).find((s) => String(s.seat) === String(p.seat));
      if (S.st.phase === "result") {
        const w = winners(S).find((x) => String(x.seat) === String(p.seat));
        if (w) return { text: `WON ${signed(S, num(w.net))}`, color: OK };
      }
      if (seat && S.st.phase !== "betting") return { text: seat.folded ? "FOLDED" : seat.allin ? "ALL-IN" : `IN · ${fmt(S, seat.total)} IN THE POT`, color: seat.folded ? INK3 : INK2 };
      return { text: arr(S.st.sitting).some((s) => String(s) === String(p.seat)) ? "DEALT IN NEXT HAND" : "SITTING OUT", color: INK3 };
    },
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const tb = obj(st.table);
      const { live, seats } = pokerSeats(S);
      const result = st.phase === "result" || tb.finished;
      const winSet = new Set(arr(tb.winners).map((w) => String(w.seat)));
      const best = new Set();
      if (result) for (const w of arr(tb.winners)) for (const c of arr(w.best)) best.add(c);
      // the board
      const board = live ? arr(tb.board) : [];
      for (let i = 0; i < 5; i++) {
        const x = PK.cx - 2 * 116 + i * 116;
        cardSlot(g, x, PK.cy, 104, 146, rgba("#ffffff", 0.18));
        if (board[i]) {
          const f = cardFly(S, `b${i}`, PK.cx, PK.cy - 260, x, PK.cy, t, 0.5 + i * 0.05);
          drawCard(S, g, board[i], f.x, f.y, 104, 146, { flip: f.flip, glow: best.has(board[i]) ? th.accent : null, dim: result && best.size && !best.has(board[i]) ? 0.35 : 0 });
        }
      }
      if (live) {
        const pots = arr(tb.pots);
        const pot = num(tb.pot);
        chip(g, PK.cx - 90, PK.cy - 125, 26, th.accent, null);
        txt(g, `POT ${fmt(S, pot)}`, PK.cx - 54, PK.cy - 114, 34, INK1, { font: "mono", weight: 800 });
        if (pots.length > 1) txt(g, pots.map((p, i) => `${i ? `Side ${i}` : "Main"} ${fmt(S, p.amount)}`).join(" · "), PK.cx, PK.cy + 116, 22, INK2, { align: "center", weight: 700 });
      } else pokerLobby(S, g, t, `blinds ${arr(tb.blinds).join("/") || "–"}`);
      const showdown = obj(tb.showdown);
      seats.forEach((s, i) => {
        pokerSeat(S, g, t, s, i, seats.length, {
          live, ncards: 2, showdown, best, finished: !!tb.finished, winners: result ? winSet : null,
          tags: (seat) => {
            const out = [];
            if (live && String(tb.button_seat) === String(seat.seat)) out.push({ text: "D", bg: "#f6f0e0", fg: "#111" });
            if (live && String(tb.sb_seat) === String(seat.seat)) out.push({ text: "SB", bg: "#1f5fe0" });
            if (live && String(tb.bb_seat) === String(seat.seat)) out.push({ text: "BB", bg: "#d0182f" });
            if (seat.allin) out.push({ text: "ALL-IN", bg: "#ff7419" });
            if (!live && !seat.sitting) out.push({ text: "OUT", bg: "#44444f" });
            return out;
          },
        }); // fmt: skip
      });
      // the headline and the log
      const street = { preflop: "PRE-FLOP", flop: "THE FLOP", turn: "THE TURN", river: "THE RIVER" }[tb.street] || "";
      drawHeadline(S, g, 40, 20, 470, t, headline(S, t, (p) => {
        if (p === "betting") return { title: "NEXT HAND", sub: `Blinds ${arr(tb.blinds).join(" / ")} · hand #${num(tb.hand) + 1}`, tone: th.accent };
        if (p === "locked" || p === "dealing" || p === "action") {
          if (tb.finished) return { title: "SHOWDOWN", sub: street, tone: th.accent };
          const who = tb.turn_seat != null ? playerOf(S, tb.turn_seat) : null;
          return { title: street || "DEALING", sub: who ? `${who.name || `P${tb.turn_seat}`} to act · to call ${fmt(S, tb.cur_bet)}` : "Dealing…", tone: th.accent_hi };
        }
        if (p === "result") {
          const w = arr(tb.winners)[0];
          return { title: w ? `${w.name} WINS ${fmt(S, w.won)}` : "HAND OVER", sub: w && w.hand ? String(w.hand).toUpperCase() : "Everyone else folded", tone: th.accent };
        }
        return null;
      }), { size: 44 });
      txt(g, `HAND #${num(tb.hand)} · BLINDS ${arr(tb.blinds).join("/")}`, 1500, 50, 22, INK2, { align: "right", weight: 800 });
      arr(tb.log).slice(-5).forEach((line, i, all) => txt(g, line, 40, 960 - (all.length - 1 - i) * 30, 22, i === all.length - 1 ? INK1 : INK3, { weight: 650 }));
    },
  });

  const teenpatti = makeScene({
    id: "casino-teenpatti",
    app: "casino_teenpatti",
    bg(S, g) {
      pokerBg(S, g, "TEEN PATTI");
    },
    turnSeat: (S) => obj(S.st.table).turn_seat,
    railInfo(S, p) {
      const seat = arr(obj(S.st.table).seats).find((s) => String(s.seat) === String(p.seat));
      if (S.st.phase === "result") {
        const w = winners(S).find((x) => String(x.seat) === String(p.seat));
        if (w) return { text: `WON ${signed(S, num(w.net))}`, color: OK };
      }
      if (seat && S.st.phase !== "betting") return { text: seat.folded ? "PACKED" : `${seat.seen ? "SEEN" : "BLIND"} · ${fmt(S, seat.total)} IN`, color: seat.folded ? INK3 : INK2 };
      return { text: arr(S.st.sitting).some((s) => String(s) === String(p.seat)) ? "DEALT IN NEXT HAND" : "SITTING OUT", color: INK3 };
    },
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const tb = obj(st.table);
      const { live, seats } = pokerSeats(S);
      const result = st.phase === "result" || tb.finished;
      const winSet = new Set(arr(tb.winners).map((w) => String(w.seat)));
      if (live) {
        chip(g, PK.cx - 80, PK.cy - 20, 30, th.accent, null);
        txt(g, `POT ${fmt(S, tb.pot)}`, PK.cx - 38, PK.cy - 6, 40, INK1, { font: "mono", weight: 800 });
        txt(g, `BOOT ${fmt(S, tb.boot)} · STAKE ${fmt(S, tb.stake)}`, PK.cx, PK.cy + 44, 24, INK2, { align: "center", weight: 750 });
        const hands = obj(tb.hands);
        if (result && Object.keys(hands).length) {
          txt(g, Object.entries(hands).map(([s, h]) => `${playerOf(S, s).name || `P${s}`}: ${h}`).join("   ·   "), PK.cx, PK.cy + 90, 24, th.accent_hi, { align: "center", weight: 750, maxW: 900 });
        }
      } else pokerLobby(S, g, t, `boot ${fmt(S, num(st.buy_in))}`);
      seats.forEach((s, i) => {
        pokerSeat(S, g, t, s, i, seats.length, {
          live, ncards: 3, showdown: obj(tb.showdown), best: null, finished: !!tb.finished, winners: result ? winSet : null,
          tags: (seat) => {
            const out = [];
            if (live && seat.dealer) out.push({ text: "D", bg: "#f6f0e0", fg: "#111" });
            if (live && !seat.folded) out.push(seat.seen ? { text: "SEEN", bg: "#1f5fe0" } : { text: "BLIND", bg: "#44444f" });
            if (seat.allin) out.push({ text: "ALL-IN", bg: "#ff7419" });
            if (!live && !seat.sitting) out.push({ text: "OUT", bg: "#44444f" });
            return out;
          },
        }); // fmt: skip
      });
      // events: side shows and shows
      const ss = tb.sideshow;
      const ev = obj(tb.event);
      let banner = null;
      if (ss) banner = `${playerOf(S, ss.from).name || "?"} asks ${playerOf(S, ss.to).name || "?"} for a SIDESHOW · ${num(ss.in)}s`;
      else if (ev.kind === "sideshow") banner = `SIDESHOW: ${playerOf(S, ev.loser).name || "?"} packs`;
      else if (ev.kind === "refused") banner = `${playerOf(S, ev.with).name || "?"} refused the sideshow`;
      else if (ev.kind === "show") banner = ev.tie ? "SHOW — a tie: the asker loses" : `SHOW — ${playerOf(S, ev.winner).name || "?"} wins it`;
      if (banner && live) pill(g, banner, PK.cx, PK.cy - 120, 26, rgba(th.accent, 0.92), th.ink, { align: "center" });
      drawHeadline(S, g, 40, 20, 470, t, headline(S, t, (p) => {
        if (p === "betting") return { title: "NEXT HAND", sub: `Boot ${fmt(S, num(st.buy_in))} · hand #${num(tb.hand) + 1}`, tone: th.accent };
        if (p === "locked" || p === "dealing" || p === "action") {
          if (tb.finished) return { title: "SHOW", sub: "", tone: th.accent };
          const who = tb.turn_seat != null ? playerOf(S, tb.turn_seat) : null;
          return { title: who ? `${who.name || `P${tb.turn_seat}`} TO ACT` : "DEALING", sub: "Chaal, raise, show or pack", tone: who ? seatColor(S, tb.turn_seat) : th.accent_hi };
        }
        if (p === "result") {
          const w = arr(tb.winners)[0];
          return { title: w ? `${w.name} WINS ${fmt(S, w.won)}` : "HAND OVER", sub: w && w.hand ? String(w.hand).toUpperCase() : "Everyone else packed", tone: th.accent };
        }
        return null;
      }), { size: 44 });
      txt(g, `HAND #${num(tb.hand)}`, 1500, 50, 22, INK2, { align: "right", weight: 800 });
      arr(tb.log).slice(-5).forEach((line, i, all) => txt(g, line, 40, 960 - (all.length - 1 - i) * 30, 22, i === all.length - 1 ? INK1 : INK3, { weight: 650 }));
    },
  });

  // ================================================================================================ HOUSIE
  const HB = { x: 40, y: 120, cw: 86, ch: 92 };
  const HBALL = [1190, 290];
  function housieCell(n) {
    const i = n - 1;
    return [HB.x + (i % 10) * HB.cw, HB.y + Math.floor(i / 10) * HB.ch];
  }
  function ball(g, x, y, r, n, color) {
    g.save();
    g.shadowColor = "rgba(0,0,0,.6)";
    g.shadowBlur = r * 0.4;
    g.shadowOffsetY = r * 0.1;
    circle(g, x, y, r);
    const gr = g.createRadialGradient(x - r * 0.35, y - r * 0.4, r * 0.1, x, y, r);
    gr.addColorStop(0, shade(color, 1.5));
    gr.addColorStop(0.6, color);
    gr.addColorStop(1, shade(color, 0.5));
    g.fillStyle = gr;
    g.fill();
    g.restore();
    circle(g, x, y, r * 0.62);
    g.fillStyle = "#fbf8f1";
    g.fill();
    txt(g, String(n), x, y + r * 0.22, r * (n >= 10 ? 0.6 : 0.72), "#15151c", { align: "center", weight: 900, shadow: false });
  }
  const housieColor = (n) => ["#e0263c", "#ff7419", "#e0a800", "#3ddc84", "#33d1ff", "#1f6fff", "#a64dff", "#ff3f78", "#12b35a"][Math.min(8, Math.floor(n / 10))];
  const housie = makeScene({
    id: "casino-housie",
    app: "casino_housie",
    ingest(S, st, t) {
      const h = obj(st.housie);
      const called = num(h.called);
      if (S.fx.called !== called) {
        if (called > num(S.fx.called) && !S.firstIngest) S.fx.callAt = t;
        S.fx.called = called;
      }
      // call_in is exact to 0.1 s: the next call is due at stateAt + call_in
      S.fx.nextCall = typeof h.call_in === "number" ? t + h.call_in : null;
    },
    bg(S, g) {
      const th = S.th;
      rr(g, 18, 18, RAIL_X - 34, SH - 36, 60);
      feltFill(g, th, 760, 480, 1100);
      railStroke(g, th, 18);
      rr(g, HB.x - 10, HB.y - 10, 10 * HB.cw + 20, 9 * HB.ch + 20, 18);
      g.fillStyle = "rgba(0,0,0,.35)";
      g.fill();
      for (let n = 1; n <= 90; n++) {
        const [x, y] = housieCell(n);
        rr(g, x + 4, y + 4, HB.cw - 8, HB.ch - 8, 12);
        g.fillStyle = "rgba(255,255,255,.05)";
        g.fill();
        txt(g, String(n), x + HB.cw / 2, y + HB.ch / 2 + 13, 36, "rgba(255,255,255,.28)", { align: "center", weight: 800, shadow: false });
      }
      txt(g, "HOUSIE", HB.x, 92, 44, th.accent, { weight: 900 });
      txt(g, "PRIZES", 950, 560, 20, INK3, { weight: 800, shadow: false });
    },
    railInfo(S, p) {
      const b = arr(obj(S.st.housie).buyers).find((x) => String(x.seat) === String(p.seat));
      const won = arr(obj(S.st.housie).prizes).filter((pr) => arr(pr.winners).some((w) => String(w.seat) === String(p.seat)));
      if (won.length) return { text: `WON ${won.map((w) => w.name).join(", ")}`, color: OK };
      if (b) return { text: `${b.n} ${b.n === 1 ? "TICKET" : "TICKETS"}`, color: S.th.accent_hi };
      return { text: "", color: INK3 };
    },
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const h = obj(st.housie);
      const calls = arr(h.calls);
      const last = calls[calls.length - 1];
      const callAge = S.fx.callAt != null ? t - S.fx.callAt : 9;
      const set = new Set(calls);
      txt(g, `${calls.length} / 90 CALLED`, HB.x + 10 * HB.cw, 92, 26, INK2, { align: "right", font: "mono", weight: 750 });
      for (const n of set) {
        const [x, y] = housieCell(n);
        const isLast = n === last;
        const k = isLast ? easeOut(callAge / 0.5) : 1;
        rr(g, x + 4, y + 4, HB.cw - 8, HB.ch - 8, 12);
        g.fillStyle = isLast ? th.accent : rgba(housieColor(n), 0.85);
        g.save();
        if (isLast) {
          g.shadowColor = th.accent;
          g.shadowBlur = 30 * (0.6 + 0.4 * Math.sin(t * 5));
        }
        g.globalAlpha = k;
        g.fill();
        g.restore();
        txt(g, String(n), x + HB.cw / 2, y + HB.ch / 2 + 13, 38, isLast ? th.ink : "#fff", { align: "center", weight: 900, shadow: false });
      }
      // the ball and the caller
      const ph = st.phase;
      if (ph === "dealing" || ph === "result") {
        if (last != null) {
          const k = easeOut(callAge / 0.6);
          const bounce = callAge < 0.8 ? Math.abs(Math.sin(callAge * 9)) * (1 - callAge / 0.8) * 40 : 0;
          ball(g, HBALL[0], HBALL[1] - (1 - k) * 200 - bounce, 140, last, housieColor(last));
          const left = S.fx.nextCall != null ? Math.max(0, S.fx.nextCall - t) : null;
          if (left != null && ph === "dealing" && !h.finished) {
            g.beginPath();
            g.arc(HBALL[0], HBALL[1], 162, -Math.PI / 2, -Math.PI / 2 + TAU * clamp(1 - left / num(h.pace, 6), 0, 1));
            g.lineWidth = 8;
            g.strokeStyle = rgba(th.accent, 0.8);
            g.stroke();
          }
          txt(g, HOUSIE_NAMES[last] || `Number ${last}`, HBALL[0], HBALL[1] + 200, 30, th.accent_hi, { align: "center", weight: 750 });
        } else {
          const fl = h.first_in != null ? `FIRST CALL IN ${h.first_in}` : "LOOK AT YOUR TICKETS";
          txt(g, fl, HBALL[0], HBALL[1], 40, th.accent, { align: "center", weight: 900 });
        }
        calls.slice(-7, -1).reverse().forEach((n, i) => ball(g, 1000 + i * 82, 520 - 0, 32, n, housieColor(n)));
      } else if (ph === "locked") {
        txt(g, "TICKETS ARE DEALT", HBALL[0], HBALL[1], 40, th.accent, { align: "center", weight: 900 });
      } else {
        drawHeadline(S, g, 950, 140, 550, t, headline(S, t, (p) => {
          if (p === "betting") {
            const left = S.clk.ends.left(t);
            const span = num(obj(st.rules).buy_seconds, 45);
            return { title: "BUY TICKETS", sub: `${fmt(S, h.price)} a ticket · up to ${num(h.max, 1)} each`, tone: th.accent, pulse: st.ends_in == null, ring: left != null ? { frac: left / span, label: Math.ceil(left - 1e-6), color: left < 6 ? BAD : th.accent } : null };
          }
          return null;
        }), { size: 56 });
        txt(g, "POT", 950, 360, 22, INK3, { weight: 800, shadow: false });
        txt(g, fmt(S, h.pot), 950, 430, 72, INK1, { font: "mono", weight: 800 });
        txt(g, `${num(h.sold)} tickets sold`, 950, 470, 26, INK2, { weight: 650 });
      }
      // prizes
      arr(h.prizes).forEach((pr, i) => {
        const y = 580 + i * 50;
        const won = pr.state === "won" || pr.state === "claimed";
        rr(g, 950, y, 550, 44, 10);
        g.fillStyle = won ? rgba(th.accent, 0.2) : "rgba(0,0,0,.28)";
        g.fill();
        txt(g, pr.name, 966, y + 31, 24, won ? th.accent_hi : INK1, { weight: 800 });
        txt(g, fmt(S, pr.amount), 1240, y + 31, 24, INK1, { align: "right", font: "mono", weight: 750 });
        const ws = arr(pr.winners);
        if (ws.length) {
          let x = 1262;
          ws.slice(0, 3).forEach((w) => {
            circle(g, x + 10, y + 22, 10);
            g.fillStyle = w.color || seatColor(S, w.seat);
            g.fill();
            txt(g, w.name || `P${w.seat}`, x + 26, y + 30, 20, w.color || INK1, { weight: 750, maxW: 70 });
            x += 80;
          });
        } else txt(g, pr.state === "open" ? "OPEN" : "", 1490, y + 30, 18, INK3, { align: "right", weight: 800 });
      });
      // the claim flash
      const fl = obj(h.flash);
      const age = fl.age != null ? num(fl.age) + (t - (S.ctx.stateAt || t)) : 99;
      if (fl.name && age < 4) {
        const k = easeOut(age / 0.3);
        g.save();
        g.globalAlpha = age > 3.4 ? (4 - age) / 0.6 : 1;
        rr(g, HB.x + 60, 400 - (1 - k) * 40, 740, 160, 26);
        g.fillStyle = "rgba(10,10,14,.92)";
        g.fill();
        g.lineWidth = 4;
        g.strokeStyle = fl.color || th.accent;
        g.stroke();
        txt(g, String(fl.name).toUpperCase(), HB.x + 430, 470 - (1 - k) * 40, 54, th.accent, { align: "center", weight: 900, glow: rgba(th.accent, 0.6) });
        txt(g, `${fl.who || "?"} claims it!`, HB.x + 430, 520 - (1 - k) * 40, 34, fl.color || INK1, { align: "center", weight: 800 });
        g.restore();
      }
      arr(h.bogeys).filter((b) => num(b.age) < 6).slice(-1).forEach((b) => pill(g, `BOGEY! ${b.name} — false ${b.prize} claim`, HB.x + 430, 960, 22, "rgba(255,77,94,.92)", "#fff", { align: "center" }));
      if (ph === "result") winnersCard(S, g, 950, 140, 550, t, { delay: 0.6, max: 4, empty: "Unclaimed prizes went back to the tickets" });
    },
  });

  // ================================================================================================ SLOTS
  const SL = { x: 360, y: 60, w: 820, h: 880, cell: 170, rx: 425, ry: 300 };
  function slotSprite(S, ch, px) {
    const m = obj(S.st.machine);
    const key = `${m.theme}|${ch}|${px}|${S.k}`;
    S.fx.sprites = S.fx.sprites || new Map();
    let c = S.fx.sprites.get(key);
    if (c) return c;
    const sp = obj(m.sprites).symbols ? m.sprites : obj(S.fx.lastSprites);
    const rows = arr(obj(sp.symbols)[ch]);
    const pal = arr(sp.palette);
    const n = Math.max(1, rows.length);
    const mm = makeCanvas(n * px, n * px, S.k);
    rows.forEach((row, j) => {
      for (let i = 0; i < row.length; i++) {
        const v = row[i];
        if (v === ".") continue;
        const col = pal[parseInt(v, 36)];
        if (!col) continue;
        mm.g.save();
        mm.g.shadowColor = col;
        mm.g.shadowBlur = px * 0.5;
        rr(mm.g, i * px + 1, j * px + 1, px - 2, px - 2, px * 0.28);
        mm.g.fillStyle = col;
        mm.g.fill();
        mm.g.restore();
      }
    });
    if (!rows.length && ch !== "_") txt(mm.g, ch, (n * px) / 2, (n * px) / 2 + 20, 60, "#fff", { align: "center" });
    S.fx.sprites.set(key, mm.c);
    return mm.c;
  }
  const slots = makeScene({
    id: "casino-slots",
    app: "casino_slots",
    init(S) {
      S.fx = { spin: null, reels: [null, null, null] };
    },
    ingest(S, st, t) {
      const p = st.playing;
      const fx = S.fx;
      const sp = obj(obj(st.machine).sprites);
      if (sp.symbols) fx.lastSprites = sp;
      if (p && typeof p.t === "number") {
        if (!fx.spin || fx.spin.id !== p.id) {
          fx.spin = { id: p.id, start: t - p.t, seat: p.seat };
          fx.reels = [null, null, null];
          fx.winAt = null;
        } else {
          const est = t - p.t;
          if (Math.abs(est - fx.spin.start) < 0.6) fx.spin.start += (est - fx.spin.start) * 0.3;
        }
        if (p.win != null && fx.winAt == null) fx.winAt = t;
      }
    },
    bgKey: (S) => String(obj(S.st.machine).theme || ""),
    bg(S, g) {
      const th = S.th;
      const m = obj(S.st.machine);
      rr(g, 18, 18, RAIL_X - 34, SH - 36, 60);
      feltFill(g, th, 760, 480, 1100);
      railStroke(g, th, 18);
      // the cabinet
      rr(g, SL.x, SL.y, SL.w, SL.h, 48);
      const cg = g.createLinearGradient(SL.x, 0, SL.x + SL.w, 0);
      cg.addColorStop(0, "#1a1a22");
      cg.addColorStop(0.5, "#3a3a46");
      cg.addColorStop(1, "#16161c");
      g.fillStyle = cg;
      g.shadowColor = "rgba(0,0,0,.7)";
      g.shadowBlur = 50;
      g.fill();
      g.shadowBlur = 0;
      g.lineWidth = 6;
      g.strokeStyle = th.accent;
      g.stroke();
      rr(g, SL.x + 40, SL.y + 30, SL.w - 80, 150, 30);
      const mg = g.createLinearGradient(0, SL.y + 30, 0, SL.y + 180);
      mg.addColorStop(0, shade(th.accent, 0.5));
      mg.addColorStop(1, th.accent_deep);
      g.fillStyle = mg;
      g.fill();
      txt(g, String(m.name || "SLOTS").toUpperCase(), SL.x + SL.w / 2, SL.y + 128, 64, th.accent_hi, { align: "center", weight: 900, glow: th.accent });
      rr(g, SL.rx - 20, SL.ry - 20, 3 * 230 + 40 - 40, 3 * SL.cell + 40, 22);
      g.fillStyle = "#08080b";
      g.fill();
      for (let i = 0; i < 3; i++) {
        rr(g, SL.rx + i * 230, SL.ry, 210, 3 * SL.cell, 14);
        const rg = g.createLinearGradient(0, SL.ry, 0, SL.ry + 3 * SL.cell);
        rg.addColorStop(0, "#9a9aa4");
        rg.addColorStop(0.18, "#f4f1ea");
        rg.addColorStop(0.82, "#f4f1ea");
        rg.addColorStop(1, "#9a9aa4");
        g.fillStyle = rg;
        g.fill();
      }
      for (let l = 1; l <= 5; l++) {
        const y = SL.ry + [1.5, 0.5, 2.5, 0.2, 2.8][l - 1] * SL.cell;
        pill(g, String(l), SL.rx - 44, y, 18, rgba(LINE_COLORS[l - 1], 0.9), "#111", { align: "center" });
      }
      // the lever
      rr(g, SL.x + SL.w + 6, 380, 26, 200, 12);
      g.fillStyle = "#2a2a32";
      g.fill();
      // pay table
      txt(g, "PAYS (× BET PER LINE)", 40, 92, 20, INK3, { weight: 800, shadow: false });
      const three = obj(m.three);
      Object.keys(three).forEach((ch, i) => {
        const y = 120 + i * 82;
        for (let k = 0; k < 3; k++) g.drawImage(slotSprite(S, ch, 8), 40 + k * 64, y, 56, 56);
        txt(g, `× ${three[ch]}`, 240, y + 40, 30, INK1, { font: "mono", weight: 800 });
      });
      const gy = 120 + Object.keys(three).length * 82;
      arr(m.groups).forEach((gr, i) => txt(g, `${gr[0]}  × ${gr[2]}`, 40, gy + 20 + i * 34, 24, INK2, { weight: 700 }));
      const lead = obj(m.lead);
      Object.keys(lead).forEach((k, i) => txt(g, `${k} × ${obj(m.names)[m.lead_symbol] || m.lead_symbol}  × ${lead[k]}`, 40, gy + 20 + (arr(m.groups).length + i) * 34, 24, INK2, { weight: 700 }));
      txt(g, `RTP ${(num(m.rtp) * 100).toFixed(2)} % · HIT ${(num(m.hit) * 100).toFixed(0)} %`, 40, 940, 22, th.accent, { weight: 800 });
      txt(g, "UP NEXT", 1220, 92, 20, INK3, { weight: 800, shadow: false });
      txt(g, "RECENT SPINS", 1220, 520, 20, INK3, { weight: 800, shadow: false });
    },
    railInfo(S, p) {
      const st = S.st;
      if (st.playing && String(st.playing.seat) === String(p.seat)) return { text: st.playing.win != null ? (st.playing.win ? `WON ${fmt(S, st.playing.win)}` : "NO WIN") : "SPINNING", color: S.th.accent_hi };
      if (arr(st.queue).some((q) => String(q.seat) === String(p.seat))) return { text: "IN THE QUEUE", color: INK2 };
      const r = arr(st.recent).find((q) => String(q.seat) === String(p.seat));
      if (r && r.win) return { text: `LAST WIN ${fmt(S, r.win)}`, color: OK };
      return { text: "", color: INK3 };
    },
    turnSeat: (S) => (S.st.playing ? S.st.playing.seat : null),
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const fx = S.fx;
      const m = obj(st.machine);
      const strips = arr(m.strips).map(String);
      const p = st.playing;
      const recent = arr(st.recent);
      const spinT = p && fx.spin && fx.spin.id === p.id ? t - fx.spin.start : null;
      const lastStops = p ? null : recent.length ? arr(recent[0].stops) : null;
      const pos = [0, 1, 2].map((i) => {
        const n = Math.max(1, (strips[i] || "").length);
        if (p && spinT != null) {
          const stop = arr(p.stops)[i];
          if (stop == null) {
            if (fx.reels[i]) return fx.reels[i].from;
            return (hash01(`r${p.id}${i}`) * n) - 9 * Math.max(0, spinT); // free spin until the stop is public
          }
          if (spinT < SLOT_STOPS[i] + 0.6 && !fx.reels[i]) {
            const free = hash01(`r${p.id}${i}`) * n - 9 * Math.max(0, Math.min(spinT, SLOT_STOPS[i]));
            fx.reels[i] = { from: free, t0: t, stop };
          }
          if (fx.reels[i]) {
            const R = fx.reels[i];
            const u = clamp((t - R.t0) / 0.32, 0, 1);
            let target = R.stop;
            while (target > R.from) target -= n;
            const k = 1 - Math.pow(1 - u, 3);
            const wob = u >= 1 ? 0.3 * Math.exp(-(t - R.t0 - 0.32) * 9) * Math.sin((t - R.t0 - 0.32) * 26) : 0;
            return u >= 1 ? stop + wob : lerp(R.from, target, k);
          }
          return reelPos(stop, n, spinT, i);
        }
        if (lastStops && lastStops[i] != null) return lastStops[i];
        return 0;
      });
      // the reels
      for (let i = 0; i < 3; i++) {
        const strip = strips[i] || "";
        const n = Math.max(1, strip.length);
        const x = SL.rx + i * 230;
        g.save();
        rr(g, x, SL.ry, 210, 3 * SL.cell, 14);
        g.clip();
        const base = Math.floor(pos[i]);
        const frac = pos[i] - base;
        const moving = p && spinT != null && (arr(p.stops)[i] == null || (fx.reels[i] && t - fx.reels[i].t0 < 0.3));
        for (let r = -2; r <= 2; r++) {
          const idx = mod(base + r, n);
          const ch = strip[idx] || "_";
          const y = SL.ry + (1 + r - frac) * SL.cell + SL.cell / 2;
          if (ch !== "_") {
            g.save();
            if (moving) g.globalAlpha = 0.7;
            g.drawImage(slotSprite(S, ch, 20), x + 105 - 70, y - 70, 140, 140);
            g.restore();
          }
        }
        const shadeG = g.createLinearGradient(0, SL.ry, 0, SL.ry + 3 * SL.cell);
        shadeG.addColorStop(0, "rgba(0,0,0,.45)");
        shadeG.addColorStop(0.2, "rgba(0,0,0,0)");
        shadeG.addColorStop(0.8, "rgba(0,0,0,0)");
        shadeG.addColorStop(1, "rgba(0,0,0,.45)");
        g.fillStyle = shadeG;
        g.fillRect(x, SL.ry, 210, 3 * SL.cell);
        g.restore();
      }
      // winning lines
      const winLines = p && p.win != null ? arr(p.wins) : [];
      if (winLines.length && spinT != null && spinT > SLOT_STOPS[2]) {
        winLines.forEach((w, k) => {
          const li = num(w.line, 1) - 1;
          const rows = SLOT_LINES[li] || SLOT_LINES[0];
          const on = Math.floor(t * 2.5) % winLines.length === k || winLines.length === 1;
          g.save();
          g.globalAlpha = on ? 1 : 0.35;
          g.beginPath();
          rows.forEach((row, i) => {
            const x = SL.rx + i * 230 + 105;
            const y = SL.ry + row * SL.cell + SL.cell / 2;
            if (i) g.lineTo(x, y);
            else g.moveTo(x - 120, y);
          });
          g.lineTo(SL.rx + 2 * 230 + 225, SL.ry + rows[2] * SL.cell + SL.cell / 2);
          g.lineWidth = 8;
          g.strokeStyle = LINE_COLORS[li] || th.accent;
          g.shadowColor = LINE_COLORS[li] || th.accent;
          g.shadowBlur = 20;
          g.stroke();
          g.restore();
        });
      }
      // the lever knob (pulled at the start of a spin)
      const pull = spinT != null && spinT < 0.6 ? Math.sin((spinT / 0.6) * Math.PI) : 0;
      circle(g, SL.x + SL.w + 19, 360 + pull * 220, 30);
      g.fillStyle = "#d0182f";
      g.fill();
      // the credit panel
      rr(g, SL.x + 60, 840, SL.w - 120, 76, 14);
      g.fillStyle = "#050507";
      g.fill();
      if (p) {
        txt(g, p.name || `P${p.seat}`, SL.x + 84, 890, 32, p.color || seatColor(S, p.seat), { weight: 850, maxW: 260 });
        txt(g, `BET ${fmt(S, p.bet)} × ${num(p.lines, 1)} = ${fmt(S, p.stake)}`, SL.x + SL.w / 2 + 10, 890, 26, INK2, { align: "center", font: "mono", weight: 700 });
        if (p.win != null) txt(g, p.win ? `WIN ${fmt(S, p.win)}` : "NO WIN", SL.x + SL.w - 84, 892, 34, p.win ? OK : INK3, { align: "right", font: "mono", weight: 850, glow: p.win ? OK : null });
      } else txt(g, arr(st.queue).length ? "NEXT SPIN COMING UP" : "PULL THE LEVER ON YOUR PHONE", SL.x + SL.w / 2, 890, 30, th.accent, { align: "center", weight: 850, alpha: 0.7 + 0.3 * Math.sin(t * 3) });
      // big win
      if (p && p.win && p.win >= 20 * num(p.stake, 1) && fx.winAt != null) {
        const k = easeOut((t - fx.winAt) / 0.4);
        bulbs(g, SL.x + 10, SL.y + 10, SL.w - 20, SL.h - 20, t, th.accent, 60);
        txt(g, "BIG WIN!", SL.x + SL.w / 2, SL.ry + 1.5 * SL.cell + 30, 120 * k, th.accent_hi, { align: "center", weight: 900, glow: th.accent });
      } else if (p && p.win && fx.winAt != null) bulbs(g, SL.x + 10, SL.y + 10, SL.w - 20, SL.h - 20, t, th.accent, 40);
      // queue and recent
      arr(st.queue).slice(0, 5).forEach((q, i) => {
        const y = 112 + i * 76;
        avatar(S, g, 1250, y + 30, 24, { ...playerOf(S, q.seat), color: q.color });
        txt(g, q.name || `P${q.seat}`, 1286, y + 30, 26, q.color || INK1, { weight: 800, maxW: 170 });
        txt(g, `${fmt(S, q.stake)} stake`, 1286, y + 58, 20, INK3, { weight: 650 });
      });
      if (!arr(st.queue).length) txt(g, "Nobody waiting", 1220, 140, 24, INK3, { weight: 650 });
      recent.slice(0, 5).forEach((q, i) => {
        const y = 540 + i * 76;
        avatar(S, g, 1250, y + 30, 24, { ...playerOf(S, q.seat), color: q.color });
        txt(g, q.name || `P${q.seat}`, 1286, y + 30, 26, q.color || INK1, { weight: 800, maxW: 170 });
        txt(g, q.win ? `won ${fmt(S, q.win)}` : "no win", 1286, y + 58, 20, q.win ? OK : INK3, { weight: 700 });
      });
    },
  });

  // ================================================================================================ register
  const SCENES = [roulette, blackjack, baccarat, slots, holdem, teenpatti, andarbahar, bigsix, sevens, housie];
  const API = {
    SCENES, Countdown, PhaseTracker, lockTime, parseCard, baccaratTotal, rouletteCovers, rouletteBoard, rouletteSpotXY,
    rouletteCenter, reelPos, settle, bigRoad, hash01, hexRgb, shade, wrapPi, bjSeatXY, pokerSeatXY, EU_WHEEL, US_WHEEL,
    B6_WHEEL, B6, travelExp,
  }; // fmt: skip
  if (TV) {
    TV.casino = API;
    if (typeof TV.registerScene === "function") for (const s of SCENES) TV.registerScene(s);
  }
})();
