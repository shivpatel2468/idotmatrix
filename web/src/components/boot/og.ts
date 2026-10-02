/** Intro theme "OG": the project's first boot animation, kept exactly as it moved — LEDs fly in from random
 *  points and settle into the wordmark, then breathe — just drawn better: round LEDs with soft glow halos, short
 *  motion trails while they fly, an ember-to-amber gradient across the word, and a faint reflection below. */

// "DESKDOT" in the same 3×5 font the original used
const G: Record<string, string[]> = {
  D: ["##.", "#.#", "#.#", "#.#", "##."],
  E: ["###", "#..", "##.", "#..", "###"],
  S: [".##", "#..", ".#.", "..#", "##."],
  K: ["#.#", "#.#", "##.", "#.#", "#.#"],
  O: [".#.", "#.#", "#.#", "#.#", ".#."],
  T: ["###", ".#.", ".#.", ".#.", ".#."],
};
const WORD = "DESKDOT";
const ROWS = 5;
const COLS = WORD.length * 4 - 1;

type Dot = { x: number; y: number; sx: number; sy: number; d: number; px: number; py: number };

function sprite(color: string, size: number) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const r = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  r.addColorStop(0, color);
  r.addColorStop(0.3, color + "88");
  r.addColorStop(1, color + "00");
  g.fillStyle = r;
  g.fillRect(0, 0, size, size);
  return c;
}

const mix = (a: [number, number, number], b: [number, number, number], k: number) =>
  `rgb(${Math.round(a[0] + (b[0] - a[0]) * k)},${Math.round(a[1] + (b[1] - a[1]) * k)},${Math.round(a[2] + (b[2] - a[2]) * k)})`;
const EMBER: [number, number, number] = [255, 72, 24];
const AMBER: [number, number, number] = [255, 176, 32];

export class OgIntro {
  private dots: Dot[] = [];
  private t0 = performance.now();
  private glow = sprite("#ff5a1f", 64);
  private cell = 16;
  constructor(private cv: HTMLCanvasElement) {
    [...WORD].forEach((ch, i) =>
      G[ch].forEach((row, y) =>
        [...row].forEach((c, dx) => {
          if (c !== "#") return;
          const x = i * 4 + dx;
          // the original motion: start anywhere in a tall band around the word, small random delays
          const sx = Math.random() * COLS;
          const sy = Math.random() * ROWS * 4 - ROWS * 1.5;
          this.dots.push({ x, y, sx, sy, d: Math.random() * 0.5, px: sx, py: sy });
        }),
      ),
    );
    this.resize();
  }

  restart() {
    this.t0 = performance.now();
  }

  resize() {
    this.cell = Math.max(9, Math.min(22, Math.floor((Math.min(window.innerWidth, 900) * 0.8) / COLS)));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = COLS * this.cell;
    const h = ROWS * this.cell * 1.7; // room for the reflection
    this.cv.width = Math.round(w * dpr);
    this.cv.height = Math.round(h * dpr);
    this.cv.style.width = `${w}px`;
    this.cv.style.height = `${h}px`;
    this.cv.getContext("2d")!.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  frame() {
    const g = this.cv.getContext("2d")!;
    const c = this.cell;
    const w = COLS * c;
    const h = ROWS * c;
    const t = (performance.now() - this.t0) / 1000;
    g.clearRect(0, 0, w, h * 1.7);
    // the dark matrix
    for (let y = 0; y < ROWS; y++)
      for (let x = 0; x < COLS; x++) {
        const cx = x * c + c / 2;
        const cy = y * c + c / 2;
        g.fillStyle = "#17171d";
        g.beginPath();
        g.arc(cx, cy, c * 0.34, 0, Math.PI * 2);
        g.fill();
        g.fillStyle = "rgba(255,255,255,0.05)";
        g.beginPath();
        g.arc(cx - c * 0.08, cy - c * 0.1, c * 0.12, 0, Math.PI * 2);
        g.fill();
      }
    const draw = (refl: boolean) => {
      for (const p of this.dots) {
        const k = Math.min(1, Math.max(0, (t - p.d) / 0.9));
        const e = 1 - (1 - k) ** 3;
        const x = p.sx + (p.x - p.sx) * e;
        const y = p.sy + (p.y - p.sy) * e;
        const glow = k >= 1 ? 0.75 + 0.25 * Math.sin(t * 3 + p.x * 0.4) : 0.4 + 0.6 * k;
        const col = mix(EMBER, AMBER, p.x / COLS);
        const cx = x * c + c / 2;
        const cy = refl ? (2 * ROWS - y) * c + c / 2 + c * 0.25 : y * c + c / 2;
        // the reflection fades away from the baseline (the top of each letter is the faintest)
        const fade = refl ? 0.012 + 0.07 * Math.max(0, y / (ROWS - 1)) ** 1.6 : 1;
        g.globalAlpha = refl ? glow * fade : 1;
        if (!refl && k > 0 && k < 1) {
          // a short trail behind a flying LED
          g.strokeStyle = col;
          g.globalAlpha = 0.35 * (1 - k);
          g.lineWidth = c * 0.3;
          g.lineCap = "round";
          g.beginPath();
          g.moveTo(p.px * c + c / 2, p.py * c + c / 2);
          g.lineTo(cx, cy);
          g.stroke();
          g.globalAlpha = 1;
        }
        g.globalCompositeOperation = "lighter";
        const gs = c * 2.6;
        g.globalAlpha = (refl ? fade * 0.5 : 0.55) * glow;
        g.drawImage(this.glow, cx - gs / 2, cy - gs / 2, gs, gs);
        g.globalCompositeOperation = "source-over";
        g.globalAlpha = refl ? glow * fade : Math.min(1, glow);
        g.fillStyle = col;
        g.beginPath();
        g.arc(cx, cy, c * 0.36, 0, Math.PI * 2);
        g.fill();
        if (!refl) {
          g.fillStyle = "rgba(255,240,220,0.55)";
          g.beginPath();
          g.arc(cx - c * 0.07, cy - c * 0.09, c * 0.13, 0, Math.PI * 2);
          g.fill();
          p.px = x;
          p.py = y;
        }
        g.globalAlpha = 1;
      }
    };
    draw(true);
    draw(false);
  }
}
