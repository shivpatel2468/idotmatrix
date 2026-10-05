import { type LogoTimeline, NEON, NeonLogo } from "../../lib/logo";
import { drawSilverCoin } from "../../lib/coinArt";
import { sfx } from "../../lib/sound";
import type { DoorPose } from "./sunset";

/** Intro theme "Coin Gate": an arcade cabinet front. The whole screen is a heavy brushed-steel gate split down the
 *  middle by interlocking teeth; the idotmatrix neon sign glows in a backlit marquee at the top and a coin door sits
 *  below it — a blinking INSERT COIN display, a backlit coin slot (on the seam), a service lock, a coin-return
 *  button, a CREDIT counter and a ring of chase bulbs.
 *
 *  Intro: a silver coin flies in spinning, turns edge-on, knocks the slot rim and drops in; the slot light runs down
 *  the mech, the bulbs chase round, CREDIT 0 → 1. Opening: the lock bolts retract with a clunk, the gate strains,
 *  then the halves grind apart (gears turning, a little shake, motion blur) and reveal the studio. Outro: the halves
 *  slam back together, the bolts shoot home, and the door waits for the next coin.
 *
 *  One full-screen canvas: the static gate is painted once per size; each frame redraws the live parts into an
 *  offscreen face and blits it twice, clipped to each half along the toothed seam. Reduced motion: no flight, no
 *  shake or blur; the gate fades instead of sliding. */

const BOOT_LOGO: LogoTimeline = { build: 1.3, hold: Infinity, off: 1 };

// the coin's sequence (seconds since it was armed; it starts negative = a short wait)
const HIT = 0.8; // the coin reaches the slot (flight is 0 → HIT)
const IN = 1.1; // … and is gone inside
const ROLL = 1.45; // rolling through the mech
const CREDIT = 1.85; // CREDIT 1
const READY = CREDIT + 0.3; // the gate may open from here

const OPEN_S = 2.2;
const CLOSE_S = 1.15;

// a 5-row LED font for the coin door's displays
const F: Record<string, string[]> = {
  I: ["###", ".#.", ".#.", ".#.", "###"],
  N: ["#..#", "##.#", "#.##", "#..#", "#..#"],
  S: [".##", "#..", ".#.", "..#", "##."],
  E: ["###", "#..", "##.", "#..", "###"],
  R: ["##.", "#.#", "##.", "#.#", "#.#"],
  T: ["###", ".#.", ".#.", ".#.", ".#."],
  C: [".##", "#..", "#..", "#..", ".##"],
  O: [".#.", "#.#", "#.#", "#.#", ".#."],
  D: ["##.", "#.#", "#.#", "#.#", "##."],
  G: [".##", "#..", "#.#", "#.#", ".##"],
  A: [".#.", "#.#", "###", "#.#", "#.#"],
  Y: ["#.#", "#.#", ".#.", ".#.", ".#."],
  W: ["#...#", "#...#", "#.#.#", "#.#.#", ".#.#."],
  L: ["#..", "#..", "#..", "#..", "###"],
  M: ["#...#", "##.##", "#.#.#", "#...#", "#...#"],
  " ": ["..", "..", "..", "..", ".."],
  "0": ["###", "#.#", "#.#", "#.#", "###"],
  "1": [".#.", "##.", ".#.", ".#.", "###"],
};
const textCache = new Map<string, { cols: number; dots: [number, number][] }>();
function textDots(s: string) {
  let r = textCache.get(s);
  if (r) return r;
  const dots: [number, number][] = [];
  let x = 0;
  [...s].forEach((ch, i) => {
    const g = F[ch] ?? F[" "];
    if (i) x += 1;
    g.forEach((row, y) => [...row].forEach((c, dx) => c === "#" && dots.push([x + dx, y])));
    x += g[0].length;
  });
  r = { cols: x, dots };
  textCache.set(s, r);
  return r;
}

function canvas(w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w));
  c.height = Math.max(1, Math.round(h));
  return c;
}

function rng(seed: number) {
  let s = seed;
  return () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
}

const clamp01 = (k: number) => Math.min(1, Math.max(0, k));
const easeOut = (k: number) => 1 - (1 - k) ** 3;
const easeInOut = (k: number) => (k < 0.5 ? 4 * k ** 3 : 1 - (-2 * k + 2) ** 3 / 2);

type Rect = { x: number; y: number; w: number; h: number };
type Disp = Rect & { cols: number; dp: number };
type Gear = { x: number; y: number; r: number; teeth: number; dir: 1 | -1; ratio: number };

type Layout = {
  cx: number;
  td: number; // tooth depth
  p: number; // logo dot pitch
  lox: number;
  loy: number;
  mq: Rect; // marquee
  door: Rect;
  D: number; // coin-door width
  d1: Disp; // INSERT COIN display
  d2: Disp; // CREDIT display
  ins: Rect; // the backlit coin insert
  slot: Rect;
  lock: { x: number; y: number; r: number };
  ret: { x: number; y: number; s: number };
  bulbs: [number, number][]; // round the coin door, in chase order
  mBulbs: [number, number][]; // along the marquee
  br: number; // bulb radius
  gears: Gear[];
  bolts: number[]; // y of each lock bolt
  bl: number; // bolt length
  bh: number; // bolt height
  hb: number; // hazard band height
  seam: [number, number][];
  teeth: [number, number][]; // the toothed stretches of the seam (y from → to)
};

function rr(g: CanvasRenderingContext2D, r: Rect, rad: number) {
  g.beginPath();
  g.roundRect(r.x, r.y, r.w, r.h, rad);
}

/** Bulbs along a horizontal edge, symmetric about the seam and never on it. */
function rowBulbs(cx: number, half: number, y: number, s: number): [number, number][] {
  const n = Math.max(1, Math.floor(half / s));
  const out: [number, number][] = [];
  for (let k = n - 1; k >= 0; k--) out.push([cx - (k + 0.5) * s, y]);
  for (let k = 0; k < n; k++) out.push([cx + (k + 0.5) * s, y]);
  return out;
}

