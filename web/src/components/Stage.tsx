import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { Bell, ChevronDown, Gamepad2, Eraser, ImageUp, Paintbrush, PaintBucket, Pipette, Plus, SlidersHorizontal, Sparkles, Trash2, Type, X } from "lucide-react";
import { api } from "../lib/api";
import { EMPTY_MAP, appMeta, inspect, onFrame, toast, type Tool, useStore } from "../lib/store";
import { randomTip } from "../lib/tips";
import { isPlayable, openPlay } from "../lib/gameInput";
import { Icon } from "./Icon";
import { ComposerOverlay, ComposerToolbar } from "./ComposerEditor";
import { LedPanel } from "./LedPanel";
import { MediaPrompt } from "./MediaPrompt";
import { IndicatorHotspots, PlatformStrip } from "./PlatformStrip";
import { FlyBar, FlyWing } from "./fly/FlyView";
import { openFlyView, useFly } from "../lib/fly";
import { FlyToggle } from "./FlyToggle";
import { CasinoStage } from "./casino/CasinoStage";
import { enterCasino, useCasinoApp, useCasinoView } from "./casino/state";

const KIND: Record<string, { label: string; hint: string }> = {
  stream: { label: "Live", hint: "Updates live: frames are sent over Bluetooth as they change" },
  clip: { label: "Plays by itself", hint: "Sent to the panel once as a loop — the panel plays it on its own, perfectly smooth" },
  native: { label: "Built into the panel", hint: "One of the panel's own modes; nothing is streamed" },
};

const human = (k: string) => k.replace(/_/g, " ");

function fmt(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(1);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (v == null) return "—";
  return String(v);
}

function CanvasTools() {
  const tool = useStore((s) => s.tool);
  const brush = useStore((s) => s.brush);
  const recent = useStore((s) => s.recent);
  const palette = useStore((s) => s.meta?.palette ?? EMPTY_MAP);
  const set = useStore((s) => s.set);
  const tools: [Tool, React.ReactNode, string][] = [
    ["pencil", <Paintbrush size={14} />, "Brush (B)"],
    ["eraser", <Eraser size={14} />, "Eraser (E)"],
    ["fill", <PaintBucket size={14} />, "Fill (F)"],
    ["picker", <Pipette size={14} />, "Pick colour (I)"],
  ];
  const swatches = [...new Set([...recent, ...Object.values(palette).filter((c) => c !== "#000000")])].slice(0, 22);
  const pick = (c: string) => set({ brush: c, tool: tool === "eraser" ? "pencil" : tool, recent: [c, ...recent.filter((r) => r !== c)].slice(0, 8) });
  return (
    <div className="surface flex w-full flex-wrap items-center gap-3 p-2.5 animate-rise">
      <div className="seg">
        {tools.map(([id, ic, label]) => (
          <button key={id} data-active={tool === id} title={label} onClick={() => set({ tool: id })} className="!w-9 !flex-none grid place-items-center">
            {ic}
          </button>
        ))}
      </div>
      <label className="relative h-8 w-8 shrink-0 overflow-hidden rounded-[8px] border border-line-2" title="Custom colour" style={{ background: brush }}>
        <input type="color" value={brush} onChange={(e) => pick(e.target.value)} className="absolute inset-0 cursor-pointer opacity-0" />
      </label>
      <div className="flex min-w-0 flex-1 flex-wrap gap-1">
        {swatches.map((c) => (
          <button
            key={c}
            onClick={() => pick(c)}
            title={c}
            className={clsx("h-5 w-5 rounded-[5px] border transition hover:scale-110", brush === c ? "border-white" : "border-black/40")}
            style={{ background: c, boxShadow: brush === c ? `0 0 10px ${c}` : undefined }}
          />
        ))}
      </div>
      <button className="key" onClick={() => api.action("canvas", "clear")}>
        <Trash2 size={13} /> Clear
      </button>
      <button className="key" onClick={() => set({ aiOpen: true })} title="Describe a picture and let AI draw it">
        <Sparkles size={13} /> Draw with AI
      </button>
    </div>
  );
}

/** Largest square that fits the element (the bezel must stay square at every size). */
function useSquare(max = 1400, share = 1) {
  const box = useRef<HTMLDivElement>(null);
  const [side, setSide] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSide(Math.max(200, Math.floor(Math.min(e.contentRect.width * share, e.contentRect.height, max)))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [max, share]);
  return { box, side };
}

