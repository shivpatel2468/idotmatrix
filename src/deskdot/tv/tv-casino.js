/* DeskDot TV view — the casino tables (docs/TV_VIEW.md §4, docs/CASINO.md).
 *
 * One bespoke 1920×984 broadcast scene per casino game: roulette, blackjack, baccarat, slots, Texas hold'em,
 * teen patti, andar bahar, big six, 7 up 7 down and housie. Each scene is a table layer redrawn only when something on
 * it changed, over a cached background (felt, printed layout, rail), with the moving parts (wheels, balls, dice,
 * reels, stamps, countdown rings) in small canvases of their own moved by transforms, in the table's theme
 * (status.table_theme → ctx.theme), plus the live panel as a small inset in the right-hand rail. Chips follow the
 * table's chip ladder (status.chips). The lite tier (TV.quality) drops blurred shadows and glows (docs/TV_VIEW.md §6).
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

  /** The lite tier (tv.js TV.quality): no blurred shadows / glows, fewer particles, canvases at 3/4 resolution. */
  const lite = () => !!(TV && TV.quality === "lite");
  /** A soft glow / shadow — hq only (shadowBlur is the most expensive thing a canvas does on a TV stick). */
  function glowOn(g, color, blur, oy) {
    if (lite()) return false;
    g.shadowColor = color;
    g.shadowBlur = blur;
    if (oy) g.shadowOffsetY = oy;
    return true;
  }

  // ================================================================================================ the chip ladder
  // casino/chips.py LADDER / chip_rack / break_into, copied (docs/CASINO.md §5): the TV reads status.chips and falls
  // back to this when an older engine doesn't send it. value, label, chip colour, edge-stripe colour.
  const LADDER = [
    [1, "1", "#f2efe8", "#2b6cd6"], [5, "5", "#d23a3a", "#ffffff"], [25, "25", "#2e9a55", "#ffffff"],
    [100, "100", "#1c1c22", "#e8e8e8"], [500, "500", "#7b3fc4", "#ffffff"], [1000, "1K", "#f2c230", "#5a3d00"],
    [2000, "2K", "#e85d9f", "#ffffff"], [5000, "5K", "#c9772b", "#ffffff"], [10000, "10K", "#2f6fd6", "#ffffff"],
    [25000, "25K", "#18a39a", "#ffffff"], [50000, "50K", "#9a2f4d", "#ffd36b"], [100000, "100K", "#c9a227", "#1c1c22"],
    [250000, "250K", "#5b2a86", "#ffd36b"], [500000, "500K", "#0f3d2e", "#ffd36b"], [1000000, "1M", "#111111", "#ffd36b"],
  ]; // fmt: skip
  const RACK_MAX = 7;

  /** A chip amount with K / M (casino/chips.py short): 1000 → 1K, 2500 → 2.5K, 1250 → 1.25K, 750 → 750. */
  function shortChip(v) {
    v = Math.round(num(Number(v)));
    const a = Math.abs(v);
    for (const [unit, suf] of [[1e6, "M"], [1e3, "K"]]) {
      if (a >= unit) return (v / unit).toFixed(2).replace(/0+$/, "").replace(/\.$/, "") + suf;
    }
    return String(v);
  }
  /** Python's round(): halves go to the even neighbour (chip_rack picks its rack with it). */
  function pyRound(x) {
    const f = Math.floor(x);
    const d = x - f;
    if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
    return Math.round(x);
  }
  const chipOf = (c) => ({ v: c[0], label: c[1], color: c[2], edge: c[3] });

  /** casino/chips.py chip_rack: the chips a table offers, smallest first, at most RACK_MAX. */
  function chipRack(minBet, maxBet) {
    const lo = Math.max(1, Math.floor(num(Number(minBet), 1)));
    const hi = Math.max(lo, Math.floor(num(Number(maxBet), lo)));
    const allowed = LADDER.filter((c) => lo <= c[0] && c[0] <= hi).map(chipOf);
    if (!allowed.length || allowed[0].v !== lo) {
      const above = LADDER.find((c) => c[0] > lo) || LADDER[LADDER.length - 1];
      allowed.unshift({ v: lo, label: shortChip(lo), color: above[2], edge: above[3] });
    }
    const n = allowed.length;
    if (n <= RACK_MAX) return allowed;
    const picks = [...new Set(Array.from({ length: RACK_MAX }, (_, i) => pyRound((i * (n - 1)) / (RACK_MAX - 1))))].sort((a, b) => a - b);
    return picks.map((i) => allowed[i]);
  }

  /** The table's rack: status.chips when the engine sends a valid one, else the same rack computed here. */
  function rackOf(st) {
    const c = arr(st && st.chips).filter((x) => x && typeof x.v === "number" && x.v > 0 && typeof x.color === "string");
    if (c.length) return c.map((x) => ({ v: x.v, label: String(x.label || shortChip(x.v)), color: x.color, edge: x.edge || "#ffffff" }));
    const h = obj(st && st.house);
    return chipRack(num(h.min_bet, 1), num(h.max_bet, 500));
  }

  /** An amount as chip values, largest first: greedy over the ladder (plus the rack's off-ladder table minimum). */
  function breakInto(amount, rack) {
    const vals = [...new Set([...LADDER.map((c) => c[0]), ...arr(rack).map((c) => c.v)])].sort((a, b) => b - a);
    const out = [];
    let left = Math.max(0, Math.round(num(Number(amount))));
    for (const v of vals) {
      while (left >= v && out.length < 64) {
        out.push(v);
        left -= v;
      }
    }
    if (left > 0) out.push(left);
    return out;
  }

  /** {color, edge, label} for a chip value: the rack's own chip, else the ladder's, else coloured like the next up. */
  function chipStyle(v, rack) {
    const r = arr(rack).find((c) => c.v === v);
    if (r) return r;
    const l = LADDER.find((c) => c[0] === v);
    if (l) return chipOf(l);
    const above = LADDER.find((c) => c[0] > v) || LADDER[LADDER.length - 1];
    return { v, label: shortChip(v), color: above[2], edge: above[3] };
  }

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

  /**
   * Seconds left to a round timer: to its `status.clock` anchor on the shared clock (so the TV's countdown hits zero
   * with the panel's, the phones' and the studio's), else the whole-second countdown estimate.
   */
  function leftTo(S, key, cd, t) {
    const a = obj(S.st.clock)[key];
    if (typeof a === "number" && S.ctx && typeof S.ctx.serverNow === "function") return Math.max(0, a - S.T);
    return cd.left(t);
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
    const str = String(s);
    let glowing = false;
    if (o.glow) glowing = glowOn(g, o.glow, o.glowBlur || size * 0.45);
    if (!glowing && o.shadow !== false) {
      // a hard drop shadow: the text once more, offset and dark — no blur (a blurred shadow per text is the
      // costliest thing on a TV stick, and at 3 m it reads the same)
      const dy = Math.max(1, size * 0.05);
      const a = g.globalAlpha;
      g.globalAlpha = a * 0.5;
      g.fillStyle = "#000";
      if (o.maxW) g.fillText(str, x, y + dy, o.maxW);
      else g.fillText(str, x, y + dy);
      g.globalAlpha = a;
    }
    g.fillStyle = color;
    if (o.maxW) g.fillText(str, x, y, o.maxW);
    else g.fillText(str, x, y);
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
    glowOn(g, color, 16);
    g.stroke();
    g.restore();
    if (label != null) txt(g, label, x, y + r * 0.2, r * 0.62, INK1, { align: "center", font: "mono", weight: 700 });
  }

  /**
   * A countdown ring that sweeps smoothly: drawn into a small canvas of its own every animation frame (so the big
   * table layer doesn't have to redraw for it). `left` s were left at local time `t` out of `span`; it turns
   * `low` under `lowBelow` s. Rings drawn with hudRing in a table redraw stay; the others are hidden after it.
   */
  function hudRing(S, id, x, y, r, o) {
    S.hud = S.hud || new Map();
    let h = S.hud.get(id);
    const pad = 14;
    const D = 2 * (r + pad);
    if (!h || h.r !== r || h.k !== S.k) {
      if (h) h.l.c.remove();
      const l = layer(S.root, x - D / 2, y - D / 2, D, D, S.k, false);
      h = { l, r, k: S.k, key: "" };
      S.hud.set(id, h);
    }
    if (h.x !== x || h.y !== y) {
      h.l.c.style.left = `${x - D / 2}px`;
      h.l.c.style.top = `${y - D / 2}px`;
      h.x = x;
      h.y = y;
    }
    Object.assign(h, { seen: S.drawGen, t0: S.t, left: o.left, span: o.span || 1, color: o.color, low: o.low || o.color,
      lowBelow: o.lowBelow || 0, label: o.label !== false, width: o.width }); // fmt: skip
    h.l.c.style.display = "";
  }
  /** Every frame: sweep the rings (redrawing one only when it visibly moved); hide the ones no longer drawn. */
  function hudFrame(S, t) {
    if (!S.hud) return;
    for (const h of S.hud.values()) {
      if (h.seen !== S.drawGen) {
        if (h.l.c.style.display !== "none") h.l.c.style.display = "none";
        continue;
      }
      const left = h.left == null ? null : Math.max(0, h.left - (t - h.t0));
      const frac = left == null ? 1 : clamp(left / h.span, 0, 1);
      const label = h.label && left != null ? Math.ceil(left - 1e-6) : null;
      const color = left != null && left < h.lowBelow ? h.low : h.color;
      const key = `${Math.round(frac * (lite() ? 120 : 360))}|${label}|${color}`; // ≈ 1–3 px of arc per step
      if (key === h.key) continue;
      h.key = key;
      const l = h.l;
      l.g.setTransform(l.k, 0, 0, l.k, 0, 0);
      l.g.clearRect(0, 0, l.w, l.h);
      ring(l.g, l.w / 2, l.h / 2, h.r, frac, color, label, { width: h.width });
    }
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
    if (o.glow && !glowOn(g, o.glow, 28)) {
      // lite: a crisp outline instead of the soft glow
      rr(g, -w / 2 - 4, -h / 2 - 4, w + 8, h + 8, w * 0.12);
      g.lineWidth = 4;
      g.strokeStyle = o.glow;
      g.stroke();
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
      if (!S.firstIngest) S.animUntil = Math.max(S.animUntil, t + (dur || 0.55));
      return { x: S.firstIngest ? x : fx, y: S.firstIngest ? y : fy, flip: S.firstIngest ? 1 : 0, rot: 0 };
    }
    return flyAge(S, t - t0, fx, fy, x, y, dur);
  }
  /** A card `age` s into its flight (dur s) from (fx, fy) to (x, y), turning over on the way. */
  function flyAge(S, age, fx, fy, x, y, dur) {
    const d = dur || 0.55;
    if (age < d) S.animUntil = Math.max(S.animUntil, S.t + 0.05);
    const u = clamp(age / d, 0, 1);
    const e = easeOut(u);
    return { x: lerp(fx, x, e), y: lerp(fy, y, e) - Math.sin(u * Math.PI) * 40, flip: clamp((u - 0.35) / 0.65, 0, 1), rot: (1 - e) * -0.5 };
  }

  // chips: a casino chip — body and edge inserts in the ladder's colours (casino/chips.py), an inlay that can carry a
  // player's colour and the amount. Pre-rendered once per look as a sprite (drop shadow baked in), then stamped.
  const chipCache = new Map();
  function chipSprite(r, color, edge, inlay, label, k, glow) {
    const key = `${r}|${color}|${edge}|${inlay || ""}|${label == null ? "" : label}|${k}|${glow || ""}|${lite() ? 1 : 0}`;
    let c = chipCache.get(key);
    if (c) return c;
    if (chipCache.size > 500) chipCache.clear();
    const pad = Math.ceil(r * 0.6) + (glow ? Math.ceil(r * 0.5) : 0);
    const D = 2 * (r + pad);
    const m = makeCanvas(D, D, k);
    const g = m.g;
    const x = D / 2;
    const y = D / 2;
    if (glow) {
      g.save();
      if (!glowOn(g, glow, r * 0.9)) {
        circle(g, x, y, r * 1.18);
        g.fillStyle = rgba(glow, 0.35);
        g.fill();
      }
      circle(g, x, y, r * 1.04);
      g.lineWidth = Math.max(2, r * 0.12);
      g.strokeStyle = glow;
      g.stroke();
      g.restore();
    }
    // drop shadow (soft once, here), body with a little light from the top left
    g.save();
    if (!glowOn(g, "rgba(0,0,0,.55)", r * 0.35, r * 0.12)) {
      circle(g, x, y + r * 0.12, r * 1.02);
      g.fillStyle = "rgba(0,0,0,.35)";
      g.fill();
    }
    circle(g, x, y, r);
    g.fillStyle = color;
    g.fill();
    g.restore();
    const lg = g.createRadialGradient(x - r * 0.4, y - r * 0.45, r * 0.1, x, y, r);
    lg.addColorStop(0, "rgba(255,255,255,.22)");
    lg.addColorStop(0.6, "rgba(255,255,255,0)");
    lg.addColorStop(1, "rgba(0,0,0,.22)");
    circle(g, x, y, r);
    g.fillStyle = lg;
    g.fill();
    // the edge inserts
    g.lineWidth = r * 0.22;
    g.strokeStyle = edge;
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * TAU + 0.26;
      g.beginPath();
      g.arc(x, y, r * 0.86, a, a + 0.42);
      g.stroke();
    }
    // the inlay
    const ink = inlay || shade(color, 0.86);
    circle(g, x, y, r * 0.62);
    g.fillStyle = ink;
    g.fill();
    g.lineWidth = Math.max(1, r * 0.06);
    g.setLineDash([r * 0.16, r * 0.12]);
    g.strokeStyle = rgba(edge, 0.75);
    circle(g, x, y, r * 0.55);
    g.stroke();
    g.setLineDash([]);
    circle(g, x, y, r - 0.5);
    g.lineWidth = 1;
    g.strokeStyle = "rgba(0,0,0,.35)";
    g.stroke();
    if (label != null && label !== "") {
      const [rr2, gg, bb] = hexRgb(inlay || color); // the inlay is the owner's colour, or the chip's own a shade darker
      const light = rr2 * 0.3 + gg * 0.59 + bb * 0.11 > 150;
      const s = String(label);
      const size = r * (s.length >= 5 ? 0.42 : s.length === 4 ? 0.5 : s.length === 3 ? 0.6 : 0.72);
      txt(g, s, x, y + size * 0.36, size, light ? "#141414" : "#ffffff", { align: "center", font: "mono", weight: 800, shadow: false });
    }
    c = { c: m.c, D };
    chipCache.set(key, c);
    return c;
  }

  /** One chip at (x, y). o: {alpha, glow, edge, inlay}. */
  function chip(g, x, y, r, color, label, o) {
    o = o || {};
    const sp = chipSprite(r, color, o.edge || "#ffffff", o.inlay || null, label, chipK(g), o.glow || null);
    const a = g.globalAlpha;
    if (o.alpha != null) g.globalAlpha = a * o.alpha;
    g.drawImage(sp.c, x - sp.D / 2, y - sp.D / 2, sp.D, sp.D);
    g.globalAlpha = a;
  }
  /** The device px per stage px a context draws at (its transform's scale; 1 in tests). */
  function chipK(g) {
    try {
      const m = g.getTransform && g.getTransform();
      const k = m && typeof m.a === "number" ? Math.hypot(m.a, m.b) : 1;
      return Math.round(clamp(k, 0.5, 3) * 4) / 4;
    } catch (e) {
      return 1;
    }
  }

  /**
   * A stack worth `amount`: the amount broken into ladder chips (largest at the bottom), the top chip's inlay in the
   * owner's colour with the total on it. o: {alpha, glow, rack}.
   */
  function stack(S, g, x, y, r, amount, owner, o) {
    o = o || {};
    const parts = breakInto(amount, o.rack || S.rack).slice(0, 8);
    if (!parts.length) return;
    const n = parts.length;
    for (let j = 0; j < n - 1; j++) {
      const cs = chipStyle(parts[j], o.rack || S.rack);
      chip(g, x, y + (n - 1 - j) * r * 0.17, r, cs.color, null, { alpha: o.alpha, edge: cs.edge });
    }
    const top = chipStyle(parts[n - 1], o.rack || S.rack);
    chip(g, x, y, r, top.color, shortChip(amount), { alpha: o.alpha, edge: top.edge, inlay: owner || null, glow: o.glow });
  }

  /**
   * Everyone's chips on one spot: a stack per player (their colour on the inlay), fanned, the amount on each, broken
   * into the ladder's chips. New chips drop in. o: {r, sweep (0..1 → slides to `to`, fades), glow, to: [x, y]}.
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
      // drop in with a small bounce (easeOutBack)
      const drop = u < 1 ? 1 - (1 + 2.2 * Math.pow(u - 1, 3) + 1.2 * Math.pow(u - 1, 2)) : 0;
      let cy = y + (i - (n - 1) / 2) * r * 0.25 - drop * 60;
      let alpha = (u < 1 ? 0.3 + 0.7 * Math.min(1, u * 2) : 1) * (o.dim ? 0.3 : 1);
      if (o.sweep) {
        const k = easeInOut(o.sweep);
        cx = lerp(cx, (o.to || [x, y - 200])[0], k);
        cy = lerp(cy, (o.to || [x, y - 200])[1], k);
        alpha *= 1 - k;
      }
      if (alpha <= 0.01) return;
      stack(S, g, cx, cy, r, num(e.amount), e.color || "#f0f0f0", { alpha, glow: o.glow });
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
    if (o.glow) glowOn(g, color, r * 0.8);
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
    if (!glowOn(g, color, 40 * k)) {
      // lite: a wide faint stroke under the line stands in for the blur
      rr(g, x, y, w, h, r == null ? 18 : r);
      g.lineWidth = 16;
      g.strokeStyle = rgba(color, 0.18 * k);
      g.stroke();
    }
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
    const sig = sigOf(st);
    if (sig !== S.sig) {
      S.sig = sig;
      S.ver += 1;
    }
    S.players = tablePlayers(st);
    S.rack = rackOf(st); // the table's chips (status.chips, or computed from the limits on an older engine)
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
        if (prev == null || num(e.amount) > prev) {
          S.chipT.set(key, S.firstIngest ? -1e9 : t);
          if (!S.firstIngest) S.animUntil = Math.max(S.animUntil, t + 0.45);
        }
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
    bgWanted(S);
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

  /** An absolutely placed canvas layer (stage px), backing store × k. Moving layers get their own GPU layer. */
  function layer(parent, x, y, w, h, k, moving) {
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.ceil(w * k));
    c.height = Math.max(1, Math.ceil(h * k));
    const st = c.style;
    st.position = "absolute";
    st.left = `${x}px`;
    st.top = `${y}px`;
    st.width = `${w}px`;
    st.height = `${h}px`;
    st.pointerEvents = "none";
    if (moving) {
      st.willChange = "transform, opacity";
      st.transformOrigin = "50% 50%";
    }
    parent.appendChild(c);
    const g = c.getContext("2d");
    g.setTransform(k, 0, 0, k, 0, 0);
    return { c, g, w, h, k, x, y };
  }

  /** A status signature for redraw decisions: countdown seconds and other per-tick values left out. */
  const VOLATILE = new Set(["rev", "reveal_in", "next_in", "ends_in", "age", "t", "call_in", "first_in", "turn_in", "in", "insurance_in", "at"]);
  const sigOf = (st) => JSON.stringify(st, (k, v) => (VOLATILE.has(k) ? (v == null ? null : 1) : v));

  /**
   * The engine's clock on this TV (seconds): local monotonic time + the offset tv.js estimates from server_time,
   * slewed at ≤ 30 % of real time so it never jumps (a jump > 1 s — first sync, a sleep — snaps) and never runs
   * backwards. Every reveal animation is a function of this clock, as the panel's is of the engine's.
   */
  function serverClock(S, tl) {
    const c = S.ctx || {};
    let off = 0;
    try {
      if (typeof c.serverNow === "function" && typeof c.now === "function") off = c.serverNow() - c.now();
    } catch (e) {
      off = 0;
    }
    if (!Number.isFinite(off)) off = 0;
    const k = S.sclk;
    if (k.off == null || Math.abs(off - k.off) > 1) k.off = off;
    else {
      const dt = clamp(tl - k.last, 0, 0.5);
      k.off += clamp(off - k.off, -0.3 * dt, 0.3 * dt);
    }
    k.last = tl;
    let T = tl + k.off;
    if (k.T != null && T < k.T) T = k.T;
    k.T = T;
    return T;
  }

  /** The TV-only reveal of the locked round (ctx.tv.reveal, docs/TV_VIEW.md §3) for `game`, or null. */
  function revealOf(S, game) {
    const rv = obj(obj(S.ctx && S.ctx.tv).reveal);
    return rv.game === game && (rv.outcome || rv.stops) ? rv : null;
  }
  /** Seconds since betting closed, on the engine's clock (frozen while the host pauses). */
  const sinceLockOf = (rv, T) => (rv.paused ? num(rv.since_lock) : T - (num(rv.at) - num(rv.since_lock)));

  // ------------------------------------------------------------------------------------------------ the stamp
  // A rubber stamp slammed onto the winning spot: it drops in at ×1.6, squashes on impact, splashes an ink ring
  // and settles slightly rotated, then stays (ink texture, worn edge) until the round clears. Two pre-rendered
  // layers animated by transform / opacity only (60 fps on a TV stick).
  const STAMP = 150;
  function stampLayers(S, root, name) {
    const k = wheelK();
    const st = layer(root, 0, 0, STAMP, STAMP, k, true);
    const ink = layer(root, 0, 0, STAMP, STAMP, k, true);
    const burst = layer(root, 0, 0, BURST, BURST, Math.min(k, 1), false);
    st.c.style.opacity = "0";
    ink.c.style.opacity = "0";
    burst.c.style.display = "none";
    S.L[name] = { st, ink, burst, key: null };
  }
  /**
   * The result moment: gold sparks burst from the stamp as it hits and fall away (a small canvas of its own, drawn
   * only for those 0.9 s). A pure function of the stamp's age on the shared clock, so every screen bursts together.
   */
  const BURST = 420;
  function burstDraw(S, name, x, y, age, color) {
    const L = S.L[name];
    const b = L.burst;
    if (!b) return;
    const on = age != null && age >= 0 && age < 0.9;
    if (!on) {
      if (L.burstOn) {
        b.c.style.display = "none";
        L.burstOn = false;
      }
      return;
    }
    if (!L.burstOn) {
      b.c.style.display = "";
      L.burstOn = true;
    }
    b.c.style.left = `${(x - BURST / 2).toFixed(1)}px`;
    b.c.style.top = `${(y - BURST / 2).toFixed(1)}px`;
    const g = b.g;
    g.setTransform(b.k, 0, 0, b.k, 0, 0);
    g.clearRect(0, 0, BURST, BURST);
    const n = lite() ? 10 : 26;
    const c = BURST / 2;
    const u = age / 0.9;
    for (let i = 0; i < n; i++) {
      const h = hash01(`${name}${i}`);
      const a = (i / n) * TAU + h * 0.6;
      const v = 120 + 110 * hash01(`${i}${name}v`);
      const d = v * easeOut(u) * 1.25;
      const px = c + Math.cos(a) * d;
      const py = c + Math.sin(a) * d + 90 * u * u; // a little gravity
      const r = (i % 3 === 0 ? 6 : 4) * (1 - u * 0.7);
      g.globalAlpha = 1 - u;
      g.fillStyle = i % 4 === 0 ? "#ffffff" : color;
      circle(g, px, py, r);
      g.fill();
    }
    g.globalAlpha = 1;
  }
  /** Draw the stamp's face (once per text / colour). */
  function stampPaint(S, name, text, color) {
    const L = S.L[name];
    const key = `${text}|${color}`;
    if (L.key === key) return;
    L.key = key;
    const c = STAMP / 2;
    for (const l of [L.st, L.ink]) {
      l.g.setTransform(l.k, 0, 0, l.k, 0, 0);
      l.g.clearRect(0, 0, STAMP, STAMP);
    }
    const g = L.st.g;
    g.save();
    g.globalAlpha = 0.9;
    g.lineWidth = 7;
    g.strokeStyle = color;
    circle(g, c, c, c - 8);
    g.stroke();
    g.lineWidth = 2.5;
    circle(g, c, c, c - 19);
    g.stroke();
    // the stars between the rings
    g.fillStyle = color;
    for (let i = 0; i < 12; i++) {
      const a = (i / 12) * TAU;
      circle(g, c + Math.cos(a) * (c - 13.5), c + Math.sin(a) * (c - 13.5), 2);
      g.fill();
    }
    const s = String(text);
    const size = s.length > 3 ? 34 : s.length > 2 ? 44 : 60;
    g.font = `900 ${size}px ${FONT}`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(s, c, c + 3);
    // worn ink: knock a speckle of holes out of the print
    g.globalCompositeOperation = "destination-out";
    let r = 1234567;
    for (let i = 0; i < 260; i++) {
      r = (r * 16807) % 2147483647;
      const x = (r % 1000) / 1000;
      r = (r * 16807) % 2147483647;
      const y = (r % 1000) / 1000;
      g.globalAlpha = 0.25 + ((i * 37) % 10) / 20;
      circle(g, x * STAMP, y * STAMP, 0.8 + (i % 3) * 0.7);
      g.fill();
    }
    g.restore();
    const ig = L.ink.g;
    ig.save();
    ig.lineWidth = 5;
    ig.strokeStyle = rgba(color, 0.55);
    circle(ig, c, c, c - 6);
    ig.stroke();
    for (let i = 0; i < 9; i++) {
      const a = (i / 9) * TAU + 0.3;
      ig.fillStyle = rgba(color, 0.5);
      circle(ig, c + Math.cos(a) * (c - 4), c + Math.sin(a) * (c - 4), 3 + (i % 3));
      ig.fill();
    }
    ig.restore();
  }
  /**
   * Place the stamp: centre (x, y) on the stage, `age` seconds since it hit (< 0: not yet; null: hidden),
   * `size` px across, its resting tilt `rot` (radians).
   */
  function stampMove(S, name, x, y, age, size, rot) {
    const L = S.L[name];
    const st = L.st.c.style;
    const ink = L.ink.c.style;
    if (age == null || age < -0.22) {
      if (st.opacity !== "0") st.opacity = L.op = "0";
      if (ink.opacity !== "0") ink.opacity = "0";
      L.on = false;
      burstDraw(S, name, x, y, null);
      return;
    }
    const base = size / STAMP;
    let sc;
    let sx = 1;
    let sy = 1;
    let op;
    let r;
    if (age < 0) {
      const u = (age + 0.22) / 0.22; // falling: big and faint → full size
      sc = 1.6 - 0.6 * u * u;
      op = u;
      r = rot - 0.35 * (1 - u);
    } else if (age < 0.09) {
      const u = age / 0.09; // impact: squash
      sc = 1;
      sx = 1 + 0.14 * Math.sin(u * Math.PI);
      sy = 1 - 0.16 * Math.sin(u * Math.PI);
      op = 1;
      r = rot;
    } else {
      const u = Math.min(1, (age - 0.09) / 0.35); // settle with a little wobble
      sc = 1 + 0.04 * Math.sin(u * Math.PI * 2) * (1 - u);
      op = 1 - 0.12 * u;
      r = rot + 0.05 * Math.sin(u * Math.PI * 3) * (1 - u);
    }
    const tx = `translate(${(x - STAMP / 2).toFixed(1)}px,${(y - STAMP / 2).toFixed(1)}px)`;
    const tf = `${tx} rotate(${r.toFixed(3)}rad) scale(${(base * sc * sx).toFixed(3)},${(base * sc * sy).toFixed(3)})`;
    const o = op.toFixed(3);
    if (L.tf !== tf) st.transform = L.tf = tf; // resting: no style writes at all
    if (L.op !== o) st.opacity = L.op = o;
    if (age >= 0 && age < 0.6) {
      const u = age / 0.6;
      ink.transform = `${tx} scale(${(base * (0.9 + 0.9 * u)).toFixed(3)})`;
      ink.opacity = (0.9 * (1 - u)).toFixed(3);
    } else if (ink.opacity !== "0") ink.opacity = "0";
    L.on = true;
    burstDraw(S, name, x, y, age, S.th.accent_hi || S.th.accent);
  }

  // ------------------------------------------------------------------------------------------------ the dolly
  // Roulette's win marker, as on a real table: the dealer lowers a crystal dolly on a gold base onto the winning
  // number, its shadow firming up as it comes down, and it stays there until the round clears. Two sprites drawn
  // once (the dolly, its shadow), moved by transform / opacity only.
  const DOLLY_W = 96;
  const DOLLY_H = 132;
  function dollyLayers(S, root, name) {
    const k = wheelK();
    const sh = layer(root, 0, 0, DOLLY_W, DOLLY_W / 2, k, true);
    const d = layer(root, 0, 0, DOLLY_W, DOLLY_H, k, true);
    sh.c.style.opacity = "0";
    d.c.style.opacity = "0";
    d.c.style.transformOrigin = `50% ${DOLLY_H - 12}px`;
    S.L[name] = { d, sh, painted: false };
  }
  function dollyPaint(S, name) {
    const L = S.L[name];
    if (L.painted) return;
    L.painted = true;
    const W = DOLLY_W;
    const H = DOLLY_H;
    const cx = W / 2;
    // the shadow: a soft ellipse on the felt
    const sg = L.sh.g;
    sg.setTransform(L.sh.k, 0, 0, L.sh.k, 0, 0);
    const sr = sg.createRadialGradient(cx, W / 4, 2, cx, W / 4, W / 2);
    sr.addColorStop(0, "rgba(0,0,0,0.55)");
    sr.addColorStop(0.6, "rgba(0,0,0,0.22)");
    sr.addColorStop(1, "rgba(0,0,0,0)");
    sg.fillStyle = sr;
    sg.beginPath();
    sg.ellipse(cx, W / 4, W / 2, W / 4, 0, 0, TAU);
    sg.fill();
    const g = L.d.g;
    g.setTransform(L.d.k, 0, 0, L.d.k, 0, 0);
    g.clearRect(0, 0, W, H);
    const baseY = H - 22; // centre of the base's top face
    const gold = () => {
      const l = g.createLinearGradient(cx - 28, 0, cx + 28, 0);
      l.addColorStop(0, "#7a5410");
      l.addColorStop(0.28, "#f6dc8a");
      l.addColorStop(0.5, "#fff6d6");
      l.addColorStop(0.72, "#d6a33a");
      l.addColorStop(1, "#6a470c");
      return l;
    };
    // the gold base: a short cylinder seen from slightly above
    g.fillStyle = gold();
    g.beginPath();
    g.ellipse(cx, baseY + 10, 28, 9, 0, 0, Math.PI);
    g.lineTo(cx - 28, baseY);
    g.ellipse(cx, baseY, 28, 9, 0, Math.PI, 0, true);
    g.closePath();
    g.fill();
    g.fillStyle = "#f3d27a";
    g.beginPath();
    g.ellipse(cx, baseY, 28, 9, 0, 0, TAU);
    g.fill();
    g.strokeStyle = "rgba(90,60,10,0.6)";
    g.lineWidth = 1.2;
    g.stroke();
    // the crystal body: a waisted pawn with a round head, see-through with bright edges
    const body = () => {
      g.beginPath();
      g.moveTo(cx - 20, baseY + 1);
      g.bezierCurveTo(cx - 20, baseY - 18, cx - 9, baseY - 30, cx - 8, baseY - 52);
      g.bezierCurveTo(cx - 7, baseY - 64, cx - 15, baseY - 70, cx - 15, baseY - 78);
      g.lineTo(cx + 15, baseY - 78);
      g.bezierCurveTo(cx + 15, baseY - 70, cx + 7, baseY - 64, cx + 8, baseY - 52);
      g.bezierCurveTo(cx + 9, baseY - 30, cx + 20, baseY - 18, cx + 20, baseY + 1);
      g.closePath();
    };
    const glass = g.createLinearGradient(cx - 20, 0, cx + 20, 0);
    glass.addColorStop(0, "rgba(255,255,255,0.55)");
    glass.addColorStop(0.22, "rgba(210,232,255,0.16)");
    glass.addColorStop(0.55, "rgba(190,215,245,0.10)");
    glass.addColorStop(0.8, "rgba(255,255,255,0.32)");
    glass.addColorStop(1, "rgba(150,180,220,0.35)");
    g.fillStyle = glass;
    body();
    g.fill();
    g.strokeStyle = "rgba(255,255,255,0.75)";
    g.lineWidth = 1.6;
    g.stroke();
    // the gold collar and the crystal head
    g.fillStyle = gold();
    g.beginPath();
    g.ellipse(cx, baseY - 78, 17, 5, 0, 0, TAU);
    g.fill();
    const head = g.createRadialGradient(cx - 6, baseY - 100, 2, cx, baseY - 94, 18);
    head.addColorStop(0, "rgba(255,255,255,0.95)");
    head.addColorStop(0.35, "rgba(220,236,255,0.45)");
    head.addColorStop(1, "rgba(160,190,230,0.30)");
    g.fillStyle = head;
    g.beginPath();
    g.arc(cx, baseY - 94, 16, 0, TAU);
    g.fill();
    g.strokeStyle = "rgba(255,255,255,0.8)";
    g.stroke();
    // a long glint down the left of the body
    g.strokeStyle = "rgba(255,255,255,0.85)";
    g.lineWidth = 2.4;
    g.lineCap = "round";
    g.beginPath();
    g.moveTo(cx - 15, baseY - 8);
    g.quadraticCurveTo(cx - 6, baseY - 30, cx - 4, baseY - 58);
    g.stroke();
  }
  /** Place the dolly with its base on (x, y): `age` s since it touched down (< 0: being lowered; null: off). */
  function dollyMove(S, name, x, y, age) {
    const L = S.L[name];
    const ds = L.d.c.style;
    const ss = L.sh.c.style;
    const FALL = 0.45;
    if (age == null || age < -FALL) {
      if (L.op !== "0") ds.opacity = ss.opacity = L.op = "0";
      L.tf = null;
      return;
    }
    let lift = 0;
    let op = 1;
    let sy = 1;
    if (age < 0) {
      const u = (age + FALL) / FALL; // lowered by the dealer's hand: eases down
      lift = 70 * (1 - easeOut(u));
      op = Math.min(1, u * 1.6);
    } else if (age < 0.18) {
      sy = 1 - 0.035 * Math.sin((age / 0.18) * Math.PI); // a soft settle on the felt
    }
    const tf = `translate(${(x - DOLLY_W / 2).toFixed(1)}px,${(y - (DOLLY_H - 22) - lift).toFixed(1)}px) scale(1,${sy.toFixed(3)})`;
    if (L.tf !== tf) {
      ds.transform = L.tf = tf; // resting: no style writes at all
      const near = 1 - lift / 70;
      ss.transform = `translate(${(x - DOLLY_W / 2).toFixed(1)}px,${(y - DOLLY_W / 4 + 10).toFixed(1)}px) scale(${(0.7 + 0.3 * near).toFixed(3)})`;
      ss.opacity = (op * (0.35 + 0.65 * near)).toFixed(3);
    }
    const o = op.toFixed(3);
    if (L.op !== o) ds.opacity = L.op = o;
  }

  /** Device px per stage px for the table's canvases: the stage's own (≤ 1.5), ¾ of it in the lite tier. */
  const tableK = () => clamp(num(TV && TV.pixelRatio, 1), 1, 1.5) * (lite() ? 0.75 : 1);

  function makeScene(def) {
    let S = null;
    const scene = {
      id: def.id,
      match: (app) => app === def.app,
      mount(root, ctx) {
        const k = tableK();
        root.style.position = "absolute";
        S = {
          def, root, k, ctx, st: {}, th: Object.assign({}, CLASSIC), clk: new PhaseTracker(), players: [],
          bySeat: new Map(), chipT: new Map(), chipAmt: new Map(), seen: new Map(), fx: {}, L: {}, bg: null,
          round: undefined, firstIngest: true, alive: true, raf: 0, t: 0, T: 0, err: null, sclk: {}, ver: 0,
          sig: "", lastKey: "", railKey: "", animUntil: 0,
        }; // fmt: skip
        S.bgl = layer(root, 0, 0, SW, SH, k, false); // felt, printed layout, rail frame: redrawn on theme / layout
        // the theme's felt motif (css.pattern: CSS gradients) as a static DOM layer clipped to the felt
        S.pat = document.createElement("div");
        Object.assign(S.pat.style, { position: "absolute", left: "0px", top: "0px", width: `${RAIL_X}px`, height: `${SH}px`, pointerEvents: "none" });
        root.appendChild(S.pat);
        if (def.layers) def.layers(S, root); // the moving parts: wheels, balls, dice, reels (transforms only)
        S.top = layer(root, 0, 0, SW, SH, k, false); // chips, cards, text: redrawn only when they change
        S.g = S.top.g;
        if (def.overlays) def.overlays(S, root); // stamps: above the chips, transforms only
        S.rail = layer(root, RAIL_X, 0, RAIL_W, SH, k, false);
        const pcv = document.createElement("canvas");
        pcv.style.position = "absolute";
        pcv.style.left = `${PANEL_X}px`;
        pcv.style.top = `${PANEL_Y}px`;
        pcv.style.width = `${PANEL_SIZE}px`;
        pcv.style.height = `${PANEL_SIZE}px`;
        pcv.style.borderRadius = "6px";
        root.appendChild(pcv);
        S.pcv = pcv;
        if (def.init) def.init(S);
        ingest(S, ctx);
        const me = S;
        const step = () => {
          if (!S || !S.alive || S !== me) return false;
          if (!(typeof document !== "undefined" && document.hidden)) {
            try {
              paint(S, nowOf(S.ctx));
            } catch (e) {
              if (!S.err) console.error("DeskDot TV casino scene:", def.id, e);
              S.err = e;
            }
          }
          return true;
        };
        if (TV && typeof TV.every === "function") S.stop = TV.every(step); // the page's one animation loop (tv.js)
        else {
          const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (f) => setTimeout(() => f(), 16);
          const loop = () => {
            if (step() !== false) S.raf = raf(loop);
          };
          S.raf = raf(loop);
        }
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
        const k = tableK();
        if (Math.abs(k - S.k) < 1e-3) return;
        S.k = k;
        for (const l of [S.bgl, S.top]) {
          l.c.width = Math.round(SW * k);
          l.c.height = Math.round(SH * k);
          l.k = k;
        }
        S.rail.c.width = Math.round(RAIL_W * k);
        S.rail.c.height = Math.round(SH * k);
        S.rail.k = k;
        S.bg = null;
        bgWanted(S);
        S.lastKey = S.railKey = "";
        if (S.hud) for (const h of S.hud.values()) h.k = -1; // re-made at the new resolution on the next redraw
        cardCache.clear();
        chipCache.clear();
        if (ctx && ctx.panel) scene.frame(ctx);
      },
      unmount() {
        if (!S) return;
        S.alive = false;
        if (S.stop) S.stop();
        if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(S.raf);
        S = null;
      },
      // tests
      _state: () => S,
      _paint: (t) => S && paint(S, t),
    };
    return scene;
  }

  function bgWanted(S) {
    S.bgWant = `${JSON.stringify(S.th)}|${S.k}|${S.def.bgKey ? S.def.bgKey(S) : ""}`;
  }
  function background(S) {
    if (S.bg === S.bgWant) return; // the key is built on each state (ingest), never per frame
    S.bg = S.bgWant;
    const g = S.bgl.g;
    g.setTransform(S.k, 0, 0, S.k, 0, 0);
    g.clearRect(0, 0, SW, SH);
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
    const ps = S.pat.style;
    ps.backgroundImage = th.pattern || "none";
    ps.backgroundSize = th.pattern_size || "auto";
    ps.clipPath = S.def.feltClip ? S.def.feltClip(S) : "inset(18px 16px 18px 18px round 60px)"; // rr(18, 18, RAIL_X - 34, SH - 36, 60)
    if (S.def.layersRedraw) S.def.layersRedraw(S);
  }

  /**
   * One animation frame. The moving parts only get new transforms (def.move — compositor work, no repaint); the
   * table layer is redrawn only when something on it changed (the status signature, a tick of a countdown, a chip
   * or card still in flight), so a spinning wheel holds 60 fps on a TV stick.
   */
  function paint(S, t) {
    S.t = t;
    S.T = serverClock(S, t);
    background(S);
    if (S.def.move) S.def.move(S, t);
    // how often the table layer redraws: 30 Hz (20 in lite) while chips drop / cards fly, else the scene's own
    // slow rate (countdown rings sweep in their own small canvases — hudRing — so betting needs ~1 Hz), default 4
    const L = lite();
    const hz = t < S.animUntil ? (L ? 20 : 30) : S.def.slowHz ? S.def.slowHz(S, t) : L ? 2 : 4;
    const tick = hz > 0 ? Math.floor(t * hz) : 0;
    const key = `${S.ver}|${S.def.key ? S.def.key(S, t) : ""}|${hz}|${tick}|${S.k}`;
    if (key !== S.lastKey) {
      S.lastKey = key;
      S.drawGen = (S.drawGen || 0) + 1;
      const g = S.g;
      g.setTransform(S.k, 0, 0, S.k, 0, 0);
      g.globalAlpha = 1;
      g.globalCompositeOperation = "source-over";
      g.clearRect(0, 0, SW, SH);
      S.def.draw(S, g, t);
      if (S.st.paused) paused(S, g, t);
      if (S.preview) previewNote(S, g);
    }
    hudFrame(S, t);
    if (S.def.fx) S.def.fx(S, t);
    const turn = S.def.turnSeat ? S.def.turnSeat(S) : null;
    const rk = `${S.ver}|${turn}|${S.k}`;
    if (rk !== S.railKey) {
      S.railKey = rk;
      const g = S.rail.g;
      g.setTransform(S.k, 0, 0, S.k, -RAIL_X * S.k, 0);
      g.clearRect(RAIL_X, 0, RAIL_W, SH);
      drawRail(S, g, t);
    }
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
    txt(g, "CHIPS", RAIL_X + 22, 528, 18, INK3, { weight: 800, shadow: false });
    txt(g, "RECENT", RAIL_X + 22, 602, 18, INK3, { weight: 800, shadow: false });
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
    const rows = Math.min(list.length, 7);
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
    if (list.length > rows) txt(g, `+ ${list.length - rows} more`, RAIL_X + RAIL_W - 36, 528, 18, INK3, { align: "right", weight: 700, shadow: false });
    // the table's chip rack (status.chips: only what the limits allow — 1K, 5K… at a high-roller table)
    const rack = arr(S.rack);
    const cr = rack.length > 6 ? 17 : 19;
    const step = Math.min(2 * cr + 8, (RAIL_W - 60) / Math.max(1, rack.length));
    rack.forEach((c, i) => chip(g, RAIL_X + 22 + cr + i * step, 556, cr, c.color, c.label, { edge: c.edge }));
    // the recent results strip
    const hist = arr(S.st.history).filter((h) => h && (!S.st.game || h.game === S.st.game)).slice(-7).reverse();
    let x = RAIL_X + 22;
    hist.forEach((h, i) => {
      const lbl = String(h.label == null ? "?" : h.label);
      const w = Math.max(40, measure(g, lbl, 22, { font: "mono" }) + 18);
      if (x + w > RAIL_X + RAIL_W - 24) return;
      rr(g, x, 612, w, 40, 10);
      g.fillStyle = TONE[h.tone] || TONE.white;
      g.fill();
      if (i === 0) {
        g.lineWidth = 3;
        g.strokeStyle = th.accent;
        g.stroke();
      }
      txt(g, lbl, x + w / 2, 640, 22, "#fff", { align: "center", font: "mono", weight: 800, alpha: i === 0 ? 1 : 0.8 });
      x += w + 8;
    });
    if (!hist.length) txt(g, "No rounds yet", RAIL_X + 22, 640, 20, INK3, { weight: 600 });
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
      const left = leftTo(S, "ends_at", S.clk.ends, t);
      const total = Object.values(obj(st.totals)).reduce((a, b) => a + num(b), 0);
      const n = arr(st.bettors).length;
      if (st.ends_in == null || left == null)
        return { title: "PLACE YOUR BETS", sub: "The countdown starts with the first chip", tone: th.accent, pulse: true };
      const span = num(obj(st.house).bet_seconds, 20);
      return {
        title: "PLACE YOUR BETS",
        sub: `${n} ${n === 1 ? "player" : "players"} in · ${fmt(S, total)} on the table`,
        tone: left <= 5 ? BAD : th.accent,
        ring: { frac: left / span, label: Math.ceil(left - 1e-6), color: left <= 5 ? BAD : th.accent, left, span, base: th.accent, low: BAD, lowBelow: 5.0001 },
      };
    }
    if (ph === "locked") return { title: "NO MORE BETS", sub: "Bets are locked", tone: BAD, flash: true };
    if (ph === "result") {
      const next = leftTo(S, "next_at", S.clk.next, t);
      const ws = winners(S);
      return {
        title: String(obj(st.result).label || "RESULT"),
        sub: ws.length ? `${ws.length} ${ws.length === 1 ? "winner" : "winners"}` : "The house wins this one",
        tone: th.accent,
        ring: next != null ? { frac: next / num(obj(st.house).result_seconds, 7), label: Math.ceil(next - 1e-6), color: INK3, left: next, span: num(obj(st.house).result_seconds, 7) } : null,
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
    if (h.ring && align !== "center") {
      const R = o.ringR || 50;
      if (h.ring.left != null) {
        // the countdown sweeps every frame in its own small canvas (no table redraw for it)
        hudRing(S, "head", rx, y + size * 0.55, R, { left: h.ring.left, span: h.ring.span, color: h.ring.base || h.ring.color || S.th.accent, low: h.ring.low, lowBelow: h.ring.lowBelow });
      } else ring(g, rx, y + size * 0.55, R, h.ring.frac, h.ring.color || S.th.accent, h.ring.label);
    }
  }

  /** The winners card: up to `max` winners with avatar, name and net, or "House wins". */
  function winnersCard(S, g, x, y, w, t, o) {
    o = o || {};
    const ws = winners(S);
    const max = o.max || 4;
    const k = o.instant ? 1 : easeOut((S.clk.since(t) - (o.delay || 0)) / 0.5);
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
  function rouletteWheel(S) {
    return obj(S.st.rules).wheel === "american" ? US_WHEEL : EU_WHEEL;
  }

  /** The wheel head (pockets, numbers, cone, turret) centred at (c, c) of `g`: drawn once, spun by CSS. */
  function drawWheelHead(S, g, c) {
    const wheel = rouletteWheel(S);
    g.save();
    g.translate(c, c);
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
    g.restore();
  }

  // The panel's motion (apps/casino_roulette.py), ported 1:1: angles in radians clockwise from 12 o'clock, radii in
  // panel pixels (mapped onto the HD bowl by `panelR`), times in seconds since betting closed (since_lock).
  const RP = { TRACK: 14.5, POCKET: 11.7, BW0: 6.4, BTAU: 3.3, WW0: 2.3, WTAU: 5.5, DRIFT: 0.32 };
  const ballTravel = (t) => RP.BW0 * RP.BTAU * (1 - Math.exp(-t / RP.BTAU));
  const wheelTravel = (t) => RP.WW0 * RP.WTAU * (1 - Math.exp(-t / RP.WTAU)) + RP.DRIFT * t;
  const panelR = (r) => R_POCKET + (r - RP.POCKET) * ((R_TRACK - R_POCKET) / (RP.TRACK - RP.POCKET));

  /** casino_roulette.wheel_step: how far the wheel turns (anticlockwise) in the dt s that end at since_lock. */
  function wheelStep(sinceLock, dt) {
    let out = RP.DRIFT * dt;
    if (sinceLock != null && sinceLock > 0) {
      const s0 = Math.max(0, sinceLock - dt);
      out += RP.WW0 * RP.WTAU * (Math.exp(-s0 / RP.WTAU) - Math.exp(-sinceLock / RP.WTAU));
    }
    return out;
  }

  /** casino_roulette.ball with rot = 0: the ball's angle relative to the wheel, and its radius (panel px). */
  function rouletteBallRel(t, pocket, n, spin, lock) {
    const tSettle = lock + spin - 1.0;
    const tDrop = tSettle - 1.3;
    const target = (pocket * TAU) / n;
    if (t >= tSettle) {
      const u = t - tSettle;
      return { a: target + 0.09 * Math.sin(u * 19) * Math.exp(-u * 4.5), r: RP.POCKET, settled: true };
    }
    const psi0 = target - ballTravel(tSettle) - wheelTravel(tSettle);
    const psi = psi0 + ballTravel(t) + wheelTravel(t);
    let r = RP.TRACK;
    if (t > tDrop) {
      const u = (t - tDrop) / (tSettle - tDrop);
      const ease = u * u * (3 - 2 * u);
      r = RP.TRACK - (RP.TRACK - RP.POCKET) * ease + 1.6 * Math.abs(Math.sin(u * 2.6 * Math.PI)) * (1 - u) * (1 - u);
    }
    return { a: psi, r, settled: false };
  }

  /**
   * The wheel's angle on the TV: integrated with the panel's own step (wheelStep) on the engine's clock, and pulled
   * onto the angle the panel reports (tv.wheel: its rot when it last drew, at server time `at`) — the first report
   * snaps, later ones are slewed in over ~0.3 s, so the wheel never jumps and always matches the panel's.
   */
  function rouletteRot(S, T) {
    const fx = S.fx;
    const rv = revealOf(S, "roulette");
    const sl = rv ? sinceLockOf(rv, T) : null;
    if (fx.R == null) {
      fx.R = 0;
      fx.lastT = T;
    }
    const dt = clamp(T - fx.lastT, 0, 0.5);
    fx.lastT = T;
    if (rv && fx.spinRound !== rv.round) {
      // the lock reached us a moment after it happened: the spin the wheel already made is slewed in, not jumped
      fx.spinRound = rv.round;
      const missed = Math.max(0, sl - dt);
      if (missed > 0 && missed < 3) fx.err -= wheelStep(missed, missed) - RP.DRIFT * missed;
    }
    fx.R -= wheelStep(sl, dt);
    const w = obj(obj(S.ctx && S.ctx.tv).wheel);
    if (typeof w.rot === "number" && typeof w.at === "number" && w.at !== fx.anchorAt) {
      fx.anchorAt = w.at;
      const err = w.rot - wheelStep(sl, Math.max(0, T - w.at)) - fx.R; // where the panel's wheel is now, minus ours
      if (!fx.synced || Math.abs(err) > 0.8) {
        fx.R += err;
        fx.err = 0;
        fx.synced = true;
      } else fx.err = err;
    }
    if (fx.err) {
      const c = fx.err * (1 - Math.exp(-dt / 0.3));
      fx.R += c;
      fx.err -= c;
    }
    return fx.R;
  }

  /** The ball: {a, r (HD px), alpha, settled} — launched at the lock on the panel's path; none while betting. */
  function rouletteBallNow(S, T, rot, n) {
    const fx = S.fx;
    const rv = revealOf(S, "roulette");
    const pocket = rv ? obj(rv.outcome).pocket : null;
    if (rv && typeof pocket === "number" && pocket < n) {
      const sl = sinceLockOf(rv, T);
      const b = rouletteBallRel(Math.max(0, sl), pocket, n, num(rv.spin_s, 7.5), num(rv.lock_s, LOCK));
      fx.lastBall = { pocket, T };
      return { a: rot + b.a, r: panelR(b.r), alpha: clamp(sl / 0.25, 0, 1), settled: b.settled };
    }
    if (fx.lastBall && T - fx.lastBall.T < 0.5) {
      // a new round opened: the croupier lifts the ball out (the panel simply stops drawing it)
      return { a: rot + (fx.lastBall.pocket * TAU) / n, r: R_POCKET, alpha: 1 - (T - fx.lastBall.T) / 0.5, settled: true };
    }
    return null;
  }

  const wheelK = () => clamp(num(TV && TV.pixelRatio, 1), 1, 2) * (lite() ? 0.75 : 1); // the spinning bitmaps stay crisp

  const roulette = makeScene({
    id: "casino-roulette",
    app: "casino_roulette",
    init(S) {
      S.fx = { R: null, err: 0, synced: false };
    },
    bgKey: (S) => (obj(S.st.rules).wheel === "american" ? "us" : "eu"),
    // the wheel head (pre-rendered once, spun by a CSS rotate), the winning-pocket ring (rides with it), the ball
    layers(S, root) {
      const k = wheelK();
      const D = 2 * R_HEAD + 8;
      S.L.wheel = layer(root, R_CX - D / 2, R_CY - D / 2, D, D, k, true);
      S.L.hit = layer(root, R_CX - D / 2, R_CY - D / 2, D, D, k, true);
      S.L.hit.c.style.opacity = "0";
      S.L.ball = layer(root, 0, 0, 34, 34, k, true);
      S.L.ball.c.style.opacity = "0";
      const g = S.L.ball.g;
      g.save();
      g.shadowColor = "rgba(0,0,0,.6)";
      g.shadowBlur = 6;
      g.shadowOffsetY = 3;
      circle(g, 17, 16, 10.5);
      const bg = g.createRadialGradient(13, 12, 1, 17, 16, 11);
      bg.addColorStop(0, "#ffffff");
      bg.addColorStop(1, "#b9bcc6");
      g.fillStyle = bg;
      g.fill();
      g.restore();
    },
    layersRedraw(S) {
      const l = S.L.wheel;
      l.g.setTransform(l.k, 0, 0, l.k, 0, 0);
      l.g.clearRect(0, 0, l.w, l.h);
      drawWheelHead(S, l.g, l.w / 2);
      S.fx.hitKey = null;
    },
    move(S) {
      const st = S.st;
      const wheel = rouletteWheel(S);
      const N = wheel.length;
      const T = S.T;
      const rot = rouletteRot(S, T);
      const tr = `rotate(${((rot * 180) / Math.PI).toFixed(3)}deg)`;
      S.L.wheel.c.style.transform = tr;
      S.L.hit.c.style.transform = tr;
      const ball = rouletteBallNow(S, T, rot, N);
      const bs = S.L.ball.c.style;
      if (ball && ball.alpha > 0) {
        const x = R_CX + Math.sin(ball.a) * ball.r - 17;
        const y = R_CY - Math.cos(ball.a) * ball.r - 17;
        bs.transform = `translate(${x.toFixed(2)}px,${y.toFixed(2)}px)`;
        bs.opacity = ball.alpha.toFixed(3);
      } else if (bs.opacity !== "0") bs.opacity = "0";
      S.def.stamp(S);
      // the winning pocket glows (on the wheel) once the round's result is public
      const pocket = obj(obj(st.result).outcome).pocket;
      const hitKey = st.phase === "result" && typeof pocket === "number" ? `${N}|${pocket}` : null;
      if (hitKey !== S.fx.hitKey) {
        S.fx.hitKey = hitKey;
        const l = S.L.hit;
        l.g.setTransform(l.k, 0, 0, l.k, 0, 0);
        l.g.clearRect(0, 0, l.w, l.h);
        if (hitKey) {
          const seg = TAU / N;
          const a = pocket * seg - Math.PI / 2;
          const c = l.w / 2;
          l.g.save();
          l.g.beginPath();
          l.g.arc(c, c, R_HEAD + 2, a - seg / 2, a + seg / 2);
          l.g.arc(c, c, R_POCK_IN, a + seg / 2, a - seg / 2, true);
          l.g.closePath();
          l.g.lineWidth = 4;
          l.g.strokeStyle = "#ffffff";
          l.g.shadowColor = S.th.accent;
          l.g.shadowBlur = 18;
          l.g.stroke();
          l.g.restore();
        }
        l.c.style.opacity = hitKey ? "1" : "0";
      }
    },
    overlays(S, root) {
      dollyLayers(S, root, "dolly");
    },
    // the dealer sets the dolly on the winning number the moment the ball settles in its pocket (the panel's t_settle)
    stamp(S) {
      const rv = revealOf(S, "roulette");
      const n = rv ? rouletteWheel(S)[obj(rv.outcome).pocket] : undefined;
      if (n == null) return dollyMove(S, "dolly", 0, 0, null);
      const tSettle = num(rv.lock_s, LOCK) + num(rv.spin_s, 7.5) - 1.0;
      const [x, y] = rouletteCenter(n, rouletteBoard(rouletteWheel(S).length === 38));
      dollyPaint(S, "dolly");
      dollyMove(S, "dolly", x, y + 14, sinceLockOf(rv, S.T) - tSettle);
    },
    // the table layer only redraws for a countdown tick while betting; never while the wheel is spinning
    slowHz: (S) => (S.st.phase === "betting" && S.st.ends_in != null ? 1 : 0),
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
      const th = S.th;
      const wheel = rouletteWheel(S);
      const N = wheel.length;
      const seg = TAU / N;
      const B = rouletteBoard(N === 38);
      // the sheen over the wheel (the head spins in its own layer underneath)
      const sheen = g.createRadialGradient(R_CX - 110, R_CY - 140, 10, R_CX, R_CY, R_HEAD);
      sheen.addColorStop(0, "rgba(255,255,255,.16)");
      sheen.addColorStop(0.5, "rgba(255,255,255,.03)");
      sheen.addColorStop(1, "rgba(0,0,0,.18)");
      circle(g, R_CX, R_CY, R_HEAD);
      g.fillStyle = sheen;
      g.fill();
      const resPocket = obj(obj(st.result).outcome).pocket;
      const landed = st.phase === "result" && typeof resPocket === "number" ? resPocket : null;
      const showResult = landed != null;
      // the number, big, on the cone (drawn once: the table layer doesn't redraw while the wheel turns)
      if (showResult) {
        const n = wheel[landed];
        const col = { red: "#d0182f", black: "#1b1b22", green: "#0e9a4c" }[rColor(n)];
        g.save();
        circle(g, R_CX, R_CY, 116);
        g.fillStyle = col;
        glowOn(g, rgba(th.accent, 0.8), 40);
        g.fill();
        g.lineWidth = 6;
        g.strokeStyle = th.accent;
        g.stroke();
        g.restore();
        txt(g, rLabel(n), R_CX, R_CY + 40, 120, "#fff", { align: "center", weight: 850 });
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
                if (ph === "result") {
          const n = wheel[landed];
          const words = n === 0 || n === 37 ? "ZERO" : `${rColor(n).toUpperCase()} · ${n % 2 ? "ODD" : "EVEN"} · ${n <= 18 ? "LOW" : "HIGH"}`;
          const hh = headline(S, t);
          return { ...hh, title: `${rLabel(n)} ${words}`, tone: { red: "#ff5a6e", black: INK1, green: "#3ddc84" }[rColor(n)] };
        }
        return null;
      });
      drawHeadline(S, g, B.x0, 160, 740, t, head, { size: 58 });
      // winning areas
      const win = showResult ? wheel[landed] : null;
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

      for (const spot of Object.keys(sb)) {
        const p = rouletteSpotXY(spot, B);
        if (!p) continue;
        const wins = win != null && rouletteCovers(spot).includes(win);
        spotChips(S, g, spot, sb[spot], p[0], p[1], t, { r: 21, glow: wins ? th.accent : null, dim: win != null && !wins });
      }
      // the foot: totals and winners
      const total = Object.values(obj(st.totals)).reduce((a, b) => a + num(b), 0);
      const fy = B.y0 + 3 * B.ch + B.dzH + B.emH + 34;
      txt(g, "ON THE TABLE", B.x0, fy + 22, 20, INK3, { weight: 800, shadow: false });
      txt(g, fmt(S, total), B.x0, fy + 82, 56, INK1, { font: "mono", weight: 750 });
      const house = obj(st.house);
      txt(g, `Limits ${fmt(S, num(house.min_bet, 1))} – ${fmt(S, num(house.max_bet, 500))} · straight up pays 35 to 1`, B.x0, fy + 122, 22, INK2, { weight: 600 });
      if (st.phase === "result" && showResult) winnersCard(S, g, B.x0 + 400, fy - 6, 380, t, { instant: true, max: 3 });
    },
  });

  // ================================================================================================ BIG SIX
  const BX = 470;
  const BY = 500;
  const BR = 410;
  const B6_SEG = TAU / 54;

  /**
   * The wheel's rotation (radians, clockwise) on the engine's clock — apps/casino_bigsix.py wheel_angle, 1:1:
   * φ(ts) = end − travel·(1 − ts/stop)², ts = since_lock − LOCK, with the round's `end` / `travel` from tv.reveal.
   * During the lock second (the panel shows NO MORE BETS) the TV wheel spins up from where it rested to the
   * panel's start angle with the panel's launch speed (a Hermite ramp), so it never jumps. {phi, ts, stop}
   */
  /** apps/casino_bigsix.py wheel_angle for ts ≥ 0, from the round's end angle and travel. */
  function b6Phi(end, travel, stop, ts) {
    const u = clamp(ts / stop, 0, 1);
    return end - travel * (1 - u) * (1 - u);
  }
  function b6Now(S, T) {
    const fx = S.fx;
    const rv = revealOf(S, "bigsix");
    if (rv) {
      const lock = num(rv.lock_s, LOCK);
      const stop = num(rv.stop_s, 6.4);
      const end = num(rv.end);
      const travel = num(rv.travel);
      const ts = sinceLockOf(rv, T) - lock;
      if (fx.rvRound !== rv.round) {
        fx.rvRound = rv.round;
        fx.from = fx.phi == null || ts > 0 ? end - travel : fx.phi;
      }
      let phi;
      if (ts >= 0) phi = b6Phi(end, travel, stop, ts);
      else {
        const V = (2 * travel) / stop;
        const s = clamp((ts + lock) / lock, 0, 1);
        let d = mod(end - travel - fx.from, TAU);
        while (d < V * lock * 0.5) d += TAU;
        phi = fx.from + d * (3 * s * s - 2 * s * s * s) + V * lock * (s * s * s - s * s);
      }
      fx.phi = phi;
      return { phi, ts, stop };
    }
    if (fx.phi == null) {
      const last = arr(S.st.history).filter((h) => h.game === "bigsix").slice(-1)[0];
      const seg = obj(last && last.outcome).segment;
      fx.phi = typeof seg === "number" ? -(seg + 0.5) * B6_SEG : 0;
    }
    return { phi: fx.phi, ts: null, stop: 6.4 };
  }

  function b6Wheel(S) {
    const key = `${wheelK()}`;
    if (S.fx.img && S.fx.img.key === key) return S.fx.img.c;
    const D = 2 * BR + 10;
    const m = makeCanvas(D, D, wheelK());
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
      S.fx = { phi: null };
    },
    // the wheel (pre-rendered once, spun by a CSS rotate) and the clapper (a CSS rotate about its pivot)
    layers(S, root) {
      const k = wheelK();
      const D = 2 * BR + 10;
      S.L.wheel = layer(root, BX - D / 2, BY - D / 2, D, D, k, true);
      S.L.clap = layer(root, BX - 20, BY - BR - 54, 40, 112, k, true);
      S.L.clap.c.style.transformOrigin = "20px 8px";
      const g = S.L.clap.g;
      g.save();
      g.translate(20, 8);
      g.beginPath();
      g.moveTo(-16, 0);
      g.lineTo(16, 0);
      g.lineTo(3, 92);
      g.lineTo(-3, 92);
      g.closePath();
      g.fillStyle = "#d6283a";
      g.shadowColor = "rgba(0,0,0,.6)";
      g.shadowBlur = 8;
      g.fill();
      g.restore();
    },
    layersRedraw(S) {
      const l = S.L.wheel;
      l.g.setTransform(l.k, 0, 0, l.k, 0, 0);
      l.g.clearRect(0, 0, l.w, l.h);
      l.g.drawImage(b6Wheel(S), 0, 0, l.w, l.h);
    },
    move(S) {
      const m = b6Now(S, S.T);
      S.L.wheel.c.style.transform = `rotate(${((m.phi * 180) / Math.PI).toFixed(3)}deg)`;
      // the clapper flicks while a peg passes under it (the panel's kick: the first 30 % of each segment)
      const f = (mod(-m.phi, TAU) / B6_SEG) % 1;
      const kick = m.ts != null && m.ts >= 0 && m.ts < m.stop && f < 0.3 ? 0.32 * (1 - f / 0.3) : 0;
      S.L.clap.c.style.transform = `rotate(${((-kick * 180) / Math.PI).toFixed(2)}deg)`;
      S.fx.stopped = m.ts != null && m.ts >= m.stop;
      S.fx.under = mod(Math.floor(mod(-m.phi, TAU) / B6_SEG), 54);
      const rv = revealOf(S, "bigsix");
      const seg = rv ? obj(rv.outcome).segment : null;
      if (typeof seg !== "number") stampMove(S, "stamp", 0, 0, null);
      else {
        const i = B6.findIndex((x) => x.sym === B6_WHEEL[seg]);
        const [x, y] = b6Tile(Math.max(0, i));
        stampPaint(S, "stamp", "WIN", S.th.accent);
        stampMove(S, "stamp", x + 206, y + 70, m.ts - m.stop, 104, -0.2);
      }
    },
    overlays(S, root) {
      stampLayers(S, root, "stamp");
    },
    key: (S) => (S.fx.stopped ? `stop${S.fx.under}` : ""),
    slowHz: (S) => (S.st.phase === "betting" && S.st.ends_in != null ? 1 : 0),
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
      // bulbs round the housing (lit, alternate, all on at the result)
      for (let i = 0; i < 36; i++) {
        const a = (i / 36) * TAU;
        const lit = st.phase === "result" || i % 2 === 0;
        circle(g, BX + Math.sin(a) * (BR + 30), BY - Math.cos(a) * (BR + 30), lit ? 8 : 6);
        g.fillStyle = lit ? "#fff2c0" : "rgba(255,220,140,.25)";
        g.fill();
      }
      const sheen = g.createRadialGradient(BX - 140, BY - 160, 20, BX, BY, BR);
      sheen.addColorStop(0, "rgba(255,255,255,.18)");
      sheen.addColorStop(1, "rgba(0,0,0,.15)");
      circle(g, BX, BY, BR);
      g.fillStyle = sheen;
      g.fill();
      circle(g, BX, BY - BR - 46, 14);
      g.fillStyle = "#e6c46a";
      g.fill();
      // the hub: the symbol under the clapper once the wheel has stopped (as on the panel)
      const resSeg = obj(obj(st.result).outcome).segment;
      const landed = st.phase === "result" && typeof resSeg === "number" ? resSeg : null;
      const stopSeg = landed != null ? landed : fx.stopped ? fx.under : null;
      const sym = stopSeg != null ? B6_BY[B6_WHEEL[stopSeg]] : null;
      txt(g, sym ? (sym.sym === "joker" ? "JOKER" : sym.sym === "logo" ? "LOGO" : sym.sym) : "BIG SIX", BX, BY + (sym ? 30 : 14), sym ? (sym.sym.length > 2 ? 52 : 110) : 46, sym ? sym.col : th.accent, { align: "center", weight: 850, glow: sym ? sym.col : null });
      const showRes = landed != null;
      // headline
      drawHeadline(S, g, 990, 150, 510, t, headline(S, t, (ph) => {
        if (ph === "spinning") return { title: "SPINNING…", sub: "Listen for the clapper", tone: th.accent_hi };
        if (ph === "result") {
          const s = B6_BY[B6_WHEEL[landed]];
          return { ...headline(S, t), title: `${s.sym === "joker" ? "JOKER" : s.sym === "logo" ? "LOGO" : s.sym} PAYS ${s.pays}:1`, tone: s.col };
        }
        return null;
      }), { size: 50 });
      const sb = obj(st.spot_bets);
      const winSym = showRes ? B6_WHEEL[landed] : null;
      B6.forEach((s, i) => {
        const [x, y] = b6Tile(i);
        const isWin = winSym === s.sym;
        if (isWin) glowBox(g, x, y, 250, 140, s.col, 1);
        const tot = num(obj(st.totals)[s.id]);
        if (tot) txt(g, fmt(S, tot), x + 120, y + 116, 20, INK2, { font: "mono", weight: 700 });
        spotChips(S, g, s.id, sb[s.id], x + 206, y + 74, t, { r: 24, glow: isWin ? th.accent : null, dim: winSym != null && !isWin });
      });
      if (showRes) winnersCard(S, g, 1255, 740, 250, t, { instant: true, max: 2 });
    },
  });
  function b6Tile(i) {
    if (i === 6) return [990, 740];
    return [990 + (i % 2) * 265, 250 + Math.floor(i / 2) * 160];
  }

  // ================================================================================================ 7 UP 7 DOWN
  const PIPS = { 1: [[0, 0]], 2: [[-1, -1], [1, 1]], 3: [[-1, -1], [0, 0], [1, 1]], 4: [[-1, -1], [1, -1], [-1, 1], [1, 1]],
    5: [[-1, -1], [1, -1], [0, 0], [-1, 1], [1, 1]], 6: [[-1, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [1, 1]] }; // fmt: skip
  /** A die (face 1–6, s px, rot rad), stamped from a sprite drawn once per size / face / glow. o: {glow} */
  const dieCache = new Map();
  function die(g, x, y, s, face, rot, o) {
    o = o || {};
    const k = chipK(g);
    const key = `${s}|${face}|${o.glow || ""}|${k}|${lite() ? 1 : 0}`;
    let sp = dieCache.get(key);
    if (!sp) {
      if (dieCache.size > 120) dieCache.clear();
      const D = Math.ceil(s * 1.6);
      const m = makeCanvas(D, D, k);
      dieRaw(m.g, D / 2, D / 2, s, face, 0, o);
      sp = { c: m.c, D };
      dieCache.set(key, sp);
    }
    g.save();
    g.translate(x, y);
    if (rot) g.rotate(rot);
    g.drawImage(sp.c, -sp.D / 2, -sp.D / 2, sp.D, sp.D);
    g.restore();
  }
  function dieRaw(g, x, y, s, face, rot, o) {
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
  // apps/casino_sevens.py dice_at, ported: panel px → stage px (one LED = SEV.SC px, the 12 px die = 188 px)
  const SEV = { REST: [[3, 1], [17, 1]], ROLL_Y: 10, DIE: 12, SC: 15.7, X0: 268.7, Y0: 128.8 };
  /** [{x, y, face, h}] in panel px for both dice, `sl` s after the lock (rv: the TV reveal). */
  function sevensDice(rv, sl) {
    const final = arr(obj(rv.outcome).dice);
    const u = clamp((sl - num(rv.lock_s, LOCK)) / num(rv.spin_s, 2.6), 0, 1);
    return [0, 1].map((i) => {
      const lag = 0.06 * i;
      const k = clamp((u - lag) / (1 - lag), 0, 1);
      const hop = 9 * Math.exp(-2.6 * k) * Math.abs(Math.cos(Math.PI * 2.5 * k));
      const ease = 1 - Math.pow(1 - k, 3);
      const x = SEV.REST[i][0] + (26 - 6 * i) * (1 - ease);
      const y = SEV.ROLL_Y - hop;
      const squash = hop < 0.8 && k < 0.92 && k > 0.05 ? SEV.DIE - 2 : SEV.DIE;
      const face = k >= 0.86 ? num(final[i], 1) : num(arr(arr(rv.faces)[i])[Math.floor(18 * (1 - (1 - k) * (1 - k)))], 1);
      return { x, y: y + (SEV.DIE - squash), face, h: squash, k };
    });
  }
  const restDice = (faces) => [0, 1].map((i) => ({ x: SEV.REST[i][0], y: SEV.ROLL_Y, face: num(faces[i], i ? 4 : 3), h: SEV.DIE, k: 1 }));
  const sevens = makeScene({
    id: "casino-sevens",
    app: "casino_sevens",
    init(S) {
      S.fx = { faces: [0, 0] };
    },
    layers(S, root) {
      const box = document.createElement("div");
      const bs = box.style;
      bs.position = "absolute";
      bs.left = `${TRAY.x}px`;
      bs.top = "0px";
      bs.width = `${TRAY.w}px`;
      bs.height = `${TRAY.y + TRAY.h}px`;
      bs.overflow = "hidden";
      bs.pointerEvents = "none";
      root.appendChild(box);
      const D = SEV.DIE * SEV.SC;
      S.L.dice = [0, 1].map(() => {
        const l = layer(box, 0, 0, D + 24, D + 24, wheelK(), true);
        l.c.style.transformOrigin = "0 0";
        return l;
      });
    },
    overlays(S, root) {
      stampLayers(S, root, "stamp");
    },
    move(S) {
      const st = S.st;
      const rv = revealOf(S, "sevens");
      const lastHist = arr(st.history).filter((h) => h.game === "sevens" && h.outcome).slice(-1)[0];
      let dice;
      let alpha = 1;
      if (rv) {
        const sl = sinceLockOf(rv, S.T);
        const lock = num(rv.lock_s, LOCK);
        if (sl < lock) {
          dice = restDice(arr(obj(lastHist && lastHist.outcome).dice));
          alpha = 1 - clamp(sl / 0.3, 0, 1); // the old dice are picked up during NO MORE BETS
        } else {
          dice = sevensDice(rv, sl);
          alpha = clamp((sl - lock) / 0.12, 0, 1);
        }
        const z = SEVENS.findIndex((x) => x.id === obj(rv.outcome).zone);
        stampPaint(S, "stamp", "WIN", S.th.accent);
        stampMove(S, "stamp", 60 + Math.max(0, z) * 478 + 380, 806, sl - lock - num(rv.spin_s, 2.6), 112, 0.16);
      } else {
        dice = restDice(arr(obj(lastHist && lastHist.outcome).dice));
        stampMove(S, "stamp", 0, 0, null);
      }
      dice.forEach((d, i) => {
        const l = S.L.dice[i];
        if (S.fx.faces[i] !== d.face) {
          S.fx.faces[i] = d.face;
          l.g.setTransform(l.k, 0, 0, l.k, 0, 0);
          l.g.clearRect(0, 0, l.w, l.h);
          die(l.g, l.w / 2, l.h / 2, SEV.DIE * SEV.SC, d.face, 0);
        }
        const x = SEV.X0 + d.x * SEV.SC - TRAY.x - 12;
        const y = SEV.Y0 + d.y * SEV.SC - 12;
        l.c.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) scale(1,${(d.h / SEV.DIE).toFixed(3)})`;
        l.c.style.opacity = alpha.toFixed(3);
      });
    },
    slowHz: (S) => (S.st.phase === "betting" && S.st.ends_in != null ? 1 : 0),
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
      const th = S.th;
      const ph = st.phase;
      const cx = TRAY.x + TRAY.w / 2;
      const cy = TRAY.y + TRAY.h / 2;
      const out = obj(obj(st.result).outcome);
      const res = ph === "result" && Array.isArray(out.dice) ? out : null;
      if (res) txt(g, String(res.sum), cx, TRAY.y + 98, 110, "#fff", { align: "center", weight: 900, glow: (SEVENS.find((s) => s.id === res.zone) || SEVENS[0]).col });
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
      SEVENS.forEach((z, i) => {
        const x = 60 + i * 478;
        const isWin = res && res.zone === z.id;
        if (isWin) glowBox(g, x, 640, 456, 300, z.col, 1);
        const tot = num(obj(st.totals)[z.id]);
        if (tot) txt(g, `${fmt(S, tot)} on it`, x + 426, 712, 24, INK2, { align: "right", font: "mono", weight: 700 });
        spotChips(S, g, z.id, sb[z.id], x + 228, 820, t, { r: 34, glow: isWin ? th.accent : null, dim: res && !isWin });
      });
      if (res) winnersCard(S, g, 1020, 40, 480, t, { instant: true, max: 2 });
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
  /** casino/games/baccarat.py deal_times: when each card lands, seconds after the deal starts (lock + LOCK). */
  function bacDealTimes(o) {
    const out = [["player", 0, 0.3], ["banker", 0, 0.9], ["player", 1, 1.5], ["banker", 1, 2.1]];
    let t = 2.1;
    if (arr(o.player).length === 3) out.push(["player", 2, (t += 1.6)]);
    if (arr(o.banker).length === 3) out.push(["banker", 2, (t += 1.6)]);
    return out;
  }
  /** Seconds into the deal on the engine's clock (99 once the coup is settled), or null without a reveal. */
  function bacDealT(S) {
    const rv = revealOf(S, "baccarat");
    if (!rv) return null;
    return S.st.phase === "result" ? 99 : sinceLockOf(rv, S.T) - num(rv.lock_s, LOCK);
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
    overlays(S, root) {
      stampLayers(S, root, "stamp");
    },
    // the coup is dealt on the panel's clock (deal_times); the table layer redraws as each card lands
    key: (S) => {
      const rv = revealOf(S, "baccarat");
      const td = bacDealT(S);
      return rv && td != null ? bacDealTimes(obj(rv.outcome)).filter((c) => td >= c[2]).length : "";
    },
    slowHz: (S) => (S.st.phase === "betting" && S.st.ends_in != null ? 1 : revealOf(S, "baccarat") ? 0 : 2),
    move(S) {
      const rv = revealOf(S, "baccarat");
      const o = rv ? obj(rv.outcome) : null;
      if (!o || !o.winner) return stampMove(S, "stamp", 0, 0, null);
      const times = bacDealTimes(o);
      const td = bacDealT(S);
      const b = BAC_BETS.find((x) => x.id === o.winner) || BAC_BETS[1];
      stampPaint(S, "stamp", o.winner === "tie" ? "TIE" : "WIN", S.th.accent);
      stampMove(S, "stamp", b.x + b.w / 2, 600, (S.st.phase === "result" ? 99 : td) - (times[times.length - 1][2] + 0.6), 116, -0.15);
    },
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const ph = st.phase;
      const res = ph === "result" ? obj(obj(st.result).outcome) : null;
      const rv = revealOf(S, "baccarat");
      const td = bacDealT(S);
      const cards = { player: [], banker: [] };
      const ages = {};
      if (rv && td != null) {
        const o = obj(rv.outcome);
        for (const [side, i, at] of bacDealTimes(o))
          if (td >= at) {
            cards[side][i] = arr(o[side])[i];
            ages[`${side}${i}`] = td - at;
          }
      } else if (res) {
        cards.player = arr(res.player);
        cards.banker = arr(res.banker);
      } else if (ph === "dealing") {
        cards.player = arr(obj(st.cards).player);
        cards.banker = arr(obj(st.cards).banker);
      }
      const totals = {};
      for (const side of ["player", "banker"]) {
        const shownCodes = [];
        cards[side].forEach((code, i) => {
          if (!code) return;
          const [x, y, rot] = bacCardXY(side, i);
          const age = ages[`${side}${i}`];
          const f = age != null ? flyAge(S, age, BAC_SHOE[0], BAC_SHOE[1] - 60, x, y, 0.5) : cardFly(S, `${side}${i}`, BAC_SHOE[0], BAC_SHOE[1] - 60, x, y, t, 0.6);
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
        for (const side of ["player", "banker"]) if (res.winner === side || res.winner === "tie") glowBox(g, BAC_SLOTS[side].x, 150, BAC_SLOTS[side].w, 300, res.winner === "tie" ? "#3ddc84" : BAC_SLOTS[side].col, 1);
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
        if (res && wins.has(b.id)) glowBox(g, b.x, 480, b.w, 200, th.accent, 1, 8);
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
  // casino/games/andarbahar.py deal_pace / DEAL_LEAD and the panel's FLY: card j lands at LEAD + j·pace
  const AB_LEAD = 0.9;
  const AB_FLY = 0.25;
  const abPace = (n) => Math.max(0.18, Math.min(0.6, 9 / Math.max(1, n)));
  /** The deal on the panel's clock: {t (s into the deal), k (cards dealt), n, done} or null without a reveal. */
  function abDeal(S) {
    const rv = revealOf(S, "andarbahar");
    if (!rv) return null;
    const o = obj(rv.outcome);
    const n = num(o.count, arr(o.cards).length);
    if (S.st.phase === "result") return { o, t: 99, k: n, n, done: true };
    const t = sinceLockOf(rv, S.T) - num(rv.lock_s, LOCK);
    const pace = abPace(n);
    const k = t < AB_LEAD ? 0 : Math.min(n, 1 + Math.floor((t - AB_LEAD) / pace));
    return { o, t, k, n, done: k >= n && t >= AB_LEAD + (n - 1) * pace + AB_FLY };
  }
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
    overlays(S, root) {
      stampLayers(S, root, "stamp");
    },
    key: (S) => {
      const d = abDeal(S);
      return d ? `${d.k}|${d.done}|${d.t < 0.5}` : "";
    },
    slowHz: (S) => (S.st.phase === "betting" && S.st.ends_in != null ? 1 : revealOf(S, "andarbahar") ? 0 : 2),
    move(S) {
      const d = abDeal(S);
      if (!d) return stampMove(S, "stamp", 0, 0, null);
      const w = String(d.o.winner);
      const pace = abPace(d.n);
      stampPaint(S, "stamp", "WIN", S.th.accent);
      stampMove(S, "stamp", w === "andar" ? 400 : 860, 790, d.t - (AB_LEAD + (d.n - 1) * pace + AB_FLY), 120, 0.14);
    },
    draw(S, g, t) {
      const st = S.st;
      const th = S.th;
      const ph = st.phase;
      const d = abDeal(S);
      const out = ph === "result" ? obj(obj(st.result).outcome) : null;
      const deal = d ? d.o : ph === "dealing" ? obj(st.deal) : null;
      const joker = out ? out.joker : deal ? deal.joker : null;
      const first = (out || deal || {}).first || obj(st.rules).first || "andar";
      const cards = out ? arr(out.cards) : d ? arr(d.o.cards).slice(0, d.k) : deal ? arr(deal.cards) : [];
      const matched = out ? true : d ? d.done : deal ? !!deal.matched : false;
      if (joker) {
        const f = d ? flyAge(S, d.t, 235, 400, 235, 400, 0.5) : cardFly(S, "joker", AB_SHOE[0], AB_SHOE[1], 235, 400, t, 0.7);
        drawCard(S, g, joker, f.x, f.y, 200, 280, { flip: f.flip, glow: rgba(th.accent, 0.7) });
      }
      const other = first === "andar" ? "bahar" : "andar";
      const rows = { andar: [], bahar: [] };
      cards.forEach((c, i) => rows[i % 2 === 0 ? first : other].push({ c, i }));
      for (const side of ["andar", "bahar"]) {
        const list = rows[side];
        list.forEach(({ c, i }, j) => {
          const x = abCardX(j, Math.max(list.length, 8));
          const f = d ? flyAge(S, d.t - (AB_LEAD + i * abPace(d.n)), AB_SHOE[0], AB_SHOE[1], x, AB_ROW[side], AB_FLY + 0.15) : cardFly(S, `ab${i}`, AB_SHOE[0], AB_SHOE[1], x, AB_ROW[side], t, 0.45);
          const isMatch = matched && i === cards.length - 1;
          drawCard(S, g, c, f.x, f.y, 110, 154, { flip: f.flip, rot: f.rot, glow: isMatch && f.flip >= 1 ? th.accent : null });
        });
      }
      const winner = out ? out.winner : matched && cards.length ? (cards.length % 2 === 1 ? first : other) : null;
      if (winner && (out || matched)) glowBox(g, 430, AB_ROW[winner] - 110, 1080, 220, TONE[winner], 1);
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
    // the felt as bg() draws it: a flat top and the big arc round the seats
    feltClip: () => {
      const R = BJ_R + 180;
      const a1 = Math.atan2(360 - BJ_C[1], RAIL_X - 40 - BJ_C[0]);
      const a2 = Math.atan2(360 - BJ_C[1], 40 - BJ_C[0]);
      const p = (a) => `${(BJ_C[0] + Math.cos(a) * R).toFixed(1)} ${(BJ_C[1] + Math.sin(a) * R).toFixed(1)}`;
      return `path("M 40 18 L ${RAIL_X - 40} 18 L ${RAIL_X - 40} 360 L ${p(a1)} A ${R} ${R} 0 0 1 ${p(a2)} Z")`;
    },
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
          hudRing(S, `turn${seat.seat}`, x, y, 62, { left: tc.left(t), span: num(obj(st.house).turn_seconds, 20), color: th.accent, low: BAD, lowBelow: 5, label: false, width: 7 });
        }
        const hands = arr(seat.hands);
        const bet = hands.length ? hands.reduce((a, h) => a + num(h.bet), 0) : num(seat.bet);
        const entries = arr(sb.main).filter((e) => String(e.seat) === String(seat.seat));
        if (entries.length) spotChips(S, g, `main`, entries.map((e) => ({ ...e, amount: bet || e.amount })), x, y, t, { r: 30 });
        else if (bet) stack(S, g, x, y, 30, bet, p.color);
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
            return { title: "INSURANCE?", sub: "The dealer shows an ace", tone: "#4a86ff", ring: left != null ? { frac: left / 12, label: Math.ceil(left - 1e-6), color: "#4a86ff", left, span: 12 } : null };
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
      stack(S, g, bx, by, 24, num(seat.bet), p.color);
      txt(g, fmt(S, seat.bet), bx + 32, by + 9, 24, INK1, { font: "mono", weight: 800 });
    }
    // avatar + plate
    const winner = o.winners && o.winners.has(String(seat.seat));
    if (seat.turn) {
      const tc = S.fx.turnCd || (S.fx.turnCd = new Countdown());
      const tb = obj(S.st.table);
      tc.observe(`${seat.seat}|${arr(tb.log).length}|${tb.hand}`, tb.turn_in, S.ctx.stateAt || t);
      hudRing(S, `turn${seat.seat}`, x, y, 58, { left: tc.left(t), span: num(tb.turn_span, 20), color: th.accent, low: BAD, lowBelow: 5, label: false, width: 8 });
    }
    if (winner) {
      g.save();
      circle(g, x, y, 62 + 4 * Math.sin(t * 6));
      g.strokeStyle = th.accent;
      g.lineWidth = 6;
      glowOn(g, th.accent, 30);
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
    const left = leftTo(S, "ends_at", S.clk.ends, t);
    if (left != null) {
      txt(g, "NEXT HAND IN", PK.cx, PK.cy - 40, 30, INK2, { align: "center", weight: 800 });
      txt(g, String(Math.ceil(left - 1e-6)), PK.cx, PK.cy + 60, 110, th.accent, { align: "center", font: "mono", weight: 800, glow: rgba(th.accent, 0.5) });
    } else {
      txt(g, n >= 2 ? "DEALING SOON" : "WAITING FOR PLAYERS", PK.cx, PK.cy, 46, th.accent, { align: "center", weight: 900 });
      txt(g, `${n} in · at least two to deal · ${needs}`, PK.cx, PK.cy + 50, 26, INK2, { align: "center", weight: 650 });
    }
  }

  const pokerClip = () => `ellipse(${PK.rx}px ${PK.ry}px at ${PK.cx}px ${PK.cy}px)`;
  const holdem = makeScene({
    id: "casino-holdem",
    app: "casino_holdem",
    feltClip: pokerClip,
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
        if (pot > 0) stack(S, g, PK.cx - 90, PK.cy - 125, 26, pot, th.accent);
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
    feltClip: pokerClip,
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
        if (num(tb.pot) > 0) stack(S, g, PK.cx - 80, PK.cy - 20, 30, num(tb.pot), th.accent);
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
  /** A housie ball (number n, radius r), stamped from a sprite drawn once per number / size. */
  const ballCache = new Map();
  function ball(g, x, y, r, n, color) {
    const k = chipK(g);
    const key = `${r}|${n}|${color}|${k}|${lite() ? 1 : 0}`;
    let sp = ballCache.get(key);
    if (!sp) {
      if (ballCache.size > 200) ballCache.clear();
      const D = Math.ceil(r * 2.8);
      const m = makeCanvas(D, D, k);
      ballRaw(m.g, D / 2, D / 2, r, n, color);
      sp = { c: m.c, D };
      ballCache.set(key, sp);
    }
    g.drawImage(sp.c, x - sp.D / 2, y - sp.D / 2, sp.D, sp.D);
  }
  function ballRaw(g, x, y, r, n, color) {
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
        if (isLast) glowOn(g, th.accent, 30 * (0.6 + 0.4 * Math.sin(t * 5)));
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
            const left = leftTo(S, "ends_at", S.clk.ends, t);
            const span = num(obj(st.rules).buy_seconds, 45);
            return { title: "BUY TICKETS", sub: `${fmt(S, h.price)} a ticket · up to ${num(h.max, 1)} each`, tone: th.accent, pulse: st.ends_in == null, ring: left != null ? { frac: left / span, label: Math.ceil(left - 1e-6), color: left < 6 ? BAD : th.accent, left, span, base: th.accent, low: BAD, lowBelow: 6 } : null };
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
      S.fx = { pos: [null, null, null], spinT: null };
    },
    ingest(S, st, t) {
      const p = st.playing;
      const fx = S.fx;
      const sp = obj(obj(st.machine).sprites);
      if (sp.symbols) fx.lastSprites = sp;
      if (!p || p.id !== fx.winId) fx.winAt = null;
      if (p && p.win != null && fx.winAt == null) {
        fx.winAt = t;
        fx.winId = p.id;
      }
    },
    // the three reels: small canvases of their own, repainted only while they turn
    layers(S, root) {
      S.L.reels = [0, 1, 2].map((i) => layer(root, SL.rx + i * 230, SL.ry, 210, 3 * SL.cell, S.k, false));
    },
    layersRedraw(S) {
      S.fx.pos = [null, null, null];
    },
    /** The reels on the panel's clock: reel_pos(stop, n, t, i) with the playing spin's stops from tv.reveal. */
    move(S) {
      const st = S.st;
      const fx = S.fx;
      const strips = arr(obj(st.machine).strips).map(String);
      const p = st.playing;
      const rv = revealOf(S, "slots");
      const live = rv && p && rv.spin === p.id;
      const spinT = live ? (rv.paused ? num(rv.t) : S.T - (num(rv.at) - num(rv.t))) : null;
      fx.spinT = spinT;
      const recent = arr(st.recent);
      const last = !p && recent.length ? arr(recent[0].stops) : null;
      for (let i = 0; i < 3; i++) {
        const strip = strips[i] || "";
        const n = Math.max(1, strip.length);
        let pos = 0;
        if (live) pos = reelPos(num(arr(rv.stops)[i]), n, spinT, i);
        else if (p) pos = arr(p.stops)[i] != null ? p.stops[i] : num(fx.pos[i]);
        else if (last && last[i] != null) pos = last[i];
        const prev = fx.pos[i];
        if (prev != null && Math.abs(pos - prev) < 1e-4 && fx.strip !== undefined) continue;
        const moving = prev != null && Math.abs(pos - prev) > 0.08;
        fx.pos[i] = pos;
        const l = S.L.reels[i];
        const g = l.g;
        g.setTransform(l.k, 0, 0, l.k, 0, 0);
        g.clearRect(0, 0, l.w, l.h);
        const base = Math.floor(pos);
        const frac = pos - base;
        for (let r = -2; r <= 2; r++) {
          const ch = strip[mod(base + r, n)] || "_";
          if (ch === "_") continue;
          const y = (1 + r - frac) * SL.cell + SL.cell / 2;
          g.globalAlpha = moving ? 0.75 : 1;
          g.drawImage(slotSprite(S, ch, 20), 105 - 70, y - 70, 140, 140);
        }
        g.globalAlpha = 1;
      }
      fx.strip = strips.join("|");
    },
    key: (S) => `${S.st.playing ? S.st.playing.id : "-"}|${S.fx.spinT != null && S.fx.spinT > SLOT_STOPS[2]}`,
    slowHz: (S) => (S.fx.spinT != null && S.fx.spinT <= SLOT_STOPS[2] ? 0 : 4),
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
      const spinT = fx.spinT;
      // the glass over the reels (the reels turn in their own layers below)
      for (let i = 0; i < 3; i++) {
        const x = SL.rx + i * 230;
        const shadeG = g.createLinearGradient(0, SL.ry, 0, SL.ry + 3 * SL.cell);
        shadeG.addColorStop(0, "rgba(0,0,0,.45)");
        shadeG.addColorStop(0.2, "rgba(0,0,0,0)");
        shadeG.addColorStop(0.8, "rgba(0,0,0,0)");
        shadeG.addColorStop(1, "rgba(0,0,0,.45)");
        g.fillStyle = shadeG;
        g.fillRect(x, SL.ry, 210, 3 * SL.cell);
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
          glowOn(g, LINE_COLORS[li] || th.accent, 20);
          g.stroke();
          g.restore();
        });
      }
      // the lever knob (pulled at the start of a spin)
      const pull = 0;
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
    rouletteCenter, reelPos, bigRoad, hash01, hexRgb, shade, wrapPi, bjSeatXY, pokerSeatXY, EU_WHEEL, US_WHEEL,
    B6_WHEEL, B6, wheelStep, rouletteBallRel, panelR, b6Phi, sevensDice, bacDealTimes, abPace, serverClock, sigOf,
    R_CX, R_CY, BX, BY, SEV, LADDER, RACK_MAX, chipRack, rackOf, breakInto, shortChip, chipStyle, pyRound,
  }; // fmt: skip
  if (TV) {
    TV.casino = API;
    if (typeof TV.registerScene === "function") for (const s of SCENES) TV.registerScene(s);
  }
})();
