import { Bell, Ellipsis, RefreshCw, Search, Settings2, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { openSettings, useStore } from "../lib/store";
import { usePhone } from "../lib/useMedia";
import { useFlyPlaying } from "../lib/flyControl";
import { useFly } from "../lib/fly";
import { Sheet } from "./Sheet";
import { FlyToggle, RoamSign } from "./FlyToggle";
import { NeonMark } from "./NeonMark";
import { SafetySwitch } from "./SafetySwitch";
import { Dices } from "lucide-react";
import { openCasino, rememberCasino, useCasinoApp, useCasinoView } from "./casino/state";

/** The DeskDot logo, centred in the header: LEDs that build and strike like neon (components/NeonMark). */
function Wordmark() {
  const phone = typeof window !== "undefined" && window.innerWidth < 640;
  return (
    <div className="flex shrink-0 justify-center" title="DeskDot studio">
      <NeonMark pitch={phone ? 2.6 : 3.8} />
    </div>
  );
}

/** "Is my panel OK?" in one word, a tone and a hint. */
function usePanelStatus() {
  const dev = useStore((s) => s.state?.device);
  const link = useStore((s) => s.link);
  const released = useStore((s) => s.state?.engine.released ?? false);
  let tone: "ok" | "warn" | "bad" | undefined = "warn";
  let label = "Connecting…";
  let detail = "";
  let retry = false;
  if (link !== "open") {
    label = link === "connecting" ? "Starting up…" : "Studio offline";
    detail = link === "closed" ? "The DeskDot engine isn't running — start it with `uv run deskdot serve`" : "";
  } else if (dev) {
    if (!dev.link_enabled) { tone = undefined; label = "Panel link off"; detail = "Bluetooth link is switched off — open Device settings to connect"; }
    else if (released) { tone = "ok"; label = "Panel on its own"; detail = "The panel runs by itself; show any app to take it back"; }
    else if (dev.status === "connected") { tone = "ok"; label = dev.name ?? "Panel connected"; detail = `Connected · ${dev.link_fps.toFixed(1)} frames/s · ${dev.address ?? ""}`; }
    else if (dev.status === "error") { tone = "bad"; label = "Can't reach panel"; detail = dev.last_error ?? ""; retry = true; }
    else { label = dev.status === "scanning" ? "Looking for panel…" : dev.status === "connecting" ? "Pairing…" : "Not connected"; retry = dev.status === "disconnected"; }
  }
  return { tone, label, detail, retry, sim: dev?.kind === "sim" };
}

/** One pill that answers "is my panel OK?" — click for Device settings. */
function StatusPill() {
  const { tone, label, detail, retry } = usePanelStatus();
  const dev = useStore((s) => s.state?.device);
  return (
    <div className="flex min-w-0 items-center">
      <button onClick={() => openSettings("device")} title={detail || "Device settings"}
        className="flex min-w-0 items-center gap-2.5 rounded-full border border-line bg-chassis-1 py-1.5 pl-3 pr-3 transition hover:border-line-2">
        <span className="led shrink-0" data-on={tone} />
        <span className="max-w-[40vw] truncate text-[12.5px] font-medium sm:max-w-[180px]">{label}</span>
        {dev?.kind === "sim" && <span className="engrave rounded bg-chassis-3 px-1.5 py-0.5 !text-[8px] !text-info" title="Simulated panel">Sim</span>}
      </button>
      {retry && (
        <button className="key key-ghost key-icon ml-1" title="Try to reconnect" aria-label="Reconnect" onClick={() => api.reconnect()}>
          <RefreshCw size={13} />
        </button>
      )}
    </div>
  );
}

function useBrightness() {
  const level = useStore((s) => s.state?.settings.brightness ?? 60);
  const [v, setV] = useState(level);
  const t = useRef<number>(0);
  const dragging = useRef(false);
  useEffect(() => {
    if (!dragging.current) setV(level);
  }, [level]);
  const input = (cls: string) => (
    <input type="range" min={5} max={100} value={v} aria-label="Panel brightness" className={`fader ${cls}`}
      style={{ ["--fill" as string]: `${((v - 5) / 95) * 100}%` }}
      onPointerDown={() => (dragging.current = true)}
      onPointerUp={() => (dragging.current = false)}
      onChange={(e) => {
        const n = +e.target.value;
        setV(n);
        clearTimeout(t.current);
        t.current = window.setTimeout(() => api.settings({ brightness: n }), 90);
      }} />
  );
  return { v, input };
}

/** Inline fader on wide screens; a sun key with a pop-over fader on phones. */
function Brightness() {
  const { v, input } = useBrightness();
  const [open, setOpen] = useState(false);
  return (
    <>
      <label className="hidden items-center gap-2.5 md:flex" title="Panel brightness">
        <Sun size={14} className="text-ink-3" />
        {input("w-24 lg:w-28")}
        <span className="w-7 text-right font-mono text-[11px] tabular-nums text-ink-2">{v}</span>
      </label>
      <div className="relative md:hidden">
        <button className="key key-icon" aria-expanded={open} aria-label={`Brightness ${v}%`} title="Brightness" onClick={() => setOpen((o) => !o)}>
          <Sun size={15} />
        </button>
        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div className="surface absolute right-0 top-11 z-50 flex w-[min(300px,80vw)] items-center gap-3 p-4 animate-rise">
              <Sun size={15} className="shrink-0 text-ink-3" />
              {input("flex-1")}
              <span className="w-8 text-right font-mono text-[12px] tabular-nums text-ink-1">{v}</span>
            </div>
          </>
        )}
      </div>
    </>
  );
}

