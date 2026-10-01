import clsx from "clsx";
import { Check, ChevronDown, ChevronUp, GripVertical, Plus, Save, Search, Shuffle, SkipBack, SkipForward, Square, Play, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, loadPresets } from "../lib/api";
import { EMPTY_LIST, appMeta, toast, useStore } from "../lib/store";
import type { AppMeta, PlaylistItem, Preset } from "../lib/types";
import { Icon } from "./Icon";

/**
 * Playback: the ONE place that answers "what's playing, what's next".
 * Presets (one tap = a whole rotation), the transport, and the playlist editor (the "queue").
 * `variant="dock"` is the desktop footer; `variant="sheet"` is the phone's Play tab.
 */

type Variant = "dock" | "sheet";

function usePlayback() {
  const pl = useStore((s) => s.state?.engine.playlist);
  const mode = useStore((s) => s.state?.engine.mode);
  const focus = useStore((s) => s.state?.engine.focus);
  const activeId = useStore((s) => s.state?.engine.active_preset ?? null);
  const presets = useStore((s) => s.presets);
  const running = !!pl && mode === "playlist" && pl.enabled;
  const active = presets?.find((p) => p.id === activeId) ?? null;
  const items = pl?.items ?? (EMPTY_LIST as unknown as PlaylistItem[]);
  const curIdx = items.findIndex((it) => it.id === pl?.current_item);
  let next: PlaylistItem | null = null;
  if (running && items.length > 1) {
    for (let k = 1; k <= items.length; k++) {
      const it = items[(Math.max(0, curIdx) + k) % items.length];
      if (it.enabled && it.id !== pl?.current_item) { next = it; break; }
    }
  }
  const cur = curIdx >= 0 ? items[curIdx] : null;
  return { pl, running, focus, active, activeId, cur, next, items };
}

/** A thin bar that fills while the current playlist item is on screen (animated locally, no re-renders). */
function Progress({ duration, className }: { duration: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const { state, stateAt } = useStore.getState();
      const rem = state?.engine.playlist.remaining;
      if (ref.current && rem != null) {
        const left = Math.max(0, rem - (performance.now() - stateAt) / 1000);
        ref.current.style.width = `${Math.min(100, (1 - left / duration) * 100)}%`;
      }
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [duration]);
  return (
    <div className={clsx("h-[3px] overflow-hidden rounded-full bg-chassis-4", className)}>
      <div ref={ref} className="h-full w-0 rounded-full bg-ember shadow-[0_0_8px_var(--color-ember)]" />
    </div>
  );
}

/** Seconds left on the current item, ticking locally. */
function Countdown() {
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const { state, stateAt } = useStore.getState();
  const rem = state?.engine.playlist.remaining;
  if (rem == null) return null;
  const left = Math.max(0, Math.ceil(rem - (performance.now() - stateAt) / 1000));
  return <span className="tabular-nums">{left} s</span>;
}

async function play(p: Preset) {
  const shuffle = useStore.getState().shuffle;
  await api.playPreset(p.id, shuffle);
  toast(`Playing ${p.name}${shuffle ? " · shuffled" : ""}`, "ok");
}

