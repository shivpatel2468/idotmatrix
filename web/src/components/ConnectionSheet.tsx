import { AlertTriangle, Bluetooth, Check, Circle, Globe, Laptop, Loader2, MonitorSmartphone, RefreshCw, Search, Smartphone, Unplug, X } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "../lib/api";
import { openSettings, toast, useStore } from "../lib/store";
import type { DeviceInfo, HandoverBrief, HandoverPeer } from "../lib/types";
import { Sheet } from "./Sheet";
import { Picker } from "./Picker";

/*
 * The Connection sheet (docs/STUDIO_UI.md "Connection"): what the panel is connected to, where, how well, and the
 * one thing to do next. Opened from the top bar's status pill (and `#connection` in the URL, which the web app links
 * to when DeskDot on this computer holds the panel). Engine facts come from `state.device` (device/base.py
 * DeviceInfo, reasons from device/diagnose.py); in the browser app the page host adds its own (window.deskdotWeb,
 * web/webapp/host.js): the remembered panel, "pick it again", and whether DeskDot on this computer has it.
 *
 * Hand-over (ADR 0015): every DeskDot nearby (this computer, the phone app, a browser tab) with who holds the panel,
 * one "Use the panel here" button, and the hand-over's live steps. The engine publishes them as `state.handover`; in
 * the browser app the page host builds the same shape from DeskDot on this computer (`deskdotWeb.handover`).
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
  handover?: HandoverBrief | null;
};
type WebHost = {
  state(): WebLink;
  pick?(): Promise<void>;
  probeDesktop?(): Promise<DesktopProbe>;
  useHere?(force?: boolean): Promise<void>;
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

export function summarize(dev: DeviceInfo | undefined, web?: WebLink | null, ho?: HandoverBrief | null): Summary {
  if (!dev) return { tone: "warn", label: "Starting up…", title: "Starting up…", action: null };
  const name = dev.name ?? "your panel";
  const progress = ho?.progress && !ho.progress.done ? ho.progress : null;
  if (progress) return { tone: "warn", label: "Moving here…", title: "Bringing the panel here…", action: null };
  if (!dev.link_enabled && ho?.moved_to)
    return { tone: undefined, label: `On ${ho.moved_to.name}`, title: `Panel moved to ${ho.moved_to.name}`, action: "connect" };
  if (!dev.link_enabled)
    return { tone: undefined, label: "Released", title: "Panel released — other apps can use it", action: "connect" };
  if (dev.status !== "connected" && ho?.holder && !ho.holder.me)
    return { tone: undefined, label: `On ${ho.holder.name}`, title: `${ho.holder.name} has the panel`, action: "connect" };
  if (dev.status !== "connected" && dev.reason === "recovering")
    return { tone: "warn", label: "Recovering…", title: "Recovering the link", action: "retry" };
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
  const engineHo = useStore((s) => s.state?.handover);
  const web = useWebLink();
  const ho = dev?.kind === "web" ? (web?.handover ?? null) : (engineHo ?? null);
  return { dev, web, ho, ...summarize(dev, web, ho) };
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

const KIND_ICON: Record<string, typeof Laptop> = { ble: Laptop, sim: Laptop, android: Smartphone, web: Globe };

function peerStatus(p: HandoverPeer): string {
  if (p.holding) return p.panel ? `has the panel (${p.panel})` : "has the panel";
  if (p.online) return "nearby";
  return p.ago != null && p.ago < 7200 ? `last seen ${ago(p.ago)}` : "not seen lately";
}

function StepIcon({ state }: { state: string }) {
  if (state === "done") return <Check size={13} className="text-ok" />;
  if (state === "active") return <Loader2 size={13} className="animate-spin text-info" />;
  if (state === "failed") return <X size={13} className="text-bad" />;
  return <Circle size={10} className="text-ink-4" />;
}

/** Someone asked to pair with this DeskDot: shown even while the sheet is closed (the user must Allow it here). */
function PairPrompt({ ho, floating }: { ho: HandoverBrief; floating?: boolean }) {
  const req = ho.pair_requests[0];
  if (!req) return null;
  const answer = (allow: boolean) => () => void api.handover.answer(req.id, allow).catch(() => undefined);
  return (
    <section
      className={
        floating
          ? "fixed bottom-4 right-4 z-50 w-[min(360px,calc(100vw-2rem))] rounded-xl border border-info/40 bg-chassis-1 p-3 text-[12.5px] shadow-xl"
          : "rounded-xl border border-info/40 bg-info/10 p-3 text-[12.5px]"
      }
    >
      <p className="text-ink-1">
        <b>{req.name}</b> wants to pair with this DeskDot, so the two can hand the panel to each other.
      </p>
      <p className="mt-1 text-ink-2">
        Check that {req.name} shows the same code: <b className="font-mono text-[14px] text-ink-1">{req.code}</b>
      </p>
      <div className="mt-2.5 flex gap-2">
        <button className="key key-ember" onClick={answer(true)}>Allow</button>
        <button className="key key-ghost" onClick={answer(false)}>Don't allow</button>
      </div>
    </section>
  );
}

