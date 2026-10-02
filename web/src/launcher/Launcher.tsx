// DeskDot Launcher: a keyboard-first command bar over the engine's HTTP API (docs/LAUNCHERS.md).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Bell, Bug, ChevronLeft, ChevronRight, Clock, CornerDownLeft, Gamepad2, LayoutGrid, List, ListMusic, Monitor,
  Music, Palette, PawPrint, Power, Search, Send, Settings2, SkipBack, SkipForward, Sparkles, Sun, Wifi, Workflow,
  Zap, type LucideIcon,
} from "lucide-react";
import type { EngineState, Meta, Preset } from "../lib/types";
import { api, hideShell, inShell, openStudio, shellApi } from "./client";
import {
  CATEGORY_LABEL, CATEGORY_ORDER, buildItems, groupLabel, highlight, queryItems, rank, type Ctx, type Item,
} from "./search";

const RECENT_KEY = "deskdot.launcher.recent";
const VIEW_KEY = "deskdot.launcher.view";
const loadRecent = (): string[] => {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
};
const saveRecent = (ids: string[]) => {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(ids.slice(0, 12)));
  } catch {
    /* storage blocked */
  }
};
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const MOD = isMac ? "⌘" : "Ctrl";

const CATEGORY_ICON: Record<string, LucideIcon> = {
  time: Clock, data: Zap, media: Music, creative: Palette, ambient: Sparkles, productivity: Workflow,
  pets: PawPrint, games: Gamepad2, device: Monitor,
};
const ITEM_ICON: Record<string, LucideIcon> = {
  now: Monitor, brightness: Sun, next: SkipForward, prev: SkipBack, power: Power, playlist: ListMusic, fly: Bug,
  "fly-handback": Bug, dismiss: Bell, studio: LayoutGrid, reconnect: Wifi, "brightness-set": Sun,
};
function iconFor(it: Item): LucideIcon {
  if (ITEM_ICON[it.id]) return ITEM_ICON[it.id];
  if (it.kind === "fly") return Bug;
  if (it.kind === "preset") return ListMusic;
  if (it.kind === "setting") return Settings2;
  if (it.kind === "say") return Send;
  return CATEGORY_ICON[it.category ?? ""] ?? Sparkles;
}
/** Items that leave the launcher open after Enter (you usually press them more than once). */
const STAYS_OPEN = new Set(["next", "prev", "power", "playlist", "brightness", "reconnect"]);