// ------------------------------------------------------------------ preset cards
function PresetCard({ p, active, variant }: { p: Preset; active: boolean; variant: Variant }) {
  const [confirm, setConfirm] = useState(false);
  const n = p.items.length;
  if (confirm) {
    return (
      <div className={clsx("flex shrink-0 items-center gap-2 rounded-[11px] border border-bad/40 bg-bad/10 px-3", variant === "dock" ? "h-12" : "h-16")}>
        <span className="text-[12.5px] text-ink-1">Delete “{p.name}”?</span>
        <button className="key !h-8 !px-2.5 !text-bad" onClick={async () => { await api.deletePreset(p.id); setConfirm(false); toast("Preset deleted", "ok"); loadPresets(); }}>
          <Trash2 size={12} /> Delete
        </button>
        <button className="key key-ghost !h-8 !px-2" onClick={() => setConfirm(false)}>Keep</button>
      </div>
    );
  }
  return (
    <div className={clsx("group relative shrink-0", variant === "sheet" && "min-w-0")}>
      <button
        onClick={() => play(p)}
        aria-pressed={active}
        title={active ? `${p.name} is playing — tap to restart it` : `Play ${p.name}: ${n} app${n === 1 ? "" : "s"} in a row`}
        className={clsx(
          "flex w-full items-center gap-2.5 rounded-[11px] border text-left transition",
          variant === "dock" ? "h-12 min-w-[150px] max-w-[220px] pl-2 pr-3.5" : "h-16 px-3",
          active
            ? "border-[#8a3216] bg-ember-deep/70 shadow-[0_0_26px_-12px_var(--color-ember)]"
            : "border-line bg-chassis-1 hover:-translate-y-px hover:border-line-2 hover:bg-chassis-2",
        )}
      >
        <span className={clsx("grid shrink-0 place-items-center rounded-[8px] border",
          variant === "dock" ? "h-8 w-8" : "h-10 w-10",
          active ? "border-[#8a3216] bg-black/30 text-ember" : "border-line-2 bg-chassis-3 text-ink-2 group-hover:text-ink-1")}>
          <Icon name={p.icon || "list-music"} size={variant === "dock" ? 15 : 18} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-[600] leading-tight tracking-[-0.01em]">{p.name}</span>
          <span className={clsx("mt-0.5 flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-wider", active ? "text-ember" : "text-ink-3")}>
            {active && <span className="led !h-[6px] !w-[6px] animate-pulse-dot" data-on="ember" />}
            {active ? "Playing" : `${n} app${n === 1 ? "" : "s"}`}
            {!p.builtin && !active && <span className="text-ink-4">· yours</span>}
          </span>
        </span>
      </button>
      {!p.builtin && (
        <button onClick={() => setConfirm(true)} title={`Delete ${p.name}`} aria-label={`Delete preset ${p.name}`}
          className="absolute -right-1.5 -top-1.5 grid h-6 w-6 place-items-center rounded-full border border-line-2 bg-chassis-3 text-ink-3 opacity-0 shadow transition hover:text-bad focus:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
          <X size={11} />
        </button>
      )}
    </div>
  );
}

function SavePreset({ variant, disabled }: { variant: Variant; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const save = async () => {
    const n = name.trim();
    if (!n) return;
    await api.savePreset(n);
    toast(`Saved “${n}” — tap it any time to play it again`, "ok");
    setName("");
    setOpen(false);
    loadPresets();
  };
  const h = variant === "dock" ? "h-12" : "h-16";
  if (!open) {
    return (
      <button disabled={disabled} onClick={() => setOpen(true)}
        title={disabled ? "Add some apps to the playlist first" : "Save the current playlist as your own preset"}
        className={clsx("flex shrink-0 items-center gap-2 rounded-[11px] border border-dashed border-line-2 px-3.5 text-[12.5px] text-ink-3 transition hover:border-ember hover:text-ember disabled:pointer-events-none disabled:opacity-40", h)}>
        <Save size={14} /> Save as preset
      </button>
    );
  }
  return (
    <form className={clsx("flex shrink-0 items-center gap-1.5 rounded-[11px] border border-ember/50 bg-chassis-1 px-2", h)}
      onSubmit={(e) => { e.preventDefault(); save(); }}>
      <input autoFocus value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="Name it, e.g. Morning"
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)} aria-label="Preset name"
        className="field !h-8 !w-44 !text-[12.5px]" />
      <button type="submit" className="key key-icon !h-8 !w-8" title="Save" disabled={!name.trim()}><Check size={14} /></button>
      <button type="button" className="key key-ghost key-icon !h-8 !w-8" title="Cancel" onClick={() => setOpen(false)}><X size={14} /></button>
    </form>
  );
}

function PresetSkeleton({ variant }: { variant: Variant }) {
  return (
    <>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className={clsx("skeleton shrink-0 rounded-[11px]", variant === "dock" ? "h-12 w-[160px]" : "h-16")} />
      ))}
    </>
  );
}

