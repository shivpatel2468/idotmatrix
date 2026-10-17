import { ChevronRight } from "lucide-react";
import { memo, useMemo, useRef } from "react";
import { api } from "../lib/api";
import { EMPTY_LIST, inspect, useStore } from "../lib/store";
import { useRecent } from "../lib/recent";
import type { AppMeta } from "../lib/types";
import { CATEGORY_ICON, CATEGORY_LABEL, CATEGORY_ORDER, IconTile } from "./Icon";
import { Preview } from "./Library";

type Row = { id: string; label: string; icon: string; tone: string; apps: AppMeta[]; chip: string };

/** Tap = show it on the panel; hold = its settings. A swipe never triggers either (the browser cancels the press). */
const RailCard = memo(function RailCard({ a, live }: { a: AppMeta; live: boolean }) {
  const t = useRef(0);
  const held = useRef(false);
  const down = () => {
    held.current = false;
    clearTimeout(t.current);
    t.current = window.setTimeout(() => {
      held.current = true;
      inspect(a.id);
    }, 480);
  };
  const cancel = () => clearTimeout(t.current);
  return (
    <button className="rail-card" data-live={live} aria-label={`${a.name}${live ? " (on the panel)" : " — show it on the panel"}`}
      title={`${a.description}\n\nTap to show · hold for settings`}
      onPointerDown={down} onPointerUp={cancel} onPointerLeave={cancel} onPointerCancel={cancel}
      onContextMenu={(e) => e.preventDefault()}
      onClick={() => {
        cancel();
        if (held.current) return void (held.current = false);
        if (live) return inspect(a.id); // already showing: tapping again opens its settings
        api.activate(a.id).catch(() => undefined); // req() already toasts the error
      }}>
      <Preview id={a.id} />
      {live && <span className="rail-live"><span className="led !h-[5px] !w-[5px]" data-on="ember" />Live</span>}
      <span className="rail-name">{a.name}</span>
    </button>
  );
});

/**
 * Phones, Panel tab: apps right under the panel — rows you swipe left / right (native scroll-snap with momentum,
 * peeking cards at the edge). Favourites, Recent, then one row per category. Rows off screen skip rendering
 * (`content-visibility`), and previews load lazily.
 */
export function AppRail() {
  const apps = useStore((s) => s.meta?.apps ?? EMPTY_LIST) as AppMeta[];
  const favorites = useStore((s) => s.favorites);
  const current = useStore((s) => s.state?.engine.current?.app);
  const prefs = useStore((s) => s.prefs);
  const set = useStore((s) => s.set);
  const recent = useRecent();

  const rows = useMemo(() => {
    const byId = new Map(apps.map((a) => [a.id, a]));
    const pick = (ids: readonly string[]) => ids.map((id) => byId.get(id)).filter((a): a is AppMeta => !!a);
    const byName = (a: AppMeta, b: AppMeta) => a.name.localeCompare(b.name);
    const out: Row[] = [];
    const favs = pick(favorites);
    if (favs.length) out.push({ id: "fav", label: "Favourites", icon: "star", tone: "gold", apps: favs, chip: "fav" });
    const rec = pick(recent).slice(0, 12);
    if (rec.length > 1) out.push({ id: "recent", label: "Recent", icon: "rotate-ccw-clock", tone: "info", apps: rec, chip: "all" });
    for (const c of CATEGORY_ORDER) {
      const list = apps.filter((a) => a.category === c).sort(byName);
      if (list.length) out.push({ id: c, label: CATEGORY_LABEL[c] ?? c, icon: CATEGORY_ICON[c] ?? "square", tone: c, apps: list, chip: c });
    }
    return out;
  }, [apps, favorites, recent]);

  if (!apps.length) {
    return (
      <div className="w-full space-y-2" aria-hidden>
        <div className="skeleton h-5 w-32 rounded-md" />
        <div className="flex gap-2.5 overflow-hidden">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton aspect-square w-[29%] shrink-0 rounded-[12px]" />)}</div>
      </div>
    );
  }
  return (
    <section className="rails w-full" aria-label="Apps — swipe a row, tap to show">
      {rows.map((r) => (
        <div key={r.id} className="rail" role="group" aria-label={r.label}>
          <div className="rail-head">
            <IconTile name={r.icon} tone={r.tone} size={26} />
            <h3 className="min-w-0 flex-1 truncate font-display text-[15px] font-[640] tracking-[-0.01em]">{r.label}</h3>
            <button className="rail-all" onClick={() => { prefs({ category: r.chip }); set({ mobileTab: "apps" }); }}
              aria-label={`See all ${r.label}`}>
              {r.apps.length} <ChevronRight size={14} />
            </button>
          </div>
          <div className="rail-track">
            {r.apps.map((a) => <RailCard key={a.id} a={a} live={a.id === current} />)}
          </div>
        </div>
      ))}
    </section>
  );
}