/** Every DeskDot nearby and who holds the panel (ADR 0015). */
function Nearby({ ho, dev, web }: { ho: HandoverBrief; dev: DeviceInfo; web: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  const meHolds = dev.status === "connected";
  const pairing = Object.fromEntries(ho.pairing.map((p) => [p.id, p]));
  const pair = (id: string) => async () => {
    setBusy(id);
    try {
      const r = await api.handover.pair(id);
      toast(`Confirm on the other device: code ${r.code}`, "info");
    } catch {
      /* toasted */
    } finally {
      setBusy(null);
    }
  };
  const MeIcon = KIND_ICON[dev.kind] ?? Laptop;
  return (
    <section className="qs-card">
      <div className="mb-1.5 text-[12px] font-[620] uppercase tracking-wide text-ink-3">DeskDot nearby</div>
      <div className="flex items-center gap-2.5 py-1.5 text-[12.5px]">
        <MeIcon size={14} className="shrink-0 text-ink-3" />
        <span className="min-w-0 flex-1 truncate text-ink-1">
          {ho.me.name} <span className="text-ink-3">(this one)</span>
        </span>
        <span className={meHolds ? "text-ok" : "text-ink-3"}>{meHolds ? "has the panel" : "—"}</span>
      </div>
      {ho.peers.map((p) => {
        const Icon = KIND_ICON[p.kind] ?? Laptop;
        const out = pairing[p.id];
        return (
          <div key={p.id} className="flex items-center gap-2.5 border-t border-line py-1.5 text-[12.5px]">
            <Icon size={14} className={`shrink-0 ${p.online ? "text-ink-2" : "text-ink-4"}`} />
            <span className={`min-w-0 flex-1 truncate ${p.online ? "text-ink-1" : "text-ink-3"}`}>{p.name}</span>
            {out && out.status === "pending" ? (
              <span className="text-info">confirm on {p.name}: <b className="font-mono">{out.code}</b></span>
            ) : (
              <span className={p.holding ? "text-ok" : "text-ink-3"}>{peerStatus(p)}</span>
            )}
            {!web && !p.paired && p.online && p.kind !== "web" && !(out && out.status === "pending") && (
              <button className="key !px-2 !py-0.5 text-[11.5px]" disabled={busy === p.id} onClick={pair(p.id)}
                title="Pair once so the two DeskDots can hand the panel to each other">
                Pair
              </button>
            )}
          </div>
        );
      })}
      {ho.peers.length === 0 && (
        <p className="border-t border-line pt-1.5 text-[12px] text-ink-3">
          {web
            ? "No DeskDot found on this computer."
            : ho.enabled
              ? "No other DeskDot found on this network yet (they appear within a few seconds when they're on the same Wi-Fi)."
              : "Finding other DeskDots is off."}
        </p>
      )}
      {!ho.holder && ho.probable && !meHolds && (
        <p className="border-t border-line pt-1.5 text-[12px] text-ink-3">
          Nobody nearby says they have the panel. It was last with <b className="text-ink-2">{ho.probable.name}</b> ({ago(ho.probable.ago)}).
        </p>
      )}
    </section>
  );
}

/** "Asking <device> to let go → Released → Waiting for the panel → Connected", live. */
function Progress({ ho, onForce }: { ho: HandoverBrief; onForce: () => void }) {
  const pr = ho.progress;
  if (!pr) return null;
  return (
    <section className={`rounded-xl border p-3 text-[12.5px] ${pr.error ? "border-bad/30 bg-bad/10" : "border-line bg-chassis-0"}`}>
      <ol className="space-y-1">
        {pr.steps.map((s) => (
          <li key={s.id} className={`flex items-center gap-2 ${s.state === "todo" ? "text-ink-3" : "text-ink-1"}`}>
            <span className="flex w-4 justify-center"><StepIcon state={s.state} /></span>
            {s.label}
          </li>
        ))}
      </ol>
      {pr.error && <p className="mt-2 text-ink-1">{pr.error}</p>}
      {pr.error && pr.can_force && (
        <button className="key mt-2" onClick={onForce} title="Waits for the panel to be free, then connects. Nothing is cut off mid-transfer.">
          Try anyway
        </button>
      )}
    </section>
  );
}

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
  const { dev, web, ho, tone, title, action } = useConnection();
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

  if (!isOpen) return ho && ho.pair_requests.length && dev?.kind !== "web" ? <PairPrompt ho={ho} floating /> : null;
  const desktop = probe ?? web?.desktop ?? null;
  const host = webHost();
  const connected = dev?.status === "connected";
  const isWeb = dev?.kind === "web";
  // "Use the panel here" goes through the hand-over when there is one: it asks whoever has the panel to let go first
  const take = (force = false) =>
    isWeb ? (host?.useHere ? host.useHere(force) : api.link(true)) : ho ? api.handover.take(force) : api.link(true);
  const moving = !!(ho?.progress && !ho.progress.done);

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
    connect: { label: ho?.moved_to ? "Take it back" : "Use the panel here", icon: Bluetooth, go: run(() => take()) },
    // pick() must run inside the click (Web Bluetooth's user gesture): no await before it
    pick: { label: "Pick panel", icon: Search, go: () => void host?.pick?.() },
    retry: { label: "Reconnect now", icon: RefreshCw, go: run(() => api.reconnect(true)) },
  };
  const p = action ? primary[action] : null;
  const [where, WhereIcon] = dev ? WHERE[dev.kind] : WHERE.ble;
  const problem = !connected && dev?.link_enabled && !moving && (dev?.hint || dev?.last_error);

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

        {ho && dev && ho.pair_requests.length > 0 && !isWeb && <PairPrompt ho={ho} />}

        {ho && <Progress ho={ho} onForce={run(() => take(true))} />}

        {problem && (
          <section className="flex gap-2.5 rounded-xl border border-warn/30 bg-warn/10 p-3 text-[12.5px] text-ink-2">
            <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" />
            <div className="min-w-0">
              {dev?.hint && <p className="text-ink-1">{dev.hint}</p>}
              {dev?.last_error && dev.last_error !== dev.hint && <p className="mt-1 break-words font-mono text-[10.5px] text-ink-3">{dev.last_error}</p>}
            </div>
          </section>
        )}

        {ho && dev && <Nearby ho={ho} dev={dev} web={isWeb} />}

        {isWeb && desktop && !desktop.running && (
          <p className="px-1 text-[12px] text-ink-3">
            Panel on your phone's DeskDot? This page can't reach the phone over the network (browsers block an https page
            from talking to local devices), so open DeskDot on the phone, press <b className="text-ink-2">Release the panel</b>,
            then Reconnect now here. With DeskDot running on this computer, it asks the phone for you.
          </p>
        )}

        {desktop && (desktop.running || desktop.error) && !ho && (
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
            <button className="key key-ember" disabled={busy || moving} onClick={p.go}>
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
              DeskDot finishes what it is sending, disconnects cleanly and <b className="text-ink-1">stops reconnecting</b> until
              you press Use the panel here. The panel shows its blinking pairing screen until the other app (the iDotMatrix
              phone app, the web app or another DeskDot) connects. Another DeskDot can also take it with its own Use the panel
              here — no need to release it first.
            </p>
            <div className="mt-2.5 flex gap-2">
              <button className="key" onClick={run(async () => { await api.link(false); setConfirmRelease(false); toast("Panel released — other apps can connect now", "info"); })}>
                Release the panel
              </button>
              <button className="key key-ghost" onClick={() => setConfirmRelease(false)}>Cancel</button>
            </div>
          </section>
        )}

        {ho && !isWeb && (
          <label className="flex items-center gap-2 px-1 text-[12px] text-ink-3" title="DeskDots on the same Wi-Fi find each other so you can move the panel with one button. Only on private networks; nothing leaves your network.">
            <input type="checkbox" checked={ho.enabled} onChange={(e) => void api.handover.setEnabled(e.target.checked).catch(() => undefined)} />
            Find other DeskDots on this network
          </label>
        )}

        <button className="key key-ghost !px-0 text-ink-3" onClick={() => { closeConnection(); openSettings("device"); }}>
          Device settings & link statistics
        </button>
      </div>
    </Sheet>
  );
}
