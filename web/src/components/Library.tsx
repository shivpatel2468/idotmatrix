import clsx from "clsx";
import { openCasino } from "./casino/state";
import { LayoutGrid, List, Search, Star, X } from "lucide-react";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { EMPTY_LIST, inspect, useStore } from "../lib/store";
import type { AppMeta } from "../lib/types";
import { CATEGORY_LABEL, CATEGORY_ORDER, Icon } from "./Icon";

function hash(v: unknown): string {
  const s = JSON.stringify(v ?? {});
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

/** A live thumbnail of what an app shows — rendered by the engine in a sandbox, masked into LEDs. */
const Preview = memo(function Preview({ id }: { id: string }) {
  const settings = useStore((s) => s.state?.apps?.[id]);
  const v = hash(settings);
  const [loaded, setLoaded] = useState(false);
  return (
    <div className={clsx("led-preview relative aspect-square w-full overflow-hidden rounded-[8px] bg-black", !loaded && "skeleton")}>
      <img src={`/api/apps/${id}/preview.gif?v=${v}`} alt="" loading="lazy" decoding="async" draggable={false} onLoad={() => setLoaded(true)}
        className={clsx("h-full w-full transition-opacity duration-300 [image-rendering:pixelated]", loaded ? "opacity-100" : "opacity-0")} />
      <span className="led-mask pointer-events-none absolute inset-0" />
    </div>
  );
});

type CardProps = { a: AppMeta; live: boolean; selected: boolean; fav: boolean; onPick: () => void; onFav: () => void };

/** The web app only: apps that can't run in a browser tab get a badge and the reason as a tooltip. */
function useOffWeb(a: AppMeta): string | null {
  const web = useStore((s) => s.meta?.platform === "web");
  return web && a.supported === false ? a.schema.webReason ?? "Needs the desktop app." : null;
}

function OffWebBadge({ why }: { why: string }) {
  return <span title={why} className="engrave shrink-0 rounded-full bg-warn/15 px-1.5 py-0.5 !text-[7.5px] !text-warn">Not on Browser</span>;
}

function GridCard({ a, live, selected, fav, onPick, onFav }: CardProps) {
  const offWeb = useOffWeb(a);
  return (
    <div role="button" tabIndex={0} onClick={onPick} onDoubleClick={() => api.activate(a.id)}
      onKeyDown={(e) => { if (e.key === "Enter") api.activate(a.id); if (e.key === " ") { e.preventDefault(); onPick(); } }}
      title={`${a.description}${offWeb ? `\n\nNot on Browser: ${offWeb}` : ""}\n\nClick for settings · double-click to show`} aria-label={`${a.name}${live ? " (on the panel)" : ""}`}
      className={clsx("group relative cursor-pointer rounded-[12px] border p-1.5 transition", offWeb && !live && "opacity-60",
        live ? "border-[#7a2a12] bg-ember-deep/40 shadow-[0_0_24px_-10px_var(--color-ember)]"
          : selected ? "border-line-2 bg-chassis-3" : "border-line bg-chassis-1 hover:-translate-y-px hover:border-line-2 hover:bg-chassis-2")}>
      <Preview id={a.id} />
      <div className="mt-1.5 flex items-center gap-1.5 px-0.5">
        <span className="min-w-0 flex-1 truncate text-[12px] font-[560] tracking-[-0.01em]">{a.name}</span>
        {offWeb && <OffWebBadge why={offWeb} />}
        <button onClick={(e) => { e.stopPropagation(); onFav(); }} title={fav ? "Remove from favourites" : "Add to favourites"} aria-label={fav ? `Unstar ${a.name}` : `Star ${a.name}`} aria-pressed={fav}
          className={clsx("shrink-0 rounded p-0.5 transition focus:opacity-100", fav ? "text-gold" : "text-ink-4 opacity-0 hover:text-ink-1 group-hover:opacity-100 [@media(hover:none)]:opacity-60")}>
          <Star size={12} fill={fav ? "currentColor" : "none"} />
        </button>
      </div>
      {live ? (
        <span className="engrave absolute left-3 top-3 flex items-center gap-1 rounded-full bg-black/70 px-1.5 py-0.5 !text-[7.5px] !text-ember backdrop-blur">
          <span className="led !h-[5px] !w-[5px]" data-on="ember" /> Live
        </span>
      ) : (
        <button title="Show on the panel now" aria-label={`Show ${a.name} now`} onClick={(e) => { e.stopPropagation(); api.activate(a.id); }}
          className="tile-play absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-full bg-black/70 text-ink-1 opacity-0 backdrop-blur transition hover:bg-ember hover:text-black focus:opacity-100 group-hover:opacity-100">
          <Icon name="play" size={12} fill="currentColor" />
        </button>
      )}
    </div>
  );
}

function ListRow({ a, live, selected, fav, onPick, onFav }: CardProps) {
  const offWeb = useOffWeb(a);
  return (
    <div role="button" tabIndex={0} onClick={onPick} onDoubleClick={() => api.activate(a.id)}
      onKeyDown={(e) => { if (e.key === "Enter") api.activate(a.id); if (e.key === " ") { e.preventDefault(); onPick(); } }}
      aria-label={`${a.name}${live ? " (on the panel)" : ""}`}
      className={clsx("group relative flex cursor-pointer items-center gap-3 rounded-[10px] px-2 py-1.5 transition",
        selected ? "bg-chassis-3" : "hover:bg-chassis-2")}>
      {live && <span className="absolute bottom-2 left-0 top-2 w-[2px] rounded-full bg-ember shadow-[0_0_8px_var(--color-ember)]" />}
      <div className="w-10 shrink-0"><Preview id={a.id} /></div>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 truncate text-[13px] font-[560]">
          {a.name}
          {live && <span className="engrave !text-[7.5px] !text-ember">Live</span>}
          {offWeb && <OffWebBadge why={offWeb} />}
        </span>
        <span className="block truncate text-[11px] text-ink-3">{a.description}</span>
      </span>
      <button onClick={(e) => { e.stopPropagation(); onFav(); }} aria-label={fav ? `Unstar ${a.name}` : `Star ${a.name}`} aria-pressed={fav}
        className={clsx("rounded p-1 focus:opacity-100", fav ? "text-gold" : "text-ink-4 opacity-0 hover:text-ink-1 group-hover:opacity-100 [@media(hover:none)]:opacity-60")}>
        <Star size={12} fill={fav ? "currentColor" : "none"} />
      </button>
      <button title="Show on the panel now" aria-label={`Show ${a.name} now`} onClick={(e) => { e.stopPropagation(); api.activate(a.id); }}
        className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-[8px] transition hover:bg-chassis-4 hover:text-ember focus:opacity-100",
          live ? "text-ember" : "text-ink-3 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100")}>
        <Icon name="play" size={12} fill="currentColor" />
      </button>
    </div>
  );
}

