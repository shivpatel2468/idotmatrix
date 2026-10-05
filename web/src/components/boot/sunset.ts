import { type LogoTimeline, NEON, NeonLogo } from "../../lib/logo";
import { sfx } from "../../lib/sound";

/** The intro / outro: a warm retro-synthwave sunset with a lo-fi finish. A plum-to-ember sky with twinkling
 *  stars, a striped retro sun breathing on the horizon, soft mountain silhouettes, a neon perspective grid gliding
 *  towards you, film grain, faint scanlines and a vignette. The DeskDot logo is a neon sign in the sky.
 *
 *  It is one sealed scene (no seam while shut). Opening: the sun flares, a streak of light runs along the horizon,
 *  a crack of light splits the middle, and the two halves glide apart 50/50. Closing plays it back and the crack
 *  heals once the halves meet. The scene is drawn into one offscreen canvas and blitted half into each door canvas;
 *  the doors move with CSS transforms (GPU). Static layers are pre-rendered per size, so a frame is cheap. */

export const BOOT_LOGO: LogoTimeline = { build: 1.3, hold: Infinity, off: 1 };
const HORIZON = 0.64; // horizon height (share of the screen)

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

type Layers = { sky: HTMLCanvasElement; grain: HTMLCanvasElement; finish: HTMLCanvasElement; stars: [number, number, number, number][] };

/** Sky, mountains (static), a grain tile, and the scanline + vignette finish. */
function paintLayers(w: number, h: number, dpr: number): Layers {
  const rand = rng(23);
  const hy = h * HORIZON;
  const sky = canvas(w * dpr, h * dpr);
  const g = sky.getContext("2d")!;
  g.scale(dpr, dpr);
  const sg = g.createLinearGradient(0, 0, 0, hy);
  sg.addColorStop(0, "#0b0614");
  sg.addColorStop(0.45, "#2a0c2c");
  sg.addColorStop(0.78, "#6a1838");
  sg.addColorStop(0.94, "#c2353e");
  sg.addColorStop(1, "#ff7a3c");
  g.fillStyle = sg;
  g.fillRect(0, 0, w, hy + 1);
  // the ground below the horizon: deep plum, lit warm at the horizon
  const gg = g.createLinearGradient(0, hy, 0, h);
  gg.addColorStop(0, "#3a0d22");
  gg.addColorStop(0.25, "#16081a");
  gg.addColorStop(1, "#07040b");
  g.fillStyle = gg;
  g.fillRect(0, hy, w, h - hy);
  // two ranges of soft mountains, mirrored so the sealed scene is symmetric
  const range = (base: number, amp: number, color: string, seed: number) => {
    const r = rng(seed);
    const pts: number[] = [];
    const n = 14;
    for (let i = 0; i <= n; i++) pts.push(base - (0.35 + r() * 0.65) * amp * (1 - Math.abs(i / n - 0.5) * 0.9));
    g.fillStyle = color;
    g.beginPath();
    g.moveTo(0, hy);
    for (let i = 0; i <= n; i++) {
      const x = (i / n) * (w / 2);
      g.lineTo(x, pts[i]);
    }
    for (let i = n; i >= 0; i--) g.lineTo(w - (i / n) * (w / 2), pts[i]);
    g.lineTo(w, hy);
    g.closePath();
    g.fill();
  };
  range(hy, h * 0.13, "rgba(70,18,52,0.85)", 5);
  range(hy, h * 0.07, "rgba(34,9,32,0.95)", 9);
  // a warm haze along the horizon
  const haze = g.createLinearGradient(0, hy - h * 0.06, 0, hy + h * 0.04);
  haze.addColorStop(0, "rgba(255,122,60,0)");
  haze.addColorStop(0.6, "rgba(255,122,60,0.35)");
  haze.addColorStop(1, "rgba(255,122,60,0)");
  g.fillStyle = haze;
  g.fillRect(0, hy - h * 0.06, w, h * 0.1);
  // stars (twinkled per frame), mirrored
  const stars: [number, number, number, number][] = [];
  for (let i = 0; i < Math.round((w * h) / 9000); i++) {
    const x = rand() * (w / 2);
    const y = rand() * hy * 0.78;
    const s = 0.4 + rand() * 1.2;
    const ph = rand() * Math.PI * 2;
    stars.push([x, y, s, ph], [w - x, y, s, ph + 1.3]);
  }
  // film grain tile
  const grain = canvas(160, 160);
  const gc = grain.getContext("2d")!;
  const img = gc.createImageData(160, 160);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = rand() * 255;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
    img.data[i + 3] = 18;
  }
  gc.putImageData(img, 0, 0);
  // scanlines + vignette
  const finish = canvas(w * dpr, h * dpr);
  const f = finish.getContext("2d")!;
  f.scale(dpr, dpr);
  f.fillStyle = "rgba(0,0,0,0.18)";
  for (let y = 0; y < h; y += 3) f.fillRect(0, y, w, 1);
  const v = f.createRadialGradient(w / 2, h * 0.45, Math.min(w, h) * 0.25, w / 2, h * 0.45, Math.hypot(w, h) * 0.62);
  v.addColorStop(0, "rgba(0,0,0,0)");
  v.addColorStop(1, "rgba(0,0,0,0.72)");
  f.fillStyle = v;
  f.fillRect(0, 0, w, h);
  return { sky, grain, finish, stars };
}

