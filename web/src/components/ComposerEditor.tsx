import clsx from "clsx";
import { Copy, Eye, EyeOff, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { EMPTY_MAP, useStore } from "../lib/store";

export type Layer = {
  id: string;
  kind: "text" | "time" | "seconds" | "date" | "month" | "day" | "weather" | "cpu" | "ram" | "price";
  text: string;
  x: number;
  y: number;
  font: "tiny" | "small" | "big";
  color: string;
  color2: string;
  effect: "solid" | "rainbow" | "gradient" | "pulse" | "blink" | "scroll" | "glow";
  align: "left" | "center" | "right";
  visible: boolean;
};
type Box = { id: string; x: number; y: number; w: number; h: number; text: string };

const KINDS: [Layer["kind"], string][] = [
  ["text", "Text"], ["time", "Time"], ["seconds", "Time + sec"], ["date", "Weekday + day"], ["month", "Day + month"],
  ["day", "Weekday"], ["weather", "Temperature"], ["cpu", "CPU %"], ["ram", "RAM %"], ["price", "Crypto price"],
];
const EFFECTS: Layer["effect"][] = ["solid", "rainbow", "gradient", "pulse", "blink", "glow", "scroll"];
const HEIGHT = { tiny: 5, small: 7, big: 10 } as const;
const uid = () => Math.random().toString(16).slice(2, 8);

// ------------------------------------------------------------------- shared editing state
let pending: number | undefined;
function useLayers() {
  const layers = (useStore((s) => s.state?.apps.composer?.layers) as Layer[] | undefined) ?? [];
  const save = (next: Layer[]) => {
    useStore.setState((s) =>
      s.state ? { state: { ...s.state, apps: { ...s.state.apps, composer: { ...s.state.apps.composer, layers: next } } } } : {},
    );
    clearTimeout(pending);
    pending = window.setTimeout(() => api.patchSettings("composer", { layers: next }), 120);
  };
  return { layers, save };
}

/** Transparent layer over the LED preview: click to add, drag to move, double-click to edit. */
export function ComposerOverlay() {
  const { layers, save } = useLayers();
  const boxes = (useStore((s) => s.state?.engine.current?.status?.boxes) as Box[] | undefined) ?? [];
  const sel = useStore((s) => s.layerSel);
  const set = useStore((s) => s.set);
  const brush = useStore((s) => s.brush);
  const root = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: string; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const [ghost, setGhost] = useState<Record<string, { x: number; y: number }>>({});

  const cell = (e: React.PointerEvent) => {
    const r = root.current!.getBoundingClientRect();
    return [Math.floor(((e.clientX - r.left) / r.width) * 32), Math.floor(((e.clientY - r.top) / r.height) * 32)];
  };

  // keyboard: nudge / delete the selected layer
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!sel || (e.target as HTMLElement)?.closest("input, textarea, select")) return;
      const lay = layers.find((l) => l.id === sel);
      if (!lay) return;
      const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      if (d) {
        e.preventDefault();
        e.stopImmediatePropagation();
        save(layers.map((l) => (l.id === sel ? { ...l, x: l.x + d[0], y: l.y + d[1], align: "left" } : l)));
      } else if (e.key === "Delete" || e.key === "Backspace") {
        save(layers.filter((l) => l.id !== sel));
        set({ layerSel: null });
      } else if (e.key === "Escape") set({ layerSel: null });
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [sel, layers, save, set]);

  const boxOf = (id: string) => {
    const b = boxes.find((x) => x.id === id);
    const lay = layers.find((l) => l.id === id);
    if (!lay) return null;
    const g = ghost[id];
    if (b) return g ? { ...b, x: b.x + (g.x - lay.x), y: b.y + (g.y - lay.y) } : b;
    return { id, x: g?.x ?? lay.x, y: g?.y ?? lay.y, w: Math.max(4, lay.text.length * 4), h: HEIGHT[lay.font], text: lay.text };
  };

  return (
    <div
      ref={root}
      className="absolute inset-0 cursor-crosshair"
      onPointerDown={(e) => {
        if (e.target !== root.current) return;
        const [x, y] = cell(e);
        const lay: Layer = {
          id: uid(), kind: "text", text: "TEXT", x, y: Math.min(y, 25), font: "small", color: brush, color2: "#ff00be",
          effect: "solid", align: "left", visible: true,
        };
        save([...layers, lay]);
        set({ layerSel: lay.id });
        setTimeout(() => document.getElementById("composer-text")?.focus(), 30);
      }}
    >
      {layers.map((lay) => {
        const b = boxOf(lay.id);
        if (!b || !lay.visible) return null;
        const active = sel === lay.id;
        return (
          <div
            key={lay.id}
            title={`${lay.kind}: ${b.text} — drag to move, double-click to edit`}
            className={clsx(
              "absolute cursor-move rounded-[2px] transition-[outline-color]",
              active ? "outline outline-2 outline-ember" : "outline outline-1 outline-dashed outline-white/25 hover:outline-white/70",
            )}
            style={{
              left: `${(b.x / 32) * 100}%`, top: `${(b.y / 32) * 100}%`,
              width: `${(Math.max(1, b.w) / 32) * 100}%`, height: `${(b.h / 32) * 100}%`,
              outlineOffset: 3,
            }}
            onPointerDown={(e) => {
              e.stopPropagation();
              (e.target as Element).setPointerCapture(e.pointerId);
              set({ layerSel: lay.id });
              drag.current = { id: lay.id, sx: e.clientX, sy: e.clientY, ox: lay.x, oy: lay.y, moved: false };
            }}
            onPointerMove={(e) => {
              const d = drag.current;
              if (!d || d.id !== lay.id) return;
              const r = root.current!.getBoundingClientRect();
              const dx = Math.round(((e.clientX - d.sx) / r.width) * 32);
              const dy = Math.round(((e.clientY - d.sy) / r.height) * 32);
              if (dx || dy) d.moved = true;
              setGhost({ [lay.id]: { x: d.ox + dx, y: d.oy + dy } });
            }}
            onPointerUp={() => {
              const d = drag.current;
              drag.current = null;
              const g = ghost[lay.id];
              setGhost({});
              if (d?.moved && g) {
                // a dragged layer is positioned explicitly from now on
                const x = lay.align === "left" ? g.x : b.x + (g.x - lay.x);
                save(layers.map((l) => (l.id === lay.id ? { ...l, x, y: g.y, align: "left" } : l)));
              }
            }}
            onDoubleClick={() => document.getElementById("composer-text")?.focus()}
          >
            {active && <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-ember px-1 font-mono text-[9px] text-black">{lay.kind}</span>}
          </div>
        );
      })}
    </div>
  );
}

