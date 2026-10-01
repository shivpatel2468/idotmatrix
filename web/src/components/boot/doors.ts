import { type LogoTimeline, NEON, NeonLogo } from "../../lib/logo";

/** The intro / outro. One sealed LED-matrix face covers the screen — no seam while shut. The idotmatrix logo
 *  builds and strikes in the middle. To open: a power surge lights every LED in a ring from the logo outwards, a
 *  crack of light splits the face down the middle, and the two halves slide apart 50/50 (tilting back a little in
 *  3D), light pouring through. Closing plays it backwards and the crack heals once the halves meet.
 *
 *  The face is drawn once per frame into an offscreen canvas and blitted half into each door canvas; the doors
 *  themselves move with CSS transforms (GPU), so the motion stays smooth on modest hardware. */

export const BOOT_LOGO: LogoTimeline = { build: 1.3, hold: Infinity, off: 1 };
const PITCH = 14;

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

/** The whole sealed face: brushed metal, an LED matrix, circuit traces — and a lit twin of the dots and traces. */
function paintFace(w: number, h: number, dpr: number) {
  const base = canvas(w * dpr, h * dpr);
  const lit = canvas(w * dpr, h * dpr);
  const g = base.getContext("2d")!;
  const l = lit.getContext("2d")!;
  g.scale(dpr, dpr);
  l.scale(dpr, dpr);
  const rand = rng(11);
  const cx = w / 2;
  // metal: brighter in the middle, falling into darkness at the edges
  const grad = g.createRadialGradient(cx, h * 0.42, 0, cx, h * 0.42, Math.max(w, h) * 0.75);
  grad.addColorStop(0, "#17171f");
  grad.addColorStop(0.6, "#0d0d12");
  grad.addColorStop(1, "#060608");
  g.fillStyle = grad;
  g.fillRect(0, 0, w, h);
  for (let i = 0; i < h; i += 2) {
    g.fillStyle = `rgba(255,255,255,${0.006 + rand() * 0.012})`;
    g.fillRect(0, i, w, 1);
  }
  // the LED matrix, symmetric about the centre so the two halves mirror each other
  const cols = Math.floor((w - 60) / PITCH / 2) * 2;
  const rows = Math.floor((h - 60) / PITCH);
  const x0 = cx - (cols / 2) * PITCH;
  const y0 = (h - rows * PITCH) / 2;
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      const x = x0 + c * PITCH + PITCH / 2;
      const y = y0 + r * PITCH + PITCH / 2;
      g.fillStyle = "#14141a";
      g.beginPath();
      g.arc(x, y, 2.7, 0, Math.PI * 2);
      g.fill();
      g.fillStyle = "rgba(255,255,255,0.04)";
      g.beginPath();
      g.arc(x - 0.7, y - 0.9, 1, 0, Math.PI * 2);
      g.fill();
      l.globalAlpha = 0.3 + rand() * 0.7;
      l.fillStyle = "#fff";
      l.beginPath();
      l.arc(x, y, 2.5, 0, Math.PI * 2);
      l.fill();
    }
  l.globalAlpha = 1;
  // circuit traces running from the edges in towards the logo (mirrored left/right)
  const traces = Math.round(h / 52);
  for (let i = 0; i < traces; i++) {
    let y = 40 + rand() * (h - 80);
    let x = 20;
    const pts: [number, number][] = [[x, y]];
    const goal = cx - 120 - rand() * (w * 0.18);
    while (x < goal) {
      x = Math.min(goal, x + 40 + rand() * 110);
      pts.push([x, y]);
      if (rand() < 0.6) {
        y = Math.min(h - 30, Math.max(30, y + (rand() - 0.5) * 80));
        x += 16;
        pts.push([x, y]);
      }
    }
    for (const mirror of [false, true])
      for (const [ctx, style, wdt] of [[g, "#1d1d26", 2.2], [l, "#fff", 1.6]] as const) {
        ctx.strokeStyle = style;
        ctx.lineWidth = wdt;
        ctx.lineJoin = "round";
        ctx.beginPath();
        pts.forEach(([px, py], k) => {
          const X = mirror ? w - px : px;
          if (k) ctx.lineTo(X, py);
          else ctx.moveTo(X, py);
        });
        ctx.stroke();
        const [ex, ey] = pts[pts.length - 1];
        ctx.fillStyle = style;
        ctx.beginPath();
        ctx.arc(mirror ? w - ex : ex, ey, 4, 0, Math.PI * 2);
        ctx.fill();
      }
  }
  // the lit twin takes the logo's colours: pink on the left, amber in the middle, cyan on the right
  l.globalCompositeOperation = "source-in";
  const lg = l.createLinearGradient(0, 0, w, 0);
  lg.addColorStop(0, NEON[0]);
  lg.addColorStop(0.5, NEON[1]);
  lg.addColorStop(1, NEON[2]);
  l.fillStyle = lg;
  l.fillRect(0, 0, w, h);
  // engraved captions
  g.font = '500 10px "Martian Mono", "Cascadia Mono", monospace';
  g.fillStyle = "rgba(255,255,255,0.16)";
  g.textAlign = "left";
  g.fillText("32 × 32 RGB · BLUETOOTH LE", 30, h - 26);
  g.textAlign = "right";
  g.fillText("LIVE DESKTOP COMPANION", w - 30, h - 26);
  return { base, lit };
}

