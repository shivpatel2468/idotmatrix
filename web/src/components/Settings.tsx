import clsx from "clsx";
import { AlertTriangle, Bluetooth, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { api, loadPresets } from "../lib/api";
import { type SettingsSection, type SettingsTab, toast, useStore } from "../lib/store";
import type { EngineState, Handoff } from "../lib/types";
import { AutopilotEditor } from "./AutopilotEditor";
import { ColourCalibration } from "./calibration/ColourCalibration";
import { MotionLab } from "./calibration/MotionLab";
import { Row, Slider, Toggle } from "./controls";
import { IntegrationsTab } from "./IntegrationsTab";
import { Icon } from "./Icon";
import { Modal } from "./Overlays";
import { SFX_NAMES, SOUND_CATEGORIES, type SfxName, getSound, onSound, setSound, sfx, sfxCategory } from "../lib/sound";
import { INTRO_THEMES, type IntroTheme, getIntroTheme, replayIntro, setIntroTheme } from "../lib/intro";

type St = EngineState;

/**
 * Settings, in four plain sections. Every block has an anchor id (`set-<block>`): "open settings at X"
 * links (the old tab ids) and the search box scroll straight to it.
 */
const SECTIONS: [SettingsSection, string, string, string][] = [
  ["display", "Display & colour", "monitor", "Brightness, night mode, studio sounds, colours, smooth motion"],
  ["alerts", "Notifications & integrations", "bell-ring", "Computer alerts, On Air, eye breaks, phone pushes, smart home"],
  ["playlist", "Playlist & hand-off", "list-music", "Transitions, presets, following your apps, running without the computer"],
  ["device", "Device", "bluetooth", "Connection, location, sound input, data sources"],
];

const BLOCK_SECTION: Record<SettingsTab, SettingsSection> = {
  display: "display", transfer: "display", calibrate: "display",
  alerts: "alerts", notifications: "alerts", integrations: "alerts",
  playlist: "playlist", autopilot: "playlist", handoff: "playlist",
  device: "device", panel: "device", weather: "device", audio: "device",
};

/** What the settings search knows about: label, extra words, and the block it lives in. */
const INDEX: [string, string, SettingsTab | string][] = [
  ["Brightness", "dim bright level", "display-basics"],
  ["Night mode", "dim overnight schedule sleep dark", "display-basics"],
  ["Rotate 180°", "flip upside down mount", "display-basics"],
  ["Studio sounds", "sound effects sfx audio volume mute quiet clicks casino chips fly buzz", "sound"],
  ["Colour calibration", "color white gamma saturation black wizard tint match screen video test", "calibrate"],
  ["Colour presets", "preset sony lg samsung macbook apple dell benq srgb rec709 warm night claude quick match", "calibrate"],
  ["Advanced colour", "contrast temperature kelvin per-channel gamma gains dither peak level preview match", "calibrate"],
  ["Smooth motion test", "tearing flicker stutter judder ufo ball scroll calibration transfer", "transfer"],
  ["Motion presets", "smoothest balanced battery ble friendly auto-tune autotune", "transfer"],
  ["Refresh rate", "fps hz frames speed", "transfer"],
  ["Temporal smoothing", "smooth streams jitter visualiser", "transfer"],
  ["Packet spacing", "bluetooth gap ms timing", "transfer"],
  ["Computer notifications", "windows mac teams whatsapp toast alerts", "notifications"],
  ["On Air", "call webcam camera microphone meeting", "onair"],
  ["Eye break", "20-20-20 rest eyes reminder", "eyebreak"],
  ["Status indicators", "led dot corner build light", "indicators"],
  ["Phone pushes (ntfy)", "ntfy phone push topic curl", "ntfy"],
  ["Home Assistant", "smart home hass token entity", "homeassistant"],
  ["App transitions", "cut push fade wipe switch", "transitions"],
  ["Your presets", "preset delete saved playlist", "presets"],
  ["Follow the app I'm using", "autopilot rules spotify foreground window", "autopilot"],
  ["Keep showing when my computer is off", "hand off handoff sleep exit laptop lid clock", "handoff"],
  ["Connection", "bluetooth connect disconnect reconnect scan pair", "panel"],
  ["Location & units", "city weather celsius fahrenheit metric imperial", "weather"],
  ["Sound input", "audio microphone system loopback visualizer", "audio"],
  ["Data sources", "providers status health", "sources"],
  ["Link statistics", "frames sent dropped telemetry latency", "sources"],
];
const INDEX_SECTION: Record<string, SettingsSection> = {
  "display-basics": "display", sound: "display", onair: "alerts", eyebreak: "alerts", indicators: "alerts", ntfy: "alerts",
  homeassistant: "alerts", transitions: "playlist", presets: "playlist", sources: "device",
};
const sectionOf = (block: string): SettingsSection => BLOCK_SECTION[block as SettingsTab] ?? INDEX_SECTION[block] ?? "display";

/** A titled card inside a section; `id` makes it a scroll target. */
function Block({ id, title, hint, icon, children, tone }: {
  id: string; title: string; hint?: React.ReactNode; icon?: string; children: React.ReactNode; tone?: "plain";
}) {
  return (
    <section id={`set-${id}`} className={clsx("scroll-mt-4 rounded-xl", tone !== "plain" && "border border-line bg-chassis-0/60 p-4")}>
      <div className="mb-1 flex items-center gap-2">
        {icon && <Icon name={icon} size={15} className="text-ember" />}
        <h3 className="font-display text-[15px] font-[640] tracking-[-0.01em]">{title}</h3>
      </div>
      {hint && <p className="mb-2 text-[12px] leading-relaxed text-ink-3">{hint}</p>}
      {children}
    </section>
  );
}

function Advanced({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <details className="group/adv mt-3 rounded-lg border border-line">
      <summary className="flex cursor-pointer select-none list-none items-center gap-2 rounded-lg px-3 py-2.5 text-[12.5px] text-ink-2 hover:bg-chassis-2/60">
        <span className="transition group-open/adv:rotate-90">›</span> {label}
      </summary>
      <div className="border-t border-line px-3 pb-3 pt-1">{children}</div>
    </details>
  );
}

// ------------------------------------------------------------------ display
function DisplayBasics({ st }: { st: St }) {
  const s = st.settings;
  const night = s.display.night;
  return (
    <Block id="display-basics" title="Display" icon="sun">
      <div className="divide-y divide-line">
        <Row label="Brightness" hint="Also on the top bar.">
          <Slider value={s.brightness} min={5} max={100} unit="%" onCommit={(v) => api.settings({ brightness: v })} />
        </Row>
        <Row label="Night mode" hint={s.night_active ? "On right now — the panel is dimmed." : "Dim the panel automatically overnight."}>
          <Toggle on={night.enabled} label="Night mode" onChange={(v) => api.display({ night: { enabled: v } })} />
        </Row>
        {night.enabled && (
          <>
            <Row label="From / until">
              <input type="time" className="field !h-8 !w-28 [color-scheme:dark]" defaultValue={night.start} aria-label="Night starts" onBlur={(e) => api.display({ night: { start: e.target.value } })} />
              <span className="text-ink-3">→</span>
              <input type="time" className="field !h-8 !w-28 [color-scheme:dark]" defaultValue={night.end} aria-label="Night ends" onBlur={(e) => api.display({ night: { end: e.target.value } })} />
            </Row>
            <Row label="Night brightness">
              <Slider value={night.brightness} min={1} max={60} unit="%" onCommit={(v) => api.display({ night: { brightness: v } })} />
            </Row>
          </>
        )}
        <Row label="Rotate 180°" hint="If the panel is mounted upside down.">
          <Toggle on={s.flip} label="Rotate 180°" onChange={(v) => api.settings({ flip: v })} />
        </Row>
      </div>
    </Block>
  );
}

// ------------------------------------------------------------------- sound
/** The studio's own sound effects (lib/sound.ts; per browser). Not the panel's sound input — that's in Device. */
function SoundBlock() {
  const p = useSyncExternalStore(onSound, getSound);
  const [pick, setPick] = useState<SfxName>("coin-insert");
  const test = () => {
    // one effect from each category that's switched on, a beat apart
    const demo: SfxName[] = (["click", "chip", "coin-insert", "score"] as SfxName[]).filter((n) => p.cats[sfxCategory(n)]);
    demo.forEach((n, i) => setTimeout(() => sfx(n), i * 420));
  };
  return (
    <Block id="sound" title="Sound" icon="volume-2"
      hint="Little sounds in the studio — keys, sheets, the casino table, games, the fly. All made live in the browser; nothing is downloaded.">
      <div className="divide-y divide-line">
        <Row label="Studio sounds" hint={p.on ? undefined : "Muted."}>
          <Toggle on={p.on} label="Studio sounds" onChange={(v) => setSound({ on: v })} />
        </Row>
        <Row label="Volume">
          <fieldset disabled={!p.on} className={clsx("flex items-center gap-2", !p.on && "opacity-50")}>
            <Slider value={Math.round(p.volume * 100)} min={0} max={100} unit="%" onCommit={(v) => { setSound({ volume: v / 100 }); sfx("click"); }} />
          </fieldset>
        </Row>
        {SOUND_CATEGORIES.map(([id, label, hint]) => (
          <Row key={id} label={label} hint={hint}>
            <fieldset disabled={!p.on} className={p.on ? undefined : "opacity-50"}>
              <Toggle on={p.cats[id]} label={label} onChange={(v) => setSound({ cats: { ...p.cats, [id]: v } })} />
            </fieldset>
          </Row>
        ))}
        <Row label="Quiet when the tab is in the background">
          <Toggle on={p.hiddenMute} label="Quiet when the tab is in the background" onChange={(v) => setSound({ hiddenMute: v })} />
        </Row>
        <Row label="Try them" hint="Test plays one effect from each category that is on; or pick any effect and press play.">
          <button className="key" disabled={!p.on} onClick={test} data-sfx="off"><Icon name="volume-2" size={13} /> Test</button>
          <select className="field !h-8 !w-40" value={pick} aria-label="Effect" onChange={(e) => setPick(e.target.value as SfxName)}>
            {SFX_NAMES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <button className="key key-icon" disabled={!p.on} aria-label={`Play ${pick}`} title="Play it" onClick={() => sfx(pick)} data-sfx="off"><Icon name="play" size={12} /></button>
        </Row>
      </div>
    </Block>
  );
}

// ------------------------------------------------------------ notifications
function NotificationsTab({ st }: { st: St }) {
  const n = st.settings.os_notifications;
  const save = (p: Partial<typeof n>) => api.settings({ os_notifications: { ...n, ...p } });
  const [can, host] = useHostCan("notifications");
  const mac = useStore((s) => s.meta?.platform) === "macos";
  return (
    <div className="divide-y divide-line">
      <Row label="Show computer notifications" hint={can ? `Toasts from ${mac ? "macOS" : "Windows"} (Teams, WhatsApp, Mail, Discord…) appear live on the panel.` : `Windows/macOS only — not available on ${host}.`}>
        <fieldset disabled={!can} className={can ? undefined : "opacity-50"}><Toggle on={n.enabled} onChange={(v) => save({ enabled: v })} /></fieldset>
      </Row>
      <Row label="Style">
        <div className="seg">
          {(["banner", "full"] as const).map((x) => (
            <button key={x} data-active={n.style === x} onClick={() => save({ style: x })}>{x === "banner" ? "Scrolling banner" : "Full screen"}</button>
          ))}
        </div>
      </Row>
      <Row label="On screen for">
        <Slider value={n.duration} min={2} max={30} unit=" s" onCommit={(v) => save({ duration: v })} />
      </Row>
      <Row label="Only these apps" hint="Comma-separated, e.g. WhatsApp, Teams. Empty = all.">
        <input className="field !h-8 !w-56" defaultValue={n.only} onBlur={(e) => save({ only: e.target.value })} />
      </Row>
      <Row label="Never these apps">
        <input className="field !h-8 !w-56" defaultValue={n.exclude} onBlur={(e) => save({ exclude: e.target.value })} />
      </Row>
      <div className="py-3">
        <button className="key" onClick={() => api.notify({ title: "TEST", message: "Notifications reach the panel", color: "#00dcff", icon: "bell", duration: 5, style: n.style as "banner" | "full" })}>
          <Icon name="send" size={13} /> Send a test
        </button>
        {mac && <p className="mt-2 text-[11.5px] text-ink-3">macOS: give your terminal (or Python) Full Disk Access in System Settings → Privacy & Security so DeskDot can read the notification centre.</p>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- audio
/** Can this engine's host do `feature`? (Older engines don't say: assume yes.) */
function useHostCan(feature: string): [boolean, string] {
  const meta = useStore((s) => s.meta);
  const ok = meta?.features?.[feature] ?? true;
  return [ok, meta?.platform_label ?? "this computer"];
}

function AudioTab({ st }: { st: St }) {
  const src = st.settings.audio_source;
  const p = st.providers.audio;
  const [loopback, host] = useHostCan("audio_loopback");
  return (
    <div className="divide-y divide-line">
      <Row label="Listen to" hint="Drives the Visualizer, and pets & characters dancing to the beat.">
        <div className="seg">
          <button data-active={src === "system"} disabled={!loopback} title={loopback ? undefined : `Not available on ${host}`}
            onClick={() => api.settings({ audio_source: "system" })}>System audio</button>
          <button data-active={src === "mic"} onClick={() => api.settings({ audio_source: "mic" })}>Microphone</button>
        </div>
      </Row>
      <Row label="Status">
        <span className="flex items-center gap-2 font-mono text-[11.5px] text-ink-2">
          <span className="led" data-on={p?.error ? "bad" : p?.active ? "ok" : undefined} /> {p?.error ?? (p?.active ? "listening" : "idle — starts when an app needs it")}
        </span>
      </Row>
      <p className="py-3 text-[11.5px] text-ink-3">System audio captures whatever your speakers play (WASAPI loopback on Windows; on macOS install a loopback device such as BlackHole). Audio never leaves this computer.</p>
    </div>
  );
}

// ------------------------------------------------------------------ location
function LocationTab({ st }: { st: St }) {
  const s = st.settings;
  const [city, setCity] = useState(s.location.city ?? "");
  const save = () => { api.settings({ location: city ? { city } : {} }); toast("Location saved", "ok"); };
  return (
    <div className="divide-y divide-line">
      <Row label="City" hint="Used by Weather, Flight Radar and sunrise/sunset. Empty = detect from IP.">
        <input className="field !h-8 !w-56" value={city} placeholder="e.g. Mumbai" onChange={(e) => setCity(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
        <button className="key" onClick={save}>Save</button>
      </Row>
      <Row label="Units">
        <div className="seg">
          {(["metric", "imperial"] as const).map((u) => (
            <button key={u} data-active={s.units === u} onClick={() => api.settings({ units: u })}>{u === "metric" ? "°C · km/h" : "°F · mph"}</button>
          ))}
        </div>
      </Row>
    </div>
  );
}

// --------------------------------------------------------- playlist & hand-off
function HandoffSection({ st }: { st: St }) {
  const [sleepOk] = useHostCan("sleep_handoff");
  const [h, setH] = useState<Handoff | null>(null);
  const [busy, setBusy] = useState(false);
  const apps = st ? Object.keys(st.apps) : [];
  const meta = useStore((s) => s.meta);
  useEffect(() => {
    api.handoff().then(setH).catch(() => undefined);
  }, []);
  if (!h) return <div className="skeleton h-40 rounded-lg" />;
  const save = async (p: Partial<Handoff>) => setH(await api.setHandoff(p));
  const name = (id: string) => meta?.apps.find((a) => a.id === id)?.name ?? id;
  return (
    <>
      <div className="divide-y divide-line">
        <Row label="What the panel shows">
          <div className="seg">
            {(["clock", "app", "last"] as const).map((m) => (
              <button key={m} data-active={h.mode === m} onClick={() => save({ mode: m })}>
                {m === "clock" ? "Its own clock" : m === "app" ? "An app, looping" : "Last picture"}
              </button>
            ))}
          </div>
        </Row>
        {h.mode === "app" && (
          <Row label="Which app" hint="Recorded as a loop the panel plays by itself (live data freezes at that moment).">
            <select className="field !h-8 !w-48" value={h.app} onChange={(e) => save({ app: e.target.value })}>
              {apps.map((a) => <option key={a} value={a}>{name(a)}</option>)}
            </select>
          </Row>
        )}
        {h.mode === "clock" && (
          <Row label="Clock look" hint="The panel's own clock face (0–7), its colour, and 24-hour time.">
            <input type="number" min={0} max={7} className="field !h-8 !w-16" aria-label="Clock face" value={h.clock_style} onChange={(e) => save({ clock_style: +e.target.value })} />
            <input type="color" className="h-8 w-10 cursor-pointer rounded" aria-label="Clock colour" value={h.color} onChange={(e) => save({ color: e.target.value })} />
            <span className="text-[12px] text-ink-3">24 h</span>
            <Toggle on={h.hour24} label="24-hour clock" onChange={(v) => save({ hour24: v })} />
          </Row>
        )}
        <Row label="When DeskDot closes"><Toggle on={h.on_exit} label="Hand over when DeskDot closes" onChange={(v) => save({ on_exit: v })} /></Row>
        <Row label="When the computer goes to sleep" hint="Windows only. Always uses the panel's clock (there's only a moment before sleep).">
          <fieldset disabled={!sleepOk} className={sleepOk ? undefined : "opacity-50"}><Toggle on={h.on_sleep} label="Hand over on sleep" onChange={(v) => save({ on_sleep: v })} /></fieldset>
        </Row>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <button className="key" disabled={busy} onClick={async () => {
          setBusy(true);
          try { const r = await api.handoffNow(); toast(`The panel is on its own now (${r.result}) — close the lid any time`, "ok"); } finally { setBusy(false); }
        }}>
          <Icon name="laptop-minimal" size={13} /> {busy ? "Handing over…" : "Let the panel run on its own now"}
        </button>
        {st.engine.released && <button className="key" onClick={() => api.takeBack()}>Take it back</button>}
      </div>
    </>
  );
}

function PresetManager() {
  const presets = useStore((s) => s.presets);
  const mine = presets?.filter((p) => !p.builtin) ?? [];
  const [confirm, setConfirm] = useState<string | null>(null);
  useEffect(() => void loadPresets(), []);
  if (!mine.length) {
    return <p className="text-[12.5px] text-ink-3">You haven't saved any yet. Build a playlist, then press <b className="text-ink-2">Save as preset</b> in the playback bar.</p>;
  }
  return (
    <div className="space-y-1.5">
      {mine.map((p) => (
        <div key={p.id} className="flex items-center gap-3 rounded-lg bg-chassis-0 px-3 py-2">
          <Icon name={p.icon || "list-music"} size={14} className="text-ink-2" />
          <span className="flex-1 text-[13px]">{p.name}</span>
          <span className="font-mono text-[10.5px] text-ink-4">{p.items.length} apps</span>
          <button className="key !h-8" onClick={() => api.playPreset(p.id, useStore.getState().shuffle)}><Icon name="play" size={12} /> Play</button>
          {confirm === p.id ? (
            <>
              <button className="key !h-8 !text-bad" onClick={async () => { await api.deletePreset(p.id); setConfirm(null); loadPresets(); toast("Preset deleted", "ok"); }}>Delete</button>
              <button className="key key-ghost !h-8" onClick={() => setConfirm(null)}>Keep</button>
            </>
          ) : (
            <button className="key key-ghost key-icon !h-8 !w-8" aria-label={`Delete ${p.name}`} title="Delete" onClick={() => setConfirm(p.id)}><Trash2 size={13} /></button>
          )}
        </div>
      ))}
    </div>
  );
}

// -------------------------------------------------------------------- device
function ConnectionBlock({ st }: { st: St }) {
  const d = st.device;
  const [found, setFound] = useState<{ address: string; name: string; rssi: number }[] | null>(null);
  const [scanning, setScanning] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const ok = d.status === "connected";
  return (
    <>
      <div className="flex items-center gap-3 rounded-lg bg-chassis-0 px-3 py-3">
        <span className="led" data-on={!d.link_enabled ? undefined : ok ? "ok" : d.status === "error" ? "bad" : "warn"} />
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-[560]">
            {!d.link_enabled ? "Bluetooth link is off" : ok ? `Connected to ${d.name ?? "your panel"}` : d.status === "error" ? "Can't reach the panel" : "Connecting…"}
            {d.kind === "sim" && <span className="engrave ml-2 !text-info">simulated</span>}
          </div>
          <div className="truncate font-mono text-[10.5px] text-ink-3">{d.address ?? "any nearby panel"}{ok ? ` · ${d.link_fps.toFixed(1)} frames/s` : ""}</div>
          {d.last_error && <div className="mt-1 text-[11.5px] text-warn">{d.last_error}</div>}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="key" onClick={() => api.reconnect()}><Bluetooth size={13} /> Reconnect</button>
        {d.kind !== "web" && ( // the browser app: Chrome's own device chooser ("Connect panel" at the top) finds panels
          <button className="key" disabled={scanning} onClick={async () => { setScanning(true); try { setFound(await api.scan()); } finally { setScanning(false); } }}>
            <Search size={13} /> {scanning ? "Scanning…" : "Find nearby panels"}
          </button>
        )}
        {d.link_enabled ? (
          confirmOff ? null : <button className="key key-ghost" onClick={() => setConfirmOff(true)}><Icon name="unplug" size={13} /> Disconnect…</button>
        ) : (
          <button className="key key-ember" onClick={() => api.link(true)}><Icon name="plug" size={13} /> Connect</button>
        )}
      </div>
      {confirmOff && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-warn/30 bg-warn/10 p-3 text-[12px] text-ink-2">
          <AlertTriangle size={14} className="shrink-0 text-warn" />
          <span className="min-w-[200px] flex-1">While disconnected the panel shows its pairing screen and nothing updates. Other apps (like the phone app) can connect instead.</span>
          <button className="key" onClick={() => { api.link(false); setConfirmOff(false); }}>Disconnect</button>
          <button className="key key-ghost" onClick={() => setConfirmOff(false)}>Cancel</button>
        </div>
      )}
      {found && (
        <div className="mt-3 space-y-1 font-mono text-[11px] text-ink-2">
          {found.length ? found.map((f) => <div key={f.address}>{f.address} · {f.name} · {f.rssi} dBm</div>) : <div>No panels found nearby.</div>}
          <div className="text-ink-4">To always use one panel, set its address in deskdot.toml (or --address).</div>
        </div>
      )}
    </>
  );
}

function SourcesBlock({ st }: { st: St }) {
  const d = st.device;
  return (
    <>
      <div className="grid grid-cols-1 gap-1.5 font-mono text-[10.5px] sm:grid-cols-2">
        {Object.entries(st.providers).map(([name, p]) => (
          <div key={name} className="flex items-center gap-2 rounded-lg bg-chassis-0 px-2.5 py-1.5" title={p.error ?? ""}>
            <span className="led" data-on={p.error ? "bad" : p.active ? "ok" : undefined} />
            <span className="text-ink-2">{name}</span>
            <span className="ml-auto truncate text-ink-4">{p.error ? "error" : p.updated ? new Date(p.updated * 1000).toLocaleTimeString() : "idle"}</span>
          </div>
        ))}
      </div>
      <Advanced label="Link statistics">
        <div className="font-mono text-[11px] leading-6 text-ink-2">
          <div>mode {d.mode} · chunk {d.mtu ?? "—"} B · last write {d.last_write_ms} ms · {d.link_fps.toFixed(1)} fps</div>
          <div>sent {d.frames_sent} frames · superseded {d.frames_dropped} · {(d.bytes_sent / 1024).toFixed(0)} KB</div>
        </div>
      </Advanced>
    </>
  );
}

/** The studio's intro / outro theme (per browser; it plays before the engine is reachable). */
function IntroThemePicker() {
  const [v, setV] = useState<IntroTheme>(() => getIntroTheme());
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-2 sm:grid-cols-2">
        {INTRO_THEMES.map((t) => (
          <button key={t.id} onClick={() => { setIntroTheme(t.id); setV(t.id); }} aria-pressed={v === t.id}
            className={clsx("rounded-[10px] border px-3 py-2.5 text-left transition", v === t.id ? "border-ember bg-ember-deep/40" : "border-line hover:border-line-2")}>
            <div className="text-[13px] font-[600]">{t.name}{t.id === "sunset" && <span className="ml-2 text-[10px] text-ink-3">default</span>}</div>
            {/* a looping preview of the intro (recorded from the studio; "Off" has none) */}
            <div className="my-2 aspect-video overflow-hidden rounded-[6px] border border-line bg-black">
              {t.id === "off"
                ? <div className="grid h-full place-items-center text-[11px] text-ink-3">No animation</div>
                : <img src={`${import.meta.env.BASE_URL}intro/${t.id}.gif`} alt={`${t.name} intro preview`} loading="lazy" className="block h-full w-full object-cover" />}
            </div>
            <div className="text-[11.5px] leading-snug text-ink-3">{t.hint}</div>
          </button>
        ))}
      </div>
      <div><button className="key" onClick={() => replayIntro()}>Play it now</button></div>
    </div>
  );
}

// ------------------------------------------------------------------- sheet
function SectionBody({ id, st }: { id: SettingsSection; st: St }) {
  if (id === "display") {
    return (
      <div className="space-y-4">
        <DisplayBasics st={st} />
        <SoundBlock />
        <Block id="intro" title="Intro & outro" icon="clapperboard"
          hint="What plays while the studio connects, and when the engine stops. OG is the original LED fly-in.">
          <IntroThemePicker />
        </Block>
        <Block id="calibrate" title="Colour calibration" icon="palette"
          hint="Every LED panel shows colour a little differently. Match it to your screen with test videos that play on both, pick a preset, or tune every knob — apps, photos and GIFs are all corrected.">
          <ColourCalibration st={st} />
        </Block>
        <Block id="transfer" title="Smooth motion" icon="zap"
          hint="Seeing judder, tearing or stutter? Watch motion tests on the panel, pick the smoother one, or let Claude measure your Bluetooth link.">
          <MotionLab st={st} />
        </Block>
      </div>
    );
  }
  if (id === "alerts") {
    return (
      <div className="space-y-4">
        <Block id="notifications" title="Computer notifications" icon="bell-ring">
          <NotificationsTab st={st} />
        </Block>
        <div id="set-integrations" className="scroll-mt-4"><IntegrationsTab st={st} /></div>
      </div>
    );
  }
  if (id === "playlist") {
    return (
      <div className="space-y-4">
        <Block id="transitions" title="App transitions" icon="move-right" hint="How one app hands over to the next. “Cut” is the cleanest over Bluetooth.">
          <div className="seg max-w-sm">
            {(["cut", "push", "fade", "wipe"] as const).map((t) => (
              <button key={t} data-active={st.settings.transition === t} onClick={() => api.settings({ transition: t })}>{t}</button>
            ))}
          </div>
        </Block>
        <Block id="presets" title="Your presets" icon="list-music"><PresetManager /></Block>
        <Block id="autopilot" title="Follow the app I'm using" icon="wand-sparkles"
          hint="Autopilot: when an app is in front on your computer (Spotify, VS Code, a YouTube tab…), show a matching app on the panel.">
          <AutopilotEditor />
        </Block>
        <Block id="handoff" title="Keep showing when my computer is off" icon="laptop-minimal"
          hint="The panel can keep going on its own: its built-in clock keeps time, or it loops the last animation it was given. DeskDot hands over automatically.">
          <HandoffSection st={st} />
        </Block>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <Block id="panel" title="Connection" icon="bluetooth"><ConnectionBlock st={st} /></Block>
      <Block id="weather" title="Location & units" icon="map-pin"><LocationTab st={st} /></Block>
      <Block id="audio" title="Sound input" icon="audio-lines"><AudioTab st={st} /></Block>
      <Block id="sources" title="Data sources" icon="activity" hint="Where live data comes from, and whether it's healthy."><SourcesBlock st={st} /></Block>
    </div>
  );
}

export function SettingsSheet() {
  const open = useStore((s) => s.settingsOpen);
  const tab = useStore((s) => s.settingsTab);
  const st = useStore((s) => s.state);
  const set = useStore((s) => s.set);
  const [q, setQ] = useState("");
  const body = useRef<HTMLDivElement>(null);
  const section = sectionOf(tab);

  // jump to the requested block (old tab ids and search results are block anchors)
  useEffect(() => {
    if (!open) return;
    const el = document.getElementById(`set-${tab}`);
    if (el && tab !== section) {
      requestAnimationFrame(() => {
        el.scrollIntoView({ block: "start", behavior: "smooth" });
        el.classList.add("flash");
        setTimeout(() => el.classList.remove("flash"), 1400);
      });
    } else body.current?.scrollTo({ top: 0 });
  }, [open, tab, section]);

  const results = useMemo(() => {
    const f = q.trim().toLowerCase();
    if (!f) return null;
    return INDEX.filter(([label, words]) => `${label} ${words}`.toLowerCase().includes(f));
  }, [q]);

  if (!st) return null;
  const close = () => { set({ settingsOpen: false }); setQ(""); };
  const go = (t: SettingsTab | string) => { setQ(""); set({ settingsTab: t as SettingsTab }); };
  return (
    <Modal open={open} onClose={close} title="Settings" width={880} bodyRef={body}
      header={
        <label className="relative mr-3 hidden w-56 sm:block">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-4" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search settings" aria-label="Search settings" className="field !h-8 !pl-8 !text-[12.5px]"
            onKeyDown={(e) => { if (e.key === "Enter" && results?.[0]) go(results[0][2]); }} />
        </label>
      }>
      <div className="flex flex-col gap-5 sm:flex-row">
        <nav className="sticky -top-4 z-10 -mx-4 -mt-4 flex shrink-0 gap-1 overflow-x-auto bg-chassis-1/95 px-4 py-2 backdrop-blur [scrollbar-width:none] sm:top-0 sm:mx-0 sm:mt-0 sm:w-52 sm:flex-col sm:self-start sm:bg-transparent sm:p-0 sm:backdrop-blur-none" aria-label="Settings sections">
          <label className="relative mb-1 block shrink-0 sm:hidden">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-4" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search" aria-label="Search settings" className="field !h-10 !w-32 !pl-8" />
          </label>
          {SECTIONS.map(([id, label, icon, hint]) => (
            <button key={id} onClick={() => go(id)} aria-current={section === id && !results ? "page" : undefined}
              className={clsx("flex shrink-0 items-start gap-2.5 rounded-lg px-3 py-2.5 text-left transition",
                section === id && !results ? "bg-chassis-3 text-ink-1" : "text-ink-3 hover:bg-chassis-2 hover:text-ink-1")}>
              <Icon name={icon} size={15} className={clsx("mt-0.5 shrink-0", section === id && !results && "text-ember")} />
              <span>
                <span className="block text-[13px] leading-tight">{label}</span>
                <span className="mt-0.5 hidden text-[10.5px] leading-snug text-ink-4 sm:block">{hint}</span>
              </span>
            </button>
          ))}
        </nav>
        <div className="min-w-0 flex-1">
          {results ? (
            <div className="space-y-1">
              <div className="engrave mb-2">{results.length ? `${results.length} match${results.length === 1 ? "" : "es"}` : "No setting matches"}</div>
              {results.map(([label, , block]) => (
                <button key={label} onClick={() => go(block)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-chassis-3">
                  <span className="flex-1 text-[13.5px]">{label}</span>
                  <span className="engrave !text-[8.5px]">{SECTIONS.find((s) => s[0] === sectionOf(block))?.[1]}</span>
                </button>
              ))}
              {!results.length && (
                <button className="key mt-2" onClick={() => setQ("")}><X size={13} /> Clear search</button>
              )}
            </div>
          ) : (
            <SectionBody key={section} id={section} st={st} />
          )}
        </div>
      </div>
    </Modal>
  );
}