export function Launcher() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [state, setState] = useState<EngineState | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [offline, setOffline] = useState(false);
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const [view, setView] = useState<"list" | "grid">(() => (localStorage.getItem(VIEW_KEY) === "grid" ? "grid" : "list"));
  const [recent, setRecent] = useState<string[]>(loadRecent);
  const [toast, setToast] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [visible, setVisible] = useState(true);
  const [shellInfo, setShellInfo] = useState<{ hotkey: string; autostart: boolean } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const shownAt = useRef(performance.now());
  const metaAt = useRef(0);

  // ---------------------------------------------------------------- data
  const refresh = useCallback(async (full = false) => {
    try {
      const jobs: Promise<unknown>[] = [api.state().then(setState)];
      if (full || !metaAt.current || performance.now() - metaAt.current > 60_000) {
        jobs.push(api.meta().then((m) => ((metaAt.current = performance.now()), setMeta(m))));
        jobs.push(api.presets().then(setPresets));
      }
      await Promise.all(jobs);
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    void refresh(true);
  }, [refresh]);
  useEffect(() => {
    if (!visible) return;
    const t = setInterval(() => void refresh(), 3000);
    return () => clearInterval(t);
  }, [visible, refresh]);

  // ---------------------------------------------------------------- shell (deskdot launcher) events
  useEffect(() => {
    const onShow = () => {
      shownAt.current = performance.now();
      setVisible(true);
      setSel(0);
      setRecent(loadRecent());
      void refresh(true);
      requestAnimationFrame(() => {
        input.current?.focus();
        input.current?.select();
      });
    };
    const onHide = () => setVisible(false);
    const onBlur = () => {
      if (!inShell() || performance.now() - shownAt.current < 400) return;
      setTimeout(() => !document.hasFocus() && hideShell(), 120);
    };
    const onReady = () => void shellApi()?.info().then(setShellInfo).catch(() => undefined);
    window.addEventListener("deskdot:show", onShow);
    window.addEventListener("deskdot:hide", onHide);
    window.addEventListener("blur", onBlur);
    window.addEventListener("pywebviewready", onReady);
    if (shellApi()) onReady();
    if (!inShell()) window.addEventListener("focus", onShow);
    input.current?.focus();
    return () => {
      window.removeEventListener("deskdot:show", onShow);
      window.removeEventListener("deskdot:hide", onHide);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("pywebviewready", onReady);
      window.removeEventListener("focus", onShow);
    };
  }, [refresh]);

  // ---------------------------------------------------------------- items
  const ctx: Ctx = useMemo(() => ({ meta, state, presets, api, inShell: inShell() }), [meta, state, presets]);
  const all = useMemo(() => {
    const items = buildItems(ctx);
    if (shellInfo) {
      items.push({
        id: "autostart",
        kind: "action",
        title: `Start the launcher with login: ${shellInfo.autostart ? "on" : "off"}`,
        subtitle: shellInfo.autostart ? "Turn it off" : "Open it in the background when you sign in",
        keywords: "autostart login startup boot launcher",
        searchOnly: true,
        verb: shellInfo.autostart ? "Turn off" : "Turn on",
        run: async () => {
          const on = (await shellApi()?.set_autostart(!shellInfo.autostart)) ?? false;
          setShellInfo({ ...shellInfo, autostart: on });
          return on ? "Starts with login" : "Won't start with login";
        },
      });
      items.push({
        id: "quit-launcher",
        kind: "action",
        title: "Quit the launcher",
        subtitle: `${shellInfo.hotkey} won't open it until you start it again`,
        keywords: "quit exit close launcher",
        searchOnly: true,
        verb: "Quit",
        run: async () => (await shellApi()?.quit(), ""),
      });
    }
    return items;
  }, [ctx, shellInfo]);
  const extra = useMemo(() => queryItems(query, ctx), [query, ctx]);
  const results = useMemo(() => {
    const r = rank(all, extra, query, recent);
    if (view === "list") return r;
    const apps = r.filter((i) => i.kind === "app" || i.kind === "game");
    const order = (c?: string) => {
      const i = CATEGORY_ORDER.indexOf(c ?? "");
      return i < 0 ? 99 : i;
    };
    return query.trim() ? apps : [...apps].sort((a, b) => order(a.category) - order(b.category));
  }, [all, extra, query, recent, view]);
  const cur = results[Math.min(sel, results.length - 1)] as Item | undefined;

  useEffect(() => setSel(0), [view]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel, view]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  // ---------------------------------------------------------------- actions
  const remember = (id: string) => {
    const next = [id, ...recent.filter((r) => r !== id)].slice(0, 12);
    setRecent(next);
    saveRecent(next);
  };

  const studio = (it: Item | undefined) => {
    if (!it) return;
    remember(it.id);
    openStudio(it.studio ?? "/");
  };

  const run = async (it: Item | undefined) => {
    if (!it || busy) return;
    if (it.kind === "setting" || it.id === "now" || it.id === "studio") return studio(it);
    if (it.id === "brightness") return;
    setBusy(it.id);
    try {
      const msg = await it.run();
      remember(it.id);
      if (msg) setToast({ text: msg });
      void refresh();
      if (inShell() && !STAYS_OPEN.has(it.id)) setTimeout(hideShell, 380);
    } catch (e) {
      setToast({ text: (e as Error).message || "That didn't work", bad: true });
    } finally {
      setBusy(null);
    }
  };

  const brightness = state?.settings.brightness ?? 60;
  const briTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const setBrightness = (v: number) => {
    const b = Math.max(5, Math.min(100, Math.round(v)));
    setState((s) => (s ? { ...s, settings: { ...s.settings, brightness: b } } : s));
    clearTimeout(briTimer.current);
    briTimer.current = setTimeout(() => void api.settings({ brightness: b }).catch(() => undefined), 120);
  };

  // grid navigation by on-screen position (sections make the column count uneven)
  const moveGrid = (dir: "up" | "down") => {
    const root = listRef.current;
    const here = root?.querySelector<HTMLElement>(`[data-i="${sel}"]`);
    if (!root || !here) return;
    const r0 = here.getBoundingClientRect();
    const tiles = [...root.querySelectorAll<HTMLElement>("[data-i]")].map((el) => ({
      i: Number(el.dataset.i),
      r: el.getBoundingClientRect(),
    }));
    const rows = tiles.filter((t) => (dir === "down" ? t.r.top > r0.top + 4 : t.r.top < r0.top - 4));
    if (!rows.length) return;
    const rowTop = dir === "down" ? Math.min(...rows.map((t) => t.r.top)) : Math.max(...rows.map((t) => t.r.top));
    const row = rows.filter((t) => Math.abs(t.r.top - rowTop) < 4);
    const cx = r0.left + r0.width / 2;
    row.sort((a, b) => Math.abs(a.r.left + a.r.width / 2 - cx) - Math.abs(b.r.left + b.r.width / 2 - cx));
    setSel(row[0].i);
  };

  const onKey = (e: React.KeyboardEvent) => {
    const n = results.length;
    const k = e.key;
    if (k === "Escape") {
      e.preventDefault();
      if (query) setQuery("");
      else if (inShell()) hideShell();
      return;
    }
    if (k === "Tab") {
      e.preventDefault();
      const v = view === "list" ? "grid" : "list";
      setView(v);
      try {
        localStorage.setItem(VIEW_KEY, v);
      } catch {
        /* ignore */
      }
      return;
    }
    if (k === "Enter") {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) studio(cur);
      else void run(cur);
      return;
    }
    if (!n) return;
    if (k === "ArrowDown" || k === "ArrowUp") {
      e.preventDefault();
      if (view === "grid") moveGrid(k === "ArrowDown" ? "down" : "up");
      else setSel((s) => (k === "ArrowDown" ? (s + 1) % n : (s - 1 + n) % n));
    } else if ((k === "ArrowLeft" || k === "ArrowRight") && view === "grid") {
      e.preventDefault();
      setSel((s) => Math.max(0, Math.min(n - 1, s + (k === "ArrowRight" ? 1 : -1))));
    } else if ((k === "ArrowLeft" || k === "ArrowRight") && cur?.id === "brightness") {
      e.preventDefault();
      setBrightness(brightness + (k === "ArrowRight" ? 5 : -5) * (e.shiftKey ? 2 : 1));
    } else if (k === "PageDown" || k === "PageUp") {
      e.preventDefault();
      setSel((s) => Math.max(0, Math.min(n - 1, s + (k === "PageDown" ? 8 : -8))));
    }
  };

  // ---------------------------------------------------------------- render
  const device = state?.device;
  const linkOk = device?.status === "connected";
  return (
    <div className="lx-card" onKeyDown={onKey}>
      <header className="lx-search">
        <DotMark />
        <Search size={17} className="lx-search-icon" aria-hidden />
        <input
          ref={input}
          autoFocus
          spellCheck={false}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSel(0);
          }}
          placeholder={view === "grid" ? "Filter the display menu…" : "Search apps, games, presets, controls…  (> to send text)"}
          aria-label="Search DeskDot"
          aria-controls="lx-results"
          aria-activedescendant={cur ? `lx-${sel}` : undefined}
        />
        <div className="lx-seg" role="tablist" aria-label="View">
          <button role="tab" aria-selected={view === "list"} className={view === "list" ? "on" : ""} onClick={() => setView("list")} title="Results (Tab)">
            <List size={15} />
          </button>
          <button role="tab" aria-selected={view === "grid"} className={view === "grid" ? "on" : ""} onClick={() => setView("grid")} title="Display menu (Tab)">
            <LayoutGrid size={15} />
          </button>
        </div>
      </header>

      <main className="lx-body">
        <div className={view === "grid" ? "lx-grid" : "lx-list"} id="lx-results" role="listbox" ref={listRef}>
          {offline && (
            <div className="lx-empty">
              <b>Can't reach the DeskDot engine.</b>
              <span>Start it with <code>deskdot serve</code>, or from the launcher's tray icon.</span>
            </div>
          )}
          {!offline && !results.length && meta && <div className="lx-empty">Nothing matches “{query}”.</div>}
          {view === "list" ? (
            <ListView results={results} sel={sel} query={query} recent={recent} busy={busy} onPick={(i) => setSel(i)} onRun={(it) => void run(it)} />
          ) : (
            <GridView results={results} sel={sel} query={query} onPick={(i) => setSel(i)} onRun={(it) => void run(it)} />
          )}
        </div>
        <Preview item={cur} meta={meta} state={state} presets={presets} visible={visible} brightness={brightness} setBrightness={setBrightness} />
      </main>

      <footer className="lx-foot">
        <span className={`lx-dot ${offline ? "bad" : linkOk ? "ok" : "warn"}`} />
        <span className="lx-status">
          {offline ? "Engine offline" : device ? `${device.name ?? (device.kind === "sim" ? "Simulator" : "Panel")} · ${device.status}` : "Connecting…"}
        </span>
        {toast && <span className={`lx-toast ${toast.bad ? "bad" : ""}`}>{toast.text}</span>}
        <span className="lx-hints">
          {cur && (
            <>
              <Hint k={<CornerDownLeft size={11} />}>{cur.id === "brightness" ? "← → adjust" : cur.verb}</Hint>
              {cur.studio && <Hint k={`${MOD} ↵`}>Studio</Hint>}
            </>
          )}
          <Hint k="Tab">{view === "list" ? "Display menu" : "List"}</Hint>
          {inShell() && <Hint k="Esc">Hide</Hint>}
        </span>
      </footer>
    </div>
  );
}

