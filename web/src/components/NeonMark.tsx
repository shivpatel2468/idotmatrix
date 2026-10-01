import { useEffect, useRef } from "react";
import { type LogoTimeline, NeonLogo } from "../lib/logo";

const HEADER: LogoTimeline = { build: 1.5, hold: 14, off: 1.2 };

/** The header logo: "idotmatrix" in LEDs, built and struck like neon, on a loop. Hover strikes it again. */
export function NeonMark({ pitch = 3.4 }: { pitch?: number }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const restart = useRef<() => void>(() => {});
  useEffect(() => {
    const c = cv.current!;
    const logo = new NeonLogo();
    const pad = pitch * 2.2; // room for the glow
    const w = logo.cols * pitch + pad * 2;
    const h = logo.rows * pitch + pad * 2;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    c.style.width = `${w}px`;
    c.style.height = `${h}px`;
    const ctx = c.getContext("2d")!;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let t0 = performance.now();
    let raf = 0;
    let last = 0;
    restart.current = () => {
      // jump to just before the strike, so hovering re-lights the tubes
      const lt = ((performance.now() - t0) / 1000) % logo.cycle(HEADER);
      if (lt > HEADER.build + 1.6) t0 = performance.now() - HEADER.build * 1000;
    };
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (document.visibilityState !== "visible" || now - last < 1000 / 40) return; // 40 fps is plenty
      last = now;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      logo.draw(ctx, (now - t0) / 1000, pad, pad, pitch, HEADER, { grid: true, still });
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [pitch]);
  return <canvas ref={cv} aria-label="idotmatrix" role="img" className="block" onMouseEnter={() => restart.current()} />;
}