const easeInOut = (k: number) => (k < 0.5 ? 4 * k ** 3 : 1 - (-2 * k + 2) ** 3 / 2);
const easeOut = (k: number) => 1 - (1 - k) ** 4;

export type DoorPose = { open: number; crack: number; shine: number };

export class SunsetDoors {
  private w = 0;
  private h = 0;
  private dpr = 1;
  private layers: Layers | null = null;
  private out = canvas(1, 1);
  private logo = new NeonLogo();
  open = 0; // 0 = sealed, 1 = fully apart
  private crack = 0; // the light splitting the seal, 0..1
  private streak = 0; // the horizon light streak when opening, 0..1
  private dir: 0 | 1 = 0;
  private t = 1; // progress of the current open/close, 0..1
  private t0 = performance.now();
  private flare = 0;
  private grainPattern: CanvasPattern | null = null;
  private sunC: HTMLCanvasElement | null = null;
  private logoT = 0; // the logo's clock last frame (to buzz once as the tubes strike)

  constructor(readonly left: HTMLCanvasElement, readonly right: HTMLCanvasElement, startOpen = false) {
    if (startOpen) {
      this.open = 1;
      this.crack = 1;
      this.dir = 1;
    }
  }

  resize() {
    this.dpr = Math.min(1.5, window.devicePixelRatio || 1);
    this.w = window.innerWidth;
    this.h = window.innerHeight;
    const half = Math.ceil(this.w / 2);
    for (const c of [this.left, this.right]) {
      c.width = Math.round(half * this.dpr);
      c.height = Math.round(this.h * this.dpr);
      c.style.width = `${half}px`;
      c.style.height = `${this.h}px`;
    }
    this.layers = paintLayers(this.w, this.h, this.dpr);
    this.out = canvas(this.w * this.dpr, this.h * this.dpr);
    this.grainPattern = null;
  }

  slide(to: 0 | 1) {
    if (this.dir === to && this.t < 1) return;
    this.dir = to;
    this.t = 0;
    if (to === 0) this.t0 = performance.now() + 900; // the logo builds again once the doors are sealed
  }

  get idle() {
    return this.t >= 1;
  }

  /** The retro sun: a gradient disc cut by horizontal gaps that widen towards the horizon and drift down. */
  private sun(o: CanvasRenderingContext2D, now: number, glow: number) {
    const { w, h } = this;
    const hy = h * HORIZON;
    const r = Math.min(w * 0.15, h * 0.23) * (1 + Math.sin(now * 0.7) * 0.006);
    const cx = w / 2;
    const cy = hy - r * 0.18;
    // halo
    o.globalCompositeOperation = "lighter";
    // the flare only warms the halo a little: a big additive bloom here washes out the sky and the sign above it
    const halo = o.createRadialGradient(cx, cy, r * 0.6, cx, cy, r * (2.4 + glow * 0.3));
    halo.addColorStop(0, `rgba(255,140,46,${0.35 + glow * 0.12})`);
    halo.addColorStop(0.5, `rgba(255,79,123,${0.12 + glow * 0.06})`);
    halo.addColorStop(1, "rgba(0,0,0,0)");
    o.fillStyle = halo;
    o.fillRect(cx - r * 3.5, cy - r * 3.5, r * 7, r * 7);
    o.globalCompositeOperation = "source-over";
    // the disc goes on its own layer so the gaps show the sky, not whatever is behind the doors
    const size = Math.ceil(r * 2 + 4);
    if (!this.sunC || this.sunC.width !== size) this.sunC = canvas(size, size);
    const s = this.sunC.getContext("2d")!;
    s.setTransform(1, 0, 0, 1, 0, 0);
    s.globalCompositeOperation = "source-over";
    s.clearRect(0, 0, size, size);
    const sx = cx - size / 2;
    const sy = cy - size / 2;
    s.translate(-sx, -sy);
    s.beginPath();
    s.arc(cx, cy, r, 0, Math.PI * 2);
    const sg = s.createLinearGradient(0, cy - r, 0, hy);
    sg.addColorStop(0, "#ffe9a0");
    sg.addColorStop(0.35, NEON[2]);
    sg.addColorStop(0.7, NEON[1]);
    sg.addColorStop(1, NEON[0]);
    s.fillStyle = sg;
    s.fill();
    s.globalCompositeOperation = "destination-out";
    const drift = (now * 0.08) % 1;
    for (let i = 0; i < 8; i++) {
      const k = (i + drift) / 8;
      const y = cy - r * 0.42 + k * r * 0.62;
      const hgt = 1.5 + k ** 1.4 * r * 0.075;
      s.fillRect(cx - r, y, r * 2, hgt);
    }
    s.fillRect(cx - r - 2, hy, r * 2 + 4, r * 2); // below the horizon
    o.drawImage(this.sunC, sx, sy, size, size);
  }