function layout(w: number, h: number, cols: number): Layout {
  const cx = Math.round(w / 2);
  // phones: the sign fills ~80 % of the width (with its marquee, never wider than the screen)
  const p = w < 640 ? Math.min(22, (w * 0.8) / cols) : Math.max(9, Math.min(24, (w * 0.5) / cols));
  const padX = Math.max(10, p * 1.6);
  const padY = Math.max(8, p * 1.3);
  const mqW = cols * p + padX * 2;
  const mqH = 7 * p + padY * 2;
  const mq = { x: cx - mqW / 2, y: Math.max(16, h * 0.06), w: mqW, h: mqH };
  const lox = Math.round(cx - Math.round(cols / 2) * p);
  const loy = mq.y + padY;
  const doorTop = mq.y + mqH + Math.max(18, h * 0.05);
  // the status panel sits at 71 % of the height: the door ends above it
  const D = Math.max(140, Math.min(w * 0.84, 360, (h * 0.68 - doorTop) / 0.92));
  const door = { x: cx - D / 2, y: doorTop, w: D, h: D * 0.92 };
  const dp1 = (D * 0.84) / 46;
  const d1 = { x: cx - 23 * dp1, y: door.y + D * 0.07, w: 46 * dp1, h: 7 * dp1, cols: 46, dp: dp1 };
  const dp2 = (D * 0.5) / 32;
  const d2 = { x: cx - 16 * dp2, y: door.y + D * 0.7, w: 32 * dp2, h: 7 * dp2, cols: 32, dp: dp2 };
  const ins = { x: cx - D * 0.1, y: door.y + D * 0.27, w: D * 0.2, h: D * 0.34 };
  const sw = Math.max(4, D * 0.026);
  const slot = { x: cx - sw / 2, y: ins.y + ins.h * 0.2, w: sw, h: ins.h * 0.58 };
  const lock = { x: cx - D * 0.3, y: ins.y + ins.h * 0.45, r: D * 0.065 };
  const ret = { x: cx + D * 0.3, y: ins.y + ins.h * 0.45, s: D * 0.13 };
  // chase bulbs round the door, clockwise from the top-left
  const inset = D * 0.035;
  const s = D * 0.085;
  const top = rowBulbs(cx, D / 2 - inset - s * 0.3, door.y + inset, s);
  const bottom = rowBulbs(cx, D / 2 - inset - s * 0.3, door.y + door.h - inset, s).reverse();
  const side = (x: number, down: boolean) => {
    const out: [number, number][] = [];
    const n = Math.max(1, Math.floor((door.h - inset * 2) / s) - 1);
    for (let i = 1; i <= n; i++) {
      const y = door.y + inset + ((door.h - inset * 2) * i) / (n + 1);
      out.push([x, y]);
    }
    return down ? out : out.reverse();
  };
  const bulbs = [...top, ...side(door.x + door.w - inset, true), ...bottom, ...side(door.x + inset, false)];
  const ms = Math.max(14, p * 2.2);
  const mBulbs = [...rowBulbs(cx, mqW / 2 - ms * 0.4, mq.y + mqH + 7, ms)];
  const br = Math.max(1.6, D * 0.011);
  const td = Math.max(10, Math.min(18, w * 0.018));
  const hb = Math.max(14, Math.min(26, h * 0.03));
  // gears beside the coin door, when the screen has room for them
  const room = (w - D) / 2 - 24;
  const R = Math.min(D * 0.2, room * 0.36);
  const gears: Gear[] = [];
  if (R >= 22) {
    for (const dir of [-1, 1] as const) {
      const gx = cx + dir * (D / 2 + 16 + R * 1.1);
      const gy = door.y + door.h * 0.42;
      const r2 = R * 0.52;
      const a = (55 * Math.PI) / 180;
      const dist = (R + r2) * 0.9;
      gears.push({ x: gx, y: gy, r: R, teeth: 16, dir, ratio: 1 });
      gears.push({ x: gx + dir * Math.cos(a) * dist, y: gy + Math.sin(a) * dist, r: r2, teeth: 9, dir: -dir as 1 | -1, ratio: R / r2 });
    }
  }
  // lock bolts across the seam: between the marquee and the door, below the door, and near the bottom
  const bh = Math.max(8, D * 0.035);
  const bl = Math.max(24, D * 0.12);
  const bolts: number[] = [];
  const gapA = door.y - (mq.y + mqH);
  if (gapA > bh + 10) bolts.push(mq.y + mqH + gapA / 2);
  const below = h * 0.71 - (door.y + door.h);
  if (below > bh + 14) bolts.push(door.y + door.h + below / 2);
  bolts.push(h - hb - Math.max(18, h * 0.045));
  // the seam: straight through the marquee and the door, teeth everywhere else
  const flats: [number, number][] = [
    [mq.y - 10, mq.y + mqH + 10],
    [door.y - 10, door.y + door.h + 10],
  ];
  const seam: [number, number][] = [[cx, -20]];
  const teeth: [number, number][] = [];
  let y = 0;
  const zones: [number, number][] = [];
  for (const [a, b] of flats) {
    if (a > y) zones.push([y, a]);
    y = Math.max(y, b);
  }
  if (y < h) zones.push([y, h]);
  for (const [a, b] of zones) {
    const len = b - a;
    const n = Math.floor(len / (td * 3.2));
    seam.push([cx, a]);
    if (n < 1) continue;
    teeth.push([a, b]);
    const L = len / n;
    for (let i = 0; i < n; i++) {
      const y0 = a + i * L;
      const off = td / 2;
      seam.push([cx + off, y0 + L * 0.1], [cx + off, y0 + L * 0.4], [cx - off, y0 + L * 0.6], [cx - off, y0 + L * 0.9], [cx, y0 + L]);
    }
  }
  seam.push([cx, h + 20]);
  return { cx, td, p, lox, loy, mq, door, D, d1, d2, ins, slot, lock, ret, bulbs, mBulbs, br, gears, bolts, bl, bh, hb, seam, teeth };
}

function hazard(g: CanvasRenderingContext2D, r: Rect, a: string, b: string, step: number) {
  g.save();
  g.beginPath();
  g.rect(r.x, r.y, r.w, r.h);
  g.clip();
  g.fillStyle = b;
  g.fillRect(r.x, r.y, r.w, r.h);
  g.fillStyle = a;
  for (let x = r.x - r.h - step * 2; x < r.x + r.w + r.h; x += step * 2) {
    g.beginPath();
    g.moveTo(x, r.y + r.h);
    g.lineTo(x + step, r.y + r.h);
    g.lineTo(x + step + r.h, r.y);
    g.lineTo(x + r.h, r.y);
    g.closePath();
    g.fill();
  }
  g.restore();
}