const easeInOut = (k: number) => (k < 0.5 ? 4 * k ** 3 : 1 - (-2 * k + 2) ** 3 / 2);
const easeOut = (k: number) => 1 - (1 - k) ** 4;

export type DoorPose = { open: number; crack: number; shine: number };

export class Doors {
  private w = 0;
  private h = 0;
  private dpr = 1;
  private face: { base: HTMLCanvasElement; lit: HTMLCanvasElement } | null = null;
  private out = canvas(1, 1);
  private scratchC: HTMLCanvasElement | null = null;
  private logo = new NeonLogo();
  open = 0; // 0 = sealed, 1 = fully apart
  private crack = 0; // the light splitting the seal, 0..1
  private surge = -1; // the power-surge ring, 0..1 (−1 = none)
  private dir: 0 | 1 = 0;
  private t = 1; // progress of the current open/close, 0..1
  private t0 = performance.now();
  private flare = 0;

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
    this.face = paintFace(this.w, this.h, this.dpr);
    this.out = canvas(this.w * this.dpr, this.h * this.dpr);
  }

  slide(to: 0 | 1) {
    if (this.dir === to && this.t < 1) return;
    this.dir = to;
    this.t = 0;
    if (to === 1) this.surge = 0;
    else this.t0 = performance.now() + 900; // the logo builds again once the doors are sealed
  }

  get idle() {
    return this.t >= 1;
  }

  private scratch() {
    if (!this.scratchC || this.scratchC.width !== this.out.width || this.scratchC.height !== this.out.height) {
      this.scratchC = canvas(this.out.width, this.out.height);
    }
    return this.scratchC;
  }

  /** Light only the LEDs and traces under a radial band (centre cx, cy; inner → outer radius), additively. */
  private lightRing(o: CanvasRenderingContext2D, cx: number, cy: number, r0: number, r1: number, peak: number, inner = 0) {
    const { w, h, dpr } = this;
    const sc = this.scratch().getContext("2d")!;
    sc.setTransform(1, 0, 0, 1, 0, 0);
    sc.globalCompositeOperation = "source-over";
    sc.clearRect(0, 0, this.scratch().width, this.scratch().height);
    sc.setTransform(dpr, 0, 0, dpr, 0, 0);
    sc.drawImage(this.face!.lit, 0, 0, w, h);
    sc.globalCompositeOperation = "destination-in";
    const g = sc.createRadialGradient(cx, cy, Math.max(0, r0), cx, cy, Math.max(r0 + 1, r1));
    g.addColorStop(0, `rgba(0,0,0,${inner})`);
    g.addColorStop(0.82, `rgba(0,0,0,${peak})`);
    g.addColorStop(1, "rgba(0,0,0,0)");
    sc.fillStyle = g;
    sc.fillRect(0, 0, w, h);
    o.globalCompositeOperation = "lighter";
    o.drawImage(this.scratch(), 0, 0, w, h);
    o.globalCompositeOperation = "source-over";
  }

  /** Advance and draw; returns the pose for the CSS transforms of the two door elements. */
  frame(dt: number): DoorPose {
    if (!this.face) this.resize();
    const { w, h, dpr } = this;
    const OPEN_S = 2.3;
    const CLOSE_S = 1.1;
    if (this.t < 1) {
      const before = this.t;
      this.t = Math.min(1, this.t + dt / (this.dir ? OPEN_S : CLOSE_S));
      const k = this.t;
      if (this.dir === 1) {
        // 0–.3 power surge, .2–.38 the crack, .32–1 the slide
        this.surge = Math.min(1, k / 0.3);
        this.flare = Math.max(this.flare, Math.sin(Math.min(1, k / 0.3) * Math.PI));
        this.crack = Math.min(1, Math.max(0, (k - 0.2) / 0.18));
        this.open = easeInOut(Math.min(1, Math.max(0, (k - 0.32) / 0.68)));
      } else {
        this.surge = -1;
        this.open = 1 - easeOut(Math.min(1, k / 0.82));
        this.crack = k < 0.82 ? 1 : 1 - (k - 0.82) / 0.18; // sealed: the crack heals
        if (k >= 0.82 && before < 0.82) this.flare = 0.8; // the thud of the seal
      }
    }
    this.flare = Math.max(0, this.flare - dt * 1.4);
    const o = this.out.getContext("2d")!;
    o.setTransform(dpr, 0, 0, dpr, 0, 0);
    o.globalCompositeOperation = "source-over";
    o.globalAlpha = 1;
    o.drawImage(this.face!.base, 0, 0, w, h);
    const cx = w / 2;
    const cy = h * 0.42;
    const reach = Math.hypot(w, h) * 0.62;
    // ---- a slow breathing scan from the logo outwards, and the power-surge ring when opening
    const band = ((performance.now() / 1000) % 3.2) / 3.2 * reach;
    this.lightRing(o, cx, cy, band - 150, band + 30, 0.42);
    if (this.surge >= 0 && this.surge < 1) {
      const r = easeOut(this.surge) * reach * 1.4;
      this.lightRing(o, cx, cy, r - 240, r + 10, 1, 0.3);
    }
    // ---- the logo, centred; a gap between LED columns falls exactly on the split
    const p = Math.max(9, Math.min(30, (w * 0.6) / this.logo.cols));
    const ox = Math.round(cx - Math.round(this.logo.cols / 2) * p);
    const oy = cy - (this.logo.rows * p) / 2;
    const plate = o.createRadialGradient(cx, cy, 0, cx, cy, this.logo.cols * p * 0.6);
    plate.addColorStop(0, "rgba(3,3,5,0.88)");
    plate.addColorStop(1, "rgba(3,3,5,0)");
    o.fillStyle = plate;
    o.fillRect(0, 0, w, h);
    this.logo.draw(o, (performance.now() - this.t0) / 1000, ox, oy, p, BOOT_LOGO, { grid: true, flare: this.flare });
    // ---- the crack of light down the middle (only while splitting or healing — sealed, there's no seam)
    if (this.crack > 0.01) {
      o.globalCompositeOperation = "lighter";
      const len = this.crack * h * 0.62;
      const cg = o.createLinearGradient(0, cy - len, 0, cy + len);
      cg.addColorStop(0, "rgba(255,255,255,0)");
      cg.addColorStop(0.5, `rgba(255,240,225,${0.95 * Math.min(1, this.crack * 1.4)})`);
      cg.addColorStop(1, "rgba(255,255,255,0)");
      o.fillStyle = cg;
      o.fillRect(cx - 1.2, cy - len, 2.4, len * 2);
      const halo = o.createRadialGradient(cx, cy, 0, cx, cy, 170 * this.crack);
      halo.addColorStop(0, `rgba(255,190,120,${0.35 * this.crack})`);
      halo.addColorStop(1, "rgba(0,0,0,0)");
      o.fillStyle = halo;
      o.fillRect(cx - 170, cy - 170, 340, 340);
      o.globalCompositeOperation = "source-over";
    }
    // ---- split into the two doors
    const half = Math.ceil(w / 2);
    for (const [c, sx] of [[this.left, 0], [this.right, w - half]] as const) {
      const g = c.getContext("2d")!;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.clearRect(0, 0, c.width, c.height);
      g.drawImage(this.out, sx * dpr, 0, half * dpr, h * dpr, 0, 0, c.width, c.height);
      if (this.open > 0.002) {
        // the inner edge catches the light pouring through
        const ex = sx === 0 ? c.width - 3 * dpr : 0;
        const eg = g.createLinearGradient(ex, 0, ex + 3 * dpr, 0);
        eg.addColorStop(0, "rgba(255,230,210,0.9)");
        eg.addColorStop(1, "rgba(255,230,210,0.2)");
        g.fillStyle = eg;
        g.fillRect(ex, 0, 3 * dpr, c.height);
      }
    }
    return { open: this.open, crack: this.crack, shine: Math.min(1, this.crack) * (1 - this.open * 0.85) };
  }
}