function Skeleton({ view, size }: { view: "grid" | "list"; size: number }) {
  return view === "grid" ? (
    <div className="grid gap-2.5" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${size}px, 1fr))` }}>
      {Array.from({ length: 9 }, (_, i) => <div key={i} className="skeleton aspect-[1/1.18] rounded-[12px]" />)}
    </div>
  ) : (
    <div className="space-y-2">{Array.from({ length: 10 }, (_, i) => <div key={i} className="skeleton h-12 rounded-[10px]" />)}</div>
  );
}

/** Every app, grouped by category, with live previews. Click = settings; ▶ / double-click = show on the panel. */
export function Library({ fill = false, flat = false }: {
  fill?: boolean;
  flat?: boolean; // phones: no card, no inner scroll — the tab scrolls, the search row sticks to its top
}) {
  const meta = useStore((s) => s.meta);
  const apps = useStore((s) => s.meta?.apps ?? EMPTY_LIST) as AppMeta[];
  const current = useStore((s) => s.state?.engine.current?.app);
  const selected = useStore((s) => s.selected);
  const favorites = useStore((s) => s.favorites);
  const view = useStore((s) => s.libraryView);
  const cardSize = useStore((s) => s.cardSize);
  const category = useStore((s) => s.category);
  const prefs = useStore((s) => s.prefs);
  const [q, setQ] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const chipRow = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const [headH, setHeadH] = useState(0); // flat: section titles stick just under the sticky search row
  useEffect(() => {
    if (!flat || !head.current) return;
    const ro = new ResizeObserver(() => setHeadH(head.current?.offsetHeight ?? 0));
    ro.observe(head.current);
    return () => ro.disconnect();
  }, [flat]);
  // keep the selected category chip visible in its scrolling row
  useEffect(() => {
    const row = chipRow.current;
    const chip = row?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (row && chip) row.scrollTo({ left: chip.offsetLeft - row.clientWidth / 2 + chip.clientWidth / 2 });
  }, [category, meta]);

  const cats = useMemo(() => CATEGORY_ORDER.filter((c) => apps.some((a) => a.category === c)), [apps]);
  const f = q.trim().toLowerCase();

  // sections: favourites first (in "All"), then each category, alphabetical inside
  const sections = useMemo(() => {
    const match = (a: AppMeta) => !f || `${a.name} ${a.description} ${a.id} ${CATEGORY_LABEL[a.category] ?? a.category}`.toLowerCase().includes(f);
    const byName = (a: AppMeta, b: AppMeta) => a.name.localeCompare(b.name);
    const out: { id: string; label: string; apps: AppMeta[] }[] = [];
    const favs = apps.filter((a) => favorites.includes(a.id) && match(a)).sort(byName);
    if (category === "fav") return [{ id: "fav", label: "Favourites", apps: favs }];
    if (category === "all" && favs.length && !f) out.push({ id: "fav", label: "Favourites", apps: favs });
    for (const c of cats) {
      if (category !== "all" && category !== c) continue;
      const l = apps.filter((a) => a.category === c && match(a)).sort(byName);
      if (l.length) out.push({ id: c, label: CATEGORY_LABEL[c] ?? c, apps: l });
    }
    return out;
  }, [apps, cats, f, category, favorites]);
  const total = sections.reduce((n, s) => n + s.apps.length, 0);

  const toggleFav = (id: string) =>
    prefs({ favorites: favorites.includes(id) ? favorites.filter((x) => x !== id) : [...favorites, id] });
  const chips: [string, string][] = [["all", "All"], ["fav", "★ Favourites"], ...cats.map((c) => [c, CATEGORY_LABEL[c] ?? c] as [string, string])];
  const pickChip = (id: string) => {
    if (id === "casino") void openCasino(); // the Casino category is a door: it enters casino mode
    prefs({ category: id });
    if (flat) document.querySelector(".phone-scroll")?.scrollTo({ top: 0 });
    else scroller.current?.scrollTo({ top: 0 });
  };

  return (
    <aside className={clsx("flex flex-col", flat ? "" : "surface min-h-0 overflow-hidden", !flat && (fill ? "flex-1" : "h-full"))} aria-label="App library">
      <div ref={head} className={clsx("space-y-2.5", flat ? "lib-head" : "border-b border-line p-3")}>
        <div className={clsx("flex items-center gap-2", flat && "hidden")}>
          <h2 className="font-display text-[15px] font-[640] tracking-[-0.01em]">Apps</h2>
          <span className="font-mono text-[10px] text-ink-4">{apps.length || ""}</span>
          <div className="seg ml-auto !p-[2px]" role="group" aria-label="Library view">
            <button data-active={view === "grid"} title="Big previews" aria-label="Grid view" onClick={() => prefs({ libraryView: "grid" })} className="!flex-none !px-2"><LayoutGrid size={13} /></button>
            <button data-active={view === "list"} title="Compact list" aria-label="List view" onClick={() => prefs({ libraryView: "list" })} className="!flex-none !px-2"><List size={13} /></button>
          </div>
        </div>
        <div className="flex items-center gap-2">
        <label className="relative block min-w-0 flex-1">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-4" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${apps.length || ""} apps`} aria-label="Search apps"
            onKeyDown={(e) => e.key === "Escape" && setQ("")}
            className="field !h-9 !pl-8 !pr-8 !text-[13px]" />
          {q && (
            <button className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-3 hover:text-ink-1" aria-label="Clear search" onClick={() => setQ("")}>
              <X size={13} />
            </button>
          )}
        </label>
        {flat && (
          <div className="seg !p-[2px]" role="group" aria-label="Library view">
            <button data-active={view === "grid"} aria-label="Grid view" onClick={() => prefs({ libraryView: "grid" })} className="!flex-none !px-2.5"><LayoutGrid size={15} /></button>
            <button data-active={view === "list"} aria-label="List view" onClick={() => prefs({ libraryView: "list" })} className="!flex-none !px-2.5"><List size={15} /></button>
          </div>
        )}
        </div>
        <div ref={chipRow} className="relative -mx-3 flex gap-1 overflow-x-auto px-3 pb-0.5 [scrollbar-width:none]" role="tablist" aria-label="Categories">
          {chips.map(([id, label]) => (
            <button key={id} role="tab" aria-selected={category === id} onClick={() => pickChip(id)}
              className={clsx("shrink-0 rounded-full border px-2.5 py-[5px] text-[11.5px] transition",
                category === id ? "border-[#7a2a12] bg-ember-deep text-ember" : "border-line text-ink-3 hover:border-line-2 hover:text-ink-1")}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div ref={scroller} className={flat ? "pb-2" : "min-h-0 flex-1 overflow-y-auto px-2.5 pb-3"}>
        {!meta ? (
          <div className="pt-3"><Skeleton view={view} size={cardSize} /></div>
        ) : total === 0 ? (
          <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
            <span className="grid h-11 w-11 place-items-center rounded-full border border-line bg-chassis-0 text-ink-3">
              {category === "fav" && !f ? <Star size={18} /> : <Search size={18} />}
            </span>
            {category === "fav" && !f ? (
              <>
                <p className="text-[13px] text-ink-2">No favourites yet.</p>
                <p className="max-w-[220px] text-[12px] text-ink-3">Tap the ☆ on any app to keep it here, at the top of your library.</p>
                <button className="key" onClick={() => pickChip("all")}>Browse all apps</button>
              </>
            ) : (
              <>
                <p className="text-[13px] text-ink-2">Nothing matches “{q}”{category !== "all" ? ` in ${chips.find((c) => c[0] === category)?.[1]}` : ""}.</p>
                <button className="key" onClick={() => { setQ(""); pickChip("all"); }}>Clear search</button>
              </>
            )}
          </div>
        ) : (
          sections.map((s) => (
            <section key={s.id} aria-label={s.label}>
              <h3 className={clsx("sticky z-[2] flex items-center gap-2 pb-2 pt-3 backdrop-blur-sm", flat ? "lib-sec -mx-3 bg-chassis-0/90 px-4" : "top-0 -mx-2.5 bg-chassis-1/92 px-3.5")}
                style={flat ? { top: headH } : undefined}>
                {s.id === "fav" && <Star size={11} className="text-gold" fill="currentColor" />}
                <span className="engrave !text-ink-2">{s.label}</span>
                <span className="font-mono text-[9px] text-ink-4">{s.apps.length}</span>
              </h3>
              {view === "grid" ? (
                <div className={clsx("grid", flat ? "lib-grid-phone" : "gap-2.5")} style={flat ? undefined : { gridTemplateColumns: `repeat(auto-fill, minmax(${cardSize}px, 1fr))` }}>
                  {s.apps.map((a) => (
                    <GridCard key={a.id} a={a} live={a.id === current} selected={selected === a.id} fav={favorites.includes(a.id)}
                      onPick={() => inspect(a.id)} onFav={() => toggleFav(a.id)} />
                  ))}
                </div>
              ) : (
                <div className="space-y-0.5">
                  {s.apps.map((a) => (
                    <ListRow key={a.id} a={a} live={a.id === current} selected={selected === a.id} fav={favorites.includes(a.id)}
                      onPick={() => inspect(a.id)} onFav={() => toggleFav(a.id)} />
                  ))}
                </div>
              )}
            </section>
          ))
        )}
      </div>

      {view === "grid" && meta && (
        <label className="hidden items-center gap-2.5 border-t border-line px-3 py-2 md:flex" title="Preview size">
          <LayoutGrid size={11} className="text-ink-4" />
          <input type="range" min={72} max={220} value={cardSize} aria-label="Preview size" className="fader !h-4"
            style={{ ["--fill" as string]: `${((cardSize - 72) / 148) * 100}%` }}
            onChange={(e) => prefs({ cardSize: +e.target.value })} />
        </label>
      )}
    </aside>
  );
}
