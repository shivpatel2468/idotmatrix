import { useEffect, useRef, useState } from "react";

/** A settings row: label + hint on the left, controls on the right (wraps on narrow screens). */
export function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5">
      <div className="min-w-[160px] flex-1">
        <div className="text-[13px] font-[560]">{label}</div>
        {hint && <div className="text-[11.5px] leading-snug text-ink-3">{hint}</div>}
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

/** A range input that shows its value and commits after a short pause (no request per pixel). */
export function Slider({ value, min, max, step = 1, unit = "", onCommit, width = 180 }: {
  value: number; min: number; max: number; step?: number; unit?: string; onCommit: (v: number) => void; width?: number;
}) {
  const [v, setV] = useState(value);
  const t = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => setV(value), [value]);
  return (
    <>
      <input type="range" min={min} max={max} step={step} value={v} className="fader" style={{ width, ["--fill" as string]: `${((v - min) / (max - min)) * 100}%` }}
        onChange={(e) => {
          const n = +e.target.value;
          setV(n);
          clearTimeout(t.current);
          t.current = setTimeout(() => onCommit(n), 140);
        }} />
      <span className="w-14 text-right font-mono text-[11.5px] tabular-nums text-ink-1">{step < 1 ? v.toFixed(2) : v}{unit}</span>
    </>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  return <button role="switch" aria-checked={on} aria-label={label} className="toggle" onClick={() => onChange(!on)} />;
}
