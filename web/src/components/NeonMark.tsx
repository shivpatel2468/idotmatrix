import { useEffect, useRef } from "react";
import { type LogoTimeline, NeonLogo } from "../lib/logo";

const HEADER: LogoTimeline = { build: 1.5, hold: 14, off: 1.2 };

/** The header logo: "DeskDot" in LEDs, built and struck like neon, on a loop. Hover strikes it again.
 *  It redraws only while something moves (build, strike, the loose letter's blink, power-down), idles while the
 *  tubes just hum, and stops while the tab is hidden. */
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
    let timer = 0;
    let last = 0;
    const kick = () => {
      if (!raf && !timer) raf = requestAnimationFrame(frame);
    };
    const wakeNow = () => {
      clearTimeout(timer);
      timer = 0;
      kick();
    };
    const frame = (now: number) => {
      raf = 0;
      if (document.hidden) return; // visibilitychange wakes it
      if (now - last < 1000 / 40) {
        raf = requestAnimationFrame(frame); // 40 fps is plenty
        return;
      }
      last = now;
      const t = (now - t0) / 1000;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      logo.draw(ctx, t, pad, pad, pitch, HEADER, { grid: true, still });
      if (still) return;
      const idle = logo.wake(t, HEADER);
      if (idle > 0) timer = window.setTimeout(() => ((timer = 0), kick()), idle * 1000);
      else raf = requestAnimationFrame(frame);
    };
    restart.current = () => {
      // jump to just before the strike, so hovering re-lights the tubes
      const lt = ((performance.now() - t0) / 1000) % logo.cycle(HEADER);
      if (lt > HEADER.build + 1.6) t0 = performance.now() - HEADER.build * 1000;
      wakeNow();
    };
    const onVis = () => {
      if (document.hidden) {
        clearTimeout(timer);
        timer = 0;
      } else wakeNow();
    };
    document.addEventListener("visibilitychange", onVis);
    kick();
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [pitch]);
  return <canvas ref={cv} aria-label="DeskDot, written in glowing LED dots" role="img" className="block" onMouseEnter={() => restart.current()} />;
}
