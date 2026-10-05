import clsx from "clsx";
import { CornerDownLeft, Search, Send, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { openPlay } from "../lib/gameInput";
import { letFlyPlay, takeBackFromFly } from "../lib/flyControl";
import { openFriends } from "./Multiplayer";
import { EMPTY_LIST, openSettings, toast, useStore } from "../lib/store";
import type { Notice } from "../lib/types";
import { Icon } from "./Icon";
import { sheetSound } from "../lib/sound";

export function Modal({ open, onClose, title, children, width = 440, header, bodyRef }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; width?: number;
  header?: React.ReactNode; bodyRef?: React.Ref<HTMLDivElement>;
}) {
  const wasOpen = useRef(open);
  useEffect(() => sheetSound(open, wasOpen), [open]);
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid grid-cols-[minmax(0,1fr)] place-items-center bg-black/60 backdrop-blur-[3px] sm:p-4" onMouseDown={onClose}>
      <div className="surface flex h-screen h-[100dvh] w-full animate-rise flex-col max-sm:!rounded-none sm:h-auto" style={{ maxWidth: width }}
        onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex shrink-0 items-center border-b border-line px-4 pb-3 pt-[max(12px,env(safe-area-inset-top))] sm:px-5 sm:pt-3">
          <h2 className="font-display text-[17px] font-[640] tracking-[-0.015em]">{title}</h2>
          <span className="flex-1" />
          {header}
          <button className="key key-ghost key-icon -mr-2" onClick={onClose} aria-label="Close" title="Close (Esc)"><X size={16} /></button>
        </div>
        <div ref={bodyRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 pb-[max(16px,env(safe-area-inset-bottom))] sm:max-h-[78vh] sm:p-5">{children}</div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ notify
export function NotifyComposer() {
  const open = useStore((s) => s.notifyOpen);
  const icons = useStore((s) => s.meta?.icons ?? EMPTY_LIST) as string[];
  const set = useStore((s) => s.set);
  const [n, setN] = useState<Notice>({ title: "HEADS UP", message: "", color: "#00dcff", icon: "bell", duration: 6, style: "banner" });
  const close = () => set({ notifyOpen: false });
  const send = async () => {
    if (!n.message && !n.title) return;
    await api.notify(n);
    toast("Notification sent", "ok");
    close();
  };
  return (
    <Modal open={open} onClose={close} title="Send a message to the panel">
      <div className="space-y-3.5">
        <div className="grid grid-cols-[1fr_auto] gap-2">
          <input className="field" placeholder="Title" value={n.title} maxLength={40} onChange={(e) => setN({ ...n, title: e.target.value })} />
          <label className="relative h-[2.2rem] w-12 overflow-hidden rounded-[9px] border border-line-2" style={{ background: n.color }}>
            <input type="color" value={n.color} onChange={(e) => setN({ ...n, color: e.target.value })} className="absolute inset-0 opacity-0" />
          </label>
        </div>
        <textarea className="field" autoFocus placeholder="Message — long text scrolls" value={n.message} maxLength={280}
          onChange={(e) => setN({ ...n, message: e.target.value })}
          onKeyDown={(e) => e.key === "Enter" && (e.metaKey || e.ctrlKey) && send()} />
        <div>
          <div className="engrave mb-1.5">Icon</div>
          <div className="flex flex-wrap gap-1.5">
            {[null, ...icons].map((ic) => (
              <button key={ic ?? "none"} onClick={() => setN({ ...n, icon: ic })}
                className={clsx("rounded-lg border px-2.5 py-1.5 font-mono text-[10px] uppercase", n.icon === ic ? "border-ember text-ember" : "border-line text-ink-3 hover:text-ink-1")}>
                {ic ?? "none"}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="engrave mb-1.5">Style</div>
            <div className="seg">
              {(["banner", "full", "celebrate"] as const).map((s) => (
                <button key={s} data-active={n.style === s} onClick={() => setN({ ...n, style: s })}>{s}</button>
              ))}
            </div>
          </div>
          <div>
            <div className="engrave mb-1.5">Seconds · {n.duration}</div>
            <input type="range" className="fader" min={2} max={30} value={n.duration} style={{ ["--fill" as string]: `${((n.duration - 2) / 28) * 100}%` }}
              onChange={(e) => setN({ ...n, duration: +e.target.value })} />
          </div>
        </div>
        <button className="key key-ember w-full !h-10" onClick={send}><Send size={13} /> Send to the panel</button>
        <p className="text-[11px] leading-relaxed text-ink-4">
          Scripts can do this too: <code className="text-ink-3">POST /api/notify</code> — see docs/API.md.
        </p>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------- command palette
type Cmd = { id: string; label: string; hint: string; icon: string; run: () => void };

export function CommandPalette() {
  const open = useStore((s) => s.palette);
  const meta = useStore((s) => s.meta);
  const presets = useStore((s) => s.presets);
  const set = useStore((s) => s.set);
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const close = () => { set({ palette: false }); setQ(""); setI(0); };

  const cmds = useMemo<Cmd[]>(() => {
    const apps: Cmd[] = (meta?.apps ?? []).map((a) => ({ id: a.id, label: a.name, hint: "Show app", icon: a.icon, run: () => api.activate(a.id) }));
    const pre: Cmd[] = (presets ?? []).map((p) => ({
      id: `preset-${p.id}`, label: `Play ${p.name}`, hint: "Preset", icon: p.icon || "list-music",
      run: () => api.playPreset(p.id, useStore.getState().shuffle).then(() => toast(`Playing ${p.name}`, "ok")),
    }));
    return [
      { id: "play", label: "Play a game…", hint: "Play mode", icon: "gamepad-2", run: () => void openPlay() },
      { id: "friends", label: "Play with a friend…", hint: "Play mode · Wi-Fi", icon: "users", run: () => void openFriends() },
      { id: "fly-play", label: "Let the fly play", hint: "Fruit fly · F", icon: "bug", run: () => void letFlyPlay() },
      { id: "fly-back", label: "Take the game back from the fly", hint: "Fruit fly · F", icon: "hand", run: () => void takeBackFromFly() },
      ...apps,
      ...pre,
      { id: "pl-play", label: "Resume playlist", hint: "Playback", icon: "play", run: () => api.playlist("play") },
      { id: "pl-stop", label: "Stop playlist", hint: "Playback", icon: "square", run: () => api.playlist("stop") },
      { id: "pl-next", label: "Next app", hint: "Playback", icon: "skip-forward", run: () => api.playlist("next") },
      { id: "shuffle", label: "Shuffle presets on / off", hint: "Playback", icon: "shuffle", run: () => useStore.getState().prefs({ shuffle: !useStore.getState().shuffle }) },
      { id: "notify", label: "Send a message to the panel…", hint: "Create", icon: "bell", run: () => set({ notifyOpen: true }) },
      { id: "ai", label: "Make pixel art with AI…", hint: "Create", icon: "sparkles", run: () => set({ aiOpen: true }) },
      { id: "tv", label: "Show on TV…", hint: "Big screen", icon: "tv", run: () => set({ tvOpen: true }) },
      { id: "draw", label: "Draw on the panel", hint: "Create", icon: "paintbrush", run: () => api.activate("canvas") },
      { id: "think", label: "Claude: thinking", hint: "Agent", icon: "bot", run: () => fetch("/api/agent/thinking", { method: "POST" }) },
      { id: "done", label: "Claude: done (5 s)", hint: "Agent", icon: "party-popper", run: () => fetch("/api/agent/done?hold=5", { method: "POST" }) },
      { id: "b100", label: "Brightness 100%", hint: "Panel", icon: "sun", run: () => api.settings({ brightness: 100 }) },
      { id: "b30", label: "Brightness 30%", hint: "Panel", icon: "sun-dim", run: () => api.settings({ brightness: 30 }) },
      { id: "off", label: "Turn the display off", hint: "Panel", icon: "power", run: () => api.settings({ power: false }) },
      { id: "on", label: "Turn the display on", hint: "Panel", icon: "power", run: () => api.settings({ power: true }) },
      { id: "settings", label: "Settings", hint: "Studio", icon: "settings-2", run: () => openSettings("display") },
      { id: "display", label: "Night mode & display", hint: "Settings", icon: "monitor", run: () => openSettings("display") },
      { id: "calib", label: "Calibrate panel colours…", hint: "Settings", icon: "palette", run: () => openSettings("calibrate") },
      { id: "motion", label: "Fix tearing / flicker (smooth motion test)", hint: "Settings", icon: "zap", run: () => openSettings("transfer") },
      { id: "osn", label: "Computer notifications on the panel", hint: "Settings", icon: "bell-ring", run: () => openSettings("notifications") },
      { id: "integr", label: "Integrations: On Air, eye break, ntfy, Home Assistant", hint: "Settings", icon: "plug-zap", run: () => openSettings("integrations") },
      { id: "auto", label: "Follow the app I'm using (autopilot)", hint: "Settings", icon: "wand-sparkles", run: () => openSettings("autopilot") },
      { id: "audio", label: "Sound input (system / microphone)", hint: "Settings", icon: "audio-lines", run: () => openSettings("audio") },
      { id: "loc", label: "Location & units", hint: "Settings", icon: "map-pin", run: () => openSettings("weather") },
      { id: "handoffset", label: "Keep showing when my computer is off…", hint: "Settings", icon: "laptop-minimal", run: () => openSettings("handoff") },
      { id: "handoff", label: "Let the panel run on its own now", hint: "Panel", icon: "laptop-minimal", run: () => api.handoffNow().then((r) => toast(`The panel is on its own now (${r.result})`, "ok")) },
      { id: "takeback", label: "Take the panel back", hint: "Panel", icon: "monitor-play", run: () => api.takeBack() },
      { id: "device", label: "Device & connection", hint: "Settings", icon: "bluetooth", run: () => openSettings("panel") },
      { id: "unlink", label: "Disconnect from the panel (shows its pairing screen)", hint: "Panel", icon: "unplug", run: () => api.link(false) },
      { id: "link", label: "Connect to the panel", hint: "Panel", icon: "plug", run: () => api.link(true) },
    ];
  }, [meta, presets, set]);

  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const list = cmds.filter((c) => { const t = `${c.label} ${c.hint}`.toLowerCase(); return words.every((w) => t.includes(w)); }).slice(0, 9);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-center bg-black/55 px-3 pt-[10vh] backdrop-blur-[2px] sm:pt-[14vh]" onMouseDown={close}>
      <div className="surface h-fit w-full max-w-lg overflow-hidden animate-rise" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Find anything">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search size={15} className="text-ink-3" />
          <input autoFocus value={q} placeholder="Find an app, a preset or a setting…" aria-label="Search commands" className="h-12 flex-1 bg-transparent text-[14px] outline-none placeholder:text-ink-4"
            onChange={(e) => { setQ(e.target.value); setI(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(list.length - 1, x + 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
              if (e.key === "Enter" && list[i]) { list[i].run(); close(); }
              if (e.key === "Escape") close();
            }} />
          <kbd className="engrave">esc</kbd>
        </div>
        <div className="p-1.5">
          {list.map((c, k) => (
            <button key={c.id} onMouseEnter={() => setI(k)} onClick={() => { c.run(); close(); }}
              className={clsx("flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left", k === i ? "bg-chassis-3" : "")}>
              <Icon name={c.icon} size={15} className={k === i ? "text-ember" : "text-ink-3"} />
              <span className="flex-1 text-[13.5px]">{c.label}</span>
              <span className="engrave !text-[8.5px]">{c.hint}</span>
              {k === i && <CornerDownLeft size={12} className="text-ink-3" />}
            </button>
          ))}
          {!list.length && <div className="px-3 py-6 text-center text-[13px] text-ink-3">Nothing matches “{q}”. Try an app name, “preset” or “night”.</div>}
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ toasts
export function Toasts() {
  const toasts = useStore((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-24 left-3 right-3 z-[70] flex flex-col items-center gap-2 md:bottom-44 md:left-auto md:right-5 md:items-end" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="surface flex animate-rise items-center gap-2.5 px-3.5 py-2.5 text-[12.5px]">
          <span className="led" data-on={t.tone === "error" ? "bad" : t.tone === "ok" ? "ok" : "ember"} />
          {t.text}
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------- drop zone
export function DropZone() {
  const [active, setActive] = useState(false);
  const depth = useRef(0);
  useEffect(() => {
    const enter = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("Files")) return;
      depth.current++;
      setActive(true);
    };
    const leave = () => {
      depth.current = Math.max(0, depth.current - 1);
      if (!depth.current) setActive(false);
    };
    const over = (e: DragEvent) => e.dataTransfer?.types.includes("Files") && e.preventDefault();
    const drop = async (e: DragEvent) => {
      if (!e.dataTransfer?.files.length) return;
      e.preventDefault();
      depth.current = 0;
      setActive(false);
      const f = e.dataTransfer.files[0];
      toast(`Uploading ${f.name}…`);
      await api.upload(f, true);
      useStore.setState({ selected: "gallery" });
      toast("On the panel", "ok");
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, []);
  if (!active) return null;
  return (
    <div className="pointer-events-none fixed inset-4 z-[80] grid place-items-center rounded-[22px] border-2 border-dashed border-ember bg-black/70 backdrop-blur-sm">
      <div className="text-center">
        <Upload className="mx-auto mb-3 text-ember" size={30} />
        <div className="font-display text-[22px] font-[640]">Drop to show on the panel</div>
        <div className="engrave mt-2">PNG · JPG · GIF · WEBP — photos are LED-calibrated, pixel art stays crisp</div>
      </div>
    </div>
  );
}