/** A casino table is on the panel but its casino view was left: the gold way back, next to the panel status. */
function CasinoKey() {
  const app = useCasinoApp();
  const inCasino = useCasinoView();
  const hasCasino = useStore((s) => !!s.meta?.apps.some((a) => a.category === "casino"));
  useEffect(() => {
    if (app) rememberCasino(app); // the key reopens this table later, from any app
  }, [app]);
  if (inCasino || !hasCasino) return null; // in the casino already / no casino
  return (
    <button className="cz-gold shrink-0" onClick={() => void openCasino()} title={app ? "Back to the casino table: house, players and the room" : "Open the casino: the last table goes on the panel"}>
      <Dices size={14} /> Casino
    </button>
  );
}

/** Phones: everything the wide header holds, in a bottom sheet under one "more" key. */
function QuickSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { tone, label, detail, retry, sim } = usePanelStatus();
  const { v, input } = useBrightness();
  const roam = useFly((s) => s.gfx.roam);
  const set = useStore((s) => s.set);
  const go = (fn: () => void) => () => { onClose(); fn(); };
  return (
    <Sheet open={open} onClose={onClose} title="Quick controls">
      <div className="space-y-3">
        <section className="qs-card">
          <div className="flex items-center gap-3">
            <span className="led shrink-0" data-on={tone} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14px] font-[600]">{label}{sim && !/sim/i.test(label) ? " · simulator" : ""}</span>
              {detail && <span className="block truncate text-[11.5px] text-ink-3">{detail}</span>}
            </span>
            {retry && <button className="key key-icon" aria-label="Reconnect" onClick={() => api.reconnect()}><RefreshCw size={14} /></button>}
            <button className="key" onClick={go(() => openSettings("device"))}>Device</button>
          </div>
          <label className="mt-3 flex items-center gap-3" title="Panel brightness">
            <Sun size={16} className="shrink-0 text-ink-3" />
            {input("flex-1")}
            <span className="w-9 text-right font-mono text-[12px] tabular-nums text-ink-1">{v}%</span>
          </label>
          <div className="mt-3 flex items-center gap-3 border-t border-line pt-3">
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-[560]">Panel power</span>
              <span className="block text-[11.5px] text-ink-3">Lift the guard, then press the red button</span>
            </span>
            <SafetySwitch />
          </div>
        </section>
        <section className="qs-card">
          <div className="engrave mb-2.5 !text-[9px] !text-ink-3">Fruit fly</div>
          <FlyToggle picker up className="[&>.flybtn]:!h-12 [&>.flybtn]:w-full [&>.flybtn]:justify-center" />
          <div className="mt-3 flex items-center gap-3">
            <RoamSign />
            <span className="min-w-0 flex-1 text-[12.5px] text-ink-2">{roam ? "The fly roams your screen — tap the sign to spray it away." : "No flies on screen — tap the sign to let it back."}</span>
          </div>
        </section>
        <div className="grid grid-cols-3 gap-2">
          <button className="qs-tile" onClick={go(() => set({ palette: true }))}><Search size={18} />Find</button>
          <button className="qs-tile" onClick={go(() => set({ notifyOpen: true }))}><Bell size={18} />Message</button>
          <button className="qs-tile" onClick={go(() => openSettings("display"))}><Settings2 size={18} />Settings</button>
        </div>
      </div>
    </Sheet>
  );
}

