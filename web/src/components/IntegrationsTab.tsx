import { useState } from "react";
import { api } from "../lib/api";
import { PLATFORM_LABEL } from "../lib/platform";
import { toast, useStore } from "../lib/store";
import type { EngineState, Indicator, Integrations } from "../lib/types";
import { Row, Slider, Toggle } from "./controls";
import { Icon } from "./Icon";

type St = EngineState;

const DEFAULTS: Integrations = {
  onair: { enabled: false, style: "full", look: "sign", webcam: true, microphone: true, exclude: "" },
  eyebreak: { enabled: false, interval_min: 20, style: "breathe" },
  ntfy: {
    enabled: false, server: "https://ntfy.sh", topics: "", token: "", token_set: false,
    style: "auto", duration: 8, route_prefix: "app-", lifetime: 3600,
  },
  homeassistant: { url: "", token: "", token_set: false },
};

function Section({ id, icon, title, status, children }: {
  id: string; icon: string; title: string; status?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <section id={`set-${id}`} className="scroll-mt-4 rounded-xl border border-line bg-chassis-0/60 p-4">
      <div className="mb-1 flex items-center gap-2">
        <Icon name={icon} size={15} className="text-ember" />
        <h3 className="font-display text-[15px] font-[640] tracking-[-0.01em]">{title}</h3>
        {status && <span className="ml-auto flex items-center gap-2 font-mono text-[10.5px] text-ink-3">{status}</span>}
      </div>
      <div className="divide-y divide-line">{children}</div>
    </section>
  );
}