  /** The neon floor: lines converge to the vanishing point; cross lines glide towards the viewer. */
  private grid(o: CanvasRenderingContext2D, now: number, glow: number) {
    const { w, h } = this;
    const hy = h * HORIZON;
    const cx = w / 2;
    o.save();
    o.beginPath();
    o.rect(0, hy, w, h - hy);
    o.clip();
    o.globalCompositeOperation = "lighter";
    o.lineWidth = 1.2;
    const n = 22;
    for (let i = -n; i <= n; i++) {
      const xb = cx + i * (w / n) * 1.6;
      const a = 0.22 + (1 - Math.abs(i) / n) * 0.25 + glow * 0.3;
      o.strokeStyle = `rgba(255,79,123,${a})`;
      o.beginPath();
      o.moveTo(cx + i * 6, hy);
      o.lineTo(xb, h);
      o.stroke();
    }
    const speed = 0.35;
    for (let k = 0; k < 14; k++) {
      const z = (k + ((now * speed) % 1)) / 14; // 0 at the horizon → 1 at the viewer
      const y = hy + (h - hy) * z * z;
      const a = Math.min(1, z * 1.6) * (0.55 + glow * 0.25);
      o.strokeStyle = `rgba(255,140,46,${a})`;
      o.lineWidth = 0.8 + z * 1.6;
      o.beginPath();
      o.moveTo(0, y);
      o.lineTo(w, y);
      o.stroke();
    }
    // the horizon line itself
    o.strokeStyle = `rgba(255,207,77,${0.55 + glow * 0.45})`;
    o.lineWidth = 1.5;
    o.beginPath();
    o.moveTo(0, hy);
    o.lineTo(w, hy);
    o.stroke();
    o.restore();
    o.globalCompositeOperation = "source-over";
  }

