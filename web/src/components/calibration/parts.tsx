import clsx from "clsx";
import { useEffect, useRef } from "react";
import { type Calib, calibrator, type Search, candidates } from "../../lib/calib";
import { onFrame } from "../../lib/store";
import { api } from "../../lib/api";
import { LedPanel } from "../LedPanel";

const N = 32;

/** Stop whatever test card is on the panel when the component that started it goes away. */
export function useClearOnUnmount() {
  useEffect(() => {
    // a reload or closed tab skips React's cleanup: tell the engine on the way out (keepalive survives unload)
    const bye = () => void fetch("/api/calibration/pattern", { method: "DELETE", keepalive: true }).catch(() => undefined);
    window.addEventListener("pagehide", bye);
    return () => {
      window.removeEventListener("pagehide", bye);
      void api.clearPattern().catch(() => undefined);
    };
  }, []);
}

/** The reference: the test video exactly as the computer screen shows it (never calibrated). */
export function ScreenReference({ size = 208, split }: { size?: number; split?: number }) {
  return (
    <figure className="m-0">
      <div className="relative overflow-hidden rounded-[10px] border border-line bg-black p-1.5" style={{ width: size + 12 }}>
        <LedPanel size={size} look="pixel" glow={false} lookSwitch={false} raw />
        {split !== undefined && <SplitLine split={split} />}
      </div>
      <figcaption className="engrave mt-1.5 text-center">On your screen</figcaption>
    </figure>
  );
}

function SplitLine({ split }: { split: number }) {
  return (
    <div className="pointer-events-none absolute inset-1.5">
      {split > 0 && split < N && (
        <span className="absolute inset-y-0 w-px bg-ember/70" style={{ left: `${(split / N) * 100}%` }} />
      )}
    </div>
  );
}

/**
 * What the panel is sent, sketched locally with the same maths as the engine: the live reference frame through
 * `a` on the left of `split` and `b` on the right. (The real LEDs add their own light; this shows the intent.)
 */
export function PanelSketch({ a, b, split = 16, size = 120, caption = "Sent to the panel" }: {
  a: Calib; b?: Calib | null; split?: number; size?: number; caption?: string;
}) {
  const cv = useRef<HTMLCanvasElement>(null);
  const key = JSON.stringify([a, b, split]);
  useEffect(() => {
    const canvas = cv.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;
    const img = ctx.createImageData(N, N);
    const fa = calibrator(a), fb = b ? calibrator(b) : fa;
    const bufA = new Uint8Array(N * N * 3), bufB = new Uint8Array(N * N * 3);
    return onFrame((rgb) => {
      const ra = fa(rgb, bufA), rb = fb(rgb, bufB);
      for (let i = 0; i < N * N; i++) {
        const x = i % N;
        const src = x < split ? ra : rb;
        img.data[i * 4] = src[i * 3];
        img.data[i * 4 + 1] = src[i * 3 + 1];
        img.data[i * 4 + 2] = src[i * 3 + 2];
        img.data[i * 4 + 3] = 255;
      }
      ctx.putImageData(img, 0, 0);
    });
  }, [key]); // `key` captures a, b and split
  return (
    <figure className="m-0">
      <div className="rounded-[10px] border border-line bg-black p-1.5">
        <canvas ref={cv} width={N} height={N} style={{ width: size, height: size, imageRendering: "pixelated", display: "block" }} aria-label={caption} role="img" />
      </div>
      <figcaption className="engrave mt-1.5 text-center">{caption}</figcaption>
    </figure>
  );
}

/** Step dots + a label. */
export function Progress({ steps, at, labels }: { steps: number; at: number; labels?: string[] }) {
  return (
    <div>
      <div className="flex gap-1" role="progressbar" aria-valuemin={0} aria-valuemax={steps} aria-valuenow={at}>
        {Array.from({ length: steps }, (_, i) => (
          <span key={i} title={labels?.[i]} className={clsx("h-1.5 flex-1 rounded-full transition-colors duration-500", i < at ? "bg-ember" : i === at ? "bg-ember/50" : "bg-chassis-3")} />
        ))}
      </div>
    </div>
  );
}

/**
 * The converging search, drawn: the full range, the window still in play, and where A and B sit in it.
 * Watching the window shrink is the "you're getting closer" feedback.
 */