function Seg<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="seg">
      {options.map(([id, label]) => (
        <button key={id} data-active={value === id} onClick={() => onChange(id)}>{label}</button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------- on air
function OnAirSection({ st, cfg }: { st: St; cfg: Integrations["onair"] }) {
  const save = (p: Partial<Integrations["onair"]>) => api.integration("onair", p);
  const live = st.engine.onair;
  const apps = live ? Object.values(live.apps).flat() : [];
  // the engine's host decides (not this browser's OS): On Air reads the Windows privacy registry
  const meta = useStore((s) => s.meta);
  const win = meta?.features?.onair ?? meta?.platform === undefined;
  const host = meta?.platform ? PLATFORM_LABEL[meta.platform] : "this OS";
  return (
    <Section icon="radio" id="onair" title="On Air" status={
      <><span className="led" data-on={live?.active ? "bad" : cfg.enabled ? "ok" : undefined} />
        {live?.active ? `live · ${apps.join(", ")}` : cfg.enabled ? "watching" : "off"}</>
    }>
      <Row label="Show when I'm on a call" hint={win
        ? "Lights up while any app uses your webcam or microphone (Windows privacy registry, checked every 2 s)."
        : `Needs Windows: DeskDot runs on ${host}, which doesn't say when the camera / microphone is in use. The style below still works with the preview.`}>
        <Toggle on={cfg.enabled} onChange={(v) => save({ enabled: v })} label="On Air" />
      </Row>
      <Row label="Style" hint={cfg.style === "full" ? "Takes over the playlist; plays natively, so a long call costs no Bluetooth traffic."
        : cfg.style === "glow" ? "A breathing red border over every app (streams while live)." : "A red mic / camera tab in the top-left corner of every app."}>
        <Seg value={cfg.style} onChange={(v) => save({ style: v })} options={[["full", "Full screen"], ["badge", "Corner badge"], ["glow", "Border glow"]]} />
      </Row>
      {cfg.style === "full" && (
        <Row label="Sign">
          <Seg value={cfg.look} onChange={(v) => save({ look: v })} options={[["sign", "Lit sign"], ["outline", "Outline"]]} />
        </Row>
      )}
      <Row label="Watch">
        <span className="flex items-center gap-2 text-[12px] text-ink-2">Camera <Toggle on={cfg.webcam} onChange={(v) => save({ webcam: v })} label="Camera" /></span>
        <span className="flex items-center gap-2 text-[12px] text-ink-2">Microphone <Toggle on={cfg.microphone} onChange={(v) => save({ microphone: v })} label="Microphone" /></span>
      </Row>
      <Row label="Ignore these apps" hint="Comma-separated names or path parts, e.g. obs64, voicemeeter. DeskDot itself is always ignored.">
        <input className="field !h-8 !w-56" defaultValue={cfg.exclude} onBlur={(e) => e.target.value !== cfg.exclude && save({ exclude: e.target.value })} />
      </Row>
      <div className="flex gap-2 pt-2.5">
        <button className="key" onClick={() => api.onairSimulate(8)}><Icon name="eye" size={13} /> Preview 8 s</button>
        {live?.simulated && <button className="key key-ghost" onClick={() => api.onairSimulate(0)}>Stop preview</button>}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------- eye break
function EyeBreakSection({ st, cfg }: { st: St; cfg: Integrations["eyebreak"] }) {
  const save = (p: Partial<Integrations["eyebreak"]>) => api.integration("eyebreak", p);
  const eb = st.engine.eyebreak;
  const next = eb?.next_in_s;
  const platform = useStore((s) => s.meta?.platform);
  const unsupported = eb?.supported === false;
  return (
    <Section icon="eye" id="eyebreak" title="Eye break · 20-20-20" status={
      <><span className="led" data-on={eb?.active ? "ember" : cfg.enabled ? "ok" : undefined} />
        {eb?.active ? "break now" : cfg.enabled && next != null ? `next in ${Math.ceil(next / 60)} min` : "off"}</>
    }>
      <Row label="Remind me to look away" hint={unsupported
        ? `Needs Windows or macOS: DeskDot runs on ${platform ? PLATFORM_LABEL[platform] : "a host"} that can't see keyboard / mouse activity, so the timer never starts. "Try it now" still shows it.`
        : "After continuous keyboard / mouse use, a calm 20-second countdown: look 20 feet away. Skipped during calls and full-screen games (Windows); 2 min away from the keyboard resets the timer."}>
        <Toggle on={cfg.enabled} onChange={(v) => save({ enabled: v })} label="Eye break" />
      </Row>
      <Row label="Every">
        <Slider value={cfg.interval_min} min={5} max={120} step={5} unit=" min" onCommit={(v) => save({ interval_min: v })} />
      </Row>
      <Row label="Style">
        <Seg value={cfg.style} onChange={(v) => save({ style: v })} options={[["breathe", "Breathing orb"], ["ring", "Countdown ring"]]} />
      </Row>
      <div className="pt-2.5">
        <button className="key" onClick={() => api.eyebreakNow()}><Icon name="play" size={13} /> Try it now</button>
      </div>
    </Section>
  );
}

// --------------------------------------------------------------- indicators
const IND_POS = ["top-right", "right, middle", "bottom-right"];

function IndicatorRow({ slot, st }: { slot: number; st: St }) {
  const live = st.engine.indicators?.[String(slot)];
  const [color, setColor] = useState(live?.color ?? ["#00ff78", "#ffaa00", "#ff143c"][slot - 1]);
  const [mode, setMode] = useState<"steady" | "blink" | "fade">(live?.blink ? "blink" : live?.fade ? "fade" : "steady");
  const [size, setSize] = useState<"2" | "3">(String(live?.size ?? 2) as "2" | "3");
  const send = () => {
    const ind: Partial<Indicator> = { color, blink: mode === "blink" ? 1000 : 0, fade: mode === "fade" ? 2000 : 0, size: +size as 2 | 3 };
    api.setIndicator(slot, ind);
  };
  return (
    <Row label={`Indicator ${slot}`} hint={live ? `${IND_POS[slot - 1]} · on${live.remaining_s != null ? ` · ${Math.ceil(live.remaining_s)} s left` : ""}` : IND_POS[slot - 1]}>
      <span className="led" data-on={live ? "ok" : undefined} />
      <label className="relative h-8 w-8 shrink-0 overflow-hidden rounded-[8px] border border-line-2" title="Colour" style={{ background: color }}>
        <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="absolute inset-0 cursor-pointer opacity-0" />
      </label>
      <Seg value={mode} onChange={setMode} options={[["steady", "Steady"], ["blink", "Blink"], ["fade", "Fade"]]} />
      <Seg value={size} onChange={setSize} options={[["2", "2px"], ["3", "3px"]]} />
      <button className="key" onClick={send}>Set</button>
      <button className="key key-ghost" disabled={!live} onClick={() => api.clearIndicator(slot)}>Clear</button>
    </Row>
  );
}

function IndicatorsSection({ st }: { st: St }) {
  const web = useStore((s) => s.meta?.platform === "web");
  return (
    <Section icon="square-dot" id="indicators" title="Status indicators" status={`${Object.keys(st.engine.indicators ?? {}).length} / 3 lit`}>
      <p className="py-2 text-[11.5px] leading-snug text-ink-3">
        Small squares on the right edge, drawn over every app — for build status, a door sensor, unread mail.
        {web ? "In the browser app only this page can set them: scripts and agents need the desktop app's local API."
          : <>Scripts set them with <code className="font-mono text-ink-2">POST /api/indicators/1</code> (see docs/API.md).</>}
      </p>
      {[1, 2, 3].map((n) => <IndicatorRow key={n} slot={n} st={st} />)}
    </Section>
  );
}

// --------------------------------------------------------------------- ntfy
function NtfySection({ st, cfg }: { st: St; cfg: Integrations["ntfy"] }) {
  const save = (p: Partial<Integrations["ntfy"]>) => api.integration("ntfy", p);
  const [token, setToken] = useState("");
  const p = st.providers.ntfy as ({ error: string | null; connected?: boolean } | undefined);
  const first = cfg.topics.split(",")[0]?.trim() || "your-topic";
  const web = useStore((s) => s.meta?.platform === "web");
  return (
    <Section icon="smartphone" id="ntfy" title="Phone pushes (ntfy)" status={
      <><span className="led" data-on={p?.error ? "bad" : p?.connected ? "ok" : undefined} />
        {p?.error ? "error" : p?.connected ? "subscribed" : cfg.enabled ? "connecting…" : "off"}</>
    }>
      <Row label="Subscribe" hint={`Free, no account: install the ntfy app, pick a hard-to-guess topic name, send to it from anywhere.${web ? " The browser app checks for new messages every 10 s while this tab is open." : ""}`}>
        <Toggle on={cfg.enabled} onChange={(v) => save({ enabled: v })} label="ntfy" />
      </Row>
      <Row label="Topics" hint="Comma-separated. Anyone who knows a topic name can post to it — make it long and random.">
        <input className="field !h-8 !w-56" placeholder="e.g. deskdot-7f3k2q" defaultValue={cfg.topics} onBlur={(e) => e.target.value !== cfg.topics && save({ topics: e.target.value })} />
      </Row>
      <Row label="Server" hint="ntfy.sh, or your self-hosted server.">
        <input className="field !h-8 !w-56" defaultValue={cfg.server} onBlur={(e) => e.target.value !== cfg.server && save({ server: e.target.value })} />
      </Row>
      <Row label="Access token" hint="Only for protected topics. Stored locally, never shown again.">
        <input type="password" className="field !h-8 !w-44" value={token} placeholder={cfg.token_set ? `saved ${cfg.token}` : "optional"} onChange={(e) => setToken(e.target.value)} />
        <button className="key" disabled={!token} onClick={() => { save({ token }); setToken(""); toast("Token saved", "ok"); }}>Save</button>
        {cfg.token_set && <button className="key key-ghost" onClick={() => save({ token: "" })}>Remove</button>}
      </Row>
      <Row label="Style" hint="Auto: priority 4–5 go full screen (5 in red), lower priorities slide in as a banner.">
        <Seg value={cfg.style} onChange={(v) => save({ style: v })} options={[["auto", "By priority"], ["banner", "Banner"], ["full", "Full screen"]]} />
      </Row>
      <Row label="On screen for">
        <Slider value={cfg.duration} min={2} max={30} unit=" s" onCommit={(v) => save({ duration: v })} />
      </Row>
      <Row label="Route to a custom app" hint={`Tag a message "${cfg.route_prefix || "app-"}garage" to show it as the custom app "garage" in the rotation instead of popping up.`}>
        <input className="field !h-8 !w-24" defaultValue={cfg.route_prefix} onBlur={(e) => e.target.value !== cfg.route_prefix && save({ route_prefix: e.target.value })} />
        <Slider value={Math.round(cfg.lifetime / 60)} min={0} max={1440} step={15} unit=" min" width={120} onCommit={(v) => save({ lifetime: v * 60 })} />
      </Row>
      <p className="py-2.5 font-mono text-[10.5px] leading-relaxed text-ink-3">
        curl -H "Title: Laundry" -H "Tags: white_check_mark" -d "Dryer done" {cfg.server.replace(/^https?:\/\//, "")}/{first}
      </p>
      {p?.error && <p className="pb-2 text-[11.5px] text-warn">{p.error}</p>}
    </Section>
  );
}

// ------------------------------------------------------------ home assistant
function HassSection({ st, cfg }: { st: St; cfg: Integrations["homeassistant"] }) {
  const [url, setUrl] = useState(cfg.url);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const p = st.providers.homeassistant;
  const web = useStore((s) => s.meta?.platform === "web");
  const save = async () => {
    await api.integration("homeassistant", token ? { url, token } : { url });
    setToken("");
    toast("Home Assistant saved", "ok");
  };
  const test = async () => {
    setBusy(true);
    try {
      const r = await api.hassTest();
      toast(r.ok ? `Connected: ${r.message}` : r.message, r.ok ? "ok" : "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section icon="house" id="homeassistant" title="Home Assistant" status={
      <><span className="led" data-on={p?.error ? "bad" : p?.active ? "ok" : cfg.token_set ? "warn" : undefined} />
        {!cfg.url || !cfg.token_set ? "not set up" : p?.error ? "error" : p?.active ? "polling" : "ready"}</>
    }>
      <Row label="URL" hint={web
        ? "The browser app needs an https address (Nabu Casa or your own reverse proxy) that lists https://idotmatrix.com in HA's http: cors_allowed_origins. A plain http://….local address only works from the desktop app."
        : "Your Home Assistant, e.g. http://homeassistant.local:8123"}>
        <input className="field !h-8 !w-64" value={url} placeholder="http://homeassistant.local:8123" onChange={(e) => setUrl(e.target.value)} />
      </Row>
      <Row label="Long-lived token" hint={`HA → your profile → Security → Long-lived access tokens. Stored only ${web ? "in this browser" : "on this computer"}; never shown again.`}>
        <input type="password" className="field !h-8 !w-64" value={token} placeholder={cfg.token_set ? `saved ${cfg.token}` : "paste token"} onChange={(e) => setToken(e.target.value)} />
      </Row>
      <div className="flex flex-wrap items-center gap-2 py-2.5">
        <button className="key key-ember" onClick={save}><Icon name="check" size={13} /> Save</button>
        <button className="key" disabled={busy || !cfg.token_set} onClick={test}><Icon name="plug" size={13} /> {busy ? "Testing…" : "Test connection"}</button>
        <span className="text-[11.5px] text-ink-3">Then add the <b className="text-ink-2">Home Assistant</b> app and pick an entity id.</span>
      </div>
      {p?.error && <p className="pb-2 text-[11.5px] text-warn">{p.error}</p>}
    </Section>
  );
}

export function IntegrationsTab({ st }: { st: St }) {
  const cfg: Integrations = { ...DEFAULTS, ...(st.settings.integrations ?? {}) };
  return (
    <div className="space-y-4">
      <OnAirSection st={st} cfg={cfg.onair} />
      <EyeBreakSection st={st} cfg={cfg.eyebreak} />
      <IndicatorsSection st={st} />
      <NtfySection st={st} cfg={cfg.ntfy} />
      <HassSection st={st} cfg={cfg.homeassistant} />
    </div>
  );
}
