import { LayoutGrid, ListMusic, MonitorPlay, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AiCreator } from "./components/AiCreator";
import { Boot } from "./components/Boot";
import { CoinDrop } from "./components/CoinDrop";
import { RoamingFly } from "./components/RoamingFly";
import { FlyToggle, RoamSign } from "./components/FlyToggle";
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
import { flyPlayingNow, toggleFly } from "./lib/flyControl";
import { useCasinoView } from "./components/casino/state";
import { usePhone } from "./lib/useMedia";

function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.("input, textarea, select, [contenteditable]");
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
      if (k === "f" && !painting) return void toggleFly(flyPlayingNow()); // the fruit fly plays / hands back
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

/** Bottom right, under the settings panel: let the fly play / take back, and the flies-allowed sign. */
function FlyDock() {
  return (
    <div className="surface flex shrink-0 items-center justify-between gap-2 px-2.5 py-2">
      <RoamSign />
      <FlyToggle picker up className="min-w-0 [&>.flybtn]:max-w-full" />
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

/** Phones: a slim "now playing" strip (the live panel + its name) at the top of the Apps and Presets tabs. */
function MiniPreview() {
  const cur = useStore((s) => s.state?.engine.current?.app);
  const power = useStore((s) => s.state?.settings.power ?? true);
  const set = useStore((s) => s.set);
  useStore((s) => s.meta);
  const meta = appMeta(cur);
  return (
    <button onClick={() => set({ mobileTab: "panel" })} className="mini-now" aria-label={`Now showing ${meta?.name ?? "nothing"} — back to the panel`}>
      <span className={`overflow-hidden rounded-[5px] bg-black transition-opacity ${power ? "" : "opacity-20"}`}><LedPanel size={40} glow={false} /></span>
      <span className="min-w-0 flex-1">
        <span className="engrave block !text-[7.5px] !text-ink-3">Now showing</span>
        <span className="block truncate text-[14px] font-[620]">{meta?.name ?? "—"}</span>
      </span>
      <Icon name="maximize-2" size={14} className="text-ink-3" />
    </button>
  );
}

const TABS: [MobileTab, string, React.ReactNode][] = [
  ["panel", "Panel", <MonitorPlay size={20} />],
  ["apps", "Apps", <LayoutGrid size={20} />],
  ["play", "Presets", <ListMusic size={20} />],
  ["tune", "Settings", <SlidersHorizontal size={20} />],
];

/** Phones: the bottom tab bar (thumb zone) — a lit pill behind the active icon, labels always shown. */
function TabBar() {
  const tab = useStore((s) => s.mobileTab);
  const running = useStore((s) => s.state?.engine.mode === "playlist");
  const set = useStore((s) => s.set);
  const pick = (id: MobileTab) => {
    // tapping the open tab again scrolls it back to the top (the iOS / Android convention)
    if (id === tab) document.querySelector(".phone-scroll")?.scrollTo({ top: 0, behavior: "smooth" });
    else set({ mobileTab: id });
  };
  return (
    <nav className="tabbar" aria-label="Sections">
      {TABS.map(([id, label, icon]) => (
        <button key={id} onClick={() => pick(id)} aria-current={tab === id ? "page" : undefined} className="tabbar-btn">
          <span className="tabbar-pill">
            {icon}
            {id === "play" && running && <span className="led absolute right-2 top-0.5 !h-[6px] !w-[6px]" data-on="ok" />}
          </span>
          {label}
        </button>
      ))}
    </nav>
  );
}

/**
 * Phones: one scroll area per tab (no scroll boxes inside cards), sticky tool rows inside it, the tab bar and the
 * home indicator kept clear. The Panel tab sizes the panel to the screen, so it doesn't scroll as a page.
 */
function PhoneLayout() {
  const tab = useStore((s) => s.mobileTab);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 });
  }, [tab]);
  if (tab === "panel")
    return (
      <>
        <div className="phone-panel flex min-h-0 flex-1 flex-col px-3"><Stage /></div>
        <TabBar />
      </>
    );
  return (
    <>
      <div ref={scroller} className="phone-scroll">
        {tab !== "tune" && <MiniPreview />}
        {tab === "apps" && <Library flat />}
        {tab === "play" && <div className="pt-1"><PlaybackSheet /></div>}
        {tab === "tune" && <Inspector flat />}
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
  const casino = useCasinoView(); // a casino game is on the panel: the drawers close and the casino wings open
  const fly = useFlyView() && !casino; // a fruit fly is playing: the side drawers close and its brain fills their space
  const shut = fly || casino;

  return (
    <div className="noise flex h-full flex-col">
      <div className="app-shell flex min-h-0 flex-1 flex-col">
      <TopBar />
      {phone ? (
        <PhoneLayout />
      ) : (
        <>
          <div className="flex min-h-0 flex-1 px-3 pb-3 md:gap-1">
            <div className="drawer drawer-l hidden min-h-0 shrink-0 md:flex md:flex-col" data-closed={shut} style={{ width: shut ? 0 : libraryWidth }} aria-hidden={shut}>
              <div className="flex min-h-0 flex-1 flex-col" style={{ width: libraryWidth }}><Library /></div>
            </div>
            {!shut && <Splitter title="Library width" onReset={() => prefs({ libraryWidth: 300 })}
              onDrag={(dx) => prefs({ libraryWidth: clamp(useStore.getState().libraryWidth + dx, 220, LIBRARY_MAX) })} />}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              <Stage fly={fly} />
            </div>
            {!shut && <Splitter title="Settings panel width" className="hidden xl:block" onReset={() => prefs({ inspectorWidth: 340 })}
              onDrag={(dx) => prefs({ inspectorWidth: clamp(useStore.getState().inspectorWidth - dx, 300, INSPECTOR_MAX) })} />}
            <div className="drawer drawer-r hidden min-h-0 shrink-0 xl:flex xl:flex-col" data-closed={shut} style={{ width: shut ? 0 : inspectorWidth }} aria-hidden={shut}>
              <div className="flex min-h-0 flex-1 flex-col gap-2" style={{ width: inspectorWidth }}>
                <Inspector fill />
                <FlyDock />
              </div>
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
      <CoinDrop />
      <Boot />
    </div>
  );
}