export function SearchMeter({ s, fmt = (v: number) => v.toFixed(2), lowLabel, highLabel }: {
  s: Search; fmt?: (v: number) => string; lowLabel?: string; highLabel?: string;
}) {
  const [a, b] = candidates(s);
  const pct = (v: number) => `${((v - s.min) / (s.max - s.min)) * 100}%`;
  const lo = Math.max(s.min, s.c - 2 * s.d), hi = Math.min(s.max, s.c + 2 * s.d);
  return (
    <div className="select-none">
      <div className="relative h-7">
        <div className="absolute inset-x-0 top-3 h-1 rounded-full bg-chassis-3" />
        <div className="absolute top-2.5 h-2 rounded-full bg-ember/25 transition-all duration-500" style={{ left: pct(lo), width: `calc(${pct(hi)} - ${pct(lo)})` }} />
        {!s.done && (
          <>
            <Pin at={pct(a)} label="A" />
            <Pin at={pct(b)} label="B" />
          </>
        )}
        {s.done && <Pin at={pct(s.c)} label="✓" ember />}
      </div>
      <div className="flex justify-between font-mono text-[10px] text-ink-4">
        <span>{lowLabel ?? fmt(s.min)}</span>
        <span className="text-ink-3">{s.done ? `→ ${fmt(s.c)}` : `round ${s.round + 1} of ${s.rounds}`}</span>
        <span>{highLabel ?? fmt(s.max)}</span>
      </div>
    </div>
  );
}

function Pin({ at, label, ember }: { at: string; label: string; ember?: boolean }) {
  return (
    <span className={clsx("absolute top-0 grid h-7 w-6 -translate-x-1/2 place-items-center rounded-md border font-mono text-[11px] font-bold transition-all duration-500",
      ember ? "border-ember bg-ember text-black" : "border-line-2 bg-chassis-2 text-ink-1")} style={{ left: at }}>
      {label}
    </span>
  );
}

/** A row of colour swatches (a preset's look on skin, sky, foliage, ember, greys and white). */
export function Swatches({ colors, className }: { colors: string[]; className?: string }) {
  return (
    <div className={clsx("flex overflow-hidden rounded-[5px] border border-white/5", className)} aria-hidden>
      {colors.map((c, i) => <span key={i} className="h-3 flex-1" style={{ background: c }} />)}
    </div>
  );
}

/** Chips to pick which test video plays. */
export function VideoChips({ videos, value, onChange }: { videos: { id: string; name: string; hint: string }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Test video">
      {videos.map((v) => (
        <button key={v.id} role="radio" aria-checked={value === v.id} title={v.hint} onClick={() => onChange(v.id)}
          className={clsx("rounded-full border px-2.5 py-1 text-[11.5px] transition",
            value === v.id ? "border-ember bg-ember-deep text-ink-1" : "border-line text-ink-3 hover:border-line-2 hover:text-ink-1")}>
          {v.name}
        </button>
      ))}
    </div>
  );
}

export const CAL_VIDEO_FALLBACK = [
  { id: "card", name: "Everything card", hint: "" },
  { id: "skin", name: "Skin tones", hint: "" },
  { id: "sky", name: "Sky gradient", hint: "" },
  { id: "wheel", name: "Colour wheel spin", hint: "" },
  { id: "bars", name: "Moving colour bars", hint: "" },
  { id: "ramp", name: "Grey ramp sweep", hint: "" },
  { id: "pulse", name: "Black & white levels", hint: "" },
  { id: "white", name: "Neutral greys", hint: "" },
];

/** Big A / same / B answer keys with keyboard shortcuts (A or ←, S or space, B or →). */
export function ABKeys({ onPick, labels = ["A", "B"], sides = ["left half", "right half"], sameLabel = "Look the same", disabled }: {
  onPick: (p: "a" | "b" | "same") => void; labels?: [string, string]; sides?: [string, string]; sameLabel?: string; disabled?: boolean;
}) {
  const pick = useRef(onPick);
  pick.current = onPick;
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (disabled || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const k = e.key.toLowerCase();
      if (k === "a" || k === "arrowleft") pick.current("a");
      else if (k === "b" || k === "arrowright") pick.current("b");
      else if (k === "s" || k === " ") { e.preventDefault(); pick.current("same"); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [disabled]);
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] gap-2">
      <button className="key !h-12 justify-center !text-[14px]" disabled={disabled} onClick={() => onPick("a")}>
        <span className="font-mono text-[16px] font-bold text-ember">{labels[0]}</span> {sides[0]}
      </button>
      <button className="key key-ghost !h-12 justify-center" disabled={disabled} onClick={() => onPick("same")}>{sameLabel}</button>
      <button className="key !h-12 justify-center !text-[14px]" disabled={disabled} onClick={() => onPick("b")}>
        {sides[1]} <span className="font-mono text-[16px] font-bold text-ember">{labels[1]}</span>
      </button>
    </div>
  );
}
