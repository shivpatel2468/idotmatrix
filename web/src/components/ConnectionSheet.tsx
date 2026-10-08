import { AlertTriangle, Bluetooth, Laptop, MonitorSmartphone, RefreshCw, Search, Unplug } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "../lib/api";
import { openSettings, toast, useStore } from "../lib/store";
import type { DeviceInfo } from "../lib/types";
import { Sheet } from "./Sheet";
import { Picker } from "./Picker";

/*
 * The Connection sheet (docs/STUDIO_UI.md "Connection"): what the panel is connected to, where, how well, and the
 * one thing to do next. Opened from the top bar's status pill (and `#connection` in the URL, which the web app links
 * to when DeskDot on this computer holds the panel). Engine facts come from `state.device` (device/base.py
 * DeviceInfo, reasons from device/diagnose.py); in the browser app the page host adds its own (window.deskdotWeb,
 * web/webapp/host.js): the remembered panel, "pick it again", and whether DeskDot on this computer has it.
 */

// ------------------------------------------------------------------ open / close (no global store change needed)
let open = false;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
export function openConnection() {
  open = true;
  emit();
}
function closeConnection() {
  open = false;
  emit();
  if (location.hash === "#connection") history.replaceState(null, "", location.pathname + location.search);
}
const useOpen = () => useSyncExternalStore((f) => (subs.add(f), () => subs.delete(f)), () => open);

// ------------------------------------------------------------------ the browser app's page host (optional)
type DesktopProbe = { running: boolean; holding: boolean | null; panel: string | null; url: string; error?: string };
type WebLink = {
  engine: string;
  link: "idle" | "needs-user" | "connecting" | "connected" | "error";
  detail: string;
  step?: string;
  panel?: string | null;
  packet: number;
  packetChoice?: number | null;
  bluetooth: boolean;
  needsPick?: boolean;
  desktop?: DesktopProbe | null;
};
type WebHost = {
  state(): WebLink;
  pick?(): Promise<void>;
  probeDesktop?(): Promise<DesktopProbe>;
  attachStudio?(): void;
  setPacket?(n: number | null): void;
};
const webHost = (): WebHost | undefined => (window as unknown as { deskdotWeb?: WebHost }).deskdotWeb;

function useWebLink(): WebLink | null {
  const [s, setS] = useState<WebLink | null>(() => webHost()?.state() ?? null);
  useEffect(() => {
    const host = webHost();
    if (!host) return;
    host.attachStudio?.(); // the studio's pill takes over from the page's floating one
    const on = () => setS({ ...host.state() });
    window.addEventListener("deskdot-web", on);
    on();
    return () => window.removeEventListener("deskdot-web", on);
  }, []);
  return s;
}

// ------------------------------------------------------------------ one summary for the pill and the sheet
export type Summary = {
  tone: "ok" | "warn" | "bad" | undefined;
  label: string; // pill text: "IDM-1234", "Connecting…", "Not connected", "In use elsewhere"…
  title: string; // the sheet's headline
  action: "connect" | "pick" | "retry" | null; // the one obvious next step
};

export function summarize(dev: DeviceInfo | undefined, web?: WebLink | null): Summary {
  if (!dev) return { tone: "warn", label: "Starting up…", title: "Starting up…", action: null };
  const name = dev.name ?? "your panel";
  if (!dev.link_enabled)
    return { tone: undefined, label: "Released", title: "Panel released — other apps can use it", action: "connect" };
  if (dev.status === "connected") return { tone: "ok", label: dev.name ?? "Connected", title: `Connected to ${name}`, action: null };
  if (dev.kind === "web" && (web?.needsPick || dev.reason === "needs_user" || dev.reason === "permission"))
    return { tone: "warn", label: "Pick your panel", title: "Pick your panel to connect", action: "pick" };
  if (web?.desktop?.holding) return { tone: "bad", label: "In use elsewhere", title: "Your panel is connected to DeskDot on this computer", action: "retry" };
  if (dev.status === "connecting" || dev.status === "scanning")
    return { tone: "warn", label: dev.status === "scanning" ? "Looking for panel…" : "Connecting…", title: dev.status === "scanning" ? "Looking for your panel…" : `Connecting to ${name}…`, action: "retry" };
  if (dev.reason === "busy") return { tone: "bad", label: "In use elsewhere", title: "The panel seems to be in use by another app", action: "retry" };
  if (dev.reason === "bluetooth_off") return { tone: "bad", label: "Bluetooth is off", title: "Bluetooth is off", action: "retry" };
  if (dev.reason === "link_lost") return { tone: "warn", label: "Reconnecting…", title: "Link lost — reconnecting", action: "retry" };
  return { tone: dev.status === "error" ? "bad" : "warn", label: "Not connected", title: dev.reason === "not_found" ? "Can't find the panel" : "Not connected", action: "retry" };
}