/** The phone header: status dot, the logo, search and one key for the rest (QuickSheet). */
function PhoneTopBar() {
  const { tone, label } = usePanelStatus();
  const set = useStore((s) => s.set);
  const flyOn = useFlyPlaying();
  const power = useStore((s) => s.state?.settings.power ?? true);
  const [more, setMore] = useState(false);
  return (
    <header className="phone-head grid shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-2 px-3">
      <button className="flex min-w-0 items-center gap-2 justify-self-start rounded-full py-2 pr-2" onClick={() => setMore(true)} aria-label={`${label} — quick controls`}>
        <span className="led shrink-0" data-on={power ? tone : "bad"} />
        <span className="max-w-[24vw] truncate text-[11.5px] font-medium text-ink-2">{power ? label : "Panel off"}</span>
      </button>
      <Wordmark />
      <div className="flex items-center justify-end gap-1.5">
        <button onClick={() => set({ palette: true })} className="key key-ghost key-icon" title="Find an app or action" aria-label="Search">
          <Search size={17} />
        </button>
        <button className="key key-icon relative" aria-label="Quick controls: brightness, power, fruit fly, settings" aria-haspopup="dialog" onClick={() => setMore(true)}>
          <Ellipsis size={18} />
          {flyOn && <span className="led absolute -right-0.5 -top-0.5 !h-[7px] !w-[7px]" data-on="ember" />}
        </button>
      </div>
      <QuickSheet open={more} onClose={() => setMore(false)} />
    </header>
  );
}

export function TopBar() {
  const set = useStore((s) => s.set);
  const phone = usePhone();
  if (phone) return <PhoneTopBar />;
  return (
    <header className="grid h-16 shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-2 px-3 sm:gap-3 md:px-5">
      <div className="flex min-w-0 items-center gap-2.5"><StatusPill /><CasinoKey /></div>
      <Wordmark />
      <div className="flex min-w-0 items-center justify-end gap-2 sm:gap-3">
      {/* on wide screens these live under the settings panel (App.tsx FlyDock) */}
      <div className="xl:hidden"><RoamSign /></div>
      <FlyToggle picker compact className="xl:hidden" />
      <button onClick={() => set({ palette: true })} className="key key-ghost hidden lg:inline-flex" title="Find an app or action (Ctrl K)">
        <Search size={13} /> <span className="normal-case tracking-normal">Find anything</span>
        <kbd className="ml-1 rounded bg-chassis-0 px-1.5 py-0.5 text-[9px] text-ink-3">Ctrl K</kbd>
      </button>
      <button onClick={() => set({ palette: true })} className="key key-icon lg:hidden" title="Find an app or action" aria-label="Search">
        <Search size={15} />
      </button>
      <Brightness />
      <button className="key key-icon" title="Settings" aria-label="Settings" onClick={() => openSettings("display")}>
        <Settings2 size={15} />
      </button>
      <SafetySwitch />
      </div>
    </header>
  );
}
