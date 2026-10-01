import { LayoutGrid, ListMusic, MonitorPlay, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AiCreator } from "./components/AiCreator";
import { Boot } from "./components/Boot";
import { RoamingFly } from "./components/RoamingFly";
import { Inspector } from "./components/Inspector";
import { Library } from "./components/Library";
import { CommandPalette, DropZone, NotifyComposer, Toasts } from "./components/Overlays";
import { SettingsSheet } from "./components/Settings";
import { Icon } from "./components/Icon";
import { LedPanel } from "./components/LedPanel";
import { PlaybackSheet, PlaylistDock } from "./components/PlaylistDock";
import { PlayMode } from "./components/PlayMode";
import { Stage } from "./components/Stage";
import { TopBar } from "./components/TopBar";
import { api, loadPresets } from "./lib/api";
import { INSPECTOR_MAX, LIBRARY_MAX, type MobileTab, appMeta, useStore } from "./lib/store";
import { gameKeyDown, isPlayable } from "./lib/gameInput";
import { connect } from "./lib/ws";
import { startFlyPolling, useFlyView } from "./lib/fly";

function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest("input, textarea, select, [contenteditable]");
      const s = useStore.getState();
      if (s.playMode) return; // Play mode owns the keyboard (components/PlayMode.tsx)
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        s.set({ palette: !s.palette });
        return;
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey || s.palette) return;
      const painting = s.state?.engine.current?.app === "canvas";
      const k = e.key.toLowerCase();
      const current = s.state?.engine.current?.app;
      const cat = s.meta?.apps.find((a) => a.id === current)?.category;
      if (current && (current === "arcade" || cat === "games")) {
        // press on keydown, our own auto-repeat while held (lib/gameInput.ts), release on keyup
        if (gameKeyDown(e, current)) return;
        if (k === "p" && isPlayable(appMeta(current))) return void s.set({ playMode: true });
      }
      if (current === "composer" && k.startsWith("arrow")) return; // Text Studio nudges layers
      if (k === "n") s.set({ notifyOpen: true });
      else if (k === "arrowright") api.playlist("next");
      else if (k === "arrowleft") api.playlist("prev");
      else if (painting && k === "b") s.set({ tool: "pencil" });
      else if (painting && k === "e") s.set({ tool: "eraser" });
      else if (painting && k === "f") s.set({ tool: "fill" });
      else if (painting && k === "i") s.set({ tool: "picker" });
      else if (/^[1-9]$/.test(k)) {
        const app = s.meta?.apps[+k - 1];
        if (app) api.activate(app.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Tablet widths: the inspector slides over from the right. (Phones use the bottom tabs instead.) */
function Drawers() {
  const drawer = useStore((s) => s.drawer);
  const set = useStore((s) => s.set);
  const phone = usePhone();
  useEffect(() => {
    if (phone && drawer) set({ drawer: null, mobileTab: drawer === "library" ? "apps" : "tune" });
  }, [phone, drawer, set]);
  if (!drawer || phone) return null;
  return (
    <div className={drawer === "inspector" ? "xl:hidden" : "md:hidden"}>
      <div className="fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px]" onClick={() => set({ drawer: null })} />
      <div className={`fixed bottom-3 top-3 z-40 flex w-[min(380px,calc(100vw-24px))] animate-rise flex-col ${drawer === "inspector" ? "right-3" : "left-3"}`}
        onKeyDown={(e) => e.key === "Escape" && set({ drawer: null })}>
        {drawer === "inspector" ? <Inspector /> : <Library />}
      </div>
    </div>
  );
}

/** A draggable divider between two columns; reports the pointer's x delta. */
function Splitter({ onDrag, onReset, title, className = "hidden md:block" }: {
  onDrag: (dx: number) => void;
  onReset: () => void;
  title: string;
  className?: string; // visibility per breakpoint (the splitter must be a direct child of the row to get its height)
}) {
  const [drag, setDrag] = useState(false);
  const last = useRef(0);
  return (
    <div className={`splitter ${className}`} data-drag={drag} title={`${title} — drag to resize, double-click to reset`}
      role="separator" aria-orientation="vertical" aria-label={title}
      onDoubleClick={onReset}
      onPointerDown={(e) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        last.current = e.clientX;
        setDrag(true);
      }}
      onPointerMove={(e) => {
        if (!drag) return;
        onDrag(e.clientX - last.current);
        last.current = e.clientX;
      }}
      onPointerUp={() => setDrag(false)}
      onPointerCancel={() => setDrag(false)} />
  );
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function usePhone() {
  const q = "(max-width: 767.98px)";
  const [phone, setPhone] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setPhone(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return phone;
}

/** Phones: the live panel stays in view at the top of every tab. */
function MiniPreview() {
  const cur = useStore((s) => s.state?.engine.current?.app);
  const power = useStore((s) => s.state?.settings.power ?? true);
  const set = useStore((s) => s.set);
  useStore((s) => s.meta);
  const meta = appMeta(cur);
  return (
    <button onClick={() => set({ mobileTab: "panel" })} className="surface flex w-full shrink-0 items-center gap-3 p-2 pr-4 text-left" aria-label="Back to the panel">
      <span className={`overflow-hidden rounded-[6px] bg-black transition-opacity ${power ? "" : "opacity-20"}`}><LedPanel size={72} glow={false} /></span>
      <span className="min-w-0 flex-1">
        <span className="engrave block !text-[8px]">Now showing</span>
        <span className="block truncate font-display text-[16px] font-[640]">{meta?.name ?? "—"}</span>
      </span>
      <Icon name="maximize-2" size={15} className="text-ink-3" />
    </button>
  );
}

const TABS: [MobileTab, string, React.ReactNode][] = [
  ["panel", "Panel", <MonitorPlay size={20} />],
  ["apps", "Apps", <LayoutGrid size={20} />],
  ["play", "Presets", <ListMusic size={20} />],
  ["tune", "Settings", <SlidersHorizontal size={20} />],
];

function TabBar() {
  const tab = useStore((s) => s.mobileTab);
  const running = useStore((s) => s.state?.engine.mode === "playlist");
  const set = useStore((s) => s.set);
  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-chassis-1/95 pb-[env(safe-area-inset-bottom)] backdrop-blur" aria-label="Sections">
      <div className="grid grid-cols-4">
        {TABS.map(([id, label, icon]) => (
          <button key={id} onClick={() => set({ mobileTab: id })} aria-current={tab === id ? "page" : undefined}
            className={`relative flex h-16 flex-col items-center justify-center gap-1 text-[11px] transition ${tab === id ? "text-ember" : "text-ink-3 active:text-ink-1"}`}>
            {tab === id && <span className="absolute top-0 h-[2px] w-10 rounded-full bg-ember shadow-[0_0_10px_var(--color-ember)]" />}
            <span className="relative">
              {icon}
              {id === "play" && running && <span className="led absolute -right-1.5 -top-1 !h-[6px] !w-[6px]" data-on="ok" />}
            </span>
            {label}
          </button>
        ))}
      </div>
    </nav>
  );
}

function PhoneLayout() {
  const tab = useStore((s) => s.mobileTab);
  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 pb-[calc(76px+env(safe-area-inset-bottom))]">
        {tab !== "panel" && <MiniPreview />}
        {tab === "panel" && <div className="flex min-h-0 flex-1 flex-col"><Stage /></div>}
        {tab === "apps" && <Library fill />}
        {tab === "play" && <div className="min-h-0 flex-1 overflow-y-auto pb-2"><PlaybackSheet /></div>}
        {tab === "tune" && <Inspector fill />}
      </div>
      <TabBar />
    </>
  );
}

export default function App() {
  useShortcuts();
  useEffect(() => {
    connect();
    api.meta().then((meta) => useStore.setState({ meta }));
    loadPresets();
    startFlyPolling();
  }, []);
  const libraryWidth = useStore((s) => s.libraryWidth);
  const inspectorWidth = useStore((s) => s.inspectorWidth);
  const prefs = useStore((s) => s.prefs);
  const phone = usePhone();
  const fly = useFlyView(); // a fruit fly is playing: the side drawers close and its brain fills their space

  return (
    <div className="noise flex h-full flex-col">
      <div className="app-shell flex min-h-0 flex-1 flex-col">
      <TopBar />
      {phone ? (
        <PhoneLayout />
      ) : (
        <>
          <div className="flex min-h-0 flex-1 px-3 pb-3 md:gap-1">
            <div className="drawer drawer-l hidden min-h-0 shrink-0 md:flex md:flex-col" data-closed={fly} style={{ width: fly ? 0 : libraryWidth }} aria-hidden={fly}>
              <div className="flex min-h-0 flex-1 flex-col" style={{ width: libraryWidth }}><Library /></div>
            </div>
            {!fly && <Splitter title="Library width" onReset={() => prefs({ libraryWidth: 300 })}
              onDrag={(dx) => prefs({ libraryWidth: clamp(useStore.getState().libraryWidth + dx, 220, LIBRARY_MAX) })} />}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              <Stage fly={fly} />
            </div>
            {!fly && <Splitter title="Settings panel width" className="hidden xl:block" onReset={() => prefs({ inspectorWidth: 340 })}
              onDrag={(dx) => prefs({ inspectorWidth: clamp(useStore.getState().inspectorWidth - dx, 300, INSPECTOR_MAX) })} />}
            <div className="drawer drawer-r hidden min-h-0 shrink-0 xl:flex xl:flex-col" data-closed={fly} style={{ width: fly ? 0 : inspectorWidth }} aria-hidden={fly}>
              <div className="flex min-h-0 flex-1 flex-col" style={{ width: inspectorWidth }}><Inspector fill /></div>
            </div>
          </div>
          <div className="px-3 pb-3">
            <PlaylistDock />
          </div>
        </>
      )}
      </div>
      <Drawers />
      <NotifyComposer />
      <SettingsSheet />
      <AiCreator />
      <PlayMode />
      <CommandPalette />
      <DropZone />
      <Toasts />
      <RoamingFly />
      <Boot />
    </div>
  );
}
