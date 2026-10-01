import clsx from "clsx";
import { Bug, Gauge, PanelLeftOpen, RotateCcw, Settings2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_GFX, FLY_KEYS, type FlyGfx, type FlyKey, KEY_GLYPH, KEY_ROLE, THEMES, closeFlyView, useFly,
} from "../../lib/fly";
import { appMeta } from "../../lib/store";
import { Slider, Toggle } from "../controls";

type SceneKind = "brain" | "keyboard";

/** A three.js view; the scene code (and three.js itself) loads only when the first one mounts. */
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
function KeyHud() {
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
        {presses.slice(-14).map((p) => (
          <span key={p.id} className="fly-chip" style={{ ["--c" as string]: color(p.key) }} title={KEY_ROLE[p.key]}>
            {KEY_GLYPH[p.key]}
          </span>
        ))}
        {!presses.length && <span className="text-[11px] text-ink-4">Waiting for the first spike…</span>}
      </div>
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
    <div className="pointer-events-none absolute inset-x-3 bottom-3">
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

/** One side of the Fly view: a 3D scene with its title and readout. Slides in from its edge. */
export function FlyWing({ side }: { side: "left" | "right" }) {
  const swap = useFly((s) => s.gfx.swap);
  const hud = useFly((s) => s.gfx.hud);
  const showFps = useFly((s) => s.gfx.showFps);
  const [fps, setFps] = useState<[number, string]>([0, ""]);
  const kind: SceneKind = (side === "left") !== swap ? "brain" : "keyboard";
  return (
    <section className={clsx("fly-wing relative min-h-0 min-w-0 flex-1 overflow-hidden", side === "left" ? "fly-wing-l" : "fly-wing-r")}
      aria-label={kind === "brain" ? "The fly's brain, live" : "The fly at the keyboard"}>
      <FlyCanvas key={kind} kind={kind} onFps={(f, t) => setFps([f, t])} />
      <header className="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-2">
        <div>
          <div className="engrave !text-[8.5px] !text-ink-3">{kind === "brain" ? "Visual circuit · live" : "Descending neurons → keys"}</div>
          <div className="font-display text-[15px] font-[640] text-ink-1">{kind === "brain" ? "Inside the fly's brain" : "The fly at the keyboard"}</div>
        </div>
        {showFps && <span className="fly-glass px-2 py-1 font-mono text-[10px] tabular-nums text-ink-2">{fps[0]} fps · {fps[1]}</span>}
      </header>
      {hud && (kind === "keyboard" ? <KeyHud /> : <BrainHud />)}
    </section>
  );
}

/** Above the panel while the Fly view is open: who is playing, settings, and the way out. */
export function FlyBar() {
  const snap = useFly((s) => s.snap);
  const open = useFly((s) => s.settingsOpen);
  const set = useFly((s) => s.set);
  const name = appMeta(snap.app)?.name ?? snap.app;
  return (
    <div className="fly-bar relative z-20 flex items-center gap-2">
      <span className="fly-glass flex items-center gap-2 px-3 py-1.5 text-[12px]">
        <Bug size={14} className="text-ember" />
        <b className="font-[600] text-ink-1">{snap.driving === false ? "You took over" : "A fruit fly is playing"}</b>
        <span className="hidden text-ink-3 lg:inline">· {name}</span>
      </span>
      <button className="key !h-8" onClick={() => set({ settingsOpen: !open })} aria-expanded={open} title="Graphics and Fly view settings">
        <Settings2 size={14} /> <span className="hidden lg:inline">Graphics</span>
      </button>
      <button className="key !h-8" onClick={closeFlyView} title="Close the Fly view and bring the side panels back">
        <PanelLeftOpen size={14} /> <span className="hidden lg:inline">Panels</span>
      </button>
      {open && <FlySettings onClose={() => set({ settingsOpen: false })} />}
    </div>
  );
}

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
      <div className="min-w-[120px]">
        <div className="text-[12.5px] font-[560] text-ink-1">{label}</div>
        {hint && <div className="text-[11px] leading-snug text-ink-3">{hint}</div>}
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

/** Everything about how the Fly view looks, persisted per browser. */
function FlySettings({ onClose }: { onClose: () => void }) {
  const g = useFly((s) => s.gfx);
  const setGfx = useFly((s) => s.setGfx);
  const [tab, setTab] = useState<"graphics" | "scene" | "fly" | "layout">("graphics");
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
    <div ref={ref} className="fly-settings surface absolute left-1/2 top-11 z-30 w-[min(400px,calc(100vw-32px))] -translate-x-1/2 animate-rise p-3" role="dialog" aria-label="Fly view settings">
      <div className="mb-2 flex items-center gap-2">
        <Gauge size={15} className="text-ember" />
        <div className="flex-1 font-display text-[14px] font-[640]">Fly view</div>
        <button className="key !h-7 !px-2" onClick={() => setGfx(DEFAULT_GFX)} title="Reset every Fly view setting"><RotateCcw size={13} /></button>
        <button className="key !h-7 !px-2" onClick={onClose} aria-label="Close"><X size={13} /></button>
      </div>
      <Seg value={tab} onChange={setTab} options={[["graphics", "Graphics"], ["scene", "Scene"], ["fly", "Fly & keys"], ["layout", "Layout"]]} />
      <div className="mt-2 max-h-[min(60vh,520px)] divide-y divide-line overflow-y-auto pr-1">
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
            <Line label="Particles" hint="Signals, sparks and dust"><Slider value={g.particles} min={0} max={1.5} step={0.05} width={140} onCommit={(particles) => setGfx({ particles })} /></Line>
            <Line label="Shadows" hint="High and Ultra only"><Toggle on={g.shadows} onChange={(shadows) => setGfx({ shadows })} label="Shadows" /></Line>
            <Line label="Show frame rate"><Toggle on={g.showFps} onChange={(showFps) => setGfx({ showFps })} label="Show frame rate" /></Line>
          </>
        )}
        {tab === "scene" && (
          <>
            <Line label="Colour theme">
              <div className="flex flex-wrap justify-end gap-1.5">
                {Object.entries(THEMES).map(([id, t]) => (
                  <button key={id} className="fly-swatch" data-on={g.theme === id} onClick={() => setGfx({ theme: id as FlyGfx["theme"] })} title={t.name}
                    style={{ background: `linear-gradient(135deg, ${t.eye}, ${t.loom} 55%, ${t.gf})` }} aria-label={t.name} />
                ))}
              </div>
            </Line>
            <Line label="Camera" hint="Drag to orbit, scroll to zoom">
              <Seg value={g.camera} onChange={(camera) => setGfx({ camera })} options={[["orbit", "Orbit"], ["front", "Front"], ["top", "Top"], ["close", "Close"]]} />
            </Line>
            <Line label="Auto-rotate"><Toggle on={g.autoRotate} onChange={(autoRotate) => setGfx({ autoRotate })} label="Auto-rotate" /></Line>
            {g.autoRotate && <Line label="Rotate speed"><Slider value={g.rotateSpeed} min={0.1} max={2} step={0.05} width={140} onCommit={(rotateSpeed) => setGfx({ rotateSpeed })} /></Line>}
            <Line label="Wiring between layers"><Toggle on={g.trails} onChange={(trails) => setGfx({ trails })} label="Wiring" /></Line>
            <Line label="Layer spacing"><Slider value={g.brainSpread} min={0.7} max={1.4} step={0.05} width={140} onCommit={(brainSpread) => setGfx({ brainSpread })} /></Line>
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
        {tab === "layout" && (
          <>
            <Line label="Open automatically" hint="When a fly starts playing, close the side panels and show its brain">
              <Toggle on={g.autoOpen} onChange={(autoOpen) => setGfx({ autoOpen })} label="Open automatically" />
            </Line>
            <Line label="Swap sides" hint="Keyboard on the left, brain on the right"><Toggle on={g.swap} onChange={(swap) => setGfx({ swap })} label="Swap sides" /></Line>
          </>
        )}
      </div>
    </div>
  );
}
