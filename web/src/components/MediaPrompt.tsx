import { useEffect, useState } from "react";
import { Camera, Mic, MonitorUp, type LucideIcon } from "lucide-react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";

/*
 * Web app only (idotmatrix.com/app/): camera / screen / sound permission for the app on the panel. The engine asks
 * for a stream (providers/webmedia.py), the page's capture add-on (web/webapp/host-media.js) tracks it and exposes
 * `window.DeskDotMedia`; this card shows its state and turns a click into the browser prompt — getDisplayMedia
 * only works from a user gesture, so `start()` is called straight from the button. Renders nothing elsewhere.
 */

type Kind = "camera" | "screen" | "audio";
type KindState = { wanted: boolean; state: string; detail: string; source: string };
type Snapshot = { caps: Record<string, boolean> } & Record<Kind, KindState>;
type MediaApi = {
  snapshot: () => Snapshot;
  start: (kind: Kind, opts?: Record<string, unknown>) => void;
  stop: (kind: Kind) => void;
};

const media = (): MediaApi | undefined => (window as unknown as { DeskDotMedia?: MediaApi }).DeskDotMedia;

const KINDS: Kind[] = ["screen", "camera", "audio"];
const ICON: Record<Kind, LucideIcon> = { camera: Camera, screen: MonitorUp, audio: Mic };

function useMedia(on: boolean): Snapshot | null {
  const [snap, setSnap] = useState<Snapshot | null>(() => (on ? media()?.snapshot() ?? null : null));
  useEffect(() => {
    if (!on) return;
    const update = (e?: Event) => setSnap((e as CustomEvent<Snapshot> | undefined)?.detail ?? media()?.snapshot() ?? null);
    update();
    window.addEventListener("deskdot-media", update);
    const late = setInterval(() => media() && update(), 2000); // the add-on loads after the studio
    return () => {
      window.removeEventListener("deskdot-media", update);
      clearInterval(late);
    };
  }, [on]);
  return snap;
}

function copy(kind: Kind, s: KindState): { title: string; action: string } {
  const system = kind === "audio" && s.source !== "mic";
  if (kind === "screen") return { title: "Share a screen to mirror", action: "Choose screen" };
  if (kind === "camera") return { title: "This app needs your camera", action: "Allow camera" };
  return system
    ? { title: "Share the sound this app reacts to", action: "Share sound" }
    : { title: "This app listens through your microphone", action: "Allow microphone" };
}

/** The stage card: one row per stream the panel's app is waiting for (or sharing). */
export function MediaPrompt() {
  const web = useStore((s) => s.meta?.platform) === "web";
  const snap = useMedia(web);
  if (!web || !snap) return null;
  const rows = KINDS.filter((k) => snap[k]?.wanted && snap[k].state !== "idle");
  if (!rows.length) return null;
  return (
    <>
      {rows.map((k) => (
        <MediaRow key={k} kind={k} s={snap[k]} />
      ))}
    </>
  );
}

function MediaRow({ kind, s }: { kind: Kind; s: KindState }) {
  const m = media();
  const Icon = ICON[kind];
  const { title, action } = copy(kind, s);
  const useMic = () => {
    m?.start("audio", { source: "mic" }); // inside the click: the prompt may need it
    void api.settings({ audio_source: "mic" });
  };
  const micOption = kind === "audio" && s.source !== "mic" && s.state !== "live";

  if (s.state === "live")
    return (
      <div className="surface flex w-full items-center gap-3 px-4 py-2 text-[12.5px] text-ink-2 animate-rise">
        <span className="led" data-on="ok" />
        <Icon size={15} className="shrink-0 text-ink-3" />
        <span className="min-w-0 flex-1 truncate">
          {kind === "camera" ? "Camera on" : kind === "screen" ? "Sharing" : "Listening"}
          {s.detail ? ` · ${s.detail}` : ""}
        </span>
        <button className="key ml-auto shrink-0" onClick={() => m?.stop(kind)}>
          Stop sharing
        </button>
      </div>
    );

  const problem = ["denied", "error", "stopped"].includes(s.state);
  return (
    <div className="surface flex w-full flex-wrap items-center gap-3 px-4 py-3 text-[12.5px] text-ink-2 animate-rise">
      <span className="led" data-on={problem ? "bad" : s.state === "unsupported" ? undefined : "warn"} />
      <Icon size={18} className="shrink-0 text-ember" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="font-[600] text-ink-1">{s.state === "unsupported" ? "Not available in this browser" : title}</span>
        {s.detail && <span className="text-[11.5px] leading-snug text-ink-3">{s.detail}</span>}
      </div>
      {s.state !== "unsupported" && (
        <div className="ml-auto flex shrink-0 flex-wrap gap-2">
          {micOption && (
            <button className="key" onClick={useMic}>
              Use microphone
            </button>
          )}
          <button className="key key-ember" disabled={s.state === "starting"} onClick={() => m?.start(kind)}>
            {s.state === "starting" ? "Waiting…" : problem ? "Try again" : action}
          </button>
        </div>
      )}
    </div>
  );
}
