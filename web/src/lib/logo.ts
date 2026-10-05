/** The "DeskDot" logo as LEDs: three neon tubes, a drop-cap "D", "esk" and "Dot" ("Desk" rose, "Dot" gold),
 *  built dot by dot at the same time (the D drops in, "esk" types in, "Dot" rains down), then struck
 *  like real neon — a stutter of flashes as the gas catches — a steady hum, a power-down, and round again. Canvas 2D;
 *  cheap enough for the header.
 *
 *  Plain-JS copies of this renderer live in the pages that can't import it (src/deskdot/tv/tv.js, casino.html,
 *  controller.html, web/webapp/join/join.js, web/webapp/host.js — between `// <deskdot-logo>` markers).
 *  tests/test_logo_copies.py fails if their glyphs, tubes, colours or timings drift from this file: change them
 *  everywhere at once. */

// 7-row pixel font (rows 0–1 ascenders / cap height, 2–6 x-height)
const GLYPHS: Record<string, string[]> = {
  D: ["###.", "#..#", "#..#", "#..#", "#..#", "#..#", "###."],
  e: ["....", "....", ".##.", "#..#", "####", "#...", ".###"],
  s: ["....", "....", ".###", "#...", ".##.", "...#", "###."],
  k: ["#...", "#...", "#..#", "#.#.", "##..", "#.#.", "#..#"],
  o: ["....", "....", ".##.", "#..#", "#..#", "#..#", ".##."],
  t: ["...", ".#.", "###", ".#.", ".#.", ".#.", "..#"],
};
/** The word, as its three tubes. */
const TUBES = ["D", "esk", "Dot"];
export const ROWS = 7;

export type Part = 0 | 1 | 2;
type Dot = { x: number; y: number; part: Part; col: number; seed: number; letter: number };

function layout(words: string[], gap: number) {
  const dots: Dot[] = [];
  let x = 0;
  const parts: { from: number; to: number }[] = [];
  let letter = 0;
  words.forEach((w, part) => {
    if (part) x += gap;
    const from = x;
    [...w].forEach((ch, i) => {
      const g = GLYPHS[ch];
      if (i) x += 1;
      g.forEach((row, y) =>
        [...row].forEach((c, dx) => {
          if (c === "#") dots.push({ x: x + dx, y, part: part as Part, col: 0, seed: Math.random(), letter });
        }),
      );
      x += g[0].length;
      letter++;
    });
    parts.push({ from, to: x });
  });
  for (const d of dots) {
    const p = parts[d.part];
    d.col = (d.x - p.from) / Math.max(1, p.to - p.from - 1);
  }
  return { dots, cols: x, parts };
}

/** Neon ignition: the stutter of a tube being struck. [seconds, level] steps, then steady. */
const STRIKE: [number, number][][] = [
  [[0.05, 1], [0.07, 0], [0.03, 0.7], [0.16, 0], [0.04, 1], [0.05, 0.15], [0.09, 0.55], [0.05, 0], [0.06, 0.9], [0.04, 0.4]],
  [[0.04, 0.6], [0.12, 0], [0.05, 1], [0.04, 0], [0.03, 1], [0.22, 0.05], [0.05, 0.8], [0.03, 0.2], [0.07, 1], [0.05, 0.5]],
  [[0.03, 0.8], [0.05, 0], [0.04, 0.5], [0.09, 0], [0.05, 1], [0.03, 0], [0.12, 0.3], [0.04, 1], [0.08, 0.1], [0.06, 0.85]],
];
/** Each tube is struck a moment after the last, like a sign coming on letter-group by letter-group. */
const DELAY = [0, 0.28, 0.12];

/** A warm neon-sign palette: rose, tangerine, gold. */
export const NEON: [string, string, string] = ["#ff3f78", "#ff7419", "#ffcc33"];
/** The DeskDot wordmark's colours: two shades, "Desk" rose and "Dot" gold (the logo still builds in three parts). */
export const LOGO: [string, string, string] = ["#ff3f78", "#ff3f78", "#ffcc33"];

