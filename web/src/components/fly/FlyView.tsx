import clsx from "clsx";
import { Brain, Bug, Gauge, Hand, Maximize2, Minimize2, PanelLeftOpen, RefreshCw, RotateCcw, Settings2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  BRAIN_FORMS, type BrainConfig, type BrainPreset, CAMERAS, type CameraMode, DEFAULT_GFX, FLY_KEYS, type FlyGfx, type FlyKey,
  type FullLayout, type FullView, KEY_GLYPH, KEY_ROLE, OldEngine, THEMES, closeFlyView, flyCanPilot, flyHandBack,
  loadBrainConfig, loadBrainPresets, patchBrainConfig, useFly,
} from "../../lib/fly";
import { appMeta, toast } from "../../lib/store";
import { LedPanel } from "../LedPanel";
import { Slider, Toggle } from "../controls";

type SceneKind = "brain" | "keyboard";

/** A three.js view; the scene code (and three.js itself) loads only when the first one mounts. One renderer per
 *  mounted canvas: unmounting disposes it (and gives its GL context back). */
function FlyCanvas({ kind, onFps }: { kind: SceneKind; onFps?: (fps: number, tier: string) => void }) {
  const el = useRef<HTMLDivElement>(null);
  const host = useRef<{ apply: (g: FlyGfx) => void; dispose: () => void } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const gfx = useFly((s) => s.gfx);
  const fps = useRef(onFps);
  fps.current = onFps;

  useEffect(() => {
    let dead = false;
    import("./three")
      .then((m) => {
        if (dead || !el.current) return;
        try {
          const scene = kind === "brain" ? new m.BrainScene() : new m.KeyboardScene();
          const h = new m.Host(el.current, scene, useFly.getState().gfx);
          h.onFps = (f, t) => fps.current?.(f, t);
          host.current = h;
        } catch (e) {
          setFailed(e instanceof Error ? e.message : String(e));
        }
      })
      .catch((e) => setFailed(String(e)));
    return () => {
      dead = true;
      host.current?.dispose();
      host.current = null;
    };
  }, [kind]);

  useEffect(() => {
    host.current?.apply(gfx);
  }, [gfx]);

  return (
    <div ref={el} className="fly-scene absolute inset-0">
      {failed && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center text-[12px] text-ink-3">
          3D isn't available in this browser (WebGL is off or blocked).
        </div>
      )}
    </div>
  );
}

function kpm(presses: { at: number }[]) {
  const now = performance.now();
  return presses.filter((p) => now - p.at < 60_000).length;
}