/** While an app opens (settings apply, clips bake, the first frame streams) — a scan + a tip. */
function OpeningOverlay() {
  const opening = useStore((s) => s.opening);
  const cur = useStore((s) => s.state?.engine.current);
  const set = useStore((s) => s.set);
  const [tip, setTip] = useState(() => randomTip());
  const name = appMeta(opening?.app)?.name;
  useEffect(() => {
    if (!opening) return;
    setTip(randomTip());
    const give = setTimeout(() => set({ opening: null }), 6000);
    return () => clearTimeout(give);
  }, [opening, set]);
  useEffect(() => {
    if (!opening || cur?.app !== opening.app || cur.baking) return;
    // done once the app is current, not baking, and a fresh frame has arrived
    let first = true;
    const off = onFrame(() => {
      if (first) return void (first = false); // onFrame replays the last frame immediately
      set({ opening: null });
    });
    const t = setTimeout(() => set({ opening: null }), 900);
    return () => {
      off();
      clearTimeout(t);
    };
  }, [opening, cur?.app, cur?.baking, set]);
  if (!opening) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-end bg-black/45 p-[6%] backdrop-blur-[1.5px] animate-rise">
      <div className="opening-scan" />
      <div className="relative flex max-w-[86%] flex-col items-center gap-2 rounded-[12px] border border-line bg-chassis-1/90 px-4 py-3 text-center shadow-2xl">
        <span className="engrave flex items-center gap-2 !text-ember">
          <span className="led" data-on="ember" /> {cur?.baking && cur.app === opening.app ? "Baking loop ·" : "Opening"} {name ?? opening.app}
        </span>
        <span className="text-[12px] leading-snug text-ink-2">{tip}</span>
      </div>
    </div>
  );
}

type Blip = { id: string; callsign?: string; x: number; y: number; alt_ft?: number; speed_kt?: number; type?: string };
type RadarStatus = { count?: number; range_nm?: number; source?: string; blips?: Blip[]; selected?: Record<string, unknown> | null };

/** Flight Radar: clickable blips over the panel preview. */
function RadarOverlay() {
  const status = useStore((s) => s.state?.engine.current?.status) as RadarStatus | undefined;
  const blips = status?.blips ?? [];
  const sel = status?.selected?.id as string | undefined;
  return (
    <div className="absolute inset-0 z-[5]">
      {blips.map((b) => (
        <button key={b.id} title={`${b.callsign ?? b.id}${b.alt_ft ? ` · ${b.alt_ft} ft` : ""}`}
          onClick={() => api.action("radar", sel === b.id ? "clear" : "select", { id: b.id })}
          className={clsx("absolute h-[9%] w-[9%] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 transition",
            sel === b.id ? "border-[#39ff7a] shadow-[0_0_14px_#39ff7a]" : "border-transparent hover:border-[#39ff7a]/70")}
          style={{ left: `${((b.x + 0.5) / 32) * 100}%`, top: `${((b.y + 0.5) / 32) * 100}%` }} />
      ))}
    </div>
  );
}

