import clsx from "clsx";
import { Music, Pause, Play, Repeat, SkipBack, SkipForward } from "lucide-react";
import { api } from "../lib/api";
import { appMeta, useStore } from "../lib/store";

/** What the Now Playing app reports in `engine.current.status` (see `NowPlaying.status()`). */
type MusicStatus = {
  active?: boolean;
  title?: string;
  artist?: string;
  album?: string;
  playing?: boolean;
  source_label?: string;
  art_id?: string | null;
  layout?: string;
  /** transport actions that reach the player on this computer; empty = no control here */
  actions?: string[];
};

/**
 * The music side of the full-screen view while Now Playing is on the panel: the track, the player's transport
 * (only where the computer can control the player) and a visual layout picker (each tile is the layout drawn for
 * a demo song by `GET /api/nowplaying/layouts/{id}.png`).
 */
export function MusicDeck() {
  const cur = useStore((s) => s.state?.engine.current);
  const settings = useStore((s) => s.state?.apps?.nowplaying) ?? {};
  const prop = appMeta("nowplaying")?.schema.properties?.layout;
  if (cur?.app !== "nowplaying") return null;
  const st = (cur.status ?? {}) as MusicStatus;
  const layouts = prop?.enum ?? [];
  const labels = prop?.enumLabels ?? {};
  const chosen = String(settings.layout ?? "karaoke");
  const showing = st.layout ?? chosen;
  const can = (op: string) => Array.isArray(st.actions) && st.actions.includes(op);
  const rotating = typeof settings.rotate === "string" && settings.rotate !== "off";

  return (
    <section className="flex flex-col gap-4" aria-label="Music">
      <div className="flex items-center gap-3">
        <span className="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-[10px] border border-line bg-chassis-1 text-ink-3">
          {st.art_id ? <img src={`/api/nowplaying/art?k=${st.art_id}`} alt="" className="h-full w-full object-cover" /> : <Music size={20} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="engrave">{st.active ? (st.playing ? `Playing${st.source_label ? ` · ${st.source_label}` : ""}` : "Paused") : "No music playing"}</div>
          <div className="truncate font-display text-[17px] font-[640]">{st.active ? st.title : "—"}</div>
          {st.active && <div className="truncate text-[13px] text-ink-3">{[st.artist, st.album].filter(Boolean).join(" · ")}</div>}
        </div>
        {st.active && (can("prev") || can("toggle") || can("next")) && (
          <div className="flex shrink-0 items-center gap-1.5" role="group" aria-label="Music controls">
            {can("prev") && (
              <button className="key key-icon !h-10 !w-10" onClick={() => api.nowplaying("prev")} aria-label="Previous track" title="Previous track">
                <SkipBack size={15} />
              </button>
            )}
            {can("toggle") && (
              <button className="key key-icon !h-11 !w-11 !border-ember-line !text-ember" onClick={() => api.nowplaying("toggle")} aria-label={st.playing ? "Pause music" : "Play music"} title={st.playing ? "Pause" : "Play"}>
                {st.playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" className="translate-x-[1px]" />}
              </button>
            )}
            {can("next") && (
              <button className="key key-icon !h-10 !w-10" onClick={() => api.nowplaying("next")} aria-label="Next track" title="Next track">
                <SkipForward size={15} />
              </button>
            )}
          </div>
        )}
      </div>

      {layouts.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-2">
            <span className="engrave">Layout</span>
            {rotating && (
              <span className="flex items-center gap-1 text-[11.5px] text-ink-3" title="Auto-rotate is on in the app's settings (Song change)">
                <Repeat size={11} /> rotating · showing {labels[showing] ?? showing}
              </span>
            )}
          </div>
          <div className="grid max-h-[34vh] grid-cols-[repeat(auto-fill,minmax(68px,1fr))] gap-2 overflow-y-auto pr-1" role="radiogroup" aria-label="Now Playing layout">
            {layouts.map((id) => (
              <button key={id} role="radio" aria-checked={chosen === id} title={labels[id] ?? id}
                onClick={() => api.patchSettings("nowplaying", { layout: id })}
                className={clsx("flex flex-col items-center gap-1 rounded-[10px] border p-1.5 text-[11px] transition",
                  chosen === id ? "border-ember-line bg-ember-deep/70 text-ink-1" : "border-line bg-chassis-1/80 text-ink-3 hover:text-ink-1")}>
                <span className="led-preview relative block aspect-square w-full overflow-hidden rounded-[4px] bg-black"><img src={`/api/nowplaying/layouts/${id}.png?scale=3`} alt="" loading="lazy" className="block h-full w-full [image-rendering:pixelated]" /></span>
                <span className="w-full truncate text-center">{labels[id] ?? id}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