// ------------------------------------------------------------------ list
function ListView(props: {
  results: Item[]; sel: number; query: string; recent: string[]; busy: string | null;
  onPick: (i: number) => void; onRun: (it: Item) => void;
}) {
  const { results, sel, query, recent, busy } = props;
  const recentSet = new Set(recent);
  let last = "";
  const rows: ReactNode[] = [];
  results.forEach((it, i) => {
    const g = !query.trim() && recentSet.has(it.id) && i < recent.length ? "Recent" : query.trim() ? "" : groupLabel(it);
    if (g && g !== last) rows.push(<div key={`g-${g}-${i}`} className="lx-group">{g}</div>);
    last = g || last;
    const Ico = iconFor(it);
    rows.push(
      <div
        key={it.id}
        id={`lx-${i}`}
        data-i={i}
        role="option"
        aria-selected={i === sel}
        className={`lx-row ${i === sel ? "sel" : ""} k-${it.kind}`}
        onMouseMove={() => i !== sel && props.onPick(i)}
        onClick={() => props.onRun(it)}
      >
        <span className="lx-ico"><Ico size={16} strokeWidth={1.7} /></span>
        <span className="lx-text">
          <span className="lx-title"><Marked text={it.title} query={query} /></span>
          <span className="lx-sub">{it.subtitle}</span>
        </span>
        {busy === it.id ? <span className="lx-spin" /> : <span className="lx-kind">{kindLabel(it)}</span>}
      </div>,
    );
  });
  return <>{rows}</>;
}