/** Flight Radar: details of the selected flight. */
function RadarCard() {
  const status = useStore((s) => s.state?.engine.current?.status) as RadarStatus | undefined;
  const sel = status?.selected;
  const route = sel?.route as Record<string, unknown> | string | null | undefined;
  const v = (k: string) => (sel?.[k] ?? null) as unknown;
  const rows: [string, unknown][] = sel && !sel.lost ? [
    ["Callsign", v("callsign")], ["Type", v("type")], ["Registration", v("reg") ?? v("registration")],
    ["Altitude", v("alt_ft") != null ? `${v("alt_ft")} ft` : null], ["Speed", v("speed_kt") != null ? `${v("speed_kt")} kt` : null],
    ["Track", v("track") != null ? `${v("track")}°` : null],
    ["Distance", v("dist_nm") != null ? `${v("dist_nm")} nm @ ${v("bearing_deg")}°` : null],
    ["Squawk", v("squawk")],
  ] : [];
  const place = (x: unknown) => (x && typeof x === "object" ? String((x as Record<string, unknown>).iata ?? (x as Record<string, unknown>).name ?? "") : x ? String(x) : "");
  const routeText = typeof route === "string" ? route
    : route ? [route.airline ? place(route.airline) : "", [place(route.origin), place(route.destination)].filter(Boolean).join(" → ")].filter(Boolean).join(" · ") : null;
  return (
    <div className="surface w-full p-3 text-[12px] animate-rise">
      <div className="flex flex-wrap items-center gap-2">
        <span className="led" data-on="ok" />
        <span className="engrave">Radar</span>
        <span className="font-mono text-ink-2">{status?.count ?? 0} aircraft · {status?.range_nm ?? "?"} nm{status?.source ? ` · ${status.source}` : ""}</span>
        <button className="key ml-auto" onClick={() => api.action("radar", "next")}><Icon name="crosshair" size={13} /> Next</button>
        {sel && <button className="key" title="Clear selection" onClick={() => api.action("radar", "clear")}><X size={13} /></button>}
      </div>
      {!sel && <p className="mt-2 text-ink-3">Click a green blip on the panel to see that flight's details.</p>}
      {sel?.lost ? <p className="mt-2 text-warn">That flight has left the radar.</p> : null}
      {rows.length > 0 && (
        <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
          {routeText && <div className="col-span-full font-display text-[15px] font-[620] text-[#39ff7a]">{routeText}</div>}
          {rows.filter(([, x]) => x != null && x !== "").map(([k, x]) => (
            <div key={k}>
              <div className="engrave !text-[8px]">{k}</div>
              <div className="font-mono text-ink-1">{String(x)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Screen Mirror / Camera: the magnification slider right under the panel. */
function MagnifyBar({ app }: { app: string }) {
  const stored = useStore((s) => s.state?.apps?.[app]?.zoom);
  const [zoom, setZoom] = useState<number>(Number(stored ?? 1));
  useEffect(() => setZoom(Number(stored ?? 1)), [stored]);
  const commit = useRef<ReturnType<typeof setTimeout>>(undefined);
  const change = (z: number) => {
    setZoom(z);
    clearTimeout(commit.current);
    commit.current = setTimeout(() => api.patchSettings(app, { zoom: z }), 120);
  };
  return (
    <div className="surface flex w-full flex-wrap items-center gap-3 px-4 py-2.5 animate-rise">
      <Icon name="zoom-in" size={14} className="text-ink-3" />
      <span className="engrave">Magnify</span>
      <input type="range" min={1} max={8} step={0.1} value={zoom} className="fader min-w-[120px] flex-1"
        style={{ ["--fill" as string]: `${((zoom - 1) / 7) * 100}%` }} onChange={(e) => change(+e.target.value)} />
      <span className="w-11 text-right font-mono text-[12px] text-ink-1">{zoom.toFixed(1)}×</span>
      {[1, 2, 4].map((z) => (
        <button key={z} className="key !px-2" onClick={() => change(z)}>{z}×</button>
      ))}
    </div>
  );
}

/** Everything you can *make* for the panel, in one menu — keeps the top bar calm. */
function CreateMenu() {
  const [open, setOpen] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const set = useStore((s) => s.set);
  const items: [React.ReactNode, string, string, () => void][] = [
    [<Bell size={15} />, "Send a message", "Flash a notification on the panel (N)", () => set({ notifyOpen: true })],
    [<Sparkles size={15} />, "Make with AI", "Describe pixel art or an animation", () => set({ aiOpen: true })],
    [<ImageUp size={15} />, "Show a picture or GIF", "Or drop a file anywhere on the studio", () => file.current?.click()],
    [<Paintbrush size={15} />, "Draw on the panel", "Paint pixels right on the preview", () => api.activate("canvas")],
    [<Type size={15} />, "Write text", "Place and style text in Text Studio", () => api.activate("composer")],
  ];
  return (
    <div className="relative">
      <button className="key" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((o) => !o)}>
        <Plus size={13} /> Create <ChevronDown size={12} className={clsx("transition", open && "rotate-180")} />
      </button>
      <input ref={file} type="file" accept="image/*" hidden onChange={async (e) => {
        const f = e.target.files?.[0];
        e.target.value = "";
        if (!f) return;
        toast(`Uploading ${f.name}…`);
        await api.upload(f, true);
        useStore.setState({ selected: "gallery" });
        toast("On the panel", "ok");
      }} />
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div role="menu" className="surface absolute bottom-full right-0 z-50 mb-2 w-[min(290px,86vw)] p-1.5 animate-rise"
            onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
            {items.map(([ic, label, hint, run]) => (
              <button key={label} role="menuitem" className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-chassis-3 focus:bg-chassis-3"
                onClick={() => { setOpen(false); run(); }}>
                <span className="text-ink-2">{ic}</span>
                <span className="min-w-0">
                  <span className="block text-[13px] text-ink-1">{label}</span>
                  <span className="block truncate text-[11px] text-ink-3">{hint}</span>
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Phones: a one-line "what's rotating" that opens the Play tab. */
function MiniPlayback() {
  const running = useStore((s) => s.state?.engine.mode === "playlist" && !!s.state?.engine.playlist.enabled);
  const activeId = useStore((s) => s.state?.engine.active_preset ?? null);
  const presets = useStore((s) => s.presets);
  const set = useStore((s) => s.set);
  const name = presets?.find((p) => p.id === activeId)?.name ?? "Your playlist";
  return (
    <button onClick={() => set({ mobileTab: "play" })}
      className="surface flex w-full items-center gap-3 px-4 py-3 text-left md:hidden">
      <span className="led" data-on={running ? "ok" : undefined} />
      <span className="min-w-0 flex-1">
        <span className="engrave block !text-[8px]">{running ? "Rotating" : "Presets"}</span>
        <span className="block truncate text-[13.5px] font-[560]">{running ? name : "Play a preset — every game, all pets…"}</span>
      </span>
      <Icon name="chevron-right" size={16} className="text-ink-3" />
    </button>
  );
}

/** The stage: the panel and its tools — or, while a casino game is on the panel, the casino table (casino/). */
export function Stage({ fly = false }: { fly?: boolean }) {
  const casino = useCasinoView();
  if (casino)
    return (
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto overflow-x-hidden px-1 py-1">
        <CasinoStage />
      </main>
    );
  return <StageBody fly={fly} />;
}

function StageBody({ fly = false }: { fly?: boolean }) {
  const casinoApp = useCasinoApp(); // a casino game whose casino view the host left: offer the way back
  const { box, side } = useSquare(1400, fly ? 0.4 : 1);
  const flyLive = useFly((s) => s.snap.active);
  const cur = useStore((s) => s.state?.engine.current);
  const overlay = useStore((s) => s.state?.engine.overlay);
  const power = useStore((s) => s.state?.settings.power ?? true);
  const released = useStore((s) => s.state?.engine.released ?? false);
  useStore((s) => s.meta); // re-render when meta loads
  const meta = appMeta(cur?.app);
  const painting = cur?.app === "canvas";
  const composing = cur?.app === "composer";
  const gaming = cur?.app === "arcade" || meta?.category === "games";
  const playable = isPlayable(meta);
  const radar = cur?.app === "radar";
  const magnify = cur?.app === "mirror" || cur?.app === "camera";
  const status = gaming ? [] : Object.entries(cur?.status ?? {}).filter(([, v]) => v !== null && typeof v !== "object").slice(0, 4);

  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col items-center gap-4 overflow-y-auto px-2 py-1">
      {fly && <FlyBar />}
      <div ref={box} className={clsx("relative flex w-full flex-1 items-center justify-center", fly && "gap-3")} style={{ minHeight: 260 }}>
        {fly && <FlyWing side="left" />}
        <div className="bezel shrink-0 animate-rise" style={{ width: side, height: side }}>
          <span className="screw left-[7px] top-[7px]" />
          <span className="screw right-[7px] top-[7px]" />
          <span className="screw bottom-[7px] left-[7px]" />
          <span className="screw bottom-[7px] right-[7px]" />
          <div className={clsx("relative h-full w-full transition-opacity duration-500", !power && "opacity-15")}>
            <LedPanel paintable={painting} />
            {composing && <ComposerOverlay />}
            {radar && <RadarOverlay />}
            {!painting && !composing && <IndicatorHotspots />}
            <OpeningOverlay />
          </div>
          <span className="engrave absolute bottom-[3px] left-1/2 -translate-x-1/2 whitespace-nowrap !text-[7.5px] !text-ink-4">
            iDotMatrix · 32 × 32 RGB
          </span>
        </div>
        {fly && <FlyWing side="right" />}
        {!fly && casinoApp && (
          <button className="key cz-enter absolute left-2 top-2 hidden md:inline-flex" onClick={enterCasino} title="Back to the casino table: house, players and the room">
            <Icon name="dices" size={14} /> Casino
          </button>
        )}
        {!fly && flyLive && (
          <button className="key key-ember absolute right-2 top-2 hidden md:inline-flex" onClick={openFlyView} title="Watch the fly's brain and the keys it presses, in 3D">
            <Icon name="bug" size={14} /> Fly view
          </button>
        )}
      </div>

      <div className="flex w-full flex-col items-center gap-3" style={{ maxWidth: Math.max(640, side) }}>
      <MediaPrompt />
      {released && (
        <div className="surface flex w-full items-center gap-3 px-4 py-2.5 text-[12.5px] text-ink-2 animate-rise">
          <span className="led" data-on="ok" />
          <span className="flex-1">The panel is running on its own — your computer can sleep. Show any app to take over again.</span>
          <button className="key ml-auto shrink-0" onClick={() => api.takeBack()}>Take it back</button>
        </div>
      )}
      <PlatformStrip />
      {painting && <CanvasTools />}
      {radar && <RadarCard />}
      {magnify && cur && <MagnifyBar app={cur.app} />}
      {composing && <ComposerToolbar />}
      {gaming && (
        <div className="surface flex w-full flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 text-[12.5px] text-ink-2 animate-rise">
          <span className="led" data-on={cur?.status?.player === "you" ? "ok" : "ember"} />
          <span className="min-w-0 flex-1">
            <b className="font-[600] text-ink-1">{cur?.status?.player === "you" ? "You're playing" : cur?.status?.player === "fly" ? "A fruit fly is playing" : "Playing itself"}</b>
            <span className="hidden md:inline"> · <kbd className="kbd">← ↑ → ↓</kbd> or <kbd className="kbd">WASD</kbd> to take over, <kbd className="kbd">Space</kbd> for action</span>
            <span className="md:hidden"> · open Play mode for the game pad</span>
          </span>
          <span className="shrink-0 font-mono text-ink-1">{String(cur?.status?.score ?? 0)} <span className="text-ink-4">/ best {String(cur?.status?.best ?? 0)}</span></span>
          <div className="flex gap-2 max-md:w-full">
            {playable && (
              <button className="key key-ember max-md:!h-12 max-md:flex-1" onClick={() => openPlay()} title="Full-window game view with big controls (P)">
                <Gamepad2 size={15} /> Play
              </button>
            )}
            <FlyToggle className="max-md:min-w-0 max-md:flex-1 [&>.flybtn]:max-md:!h-12 [&>.flybtn]:max-md:w-full [&>.flybtn]:max-md:justify-center" />
          </div>
        </div>
      )}

      <div className="surface flex w-full flex-wrap items-center gap-x-4 gap-y-2.5 px-4 py-3">
        <div className={clsx("flex min-w-0 flex-1 items-center gap-3", !painting && (meta?.actions.length ?? 0) > 0 && "max-sm:basis-full")}>
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[10px] border border-[#7a2a12] bg-ember-deep text-ember">
            <Icon name={meta?.icon ?? "square"} size={17} />
          </span>
          <div className="min-w-0">
            <div className="engrave flex items-center gap-2 whitespace-nowrap !text-[8.5px]">
              Now showing
              {cur && (
                <span title={KIND[cur.kind]?.hint} className="rounded-full border border-line px-1.5 py-px !tracking-[0.12em] !text-ink-3">
                  {cur.baking ? "getting ready…" : KIND[cur.kind]?.label}
                </span>
              )}
            </div>
            <div className="truncate font-display text-[18px] font-[640] tracking-[-0.015em]">{meta?.name ?? (cur ? cur.app : "Nothing yet")}</div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 max-sm:w-full max-sm:[&>*:last-child]:ml-auto">
          {meta && !painting && meta.actions.map((a) => (
            <button key={a.id} className="key" title={a.label} aria-label={a.label} onClick={() => api.action(meta.id, a.id)}>
              <Icon name={a.icon} size={13} />
              <span className="hidden 2xl:inline">{a.label}</span>
            </button>
          ))}
          {cur && (
            <button className="key hidden md:inline-flex xl:hidden" onClick={() => inspect(cur.app)} title="This app's settings">
              <SlidersHorizontal size={13} /> Settings
            </button>
          )}
          <CreateMenu />
        </div>
        {status.length > 0 && (
          <div className="flex w-full min-w-0 flex-wrap gap-1.5">
            {status.map(([k, v]) => (
              <span key={k} className="rounded-md bg-chassis-0 px-2 py-1 font-mono text-[10.5px] text-ink-2">
                <span className="text-ink-4">{human(k)}</span> {fmt(v)}
              </span>
            ))}
          </div>
        )}
        {cur?.error && (
          <div className="w-full rounded-md border border-bad/30 bg-bad/10 px-3 py-2 text-[12px] text-bad">
            <b className="font-[600]">This app hit a problem:</b> <span className="font-mono text-[11px]">{cur.error}</span>
          </div>
        )}
        {overlay && (
          <div className="flex w-full items-center gap-2 rounded-md bg-chassis-0 px-3 py-2 text-[12px]">
            <span className="led" data-on="ember" />
            <span className="engrave !text-ink-2">Message</span>
            <span className="truncate text-ink-1">{overlay.title} {overlay.message}</span>
            <button className="ml-auto text-ink-3 hover:text-ink-1" title="Dismiss" aria-label="Dismiss message" onClick={() => api.dismiss()}>
              <X size={14} />
            </button>
          </div>
        )}
      </div>
      <MiniPlayback />
      </div>
    </main>
  );
}