/** The pill's state, shared by the top bar (desktop and phone). */
export function useConnection() {
  const dev = useStore((s) => s.state?.device);
  const web = useWebLink();
  return { dev, web, ...summarize(dev, web) };
}

// ------------------------------------------------------------------ helpers
function useNow(on: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!on) return;
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, [on]);
  return now;
}

function ago(s: number): string {
  if (s < 5) return "just now";
  if (s < 90) return `${Math.round(s)} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

function span(s: number): string {
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function signal(rssi: number | null | undefined): string | null {
  if (rssi == null) return null;
  const q = rssi >= -65 ? "Strong" : rssi >= -80 ? "OK" : "Weak — move the panel closer";
  return `${q} (${rssi} dBm)`;
}

const WHERE: Record<DeviceInfo["kind"], [string, typeof Laptop]> = {
  ble: ["DeskDot on this computer, over Bluetooth", Laptop],
  web: ["This browser tab, over Web Bluetooth", MonitorSmartphone],
  android: ["The DeskDot Android app", MonitorSmartphone],
  sim: ["A simulated panel (no hardware)", Laptop],
};

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5 text-[12.5px]">
      <span className="w-28 shrink-0 text-ink-3">{k}</span>
      <span className="min-w-0 flex-1 text-ink-1">{v}</span>
    </div>
  );
}

// ------------------------------------------------------------------ the sheet
export function ConnectionSheet() {
  const isOpen = useOpen();
  const { dev, web, tone, title, action } = useConnection();
  const now = useNow(isOpen);
  const [confirmRelease, setConfirmRelease] = useState(false);
  const [busy, setBusy] = useState(false);
  const [probe, setProbe] = useState<DesktopProbe | null>(null);

  useEffect(() => {
    if (location.hash === "#connection") openConnection();
  }, []);
  useEffect(() => {
    if (!isOpen) setConfirmRelease(false);
  }, [isOpen]);

  if (!isOpen) return null;
  const desktop = probe ?? web?.desktop ?? null;
  const host = webHost();
  const connected = dev?.status === "connected";

  const run = (fn: () => Promise<unknown>) => async () => {
    setBusy(true);
    try {
      await fn();
    } catch {
      /* api.req already toasted */
    } finally {
      setBusy(false);
    }
  };
  const primary = {
    connect: { label: "Use the panel here", icon: Bluetooth, go: run(() => api.link(true)) },
    // pick() must run inside the click (Web Bluetooth's user gesture): no await before it
    pick: { label: "Pick panel", icon: Search, go: () => void host?.pick?.() },
    retry: { label: "Reconnect now", icon: RefreshCw, go: run(() => api.reconnect(true)) },
  };
  const p = action ? primary[action] : null;
  const [where, WhereIcon] = dev ? WHERE[dev.kind] : WHERE.ble;
  const problem = !connected && dev?.link_enabled && (dev?.hint || dev?.last_error);

  return (
    <Sheet open onClose={closeConnection} title="Connection">
      <div className="space-y-3">
        <section className="qs-card">
          <div className="flex items-start gap-3">
            <span className="led mt-1.5 shrink-0" data-on={tone} />
            <div className="min-w-0 flex-1">
              <div className="text-[15px] font-[620] leading-snug">{title}</div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[12px] text-ink-3">
                <WhereIcon size={12} className="shrink-0" /> {where}
              </div>
            </div>
          </div>
          {dev && (
            <div className="mt-3 border-t border-line pt-2">
              <Row k="Panel" v={<>{dev.name ?? "not found yet"} <span className="font-mono text-[10.5px] text-ink-3">{dev.kind === "web" ? "" : dev.address ?? ""}</span></>} />
              {signal(dev.rssi) && <Row k="Signal" v={signal(dev.rssi)} />}
              {connected && dev.connected_since && <Row k="Connected for" v={span(now - dev.connected_since)} />}
              {connected && <Row k="Link" v={`${dev.link_fps.toFixed(1)} frames/s · ${dev.mtu ?? "—"}-byte packets`} />}
              {!connected && dev.last_seen && <Row k="Last seen" v={ago(now - dev.last_seen)} />}
              {!connected && dev.link_enabled && (dev.attempts ?? 0) > 0 && (
                <Row k="Attempts" v={`${dev.attempts}${dev.retry_at && dev.retry_at > now ? ` · next try in ${Math.ceil(dev.retry_at - now)} s` : " · trying now"}`} />
              )}
              {web?.step && !connected && <Row k="Step" v={web.step} />}
            </div>
          )}
        </section>

        {problem && (
          <section className="flex gap-2.5 rounded-xl border border-warn/30 bg-warn/10 p-3 text-[12.5px] text-ink-2">
            <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" />
            <div className="min-w-0">
              {dev?.hint && <p className="text-ink-1">{dev.hint}</p>}
              {dev?.last_error && dev.last_error !== dev.hint && <p className="mt-1 break-words font-mono text-[10.5px] text-ink-3">{dev.last_error}</p>}
            </div>
          </section>
        )}

        {desktop && (desktop.running || desktop.error) && (
          <section className="flex gap-2.5 rounded-xl border border-line bg-chassis-0 p-3 text-[12.5px] text-ink-2">
            <Laptop size={15} className="mt-0.5 shrink-0 text-info" />
            <div className="min-w-0">
              {desktop.running ? (
                <>
                  <p className="text-ink-1">
                    {desktop.holding ? `Your panel${desktop.panel ? ` (${desktop.panel})` : ""} is connected to DeskDot on this computer.` : "DeskDot is running on this computer."}
                  </p>
                  <p className="mt-1">
                    Open it there and press <b className="text-ink-1">Release the panel</b> (or quit DeskDot), then press Reconnect now here.{" "}
                    <a className="text-info underline" href={desktop.url} target="_blank" rel="noreferrer">Open DeskDot on this computer</a>
                  </p>
                </>
              ) : (
                <p>{desktop.error}</p>
              )}
            </div>
          </section>
        )}

        <div className="flex flex-wrap gap-2">
          {p && (
            <button className="key key-ember" disabled={busy} onClick={p.go}>
              <p.icon size={13} /> {p.label}
            </button>
          )}
          {dev?.kind === "web" && !connected && host?.probeDesktop && (
            <button className="key" onClick={async () => setProbe(await host.probeDesktop!())}>
              <Laptop size={13} /> Is DeskDot open on this computer?
            </button>
          )}
          {dev?.kind === "web" && connected && host?.pick && (
            <button className="key" onClick={() => void host.pick!()} title="Choose a different IDM-… panel">
              <Search size={13} /> Pick another panel
            </button>
          )}
          {connected && (
            <button className="key" disabled={busy} title="Drop the link and connect again (the panel blinks its pairing icon for a moment)" onClick={run(() => api.reconnect())}>
              <RefreshCw size={13} /> Reconnect
            </button>
          )}
          {dev?.link_enabled && dev.kind !== "sim" && !confirmRelease && (
            <button className="key key-ghost" onClick={() => setConfirmRelease(true)}>
              <Unplug size={13} /> Release the panel…
            </button>
          )}
        </div>

        {dev?.kind === "web" && host?.setPacket && (
          <label className="flex items-center gap-2 text-[12px] text-ink-3" title="Bytes per Bluetooth write. Browsers don't report the link's limit; if frames look broken, try a smaller size.">
            Packet size
            <Picker label="Packet size" size="sm" className="!w-40" value={String(web?.packetChoice ?? "")}
              onChange={(v) => {
                host.setPacket!(v ? +v : null);
                toast("Packet size changes on the next connect — press Reconnect", "info");
              }}
              options={[
                { value: "", label: `Auto (${web?.packet ?? "?"} B)`, hint: "What the link reports" },
                { value: "20", label: "20 B", hint: "Safest" },
                { value: "182", label: "182 B" },
                { value: "244", label: "244 B" },
                { value: "512", label: "512 B", hint: "Fastest" },
              ]} />
          </label>
        )}

        {confirmRelease && (
          <section className="rounded-xl border border-warn/30 bg-warn/10 p-3 text-[12.5px] text-ink-2">
            <p className="text-ink-1">Let another app use the panel?</p>
            <p className="mt-1">
              DeskDot disconnects and <b className="text-ink-1">stops reconnecting</b> until you press Use the panel here. The
              panel shows its blinking pairing screen until the other app (the iDotMatrix phone app, the web app or
              another DeskDot) connects.
            </p>
            <div className="mt-2.5 flex gap-2">
              <button className="key" onClick={run(async () => { await api.link(false); setConfirmRelease(false); toast("Panel released — other apps can connect now", "info"); })}>
                Release the panel
              </button>
              <button className="key key-ghost" onClick={() => setConfirmRelease(false)}>Cancel</button>
            </div>
          </section>
        )}

        <button className="key key-ghost !px-0 text-ink-3" onClick={() => { closeConnection(); openSettings("device"); }}>
          Device settings & link statistics
        </button>
      </div>
    </Sheet>
  );
}