function kindLabel(it: Item): string {
  switch (it.kind) {
    case "game": return "Game";
    case "app": return CATEGORY_LABEL[it.category ?? ""] ?? "App";
    case "preset": return "Preset";
    case "setting": return "Settings";
    case "fly": return "Fly";
    case "say": return "Send";
    case "now": return "Live";
    default: return "Control";
  }
}

function Marked({ text, query }: { text: string; query: string }) {
  const hit = highlight(query, text);
  if (!hit.size) return <>{text}</>;
  return <>{[...text].map((c, i) => (hit.has(i) ? <mark key={i}>{c}</mark> : c))}</>;
}

// ------------------------------------------------------------------ display menu (grid)
function GridView(props: { results: Item[]; sel: number; query: string; onPick: (i: number) => void; onRun: (it: Item) => void }) {
  const { results, sel } = props;
  const out: ReactNode[] = [];
  let cat = "";
  let tiles: ReactNode[] = [];
  const flush = () => {
    if (tiles.length) out.push(<section key={`s-${cat}`}><h3>{CATEGORY_LABEL[cat] ?? cat}</h3><div className="lx-tiles">{tiles}</div></section>);
    tiles = [];
  };
  results.forEach((it, i) => {
    if ((it.category ?? "") !== cat) {
      flush();
      cat = it.category ?? "";
    }
    tiles.push(
      <button
        key={it.id}
        id={`lx-${i}`}
        data-i={i}
        role="option"
        aria-selected={i === sel}
        className={`lx-tile ${i === sel ? "sel" : ""}`}
        onMouseMove={() => i !== sel && props.onPick(i)}
        onClick={() => props.onRun(it)}
        tabIndex={-1}
      >
        <span className="lx-led sm"><img loading="lazy" alt="" src={`/api/apps/${it.app}/preview.gif`} /></span>
        <span className="lx-tile-name">{it.title}</span>
      </button>,
    );
  });
  flush();
  return <>{out}</>;
}

