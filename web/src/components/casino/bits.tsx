import clsx from "clsx";
import { useEffect, useMemo, useRef, useState } from "react";
import { type Avatar, fmt, useCasino } from "./state";

const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Credits that count up / down to their new value (instant with reduced motion), flashing green or red. */
export function Credits({ value, className }: { value: number; className?: string }) {
  const [shown, setShown] = useState(value);
  const [dir, setDir] = useState<"up" | "down" | null>(null);
  const from = useRef(value);
  const raf = useRef(0);
  useEffect(() => {
    const start = from.current;
    if (start === value) return;
    setDir(value > start ? "up" : "down");
    const dur = reduced() ? 0 : Math.min(1100, Math.max(350, Math.abs(value - start) * 2));
    const t0 = performance.now();
    cancelAnimationFrame(raf.current);
    const step = () => {
      const k = dur ? Math.min(1, (performance.now() - t0) / dur) : 1;
      const e = 1 - (1 - k) ** 3;
      const v = Math.round(start + (value - start) * e);
      from.current = v;
      setShown(v);
      if (k < 1) raf.current = requestAnimationFrame(step);
      else setTimeout(() => setDir(null), 600);
    };
    step();
    return () => cancelAnimationFrame(raf.current);
  }, [value]);
  return <span className={clsx("cz-credits tabular-nums", className)} data-dir={dir ?? undefined}>{fmt(shown)}</span>;
}

/** A phone player's 8×8 pixel avatar (gfx/avatars.py) in their colour; a monogram until the art is known. */
export function AvatarPix({ id, color, name, size = 30 }: { id?: string; color: string; name: string; size?: number }) {
  const art = useCasino((s) => (id ? s.avatars[id] : undefined)) as Avatar | undefined;
  const rects = useMemo(() => {
    if (!art) return null;
    const dark = shade(color, 0.55);
    const pal: Record<string, string> = { c: color, d: dark, w: "#f4f4f4", k: "#111116", y: "#ffd23f", r: "#ff3b4d" };
    const out: React.ReactNode[] = [];
    art.px.forEach((row, y) => [...row].forEach((ch, x) => {
      if (pal[ch]) out.push(<rect key={`${x}-${y}`} x={x} y={y} width={1.02} height={1.02} fill={pal[ch]} />);
    }));
    return out;
  }, [art, color]);
  return (
    <span className="cz-avatar" style={{ width: size, height: size, ["--c" as string]: color }} title={art?.name}>
      {rects ? (
        <svg viewBox="-1 -1 10 10" width={size - 6} height={size - 6} shapeRendering="crispEdges" aria-hidden>{rects}</svg>
      ) : (
        <b style={{ fontSize: size * 0.42 }}>{(name || "?").slice(0, 1).toUpperCase()}</b>
      )}
    </span>
  );
}

export function shade(hex: string, k: number): string {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  const c = [0, 2, 4].map((i) => Math.round(parseInt(h.slice(i, i + 2), 16) * k));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

/** A round countdown dial: the ring empties as betting time runs out (red for the last 5 s). */
export function CountdownRing({ left, span, size = 44 }: { left: number | null; span: number; size?: number }) {
  const r = size / 2 - 4;
  const c = 2 * Math.PI * r;
  const frac = left == null ? 1 : Math.max(0, Math.min(1, left / Math.max(1, span)));
  const hurry = left != null && left <= 5;
  return (
    <span className="cz-ring" style={{ width: size, height: size }} data-hurry={hurry || undefined} aria-hidden>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} className="cz-ring-track" />
        <circle cx={size / 2} cy={size / 2} r={r} className="cz-ring-fill" strokeDasharray={c} strokeDashoffset={c * (1 - frac)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <b>{left == null ? "∞" : Math.ceil(left - 1e-6)}</b>
    </span>
  );
}

/** One casino chip (the rack and the cascade). */
export function Chip({ value, size = 34, active, onClick, title }: { value: number | "all"; size?: number; active?: boolean; onClick?: () => void; title?: string }) {
  const col = chipColor(value);
  const Tag = onClick ? "button" : "span";
  return (
    <Tag className="cz-chip" data-active={active || undefined} data-v={String(value)} onClick={onClick} title={title} aria-pressed={onClick ? !!active : undefined}
      style={{ width: size, height: size, ["--chip" as string]: col, fontSize: size * (value === "all" ? 0.26 : 0.3) }}>
      <span>{value === "all" ? "ALL" : value >= 1000 ? `${value / 1000}k` : value}</span>
    </Tag>
  );
}

export function chipColor(v: number | "all"): string {
  if (v === "all") return "#ff3f78";
  if (v >= 500) return "#7b3fe4";
  if (v >= 100) return "#1d1d24";
  if (v >= 25) return "#13a65a";
  if (v >= 5) return "#e3263f";
  return "#e9e6dc";
}

/** Inline numeric entry that commits on Enter / blur. */
export function NumberInput({ value, min = 0, max, onCommit, className, label, width = 92 }: {
  value: number; min?: number; max?: number; onCommit: (v: number) => void; className?: string; label?: string; width?: number;
}) {
  const [v, setV] = useState(String(value));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setV(String(value));
  }, [value]);
  const commit = () => {
    focused.current = false;
    const n = Math.round(Number(v));
    if (!Number.isFinite(n)) return setV(String(value));
    const c = Math.max(min, max != null ? Math.min(max, n) : n);
    setV(String(c));
    if (c !== value) onCommit(c);
  };
  return (
    <input className={clsx("cz-num", className)} inputMode="numeric" aria-label={label} value={v} style={{ width }}
      onFocus={() => (focused.current = true)} onChange={(e) => setV(e.target.value.replace(/[^\d-]/g, ""))}
      onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") { setV(String(value)); (e.target as HTMLInputElement).blur(); } }} />
  );
}

/** A small section header inside a wing. */
export function Section({ title, hint, right, children, className }: { title: string; hint?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={clsx("cz-section", className)}>
      <header>
        <div className="min-w-0 flex-1">
          <h3>{title}</h3>
          {hint && <p>{hint}</p>}
        </div>
        {right}
      </header>
      {children}
    </section>
  );
}

/** Segmented tabs in the casino style. */
export function Tabs<T extends string>({ value, options, onChange, label }: { value: T; options: [T, string, number?][]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="cz-tabs" role="tablist" aria-label={label}>
      {options.map(([id, text, badge]) => (
        <button key={id} role="tab" aria-selected={value === id} data-on={value === id} onClick={() => onChange(id)}>
          {text}
          {badge ? <i>{badge}</i> : null}
        </button>
      ))}
    </div>
  );
}
