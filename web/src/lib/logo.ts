/** The "idotmatrix" logo as LEDs: three neon tubes, "i", "dot" and "matrix", each its own colour, built dot by dot
 *  at the same time (the i drops in, "dot" types in, "matrix" rains down), then struck like real neon — a stutter of
 *  flashes as the gas catches — a steady hum, a power-down, and round again. Canvas 2D; cheap enough for the header. */

// 7-row lowercase pixel font (rows 0–1 ascenders, 2–6 x-height)
const GLYPHS: Record<string, string[]> = {
  i: ["#", ".", "#", "#", "#", "#", "#"],
  d: ["...#", "...#", ".###", "#..#", "#..#", "#..#", ".###"],
  o: ["....", "....", ".##.", "#..#", "#..#", "#..#", ".##."],
  t: ["...", ".#.", "###", ".#.", ".#.", ".#.", "..#"],
  m: [".....", ".....", "####.", "#.#.#", "#.#.#", "#.#.#", "#.#.#"],
  a: ["....", "....", ".###", "...#", ".###", "#..#", ".###"],
  r: ["....", "....", "#.##", "##..", "#...", "#...", "#..."],
  x: [".....", ".....", "#...#", ".#.#.", "..#..", ".#.#.", "#...#"],
};
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

/** A neon-sign palette: hot pink, amber, ice cyan. */
export const NEON: [string, string, string] = ["#ff2d78", "#ffb21a", "#1fe0ff"];

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
  private glitchLetter = 7; // the "r" of matrix: the tube that's a little loose
  colors: string[];

  constructor(colors: string[] = NEON, gap = 1) {
    const l = layout(["i", "dot", "matrix"], gap);
    this.dots = l.dots;
    this.cols = l.cols;
    this.parts = l.parts;
    this.colors = colors;
    this.glows = colors.map((c) => glowSprite(c, 64));
  }

  cycle(tl: LogoTimeline) {
    return tl.build + 1.4 + tl.hold + tl.off;
  }

  /**
   * Draw at (ox, oy) with dot pitch `p` (CSS px). `t` = seconds since start (loops by itself).
   * `parts` limits drawing to one word (the boot doors draw each half on its own door). `flare` (0..1) overdrives
   * the glow, for the moment the doors unlock.
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
      if (lit) level = 0.93 + 0.07 * Math.sin(lt * 47 + part * 3) * Math.sin(lt * 13.3);
      let dying = 0;
      if (lt > offAt) {
        dying = Math.min(1, (lt - offAt) / tl.off);
        const sputter = dying < 0.35 ? (Math.sin(lt * 90) > 0.2 ? 1 : 0.25) : 0;
        level = Math.max(0, 1 - dying * 2.4) * (0.5 + sputter * 0.5);
      }
      level = Math.min(1.6, level + flare * 0.8);
      const color = this.colors[part];
      const glow = this.glows[part];

      for (const d of this.dots) {
        if (d.part !== part) continue;
        // ---- assemble: the "i" drops in, "dot" types in from the left (pop), "matrix" rains down (bounce)
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
        // ---- power-down scatter: "i" and "dot" sweep out to the right, "matrix" falls away
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
        if (lit && dying === 0 && d.letter === this.glitchLetter) {
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
          ctx.globalAlpha = Math.min(1, light * 0.5);
          const gs = p * (3.4 + flare * 2.5);
          ctx.drawImage(glow, cx - gs / 2, cy - gs / 2, gs, gs);
          // the tube itself, then its white-hot core
          ctx.globalAlpha = Math.min(1, light);
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(cx, cy, r * (1 + pop * 0.5), 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = Math.min(1, light * 0.8);
          ctx.fillStyle = "#ffffff";
          ctx.beginPath();
          ctx.arc(cx, cy, r * 0.45, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalCompositeOperation = "source-over";
        }
      }
    }
    ctx.globalAlpha = 1;
  }
}