// ------------------------------------------------------------------ preview pane
function Preview(props: {
  item: Item | undefined; meta: Meta | null; state: EngineState | null; presets: Preset[]; visible: boolean;
  brightness: number; setBrightness: (v: number) => void;
}) {
  const { item, meta, state, visible } = props;
  const [tick, setTick] = useState(0);
  const live = item?.id === "now";
  useEffect(() => {
    if (!live || !visible) return;
    const t = setInterval(() => setTick((x) => x + 1), 450);
    return () => clearInterval(t);
  }, [live, visible]);
  if (!item) return <aside className="lx-preview" />;
  const appMeta = meta?.apps.find((a) => a.id === item.app);
  const Ico = iconFor(item);

  let hero: ReactNode;
  if (live) {
    hero = <span className="lx-led"><img alt="What the panel shows now" src={`/api/frame.png?scale=8&t=${tick}`} /></span>;
  } else if (item.id === "brightness" || item.id === "brightness-set") {
    const v = item.id === "brightness" ? props.brightness : Number(/(\d+)%/.exec(item.title)?.[1] ?? props.brightness);
    hero = (
      <div className="lx-bri">
        <Sun size={30} strokeWidth={1.4} style={{ opacity: 0.4 + v / 170 }} />
        <b>{v}%</b>
        {item.id === "brightness" && (
          <div className="lx-bri-row">
            <button tabIndex={-1} onClick={() => props.setBrightness(v - 10)} aria-label="Dimmer"><ChevronLeft size={14} /></button>
            <input type="range" min={5} max={100} step={1} value={v} tabIndex={-1} aria-label="Brightness"
              onChange={(e) => props.setBrightness(Number(e.target.value))} />
            <button tabIndex={-1} onClick={() => props.setBrightness(v + 10)} aria-label="Brighter"><ChevronRight size={14} /></button>
          </div>
        )}
      </div>
    );
  } else if (item.app && (item.kind === "app" || item.kind === "game" || item.kind === "fly")) {
    hero = <span className="lx-led"><img key={item.app} alt={`${item.title} preview`} src={`/api/apps/${item.app}/preview.gif`} /></span>;
  } else if (item.kind === "preset") {
    const p = props.presets.find((x) => `preset:${x.id}` === item.id);
    hero = (
      <div className="lx-preset">
        {p?.items.slice(0, 4).map((it, i) => (
          <span key={i} className="lx-led xs"><img loading="lazy" alt="" src={`/api/apps/${it.app}/preview.gif`} /></span>
        ))}
      </div>
    );
  } else {
    hero = <span className="lx-big-ico"><Ico size={40} strokeWidth={1.3} /></span>;
  }

  const presetApps =
    item.kind === "preset"
      ? props.presets.find((x) => `preset:${x.id}` === item.id)?.items.map((i) => meta?.apps.find((a) => a.id === i.app)?.name ?? i.app)
      : null;
  const facts: [string, string][] = [];
  if (appMeta && item.kind !== "fly") {
    facts.push(["Category", CATEGORY_LABEL[appMeta.category] ?? appMeta.category]);
    const n = Object.keys(appMeta.schema?.properties ?? {}).length;
    if (n) facts.push(["Settings", String(n)]);
    if ((appMeta.max_players ?? 1) > 1) facts.push(["Players", `up to ${appMeta.max_players}`]);
  }
  if (live && state) {
    facts.push(["Mode", state.engine.mode === "playlist" ? "Playlist" : "Manual"]);
    facts.push(["Brightness", `${state.settings.brightness}%`]);
    if (state.engine.current?.kind) facts.push(["Playback", state.engine.current.kind]);
  }

  return (
    <aside className="lx-preview" aria-live="polite">
      <div className="lx-hero">{hero}</div>
      <h2>{item.title}</h2>
      <p>{item.kind === "app" || item.kind === "game" ? appMeta?.description ?? item.subtitle : item.subtitle}</p>
      {presetApps && <p className="lx-chips">{presetApps.slice(0, 14).map((n, i) => <span key={i}>{n}</span>)}{presetApps.length > 14 && <span>+{presetApps.length - 14}</span>}</p>}
      {facts.length > 0 && (
        <dl>
          {facts.map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
          ))}
        </dl>
      )}
    </aside>
  );
}

function Hint({ k, children }: { k: ReactNode; children: ReactNode }) {
  return (
    <span className="lx-hint">
      <kbd>{k}</kbd>
      {children}
    </span>
  );
}

/** The DeskDot mark: a 4×4 dot matrix in the warm brand gradient. */
function DotMark() {
  const on = [0, 3, 5, 6, 9, 10, 12, 15];
  return (
    <span className="lx-mark" aria-hidden>
      {Array.from({ length: 16 }, (_, i) => (
        <i key={i} className={on.includes(i) ? "on" : ""} style={{ ["--d" as string]: `${((i % 4) + Math.floor(i / 4)) / 6}` }} />
      ))}
    </span>
  );
}