/** Styling controls for the selected layer (shown under the panel). */
export function ComposerToolbar() {
  const { layers, save } = useLayers();
  const sel = useStore((s) => s.layerSel);
  const set = useStore((s) => s.set);
  const palette = useStore((s) => s.meta?.palette ?? EMPTY_MAP);
  const lay = layers.find((l) => l.id === sel);
  const upd = (p: Partial<Layer>) => lay && save(layers.map((l) => (l.id === lay.id ? { ...l, ...p } : l)));
  const swatches = Object.entries(palette).filter(([k]) => !["black", "ink", "shade", "ok", "warn", "bad", "info"].includes(k));

  if (!lay) {
    return (
      <div className="surface flex w-full max-w-[640px] flex-wrap items-center gap-3 p-3 animate-rise">
        <span className="led" data-on="ember" />
        <span className="text-[12.5px] text-ink-2">
          <b className="text-ink-1">Click anywhere on the panel</b> to place text · drag to move · arrows nudge · Del removes
        </span>
        <button className="key ml-auto" onClick={() => {
          const l: Layer = { id: uid(), kind: "text", text: "HELLO", x: 1, y: 12, font: "small", color: "#ffffff",
            color2: "#ff00be", effect: "solid", align: "center", visible: true };
          save([...layers, l]);
          set({ layerSel: l.id });
        }}><Plus size={13} /> Add text</button>
      </div>
    );
  }
  const needsText = lay.kind === "text" || lay.kind === "price" || lay.kind === "cpu" || lay.kind === "ram";
  return (
    <div className="surface w-full max-w-[640px] space-y-2.5 p-3 animate-rise">
      <div className="flex flex-wrap items-center gap-2">
        <select className="field !h-8 !w-36 !text-[12px]" value={lay.kind} onChange={(e) => upd({ kind: e.target.value as Layer["kind"], text: e.target.value === "price" ? "BTC" : e.target.value === "text" ? lay.text || "TEXT" : e.target.value === "cpu" ? "CPU " : e.target.value === "ram" ? "RAM " : "" })}>
          {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        {needsText && (
          <input id="composer-text" className="field !h-8 min-w-0 flex-1 !font-mono !text-[12.5px] uppercase" value={lay.text}
            placeholder={lay.kind === "price" ? "Symbol e.g. BTC" : lay.kind === "text" ? "Your text" : "Label"}
            maxLength={120} onChange={(e) => upd({ text: e.target.value.toUpperCase() })} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
        )}
        <div className="ml-auto flex gap-1">
          <button className="key key-icon !h-8 !w-8" title={lay.visible ? "Hide" : "Show"} onClick={() => upd({ visible: !lay.visible })}>
            {lay.visible ? <Eye size={13} /> : <EyeOff size={13} />}
          </button>
          <button className="key key-icon !h-8 !w-8" title="Duplicate" onClick={() => {
            const c = { ...lay, id: uid(), y: Math.min(28, lay.y + 8) };
            save([...layers, c]);
            set({ layerSel: c.id });
          }}><Copy size={13} /></button>
          <button className="key key-icon !h-8 !w-8" title="Delete (Del)" onClick={() => { save(layers.filter((l) => l.id !== lay.id)); set({ layerSel: null }); }}>
            <Trash2 size={13} />
          </button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="seg">
          {(["tiny", "small", "big"] as const).map((f) => (
            <button key={f} data-active={lay.font === f} onClick={() => upd({ font: f })} title={f === "big" ? "Digits only" : undefined}>{f}</button>
          ))}
        </div>
        <div className="seg">
          {(["left", "center", "right"] as const).map((a) => <button key={a} data-active={lay.align === a} onClick={() => upd({ align: a })}>{a}</button>)}
        </div>
        <select className="field !h-8 !w-28 !text-[12px]" value={lay.effect} onChange={(e) => upd({ effect: e.target.value as Layer["effect"] })}>
          {EFFECTS.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <label className="relative h-7 w-9 overflow-hidden rounded-[7px] border border-line-2" style={{ background: lay.color }} title="Colour">
          <input type="color" value={lay.color} onChange={(e) => upd({ color: e.target.value })} className="absolute inset-0 opacity-0" />
        </label>
        {lay.effect === "gradient" && (
          <label className="relative h-7 w-9 overflow-hidden rounded-[7px] border border-line-2" style={{ background: lay.color2 }} title="Gradient end">
            <input type="color" value={lay.color2} onChange={(e) => upd({ color2: e.target.value })} className="absolute inset-0 opacity-0" />
          </label>
        )}
        {swatches.map(([n, c]) => (
          <button key={n} title={n} onClick={() => upd({ color: c })} className={clsx("h-5 w-5 rounded-[5px] border", lay.color === c ? "border-white" : "border-black/40")} style={{ background: c }} />
        ))}
        <span className="ml-auto font-mono text-[10px] text-ink-4">X{lay.x} Y{lay.y}</span>
      </div>
    </div>
  );
}
