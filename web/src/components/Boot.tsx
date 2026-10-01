import { useEffect, useRef, useState } from "react";
import { useStore } from "../lib/store";
import { TIPS } from "../lib/tips";

// "DOTDECK" as a 5-row bitmap (the same 3x5 font the panel uses)
const WORD: string[] = [
  "##...#..###.##..###..##.#.#",
  "#.#.#.#..#..#.#.#...#...#.#",
  "#.#.#.#..#..#.#.##..#...##.",
  "#.#.#.#..#..#.#.#...#...#.#",
  "##...#...#..##..###..##.#.#",
];

/**
 * Boot screen: LEDs fly in from random positions and settle into the wordmark while the studio
 * connects; progress follows real milestones (engine link, app catalogue, first frame).
 */
export function Boot() {
  const meta = useStore((s) => s.meta);
  const state = useStore((s) => s.state);
  const link = useStore((s) => s.link);
  const cv = useRef<HTMLCanvasElement>(null);
  const [done, setDone] = useState(false);
  const [gone, setGone] = useState(false);
  const [tip, setTip] = useState(() => Math.floor(Math.random() * TIPS.length));
  const start = useRef(performance.now());

  const steps = [
    { label: "Waking the engine", ok: link === "open" },
    { label: "Loading apps", ok: !!meta },
    { label: "Reading the panel", ok: !!state },
  ];
  const progress = steps.filter((s) => s.ok).length / steps.length;

  useEffect(() => {
    const t = setInterval(() => setTip((i) => (i + 1) % TIPS.length), 2600);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (progress < 1) return;
    const wait = Math.max(0, 1700 - (performance.now() - start.current));
    const t = setTimeout(() => setDone(true), wait);
    return () => clearTimeout(t);
  }, [progress]);

  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => setGone(true), 650);
    return () => clearTimeout(t);
  }, [done]);

  // LED fly-in animation
  useEffect(() => {
    const c = cv.current;
    if (!c) return;
    const ctx = c.getContext("2d")!;
    const cols = WORD[0].length, rows = WORD.length;
    const cell = 14;
    c.width = cols * cell;
    c.height = rows * cell;
    const dots: { x: number; y: number; sx: number; sy: number; d: number }[] = [];
    WORD.forEach((row, y) =>
      [...row].forEach((ch, x) => {
        if (ch === "#") dots.push({ x, y, sx: Math.random() * cols, sy: Math.random() * rows * 4 - rows * 1.5, d: Math.random() * 0.5 });
      }),
    );
    let raf = 0;
    const t0 = performance.now();
    const draw = () => {
      const t = (performance.now() - t0) / 1000;
      ctx.clearRect(0, 0, c.width, c.height);
      for (let y = 0; y < rows; y++)
        for (let x = 0; x < cols; x++) {
          ctx.fillStyle = "#16161c";
          ctx.beginPath();
          ctx.roundRect(x * cell + 2, y * cell + 2, cell - 4, cell - 4, 3);
          ctx.fill();
        }
      for (const p of dots) {
        const k = Math.min(1, Math.max(0, (t - p.d) / 0.9));
        const e = 1 - Math.pow(1 - k, 3);
        const x = p.sx + (p.x - p.sx) * e, y = p.sy + (p.y - p.sy) * e;
        const glow = k >= 1 ? 0.75 + 0.25 * Math.sin(t * 3 + p.x * 0.4) : 0.4 + 0.6 * k;
        ctx.shadowColor = "#ff4818";
        ctx.shadowBlur = 14 * glow;
        ctx.fillStyle = `rgba(255,${72 + 60 * (1 - k)},24,${glow})`;
        ctx.beginPath();
        ctx.roundRect(x * cell + 2, y * cell + 2, cell - 4, cell - 4, 3);
        ctx.fill();
      }
      ctx.shadowBlur = 0;
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);

  if (gone) return null;
  return (
    <div className={`fixed inset-0 z-[100] grid place-items-center bg-chassis-0 transition-opacity duration-600 ${done ? "opacity-0" : "opacity-100"}`}
      style={{ transitionDuration: "600ms" }}>
      <div className="flex w-[min(560px,90vw)] flex-col items-center gap-8">
        <canvas ref={cv} className="max-w-full" />
        <div className="w-full">
          <div className="h-[3px] overflow-hidden rounded-full bg-chassis-3">
            <div className="h-full rounded-full bg-ember shadow-[0_0_12px_var(--color-ember)] transition-all duration-500" style={{ width: `${Math.max(8, progress * 100)}%` }} />
          </div>
          <div className="mt-3 flex justify-between">
            {steps.map((s) => (
              <span key={s.label} className="engrave flex items-center gap-1.5 !text-[8.5px]">
                <span className="led" data-on={s.ok ? "ok" : "warn"} /> {s.label}
              </span>
            ))}
          </div>
        </div>
        <p key={tip} className="min-h-[3em] max-w-md animate-rise text-center text-[13px] leading-relaxed text-ink-2">
          <span className="engrave mr-2 !text-ember">Tip</span>{TIPS[tip]}
        </p>
        {link === "closed" && (
          <p className="text-center font-mono text-[11px] text-warn">Engine not reachable — start it with <code>uv run dotdeck serve</code></p>
        )}
      </div>
    </div>
  );
}