function strike(part: Part, t: number): number {
  if (t < 0) return 0;
  let acc = 0;
  for (const [d, v] of STRIKE[part]) {
    acc += d;
    if (t < acc) return v;
  }
  return 1;
}
const strikeLen = (part: Part) => STRIKE[part].reduce((n, [d]) => n + d, 0);

const easeOut = (k: number) => 1 - (1 - k) ** 3;
const bounce = (k: number) => {
  const n = 7.5625;
  const d = 2.75;
  if (k < 1 / d) return n * k * k;
  if (k < 2 / d) return n * (k -= 1.5 / d) * k + 0.75;
  if (k < 2.5 / d) return n * (k -= 2.25 / d) * k + 0.9375;
  return n * (k -= 2.625 / d) * k + 0.984375;
};

function glowSprite(color: string, size: number) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const r = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  r.addColorStop(0, color);
  r.addColorStop(0.25, color + "aa");
  r.addColorStop(0.6, color + "22");
  r.addColorStop(1, color + "00");
  g.fillStyle = r;
  g.fillRect(0, 0, size, size);
  return c;
}

export type LogoTimeline = {
  build: number; // seconds to assemble the dots
  hold: number; // seconds lit (Infinity = stay lit)
  off: number; // seconds of power-down + scatter
};

export class NeonLogo {
  readonly cols: number;
  readonly rows = ROWS;
  readonly parts: { from: number; to: number }[];
  private dots: Dot[];
  private glows: HTMLCanvasElement[];
  private glitchLetter = 5; // the "o" of Dot: the tube that's a little loose
  colors: string[];

  constructor(colors: string[] = LOGO, gap = 1) {
    const l = layout(TUBES, gap);
    this.dots = l.dots;
    this.cols = l.cols;
    this.parts = l.parts;
    this.colors = colors;
    this.glows = colors.map((c) => glowSprite(c, 64));
  }

  cycle(tl: LogoTimeline) {
    return tl.build + 1.4 + tl.hold + tl.off;
  }

  /** Seconds until the picture changes again (0 = it is moving now: build, strike, the loose letter's blink,
   *  power-down). While lit it only wakes for the blink, so a caller can idle instead of redrawing every frame. */
  wake(t: number, tl: LogoTimeline) {
    const total = this.cycle(tl);
    const lt = Number.isFinite(total) ? t % total : t;
    const igniteAt = tl.build + 0.15;
    const offAt = tl.build + 1.4 + tl.hold;
    const litAt = Math.max(tl.build + 0.6, igniteAt + Math.max(...([0, 1, 2] as Part[]).map((p) => DELAY[p] + strikeLen(p)))) + 0.05;
    if (lt < litAt || lt >= offAt) return 0;
    const g = (lt * 0.37) % 1;
    if (g > 0.61 && g < 0.68) return 0;
    return Math.min(((1.61 - g) % 1) / 0.37, offAt - lt);
  }

