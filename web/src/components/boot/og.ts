/** Intro theme "OG": the project's first boot animation — LEDs fly in from random points and glide into the
 *  wordmark — drawn clean for any screen: flat round LEDs in the brand's two shades ("DESK" rose, "DOT" gold), a
 *  smooth ease-out, no glare, halos or reflection. */

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

type Dot = { x: number; y: number; sx: number; sy: number; d: number; col: string };

// the brand's two shades: "DESK" rose, "DOT" gold
const ROSE = "#ff3f78";
const GOLD = "#ffcc33";
const FLY = 1.1; // seconds one LED takes to fly home
const ease = (k: number) => (k >= 1 ? 1 : 1 - (1 - k) ** 4);

export class OgIntro {
  private dots: Dot[] = [];
  private t0 = performance.now();
  private cell = 16;
  constructor(private cv: HTMLCanvasElement) {
    [...WORD].forEach((ch, i) =>
      G[ch].forEach((row, y) =>
        [...row].forEach((c, dx) => {
          if (c !== "#") return;
          const x = i * 4 + dx;
          // the original motion: start anywhere in a band around the word, small random delays
          const sx = Math.random() * COLS;
          const sy = Math.random() * ROWS * 3 - ROWS;
          this.dots.push({ x, y, sx, sy, d: Math.random() * 0.45, col: i < 4 ? ROSE : GOLD });
        }),
      ),
    );
    this.resize();
  }

  restart() {
    this.t0 = performance.now();
  }

  resize() {
    this.cell = Math.max(window.innerWidth < 640 ? 4 : 9, Math.min(22, Math.floor((Math.min(window.innerWidth, 900) * (window.innerWidth < 640 ? 0.9 : 0.8)) / COLS)));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = COLS * this.cell;
    const h = ROWS * this.cell;
    this.cv.width = Math.round(w * dpr);
    this.cv.height = Math.round(h * dpr);
    this.cv.style.width = `${w}px`;
    this.cv.style.height = `${h}px`;
    this.cv.getContext("2d")!.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  /** Clean, flat LEDs: no halos, no specular glints, no reflection — just crisp round dots gliding home. */
  frame() {
    const g = this.cv.getContext("2d")!;
    const c = this.cell;
    const r = c * 0.36;
    const t = (performance.now() - this.t0) / 1000;
    g.clearRect(0, 0, COLS * c, ROWS * c);
    // the unlit matrix, barely there
    g.fillStyle = "#15151b";
    g.beginPath();
    for (let y = 0; y < ROWS; y++)
      for (let x = 0; x < COLS; x++) {
        g.moveTo(x * c + c / 2 + r, y * c + c / 2);
        g.arc(x * c + c / 2, y * c + c / 2, r, 0, Math.PI * 2);
      }
    g.fill();
    // a slow, gentle shimmer across the word once everything has landed
    const settled = Math.max(0, t - 0.45 - FLY);
    for (const p of this.dots) {
      const k = Math.min(1, Math.max(0, (t - p.d) / FLY));
      if (k <= 0) continue;
      const e = ease(k);
      const cx = (p.sx + (p.x - p.sx) * e) * c + c / 2;
      const cy = (p.sy + (p.y - p.sy) * e) * c + c / 2;
      const shimmer = settled > 0 ? 0.9 + 0.1 * Math.sin(settled * 2.2 - p.x * 0.35) : 1;
      g.globalAlpha = Math.min(1, 0.25 + k * 1.2) * shimmer;
      g.fillStyle = p.col;
      g.beginPath();
      g.arc(cx, cy, r, 0, Math.PI * 2);
      g.fill();
    }
    g.globalAlpha = 1;
  }
}
