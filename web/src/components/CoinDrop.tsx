import { useEffect, useRef } from "react";
import { drawSilverCoin } from "../lib/coinArt";
import { sfx } from "../lib/sound";

/**
 * The casino key's coin drop: a silver coin (the Coin Gate intro's coin) arcs in spinning, turns edge-on, drops into a
 * glowing gold slot in the middle of the screen, the slot flashes and a few gold sparks fly — every time the key is
 * pressed. A transparent overlay that never takes a click; `playCoinDrop()` starts it from anywhere.
 */
const EVENT = "deskdot:coin-drop";
export const playCoinDrop = () => window.dispatchEvent(new Event(EVENT));

const FLY = 0.62; // s: the coin's arc to the slot
const SINK = 0.3; // s: sliding in
const GLOW = 0.55; // s: the slot's flash and sparks fading out
const TOTAL = FLY + SINK + GLOW;

const ease = (t: number) => 1 - (1 - t) ** 3;

export function CoinDrop() {
  const cv = useRef<HTMLCanvasElement>(null);
  const raf = useRef(0);

  useEffect(() => {
    const play = () => {
      sfx("coin-insert");
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setTimeout(() => sfx("coin-drop"), 180);
        return;
      }
      const c = cv.current;
      if (!c) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = window.innerWidth;
      const h = window.innerHeight;
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
      c.style.display = "block";
      const g = c.getContext("2d")!;
      const R = Math.max(26, Math.min(54, Math.min(w, h) * 0.06));
      const slot = { x: w / 2, y: h * 0.46, w: R * 0.5, h: R * 2.5 };
      const from = { x: w * 0.5 + Math.min(w * 0.3, 360), y: -R * 2 };
      const sparks = Array.from({ length: 16 }, (_, i) => ({ a: (i / 16) * Math.PI * 2 + Math.random() * 0.3, v: 80 + Math.random() * 140, r: 1.5 + Math.random() * 2 }));
      const t0 = performance.now();
      let dropped = false;
      cancelAnimationFrame(raf.current);

      const frame = (now: number) => {
        const t = (now - t0) / 1000;
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.clearRect(0, 0, w, h);
        // the slot: a dark rounded slit with a gold bezel, lit up as the coin arrives and when it drops
        const arrive = Math.min(1, t / FLY);
        const flash = t > FLY ? Math.max(0, 1 - (t - FLY - SINK * 0.5) / GLOW) : 0;
        const slotA = t < FLY + SINK + GLOW * 0.4 ? Math.min(1, t / 0.18) : Math.max(0, 1 - (t - FLY - SINK - GLOW * 0.4) / (GLOW * 0.6));
        g.globalAlpha = slotA;
        const halo = g.createRadialGradient(slot.x, slot.y, 0, slot.x, slot.y, R * (2.2 + flash * 1.6));
        halo.addColorStop(0, `rgba(255,204,51,${0.35 * arrive + 0.5 * flash})`);
        halo.addColorStop(1, "rgba(255,204,51,0)");
        g.fillStyle = halo;
        g.fillRect(slot.x - R * 4, slot.y - R * 4, R * 8, R * 8);
        const bx = slot.x - slot.w / 2 - 5;
        const by = slot.y - slot.h / 2 - 5;
        g.fillStyle = "#e0a91c";
        g.beginPath();
        g.roundRect(bx, by, slot.w + 10, slot.h + 10, 8);
        g.fill();
        g.fillStyle = "#ffe08a";
        g.beginPath();
        g.roundRect(bx + 1.5, by + 1.5, slot.w + 7, slot.h + 7, 7);
        g.fill();
        g.fillStyle = "#120c02";
        g.beginPath();
        g.roundRect(slot.x - slot.w / 2, slot.y - slot.h / 2, slot.w, slot.h, 4);
        g.fill();
        g.globalAlpha = 1;

        if (t < FLY) {
          // in flight: an arc from the top right, spinning, turning edge-on at the end
          const k = ease(arrive);
          const x = from.x + (slot.x - from.x) * k;
          const y = from.y + (slot.y - R * 1.6 - from.y) * k - Math.sin(k * Math.PI) * h * 0.08;
          const ang = arrive * (Math.PI * 4 + Math.PI / 2 + 0.03); // two full turns, ending edge-on
          drawSilverCoin(g, x, y, R, ang, 1);
        } else if (t < FLY + SINK) {
          // edge-on, sliding down into the slit (clipped by the slot's top)
          if (!dropped) {
            dropped = true;
            sfx("coin-drop");
          }
          const k = (t - FLY) / SINK;
          const y = slot.y - R * 1.6 + k * k * R * 2.6;
          g.save();
          g.beginPath();
          g.rect(0, 0, w, slot.y - slot.h / 2 + 2);
          g.clip();
          drawSilverCoin(g, slot.x, y, R, Math.PI / 2 + 0.03, 1);
          g.restore();
        }
        // sparks from the slot once the coin is in
        if (t > FLY + SINK * 0.6) {
          const s = t - FLY - SINK * 0.6;
          const a = Math.max(0, 1 - s / GLOW);
          g.fillStyle = `rgba(255,224,138,${a})`;
          for (const p of sparks) {
            const d = p.v * s;
            g.beginPath();
            g.arc(slot.x + Math.cos(p.a) * (slot.w + d), slot.y - slot.h * 0.2 + Math.sin(p.a) * d * 0.8 + 60 * s * s, p.r * a + 0.4, 0, Math.PI * 2);
            g.fill();
          }
        }
        if (t < TOTAL) raf.current = requestAnimationFrame(frame);
        else {
          g.clearRect(0, 0, w, h);
          c.style.display = "none";
        }
      };
      raf.current = requestAnimationFrame(frame);
    };
    window.addEventListener(EVENT, play);
    return () => {
      window.removeEventListener(EVENT, play);
      cancelAnimationFrame(raf.current);
    };
  }, []);

  return <canvas ref={cv} aria-hidden className="pointer-events-none fixed inset-0 z-[90] h-full w-full" style={{ display: "none" }} />;
}