export function PresetList({ variant }: { variant: Variant }) {
  const presets = useStore((s) => s.presets);
  const { activeId, running, items } = usePlayback();
  const mine = presets?.filter((p) => !p.builtin) ?? [];
  const builtin = presets?.filter((p) => p.builtin) ?? [];
  const cards = (list: Preset[]) => list.map((p) => <PresetCard key={p.id} p={p} active={running && activeId === p.id} variant={variant} />);
  if (variant === "dock") {
    return (
      <div className="-mx-1 flex min-w-0 gap-2 overflow-x-auto px-1 pb-1 pt-1.5" role="list" aria-label="Presets">
        {presets === null ? <PresetSkeleton variant={variant} /> : <>{cards(mine)}{cards(builtin)}</>}
        <SavePreset variant={variant} disabled={!items.length} />
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {mine.length > 0 && (
        <div>
          <div className="engrave mb-2">Your presets</div>
          <div className="grid grid-cols-2 gap-2">{cards(mine)}</div>
        </div>
      )}
      <div>
        {mine.length > 0 && <div className="engrave mb-2">Ready-made</div>}
        <div className="grid grid-cols-2 gap-2">{presets === null ? <PresetSkeleton variant={variant} /> : cards(builtin)}</div>
      </div>
      <SavePreset variant={variant} disabled={!items.length} />
    </div>
  );
}

// ---------------------------------------------------------------- transport
function Transport({ variant }: { variant: Variant }) {
  const { running, focus, active, cur, next, items } = usePlayback();
  const shuffle = useStore((s) => s.shuffle);
  const queueOpen = useStore((s) => s.queueOpen);
  const prefs = useStore((s) => s.prefs);
  const curMeta = appMeta(cur?.app);
  const nextMeta = appMeta(next?.app);
  const big = variant === "sheet";
  const k = big ? "!h-11 !w-11" : "!h-9 !w-9";
  const title = running ? (active ? active.name : "Your playlist") : "Showing one app";
  const sub = running
    ? focus ? "Paused for a moment — something else took over the panel" : null
    : items.length ? "Tap a preset to rotate apps automatically, or resume your playlist" : "Tap a preset to rotate apps automatically";

  return (
    <div className={clsx("flex min-w-0 items-center gap-3", big && "flex-wrap")}>
      <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Playback controls">
        <button className={clsx("key key-icon", k)} title="Previous app (←)" aria-label="Previous" disabled={!running} onClick={() => api.playlist("prev")}>
          <SkipBack size={14} />
        </button>
        <button className={clsx("key key-icon", k, running && "!text-ember")} disabled={!running && !items.length}
          title={running ? "Stop — keep showing the current app" : "Resume the playlist"} aria-label={running ? "Stop playlist" : "Play playlist"}
          onClick={() => api.playlist(running ? "stop" : "play")}>
          {running ? <Square size={12} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
        </button>
        <button className={clsx("key key-icon", k)} title="Next app (→)" aria-label="Next" disabled={!running} onClick={() => api.playlist("next")}>
          <SkipForward size={14} />
        </button>
      </div>

      <div className={clsx("min-w-0 flex-1", big && "basis-full order-first")}>
        <div className="flex items-center gap-2">
          <span className="led shrink-0" data-on={running ? (focus ? "warn" : "ok") : undefined} />
          <span className="engrave shrink-0 !text-[8.5px]">{running ? (active ? "Preset" : "Playlist") : "Playback"}</span>
          <span className={clsx("truncate font-display font-[640] tracking-[-0.015em]", big ? "text-[18px]" : "text-[14.5px]")}>{title}</span>
        </div>
        {running && !focus && cur ? (
          <div className="mt-1 flex min-w-0 items-center gap-2 text-[11.5px] text-ink-3">
            <span className="truncate text-ink-2">{curMeta?.name ?? cur.app}</span>
            <span className="shrink-0 font-mono text-[10.5px] text-ink-4"><Countdown /></span>
            <Progress duration={cur.duration} className="min-w-[40px] max-w-[160px] flex-1" />
            {nextMeta && <span className="hidden truncate sm:inline">Next: <span className="text-ink-2">{nextMeta.name}</span></span>}
          </div>
        ) : (
          sub && <div className="mt-0.5 truncate text-[11.5px] text-ink-3">{sub}</div>
        )}
      </div>

      <button className={clsx("key shrink-0", big ? "!h-11" : "!h-9", shuffle && "!border-[#7a2a12] !text-ember")} aria-pressed={shuffle}
        title={shuffle ? "Shuffle is on — presets play in random order" : "Shuffle presets"} onClick={() => prefs({ shuffle: !shuffle })}>
        <Shuffle size={13} /> <span className={variant === "dock" ? "hidden 2xl:inline" : ""}>Shuffle</span>
      </button>
      {variant === "dock" && (
        <button className="key shrink-0 !h-9" aria-expanded={queueOpen} onClick={() => prefs({ queueOpen: !queueOpen })}
          title={queueOpen ? "Hide the playlist editor" : "Edit what plays and for how long"}>
          Edit playlist <span className="rounded bg-chassis-0 px-1.5 py-0.5 text-[9px] text-ink-3">{items.length}</span>
          {queueOpen ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
        </button>
      )}
    </div>
  );
}

// -------------------------------------------------------------------- queue
function AddApp({ onAdd, variant }: { onAdd: (id: string) => void; variant: Variant }) {
  const apps = useStore((s) => s.meta?.apps ?? EMPTY_LIST) as AppMeta[];
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const list = useMemo(() => {
    const f = q.trim().toLowerCase();
    return apps.filter((a) => !f || `${a.name} ${a.description}`.toLowerCase().includes(f)).slice(0, 60);
  }, [apps, q]);
  return (
    <div className={clsx("relative shrink-0", variant === "sheet" && "w-full")}>
      <button onClick={() => setOpen((a) => !a)} aria-expanded={open}
        className={clsx("flex items-center justify-center gap-2 rounded-[10px] border border-dashed border-line-2 text-[12px] text-ink-3 transition hover:border-ember hover:text-ember",
          variant === "dock" ? "h-full min-h-[64px] w-[92px] flex-col" : "h-12 w-full")}>
        <Plus size={16} /> Add app
      </button>
      {open && (
        <div className={clsx("surface z-40 flex max-h-80 w-64 flex-col p-1.5",
          variant === "dock" ? "fixed bottom-24 right-6" : "absolute bottom-full left-0 mb-2 w-full")}
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
          <label className="relative mb-1 block">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-4" />
            <input autoFocus className="field !h-8 !pl-8 !text-[12.5px]" placeholder="Find an app" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <div className="min-h-0 overflow-y-auto">
            {list.map((a) => (
              <button key={a.id} className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-chassis-3"
                onClick={() => { onAdd(a.id); setOpen(false); setQ(""); }}>
                <Icon name={a.icon} size={14} className="text-ink-2" /> {a.name}
              </button>
            ))}
            {!list.length && <p className="px-3 py-4 text-center text-[12px] text-ink-3">No app matches.</p>}
          </div>
          <button className="key key-ghost mt-1 !h-8" onClick={() => setOpen(false)}>Close</button>
        </div>
      )}
    </div>
  );
}

function Queue({ variant }: { variant: Variant }) {
  const { pl, running, focus } = usePlayback();
  const drag = useRef<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  if (!pl) return null;
  const save = (items: PlaylistItem[]) => api.putPlaylist(pl.enabled, items);
  const patch = (i: number, p: Partial<PlaylistItem>) => save(pl.items.map((it, k) => (k === i ? { ...it, ...p } : it)));
  const add = (app: string) =>
    save([...pl.items, { id: "", app, duration: 15, settings: {}, enabled: true }].map(({ id, ...r }) => (id ? { id, ...r } : r)) as PlaylistItem[]);
  const move = (from: number, to: number) => {
    if (to < 0 || to >= pl.items.length || from === to) return;
    const items = [...pl.items];
    const [m] = items.splice(from, 1);
    items.splice(to, 0, m);
    save(items);
  };

  return (
    <div className={clsx(variant === "dock" ? "flex min-w-0 gap-2 overflow-x-auto border-t border-line pb-1 pt-2.5" : "space-y-1.5")}>
      {!pl.items.length && (
        <p className={clsx("text-[12.5px] text-ink-3", variant === "dock" ? "self-center px-2" : "py-2")}>
          The playlist is empty — play a preset, or add apps one by one.
        </p>
      )}
      {pl.items.map((it, i) => {
        const m = appMeta(it.app);
        const isCur = running && !focus && pl.current_item === it.id;
        const overrides = Object.keys(it.settings ?? {}).length;
        return (
          <div key={it.id} draggable
            onDragStart={() => (drag.current = i)}
            onDragOver={(e) => { e.preventDefault(); setOver(i); }}
            onDragLeave={() => setOver(null)}
            onDrop={() => { setOver(null); if (drag.current != null) move(drag.current, i); }}
            className={clsx(
              "group relative flex shrink-0 rounded-[10px] border transition",
              variant === "dock" ? "w-[168px] cursor-grab flex-col gap-2 p-2.5 active:cursor-grabbing" : "items-center gap-2.5 p-2",
              isCur ? "border-[#7a2a12] bg-ember-deep/60" : "border-line bg-chassis-1 hover:border-line-2",
              !it.enabled && "opacity-45",
              over === i && "ring-1 ring-ember",
            )}>
            <div className="flex min-w-0 flex-1 items-center gap-2">
              {variant === "dock" ? (
                <span className={clsx("font-mono text-[9px] tabular-nums", isCur ? "text-ember" : "text-ink-4")}>{String(i + 1).padStart(2, "0")}</span>
              ) : (
                <GripVertical size={14} className="shrink-0 text-ink-4" />
              )}
              <Icon name={m?.icon ?? "square"} size={14} className={clsx("shrink-0", isCur ? "text-ember" : "text-ink-2")} />
              <span className="min-w-0 flex-1 truncate text-[12.5px] font-[560]">{m?.name ?? it.app}</span>
              {overrides > 0 && <span className="engrave !text-[8px] !text-info" title={`Own settings: ${JSON.stringify(it.settings)}`}>+{overrides}</span>}
            </div>
            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-1 rounded-md bg-chassis-0 px-1.5" title="Seconds on screen">
                <input type="number" min={3} max={3600} defaultValue={it.duration} aria-label={`Seconds for ${m?.name ?? it.app}`}
                  onBlur={(e) => +e.target.value !== it.duration && patch(i, { duration: Math.max(3, +e.target.value) })}
                  onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                  className="w-10 bg-transparent py-1 font-mono text-[11px] text-ink-2 outline-none focus:text-ink-1" />
                <span className="font-mono text-[9px] text-ink-4">s</span>
              </label>
              {variant === "sheet" && (
                <>
                  <button className="key key-ghost key-icon !h-9 !w-9" aria-label="Move up" disabled={i === 0} onClick={() => move(i, i - 1)}><ChevronUp size={14} /></button>
                  <button className="key key-ghost key-icon !h-9 !w-9" aria-label="Move down" disabled={i === pl.items.length - 1} onClick={() => move(i, i + 1)}><ChevronDown size={14} /></button>
                </>
              )}
              <button role="switch" aria-checked={it.enabled} aria-label={`Include ${m?.name ?? it.app}`} title={it.enabled ? "Included — tap to skip it" : "Skipped — tap to include it"}
                className="toggle ml-auto scale-[0.8]" onClick={() => patch(i, { enabled: !it.enabled })} />
              <button onClick={() => save(pl.items.filter((_, k) => k !== i))} title="Remove from playlist" aria-label={`Remove ${m?.name ?? it.app}`}
                className="grid h-7 w-7 place-items-center rounded-md text-ink-4 transition hover:bg-chassis-3 hover:text-bad">
                <X size={13} />
              </button>
            </div>
            {isCur && variant === "dock" && <Progress duration={it.duration} className="absolute inset-x-2 bottom-1 !h-[2px]" />}
          </div>
        );
      })}
      <AddApp onAdd={add} variant={variant} />
    </div>
  );
}

// ---------------------------------------------------------------- exports
export function PlaylistDock() {
  const pl = useStore((s) => s.state?.engine.playlist);
  const queueOpen = useStore((s) => s.queueOpen);
  if (!pl) return <div className="skeleton h-[108px] rounded-[14px]" />;
  return (
    <footer className="surface flex shrink-0 flex-col p-2.5 pb-1.5" aria-label="Playback">
      <Transport variant="dock" />
      <PresetList variant="dock" />
      {queueOpen && <Queue variant="dock" />}
    </footer>
  );
}

/** Phone: the Play tab. */
export function PlaybackSheet() {
  const pl = useStore((s) => s.state?.engine.playlist);
  if (!pl) return <div className="skeleton h-40 rounded-[14px]" />;
  return (
    <div className="space-y-4">
      <section className="surface p-3.5"><Transport variant="sheet" /></section>
      <section>
        <h2 className="mb-1 font-display text-[18px] font-[640] tracking-[-0.015em]">Play a preset</h2>
        <p className="mb-3 text-[12.5px] text-ink-3">One tap fills the playlist and starts rotating — every game, all the pets, a desk dashboard…</p>
        <PresetList variant="sheet" />
      </section>
      <section>
        <h2 className="mb-2 font-display text-[16px] font-[640] tracking-[-0.015em]">Up next</h2>
        <Queue variant="sheet" />
      </section>
    </div>
  );
}