/** The keystroke log: every key the fly's neurons pressed, as it happens. */
function KeyHud({ compact = false }: { compact?: boolean }) {
  const presses = useFly((s) => s.presses);
  const counts = useFly((s) => s.counts);
  const theme = THEMES[useFly((s) => s.gfx.theme)];
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const total = FLY_KEYS.reduce((n, k) => n + (counts[k] ?? 0), 0);
  const max = Math.max(1, ...FLY_KEYS.map((k) => counts[k] ?? 0));
  const color = (k: FlyKey) => (k === "a" ? theme.gf : theme[k]);
  // a streak: presses less than 0.5 s apart
  const streak = useMemo(() => {
    let n = 0;
    for (let i = presses.length - 1; i > 0 && presses[i].at - presses[i - 1].at < 500; i--) n++;
    return presses.length ? n + 1 : 0;
  }, [presses]);
  return (
    <div className="pointer-events-none absolute inset-x-3 bottom-3 flex flex-col gap-2">
      <div className="fly-ticker" aria-live="off">
        {presses.slice(compact ? -8 : -14).map((p) => (
          <span key={p.id} className="fly-chip" style={{ ["--c" as string]: color(p.key) }} title={KEY_ROLE[p.key]}>
            {KEY_GLYPH[p.key]}
          </span>
        ))}
        {!presses.length && <span className="text-[11px] text-ink-4">Waiting for the first spike…</span>}
      </div>
      {!compact && (
        <div className="fly-glass grid grid-cols-5 gap-1.5 p-2">
          {FLY_KEYS.map((k) => (
            <div key={k} className="flex flex-col items-center gap-1" title={KEY_ROLE[k]}>
              <div className="relative h-8 w-full overflow-hidden rounded-[4px] bg-white/[0.04]">
                <div className="absolute inset-x-0 bottom-0 transition-[height] duration-300"
                  style={{ height: `${((counts[k] ?? 0) / max) * 100}%`, background: `linear-gradient(to top, ${color(k)}, transparent)` }} />
              </div>
              <span className="font-mono text-[11px] font-[600]" style={{ color: color(k) }}>{KEY_GLYPH[k]}</span>
              <span className="font-mono text-[9.5px] tabular-nums text-ink-3">{counts[k] ?? 0}</span>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.14em] text-ink-3">
        <span><b className="text-ink-1 tabular-nums">{total}</b> keys</span>
        <span><b className="text-ink-1 tabular-nums">{kpm(presses)}</b> / min</span>
        <span className={clsx(streak >= 4 && "fly-streak")}>streak <b className="text-ink-1 tabular-nums">{streak}</b></span>
      </div>
    </div>
  );
}

/** The live neuron readout under the brain view. */
function BrainHud() {
  const snap = useFly((s) => s.snap);
  const theme = THEMES[useFly((s) => s.gfx.theme)];
  const bars: [string, number, string][] = [
    ["HS ←", snap.hs?.left ?? 0, theme.left], ["HS →", snap.hs?.right ?? 0, theme.right],
    ["VS ↑", snap.hs?.up ?? 0, theme.up], ["VS ↓", snap.hs?.down ?? 0, theme.down],
    ["LPLC2", Math.min(1, (snap.looming ?? 0) * 0.8), theme.loom], ["GF", snap.gf ?? 0, theme.gf],
  ];
  return (
    <div className="fly-brainhud pointer-events-none absolute inset-x-3 bottom-3">
      <div className="fly-glass grid grid-cols-6 gap-1.5 p-2">
        {bars.map(([label, v, c]) => (
          <div key={label} className="flex flex-col items-center gap-1">
            <div className="relative h-8 w-full overflow-hidden rounded-[4px] bg-white/[0.04]">
              <div className="absolute inset-x-0 bottom-0 transition-[height] duration-150" style={{ height: `${Math.min(1, v * 2) * 100}%`, background: `linear-gradient(to top, ${c}, transparent)` }} />
            </div>
            <span className="whitespace-nowrap font-mono text-[9px]" style={{ color: c }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ full screen

let usingApi = false; // we asked the browser for full screen (so leaving it closes our view)

/** Show scenes full screen: the browser's real full screen when it allows it, else a fixed overlay (same look).
 *  Must be called from a click (browsers only grant full screen to a user gesture). */
export function enterFlyFull(view: FullView) {
  useFly.setState({ full: view, settingsOpen: false });
  const root = document.documentElement;
  if (!document.fullscreenElement && root.requestFullscreen) {
    root.requestFullscreen({ navigationUI: "hide" }).then(() => (usingApi = true), () => (usingApi = false));
  }
}

export function exitFlyFull() {
  useFly.setState({ full: null });
  if (usingApi && document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
  usingApi = false;
}

const VIEW_NAME: Record<FullView, string> = { brain: "Brain", keyboard: "Keyboard", both: "Both" };
const LAYOUTS: [FullLayout, string][] = [["side", "Side by side"], ["inset", "Brain big"], ["stacked", "Stacked"]];

function MiniSelect<T extends string>({ value, options, onChange, label }: { value: T; options: [T, string][]; onChange: (v: T) => void; label: string }) {
  return (
    <select className="fly-mini" value={value} aria-label={label} title={label} onChange={(e) => onChange(e.target.value as T)}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

/** One 3D scene with its title, quick controls and readout: a wing beside the panel, or a full-screen pane. */
function ScenePane({ kind, variant, className }: { kind: SceneKind; variant: "wing" | "full" | "inset"; className?: string }) {
  const hud = useFly((s) => s.gfx.hud);
  const showFps = useFly((s) => s.gfx.showFps);
  const cam = useFly((s) => (kind === "brain" ? s.gfx.camBrain : s.gfx.camKeys));
  const form = useFly((s) => s.gfx.brainForm);
  const look = useFly((s) => s.gfx.fly);
  const setGfx = useFly((s) => s.setGfx);
  const [fps, setFps] = useState<[number, string]>([0, ""]);
  const onFps = useCallback((f: number, t: string) => setFps([f, t]), []);
  const brain = kind === "brain";
  const setCam = (v: CameraMode) => setGfx(brain ? { camBrain: v } : { camKeys: v });
  const formHint = BRAIN_FORMS.find((f) => f[0] === form)?.[2];
  return (
    <section className={clsx("fly-pane min-h-0 min-w-0 overflow-hidden", variant === "wing" ? "absolute inset-0" : "relative", className)} data-variant={variant}
      aria-label={brain ? "The fly's brain, live" : "The fly at the keyboard"}>
      <FlyCanvas key={kind} kind={kind} onFps={onFps} />
      <header className="fly-pane-head pointer-events-none absolute inset-x-3 top-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="engrave !text-[8.5px] !text-ink-3">{brain ? "Visual circuit · live" : "Descending neurons → keys"}</div>
          <div className="truncate font-display text-[15px] font-[640] text-ink-1" title={brain ? formHint : undefined}>
            {brain ? "Inside the fly's brain" : "The fly at the keyboard"}
          </div>
        </div>
        <div className="pointer-events-auto flex flex-wrap items-center justify-end gap-1.5">
          {showFps && <span className="fly-glass px-2 py-1 font-mono text-[10px] tabular-nums text-ink-2">{fps[0]} fps · {fps[1]}</span>}
          {brain ? (
            <MiniSelect label="Brain view: how the circuit is drawn" value={form} onChange={(brainForm) => setGfx({ brainForm })}
              options={BRAIN_FORMS.map(([v, l]) => [v, l])} />
          ) : (
            <MiniSelect label="Fly look" value={look} onChange={(fly) => setGfx({ fly })}
              options={[["wild", "Wild"], ["golden", "Gold"], ["chrome", "Chrome"], ["ghost", "Ghost"]]} />
          )}
          {variant === "wing" && <MiniSelect label="Camera angle" value={cam} onChange={setCam} options={CAMERAS} />}
          {variant === "wing" && (
            <button className="fly-mini-btn" onClick={() => enterFlyFull(kind)} title={`Full screen: ${brain ? "the brain" : "the keyboard"}`} aria-label="Full screen">
              <Maximize2 size={13} />
            </button>
          )}
        </div>
      </header>
      {variant !== "wing" && (
        <div className="fly-cambar pointer-events-auto absolute left-1/2 top-14 -translate-x-1/2" role="radiogroup" aria-label="Camera angle">
          {CAMERAS.map(([v, l]) => (
            <button key={v} role="radio" aria-checked={cam === v} data-on={cam === v} onClick={() => setCam(v)}
              title={v === "cinematic" ? "The camera cuts and glides between angles by itself" : `${l} view`}>{l}</button>
          ))}
        </div>
      )}
      {hud && variant !== "inset" && (brain ? <BrainHud /> : <KeyHud />)}
      {hud && variant === "inset" && !brain && <KeyHud compact />}
    </section>
  );
}

/** Full screen: one scene, or "Both" (brain, the live panel, keyboard) in a choice of layouts. */
function FlyFull() {
  const view = useFly((s) => s.full);
  const layout = useFly((s) => s.gfx.fullLayout);
  const swap = useFly((s) => s.gfx.swap);
  const snap = useFly((s) => s.snap);
  const setGfx = useFly((s) => s.setGfx);
  const [idle, setIdle] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // leaving the browser's full screen (Esc, F11…) closes the view; in the overlay fallback, Esc does
    const onFs = () => {
      if (!document.fullscreenElement && usingApi) {
        usingApi = false;
        useFly.setState({ full: null });
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (useFly.getState().settingsOpen) return; // the settings popover closes first
      e.stopPropagation();
      exitFlyFull();
    };
    document.addEventListener("fullscreenchange", onFs);
    window.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("fullscreenchange", onFs);
      window.removeEventListener("keydown", onKey, true);
    };
  }, []);

  useEffect(() => {
    // the controls fade away while you watch; any movement brings them back
    let t: ReturnType<typeof setTimeout>;
    const wake = () => {
      setIdle(false);
      clearTimeout(t);
      t = setTimeout(() => setIdle(true), 2800);
    };
    wake();
    const el = ref.current;
    el?.addEventListener("pointermove", wake);
    el?.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    return () => {
      clearTimeout(t);
      el?.removeEventListener("pointermove", wake);
      el?.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
    };
  }, []);

  if (!view) return null;
  const name = appMeta(snap.app)?.name ?? snap.app;
  const both = view === "both";
  return createPortal(
    <div ref={ref} className="fly-full" data-view={view} data-layout={both ? layout : "single"} data-swap={swap} data-idle={idle}
      role="dialog" aria-modal="true" aria-label="Fly view, full screen">
      <header className="fly-full-bar">
        <span className="fly-glass flex items-center gap-2 px-3 py-1.5 text-[12px]">
          <Bug size={14} className="text-ember" />
          <b className="font-[600] text-ink-1">{!snap.active ? "The fly has stopped" : snap.driving === false ? "You took over" : "A fruit fly is playing"}</b>
          {name && <span className="hidden text-ink-3 md:inline">· {name}</span>}
        </span>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <div className="fly-seg" role="radiogroup" aria-label="What to show">
            {(["brain", "both", "keyboard"] as FullView[]).map((v) => (
              <button key={v} role="radio" aria-checked={view === v} data-on={view === v} onClick={() => useFly.setState({ full: v })}>{VIEW_NAME[v]}</button>
            ))}
          </div>
          {both && (
            <div className="fly-seg" role="radiogroup" aria-label="Layout">
              {LAYOUTS.map(([v, l]) => (
                <button key={v} role="radio" aria-checked={layout === v} data-on={layout === v} onClick={() => setGfx({ fullLayout: v })}>{l}</button>
              ))}
            </div>
          )}
        </div>
        <button className="key !h-8" onClick={exitFlyFull} title="Leave full screen (Esc)">
          <Minimize2 size={14} /> <span className="hidden sm:inline">Exit</span> <kbd className="fly-kbd">Esc</kbd>
        </button>
      </header>
      <div className="fly-full-body">
        {view !== "keyboard" && <ScenePane kind="brain" variant="full" className="fly-full-brain" />}
        {both && (
          <div className="fly-full-panel">
            <div className="bezel fly-full-bezel">
              <span className="screw left-[7px] top-[7px]" />
              <span className="screw right-[7px] top-[7px]" />
              <span className="screw bottom-[7px] left-[7px]" />
              <span className="screw bottom-[7px] right-[7px]" />
              <div className="relative h-full w-full"><LedPanel crisp lookSwitch={false} /></div>
            </div>
          </div>
        )}
        {view !== "brain" && <ScenePane kind="keyboard" variant={both && layout === "inset" ? "inset" : "full"} className="fly-full-keys" />}
      </div>
    </div>,
    document.body,
  );
}

// ------------------------------------------------------------------ wings beside the panel

/** The glowing bar between a wing and the panel: drag to give one wing more room (the other gets less; the
 *  panel keeps its size). Double-click resets; arrow keys nudge. */
function WingSplitter({ side }: { side: "left" | "right" }) {
  const [drag, setDrag] = useState(false);
  const start = useRef<{ x: number; mine: number; total: number } | null>(null);
  const measure = (el: HTMLElement) => {
    const row = el.parentElement;
    const l = row?.querySelector<HTMLElement>(":scope > .fly-wing-l");
    const r = row?.querySelector<HTMLElement>(":scope > .fly-wing-r");
    if (!l || !r) return null;
    const wl = l.getBoundingClientRect().width, wr = r.getBoundingClientRect().width;
    return { mine: side === "left" ? wl : wr, total: wl + wr };
  };
  const set = (mine: number, total: number) => {
    const min = Math.min(220, total * 0.25);
    const m = Math.max(min, Math.min(total - min, mine));
    const wMine = (m / total) * 2, wOther = 2 - wMine;
    useFly.getState().setGfx(side === "left" ? { wingL: wMine, wingR: wOther } : { wingR: wMine, wingL: wOther });
  };
  return (
    <div className={clsx("fly-split", side === "left" ? "fly-split-l" : "fly-split-r")} data-drag={drag}
      role="separator" aria-orientation="vertical" tabIndex={0}
      aria-label={side === "left" ? "Left 3D view width" : "Right 3D view width"}
      title="Drag to resize the 3D views · double-click to make them equal"
      onDoubleClick={() => useFly.getState().setGfx({ wingL: 1, wingR: 1 })}
      onKeyDown={(e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const m = measure(e.currentTarget);
        if (!m) return;
        const dx = (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 80 : 24);
        set(m.mine + (side === "left" ? dx : -dx), m.total);
      }}
      onPointerDown={(e) => {
        const m = measure(e.currentTarget);
        if (!m) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        start.current = { x: e.clientX, ...m };
        setDrag(true);
      }}
      onPointerMove={(e) => {
        const s = start.current;
        if (!s) return;
        const dx = e.clientX - s.x;
        set(s.mine + (side === "left" ? dx : -dx), s.total);
      }}
      onPointerUp={() => { start.current = null; setDrag(false); }}
      onPointerCancel={() => { start.current = null; setDrag(false); }}>
      <span />
    </div>
  );
}

/** One side of the Fly view: a 3D scene beside the panel. Slides in from its edge; a glowing bar between it and
 *  the panel resizes it. While a scene is full screen the wing rests (no renderer of its own). */
export function FlyWing({ side }: { side: "left" | "right" }) {
  const swap = useFly((s) => s.gfx.swap);
  const weight = useFly((s) => (side === "left" ? s.gfx.wingL : s.gfx.wingR));
  const full = useFly((s) => s.full);
  const kind: SceneKind = (side === "left") !== swap ? "brain" : "keyboard";
  const wing = (
    <div className={clsx("fly-wing relative min-h-0 min-w-0", side === "left" ? "fly-wing-l" : "fly-wing-r")} style={{ flex: `${weight} 1 0%` }}>
      {full ? (
        <div className="absolute inset-0 grid place-items-center p-4 text-center">
          <div className="flex flex-col items-center gap-2 text-[12px] text-ink-3">
            <Maximize2 size={18} className="text-ink-4" />
            Showing full screen
            <button className="key !h-8" onClick={exitFlyFull}><Minimize2 size={13} /> Back here</button>
          </div>
        </div>
      ) : (
        <ScenePane kind={kind} variant="wing" />
      )}
    </div>
  );
  const split = <WingSplitter side={side} />;
  return side === "left" ? <>{wing}{split}</> : <>{split}{wing}</>;
}

/** Above the panel while the Fly view is open: who is playing, settings, full screen, and the way out. */
export function FlyBar() {
  const snap = useFly((s) => s.snap);
  const open = useFly((s) => s.settingsOpen);
  const full = useFly((s) => s.full);
  const set = useFly((s) => s.set);
  const name = appMeta(snap.app)?.name ?? snap.app;
  useEffect(() => {
    loadBrainConfig().catch(() => undefined); // the scope draws the spike threshold; older engines: no tuning
  }, []);
  return (
    <div className="fly-bar relative z-20 flex items-center gap-2">
      <span className="fly-glass flex items-center gap-2 px-3 py-1.5 text-[12px]">
        <Bug size={14} className="text-ember" />
        <b className="font-[600] text-ink-1">{snap.driving === false ? "You took over" : "A fruit fly is playing"}</b>
        <span className="hidden text-ink-3 lg:inline">· {name}</span>
      </span>
      <button className="key !h-8" onClick={() => set({ settingsOpen: !open })} aria-expanded={open} title="Graphics, brain view and the fly's brain settings">
        <Settings2 size={14} /> <span className="hidden lg:inline">Graphics</span>
      </button>
      <button className="key !h-8" onClick={() => enterFlyFull("both")} title="Full screen: the brain, the panel and the keyboard together">
        <Maximize2 size={14} /> <span className="hidden lg:inline">Full screen</span>
      </button>
      {flyCanPilot(snap.app) && (
        <button className="key !h-8" onClick={flyHandBack} title="Take the game back from the fly; it goes back to roaming the screen">
          <Hand size={14} /> <span className="hidden lg:inline">Take back</span>
        </button>
      )}
      <button className="key !h-8" onClick={closeFlyView} title="Close the Fly view and bring the side panels back">
        <PanelLeftOpen size={14} /> <span className="hidden lg:inline">Panels</span>
      </button>
      {open && !full && <FlySettings onClose={() => set({ settingsOpen: false })} />}
      {full && <FlyFull />}
    </div>
  );
}

// ------------------------------------------------------------------ settings popover

function Seg<T extends string | number>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="fly-seg" role="radiogroup">
      {options.map(([v, label]) => (
        <button key={String(v)} role="radio" aria-checked={value === v} data-on={value === v} onClick={() => onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

function Line({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 py-1.5">
      <div className="min-w-[120px] flex-1">
        <div className="text-[12.5px] font-[560] text-ink-1">{label}</div>
        {hint && <div className="text-[11px] leading-snug text-ink-3">{hint}</div>}
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

type Tab = "graphics" | "scene" | "fly" | "brain" | "layout";

/** Everything about how the Fly view looks (persisted per browser), and the fly's brain itself (on the engine). */
function FlySettings({ onClose }: { onClose: () => void }) {
  const g = useFly((s) => s.gfx);
  const setGfx = useFly((s) => s.setGfx);
  const [tab, setTab] = useState<Tab>("graphics");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as HTMLElement).closest(".fly-bar")) onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [onClose]);
  return (
    <div ref={ref} className="fly-settings surface absolute left-1/2 top-11 z-30 w-[min(420px,calc(100vw-32px))] -translate-x-1/2 animate-rise p-3" role="dialog" aria-label="Fly view settings">
      <div className="mb-2 flex items-center gap-2">
        <Gauge size={15} className="text-ember" />
        <div className="flex-1 font-display text-[14px] font-[640]">Fly view</div>
        {tab !== "brain" && <button className="key !h-7 !px-2" onClick={() => setGfx(DEFAULT_GFX)} title="Reset every Fly view setting"><RotateCcw size={13} /></button>}
        <button className="key !h-7 !px-2" onClick={onClose} aria-label="Close"><X size={13} /></button>
      </div>
      <Seg value={tab} onChange={setTab} options={[["graphics", "Graphics"], ["scene", "Scene"], ["fly", "Fly & keys"], ["brain", "Brain"], ["layout", "Layout"]]} />
      <div className="mt-2 max-h-[min(60vh,540px)] divide-y divide-line overflow-y-auto pr-1">
        {tab === "graphics" && (
          <>
            <Line label="Quality" hint="Auto adjusts to keep it smooth on this computer">
              <Seg value={g.quality} onChange={(quality) => setGfx({ quality })} options={[["auto", "Auto"], ["low", "Low"], ["balanced", "Mid"], ["high", "High"], ["ultra", "Ultra"]]} />
            </Line>
            <Line label="Frame rate cap" hint="Lower saves battery and heat">
              <Seg value={g.fpsCap} onChange={(fpsCap) => setGfx({ fpsCap })} options={[[30, "30"], [60, "60"], [0, "Max"]]} />
            </Line>
            <Line label="Bloom glow"><Toggle on={g.bloom} onChange={(bloom) => setGfx({ bloom })} label="Bloom glow" /></Line>
            {g.bloom && <Line label="Glow strength"><Slider value={g.bloomStrength} min={0.2} max={2.5} step={0.05} width={140} onCommit={(bloomStrength) => setGfx({ bloomStrength })} /></Line>}
            <Line label="Particles" hint="Neurons, signals, sparks and dust"><Slider value={g.particles} min={0} max={1.5} step={0.05} width={140} onCommit={(particles) => setGfx({ particles })} /></Line>
            <Line label="Shadows" hint="High and Ultra only"><Toggle on={g.shadows} onChange={(shadows) => setGfx({ shadows })} label="Shadows" /></Line>
            <Line label="Show frame rate"><Toggle on={g.showFps} onChange={(showFps) => setGfx({ showFps })} label="Show frame rate" /></Line>
          </>
        )}
        {tab === "scene" && (
          <>
            <div className="py-2">
              <div className="text-[12.5px] font-[560] text-ink-1">Brain view</div>
              <div className="mb-2 text-[11px] leading-snug text-ink-3">How the circuit is drawn. Every view is the same live brain.</div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {BRAIN_FORMS.map(([id, name, hint]) => (
                  <button key={id} className="fly-form" data-on={g.brainForm === id} onClick={() => setGfx({ brainForm: id })} aria-pressed={g.brainForm === id}>
                    <b>{name}</b>
                    <span>{hint}</span>
                  </button>
                ))}
              </div>
            </div>
            <Line label="Colour theme">
              <div className="flex flex-wrap justify-end gap-1.5">
                {Object.entries(THEMES).map(([id, t]) => (
                  <button key={id} className="fly-swatch" data-on={g.theme === id} onClick={() => setGfx({ theme: id as FlyGfx["theme"] })} title={t.name}
                    style={{ background: `linear-gradient(135deg, ${t.eye}, ${t.loom} 55%, ${t.gf})` }} aria-label={t.name} />
                ))}
              </div>
            </Line>
            <Line label="Brain camera" hint="Drag to orbit, scroll to zoom. Cinematic cuts between angles by itself">
              <Seg value={g.camBrain} onChange={(camBrain) => setGfx({ camBrain })} options={CAMERAS} />
            </Line>
            <Line label="Keyboard camera">
              <Seg value={g.camKeys} onChange={(camKeys) => setGfx({ camKeys })} options={CAMERAS} />
            </Line>
            <Line label="Auto-rotate" hint="Orbit camera only; off when your system asks for less motion"><Toggle on={g.autoRotate} onChange={(autoRotate) => setGfx({ autoRotate })} label="Auto-rotate" /></Line>
            {g.autoRotate && <Line label="Rotate speed"><Slider value={g.rotateSpeed} min={0.1} max={2} step={0.05} width={140} onCommit={(rotateSpeed) => setGfx({ rotateSpeed })} /></Line>}
            <Line label="Synapses and wiring"><Toggle on={g.trails} onChange={(trails) => setGfx({ trails })} label="Wiring" /></Line>
            {g.brainForm === "tower" && <Line label="Layer spacing"><Slider value={g.brainSpread} min={0.7} max={1.4} step={0.05} width={140} onCommit={(brainSpread) => setGfx({ brainSpread })} /></Line>}
            <Line label="Neuron labels"><Toggle on={g.labels} onChange={(labels) => setGfx({ labels })} label="Labels" /></Line>
          </>
        )}
        {tab === "fly" && (
          <>
            <Line label="Fly">
              <Seg value={g.fly} onChange={(fly) => setGfx({ fly })} options={[["wild", "Wild"], ["golden", "Gold"], ["chrome", "Chrome"], ["ghost", "Ghost"]]} />
            </Line>
            <Line label="Fly size"><Slider value={g.flySize} min={0.7} max={1.4} step={0.05} width={140} onCommit={(flySize) => setGfx({ flySize })} /></Line>
            <Line label="Iridescent wings"><Toggle on={g.wingShimmer} onChange={(wingShimmer) => setGfx({ wingShimmer })} label="Iridescent wings" /></Line>
            <Line label="Keyboard">
              <Seg value={g.board} onChange={(board) => setGfx({ board })} options={[["midnight", "Midnight"], ["rgb", "RGB"], ["retro", "Retro"], ["glass", "Glass"]]} />
            </Line>
            <Line label="Keystroke log and stats"><Toggle on={g.hud} onChange={(hud) => setGfx({ hud })} label="Keystroke log" /></Line>
          </>
        )}
        {tab === "brain" && <BrainTuning />}
        {tab === "layout" && (
          <>
            <Line label="Open automatically" hint="When a fly starts playing, close the side panels and show its brain">
              <Toggle on={g.autoOpen} onChange={(autoOpen) => setGfx({ autoOpen })} label="Open automatically" />
            </Line>
            <Line label="Swap sides" hint="Keyboard on the left, brain on the right"><Toggle on={g.swap} onChange={(swap) => setGfx({ swap })} label="Swap sides" /></Line>
            <Line label="View widths" hint="Or drag the glowing bars beside the panel">
              <button className="key !h-7" disabled={g.wingL === 1 && g.wingR === 1} onClick={() => setGfx({ wingL: 1, wingR: 1 })}>Equal</button>
            </Line>
            <Line label="Full screen" hint="Brain, keyboard, or both with the live panel between them">
              <div className="flex gap-1.5">
                {(["brain", "both", "keyboard"] as FullView[]).map((v) => (
                  <button key={v} className="key !h-7" onClick={() => enterFlyFull(v)}><Maximize2 size={12} /> {VIEW_NAME[v]}</button>
                ))}
              </div>
            </Line>
            <Line label="“Both” layout">
              <Seg value={g.fullLayout} onChange={(fullLayout) => setGfx({ fullLayout })} options={LAYOUTS} />
            </Line>
            <Line label="Roaming fly" hint="A fly wanders the screen; click it and it takes over the game"><Toggle on={g.roam} onChange={(roam) => setGfx({ roam })} label="Roaming fly" /></Line>
          </>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the fly's brain (engine: /api/fly/config)

type Knob = { k: Exclude<keyof BrainConfig, "preset">; label: string; hint: string; min: number; max: number; step: number };
const KNOBS: [string, Knob[]][] = [
  ["Senses", [
    { k: "phototaxis", label: "Drawn to light", hint: "How hard it turns towards bright things", min: 0, max: 1, step: 0.01 },
    { k: "looming", label: "Fear of looming things", hint: "How strongly it feels something rushing at it (LPLC2)", min: 0, max: 3, step: 0.05 },
    { k: "motion", label: "Follows motion", hint: "How much sweeping motion steers it (HS/VS cells)", min: 0, max: 3, step: 0.05 },
    { k: "lure", label: "Smell for the goal", hint: "How strongly the game's goal pulls it in", min: 0, max: 3, step: 0.05 },
  ]],
  ["Reflexes", [
    { k: "escape", label: "Escape reflex", hint: "Giant-fibre sensitivity: how easily it jumps away (key A)", min: 0, max: 3, step: 0.05 },
  ]],
  ["Neurons", [
    { k: "threshold", label: "Trigger point", hint: "How much push a neuron needs before it presses a key", min: 0.3, max: 3, step: 0.05 },
    { k: "leak", label: "Memory", hint: "How much of its drive carries over from one moment to the next", min: 0.3, max: 0.99, step: 0.01 },
    { k: "refractory", label: "Rest after a press", hint: "Steps a neuron waits after each spike", min: 0, max: 10, step: 1 },
    { k: "noise", label: "Jumpiness (noise)", hint: "Random twitches. 0 = perfectly predictable", min: 0, max: 0.5, step: 0.01 },
  ]],
];

/** Tune the brain the fly plays with: presets and plain-language sliders, applied live on the engine. */
function BrainTuning() {
  const [cfg, setCfg] = useState<BrainConfig | null>(() => useFly.getState().brainCfg);
  const [presets, setPresets] = useState<BrainPreset[]>([]);
  const [state, setState] = useState<"loading" | "ok" | "old" | "offline">("loading");

  const load = useCallback(() => {
    setState("loading");
    Promise.all([loadBrainConfig(), loadBrainPresets().catch(() => [] as BrainPreset[])])
      .then(([c, p]) => {
        setCfg(c);
        setPresets(Array.isArray(p) ? p : []);
        setState("ok");
      })
      .catch((e) => setState(e instanceof OldEngine ? "old" : "offline"));
  }, []);
  useEffect(load, [load]);

  const patch = async (p: Partial<BrainConfig>) => {
    if (cfg) setCfg({ ...cfg, ...p }); // optimistic: the slider stays where it was let go
    try {
      setCfg(await patchBrainConfig(p));
    } catch (e) {
      if (e instanceof OldEngine) setState("old");
      else toast(`Couldn't change the fly's brain: ${e instanceof Error ? e.message : e}`, "error");
    }
  };

  if (state === "old")
    return (
      <div className="flex items-start gap-3 py-3 text-[12px] text-ink-2">
        <Brain size={18} className="mt-0.5 shrink-0 text-ink-3" />
        <div>
          <div className="font-[560] text-ink-1">Needs a newer engine</div>
          <div className="text-ink-3">This engine can't tune the fly's brain yet. Update DeskDot and restart it, then come back here.</div>
          <button className="key mt-2 !h-7" onClick={load}><RefreshCw size={12} /> Check again</button>
        </div>
      </div>
    );
  if (state === "offline" || (state === "loading" && !cfg))
    return (
      <div className="flex items-center gap-3 py-3 text-[12px] text-ink-3">
        {state === "loading" ? <span className="skeleton h-4 w-40 rounded" /> : <>Can't reach the engine. <button className="key !h-7" onClick={load}><RefreshCw size={12} /> Retry</button></>}
      </div>
    );
  if (!cfg) return null;
  const defaults = presets.find((p) => p.id === "default")?.config;
  return (
    <>
      <div className="py-2">
        <div className="text-[12.5px] font-[560] text-ink-1">Personality</div>
        <div className="mb-2 text-[11px] leading-snug text-ink-3">Changes apply at once to every game the fly plays.</div>
        <div className="flex flex-wrap gap-1.5">
          {presets.map((p) => (
            <button key={p.id} className="fly-chip-btn" data-on={cfg.preset === p.id} title={p.description}
              onClick={() => patch({ ...p.config, preset: p.id })}>{p.name}</button>
          ))}
          {cfg.preset && !presets.some((p) => p.id === cfg.preset) && <span className="fly-chip-btn" data-on>Custom</span>}
          {!presets.length && <span className="text-[11px] text-ink-4">No presets on this engine.</span>}
        </div>
        {presets.find((p) => p.id === cfg.preset)?.description && (
          <div className="mt-1.5 text-[11px] text-ink-3">{presets.find((p) => p.id === cfg.preset)!.description}</div>
        )}
      </div>
      {KNOBS.map(([group, knobs]) => (
        <div key={group} className="py-1">
          <div className="engrave pb-0.5 pt-1.5">{group}</div>
          {knobs.map((n) => (
            <Line key={n.k} label={n.label} hint={n.hint}>
              <Slider value={cfg[n.k]} min={n.min} max={n.max} step={n.step} width={120} onCommit={(v) => patch({ [n.k]: v })} />
            </Line>
          ))}
        </div>
      ))}
      <div className="flex items-center justify-between py-2.5">
        <span className="text-[11px] text-ink-3">Back to the brain as modelled</span>
        <button className="key !h-7" onClick={() => patch(defaults ? { ...defaults, preset: "default" } : { preset: "default", ...BRAIN_DEFAULTS })}>
          <RotateCcw size={12} /> Reset brain
        </button>
      </div>
    </>
  );
}

const BRAIN_DEFAULTS: Omit<BrainConfig, "preset"> = {
  phototaxis: 0.3, looming: 1, motion: 1, leak: 0.8, threshold: 1, refractory: 2, noise: 0.06, escape: 1, lure: 1,
};