  /** Advance and draw; returns the pose for the CSS transforms of the two door elements. */
  frame(dt: number): DoorPose {
    if (!this.layers) this.resize();
    const { w, h, dpr } = this;
    const L = this.layers!;
    const OPEN_S = 2.4;
    const CLOSE_S = 1.2;
    if (this.t < 1) {
      const before = this.t;
      this.t = Math.min(1, this.t + dt / (this.dir ? OPEN_S : CLOSE_S));
      const k = this.t;
      if (this.dir === 1) {
        if (before === 0) sfx("door-open");
        // 0–.3 the sun flares and the horizon streak runs out; .22–.4 the crack; .34–1 the glide
        this.flare = Math.max(this.flare, Math.sin(Math.min(1, k / 0.3) * Math.PI));
        this.streak = Math.min(1, k / 0.3);
        this.crack = Math.min(1, Math.max(0, (k - 0.22) / 0.18));
        this.open = easeInOut(Math.min(1, Math.max(0, (k - 0.34) / 0.66)));
      } else {
        this.streak = 0;
        this.open = 1 - easeOut(Math.min(1, k / 0.82));
        this.crack = k < 0.82 ? 1 : 1 - (k - 0.82) / 0.18; // sealed: the crack heals
        if (k >= 0.82 && before < 0.82) {
          this.flare = 0.6; // the soft thud of the seal
          sfx("door-close");
        }
      }
    }
    this.flare = Math.max(0, this.flare - dt * 1.2);
    const now = performance.now() / 1000;
    const o = this.out.getContext("2d")!;
    o.setTransform(dpr, 0, 0, dpr, 0, 0);
    o.globalCompositeOperation = "source-over";
    o.globalAlpha = 1;
    o.drawImage(L.sky, 0, 0, w, h);
    // twinkling stars
    o.fillStyle = "#ffe9d6";
    for (const [x, y, s, ph] of L.stars) {
      o.globalAlpha = 0.25 + 0.55 * (0.5 + 0.5 * Math.sin(now * 1.3 + ph));
      o.fillRect(x, y, s, s);
    }
    o.globalAlpha = 1;
    this.sun(o, now, this.flare);
    this.grid(o, now, this.flare);
    const hy = h * HORIZON;
    // the opening streak: light racing out along the horizon from the centre
    if (this.streak > 0 && this.streak < 1) {
      o.globalCompositeOperation = "lighter";
      const len = easeOut(this.streak) * w * 0.6;
      const sg = o.createLinearGradient(w / 2 - len, 0, w / 2 + len, 0);
      sg.addColorStop(0, "rgba(255,255,255,0)");
      sg.addColorStop(0.5, `rgba(255,236,210,${0.9 * (1 - this.streak * 0.6)})`);
      sg.addColorStop(1, "rgba(255,255,255,0)");
      o.fillStyle = sg;
      o.fillRect(w / 2 - len, hy - 2, len * 2, 4);
      o.globalCompositeOperation = "source-over";
    }
    // the logo: a neon sign in the sky; a gap between LED columns falls exactly on the split
    // phones: the sign fills ~86 % of the width (never wider than the screen)
    const p = w < 640 ? Math.min(28, (w * 0.86) / this.logo.cols) : Math.max(9, Math.min(28, (w * 0.56) / this.logo.cols));
    const cx = w / 2;
    const ly = h * 0.24;
    const ox = Math.round(cx - Math.round(this.logo.cols / 2) * p);
    const oy = ly - (this.logo.rows * p) / 2;
    const plate = o.createRadialGradient(cx, ly, 0, cx, ly, this.logo.cols * p * 0.62);
    plate.addColorStop(0, "rgba(8,3,12,0.55)");
    plate.addColorStop(1, "rgba(8,3,12,0)");
    o.fillStyle = plate;
    o.fillRect(0, 0, w, h);
    const lt = (performance.now() - this.t0) / 1000;
    if (this.logoT < BOOT_LOGO.build + 0.15 && lt >= BOOT_LOGO.build + 0.15) sfx("logo-buzz");
    this.logoT = lt;
    this.logo.draw(o, lt, ox, oy, p, BOOT_LOGO, { grid: true, flare: this.flare * 0.6 });
    // the crack of light down the middle (only while splitting or healing)
    if (this.crack > 0.01) {
      o.globalCompositeOperation = "lighter";
      const len = this.crack * h * 0.7;
      const my = h * 0.48;
      const cg = o.createLinearGradient(0, my - len, 0, my + len);
      cg.addColorStop(0, "rgba(255,255,255,0)");
      cg.addColorStop(0.5, `rgba(255,236,214,${0.95 * Math.min(1, this.crack * 1.4)})`);
      cg.addColorStop(1, "rgba(255,255,255,0)");
      o.fillStyle = cg;
      o.fillRect(cx - 1.2, my - len, 2.4, len * 2);
      const halo = o.createRadialGradient(cx, my, 0, cx, my, 190 * this.crack);
      halo.addColorStop(0, `rgba(255,170,90,${0.3 * this.crack})`);
      halo.addColorStop(1, "rgba(0,0,0,0)");
      o.fillStyle = halo;
      o.fillRect(cx - 190, my - 190, 380, 380);
      o.globalCompositeOperation = "source-over";
    }
    // lo-fi finish: moving grain, scanlines, vignette
    this.grainPattern ??= o.createPattern(L.grain, "repeat");
    if (this.grainPattern) {
      const gx = Math.floor(Math.random() * 160);
      const gy = Math.floor(Math.random() * 160);
      o.save();
      o.translate(-gx, -gy);
      o.fillStyle = this.grainPattern;
      o.fillRect(gx, gy, w + 160, h + 160);
      o.restore();
    }
    o.drawImage(L.finish, 0, 0, w, h);

    // split into the two doors
    const half = Math.ceil(w / 2);
    for (const [c, sx] of [[this.left, 0], [this.right, w - half]] as const) {
      const g = c.getContext("2d")!;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, c.width, c.height);
      g.drawImage(this.out, sx * dpr, 0, half * dpr, h * dpr, 0, 0, c.width, c.height);
      if (this.open > 0.002) {
        // the inner edge: a thin warm neon rim
        const ex = sx === 0 ? c.width - 3 * dpr : 0;
        const eg = g.createLinearGradient(0, 0, 0, c.height);
        eg.addColorStop(0, NEON[0]);
        eg.addColorStop(0.5, NEON[1]);
        eg.addColorStop(1, NEON[2]);
        g.globalAlpha = 0.9;
        g.fillStyle = eg;
        g.fillRect(ex, 0, 3 * dpr, c.height);
        g.globalAlpha = 1;
      }
    }
    return { open: this.open, crack: this.crack, shine: Math.min(1, this.crack) * (1 - this.open * 0.85) };
  }
}
