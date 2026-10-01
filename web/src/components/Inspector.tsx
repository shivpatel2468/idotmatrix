import { LayoutGrid, ListPlus, Play, RotateCcw } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../lib/api";
import { appMeta, isPhone, toast, useStore } from "../lib/store";
import { CATEGORY_LABEL, Icon } from "./Icon";
import { SchemaForm } from "./SchemaForm";

/** Settings for the selected app (defaults to whatever is on screen). */
export function Inspector({ fill = false }: { fill?: boolean }) {
  const selected = useStore((s) => s.selected);
  const current = useStore((s) => s.state?.engine.current?.app ?? null);
  const settings = useStore((s) => s.state?.apps);
  const playlist = useStore((s) => s.state?.engine.playlist);
  const meta0 = useStore((s) => s.meta);
  const id = selected ?? current;
  const meta = appMeta(id);
  const pending = useRef<Record<string, unknown>>({});
  const timer = useRef(0);
  const [confirmReset, setConfirmReset] = useState(false);

  if (!meta) {
    return (
      <aside className={`surface inspector-box flex flex-col items-center justify-center gap-3 p-8 text-center ${fill ? "flex-1" : ""}`}>
        {!meta0 ? (
          <div className="w-full space-y-3">
            <div className="skeleton h-10 w-2/3 rounded-lg" />
            <div className="skeleton h-9 rounded-lg" />
            <div className="skeleton h-24 rounded-lg" />
          </div>
        ) : (
          <>
            <span className="grid h-11 w-11 place-items-center rounded-full border border-line bg-chassis-0 text-ink-3"><LayoutGrid size={18} /></span>
            <p className="text-[13px] text-ink-2">Pick an app to see its settings.</p>
            <button className="key" onClick={() => (isPhone() ? useStore.setState({ mobileTab: "apps" }) : useStore.setState({ drawer: window.innerWidth < 768 ? "library" : null }))}>
              Browse apps
            </button>
          </>
        )}
      </aside>
    );
  }
  const value = settings?.[meta.id] ?? {};
  const live = meta.id === current;

  // coalesce rapid edits (faders) into one PATCH
  const change = (patch: Record<string, unknown>) => {
    Object.assign(pending.current, patch);
    useStore.setState((s) =>
      s.state ? { state: { ...s.state, apps: { ...s.state.apps, [meta.id]: { ...value, ...patch } } } } : {},
    );
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const p = pending.current;
      pending.current = {};
      api.patchSettings(meta.id, p);
    }, 160);
  };

  const addToPlaylist = async () => {
    if (!playlist) return;
    await api.putPlaylist(playlist.enabled, [...playlist.items, { app: meta.id, duration: 15, settings: {}, enabled: true }]);
    toast(`${meta.name} added to the playlist`, "ok");
  };

  const reset = async () => {
    const defaults = Object.fromEntries(Object.entries(meta.schema.properties ?? {}).map(([k, p]) => [k, p.default]));
    await api.patchSettings(meta.id, defaults);
    setConfirmReset(false);
    toast(`${meta.name} is back to its defaults`, "ok");
  };
  const hasSettings = Object.keys(meta.schema.properties ?? {}).length > 0;

  return (
    <aside className={`surface inspector-box flex min-h-0 flex-col overflow-hidden ${fill ? "flex-1" : ""}`} aria-label={`${meta.name} settings`}>
      <div className="border-b border-line p-4">
        <div className="flex items-start gap-3">
          <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-[10px] border ${live ? "border-[#7a2a12] bg-ember-deep text-ember" : "border-line-2 bg-chassis-3 text-ink-1"}`}>
            <Icon name={meta.icon} size={18} />
          </span>
          <div className="min-w-0">
            <div className="engrave flex items-center gap-1.5 !text-[8.5px]">
              {live ? <><span className="led !h-[6px] !w-[6px]" data-on="ember" /> On the panel now</> : CATEGORY_LABEL[meta.category] ?? "App"}
            </div>
            <h2 className="font-display text-[20px] font-[660] leading-tight tracking-[-0.02em]">{meta.name}</h2>
            <p className="mt-1 text-[12.5px] leading-snug text-ink-3">{meta.description}</p>
          </div>
        </div>
        <div className="mt-4 flex gap-2">
          <button className={live ? "key flex-1 !h-10" : "key key-ember flex-1 !h-10"} onClick={() => api.activate(meta.id)}
            title={live ? "Already on the panel — press to restart it" : "Show this app on the panel now"}>
            <Play size={12} fill="currentColor" /> {live ? "Showing now" : "Show on panel"}
          </button>
          <button className="key !h-10" title="Add to the end of the playlist" onClick={addToPlaylist}>
            <ListPlus size={14} /> <span className="normal-case tracking-normal">Playlist</span>
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <SchemaForm schema={meta.schema} value={value} onChange={change} />
        <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <p className="flex-1 text-[11.5px] text-ink-4">
            {hasSettings ? <>Changes apply as you go and are saved.{live ? "" : " Press Show on panel to see them."}</> : null}
          </p>
          {hasSettings && (confirmReset ? (
            <span className="flex items-center gap-1.5">
              <span className="text-[11.5px] text-ink-2">Reset all?</span>
              <button className="key !h-8 !px-2.5" onClick={reset}>Reset</button>
              <button className="key key-ghost !h-8 !px-2" onClick={() => setConfirmReset(false)}>Cancel</button>
            </span>
          ) : (
            <button className="key key-ghost !h-8 !px-2.5" onClick={() => setConfirmReset(true)} title="Put every setting back to its default">
              <RotateCcw size={12} /> Defaults
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