function rivet(g: CanvasRenderingContext2D, x: number, y: number, r: number) {
  const rg = g.createRadialGradient(x - r * 0.35, y - r * 0.4, r * 0.1, x, y, r);
  rg.addColorStop(0, "#d9dde3");
  rg.addColorStop(0.45, "#6f757e");
  rg.addColorStop(1, "#1d2025");
  g.fillStyle = "rgba(0,0,0,0.45)";
  g.beginPath();
  g.arc(x + r * 0.25, y + r * 0.35, r * 1.05, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = rg;
  g.beginPath();
  g.arc(x, y, r, 0, Math.PI * 2);
  g.fill();
}

function chrome(g: CanvasRenderingContext2D, r: Rect) {
  const cg = g.createLinearGradient(0, r.y, 0, r.y + r.h);
  cg.addColorStop(0, "#c9ced6");
  cg.addColorStop(0.18, "#6c727b");
  cg.addColorStop(0.5, "#a7adb6");
  cg.addColorStop(0.82, "#4a4f57");
  cg.addColorStop(1, "#8d939c");
  return cg;
}

function gearSprite(r: number, teeth: number) {
  const size = Math.ceil(r * 2 + 6);
  const c = canvas(size * 2, size * 2); // drawn at 2x for crisp rotation
  const g = c.getContext("2d")!;
  g.scale(2, 2);
  g.translate(size / 2, size / 2);
  const ro = r;
  const ri = r * 0.84;
  g.beginPath();
  for (let i = 0; i < teeth; i++) {
    const a0 = (i / teeth) * Math.PI * 2;
    const a1 = ((i + 0.5) / teeth) * Math.PI * 2;
    const st = (Math.PI * 2) / teeth;
    const pts: [number, number][] = [
      [ri, a0],
      [ro, a0 + st * 0.12],
      [ro, a1 - st * 0.12],
      [ri, a1],
    ];
    pts.forEach(([rad, a], k) => {
      const x = Math.cos(a) * rad;
      const y = Math.sin(a) * rad;
      if (i === 0 && k === 0) g.moveTo(x, y);
      else g.lineTo(x, y);
    });
    g.arc(0, 0, ri, a1, a0 + st);
  }
  g.closePath();
  const fg = g.createLinearGradient(-r, -r, r, r);
  fg.addColorStop(0, "#9aa1aa");
  fg.addColorStop(0.5, "#4c525a");
  fg.addColorStop(1, "#2a2e34");
  g.fillStyle = fg;
  g.shadowColor = "rgba(0,0,0,0.6)";
  g.shadowBlur = 6;
  g.shadowOffsetY = 2;
  g.fill();
  g.shadowColor = "transparent";
  g.strokeStyle = "rgba(255,255,255,0.18)";
  g.lineWidth = 1;
  g.stroke();
  // lightening holes and the hub
  g.globalCompositeOperation = "destination-out";
  const holes = teeth > 12 ? 5 : 3;
  for (let i = 0; i < holes; i++) {
    const a = (i / holes) * Math.PI * 2;
    g.beginPath();
    g.arc(Math.cos(a) * r * 0.5, Math.sin(a) * r * 0.5, r * (teeth > 12 ? 0.17 : 0.2), 0, Math.PI * 2);
    g.fill();
  }
  g.globalCompositeOperation = "source-over";
  g.fillStyle = "#1b1e22";
  g.beginPath();
  g.arc(0, 0, r * 0.2, 0, Math.PI * 2);
  g.fill();
  rivet(g, 0, 0, r * 0.11);
  return c;
}

type Static = { face: HTMLCanvasElement; gearC: HTMLCanvasElement[] };

/** The gate, painted once per size: steel, rivets, hazard stripes, the marquee box, the coin door and its parts. */
function paintStatic(w: number, h: number, dpr: number, Lo: Layout): Static {
  const face = canvas(w * dpr, h * dpr);
  const g = face.getContext("2d")!;
  g.scale(dpr, dpr);
  const rand = rng(41);
  const { cx, mq, door, D } = Lo;
  // brushed steel, a soft sheen across it
  const base = g.createLinearGradient(0, 0, 0, h);
  base.addColorStop(0, "#2b2f36");
  base.addColorStop(0.5, "#1f2228");
  base.addColorStop(1, "#131519");
  g.fillStyle = base;
  g.fillRect(0, 0, w, h);
  for (let y = 0; y < h; y += 1) {
    const a = rand() * 0.035;
    g.fillStyle = rand() < 0.5 ? `rgba(255,255,255,${a})` : `rgba(0,0,0,${a * 1.6})`;
    g.fillRect(0, y, w, 1);
  }
  const sheen = g.createLinearGradient(0, 0, w, h);
  sheen.addColorStop(0, "rgba(255,255,255,0)");
  sheen.addColorStop(0.42, "rgba(255,255,255,0.05)");
  sheen.addColorStop(0.5, "rgba(255,255,255,0.08)");
  sheen.addColorStop(0.58, "rgba(255,255,255,0.03)");
  sheen.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = sheen;
  g.fillRect(0, 0, w, h);
  // panel lines and rivets on each half (mirrored)
  const wide = Math.max(mq.w, D) / 2;
  const px = wide + (w / 2 - wide) * 0.55;
  const rr0 = Math.max(2.4, Math.min(4, w * 0.003));
  for (const dir of [-1, 1]) {
    if (w / 2 - px > 30) {
      const x = cx + dir * px;
      g.fillStyle = "rgba(0,0,0,0.55)";
      g.fillRect(x - 1, 0, 2, h - Lo.hb);
      g.fillStyle = "rgba(255,255,255,0.06)";
      g.fillRect(x + 1, 0, 1, h - Lo.hb);
      for (let y = 28; y < h - Lo.hb - 14; y += 56) {
        rivet(g, x - 9, y, rr0);
        rivet(g, x + 9, y, rr0);
      }
    }
    for (let x = 22; x < w / 2 - 20; x += 60) {
      rivet(g, cx + dir * (w / 2 - x), 12, rr0);
      rivet(g, cx + dir * (w / 2 - x), h - Lo.hb - 10, rr0);
    }
  }
  // the bottom hazard band
  hazard(g, { x: 0, y: h - Lo.hb, w, h: Lo.hb }, "#d9a514", "#141518", Lo.hb * 0.9);
  g.fillStyle = "rgba(0,0,0,0.6)";
  g.fillRect(0, h - Lo.hb - 2, w, 2);
  // hazard stripes along the toothed seam, so the interlock reads as a zipper
  const zip = Lo.td * 1.25;
  for (const [a, b] of Lo.teeth) {
    const bot = Math.min(b, h - Lo.hb - 2);
    if (bot > a) hazard(g, { x: cx - zip, y: a, w: zip * 2, h: bot - a }, "rgba(217,165,20,0.55)", "rgba(10,10,12,0.6)", Lo.td * 0.7);
  }
  // the seam groove
  g.beginPath();
  Lo.seam.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
  g.strokeStyle = "rgba(0,0,0,0.85)";
  g.lineWidth = 2.5;
  g.stroke();
  g.save();
  g.translate(1.5, 0);
  g.strokeStyle = "rgba(255,255,255,0.07)";
  g.lineWidth = 1;
  g.stroke();
  g.restore();

  // ---- the marquee: a chrome bezel round a black glass box
  const bez = 6;
  const mo = { x: mq.x - bez, y: mq.y - bez, w: mq.w + bez * 2, h: mq.h + bez * 2 };
  g.save();
  g.shadowColor = "rgba(0,0,0,0.7)";
  g.shadowBlur = 18;
  g.shadowOffsetY = 6;
  g.fillStyle = chrome(g, mo);
  rr(g, mo, 10);
  g.fill();
  g.restore();
  const glass = g.createLinearGradient(0, mq.y, 0, mq.y + mq.h);
  glass.addColorStop(0, "#0d0910");
  glass.addColorStop(1, "#050407");
  g.fillStyle = glass;
  rr(g, mq, 6);
  g.fill();
  g.strokeStyle = "rgba(0,0,0,0.8)";
  g.lineWidth = 1.5;
  g.stroke();
  for (const [x, y] of [[mo.x + 7, mo.y + 7], [mo.x + mo.w - 7, mo.y + 7], [mo.x + 7, mo.y + mo.h - 7], [mo.x + mo.w - 7, mo.y + mo.h - 7]] as const)
    rivet(g, x, y, 2.6);
  // bulb sockets along the marquee
  for (const [x, y] of Lo.mBulbs) {
    g.fillStyle = "#0c0d10";
    g.beginPath();
    g.arc(x, y, Lo.br + 1.6, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "rgba(255,220,170,0.12)";
    g.beginPath();
    g.arc(x, y, Lo.br, 0, Math.PI * 2);
    g.fill();
  }

  // ---- the coin door
  g.save();
  g.shadowColor = "rgba(0,0,0,0.75)";
  g.shadowBlur = 22;
  g.shadowOffsetY = 8;
  const body = g.createLinearGradient(0, door.y, 0, door.y + door.h);
  body.addColorStop(0, "#41454d");
  body.addColorStop(0.5, "#2b2e34");
  body.addColorStop(1, "#1d2024");
  g.fillStyle = body;
  rr(g, door, D * 0.05);
  g.fill();
  g.restore();
  g.strokeStyle = "rgba(255,255,255,0.16)";
  g.lineWidth = 1.2;
  rr(g, { x: door.x + 0.5, y: door.y + 0.5, w: door.w - 1, h: door.h - 1 }, D * 0.05);
  g.stroke();
  g.strokeStyle = "rgba(0,0,0,0.5)";
  rr(g, { x: door.x + D * 0.06, y: door.y + D * 0.06, w: door.w - D * 0.12, h: door.h - D * 0.12 }, D * 0.03);
  g.stroke();
  const ri = D * 0.06;
  for (const [x, y] of [[door.x + ri, door.y + ri], [door.x + door.w - ri, door.y + ri], [door.x + ri, door.y + door.h - ri], [door.x + door.w - ri, door.y + door.h - ri]] as const)
    rivet(g, x, y, Math.max(2.2, D * 0.012));
  for (const [x, y] of Lo.bulbs) {
    g.fillStyle = "#0c0d10";
    g.beginPath();
    g.arc(x, y, Lo.br + 1.4, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "rgba(255,220,170,0.1)";
    g.beginPath();
    g.arc(x, y, Lo.br, 0, Math.PI * 2);
    g.fill();
  }
  // the two LED displays: black windows, every LED dark
  for (const d of [Lo.d1, Lo.d2]) {
    const pad = d.dp * 0.8;
    g.fillStyle = "#050506";
    rr(g, { x: d.x - pad, y: d.y - pad * 0.6, w: d.w + pad * 2, h: d.h + pad * 1.2 }, 3);
    g.fill();
    g.strokeStyle = "rgba(255,255,255,0.12)";
    g.lineWidth = 1;
    g.stroke();
    g.fillStyle = "rgba(255,255,255,0.05)";
    for (let y = 0; y < 7; y++)
      for (let x = 0; x < d.cols; x++) {
        g.beginPath();
        g.arc(d.x + (x + 0.5) * d.dp, d.y + (y + 0.5) * d.dp, d.dp * 0.3, 0, Math.PI * 2);
        g.fill();
      }
  }
  // the coin insert: a chrome frame round a red plastic window
  const { ins } = Lo;
  const fr = { x: ins.x - 4, y: ins.y - 4, w: ins.w + 8, h: ins.h + 8 };
  g.fillStyle = chrome(g, fr);
  rr(g, fr, 6);
  g.fill();
  g.fillStyle = "#2a080c";
  rr(g, ins, 4);
  g.fill();
  // the service lock
  const { lock, ret } = Lo;
  g.fillStyle = chrome(g, { x: lock.x - lock.r, y: lock.y - lock.r, w: lock.r * 2, h: lock.r * 2 });
  g.beginPath();
  g.arc(lock.x, lock.y, lock.r, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = "#3a3e45";
  g.beginPath();
  g.arc(lock.x, lock.y, lock.r * 0.72, 0, Math.PI * 2);
  g.fill();
  g.fillStyle = "#0a0b0d";
  g.beginPath();
  g.arc(lock.x, lock.y - lock.r * 0.12, lock.r * 0.18, 0, Math.PI * 2);
  g.fill();
  g.fillRect(lock.x - lock.r * 0.08, lock.y - lock.r * 0.12, lock.r * 0.16, lock.r * 0.42);
  // the coin-return housing
  const rh = { x: ret.x - ret.s / 2 - 3, y: ret.y - ret.s / 2 - 3, w: ret.s + 6, h: ret.s + 6 };
  g.fillStyle = chrome(g, rh);
  rr(g, rh, 5);
  g.fill();
  // engraved labels
  const fs = Math.max(7, Math.round(D * 0.03));
  g.font = `600 ${fs}px "Martian Mono", "Cascadia Mono", monospace`;
  g.textAlign = "center";
  g.fillStyle = "rgba(255,255,255,0.3)";
  g.fillText("SERVICE", lock.x, lock.y + lock.r + fs * 1.6);
  g.fillText("RETURN", ret.x, ret.y + ret.s / 2 + fs * 1.6);
  g.fillText("1 COIN · 1 CREDIT", cx, Lo.d2.y + Lo.d2.h + fs * 1.9);
  // bolt guides (left half) and keepers (right half)
  for (const y of Lo.bolts) {
    const gr = { x: cx - Lo.bl * 2.15, y: y - Lo.bh / 2 - 4, w: Lo.bl * 1.1, h: Lo.bh + 8 };
    const kx = cx + Math.max(Lo.bl * 0.35, Lo.td * 0.6 + 3); // clear of the teeth
    const kp = { x: kx, y: y - Lo.bh / 2 - 4, w: cx + Lo.bl * 1.2 - kx, h: Lo.bh + 8 };
    for (const r of [gr, kp]) {
      g.fillStyle = "#16181c";
      rr(g, r, 3);
      g.fill();
      g.strokeStyle = "rgba(255,255,255,0.12)";
      g.lineWidth = 1;
      g.stroke();
      rivet(g, r.x + 5, y, 2);
      rivet(g, r.x + r.w - 5, y, 2);
    }
  }
  const gearC = Lo.gears.map((ge) => gearSprite(ge.r, ge.teeth));
  return { face, gearC };
}

function glowSprite(color: string, size: number) {
  const c = canvas(size, size);
  const g = c.getContext("2d")!;
  const r = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  r.addColorStop(0, color);
  r.addColorStop(0.3, color + "88");
  r.addColorStop(1, color + "00");
  g.fillStyle = r;
  g.fillRect(0, 0, size, size);
  return c;
}

export class CoinGate {
  private w = 0;
  private h = 0;
  private dpr = 1;
  private Lo: Layout | null = null;
  private S: Static | null = null;
  private out = canvas(1, 1);
  private clipL: Path2D | null = null;
  private clipR: Path2D | null = null;
  private seamLine: Path2D | null = null;
  private logo = new NeonLogo();
  private bulbGlow = glowSprite("#ffc46b", 32);
  private ledGlow = [glowSprite(NEON[1], 32), glowSprite(NEON[2], 32)];
  private reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  open = 0; // 0 = sealed, 1 = fully apart
  private dir: 0 | 1 = 0;
  private t = 1; // progress of the current open/close, 0..1
  private t0 = performance.now();
  private armed = false;
  private fresh = true; // the first coin of a page load waits for the sign to build
  private seq = -1; // the coin's clock (see HIT…READY)
  private bolt = 0; // 0 = bolts home, 1 = retracted
  private shake = 0;
  private flare = 0;
  private travel = 0; // px each half has moved
  private lastTravel = 0;
  private hitFlash = 0;
  private logoT = 0;

  constructor(readonly left: HTMLCanvasElement, startOpen = false) {
    if (startOpen) {
      this.open = 1;
      this.dir = 1;
      this.bolt = 1;
      this.fresh = false;
    }
  }

  resize() {
    this.dpr = Math.min(1.5, window.devicePixelRatio || 1);
    this.w = window.innerWidth;
    this.h = window.innerHeight;
    const c = this.left;
    c.width = Math.round(this.w * this.dpr);
    c.height = Math.round(this.h * this.dpr);
    c.style.width = `${this.w}px`;
    c.style.height = `${this.h}px`;
    const Lo = layout(this.w, this.h, this.logo.cols);
    this.Lo = Lo;
    this.S = paintStatic(this.w, this.h, this.dpr, Lo);
    this.out = canvas(this.w * this.dpr, this.h * this.dpr);
    const line = new Path2D();
    Lo.seam.forEach(([x, y], i) => (i ? line.lineTo(x, y) : line.moveTo(x, y)));
    this.seamLine = line;
    const half = (edge: number) => {
      const p = new Path2D();
      p.moveTo(edge, -20);
      for (const [x, y] of Lo.seam) p.lineTo(x, y);
      p.lineTo(edge, this.h + 20);
      p.closePath();
      return p;
    };
    this.clipL = half(-20);
    this.clipR = half(this.w + 20);
  }

  /** The engine is reachable: the next coin may drop (Boot calls this as the intro phase begins). */
  arm() {
    if (this.armed) return;
    this.armed = true;
    this.seq = this.fresh ? -1.1 : -0.35;
    this.fresh = false;
  }

  slide(to: 0 | 1) {
    if (this.dir === to && this.t < 1) return;
    this.dir = to;
    this.t = 0;
    if (to === 1) this.arm();
    else {
      this.armed = false;
      this.seq = -1;
      this.t0 = performance.now() + 1000; // the sign rebuilds once the gate is shut
    }
  }

  get idle() {
    return this.t >= 1;
  }

  private advance(dt: number) {
    const prev = this.seq;
    const sealed = this.open === 0 && (this.dir === 1 || this.t >= 1);
    if (this.armed && sealed && this.seq < READY) {
      this.seq += dt * (this.dir === 1 ? 2 : 1); // the studio is waiting: hurry the coin a little
      if (this.reduced && this.seq >= 0) this.seq = READY;
    }
    const cross = (a: number) => prev < a && this.seq >= a;
    if (cross(this.reduced ? 0 : HIT)) {
      sfx("coin-insert");
      this.hitFlash = 1;
      if (!this.reduced) this.shake = Math.max(this.shake, 1.5);
    }
    if (!this.reduced && cross(IN)) sfx("coin-drop");
    if (!this.reduced && cross(ROLL)) sfx("coin-roll", { volume: 0.8 });
    if (cross(CREDIT) || (this.reduced && cross(0))) this.flare = Math.max(this.flare, 0.5);

    if (this.t < 1 && (this.dir === 0 || this.seq >= READY)) {
      const before = this.t;
      this.t = Math.min(1, this.t + dt / (this.reduced ? 0.6 : this.dir ? OPEN_S : CLOSE_S));
      const k = this.t;
      const crossed = (a: number) => before < a && k >= a;
      if (this.reduced) {
        this.open = this.dir ? k : 1 - k;
        this.bolt = this.dir ? 1 : 1 - k;
        if (crossed(this.dir ? 0 : 0.5)) sfx(this.dir ? "gate-open" : "gate-close");
      } else if (this.dir === 1) {
        // 0–.16 the bolts retract (clunk), .16–.3 the gate strains, .3–1 the halves grind apart, accelerating
        if (before === 0) sfx("gate-unlock");
        this.bolt = easeInOut(clamp01(k / 0.16));
        if (crossed(0.16)) {
          this.shake = Math.max(this.shake, 5);
          this.flare = Math.max(this.flare, 0.4);
        }
        if (crossed(0.3)) {
          sfx("gate-open");
          this.shake = Math.max(this.shake, 3.5);
        }
        const m = clamp01((k - 0.3) / 0.7);
        this.open = k < 0.3 ? 0 : Math.min(1, 0.012 * clamp01(m / 0.1) + 0.988 * (Math.max(0, m - 0.1) / 0.9) ** 2.3);
      } else {
        // the halves slam in, rebound a hair, and the bolts shoot home
        this.bolt = k < 0.85 ? 1 : 1 - easeOut((k - 0.85) / 0.15);
        if (k < 0.7) this.open = 1 - (k / 0.7) ** 2.2;
        else if (k < 0.85) this.open = 0.008 * Math.sin(((k - 0.7) / 0.15) * Math.PI);
        else this.open = 0;
        if (crossed(0.7)) {
          sfx("gate-close");
          this.shake = Math.max(this.shake, 9);
          this.flare = Math.max(this.flare, 0.35);
        }
        if (crossed(0.85)) this.shake = Math.max(this.shake, 3);
      }
    }
    this.flare = Math.max(0, this.flare - dt * 1.5);
    this.shake = Math.max(0, this.shake - dt * 22);
    this.hitFlash = Math.max(0, this.hitFlash - dt * 3);
  }

  private bulbs(o: CanvasRenderingContext2D, pts: [number, number][], now: number, offset: number) {
    const n = pts.length;
    const Lo = this.Lo!;
    const credited = this.seq >= CREDIT;
    const opening = this.dir === 1 && this.t > 0 && this.t < 0.3;
    o.globalCompositeOperation = "lighter";
    for (let i = 0; i < n; i++) {
      const j = (i + offset) % n;
      let v: number;
      if (opening) v = Math.floor(now * 9) % 2 ? 1 : 0.3;
      else if (this.seq >= ROLL && this.seq < CREDIT) {
        const head = ((this.seq - ROLL) / (CREDIT - ROLL)) * n * 1.5;
        const d = (head - j + n * 2) % n;
        v = Math.max(0.12, 1 - d / 7);
      } else if (credited) v = (j + Math.floor(now * 14)) % 3 === 0 ? 1 : 0.22;
      else v = (j + Math.floor(now * 5)) % 4 === 0 ? (this.armed ? 0.85 : 0.5) : 0.08;
      if (v < 0.05) continue;
      const [x, y] = pts[i];
      o.globalAlpha = v * 0.45;
      const gs = Lo.br * 7;
      o.drawImage(this.bulbGlow, x - gs / 2, y - gs / 2, gs, gs);
      o.globalAlpha = Math.min(1, v);
      o.fillStyle = "#ffd896";
      o.beginPath();
      o.arc(x, y, Lo.br, 0, Math.PI * 2);
      o.fill();
    }
    o.globalCompositeOperation = "source-over";
    o.globalAlpha = 1;
  }

  private display(o: CanvasRenderingContext2D, d: Disp, text: string, color: string, glow: HTMLCanvasElement, level: number) {
    if (!text || level <= 0) return;
    const { cols, dots } = textDots(text);
    const x0 = Math.floor((d.cols - cols) / 2);
    const r = d.dp * 0.36;
    o.globalCompositeOperation = "lighter";
    for (const [x, y] of dots) {
      const px = d.x + (x0 + x + 0.5) * d.dp;
      const py = d.y + (y + 1.5) * d.dp;
      o.globalAlpha = Math.min(0.4, level * 0.35);
      const gs = d.dp * 2.4;
      o.drawImage(glow, px - gs / 2, py - gs / 2, gs, gs);
      o.globalAlpha = Math.min(1, level);
      o.fillStyle = color;
      o.beginPath();
      o.arc(px, py, r, 0, Math.PI * 2);
      o.fill();
    }
    o.globalCompositeOperation = "source-over";
    o.globalAlpha = 1;
  }

  /** A silver coin, spinning about its vertical axis: `angle` π/2 is edge-on. */
  private coin(o: CanvasRenderingContext2D, x: number, y: number, R: number, angle: number, alpha: number) {
    drawSilverCoin(o, x, y, R, angle, alpha);
  }

  /** Draw the whole gate (static + live parts) into the offscreen face. */
  private paintFace(now: number) {
    const { w, h, dpr } = this;
    const Lo = this.Lo!;
    const S = this.S!;
    const o = this.out.getContext("2d")!;
    o.setTransform(dpr, 0, 0, dpr, 0, 0);
    o.globalCompositeOperation = "source-over";
    o.globalAlpha = 1;
    o.drawImage(S.face, 0, 0, w, h);
    const { cx, mq, ins, slot, ret } = Lo;
    const credited = this.seq >= CREDIT;

    // ---- the marquee sign: a faint warm backlight on the glass, then the neon logo
    const back = o.createRadialGradient(cx, mq.y + mq.h / 2, 0, cx, mq.y + mq.h / 2, mq.w * 0.55);
    back.addColorStop(0, "rgba(255,116,25,0.07)");
    back.addColorStop(1, "rgba(255,116,25,0)");
    o.fillStyle = back;
    o.fillRect(mq.x, mq.y, mq.w, mq.h);
    o.save();
    o.beginPath();
    o.roundRect(mq.x, mq.y, mq.w, mq.h, 6);
    o.clip();
    const lt = (now * 1000 - this.t0) / 1000;
    if (this.logoT < BOOT_LOGO.build + 0.15 && lt >= BOOT_LOGO.build + 0.15) sfx("logo-buzz");
    this.logoT = lt;
    this.logo.draw(o, lt, Lo.lox, Lo.loy, Lo.p, BOOT_LOGO, { grid: true, flare: this.flare * 0.6 });
    o.restore();
    // glass reflection
    const refl = o.createLinearGradient(0, mq.y, 0, mq.y + mq.h);
    refl.addColorStop(0, "rgba(255,255,255,0.06)");
    refl.addColorStop(0.45, "rgba(255,255,255,0)");
    o.fillStyle = refl;
    o.fillRect(mq.x, mq.y, mq.w, mq.h * 0.45);

    // ---- bulbs
    this.bulbs(o, Lo.mBulbs, now, 0);
    this.bulbs(o, Lo.bulbs, now, 0);

    // ---- the displays
    const opening = this.dir === 1 && this.t > 0;
    let msg = "";
    let lvl = 1;
    if (opening) msg = "WELCOME";
    else if (credited) {
      msg = "GET READY";
      lvl = 0.85 + 0.15 * Math.sin(now * 6);
    } else if (now % 1.1 < 0.68) {
      msg = "INSERT COIN";
      lvl = this.armed ? 1 : 0.7;
    }
    this.display(o, Lo.d1, msg, NEON[1], this.ledGlow[0], lvl);
    const since = this.seq - CREDIT;
    const blink = credited && since < 0.6 ? (Math.floor(since * 10) % 2 ? 0.35 : 1.15) : 1;
    this.display(o, Lo.d2, `CREDIT ${credited ? 1 : 0}`, NEON[2], this.ledGlow[1], (credited ? 1 : 0.75) * blink);

    // ---- the coin insert: backlit red plastic; a band of light runs down it as the coin drops through the mech
    let lit = 0.5 + 0.12 * Math.sin(now * 3);
    if (credited) lit = 0.8;
    lit += this.hitFlash * 0.35;
    const ig = o.createLinearGradient(0, ins.y, 0, ins.y + ins.h);
    ig.addColorStop(0, "#ff6a3a");
    ig.addColorStop(1, "#c81e3c");
    o.globalAlpha = Math.min(1, lit);
    o.fillStyle = ig;
    o.beginPath();
    o.roundRect(ins.x, ins.y, ins.w, ins.h, 4);
    o.fill();
    if (this.seq >= IN && this.seq < CREDIT) {
      const q = (this.seq - IN) / (CREDIT - IN);
      const by = ins.y + q * ins.h * 1.3 - ins.h * 0.15;
      const bg = o.createLinearGradient(0, by - ins.h * 0.18, 0, by + ins.h * 0.18);
      bg.addColorStop(0, "rgba(255,230,190,0)");
      bg.addColorStop(0.5, "rgba(255,230,190,0.75)");
      bg.addColorStop(1, "rgba(255,230,190,0)");
      o.save();
      o.beginPath();
      o.roundRect(ins.x, ins.y, ins.w, ins.h, 4);
      o.clip();
      o.globalAlpha = 1;
      o.fillStyle = bg;
      o.fillRect(ins.x, by - ins.h * 0.18, ins.w, ins.h * 0.36);
      o.restore();
    }
    o.globalAlpha = 1;
    // a soft sheen on the plastic and the arrow pointing into the slot
    o.fillStyle = "rgba(255,255,255,0.1)";
    o.fillRect(ins.x + 2, ins.y + 2, ins.w * 0.3, ins.h - 4);
    o.fillStyle = `rgba(255,240,220,${0.35 + 0.3 * lit})`;
    const ay = ins.y + ins.h * 0.09;
    const aw = ins.w * 0.18;
    o.beginPath();
    o.moveTo(cx - aw, ay - aw * 0.5);
    o.lineTo(cx + aw, ay - aw * 0.5);
    o.lineTo(cx, ay + aw * 0.45);
    o.closePath();
    o.fill();
    // the slot
    o.fillStyle = "#070708";
    o.beginPath();
    o.roundRect(slot.x, slot.y, slot.w, slot.h, slot.w / 2);
    o.fill();
    o.strokeStyle = `rgba(255,236,214,${0.18 + this.hitFlash * 0.7})`;
    o.lineWidth = 1;
    o.stroke();

    // ---- the coin-return button: red, lit from inside, it flashes when the coin knocks
    const bs = ret.s;
    const rg = o.createLinearGradient(0, ret.y - bs / 2, 0, ret.y + bs / 2);
    rg.addColorStop(0, "#ff5a4a");
    rg.addColorStop(1, "#8e1426");
    o.globalAlpha = 0.55 + 0.25 * (credited ? 1 : 0) + this.hitFlash * 0.3;
    o.fillStyle = rg;
    o.beginPath();
    o.roundRect(ret.x - bs / 2, ret.y - bs / 2, bs, bs, 4);
    o.fill();
    o.globalAlpha = 1;
    o.fillStyle = "rgba(255,255,255,0.22)";
    o.fillRect(ret.x - bs / 2 + 3, ret.y - bs / 2 + 2, bs - 6, bs * 0.18);

    // ---- gears (each turns with its half of the gate)
    Lo.gears.forEach((ge, i) => {
      const spr = S.gearC[i];
      const rot = ((this.travel + this.bolt * ge.r * ge.ratio * 0.5) / ge.r) * ge.dir;
      const size = spr.width / 2;
      o.save();
      o.translate(ge.x, ge.y);
      o.rotate(rot + (i % 2 ? Math.PI / ge.teeth : 0));
      o.drawImage(spr, -size / 2, -size / 2, size, size);
      o.restore();
    });

    // ---- the coin's flight and insertion (only while the gate is shut)
    if (!this.reduced && this.armed && this.seq > 0 && this.seq < IN) {
      const R = Lo.D * 0.085;
      const end: [number, number] = [cx, slot.y + slot.h / 2];
      const p0: [number, number] = [w + R * 3, Math.min(h * 0.92, Lo.door.y + Lo.door.h * 1.05)];
      const p1: [number, number] = [cx + Math.min(w * 0.35, Lo.D * 1.1), Lo.door.y - Lo.D * 0.25];
      const at = (u: number) => {
        const e = 1 - (1 - u) ** 2;
        const a = 1 - e;
        return {
          x: a * a * p0[0] + 2 * a * e * p1[0] + e * e * end[0],
          y: a * a * p0[1] + 2 * a * e * p1[1] + e * e * end[1],
          s: 1.55 - 0.55 * e,
          ang: Math.PI / 2 + (1 - e) * 5 * Math.PI,
        };
      };
      if (this.seq < HIT) {
        const u = this.seq / HIT;
        for (const [du, al] of [[0.08, 0.1], [0.04, 0.2]] as const) {
          if (u - du <= 0) continue;
          const g = at(u - du);
          this.coin(o, g.x, g.y, R * g.s, g.ang, al);
        }
        const c = at(u);
        // a soft shadow on the steel
        o.fillStyle = "rgba(0,0,0,0.25)";
        o.beginPath();
        o.ellipse(c.x + R * 0.5 * c.s, c.y + R * 0.6 * c.s, R * c.s * 0.8, R * c.s * 0.9, 0, 0, Math.PI * 2);
        o.fill();
        this.coin(o, c.x, c.y, R * c.s, c.ang, 1);
      } else {
        // knocks the rim, bounces, then slides in edge-first
        const q = (this.seq - HIT) / (IN - HIT);
        const bounce = q < 0.45 ? -Math.sin((q / 0.45) * Math.PI) * R * 0.14 : 0;
        const gone = clamp01((q - 0.45) / 0.55);
        o.save();
        o.beginPath();
        o.rect(slot.x - R, slot.y - R * 0.6, slot.w + R * 2, slot.h + R * 1.2);
        o.clip();
        this.coin(o, end[0], end[1] + bounce, R * (1 - gone * 0.12), Math.PI / 2 + 0.05, 1 - gone);
        o.restore();
      }
    }
  }

  /** Advance and draw; returns the pose (the door CSS is unused for this theme — it draws its own halves). */
  frame(dt: number): DoorPose {
    if (!this.Lo) this.resize();
    this.advance(dt);
    const { w, h, dpr } = this;
    const Lo = this.Lo!;
    const now = performance.now() / 1000;
    this.paintFace(now);
    this.lastTravel = this.travel;
    this.travel = this.reduced ? 0 : this.open * (w / 2 + Lo.td + 40);
    const v = this.travel - this.lastTravel;
    const c = this.left.getContext("2d")!;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.globalAlpha = 1;
    c.clearRect(0, 0, this.left.width, this.left.height);
    const sh = this.reduced ? 0 : this.shake;
    const sx = (Math.random() * 2 - 1) * sh;
    const sy = (Math.random() * 2 - 1) * sh * 0.6;
    c.setTransform(dpr, 0, 0, dpr, sx * dpr, sy * dpr);
    if (this.reduced) c.globalAlpha = 1 - this.open;
    if (this.travel < 0.25) {
      c.drawImage(this.out, 0, 0, w, h);
      this.bolts(c, 0);
    } else {
      for (const side of [-1, 1] as const) {
        const dx = side * this.travel;
        const clip = side < 0 ? this.clipL! : this.clipR!;
        // the half's shadow falling on the studio along its toothed edge
        c.save();
        c.translate(dx, 0);
        c.strokeStyle = "rgba(0,0,0,0.35)";
        c.lineWidth = 22;
        c.stroke(this.seamLine!);
        c.restore();
        // motion blur: faint ghosts trailing the edge while the gate moves fast
        if (Math.abs(v) > 3) {
          for (const [k, a] of [[1.6, 0.16], [0.8, 0.26]] as const) {
            c.save();
            c.globalAlpha = a;
            c.translate(dx - side * v * k, 0);
            c.clip(clip);
            c.drawImage(this.out, 0, 0, w, h);
            c.restore();
          }
        }
        c.save();
        c.translate(dx, 0);
        c.clip(clip);
        c.drawImage(this.out, 0, 0, w, h);
        c.restore();
        // the steel edge catches the light
        c.save();
        c.translate(dx + side * 0.5, 0);
        c.strokeStyle = "rgba(225,230,238,0.35)";
        c.lineWidth = 1.5;
        c.stroke(this.seamLine!);
        c.restore();
        if (side < 0) this.bolts(c, dx);
      }
    }
    c.globalAlpha = 1;
    return { open: this.open, crack: 0, shine: 0 };
  }

  /** Lock bolts: chrome bars across the seam, riding on the left half. */
  private bolts(c: CanvasRenderingContext2D, dx: number) {
    const Lo = this.Lo!;
    const { cx, bl, bh, td } = Lo;
    for (const y of Lo.bolts) {
      const x0 = cx - bl * 1.95 + dx;
      const x1 = cx + bl * 1.05 - this.bolt * (bl * 1.05 + td * 0.6 + 6) + dx;
      const r = { x: x0, y: y - bh / 2, w: Math.max(4, x1 - x0), h: bh };
      c.fillStyle = "rgba(0,0,0,0.4)";
      c.beginPath();
      c.roundRect(r.x + 1, r.y + 2, r.w, r.h, bh / 2);
      c.fill();
      c.fillStyle = chrome(c, r);
      c.beginPath();
      c.roundRect(r.x, r.y, r.w, r.h, bh / 2);
      c.fill();
      c.fillStyle = "rgba(0,0,0,0.35)";
      c.fillRect(x0 + bl * 0.55, r.y + 1, 2, r.h - 2);
    }
  }
}