  /**
   * Draw at (ox, oy) with dot pitch `p` (CSS px). `t` = seconds since start (loops by itself).
   * `parts` limits drawing to one word (the boot doors draw each half on its own door). `flare` (0..1) is a
   * short flash for the moment the doors unlock: hotter cores, a touch brighter — never a bigger halo.
   */
  draw(ctx: CanvasRenderingContext2D, t: number, ox: number, oy: number, p: number, tl: LogoTimeline, opts: { grid?: boolean; flare?: number; still?: boolean } = {}) {
    const parts: Part[] = [0, 1, 2];
    const flare = opts.flare ?? 0;
    const total = this.cycle(tl);
    const lt = opts.still ? tl.build + 3 : Number.isFinite(total) ? t % total : t;
    const igniteAt = tl.build + 0.15;
    const offAt = tl.build + 1.4 + tl.hold;
    const r = p * 0.36;

    if (opts.grid) {
      // the matrix the logo is lit on: every LED, dark
      ctx.fillStyle = "rgba(255,255,255,0.045)";
      for (let y = 0; y < ROWS; y++)
        for (let x = 0; x < this.cols; x++) {
          ctx.beginPath();
          ctx.arc(ox + (x + 0.5) * p, oy + (y + 0.5) * p, r * 0.7, 0, Math.PI * 2);
          ctx.fill();
        }
    }

    for (const part of parts) {
      // tube level: struck, humming, glitching, dying
      let level = strike(part, lt - igniteAt - DELAY[part]);
      const lit = lt > igniteAt + DELAY[part] + strikeLen(part);
      if (lit) level = opts.still ? 1 : 0.93 + 0.07 * Math.sin(lt * 47 + part * 3) * Math.sin(lt * 13.3);
      let dying = 0;
      if (lt > offAt) {
        dying = Math.min(1, (lt - offAt) / tl.off);
        const sputter = dying < 0.35 ? (Math.sin(lt * 90) > 0.2 ? 1 : 0.25) : 0;
        level = Math.max(0, 1 - dying * 2.4) * (0.5 + sputter * 0.5);
      }
      // the flare is a brief flash, not a bloom: it lifts the tubes a little and heats their cores. Additive halos
      // overlap their neighbours (a halo spans ~3 dots), so growing or brightening them washes the dots into one
      // blur — keep the halo size and strength fixed and the dots stay crisp at every moment.
      level = Math.min(1.08, level + flare * 0.15);
      const color = this.colors[part];
      const glow = this.glows[part];

      for (const d of this.dots) {
        if (d.part !== part) continue;
        // ---- assemble: the "D" drops in, "esk" types in from the left (pop), "Dot" rains down (bounce)
        let x = d.x;
        let y = d.y;
        let k: number;
        let pop = 0;
        if (part === 0) {
          const start = (6 - d.y) * 0.05;
          k = Math.min(1, Math.max(0, (lt - start) / 0.5));
          y = d.y - (1 - bounce(k)) * 9;
        } else if (part === 1) {
          const start = d.col * tl.build * 0.75 + d.y * 0.012;
          k = Math.min(1, Math.max(0, (lt - start) / 0.22));
          pop = k > 0 && k < 1 ? Math.sin(k * Math.PI) : 0;
          x = d.x - (1 - easeOut(k)) * 1.2;
        } else {
          const start = (1 - d.col) * tl.build * 0.55 + d.seed * tl.build * 0.3;
          k = Math.min(1, Math.max(0, (lt - start) / 0.55));
          y = d.y - (1 - bounce(k)) * (6 + d.y);
        }
        if (k <= 0) continue;
        // ---- power-down scatter: "D" and "esk" sweep out to the right, "Dot" falls away
        let fade = 1;
        if (dying > 0.35) {
          const q = Math.min(1, Math.max(0, (dying - 0.35) / 0.65 - (part === 2 ? d.seed * 0.3 : d.col * 0.4)));
          fade = 1 - q;
          if (part !== 2) x += easeOut(q) * 3;
          else y += q * q * 9;
          if (fade <= 0) continue;
        }
        // the loose tube: one letter blinks out for a beat now and then
        let lv = level;
        if (lit && !opts.still && dying === 0 && d.letter === this.glitchLetter) {
          const g = (lt * 0.37) % 1;
          if (g > 0.62 && g < 0.645) lv *= 0.1;
          else if (g > 0.66 && g < 0.672) lv *= 0.3;
        }
        const cx = ox + (x + 0.5) * p;
        const cy = oy + (y + 0.5) * p;
        // unlit glass: the tube is visible before it's struck
        ctx.globalAlpha = 0.22 * fade * Math.min(1, k * 2);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(cx, cy, r * (1 + pop * 0.6), 0, Math.PI * 2);
        ctx.fill();
        const light = Math.max(lv, pop * 0.9) * fade;
        if (light > 0.02) {
          ctx.globalCompositeOperation = "lighter";
          // the halo the gas throws on the wall
          ctx.globalAlpha = Math.min(0.5, light * 0.5);
          const gs = p * 3.4;
          ctx.drawImage(glow, cx - gs / 2, cy - gs / 2, gs, gs);
          // the tube itself, then its white-hot core
          ctx.globalAlpha = Math.min(1, light);
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(cx, cy, r * (1 + pop * 0.5), 0, Math.PI * 2);
          ctx.fill();
          // a small hot core keeps each tube's colour readable
          ctx.globalAlpha = Math.min(1, light * 0.5 + flare * 0.35);
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
}
