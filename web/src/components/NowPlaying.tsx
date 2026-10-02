import clsx from "clsx";
import { Minimize2, Play, Shuffle, SkipBack, SkipForward, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { exitFullscreen, fullscreenElement, onFullscreenChange, requestFullscreen } from "../lib/compat";
import { appMeta, useStore } from "../lib/store";
import { Icon } from "./Icon";
import { LedPanel } from "./LedPanel";
import { Countdown, Progress, usePlayback } from "./PlaylistDock";

/**
 * Full-screen "now playing", like Spotify's full-screen player: the live panel huge in the middle, what's on
 * and what's next, the transport, and the up-next strip. Opens the browser's real fullscreen too.
 * Keys: Esc closes · Space play/stop · ← / → previous / next.
 */
export function NowPlaying({ onClose }: { onClose: () => void }) {
  const { running, focus, active, cur, next, items, pl } = usePlayback();
  const shuffle = useStore((s) => s.shuffle);
  const prefs = useStore((s) => s.prefs);
  const shownApp = useStore((s) => s.state?.engine.current?.app ?? null);
  const root = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState(420);
  // the parent re-renders on every state tick: keep effects stable and read the latest callback/state from refs
  const close = useRef(onClose);
  close.current = onClose;
  const live = useRef({ running, items: items.length });
  live.current = { running, items: items.length };

  // the panel preview fills the space it has, as a square
  useEffect(() => {
    const fit = () => setSize(Math.max(200, Math.min(window.innerHeight * 0.6, window.innerWidth * 0.48, 760)));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  // real fullscreen while open; leaving the browser's fullscreen (Esc / F11) closes the view too
  useEffect(() => {
    // not allowed (iframe) or not supported (iPhone Safari): the fixed overlay still covers the window
    void requestFullscreen(root.current);
    const off = onFullscreenChange(() => {
      if (!fullscreenElement()) close.current();
    });
    return () => {
      off();
      exitFullscreen();
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const { running: on, items: n } = live.current;
      if (e.key === "Escape") close.current();
      else if (e.key === " ") {
        e.preventDefault();
        if (on || n) api.playlist(on ? "stop" : "play");
      } else if (e.key === "ArrowLeft" && on) api.playlist("prev");
      else if (e.key === "ArrowRight" && on) api.playlist("next");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const showing = appMeta(running && !focus && cur ? cur.app : shownApp ?? undefined);
  const nextMeta = appMeta(next?.app);
  const context = running ? (active ? active.name : "Your playlist") : "Showing one app";

  return (
    <div ref={root} className="nowplaying fixed inset-0 z-[60] flex flex-col overflow-hidden bg-chassis-0 text-ink-1" role="dialog" aria-modal="true" aria-label="Now playing, full screen">
      {/* ambient light from the panel, like Spotify's colour wash */}
      <div className="np-wash pointer-events-none absolute inset-0" aria-hidden />

      <header className="relative flex items-center gap-3 px-6 pt-[max(20px,env(safe-area-inset-top))]">
        <span className="led" data-on={running ? (focus ? "warn" : "ok") : undefined} />
        <span className="engrave">{running ? (active ? "Playing preset" : "Playing playlist") : "On the panel"}</span>
        <span className="truncate font-display text-[15px] font-[620] text-ink-2">{context}</span>
        <button className="key key-icon ml-auto !h-10 !w-10" onClick={onClose} title="Exit full screen (Esc)" aria-label="Exit full screen">
          <Minimize2 size={16} />
        </button>
      </header>

      <main className="relative flex min-h-0 flex-1 flex-wrap items-center justify-center gap-x-14 gap-y-6 px-6 py-4">
        <div className="np-panel shrink-0" style={{ width: size, height: size }}>
          <LedPanel size={size} lookSwitch={false} />
        </div>

        <div className="flex w-[min(440px,90vw)] flex-col gap-5">
          <div className="flex items-center gap-4">
            <span className="grid h-14 w-14 shrink-0 place-items-center rounded-[14px] border border-[#7a2a12] bg-ember-deep text-ember">
              <Icon name={showing?.icon ?? "square"} size={24} />
            </span>
            <div className="min-w-0">
              <div className="engrave">Now showing</div>
              <h1 className="truncate font-display text-[clamp(28px,4vw,46px)] font-[680] leading-[1.05] tracking-[-0.02em]">{showing?.name ?? "—"}</h1>
            </div>
          </div>
          {showing?.description && <p className="text-[14px] leading-snug text-ink-3">{showing.description}</p>}

          {running && !focus && cur ? (
            <div>
              <Progress duration={cur.duration} className="!h-[5px]" />
              <div className="mt-2 flex items-center justify-between font-mono text-[12px] text-ink-3">
                <span><Countdown /> left</span>
                {nextMeta && <span className="truncate pl-4">Next: <span className="text-ink-1">{nextMeta.name}</span></span>}
              </div>
            </div>
          ) : (
            <p className="text-[13px] text-ink-3">
              {focus ? "Paused for a moment: something else took over the panel." : items.length ? "Press play to rotate your playlist." : "Pick a preset to rotate apps automatically."}
            </p>
          )}

          <div className="flex items-center gap-3" role="group" aria-label="Playback controls">
            <button className="key key-icon !h-12 !w-12" disabled={!running} onClick={() => api.playlist("prev")} aria-label="Previous" title="Previous (←)">
              <SkipBack size={18} />
            </button>
            <button className={clsx("np-play grid h-16 w-16 place-items-center rounded-full transition", running ? "bg-ink-1 text-chassis-0" : "bg-ember text-chassis-0")}
              disabled={!running && !items.length} onClick={() => api.playlist(running ? "stop" : "play")}
              aria-label={running ? "Stop playlist" : "Play playlist"} title={running ? "Stop (Space)" : "Play (Space)"}>
              {running ? <Square size={18} fill="currentColor" /> : <Play size={22} fill="currentColor" className="translate-x-[1px]" />}
            </button>
            <button className="key key-icon !h-12 !w-12" disabled={!running} onClick={() => api.playlist("next")} aria-label="Next" title="Next (→)">
              <SkipForward size={18} />
            </button>
            <button className={clsx("key ml-auto !h-12", shuffle && "!border-[#7a2a12] !text-ember")} aria-pressed={shuffle} onClick={() => prefs({ shuffle: !shuffle })}>
              <Shuffle size={14} /> Shuffle
            </button>
          </div>
        </div>
      </main>

      {pl && pl.items.length > 0 && (
        <footer className="relative border-t border-line/70 px-6 pb-[max(18px,env(safe-area-inset-bottom))] pt-3">
          <div className="engrave mb-2">Up next</div>
          <div className="flex gap-2 overflow-x-auto pb-1" role="list">
            {pl.items.map((it, i) => {
              const m = appMeta(it.app);
              const isCur = running && !focus && pl.current_item === it.id;
              return (
                <div key={it.id} role="listitem" className={clsx("flex w-[176px] shrink-0 items-center gap-2 rounded-[10px] border p-2.5",
                  isCur ? "border-[#7a2a12] bg-ember-deep/70" : "border-line bg-chassis-1/80", !it.enabled && "opacity-40")}>
                  <span className={clsx("font-mono text-[9px] tabular-nums", isCur ? "text-ember" : "text-ink-4")}>{String(i + 1).padStart(2, "0")}</span>
                  <Icon name={m?.icon ?? "square"} size={14} className={isCur ? "text-ember" : "text-ink-2"} />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-[560]">{m?.name ?? it.app}</span>
                  <span className="font-mono text-[10px] text-ink-4">{it.duration}s</span>
                </div>
              );
            })}
          </div>
        </footer>
      )}
    </div>
  );
}
